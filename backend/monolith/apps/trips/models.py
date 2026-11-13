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
from django.utils import timezone


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
    #: What the traveler accepts (spec 5.6): `DeliveryRequest.category` codes
    #: this journey refuses, sorted and unique, and whether it takes fragile
    #: items. Written only through the route write serializer and enforced by
    #: `item_accepted_by_traveler` in matching.
    refused_categories = models.JSONField(default=list, blank=True)
    accepts_fragile = models.BooleanField(default=True)
    #: Pause (spec 5.7). A paused journey is not discoverable and accepts no
    #: new offers; funded deals continue. `paused_by_staff` means only staff
    #: may resume it, and a staff pause always carries its reason. The owner's
    #: own pause carries none.
    paused_at = models.DateTimeField(null=True, blank=True)
    paused_by_staff = models.BooleanField(default=False)
    pause_reason = models.CharField(max_length=500, blank=True, default="")
    #: The traveler's own price (spec 8): EUR cents per kg of chargeable
    #: weight and a minimum per parcel. Both or neither; a journey with
    #: neither behaves exactly as an unpriced one always has. Written only by
    #: `apps.trips.pricing.apply_journey_price`, which records each change in
    #: `JourneyPriceChange`; read only by `apps.matching.listed_price`.
    price_per_kg_eur_cents = models.PositiveIntegerField(null=True, blank=True)
    min_price_eur_cents = models.PositiveIntegerField(null=True, blank=True)
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
            models.CheckConstraint(
                condition=(
                    models.Q(
                        paused_at__isnull=True,
                        paused_by_staff=False,
                        pause_reason="",
                    )
                    | models.Q(
                        paused_at__isnull=False,
                        paused_by_staff=False,
                        pause_reason="",
                    )
                    | (
                        models.Q(paused_at__isnull=False, paused_by_staff=True)
                        & ~models.Q(pause_reason="")
                    )
                ),
                name="journey_pause_consistent",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        price_per_kg_eur_cents__isnull=True,
                        min_price_eur_cents__isnull=True,
                    )
                    # Explicit non-null: a CHECK passes when it evaluates to
                    # NULL, and `NULL >= 1` is NULL, not false.
                    | models.Q(
                        price_per_kg_eur_cents__isnull=False,
                        min_price_eur_cents__isnull=False,
                        price_per_kg_eur_cents__gte=1,
                        min_price_eur_cents__gte=1,
                    )
                ),
                name="journey_price_complete",
            ),
        ]

    @property
    def is_paused(self) -> bool:
        return self.paused_at is not None

    @property
    def has_price(self) -> bool:
        return self.price_per_kg_eur_cents is not None

    def __str__(self) -> str:
        return (
            f"Journey #{self.pk} "
            f"{self.start_place_id or self.start_location_id}"
            f"→{self.destination_place_id or self.destination_location_id}"
        )


