from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Min, Q, Sum
from django.utils import timezone

from apps.accounts.models import User
from apps.core.business_settings import calculate_offer_economics
from apps.deals.models import Deal, DealEvent, DealLegAllocation, DealTermsSnapshot
from apps.kyc.models import KycSubmission
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.routing.geometry import GeoPoint
from apps.routing.providers import (
    GeocodeResult,
    RouteProvider,
    RouteProviderError,
    RouteProviderUnavailable,
    RouteResult,
    get_route_provider,
)
from apps.trips.models import Journey, JourneyLeg, JourneyLegProof

from .discovery import evaluate_candidate, phase2_policy
from .models import Match, MatchEvent, Offer
from .policy import Phase2Policy


class V1OfferError(RuntimeError):
    """Base for every V1 negotiation failure.

    `code` is the machine contract; the message is presentation text only.
    Subclasses may attach extra structured fields through `details()` so a
    client never has to parse an English sentence.
    """

    code = "offer_error"

    def details(self) -> dict:
        return {}


class OfferAuthorizationError(V1OfferError):
    code = "not_authorized"


class OfferStateError(V1OfferError):
    """Generic state failure.

    Kept as the shared base so existing `except OfferStateError` handlers still
    catch every state transition, but no code path raises it directly any more:
    each cause has its own subclass and therefore its own machine code.

    Any state failure may also carry the compatibility gate names that produced
    it, so a client learns *which* gate closed without reading the sentence.
    """

    code = "invalid_state"

    def __init__(self, message: str, *, rejection_codes: tuple[str, ...] = ()):
        super().__init__(message)
        self.rejection_codes = tuple(rejection_codes)

    def details(self) -> dict:
        if not self.rejection_codes:
            return {}
        return {"rejection_codes": list(self.rejection_codes)}


class RequestNotOpen(OfferStateError):
    code = "request_not_open"


class RequestAlreadyMatched(OfferStateError):
    code = "request_already_matched"


class JourneyNotActive(OfferStateError):
    code = "journey_not_active"


class OfferNotPending(OfferStateError):
    code = "offer_not_pending"


class MatchNotPending(OfferStateError):
    code = "match_not_pending"


class MatchLegRangeMissing(OfferStateError):
    code = "match_leg_range_missing"


class OfferEconomicsMissing(OfferStateError):
    code = "offer_economics_missing"


class LegacyContractNotSupported(OfferStateError):
    code = "legacy_contract_not_supported"


class ProductRequestRetired(OfferStateError):
    code = "product_request_retired"


class RequestWeightInvalid(OfferStateError):
    code = "request_weight_invalid"


class InvalidReservationGrace(OfferStateError):
    code = "invalid_reservation_grace"


class RoutePreflightMissing(OfferStateError):
    code = "route_preflight_missing"


class RouteInputsChanged(OfferStateError):
    code = "route_inputs_changed"


class InvalidLegRange(V1OfferError):
    code = "invalid_leg_range"


class CapacityExceeded(V1OfferError):
    code = "capacity_exceeded"

    def __init__(self, message: str, *, journey_leg_ids: list[int] | None = None):
        super().__init__(message)
        self.journey_leg_ids = journey_leg_ids or []

    def details(self) -> dict:
        return {"journey_leg_ids": list(self.journey_leg_ids)}


class IncompatibleCandidate(OfferStateError):
    """A hard compatibility gate failed with no more specific code.

    The failing gate names travel as `rejection_codes`; revoked traveler KYC is
    `traveler_kyc_current` and a missing/withdrawn flight proof is
    `flight_proofs_approved`.
    """

    code = "incompatible_candidate"


class PriceBelowMinimum(OfferStateError):
    code = "reward_below_minimum"

    def __init__(self, message: str, *, minimum_reward_eur_cents: int):
        super().__init__(message)
        self.minimum_reward_eur_cents = minimum_reward_eur_cents

    def details(self) -> dict:
        return {"minimum_reward_eur_cents": self.minimum_reward_eur_cents}


#: Compatibility gates that have a dedicated machine code, in the order a
#: client should be told about them. Everything else collapses to
#: `incompatible_candidate` while still reporting its gate names.
GATE_ERROR_CLASSES: tuple[tuple[str, type], ...] = (
    ("journey_active", JourneyNotActive),
    ("request_active", RequestNotOpen),
    ("request_has_no_active_deal", RequestAlreadyMatched),
)


class _FrozenRouteReplayMiss(RuntimeError):
    """Raised when locked rows would require route I/O not done in preflight."""


