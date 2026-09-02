from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.locations.models import Location, Place
from apps.locations.serializers import PublicLocationSerializer
from apps.matching.public_contract import distance_band
from apps.routing.geometry import GeoPoint
from apps.routing.providers import RouteProviderError, get_route_provider

from .models import (
    Airport,
    Journey,
    JourneyLeg,
    JourneyLegProof,
    Trip,
    TripStopover,
)


class AirportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Airport
        fields = ("iata", "city", "name", "country")
        read_only_fields = fields


class StopoverInputSerializer(serializers.Serializer):
    airport = serializers.CharField(min_length=3, max_length=3)
    arrives_at = serializers.DateTimeField(required=False, allow_null=True)
    departs_at = serializers.DateTimeField(required=False, allow_null=True)


class StopoverOutputSerializer(serializers.ModelSerializer):
    airport = AirportSerializer(read_only=True)

    class Meta:
        model = TripStopover
        fields = ("id", "position", "airport", "arrives_at", "departs_at")
        read_only_fields = fields


class TripCreateSerializer(serializers.Serializer):
    origin = serializers.CharField(min_length=3, max_length=3)
    destination = serializers.CharField(min_length=3, max_length=3)
    departure_at = serializers.DateTimeField()
    capacity_kg = serializers.IntegerField(min_value=1, max_value=200)
    flight_number = serializers.CharField(
        required=False, allow_blank=True, max_length=12, default=""
    )
    notes = serializers.CharField(
        required=False, allow_blank=True, max_length=2000, default=""
    )
    stopovers = StopoverInputSerializer(many=True, required=False, default=list)

    def validate(self, attrs: dict) -> dict:
        if attrs["origin"].upper() == attrs["destination"].upper():
            raise serializers.ValidationError(
                {"destination": "Origin and destination must differ."}
            )
        if attrs["departure_at"] <= timezone.now():
            raise serializers.ValidationError(
                {"departure_at": "Departure must be in the future."}
            )
        # Validate every IATA exists.
        codes = {attrs["origin"].upper(), attrs["destination"].upper()}
        for s in attrs.get("stopovers", []):
            codes.add(s["airport"].upper())
        known = set(
            Airport.objects.filter(iata__in=codes).values_list("iata", flat=True)
        )
        missing = codes - known
        if missing:
            raise serializers.ValidationError(
                {"airports": f"Unknown IATA code(s): {', '.join(sorted(missing))}"}
            )
        attrs["origin"] = attrs["origin"].upper()
        attrs["destination"] = attrs["destination"].upper()
        return attrs


