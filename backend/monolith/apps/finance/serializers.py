"""Read contracts for the V1 payment API.

Two rules shape every serializer here.

**The client computes nothing.** Deposits, outstanding balances, FX, commission,
sender totals, refund amounts and payout eligibility are all pre-computed
fields. There is no arithmetic left for Flutter to get wrong or to disagree
with the server about.

**Provider internals stay internal.** A party sees the state of their own
payment and the URL they must visit. They do not see idempotency keys, raw
provider payloads, webhook metadata, guest token hashes or another user's
attempt. The guest sees less again — see `GuestPaymentSerializer`.
"""

from __future__ import annotations

from django.conf import settings
from rest_framework import serializers

from apps.core.languages import CommunicationLanguage

from .models import (
    PaymentAttempt,
    PaymentOrder,
    PaymentProvider,
    PaymentRefund,
    Payout,
)
from .money import format_minor, format_rate


class PaymentAttemptSerializer(serializers.ModelSerializer):
    """One attempt, as its own payer or the order owner may see it."""

    payment_amount = serializers.SerializerMethodField()
    eur_dzd_rate = serializers.SerializerMethodField()
    is_guest_payment = serializers.SerializerMethodField()

    class Meta:
        model = PaymentAttempt
        fields = (
            "id",
            "provider",
            "status",
            "amount_eur_cents",
            "payment_currency",
            "provider_amount_minor",
            "provider_amount_exponent",
            "payment_amount",
            "fx_rate_micros",
            "eur_dzd_rate",
            "checkout_url",
            "failure_code",
            "is_guest_payment",
            "expires_at",
            "succeeded_at",
            "created_at",
        )
        read_only_fields = fields

    def get_payment_amount(self, obj: PaymentAttempt) -> str:
        return format_minor(
            obj.provider_amount_minor, exponent=obj.provider_amount_exponent
        )

    def get_eur_dzd_rate(self, obj: PaymentAttempt) -> str | None:
        return format_rate(obj.fx_rate_micros) if obj.fx_rate_micros else None

    def get_is_guest_payment(self, obj: PaymentAttempt) -> bool:
        return obj.guest_link_id is not None


class PaymentRefundSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentRefund
        fields = (
            "id",
            "amount_eur_cents",
            "provider",
            "reason",
            "status",
            "failure_code",
            "succeeded_at",
            "created_at",
        )
        read_only_fields = fields


def payment_settlement_payload(order: PaymentOrder) -> dict:
    """What actually happened to this obligation, in one block.

    J2 freezes this so J3 can build a real confirmation screen without asking
    the server four more questions or doing arithmetic of its own. Every value
    is server-computed and privacy-safe:

    * `is_settled` is the authoritative answer to "did it go through" -- the
      reconciled order status, never a client's return from a checkout page.
    * `deposit_credited_eur_cents` is what a posting deposit discharged, so the
      screen can say "your deposit covered this much" instead of looking like a
      second charge.
    * `paid_by` says `guest` or `self` without naming the guest. Who paid is the
      owner's business; the guest's email is not, and never appears here.
    * `next_step` is the one thing the sender does next, named by the server
      because the server is what knows whether a Deal is now funded.
    """

    # `all()` so a prefetched order answers from its cache and an un-prefetched
    # one costs exactly one query; the narrowing is done here either way.
    applied = [
        attempt
        for attempt in order.attempts.all()
        if attempt.status == PaymentAttempt.Status.SUCCEEDED
        and not attempt.is_unapplied
    ]
    guest_paid = any(attempt.guest_link_id is not None for attempt in applied)
    settled = order.status in (
        PaymentOrder.Status.PAID,
        PaymentOrder.Status.REFUND_PENDING,
        PaymentOrder.Status.PARTIALLY_REFUNDED,
        PaymentOrder.Status.REFUNDED,
    )
    if order.purpose == PaymentOrder.Purpose.POSTING_DEPOSIT:
        next_step = "await_offers" if settled else "pay_posting_deposit"
    else:
        next_step = "await_pickup" if settled else "pay_deal_balance"
    return {
        "is_settled": settled,
        "purpose": order.purpose,
        "currency": "EUR",
        "amount_eur_cents": int(order.amount_eur_cents),
        "paid_eur_cents": int(order.paid_eur_cents),
        "deposit_credited_eur_cents": int(order.credited_eur_cents),
        "remaining_eur_cents": order.outstanding_eur_cents,
        "refunded_eur_cents": int(order.refunded_eur_cents),
        "deal_id": order.deal_id,
        "delivery_request_id": order.delivery_request_id,
        "paid_by": ("guest" if guest_paid else "self") if applied else None,
        "next_step": next_step,
        "paid_at": order.paid_at,
    }


