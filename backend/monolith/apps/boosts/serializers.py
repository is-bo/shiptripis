"""Read and write contracts for paid sender boosts.

Two rules shape everything here.

**The client proposes an amount; the server prices the economics.** A preview
returns the authoritative Traveler/platform split and settings version. The
purchase must echo that version, while the server validates the €5 minimum and
recomputes every cent.

**A purchase answer is a payment answer.** `BoostPurchaseSerializer` carries the
linked `PaymentOrder`'s public reference and the amount still outstanding,
because the next thing the client does is open the existing checkout route with
them. It does not carry attempts, provider identifiers or anything else the
finance API already owns.
"""

from __future__ import annotations

from rest_framework import serializers

from .models import BoostPurchase
from .services import MAX_EUR_CENTS


class BoostPackageSerializer(serializers.Serializer):
    """One admin-configured package, exactly as the server prices it."""

    code = serializers.CharField(read_only=True)
    label = serializers.CharField(read_only=True)
    duration_seconds = serializers.IntegerField(read_only=True)
    ranking_weight = serializers.IntegerField(read_only=True)
    currency = serializers.CharField(read_only=True)


class BoostPurchaseCreateSerializer(serializers.Serializer):
    """The whole request body: which package.

    An unknown code is refused by the service against the active revision
    rather than by a choice list compiled into the image, because the packages
    on offer are an operator decision that changes without a deploy.
    """

    package_code = serializers.CharField(max_length=32, trim_whitespace=True)
    amount_eur_cents = serializers.IntegerField(min_value=1, max_value=MAX_EUR_CENTS)
    preview_settings_version = serializers.IntegerField(min_value=1)


class BoostPreviewSerializer(serializers.Serializer):
    package_code = serializers.CharField(max_length=32, trim_whitespace=True)
    amount_eur_cents = serializers.IntegerField(min_value=1, max_value=MAX_EUR_CENTS)


class BoostPurchaseSerializer(serializers.ModelSerializer):
    """One purchase and the obligation the buyer must now settle.

    Callers should `select_related("payment_order")`; the payment fields read
    straight off it.
    """

    payment_order_reference = serializers.SerializerMethodField()
    payment_status = serializers.SerializerMethodField()
    payment_amount_eur_cents = serializers.SerializerMethodField()
    payment_outstanding_eur_cents = serializers.SerializerMethodField()
    delivery_request_id = serializers.IntegerField(read_only=True)
    currency = serializers.SerializerMethodField()

    class Meta:
        model = BoostPurchase
        fields = (
            "public_reference",
            "delivery_request_id",
            "package_code",
            "package_snapshot",
            "status",
            "duration_seconds",
            "amount_eur_cents",
            "currency",
            "ranking_weight",
            "economics_version",
            "traveler_share_bps",
            "traveler_boost_eur_cents",
            "platform_boost_eur_cents",
            "activated_at",
            "expires_at",
            "disposition_reason",
            "created_at",
            "payment_order_reference",
            "payment_status",
            "payment_amount_eur_cents",
            "payment_outstanding_eur_cents",
        )
        read_only_fields = fields

    def get_currency(self, obj: BoostPurchase) -> str:
        return "EUR"

    def get_payment_order_reference(self, obj: BoostPurchase) -> str | None:
        order = obj.payment_order
        return str(order.public_reference) if order is not None else None

    def get_payment_status(self, obj: BoostPurchase) -> str | None:
        order = obj.payment_order
        return order.status if order is not None else None

    def get_payment_amount_eur_cents(self, obj: BoostPurchase) -> int | None:
        order = obj.payment_order
        return int(order.amount_eur_cents) if order is not None else None

    def get_payment_outstanding_eur_cents(self, obj: BoostPurchase) -> int | None:
        order = obj.payment_order
        return order.outstanding_eur_cents if order is not None else None
