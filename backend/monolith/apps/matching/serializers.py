"""Matching serializers — read + create/counter/accept/decline.

Keep create-side serializers thin; the views own the state-machine + Redis
publish logic. These just validate shape.
"""

from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist
from rest_framework import serializers

from apps.parcels.models import ParcelRequest

from .models import Match, MatchEvent, Offer
from .public_contract import public_compatibility_payload, public_terms_snapshot


#: Legacy DZD economics columns. They are structural NOT NULL zeroes on a V1
#: EUR offer and would read as a real DZD price to any client that still speaks
#: DZD, so they are dropped from a V1 offer's representation entirely. Legacy
#: offers keep them; admin and the database keep them in every case.
LEGACY_DZD_FIELDS = (
    "base_amount_dzd",
    "base_fee_dzd",
    "commission_dzd",
    "total_dzd",
)


def allowed_offer_actions(offer: Offer, match: Match, *, user_id: int | None) -> list:
    """Server-declared negotiation actions for one caller.

    This is UX guidance so a client never re-derives the state machine from
    (my id, proposer id, offer status, match status, request status). It is not
    an authorization decision: every mutation re-checks the same rules under
    row locks and still fails transactionally on stale state.
    """

    if user_id is None:
        return []
    if match.parcel.kind == ParcelRequest.Kind.PRODUCT:
        return []
    if user_id not in (match.sender_id, match.traveler_id):
        return []
    if offer.status != Offer.Status.PENDING or match.status != Match.Status.PENDING:
        return []
    if offer.proposer_id == user_id:
        return ["withdraw"]
    actions = []
    is_v1 = offer.economics_version == Offer.EconomicsVersion.V1_EUR
    if is_v1 and match.parcel.status == ParcelRequest.Status.OPEN:
        actions.append("accept")
    if is_v1:
        actions.append("counter")
    actions.append("decline")
    return actions


def awaiting_party(offer: Offer, match: Match) -> tuple[str | None, int | None]:
    if offer.status != Offer.Status.PENDING or match.status != Match.Status.PENDING:
        return None, None
    if offer.proposed_by == Offer.ProposedBy.SENDER:
        return "traveler", match.traveler_id
    return "sender", match.sender_id