class PaymentOrderSerializer(serializers.ModelSerializer):
    """The owner's view of one obligation.

    `outstanding_eur_cents` is the number a checkout will charge, already net of
    any posting-deposit credit. The client renders it; it never derives it.
    """

    outstanding_eur_cents = serializers.IntegerField(read_only=True)
    deposit_credit_eur_cents = serializers.IntegerField(
        source="credited_eur_cents", read_only=True
    )
    attempts = PaymentAttemptSerializer(many=True, read_only=True)
    refunds = PaymentRefundSerializer(many=True, read_only=True)
    deal_id = serializers.IntegerField(read_only=True)
    delivery_request_id = serializers.IntegerField(read_only=True)
    settlement = serializers.SerializerMethodField()

    class Meta:
        model = PaymentOrder
        fields = (
            "public_reference",
            "purpose",
            "status",
            "currency",
            "amount_eur_cents",
            "deposit_credit_eur_cents",
            "paid_eur_cents",
            "refunded_eur_cents",
            "outstanding_eur_cents",
            "deal_id",
            "delivery_request_id",
            "paid_at",
            "created_at",
            "attempts",
            "refunds",
            "settlement",
        )
        read_only_fields = fields

    def get_settlement(self, obj: PaymentOrder) -> dict:
        return payment_settlement_payload(obj)


class PaymentOrderSummarySerializer(serializers.ModelSerializer):
    """The list form: state and money, without the attempt/refund history."""

    outstanding_eur_cents = serializers.IntegerField(read_only=True)
    deposit_credit_eur_cents = serializers.IntegerField(
        source="credited_eur_cents", read_only=True
    )
    deal_id = serializers.IntegerField(read_only=True)
    delivery_request_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = PaymentOrder
        fields = (
            "public_reference",
            "purpose",
            "status",
            "currency",
            "amount_eur_cents",
            "deposit_credit_eur_cents",
            "paid_eur_cents",
            "refunded_eur_cents",
            "outstanding_eur_cents",
            "deal_id",
            "delivery_request_id",
            "paid_at",
            "created_at",
        )
        read_only_fields = fields


class PayoutSerializer(serializers.ModelSerializer):
    """What a traveler may see about their own earnings.

    Deliberately excludes the admin actor, the internal notes and the provider
    payout id. `status` plus `eligible_at` is the whole story a traveler needs:
    Phase 3 always answers `not_eligible`, because release is Phase 4's gate.
    """

    deal_id = serializers.IntegerField(read_only=True)
    payout_amount = serializers.SerializerMethodField()
    mobile = serializers.SerializerMethodField()
    reference = serializers.UUIDField(source="public_reference", read_only=True)

    class Meta:
        model = Payout
        fields = (
            "id",
            "deal_id",
            "amount_eur_cents",
            "method",
            "status",
            "eligible_at",
            "scheduled_for",
            "payout_currency",
            "payout_amount",
            "reference",
            "paid_at",
            "created_at",
            "mobile",
        )
        read_only_fields = fields

    def get_mobile(self, obj):
        from .payout_mobile import payout_status

        return payout_status(obj, context=self.context.get("payout_page"))

    def get_payout_amount(self, obj: Payout) -> str | None:
        if obj.payout_amount_minor is None or obj.payout_amount_exponent is None:
            return None
        return format_minor(
            obj.payout_amount_minor, exponent=obj.payout_amount_exponent
        )


