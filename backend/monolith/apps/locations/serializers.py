from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from django.db import IntegrityError, transaction
from rest_framework import serializers

from apps.trips.models import Airport

from .models import Location


class PublicLocationSerializer(serializers.ModelSerializer):
    """Coarse representation safe for any authenticated caller."""

    airport = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Location
        fields = (
            "id",
            "kind",
            "public_label",
            "city",
            "region",
            "country_code",
            "coarse_latitude",
            "coarse_longitude",
            "precision",
            "coordinates_trusted",
            "coordinate_dataset_version",
            "airport",
            "created_at",
        )
        read_only_fields = fields


class PrivateLocationSerializer(serializers.ModelSerializer):
    """Create/owner representation containing exact and provider fields."""

    country_code = serializers.CharField(min_length=2, max_length=2)
    airport = serializers.PrimaryKeyRelatedField(
        queryset=Airport.objects.all(),
        required=False,
        allow_null=True,
    )
    created_by_id = serializers.IntegerField(read_only=True)
    owner_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Location
        fields = (
            "id",
            "kind",
            "normalized_label",
            "public_label",
            "private_label",
            "city",
            "region",
            "country_code",
            "latitude",
            "longitude",
            "coarse_latitude",
            "coarse_longitude",
            "provider",
            "source",
            "provider_place_id",
            "provider_metadata",
            "precision",
            "airport",
            "created_by_id",
            "owner_id",
            "created_at",
            "updated_at",
            "coordinates_trusted",
            "coordinate_dataset_version",
        )
        read_only_fields = (
            "id",
            "public_label",
            "coarse_latitude",
            "coarse_longitude",
            "created_by_id",
            "owner_id",
            "created_at",
            "updated_at",
            "coordinates_trusted",
            "coordinate_dataset_version",
        )
        # The conditional database UniqueConstraint is mirrored below so the
        # API returns a field-specific error instead of a generic one.
        validators = []

    def validate_country_code(self, value: str) -> str:
        country_code = value.upper()
        if not country_code.isascii() or not country_code.isalpha():
            raise serializers.ValidationError("Use an ISO 3166-1 alpha-2 country code.")
        return country_code

    def validate_provider_metadata(self, value: object) -> dict:
        if not isinstance(value, dict):
            raise serializers.ValidationError("Must be a JSON object.")
        return value

    def validate(self, attrs: dict) -> dict:
        server_derived_fields = {
            "public_label",
            "coarse_latitude",
            "coarse_longitude",
        }
        supplied_derived = server_derived_fields.intersection(self.initial_data)
        if supplied_derived:
            raise serializers.ValidationError(
                {
                    field: "This privacy-safe value is derived by the server."
                    for field in sorted(supplied_derived)
                }
            )

        identity_fields = {"created_by", "created_by_id", "owner", "owner_id"}
        supplied_identity = identity_fields.intersection(self.initial_data)
        if supplied_identity:
            raise serializers.ValidationError(
                {
                    field: "This identity is assigned by the server."
                    for field in sorted(supplied_identity)
                }
            )

        provider = attrs.get("provider", "")
        provider_place_id = attrs.get("provider_place_id", "")
        if provider_place_id and not provider:
            raise serializers.ValidationError(
                {"provider": "Required when provider_place_id is set."}
            )
        if provider and provider_place_id:
            request = self.context.get("request")
            owner = self.instance.owner if self.instance is not None else None
            if request is not None and request.user.is_authenticated:
                owner = request.user
            duplicate = Location.objects.filter(
                owner=owner,
                provider=provider,
                provider_place_id=provider_place_id,
            )
            if self.instance is not None:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                raise serializers.ValidationError(
                    {
                        "provider_place_id": (
                            "This provider place already has a Location record."
                        )
                    }
                )

        airport = attrs.get("airport")
        if airport is not None and attrs.get("kind") != Location.Kind.AIRPORT:
            raise serializers.ValidationError(
                {"airport": "An Airport link is valid only for airport locations."}
            )
        return attrs

    def create(self, validated_data: dict) -> Location:
        country_code = validated_data["country_code"]
        airport = validated_data.get("airport")
        city = airport.city if airport is not None else validated_data["city"]
        validated_data["public_label"] = f"{city}, {country_code}"
        # One decimal degree is deliberately city-level (roughly 11 km in
        # latitude) and cannot be tightened by an API caller.
        quantum = Decimal("0.1")
        validated_data["coarse_latitude"] = validated_data["latitude"].quantize(
            quantum, rounding=ROUND_HALF_UP
        )
        validated_data["coarse_longitude"] = validated_data["longitude"].quantize(
            quantum, rounding=ROUND_HALF_UP
        )
        try:
            with transaction.atomic():
                return super().create(validated_data)
        except IntegrityError:
            provider = validated_data.get("provider", "")
            provider_place_id = validated_data.get("provider_place_id", "")
            owner = validated_data.get("owner")
            if (
                provider
                and provider_place_id
                and Location.objects.filter(
                    owner=owner,
                    provider=provider,
                    provider_place_id=provider_place_id,
                ).exists()
            ):
                raise serializers.ValidationError(
                    {
                        "provider_place_id": (
                            "This provider place already has a Location record."
                        )
                    }
                ) from None
            raise


def serialize_location_for_user(location: Location, user) -> dict:
    """Choose visibility per object, including for mixed-owner list results."""

    serializer_class = (
        PrivateLocationSerializer
        if user.is_authenticated and location.owner_id == user.id
        else PublicLocationSerializer
    )
    return serializer_class(location).data
