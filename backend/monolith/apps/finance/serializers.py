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

from rest_framework import serializers

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
        )
        read_only_fields = fields


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
        )
        read_only_fields = fields

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


class GuestLinkCreateSerializer(serializers.Serializer):
    label = serializers.CharField(
        required=False, allow_blank=True, max_length=80
    )


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
