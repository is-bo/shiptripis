"""Durable transactional messaging: arm an obligation, render it, dispatch it.

Why this exists at all is worth being precise about, because the platform
already has two things that look like notification infrastructure and neither of
them is a promise:

* `redis_bus.publish_after_commit` is a live fan-out plus an in-app inbox row.
  It is fire-and-forget by design and is documented as such.
* The generic Redis email stream carries only non-secret, already-rendered
  messages. Secret-bearing messages (verification, password reset, invitations,
  and delivery codes) are rendered and sent through Django's trusted SMTP
  boundary so their plaintext never enters Redis.

The Phase 4 obligation is a PostgreSQL row (`OutboundMessage`). The Redis stream
is only how it travels once it exists. That is the same rule Phase 3 applied to
money: Redis may accelerate, Redis is never the record.

**Secret material never rests in message context or transport events.**
`context` holds what a template needs and nothing secret. A code is named by
`secret_ref` and resolved only in the final trusted SMTP render/send boundary;
the plaintext is not in this table, Redis, `core_published_event`, the in-app
inbox, audit metadata, or logs.

**Delivery semantics.** One logical message is one row, deduplicated on `key`,
so arming it twice is arming it once. Dispatch claims the row, hands the
rendered body to the transport, and only then marks it dispatched: a crash in
between can resend the same logical content with a stable Message-ID.
The obligation is unique; SMTP transport remains at-least-once. A crash after
SMTP acceptance but before the database commit can produce a duplicate. SMTP
acceptance is not evidence of final inbox delivery.
"""

from __future__ import annotations

import json
import logging
import uuid
import smtplib
import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone as datetime_timezone
from urllib.parse import quote, urlsplit
from email.utils import parseaddr

import redis
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import IntegrityError, connection, transaction
from django.utils import translation
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import redis_bus
from apps.core.languages import normalize_communication_language
from apps.core.models import PublishedEvent

from .email_layout import EmailDocument, to_html, to_text

from .models import OutboundMessage, OutboundSecret

logger = logging.getLogger(__name__)

_EMAIL_STREAM = "email:send"
_EMAIL_STREAM_MAXLEN = 10_000
_DELIVERY_RECEIPT_TIMEOUT = timedelta(minutes=2)
_SECRET_PROVIDER_KINDS = frozenset(
    {
        OutboundMessage.Kind.EMAIL_VERIFICATION,
        OutboundMessage.Kind.PASSWORD_RESET,
        OutboundMessage.Kind.ADMIN_INVITATION,
        OutboundMessage.Kind.RECIPIENT_DELIVERY_CODE,
    }
)


class SecretUnavailable(RuntimeError):
    """A message referenced a secret that can no longer be resolved."""


class EmailDeliveryError(OSError):
    """Fixed-vocabulary error safe for the durable job runner and logs."""


# --- arming -------------------------------------------------------------------


