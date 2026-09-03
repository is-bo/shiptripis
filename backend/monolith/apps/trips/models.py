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

from decimal import Decimal

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


class TripMedia(models.Model):
    """Photo attached to a trip (airline ticket / boarding pass).

    `object_key` references an object in MinIO/S3; Django never stores
    bytes (ARCHITECTURE.md §9, §11).
    """

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="media")
    bucket = models.CharField(max_length=64)
    object_key = models.CharField(max_length=255)
    content_type = models.CharField(max_length=64, default="image/jpeg")
    bytes = models.PositiveIntegerField(default=0)
    kind = models.CharField(max_length=24, default="ticket")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "trips_media"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["trip", "created_at"], name="trips_media_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["bucket", "object_key"],
                name="trips_media_unique_object",
            ),
        ]

    def __str__(self) -> str:
        return f"trip#{self.trip_id} {self.object_key}"


class Journey(models.Model):
    """V1 traveler itinerary made from ordered, segment-capacity legs.

    ``Trip`` remains the legacy airport-to-airport record. New marketplace
    behavior is built on Journey; ``legacy_trip`` is only an audit and
    migration bridge and must not be interpreted as the source of truth.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING_VERIFICATION = "pending_verification", "Pending verification"
        ACTIVE = "active", "Active"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    traveler = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="journeys",
    )
    # Version 1 rows retain the historical Location-only shape.  New V1
    # journeys use schema_version=2 and stable catalogue places; Location is
    # optional operational meeting detail only.
    schema_version = models.PositiveSmallIntegerField(default=1)
    start_place = models.ForeignKey(
        "locations.Place",
        on_delete=models.PROTECT,
        related_name="journeys_starting_at",
        null=True,
        blank=True,
    )
    destination_place = models.ForeignKey(
        "locations.Place",
        on_delete=models.PROTECT,
        related_name="journeys_ending_at",
        null=True,
        blank=True,
    )
    start_location = models.ForeignKey(
        "locations.Location",
        on_delete=models.PROTECT,
        related_name="journeys_starting_here",
        null=True,
        blank=True,
    )
    destination_location = models.ForeignKey(
        "locations.Location",
        on_delete=models.PROTECT,
        related_name="journeys_ending_here",
        null=True,
        blank=True,
    )
    legacy_trip = models.OneToOneField(
        Trip,
        on_delete=models.PROTECT,
        related_name="v1_journey",
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    published_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default="", max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "trips_journey"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["status", "-published_at"],
                name="journey_status_published_idx",
            ),
            models.Index(
                fields=["traveler", "status", "-created_at"],
                name="journey_owner_status_idx",
            ),
            models.Index(
                fields=["start_location", "destination_location", "status"],
                name="journey_endpoints_idx",
            ),
            models.Index(
                fields=["start_place", "destination_place", "status"],
                name="journey_place_endpoints_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(start_location__isnull=True)
                        | models.Q(destination_location__isnull=True)
                        | ~models.Q(start_location=models.F("destination_location"))
                    )
                    & (
                        models.Q(start_place__isnull=True)
                        | models.Q(destination_place__isnull=True)
                        | ~models.Q(start_place=models.F("destination_place"))
                    )
                ),
                name="journey_distinct_endpoints",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        schema_version=1,
                        start_place__isnull=True,
                        destination_place__isnull=True,
                    )
                    | models.Q(
                        schema_version=2,
                        start_place__isnull=False,
                        destination_place__isnull=False,
                    )
                ),
                name="journey_canonical_endpoints",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"Journey #{self.pk} "
            f"{self.start_place_id or self.start_location_id}"
            f"→{self.destination_place_id or self.destination_location_id}"
        )


class JourneyLeg(models.Model):
    """One ordered segment of a V1 Journey.

    Position is zero-based and must be contiguous when a journey is
    published. The unique constraint prevents ambiguous ordering while the
    publication service validates the cross-row continuity invariants.
    """

    class Mode(models.TextChoices):
        FLIGHT = "FLIGHT", "Flight"
        DRIVE = "DRIVE", "Drive"

    journey = models.ForeignKey(
        Journey,
        on_delete=models.CASCADE,
        related_name="legs",
    )
    origin_place = models.ForeignKey(
        "locations.Place",
        on_delete=models.PROTECT,
        related_name="journey_legs_originating",
        null=True,
        blank=True,
    )
    destination_place = models.ForeignKey(
        "locations.Place",
        on_delete=models.PROTECT,
        related_name="journey_legs_ending",
        null=True,
        blank=True,
    )
    position = models.PositiveSmallIntegerField()
    mode = models.CharField(max_length=8, choices=Mode.choices)
    origin = models.ForeignKey(
        "locations.Location",
        on_delete=models.PROTECT,
        related_name="journey_legs_from",
        null=True,
        blank=True,
    )
    destination = models.ForeignKey(
        "locations.Location",
        on_delete=models.PROTECT,
        related_name="journey_legs_to",
        null=True,
        blank=True,
    )
    depart_at = models.DateTimeField()
    arrive_at = models.DateTimeField(null=True, blank=True)
    capacity_kg = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )

    # Mode-specific and provider-neutral route inputs. Matching/ranking is a
    # later phase; these fields preserve the route snapshot needed for it.
    distance_meters = models.PositiveBigIntegerField(null=True, blank=True)
    route_duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    route_polyline = models.TextField(blank=True, default="")
    route_provider = models.CharField(max_length=64, blank=True, default="")
    route_profile = models.CharField(max_length=32, blank=True, default="")
    route_captured_at = models.DateTimeField(null=True, blank=True)
    allowed_detour_meters = models.PositiveIntegerField(null=True, blank=True)
    route_metadata = models.JSONField(default=dict, blank=True)
    flight_number = models.CharField(max_length=16, blank=True, default="")
    departure_airport_metadata = models.JSONField(default=dict, blank=True)
    arrival_airport_metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "trips_journey_leg"
        ordering = ["journey", "position"]
        indexes = [
            models.Index(
                fields=["origin", "destination", "depart_at"],
                name="journey_leg_route_idx",
            ),
            models.Index(
                fields=["mode", "depart_at"],
                name="journey_leg_mode_time_idx",
            ),
            models.Index(
                fields=["journey", "depart_at", "arrive_at"],
                name="journey_leg_time_window_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["journey", "position"],
                name="journey_leg_unique_position",
            ),
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(origin__isnull=True)
                        | models.Q(destination__isnull=True)
                        | ~models.Q(origin=models.F("destination"))
                    )
                    & (
                        models.Q(origin_place__isnull=True)
                        | models.Q(destination_place__isnull=True)
                        | ~models.Q(origin_place=models.F("destination_place"))
                    )
                ),
                name="journey_leg_distinct_endpoints",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(origin_place__isnull=True, destination_place__isnull=True)
                    | models.Q(
                        origin_place__isnull=False, destination_place__isnull=False
                    )
                ),
                name="journey_leg_canonical_endpoints",
            ),
            models.CheckConstraint(
                condition=models.Q(capacity_kg__gt=0),
                name="journey_leg_positive_capacity",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(arrive_at__isnull=True)
                    | models.Q(arrive_at__gt=models.F("depart_at"))
                ),
                name="journey_leg_arrival_after_departure",
            ),
        ]

    def __str__(self) -> str:
        return f"Journey #{self.journey_id} leg {self.position} ({self.mode})"


class JourneyLegProof(models.Model):
    """Private transport proof for a flight leg.

    Storage references are private implementation details. API serializers
    expose them only to the owning traveler; administrators retain access for
    review. Multiple submissions preserve rejection and re-submission history.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    leg = models.ForeignKey(
        JourneyLeg,
        on_delete=models.CASCADE,
        related_name="proofs",
    )
    bucket = models.CharField(max_length=64)
    object_key = models.CharField(max_length=512)
    content_type = models.CharField(max_length=64, default="image/jpeg")
    bytes = models.PositiveIntegerField(default=0)
    kind = models.CharField(max_length=24, default="ticket")
    metadata = models.JSONField(default=dict, blank=True)
    # A phone loses its connection mid-upload more often than it succeeds
    # first time. The client stamps one key per *selected file* so a retry
    # re-attaches to the row the first attempt may already have created,
    # instead of leaving a reviewer with three copies of one boarding pass.
    idempotency_key = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviewed_journey_leg_proofs",
        null=True,
        blank=True,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, default="", max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "trips_journey_leg_proof"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["leg", "status", "-created_at"],
                name="journey_proof_review_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["bucket", "object_key"],
                name="journey_proof_unique_object",
            ),
            models.UniqueConstraint(
                fields=["leg", "idempotency_key"],
                condition=~models.Q(idempotency_key=""),
                name="journey_proof_unique_idempotency_key",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status="pending",
                        reviewer__isnull=True,
                        reviewed_at__isnull=True,
                        rejection_reason="",
                    )
                    | models.Q(
                        status="approved",
                        reviewer__isnull=False,
                        reviewed_at__isnull=False,
                        rejection_reason="",
                    )
                    | (
                        models.Q(
                            status="rejected",
                            reviewer__isnull=False,
                            reviewed_at__isnull=False,
                        )
                        & ~models.Q(rejection_reason="")
                    )
                ),
                name="journey_proof_review_consistent",
            ),
        ]

    def __str__(self) -> str:
        return f"Journey leg #{self.leg_id} proof #{self.pk} ({self.status})"


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
    status = models.CharField(
        max_length=24
    )  # "scheduled" / "boarding" / "in_air" / ...
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
