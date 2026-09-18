"""ShipTrip V1 financial schema.

The legacy `apps.payments` schema binds one `PaymentIntent` to one accepted
`Offer` and carries DZD as if it were marketplace truth. It stays in the
database as history and keeps serving legacy rows; nothing here reinterprets
it and nothing here writes to it.

The V1 model separates two things the legacy schema conflated:

``PaymentOrder``
    The **business obligation**, always in canonical EUR cents. It knows what
    is owed, what has been credited without cash (a posting deposit rolled into
    a deal), what has been captured, and what has been refunded. It does not
    know or care which rail the money arrives on.

``PaymentAttempt``
    One **provider attempt** against that obligation. Stripe in EUR, Chargily
    in DZD at an immutable snapshotted rate, or the test-only mock. An order may
    have many attempts over its life; provider semantics never become the
    canonical business truth.

Everything else hangs off that split:

* ``PaymentProviderEvent`` is the webhook idempotency ledger. Provider event
  IDs are unique per provider, so a duplicate or out-of-order delivery is a
  no-op rather than a second state change.
* ``PaymentRefund`` records money going back out, bounded by a database check
  that total refunds never exceed total captures.
* ``GuestPaymentLink`` lets a third party pay a sender's order without any
  ShipTrip account and without acquiring any authority over the Deal. Only a
  hash of the token is stored.
* ``LedgerTransaction`` / ``LedgerEntry`` are the append-only double-entry
  record. Every financial fact writes a balanced set of entries; corrections
  are new compensating entries, never edits.
* ``Payout`` is the provider-agnostic traveler obligation. Phase 3 creates it
  and deliberately cannot release it — release eligibility is Phase 4.
* ``ScheduledJob`` is the durable obligation store for delayed financial work.
  Redis may accelerate scheduling; this table is the source of truth.

Money is integer EUR cents everywhere. There is no float arithmetic in this
app, and no column stores a currency other than EUR for a canonical amount.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q

from apps.core.languages import CommunicationLanguage
from .payout_models import (  # noqa: F401 -- Django model registration/public imports
    FinancialMode,
    ManualPayoutReceipt,
    StripePayoutAccount,
    PayoutIdentityAttestation,
    PayoutIdentityRevocation,
    PayoutIdentityReviewAssignment,
    PayoutEvidence,
    DzdPayoutProfileRevision,
    PayoutProfileReview,
    PayoutMethodVersion,
    PayoutAmountRevision,
    PayoutInstructionAmendment,
    PayoutInstructionConfirmation,
    PayoutAttempt,
    PayoutProviderOperation,
    PayoutFundingAllocation,
    PayoutFundingRelease,
    StripeDisbursement,
    StripeDisbursementAllocation,
    FinanceHold,
    ProviderDispute,
    PayoutEvent,
)


class PaymentProvider(models.TextChoices):
    """Rails a PaymentAttempt can run on.

    MOCK exists for unit/integration tests and local development only. The
    provider registry refuses to hand it out unless the deployment has
    explicitly opted in, and `config.settings.prod` refuses to boot if that
    opt-in is set. There is no fallback path from STRIPE or CHARGILY to MOCK.
    """

    STRIPE = "stripe", "Stripe"
    CHARGILY = "chargily", "Chargily"
    MOCK = "mock", "Mock (tests/local only)"


class PaymentOrder(models.Model):
    """A canonical EUR obligation owned by one user.

    The four money columns are the whole state:

    ``amount_eur_cents``      what is owed in total
    ``credited_eur_cents``    discharged without new cash (posting-deposit credit)
    ``paid_eur_cents``        captured through succeeded attempts
    ``refunded_eur_cents``    sent back out again

    ``outstanding_eur_cents`` is derived, never stored, so it cannot drift.
    Database check constraints — not application code — enforce that an order
    can never over-collect (`credited + paid <= amount`) and that refunds can
    never exceed captures (`refunded <= paid`).
    """

    class Purpose(models.TextChoices):
        POSTING_DEPOSIT = "posting_deposit", "Posting deposit"
        DEAL_BALANCE = "deal_balance", "Deal balance"
        BOOST = "boost", "Boost"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PARTIALLY_PAID = "partially_paid", "Partially paid"
        PAID = "paid", "Paid"
        REFUND_PENDING = "refund_pending", "Refund pending"
        PARTIALLY_REFUNDED = "partially_refunded", "Partially refunded"
        REFUNDED = "refunded", "Refunded"
        CANCELLED = "cancelled", "Cancelled"

    #: Statuses in which new provider money may still be collected.
    COLLECTABLE_STATUSES = ("pending", "partially_paid")
    #: Statuses that no longer accept new checkouts.
    CLOSED_STATUSES = (
        "paid",
        "refund_pending",
        "partially_refunded",
        "refunded",
        "cancelled",
    )

    #: Opaque external handle. Guest surfaces and client deep links quote this
    #: instead of the primary key so an order cannot be enumerated.
    public_reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payment_orders",
        help_text="The user who owes this obligation. Always the sender in V1.",
    )
    purpose = models.CharField(max_length=20, choices=Purpose.choices, db_index=True)
    currency = models.CharField(
        max_length=3,
        default="EUR",
        editable=False,
        help_text="Canonical marketplace currency. Always EUR.",
    )

    amount_eur_cents = models.PositiveBigIntegerField(
        validators=[MinValueValidator(1)],
        help_text="The gross obligation in canonical EUR cents.",
    )
    credited_eur_cents = models.PositiveBigIntegerField(
        default=0,
        help_text="Discharged without new cash, e.g. a posting-deposit credit.",
    )
    paid_eur_cents = models.PositiveBigIntegerField(
        default=0,
        help_text="Captured through succeeded provider attempts.",
    )
    refunded_eur_cents = models.PositiveBigIntegerField(
        default=0,
        help_text="Refunded out of captured funds. Never exceeds paid_eur_cents.",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    delivery_request = models.ForeignKey(
        "parcels.DeliveryRequest",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payment_orders",
    )
    deal = models.ForeignKey(
        "deals.Deal",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payment_orders",
    )
    #: Set by `apps.boosts` to the purchase this obligation pays for.
    boost_reference = models.CharField(max_length=64, blank=True, default="")

    #: The posting-deposit order whose funds were credited into this one. The
    #: one-to-one link is what makes double-crediting structurally impossible:
    #: a deposit can be the credit source of at most one balance order.
    credit_source = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="credited_into",
    )

    business_settings_version = models.ForeignKey(
        "core.BusinessSettingsVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payment_orders",
    )
    terms_snapshot = models.JSONField(
        default=dict,
        blank=True,
        help_text="Immutable policy/economics inputs used to compute this amount.",
    )

    paid_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "finance_payment_order"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "-created_at"], name="fin_order_owner_idx"),
            models.Index(fields=["status", "purpose"], name="fin_order_status_idx"),
            models.Index(
                fields=["delivery_request", "purpose"], name="fin_order_request_idx"
            ),
            models.Index(fields=["deal", "purpose"], name="fin_order_deal_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(currency="EUR"),
                name="fin_order_currency_eur",
            ),
            models.CheckConstraint(
                condition=Q(amount_eur_cents__gt=0),
                name="fin_order_amount_positive",
            ),
            # An order can never collect more than it owes. This is the
            # database-level guard behind "no free or double-funded Deal".
            models.CheckConstraint(
                condition=Q(
                    amount_eur_cents__gte=F("credited_eur_cents") + F("paid_eur_cents")
                ),
                name="fin_order_no_overcollection",
            ),
            # The refund invariant, enforced where application code cannot
            # forget it.
            models.CheckConstraint(
                condition=Q(refunded_eur_cents__lte=F("paid_eur_cents")),
                name="fin_order_refund_within_capture",
            ),
            models.CheckConstraint(
                condition=(
                    Q(purpose="posting_deposit", delivery_request__isnull=False)
                    | Q(purpose="deal_balance", deal__isnull=False)
                    | Q(purpose="boost", delivery_request__isnull=False)
                ),
                name="fin_order_reference_required",
            ),
            # At most one live posting-deposit obligation per request.
            models.UniqueConstraint(
                fields=["delivery_request"],
                condition=Q(purpose="posting_deposit") & ~Q(status="cancelled"),
                name="fin_order_one_live_deposit_per_request",
            ),
            # At most one live balance obligation per deal.
            models.UniqueConstraint(
                fields=["deal"],
                condition=Q(purpose="deal_balance") & ~Q(status="cancelled"),
                name="fin_order_one_live_balance_per_deal",
            ),
        ]

    @property
    def outstanding_eur_cents(self) -> int:
        """What still has to arrive as cash. Derived, never stored."""

        return max(
            0,
            int(self.amount_eur_cents)
            - int(self.credited_eur_cents)
            - int(self.paid_eur_cents),
        )

    @property
    def net_paid_eur_cents(self) -> int:
        return int(self.paid_eur_cents) - int(self.refunded_eur_cents)

    @property
    def is_collectable(self) -> bool:
        return self.status in self.COLLECTABLE_STATUSES

    def __str__(self) -> str:
        return (
            f"Order#{self.pk} {self.purpose} {self.amount_eur_cents}c "
            f"({self.status})"
        )


class PaymentAttempt(models.Model):
    """One provider attempt against a PaymentOrder.

    ``amount_eur_cents`` is what this attempt is trying to collect in canonical
    terms. ``provider_amount_minor`` is what the provider was actually asked to
    charge, in that provider's own unit — Stripe cents for EUR, whole dinars for
    Chargily DZD — with ``provider_amount_exponent`` recording which.

    For a non-EUR rail the FX columns are an immutable snapshot. Changing the
    admin rate afterwards changes nothing here: reconciliation, refunds and
    reporting all read this row's own numbers.
    """

    class Status(models.TextChoices):
        CREATED = "created", "Created"
        CHECKOUT_PENDING = "checkout_pending", "Checkout pending"
        PROCESSING = "processing", "Processing"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"

    class OperationalResolution(models.TextChoices):
        RESOLVED = "resolved", "Resolved"
        DISMISSED = "dismissed", "Dismissed"
        SUPERSEDED = "superseded", "Superseded"

    #: Statuses in which the attempt may still become succeeded.
    OPEN_STATUSES = ("created", "checkout_pending", "processing")
    TERMINAL_STATUSES = ("succeeded", "failed", "expired", "cancelled")

    provider_mode = models.CharField(
        max_length=16,
        choices=FinancialMode.choices,
        default=FinancialMode.LEGACY_UNKNOWN,
    )
    provider_charge_id = models.CharField(max_length=255, blank=True, default="")
    mode_evidence = models.CharField(max_length=64, blank=True, default="")

    order = models.ForeignKey(
        PaymentOrder,
        on_delete=models.PROTECT,
        related_name="attempts",
    )
    provider = models.CharField(
        max_length=16, choices=PaymentProvider.choices, db_index=True
    )

    payer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payment_attempts",
        help_text="Null when a guest paid on the owner's behalf.",
    )
    guest_link = models.ForeignKey(
        "finance.GuestPaymentLink",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="attempts",
    )
    guest_email = models.EmailField(
        blank=True,
        default="",
        help_text="Provider-reported guest payer email. Never a ShipTrip identity.",
    )

    amount_eur_cents = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    payment_currency = models.CharField(max_length=3)
    provider_amount_minor = models.PositiveBigIntegerField()
    provider_amount_exponent = models.PositiveSmallIntegerField(
        default=2,
        help_text="Minor units per major unit as 10**exponent. EUR=2, DZD=0.",
    )

    fx_rate_micros = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Immutable EUR->payment-currency rate x 1_000_000. Null for an "
            "EUR-native attempt."
        ),
    )
    fx_source = models.CharField(max_length=64, blank=True, default="")
    fx_settings_version = models.ForeignKey(
        "core.BusinessSettingsVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payment_attempts",
    )
    fx_snapshot_at = models.DateTimeField(null=True, blank=True)

    provider_session_id = models.CharField(max_length=255, blank=True, default="")
    provider_payment_id = models.CharField(max_length=255, blank=True, default="")
    idempotency_key = models.CharField(
        max_length=128,
        help_text="What we sent the provider. Stable across our own retries.",
    )
    checkout_url = models.URLField(max_length=1024, blank=True, default="")

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CREATED,
        db_index=True,
    )
    failure_code = models.CharField(max_length=64, blank=True, default="")
    failure_message = models.CharField(max_length=255, blank=True, default="")
    #: Set when a success arrived that the order could not absorb (order already
    #: covered, or cancelled). The money is real; the order was not funded by it
    #: and an automatic refund is raised instead.
    is_unapplied = models.BooleanField(
        default=False,
        help_text="Succeeded but not applied to the order; awaiting refund.",
    )
    operational_resolution = models.CharField(
        max_length=16,
        choices=OperationalResolution.choices,
        blank=True,
        default="",
        db_index=True,
        help_text=(
            "Operator attention state only. It never changes the provider or "
            "financial outcome recorded above."
        ),
    )
    operational_resolved_at = models.DateTimeField(null=True, blank=True)
    operational_resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="resolved_payment_attempt_alerts",
    )
    operational_resolution_reason = models.CharField(
        max_length=500, blank=True, default=""
    )

    expires_at = models.DateTimeField(null=True, blank=True)
    succeeded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "finance_payment_attempt"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["order", "-created_at"], name="fin_attempt_order_idx"),
            models.Index(
                fields=["provider", "status"], name="fin_attempt_provider_idx"
            ),
            models.Index(
                fields=["status", "expires_at"], name="fin_attempt_expiry_idx"
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_session_id"],
                condition=~Q(provider_session_id=""),
                name="fin_attempt_unique_provider_session",
            ),
            models.UniqueConstraint(
                fields=["provider", "provider_payment_id"],
                condition=~Q(provider_payment_id=""),
                name="fin_attempt_unique_provider_payment",
            ),
            models.UniqueConstraint(
                fields=["provider", "idempotency_key"],
                name="fin_attempt_unique_idempotency",
            ),
            # Exactly one open attempt per order at a time. Switching provider
            # cancels the previous attempt through the service, so a sender can
            # never have two live checkouts racing to fund the same obligation.
            models.UniqueConstraint(
                fields=["order"],
                condition=Q(status__in=["created", "checkout_pending", "processing"]),
                name="fin_attempt_one_open_per_order",
            ),
            models.CheckConstraint(
                condition=Q(amount_eur_cents__gt=0),
                name="fin_attempt_amount_positive",
            ),
            models.CheckConstraint(
                condition=(
                    Q(payment_currency="EUR", fx_rate_micros__isnull=True)
                    | (~Q(payment_currency="EUR") & Q(fx_rate_micros__isnull=False))
                ),
                name="fin_attempt_fx_required_for_conversion",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        operational_resolution="",
                        operational_resolved_at__isnull=True,
                        operational_resolved_by__isnull=True,
                        operational_resolution_reason="",
                    )
                    | (
                        ~Q(operational_resolution="")
                        & Q(operational_resolved_at__isnull=False)
                        & ~Q(operational_resolution_reason="")
                    )
                ),
                name="fin_attempt_resolution_complete",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"Attempt#{self.pk} {self.provider} order={self.order_id} "
            f"({self.status})"
        )


class PaymentProviderEvent(models.Model):
    """Append-only webhook log and the idempotency key for event processing.

    A provider may deliver the same event many times, out of order, or after
    the provider has been disabled for new checkouts. Uniqueness on
    ``(provider, provider_event_id)`` prevents duplicate economic identity,
    while ``processing_result`` distinguishes receipt from successful
    application. A duplicate delivery resumes a received/processing/retryable
    row; only an applied or intentionally ignored event is a terminal no-op.

    ``payload`` is scrubbed before storage — see `apps.finance.webhooks`. It
    never holds card data, and it never holds a webhook secret or guest token.
    """

    class ProcessingResult(models.TextChoices):
        RECEIVED = "received", "Received"
        PROCESSING = "processing", "Processing"
        APPLIED = "applied", "Applied"
        IGNORED = "ignored", "Ignored"
        RETRYABLE = "retryable", "Retryable"
        FAILED = "failed", "Failed"

    provider = models.CharField(max_length=16, choices=PaymentProvider.choices)
    provider_mode = models.CharField(
        max_length=16,
        choices=FinancialMode.choices,
        default=FinancialMode.LEGACY_UNKNOWN,
    )
    provider_account_id = models.CharField(max_length=255, blank=True, default="")
    endpoint_scope = models.CharField(max_length=24, default="platform")
    api_version = models.CharField(max_length=64, blank=True, default="")
    provider_event_id = models.CharField(max_length=255)
    event_type = models.CharField(max_length=128, blank=True, default="")
    # H2 provenance: which provider object the event was about, so a connected
    # account event can be correlated without re-reading the payload. Opaque
    # ids and Stripe's own object names only.
    object_type = models.CharField(max_length=64, blank=True, default="")
    object_id = models.CharField(max_length=255, blank=True, default="")

    attempt = models.ForeignKey(
        PaymentAttempt,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="provider_events",
    )
    order = models.ForeignKey(
        PaymentOrder,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="provider_events",
    )

    signature_verified = models.BooleanField(default=False)
    payload = models.JSONField(default=dict, blank=True)
    payload_fingerprint = models.CharField(max_length=64, blank=True, default="")
    normalized_event = models.JSONField(
        default=dict,
        blank=True,
        help_text="Safe normalized fields required to re-drive processing.",
    )
    processing_result = models.CharField(
        max_length=12,
        choices=ProcessingResult.choices,
        default=ProcessingResult.RECEIVED,
    )
    processing_note = models.CharField(max_length=255, blank=True, default="")
    processing_attempts = models.PositiveSmallIntegerField(default=0)
    last_error_code = models.CharField(max_length=64, blank=True, default="")
    last_error_message = models.CharField(max_length=500, blank=True, default="")

    received_at = models.DateTimeField(auto_now_add=True)
    processing_started_at = models.DateTimeField(null=True, blank=True)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "finance_provider_event"
        ordering = ["-received_at"]
        indexes = [
            models.Index(
                fields=["provider", "-received_at"], name="fin_event_provider_idx"
            ),
            models.Index(fields=["attempt", "-received_at"], name="fin_event_att_idx"),
            models.Index(
                fields=["processing_result", "next_retry_at"],
                name="fin_event_recovery_idx",
            ),
            models.Index(
                fields=["endpoint_scope", "provider_account_id", "-received_at"],
                name="fin_event_scope_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_event_id"],
                name="fin_event_unique_provider_event",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.provider}/{self.event_type} {self.provider_event_id}"


class PaymentRefund(models.Model):
    """Money going back out against a specific captured attempt.

    Refunds are additive rows, never edits: the original payment survives
    untouched. The order-level check constraint bounds the total, and
    ``idempotency_key`` makes a retried refund request a no-op.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    provider_mode = models.CharField(
        max_length=16,
        choices=FinancialMode.choices,
        default=FinancialMode.LEGACY_UNKNOWN,
    )

    class Reason(models.TextChoices):
        DEPOSIT_EXPIRY = "deposit_expiry", "Request expired unmatched"
        SENDER_CANCELLED = "sender_cancelled", "Sender cancelled before acceptance"
        UNAPPLIED_PAYMENT = "unapplied_payment", "Payment could not be applied"
        DEAL_CANCELLED = "deal_cancelled", "Deal cancelled before funding"
        ADMIN = "admin", "Administrative refund"
        # --- Phase 4 ---
        DEAL_CANCELLED_FUNDED = (
            "deal_cancelled_funded",
            "Deal cancelled after funding",
        )
        DISPUTE_RESOLUTION = "dispute_resolution", "Dispute resolution"
        NO_SHOW = "no_show", "Verified no-show"
        BOOST_UNUSABLE = "boost_unusable", "Boost paid but no longer usable"

    order = models.ForeignKey(
        PaymentOrder, on_delete=models.PROTECT, related_name="refunds"
    )
    attempt = models.ForeignKey(
        PaymentAttempt, on_delete=models.PROTECT, related_name="refunds"
    )
    amount_eur_cents = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    provider = models.CharField(max_length=16, choices=PaymentProvider.choices)
    provider_refund_id = models.CharField(max_length=255, blank=True, default="")
    idempotency_key = models.CharField(max_length=128, unique=True)
    reason = models.CharField(max_length=24, choices=Reason.choices)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    failure_code = models.CharField(max_length=64, blank=True, default="")
    failure_message = models.CharField(max_length=255, blank=True, default="")
    processing_attempts = models.PositiveSmallIntegerField(default=0)
    processing_started_at = models.DateTimeField(null=True, blank=True)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    last_provider_check_at = models.DateTimeField(null=True, blank=True)
    requires_manual_action = models.BooleanField(default=False, db_index=True)

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payment_refunds_requested",
        help_text="Null when the platform raised the refund automatically.",
    )
    #: Set only when an operator settled the refund by hand, which is the whole
    #: path for a rail with no refund API (Chargily). A refund that leaves the
    #: platform without an actor and a reference is an untraceable movement of
    #: money, so the constraint below refuses one.
    settled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payment_refunds_settled",
    )
    settlement_reference = models.CharField(max_length=128, blank=True, default="")
    settlement_note = models.CharField(max_length=255, blank=True, default="")
    succeeded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "finance_payment_refund"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["order", "-created_at"], name="fin_refund_order_idx"),
            models.Index(fields=["status"], name="fin_refund_status_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_refund_id"],
                condition=~Q(provider_refund_id=""),
                name="fin_refund_unique_provider_refund",
            ),
            models.CheckConstraint(
                condition=Q(amount_eur_cents__gt=0),
                name="fin_refund_amount_positive",
            ),
            # A manually settled refund must carry its evidence: who sent it and
            # under what reference. Provider-settled refunds carry the provider
            # refund id instead.
            models.CheckConstraint(
                condition=(Q(settled_by__isnull=True) | ~Q(settlement_reference="")),
                name="fin_refund_manual_requires_reference",
            ),
        ]

    def __str__(self) -> str:
        return f"Refund#{self.pk} order={self.order_id} {self.amount_eur_cents}c"