def enqueue_message(
    *,
    kind: str,
    key: str,
    to_email: str,
    context: dict | None = None,
    deal_id: int | None = None,
    recipient_user_id: int | None = None,
    secret_ref: str = "",
    language: str | None = None,
    run_at: datetime | None = None,
    max_attempts: int = 10,
) -> OutboundMessage:
    """Record the obligation and arm its durable dispatch job. Idempotent on `key`.

    Call inside the transaction that made the message true. The row and the fact
    it describes then commit together, so there is no window in which the Deal
    says a recipient was notified and no obligation exists to notify them.
    """

    run_at = run_at or timezone.now()
    if language is None and recipient_user_id is not None:
        from apps.accounts.models import User

        language = (
            User.objects.filter(pk=recipient_user_id)
            .values_list("preferred_language", flat=True)
            .first()
        )
    resolved_language = normalize_communication_language(language)
    if context is not None and not isinstance(context, dict):
        raise ValueError("Email context must be an object.")
    def check_context(value):
        if isinstance(value, dict):
            for name, item in value.items():
                if any(part in str(name).lower() for part in ("password", "token", "secret", "credential", "sealed")) or str(name).lower() in {"code", "otp", "delivery_code", "reset_code"}:
                    raise ValueError("Secret material must use the trusted secret reference.")
                check_context(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                check_context(item)
    check_context(context)
    try:
        with transaction.atomic():
            message = OutboundMessage.objects.create(
                kind=kind,
                key=key,
                to_email=to_email,
                context=context or {},
                language=resolved_language,
                deal_id=deal_id,
                recipient_user_id=recipient_user_id,
                secret_ref=secret_ref,
                next_attempt_at=run_at,
                max_attempts=max_attempts,
            )
    except IntegrityError:
        return OutboundMessage.objects.get(key=key)

    # Late import: `apps.notifications` must not depend on `apps.finance` at
    # import time, only at call time.
    from apps.finance.models import ScheduledJob
    from apps.finance.services import schedule_job

    schedule_job(
        kind=ScheduledJob.Kind.OUTBOUND_MESSAGE,
        key=f"outbound_message:{message.pk}",
        run_at=run_at,
        payload={"message_id": message.pk},
        max_attempts=max_attempts,
    )
    return message


def enqueue_secret_message(
    *,
    kind: str,
    key: str,
    to_email: str,
    secret: str,
    secret_expires_at: datetime,
    context: dict | None = None,
    recipient_user_id: int | None = None,
    language: str | None = None,
    max_attempts: int = 10,
) -> OutboundMessage:
    """Arm a durable OTP email without storing the plaintext code.

    The authentication-domain row keeps only its verification hash. A
    short-lived, independently encrypted copy is referenced by the outbox and
    erased after SMTP acceptance. The invitation's canonical capability remains
    SHA-256 hashed in its invitation row; this short-lived encrypted delivery
    copy is never exposed by an API, audit row, or event payload.
    """

    allowed = {
        OutboundMessage.Kind.EMAIL_VERIFICATION,
        OutboundMessage.Kind.PASSWORD_RESET,
        OutboundMessage.Kind.ADMIN_INVITATION,
    }
    if kind not in allowed:
        raise ValueError("This message kind cannot use the outbound secret vault.")
    if secret_expires_at <= timezone.now():
        raise ValueError("Outbound email secret expiry must be in the future.")

    from .secrets import seal

    with transaction.atomic():
        existing = OutboundMessage.objects.filter(key=key).first()
        if existing is not None:
            return existing
        secret_id = uuid.uuid4()
        vault, _created = OutboundSecret.objects.get_or_create(
            key=key,
            defaults={
                "id": secret_id, "purpose": kind,
                "sealed_value": seal(secret_id=secret_id, purpose=kind, plaintext=secret),
                "expires_at": secret_expires_at,
            },
        )
        return enqueue_message(
            kind=kind,
            key=key,
            to_email=to_email,
            context=context,
            recipient_user_id=recipient_user_id,
            language=language,
            secret_ref=f"outbound_secret:{vault.pk}",
            max_attempts=max_attempts,
        )


def cancel_message(*, key: str, reason: str = "") -> int:
    """Withdraw an obligation that is no longer true. Never cancels a sent one."""

    from apps.finance.models import ScheduledJob

    now = timezone.now()
    with transaction.atomic():
        message_ids = list(
            OutboundMessage.objects.select_for_update()
            .filter(key=key, status=OutboundMessage.Status.PENDING)
            .values_list("pk", flat=True)
        )
        if not message_ids:
            return 0
        updated = OutboundMessage.objects.filter(pk__in=message_ids).update(
            status=OutboundMessage.Status.CANCELLED,
            last_error=reason[:500],
            updated_at=now,
        )
        ScheduledJob.objects.filter(
            kind=ScheduledJob.Kind.OUTBOUND_MESSAGE,
            payload__message_id__in=message_ids,
            status__in=(ScheduledJob.Status.PENDING, ScheduledJob.Status.FAILED),
        ).update(
            status=ScheduledJob.Status.CANCELLED,
            last_error=reason[:500],
            last_result="message_cancelled",
            completed_at=now,
            updated_at=now,
        )
        return updated


# --- secret resolution --------------------------------------------------------


def resolve_secret(message: OutboundMessage) -> str:
    """Open the one secret a message may carry, at render time only.

    The single supported form is `handover_code:<id>`. Opening it writes a
    `HandoverCodeAccess` audit row with no actor, which is how a
    platform-rendered notification is distinguished from a human reveal.
    """

    if not message.secret_ref:
        return ""
    resolver, _, raw_id = message.secret_ref.partition(":")
    if resolver == "outbound_secret":
        try:
            secret_id = uuid.UUID(raw_id)
        except (TypeError, ValueError) as exc:
            raise SecretUnavailable(
                "The outbound secret reference is invalid."
            ) from exc
        vault = OutboundSecret.objects.filter(pk=secret_id).first()
        if vault is None or vault.consumed_at is not None or not vault.sealed_value:
            raise SecretUnavailable("The outbound email secret is unavailable.")
        if vault.expires_at <= timezone.now():
            raise SecretUnavailable("The outbound email secret has expired.")
        if vault.purpose != message.kind:
            raise SecretUnavailable("The outbound email secret purpose does not match.")
        if vault.key != message.key:
            raise SecretUnavailable("The outbound email secret obligation does not match.")
        from .backlog import secret_problem
        if secret_problem(message):
            raise SecretUnavailable("The email capability is no longer current.")
        from .secrets import OutboundSecretError, unseal

        try:
            return unseal(
                secret_id=vault.pk,
                purpose=vault.purpose,
                sealed_value=vault.sealed_value,
            )
        except OutboundSecretError as exc:
            raise SecretUnavailable(
                "The outbound email secret could not be opened."
            ) from exc

    if resolver != "handover_code" or not raw_id.isdigit():
        raise SecretUnavailable(f"Unsupported secret reference {resolver!r}.")

    from apps.handover.models import DealHandoverCode, HandoverCodeAccess
    from apps.handover.codes import SealError, unseal_code

    code = DealHandoverCode.objects.filter(pk=int(raw_id)).first()
    if code is None:
        raise SecretUnavailable("The referenced handover code no longer exists.")
    if (
        code.status != DealHandoverCode.Status.ACTIVE
        or code.kind != DealHandoverCode.Kind.DELIVERY
        or code.deal_id != message.deal_id
    ):
        # The code was rotated, used or cancelled before this message went out.
        # Sending the old value would be worse than not sending at all.
        raise SecretUnavailable("The handover code is not available for this obligation.")
    from apps.deals.models import DealRecipient
    if not DealRecipient.objects.filter(deal_id=message.deal_id, email=message.to_email).exists():
        raise SecretUnavailable("The delivery recipient has changed.")
    try:
        plaintext = unseal_code(
            deal_id=code.deal_id, kind=code.kind, sealed=code.sealed_code
        )
    except SealError as exc:
        raise SecretUnavailable("The handover code could not be opened.") from exc
    HandoverCodeAccess.objects.create(
        code=code,
        deal_id=code.deal_id,
        purpose=HandoverCodeAccess.Purpose.RECIPIENT_NOTIFICATION,
        actor=None,
    )
    return plaintext


# --- rendering ----------------------------------------------------------------


def _facts(context: dict, *extra: tuple[str, str]) -> tuple[tuple[str, str], ...]:
    """Reference rows. Deliberately a small allow-list of context keys.

    Domain events carry provider references and other operational metadata.
    A transactional email should contain the minimum a recipient needs to
    identify what it is about, and never echo an arbitrary payload.
    """

    rows = [(label, str(value)) for label, value in extra if value]
    reference = context.get("deal_reference", "")
    if reference:
        rows.append((_("Delivery reference"), str(reference)))
    return tuple(rows)


def _amount_fact(context: dict) -> tuple[str, str]:
    raw = context.get("amount_eur_cents")
    if raw in (None, ""):
        return ("", "")
    try:
        cents = int(raw)
    except (TypeError, ValueError):
        return ("", "")
    # LRI/PDI keep the symbol and decimal digits in order in Arabic plain text.
    return (_("Amount"), f"\u2066€{cents // 100}.{cents % 100:02d}\u2069")


def _recipient_delivery_code(context: dict, secret: str) -> EmailDocument:
    reference = context.get("deal_reference", "")
    sender_name = context.get("sender_name", "") or _("Your sender")
    recipient_name = context.get("recipient_name", "")
    greeting = (
        _("Hello %(recipient_name)s,") % {"recipient_name": recipient_name}
        if recipient_name
        else _("Hello,")
    )
    return EmailDocument(
        subject=_("Your Waçla delivery code"),
        preheader=_("Keep this code private until the parcel is in your hands."),
        eyebrow=_("Delivery"),
        heading=_("Your parcel is on its way"),
        paragraphs=(
            greeting,
            _(
                "%(sender_name)s has sent you a parcel through Waçla and it is "
                "on its way."
            )
            % {"sender_name": sender_name},
            _(
                "Give this code to the traveler only once the parcel is physically "
                "in your hands. Entering it confirms delivery and starts the "
                "payment protection window."
            ),
        ),
        highlight=(_("Your delivery code"), secret),
        callout=(
            _(
                "Never share this code by phone, message or email with anyone "
                "before you have the parcel. Waçla will never ask you for it."
            )
        ),
        facts=_facts({"deal_reference": reference}),
    )


def _build_document(message: OutboundMessage) -> EmailDocument:
    """Build the document for one obligation. The only place a code becomes text."""

    if not isinstance(message.context, dict):
        raise SecretUnavailable("Invalid email context.")
    context = dict(message.context)
    kind = message.kind
    reference = context.get("deal_reference", "")

    if kind == OutboundMessage.Kind.EMAIL_VERIFICATION:
        return EmailDocument(
            subject=_("Confirm your Waçla email"),
            preheader=_("Use this code to confirm your email address."),
            eyebrow=_("Account"),
            heading=_("Welcome to Waçla"),
            paragraphs=(
                _(
                    "Enter this code on the verification screen to confirm your "
                    "email address."
                ),
            ),
            highlight=(_("Your verification code"), resolve_secret(message)),
            callout=(
                _(
                    "Use this code before it expires. Waçla will never ask you to share "
                    "this code outside the verification screen."
                )
            ),
        )
    if kind == OutboundMessage.Kind.PASSWORD_RESET:
        return EmailDocument(
            subject=_("Reset your Waçla password"),
            preheader=_("Use this private code to reset your password."),
            eyebrow=_("Account security"),
            heading=_("Reset your password"),
            paragraphs=(_("Enter this code on the password reset screen."),),
            highlight=(_("Your password reset code"), resolve_secret(message)),
            callout=(
                _(
                    "Use this code before it expires. If you did not request this, ignore "
                    "this email and keep your code private."
                )
            ),
        )
    if kind == OutboundMessage.Kind.ADMIN_INVITATION:
        base = str(context.get("frontend_base_url", "")).rstrip("/")
        parsed = urlsplit(base)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
            raise SecretUnavailable("Invitation requires a trusted HTTPS public origin.")
        token = resolve_secret(message)
        locale = normalize_communication_language(message.language)
        invite_url = f"{base}/admin/invitations/accept?language={locale}#token={quote(token, safe='')}"
        roles = {
            "ops": _("Operations"), "support": _("Support"), "finance": _("Finance"),
            "trust_verification": _("Trust / Verification"), "super_admin": _("Super Admin"),
        }
        return EmailDocument(
            subject=_("You have been invited to Waçla Operations"),
            preheader=_("Use your private link to accept this invitation."),
            eyebrow=_("Operations"),
            heading=_("You have been invited to Waçla Operations"),
            paragraphs=(
                _("A Waçla administrator invited you to join the operations team."),
            ),
            action=(_("Accept your invitation"), invite_url),
            callout=_("This private link can be used once. If you were not expecting this, contact Waçla support."),
            facts=((_("Role"), roles.get(context.get("role"), _("Operations"))),),
        )
    if kind == OutboundMessage.Kind.RECIPIENT_DELIVERY_CODE:
        return _recipient_delivery_code(context, resolve_secret(message))

    # The inventory below renders from a small allow-list of context fields.
    if kind == OutboundMessage.Kind.KYC_STATUS:
        approved = context.get("status") == "approved"
        return EmailDocument(
            subject=_("Waçla identity verification update"),
            preheader=(
                _("Your identity verification is approved.")
                if approved
                else _("Your identity verification needs attention.")
            ),
            eyebrow=_("Verification"),
            heading=(
                _("Your identity verification is approved")
                if approved
                else _("Your identity verification needs attention")
            ),
            paragraphs=(
                (
                    _("You can now publish a journey after its other checks pass.")
                    if approved
                    else _("Please review the reason and submit updated documents.")
                ),
                (
                    _("Reason: %(reason)s") % {"reason": context["reason"]}
                    if context.get("reason")
                    else ""
                ),
                _("Open the Waçla app to see the next step."),
            ),
        )
    if kind == OutboundMessage.Kind.FLIGHT_PROOF_STATUS:
        approved = context.get("status") == "approved"
        return EmailDocument(
            subject=_("Waçla flight proof update"),
            preheader=(
                _("Your flight proof is approved.")
                if approved
                else _("Your flight proof needs attention.")
            ),
            eyebrow=_("Verification"),
            heading=(
                _("Your flight proof is approved")
                if approved
                else _("Your flight proof needs attention")
            ),
            paragraphs=(
                (
                    _("The verified flight leg can be used for matching.")
                    if approved
                    else _("Please review the reason and submit updated proof.")
                ),
                (
                    _("Reason: %(reason)s") % {"reason": context["reason"]}
                    if context.get("reason")
                    else ""
                ),
                _("Open the Waçla app to see the next step."),
            ),
            facts=(
                (_("Journey reference"), str(context.get("journey_reference", ""))),
            ),
        )
    if kind == OutboundMessage.Kind.PAYMENT_REQUIRED:
        return EmailDocument(
            subject=_("Payment needed for your Waçla delivery"),
            preheader=_("Open Waçla to review the payment needed."),
            eyebrow=_("Payment"),
            heading=_("A payment is needed to continue"),
            paragraphs=(
                _("A payment is required before this delivery can continue."),
                _("Open Waçla to review the amount and available provider."),
            ),
            facts=_facts(
                context,
                (_("Payment reference"), context.get("payment_reference", reference)),
                _amount_fact(context),
            ),
        )
    if kind == OutboundMessage.Kind.PAYMENT_PROCESSING:
        return EmailDocument(
            subject=_("Your Waçla payment is processing"),
            preheader=_("The provider is still confirming your payment."),
            eyebrow=_("Payment"),
            heading=_("Your payment is being confirmed"),
            paragraphs=(
                _(
                    "Your payment has been received by the provider and is being "
                    "confirmed."
                ),
            ),
            facts=_facts(
                context,
                (_("Payment reference"), context.get("payment_reference", reference)),
            ),
        )
    if kind == OutboundMessage.Kind.PAYMENT_FAILED:
        return EmailDocument(
            subject=_("Your Waçla payment needs attention"),
            preheader=_("The payment failed; open Waçla to try again."),
            eyebrow=_("Payment"),
            heading=_("That payment did not go through"),
            paragraphs=(
                _("The payment provider could not complete this attempt."),
                _("Open Waçla to retry or choose another available provider."),
            ),
            facts=_facts(
                context,
                (_("Payment reference"), context.get("payment_reference", reference)),
                _amount_fact(context),
            ),
        )
    if kind == OutboundMessage.Kind.PAYMENT_SUCCEEDED:
        return EmailDocument(
            subject=_("Waçla payment confirmed"),
            preheader=_("Your payment is confirmed."),
            eyebrow=_("Payment"),
            heading=_("Your payment is confirmed"),
            paragraphs=(_("Your payment is confirmed and the delivery can continue."),),
            facts=_facts(
                context,
                (_("Payment reference"), context.get("payment_reference", reference)),
                _amount_fact(context),
            ),
        )
    if kind == OutboundMessage.Kind.GUEST_PAYMENT:
        succeeded = context.get("status") == "succeeded"
        failed = context.get("status") == "failed"
        return EmailDocument(
            subject=(
                _("Your Waçla payment receipt")
                if succeeded
                else _("Your Waçla guest payment needs attention")
                if failed
                else _("Your Waçla guest payment")
            ),
            preheader=(
                _("Your guest payment was confirmed.")
                if succeeded
                else _("Your guest payment did not complete.")
                if failed
                else _("A guest payment update is available.")
            ),
            eyebrow=_("Payment"),
            heading=(
                _("Your guest payment is confirmed")
                if succeeded
                else _("Your guest payment did not go through")
                if failed
                else _("Your guest payment")
            ),
            paragraphs=(
                (
                    _("Waçla received this payment for the reference below.")
                    if succeeded
                    else _("The provider could not complete this guest payment.")
                    if failed
                    else _("A guest payment update is available.")
                ),
            ),
            callout=(
                _(
                    "This payment does not create a Waçla account or give access "
                    "to the delivery. Keep the reference private and contact "
                    "Waçla support if you need help."
                )
            ),
            facts=_facts(
                {},
                (_("Payment reference"), context.get("payment_reference", "")),
                _amount_fact(context),
            ),
        )
    if kind == OutboundMessage.Kind.REFUND_STATUS:
        succeeded = context.get("status") == "succeeded"
        return EmailDocument(
            subject=_("Waçla refund update"),
            preheader=(
                _("Your refund is complete.")
                if succeeded
                else _("Your refund is being processed.")
            ),
            eyebrow=_("Payment"),
            heading=(
                _("Your refund is complete")
                if succeeded
                else _("Your refund is being processed")
            ),
            paragraphs=(
                (
                    _("Waçla has completed the refund shown below.")
                    if succeeded
                    else _("Waçla has started the refund shown below.")
                ),
                _("The time it takes to appear depends on the payment provider."),
            ),
            facts=_facts(
                context,
                (_("Payment reference"), context.get("payment_reference", reference)),
                _amount_fact(context),
            ),
        )
    if kind == OutboundMessage.Kind.EVIDENCE_REQUEST:
        return EmailDocument(
            subject=_("More information is needed for your Waçla case"),
            preheader=_("Open Waçla to review the evidence request."),
            eyebrow=_("Dispute"),
            heading=_("We need a little more information"),
            paragraphs=(_("The Waçla trust team requested additional evidence."),),
            callout=_(
                "Open the app to upload evidence. Never include a handover code."
            ),
            facts=_facts(
                context,
                (_("Dispute reference"), context.get("dispute_reference", "")),
            ),
        )
    if kind == OutboundMessage.Kind.SECURITY_EVENT:
        password_reset = context.get("event") == "password_reset_completed"
        return EmailDocument(
            subject=_("Waçla security notice"),
            preheader=(
                _("Your Waçla password was changed.")
                if password_reset
                else _("A security or account change was made")
            ),
            eyebrow=_("Account security"),
            heading=(
                _("Your password was changed")
                if password_reset
                else _("A security or account change was made")
            ),
            paragraphs=(
                _("The password for your Waçla account was changed.")
                if password_reset
                else str(
                    context.get(
                        "summary",
                        _("There was a security or account change."),
                    )
                ),
            ),
            callout=(
                _(
                    "If you did not make this change, reset your password "
                    "immediately and contact Waçla support."
                )
            ),
        )
    if kind == OutboundMessage.Kind.PICKUP_CONFIRMED:
        buffer_minutes = context.get("buffer_minutes", 30)
        return EmailDocument(
            subject=_("Pickup confirmed"),
            preheader=_("The traveler has collected your parcel."),
            eyebrow=_("Delivery"),
            heading=_("The traveler has collected your parcel"),
            paragraphs=(
                _("The traveler has confirmed pickup of your parcel."),
                _(
                    "Your delivery code becomes available in %(minutes)s minutes, "
                    "and the recipient is emailed at the same time."
                )
                % {"minutes": buffer_minutes},
            ),
            facts=_facts(context),
        )
    if kind == OutboundMessage.Kind.DELIVERY_CODE_RELEASED:
        return EmailDocument(
            subject=_("Your delivery code is now available"),
            preheader=_("Open Waçla to view the delivery code."),
            eyebrow=_("Delivery"),
            heading=_("Your delivery code is now available"),
            paragraphs=(
                _(
                    "The safety window has passed. You can now view the delivery "
                    "code in the Waçla app, and the recipient has been emailed "
                    "their copy."
                ),
            ),
            callout=_("The code is not in this email. Open the app to see it."),
            facts=_facts(context),
        )
    if kind == OutboundMessage.Kind.DELIVERY_CONFIRMED:
        return EmailDocument(
            subject=_("Delivery confirmed"),
            preheader=_("The delivery code was accepted successfully."),
            eyebrow=_("Delivery"),
            heading=_("The delivery is confirmed"),
            paragraphs=(
                _(
                    "The delivery code was entered successfully and the delivery "
                    "is confirmed."
                ),
            ),
            facts=_facts(
                context,
                (
                    _("Payment protection runs until"),
                    context.get("protection_ends_at", _("the end of the window")),
                ),
            ),
        )
    if kind == OutboundMessage.Kind.PROTECTION_ENDED:
        return EmailDocument(
            subject=_("Payment protection has ended"),
            preheader=_("The protection window closed with no open dispute."),
            eyebrow=_("Payment protection"),
            heading=_("Payment protection has ended"),
            paragraphs=(
                _(
                    "The protection window for this delivery has closed with no "
                    "open dispute. The traveler's payout is now eligible."
                ),
            ),
            facts=_facts(context),
        )
    if kind == OutboundMessage.Kind.PROTECTION_ENDING:
        return EmailDocument(
            subject=_("Payment protection ends soon"),
            preheader=_("Open a dispute before the protection deadline if needed."),
            eyebrow=_("Payment protection"),
            heading=_("Payment protection ends soon"),
            paragraphs=(
                _(
                    "If something is wrong with this delivery, open a dispute "
                    "before the protection window closes."
                ),
            ),
            facts=_facts(
                context,
                (_("Protection ends at"), context.get("protection_ends_at", "")),
            ),
        )
    if kind == OutboundMessage.Kind.DISPUTE_OPENED:
        return EmailDocument(
            subject=_("A dispute has been opened"),
            preheader=_(
                "The traveler's payout is frozen while the dispute is reviewed."
            ),
            eyebrow=_("Dispute"),
            heading=_("A dispute has been opened"),
            paragraphs=(
                _(
                    "A dispute has been opened on this delivery. The traveler's "
                    "payout is frozen while it is reviewed."
                ),
            ),
            facts=_facts(
                context,
                (_("Dispute reference"), context.get("dispute_reference", "")),
            ),
        )
    if kind == OutboundMessage.Kind.DISPUTE_RESOLVED:
        resolution_labels = {
            "full_sender_refund": _("Full sender refund"),
            "full_traveler_payout": _("Full traveler payout"),
            "partial_split": _("Partial split"),
        }
        resolution_label = resolution_labels.get(
            str(context.get("resolution", "")),
            context.get("resolution_label", ""),
        )
        return EmailDocument(
            subject=_("Your dispute has been resolved"),
            preheader=_("Open Waçla to review the dispute outcome."),
            eyebrow=_("Dispute"),
            heading=_("Your dispute has been resolved"),
            # The outbox is durable, so a row queued before a deploy is
            # rendered after it. A value interpolated mid-sentence has to
            # survive its own absence, or the recipient reads "resolved this
            # dispute as: ." — the two sentences below both stand alone.
            paragraphs=(
                (
                    _(
                        "A Waçla administrator has resolved this dispute as: "
                        "%(resolution)s."
                    )
                    % {"resolution": resolution_label}
                    if resolution_label
                    else _(
                        "A Waçla administrator has resolved this dispute. Open "
                        "Waçla to see the outcome."
                    )
                ),
            ),
            facts=_facts(
                context,
                (_("Dispute reference"), context.get("dispute_reference", "")),
            ),
        )
    if kind == OutboundMessage.Kind.PAYOUT_STATUS:
        payout_labels = {
            "eligible": _("eligible"),
            "scheduled": _("scheduled"),
            "processing": _("processing"),
            "paid": _("paid"),
            "failed": _("needs attention"),
        }
        payout_status = payout_labels.get(
            str(context.get("payout_status", "")), _("updated")
        )
        return EmailDocument(
            subject=_("Payout update"),
            preheader=_("Your Waçla payout status was updated."),
            eyebrow=_("Payout"),
            heading=_("Your payout was updated"),
            paragraphs=(
                (
                    _("Your Waçla payout status is now %(status)s.")
                    % {"status": payout_status}
                    if context.get("payout_status")
                    else _(
                        "Your Waçla payout was updated. Open Waçla to see "
                        "its current status."
                    )
                ),
            ),
            facts=_facts(context),
        )
    if kind == OutboundMessage.Kind.DEAL_CANCELLED:
        cancellation_labels = {
            "sender": _("cancelled by the sender"),
            "traveler": _("cancelled by the traveler"),
            "admin": _("cancelled by an administrator"),
        }
        cancellation_reason = cancellation_labels.get(
            str(context.get("cancelled_by_role", "")),
            context.get("reason", _("cancelled")),
        )
        return EmailDocument(
            subject=_("Delivery cancelled"),
            preheader=_("This Waçla delivery has been cancelled."),
            eyebrow=_("Delivery"),
            heading=_("This delivery has been cancelled"),
            paragraphs=(
                _("This delivery has been cancelled."),
                _(
                    "Any refund due is processed automatically and appears in "
                    "your payment history."
                ),
            ),
            facts=_facts(
                context,
                (_("Reason"), cancellation_reason),
            ),
        )
    if kind == OutboundMessage.Kind.RATING_AVAILABLE:
        return EmailDocument(
            subject=_("Leave a review"),
            preheader=_("You can now review the other party."),
            eyebrow=_("After the delivery"),
            heading=_("You can now leave a review"),
            paragraphs=(
                _("You can now review the other party for this delivery."),
                _(
                    "Reviews stay hidden until both sides have submitted or the "
                    "review window closes."
                ),
            ),
            facts=_facts(context),
        )
    raise SecretUnavailable(f"No template for outbound message kind {kind!r}.")


def build_document(message: OutboundMessage) -> EmailDocument:
    document = _build_document(message)
    if message.secret_ref.startswith("outbound_secret:"):
        vault = OutboundSecret.objects.filter(pk=message.secret_ref.split(":", 1)[1]).first()
        if vault:
            deadline = vault.expires_at.astimezone(datetime_timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            document = replace(document, facts=(*document.facts, (_("Expires at (UTC)"), deadline)))
    return document


def render(message: OutboundMessage) -> tuple[str, str]:
    """Build `(subject, plain-text body)`. The only place a code becomes text."""

    language = normalize_communication_language(message.language)
    with translation.override(language):
        document = build_document(message)
        return document.subject, to_text(document, language=language)


def render_parts(message: OutboundMessage) -> tuple[str, str, str]:
    """Build `(subject, text, html)` for a multipart send.

    Both bodies come from one document, so the plain-text part and the HTML
    part cannot drift apart and say different things about the same delivery.
    """

    language = normalize_communication_language(message.language)
    with translation.override(language):
        document = build_document(message)
        support = str(getattr(settings, "EMAIL_SUPPORT_ADDR", "") or "")
        return (
            document.subject,
            to_text(document, support_email=support, language=language),
            to_html(
                document,
                support_email=support,
                site_url=str(getattr(settings, "FRONTEND_BASE_URL", "") or ""),
                language=language,
            ),
        )


# --- dispatch -----------------------------------------------------------------


def _xadd_email(
    *,
    to: str,
    subject: str,
    body: str,
    html: str,
    kind: str,
    event_id: str,
) -> str:
    """Hand a rendered message to the Go email transport.

    Not `enqueue_email_after_commit`: this runs *after* the claim has committed
    and must report its own success or failure so the obligation row can be
    retried. The audit row is written first, exactly as the pub/sub path does,
    so an undelivered message still surfaces in the daily sweep.
    """

    payload = {
        "event_id": event_id,
        "to": to,
        "subject": subject,
        "body": body,
        "html": html,
        "kind": kind,
    }
    serialized = json.dumps(payload, separators=(",", ":"))
    payload_hash = redis_bus._payload_hash(payload)
    event, created = PublishedEvent.objects.get_or_create(
        event_id=event_id,
        defaults={"channel": settings.EMAIL_STREAM, "payload_hash": payload_hash},
    )
    if not created and (
        event.channel != settings.EMAIL_STREAM or event.payload_hash != payload_hash
    ):
        raise RuntimeError("Outbound email event payload changed between retries.")
    redis_bus.get_client().xadd(
        settings.EMAIL_STREAM,
        {"event_id": event_id, "payload": serialized},
        maxlen=_EMAIL_STREAM_MAXLEN,
        approximate=True,
    )
    return event_id


def _send_email_via_provider(
    *, to: str, subject: str, body: str, html: str = "", obligation_id: int | None = None
) -> None:
    """Send a secret-bearing message at the final SMTP boundary.

    The Go stream worker is used for ordinary transactional messages. A
    delivery code must not be serialized into Redis, so this narrow adapter
    renders and sends inside the trusted Django worker process instead. The
    database OutboundMessage remains the durable retry obligation.
    """

    backend = str(getattr(settings, "EMAIL_BACKEND", ""))
    if backend.endswith(".console.EmailBackend"):
        # Console backends print the body, which would put the handover code in
        # logs. Local development must use MailHog/SMTP for this message.
        raise RuntimeError("Secret-bearing email requires a non-console SMTP backend.")
    reply_to = [settings.EMAIL_REPLY_TO] if settings.EMAIL_REPLY_TO else None
    message = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to],
        reply_to=reply_to,
    )
    if obligation_id is not None:
        domain = parseaddr(settings.DEFAULT_FROM_EMAIL)[1].rsplit("@", 1)[-1]
        identity = hashlib.sha256(f"outbound:{obligation_id}".encode()).hexdigest()
        message.extra_headers["Message-ID"] = f"<wacla-{identity}@{domain}>"
    if html:
        # The HTML part is built from the same document as the text part and in
        # the same trusted process. It is an alternative rendering, never an
        # extra place a secret could take a different route.
        message.attach_alternative(html, "text/html")
    if message.send(fail_silently=False) != 1:
        raise RuntimeError("Email provider did not accept the message.")


