from __future__ import annotations

from django.contrib import admin

from .models import PublishedEvent


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
