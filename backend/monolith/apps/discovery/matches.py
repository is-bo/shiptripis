"""The Matches tier: real compatible matches for the caller's own items.

It is a fan-in over the two existing engines and nothing else (spec 4.1: "No
second matching implementation may exist"). A sender's group is the first page
of `find_travelers` for one of their open requests; a traveler's group is the
head of `compatible_requests_for_journey` for one of their journeys, in that
endpoint's own public shape. Both are bounded: at most three items, at most
three results each.
"""

from __future__ import annotations

from datetime import datetime

from django.db.models import OuterRef, Subquery

from apps.matching.discovery import (
    _place_matching_prefetches,
    compatible_journeys_for_request,
    compatible_requests_for_journey,
)
from apps.matching.find_travelers import find_travelers
from apps.matching.policy import Phase2Policy
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.trips.lifecycle import discoverable
from apps.trips.models import Journey, JourneyLeg

from .places import locality_block

MAX_ITEMS = 3
MAX_RESULTS_PER_ITEM = 3

STATE_RESULTS = "results"
STATE_NONE = "none"
STATE_NO_ACTIVE_ITEMS = "no_active_items"


def _envelope(groups: list[dict]) -> dict:
    if not groups:
        state = STATE_NO_ACTIVE_ITEMS
    elif any(group["results"] for group in groups):
        state = STATE_RESULTS
    else:
        state = STATE_NONE
    return {"state": state, "groups": groups}


def sender_matches(*, user, policy: Phase2Policy, at: datetime) -> dict:
    requests = list(
        DeliveryRequest.objects.select_related(
            "sender",
            "pickup_location",
            "delivery_location",
            "pickup_place__parent",
            "delivery_place__parent",
        )
        .prefetch_related(*_place_matching_prefetches("pickup_place", "delivery_place"))
        .filter(
            sender=user,
            kind=ParcelRequest.Kind.DELIVERY,
            schema_version=3,
            status=ParcelRequest.Status.OPEN,
            deadline_at__gt=at,
        )
        .order_by("-created_at", "-pk")[:MAX_ITEMS]
    )
    groups = []
    for delivery_request in requests:
        page, _ = find_travelers(
            delivery_request=delivery_request,
            candidates=compatible_journeys_for_request(
                delivery_request=delivery_request, policy=policy, at=at
            ),
            limit=min(MAX_RESULTS_PER_ITEM, policy.result_limit),
            offset=0,
            at=at,
        )
        groups.append(
            {
                "request": {
                    "id": delivery_request.pk,
                    "pickup": locality_block(delivery_request.pickup_place),
                    "delivery": locality_block(delivery_request.delivery_place),
                    "deadline_at": delivery_request.deadline_at.isoformat(),
                },
                "results": list(page.results),
                "more_available": page.total > len(page.results),
            }
        )
    return _envelope(groups)


def traveler_matches(*, user, policy: Phase2Policy, at: datetime) -> dict:
    next_departure = (
        JourneyLeg.objects.filter(journey_id=OuterRef("pk"), depart_at__gt=at)
        .order_by("depart_at", "pk")
        .values("depart_at")[:1]
    )
    journeys = list(
        discoverable(
            Journey.objects.select_related(
                "start_place__parent", "destination_place__parent"
            ).prefetch_related(
                *_place_matching_prefetches("start_place", "destination_place")
            ),
            at=at,
        )
        .filter(traveler=user, schema_version__gte=2)
        .annotate(next_departure=Subquery(next_departure))
        .filter(next_departure__isnull=False)
        .order_by("next_departure", "pk")[:MAX_ITEMS]
    )
    groups = []
    for journey in journeys:
        rows = compatible_requests_for_journey(journey=journey, policy=policy, at=at)
        groups.append(
            {
                "journey": {
                    "id": journey.pk,
                    "origin": locality_block(journey.start_place),
                    "destination": locality_block(journey.destination_place),
                    "next_departure_at": journey.next_departure.isoformat(),
                },
                # The compatible-requests endpoint's own card rows: cities
                # only, and the detour-bearing recommendation withheld.
                "results": [row.as_card_row() for row in rows[:MAX_RESULTS_PER_ITEM]],
                "more_available": len(rows) > MAX_RESULTS_PER_ITEM,
            }
        )
    return _envelope(groups)
