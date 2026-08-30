"""Service boundaries for administrative identity and audit actions."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import AdminAuditLog, AdminInvitation
from .permissions import (
    AdminRole,
    assign_admin_roles,
    has_admin_permission,
    normalize_role,
    user_admin_roles,
)


_SECRET_KEY_PARTS = (
    "password",
    "token",
    "secret",
    "code",
    "credential",
    "private_key",
    "sealed",
)


def _safe_json(value: Any):
    """Defensively redact secret-shaped keys in audit metadata."""

    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            key_text = str(key).casefold()
            if any(part in key_text for part in _SECRET_KEY_PARTS):
                clean[str(key)] = "[REDACTED]"
            else:
                clean[str(key)] = _safe_json(item)
        return clean
    if isinstance(value, (list, tuple)):
        return [_safe_json(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _target_parts(target=None, *, target_type: str = "", target_id: str = ""):
    if target is not None:
        meta = target._meta
        target_type = f"{meta.app_label}.{meta.model_name}"
        target_id = str(target.pk)
    return target_type[:128], str(target_id)[:128]


def record_admin_action(
    *,
    actor=None,
    action: str,
    target=None,
    target_type: str = "",
    target_id: str = "",
    before: dict | None = None,
    after: dict | None = None,
    reason: str = "",
    reference: str = "",
    metadata: dict | None = None,
) -> AdminAuditLog:
    """Persist one immutable, redacted administrative audit record."""

    target_type, target_id = _target_parts(
        target, target_type=target_type, target_id=target_id
    )
    return AdminAuditLog.objects.create(
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        reason=(reason or "")[:500],
        reference=(reference or "")[:200],
        before=_safe_json(before or {}),
        after=_safe_json(after or {}),
        metadata=_safe_json(metadata or {}),
    )


def _require_admin_manager(actor, role: str | None = None):
    if not has_admin_permission(actor, "manage_admins"):
        raise PermissionDenied("Only an administrator with manage_admins may do this.")
    if role is not None and normalize_role(role) == AdminRole.SUPER_ADMIN:
        if not getattr(actor, "is_superuser", False):
            raise PermissionDenied("Only a Super Admin may invite a Super Admin.")


@transaction.atomic
def create_admin_invitation(
    *,
    actor,
    email: str,
    role: str,
    ttl: timedelta = timedelta(hours=24),
) -> tuple[AdminInvitation, str]:
    """Create and audit a role-bound invitation.

    No caller can supply a permission list: the role is normalized against the
    fixed matrix before the row is written.
    """

    normalized_role = normalize_role(role)
    _require_admin_manager(actor, normalized_role)
    invitation, plaintext = AdminInvitation.issue(
        email=email,
        role=normalized_role,
        invited_by=actor,
        ttl=ttl,
    )
    from django.conf import settings
    from apps.notifications.models import OutboundMessage
    from apps.notifications.outbox import enqueue_secret_message

    enqueue_secret_message(
        kind=OutboundMessage.Kind.ADMIN_INVITATION,
        key=f"admin_invitation:{invitation.pk}",
        to_email=invitation.email,
        secret=plaintext,
        secret_expires_at=invitation.expires_at,
        context={
            "role_label": invitation.get_role_display(),
            "frontend_base_url": getattr(settings, "FRONTEND_BASE_URL", ""),
        },
    )
    record_admin_action(
        actor=actor,
        action="admin_invitation.created",
        target=invitation,
        after={"email": invitation.email, "role": invitation.role, "expires_at": invitation.expires_at.isoformat()},
        metadata={"invitation_id": str(invitation.pk)},
    )
    return invitation, plaintext


def revoke_admin_invitation(*, actor, invitation_id) -> AdminInvitation:
    """Revoke an unused invitation and audit the decision."""

    _require_admin_manager(actor)
    with transaction.atomic():
        invitation = AdminInvitation.objects.select_for_update().get(pk=invitation_id)
        was_active = invitation.is_active
        if was_active:
            invitation.revoke()
            record_admin_action(
                actor=actor,
                action="admin_invitation.revoked",
                target=invitation,
                before={"role": invitation.role, "email": invitation.email},
                after={"revoked_at": invitation.revoked_at.isoformat()},
                metadata={"invitation_id": str(invitation.pk)},
            )
        return invitation


def accept_admin_invitation(
    *,
    plaintext_token: str,
    password: str = "",
    full_name: str = "",
    authenticated_user=None,
):
    """Consume an invitation atomically and provision the bound account."""

    if not plaintext_token:
        raise ValidationError("Invitation token is required.")
    User = get_user_model()
    with transaction.atomic():
        invitation = AdminInvitation.resolve(plaintext_token, for_update=True)
        if invitation is None:
            raise ValidationError("Invitation is invalid, expired, used, or revoked.")

        existing = User.objects.select_for_update().filter(email__iexact=invitation.email).first()
        if existing is None:
            if not password:
                raise ValidationError("Password is required for a new administrator account.")
            username = invitation.email
            # User.username is unique in the legacy schema.  Email is unique as
            # well, so using the normalized email keeps the account deterministic.
            user = User(
                username=username,
                email=invitation.email,
                full_name=(full_name or invitation.email.split("@", 1)[0])[:120],
            )
        else:
            if (
                authenticated_user is None
                or not getattr(authenticated_user, "is_authenticated", False)
                or authenticated_user.pk != existing.pk
            ):
                raise PermissionDenied(
                    "An existing account must sign in before accepting this invitation."
                )
            user = existing
            if full_name:
                user.full_name = full_name[:120]

        if existing is None:
            validate_password(password, user=user)
            user.set_password(password)
        user.email = invitation.email
        user.is_active = True
        user.is_staff = True
        user.is_email_verified = True
        user.role = "admin"
        user.save()
        assign_admin_roles(
            user,
            (invitation.role,),
            elevate_super_admin=invitation.role == AdminRole.SUPER_ADMIN,
        )

        invitation.used_at = timezone.now()
        invitation.accepted_by = user
        invitation.save(update_fields=("used_at", "accepted_by"))
        record_admin_action(
            actor=user,
            action="admin_invitation.accepted",
            target=user,
            after={"email": user.email, "role": invitation.role, "is_staff": user.is_staff},
            metadata={"invitation_id": str(invitation.pk), "invited_by_id": invitation.invited_by_id},
        )
        return user


@transaction.atomic
def change_admin_role(*, actor, user_id: int, role: str):
    """Assign one fixed role; callers can never submit arbitrary permissions."""

    if not has_admin_permission(actor, "manage_permissions"):
        raise PermissionDenied("Only an administrator with manage_permissions may do this.")
    normalized_role = normalize_role(role)
    if normalized_role == AdminRole.SUPER_ADMIN and not actor.is_superuser:
        raise PermissionDenied("Only a Super Admin may assign the Super Admin role.")

    User = get_user_model()
    user = User.objects.select_for_update().get(pk=user_id)
    if user.pk == actor.pk and user.is_superuser and normalized_role != AdminRole.SUPER_ADMIN:
        raise ValidationError("A Super Admin cannot demote their own active account.")
    before = {
        "roles": user_admin_roles(user),
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
    }
    assign_admin_roles(
        user,
        (normalized_role,),
        elevate_super_admin=user.is_superuser or normalized_role == AdminRole.SUPER_ADMIN,
    )
    # A Super Admin changing another Super Admin to a lesser role is an
    # explicit demotion, not an accidental side effect of ordinary assignment.
    if user.pk != actor.pk and normalized_role != AdminRole.SUPER_ADMIN and user.is_superuser:
        user.is_superuser = False
        user.save(update_fields=("is_superuser",))
    record_admin_action(
        actor=actor,
        action="admin.role_changed",
        target=user,
        before=before,
        after={
            "roles": user_admin_roles(user),
            "is_staff": user.is_staff,
            "is_superuser": user.is_superuser,
        },
    )
    return user


class AdminReviewError(RuntimeError):
    code = "admin_review_not_permitted"


@transaction.atomic
def review_kyc_submission(*, actor, submission_id: int, decision: str, reason: str = ""):
    """Review one pending KYC submission through an auditable locked flow."""

    from apps.accounts.models import User
    from apps.kyc.models import KycSubmission

    if not has_admin_permission(actor, "review_kyc"):
        raise PermissionDenied("KYC review permission is required.")
    if decision not in (KycSubmission.Status.APPROVED, KycSubmission.Status.REJECTED):
        raise AdminReviewError("KYC decisions must be approved or rejected.")
    clean_reason = (reason or "").strip()
    if decision == KycSubmission.Status.REJECTED and not clean_reason:
        raise AdminReviewError("A rejection reason is required.")

    submission = KycSubmission.objects.select_for_update().get(pk=submission_id)
    if submission.status == decision:
        return submission
    if submission.status != KycSubmission.Status.PENDING:
        raise AdminReviewError("Only a pending KYC submission may be reviewed.")
    before = {"status": submission.status, "rejection_reason": submission.rejection_reason}
    submission.status = decision
    submission.rejection_reason = clean_reason if decision == KycSubmission.Status.REJECTED else ""
    submission.reviewed_by_id = actor.pk
    submission.reviewed_at = timezone.now()
    submission.save(
        update_fields=(
            "status",
            "rejection_reason",
            "reviewed_by_id",
            "reviewed_at",
            "updated_at",
        )
    )
    verified = KycSubmission.objects.filter(
        user_id=submission.user_id,
        status=KycSubmission.Status.APPROVED,
    ).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
    ).exists()
    User.objects.filter(pk=submission.user_id).update(is_kyc_verified=verified)
    record_admin_action(
        actor=actor,
        action=f"kyc.{decision}",
        target=submission,
        before=before,
        after={"status": submission.status, "rejection_reason": submission.rejection_reason},
        reason=clean_reason,
    )
    from apps.notifications.models import OutboundMessage
    from apps.notifications.outbox import enqueue_message

    enqueue_message(
        kind=OutboundMessage.Kind.KYC_STATUS,
        key=f"kyc_status:{submission.pk}:{decision}",
        to_email=submission.user.email,
        recipient_user_id=submission.user_id,
        context={
            "status": (
                "approved"
                if decision == KycSubmission.Status.APPROVED
                else "action_required"
            ),
            "reason": submission.rejection_reason,
        },
    )
    return submission


@transaction.atomic
def review_flight_proof(*, actor, proof_id: int, decision: str, reason: str = ""):
    """Review one pending flight proof without exposing a generic status edit."""

    from apps.trips.models import JourneyLegProof

    if not has_admin_permission(actor, "review_flight_proofs"):
        raise PermissionDenied("Flight-proof review permission is required.")
    if decision not in (JourneyLegProof.Status.APPROVED, JourneyLegProof.Status.REJECTED):
        raise AdminReviewError("Flight-proof decisions must be approved or rejected.")
    clean_reason = (reason or "").strip()
    if decision == JourneyLegProof.Status.REJECTED and not clean_reason:
        raise AdminReviewError("A rejection reason is required.")

    proof = JourneyLegProof.objects.select_for_update().get(pk=proof_id)
    if proof.status == decision:
        return proof
    if proof.status != JourneyLegProof.Status.PENDING:
        raise AdminReviewError("Only a pending flight proof may be reviewed.")
    before = {"status": proof.status, "rejection_reason": proof.rejection_reason}
    proof.status = decision
    proof.rejection_reason = clean_reason if decision == JourneyLegProof.Status.REJECTED else ""
    proof.reviewer = actor
    proof.reviewed_at = timezone.now()
    proof.save(
        update_fields=(
            "status",
            "rejection_reason",
            "reviewer",
            "reviewed_at",
            "updated_at",
        )
    )
    record_admin_action(
        actor=actor,
        action=f"flight_proof.{decision}",
        target=proof,
        before=before,
        after={"status": proof.status, "rejection_reason": proof.rejection_reason},
        reason=clean_reason,
    )
    from apps.notifications.models import OutboundMessage
    from apps.notifications.outbox import enqueue_message

    traveler = proof.leg.journey.traveler
    enqueue_message(
        kind=OutboundMessage.Kind.FLIGHT_PROOF_STATUS,
        key=f"flight_proof_status:{proof.pk}:{decision}",
        to_email=traveler.email,
        recipient_user_id=traveler.pk,
        context={
            "status": (
                "approved"
                if decision == JourneyLegProof.Status.APPROVED
                else "action_required"
            ),
            "reason": proof.rejection_reason,
            "journey_reference": f"J-{proof.leg.journey_id}",
        },
    )
    return proof
