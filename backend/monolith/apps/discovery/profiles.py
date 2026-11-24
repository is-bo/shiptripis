"""The People tier and a member's own public profile (spec 4.2, 4.3, 4.5).

A profile is visible when, and only while, all of these hold: the member turned
it on, staff have not hidden it, the account is active and not banned, and the
`profiles_enabled` switch is on. `visible_profiles()` is that rule, and every
read path in this app goes through it; turning a profile off removes it from
the next request, with nothing cached.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Exists, F, OuterRef, Prefetch, Q, QuerySet, Subquery
from django.db.models.functions import Greatest
from django.utils import timezone

from apps.accounts.photos import public_photo
from apps.kyc.models import KycSubmission
from apps.matching.find_travelers import first_name
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.trips.models import Journey

from .errors import DiscoveryError
from .listings import RouteFilter, journey_route_exists, request_route_q
from .models import MAX_USUAL_ROUTES, PublicProfile, PublicProfileRoute
from .places import PlaceNotFound, locality_block, resolve_locality

User = get_user_model()

#: The wording a member agrees to when they turn their profile on. Bump it when
#: the opt-in card's text or the published card's fields change.
PROFILE_CONSENT_VERSION = "l2a-2026-11"

#: "A traveler is a member with a published journey in the last 12 months or a
#: usual route; a sender likewise with requests" (plan L2A).
ACTIVITY_WINDOW = timedelta(days=365)

ROLE_TRAVELER = "traveler"
ROLE_SENDER = "sender"

STATE_VISIBLE = "visible"
STATE_NOT_VISIBLE = "not_visible"
STATE_HIDDEN = "hidden"
STATE_DISABLED = "disabled"


def _current_kyc():
    now = timezone.now()
    return KycSubmission.objects.filter(
        user_id=OuterRef("user_id"), status=KycSubmission.Status.APPROVED
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))


def _routes_prefetch() -> Prefetch:
    return Prefetch(
        "usual_routes",
        queryset=PublicProfileRoute.objects.select_related(
            "origin_locality__parent", "destination_locality__parent"
        ).order_by("position"),
    )


def visible_profiles() -> QuerySet:
    """Profiles anyone may see, with everything their card renders loaded."""

    return (
        PublicProfile.objects.select_related("user", "user__profile_photo")
        .prefetch_related(_routes_prefetch())
        .filter(
            is_discoverable=True,
            hidden_at__isnull=True,
            user__is_active=True,
            user__is_banned=False,
        )
        .annotate(identity_verified=Exists(_current_kyc()))
    )


def _recent_journeys(at: datetime) -> QuerySet:
    return Journey.objects.filter(
        traveler_id=OuterRef("user_id"),
        published_at__gte=at - ACTIVITY_WINDOW,
    )


def _recent_requests(at: datetime) -> QuerySet:
    return DeliveryRequest.objects.filter(
        sender_id=OuterRef("user_id"),
        kind=ParcelRequest.Kind.DELIVERY,
        created_at__gte=at - ACTIVITY_WINDOW,
    ).exclude(status=ParcelRequest.Status.AWAITING_DEPOSIT)


def people(
    *, side: str, route: RouteFilter, viewer_id: int | None, at: datetime
) -> QuerySet:
    """Visible profiles on one side of the marketplace, most recently active first.

    `side` is who is listed: `traveler` or `sender`. With a route, a person is
    on it when one of their usual routes is, or when their own recent trips
    (or requests) were. A member (`viewer_id`) is never listed to themselves;
    a guest (`None`) has no one to leave out.
    """

    activity = _recent_journeys(at) if side == ROLE_TRAVELER else _recent_requests(at)
    latest_field = "published_at" if side == ROLE_TRAVELER else "created_at"
    usual = PublicProfileRoute.objects.filter(profile_id=OuterRef("pk"))
    queryset = visible_profiles()
    if viewer_id is not None:
        queryset = queryset.exclude(user_id=viewer_id)
    queryset = queryset.alias(
        has_activity=Exists(activity), has_usual_route=Exists(usual)
    ).filter(Q(has_activity=True) | Q(has_usual_route=True))
    if route.has_origin or route.has_destination:
        usual_on_route = usual.filter(
            _route_end_q("origin_locality", route.origin_place_ids, route.origin_country)
            & _route_end_q(
                "destination_locality",
                route.destination_place_ids,
                route.destination_country,
            )
        )
        activity_on_route = activity.filter(
            journey_route_exists(route, departing_after=None)
            if side == ROLE_TRAVELER
            else request_route_q(route)
        )
        queryset = queryset.alias(
            usual_on_route=Exists(usual_on_route),
            activity_on_route=Exists(activity_on_route),
        ).filter(Q(usual_on_route=True) | Q(activity_on_route=True))
    latest = activity.order_by(f"-{latest_field}").values(latest_field)[:1]
    return queryset.annotate(
        last_active_at=Greatest(Subquery(latest), "consented_at")
    ).order_by(F("last_active_at").desc(nulls_last=True), "-pk")


def _route_end_q(field: str, place_ids, country) -> Q:
    condition = Q()
    if place_ids is not None:
        condition &= Q(**{f"{field}_id__in": place_ids})
    if country is not None:
        condition &= Q(**{f"{field}__country_id": country})
    return condition


def profile_card(profile: PublicProfile, *, trust: dict) -> dict:
    """Spec 4.2 profile card. The exact card others see, built key by key.

    The trust summary covers the whole person, both sides of every delivery,
    so the card a member previews of themselves is the card everyone reads.
    """

    user = profile.user
    joined = user.date_joined
    # An unsaved profile is the off-by-default answer for a member who has
    # never opened discovery: it has no public id and no routes yet.
    routes = profile.usual_routes.all() if profile.pk else ()
    return {
        "id": str(profile.public_id) if profile.pk else None,
        "display_name": first_name(user.full_name),
        "photo": public_photo(user),
        "identity_verified": bool(getattr(profile, "identity_verified", False)),
        "member_since": f"{joined.year:04d}-{joined.month:02d}" if joined else None,
        "rating": trust["rating"],
        "completed_deliveries": trust["completed_deliveries"],
        "usual_routes": [
            {
                "origin": locality_block(route.origin_locality),
                "destination": locality_block(route.destination_locality),
            }
            for route in routes
        ],
    }


# ---------------------------------------------------------------------------
# A member's own profile
# ---------------------------------------------------------------------------


def own_profile(user) -> PublicProfile:
    """The member's profile with card rows loaded, or an unsaved default.

    Reading never writes: a member who has never touched discovery has no row,
    and their answer is the off-by-default profile.
    """

    profile = (
        PublicProfile.objects.select_related("user", "user__profile_photo")
        .prefetch_related(_routes_prefetch())
        .annotate(identity_verified=Exists(_current_kyc()))
        .filter(user=user)
        .first()
    )
    if profile is None:
        profile = PublicProfile(user=user)
        profile.identity_verified = (
            KycSubmission.objects.filter(user=user, status=KycSubmission.Status.APPROVED)
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
            .exists()
        )
    return profile


def own_state(profile: PublicProfile, *, profiles_enabled: bool) -> str:
    if not profiles_enabled:
        return STATE_DISABLED
    if profile.hidden_at is not None:
        # The owner is told only that the profile is not currently visible;
        # the staff reason is an operations record, not a message.
        return STATE_HIDDEN
    return STATE_VISIBLE if profile.is_discoverable else STATE_NOT_VISIBLE


def show_prompt(profile: PublicProfile, *, profiles_enabled: bool) -> bool:
    """The one-time opt-in card on Home (spec 4.3)."""

    return (
        profiles_enabled
        and not profile.is_discoverable
        and profile.hidden_at is None
        and profile.prompt_dismissed_at is None
    )


@dataclass(frozen=True, slots=True)
class ProfileUpdate:
    is_discoverable: bool | None = None
    usual_routes: list[tuple[int, int]] | None = None
    prompt_dismissed: bool = False


def _resolve_routes(pairs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if len(pairs) > MAX_USUAL_ROUTES:
        raise DiscoveryError(
            "usual_routes_too_many",
            f"A public profile shows at most {MAX_USUAL_ROUTES} usual routes.",
        )
    resolved: list[tuple[int, int]] = []
    for origin_id, destination_id in pairs:
        try:
            origin = resolve_locality(origin_id)
            destination = resolve_locality(destination_id)
        except PlaceNotFound as exc:
            raise DiscoveryError(exc.code, str(exc)) from exc
        if origin.pk == destination.pk:
            raise DiscoveryError(
                "usual_route_same_city", "A usual route needs two different cities."
            )
        pair = (origin.pk, destination.pk)
        if pair in resolved:
            raise DiscoveryError(
                "usual_route_duplicate", "Each usual route can be listed once."
            )
        resolved.append(pair)
    return resolved


def update_own_profile(user, change: ProfileUpdate, *, profiles_enabled: bool) -> None:
    """Apply a member's own profile change under a row lock.

    Turning the profile **off** and dismissing the prompt always work, whatever
    the switch says: a member must always be able to withdraw. Turning it
    **on** needs the switch, and records which wording they agreed to.
    """

    if change.is_discoverable and not profiles_enabled:
        raise DiscoveryError(
            "discovery_profiles_disabled",
            "Public profiles are not available right now.",
            status=409,
        )
    routes = None if change.usual_routes is None else _resolve_routes(change.usual_routes)
    now = timezone.now()
    with transaction.atomic():
        PublicProfile.objects.get_or_create(user=user)
        profile = PublicProfile.objects.select_for_update(no_key=True).get(user=user)
        fields: list[str] = []
        if change.is_discoverable is not None and change.is_discoverable != profile.is_discoverable:
            profile.is_discoverable = change.is_discoverable
            fields.append("is_discoverable")
            if change.is_discoverable:
                profile.consent_version = PROFILE_CONSENT_VERSION
                profile.consented_at = now
                fields += ["consent_version", "consented_at"]
        if (change.prompt_dismissed or change.is_discoverable) and profile.prompt_dismissed_at is None:
            profile.prompt_dismissed_at = now
            fields.append("prompt_dismissed_at")
        if fields:
            profile.save(update_fields=[*fields, "updated_at"])
        if routes is not None:
            profile.usual_routes.all().delete()
            PublicProfileRoute.objects.bulk_create(
                PublicProfileRoute(
                    profile=profile,
                    position=position,
                    origin_locality_id=origin_id,
                    destination_locality_id=destination_id,
                )
                for position, (origin_id, destination_id) in enumerate(routes)
            )


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------


def set_profile_hidden(*, user, actor, hidden: bool, reason: str) -> PublicProfile:
    """Hide or unhide a member's profile, audited, under a row lock (spec 4.5).

    Hiding a member who never created a profile still records the decision, so
    a profile they create later starts hidden.
    """

    from apps.admin_panel.services import record_admin_action

    reason = (reason or "").strip()
    if not reason:
        raise DiscoveryError("reason_required", "A reason is required.")
    with transaction.atomic():
        PublicProfile.objects.get_or_create(user=user)
        profile = PublicProfile.objects.select_for_update(no_key=True).get(user=user)
        before = {"hidden": profile.hidden_at is not None}
        if hidden and profile.hidden_at is None:
            profile.hidden_at = timezone.now()
            profile.hidden_by = actor
            profile.hidden_reason = reason[:500]
        elif not hidden and profile.hidden_at is not None:
            profile.hidden_at = None
            profile.hidden_by = None
            profile.hidden_reason = ""
        else:
            raise DiscoveryError(
                "profile_visibility_unchanged",
                "The profile is already hidden." if hidden else "The profile is not hidden.",
                status=409,
            )
        profile.save(update_fields=["hidden_at", "hidden_by", "hidden_reason", "updated_at"])
        record_admin_action(
            actor=actor,
            action="discovery.profile_hidden" if hidden else "discovery.profile_unhidden",
            target=profile,
            before=before,
            after={"hidden": hidden},
            reason=reason,
        )
    return profile
