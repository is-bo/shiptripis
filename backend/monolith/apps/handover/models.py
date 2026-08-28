"""Deal-scoped handover codes.

This is a new domain, not a migration of `apps.verification`. The legacy
`HandoverCode` hangs off a `Match`, is auto-issued to the sender the instant a
pickup is verified, and publishes its plaintext over the Redis bus to *both*
parties -- which for a delivery code means straight to the traveler. It also
locks itself before `Match`, inverting the global financial lock order. None of
that is reusable, so the legacy model keeps serving legacy rows and V1 Deals get
this instead. See `docs/PHASE4_HANDOVER_DISPUTES.md` for the full audit.

Two invariants shape everything below:

* **The traveler never reads a delivery code.** There is no field, serializer,
  endpoint, event payload or admin surface that returns one to them. The seal
  exists so the *sender* can re-open a code they already own.
* **The delivery code does not exist for anybody during the safety buffer.**
  `available_at` is a stored column, not a computed convenience, and the
  reveal path compares against it under a row lock.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class DealHandoverCode(models.Model):
    """One issued code for one Deal, in one direction.

    ``code_hash`` answers "is this the right code". ``sealed_code`` answers
    "show me my code again". They are derived from different keys and used by
    different call paths on purpose: verification never decrypts, and revealing
    never compares.
    """

    class Kind(models.TextChoices):
        PICKUP = "pickup", "Pickup (sender to traveler)"
        DELIVERY = "delivery", "Delivery (recipient to traveler)"

    class Status(models.TextChoices):
        #: Issued, but inside a timed safety buffer. Nobody may reveal it.
        BUFFERED = "buffered", "Buffered (safety window open)"
        ACTIVE = "active", "Active"
        USED = "used", "Used"
        LOCKED = "locked", "Locked (attempt budget exhausted)"
        SUPERSEDED = "superseded", "Superseded by a rotation"
        CANCELLED = "cancelled", "Cancelled with the deal"

    #: Statuses a submission may be checked against.
    SUBMITTABLE_STATUSES = ("active",)
    #: Statuses that still occupy the one-live-code-per-kind slot.
    LIVE_STATUSES = ("buffered", "active")

    deal = models.ForeignKey(
        "deals.Deal",
        on_delete=models.PROTECT,
        related_name="handover_codes",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices, db_index=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )

    #: HMAC-SHA256(pepper, deal:kind:code). The pepper is an environment
    #: secret, so a database dump cannot be brute-forced offline.
    code_hash = models.CharField(max_length=64)
    #: Encrypt-then-MAC of the plaintext, bound to (deal, kind). Only the
    #: sender-facing reveal services ever open it; see `apps.handover.codes`.
    sealed_code = models.TextField()
    code_length = models.PositiveSmallIntegerField()

    #: The instant this code may first be revealed. Null means immediately.
    #: For a delivery code it is `pickup_confirmed_at + buffer`, snapshotted
    #: from the Deal's frozen lifecycle policy rather than read live.
    available_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)

    failed_attempts = models.PositiveSmallIntegerField(default=0)
    lockout_count = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    issued_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="deal_handover_codes_issued",
        help_text="Always the sender. The traveler is never issued a code.",
    )
    used_at = models.DateTimeField(null=True, blank=True)
    used_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="deal_handover_codes_redeemed",
    )
    superseded_at = models.DateTimeField(null=True, blank=True)
    rotation = models.PositiveSmallIntegerField(default=1)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "handover_deal_code"
        ordering = ["deal_id", "kind", "-id"]
        constraints = [
            # At most one live code per (deal, kind). Rotation supersedes the
            # previous row before inserting the replacement, in one transaction,
            # so two codes can never both open the same handover.
            models.UniqueConstraint(
                fields=["deal", "kind"],
                condition=Q(status__in=["buffered", "active"]),
                name="handover_one_live_code_per_kind",
            ),
            models.CheckConstraint(
                condition=~Q(code_hash="") & ~Q(sealed_code=""),
                name="handover_code_material_present",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(status="used")
                    | (Q(used_at__isnull=False) & Q(used_by__isnull=False))
                ),
                name="handover_used_requires_actor",
            ),
            # A buffered code has a future availability instant by definition.
            # Without this a bug that forgot to set it would silently make the
            # delivery code revealable the moment pickup was confirmed.
            models.CheckConstraint(
                condition=~Q(status="buffered") | Q(available_at__isnull=False),
                name="handover_buffered_requires_available_at",
            ),
        ]
        indexes = [
            models.Index(fields=["deal", "kind", "status"], name="handover_lookup_idx"),
            models.Index(
                fields=["status", "available_at"], name="handover_release_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"HandoverCode#{self.pk} deal={self.deal_id} {self.kind} ({self.status})"


class HandoverAttempt(models.Model):
    """Append-only audit of every code submission.

    Written for successes and failures alike, and never carrying the submitted
    value or any hint of how close it was. It is both the forensic record for a
    dispute and the input to the sliding-window rate limit, which is why it is
    a table rather than a counter: a counter cannot answer "how many attempts in
    the last hour" after a process restart.
    """

    class Result(models.TextChoices):
        SUCCEEDED = "succeeded", "Succeeded"
        MISMATCH = "mismatch", "Wrong code"
        NOT_AVAILABLE = "not_available", "No submittable code"
        LOCKED = "locked", "Locked out"
        RATE_LIMITED = "rate_limited", "Rate limited"
        NOT_AUTHORIZED = "not_authorized", "Not authorized"
        WRONG_STATE = "wrong_state", "Deal not in a submittable state"

    deal = models.ForeignKey(
        "deals.Deal",
        on_delete=models.PROTECT,
        related_name="handover_attempts",
    )
    code = models.ForeignKey(
        DealHandoverCode,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="attempts",
    )
    kind = models.CharField(max_length=16, choices=DealHandoverCode.Kind.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="handover_attempts",
    )
    result = models.CharField(max_length=20, choices=Result.choices, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "handover_attempt"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["deal", "kind", "-created_at"], name="handover_att_window_idx"
            ),
            models.Index(
                fields=["actor", "-created_at"], name="handover_att_actor_idx"
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Handover attempts are append-only.")
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"HandoverAttempt#{self.pk} deal={self.deal_id} {self.result}"


class HandoverCodeAccess(models.Model):
    """Append-only record of every time a sealed code was actually opened.

    Revealing a code is the one operation that turns stored ciphertext back
    into a secret, so it is audited on its own rather than folded into the Deal
    timeline. The row names who opened what and why; it never stores the value.
    """

    class Purpose(models.TextChoices):
        SENDER_REVEAL = "sender_reveal", "Sender viewed the code"
        RECIPIENT_NOTIFICATION = (
            "recipient_notification",
            "Rendered into the recipient notification",
        )

    code = models.ForeignKey(
        DealHandoverCode,
        on_delete=models.PROTECT,
        related_name="accesses",
    )
    deal = models.ForeignKey(
        "deals.Deal",
        on_delete=models.PROTECT,
        related_name="handover_code_accesses",
    )
    purpose = models.CharField(max_length=32, choices=Purpose.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="handover_code_accesses",
        help_text="Null when the platform rendered a notification.",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "handover_code_access"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["deal", "-created_at"], name="handover_access_idx"),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Handover code accesses are append-only.")
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"HandoverCodeAccess#{self.pk} code={self.code_id} {self.purpose}"
