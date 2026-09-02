"""Transactional V1 Journey domain operations."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.kyc.models import KycSubmission

from apps.locations.models import AirportLocalityMapping, Place

from .models import Journey, JourneyLeg, JourneyLegProof


@dataclass(frozen=True)
class JourneyDomainError(Exception):
    """A client-safe, stable Journey domain failure."""

    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def has_current_kyc_approval(user, *, at=None) -> bool:
    """Return whether ``user`` has an approved, unexpired KYC submission.

    The denormalized ``User.is_kyc_verified`` flag can lag the shared KYC
    table. Journey publication intentionally reads the authoritative
    submission records and accounts for optional document expiry.
    """

    at = at or timezone.now()
    return (
        KycSubmission.objects.filter(
            user=user,
            status=KycSubmission.Status.APPROVED,
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=at))
        .exists()
    )


def validate_journey_verification_gates(journey: Journey) -> None:
    """Recheck the mutable KYC/proof gates for a published journey.

    Publication is not a permanent authorization grant: KYC can expire and a
    proof can be rejected later. Offer creation and acceptance call this
    helper again while holding their aggregate locks.
    """

    if not has_current_kyc_approval(journey.traveler):
        raise JourneyDomainError(
            "traveler_kyc_not_approved",
            "Current traveler KYC approval is required for this journey.",
        )

    flight_leg_ids = list(
        JourneyLeg.objects.filter(
            journey=journey,
            mode=JourneyLeg.Mode.FLIGHT,
        ).values_list("pk", flat=True)
    )
    if not flight_leg_ids:
        return
    approved_leg_ids = set(
        JourneyLegProof.objects.filter(
            leg_id__in=flight_leg_ids,
            status=JourneyLegProof.Status.APPROVED,
        ).values_list("leg_id", flat=True)
    )
    if approved_leg_ids != set(flight_leg_ids):
        raise JourneyDomainError(
            "flight_proof_not_approved",
            "Every flight leg requires a currently approved transport proof.",
        )


def _validate_leg_sequence(journey: Journey, legs: list[JourneyLeg]) -> None:
    if not legs:
        raise JourneyDomainError(
            "journey_has_no_legs",
            "A journey must contain at least one leg before publication.",
        )

    positions = [leg.position for leg in legs]
    if positions != list(range(len(legs))):
        raise JourneyDomainError(
            "journey_leg_positions_invalid",
            "Journey leg positions must be contiguous and start at zero.",
        )

    canonical = journey.schema_version >= 2

    def matching_place_id(place: Place | None) -> int | None:
        if place is None:
            return None
        if place.place_type == Place.PlaceType.LOCALITY:
            return place.pk
        mapping = place.airport_mappings.filter(
            active=True,
            is_primary=True,
            relationship_type=AirportLocalityMapping.RelationshipType.SERVED,
            locality__active=True,
        ).first()
        return mapping.locality_id if mapping else None

    if canonical:
        if matching_place_id(legs[0].origin_place) != matching_place_id(
            journey.start_place
        ) or matching_place_id(legs[-1].destination_place) != matching_place_id(
            journey.destination_place
        ):
            raise JourneyDomainError(
                "journey_endpoints_mismatch",
                "Journey endpoints must match the first and last leg.",
            )
    elif (
        legs[0].origin_id != journey.start_location_id
        or legs[-1].destination_id != journey.destination_location_id
    ):
        raise JourneyDomainError(
            "journey_endpoints_mismatch",
            "Journey endpoints must match the first and last leg.",
        )

    for index, leg in enumerate(legs):
        if canonical:
            origin_node = matching_place_id(leg.origin_place)
            destination_node = matching_place_id(leg.destination_place)
        else:
            origin_node = leg.origin_id
            destination_node = leg.destination_id
        if (
            origin_node is None
            or destination_node is None
            or origin_node == destination_node
        ):
            raise JourneyDomainError(
                "journey_leg_endpoints_invalid",
                f"Leg {leg.position} origin and destination must differ.",
            )
        if leg.arrive_at is not None and leg.arrive_at <= leg.depart_at:
            raise JourneyDomainError(
                "journey_leg_time_invalid",
                f"Leg {leg.position} arrival must be after departure.",
            )
        if index == 0:
            continue

        previous = legs[index - 1]
        if canonical:
            previous_node = matching_place_id(previous.destination_place)
            current_node = matching_place_id(leg.origin_place)
        else:
            previous_node = previous.destination_id
            current_node = leg.origin_id
        if (
            previous_node is None
            or current_node is None
            or previous_node != current_node
        ):
            raise JourneyDomainError(
                "journey_legs_disconnected",
                "Each leg must begin where the previous leg ends.",
            )
        if leg.depart_at <= previous.depart_at:
            raise JourneyDomainError(
                "journey_leg_time_order_invalid",
                "Journey leg departure times must be strictly increasing.",
            )
        if previous.arrive_at is not None and leg.depart_at < previous.arrive_at:
            raise JourneyDomainError(
                "journey_leg_time_order_invalid",
                "A leg cannot depart before the previous leg arrives.",
            )


@transaction.atomic
def publish_journey(*, journey: Journey, actor) -> Journey:
    """Publish ``journey`` after enforcing every V1 verification gate.

    Locking the aggregate makes concurrent publish attempts idempotent. The
    returned instance is the locked, freshly loaded row rather than a stale
    caller-provided object.
    """

    locked = Journey.objects.select_for_update(no_key=True).get(pk=journey.pk)
    if locked.traveler_id != actor.pk:
        raise JourneyDomainError(
            "journey_not_owned",
            "Only the journey owner can publish it.",
        )
    if locked.status not in {
        Journey.Status.DRAFT,
        Journey.Status.PENDING_VERIFICATION,
        Journey.Status.ACTIVE,
    }:
        raise JourneyDomainError(
            "journey_status_not_publishable",
            f"A journey in status '{locked.status}' cannot be published.",
        )
    legs = list(
        JourneyLeg.objects.filter(journey=locked)
        .select_for_update(no_key=True)
        .order_by("position", "pk")
    )
    _validate_leg_sequence(locked, legs)
    validate_journey_verification_gates(locked)

    if locked.status == Journey.Status.ACTIVE:
        return locked

    locked.status = Journey.Status.ACTIVE
    locked.published_at = locked.published_at or timezone.now()
    locked.save(update_fields=["status", "published_at", "updated_at"])
    return locked


@dataclass(frozen=True, slots=True)
class JourneyCancellationResult:
    journey: Journey
    released_allocations: int
    changed: bool


def cancel_journey(*, journey: Journey, actor) -> JourneyCancellationResult:
    """Cancel first, then idempotently release every pre-funding reservation."""

    # Imported lazily to avoid a trips -> deals -> matching -> trips cycle.
    from apps.deals.models import Deal

    changed = False
    with transaction.atomic():
        locked = Journey.objects.select_for_update(no_key=True).get(pk=journey.pk)
        if locked.traveler_id != actor.id:
            raise JourneyDomainError(
                "journey_not_owned",
                "Only the journey owner may cancel it.",
            )
        if locked.status in (Journey.Status.IN_PROGRESS, Journey.Status.COMPLETED):
            raise JourneyDomainError(
                "journey_not_cancellable",
                f"A journey in status '{locked.status}' cannot be cancelled.",
            )
        funded_deal = (
            Deal.objects.select_for_update(no_key=True)
            .filter(
                journey_id=locked.pk,
                status__in=(
                    Deal.Status.OFFER_ACCEPTED,
                    Deal.Status.FUNDED,
                    Deal.Status.PICKUP_READY,
                    Deal.Status.PICKED_UP,
                    Deal.Status.IN_TRANSIT,
                    Deal.Status.DELIVERY_READY,
                    Deal.Status.DELIVERY_CONFIRMED,
                    Deal.Status.PROTECTION_WINDOW,
                    Deal.Status.DISPUTED,
                ),
            )
            .order_by("pk")
            .first()
        )
        if funded_deal is not None:
            raise JourneyDomainError(
                "journey_has_funded_deal",
                "A journey with a funded or operational deal cannot be cancelled.",
            )
        if locked.status != Journey.Status.CANCELLED:
            locked.status = Journey.Status.CANCELLED
            locked.save(update_fields=["status", "updated_at"])
            changed = True

    from apps.deals.services import release_pending_deal_reservation
    from apps.matching.models import Match, MatchEvent, Offer

    # The cancelled status is committed before release locks are acquired.
    # An in-flight acceptance therefore either completes first and appears in
    # this query, or observes cancellation and rolls back.
    deal_ids = list(
        Deal.objects.filter(
            journey_id=locked.pk,
            status=Deal.Status.PAYMENT_REQUIRED,
        ).values_list("pk", flat=True)
    )
    released = 0
    for deal_id in deal_ids:
        result = release_pending_deal_reservation(
            deal_id=deal_id,
            reason="journey_cancelled",
        )
        released += result.released_allocations

    with transaction.atomic():
        pending_matches = list(
            Match.objects.select_for_update(no_key=True)
            .filter(journey_id=locked.pk, status=Match.Status.PENDING)
            .order_by("pk")
        )
        pending_ids = [match.pk for match in pending_matches]
        if pending_ids:
            now = timezone.now()
            Offer.objects.filter(
                match_id__in=pending_ids,
                status=Offer.Status.PENDING,
            ).update(status=Offer.Status.EXPIRED, responded_at=now)
            Match.objects.filter(pk__in=pending_ids).update(
                status=Match.Status.CANCELLED
            )
            MatchEvent.objects.bulk_create(
                [
                    MatchEvent(
                        match=match,
                        actor=actor,
                        kind=MatchEvent.Kind.MATCH_CANCELLED,
                        payload={"reason": "journey_cancelled"},
                    )
                    for match in pending_matches
                ]
            )

    locked.refresh_from_db()
    return JourneyCancellationResult(
        journey=locked,
        released_allocations=released,
        changed=changed,
    )
