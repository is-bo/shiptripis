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


class PreparedAction(models.Model):
    """A change the helper prepared for its admin to confirm (spec 20.4, plan L16).

    Nothing happens when the helper prepares it. The admin opens it on the
    console, reads the server's summary and confirms; only then does the
    console's own action run, as that admin, with their rights at that moment
    (`apps.admin_helper.prepared.confirm`). It can be confirmed once, by the
    admin whose key prepared it, while it waits and before it expires.

    ``basis`` is what the target looked like when the change was prepared. It
    never leaves the server: confirming compares it with the target now, and
    any difference is "This no longer applies".
    """

    class Status(models.TextChoices):
        WAITING = "waiting", "Waiting for confirmation"
        CONFIRMED = "confirmed", "Confirmed"
        REJECTED = "rejected", "Rejected"
        EXPIRED = "expired", "Expired"
        FAILED = "failed", "No longer applied"

    REASON_MAX_LENGTH = 500

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="helper_prepared_actions",
    )
    key = models.ForeignKey(
        AdminHelperKey, on_delete=models.PROTECT, related_name="prepared_actions"
    )
    #: The registry code (`apps.admin_helper.actions.registry`).
    action = models.CharField(max_length=40)
    target_type = models.CharField(max_length=16)
    target_id = models.PositiveBigIntegerField()
    #: The parameters as the registry cleaned them.
    params = models.JSONField(default=dict, blank=True)
    #: Why the helper prepared it, as the assistant wrote it. Shown on the
    #: console in a box marked as written by the AI helper.
    helper_reason = models.CharField(max_length=REASON_MAX_LENGTH)
    #: The server's own one-line description, written at preparation.
    summary = models.CharField(max_length=500)
    basis = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.WAITING, db_index=True
    )
    created_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    decided_at = models.DateTimeField(null=True, blank=True)
    #: What happened: ``{"code", "message"}`` and, once confirmed, the
    #: admin's own reason.
    outcome = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "admin_helper_prepared_action"
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("admin", "status", "-created_at"),
                name="admin_helper_action_admin_idx",
            ),
        ]
        constraints = [
            # One waiting change per admin, action and target: a repeat with
            # the same parameters answers the waiting one again; different
            # parameters are refused until it is decided.
            models.UniqueConstraint(
                fields=("admin", "action", "target_type", "target_id"),
                condition=Q(status="waiting"),
                name="admin_helper_one_waiting_action",
            ),
            models.CheckConstraint(
                condition=Q(
                    status__in=("waiting", "confirmed", "rejected", "expired", "failed")
                ),
                name="admin_helper_action_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(expires_at__gt=models.F("created_at")),
                name="admin_helper_action_expires_after_creation",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="waiting", decided_at__isnull=True)
                    | (~Q(status="waiting") & Q(decided_at__isnull=False))
                ),
                name="admin_helper_action_decided_when_not_waiting",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.action} on {self.target_type} {self.target_id} ({self.status})"