class GuestPaymentSerializer(serializers.Serializer):
    """Everything a third-party payer is entitled to see. Nothing else.

    No sender, no traveler, no recipient, no addresses, no parcel, no deal, no
    order id. Paying does not make the guest a party, so the payload never
    describes one.
    """

    amount_eur_cents = serializers.IntegerField(read_only=True)
    currency = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    expires_at = serializers.CharField(read_only=True)
    providers = serializers.ListField(read_only=True)


# --- write contracts ---------------------------------------------------------


class CheckoutCreateSerializer(serializers.Serializer):
    """The client chooses a rail. It never supplies an amount, rate or currency.

    Any attempt to pass an amount is rejected outright rather than ignored, so a
    tampering client gets a clear 400 instead of believing it set the price.
    """

    provider = serializers.ChoiceField(choices=PaymentProvider.choices)

    _FORBIDDEN = (
        "amount",
        "amount_eur_cents",
        "amount_minor",
        "currency",
        "payment_currency",
        "fx_rate",
        "fx_rate_micros",
        "eur_dzd_rate",
        "provider_amount_minor",
        "total",
    )

    def validate(self, attrs):
        supplied = set(getattr(self, "initial_data", {}) or {})
        offending = sorted(supplied.intersection(self._FORBIDDEN))
        if offending:
            raise serializers.ValidationError(
                {
                    "code": "client_supplied_amount_rejected",
                    "detail": (
                        "Payment amounts, currencies and exchange rates are "
                        "server-calculated."
                    ),
                    "rejected_fields": offending,
                }
            )
        return attrs


class PostingDepositCreateSerializer(serializers.Serializer):
    """Optionally, the deposit the sender chose for themselves.

    One integer or nothing. Omitting it accepts the server's recommendation;
    supplying it is a choice the server then bounds -- below by the configured
    floor, above by the obligation the deposit is being paid against. Neither
    bound is expressed here, because both are properties of the request and the
    active settings revision rather than of the wire format.
    """

    amount_eur_cents = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=100_000_000,
    )


class GuestLinkCreateSerializer(serializers.Serializer):
    label = serializers.CharField(
        required=False, allow_blank=True, max_length=80
    )
    communication_language = serializers.ChoiceField(
        choices=CommunicationLanguage.choices,
        required=False,
    )


class GuestCheckoutCreateSerializer(CheckoutCreateSerializer):
    """A guest identifies only the mailbox that should receive their receipt.

    Email is collected by ShipTrip before redirecting to a hosted provider so
    every enabled rail has the same durable receipt path. It grants no account
    or Deal authority and is never included in a guest read response.
    """

    email = serializers.EmailField(
        max_length=254,
        required=False,
        allow_blank=True,
        default="",
    )

    def validate(self, attrs: dict) -> dict:
        attrs = super().validate(attrs)
        if settings.TRANSACTIONAL_EMAIL_ENABLED and not attrs.get("email"):
            raise serializers.ValidationError(
                {"email": "An email address is required for the payment receipt."}
            )
        return attrs


class ManualPayoutCompleteSerializer(serializers.Serializer):
    """Admin-only settlement record. Every field is audit evidence."""

    payout_currency = serializers.CharField(max_length=3)
    payout_amount_minor = serializers.IntegerField(min_value=1)
    reference = serializers.CharField(max_length=128)
    fx_rate_micros = serializers.IntegerField(
        required=False, allow_null=True, min_value=1
    )
    receipt_url = serializers.URLField(required=False, allow_blank=True)
    notes = serializers.CharField(
        required=False, allow_blank=True, max_length=2000
    )


class RefundRequestSerializer(serializers.Serializer):
    """Admin-only refund request against one attempt."""

    attempt_id = serializers.IntegerField(min_value=1)
    amount_eur_cents = serializers.IntegerField(min_value=1)
    reason = serializers.ChoiceField(choices=PaymentRefund.Reason.choices)


class ManualRefundSettleSerializer(serializers.Serializer):
    """Admin-only record that an operator sent a refund by hand.

    The path for a rail with no refund API. Every field is audit evidence, and
    the reference is required by a database constraint as well as here.
    """

    settlement_reference = serializers.CharField(max_length=128)
    settlement_note = serializers.CharField(
        required=False, allow_blank=True, max_length=255
    )
