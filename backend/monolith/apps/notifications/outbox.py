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
between causes a resend of a byte-identical message rather than a silent loss.
That is at-least-once transport of an exactly-once obligation, and for a code
that does not change between attempts it is indistinguishable from exactly-once
at the recipient.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta

import redis
from django.conf import settings
from django.core.mail import EmailMessage
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.core import redis_bus
from apps.core.models import PublishedEvent

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
    run_at: datetime | None = None,
    max_attempts: int = 10,
) -> OutboundMessage:
    """Record the obligation and arm its durable dispatch job. Idempotent on `key`.

    Call inside the transaction that made the message true. The row and the fact
    it describes then commit together, so there is no window in which the Deal
    says a recipient was notified and no obligation exists to notify them.
    """

    run_at = run_at or timezone.now()
    try:
        with transaction.atomic():
            message = OutboundMessage.objects.create(
                kind=kind,
                key=key,
                to_email=to_email,
                context=context or {},
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
        vault = OutboundSecret.objects.create(
            id=secret_id,
            key=key,
            purpose=kind,
            sealed_value=seal(
                secret_id=secret_id,
                purpose=kind,
                plaintext=secret,
            ),
            expires_at=secret_expires_at,
        )
        return enqueue_message(
            kind=kind,
            key=key,
            to_email=to_email,
            context=context,
            recipient_user_id=recipient_user_id,
            secret_ref=f"outbound_secret:{vault.pk}",
            max_attempts=max_attempts,
        )


def cancel_message(*, key: str, reason: str = "") -> int:
    """Withdraw an obligation that is no longer true. Never cancels a sent one."""

    return OutboundMessage.objects.filter(
        key=key, status=OutboundMessage.Status.PENDING
    ).update(
        status=OutboundMessage.Status.CANCELLED,
        last_error=reason[:500],
        updated_at=timezone.now(),
    )


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
            raise SecretUnavailable("The outbound secret reference is invalid.") from exc
        vault = OutboundSecret.objects.filter(pk=secret_id).first()
        if vault is None or vault.consumed_at is not None or not vault.sealed_value:
            raise SecretUnavailable("The outbound email secret is unavailable.")
        if vault.expires_at <= timezone.now():
            raise SecretUnavailable("The outbound email secret has expired.")
        if vault.purpose != message.kind:
            raise SecretUnavailable("The outbound email secret purpose does not match.")
        from .secrets import OutboundSecretError, unseal

        try:
            return unseal(
                secret_id=vault.pk,
                purpose=vault.purpose,
                sealed_value=vault.sealed_value,
            )
        except OutboundSecretError as exc:
            raise SecretUnavailable("The outbound email secret could not be opened.") from exc

    if resolver != "handover_code" or not raw_id.isdigit():
        raise SecretUnavailable(f"Unsupported secret reference {resolver!r}.")

    from apps.handover.models import DealHandoverCode, HandoverCodeAccess
    from apps.handover.codes import SealError, unseal_code

    code = DealHandoverCode.objects.filter(pk=int(raw_id)).first()
    if code is None:
        raise SecretUnavailable("The referenced handover code no longer exists.")
    if code.status not in DealHandoverCode.LIVE_STATUSES:
        # The code was rotated, used or cancelled before this message went out.
        # Sending the old value would be worse than not sending at all.
        raise SecretUnavailable(f"The handover code is {code.status}.")
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


def _recipient_delivery_code(context: dict, secret: str) -> tuple[str, str]:
    reference = context.get("deal_reference", "")
    sender_name = context.get("sender_name", "your sender")
    body = (
        f"Hello {context.get('recipient_name', '')},\n\n"
        f"{sender_name} has sent you a parcel through ShipTrip and it is on "
        "its way.\n\n"
        f"Your delivery code is: {secret}\n\n"
        "Give this code to the traveler only once the parcel is physically in "
        "your hands. Entering it is what confirms the delivery and starts the "
        "payment protection window.\n\n"
        "Never share this code by phone, message or email with anyone before "
        "you have the parcel. ShipTrip will never ask you for it.\n\n"
        f"Delivery reference: {reference}\n"
    )
    return ("Your ShipTrip delivery code", body)


def _plain(subject: str, lines: list[str]) -> tuple[str, str]:
    return subject, "\n".join(lines) + "\n"


def render(message: OutboundMessage) -> tuple[str, str]:
    """Build `(subject, body)`. The only place a code becomes text."""

    context = dict(message.context or {})
    kind = message.kind
    if kind == OutboundMessage.Kind.EMAIL_VERIFICATION:
        code = resolve_secret(message)
        return _plain(
            "Confirm your ShipTrip email",
            [
                "Welcome to ShipTrip.",
                "",
                f"Your email verification code is: {code}",
                "",
                "It expires in 15 minutes. ShipTrip will never ask you to "
                "share this code outside the verification screen.",
            ],
        )
    if kind == OutboundMessage.Kind.PASSWORD_RESET:
        code = resolve_secret(message)
        return _plain(
            "Reset your ShipTrip password",
            [
                f"Your password reset code is: {code}",
                "",
                "It expires in 15 minutes. If you did not request this, "
                "ignore this email and keep your code private.",
            ],
        )
    if kind == OutboundMessage.Kind.ADMIN_INVITATION:
        base = str(context.get("frontend_base_url", "")).rstrip("/")
        invite_url = (
            f"{base}/admin/invitations/accept?token={resolve_secret(message)}"
            if base
            else "the secure invitation link"
        )
        return _plain(
            "You have been invited to ShipTrip Operations",
            [
                "A ShipTrip administrator invited you to join the operations team.",
                "",
                f"Role: {context.get('role_label', 'operations')}",
                f"Accept your invitation: {invite_url}",
                "",
                "This link expires in 24 hours and can be used once.",
                "If you were not expecting this, contact ShipTrip support.",
            ],
        )
    if kind == OutboundMessage.Kind.RECIPIENT_DELIVERY_CODE:
        return _recipient_delivery_code(context, resolve_secret(message))

    reference = context.get("deal_reference", "")
    tail = [f"Delivery reference: {reference}"]
    # The inventory below is intentionally rendered from a small allow-list of
    # context fields.  Domain events may carry provider references or other
    # operational metadata, but transactional mail should contain only the
    # minimum user-facing status and never echo arbitrary payload keys.
    if kind == OutboundMessage.Kind.KYC_STATUS:
        return _plain(
            "ShipTrip identity verification update",
            [
                "Your identity verification status is now "
                f"{context.get('status', 'updated') }.",
                str(context.get("reason", "")) if context.get("reason") else "",
                "Open the ShipTrip app to see the next step.",
            ],
        )
    if kind == OutboundMessage.Kind.FLIGHT_PROOF_STATUS:
        return _plain(
            "ShipTrip flight proof update",
            [
                "Your flight proof status is now "
                f"{context.get('status', 'updated') }.",
                str(context.get("reason", "")) if context.get("reason") else "",
                "Open the ShipTrip app to see the next step.",
            ],
        )
    if kind == OutboundMessage.Kind.PAYMENT_REQUIRED:
        return _plain(
            "Payment needed for your ShipTrip delivery",
            [
                "A payment is required before this delivery can continue.",
                f"Payment reference: {context.get('payment_reference', reference)}",
                "Open ShipTrip to review the amount and available provider.",
            ],
        )
    if kind == OutboundMessage.Kind.PAYMENT_PROCESSING:
        return _plain(
            "Your ShipTrip payment is processing",
            [
                "Your payment has been received by the provider and is being confirmed.",
                f"Payment reference: {context.get('payment_reference', reference)}",
            ],
        )
    if kind == OutboundMessage.Kind.PAYMENT_FAILED:
        return _plain(
            "Your ShipTrip payment needs attention",
            [
                "The payment provider could not complete this attempt.",
                f"Payment reference: {context.get('payment_reference', reference)}",
                "Open ShipTrip to retry or choose another available provider.",
            ],
        )
    if kind == OutboundMessage.Kind.PAYMENT_SUCCEEDED:
        return _plain(
            "ShipTrip payment confirmed",
            [
                "Your payment is confirmed and the delivery can continue.",
                f"Payment reference: {context.get('payment_reference', reference)}",
            ],
        )
    if kind == OutboundMessage.Kind.GUEST_PAYMENT:
        return _plain(
            "Your ShipTrip guest payment",
            [
                "Your guest payment link or status is ready.",
                f"Payment reference: {context.get('payment_reference', reference)}",
                "Keep this reference private and use ShipTrip support if you need help.",
            ],
        )
    if kind == OutboundMessage.Kind.REFUND_STATUS:
        return _plain(
            "ShipTrip refund update",
            [
                "Your refund status is now "
                f"{context.get('status', 'updated')}.",
                f"Payment reference: {context.get('payment_reference', reference)}",
                "Refund timing depends on the payment provider.",
            ],
        )
    if kind == OutboundMessage.Kind.EVIDENCE_REQUEST:
        return _plain(
            "More information is needed for your ShipTrip case",
            [
                "The ShipTrip trust team requested additional evidence.",
                f"Dispute reference: {context.get('dispute_reference', '')}",
                "Open the app to upload evidence. Never include a handover code.",
            ],
        )
    if kind == OutboundMessage.Kind.SECURITY_EVENT:
        return _plain(
            "ShipTrip security notice",
            [
                str(context.get("summary", "There was a security or account change.")),
                "If you did not make this change, reset your password and contact support.",
            ],
        )
    if kind == OutboundMessage.Kind.PICKUP_CONFIRMED:
        return _plain(
            "Pickup confirmed",
            [
                "The traveler has confirmed pickup of your parcel.",
                "",
                "Your delivery code becomes available in "
                f"{context.get('buffer_minutes', 30)} minutes, and the "
                "recipient is emailed at the same time.",
                "",
                *tail,
            ],
        )
    if kind == OutboundMessage.Kind.DELIVERY_CODE_RELEASED:
        return _plain(
            "Your delivery code is now available",
            [
                "The safety window has passed. You can now view the delivery "
                "code in the ShipTrip app, and the recipient has been emailed "
                "their copy.",
                "",
                *tail,
            ],
        )
    if kind == OutboundMessage.Kind.DELIVERY_CONFIRMED:
        return _plain(
            "Delivery confirmed",
            [
                "The delivery code was entered successfully and the delivery "
                "is confirmed.",
                "",
                "Payment protection runs until "
                f"{context.get('protection_ends_at', 'the end of the window')}.",
                "",
                *tail,
            ],
        )
    if kind == OutboundMessage.Kind.PROTECTION_ENDED:
        return _plain(
            "Payment protection has ended",
            [
                "The protection window for this delivery has closed with no "
                "open dispute. The traveler's payout is now eligible.",
                "",
                *tail,
            ],
        )
    if kind == OutboundMessage.Kind.PROTECTION_ENDING:
        return _plain(
            "Payment protection ends soon",
            [
                "If something is wrong with this delivery, open a dispute "
                "before the protection window closes.",
                "",
                *tail,
            ],
        )
    if kind == OutboundMessage.Kind.DISPUTE_OPENED:
        return _plain(
            "A dispute has been opened",
            [
                "A dispute has been opened on this delivery. The traveler's "
                "payout is frozen while it is reviewed.",
                "",
                f"Dispute reference: {context.get('dispute_reference', '')}",
                *tail,
            ],
        )
    if kind == OutboundMessage.Kind.DISPUTE_RESOLVED:
        return _plain(
            "Your dispute has been resolved",
            [
                "A ShipTrip administrator has resolved this dispute as: "
                f"{context.get('resolution_label', '')}.",
                "",
                f"Dispute reference: {context.get('dispute_reference', '')}",
                *tail,
            ],
        )
    if kind == OutboundMessage.Kind.PAYOUT_STATUS:
        return _plain(
            "Payout update",
            [
                "Your ShipTrip payout status is now "
                f"{context.get('payout_status', '')}.",
                "",
                *tail,
            ],
        )
    if kind == OutboundMessage.Kind.DEAL_CANCELLED:
        return _plain(
            "Delivery cancelled",
            [
                "This delivery has been cancelled.",
                "",
                f"Reason: {context.get('reason', 'cancelled')}",
                "",
                "Any refund due is processed automatically and appears in "
                "your payment history.",
                "",
                *tail,
            ],
        )
    if kind == OutboundMessage.Kind.RATING_AVAILABLE:
        return _plain(
            "Leave a review",
            [
                "You can now review the other party for this delivery.",
                "",
                "Reviews stay hidden until both sides have submitted or the "
                "review window closes.",
                "",
                *tail,
            ],
        )
    raise SecretUnavailable(f"No template for outbound message kind {kind!r}.")


# --- dispatch -----------------------------------------------------------------


def _xadd_email(
    *,
    to: str,
    subject: str,
    body: str,
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
        "kind": kind,
    }
    serialized = json.dumps(payload, separators=(",", ":"))
    payload_hash = redis_bus._payload_hash(payload)
    event, created = PublishedEvent.objects.get_or_create(
        event_id=event_id,
        defaults={"channel": _EMAIL_STREAM, "payload_hash": payload_hash},
    )
    if not created and (
        event.channel != _EMAIL_STREAM or event.payload_hash != payload_hash
    ):
        raise RuntimeError("Outbound email event payload changed between retries.")
    redis_bus.get_client().xadd(
        _EMAIL_STREAM,
        {"event_id": event_id, "payload": serialized},
        maxlen=_EMAIL_STREAM_MAXLEN,
        approximate=True,
    )
    return event_id


def _send_email_via_provider(*, to: str, subject: str, body: str) -> None:
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
    reply_to = [settings.EMAIL_SUPPORT_ADDR] if settings.EMAIL_SUPPORT_ADDR else None
    message = EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to],
        reply_to=reply_to,
    )
    if message.send(fail_silently=False) != 1:
        raise RuntimeError("Email provider did not accept the message.")