class TripSerializer(serializers.ModelSerializer):
    origin = AirportSerializer(read_only=True)
    destination = AirportSerializer(read_only=True)
    stopovers = StopoverOutputSerializer(many=True, read_only=True)
    traveler_id = serializers.IntegerField(source="traveler.id", read_only=True)
    traveler_name = serializers.CharField(source="traveler.full_name", read_only=True)

    class Meta:
        model = Trip
        fields = (
            "id",
            "traveler_id",
            "traveler_name",
            "origin",
            "destination",
            "departure_at",
            "capacity_kg",
            "flight_number",
            "notes",
            "status",
            "stopovers",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class JourneyLegInputSerializer(serializers.Serializer):
    position = serializers.IntegerField(min_value=0, required=False)
    mode = serializers.ChoiceField(choices=JourneyLeg.Mode.choices)
    origin_place_id = serializers.PrimaryKeyRelatedField(
        source="origin_place",
        queryset=Place.objects.filter(active=True),
        required=True,
        allow_null=False,
    )
    destination_place_id = serializers.PrimaryKeyRelatedField(
        source="destination_place",
        queryset=Place.objects.filter(active=True),
        required=True,
        allow_null=False,
    )
    origin = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), required=False, allow_null=True
    )
    destination = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), required=False, allow_null=True
    )
    depart_at = serializers.DateTimeField()
    arrive_at = serializers.DateTimeField(required=False, allow_null=True)
    capacity_kg = serializers.DecimalField(
        max_digits=8,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )
    flight_number = serializers.CharField(
        max_length=16, required=False, allow_blank=True, default=""
    )
    departure_airport_metadata = serializers.JSONField(required=False, default=dict)
    arrival_airport_metadata = serializers.JSONField(required=False, default=dict)

    def validate(self, attrs: dict) -> dict:
        server_route_fields = {
            "distance_meters",
            "route_duration_seconds",
            "route_polyline",
            "route_provider",
            "route_profile",
            "route_captured_at",
            "allowed_detour_meters",
            "route_metadata",
        }
        supplied = server_route_fields.intersection(getattr(self, "initial_data", {}))
        if supplied:
            raise serializers.ValidationError(
                {
                    field: "Route snapshots are calculated and assigned by the server."
                    for field in sorted(supplied)
                }
            )
        origin_place = attrs["origin_place"]
        destination_place = attrs["destination_place"]
        for field, place in (
            ("origin_place_id", origin_place),
            ("destination_place_id", destination_place),
        ):
            if place.place_type not in {
                Place.PlaceType.LOCALITY,
                Place.PlaceType.AIRPORT,
            }:
                raise serializers.ValidationError(
                    {field: "Choose a locality or airport."}
                )
            if place.resolve_matching_locality() is None:
                raise serializers.ValidationError(
                    {field: "This place is temporarily unavailable for matching."}
                )
        if origin_place.pk == destination_place.pk:
            raise serializers.ValidationError(
                {"destination_place_id": "Leg endpoints must differ."}
            )
        arrive_at = attrs.get("arrive_at")
        if arrive_at is not None and arrive_at <= attrs["depart_at"]:
            raise serializers.ValidationError(
                {"arrive_at": "Arrival must be after departure."}
            )
        if attrs["mode"] == JourneyLeg.Mode.FLIGHT:
            if not attrs.get("flight_number", "").strip():
                raise serializers.ValidationError(
                    {"flight_number": "Flight legs require a flight number."}
                )
            if (
                origin_place.place_type != Place.PlaceType.AIRPORT
                or destination_place.place_type != Place.PlaceType.AIRPORT
            ):
                raise serializers.ValidationError(
                    {
                        "origin_place_id": (
                            "Canonical flight legs must start and end at airports."
                        )
                    }
                )
        elif attrs.get("flight_number", "").strip():
            raise serializers.ValidationError(
                {"flight_number": "Drive legs cannot have a flight number."}
            )
        return attrs