class GuestPaymentLink(models.Model):
    """A single-purpose, expiring capability to pay one PaymentOrder.

    Holding this token lets someone pay. It does not make them a party: it
    grants no Deal ownership, no chat access, no dispute authority and no view
    of the recipient, the addresses or the counterparty. The guest surface
    returns the amount, the currency and a generic description — nothing else.

    ``token_hash`` is what a guest's token is looked up by. The plaintext is
    never stored: it is re-derived for the order owner from ``token_seed`` and
    a key that lives only in the application's settings, so the owner can share
    the same live link again instead of being handed a replacement every time
    they open the sheet. A database read alone still cannot reconstruct a
    working link. Links issued before the seed existed have an empty seed and
    simply cannot be shown again; the owner replaces them.
    """

    order = models.ForeignKey(
        PaymentOrder, on_delete=models.PROTECT, related_name="guest_links"
    )
    token_hash = models.CharField(
        max_length=64,
        unique=True,
        help_text="SHA-256 hex digest of the token. The plaintext is never stored.",
    )
    token_seed = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text=(
            "Random input the owner's token is re-derived from with an "
            "application key. Useless without that key; empty on links issued "
            "before J7C, which cannot be shown again."
        ),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="guest_payment_links_created",
    )
    label = models.CharField(
        max_length=80,
        blank=True,
        default="",
        help_text="Owner's own note, e.g. 'Dad'. Never shown to the guest.",
    )
    communication_language = models.CharField(
        max_length=2,
        choices=CommunicationLanguage.choices,
        default=CommunicationLanguage.ENGLISH,
        help_text="Language snapshotted when the owner creates the guest payment link.",
    )
    expires_at = models.DateTimeField(db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "finance_guest_payment_link"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["order", "-created_at"], name="fin_guest_order_idx"),
        ]
        constraints = [
            # One live link per order. Issuing a new one revokes the previous.
            models.UniqueConstraint(
                fields=["order"],
                condition=Q(revoked_at__isnull=True) & Q(consumed_at__isnull=True),
                name="fin_guest_one_live_link_per_order",
            ),
        ]

    def __str__(self) -> str:
        return f"GuestLink#{self.pk} order={self.order_id}"


