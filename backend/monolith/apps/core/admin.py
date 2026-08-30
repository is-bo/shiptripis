from __future__ import annotations

from django.contrib import admin
from django.template.loader import render_to_string
from django.utils.html import format_html

from apps.core.admin_display import basis_points, status
from apps.core.policy_display import boost_packages, policy_rows

from .models import BusinessSettingsVersion, PublishedEvent


@admin.register(PublishedEvent)
class PublishedEventAdmin(admin.ModelAdmin):
    list_display = (
        "event_id",
        "channel",
        "published_at",
        "delivered_at",
        "undelivered_chip",
    )
    list_filter = ("channel",)
    search_fields = ("event_id", "channel")
    readonly_fields = (
        "id",
        "channel",
        "event_id",
        "payload_hash",
        "published_at",
        "delivered_at",
    )
    date_hierarchy = "published_at"
    ordering = ("-published_at",)

    # An undelivered event is the queue signal on this page, so it reads as an
    # alarm rather than as a boolean that happens to be true.
    @admin.display(description="Delivery", ordering="delivered_at")
    def undelivered_chip(self, obj: PublishedEvent) -> str:
        if obj.delivered_at is None:
            return format_html('<span class="st-chip st-attn">Undelivered</span>')
        return format_html('<span class="st-chip st-ok">Delivered</span>')


@admin.register(BusinessSettingsVersion)
class BusinessSettingsVersionAdmin(admin.ModelAdmin):
    """Read-only inspection of the versioned commercial configuration.

    Creating and activating a revision used to be possible from this page, and
    should not have been. Phase 6A makes settings activation a named,
    least-privilege capability: `POST /api/admin/settings` checks
    `CanManageSettings`, validates the policy through
    `AdminSettingsCreateSerializer`, requires a written reason, and records the
    change in the immutable admin audit stream in the same transaction.

    The Django admin action bypassed all four. It ran on Django's generic
    `core.change_businesssettingsversion` model permission rather than the
    Phase 6A capability, wrote no audit row, and — through the ordinary add
    form — accepted an arbitrary `policy` document that the API's validation
    would have rejected. Commission rates, deposits, FX and the protection and
    buffer windows are exactly the settings that must not be changeable through
    an unaudited path, so this page inspects and the audited route decides.
    """

    list_display = (
        "version",
        "status_chip",
        "canonical_currency",
        "commission_display",
        "pricing_version",
        "activated_at",
        "created_by",
        "created_at",
    )
    status_chip = status("status", "Status")
    commission_display = basis_points("commission_rate_bps", "Commission")
    list_filter = ("status", "canonical_currency", "pricing_version")
    search_fields = ("version", "pricing_version", "created_by__email")
    list_select_related = ("created_by",)
    ordering = ("-version",)
    fields = (
        "version",
        "status",
        "canonical_currency",
        "commission_rate_bps",
        "commission_display",
        "pricing_version",
        "key_values",
        "policy",
        "created_by",
        "activated_at",
        "created_at",
    )
    readonly_fields = fields

    @admin.display(description="Key values")
    def key_values(self, obj: BusinessSettingsVersion) -> str:
        """The knobs an operator is actually asked about, in their own units.

        The stored document stays below this table and remains the authority.
        Every row names the key it read, so the reading can be checked rather
        than trusted, and a key that is absent says so instead of showing a
        plausible default.
        """

        return render_to_string(
            "admin/core/businesssettingsversion/key_values.html",
            {
                "rows": policy_rows(
                    obj.policy, commission_rate_bps=obj.commission_rate_bps
                ),
                "packages": boost_packages(obj.policy),
            },
        )

    def has_add_permission(self, request):  # noqa: ARG002
        return False

    def has_change_permission(self, request, obj=None):  # noqa: ARG002
        return False

    def has_delete_permission(self, request, obj=None):  # noqa: ARG002
        return False
