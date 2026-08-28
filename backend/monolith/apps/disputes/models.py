"""Disputes: the only thing that can stop a payout, and the only thing that can
move money after delivery has been confirmed.

A dispute is a first-class record, not a flag on the Deal, for three reasons.
It needs its own state machine and its own audit trail; it needs an evidence
bundle captured at the moment it was opened, before anybody could tidy anything
up; and its resolution is a financial operation that has to be idempotent under
two administrators clicking at the same time.

The freeze is structural. `apps.finance.payout_release` refuses to make a payout
eligible while a row here is in one of `ACTIVE_STATUSES`, and both that check
and this table are reached through the same `lock_deal_aggregate` entry point,
so "the timer read stale dispute state" is not an available interleaving.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q


class Dispute(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        AWAITING_EVIDENCE = "awaiting_evidence", "Awaiting evidence"
        UNDER_REVIEW = "under_review", "Under review"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    class OpenedByRole(models.TextChoices):
        SENDER = "sender", "Sender"
        TRAVELER = "traveler", "Traveler"
        ADMIN = "admin", "Admin"

    class Category(models.TextChoices):
        NOT_DELIVERED = "not_delivered", "Parcel not delivered"
        DAMAGED = "damaged", "Parcel damaged"
        WRONG_ITEM = "wrong_item", "Wrong or missing contents"
        LATE = "late", "Delivered far too late"
        NO_SHOW = "no_show", "Counterparty did not show up"
        PAYMENT = "payment", "Payment or amount problem"
        OTHER = "other", "Other"

    class Resolution(models.TextChoices):
        FULL_SENDER_REFUND = "full_sender_refund", "Full sender refund"
        FULL_TRAVELER_PAYOUT = "full_traveler_payout", "Full traveler payout"
        PARTIAL_SPLIT = "partial_split", "Partial split"

    #: While a dispute is in one of these, the payout stays frozen.
    ACTIVE_STATUSES = ("open", "awaiting_evidence", "under_review")

    public_reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    deal = models.ForeignKey(
        "deals.Deal",
        on_delete=models.PROTECT,
        related_name="disputes",
    )
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="disputes_opened",
    )
    opened_by_role = models.CharField(max_length=10, choices=OpenedByRole.choices)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.OPEN, db_index=True
    )
    category = models.CharField(max_length=20, choices=Category.choices)
    reason_text = models.TextField(max_length=4_000)

    #: Immutable references captured when the dispute opened: the Deal
    #: timeline, offer history, terms, payment/refund/payout events, handover
    #: verification and attempt events, chat and journey-proof references. It
    #: holds ids and facts, never a handover code and never recipient contact
    #: details.
    evidence_bundle = models.JSONField(default=dict, blank=True)

    #: Copied from the Deal so the record still explains itself if the Deal is
    #: later resolved, refunded or archived.
    protection_ends_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(auto_now_add=True, db_index=True)

    resolution = models.CharField(
        max_length=24, choices=Resolution.choices, blank=True, default=""
    )
    #: The resolved split, in canonical EUR cents. The three must sum to the
    #: total the platform actually collected for this Deal; the check below and
    #: the ledger both refuse anything else.
    sender_refund_eur_cents = models.PositiveBigIntegerField(null=True, blank=True)
    traveler_payout_eur_cents = models.PositiveBigIntegerField(null=True, blank=True)
    platform_fee_eur_cents = models.PositiveBigIntegerField(null=True, blank=True)
    collected_total_eur_cents = models.PositiveBigIntegerField(null=True, blank=True)
    resolution_note = models.TextField(blank=True, default="", max_length=4_000)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="disputes_resolved",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    #: True once the payout has actually been moved out of an eligible state
    #: (or was already `not_eligible`) because of this dispute.
    payout_frozen = models.BooleanField(default=False)
    #: True when the dispute was opened after the payout had already been paid.
    #: Only an admin can reach that state; a party's dispute window closes with
    #: the protection window, before any payout can be released.
    payout_already_settled = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "disputes_dispute"
        ordering = ["-opened_at", "-id"]
        # Named capabilities rather than a single is_staff flag. Reading a
        # party's evidence and moving their money are different jobs and are
        # granted separately; see `apps.core.permissions`.
        permissions = [
            ("resolve_dispute", "Can resolve a dispute and settle its money"),
            ("view_dispute_evidence", "Can view dispute evidence files"),
        ]
        constraints = [
            # One active dispute per Deal. A second "open dispute" call from a
            # retrying client resolves to the existing row instead of creating
            # a rival one with its own resolution.
            models.UniqueConstraint(
                fields=["deal"],
                condition=Q(status__in=["open", "awaiting_evidence", "under_review"]),
                name="disputes_one_active_per_deal",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(status="resolved")
                    | (
                        ~Q(resolution="")
                        & Q(resolved_at__isnull=False)
                        & Q(resolved_by__isnull=False)
                    )
                ),
                name="disputes_resolved_requires_evidence",
            ),
            # Money may not appear or vanish in a resolution. Every cent the
            # platform collected is returned, paid out, or kept as commission.
            models.CheckConstraint(
                condition=(
                    Q(collected_total_eur_cents__isnull=True)
                    | Q(
                        collected_total_eur_cents=(
                            F("sender_refund_eur_cents")
                            + F("traveler_payout_eur_cents")
                            + F("platform_fee_eur_cents")
                        )
                    )
                ),
                name="disputes_resolution_reconciles",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "-opened_at"], name="disputes_queue_idx"),
            models.Index(fields=["deal", "-opened_at"], name="disputes_deal_idx"),
        ]

    @property
    def is_active(self) -> bool:
        return self.status in self.ACTIVE_STATUSES

    def __str__(self) -> str:
        return f"Dispute#{self.pk} deal={self.deal_id} ({self.status})"


class DisputeEvent(models.Model):
    """Append-only dispute timeline. Mirrors the Deal timeline's rules."""

    class Kind(models.TextChoices):
        OPENED = "opened", "Opened"
        STATUS_CHANGED = "status_changed", "Status changed"
        EVIDENCE_ADDED = "evidence_added", "Evidence added"
        BUNDLE_CAPTURED = "bundle_captured", "Evidence bundle captured"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"
        PAYOUT_FROZEN = "payout_frozen", "Payout frozen"
        NOTE = "note", "Administrative note"

    dispute = models.ForeignKey(
        Dispute, on_delete=models.PROTECT, related_name="events"
    )
    kind = models.CharField(max_length=24, choices=Kind.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="dispute_events",
    )
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "disputes_event"
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(
                fields=["dispute", "created_at"], name="disputes_event_idx"
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Dispute events are append-only.")
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"DisputeEvent#{self.pk} {self.kind}"


class DisputeEvidence(models.Model):
    """A party's own submission: text, a photo or a video.

    Media lives in the private object store; only the key is here. Access is
    always through a short-lived signed URL issued by the API after an
    authorization check, never by handing out a bucket path.
    """

    class Kind(models.TextChoices):
        TEXT = "text", "Text"
        PHOTO = "photo", "Photo"
        VIDEO = "video", "Video"

    dispute = models.ForeignKey(
        Dispute, on_delete=models.PROTECT, related_name="evidence"
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="dispute_evidence",
    )
    kind = models.CharField(max_length=10, choices=Kind.choices)
    text = models.TextField(blank=True, default="", max_length=4_000)
    storage_bucket = models.CharField(max_length=64, blank=True, default="")
    storage_key = models.CharField(max_length=255, blank=True, default="")
    content_type = models.CharField(max_length=64, blank=True, default="")
    size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    #: SHA-256 of the stored bytes, so a later download can be proven to be the
    #: file that was submitted.
    content_sha256 = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "disputes_evidence"
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(kind="text", storage_key="") & ~Q(text="")
                    | (~Q(kind="text") & ~Q(storage_key=""))
                ),
                name="disputes_evidence_payload_matches_kind",
            ),
        ]
        indexes = [
            models.Index(
                fields=["dispute", "created_at"], name="disputes_evidence_idx"
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Dispute evidence is append-only.")
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"DisputeEvidence#{self.pk} dispute={self.dispute_id} {self.kind}"
