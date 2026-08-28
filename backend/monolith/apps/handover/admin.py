"""Operations admin views for Deal handover codes and attempt audit logs.

All handover models are registered strictly read-only. Verification and lifecycle
progressions occur only through transactional service operations with aggregate
locking and event logging. Manual modification by staff would bypass security
controls, unseal secrets without audit, or create invalid state transitions.
"""

from __future__ import annotations

from django.contrib import admin

from .models import DealHandoverCode, HandoverAttempt, HandoverCodeAccess


class _ReadOnlyAdmin(admin.ModelAdmin):
    """No add, no change, no delete. Handover records are immutable."""

    def has_add_permission(self, request):  # noqa: ARG002
        return False

    def has_change_permission(self, request, obj=None):  # noqa: ARG002
        return False

    def has_delete_permission(self, request, obj=None):  # noqa: ARG002
        return False


@admin.register(DealHandoverCode)
class DealHandoverCodeAdmin(_ReadOnlyAdmin):
    # code_hash and sealed_code are deliberately excluded from list_display,
    # fields, readonly_fields, and search_fields: an administrator has no
    # operational need for code material and the Django admin is not an audited
    # reveal path.
    list_display = (
        "id",
        "deal",
        "kind",
        "status",
        "issued_to",
        "used_by",
        "rotation",
        "failed_attempts",
        "lockout_count",
        "locked_until",
        "available_at",
        "released_at",
        "used_at",
        "created_at",
    )
    list_filter = ("kind", "status", "created_at")
    search_fields = ("deal__id", "issued_to__email", "used_by__email")
    date_hierarchy = "created_at"
    fields = (
        "deal",
        "kind",
        "status",
        "code_length",
        "available_at",
        "released_at",
        "failed_attempts",
        "lockout_count",
        "locked_until",
        "issued_to",
        "used_at",
        "used_by",
        "superseded_at",
        "rotation",
        "created_at",
        "updated_at",
    )
    readonly_fields = fields


@admin.register(HandoverAttempt)
class HandoverAttemptAdmin(_ReadOnlyAdmin):
    list_display = (
        "id",
        "deal",
        "code",
        "kind",
        "actor",
        "result",
        "created_at",
    )
    list_filter = ("kind", "result", "created_at")
    search_fields = ("deal__id", "actor__email")
    date_hierarchy = "created_at"
    fields = (
        "deal",
        "code",
        "kind",
        "actor",
        "result",
        "created_at",
    )
    readonly_fields = fields


@admin.register(HandoverCodeAccess)
class HandoverCodeAccessAdmin(_ReadOnlyAdmin):
    list_display = (
        "id",
        "deal",
        "code",
        "purpose",
        "actor",
        "created_at",
    )
    list_filter = ("purpose", "created_at")
    search_fields = ("deal__id", "actor__email")
    date_hierarchy = "created_at"
    fields = (
        "code",
        "deal",
        "purpose",
        "actor",
        "created_at",
    )
    readonly_fields = fields
