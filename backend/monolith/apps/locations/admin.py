from django.contrib import admin

from .models import AirportLocalityMapping, Country, Location, Place, PlaceAlternateName


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "source", "source_id", "active", "updated_at")
    list_filter = ("active", "source")
    search_fields = ("code", "name", "normalized_name", "source_id")
    list_editable = ("active",)
    readonly_fields = (
        "code",
        "name",
        "normalized_name",
        "source",
        "source_id",
        "source_version",
        "metadata",
        "created_at",
        "updated_at",
    )


@admin.register(Place)
class PlaceAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "place_type",
        "country",
        "parent",
        "source",
        "source_id",
        "active",
    )
    list_filter = ("country", "place_type", "active", "source", "passenger_use")
    search_fields = (
        "name",
        "normalized_name",
        "source_id",
        "iata_code",
        "icao_code",
        "parent__name",
    )
    autocomplete_fields = ("country", "parent", "legacy_airport")
    list_editable = ("active",)
    readonly_fields = (
        "id",
        "country",
        "place_type",
        "source",
        "source_id",
        "source_version",
        "name",
        "normalized_name",
        "parent",
        "admin_level",
        "latitude",
        "longitude",
        "iata_code",
        "icao_code",
        "airport_type",
        "passenger_use",
        "legacy_airport",
        "metadata",
        "created_at",
        "updated_at",
    )
    ordering = ("country", "name", "id")
    list_select_related = ("country", "parent")


@admin.register(PlaceAlternateName)
class PlaceAlternateNameAdmin(admin.ModelAdmin):
    list_display = ("name", "language", "place", "source", "source_id", "active")
    list_filter = ("language", "active", "source")
    search_fields = ("name", "normalized_name", "place__name", "source_id")
    autocomplete_fields = ("place",)
    list_editable = ("active",)
    readonly_fields = (
        "place",
        "name",
        "normalized_name",
        "language",
        "source",
        "source_id",
        "source_version",
        "metadata",
    )
    list_select_related = ("place",)


@admin.register(AirportLocalityMapping)
class AirportLocalityMappingAdmin(admin.ModelAdmin):
    list_display = (
        "airport",
        "locality",
        "relationship_type",
        "is_primary",
        "source",
        "source_id",
        "active",
    )
    list_filter = ("relationship_type", "is_primary", "active", "source")
    search_fields = (
        "airport__name",
        "airport__iata_code",
        "locality__name",
        "source_id",
    )
    autocomplete_fields = ("airport", "locality")
    list_editable = ("is_primary", "active")
    readonly_fields = (
        "airport",
        "locality",
        "relationship_type",
        "source",
        "source_id",
        "source_version",
        "metadata",
    )
    list_select_related = ("airport", "locality")


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "kind",
        "public_label",
        "city",
        "country_code",
        "owner",
        "created_at",
    )
    list_filter = ("kind", "country_code", "precision", "provider")
    search_fields = (
        "public_label",
        "private_label",
        "normalized_label",
        "city",
        "provider_place_id",
        "airport__iata",
        "owner__email",
    )
    autocomplete_fields = ("airport", "created_by", "owner")
    ordering = ("-created_at",)

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
