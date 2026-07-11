from __future__ import annotations

from django.utils import timezone
from rest_framework import serializers

from .models import Airport, Trip, TripStopover


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
        known = set(Airport.objects.filter(iata__in=codes).values_list("iata", flat=True))
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
    traveler_name = serializers.CharField(
        source="traveler.full_name", read_only=True
    )

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
