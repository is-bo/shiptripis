"""Trips schema.

Per ARCHITECTURE.md §11:
- `Airport` — IATA-keyed (CLAUDE.md §5: don't change to surrogate id without
  data migration, historic Trip rows FK to it).
- `Trip` — a traveler offering capacity origin → destination on a date.
- `TripStopover` — optional intermediate airports.
- `FlightTrackingSnapshot` — cached external API readings; written by a
  worker, read by the sender's flight-tracking screen.

Status machine (Trip):
    draft → active → in_transit → delivered → completed
                  ↘ cancelled
"""

from __future__ import annotations

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Airport(models.Model):
    """Reference table; seed data lives in a data migration.

    Primary key is the 3-letter IATA code. Trip rows FK to this. CLAUDE.md
    explicitly forbids switching to a surrogate id without migrating
    historic FK data.
    """

    iata = models.CharField(max_length=3, primary_key=True)
    city = models.CharField(max_length=80)
    name = models.CharField(max_length=120)
    country = models.CharField(max_length=2)  # ISO 3166-1 alpha-2

    class Meta:
        db_table = "trips_airport"
        ordering = ["country", "city"]
        indexes = [models.Index(fields=["country"], name="trips_airport_country_idx")]

    def __str__(self) -> str:
        return f"{self.iata} — {self.city}"


class Trip(models.Model):
    """Capacity offered by a traveler from origin → destination on a date."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        IN_TRANSIT = "in_transit", "In transit"
        DELIVERED = "delivered", "Delivered"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    traveler = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trips",
    )
    origin = models.ForeignKey(
        Airport,
        on_delete=models.PROTECT,
        related_name="trips_from",
    )
    destination = models.ForeignKey(
        Airport,
        on_delete=models.PROTECT,
        related_name="trips_to",
    )

    departure_at = models.DateTimeField()
    capacity_kg = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1)],
        help_text="Total kg the traveler can carry for parcels.",
    )
    notes = models.TextField(blank=True, default="")

    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )
    flight_number = models.CharField(max_length=12, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "trips_trip"
        ordering = ["departure_at"]
        indexes = [
            models.Index(
                fields=["origin", "destination", "departure_at"],
                name="trips_corridor_idx",
            ),
            models.Index(fields=["traveler", "-departure_at"], name="trips_user_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(origin=models.F("destination")),
                name="trips_origin_neq_destination",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.origin_id}→{self.destination_id} {self.departure_at:%Y-%m-%d}"


class TripStopover(models.Model):
    """Optional intermediate airports for a trip.

    Ordered by `position` (0-based, contiguous). Travelers can use this to
    advertise that they'll pass through airport X for ~N hours.
    """

    trip = models.ForeignKey(
        Trip,
        on_delete=models.CASCADE,
        related_name="stopovers",
    )
    airport = models.ForeignKey(Airport, on_delete=models.PROTECT)
    position = models.PositiveSmallIntegerField()
    arrives_at = models.DateTimeField(null=True, blank=True)
    departs_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "trips_stopover"
        ordering = ["trip", "position"]
        constraints = [
            models.UniqueConstraint(
                fields=["trip", "position"],
                name="trips_stopover_unique_position",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.trip_id}#{self.position} {self.airport_id}"


class FlightTrackingSnapshot(models.Model):
    """Cached snapshot from an external flight-tracking API.

    Written by a worker (V2). Reads are point-in-time; older snapshots
    stay for the sender to scrub history if we want it later.
    """

    trip = models.ForeignKey(
        Trip,
        on_delete=models.CASCADE,
        related_name="tracking_snapshots",
    )
    captured_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=24)  # "scheduled" / "boarding" / "in_air" / ...
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    altitude_m = models.IntegerField(null=True, blank=True)
    speed_kph = models.IntegerField(null=True, blank=True)
    raw = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "trips_tracking_snapshot"
        ordering = ["-captured_at"]
        indexes = [
            models.Index(fields=["trip", "-captured_at"], name="trips_track_trip_idx"),
        ]
