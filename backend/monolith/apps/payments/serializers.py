"""Payments serializers — read + create."""

from __future__ import annotations

from rest_framework import serializers

from .models import PaymentEvent, PaymentIntent, Refund


class PaymentIntentSerializer(serializers.ModelSerializer):
    payer_id = serializers.IntegerField(read_only=True)
    offer_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = PaymentIntent
        fields = (
            "id",
            "offer_id",
            "payer_id",
            "provider",
            "provider_intent_id",
            "amount_minor",
            "currency",
            "status",
            "client_idempotency_key",
            "failure_code",
            "failure_message",
            "succeeded_at",
            "refunded_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class PaymentEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentEvent
        fields = (
            "id",
            "provider",
            "provider_event_id",
            "kind",
            "payload",
            "created_at",
        )
        read_only_fields = fields


class RefundSerializer(serializers.ModelSerializer):
    intent_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Refund
        fields = (
            "id",
            "intent_id",
            "amount_minor",
            "currency",
            "provider",
            "provider_refund_id",
            "reason",
            "status",
            "succeeded_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class CreateIntentSerializer(serializers.Serializer):
    """Payload for POST /api/payments/intents.

    `offer_id` is required and must point to an accepted Offer that:
      - belongs to a Match where the caller is the sender
      - has no existing succeeded PaymentIntent

    `currency` defaults to DZD (the platform's currency). `idempotency_key`
    is optional but recommended; without it, double-submits create dupes
    constrained only by the open-intent uniqueness rule.
    """

    offer_id = serializers.IntegerField()
    currency = serializers.ChoiceField(choices=("DZD", "EUR"), default="DZD")
    idempotency_key = serializers.CharField(
        required=False, allow_blank=True, max_length=64
    )