class LedgerAccount(models.TextChoices):
    """Accounts in the V1 double-entry ledger.

    Sign convention: an entry is positive when it increases an asset and
    negative when it increases a liability or recognises revenue. Every
    transaction's entries therefore sum to exactly zero, which is what makes
    "money appeared from nowhere" a detectable condition rather than a hope.
    """

    PROVIDER_CLEARING = "provider_clearing", "Provider clearing (asset)"
    SENDER_DEPOSIT = "sender_deposit", "Posting deposit held (liability)"
    DEAL_FUNDS = "deal_funds", "Deal funds held (liability)"
    TRAVELER_PAYABLE = "traveler_payable", "Traveler payable (liability)"
    PLATFORM_COMMISSION = "platform_commission", "Platform commission (revenue)"
    # --- H3: where externally committed EUR actually sits -----------------
    #: Money that has left the platform's Stripe balance and now sits in a
    #: Traveler's connected account. Still ShipTrip's asset, still owed to the
    #: Traveler: a Transfer does not discharge the payable.
    CONNECT_FUNDS = "connect_funds", "Connected account funds (asset)"
    #: Money a bank payout has taken out of the connected account and not yet
    #: delivered. Discharges the payable only when the provider says `paid`.
    PAYOUT_IN_TRANSIT = "payout_in_transit", "Bank payout in transit (asset)"