class JourneyPriceChange(models.Model):
    """One change of a journey's traveler price, append-only (spec 8).

    The audit trail of the price: who set it, from what, to what, and when.
    A price change never touches an existing offer or deal (each froze its own
    `listed_price` in its terms snapshot), so this history is the only record
    of what a sender would have seen pre-filled at a given moment.
    """

    journey = models.ForeignKey(
        Journey, on_delete=models.PROTECT, related_name="price_changes"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    price_per_kg_eur_cents_before = models.PositiveIntegerField(null=True, blank=True)
    min_price_eur_cents_before = models.PositiveIntegerField(null=True, blank=True)
    price_per_kg_eur_cents_after = models.PositiveIntegerField(null=True, blank=True)
    min_price_eur_cents_after = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "trips_journey_price_change"
        ordering = ["created_at", "pk"]
        indexes = [
            models.Index(
                fields=["journey", "created_at"],
                name="journey_price_change_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Price change #{self.pk} on journey #{self.journey_id}"


class JourneyLegProgress(models.Model):
    """A traveler's statement about one leg: at the port, departed, arrived (spec 11).

    A report is a statement, not a fact the platform vouches for. It changes
    no deal status and moves no money; it is copied to the timeline of every
    funded parcel on the leg, labelled as reported by the traveler. A report
    can be retracted for a short while, which keeps the row and stamps
    `retracted_at`; history is never deleted. One live row per leg and kind.
    """

    class Kind(models.TextChoices):
        AT_PORT = "at_port", "At the port"
        DEPARTED = "departed", "Departed"
        ARRIVED = "arrived", "Arrived"

    class Source(models.TextChoices):
        TRAVELER = "traveler", "Traveler"
        STAFF = "staff", "Staff"

    leg = models.ForeignKey(
        "trips.JourneyLeg", on_delete=models.CASCADE, related_name="progress_reports"
    )
    kind = models.CharField(max_length=10, choices=Kind.choices)
    source = models.CharField(
        max_length=10, choices=Source.choices, default=Source.TRAVELER
    )
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    reported_at = models.DateTimeField(default=timezone.now)
    retracted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "trips_journey_leg_progress"
        ordering = ["reported_at", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["leg", "kind"],
                condition=models.Q(retracted_at__isnull=True),
                name="journey_leg_progress_one_live",
            ),
        ]

    def __str__(self) -> str:
        return f"Progress #{self.pk} {self.kind} on leg #{self.leg_id}"


class JourneyScheduleChange(models.Model):
    """New times for an active journey, and the senders' answers (spec 12, L9A).

    Times only: the legs, stops and places stay as they are. ``original`` and
    ``proposed`` are the whole schedule before and after, one entry per leg
    (``leg_id``, ``position``, ``depart_at``, ``arrive_at``), so the record of
    the schedule that was replaced is kept for good. ``affected`` is the latest
    classification of the parcels on the changed legs, written each time the
    change is settled.

    A change never writes a deal: the funded arrival floor, the arrival snapshot
    and the agreed pickup time stay what funding froze.
    """

    class Status(models.TextChoices):
        PENDING_SENDERS = "pending_senders", "Waiting for senders"
        APPLIED = "applied", "Applied"
        WITHDRAWN = "withdrawn", "Withdrawn"

    class WithdrawnBy(models.TextChoices):
        TRAVELER = "traveler", "The traveler"
        #: The trip moved on while the change waited (a leg was reported
        #: departed, or the journey stopped being live), so it can no longer
        #: apply as proposed.
        NO_LONGER_VALID = "no_longer_valid", "No longer fits the trip"

    journey = models.ForeignKey(
        Journey, on_delete=models.PROTECT, related_name="schedule_changes"
    )
    proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING_SENDERS,
        db_index=True,
    )
    #: The traveler's own words, shown to the senders asked to agree.
    reason = models.CharField(max_length=500, blank=True, default="")
    original = models.JSONField(default=list)
    proposed = models.JSONField(default=list)
    affected = models.JSONField(default=list, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdrawn_by = models.CharField(
        max_length=16, choices=WithdrawnBy.choices, blank=True, default=""
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "trips_journey_schedule_change"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["journey", "-created_at"], name="journey_schedule_change_idx"
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["journey"],
                condition=models.Q(status="pending_senders"),
                name="journey_one_pending_schedule_change",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status="pending_senders",
                        applied_at__isnull=True,
                        withdrawn_at__isnull=True,
                        withdrawn_by="",
                    )
                    | models.Q(
                        status="applied",
                        applied_at__isnull=False,
                        withdrawn_at__isnull=True,
                        withdrawn_by="",
                    )
                    | (
                        models.Q(
                            status="withdrawn",
                            applied_at__isnull=True,
                            withdrawn_at__isnull=False,
                        )
                        & ~models.Q(withdrawn_by="")
                    )
                ),
                name="journey_schedule_change_state_consistent",
            ),
        ]

    def __str__(self) -> str:
        return f"Schedule change #{self.pk} on journey #{self.journey_id} ({self.status})"