class _RecordingRouteProvider:
    """Record provider outcomes before acquiring database row locks."""

    def __init__(self, provider: RouteProvider) -> None:
        self.provider = provider
        self.name = provider.name
        self._capabilities = provider.capabilities()
        self._outcomes: dict[tuple, list[tuple[bool, object]]] = {}

    def capabilities(self) -> frozenset[str]:
        return self._capabilities

    def _record(self, key: tuple, callback):
        try:
            value = callback()
        except (RouteProviderUnavailable, RouteProviderError) as exc:
            self._outcomes.setdefault(key, []).append((False, exc))
            raise
        self._outcomes.setdefault(key, []).append((True, value))
        return value

    def geocode(
        self,
        query: str,
        *,
        country_code: str | None = None,
    ) -> tuple[GeocodeResult, ...]:
        key = ("geocode", query, country_code)
        return self._record(
            key,
            lambda: self.provider.geocode(query, country_code=country_code),
        )

    def reverse_geocode(self, point: GeoPoint) -> GeocodeResult:
        key = ("reverse_geocode", point)
        return self._record(key, lambda: self.provider.reverse_geocode(point))

    def directions(
        self,
        points,
        *,
        profile: str,
    ) -> RouteResult:
        frozen_points = tuple(points)
        key = ("directions", frozen_points, profile)
        return self._record(
            key,
            lambda: self.provider.directions(frozen_points, profile=profile),
        )

    def replay(self) -> _FrozenRouteProvider:
        return _FrozenRouteProvider(
            name=self.name,
            capabilities=self._capabilities,
            outcomes={key: tuple(values) for key, values in self._outcomes.items()},
        )


class _FrozenRouteProvider:
    """Replay preflight provider outcomes without cache, network, or provider I/O."""

    def __init__(
        self,
        *,
        name: str,
        capabilities: frozenset[str],
        outcomes: dict[tuple, tuple[tuple[bool, object], ...]],
    ) -> None:
        self.name = name
        self._capabilities = capabilities
        self._outcomes = outcomes
        self._positions: dict[tuple, int] = {}

    def capabilities(self) -> frozenset[str]:
        return self._capabilities

    def _replay(self, key: tuple):
        try:
            outcomes = self._outcomes[key]
            position = self._positions.get(key, 0)
            succeeded, value = outcomes[position]
        except (KeyError, IndexError) as exc:
            raise _FrozenRouteReplayMiss(
                "Route inputs changed after provider preflight; retry the operation."
            ) from exc
        self._positions[key] = position + 1
        if succeeded:
            return value
        assert isinstance(value, (RouteProviderUnavailable, RouteProviderError))
        raise value

    def geocode(
        self,
        query: str,
        *,
        country_code: str | None = None,
    ) -> tuple[GeocodeResult, ...]:
        return self._replay(("geocode", query, country_code))

    def reverse_geocode(self, point: GeoPoint) -> GeocodeResult:
        return self._replay(("reverse_geocode", point))

    def directions(
        self,
        points,
        *,
        profile: str,
    ) -> RouteResult:
        return self._replay(("directions", tuple(points), profile))


@dataclass(frozen=True, slots=True)
class AcceptedDeal:
    deal: Deal
    created: bool


def _v1_offer_values(
    traveler_reward_eur_cents: int,
    *,
    evaluation,
    policy,
) -> dict:
    settings_version = policy.settings_version
    economics = calculate_offer_economics(traveler_reward_eur_cents, settings_version)
    snapshot = {
        "canonical_currency": "EUR",
        "commission_rate_bps": settings_version.commission_rate_bps,
        "pricing_version": settings_version.pricing_version,
        "business_settings_version": settings_version.version,
        "policy": settings_version.policy,
        "pricing": evaluation.pricing.as_dict(),
        "compatibility": evaluation.compatibility.as_dict(),
        "ranking": evaluation.ranking,
        "reservation": {
            "payment_grace_seconds": policy.payment_grace_seconds,
        },
    }
    return {
        **economics,
        "economics_version": Offer.EconomicsVersion.V1_EUR,
        "currency": Offer.Currency.EUR,
        "pricing_version": settings_version.pricing_version,
        "business_settings_version": settings_version,
        "terms_snapshot": snapshot,
        # Required legacy columns remain explicit zeroes and are never read as EUR.
        "base_amount_dzd": 0,
        "base_fee_dzd": 0,
        "commission_dzd": 0,
        "total_dzd": 0,
    }


