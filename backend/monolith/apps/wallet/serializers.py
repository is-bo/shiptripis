"""Wallet serializers — read-only views into ledger state."""

from __future__ import annotations

from rest_framework import serializers

from .models import Hold, Wallet, WalletEntry, Withdrawal


class WalletEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = WalletEntry
        fields = (
            "id",
            "kind",
            "amount_minor",
            "currency",
            "key",
            "source",
            "source_id",
            "note",
            "created_at",
        )
        read_only_fields = fields


class HoldSerializer(serializers.ModelSerializer):
    class Meta:
        model = Hold
        fields = (
            "id",
            "amount_minor",
            "currency",
            "source",
            "source_id",
            "status",
            "opened_at",
            "closed_at",
        )
        read_only_fields = fields


class WalletSerializer(serializers.ModelSerializer):
    total_minor = serializers.IntegerField(read_only=True)
    available_minor = serializers.IntegerField(read_only=True)
    on_hold_minor = serializers.IntegerField(read_only=True)

    class Meta:
        model = Wallet
        fields = (
            "id",
            "currency",
            "total_minor",
            "available_minor",
            "on_hold_minor",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class WithdrawalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Withdrawal
        fields = (
            "id",
            "amount_minor",
            "currency",
            "destination",
            "destination_ref",
            "status",
            "sent_at",
            "created_at",
        )
        read_only_fields = fields


class WithdrawalCreateSerializer(serializers.Serializer):
    currency = serializers.ChoiceField(choices=("DZD", "EUR"))
    amount_minor = serializers.IntegerField(min_value=1)
    destination = serializers.ChoiceField(
        choices=("bank", "card", "edahabia", "stripe")
    )
    destination_ref = serializers.CharField(
        required=False, allow_blank=True, max_length=128
    )
