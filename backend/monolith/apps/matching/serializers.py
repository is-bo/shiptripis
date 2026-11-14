"""Matching serializers — read + create/counter/accept/decline.

Keep create-side serializers thin; the views own the state-machine + Redis
publish logic. These just validate shape.
"""

from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from rest_framework import serializers

from apps.parcels.models import ParcelRequest
from apps.parcels import tracking

from .find_travelers import DEFAULT_PAGE_SIZE, SORT_BEST_MATCH, SORT_VALUES
from .models import Match, Offer
from .offer_deadlines import deadline_passed, effective_status
from .offer_economics import OfferEconomicsReader
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
    if deadline_passed(offer, at=timezone.now()):
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


def offer_economics_reader(context: dict) -> OfferEconomicsReader:
    """The one reader a whole response shares, created on first use."""

    reader = context.get("offer_economics")
    if reader is None:
        reader = OfferEconomicsReader()
        context["offer_economics"] = reader
    return reader


def awaiting_party(offer: Offer, match: Match) -> tuple[str | None, int | None]:
    if offer.status != Offer.Status.PENDING or match.status != Match.Status.PENDING:
        return None, None
    if deadline_passed(offer, at=timezone.now()):
        return None, None
    if offer.proposed_by == Offer.ProposedBy.SENDER:
        return "traveler", match.traveler_id
    return "sender", match.sender_id