def _validate_evaluation(
    *,
    delivery_request: DeliveryRequest,
    journey: Journey,
    traveler_reward_eur_cents: int,
    expected_start_leg_id: int | None = None,
    expected_end_leg_id: int | None = None,
    policy: Phase2Policy | None = None,
    route_provider: RouteProvider | None = None,
    at=None,
):
    policy = policy or phase2_policy()
    try:
        evaluation = evaluate_candidate(
            delivery_request=delivery_request,
            journey=journey,
            policy=policy,
            at=at,
            route_provider=route_provider,
        )
    except _FrozenRouteReplayMiss as exc:
        raise RouteInputsChanged(str(exc)) from exc
    if not evaluation.compatibility.compatible:
        rejection_codes = evaluation.compatibility.rejection_codes
        if "capacity_available_on_every_leg" in rejection_codes:
            raise CapacityExceeded(
                "One or more covered journey legs no longer has enough capacity.",
                journey_leg_ids=[
                    leg.pk for leg in evaluation.compatibility.covered_legs
                ],
            )
        reasons = ", ".join(rejection_codes)
        message = f"The request and journey are incompatible: {reasons}."
        for code, error_class in GATE_ERROR_CLASSES:
            if code in rejection_codes:
                raise error_class(message, rejection_codes=rejection_codes)
        raise IncompatibleCandidate(message, rejection_codes=rejection_codes)
    covered = evaluation.compatibility.covered_legs
    if not covered:
        raise IncompatibleCandidate(
            "The compatible candidate covers no journey legs.",
            rejection_codes=("covered_legs_empty",),
        )
    if expected_start_leg_id is not None and (
        covered[0].pk != expected_start_leg_id or covered[-1].pk != expected_end_leg_id
    ):
        raise InvalidLegRange(
            "The submitted leg range does not match the server-calculated sub-route."
        )
    assert evaluation.pricing is not None
    minimum = evaluation.pricing.minimum_reward_eur_cents
    if traveler_reward_eur_cents < minimum:
        raise PriceBelowMinimum(
            f"Traveler reward must be at least {minimum} EUR cents for this match.",
            minimum_reward_eur_cents=minimum,
        )
    return policy, evaluation


def _preflight_evaluation(
    *,
    delivery_request: DeliveryRequest,
    journey: Journey,
    traveler_reward_eur_cents: int,
    expected_start_leg_id: int,
    expected_end_leg_id: int,
    policy: Phase2Policy,
) -> _FrozenRouteProvider:
    """Resolve every possible external route lookup before taking row locks."""

    provider = _RecordingRouteProvider(
        get_route_provider(
            external_call_budget=(
                settings.ROUTE_PROVIDER_MAX_EXTERNAL_CALLS_PER_MATCHING_REQUEST
            )
        )
    )
    _validate_evaluation(
        delivery_request=delivery_request,
        journey=journey,
        traveler_reward_eur_cents=traveler_reward_eur_cents,
        expected_start_leg_id=expected_start_leg_id,
        expected_end_leg_id=expected_end_leg_id,
        policy=policy,
        route_provider=provider,
    )
    return provider.replay()


def _lock_journey_legs(journey: Journey) -> list[JourneyLeg]:
    """Lock every leg of ``journey`` for update and return them in route order.

    ``of=("self",)`` is load-bearing, not cosmetic. Compatibility needs each
    leg's ``origin``/``destination`` row, and both columns became nullable with
    canonical geography, so ``select_related`` compiles to a LEFT OUTER JOIN. A
    bare ``FOR UPDATE`` would then ask PostgreSQL to lock the nullable side of
    that join, which it rejects outright with "FOR UPDATE cannot be applied to
    the nullable side of an outer join". SQLite never sees this: it has no
    ``has_select_for_update``, so the clause is dropped before it is compiled.

    Naming the leg table keeps the lock exactly where the transaction writes —
    the per-segment capacity rows — and leaves the read-only Location rows
    unlocked, which is what every caller already intended.

    Callers must already hold the Journey row lock; legs are always taken after
    their journey and never before it.
    """

    return list(
        JourneyLeg.objects.select_for_update(no_key=True, of=("self",))
        .select_related("origin", "destination")
        .filter(journey=journey)
        .order_by("position", "pk")
    )


def _lock_acceptance_eligibility(
    *,
    delivery_request: DeliveryRequest,
    journey: Journey,
    legs: list[JourneyLeg],
    at,
) -> None:
    """Freeze mutable account, KYC, and flight-proof gates for acceptance.

    Review transitions update KYC/proof rows before any related User row. Keep
    the same eligibility-witness -> User order here to avoid a User/KYC
    deadlock, and attach the locked result so compatibility performs no later
    unlocked EXISTS read.
    """

    current_kyc = (
        KycSubmission.objects.select_for_update(no_key=True)
        .filter(user_id=journey.traveler_id, status=KycSubmission.Status.APPROVED)
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=at))
        .order_by("pk")
        .first()
    )
    journey.has_current_kyc_value = current_kyc is not None

    flight_legs = [leg for leg in legs if leg.mode == JourneyLeg.Mode.FLIGHT]
    proof_witness_ids = list(
        JourneyLegProof.objects.filter(
            leg_id__in=[leg.pk for leg in flight_legs],
            status=JourneyLegProof.Status.APPROVED,
        )
        .values("leg_id")
        .annotate(witness_id=Min("pk"))
        .values_list("witness_id", flat=True)
    )
    approved_proof_leg_ids = set(
        JourneyLegProof.objects.select_for_update(no_key=True)
        .filter(pk__in=proof_witness_ids, status=JourneyLegProof.Status.APPROVED)
        .order_by("pk")
        .values_list("leg_id", flat=True)
    )
    for leg in flight_legs:
        leg.has_approved_proof_value = leg.pk in approved_proof_leg_ids

    locked_users = {
        user.pk: user
        for user in User.objects.select_for_update(no_key=True)
        .filter(pk__in={delivery_request.sender_id, journey.traveler_id})
        .order_by("pk")
    }
    delivery_request.sender = locked_users[delivery_request.sender_id]
    journey.traveler = locked_users[journey.traveler_id]