class JourneyCreateSerializer(serializers.Serializer):
    start_place_id = serializers.PrimaryKeyRelatedField(
        source="start_place",
        queryset=Place.objects.filter(active=True),
        required=True,
        allow_null=False,
    )
    destination_place_id = serializers.PrimaryKeyRelatedField(
        source="destination_place",
        queryset=Place.objects.filter(active=True),
        required=True,
        allow_null=False,
    )
    start_location = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), required=False, allow_null=True
    )
    destination_location = serializers.PrimaryKeyRelatedField(
        queryset=Location.objects.all(), required=False, allow_null=True
    )
    notes = serializers.CharField(
        required=False, allow_blank=True, max_length=2000, default=""
    )
    legs = JourneyLegInputSerializer(many=True, allow_empty=False, max_length=20)

    @staticmethod
    def _matching_place_id(place: Place) -> int | None:
        locality = place.resolve_matching_locality()
        return locality.pk if locality is not None else None

    def _validate_location_access(self, locations: set[Location]) -> None:
        request = self.context.get("request")
        user_id = getattr(getattr(request, "user", None), "pk", None)
        inaccessible = [
            location.pk
            for location in locations
            if location.owner_id is not None and location.owner_id != user_id
        ]
        if inaccessible:
            raise serializers.ValidationError(
                {"locations": ("Private locations may only be used by their owner.")}
            )

    def validate(self, attrs: dict) -> dict:
        server_route_fields = {
            "distance_meters",
            "route_duration_seconds",
            "route_polyline",
            "route_provider",
            "route_profile",
            "route_captured_at",
            "allowed_detour_meters",
            "route_metadata",
        }
        raw_legs = self.initial_data.get("legs", [])
        for index, raw_leg in enumerate(raw_legs):
            supplied = server_route_fields.intersection(raw_leg)
            if supplied:
                raise serializers.ValidationError(
                    {
                        "legs": {
                            index: {
                                field: (
                                    "Route snapshots are calculated and assigned "
                                    "by the server."
                                )
                                for field in sorted(supplied)
                            }
                        }
                    }
                )
        start_place = attrs["start_place"]
        destination_place = attrs["destination_place"]
        start_location = attrs.get("start_location")
        destination_location = attrs.get("destination_location")
        for field, place in (
            ("start_place_id", start_place),
            ("destination_place_id", destination_place),
        ):
            if place.place_type not in {
                Place.PlaceType.LOCALITY,
                Place.PlaceType.AIRPORT,
            }:
                raise serializers.ValidationError(
                    {field: "Choose a locality or airport."}
                )
            if self._matching_place_id(place) is None:
                raise serializers.ValidationError(
                    {field: "Place is unavailable for matching."}
                )
        if start_place.pk == destination_place.pk:
            raise serializers.ValidationError(
                {"destination_place_id": "Journey endpoints must differ."}
            )

        legs = attrs["legs"]
        positions = [leg.get("position", index) for index, leg in enumerate(legs)]
        if sorted(positions) != list(range(len(legs))):
            raise serializers.ValidationError(
                {"legs": "Leg positions must be unique, contiguous, and start at zero."}
            )
        for index, leg in enumerate(legs):
            leg["position"] = positions[index]
        legs.sort(key=lambda leg: leg["position"])

        if self._matching_place_id(
            legs[0]["origin_place"]
        ) != self._matching_place_id(start_place) or self._matching_place_id(
            legs[-1]["destination_place"]
        ) != self._matching_place_id(destination_place):
            raise serializers.ValidationError(
                {"legs": "First and last leg must match the journey endpoints."}
            )

        for index in range(1, len(legs)):
            previous = legs[index - 1]
            current = legs[index]
            previous_node = self._matching_place_id(previous["destination_place"])
            current_node = self._matching_place_id(current["origin_place"])
            if previous_node != current_node:
                raise serializers.ValidationError(
                    {"legs": "Every leg must connect to the next leg."}
                )
            if current["depart_at"] <= previous["depart_at"]:
                raise serializers.ValidationError(
                    {"legs": "Leg departure times must be strictly increasing."}
                )
            if (
                previous.get("arrive_at") is not None
                and current["depart_at"] < previous["arrive_at"]
            ):
                raise serializers.ValidationError(
                    {"legs": "A leg cannot depart before the previous leg arrives."}
                )

        scoped_locations = {
            location
            for location in (start_location, destination_location)
            if location is not None
        }
        scoped_locations.update(
            location
            for leg in legs
            for location in (leg.get("origin"), leg.get("destination"))
            if location is not None
        )
        self._validate_location_access(scoped_locations)
        scoped_pairs = [
            ("start_location", start_location, start_place),
            ("destination_location", destination_location, destination_place),
        ]
        for index, leg in enumerate(legs):
            scoped_pairs.extend(
                (
                    (
                        f"legs.{index}.origin",
                        leg.get("origin"),
                        leg["origin_place"],
                    ),
                    (
                        f"legs.{index}.destination",
                        leg.get("destination"),
                        leg["destination_place"],
                    ),
                )
            )
        invalid = [
            field
            for field, location, place in scoped_pairs
            if location is not None and location.canonical_place_id != place.pk
        ]
        if invalid:
            raise serializers.ValidationError(
                {
                    "locations": (
                        "Every preferred point must belong to its selected "
                        f"canonical place: {', '.join(invalid)}."
                    )
                }
            )
        return attrs

    def create(self, validated_data: dict) -> Journey:
        legs = validated_data.pop("legs")
        provider = get_route_provider(external_call_budget=max(1, len(legs)))
        for leg in legs:
            if leg["mode"] != JourneyLeg.Mode.DRIVE:
                continue
            try:
                origin = leg.get("origin")
                destination = leg.get("destination")
                if origin is None:
                    origin = leg["origin_place"]
                if destination is None:
                    destination = leg["destination_place"]
                if origin.latitude is None or destination.latitude is None:
                    continue
                route = provider.directions(
                    [
                        GeoPoint(
                            float(origin.latitude),
                            float(origin.longitude),
                        ),
                        GeoPoint(
                            float(destination.latitude),
                            float(destination.longitude),
                        ),
                    ],
                    profile="drive",
                )
            except RouteProviderError:
                continue
            leg.update(
                {
                    "distance_meters": route.distance_meters,
                    "route_duration_seconds": route.duration_seconds,
                    "route_polyline": route.polyline,
                    "route_provider": route.provider,
                    "route_profile": route.profile,
                    "route_captured_at": timezone.now(),
                    "route_metadata": {
                        "cache_namespace": provider.cache_namespace,
                        "corridor_points": [
                            {
                                "latitude": point.latitude,
                                "longitude": point.longitude,
                            }
                            for point in route.corridor_points
                        ],
                        "provider_metadata": route.metadata,
                    },
                }
            )
        with transaction.atomic():
            journey = Journey.objects.create(
                traveler=self.context["request"].user,
                schema_version=2,
                status=Journey.Status.DRAFT,
                **validated_data,
            )
            JourneyLeg.objects.bulk_create(
                [JourneyLeg(journey=journey, **leg) for leg in legs]
            )
        return journey


