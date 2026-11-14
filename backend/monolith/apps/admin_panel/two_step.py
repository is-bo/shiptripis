"""Staff two-step sign-in (spec 19.1, plan 2.12 and L14).

Every staff account signs in with its password and then a 6-digit code from an
authenticator app. This module is the only place that knows how:

* the codes are RFC 6238 time-based one-time passwords (SHA-1, 6 digits,
  30-second steps, one step of tolerance either side), written here with the
  standard library and pinned to the RFC's published vectors by a test;
* `two_step_satisfied(request)` is the only answer to "has this staff session
  passed the second step", and `fresh_two_step(request)` the only answer to
  "recently" (a code entered in the last 10 minutes);
* enrolment, verification, recovery codes, the lockout and the reset all write
  through the functions below, under a row lock, with an audit row where spec
  19.1 asks for one.

The verification lives in the Django session, bound to the user's id, and
costs no query. It cannot outlive the session: signing out flushes it, every
password sign-in clears it (`clear_on_sign_in`), and a reset ends the target's
sessions. Nothing outside this process can mark a session verified: there is
no setting, header, parameter or route that does it. The one relaxation is the
server setting ``ADMIN_TWO_STEP_REQUIRED``, for local development, which
`config.settings.prod` refuses to start with.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from importlib import import_module
from urllib.parse import quote, urlencode

from django.conf import settings
from django.core.exceptions import (
    ImproperlyConfigured,
    PermissionDenied,
    ValidationError,
)
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.finance import sensitive_data

from .models import AdminRecoveryCode, AdminTwoStep
from .permissions import has_admin_permission

#: Where the verification is kept in the session. Its value is
#: ``{"user": <user id>, "at": <unix seconds of the last accepted code>}``.
SESSION_KEY = "admin_two_step"
#: The recovery codes of a just-finished enrolment, until their one display.
RECOVERY_DISPLAY_SESSION_KEY = "admin_two_step_recovery_codes"

PERIOD_SECONDS = 30
DIGITS = 6
TOLERANCE_STEPS = 1
MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 15
FRESH_MINUTES = 10
RECOVERY_CODE_COUNT = 10
#: 16 characters of base32: 80 bits, beyond offline guessing of the digests.
RECOVERY_CODE_LENGTH = 16
ISSUER = "Wassla Operations"

#: The machine codes the staff API answers with.
TWO_STEP_REQUIRED_CODE = "admin_two_step_required"
FRESH_TWO_STEP_REQUIRED_CODE = "admin_fresh_two_step_required"

#: Outcome reasons.
WRONG = "wrong"
LOCKED = "locked"
NOT_ENROLLED = "not_enrolled"
ALREADY_ENROLLED = "already_enrolled"

_ENVELOPE_MODEL = "admin_panel.AdminTwoStep"
_ENVELOPE_FIELD = "secret"
_BASE32 = "abcdefghijklmnopqrstuvwxyz234567"


def required() -> bool:
    """False only on a development server that relaxed the gate."""

    return bool(getattr(settings, "ADMIN_TWO_STEP_REQUIRED", True))


# --- RFC 4226 / RFC 6238 -------------------------------------------------------


def hotp(key: bytes, counter: int, *, digits: int = DIGITS) -> str:
    """RFC 4226 HOTP with HMAC-SHA-1 and dynamic truncation."""

    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10**digits).zfill(digits)


def time_step(moment: datetime) -> int:
    """The RFC 6238 counter for a moment: whole 30-second steps since 1970."""

    return int(moment.timestamp()) // PERIOD_SECONDS


def totp(key: bytes, moment: datetime, *, digits: int = DIGITS) -> str:
    return hotp(key, time_step(moment), digits=digits)


def _normalize_code(code: str) -> str | None:
    text = "".join(str(code or "").split())
    if len(text) != DIGITS or not text.isascii() or not text.isdigit():
        return None
    return text


def _accepted_step(key: bytes, code: str, *, now: datetime, after_step: int) -> int | None:
    """The step a code is valid for, inside the tolerance window, or ``None``.

    A code for ``after_step`` or an earlier step is refused even when it is
    otherwise right: that is what stops a code being used twice.
    """

    typed = _normalize_code(code)
    if typed is None:
        return None
    current = time_step(now)
    accepted = None
    # Every candidate is compared, in constant time, so the answer's timing
    # does not say which step matched.
    for step in range(current - TOLERANCE_STEPS, current + TOLERANCE_STEPS + 1):
        if hmac.compare_digest(hotp(key, step), typed) and step > after_step:
            accepted = step
    return accepted


# --- keys ------------------------------------------------------------------------


def _new_secret() -> str:
    """A fresh 160-bit key as unpadded base32, the form authenticator apps take."""

    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _key_bytes(secret_b32: str) -> bytes:
    padding = "=" * (-len(secret_b32) % 8)
    return base64.b32decode(secret_b32 + padding)


def _seal(row: AdminTwoStep, secret_b32: str) -> str:
    return sensitive_data.encrypt(
        secret_b32, model=_ENVELOPE_MODEL, record=row.pk, field=_ENVELOPE_FIELD
    )


def secret_text(row: AdminTwoStep) -> str:
    """The row's key as base32 text, for the enrolment page only."""

    return sensitive_data.decrypt(
        row.secret, model=_ENVELOPE_MODEL, record=row.pk, field=_ENVELOPE_FIELD
    )


