"""Operations view over the J2 Boost audit trail."""

from __future__ import annotations

from django.contrib import admin

from apps.core.admin_display import money

from .models import BoostIntentEvent


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