def create_sender_offer(
    *,
    sender: User,
    delivery_request: DeliveryRequest,
    journey: Journey,
    start_leg_id: int,
    end_leg_id: int,
    traveler_reward_eur_cents: int,
    note: str = "",
) -> Offer:
    request_row = DeliveryRequest.objects.select_related(
        "sender", "pickup_location", "delivery_location"
    ).get(pk=delivery_request.pk)
    journey_row = Journey.objects.select_related("traveler").get(pk=journey.pk)
    if request_row.sender_id != sender.id:
        raise OfferAuthorizationError("Only the request sender may propose first.")
    if journey_row.traveler_id == sender.id:
        raise OfferAuthorizationError("A sender cannot propose to their own journey.")
    if (
        request_row.target_traveler_id is not None
        and request_row.target_traveler_id != journey_row.traveler_id
    ):
        raise OfferAuthorizationError(
            "This private delivery request targets a different traveler."
        )
    journey_row._matching_legs = list(
        JourneyLeg.objects.select_related("origin", "destination")
        .filter(journey=journey_row)
        .order_by("position", "pk")
    )
    replay_provider = _preflight_evaluation(
        delivery_request=request_row,
        journey=journey_row,
        traveler_reward_eur_cents=traveler_reward_eur_cents,
        expected_start_leg_id=start_leg_id,
        expected_end_leg_id=end_leg_id,
        policy=phase2_policy(),
    )
    return _create_sender_offer_locked(
        sender=sender,
        delivery_request_id=delivery_request.pk,
        journey_id=journey.pk,
        start_leg_id=start_leg_id,
        end_leg_id=end_leg_id,
        traveler_reward_eur_cents=traveler_reward_eur_cents,
        note=note,
        replay_provider=replay_provider,
    )


@transaction.atomic
def _create_sender_offer_locked(
    *,
    sender: User,
    delivery_request_id: int,
    journey_id: int,
    start_leg_id: int,
    end_leg_id: int,
    traveler_reward_eur_cents: int,
    note: str,
    replay_provider: RouteProvider,
) -> Offer:
    request_row = (
        DeliveryRequest.objects.select_for_update(
            no_key=True, of=("self", "parcelrequest_ptr")
        )
        .select_related("sender", "pickup_location", "delivery_location")
        .get(pk=delivery_request_id)
    )
    journey_row = (
        Journey.objects.select_for_update(no_key=True)
        .select_related("traveler")
        .get(pk=journey_id)
    )
    if request_row.sender_id != sender.id:
        raise OfferAuthorizationError("Only the request sender may propose first.")
    if request_row.status != ParcelRequest.Status.OPEN:
        raise RequestNotOpen("The delivery request is not open.")
    if getattr(request_row, "schema_version", 1) < 2:
        raise LegacyContractNotSupported(
            "Legacy delivery requests cannot enter the V1 flow."
        )
    if journey_row.status != Journey.Status.ACTIVE:
        raise JourneyNotActive("The journey is not active.")
    if journey_row.traveler_id == sender.id:
        raise OfferAuthorizationError("A sender cannot propose to their own journey.")
    if (
        request_row.target_traveler_id is not None
        and request_row.target_traveler_id != journey_row.traveler_id
    ):
        raise OfferAuthorizationError(
            "This private delivery request targets a different traveler."
        )

    locked_legs = _lock_journey_legs(journey_row)
    journey_row._matching_legs = locked_legs
    policy, evaluation = _validate_evaluation(
        delivery_request=request_row,
        journey=journey_row,
        traveler_reward_eur_cents=traveler_reward_eur_cents,
        expected_start_leg_id=start_leg_id,
        expected_end_leg_id=end_leg_id,
        route_provider=replay_provider,
    )
    legs = list(evaluation.compatibility.covered_legs)
    offer_values = _v1_offer_values(
        traveler_reward_eur_cents,
        evaluation=evaluation,
        policy=policy,
    )
    match = Match.objects.create(
        parcel=request_row.parcelrequest_ptr,
        journey=journey_row,
        start_leg=legs[0],
        end_leg=legs[-1],
        sender=sender,
        traveler=journey_row.traveler,
        status=Match.Status.PENDING,
        matching_version=evaluation.compatibility.as_dict()["matching_version"],
        matched_distance_meters=evaluation.compatibility.matched_distance_meters,
        compatibility_snapshot=evaluation.compatibility.as_dict(),
        ranking_snapshot=evaluation.ranking or {},
    )
    offer = Offer.objects.create(
        match=match,
        proposed_by=Offer.ProposedBy.SENDER,
        proposer=sender,
        note=note,
        **offer_values,
    )
    MatchEvent.objects.create(
        match=match,
        offer=offer,
        actor=sender,
        kind=MatchEvent.Kind.OFFER_CREATED,
        payload={
            "economics_version": Offer.EconomicsVersion.V1_EUR,
            "currency": Offer.Currency.EUR,
            "start_leg_id": legs[0].id,
            "end_leg_id": legs[-1].id,
        },
    )
    return offer


