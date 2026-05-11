"""Payments schema — PaymentIntent + PaymentEvent + Refund.

V1 reality check:
- We're shipping a MOCK provider for now. The schema, state machine, and
  endpoints are real and reflect how Stripe + Edahabia will plug in.
- `provider` distinguishes Stripe (EUR senders, V2) vs Edahabia (DZD senders,
  V2) vs `mock` (V1 — instant success).
- `provider_intent_id` + `provider_event_id` are idempotency keys. Webhook
  replays from real providers will not double-credit (CLAUDE.md §6/G6).

Money is integer minor units (DZD has no minor unit, so it's whole DZD; EUR
is cents). `currency` is ISO 4217. Pricing is frozen on the Offer row
(matching app) — we snapshot `amount_minor` + `currency` from there at
creation; never recompute.

State machine (PaymentIntent):

    requires_payment_method → processing → succeeded
                                         → failed
                                         → cancelled
    succeeded → refund_pending → refunded (full)
                              → refunded (partial)   (refund_pending stays
                                                       open until full)

Only `succeeded` payments can fund the wallet hold for the matched Offer.
Verification (handover) is what eventually releases funds to the traveler.
"""

from __future__ import annotations

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.matching.models import Offer


class PaymentIntent(models.Model):
    """A sender's payment for a specific accepted Offer.

    Lifecycle is driven by `apps.payments.views` + the provider webhook (or
    in V1, the mock instant-success path). After `succeeded`, the wallet
    app holds the funds in escrow until handover unlocks the payout.
    """

    class Provider(models.TextChoices):
        MOCK = "mock", "Mock (V1)"
        STRIPE = "stripe", "Stripe"
        EDAHABIA = "edahabia", "Edahabia"

    class Status(models.TextChoices):
        REQUIRES_PAYMENT_METHOD = "requires_payment_method", "Requires payment method"
        PROCESSING = "processing", "Processing"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"
        REFUND_PENDING = "refund_pending", "Refund pending"
        REFUNDED = "refunded", "Refunded"

    class Currency(models.TextChoices):
        DZD = "DZD", "Algerian Dinar"
        EUR = "EUR", "Euro"

    offer = models.OneToOneField(
        Offer,
        on_delete=models.PROTECT,
        related_name="payment",
        help_text="Each accepted Offer has exactly one PaymentIntent.",
    )
    payer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payments_made",
        help_text="The sender. Matches offer.match.sender_id.",
    )

    provider = models.CharField(
        max_length=12, choices=Provider.choices, default=Provider.MOCK
    )
    # Provider-side ID for idempotency. UNIQUE per provider so the same
    # `pi_xxx` from Stripe can't be replayed and a real Stripe ID can't
    # collide with a mock-mode ID.
    provider_intent_id = models.CharField(max_length=128, blank=True, default="")

    amount_minor = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text="Integer minor units. DZD: whole DZD. EUR: cents.",
    )
    currency = models.CharField(max_length=3, choices=Currency.choices)

    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.REQUIRES_PAYMENT_METHOD,
        db_index=True,
    )

    # Idempotency for /confirm — client sends a key so retries from flaky
    # network don't double-create intents or double-capture.
    client_idempotency_key = models.CharField(max_length=64, blank=True, default="")

    failure_code = models.CharField(max_length=64, blank=True, default="")
    failure_message = models.CharField(max_length=255, blank=True, default="")

    succeeded_at = models.DateTimeField(null=True, blank=True)
    refunded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "payments_intent"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["payer", "-created_at"], name="payments_payer_idx"),
            models.Index(fields=["status"], name="payments_status_idx"),
            models.Index(
                fields=["provider", "status"], name="payments_provider_status_idx"
            ),
        ]
        constraints = [
            # Provider-scoped uniqueness on the external ID.
            models.UniqueConstraint(
                fields=["provider", "provider_intent_id"],
                condition=~models.Q(provider_intent_id=""),
                name="payments_unique_provider_intent",
            ),
            # One pending intent per offer (covers retries on a still-open
            # payment without exploding into N orphan intents).
            models.UniqueConstraint(
                fields=["offer"],
                condition=models.Q(
                    status__in=["requires_payment_method", "processing"]
                ),
                name="payments_one_open_per_offer",
            ),
            # Idempotency key uniqueness per payer (when supplied).
            models.UniqueConstraint(
                fields=["payer", "client_idempotency_key"],
                condition=~models.Q(client_idempotency_key=""),
                name="payments_unique_client_key_per_payer",
            ),
        ]

    def __str__(self) -> str:
        return f"PI#{self.id} offer={self.offer_id} {self.amount_minor}{self.currency} ({self.status})"


class PaymentEvent(models.Model):
    """Append-only audit + idempotency log for provider webhooks.

    Each row is one inbound webhook (or mock-mode synthetic event).
    `provider_event_id` is UNIQUE per provider so replays are no-ops.
    """

    class Kind(models.TextChoices):
        INTENT_CREATED = "intent_created", "Intent created"
        INTENT_PROCESSING = "intent_processing", "Intent processing"
        INTENT_SUCCEEDED = "intent_succeeded", "Intent succeeded"
        INTENT_FAILED = "intent_failed", "Intent failed"
        INTENT_CANCELLED = "intent_cancelled", "Intent cancelled"
        REFUND_CREATED = "refund_created", "Refund created"
        REFUND_SUCCEEDED = "refund_succeeded", "Refund succeeded"
        REFUND_FAILED = "refund_failed", "Refund failed"

    intent = models.ForeignKey(
        PaymentIntent, on_delete=models.CASCADE, related_name="events"
    )
    provider = models.CharField(max_length=12, choices=PaymentIntent.Provider.choices)
    provider_event_id = models.CharField(max_length=128)
    kind = models.CharField(max_length=24, choices=Kind.choices)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "payments_event"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["intent", "-created_at"], name="payments_event_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_event_id"],
                name="payments_event_unique",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind} intent={self.intent_id}"


class Refund(models.Model):
    """A refund against a succeeded PaymentIntent.

    Partial refunds are allowed (`amount_minor` < intent.amount_minor) and
    the intent stays in `refund_pending` until cumulative refunds equal the
    captured amount, at which point it moves to `refunded`.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    intent = models.ForeignKey(
        PaymentIntent, on_delete=models.PROTECT, related_name="refunds"
    )
    amount_minor = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    currency = models.CharField(max_length=3, choices=PaymentIntent.Currency.choices)

    provider = models.CharField(max_length=12, choices=PaymentIntent.Provider.choices)
    provider_refund_id = models.CharField(max_length=128, blank=True, default="")

    reason = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)

    succeeded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "payments_refund"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["intent", "-created_at"], name="payments_refund_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_refund_id"],
                condition=~models.Q(provider_refund_id=""),
                name="payments_refund_unique_provider_id",
            ),
        ]

    def __str__(self) -> str:
        return f"Refund#{self.id} intent={self.intent_id} {self.amount_minor}{self.currency}"