class JourneyScheduleChangeConsent(models.Model):
    """One sender's answer to a material schedule change, for one parcel."""

    class State(models.TextChoices):
        PENDING = "pending", "Waiting for the sender"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"

    class Reason(models.TextChoices):
        #: The new arrival at the parcel's drop-off stop is after its deadline.
        DEADLINE = "deadline", "Misses the deadline"
        #: The arrival moved by more than `route_change.material_shift_minutes`
        #: from the one the sender last agreed to.
        SHIFT = "shift", "Moves the arrival"
        #: For a parcel not collected yet: the departure from its pickup stop
        #: moved by more than the same threshold from the pickup time the
        #: sender last agreed to, or earlier than the agreed pickup time.
        PICKUP = "pickup", "Moves the pickup"

    change = models.ForeignKey(
        JourneyScheduleChange, on_delete=models.PROTECT, related_name="consents"
    )
    deal = models.ForeignKey(
        "deals.Deal", on_delete=models.PROTECT, related_name="schedule_change_consents"
    )
    state = models.CharField(
        max_length=10, choices=State.choices, default=State.PENDING, db_index=True
    )
    reasons = models.JSONField(default=list)
    arrival_before = models.DateTimeField()
    arrival_after = models.DateTimeField()
    #: The departure from the parcel's pickup stop, before and after.
    pickup_before = models.DateTimeField()
    pickup_after = models.DateTimeField()
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "trips_journey_schedule_change_consent"
        ordering = ["change", "deal"]
        constraints = [
            models.UniqueConstraint(
                fields=["change", "deal"], name="journey_schedule_consent_unique"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(state="pending", decided_at__isnull=True)
                    | models.Q(
                        state__in=["accepted", "declined"], decided_at__isnull=False
                    )
                ),
                name="journey_schedule_consent_decided",
            ),
        ]

    def __str__(self) -> str:
        return f"Consent of deal #{self.deal_id} to change #{self.change_id} ({self.state})"


class JourneyLeg(models.Model):
    """One ordered segment of a V1 Journey.

    Position is zero-based and must be contiguous when a journey is
    published. The unique constraint prevents ambiguous ordering while the
    publication service validates the cross-row continuity invariants.
    """

    class Mode(models.TextChoices):
        FLIGHT = "FLIGHT", "Flight"
        DRIVE = "DRIVE", "Drive"
        SEA = "SEA", "Sea"

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
    #: Optional secondary capacity (spec 5.5). Weight stays the main capacity.
    #: Volume is enforced only against a request that has dimensions; a parcel
    #: count is enforced whenever declared.
    capacity_volume_l = models.PositiveIntegerField(null=True, blank=True)
    capacity_parcels = models.PositiveSmallIntegerField(null=True, blank=True)

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
                    models.Q(capacity_volume_l__isnull=True)
                    | models.Q(capacity_volume_l__gt=0)
                )
                & (
                    models.Q(capacity_parcels__isnull=True)
                    | models.Q(capacity_parcels__gt=0)
                ),
                name="journey_leg_positive_optional_capacity",
            ),
            models.CheckConstraint(
                condition=~models.Q(mode="SEA") | models.Q(flight_number=""),
                name="journey_leg_sea_has_no_flight_number",
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


class JourneyStopDetail(models.Model):
    """Optional handover options for one stop of a Journey (spec 5.1).

    A stop is a node of the leg chain: position 0 is the first leg's origin
    and position ``n`` the last leg's destination. A journey with no rows
    behaves exactly as before L3A: every stop accepts pickup and drop-off.

    ``handover_note`` and the window are handover detail. The note is shown
    only to the parties of a funded deal that uses the stop, through the frozen
    funding snapshot (`apps.deals.arrival`), and to the owner.
    """

    journey = models.ForeignKey(
        Journey,
        on_delete=models.CASCADE,
        related_name="stop_details",
    )
    position = models.PositiveSmallIntegerField()
    accepts_pickup = models.BooleanField(default=True)
    accepts_dropoff = models.BooleanField(default=True)
    handover_note = models.CharField(max_length=280, blank=True, default="")
    window_start = models.DateTimeField(null=True, blank=True)
    window_end = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "trips_journey_stop_detail"
        ordering = ["journey", "position"]
        constraints = [
            models.UniqueConstraint(
                fields=["journey", "position"],
                name="journey_stop_detail_unique_position",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(window_start__isnull=True, window_end__isnull=True)
                    | models.Q(
                        window_start__isnull=False,
                        window_end__isnull=False,
                        window_end__gt=models.F("window_start"),
                    )
                ),
                name="journey_stop_detail_window_ordered",
            ),
        ]

    def __str__(self) -> str:
        return f"Journey #{self.journey_id} stop {self.position}"


class JourneyLegProof(models.Model):
    """Private ticket proof for a flight or sea leg.

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
