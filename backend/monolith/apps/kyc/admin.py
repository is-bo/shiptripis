"""KYC admin — operators review pending submissions.

Per CLAUDE.md §1, Go owns the runtime KYC API. The Django admin is the
**ops review surface**: operators approve / reject pending submissions
here, and the change is observed by Go via the `kyc.status_changed`
Redis channel (or, in V2, a status webhook).
"""

from __future__ import annotations

from django.contrib import admin
from django.utils import timezone

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
        "created_at",
        "updated_at",
        "reviewed_at",
        "reviewed_by_id",
    )
    actions = ("approve_submissions", "reject_submissions")
    date_hierarchy = "created_at"

    @admin.action(description="Approve selected (set status=approved)")
    def approve_submissions(self, request, queryset):
        now = timezone.now()
        queryset.filter(status=KycSubmission.Status.PENDING).update(
            status=KycSubmission.Status.APPROVED,
            reviewed_at=now,
            reviewed_by_id=request.user.id,
        )
        # Also flip is_kyc_verified on the user — operators expect this.
        from apps.accounts.models import User

        user_ids = list(
            queryset.filter(status=KycSubmission.Status.APPROVED)
            .values_list("user_id", flat=True)
        )
        User.objects.filter(id__in=user_ids).update(is_kyc_verified=True)

    @admin.action(description="Reject selected (set status=rejected)")
    def reject_submissions(self, request, queryset):
        queryset.filter(status=KycSubmission.Status.PENDING).update(
            status=KycSubmission.Status.REJECTED,
            reviewed_at=timezone.now(),
            reviewed_by_id=request.user.id,
        )
