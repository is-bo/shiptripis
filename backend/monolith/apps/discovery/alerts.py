"""Route alerts: "tell me when someone publishes on this route" (spec 4.4).

The fan-out is a durable obligation, not an after-commit callback. Publishing
a journey, or a request opening, records one `ScheduledJob` in the same
transaction (`schedule_route_alerts`); the worker runs
`handle_route_alert_fanout`, which re-reads everything and does nothing if the
item is no longer listed. A crash between the publish and the fan-out loses
nothing, and a replay notifies nobody twice: each notification's event id is
derived from the alert and the item, and the inbox is unique per event.

At most one notification per alert per `ALERT_QUIET_PERIOD`. The check is a
single guarded UPDATE, so two items published at the same instant cannot both
pass it.
"""

from __future__ import annotations

from datetime import timedelta
from itertools import combinations

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core import channels, redis_bus
from apps.core.marketplace_policy import marketplace_policy
from apps.trips.models import Journey

from .errors import DiscoveryError
from .listings import listable_journeys, listable_requests
from .models import MAX_ACTIVE_ALERTS, RouteAlert
from .places import PlaceNotFound, resolve_locality
from .profiles import visible_profiles

ALERT_QUIET_PERIOD = timedelta(hours=6)


def schedule_route_alerts(*, journey_id: int | None = None, request_id: int | None = None) -> None:
    """Record the fan-out for one newly listed item. Call inside its transaction."""

    from apps.finance.models import ScheduledJob
    from apps.finance.services import schedule_job

    if (journey_id is None) == (request_id is None):
        raise ValueError("Exactly one of journey_id and request_id is required.")
    if journey_id is not None:
        key, payload = f"discovery_route_alerts:journey:{journey_id}", {"journey_id": journey_id}
    else:
        key, payload = f"discovery_route_alerts:request:{request_id}", {"request_id": request_id}
    schedule_job(
        kind=ScheduledJob.Kind.DISCOVERY_ROUTE_ALERTS,
        key=key, run_at=timezone.now(), payload=payload)


def handle_route_alert_fanout(payload: dict) -> str:
    """`ScheduledJob` handler. Idempotent; re-reads every gate it depends on."""

    from apps.finance.jobs import PermanentJobError

    journey_id = payload.get("journey_id")
    request_id = payload.get("request_id")
    if not (isinstance(journey_id, int) ^ isinstance(request_id, int)):
        raise PermanentJobError(
            "discovery_route_alerts needs one integer journey_id or request_id.",
            code="invalid_payload",
        )
    policy = marketplace_policy()
    if not policy.discovery.listings_enabled:
        return "listings_disabled"
    at = timezone.now()
    if journey_id is not None:
        journey = listable_journeys(at=at).filter(pk=journey_id).first()
        if journey is None:
            return "not_listed"
        owner_id = journey.traveler_id
        pairs = _journey_pairs(journey)
        watches = RouteAlert.Watches.TRIPS
        item = {"journey_id": journey.pk}
    else:
        delivery_request = listable_requests(at=at).filter(pk=request_id).first()
        if delivery_request is None:
            return "not_listed"
        owner_id = delivery_request.sender_id
        origin = delivery_request.pickup_place.resolve_matching_locality()
        destination = delivery_request.delivery_place.resolve_matching_locality()
        pairs = {(origin.pk, destination.pk)} if origin and destination else set()
        watches = RouteAlert.Watches.REQUESTS
        item = {"request_id": delivery_request.pk}
    if not pairs:
        return "no_route"

    owner_visible = (
        policy.discovery.profiles_enabled
        and visible_profiles().filter(user_id=owner_id).exists()
    )
    subject = Q(subject_user__isnull=True)
    if owner_visible:
        subject |= Q(subject_user_id=owner_id)
    route = Q()
    for origin_id, destination_id in pairs:
        route |= Q(origin_locality_id=origin_id, destination_locality_id=destination_id)
    alerts = list(
        RouteAlert.objects.filter(route, subject, watches=watches, is_active=True)
        .filter(user__is_active=True, user__is_banned=False)
        .exclude(user_id=owner_id)
        .order_by("pk")
    )
    sent = 0
    for alert in alerts:
        with transaction.atomic():
            claimed = (
                RouteAlert.objects.filter(pk=alert.pk, is_active=True)
                .filter(
                    Q(last_notified_at__isnull=True)
                    | Q(last_notified_at__lte=at - ALERT_QUIET_PERIOD)
                )
                .update(last_notified_at=at)
            )
            if not claimed:
                continue
            kind, item_id = next(iter(item.items()))
            redis_bus.publish_after_commit(
                channels.DISCOVERY_ROUTE_ALERT,
                {"alert_id": alert.pk, **item},
                targets=[alert.user_id],
                idempotency_key=f"route_alert:{alert.pk}:{kind}:{item_id}",
            )
            sent += 1
    return f"notified:{sent}"


