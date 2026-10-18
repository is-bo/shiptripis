"""Read-only classification and explicit, audited historical outbox decisions."""

import hashlib
import json
from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import OutboundMessage, OutboundSecret


def valid_row_id(value):
    """Reject malformed/overflowing bigint references before querying PostgreSQL."""
    return bool(
        value and value.isascii() and value.isdigit() and len(value) <= 19
        and 0 < int(value) <= 9223372036854775807
    )


def secret_problem(message):
    """Inspect owning state without decrypting, rendering, or auditing a code read."""
    now = timezone.now()
    if message.kind in {
        "email_verification", "password_reset", "admin_invitation",
        "recipient_delivery_code",
    } and not message.secret_ref:
        return "invalid_reference"
    if message.secret_ref.startswith("outbound_secret:"):
        try:
            vault = OutboundSecret.objects.filter(
                pk=message.secret_ref.split(":", 1)[1]
            ).first()
        except (ValueError, TypeError, ValidationError):
            return "invalid_reference"
        if not vault or vault.key != message.key or vault.purpose != message.kind:
            return "invalid_reference"
        if vault.expires_at <= now:
            return "expired"
        if vault.consumed_at or not vault.sealed_value:
            return "consumed"
        prefix, _, identity = message.key.partition(":")
        if prefix in {"email_verification", "password_reset"}:
            from apps.accounts.models import EmailVerificationCode, PasswordResetCode

            model = (
                EmailVerificationCode
                if prefix == "email_verification"
                else PasswordResetCode
            )
            if not valid_row_id(identity):
                return "invalid_reference"
            row = model.objects.select_related("user").filter(pk=identity).first()
            if (
                not row
                or row.user_id != message.recipient_user_id
                or row.user.email.casefold() != message.to_email.casefold()
            ):
                return "recipient_changed"
            if not row.is_active() or (
                prefix == "email_verification" and row.user.is_email_verified
            ):
                return "consumed_or_expired"
            latest = (
                model.objects.filter(user_id=row.user_id)
                .order_by("-created_at", "-pk")
                .first()
            )
            if latest.pk != row.pk:
                return "superseded"
        elif prefix == "admin_invitation":
            from apps.admin_panel.models import AdminInvitation

            try:
                row = AdminInvitation.objects.filter(pk=identity).first()
            except (ValueError, TypeError, ValidationError):
                return "invalid_reference"
            if (
                not row
                or not row.is_active
                or row.email.casefold() != message.to_email.casefold()
            ):
                return "invitation_obsolete"
        return ""
    if message.secret_ref.startswith("handover_code:"):
        from apps.handover.models import DealHandoverCode

        identity = message.secret_ref.split(":", 1)[1]
        if not valid_row_id(identity):
            return "invalid_reference"
        row = DealHandoverCode.objects.filter(
            pk=identity, deal_id=message.deal_id
        ).first()
        if not row or row.status != "active" or row.kind != "delivery":
            return "handover_obsolete"
        from apps.deals.models import DealRecipient

        if not DealRecipient.objects.filter(
            deal_id=message.deal_id, email=message.to_email
        ).exists():
            return "recipient_changed"
    elif message.secret_ref:
        return "invalid_reference"
    return ""


