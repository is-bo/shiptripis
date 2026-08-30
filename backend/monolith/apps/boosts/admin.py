"""Operations view over paid boosts.

Registered read-only, for the same reason every financial model is: a purchase
carries the price, duration and weight the buyer was quoted, and its status is
the joint outcome of a provider payment, the request's own state and a durable
expiry job. An operator who could edit these rows by hand could grant a paid
ranking weight nobody bought, or strand money by marking a refunded purchase
active.

`Ranking effect` is shown because it is the only thing a boost does. It is the
computed answer -- active status, and an expiry still in the future -- rather
than the stored status, so a boost whose expiry job has not run yet is visible
as what it actually is.
"""

from __future__ import annotations

from django.contrib import admin

from apps.core.admin_display import money, status

from .models import BoostPurchase


@admin.register(BoostPurchase)
class BoostPurchaseAdmin(admin.ModelAdmin):
    """No add, no change, no delete. Purchases are settled by services only."""

    list_display = (
        "id",
        "delivery_request",
        "buyer",
        "package_code",
        "status_chip",
        "ranking_effect_display",
        "price_display",
        "ranking_weight",
        "activated_at",
        "expires_at",
        "disposition_reason",
        "created_at",
    )
    list_filter = ("status", "package_code", "created_at")
    search_fields = (
        "public_reference",
        "buyer__email",
        "delivery_request__id",
        "payment_order__public_reference",
        "disposition_reason",
    )
    date_hierarchy = "created_at"
    list_select_related = ("delivery_request", "buyer", "payment_order")
    fields = (
        "public_reference",
        "delivery_request",
        "buyer",
        "payment_order",
        "package_code",
        "package_snapshot",
        "duration_seconds",
        "price_eur_cents",
        "ranking_weight",
        "business_settings_version",
        "status",
        "ranking_effect_display",
        "activated_at",
        "expires_at",
        "cancelled_at",
        "disposition_reason",
        "created_at",
        "updated_at",
    )
    readonly_fields = fields

    def has_add_permission(self, request):  # noqa: ARG002
        return False

    def has_change_permission(self, request, obj=None):  # noqa: ARG002
        return False

    def has_delete_permission(self, request, obj=None):  # noqa: ARG002
        return False

    status_chip = status("status", "Status")
    price_display = money("price_eur_cents", "Price")

    @admin.display(boolean=True, description="Ranking effect")
    def ranking_effect_display(self, obj: BoostPurchase) -> bool:
        """Is this purchase actually boosting anything right now?"""

        return obj.is_active()