def grouped_secret(secret_b32: str) -> str:
    """The key in groups of four, which is how a person types it."""

    return " ".join(secret_b32[i : i + 4] for i in range(0, len(secret_b32), 4))


def provisioning_uri(user, secret_b32: str) -> str:
    """The ``otpauth://`` address the enrolment QR code carries."""

    label = quote(f"{ISSUER}:{user.email}", safe=":@")
    query = urlencode(
        {
            "secret": secret_b32,
            "issuer": ISSUER,
            "algorithm": "SHA1",
            "digits": DIGITS,
            "period": PERIOD_SECONDS,
        },
        quote_via=quote,
    )
    return f"otpauth://totp/{label}?{query}"


def qr_svg(uri: str) -> str:
    """The address as an inline SVG QR code (segno: pure Python, no network)."""

    import segno

    return segno.make(uri, error="m", micro=False).svg_inline(
        scale=5, border=2, dark="#14232e", light="#ffffff"
    )


# --- recovery codes -------------------------------------------------------------------


def _recovery_digest(normalized: str) -> str:
    return hashlib.sha256(normalized.encode("ascii")).hexdigest()


def normalize_recovery_code(code: str) -> str | None:
    text = "".join(ch for ch in str(code or "").casefold() if ch not in " -\t\r\n")
    if len(text) != RECOVERY_CODE_LENGTH or any(ch not in _BASE32 for ch in text):
        return None
    return text


def _format_recovery_code(normalized: str) -> str:
    return "-".join(normalized[i : i + 4] for i in range(0, RECOVERY_CODE_LENGTH, 4))


def _issue_recovery_codes(user) -> list[str]:
    """Replace the user's recovery codes with ten new ones; return them once."""

    AdminRecoveryCode.objects.filter(user=user).delete()
    plain = [
        "".join(secrets.choice(_BASE32) for _ in range(RECOVERY_CODE_LENGTH))
        for _ in range(RECOVERY_CODE_COUNT)
    ]
    AdminRecoveryCode.objects.bulk_create(
        AdminRecoveryCode(user=user, code_hash=_recovery_digest(code)) for code in plain
    )
    return [_format_recovery_code(code) for code in plain]


def recovery_codes_left(user) -> int:
    return AdminRecoveryCode.objects.filter(user=user, used_at__isnull=True).count()


# --- outcomes and the lockout ----------------------------------------------------------


@dataclass(frozen=True)
class Outcome:
    ok: bool
    reason: str = ""
    locked_until: datetime | None = None
    recovery_codes: list[str] = field(default_factory=list)
    recovery_codes_left: int | None = None


def _locked(row: AdminTwoStep, now: datetime) -> bool:
    return row.locked_until is not None and row.locked_until > now


def _record_failure(row: AdminTwoStep, now: datetime) -> Outcome:
    """Count a wrong code; the fifth in a row locks the second step."""

    from .services import record_admin_action

    row.failed_attempts += 1
    if row.failed_attempts < MAX_FAILED_ATTEMPTS:
        row.save(update_fields=("failed_attempts",))
        return Outcome(False, WRONG)
    row.failed_attempts = 0
    row.locked_until = now + timedelta(minutes=LOCK_MINUTES)
    row.save(update_fields=("failed_attempts", "locked_until"))
    record_admin_action(
        actor=row.user,
        action="admin.two_step_locked",
        target=row.user,
        after={"locked_until": row.locked_until.isoformat()},
        metadata={"failed_attempts": MAX_FAILED_ATTEMPTS, "lock_minutes": LOCK_MINUTES},
    )
    return Outcome(False, LOCKED, locked_until=row.locked_until)


def _record_success(row: AdminTwoStep, *fields: str) -> None:
    row.failed_attempts = 0
    row.locked_until = None
    row.save(update_fields=("failed_attempts", "locked_until", *fields))