class LedgerTransaction(models.Model):
    """One balanced financial fact.

    ``key`` is the idempotency handle. A replayed webhook, a re-run scheduled
    job or a double-submitted admin action resolves to the same key and is
    refused by the unique index before any entry is written.
    """

    provider_mode = models.CharField(
        max_length=16,
        choices=FinancialMode.choices,
        default=FinancialMode.LEGACY_UNKNOWN,
    )

    class Kind(models.TextChoices):
        CUSTOMER_PAYMENT = "customer_payment", "Customer payment"
        DEPOSIT_CREDIT = "deposit_credit", "Posting-deposit credit"
        DEAL_FUNDING = "deal_funding", "Deal funding"
        BOOST_BINDING = "boost_binding", "Boost funds binding"
        BOOST_ALLOCATION = "boost_allocation", "Boost allocation"
        REFUND = "refund", "Refund"
        PAYOUT = "payout", "Payout"
        CORRECTION = "correction", "Correction / reversal"

    key = models.CharField(max_length=160, unique=True)
    kind = models.CharField(max_length=24, choices=Kind.choices, db_index=True)
    #: Set on a compensating transaction to name what it reverses. History is
    #: never edited; it is corrected by a new, linked row.
    reverses = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reversed_by",
    )
    note = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "finance_ledger_transaction"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["kind", "-created_at"], name="fin_ltx_kind_idx"),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Ledger transactions are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Ledger transactions are append-only; post a correction instead."
        )

    def __str__(self) -> str:
        return f"LedgerTx#{self.pk} {self.kind}"