def _journey_pairs(journey: Journey) -> set[tuple[int, int]]:
    """Every (pickup city, later drop-off city) the journey can still carry between.

    Only stops still ahead can take a parcel, so the pickup side starts at the
    first leg that has not departed, the same rule the listing filter uses.
    Departures strictly increase along a journey, so the legs ahead are a suffix.
    """

    at = timezone.now()
    ahead = [leg for leg in journey._matching_legs if leg.depart_at > at]
    if not ahead:
        return set()
    nodes = [
        _locality_id(ahead[0].origin_place),
        *(_locality_id(leg.destination_place) for leg in ahead),
    ]
    resolved = [node for node in nodes if node is not None]
    return {
        (origin, destination)
        for origin, destination in combinations(resolved, 2)
        if origin != destination
    }


def _locality_id(place) -> int | None:
    locality = place.resolve_matching_locality() if place is not None else None
    return locality.pk if locality is not None else None


# ---------------------------------------------------------------------------
# A member's own alerts
# ---------------------------------------------------------------------------


def create_alert(
    *,
    user,
    watches: str,
    origin_place_id: int,
    destination_place_id: int,
    subject_profile_id=None,
) -> tuple[RouteAlert, bool]:
    """Create one alert, or return the identical active one. Capped per member."""

    from django.contrib.auth import get_user_model

    policy = marketplace_policy()
    if not policy.discovery.listings_enabled:
        raise DiscoveryError(
            "discovery_listings_disabled",
            "Route alerts are not available right now.",
            status=409,
        )
    try:
        origin = resolve_locality(origin_place_id)
        destination = resolve_locality(destination_place_id)
    except PlaceNotFound as exc:
        raise DiscoveryError(exc.code, str(exc)) from exc
    if origin.pk == destination.pk:
        raise DiscoveryError("route_alert_same_city", "An alert needs two different cities.")
    subject_user_id = None
    if subject_profile_id is not None:
        if not policy.discovery.profiles_enabled:
            raise DiscoveryError(
                "discovery_profiles_disabled",
                "Public profiles are not available right now.",
                status=409,
            )
        subject = visible_profiles().filter(public_id=subject_profile_id).first()
        if subject is None:
            raise DiscoveryError("profile_not_found", "This profile is not available.", status=404)
        if subject.user_id == user.pk:
            raise DiscoveryError("route_alert_self", "You cannot follow your own profile.")
        subject_user_id = subject.user_id

    with transaction.atomic():
        # Serialise one member's alert writes so the cap holds under concurrency.
        get_user_model().objects.select_for_update(no_key=True).filter(pk=user.pk).first()
        existing = RouteAlert.objects.filter(
            user=user,
            watches=watches,
            origin_locality=origin,
            destination_locality=destination,
            subject_user_id=subject_user_id,
            is_active=True,
        ).first()
        if existing is not None:
            return existing, False
        if RouteAlert.objects.filter(user=user, is_active=True).count() >= MAX_ACTIVE_ALERTS:
            raise DiscoveryError(
                "route_alert_limit_reached",
                f"You can keep at most {MAX_ACTIVE_ALERTS} route alerts.",
                status=409,
            )
        alert = RouteAlert.objects.create(
            user=user,
            watches=watches,
            origin_locality=origin,
            destination_locality=destination,
            subject_user_id=subject_user_id,
        )
    return alert, True


def deactivate_alert(*, user, alert_id: int) -> bool:
    """Turn one of the member's own alerts off. False when there is none."""

    return bool(
        RouteAlert.objects.filter(pk=alert_id, user=user, is_active=True).update(
            is_active=False, deactivated_at=timezone.now()
        )
    )


def own_alerts(user):
    return (
        RouteAlert.objects.filter(user=user, is_active=True)
        .select_related(
            "origin_locality__parent",
            "destination_locality__parent",
            "subject_user__public_profile",
        )
        .order_by("-created_at", "-pk")
    )


def alert_payload(alert: RouteAlert) -> dict:
    """A member's own alert. The followed person appears by public card id only."""

    from apps.matching.find_travelers import first_name

    from .places import locality_block

    subject = None
    if alert.subject_user_id is not None:
        profile = getattr(alert.subject_user, "public_profile", None)
        subject = {
            "id": str(profile.public_id) if profile is not None else None,
            "display_name": first_name(alert.subject_user.full_name),
        }
    return {
        "id": alert.pk,
        "watches": alert.watches,
        "origin": locality_block(alert.origin_locality),
        "destination": locality_block(alert.destination_locality),
        "subject": subject,
        "created_at": alert.created_at.isoformat(),
    }

