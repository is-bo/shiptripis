from django.contrib import admin

from .models import (
    Airport,
    FlightTrackingSnapshot,
    Journey,
    JourneyLeg,
    JourneyLegProof,
    Trip,
    TripStopover,
)


@admin.register(Airport)
class AirportAdmin(admin.ModelAdmin):
    list_display = ("iata", "city", "name", "country")
    list_filter = ("country",)
    search_fields = ("iata", "city", "name")
    ordering = ("country", "city")


class TripStopoverInline(admin.TabularInline):
    model = TripStopover
    extra = 0


@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "traveler",
        "origin",
        "destination",
        "departure_at",
        "capacity_kg",
        "status",
    )
    list_filter = ("status", "origin", "destination")
    search_fields = ("traveler__email", "flight_number")
    autocomplete_fields = ("origin", "destination", "traveler")
    inlines = [TripStopoverInline]
    date_hierarchy = "departure_at"


@admin.register(FlightTrackingSnapshot)
class FlightTrackingSnapshotAdmin(admin.ModelAdmin):
    list_display = ("trip", "captured_at", "status", "latitude", "longitude")
    list_filter = ("status",)
    date_hierarchy = "captured_at"


class JourneyLegInline(admin.TabularInline):
    model = JourneyLeg
    extra = 0
    show_change_link = True
    autocomplete_fields = ("origin", "destination")

    def get_readonly_fields(self, request, obj=None):
        if obj is not None and obj.status != Journey.Status.DRAFT:
            return (
                "position",
                "mode",
                "origin",
                "destination",
                "depart_at",
                "arrive_at",
                "capacity_kg",
                "distance_meters",
                "route_polyline",
                "allowed_detour_meters",
                "route_metadata",
                "flight_number",
                "departure_airport_metadata",
                "arrival_airport_metadata",
            )
        return ()

    def has_add_permission(self, request, obj=None):
        return obj is None or obj.status == Journey.Status.DRAFT

    def has_delete_permission(self, request, obj=None):
        return obj is None or obj.status == Journey.Status.DRAFT


@admin.register(Journey)
class JourneyAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "traveler",
        "start_location",
        "destination_location",
        "status",
        "published_at",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("traveler__email", "traveler__full_name")
    autocomplete_fields = (
        "traveler",
        "start_location",
        "destination_location",
        "legacy_trip",
    )
    inlines = (JourneyLegInline,)
    date_hierarchy = "created_at"

    def get_readonly_fields(self, request, obj=None):
        fields = ["status", "published_at", "created_at", "updated_at"]
        if obj is not None and obj.status != Journey.Status.DRAFT:
            fields.extend(
                (
                    "traveler",
                    "start_location",
                    "destination_location",
                    "legacy_trip",
                    "notes",
                )
            )
        return tuple(fields)


@admin.register(JourneyLeg)
class JourneyLegAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "journey",
        "position",
        "mode",
        "origin",
        "destination",
        "depart_at",
        "capacity_kg",
    )
    list_filter = ("mode",)
    search_fields = (
        "journey__traveler__email",
        "flight_number",
        "origin__public_label",
        "destination__public_label",
    )
    autocomplete_fields = ("journey", "origin", "destination")
    date_hierarchy = "depart_at"

    def has_add_permission(self, request):
        # Legs are created through the Journey inline, where draft state is
        # available for the authorization decision.
        return False

    def has_delete_permission(self, request, obj=None):
        return obj is not None and obj.journey.status == Journey.Status.DRAFT

    def get_readonly_fields(self, request, obj=None):
        if obj is not None and obj.journey.status != Journey.Status.DRAFT:
            return tuple(
                field.name
                for field in self.model._meta.fields
                if field.name not in {"id", "created_at", "updated_at"}
            ) + ("created_at", "updated_at")
        return ("created_at", "updated_at")


@admin.register(JourneyLegProof)
class JourneyLegProofAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "leg",
        "kind",
        "status",
        "reviewer",
        "reviewed_at",
        "created_at",
    )
    list_filter = ("status", "kind", "content_type")
    search_fields = (
        "leg__journey__traveler__email",
        "leg__flight_number",
        "object_key",
    )
    autocomplete_fields = ("leg", "reviewer")
    readonly_fields = (
        "status",
        "reviewer",
        "reviewed_at",
        "rejection_reason",
        "bucket",
        "object_key",
        "content_type",
        "bytes",
        "kind",
        "metadata",
        "created_at",
        "updated_at",
    )
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
