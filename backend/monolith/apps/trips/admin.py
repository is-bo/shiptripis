from django.contrib import admin

from .models import Airport, FlightTrackingSnapshot, Trip, TripStopover


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
