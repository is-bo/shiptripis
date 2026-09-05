from __future__ import annotations

from rest_framework import serializers

from .models import AirportLocalityMapping, Country, Place


class GeographyCountrySerializer(serializers.ModelSerializer):
    class Meta:
        model = Country
        fields = ("code", "name", "active")
        read_only_fields = fields


class GeographyPlaceSerializer(serializers.ModelSerializer):
    country_code = serializers.CharField(source="country.code", read_only=True)
    display_label = serializers.CharField(read_only=True)
    place_type_label = serializers.CharField(
        source="get_place_type_display", read_only=True
    )
    parent_id = serializers.IntegerField(read_only=True)
    parent_name = serializers.CharField(
        source="parent.name", read_only=True, allow_null=True
    )
    # The parent's own tier, straight from the reviewed source (``wilaya``,
    # ``department``, ``province``, ``state``, ...).  A client can name the
    # context it already shows ("Jijel Wilaya") instead of guessing a tier
    # from the country; an unsourced parent stays an empty string.
    parent_admin_level = serializers.CharField(
        source="parent.admin_level", read_only=True, allow_null=True
    )
    served_locality = serializers.SerializerMethodField()
    matching_locality = serializers.SerializerMethodField()
    available_for_matching = serializers.SerializerMethodField()
    search_relation = serializers.SerializerMethodField()
    search_context = serializers.SerializerMethodField()
    search_distance_km = serializers.SerializerMethodField()

    class Meta:
        model = Place
        fields = (
            "id",
            "country_code",
            "place_type",
            "place_type_label",
            "name",
            "display_label",
            "normalized_name",
            "parent_id",
            "parent_name",
            "parent_admin_level",
            "admin_level",
            "latitude",
            "longitude",
            "iata_code",
            "icao_code",
            "airport_type",
            "passenger_use",
            "source",
            "source_id",
            "source_version",
            "active",
            "served_locality",
            "matching_locality",
            "available_for_matching",
            "search_relation",
            "search_context",
            "search_distance_km",
        )
        read_only_fields = fields

    def get_served_locality(self, obj: Place):
        if obj.place_type != Place.PlaceType.AIRPORT:
            return None
        mappings = getattr(obj, "_prefetched_objects_cache", {}).get("airport_mappings")
        if mappings is None:
            mappings = obj.airport_mappings.filter(
                active=True,
                is_primary=True,
                relationship_type=AirportLocalityMapping.RelationshipType.SERVED,
                locality__active=True,
            ).select_related("locality", "locality__parent")
        mapping = next(
            (
                item
                for item in mappings
                if item.active
                and item.is_primary
                and item.relationship_type
                == AirportLocalityMapping.RelationshipType.SERVED
                and item.locality.active
            ),
            None,
        )
        if mapping is None:
            return None
        locality = mapping.locality
        return {
            "id": locality.id,
            "name": locality.name,
            "display_label": locality.display_label,
            "place_type": locality.place_type,
            "admin_level": locality.admin_level,
            "parent_id": locality.parent_id,
            "parent_name": locality.parent.name if locality.parent_id else None,
            "parent_admin_level": (
                locality.parent.admin_level if locality.parent_id else None
            ),
        }

    def get_matching_locality(self, obj: Place):
        return (
            self.get_served_locality(obj)
            if obj.place_type == Place.PlaceType.AIRPORT
            else {
                "id": obj.id,
                "name": obj.name,
                "display_label": obj.display_label,
                "place_type": obj.place_type,
                "admin_level": obj.admin_level,
                "parent_id": obj.parent_id,
                "parent_name": obj.parent.name if obj.parent_id else None,
                "parent_admin_level": (
                    obj.parent.admin_level if obj.parent_id else None
                ),
            }
        )

    def get_available_for_matching(self, obj: Place) -> bool:
        return (
            obj.place_type != Place.PlaceType.AIRPORT
            or self.get_served_locality(obj) is not None
        )

    def _search_metadata(self, obj: Place) -> dict | None:
        # A direct textual match always owns its presentation, even when the
        # same airport was also discovered through a served/nearby expansion.
        if getattr(obj, "_search_rank", None) in {0, 1}:
            return {"relation": "direct_match", "context": None, "distance_km": None}
        metadata = self.context.get("search_metadata", {}).get(obj.pk)
        if metadata is not None:
            return metadata
        if getattr(obj, "_search_rank", None) is not None:
            return {"relation": "direct_match", "context": None, "distance_km": None}
        return None

    def get_search_relation(self, obj: Place) -> str | None:
        metadata = self._search_metadata(obj)
        return metadata["relation"] if metadata else None

    def get_search_context(self, obj: Place) -> dict | None:
        metadata = self._search_metadata(obj)
        context = metadata.get("context") if metadata else None
        if context is None:
            return None
        return {
            "id": context.id,
            "name": context.name,
            "display_label": context.display_label,
        }

    def get_search_distance_km(self, obj: Place) -> float | None:
        metadata = self._search_metadata(obj)
        return metadata.get("distance_km") if metadata else None
