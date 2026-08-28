"""Read-only KYC inspection for the Django admin.

Per CLAUDE.md §1, Go owns the runtime KYC API. Phase 6A's authenticated
operations API is the review surface: operators approve/reject pending
submissions through the domain service, which updates the account witness and
writes an audit record. The Django admin remains a read-only inspection view.
"""

from __future__ import annotations

from django.contrib import admin
from .models import KycSubmission


@admin.register(KycSubmission)
class KycSubmissionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "document_type",
        "status",
        "reviewed_at",
        "created_at",
    )
    list_filter = ("status", "document_type")
    search_fields = ("user__email", "user__phone")
    readonly_fields = (
        "user",
        "document_type",
        "front_image_key",
        "back_image_key",
        "selfie_image_key",
        "status",
        "rejection_reason",
        "created_at",
        "updated_at",
        "reviewed_at",
        "reviewed_by_id",
    )
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        # KYC submissions are created by the verification service.  Review
        # decisions must use the Phase 6A API/service so they validate a
        # reason, update the account witness, and write an audit record.
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