class LedgerEntry(models.Model):
    """One signed leg of a LedgerTransaction. Append-only."""

    transaction = models.ForeignKey(
        LedgerTransaction, on_delete=models.PROTECT, related_name="entries"
    )
    account = models.CharField(max_length=24, choices=LedgerAccount.choices)
    amount_eur_cents = models.BigIntegerField(
        help_text="Signed. + increases an asset, - increases a liability/revenue."
    )
    currency = models.CharField(max_length=3, default="EUR", editable=False)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        help_text="Whose sub-ledger this leg belongs to, when it is per-user.",
    )
    order = models.ForeignKey(
        PaymentOrder,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
    )
    attempt = models.ForeignKey(
        PaymentAttempt,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
    )
    refund = models.ForeignKey(
        PaymentRefund,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
    )
    payout = models.ForeignKey(
        "finance.Payout",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
    )
    deal = models.ForeignKey(
        "deals.Deal",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
    )
    note = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "finance_ledger_entry"
        ordering = ["transaction_id", "id"]
        indexes = [
            models.Index(fields=["account", "user"], name="fin_ledger_acct_user_idx"),
            models.Index(fields=["deal", "account"], name="fin_ledger_deal_idx"),
            models.Index(fields=["order"], name="fin_ledger_order_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(currency="EUR"),
                name="fin_ledger_currency_eur",
            ),
            models.CheckConstraint(
                condition=~Q(amount_eur_cents=0),
                name="fin_ledger_amount_nonzero",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError(
                "Ledger entries are append-only; post a compensating entry."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Ledger entries are append-only.")

    def __str__(self) -> str:
        return f"{self.account} {self.amount_eur_cents:+d} tx={self.transaction_id}"


class TravelerPayoutMethod(models.Model):
    """A traveler's declared destination for earnings, plus its real capability.

    Nothing here assumes a country implies a capability. ``capabilities`` holds
    what the provider actually reported, refreshed through the provider
    adapter; ``payouts_enabled`` is only true when the provider says so. When no
    method reports a live automatic capability the payout falls back to the
    manual queue.
    """

    class Method(models.TextChoices):
        STRIPE_CONNECT = "stripe_connect", "Stripe connected account"
        MANUAL = "manual", "Manual settlement"

    class Status(models.TextChoices):
        SETUP_REQUIRED = "setup_required", "Setup required"
        PENDING_REVIEW = "pending_review", "Pending review"
        READY = "ready", "Ready"
        NEEDS_ATTENTION = "needs_attention", "Needs attention"
        UNAVAILABLE = "unavailable", "Unavailable"
        DISABLED = "disabled", "Disabled"

    public_reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    currency = models.CharField(max_length=3, blank=True, default="")
    enabled = models.BooleanField(default=False)
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.SETUP_REQUIRED
    )
    status_reason = models.CharField(max_length=64, blank=True, default="")
    current_version = models.OneToOneField(
        "finance.PayoutMethodVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="current_for",
    )
    revision = models.PositiveBigIntegerField(default=0)

    traveler = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payout_methods",
    )
    method = models.CharField(max_length=20, choices=Method.choices)
    provider_account_id = models.CharField(max_length=255, blank=True, default="")
    country_code = models.CharField(max_length=2, blank=True, default="")
    payouts_enabled = models.BooleanField(default=False)
    capabilities = models.JSONField(default=dict, blank=True)
    capability_checked_at = models.DateTimeField(null=True, blank=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "finance_traveler_payout_method"
        ordering = ["-is_default", "-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(currency="", current_version__isnull=True, enabled=False)
                | Q(method="manual", currency="DZD")
                | Q(method="stripe_connect", currency="EUR"),
                name="fin_payout_method_pairing",
            ),
            models.UniqueConstraint(
                fields=["traveler", "method"],
                name="fin_payout_method_unique_per_traveler",
            ),
            models.UniqueConstraint(
                fields=["traveler"],
                condition=Q(is_default=True),
                name="fin_payout_method_one_default",
            ),
        ]

    def __str__(self) -> str:
        return f"PayoutMethod {self.method} traveler={self.traveler_id}"


class Payout(models.Model):
    """The traveler's EUR earnings obligation for one Deal.

    Phase 3 built the record and the gate; Phase 4 built the only key that opens
    it. A payout still starts ``not_eligible``, and the single normal path out
    is `apps.finance.payout_release.evaluate_payout_release`: a confirmed
    delivery, an expired protection window, no active dispute and a financial
    state that reconciles. A dispute moves it to ``frozen`` instead, and
    `fin_payout_release_requires_eligibility` keeps the boundary structural.
    """

    class Status(models.TextChoices):
        NOT_ELIGIBLE = "not_eligible", "Not eligible (protection window open)"
        BLOCKED = "blocked", "Blocked"
        SENT = "sent", "Sent"
        ELIGIBLE = "eligible", "Eligible"
        SCHEDULED = "scheduled", "Scheduled"
        PROCESSING = "processing", "Processing"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"
        #: An active dispute holds the money. Distinct from `not_eligible`,
        #: which only means the protection window has not closed yet.
        FROZEN = "frozen", "Frozen by a dispute"

    #: Statuses from which a dispute must pull the payout back.
    RELEASABLE_STATUSES = ("eligible", "scheduled", "processing")
    #: Statuses that still allow a release decision to be made.
    PRE_RELEASE_STATUSES = ("not_eligible", "frozen")

    class Method(models.TextChoices):
        UNDECIDED = "undecided", "Undecided"
        STRIPE_TRANSFER = "stripe_transfer", "Stripe transfer"
        MANUAL = "manual", "Manual settlement"

    public_reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    provider_mode = models.CharField(
        max_length=16,
        choices=FinancialMode.choices,
        default=FinancialMode.LEGACY_UNKNOWN,
    )
    snapshot_version = models.PositiveSmallIntegerField(default=0)
    legacy_classification = models.CharField(max_length=64, blank=True, default="")
    routing_policy_version = models.CharField(max_length=64, blank=True, default="")
    funding_attempt = models.ForeignKey(
        PaymentAttempt,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="funded_payouts",
    )
    funding_provider_snapshot = models.CharField(max_length=16, blank=True, default="")
    method_version = models.ForeignKey(
        "finance.PayoutMethodVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="initial_payouts",
    )
    active_instruction_version = models.ForeignKey(
        "finance.PayoutMethodVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="active_payouts",
    )
    stripe_account = models.ForeignKey(
        "finance.StripePayoutAccount", null=True, blank=True, on_delete=models.PROTECT
    )
    dzd_profile_revision = models.ForeignKey(
        "finance.DzdPayoutProfileRevision",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    snapshot_at = models.DateTimeField(null=True, blank=True)
    funded_amount_eur_cents = models.PositiveBigIntegerField(null=True, blank=True)
    original_settlement_amount_minor = models.PositiveBigIntegerField(
        null=True, blank=True
    )
    fx_source = models.CharField(max_length=64, blank=True, default="")
    fx_settings_version = models.ForeignKey(
        "core.BusinessSettingsVersion", null=True, blank=True, on_delete=models.PROTECT
    )
    fx_snapshot_at = models.DateTimeField(null=True, blank=True)
    fx_source_attempt = models.ForeignKey(
        PaymentAttempt,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payout_fx_snapshots",
    )
    rounding_policy = models.CharField(max_length=32, blank=True, default="")
    block_reason = models.CharField(max_length=64, blank=True, default="")
    next_action_at = models.DateTimeField(null=True, blank=True)
    state_version = models.PositiveBigIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)
    settlement_basis = models.CharField(max_length=64, blank=True, default="")
    eligibility_basis = models.CharField(max_length=32, blank=True, default="")
    eligibility_decision_reference = models.CharField(
        max_length=160, blank=True, default=""
    )

    deal = models.OneToOneField(
        "deals.Deal", on_delete=models.PROTECT, related_name="payout"
    )
    traveler = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payouts",
    )
    amount_eur_cents = models.PositiveBigIntegerField(
        validators=[MinValueValidator(0)],
        help_text="Canonical traveler obligation in EUR cents.",
    )
    method = models.CharField(
        max_length=20, choices=Method.choices, default=Method.UNDECIDED
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.NOT_ELIGIBLE,
        db_index=True,
    )
    #: Set by Phase 4 when the protection window closes without a dispute.
    eligible_at = models.DateTimeField(null=True, blank=True)
    scheduled_for = models.DateTimeField(null=True, blank=True)

    payout_currency = models.CharField(max_length=3, blank=True, default="")
    payout_amount_minor = models.PositiveBigIntegerField(null=True, blank=True)
    payout_amount_exponent = models.PositiveSmallIntegerField(null=True, blank=True)
    fx_rate_micros = models.PositiveBigIntegerField(null=True, blank=True)

    provider_payout_id = models.CharField(max_length=255, blank=True, default="")
    reference = models.CharField(
        max_length=128,
        blank=True,
        default="",
        help_text="Bank/transfer reference for a manual settlement.",
    )
    receipt_url = models.URLField(max_length=1024, blank=True, default="")
    admin_actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payouts_settled",
    )
    notes = models.TextField(blank=True, default="", max_length=2000)
    failure_code = models.CharField(max_length=64, blank=True, default="")

    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "finance_payout"
        ordering = ["-created_at"]
        permissions = [
            ("settle_payout", "Can record that a traveler has actually been paid"),
        ]
        indexes = [
            models.Index(
                fields=["traveler", "-created_at"], name="fin_payout_trav_idx"
            ),
            models.Index(
                fields=["status", "scheduled_for"], name="fin_payout_queue_idx"
            ),
            models.Index(fields=["method", "status"], name="fin_payout_method_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount_eur_cents__gt=0)
                | (
                    Q(snapshot_version__gt=0, amount_eur_cents=0, status="cancelled")
                    & ~Q(eligibility_decision_reference="")
                ),
                name="fin_payout_amount_positive",
            ),
            models.CheckConstraint(
                condition=Q(snapshot_version=0)
                | Q(
                    funded_amount_eur_cents__gt=0,
                    funded_amount_eur_cents__isnull=False,
                    snapshot_at__isnull=False,
                ),
                name="fin_payout_funded_snapshot",
            ),
            models.CheckConstraint(
                condition=Q(snapshot_version=0)
                | Q(
                    method="manual",
                    payout_currency="DZD",
                    payout_amount_exponent=0,
                    stripe_account__isnull=True,
                )
                | Q(
                    method="stripe_transfer",
                    payout_currency="EUR",
                    payout_amount_exponent=2,
                    fx_rate_micros__isnull=True,
                    fx_settings_version__isnull=True,
                    fx_source_attempt__isnull=True,
                    dzd_profile_revision__isnull=True,
                )
                | Q(
                    method="undecided",
                    payout_currency="",
                    block_reason="payout_preference_required",
                ),
                name="fin_payout_snapshot_pairing",
            ),
            models.CheckConstraint(
                condition=Q(snapshot_version=0)
                | ~Q(payout_currency="DZD")
                | Q(
                    fx_rate_micros__gt=0,
                    fx_rate_micros__isnull=False,
                    fx_settings_version__isnull=False,
                    fx_snapshot_at__isnull=False,
                    payout_amount_minor__isnull=False,
                )
                | Q(
                    block_reason="fx_snapshot_missing",
                    fx_rate_micros__isnull=True,
                    payout_amount_minor__isnull=True,
                ),
                name="fin_payout_dzd_fx_snapshot",
            ),
            # A paid payout must carry proof: either a provider payout id, or a
            # named admin actor plus a reference. Marking money as sent with no
            # audit trail is refused by the database.
            models.CheckConstraint(
                condition=(
                    ~Q(status="paid")
                    | ~Q(provider_payout_id="")
                    | (Q(admin_actor__isnull=False) & ~Q(reference=""))
                ),
                name="fin_payout_paid_requires_evidence",
            ),
            models.CheckConstraint(
                condition=~Q(status="paid") | Q(paid_at__isnull=False),
                name="fin_payout_paid_requires_timestamp",
            ),
            # Automatic release cannot bypass the eligibility gate: nothing past
            # `eligible` may exist without an eligibility instant, which only
            # the Phase 4 release service sets.
            models.CheckConstraint(
                condition=(
                    ~Q(
                        status__in=[
                            "eligible",
                            "scheduled",
                            "processing",
                            "sent",
                            "paid",
                        ]
                    )
                    | Q(eligible_at__isnull=False)
                ),
                name="fin_payout_release_requires_eligibility",
            ),
        ]

    def __str__(self) -> str:
        return f"Payout#{self.pk} deal={self.deal_id} {self.amount_eur_cents}c ({self.status})"