class OfferSerializer(serializers.ModelSerializer):
    proposer_id = serializers.IntegerField(read_only=True)
    terms_snapshot = serializers.SerializerMethodField()
    awaiting_party = serializers.SerializerMethodField()
    awaiting_user_id = serializers.SerializerMethodField()
    allowed_actions = serializers.SerializerMethodField()

    class Meta:
        model = Offer
        fields = (
            "id",
            "match",
            "parent_offer",
            "proposed_by",
            "proposer_id",
            "base_amount_dzd",
            "base_fee_dzd",
            "commission_dzd",
            "total_dzd",
            "economics_version",
            "currency",
            "traveler_reward_minor",
            "commission_rate_bps",
            "platform_fee_minor",
            "sender_total_minor",
            "pricing_version",
            "business_settings_version_id",
            "terms_snapshot",
            "status",
            "note",
            "expires_at",
            "responded_at",
            "awaiting_party",
            "awaiting_user_id",
            "allowed_actions",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def _match(self, obj: Offer) -> Match:
        return self.context.get("match") or obj.match

    def _user_id(self) -> int | None:
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return None
        return request.user.id

    def get_terms_snapshot(self, obj: Offer) -> dict | None:
        # The stored snapshot keeps the whole business policy, the ranking
        # factors and the internal compatibility geometry for audit. A party
        # receives only the agreed economic terms.
        return public_terms_snapshot(obj.terms_snapshot)

    def get_awaiting_party(self, obj: Offer) -> str | None:
        return awaiting_party(obj, self._match(obj))[0]

    def get_awaiting_user_id(self, obj: Offer) -> int | None:
        return awaiting_party(obj, self._match(obj))[1]

    def get_allowed_actions(self, obj: Offer) -> list:
        return allowed_offer_actions(obj, self._match(obj), user_id=self._user_id())

    def to_representation(self, instance: Offer) -> dict:
        data = super().to_representation(instance)
        if instance.economics_version == Offer.EconomicsVersion.V1_EUR:
            for field in LEGACY_DZD_FIELDS:
                data.pop(field, None)
        return data


class MatchEventSerializer(serializers.ModelSerializer):
    actor_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = MatchEvent
        fields = ("id", "kind", "actor_id", "offer", "payload", "created_at")
        read_only_fields = fields


class _MatchParcelMini(serializers.Serializer):
    """Compact parcel snapshot embedded in MatchSerializer so list/detail
    consumers don't need a second fetch to render route + weight + kind."""

    id = serializers.IntegerField()
    kind = serializers.CharField()
    weight_kg = serializers.IntegerField(allow_null=True)
    actual_weight_kg = serializers.SerializerMethodField()
    target_traveler_id = serializers.IntegerField(allow_null=True)
    origin = serializers.SerializerMethodField()
    destination = serializers.SerializerMethodField()

    def get_origin(self, obj) -> dict:
        from apps.locations.serializers import PublicLocationSerializer
        from apps.trips.serializers import AirportSerializer

        delivery = getattr(obj, "deliveryrequest", None)
        if delivery is not None and delivery.pickup_location_id:
            return PublicLocationSerializer(delivery.pickup_location).data
        return AirportSerializer(obj.origin).data if obj.origin_id else {}

    def get_destination(self, obj) -> dict:
        from apps.locations.serializers import PublicLocationSerializer
        from apps.trips.serializers import AirportSerializer

        delivery = getattr(obj, "deliveryrequest", None)
        if delivery is not None and delivery.delivery_location_id:
            return PublicLocationSerializer(delivery.delivery_location).data
        return AirportSerializer(obj.destination).data if obj.destination_id else {}

    def get_actual_weight_kg(self, obj) -> str | None:
        delivery = getattr(obj, "deliveryrequest", None)
        if delivery is None or delivery.actual_weight_kg is None:
            return None
        return str(delivery.actual_weight_kg)


class MatchSerializer(serializers.ModelSerializer):
    sender_id = serializers.IntegerField(read_only=True)
    traveler_id = serializers.IntegerField(read_only=True)
    sender_name = serializers.SerializerMethodField()
    traveler_name = serializers.SerializerMethodField()
    parcel_id = serializers.IntegerField(read_only=True)
    trip_id = serializers.IntegerField(read_only=True)
    journey_id = serializers.IntegerField(read_only=True)
    start_leg_id = serializers.IntegerField(read_only=True)
    end_leg_id = serializers.IntegerField(read_only=True)
    deal_id = serializers.SerializerMethodField()

    parcel = _MatchParcelMini(read_only=True)
    latest_offer = serializers.SerializerMethodField()
    accepted_offer = serializers.SerializerMethodField()
    compatibility_snapshot = serializers.SerializerMethodField()
    matched_distance_band = serializers.SerializerMethodField()

    class Meta:
        model = Match
        fields = (
            "id",
            "parcel_id",
            "trip_id",
            "journey_id",
            "start_leg_id",
            "end_leg_id",
            "deal_id",
            "sender_id",
            "traveler_id",
            "sender_name",
            "traveler_name",
            "status",
            "matching_version",
            "matched_distance_band",
            "compatibility_snapshot",
            "parcel",
            "latest_offer",
            "accepted_offer",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_compatibility_snapshot(self, obj: Match) -> dict | None:
        # The persisted snapshot is the internal form; a party sees only the
        # pre-funding projection of it.
        return public_compatibility_payload(obj.compatibility_snapshot)

    def get_matched_distance_band(self, obj: Match) -> dict | None:
        # The exact carried distance is measured from the private endpoint on a
        # partial leg, so only its pricing band is published.
        from .public_contract import distance_band

        return distance_band(obj.matched_distance_meters)

    def get_sender_name(self, obj: Match) -> str:
        return obj.sender.full_name

    def get_traveler_name(self, obj: Match) -> str:
        return obj.traveler.full_name

    def get_deal_id(self, obj: Match) -> int | None:
        try:
            return obj.deal.id
        except ObjectDoesNotExist:
            return None

    def _offer_context(self, obj: Match) -> dict:
        # Reuse the already-loaded Match so the nested offer never re-queries
        # it just to compute allowed_actions.
        return {**self.context, "match": obj}

    def get_latest_offer(self, obj: Match) -> dict | None:
        offers = getattr(obj, "_ordered_offers", None)
        offer = offers[0] if offers else None
        if offers is None:
            offer = obj.offers.order_by("-created_at").first()
        if offer is None:
            return None
        return OfferSerializer(offer, context=self._offer_context(obj)).data

    def get_accepted_offer(self, obj: Match) -> dict | None:
        offers = getattr(obj, "_ordered_offers", None)
        offer = (
            next(
                (row for row in offers if row.status == Offer.Status.ACCEPTED),
                None,
            )
            if offers is not None
            else obj.offers.filter(status=Offer.Status.ACCEPTED).first()
        )
        if offer is None:
            return None
        return OfferSerializer(offer, context=self._offer_context(obj)).data


class TravelerApplySerializer(serializers.Serializer):
    """Traveler applies to carry a sender's parcel.

    Creates Match + first Offer in one POST. The offer's pricing is computed
    server-side from `apps.core.pricing` based on the parcel kind. The
    traveler may override `base_amount_dzd` (their asking price for delivery,
    or the price they'll pay at the store for product) within validation
    bounds — defaults to the sender's posted intent.
    """

    parcel_id = serializers.IntegerField()
    trip_id = serializers.IntegerField()
    base_amount_dzd = serializers.IntegerField(required=False, min_value=100)
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class SenderApplySerializer(serializers.Serializer):
    """Sender applies an existing parcel to one specific traveler's trip.

    Mirrors `TravelerApplySerializer`; the difference is who proposes. The
    parcel already exists, so the sender re-enters nothing — they only
    optionally restate their price for this particular trip.
    """

    parcel_id = serializers.IntegerField()
    trip_id = serializers.IntegerField()
    base_amount_dzd = serializers.IntegerField(required=False, min_value=100)
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class CounterOfferSerializer(serializers.Serializer):
    """Counter the current pending offer with a new amount."""

    base_amount_dzd = serializers.IntegerField(min_value=100)
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class SenderProposeV1Serializer(serializers.Serializer):
    parcel_id = serializers.IntegerField()
    journey_id = serializers.IntegerField()
    start_leg_id = serializers.IntegerField()
    end_leg_id = serializers.IntegerField()
    traveler_reward_eur_cents = serializers.IntegerField(
        min_value=1, max_value=100_000_000
    )
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class CounterOfferV1Serializer(serializers.Serializer):
    traveler_reward_eur_cents = serializers.IntegerField(
        min_value=1, max_value=100_000_000
    )
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class PricingQuoteV1Serializer(serializers.Serializer):
    parcel_id = serializers.IntegerField(min_value=1)
    journey_id = serializers.IntegerField(min_value=1)


class CompatibleJourneysQuerySerializer(serializers.Serializer):
    parcel_id = serializers.IntegerField(min_value=1)


class CompatibleRequestsQuerySerializer(serializers.Serializer):
    journey_id = serializers.IntegerField(min_value=1)


class CandidateExplanationQuerySerializer(serializers.Serializer):
    parcel_id = serializers.IntegerField(min_value=1)
    journey_id = serializers.IntegerField(min_value=1)
