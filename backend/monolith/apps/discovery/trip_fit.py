"""Trip-fit alerts: "a parcel fits your trip" (spec 17.2, plan L12A).

When a request becomes open, the travelers whose published trip really fits it
are told once. "Really fits" is the matching engine's verdict and nothing
else: this module calls `compatible_journeys_for_request`, the function Find
Travelers and the Matches tier use, and keeps its eligible evaluations in the
engine's own ranking order. It evaluates, filters and ranks nothing itself.

It runs inside the request's route-alert fan-out job, before the route alerts,
so it is as durable as they are and re-reads every gate at run time: the
switch, the request still listable (the caller's check), and each journey
still discoverable and not paused (the engine's own queryset).

Limits, all in policy: at most ``trip_fit_max_travelers`` travelers per
request, best ranked first; at most ``trip_fit_daily_cap`` alerts per traveler
in 24 hours; never twice for the same request and journey. A traveler with
two fitting trips is told once, about the better ranked one, because the limit
counts travelers. The `TripFitAlert` row is written in the same transaction as
the notification, so a replay notifies nobody twice, and the event id is
derived from the request and the journey as a second guard.

The alert is not an offer: it carries the request and journey ids only,
reserves nothing, and the sender still proposes first.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db import transaction

from apps.core import channels, redis_bus
from apps.core.marketplace_policy import MarketplacePolicy
from apps.matching.discovery import compatible_journeys_for_request, phase2_policy
from apps.parcels.models import DeliveryRequest

from .models import TripFitAlert

#: The daily cap is counted over the last 24 hours, like "I can carry this".
CAP_WINDOW = timedelta(hours=24)


def notify_fitting_travelers(
    delivery_request: DeliveryRequest, *, policy: MarketplacePolicy, at: datetime
) -> frozenset[int]:
    """Tell the travelers whose trip fits; return everyone told about this request.

    The returned ids include travelers told by an earlier run of the same job,
    so the route-alert step leaves the same people out on a replay.
    """

    if policy.discovery.trip_fit_alerts_enabled:
        _notify(delivery_request, policy=policy, at=at)
    return frozenset(
        TripFitAlert.objects.filter(delivery_request=delivery_request).values_list(
            "traveler_id", flat=True
        )
    )


def _notify(delivery_request: DeliveryRequest, *, policy: MarketplacePolicy, at) -> None:
    ranked: dict[int, int] = {}  # traveler id -> best ranked journey id
    for evaluation in compatible_journeys_for_request(
        delivery_request=delivery_request, policy=phase2_policy(), at=at
    ):
        ranked.setdefault(evaluation.journey.traveler_id, evaluation.journey.pk)
    if not ranked:
        return

    with transaction.atomic():
        # Each traveler's cap is serialised on their row, in id order, so two
        # requests opening together can neither overrun a cap nor deadlock.
        list(
            get_user_model()
            .objects.select_for_update(no_key=True)
            .filter(pk__in=ranked)
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        told = set(
            TripFitAlert.objects.filter(delivery_request=delivery_request).values_list(
                "traveler_id", flat=True
            )
        )
        sent_recently = Counter(
            TripFitAlert.objects.filter(
                traveler_id__in=ranked, created_at__gt=at - CAP_WINDOW
            ).values_list("traveler_id", flat=True)
        )
        room = policy.discovery.trip_fit_max_travelers - len(told)
        chosen: list[TripFitAlert] = []
        for traveler_id, journey_id in ranked.items():
            if room <= 0:
                break
            if traveler_id in told:
                continue
            if sent_recently[traveler_id] >= policy.discovery.trip_fit_daily_cap:
                continue
            chosen.append(
                TripFitAlert(
                    delivery_request=delivery_request,
                    journey_id=journey_id,
                    traveler_id=traveler_id,
                )
            )
            room -= 1
        TripFitAlert.objects.bulk_create(chosen)
        for alert in chosen:
            redis_bus.publish_after_commit(
                channels.DISCOVERY_REQUEST_FITS_TRIP,
                {"request_id": delivery_request.pk, "journey_id": alert.journey_id},
                targets=[alert.traveler_id],
                idempotency_key=f"trip_fit:{delivery_request.pk}:{alert.journey_id}",
            )