class OfferSerializer(serializers.ModelSerializer):
    proposer_id = serializers.IntegerField(read_only=True)
    tracking_number = serializers.SerializerMethodField()
    terms_snapshot = serializers.SerializerMethodField()
    awaiting_party = serializers.SerializerMethodField()
    awaiting_user_id = serializers.SerializerMethodField()
    allowed_actions = serializers.SerializerMethodField()

    class Meta:
        model = Offer
        fields = (
            "id",
            "match",
            "tracking_number",
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

    def get_tracking_number(self, obj: Offer) -> str:
        # Only the two people of the proposal ever receive an offer.
        return tracking.for_request(self._match(obj).parcel)

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
        # L12A: from the deadline on the offer reads as expired, even in the
        # moment before the expiry job stores it (spec 17.1).
        data["status"] = effective_status(instance, at=timezone.now())
        if instance.economics_version == Offer.EconomicsVersion.V1_EUR:
            for field in LEGACY_DZD_FIELDS:
                data.pop(field, None)
        # J6.1. `traveler_reward_minor` and `sender_total_minor` stay exactly
        # what they were -- the base economics frozen on this row. The Boost
        # and the totals that include it are added beside them, under the
        # names `DealTermsSnapshot` already uses. See `offer_economics`.
        data.update(
            offer_economics_reader(self.context).project(
                instance, self._match(instance)
            )
        )
        return data


class OfferListSerializer(OfferSerializer):
    """An offer as nested in a Match *list* row (K7 D).

    Everything a card or a negotiation button reads, without `terms_snapshot`:
    about 2.9 KB per offer of frozen pricing and a second copy of the Match's
    compatibility, which no list consumer reads. The Match detail, the offer
    chain and every mutation response keep the full `OfferSerializer`.
    """

    terms_snapshot = None

    class Meta(OfferSerializer.Meta):
        fields = tuple(
            field for field in OfferSerializer.Meta.fields if field != "terms_snapshot"
        )
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
        if delivery is not None and delivery.pickup_place_id:
            place = delivery.pickup_place
            return {
                "id": place.pk,
                "name": place.name,
                "display_label": place.display_label,
                "place_type": place.place_type,
                "country_code": place.country_id,
                "iata_code": place.iata_code or None,
            }
        return AirportSerializer(obj.origin).data if obj.origin_id else {}

    def get_destination(self, obj) -> dict:
        from apps.locations.serializers import PublicLocationSerializer
        from apps.trips.serializers import AirportSerializer

        delivery = getattr(obj, "deliveryrequest", None)
        if delivery is not None and delivery.delivery_location_id:
            return PublicLocationSerializer(delivery.delivery_location).data
        if delivery is not None and delivery.delivery_place_id:
            place = delivery.delivery_place
            return {
                "id": place.pk,
                "name": place.name,
                "display_label": place.display_label,
                "place_type": place.place_type,
                "country_code": place.country_id,
                "iata_code": place.iata_code or None,
            }
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
    tracking_number = serializers.SerializerMethodField()

    parcel = _MatchParcelMini(read_only=True)
    latest_offer = serializers.SerializerMethodField()
    accepted_offer = serializers.SerializerMethodField()
    compatibility_snapshot = serializers.SerializerMethodField()
    matched_distance_band = serializers.SerializerMethodField()

    #: The nested offer shape; the list projection swaps in a lighter one.
    offer_serializer_class = OfferSerializer

    class Meta:
        model = Match
        fields = (
            "id",
            "tracking_number",
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

    def get_tracking_number(self, obj: Match) -> str:
        # A match exists only once the sender has proposed: both people of
        # the proposal may see the number.
        return tracking.for_request(obj.parcel)

    def get_deal_id(self, obj: Match) -> int | None:
        try:
            return obj.deal.id
        except ObjectDoesNotExist:
            return None

    def _offer_context(self, obj: Match) -> dict:
        # Reuse the already-loaded Match so the nested offer never re-queries
        # it just to compute allowed_actions. The economics reader is created
        # on this serializer's own context first, so every row of a list
        # shares one reader rather than each nested offer starting a new one.
        offer_economics_reader(self.context)
        return {**self.context, "match": obj}

    def get_latest_offer(self, obj: Match) -> dict | None:
        offers = getattr(obj, "_ordered_offers", None)
        offer = offers[0] if offers else None
        if offers is None:
            offer = obj.offers.order_by("-created_at").first()
        if offer is None:
            return None
        return self.offer_serializer_class(
            offer, context=self._offer_context(obj)
        ).data

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
        return self.offer_serializer_class(
            offer, context=self._offer_context(obj)
        ).data


class MatchListSerializer(MatchSerializer):
    """The Offers-list projection of a Match (K7 D), as K4 did for Journeys.

    Drops `compatibility_snapshot` and each nested offer's `terms_snapshot`,
    about three quarters of a row. No list consumer reads either: the app's
    list cards and negotiation buttons read names, status, parcel route,
    distance band, the offer economics and `allowed_actions`, all kept
    unchanged. `GET /api/matches/<id>` still returns the full serializer.
    """

    compatibility_snapshot = None
    offer_serializer_class = OfferListSerializer

    class Meta(MatchSerializer.Meta):
        fields = tuple(
            field
            for field in MatchSerializer.Meta.fields
            if field != "compatibility_snapshot"
        )
        read_only_fields = fields


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


class OfferAcceptV1Serializer(serializers.Serializer):
    """The totals the acceptor was shown. J6.1; see `OfferEconomicsConfirmation`."""

    traveler_total_minor = serializers.IntegerField(
        min_value=0, required=False, allow_null=True
    )
    sender_total_with_boost_minor = serializers.IntegerField(
        min_value=0, required=False, allow_null=True
    )


class PricingQuoteV1Serializer(serializers.Serializer):
    parcel_id = serializers.IntegerField(min_value=1)
    journey_id = serializers.IntegerField(min_value=1)


class FindTravelersQuerySerializer(serializers.Serializer):
    """Query contract for the J4 Find Travelers page.

    `limit` is capped by the view against the active policy's `result_limit`,
    which is the size of the authoritative result set; this serializer only
    holds the outer edge so an absurd value is refused before it reaches a
    slice. `sort` is a closed vocabulary because the client must never be able
    to name an order ShipTrip does not own.
    """

    parcel_id = serializers.IntegerField(min_value=1)
    limit = serializers.IntegerField(
        min_value=1, max_value=100, required=False, default=DEFAULT_PAGE_SIZE
    )
    offset = serializers.IntegerField(min_value=0, required=False, default=0)
    sort = serializers.ChoiceField(
        choices=SORT_VALUES, required=False, default=SORT_BEST_MATCH
    )


class CompatibleRequestsQuerySerializer(serializers.Serializer):
    journey_id = serializers.IntegerField(min_value=1)


class CandidateExplanationQuerySerializer(serializers.Serializer):
    parcel_id = serializers.IntegerField(min_value=1)
    journey_id = serializers.IntegerField(min_value=1)