def _transport_confirmed(event_id: str) -> bool:
    return (
        bool(event_id)
        and PublishedEvent.objects.filter(
            event_id=event_id,
            delivered_at__isnull=False,
        ).exists()
    )


def _mark_dispatched(message: OutboundMessage, *, event_id: str = "") -> None:
    now = timezone.now()
    message.status = OutboundMessage.Status.DISPATCHED
    message.transport_event_id = event_id
    message.dispatched_at = now
    message.last_error = ""
    message.next_attempt_at = None
    message.save(
        update_fields=(
            "status",
            "transport_event_id",
            "dispatched_at",
            "last_error",
            "next_attempt_at",
            "updated_at",
        )
    )
    _on_dispatched(message)


def _consume_secret_ref(message: OutboundMessage) -> None:
    resolver, _, raw_id = (message.secret_ref or "").partition(":")
    if resolver != "outbound_secret":
        return
    try:
        secret_id = uuid.UUID(raw_id)
    except (TypeError, ValueError):
        return
    OutboundSecret.objects.filter(pk=secret_id, consumed_at__isnull=True).update(
        sealed_value="",
        consumed_at=timezone.now(),
    )


def dispatch_message(*, message_id: int) -> str:
    """Serialize each obligation; hold the shared send lock only for final SMTP."""
    from .delivery_policy import acquire_send_lock

    kind = OutboundMessage.objects.only("kind").get(pk=message_id).kind
    if kind not in _SECRET_PROVIDER_KINDS:
        # The claim and event handle must commit before Redis publication so
        # a fast Go consumer can find its authoritative obligation/receipt.
        return _dispatch_message_locked(message_id=message_id)
    error = None
    with transaction.atomic():
        if not acquire_send_lock():
            return "busy"
        try:
            result = _dispatch_message_locked(message_id=message_id)
        except EmailDeliveryError as exc:
            # Commit safe retry state before the job runner sees a fixed error.
            error = exc
    if error:
        raise error from None
    return result


