""""I can carry this" (spec 4.4, kept by Ismail on 2026-11-11).

A traveler tells a sender that one of their journeys could carry the sender's
request. The server proves it first with the matching engine's own verdict
(`explain_candidate`, the same evaluation Find Travelers and the quote use).
The signal then sends the sender exactly one notification carrying the two ids
Find Travelers needs to focus on this traveler. It creates no match, no offer
and no reservation, and carries no price: the sender still proposes first.
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.core import channels, redis_bus
from apps.core.marketplace_policy import marketplace_policy
from apps.matching.discovery import explain_candidate
from apps.matching.public_contract import public_compatibility_payload
from apps.trips.models import Journey

from .errors import DiscoveryError
from .listings import listable_requests
from .models import TravelerInterest

#: The cap is "per day": counted over the last 24 hours, so it never resets
#: at a midnight that falls differently for a traveler in Algiers and in Paris.
CAP_WINDOW = timedelta(hours=24)


class IncompatibleInterest(DiscoveryError):
    def __init__(self, compatibility: dict):
        super().__init__(
            "incompatible_candidate",
            "This journey cannot carry this request.",
            status=409,
        )
        self.compatibility = compatibility


def register_interest(*, traveler, request_id: int, journey_id: int):
    """Record one signal and notify the sender once. Returns (interest, created)."""

    policy = marketplace_policy()
    if not policy.discovery.listings_enabled:
        raise DiscoveryError(
            "discovery_listings_disabled",
            "Browsing requests is not available right now.",
            status=409,
        )
    at = timezone.now()
    delivery_request = (
        listable_requests(at=at).filter(pk=request_id).exclude(sender=traveler).first()
    )
    if delivery_request is None:
        raise DiscoveryError(
            "request_not_found", "This request is no longer open.", status=404
        )
    if not Journey.objects.filter(pk=journey_id, traveler=traveler).exists():
        raise DiscoveryError("journey_not_found", "Choose one of your own journeys.", status=404)

    evaluation = explain_candidate(
        delivery_request_id=delivery_request.pk, journey_id=journey_id, at=at
    )
    if not evaluation.compatibility.compatible:
        raise IncompatibleInterest(
            public_compatibility_payload(evaluation.compatibility.as_dict())
        )

    with transaction.atomic():
        # One traveler's signals are serialised so the daily cap cannot be
        # overrun by two taps landing together.
        get_user_model().objects.select_for_update(no_key=True).filter(pk=traveler.pk).first()
        existing = TravelerInterest.objects.filter(
            delivery_request_id=delivery_request.pk, journey_id=journey_id
        ).first()
        if existing is not None:
            return existing, False
        sent_today = TravelerInterest.objects.filter(
            traveler=traveler, created_at__gt=at - CAP_WINDOW
        ).count()
        if sent_today >= policy.discovery.interest_daily_cap:
            raise DiscoveryError(
                "interest_daily_cap_reached",
                "You have reached today's limit. Try again tomorrow.",
                status=429,
            )
        interest = TravelerInterest.objects.create(
            delivery_request_id=delivery_request.pk,
            journey_id=journey_id,
            traveler=traveler,
        )
        redis_bus.publish_after_commit(
            channels.DISCOVERY_TRAVELER_INTERESTED,
            {"request_id": delivery_request.pk, "journey_id": journey_id},
            targets=[delivery_request.sender_id],
            idempotency_key=f"traveler_interest:{interest.pk}",
        )
    return interest, True
