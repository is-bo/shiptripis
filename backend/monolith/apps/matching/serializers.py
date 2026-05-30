"""Matching serializers — read + create/counter/accept/decline.

Keep create-side serializers thin; the views own the state-machine + Redis
publish logic. These just validate shape.
"""

from __future__ import annotations

from rest_framework import serializers

from .models import Match, MatchEvent, Offer


class OfferSerializer(serializers.ModelSerializer):
    proposer_id = serializers.IntegerField(read_only=True)

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
            "status",
            "note",
            "expires_at",
            "responded_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


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
    weight_kg = serializers.IntegerField()
    target_traveler_id = serializers.IntegerField(allow_null=True)
    origin = serializers.SerializerMethodField()
    destination = serializers.SerializerMethodField()

    def get_origin(self, obj) -> dict:
        from apps.trips.serializers import AirportSerializer
        return AirportSerializer(obj.origin).data

    def get_destination(self, obj) -> dict:
        from apps.trips.serializers import AirportSerializer
        return AirportSerializer(obj.destination).data


class MatchSerializer(serializers.ModelSerializer):
    sender_id = serializers.IntegerField(read_only=True)
    traveler_id = serializers.IntegerField(read_only=True)
    parcel_id = serializers.IntegerField(read_only=True)
    trip_id = serializers.IntegerField(read_only=True)

    parcel = _MatchParcelMini(read_only=True)
    latest_offer = serializers.SerializerMethodField()
    accepted_offer = serializers.SerializerMethodField()

    class Meta:
        model = Match
        fields = (
            "id",
            "parcel_id",
            "trip_id",
            "sender_id",
            "traveler_id",
            "status",
            "parcel",
            "latest_offer",
            "accepted_offer",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_latest_offer(self, obj: Match) -> dict | None:
        offer = obj.offers.order_by("-created_at").first()
        return OfferSerializer(offer).data if offer else None

    def get_accepted_offer(self, obj: Match) -> dict | None:
        offer = obj.offers.filter(status=Offer.Status.ACCEPTED).first()
        return OfferSerializer(offer).data if offer else None


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


class CounterOfferSerializer(serializers.Serializer):
    """Counter the current pending offer with a new amount."""

    base_amount_dzd = serializers.IntegerField(min_value=100)
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000)