def counter_offer(
    *,
    pending_offer: Offer,
    actor: User,
    traveler_reward_eur_cents: int,
    note: str = "",
) -> Offer:
    current = Offer.objects.select_related(
        "match", "match__parcel", "match__journey"
    ).get(pk=pending_offer.pk)
    match = current.match
    if match.parcel.kind == ParcelRequest.Kind.PRODUCT:
        raise ProductRequestRetired("ProductRequest/Kaba offer mutations are retired.")
    if actor.id not in (match.sender_id, match.traveler_id):
        raise OfferAuthorizationError("Only a party may counter this offer.")
    if current.proposer_id == actor.id:
        raise OfferAuthorizationError("The proposer cannot counter their own offer.")
    if current.status != Offer.Status.PENDING:
        raise OfferNotPending("The offer is no longer pending.")
    if match.status != Match.Status.PENDING:
        raise MatchNotPending("The negotiation is no longer pending.")
    if current.economics_version != Offer.EconomicsVersion.V1_EUR:
        raise LegacyContractNotSupported(
            "Use the legacy counter path for a legacy DZD offer."
        )
    if (
        match.journey_id is None
        or match.start_leg_id is None
        or match.end_leg_id is None
    ):
        raise MatchLegRangeMissing("The V1 match has no covered journey-leg range.")
    request_row = DeliveryRequest.objects.select_related(
        "sender", "pickup_location", "delivery_location"
    ).get(pk=match.parcel_id)
    journey = Journey.objects.select_related("traveler").get(pk=match.journey_id)
    journey._matching_legs = list(
        JourneyLeg.objects.select_related("origin", "destination")
        .filter(journey=journey)
        .order_by("position", "pk")
    )
    replay_provider = _preflight_evaluation(
        delivery_request=request_row,
        journey=journey,
        traveler_reward_eur_cents=traveler_reward_eur_cents,
        expected_start_leg_id=match.start_leg_id,
        expected_end_leg_id=match.end_leg_id,
        policy=phase2_policy(),
    )
    return _counter_offer_locked(
        pending_offer_id=pending_offer.pk,
        actor=actor,
        traveler_reward_eur_cents=traveler_reward_eur_cents,
        note=note,
        replay_provider=replay_provider,
    )


@transaction.atomic
def _counter_offer_locked(
    *,
    pending_offer_id: int,
    actor: User,
    traveler_reward_eur_cents: int,
    note: str,
    replay_provider: RouteProvider,
) -> Offer:
    # Every V1 negotiation write locks in request -> Match -> Offer order.
    # Locking the request first also serializes acceptance against counters and
    # against acceptance of a competing Match for the same request.
    snapshot = Offer.objects.values(
        "match_id", "match__parcel_id", "match__parcel__kind"
    ).get(pk=pending_offer_id)
    if snapshot["match__parcel__kind"] == ParcelRequest.Kind.PRODUCT:
        raise ProductRequestRetired("ProductRequest/Kaba offer mutations are retired.")
    DeliveryRequest.objects.select_for_update(
        no_key=True, of=("self", "parcelrequest_ptr")
    ).get(pk=snapshot["match__parcel_id"])
    match = Match.objects.select_for_update(no_key=True).get(pk=snapshot["match_id"])
    current = Offer.objects.select_for_update(no_key=True).get(pk=pending_offer_id)
    if actor.id not in (match.sender_id, match.traveler_id):
        raise OfferAuthorizationError("Only a party may counter this offer.")
    if current.proposer_id == actor.id:
        raise OfferAuthorizationError("The proposer cannot counter their own offer.")
    if current.status != Offer.Status.PENDING:
        raise OfferNotPending("The offer is no longer pending.")
    if match.status != Match.Status.PENDING:
        raise MatchNotPending("The negotiation is no longer pending.")
    if current.economics_version != Offer.EconomicsVersion.V1_EUR:
        raise LegacyContractNotSupported(
            "Use the legacy counter path for a legacy DZD offer."
        )

    request_row = DeliveryRequest.objects.select_related(
        "sender", "pickup_location", "delivery_location"
    ).get(pk=snapshot["match__parcel_id"])
    if (
        match.journey_id is None
        or match.start_leg_id is None
        or match.end_leg_id is None
    ):
        raise MatchLegRangeMissing("The V1 match has no covered journey-leg range.")
    journey = (
        Journey.objects.select_for_update(no_key=True)
        .select_related("traveler")
        .get(pk=match.journey_id)
    )
    journey._matching_legs = _lock_journey_legs(journey)
    policy, evaluation = _validate_evaluation(
        delivery_request=request_row,
        journey=journey,
        traveler_reward_eur_cents=traveler_reward_eur_cents,
        expected_start_leg_id=match.start_leg_id,
        expected_end_leg_id=match.end_leg_id,
        route_provider=replay_provider,
    )
    current.status = Offer.Status.COUNTERED
    current.responded_at = timezone.now()
    current.save(update_fields=["status", "responded_at", "updated_at"])
    side = (
        Offer.ProposedBy.SENDER
        if actor.id == match.sender_id
        else Offer.ProposedBy.TRAVELER
    )
    child = Offer.objects.create(
        match=match,
        parent_offer=current,
        proposed_by=side,
        proposer=actor,
        note=note,
        **_v1_offer_values(
            traveler_reward_eur_cents,
            evaluation=evaluation,
            policy=policy,
        ),
    )
    MatchEvent.objects.create(
        match=match,
        offer=child,
        actor=actor,
        kind=MatchEvent.Kind.OFFER_COUNTERED,
        payload={
            "parent_offer_id": current.id,
            "economics_version": Offer.EconomicsVersion.V1_EUR,
            "currency": Offer.Currency.EUR,
        },
    )
    return child