class ScheduledJob(models.Model):
    """Durable record of delayed work the platform has promised to do.

    Phase 3 introduced it for financial obligations. Phase 4 adds the rest of
    the lifecycle — the 30-minute delivery-code release, the 48-hour protection
    expiry, the rating reveal, boost expiry and outbound messages — because the
    guarantee they need is the same one, and a second scheduler would be a
    second thing that can silently stop.

    Redis is a delivery accelerator in this system, never an obligation store.
    A deposit refund that must happen when a request expires is a row here; it
    survives a process restart, a Redis flush and a worker crash, and the
    unique ``key`` plus the handler's own idempotency make a duplicate run a
    no-op rather than a second refund.
    """

    class Kind(models.TextChoices):
        DEPOSIT_EXPIRY_REFUND = "deposit_expiry_refund", "Deposit expiry refund"
        PAYMENT_GRACE_RELEASE = "payment_grace_release", "Payment grace release"
        ATTEMPT_EXPIRY = "attempt_expiry", "Checkout attempt expiry"
        PROVIDER_RECONCILE = "provider_reconcile", "Provider reconciliation"
        PROVIDER_EVENT_PROCESS = "provider_event_process", "Provider event processing"
        REFUND_RECONCILE = "refund_reconcile", "Refund reconciliation"
        PAYOUT_RELEASE_CHECK = "payout_release_check", "Payout release check"
        # --- Phase 4 durable lifecycle obligations ---
        DELIVERY_CODE_RELEASE = "delivery_code_release", "Delivery code release"
        PROTECTION_EXPIRY = "protection_expiry", "Protection window expiry"
        RATING_REVEAL = "rating_reveal", "Rating reveal"
        BOOST_EXPIRY = "boost_expiry", "Boost expiry"
        OUTBOUND_MESSAGE = "outbound_message", "Outbound message dispatch"
        NOTIFICATION_DISPATCH = "notification_dispatch", "Notification dispatch"
        # --- Phase 8F-H3 automatic EUR payout execution ---
        PAYOUT_EXECUTE = "payout_execute", "Payout execution"
        PAYOUT_RECONCILE = "payout_reconcile", "Payout reconciliation"
        PAYOUT_ACCOUNT_REFRESH = "payout_account_refresh", "Payout account refresh"
        PAYOUT_SWEEP = "payout_sweep", "Payout sweep"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    class Resolution(models.TextChoices):
        RESOLVED = "resolved", "Resolved"
        DISMISSED = "dismissed", "Dismissed"
        SUPERSEDED = "superseded", "Superseded"

    key = models.CharField(max_length=160, unique=True)
    kind = models.CharField(max_length=32, choices=Kind.choices, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    run_at = models.DateTimeField(db_index=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=8)
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.CharField(max_length=64, blank=True, default="")
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=64, blank=True, default="")
    last_error = models.CharField(max_length=500, blank=True, default="")
    last_result = models.CharField(max_length=255, blank=True, default="")
    completed_at = models.DateTimeField(null=True, blank=True)
    resolution = models.CharField(
        max_length=16,
        choices=Resolution.choices,
        blank=True,
        default="",
        db_index=True,
        help_text="Operational resolution only; execution history is retained.",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="resolved_scheduled_jobs",
    )
    resolution_reason = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "finance_scheduled_job"
        ordering = ["run_at", "id"]
        indexes = [
            models.Index(fields=["status", "run_at"], name="fin_job_due_idx"),
            models.Index(fields=["kind", "status"], name="fin_job_kind_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        resolution="",
                        resolved_at__isnull=True,
                        resolved_by__isnull=True,
                        resolution_reason="",
                    )
                    | (
                        ~Q(resolution="")
                        & Q(resolved_at__isnull=False)
                        & ~Q(resolution_reason="")
                        & Q(status="failed")
                    )
                ),
                name="fin_job_resolution_complete",
            )
        ]

    def __str__(self) -> str:
        return f"Job#{self.pk} {self.kind} @{self.run_at.isoformat()} ({self.status})"