def _locked_row(user) -> AdminTwoStep | None:
    return (
        AdminTwoStep.objects.select_for_update(no_key=True)
        .filter(user_id=user.pk)
        .first()
    )


# --- enrolment ---------------------------------------------------------------------------


def is_enrolled(user) -> bool:
    return AdminTwoStep.objects.filter(
        user_id=user.pk, confirmed_at__isnull=False
    ).exists()


def pending_enrolment(user) -> AdminTwoStep:
    """The user's enrolment in progress, created with a new key on first call.

    Reloading the enrolment page shows the same key, so an app that already
    scanned it keeps working. A confirmed enrolment is never handed out here.
    """

    row = AdminTwoStep.objects.filter(user_id=user.pk).first()
    if row is None:
        row = AdminTwoStep(user=user)
        row.secret = _seal(row, _new_secret())
        try:
            with transaction.atomic():
                row.save(force_insert=True)
        except IntegrityError:
            # Two tabs opened the page at once; the other one won.
            row = AdminTwoStep.objects.get(user_id=user.pk)
    if row.confirmed_at is not None:
        raise ValidationError("Two-step sign-in is already set up.", code=ALREADY_ENROLLED)
    return row


def confirm_enrolment(user, code: str, *, now: datetime | None = None) -> Outcome:
    """Prove the app holds the key; on success issue the ten recovery codes."""

    from .services import record_admin_action

    now = now or timezone.now()
    with transaction.atomic():
        row = _locked_row(user)
        if row is None:
            return Outcome(False, NOT_ENROLLED)
        if row.confirmed_at is not None:
            return Outcome(False, ALREADY_ENROLLED)
        if _locked(row, now):
            return Outcome(False, LOCKED, locked_until=row.locked_until)
        step = _accepted_step(
            _key_bytes(secret_text(row)), code, now=now, after_step=row.last_accepted_step
        )
        if step is None:
            return _record_failure(row, now)
        row.confirmed_at = now
        row.last_accepted_step = step
        _record_success(row, "confirmed_at", "last_accepted_step")
        codes = _issue_recovery_codes(user)
        record_admin_action(
            actor=user,
            action="admin.two_step_enrolled",
            target=user,
            after={"enrolled": True, "recovery_set": len(codes)},
        )
    return Outcome(True, recovery_codes=codes, recovery_codes_left=len(codes))


# --- verification -------------------------------------------------------------------------


def verify_code(user, code: str, *, now: datetime | None = None) -> Outcome:
    """Check a code from the app, at most once, inside the lockout rules."""

    now = now or timezone.now()
    with transaction.atomic():
        row = _locked_row(user)
        if row is None or row.confirmed_at is None:
            return Outcome(False, NOT_ENROLLED)
        if _locked(row, now):
            return Outcome(False, LOCKED, locked_until=row.locked_until)
        step = _accepted_step(
            _key_bytes(secret_text(row)), code, now=now, after_step=row.last_accepted_step
        )
        if step is None:
            return _record_failure(row, now)
        row.last_accepted_step = step
        _record_success(row, "last_accepted_step")
    return Outcome(True)


def use_recovery_code(user, code: str, *, now: datetime | None = None) -> Outcome:
    """Spend one recovery code in place of an app code. Each works once."""

    from .services import record_admin_action

    now = now or timezone.now()
    normalized = normalize_recovery_code(code)
    with transaction.atomic():
        row = _locked_row(user)
        if row is None or row.confirmed_at is None:
            return Outcome(False, NOT_ENROLLED)
        if _locked(row, now):
            return Outcome(False, LOCKED, locked_until=row.locked_until)
        spent = normalized is not None and bool(
            AdminRecoveryCode.objects.filter(
                user_id=user.pk,
                code_hash=_recovery_digest(normalized),
                used_at__isnull=True,
            ).update(used_at=now)
        )
        if not spent:
            return _record_failure(row, now)
        _record_success(row)
        left = recovery_codes_left(user)
        record_admin_action(
            actor=user,
            action="admin.two_step_recovery_code_used",
            target=user,
            after={"recovery_remaining": left},
        )
    return Outcome(True, recovery_codes_left=left)


# --- the session ---------------------------------------------------------------------------


def mark_verified(request, user) -> None:
    """Record in this session that ``user`` just passed the second step.

    The session key is rotated first, so a key that was known before the
    second step is worth nothing after it.
    """

    request.session.cycle_key()
    request.session[SESSION_KEY] = {
        "user": user.pk,
        "at": int(timezone.now().timestamp()),
    }


