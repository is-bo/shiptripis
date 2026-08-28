from __future__ import annotations

from django.contrib import admin

from .business_settings import activate_business_settings
from .models import BusinessSettingsVersion, PublishedEvent


@admin.register(PublishedEvent)
class PublishedEventAdmin(admin.ModelAdmin):
    list_display = (
        "event_id",
        "channel",
        "published_at",
        "delivered_at",
        "is_undelivered",
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

    @admin.display(boolean=True, description="Undelivered")
    def is_undelivered(self, obj: PublishedEvent) -> bool:
        return obj.delivered_at is None


@admin.register(BusinessSettingsVersion)
class BusinessSettingsVersionAdmin(admin.ModelAdmin):
    list_display = (
        "version",
        "status",
        "canonical_currency",
        "commission_rate_bps",
        "pricing_version",
        "activated_at",
        "created_at",
    )
    list_filter = ("status", "canonical_currency", "pricing_version")
    readonly_fields = (
        "canonical_currency",
        "created_by",
        "activated_at",
        "created_at",
    )
    ordering = ("-version",)
    actions = ("activate_revision",)

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None:
            fields.extend(
                ("version", "commission_rate_bps", "pricing_version", "policy", "status")
            )
        return tuple(fields)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    @admin.action(description="Activate selected business-settings revision")
    def activate_revision(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(
                request,
                "Select exactly one revision to activate.",
                level="ERROR",
            )
            return
        activate_business_settings(queryset.get())
        self.message_user(request, "Business-settings revision activated.")
