"""Read and write contracts for sender Boost.

Two rules shape everything here.

**The client names an amount; the server prices it.** A request body carries one
integer and nothing else. Bounds, the commission rate, the Traveler bonus and
the sender's cost are all computed server-side and returned, so no client ever
calculates a financial total and no client can propose one.

**The retired package is read-only.** `BoostPurchaseSerializer` still renders a
historical `BoostPurchase` exactly as it was sold. Nothing writes one.
"""

from __future__ import annotations

from rest_framework import serializers

from .models import BoostPurchase
from .services import MAX_EUR_CENTS


class BoostIntentSerializer(serializers.Serializer):
    """The whole request body: what the sender wants the Boost to be.

    Zero is valid and means "remove it". The band is enforced by the service
    against the active settings revision rather than by a constant compiled into
    the image, because the band is an operator decision that changes without a
    deploy; the ceiling here is only the representation guard.
    """

    boost_eur_cents = serializers.IntegerField(min_value=0, max_value=MAX_EUR_CENTS)


class BoostPurchaseSerializer(serializers.ModelSerializer):
    """One historical paid visibility package, as it was sold.

    Retained for audit. Callers should `select_related("payment_order")`; the
    payment fields read straight off it.
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
