"""KYC schema — Django defines the table, Go owns the runtime API.

Per CLAUDE.md §1: Go's kyc-service writes to this table; Django reads the
latest status via the model and reflects ban/active state. Status updates
flow Django←Go via gRPC + Redis (`kyc.status_changed`), but the underlying
storage is one shared Postgres table.

This module is **schema-only**: no business logic, no DRF views, no admin
write actions. Django manages migrations; the Go service does inserts /
updates via sqlc-generated repos.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class KycSubmission(models.Model):
    """One submission per (user, document_type) lifecycle.

    A user can have multiple submissions over time (re-submission after
    rejection, document renewal). The latest non-rejected row per user is
    the "current" record.
    """

    class DocumentType(models.TextChoices):
        ID_CARD = "id_card", "National ID"
        PASSPORT = "passport", "Passport"
        DRIVING_LICENSE = "driving_license", "Driving License"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        EXPIRED = "expired", "Expired"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="kyc_submissions",
        db_index=True,
    )
    document_type = models.CharField(
        max_length=24, choices=DocumentType.choices
    )

    # Front + back image keys in MinIO/S3. The bytes never touch Django.
    front_image_key = models.CharField(max_length=512)
    back_image_key = models.CharField(max_length=512, blank=True, default="")
    selfie_image_key = models.CharField(max_length=512, blank=True, default="")

    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    rejection_reason = models.TextField(blank=True, default="", max_length=2000)
    reviewed_by_id = models.BigIntegerField(
        null=True, blank=True,
        help_text="ID of the reviewer (operator user). Loose FK; no cascade.",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "kyc_submission"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["user", "-created_at"], name="kyc_user_latest_idx"
            ),
            models.Index(fields=["status"], name="kyc_status_idx"),
        ]
        constraints = [
            # Only one APPROVED submission per (user, document_type).
            # Multiple PENDING/REJECTED rows are allowed (resubmission flow).
            models.UniqueConstraint(
                fields=["user", "document_type"],
                condition=models.Q(status="approved"),
                name="kyc_one_approved_per_user_doctype",
            ),
        ]

    def __str__(self) -> str:
        return f"KycSubmission #{self.id} user={self.user_id} {self.status}"