def accept_offer(*, pending_offer: Offer, actor: User) -> AcceptedDeal:
    current = Offer.objects.select_related(
        "match", "match__parcel", "business_settings_version"
    ).get(pk=pending_offer.pk)
    match = current.match
    if match.parcel.kind == ParcelRequest.Kind.PRODUCT:
        raise ProductRequestRetired("ProductRequest/Kaba offer mutations are retired.")
    if actor.id not in (match.sender_id, match.traveler_id):
        raise OfferAuthorizationError("Only a party may accept this offer.")
    if current.proposer_id == actor.id:
        raise OfferAuthorizationError("The proposer cannot accept their own offer.")
    if current.status == Offer.Status.ACCEPTED:
        return _accept_offer_locked(
            pending_offer_id=pending_offer.pk,
            actor=actor,
            replay_provider=None,
        )
    if current.economics_version != Offer.EconomicsVersion.V1_EUR:
        raise LegacyContractNotSupported(
            "Use the legacy acceptance path for a legacy DZD offer."
        )
    if current.status != Offer.Status.PENDING:
        raise OfferNotPending("The offer is no longer pending.")
    if match.status != Match.Status.PENDING:
        raise MatchNotPending("The negotiation is no longer pending.")
    if (
        match.journey_id is None
        or match.start_leg_id is None
        or match.end_leg_id is None
    ):
        raise MatchLegRangeMissing("The V1 match has no covered journey-leg range.")
    if (
        current.traveler_reward_minor is None
        or current.business_settings_version is None
    ):
        raise OfferEconomicsMissing(
            "The V1 offer has no valid economic settings snapshot."
        )
    request_row = DeliveryRequest.objects.select_related(
        "sender", "pickup_location", "delivery_location"
    ).get(pk=match.parcel_id)
    journey = Journey.objects.select_related("traveler").get(pk=match.journey_id)
    journey._matching_legs = list(
        JourneyLeg.objects.select_related("origin", "destination")
        .filter(journey=journey)
        .order_by("position", "pk")
    )
    replay_provider = _preflight_evaluation(
        delivery_request=request_row,
        journey=journey,
        traveler_reward_eur_cents=current.traveler_reward_minor,
        expected_start_leg_id=match.start_leg_id,
        expected_end_leg_id=match.end_leg_id,
        policy=Phase2Policy.from_settings(current.business_settings_version),
    )
    return _accept_offer_locked(
        pending_offer_id=pending_offer.pk,
        actor=actor,
        replay_provider=replay_provider,
    )


