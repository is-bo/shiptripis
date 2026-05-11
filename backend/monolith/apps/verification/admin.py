from __future__ import annotations

from django.contrib import admin

from .models import HandoverCode


@admin.register(HandoverCode)
class HandoverCodeAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "match",
        "kind",
        "status",
        "attempts",
        "issued_to",
        "used_at",
        "used_by",
        "created_at",
    )
    list_filter = ("status", "kind")
    search_fields = ("match__id", "issued_to__email", "used_by__email")
    readonly_fields = (
        "match",
        "kind",
        "code_hash",
        "issued_to",
        "used_at",
        "used_by",
        "created_at",
    )