def _dispatch_message_locked(*, message_id: int) -> str:
    """Render and transport one obligation. Idempotent and safe to retry."""

    with transaction.atomic():
        message = OutboundMessage.objects.select_for_update().get(pk=message_id)
        if message.status == OutboundMessage.Status.DISPATCHED:
            return "already_dispatched"
        if message.status == OutboundMessage.Status.CANCELLED:
            return "cancelled"
        if message.status == OutboundMessage.Status.FAILED:
            return "failed"
        # EMAIL_ENABLED is the operator's kill switch for every external
        # delivery path. Secret-bearing messages bypass Redis and send from
        # Django directly, so checking only the Go consumer would let them
        # leave while delivery is documented as disabled. Keep the obligation
        # untouched so an approved activation can carry it later.
        if not bool(getattr(settings, "TRANSACTIONAL_EMAIL_ENABLED", False)):
            return "disabled"
        from .delivery_policy import activation_held, rate_limited
        if _transport_confirmed(message.transport_event_id):
            _mark_dispatched(message, event_id=message.transport_event_id)
            return "dispatched"
        if activation_held(message):
            return "activation_held"
        now = timezone.now()
        if message.last_error and message.next_attempt_at and message.next_attempt_at > now:
            return "retry_wait"
        if message.kind in _SECRET_PROVIDER_KINDS and rate_limited():
            return "rate_limited"
        if (
            message.transport_event_id
            and message.next_attempt_at is not None
            and message.next_attempt_at > now
        ):
            return "awaiting_receipt"
        if int(message.attempts) >= int(
            message.max_attempts
        ):
            message.status = OutboundMessage.Status.FAILED
            message.last_error = "SMTP delivery receipt was not confirmed."
            message.next_attempt_at = None
            message.save(
                update_fields=("status", "last_error", "next_attempt_at", "updated_at")
            )
            return "receipt_unconfirmed"
        message.attempts = int(message.attempts) + 1
        fields = ["attempts", "updated_at"]
        if message.kind not in _SECRET_PROVIDER_KINDS:
            message.transport_event_id = message.transport_event_id or uuid.uuid4().hex
            message.next_attempt_at = now + _DELIVERY_RECEIPT_TIMEOUT
            message.last_error = ""
            fields += ["transport_event_id", "next_attempt_at", "last_error"]
        message.save(update_fields=fields)
        attempts = int(message.attempts)
        max_attempts = int(message.max_attempts)

    try:
        if message.kind in _SECRET_PROVIDER_KINDS and not message.secret_ref:
            raise SecretUnavailable("The required capability reference is missing.")
        if message.kind == OutboundMessage.Kind.PROTECTION_ENDING:
            from .backlog import classify
            if classify(message)["category"] in {"expired", "obsolete"}:
                raise SecretUnavailable("The protection reminder is no longer current.")
        subject, body, html = render_parts(message)
    except (SecretUnavailable, TypeError, ValueError, KeyError):
        # The message can never become valid again, so stop retrying it and
        # leave the reason on the row for an operator.
        OutboundMessage.objects.filter(pk=message_id, status=OutboundMessage.Status.PENDING).update(
            status=OutboundMessage.Status.FAILED,
            last_error="email_context_or_capability_unavailable",
            dispatched_at=None,
            updated_at=timezone.now(),
        )
        logger.error(
            "notifications.outbound_unrenderable message=%s kind=%s",
            message_id,
            message.kind,
        )
        return "unrenderable"

    if message.kind in _SECRET_PROVIDER_KINDS:
        try:
            _send_email_via_provider(
                to=message.to_email,
                subject=subject,
                body=body,
                html=html,
                obligation_id=message.pk,
            )
        except Exception as exc:  # noqa: BLE001 - provider errors are retryable
            smtp_code = 0
            if isinstance(exc, smtplib.SMTPRecipientsRefused):
                codes = [reply[0] for reply in exc.recipients.values()]
                smtp_code = codes[0] if codes and all(500 <= code < 600 for code in codes) else 0
            elif isinstance(exc, (smtplib.SMTPDataError, smtplib.SMTPSenderRefused)):
                smtp_code = exc.smtp_code
            permanent = 500 <= smtp_code < 600
            failed_permanently = permanent or attempts >= max_attempts
            safe_error = "smtp_permanent" if permanent else "smtp_transient"
            OutboundMessage.objects.filter(pk=message_id).update(
                status=(
                    OutboundMessage.Status.FAILED
                    if failed_permanently
                    else OutboundMessage.Status.PENDING
                ),
                last_error=safe_error,
                next_attempt_at=(
                    None
                    if failed_permanently
                    else timezone.now() + _retry_delay(attempts)
                ),
                updated_at=timezone.now(),
            )
            # Never log subject/body: both may identify the recipient or carry
            # the delivery code.
            logger.warning(
                "notifications.outbound_provider_failed message=%s attempts=%s",
                message_id,
                attempts,
            )
            raise EmailDeliveryError(safe_error) from None
        with transaction.atomic():
            current = OutboundMessage.objects.select_for_update().get(pk=message_id)
            if current.status != OutboundMessage.Status.DISPATCHED:
                _mark_dispatched(current)
                _consume_secret_ref(current)
        return "dispatched"

    event_id = message.transport_event_id or uuid.uuid4().hex
    try:
        event_id = _xadd_email(
            to=message.to_email,
            subject=subject,
            body=body,
            html=html,
            kind=message.kind,
            event_id=event_id,
        )
    except (redis.RedisError, OSError):
        failed_permanently = attempts >= max_attempts
        OutboundMessage.objects.filter(
            pk=message_id, status=OutboundMessage.Status.PENDING, last_error=""
        ).update(
            status=(
                OutboundMessage.Status.FAILED
                if failed_permanently
                else OutboundMessage.Status.PENDING
            ),
            last_error="email_transport_unavailable",
            transport_event_id=event_id,
            next_attempt_at=timezone.now() + _retry_delay(attempts),
            updated_at=timezone.now(),
        )
        # The body is discarded, never logged: it may contain a delivery code.
        logger.warning(
            "notifications.outbound_transport_failed message=%s attempts=%s",
            message_id,
            attempts,
        )
        raise EmailDeliveryError("email_transport_unavailable") from None

    # The committed claim already records the handle and confirmation timeout.
    # Never overwrite a fast consumer's accepted/failure outcome after XADD.
    # If no receipt arrives, the sweep republishes the same stable event id.
    return "transported"


