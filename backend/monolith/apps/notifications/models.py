from django.conf import settings
from django.db import models

import uuid

from apps.core.languages import CommunicationLanguage


class Notification(models.Model):
    """Persisted, per-recipient notification.

    Written by `apps.core.redis_bus.publish_after_commit` for every user id in
    the `targets` list, in the same `on_commit` step that publishes to Redis.
    The Go WS dispatcher fans the same payload live; this row is the
    persistent inbox the mobile client reads on cold start and after
    backgrounding.

    `event_id` matches `core_published_event.event_id` so we can correlate
    inbox rows with delivery receipts and the G6b audit table.
    """

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    channel = models.CharField(max_length=64, db_index=True)
    event_id = models.CharField(max_length=64, db_index=True)
    payload = models.JSONField(default=dict)
    read_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "notification"
        indexes = [
            models.Index(
                fields=("recipient", "-created_at"),
                name="notif_recipient_recent_idx",
            ),
            models.Index(
                fields=("recipient", "read_at"),
                name="notif_recipient_unread_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("recipient", "event_id"),
                name="notif_recipient_event_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"Notification(channel={self.channel}, recipient={self.recipient_id})"


class OutboundMessage(models.Model):
    """A durable transactional-message obligation.

    `Notification` is the in-app inbox and `redis_bus` is the live fan-out;
    neither is a promise. An email that must reach a recipient who has no
    ShipTrip account -- above all the delivery code -- cannot depend on an
    in-memory queue, so the obligation is a row here. Ordinary mail uses Redis
    only as transport; secret-bearing mail goes from this obligation to the
    trusted SMTP boundary without serializing its plaintext into Redis.

    The context column holds what a template needs and nothing secret. A
    handover code is referenced through `secret_ref` and resolved from its
    sealed row at render time, so the plaintext exists only inside the process
    that is building the message body. It is never stored here, never written to
    a `PublishedEvent`, and never logged.
    """

    class Kind(models.TextChoices):
        EMAIL_VERIFICATION = "email_verification", "Email verification"
        PASSWORD_RESET = "password_reset", "Password reset"
        ADMIN_INVITATION = "admin_invitation", "Admin invitation"
        KYC_STATUS = "kyc_status", "KYC status"
        FLIGHT_PROOF_STATUS = "flight_proof_status", "Flight proof status"
        PAYMENT_REQUIRED = "payment_required", "Payment required"
        PAYMENT_PROCESSING = "payment_processing", "Payment processing"
        PAYMENT_FAILED = "payment_failed", "Payment failed"
        PAYMENT_SUCCEEDED = "payment_succeeded", "Payment succeeded"
        GUEST_PAYMENT = "guest_payment", "Guest payment"
        REFUND_STATUS = "refund_status", "Refund status"
        RECIPIENT_DELIVERY_CODE = (
            "recipient_delivery_code",
            "Delivery code for the recipient",
        )
        PICKUP_CONFIRMED = "pickup_confirmed", "Pickup confirmed"
        DELIVERY_CODE_RELEASED = (
            "delivery_code_released",
            "Delivery code available to the sender",
        )
        DELIVERY_CONFIRMED = "delivery_confirmed", "Delivery confirmed"
        PROTECTION_ENDING = "protection_ending", "Protection window ending"
        PROTECTION_ENDED = "protection_ended", "Protection window ended"
        DISPUTE_OPENED = "dispute_opened", "Dispute opened"
        EVIDENCE_REQUEST = "evidence_request", "Evidence requested"
        DISPUTE_RESOLVED = "dispute_resolved", "Dispute resolved"
        PAYOUT_STATUS = "payout_status", "Payout status"
        DEAL_CANCELLED = "deal_cancelled", "Deal cancelled"
        RATING_AVAILABLE = "rating_available", "Rating available"
        SECURITY_EVENT = "security_event", "Security/account event"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        DISPATCHED = "dispatched", "Dispatched to the transport"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    #: Idempotency handle. Two attempts to arm the same logical message resolve
    #: to one row, which is what "exactly once" means here in practice.
    key = models.CharField(max_length=160, unique=True)
    kind = models.CharField(max_length=32, choices=Kind.choices, db_index=True)
    channel = models.CharField(max_length=16, default="email")
    to_email = models.EmailField()
    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="outbound_messages",
        help_text="Null for a parcel recipient, who needs no ShipTrip account.",
    )
    deal = models.ForeignKey(
        "deals.Deal",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="outbound_messages",
    )
    context = models.JSONField(default=dict, blank=True)
    language = models.CharField(
        max_length=2,
        choices=CommunicationLanguage.choices,
        default=CommunicationLanguage.ENGLISH,
        db_index=True,
        help_text=(
            "Locale snapshot captured when the logical email obligation is "
            "created; later profile changes do not alter queued mail."
        ),
    )
    #: `<resolver>:<id>` naming a secret to be resolved at render time, e.g.
    #: `handover_code:41`. Never the secret itself.
    secret_ref = models.CharField(max_length=64, blank=True, default="")

    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=10)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_error = models.CharField(max_length=500, blank=True, default="")
    #: The `event_id` of the stream record that carried it, for correlation
    #: with `core_published_event`.
    transport_event_id = models.CharField(max_length=64, blank=True, default="")
    dispatched_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "notification_outbound_message"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["status", "next_attempt_at"], name="outbound_due_idx"
            ),
            models.Index(fields=["deal", "kind"], name="outbound_deal_kind_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status="pending")
                | models.Q(status="cancelled")
                | models.Q(dispatched_at__isnull=False)
                | models.Q(status="failed"),
                name="outbound_dispatched_requires_timestamp",
            ),
        ]

    def __str__(self) -> str:
        return f"OutboundMessage#{self.pk} {self.kind} ({self.status})"


class OutboundSecret(models.Model):
    """Short-lived encrypted material needed only to render a secure email.

    Verification, reset and invitation capabilities remain hash-only in their
    owning domain rows. This vault holds a separately encrypted delivery copy
    long enough for the durable email job to survive a worker or Redis restart,
    then erases the ciphertext after the SMTP provider accepts the message.
    The canonical invitation token is still SHA-256 hashed; this row is only a
    short-lived, encrypted handoff to the final email renderer.
    """

    class Purpose(models.TextChoices):
        EMAIL_VERIFICATION = "email_verification", "Email verification"
        PASSWORD_RESET = "password_reset", "Password reset"
        ADMIN_INVITATION = "admin_invitation", "Admin invitation"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=160, unique=True)
    purpose = models.CharField(max_length=32, choices=Purpose.choices)
    sealed_value = models.TextField()
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notification_outbound_secret"
        indexes = [
            models.Index(
                fields=("purpose", "expires_at"),
                name="outbound_secret_exp_idx",
            )
        ]

    def __str__(self) -> str:
        return f"OutboundSecret#{self.pk} {self.purpose}"
