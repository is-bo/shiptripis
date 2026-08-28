"""Administrative identity and audit persistence.

The models in this module intentionally do not contain arbitrary permission
JSON.  Administrative access is granted by the fixed role groups in
``apps.admin_panel.permissions``; invitation rows carry one validated role.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .permissions import ADMIN_PERMISSION_CODES, PERMISSION_LABELS, ROLE_CHOICES, normalize_role


def hash_invitation_token(token: str) -> str:
    """Hash an invitation capability before it is persisted or queried."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AdminAuditLog(models.Model):
    """Immutable record of a sensitive administrative action.

    ``before`` and ``after`` are deliberately JSON snapshots rather than full
    model dumps.  Callers should pass only safe fields; ``record`` applies a
    defensive redaction pass for common secret keys as a final guard.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="admin_audit_actions",
    )
    action = models.CharField(max_length=128, db_index=True)
    target_type = models.CharField(max_length=128, blank=True, default="", db_index=True)
    target_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    reason = models.CharField(max_length=500, blank=True, default="")
    reference = models.CharField(max_length=200, blank=True, default="")
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "admin_panel_audit_log"
        ordering = ("-created_at", "-id")
        # Permissions are all attached to this audit model so the complete
        # matrix can be inspected from Django's permission admin without
        # granting broad model-edit permissions to operators.
        permissions = tuple((code, PERMISSION_LABELS[code]) for code in ADMIN_PERMISSION_CODES)
        indexes = [
            models.Index(fields=("actor", "-created_at"), name="admin_audit_actor_time_idx"),
            models.Index(fields=("target_type", "target_id", "-created_at"), name="admin_audit_target_time_idx"),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Administrative audit logs are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Administrative audit logs are immutable.")

    def __str__(self) -> str:
        target = f" {self.target_type}:{self.target_id}" if self.target_type else ""
        return f"{self.action}{target} ({self.created_at:%Y-%m-%d %H:%M})"

    @classmethod
    def record(cls, **kwargs):
        """Compatibility wrapper around :func:`services.record_admin_action`."""

        from .services import record_admin_action

        return record_admin_action(**kwargs)


class AdminInvitation(models.Model):
    """One-use, email-bound capability to provision an admin account.

    ``token_hash`` is the only token representation stored.  The plaintext is
    returned exactly once by :meth:`issue` so the caller can deliver an email;
    it is never available through the admin list/detail views.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(db_index=True)
    role = models.CharField(max_length=32, choices=ROLE_CHOICES, db_index=True)
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="admin_invitations_sent",
    )
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True, db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True, db_index=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="admin_invitations_accepted",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "admin_panel_invitation"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("email", "expires_at"), name="admin_invite_email_exp_idx"),
            models.Index(fields=("used_at", "revoked_at", "expires_at"), name="admin_invite_active_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(email=""), name="admin_invite_email_nonempty"
            ),
            models.CheckConstraint(
                condition=models.Q(expires_at__gt=models.F("created_at")),
                name="admin_invite_expiry_after_created",
            ),
        ]

    def clean(self):
        self.email = (self.email or "").strip().lower()
        try:
            self.role = normalize_role(self.role)
        except ValueError as exc:
            raise ValidationError({"role": str(exc)}) from exc

    def save(self, *args, **kwargs):
        # ``created_at`` is populated by ``auto_now_add`` during ``save``;
        # validating the database check constraint before then would compare
        # ``expires_at`` to ``None``.  Field/choice validation still runs here;
        # the database enforces the timestamp check at insert time.
        self.full_clean(validate_constraints=False)
        return super().save(*args, **kwargs)

    @classmethod
    def issue(
        cls,
        *,
        email: str,
        role: str,
        invited_by,
        ttl: timedelta = timedelta(hours=24),
    ) -> tuple["AdminInvitation", str]:
        """Create an invitation and return ``(row, plaintext_token)``."""

        if ttl <= timedelta(0):
            raise ValueError("Invitation TTL must be positive")
        plaintext = secrets.token_urlsafe(32)
        now = timezone.now()
        invitation = cls.objects.create(
            email=email.strip().lower(),
            role=normalize_role(role),
            token_hash=hash_invitation_token(plaintext),
            invited_by=invited_by,
            expires_at=now + ttl,
        )
        return invitation, plaintext

    @property
    def is_active(self) -> bool:
        return (
            self.used_at is None
            and self.revoked_at is None
            and self.expires_at > timezone.now()
        )

    @property
    def hashed_token(self) -> str:
        """Read-only alias useful to callers that call the field ``hashed_token``."""

        return self.token_hash

    @classmethod
    def resolve(cls, plaintext_token: str, *, for_update: bool = False):
        """Resolve a plaintext capability without ever storing it."""

        qs = cls.objects
        if for_update:
            qs = qs.select_for_update()
        invitation = qs.filter(token_hash=hash_invitation_token(plaintext_token)).first()
        if invitation is None or not invitation.is_active:
            return None
        return invitation

    def revoke(self, *, at=None):
        if self.used_at is not None:
            return False
        if self.revoked_at is None:
            self.revoked_at = at or timezone.now()
            self.save(update_fields=("revoked_at",))
        return True