@transaction.atomic
def _accept_offer_locked(
    *,
    pending_offer_id: int,
    actor: User,
    replay_provider: RouteProvider | None,
) -> AcceptedDeal:
    snapshot = Offer.objects.values(
        "match_id", "match__parcel_id", "match__parcel__kind"
    ).get(pk=pending_offer_id)
    if snapshot["match__parcel__kind"] == ParcelRequest.Kind.PRODUCT:
        raise ProductRequestRetired("ProductRequest/Kaba offer mutations are retired.")
    request_row = (
        DeliveryRequest.objects.select_for_update(
            no_key=True, of=("self", "parcelrequest_ptr")
        )
        .select_related("sender", "pickup_location", "delivery_location")
        .get(pk=snapshot["match__parcel_id"])
    )
    request_matches = list(
        Match.objects.select_for_update(no_key=True)
        .filter(parcel_id=request_row.pk)
        .order_by("pk")
    )
    match_by_id = {row.pk: row for row in request_matches}
    match = match_by_id.get(snapshot["match_id"])
    if match is None:
        raise OfferNotPending("The offer no longer belongs to this request.")
    request_offers = list(
        Offer.objects.select_for_update(no_key=True)
        .filter(match_id__in=[row.pk for row in request_matches])
        .order_by("pk")
    )
    current = next((row for row in request_offers if row.pk == pending_offer_id), None)
    if current is None:
        raise OfferNotPending("The offer no longer belongs to this request.")
    if actor.id not in (match.sender_id, match.traveler_id):
        raise OfferAuthorizationError("Only a party may accept this offer.")
    if current.proposer_id == actor.id:
        raise OfferAuthorizationError("The proposer cannot accept their own offer.")
    if current.status == Offer.Status.ACCEPTED:
        existing = Deal.objects.filter(accepted_offer=current).first()
        if existing is not None:
            return AcceptedDeal(deal=existing, created=False)
    if current.economics_version != Offer.EconomicsVersion.V1_EUR:
        raise LegacyContractNotSupported(
            "Use the legacy acceptance path for a legacy DZD offer."
        )
    if current.status != Offer.Status.PENDING:
        raise OfferNotPending("The offer is no longer pending.")
    if match.status != Match.Status.PENDING:
        raise MatchNotPending("The negotiation is no longer pending.")
    if (
        match.journey_id is None
        or match.start_leg_id is None
        or match.end_leg_id is None
    ):
        raise MatchLegRangeMissing("The V1 match has no covered journey-leg range.")

    if request_row.status != ParcelRequest.Status.OPEN:
        raise RequestAlreadyMatched(
            "The delivery request is already matched or closed."
        )
    # Boosts sit after offers and before journey in the canonical financial
    # lock graph. Paid economics are bound only after the Deal row exists.
    from apps.boosts.models import BoostPurchase  # noqa: WPS433

    request_boosts = tuple(
        BoostPurchase.objects.select_for_update(no_key=True)
        .filter(delivery_request_id=request_row.pk)
        .order_by("pk")
    )
    journey = (
        Journey.objects.select_for_update(no_key=True, of=("self",))
        .select_related("traveler")
        .get(pk=match.journey_id)
    )
    if journey.status != Journey.Status.ACTIVE:
        raise JourneyNotActive("The journey is no longer active.")

    locked_legs = _lock_journey_legs(journey)
    journey._matching_legs = locked_legs
    eligibility_at = timezone.now()
    _lock_acceptance_eligibility(
        delivery_request=request_row,
        journey=journey,
        legs=locked_legs,
        at=eligibility_at,
    )
    if (
        current.traveler_reward_minor is None
        or current.business_settings_version is None
    ):
        raise OfferEconomicsMissing(
            "The V1 offer has no valid economic settings snapshot."
        )
    offer_policy = Phase2Policy.from_settings(current.business_settings_version)
    if replay_provider is None:
        raise RoutePreflightMissing(
            "The pending offer has no route preflight snapshot."
        )
    policy, evaluation = _validate_evaluation(
        delivery_request=request_row,
        journey=journey,
        traveler_reward_eur_cents=current.traveler_reward_minor,
        expected_start_leg_id=match.start_leg_id,
        expected_end_leg_id=match.end_leg_id,
        policy=offer_policy,
        route_provider=replay_provider,
        at=eligibility_at,
    )
    legs = list(evaluation.compatibility.covered_legs)
    weight = getattr(request_row, "actual_weight_kg", None)
    if weight is None or weight <= 0:
        raise RequestWeightInvalid(
            "The delivery request has no valid V1 actual weight."
        )
    weight = Decimal(weight)
    reserved_by_leg = dict(
        DealLegAllocation.objects.active()
        .filter(
            journey_leg_id__in=[leg.id for leg in legs],
        )
        .values("journey_leg_id")
        .annotate(total=Sum("allocated_weight_kg"))
        .values_list("journey_leg_id", "total")
    )
    for leg in legs:
        reserved = reserved_by_leg.get(leg.id) or Decimal("0")
        if reserved + weight > leg.capacity_kg:
            raise CapacityExceeded(
                f"Journey leg {leg.id} no longer has enough capacity.",
                journey_leg_ids=[leg.id],
            )

    deal = Deal.objects.create(
        accepted_offer=current,
        match=match,
        delivery_request=request_row,
        journey=journey,
        sender_id=match.sender_id,
        traveler_id=match.traveler_id,
        status=Deal.Status.PAYMENT_REQUIRED,
    )
    from apps.boosts.services import bind_paid_boosts_to_deal  # noqa: WPS433

    boost_terms = bind_paid_boosts_to_deal(
        locked_purchases=request_boosts,
        deal=deal,
    )
    DealTermsSnapshot.objects.create(
        deal=deal,
        currency=current.currency,
        traveler_reward_minor=current.traveler_reward_minor,
        commission_rate_bps=current.commission_rate_bps,
        platform_fee_minor=current.platform_fee_minor,
        sender_total_minor=current.sender_total_minor,
        boost_amount_minor=boost_terms["amount_eur_cents"],
        boost_traveler_bonus_minor=boost_terms["traveler_boost_eur_cents"],
        boost_platform_fee_minor=boost_terms["platform_boost_eur_cents"],
        business_settings_version=current.business_settings_version,
        pricing_version=current.pricing_version,
        policy_snapshot={
            **current.terms_snapshot,
            "boost_economics": boost_terms,
        },
        is_legacy=False,
    )
    now = timezone.now()
    grace_seconds = current.terms_snapshot.get("reservation", {}).get(
        "payment_grace_seconds",
        policy.payment_grace_seconds,
    )
    if (
        isinstance(grace_seconds, bool)
        or not isinstance(grace_seconds, int)
        or grace_seconds <= 0
    ):
        raise InvalidReservationGrace(
            "The offer has an invalid reservation grace snapshot."
        )
    reservation_expires_at = now + timedelta(seconds=grace_seconds)
    DealLegAllocation.objects.bulk_create(
        [
            DealLegAllocation(
                deal=deal,
                journey_leg=leg,
                allocated_weight_kg=weight,
                status=DealLegAllocation.Status.PENDING_PAYMENT,
                expires_at=reservation_expires_at,
            )
            for leg in legs
        ]
    )
    DealEvent.objects.create(
        deal=deal,
        actor=actor,
        kind=DealEvent.Kind.CREATED,
        payload={"offer_id": current.id, "status": deal.status},
    )
    DealEvent.objects.create(
        deal=deal,
        actor=actor,
        kind=DealEvent.Kind.CAPACITY_RESERVED,
        payload={"leg_ids": [leg.id for leg in legs], "weight_kg": str(weight)},
    )

    # The Deal's balance obligation is created in the same transaction as the
    # Deal itself, so an accepted offer can never exist without something to
    # pay. Any eligible posting deposit is credited here and only here; the
    # credit link is one-to-one, so the same deposit cannot discount a second
    # balance. Imported lazily to keep `apps.matching` free of an import-time
    # dependency on the finance app.
    from apps.finance.models import ScheduledJob  # noqa: WPS433 (late import)
    from apps.finance.policy import phase3_policy  # noqa: WPS433
    from apps.finance.services import (  # noqa: WPS433
        create_deal_balance_order,
        schedule_job,
    )

    # Payment policy comes from the *currently active* revision, not the
    # offer's frozen one. The offer froze the agreed economics — reward, fee,
    # total — and those are what the order charges. Which rails exist, how the
    # deposit is priced and what the FX rate is are properties of the moment
    # the payment happens, so an offer negotiated under an older revision still
    # accepts cleanly after a policy change.
    payment_policy = phase3_policy()
    create_deal_balance_order(
        deal=deal,
        sender_total_eur_cents=int(current.sender_total_minor),
        policy=payment_policy,
    )
    # Durable companion to the reservation sweep: the release obligation exists
    # in the database from the moment capacity is reserved, so it survives a
    # process or Redis restart even if the sweep daemon is down.
    schedule_job(
        kind=ScheduledJob.Kind.PAYMENT_GRACE_RELEASE,
        key=f"payment_grace_release:deal:{deal.pk}",
        run_at=reservation_expires_at,
        payload={"deal_id": deal.pk},
    )

    current.status = Offer.Status.ACCEPTED
    current.responded_at = now
    current.save(update_fields=["status", "responded_at", "updated_at"])
    match.status = Match.Status.ACCEPTED
    match.save(update_fields=["status", "updated_at"])
    request_row.status = ParcelRequest.Status.MATCHED
    request_row.save(update_fields=["status", "updated_at"])
    MatchEvent.objects.create(
        match=match,
        offer=current,
        actor=actor,
        kind=MatchEvent.Kind.OFFER_ACCEPTED,
        payload={"deal_id": deal.id, "currency": current.currency},
    )

    competing_ids = [
        row.pk
        for row in request_matches
        if row.pk != match.pk and row.status == Match.Status.PENDING
    ]
    if competing_ids:
        Offer.objects.filter(
            match_id__in=competing_ids, status=Offer.Status.PENDING
        ).update(status=Offer.Status.EXPIRED, responded_at=now)
        Match.objects.filter(pk__in=competing_ids).update(status=Match.Status.EXPIRED)

    return AcceptedDeal(deal=deal, created=True)
