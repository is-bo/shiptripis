from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.core.languages import CommunicationLanguage


class Deal(models.Model):
    class Status(models.TextChoices):
        OFFER_ACCEPTED = "offer_accepted", "Offer accepted"
        PAYMENT_REQUIRED = "payment_required", "Payment required"
        FUNDED = "funded", "Funded"
        PICKUP_READY = "pickup_ready", "Pickup ready"
        PICKED_UP = "picked_up", "Picked up"
        IN_TRANSIT = "in_transit", "In transit"
        DELIVERY_READY = "delivery_ready", "Delivery ready"
        DELIVERY_CONFIRMED = "delivery_confirmed", "Delivery confirmed"
        PROTECTION_WINDOW = "protection_window", "Protection window"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"
        PAYMENT_FAILED = "payment_failed", "Payment failed"
        DISPUTED = "disputed", "Disputed"
        REFUNDED = "refunded", "Refunded"
        PARTIALLY_REFUNDED = "partially_refunded", "Partially refunded"

    accepted_offer = models.OneToOneField(
        "matching.Offer",
        on_delete=models.PROTECT,
        related_name="deal",
    )
    match = models.OneToOneField(
        "matching.Match",
        on_delete=models.PROTECT,
        related_name="deal",
    )
    delivery_request = models.ForeignKey(
        "parcels.DeliveryRequest",
        on_delete=models.PROTECT,
        related_name="deals",
    )
    journey = models.ForeignKey(
        "trips.Journey",
        on_delete=models.PROTECT,
        related_name="deals",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="deals_as_sender",
    )
    traveler = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="deals_as_traveler",
    )
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.PAYMENT_REQUIRED,
        db_index=True,
    )
    is_legacy = models.BooleanField(default=False, db_index=True)
    funded_at = models.DateTimeField(null=True, blank=True)

    # --- Phase 4 lifecycle -------------------------------------------------
    #
    # Every timestamp below is server-authoritative. The client renders
    # countdowns from them and never computes a deadline of its own.

    #: The pickup instant the cancellation cutoff is measured against, frozen
    #: at funding from the request's ready window (or the matched leg's
    #: departure) so a later edit cannot move a party's cancellation penalty.
    agreed_pickup_at = models.DateTimeField(null=True, blank=True)
    #: Durations and money rules copied from the active settings revision at
    #: funding: the delivery-code buffer, the protection window, the rating
    #: window and the cancellation policy. A later revision cannot rewrite an
    #: active Deal's timeline because nothing downstream reads live settings.
    lifecycle_policy = models.JSONField(default=dict, blank=True)

    pickup_confirmed_at = models.DateTimeField(null=True, blank=True)
    #: `pickup_confirmed_at + delivery_code_buffer_seconds`. Before this
    #: instant the delivery code does not exist for anybody: not the sender,
    #: not the recipient's inbox, and never the traveler.
    delivery_code_available_at = models.DateTimeField(null=True, blank=True)
    delivery_code_released_at = models.DateTimeField(null=True, blank=True)
    delivery_confirmed_at = models.DateTimeField(null=True, blank=True)
    #: `delivery_confirmed_at + protection_window_seconds`. No payout may be
    #: released before it, and a dispute opened before it freezes the payout.
    protection_ends_at = models.DateTimeField(null=True, blank=True)
    rating_window_ends_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="deals_cancelled",
    )
    cancellation_reason = models.CharField(max_length=64, blank=True, default="")

    class NoShowParty(models.TextChoices):
        SENDER = "sender", "Sender"
        TRAVELER = "traveler", "Traveler"

    #: Admin-reviewed at launch. No automated risk scoring is derived from it
    #: yet; it exists so the decision is recorded, auditable and reportable.
    no_show_party = models.CharField(
        max_length=10, choices=NoShowParty.choices, blank=True, default=""
    )
    no_show_recorded_at = models.DateTimeField(null=True, blank=True)
    no_show_recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="deal_no_shows_recorded",
    )
    no_show_note = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "deals_deal"
        ordering = ["-created_at"]
        permissions = [
            ("record_no_show", "Can record an admin-reviewed no-show decision"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~Q(sender=F("traveler")),
                name="deals_sender_neq_traveler",
            ),
            models.UniqueConstraint(
                fields=["delivery_request"],
                condition=Q(
                    status__in=[
                        "offer_accepted",
                        "payment_required",
                        "funded",
                        "pickup_ready",
                        "picked_up",
                        "in_transit",
                        "delivery_ready",
                        "delivery_confirmed",
                        "protection_window",
                        "disputed",
                    ]
                ),
                name="deals_one_active_per_request",
            ),
            # The Phase 4 timeline can only ever run forwards. These are the
            # database's own statement of the handover order: a delivery code
            # cannot exist before a confirmed pickup, a delivery cannot be
            # confirmed before that code was released, and a protection window
            # cannot start before a confirmed delivery. Application services
            # enforce the same rules with locks and state checks; this is what
            # remains true if one of them is ever bypassed.
            models.CheckConstraint(
                condition=(
                    Q(delivery_code_available_at__isnull=True)
                    | Q(pickup_confirmed_at__isnull=False)
                ),
                name="deals_delivery_code_after_pickup",
            ),
            models.CheckConstraint(
                condition=(
                    Q(delivery_code_released_at__isnull=True)
                    | Q(delivery_code_available_at__isnull=False)
                ),
                name="deals_release_after_availability",
            ),
            models.CheckConstraint(
                condition=(
                    Q(delivery_confirmed_at__isnull=True)
                    | Q(delivery_code_released_at__isnull=False)
                ),
                name="deals_delivery_after_code_release",
            ),
            models.CheckConstraint(
                condition=(
                    Q(protection_ends_at__isnull=True)
                    | Q(delivery_confirmed_at__isnull=False)
                ),
                name="deals_protection_requires_delivery",
            ),
            models.CheckConstraint(
                condition=(
                    Q(no_show_party="")
                    | Q(
                        no_show_recorded_at__isnull=False,
                        no_show_recorded_by__isnull=False,
                    )
                ),
                name="deals_no_show_requires_actor",
            ),
        ]
        indexes = [
            models.Index(fields=["sender", "-created_at"], name="deals_sender_idx"),
            models.Index(fields=["traveler", "-created_at"], name="deals_traveler_idx"),
            models.Index(fields=["journey", "status"], name="deals_journey_status_idx"),
            models.Index(
                fields=["status", "protection_ends_at"],
                name="deals_protection_idx",
            ),
            models.Index(
                fields=["status", "delivery_code_available_at"],
                name="deals_code_release_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Deal#{self.id} ({self.status})"


class DealTermsSnapshot(models.Model):
    class Currency(models.TextChoices):
        EUR = "EUR", "Euro"
        DZD = "DZD", "Legacy Algerian dinar"

    deal = models.OneToOneField(
        Deal,
        on_delete=models.PROTECT,
        related_name="terms",
    )
    currency = models.CharField(max_length=3, choices=Currency.choices)
    traveler_reward_minor = models.PositiveBigIntegerField()
    commission_rate_bps = models.PositiveSmallIntegerField()
    platform_fee_minor = models.PositiveBigIntegerField()
    sender_total_minor = models.PositiveBigIntegerField()
    boost_amount_minor = models.PositiveBigIntegerField(default=0)
    boost_traveler_bonus_minor = models.PositiveBigIntegerField(default=0)
    boost_platform_fee_minor = models.PositiveBigIntegerField(default=0)
    business_settings_version = models.ForeignKey(
        "core.BusinessSettingsVersion",
        on_delete=models.PROTECT,
        related_name="deal_terms_snapshots",
        null=True,
        blank=True,
    )
    pricing_version = models.CharField(max_length=32)
    policy_snapshot = models.JSONField(default=dict, blank=True)
    is_legacy = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "deals_terms_snapshot"
        constraints = [
            models.CheckConstraint(
                condition=Q(commission_rate_bps__lte=10_000),
                name="deals_terms_commission_bps",
            ),
            models.CheckConstraint(
                condition=Q(
                    sender_total_minor=F("traveler_reward_minor")
                    + F("platform_fee_minor")
                ),
                name="deals_terms_total_sum",
            ),
            models.CheckConstraint(
                condition=Q(
                    boost_amount_minor=F("boost_traveler_bonus_minor")
                    + F("boost_platform_fee_minor")
                ),
                name="deals_terms_boost_total_sum",
            ),
            models.CheckConstraint(
                condition=(
                    Q(is_legacy=True)
                    | Q(currency="EUR", business_settings_version__isnull=False)
                ),
                name="deals_terms_new_currency_eur",
            ),
        ]

    def clean(self):
        super().clean()
        expected_fee = (
            self.traveler_reward_minor * self.commission_rate_bps + 9_999
        ) // 10_000
        if self.platform_fee_minor != expected_fee:
            raise ValidationError(
                {
                    "platform_fee_minor": (
                        "Platform fee must equal the ceiling of reward × rate / 10,000."
                    )
                }
            )

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Deal terms snapshots are immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def traveler_total_minor(self) -> int:
        return int(self.traveler_reward_minor) + int(self.boost_traveler_bonus_minor)

    @property
    def platform_total_minor(self) -> int:
        return int(self.platform_fee_minor) + int(self.boost_platform_fee_minor)

    @property
    def sender_total_with_boost_minor(self) -> int:
        return int(self.sender_total_minor) + int(self.boost_amount_minor)


class DealEvent(models.Model):
    """The Deal's immutable timeline.

    Every critical Phase 4 transition appends a row here and nothing ever
    updates one. Two rules bind what a payload may contain:

    * **No secrets.** A handover code -- plaintext, sealed or hashed -- never
      appears in a payload, and neither does recipient contact data. The
      timeline is readable by both parties and by admins, and
      `apps.deals.timeline` narrows it further per viewer.
    * **References, not copies.** Money, codes and evidence are named by id and
      by amount, so the timeline stays a durable index into the authoritative
      rows rather than a second, drifting copy of them.
    """

    class Kind(models.TextChoices):
        CREATED = "created", "Created"
        STATUS_CHANGED = "status_changed", "Status changed"
        CAPACITY_RESERVED = "capacity_reserved", "Capacity reserved"
        CAPACITY_RELEASED = "capacity_released", "Capacity released"
        # --- Phase 4 handover ---
        RECIPIENT_SET = "recipient_set", "Recipient details set"
        RECIPIENT_CHANGED = "recipient_changed", "Recipient details changed"
        PICKUP_CODE_ISSUED = "pickup_code_issued", "Pickup code issued"
        PICKUP_CODE_ROTATED = "pickup_code_rotated", "Pickup code rotated"
        PICKUP_CODE_FAILED = "pickup_code_failed", "Pickup code attempt failed"
        PICKUP_CODE_LOCKED = "pickup_code_locked", "Pickup code locked"
        PICKUP_CONFIRMED = "pickup_confirmed", "Pickup confirmed"
        DELIVERY_BUFFER_STARTED = (
            "delivery_buffer_started",
            "Delivery-code safety buffer started",
        )
        DELIVERY_CODE_RELEASED = (
            "delivery_code_released",
            "Delivery code released to the sender",
        )
        DELIVERY_CODE_ROTATED = "delivery_code_rotated", "Delivery code rotated"
        DELIVERY_CODE_FAILED = "delivery_code_failed", "Delivery code attempt failed"
        DELIVERY_CODE_LOCKED = "delivery_code_locked", "Delivery code locked"
        RECIPIENT_NOTIFICATION_QUEUED = (
            "recipient_notification_queued",
            "Recipient delivery-code notification queued",
        )
        RECIPIENT_NOTIFICATION_SENT = (
            "recipient_notification_sent",
            "Recipient delivery-code notification dispatched",
        )
        DELIVERY_CONFIRMED = "delivery_confirmed", "Delivery confirmed"
        # --- Phase 4 protection, payout and disputes ---
        PROTECTION_STARTED = "protection_started", "Protection window started"
        PROTECTION_EXPIRED = "protection_expired", "Protection window expired"
        PAYOUT_ELIGIBLE = "payout_eligible", "Payout became eligible"
        PAYOUT_STATUS_CHANGED = "payout_status_changed", "Payout status changed"
        DISPUTE_OPENED = "dispute_opened", "Dispute opened"
        DISPUTE_EVIDENCE_ADDED = "dispute_evidence_added", "Dispute evidence added"
        DISPUTE_STATUS_CHANGED = "dispute_status_changed", "Dispute status changed"
        DISPUTE_RESOLVED = "dispute_resolved", "Dispute resolved"
        # --- Phase 4 cancellation, no-show and ratings ---
        CANCELLATION_REQUESTED = "cancellation_requested", "Cancellation requested"
        CANCELLED_AFTER_FUNDING = (
            "cancelled_after_funding",
            "Cancelled after funding",
        )
        COMPENSATION_APPLIED = "compensation_applied", "Cancellation compensation"
        NO_SHOW_RECORDED = "no_show_recorded", "No-show recorded"
        RATING_SUBMITTED = "rating_submitted", "Rating submitted"
        RATING_REVEALED = "rating_revealed", "Ratings revealed"

    deal = models.ForeignKey(Deal, on_delete=models.PROTECT, related_name="events")
    kind = models.CharField(max_length=32, choices=Kind.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="deal_events_created",
    )
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "deals_event"
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["deal", "created_at"], name="deals_event_timeline_idx")
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Deal events are append-only.")
        return super().save(*args, **kwargs)


class DealLegAllocationQuerySet(models.QuerySet):
    def active(self, *, at=None):
        at = at or timezone.now()
        return self.filter(
            Q(status__in=("funded", "in_transit"))
            | Q(status="pending_payment", expires_at__gt=at)
            # Null is retained only for Phase 1/legacy rows and remains
            # conservative until explicitly released.
            | Q(status="pending_payment", expires_at__isnull=True)
        )


class DealLegAllocation(models.Model):
    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", "Pending payment"
        FUNDED = "funded", "Funded"
        IN_TRANSIT = "in_transit", "In transit"
        RELEASED = "released", "Released"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    deal = models.ForeignKey(
        Deal,
        on_delete=models.PROTECT,
        related_name="leg_allocations",
    )
    journey_leg = models.ForeignKey(
        "trips.JourneyLeg",
        on_delete=models.PROTECT,
        related_name="deal_allocations",
    )
    allocated_weight_kg = models.DecimalField(max_digits=8, decimal_places=3)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING_PAYMENT,
        db_index=True,
    )
    reserved_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    release_reason = models.CharField(max_length=64, blank=True, default="")

    objects = DealLegAllocationQuerySet.as_manager()

    class Meta:
        db_table = "deals_leg_allocation"
        ordering = ["journey_leg__position", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(allocated_weight_kg__gt=0),
                name="deals_allocation_positive_weight",
            ),
            models.UniqueConstraint(
                fields=["deal", "journey_leg"],
                name="deals_allocation_unique_leg",
            ),
        ]
        indexes = [
            models.Index(fields=["journey_leg", "status"], name="deals_leg_status_idx"),
            models.Index(
                fields=["status", "expires_at"], name="deals_allocation_expiry_idx"
            ),
        ]

    def __str__(self) -> str:
        return (
            f"Deal#{self.deal_id} leg#{self.journey_leg_id} "
            f"{self.allocated_weight_kg}kg"
        )