def _retry_delay(attempts: int) -> timedelta:
    return timedelta(seconds=min(60 * (2 ** max(0, attempts - 1)), 6 * 3_600))


def _on_dispatched(message: OutboundMessage) -> None:
    """Record the dispatch on the Deal timeline where it is materially visible.

    Only the recipient's delivery-code email gets a timeline entry: it is the
    one message a party cannot otherwise observe, and a dispute may later turn
    on whether it went out.
    """

    if message.kind != OutboundMessage.Kind.RECIPIENT_DELIVERY_CODE:
        return
    if message.deal_id is None:
        return
    from apps.deals.models import DealEvent

    DealEvent.objects.create(
        deal_id=message.deal_id,
        kind=DealEvent.Kind.RECIPIENT_NOTIFICATION_SENT,
        payload={"message_id": message.pk, "channel": message.channel},
    )


def dispatch_due_messages(*, limit: int = 50, at: datetime | None = None) -> int:
    """Sweep pending obligations. The ScheduledJob path is the primary driver.

    This exists for the same reason `release_expired_reservations` does: a row
    whose job was lost still has to go out, and a sweep that reads the table is
    the only thing that can notice.
    """

    at = at or timezone.now()
    if limit <= 0 or limit > 500:
        raise ValueError("Outbound dispatch limit must be between 1 and 500.")
    with transaction.atomic():
        queryset = OutboundMessage.objects.filter(
            status=OutboundMessage.Status.PENDING, next_attempt_at__lte=at
        ).order_by("next_attempt_at", "id")
        cutoff = getattr(settings, "EMAIL_ACTIVATION_NOT_BEFORE", None)
        from django.db.models import Q
        earliest = max(cutoff, at - timedelta(hours=48)) if cutoff else at - timedelta(hours=48)
        queryset = queryset.filter(Q(created_at__gte=earliest) | Q(activation_reviewed_at__gte=at-timedelta(hours=24)))
        if connection.features.has_select_for_update_skip_locked:
            queryset = queryset.select_for_update(skip_locked=True)
        else:
            queryset = queryset.select_for_update()
        message_ids = list(queryset.values_list("pk", flat=True)[:limit])
    processed = 0
    for message_id in message_ids:
        try:
            if dispatch_message(message_id=message_id) in {"transported", "dispatched"}:
                processed += 1
        except Exception:  # noqa: BLE001 - one bad message must not stop the sweep
            logger.exception(
                "notifications.outbound_sweep_failed message=%s", message_id
            )
    return processed
