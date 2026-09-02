from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from django.db import IntegrityError, transaction
from rest_framework import serializers

from apps.routing.geometry import GeoPoint, haversine_meters
from apps.routing.providers import RouteProviderError, get_route_provider
from apps.trips.models import Airport

from .geography import normalize_search_name
from .models import Location, Place, PlaceAlternateName


def _metadata_values(metadata: dict, *keys: str) -> list[str]:
    """Return non-empty provider context values from common flat/nested shapes."""

    containers = [metadata]
    for nested_key in ("address", "context", "properties"):
        nested = metadata.get(nested_key)
        if isinstance(nested, dict):
            containers.append(nested)
    values: list[str] = []
    for container in containers:
        for key in keys:
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                values.append(value.strip())
    return values


def _validate_provider_context(
    *, canonical_place: Place, metadata: dict, point: GeoPoint
) -> None:
    country_values = _metadata_values(
        metadata,
        "country_code",
        "countryCode",
        "iso_country_code",
        "country",
    )
    expected_country_values = {
        canonical_place.country_id.casefold(),
        normalize_search_name(canonical_place.country.name),
    }
    normalized_countries = {
        value.casefold() if len(value) == 2 else normalize_search_name(value)
        for value in country_values
    }
    if not country_values or expected_country_values.isdisjoint(normalized_countries):
        raise serializers.ValidationError(
            {
                "canonical_place": (
                    "The map provider could not confirm that this point is in the "
                    "selected country. Choose another point or continue without one."
                )
            }
        )

    if canonical_place.place_type == Place.PlaceType.AIRPORT:
        if canonical_place.latitude is None or canonical_place.longitude is None:
            raise serializers.ValidationError(
                {
                    "canonical_place": (
                        "This airport cannot validate a preferred point yet. "
                        "Continue without one."
                    )
                }
            )
        airport_point = GeoPoint(
            float(canonical_place.latitude),
            float(canonical_place.longitude),
        )
        # This generous operational-area check validates a meeting pin only;
        # it is never used for route compatibility or nearby-city matching.
        if haversine_meters(point, airport_point) > 50_000:
            raise serializers.ValidationError(
                {
                    "canonical_place": (
                        "The preferred point is too far from the selected airport."
                    )
                }
            )
        return

    locality_values = _metadata_values(
        metadata,
        "locality",
        "city",
        "municipality",
        "commune",
        "town",
        "village",
    )
    if not locality_values:
        raise serializers.ValidationError(
            {
                "canonical_place": (
                    "The map provider could not confirm the locality for this point. "
                    "Choose another point or continue without one."
                )
            }
        )
    expected_names = {canonical_place.normalized_name}
    expected_names.update(
        PlaceAlternateName.objects.filter(
            place=canonical_place,
            active=True,
        ).values_list("normalized_name", flat=True)
    )
    provider_names = {normalize_search_name(value) for value in locality_values}
    if expected_names.isdisjoint(provider_names):
        raise serializers.ValidationError(
            {
                "canonical_place": (
                    "The preferred point belongs to a different locality than the "
                    "selected place."
                )
            }
        )


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
    canonical_place = serializers.PrimaryKeyRelatedField(
        queryset=Place.objects.filter(active=True),
        required=True,
        allow_null=False,
    )
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
            "canonical_place",
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
        canonical_place = attrs.get("canonical_place")
        if canonical_place is not None:
            if canonical_place.place_type not in {
                Place.PlaceType.LOCALITY,
                Place.PlaceType.AIRPORT,
            }:
                raise serializers.ValidationError(
                    {
                        "canonical_place": "Preferred points require a locality or airport."
                    }
                )
            if canonical_place.country_id != attrs.get("country_code", "").upper():
                raise serializers.ValidationError(
                    {
                        "canonical_place": "Preferred point country must match the selected place."
                    }
                )
            point = GeoPoint(float(attrs["latitude"]), float(attrs["longitude"]))
            provider = get_route_provider(external_call_budget=1)
            try:
                result = provider.reverse_geocode(point)
            except RouteProviderError as exc:
                raise serializers.ValidationError(
                    {
                        "canonical_place": (
                            "The map provider could not validate this preferred point. "
                            "Choose another point or continue without one."
                        )
                    }
                ) from exc
            _validate_provider_context(
                canonical_place=canonical_place,
                metadata=result.metadata,
                point=result.point,
            )
            # Provider identity and context are server-derived for canonical
            # preferred points; client-supplied metadata is never trusted.
            attrs["normalized_label"] = result.normalized_label
            attrs["provider"] = provider.name
            attrs["provider_place_id"] = result.provider_place_id
            attrs["provider_metadata"] = result.metadata
            attrs["source"] = "reverse_geocoder"
            if result.precision in Location.Precision.values:
                attrs["precision"] = result.precision
        return attrs

    def create(self, validated_data: dict) -> Location:
        country_code = validated_data["country_code"]
        airport = validated_data.get("airport")
        canonical_place = validated_data.get("canonical_place")
        city = (
            airport.city
            if airport is not None
            else canonical_place.name
            if canonical_place is not None
            else validated_data["city"]
        )
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
