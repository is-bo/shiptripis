"""Operations view over paid boosts.

Registered read-only, for the same reason every financial model is: a purchase
carries the price, duration and weight the buyer was quoted, and its status is
the joint outcome of a provider payment, the request's own state and a durable
expiry job. An operator who could edit these rows by hand could grant a paid
ranking weight nobody bought, or strand money by marking a refunded purchase
active.

`Ranking effect` is shown as one half of the product; the immutable Traveler
bonus and platform revenue columns show the other. Ranking is the computed
answer -- active status, and an expiry still in the future -- rather
than the stored status, so a boost whose expiry job has not run yet is visible
as what it actually is.
"""

from __future__ import annotations

from django.contrib import admin

from apps.core.admin_display import money, status

from .models import BoostIntentEvent, BoostPurchase


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
        "amount_display",
        "traveler_bonus_display",
        "platform_revenue_display",
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
        "amount_eur_cents",
        "economics_version",
        "traveler_share_bps",
        "traveler_boost_eur_cents",
        "platform_boost_eur_cents",
        "deal",
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
    amount_display = money("amount_eur_cents", "Sender paid")
    traveler_bonus_display = money("traveler_boost_eur_cents", "Traveler bonus")
    platform_revenue_display = money("platform_boost_eur_cents", "Platform revenue")

    @admin.display(boolean=True, description="Ranking effect")
    def ranking_effect_display(self, obj: BoostPurchase) -> bool:
        """Is this purchase actually boosting anything right now?"""

        return obj.is_active()


@admin.register(BoostIntentEvent)
class BoostIntentEventAdmin(admin.ModelAdmin):
    """The J2 Boost audit trail. Append-only, so read-only here too.

    A Boost moves money without a payment of its own, so who changed it, from
    what, to what and under which settings revision is the whole evidence base
    for a Boost figure on a Deal. An operator who could edit a row here could
    rewrite that evidence after the fact.
    """

    list_display = (
        "id",
        "delivery_request",
        "reason",
        "previous_display",
        "amount_display",
        "request_status",
        "created_at",
    )
    list_filter = ("reason", "request_status")
    search_fields = ("delivery_request__id",)
    ordering = ("-created_at", "-id")
    fields = (
        "delivery_request",
        "actor",
        "deal",
        "reason",
        "previous_eur_cents",
        "amount_eur_cents",
        "commission_rate_bps",
        "ranking_weight",
        "business_settings_version",
        "request_status",
        "created_at",
    )
    readonly_fields = fields

    def has_add_permission(self, request):  # noqa: ARG002
        return False

    def has_change_permission(self, request, obj=None):  # noqa: ARG002
        return False

    def has_delete_permission(self, request, obj=None):  # noqa: ARG002
        return False

    previous_display = money("previous_eur_cents", "Boost before")
    amount_display = money("amount_eur_cents", "Boost after")