def _transport_confirmed(event_id: str) -> bool:
    return bool(event_id) and PublishedEvent.objects.filter(
        event_id=event_id,
        delivered_at__isnull=False,
    ).exists()


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
    """Render and transport one obligation. Idempotent and safe to retry."""

    with transaction.atomic():
        message = OutboundMessage.objects.select_for_update().get(pk=message_id)
        if message.status == OutboundMessage.Status.DISPATCHED:
            return "already_dispatched"
        if message.status == OutboundMessage.Status.CANCELLED:
            return "cancelled"
        if _transport_confirmed(message.transport_event_id):
            _mark_dispatched(message, event_id=message.transport_event_id)
            return "dispatched"
        now = timezone.now()
        if (
            message.transport_event_id
            and message.next_attempt_at is not None
            and message.next_attempt_at > now
        ):
            return "awaiting_receipt"
        if message.transport_event_id and int(message.attempts) >= int(message.max_attempts):
            message.status = OutboundMessage.Status.FAILED
            message.last_error = "SMTP delivery receipt was not confirmed."
            message.next_attempt_at = None
            message.save(
                update_fields=("status", "last_error", "next_attempt_at", "updated_at")
            )
            return "receipt_unconfirmed"
        message.attempts = int(message.attempts) + 1
        message.save(update_fields=["attempts", "updated_at"])
        attempts = int(message.attempts)
        max_attempts = int(message.max_attempts)

    try:
        subject, body = render(message)
    except SecretUnavailable as exc:
        # The message can never become valid again, so stop retrying it and
        # leave the reason on the row for an operator.
        OutboundMessage.objects.filter(pk=message_id).update(
            status=OutboundMessage.Status.FAILED,
            last_error=str(exc)[:500],
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
            )
        except Exception as exc:  # noqa: BLE001 - provider errors are retryable
            failed_permanently = attempts >= max_attempts
            OutboundMessage.objects.filter(pk=message_id).update(
                status=(
                    OutboundMessage.Status.FAILED
                    if failed_permanently
                    else OutboundMessage.Status.PENDING
                ),
                last_error=f"{type(exc).__name__}: {exc}"[:500],
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
            raise
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
            kind=message.kind,
            event_id=event_id,
        )
    except (redis.RedisError, OSError) as exc:
        failed_permanently = attempts >= max_attempts
        OutboundMessage.objects.filter(pk=message_id).update(
            status=(
                OutboundMessage.Status.FAILED
                if failed_permanently
                else OutboundMessage.Status.PENDING
            ),
            last_error=f"{type(exc).__name__}: {exc}"[:500],
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
        raise

    # XADD is transport, not delivery. Keep the PostgreSQL obligation pending
    # until the Go worker records SMTP success on core_published_event. If the
    # receipt never arrives, the table sweep re-enqueues this same event id and
    # byte-identical body after the confirmation timeout.
    now = timezone.now()
    OutboundMessage.objects.filter(pk=message_id).update(
        status=OutboundMessage.Status.PENDING,
        transport_event_id=event_id,
        dispatched_at=None,
        last_error="",
        next_attempt_at=now + _DELIVERY_RECEIPT_TIMEOUT,
        updated_at=now,
    )
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
