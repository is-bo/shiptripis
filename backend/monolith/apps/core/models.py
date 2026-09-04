"""Cross-cutting models for the monolith.

`PublishedEvent` is the V1 detection-only outbox audit (CLAUDE.md G6b):
every Redis publish writes a row here. A daily Django cron compares
`delivered_at IS NULL AND published_at < now - 5min` against Redis
`delivered:<event_id>:<user_id>` keys and alerts on mismatches.

Full transactional outbox is V2. We don't auto-recover — but we detect.
"""

from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class PublishedEvent(models.Model):
    """Audit row written for each Redis pub/sub publish from Django.

    Schema is intentionally narrow — read by both Django (cron sweep) and
    sqlc-generated Go code (so chat/notif services can mark `delivered_at`
    when they observe the event downstream).
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    channel = models.CharField(max_length=128, db_index=True)
    event_id = models.CharField(max_length=64, unique=True)
    payload_hash = models.CharField(max_length=64)  # sha256 hex
    published_at = models.DateTimeField(auto_now_add=True, db_index=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "core_published_event"
        indexes = [
            models.Index(
                fields=["delivered_at", "published_at"],
                name="core_pe_undelivered_idx",
            ),
        ]
        ordering = ["-published_at"]

    def __str__(self) -> str:
        return f"{self.channel}/{self.event_id}"


class BusinessSettingsVersion(models.Model):
    """Versioned, auditable business inputs used by new V1 economics.

    Policy/economic fields become immutable after creation. Lifecycle state
    may move from draft to active to retired through the service boundary.
    Offers and Deals copy the values they use, so a later active revision
    cannot mutate historical economics.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        RETIRED = "retired", "Retired"

    version = models.PositiveIntegerField(unique=True)
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    canonical_currency = models.CharField(max_length=3, default="EUR", editable=False)
    commission_rate_bps = models.PositiveSmallIntegerField(default=2500)
    pricing_version = models.CharField(max_length=32, default="v1")
    policy = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="business_settings_versions_created",
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "core_business_settings_version"
        ordering = ["-version"]
        constraints = [
            models.CheckConstraint(
                condition=Q(canonical_currency="EUR"),
                name="core_settings_currency_eur",
            ),
            models.CheckConstraint(
                condition=Q(commission_rate_bps__lte=10_000),
                name="core_settings_commission_bps",
            ),
            models.UniqueConstraint(
                fields=["status"],
                condition=Q(status="active"),
                name="core_settings_one_active",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "-version"], name="core_settings_status_idx"
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            immutable_fields = (
                "version",
                "canonical_currency",
                "commission_rate_bps",
                "pricing_version",
                "policy",
                "created_by_id",
            )
            if any(
                getattr(previous, field) != getattr(self, field)
                for field in immutable_fields
            ):
                raise ValidationError(
                    "Business setting values are immutable; create a new version."
                )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Business settings revisions are append-only and cannot be deleted."
        )

    def __str__(self) -> str:
        return f"Business settings v{self.version} ({self.status})"
