"""View-only admin for the tables that only hold pre-V1 history.

The legacy DZD payment, wallet and match-handover tables keep their rows
because they are history, but L1A removed every service that acted on them.
An edit in the Django admin would therefore change a historical record with
no ledger entry, no event and no audit row, and the legacy withdrawal action
marked money as sent without moving any. These pages are for reading only.
"""

from __future__ import annotations

from django.contrib import admin


class HistoricalRecordAdmin(admin.ModelAdmin):
    """No add, no change, no delete, no bulk actions."""

    actions = None

    def has_add_permission(self, request):  # noqa: ARG002
        return False

    def has_change_permission(self, request, obj=None):  # noqa: ARG002
        return False

    def has_delete_permission(self, request, obj=None):  # noqa: ARG002
        return False


class HistoricalRecordInline(admin.TabularInline):
    """The inline counterpart: rows are listed, never added or removed."""

    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):  # noqa: ARG002
        return False

    def has_change_permission(self, request, obj=None):  # noqa: ARG002
        return False