def fingerprint(message):
    # A digest binds review to the exact row; no addresses/context are emitted.
    data = {
        field: str(getattr(message, field))
        for field in (
            "pk",
            "key",
            "kind",
            "to_email",
            "context",
            "secret_ref",
            "status",
            "updated_at",
        )
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def finance_state(message):
    """Read coarse owning state without exposing financial references or PII."""
    from apps.finance.models import PaymentAttempt, PaymentRefund, Payout

    parts = message.key.split(":")
    model, position, label = None, 0, ""
    if (
        message.kind in {"payment_failed", "guest_payment"}
        and len(parts) > 2
        and parts[1] == "attempt"
    ):
        model, position, label = PaymentAttempt, 2, "payment_attempt"
    elif message.kind == "refund_status" and len(parts) > 2 and parts[1] == "refund":
        model, position, label = PaymentRefund, 2, "refund"
    elif (
        message.kind == "payout_status"
        and len(parts) > 1
        and parts[0] == "payout_status"
    ):
        model, position, label = Payout, 1, "payout"
    if model:
        identity = parts[position]
        if not identity.isascii() or not identity.isdigit() or len(identity) > 18:
            return f"{label}:invalid_reference"
        state = (
            model.objects.filter(pk=int(identity))
            .values_list("status", flat=True)
            .first()
        )
        return f"{label}:{state or 'missing'}"
    if (
        message.kind == "payout_status"
        and len(parts) > 1
        and parts[0] == "payout_event"
    ):
        import uuid

        try:
            reference = uuid.UUID(parts[1])
        except ValueError:
            return "payout:invalid_reference"
        state = (
            Payout.objects.filter(public_reference=reference)
            .values_list("status", flat=True)
            .first()
        )
        return f"payout:{state or 'missing'}"
    return ""


def classify(message):
    problem = secret_problem(message)
    state = ""
    if message.deal_id:
        from apps.deals.models import Deal

        state = (
            Deal.objects.filter(pk=message.deal_id)
            .values_list("status", flat=True)
            .first()
            or "missing"
        )
    if problem:
        category = "expired" if "expired" in problem else "obsolete"
    elif not isinstance(message.context, dict):
        category, problem = "obsolete", "invalid_context"
    elif message.kind not in OutboundMessage.Kind.values:
        category, problem = "obsolete", "unknown_kind"
    elif state in {"cancelled", "expired", "completed"} and message.kind in {
        "recipient_delivery_code",
        "pickup_confirmed",
        "delivery_code_released",
        "protection_ending",
    }:
        category, problem = "obsolete", "business_state_changed"
    elif message.created_at < timezone.now() - timedelta(days=1):
        category, problem = "review_required", "historical_notice"
    else:
        category = "current"
    if message.kind == "protection_ending" and isinstance(message.context, dict):
        try:
            deadline = parse_datetime(
                str(message.context.get("protection_ends_at", ""))
            )
        except ValueError:
            deadline = None
        if not deadline or not deadline.tzinfo or deadline <= timezone.now():
            category, problem = "expired", "protection_deadline_passed_or_invalid"
    expiry = None
    if (
        message.secret_ref.startswith("outbound_secret:")
        and problem != "invalid_reference"
    ):
        vault = OutboundSecret.objects.filter(
            pk=message.secret_ref.split(":", 1)[1]
        ).first()
        expiry = vault.expires_at.isoformat() if vault else None
    return {
        "id": message.pk,
        "kind": message.kind,
        "status": message.status,
        "created_at": message.created_at.isoformat(),
        "expires_at": expiry,
        "age_seconds": max(
            0, int((timezone.now() - message.created_at).total_seconds())
        ),
        "business_state": "/".join(filter(None, (state, finance_state(message)))),
        "category": category,
        "reason": problem,
        "fingerprint": fingerprint(message),
    }


@transaction.atomic
def review(*, message_id, expected_fingerprint, action, actor):
    from apps.admin_panel.permissions import has_admin_permission
    from apps.admin_panel.services import record_admin_action
    from .outbox import cancel_message

    if not has_admin_permission(actor, "manage_admins"):
        raise PermissionDenied("Email backlog review requires manage_admins.")
    message = OutboundMessage.objects.select_for_update().get(pk=message_id)
    if (
        message.status != OutboundMessage.Status.PENDING
        or fingerprint(message) != expected_fingerprint
    ):
        raise ValueError("Email changed; repeat the read-only audit.")
    report = classify(message)
    if action == "release":
        if report["category"] in {"expired", "obsolete"}:
            raise ValueError("Expired or obsolete obligations cannot be released.")
        if message.attempts >= message.max_attempts:
            raise ValueError(
                "Retry budget exhausted; reconcile the uncertain outcome before any reissue."
            )
        from apps.core.models import PublishedEvent

        if PublishedEvent.objects.filter(
            event_id=message.transport_event_id, delivered_at__isnull=False
        ).exists():
            raise ValueError(
                "SMTP acceptance already recorded; reconcile rather than resend."
            )
        message.activation_reviewed_at = timezone.now()
        # Old rendered stream entries must not escape after brand/config changes.
        # Their event IDs no longer name an eligible obligation in the Go guard.
        message.transport_event_id = ""
        message.next_attempt_at = timezone.now()
        message.save(
            update_fields=(
                "activation_reviewed_at",
                "transport_event_id",
                "next_attempt_at",
                "updated_at",
            )
        )
    elif action == "cancel":
        cancel_message(key=message.key, reason="activation_review_cancelled")
    else:
        raise ValueError("Unsupported email review action.")
    record_admin_action(
        actor=actor,
        action=f"email_backlog.{action}",
        target=message,
        before={"status": "pending", "category": report["category"]},
        after={"decision": action},
        reason="pre_activation_review",
    )
