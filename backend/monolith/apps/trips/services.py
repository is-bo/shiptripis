"""Transactional V1 Journey domain operations."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core import channels, redis_bus
from apps.core.event_resources import match_resources
from apps.kyc.models import KycSubmission

from apps.locations.models import AirportLocalityMapping, Place

from .models import Journey, JourneyLeg, JourneyLegProof
from .transport_rules import (
    MODE_UNAVAILABLE_CODE,
    check_leg_mode,
    mode_violation_message,
)


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
        # A leg can become impossible after it was written: the catalogue can
        # move a place between countries, and a legacy row predates the rule
        # entirely.  Publication is the last gate before senders see it, so
        # the check runs again here rather than being trusted from write time.
        violation = check_leg_mode(
            position=leg.position,
            mode=leg.mode,
            origin=leg.origin_place,
            destination=leg.destination_place,
        )
        if violation is not None:
            raise JourneyDomainError(
                MODE_UNAVAILABLE_CODE,
                mode_violation_message(violation),
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
            for match in pending_matches:
                redis_bus.publish_after_commit(
                    channels.OFFER_UPDATED,
                    match_resources(match),
                    targets=[match.sender_id, match.traveler_id],
                )

    locked.refresh_from_db()
    return JourneyCancellationResult(
        journey=locked,
        released_allocations=released,
        changed=changed,
    )


# ---------------------------------------------------------------------------
# Editing a journey
# ---------------------------------------------------------------------------

#: Statuses whose route the owner may still rewrite.
#:
#: A draft is private and a pending-verification journey is still private —
#: nobody has matched it, reserved capacity on it, or paid for it, so the
#: route is still the traveller's own business.  Every other status has
#: somebody else's expectations attached: an ACTIVE journey is discoverable
#: and may already be under offer, IN_PROGRESS is being flown, and the
#: terminal statuses are history.  Rewriting any of those would silently move
#: a delivery somebody bought.
EDITABLE_JOURNEY_STATUSES = frozenset(
    {
        Journey.Status.DRAFT,
        Journey.Status.PENDING_VERIFICATION,
    }
)

#: Match states that mean a sender is already looking at this exact route.
_BLOCKING_MATCH_STATUSES = ("pending", "accepted")


@dataclass(frozen=True, slots=True)
class JourneyEditability:
    """Whether a journey may be rewritten, and if not, why."""

    editable: bool
    code: str = ""
    message: str = ""

    def raise_if_blocked(self) -> None:
        if not self.editable:
            raise JourneyDomainError(self.code, self.message)


def journey_editability(journey: Journey, *, actor) -> JourneyEditability:
    """Answer "can this journey still be edited?" with a reason.

    Callers use this both to authorise a write and to tell the owner why the
    edit affordance is unavailable.  Hiding the button explains nothing; the
    reason is the useful part.
    """

    # Imported lazily: deals -> matching -> trips would otherwise cycle.
    from apps.deals.models import Deal
    from apps.matching.models import Match

    if journey.traveler_id != getattr(actor, "pk", None):
        return JourneyEditability(
            False,
            "journey_not_owned",
            "Only the journey owner can edit it.",
        )
    if journey.status not in EDITABLE_JOURNEY_STATUSES:
        return JourneyEditability(
            False,
            "journey_not_editable",
            f"A journey in status '{journey.status}' can no longer be edited.",
        )
    # Belt and braces.  A draft should never carry these, but if one ever
    # does, the route is load-bearing for somebody else and must not move.
    if Deal.objects.filter(journey_id=journey.pk).exists():
        return JourneyEditability(
            False,
            "journey_has_dependent_state",
            "A delivery is already attached to this journey's route.",
        )
    if Match.objects.filter(
        journey_id=journey.pk, status__in=_BLOCKING_MATCH_STATUSES
    ).exists():
        return JourneyEditability(
            False,
            "journey_has_dependent_state",
            "A sender is already proposing against this journey's route.",
        )
    return JourneyEditability(True)


#: Server-owned route snapshot fields and the value that means "not
#: measured".  An edit that turns a drive leg into a flight must not keep the
#: road distance it used to have; leaving it would let a stale polyline
#: describe a segment nobody drives.
_ROUTE_SNAPSHOT_DEFAULTS = {
    "distance_meters": None,
    "route_duration_seconds": None,
    "route_polyline": "",
    "route_provider": "",
    "route_profile": "",
    "route_captured_at": None,
    "allowed_detour_meters": None,
    "route_metadata": dict,
}


#: Leg fields whose change makes an approved flight proof prove a different
#: flight.  Item for item, this is what a boarding pass actually evidences.
_PROOF_BEARING_LEG_FIELDS = (
    "mode",
    "origin_place_id",
    "destination_place_id",
    "flight_number",
    "depart_at",
    "arrive_at",
)


def _normalized_flight_number(value: str | None) -> str:
    return (value or "").replace(" ", "").upper()


def _materially_changed_fields(existing: JourneyLeg, incoming: dict) -> list[str]:
    """Which proof-bearing fields differ between a stored leg and its edit."""

    changed: list[str] = []
    for field in _PROOF_BEARING_LEG_FIELDS:
        if field == "flight_number":
            before = _normalized_flight_number(existing.flight_number)
            after = _normalized_flight_number(incoming.get("flight_number", ""))
        elif field.endswith("_place_id"):
            before = getattr(existing, field)
            after = getattr(incoming.get(field[: -len("_id")]), "pk", None)
        else:
            before = getattr(existing, field)
            after = incoming.get(field)
        if before != after:
            changed.append(field)
    return changed


def _invalidate_leg_proofs(leg: JourneyLeg, *, changed_fields: list[str]) -> int:
    """Send a changed flight leg's live proofs back for review.

    An approved proof is demoted to pending rather than deleted.  The image is
    still the evidence a reviewer needs, and the reviewer's earlier decision
    is preserved in ``metadata`` — the row's own constraint requires an
    approval to carry a reviewer, so the audit lives beside the status rather
    than inside it.

    A rejected proof is left alone: it was already refused, and re-opening it
    would erase the refusal.
    """

    now = timezone.now()
    affected = list(
        JourneyLegProof.objects.select_for_update(no_key=True)
        .filter(
            leg=leg,
            status__in=(
                JourneyLegProof.Status.APPROVED,
                JourneyLegProof.Status.PENDING,
            ),
        )
        .order_by("pk")
    )
    for proof in affected:
        history = list(proof.metadata.get("invalidations", []))
        history.append(
            {
                "at": now.isoformat(),
                "reason": "flight_leg_materially_changed",
                "changed_fields": changed_fields,
                "previous_status": proof.status,
                "previous_reviewer_id": proof.reviewer_id,
                "previous_reviewed_at": (
                    proof.reviewed_at.isoformat() if proof.reviewed_at else None
                ),
            }
        )
        proof.metadata = {**proof.metadata, "invalidations": history}
        proof.status = JourneyLegProof.Status.PENDING
        proof.reviewer = None
        proof.reviewed_at = None
        proof.rejection_reason = ""
        proof.save(
            update_fields=[
                "metadata",
                "status",
                "reviewer",
                "reviewed_at",
                "rejection_reason",
                "updated_at",
            ]
        )
    return len(affected)


@dataclass(frozen=True, slots=True)
class JourneyRouteChange:
    """What one route edit did, in terms the owner needs to be told."""

    journey: Journey
    legs_created: int
    legs_updated: int
    legs_removed: int
    proofs_reset_for_review: int
    proofs_discarded: int


def replace_journey_route(
    *,
    journey: Journey,
    actor,
    start_place,
    destination_place,
    start_location,
    destination_location,
    notes: str,
    legs: list[dict],
) -> JourneyRouteChange:
    """Rewrite an editable journey's endpoints and whole leg chain.

    The chain is replaced as a unit under the aggregate lock.  Legs the client
    identified by ``id`` are updated in place, which is what carries an
    unchanged flight leg's reviewed proof across the edit; anything else is
    created, and any stored leg the client did not send is removed along with
    its proofs.

    The counts come back so the caller can say what happened, rather than
    letting a reviewed proof quietly become pending again.
    """

    with transaction.atomic():
        locked = Journey.objects.select_for_update(no_key=True).get(pk=journey.pk)
        journey_editability(locked, actor=actor).raise_if_blocked()

        stored = {
            leg.pk: leg
            for leg in JourneyLeg.objects.select_for_update(no_key=True)
            .filter(journey=locked)
            .order_by("position", "pk")
        }
        kept_ids = {leg["id"] for leg in legs if leg.get("id")}
        unknown = sorted(kept_ids - set(stored))
        if unknown:
            raise JourneyDomainError(
                "journey_leg_not_found",
                "This edit refers to legs that are not part of this journey.",
            )

        created = 0
        updated = 0
        reset_for_review = 0

        # Positions are unique per journey, so the incoming chain is parked in
        # a scratch band first.  Without it, moving leg 1 to position 0
        # collides with the leg still sitting there.
        scratch_offset = max((leg.position for leg in stored.values()), default=0) + (
            len(legs) + 1
        )
        for leg in stored.values():
            JourneyLeg.objects.filter(pk=leg.pk).update(
                position=leg.position + scratch_offset
            )

        for index, incoming in enumerate(legs):
            leg_id = incoming.pop("id", None)
            payload = {
                **{
                    field: (default() if callable(default) else default)
                    for field, default in _ROUTE_SNAPSHOT_DEFAULTS.items()
                },
                **incoming,
                "position": index,
            }
            if leg_id and leg_id in stored:
                existing = stored[leg_id]
                changed = _materially_changed_fields(existing, payload)
                for field, value in payload.items():
                    setattr(existing, field, value)
                existing.save()
                updated += 1
                # Only a flight leg carries proof, and only a change to what
                # the proof evidences invalidates it.  A capacity edit does
                # not make a boarding pass wrong.
                if changed and (
                    existing.mode == JourneyLeg.Mode.FLIGHT or "mode" in changed
                ):
                    reset_for_review += _invalidate_leg_proofs(
                        existing, changed_fields=changed
                    )
            else:
                JourneyLeg.objects.create(journey=locked, **payload)
                created += 1

        removed_ids = set(stored) - kept_ids
        discarded = (
            JourneyLegProof.objects.filter(leg_id__in=removed_ids).count()
            if removed_ids
            else 0
        )
        removed = len(removed_ids)
        if removed_ids:
            JourneyLeg.objects.filter(pk__in=removed_ids).delete()

        locked.start_place = start_place
        locked.destination_place = destination_place
        locked.start_location = start_location
        locked.destination_location = destination_location
        locked.notes = notes
        locked.save(
            update_fields=[
                "start_place",
                "destination_place",
                "start_location",
                "destination_location",
                "notes",
                "updated_at",
            ]
        )

        # The chain is re-read and re-validated exactly as publication would,
        # so an edit can never leave a journey in a shape publish will refuse.
        rewritten = list(
            JourneyLeg.objects.filter(journey=locked)
            .select_related("origin_place", "destination_place")
            .order_by("position", "pk")
        )
        _validate_leg_sequence(locked, rewritten)

    locked.refresh_from_db()
    return JourneyRouteChange(
        journey=locked,
        legs_created=created,
        legs_updated=updated,
        legs_removed=removed,
        proofs_reset_for_review=reset_for_review,
        proofs_discarded=discarded,
    )
