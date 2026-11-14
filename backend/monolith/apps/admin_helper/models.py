"""The AI helper's keys and its call log (spec 20.2 and 20.6, plan L15).

A key is what an admin pastes into their own AI assistant. Wassla keeps only
its SHA-256 and its last four characters: the plain key exists once, in the
response that created it. A key acts as its admin, with that admin's rights
read fresh on every call (`apps.admin_helper.keys.resolve_key`), and it opens
only `/api/admin/helper/`.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class AdminHelperKey(models.Model):
    class Kind(models.TextChoices):
        #: Reads the admin's briefing, queues and records. Lasts 8 hours.
        READ = "read", "Read key"
        #: Prepares changes (L16). Lasts 30 minutes.
        CHANGE = "change", "Change key"

    class StopReason(models.TextChoices):
        #: The admin stopped their own key.
        STOPPED = "stopped", "Stopped by its admin"
        #: A Super Admin stopped it from the AI helper page.
        STOPPED_BY_SUPER_ADMIN = "stopped_by_super_admin", "Stopped by a Super Admin"
        #: A new key of the same kind was created.
        REPLACED = "replaced", "Replaced by a new key"
        #: The admin's two-step sign-in was reset, so what the key was created
        #: behind is gone.
        TWO_STEP_RESET = "two_step_reset", "Two-step sign-in was reset"
        #: The AI helper switch was turned off (spec 20.8): every key stops
        #: for good, so turning it back on revives none.
        SWITCHED_OFF = "switched_off", "The AI helper was switched off"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="helper_keys",
    )
    kind = models.CharField(max_length=8, choices=Kind.choices)
    #: SHA-256 of the plain key, hex. The plain key is never stored.
    key_hash = models.CharField(max_length=64, unique=True)
    #: The plain key's last four characters, so its admin can tell keys apart.
    hint = models.CharField(max_length=4)
    created_at = models.DateTimeField()
    #: Set once, at creation, from the policy of that moment. It never moves:
    #: using a key does not extend it (spec 20.2).
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.CharField(
        max_length=24, choices=StopReason.choices, blank=True, default=""
    )
    last_used_at = models.DateTimeField(null=True, blank=True)
    use_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "admin_helper_key"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("admin", "-created_at"), name="admin_helper_key_admin_idx"),
        ]
        constraints = [
            # One live key per admin and kind: creating a new one stops the
            # old one in the same transaction (`keys.issue_key`).
            models.UniqueConstraint(
                fields=("admin", "kind"),
                condition=Q(revoked_at__isnull=True),
                name="admin_helper_one_live_key",
            ),
            models.CheckConstraint(
                condition=Q(kind__in=("read", "change")),
                name="admin_helper_key_kind_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(revoked_at__isnull=True, revoked_reason="")
                    | (Q(revoked_at__isnull=False) & ~Q(revoked_reason=""))
                ),
                name="admin_helper_key_stop_has_reason",
            ),
            models.CheckConstraint(
                condition=Q(expires_at__gt=models.F("created_at")),
                name="admin_helper_key_expires_after_creation",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} …{self.hint} ({self.admin_id})"


class AdminHelperCall(models.Model):
    """One call a helper key made (spec 20.6). Kept 30 days.

    The path is stored without its query string, so nothing an assistant
    typed into a search reaches the log.
    """

    key = models.ForeignKey(AdminHelperKey, on_delete=models.PROTECT, related_name="calls")
    method = models.CharField(max_length=8)
    path = models.CharField(max_length=300)
    status = models.PositiveSmallIntegerField()
    at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "admin_helper_call"
        ordering = ("-at", "-id")
        indexes = [
            models.Index(fields=("key", "-at"), name="admin_helper_call_key_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.method} {self.path} {self.status}"