class DealRecipient(models.Model):
    """Who actually receives the parcel. Private Deal data, collected after funding.

    The recipient never needs a ShipTrip account: they are reached by email at
    the end of the delivery-code safety buffer and hand the code to the traveler
    in person. That makes this row the one place the platform holds a third
    party's contact details, so it is deliberately isolated from every discovery,
    matching, public Journey and guest-payer surface, and is serialized only to
    the Deal's own sender and to staff.

    The traveler is not shown the recipient's email or phone before pickup is
    confirmed; `apps.deals.serializers` decides that projection, and this model
    stores the full record exactly once.
    """

    deal = models.OneToOneField(
        Deal,
        on_delete=models.PROTECT,
        related_name="recipient",
    )
    full_name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=32, blank=True, default="")
    delivery_note = models.TextField(blank=True, default="", max_length=1000)
    communication_language = models.CharField(
        max_length=2,
        choices=CommunicationLanguage.choices,
        blank=True,
        default="",
        help_text=(
            "Language explicitly selected for recipient communication. Blank "
            "legacy rows resolve to English."
        ),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="deal_recipients_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="deal_recipients_updated",
    )
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "deals_recipient"
        constraints = [
            models.CheckConstraint(
                condition=~Q(full_name=""),
                name="deals_recipient_name_required",
            ),
            models.CheckConstraint(
                condition=~Q(email=""),
                name="deals_recipient_email_required",
            ),
        ]

    def __str__(self) -> str:
        return f"Recipient for Deal#{self.deal_id}"