class JourneySearchFilterSerializer(serializers.Serializer):
    start_location_id = serializers.IntegerField(min_value=1, required=False)
    destination_location_id = serializers.IntegerField(min_value=1, required=False)
    start_place_id = serializers.IntegerField(min_value=1, required=False)
    destination_place_id = serializers.IntegerField(min_value=1, required=False)
    mode = serializers.ChoiceField(choices=JourneyLeg.Mode.choices, required=False)
    departure_after = serializers.DateTimeField(required=False)
    min_capacity_kg = serializers.DecimalField(
        max_digits=8,
        decimal_places=2,
        min_value=Decimal("0.01"),
        required=False,
    )


class JourneyLegProofSerializer(serializers.ModelSerializer):
    reviewer_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = JourneyLegProof
        fields = (
            "id",
            "kind",
            "content_type",
            "bytes",
            "metadata",
            "status",
            "reviewer_id",
            "reviewed_at",
            "rejection_reason",
            "bucket",
            "object_key",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def to_representation(self, instance: JourneyLegProof) -> dict:
        data = super().to_representation(instance)
        request = self.context.get("request")
        is_owner = (
            request is not None
            and request.user.is_authenticated
            and request.user.pk == instance.leg.journey.traveler_id
        )
        if not is_owner:
            for private_field in (
                "bucket",
                "object_key",
                "metadata",
                "reviewer_id",
                "rejection_reason",
            ):
                data.pop(private_field, None)
        return data


class JourneyLegSerializer(serializers.ModelSerializer):
    origin = PublicLocationSerializer(read_only=True)
    destination = PublicLocationSerializer(read_only=True)
    origin_place = serializers.SerializerMethodField()
    destination_place = serializers.SerializerMethodField()
    proofs = JourneyLegProofSerializer(many=True, read_only=True)
    has_approved_proof = serializers.SerializerMethodField()

    class Meta:
        model = JourneyLeg
        fields = (
            "id",
            "position",
            "mode",
            "origin",
            "destination",
            "origin_place",
            "destination_place",
            "depart_at",
            "arrive_at",
            "capacity_kg",
            "distance_meters",
            "route_duration_seconds",
            "route_polyline",
            "route_provider",
            "route_profile",
            "route_captured_at",
            "allowed_detour_meters",
            "route_metadata",
            "flight_number",
            "departure_airport_metadata",
            "arrival_airport_metadata",
            "has_approved_proof",
            "proofs",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_has_approved_proof(self, obj: JourneyLeg) -> bool:
        annotated = getattr(obj, "has_approved_proof_value", None)
        if annotated is not None:
            return annotated
        return any(
            proof.status == JourneyLegProof.Status.APPROVED
            for proof in obj.proofs.all()
        )

    @staticmethod
    def _place_summary(place: Place | None) -> dict | None:
        if place is None:
            return None
        locality = place.resolve_matching_locality()
        return {
            "id": place.pk,
            "name": place.name,
            "display_label": place.display_label,
            "place_type": place.place_type,
            "iata_code": place.iata_code or None,
            "country_code": place.country_id,
            "parent_name": place.parent.name
            if place.parent_id and place.parent
            else None,
            "matching_locality_id": locality.pk if locality else None,
            "matching_locality_name": locality.name if locality else None,
        }

    def get_origin_place(self, obj: JourneyLeg) -> dict | None:
        return self._place_summary(obj.origin_place)

    def get_destination_place(self, obj: JourneyLeg) -> dict | None:
        return self._place_summary(obj.destination_place)

    def to_representation(self, instance: JourneyLeg) -> dict:
        data = super().to_representation(instance)
        request = self.context.get("request")
        is_owner = (
            request is not None
            and request.user.is_authenticated
            and request.user.pk == instance.journey.traveler_id
        )
        if not is_owner:
            # A provider route or polyline can contain exact waypoints even
            # when both endpoint serializers are coarse.
            for private_field in (
                "route_polyline",
                "route_metadata",
                "departure_airport_metadata",
                "arrival_airport_metadata",
                "proofs",
            ):
                data.pop(private_field, None)
            # Phase 2B: the routed distance/duration are measured between the
            # leg's *exact* endpoints. Published at metre precision they narrow
            # a coarse endpoint to an arc around the other one, so a viewer who
            # does not own the Journey gets the band instead.
            data.pop("route_duration_seconds", None)
            data["distance_band"] = distance_band(data.pop("distance_meters", None))
        return data


class JourneySerializer(serializers.ModelSerializer):
    traveler_id = serializers.IntegerField(read_only=True)
    traveler_name = serializers.CharField(source="traveler.full_name", read_only=True)
    start_location = PublicLocationSerializer(read_only=True)
    destination_location = PublicLocationSerializer(read_only=True)
    start_place = serializers.SerializerMethodField()
    destination_place = serializers.SerializerMethodField()
    legs = JourneyLegSerializer(many=True, read_only=True)
    legacy_trip_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Journey
        fields = (
            "id",
            "traveler_id",
            "traveler_name",
            "start_location",
            "destination_location",
            "start_place",
            "destination_place",
            "legacy_trip_id",
            "status",
            "published_at",
            "notes",
            "legs",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    @staticmethod
    def _place_summary(place: Place | None) -> dict | None:
        if place is None:
            return None
        locality = place.resolve_matching_locality()
        return {
            "id": place.pk,
            "name": place.name,
            "display_label": place.display_label,
            "place_type": place.place_type,
            "iata_code": place.iata_code or None,
            "country_code": place.country_id,
            "parent_name": place.parent.name
            if place.parent_id and place.parent
            else None,
            "matching_locality_id": locality.pk if locality else None,
            "matching_locality_name": locality.name if locality else None,
        }

    def get_start_place(self, obj: Journey) -> dict | None:
        return self._place_summary(obj.start_place)

    def get_destination_place(self, obj: Journey) -> dict | None:
        return self._place_summary(obj.destination_place)