def _verification(request) -> dict | None:
    user = getattr(request, "user", None)
    session = getattr(request, "session", None)
    if user is None or session is None or not getattr(user, "is_authenticated", False):
        return None
    data = session.get(SESSION_KEY)
    if (
        not isinstance(data, dict)
        or data.get("user") != user.pk
        or not isinstance(data.get("at"), int)
    ):
        return None
    return data


def two_step_satisfied(request) -> bool:
    """Has the signed-in user passed the second step in this session?"""

    if not required():
        return True
    return _verification(request) is not None


def fresh_two_step(request, minutes: int = FRESH_MINUTES) -> bool:
    """Did the signed-in user enter a code in the last ``minutes`` minutes?"""

    if not required():
        return True
    data = _verification(request)
    if data is None:
        return False
    age = int(timezone.now().timestamp()) - data["at"]
    return 0 <= age <= minutes * 60


def fresh_until(request, minutes: int = FRESH_MINUTES) -> datetime | None:
    """When the current fresh window closes, or ``None`` when there is none."""

    data = _verification(request)
    if data is None or not fresh_two_step(request, minutes):
        return None
    return datetime.fromtimestamp(data["at"], tz=dt_timezone.utc) + timedelta(minutes=minutes)


def clear_on_sign_in(sender, request, user, **kwargs) -> None:
    """``user_logged_in`` receiver: a password sign-in always asks again.

    Django keeps the session's data when the same user signs in again without
    signing out; this makes sure the verification is not part of what it keeps.
    """

    session = getattr(request, "session", None)
    if session is not None:
        session.pop(SESSION_KEY, None)
        session.pop(RECOVERY_DISPLAY_SESSION_KEY, None)


# --- reset -----------------------------------------------------------------------------------


def end_sessions(user_id: int) -> int:
    """Delete every live session signed in as ``user_id``; return how many.

    Sessions are only kept in the database (Django's default engine), so they
    can be found and ended. Any other engine is refused rather than leaving a
    verified session alive after a reset.
    """

    from django.contrib.auth import SESSION_KEY as AUTH_SESSION_KEY
    from django.contrib.sessions.models import Session

    if settings.SESSION_ENGINE not in (
        "django.contrib.sessions.backends.db",
        "django.contrib.sessions.backends.cached_db",
    ):
        raise ImproperlyConfigured(
            "Ending a staff member's sessions needs database-backed sessions."
        )
    store = import_module(settings.SESSION_ENGINE).SessionStore
    ended = 0
    for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator():
        if str(session.get_decoded().get(AUTH_SESSION_KEY)) == str(user_id):
            store(session_key=session.session_key).delete()
            ended += 1
    return ended


def reset(*, actor, target, reason: str, via: str = "console") -> dict:
    """Remove ``target``'s second step: they enrol again at their next sign-in.

    ``actor`` is the Super Admin doing it from the staff page, or ``None`` for
    `manage.py reset_admin_two_step` (the last Super Admin's way back in). The
    target's rows are deleted, their sessions and AI helper keys ended, and one
    audit row written.
    """

    from .services import record_admin_action

    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("A reason is required.", code="reason_required")
    if not target.is_staff:
        raise ValidationError("Only a staff account has a second step.", code="not_staff")
    if actor is not None:
        if not has_admin_permission(actor, "manage_admins"):
            raise PermissionDenied("Only a Super Admin may reset a second step.")
        if target.is_superuser and not actor.is_superuser:
            raise PermissionDenied("Only a Super Admin may reset a Super Admin.")
        if actor.pk == target.pk:
            raise ValidationError(
                "You cannot reset your own second step.", code="own_account"
            )
    with transaction.atomic():
        was_enrolled = AdminTwoStep.objects.filter(
            user_id=target.pk, confirmed_at__isnull=False
        ).exists()
        AdminTwoStep.objects.filter(user_id=target.pk).delete()
        AdminRecoveryCode.objects.filter(user_id=target.pk).delete()
        ended = end_sessions(target.pk)
        # A helper key was created behind the second step being reset, so it
        # stops with it (L15).
        from apps.admin_helper.keys import stop_all_keys
        from apps.admin_helper.models import AdminHelperKey

        keys_stopped = stop_all_keys(target, reason=AdminHelperKey.StopReason.TWO_STEP_RESET)
        record_admin_action(
            actor=actor,
            action="admin.two_step_reset",
            target=target,
            before={"enrolled": was_enrolled},
            after={"enrolled": False},
            reason=reason,
            metadata={"via": via, "sessions_ended": ended, "helper_keys_stopped": keys_stopped},
        )
    return {"was_enrolled": was_enrolled, "sessions_ended": ended, "helper_keys_stopped": keys_stopped}
