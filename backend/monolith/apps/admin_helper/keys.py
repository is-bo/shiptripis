"""Creating, resolving and stopping AI helper keys (spec 20.2, plan L15).

* `issue_key` is the only way a key comes to exist. It needs a code entered in
  the last 10 minutes (spec 19.1), stops the admin's previous key of the same
  kind in the same transaction, fixes the expiry from the policy of that
  moment, and returns the plain key once. Only its SHA-256 is stored.
* `resolve_key` is the only answer to "may this key act now". Every refusal is
  the same `None`, which the API answers as one `401 admin_helper_key_invalid`,
  so a caller cannot tell an unknown key from an expired, stopped or switched
  off one.
* `stop_key` ends one key early, with its own audit row. `stop_all_keys` (a
  two-step reset) and `stop_keys_if_switched_off` end many at once, and the
  one audit row of that event carries how many keys stopped.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.admin_panel.permissions import has_admin_access, has_admin_permission
from apps.admin_panel.services import record_admin_action
from apps.admin_panel.two_step import fresh_two_step
from apps.admin_panel.two_step import required as two_step_required
from apps.core.business_settings import NoActiveBusinessSettings

from .models import AdminHelperKey
from .policy import AdminHelperPolicy, InvalidAdminHelperPolicy, admin_helper_policy

#: The machine code of every refused key (plan L15).
KEY_INVALID_CODE = "admin_helper_key_invalid"
#: Creating a key needs a code entered in the last 10 minutes (spec 19.1).
FRESH_TWO_STEP_CODE = "admin_fresh_two_step_required"
DISABLED_CODE = "admin_helper_disabled"
REASON_REQUIRED_CODE = "reason_required"

PREFIXES = {
    AdminHelperKey.Kind.READ: "wslr_",
    AdminHelperKey.Kind.CHANGE: "wslw_",
}
#: 32 random bytes in URL-safe base64 without padding: exactly 43 characters.
RANDOM_BYTES = 32
RANDOM_LENGTH = 43
_FORMAT = re.compile(r"wsl[rw]_[A-Za-z0-9_-]{43}")

#: Who may stop another admin's key: the capability only Super Admin holds.
STOP_ANY_PERMISSION = "manage_admins"


class HelperKeyError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class IssuedKey:
    key: AdminHelperKey
    #: The plain key. It exists only here: show it once and drop it.
    plain: str


def digest(plain: str) -> str:
    return hashlib.sha256(plain.encode("ascii")).hexdigest()


def lifetime(policy: AdminHelperPolicy, kind: str) -> timedelta:
    if kind == AdminHelperKey.Kind.CHANGE:
        return timedelta(minutes=policy.change_key_minutes)
    return timedelta(hours=policy.read_key_hours)


def current_policy() -> AdminHelperPolicy | None:
    """The active policy, or ``None`` when it cannot be read (every key refused)."""

    try:
        return admin_helper_policy()
    except (NoActiveBusinessSettings, InvalidAdminHelperPolicy):
        return None


def issue_key(*, admin, kind: str, request) -> IssuedKey:
    """Create ``admin``'s new key of ``kind`` and stop their previous one.

    ``request`` is the console request that asked for it: the admin must be the
    one signed in to it, and it must carry a code entered in the last 10
    minutes. The audit rows say which key was created and which it replaced.
    """

    if kind not in PREFIXES:
        raise ValueError(f"Unknown helper key kind: {kind!r}")
    if getattr(request, "user", None) is None or request.user.pk != admin.pk:
        raise PermissionDenied("An admin creates only their own keys.")
    if not has_admin_access(admin):
        raise PermissionDenied("Only staff with console access have helper keys.")
    if not fresh_two_step(request):
        raise _stale_code()
    policy = current_policy()
    if policy is None or not policy.enabled:
        raise _switched_off()

    plain = PREFIXES[kind] + secrets.token_urlsafe(RANDOM_BYTES)
    now = timezone.now()
    with transaction.atomic():
        # One creation at a time per admin, so two clicks cannot race past
        # the one-live-key constraint. A two-step reset takes the same lock
        # first, so a creation never slips past one: if the reset won, it
        # ended this session and the check below refuses.
        get_user_model().objects.select_for_update().only("pk").get(pk=admin.pk)
        if two_step_required() and not _session_alive(request):
            raise _stale_code()
        # The switch, read again under the lock an activation also needs: a
        # key is created wholly before a switch-off (which then stops it) or
        # not at all, never in between where the switch-off cannot see it.
        policy = _locked_policy()
        if policy is None or not policy.enabled:
            raise _switched_off()
        replaced = list(
            AdminHelperKey.objects.select_for_update().filter(
                admin=admin, kind=kind, revoked_at__isnull=True
            )
        )
        for old in replaced:
            _stop(old, actor=admin, reason=AdminHelperKey.StopReason.REPLACED,
                  note="A new key of the same kind was created.", at=now)
        key = AdminHelperKey.objects.create(
            admin=admin,
            kind=kind,
            key_hash=digest(plain),
            hint=plain[-4:],
            created_at=now,
            expires_at=now + lifetime(policy, kind),
        )
        record_admin_action(
            actor=admin,
            action="ai_helper.key_created",
            target=key,
            after={"kind": kind, "hint": key.hint, "expires_at": key.expires_at.isoformat()},
            reason="Created from the AI helper card.",
            metadata={"replaced": [str(old.pk) for old in replaced]},
        )
    return IssuedKey(key=key, plain=plain)


def _stale_code() -> HelperKeyError:
    return HelperKeyError(
        FRESH_TWO_STEP_CODE,
        "Creating a key needs a two-step code entered in the last 10 minutes.",
    )


def _switched_off() -> HelperKeyError:
    return HelperKeyError(DISABLED_CODE, "The AI helper is switched off.")


def _session_alive(request) -> bool:
    """The request's session still exists: a reset or sign-out has not ended it."""

    session = getattr(request, "session", None)
    session_key = getattr(session, "session_key", None)
    return bool(session_key) and session.exists(session_key)


def _locked_policy() -> AdminHelperPolicy | None:
    """The active revision's policy, with that revision locked until commit.

    `activate_business_settings` locks the same row before it retires it, so
    the two run one after the other. When an activation committed while this
    waited, the row is no longer active and is skipped; the second read sees
    the new active revision.
    """

    from apps.core.models import BusinessSettingsVersion

    for _attempt in range(2):
        active = (
            BusinessSettingsVersion.objects.select_for_update(no_key=True)
            .filter(status=BusinessSettingsVersion.Status.ACTIVE)
            .first()
        )
        if active is not None:
            try:
                return AdminHelperPolicy.from_settings(active)
            except InvalidAdminHelperPolicy:
                return None
    return None


_UNSET = object()


def resolve_key(
    plain: str | None, *, policy=_UNSET, at: datetime | None = None
) -> AdminHelperKey | None:
    """The key, with its admin loaded fresh, only if it may act now.

    It may when the helper is switched on, the key is unstopped and unexpired,
    and its admin still has console access (active, staff, not banned). Rights
    are not checked here: each endpoint checks the permission of the console
    page it mirrors, on the admin loaded by this call.
    """

    if not isinstance(plain, str) or _FORMAT.fullmatch(plain) is None:
        return None
    if policy is _UNSET:
        policy = current_policy()
    if policy is None or not policy.enabled:
        return None
    key = (
        AdminHelperKey.objects.select_related("admin")
        .filter(key_hash=digest(plain))
        .first()
    )
    now = at or timezone.now()
    if key is None or key.revoked_at is not None or key.expires_at <= now:
        return None
    if not has_admin_access(key.admin):
        return None
    return key


def _stop(key: AdminHelperKey, *, actor, reason: str, note: str, at: datetime) -> None:
    """Stop one locked key. Stopped early, its waiting changes expire with it
    (L16); replaced by a new key, they stay for the admin's console click."""

    from .prepared import expire_for_keys

    key.revoked_at = at
    key.revoked_reason = reason
    key.save(update_fields=("revoked_at", "revoked_reason"))
    expired = 0 if reason == AdminHelperKey.StopReason.REPLACED else expire_for_keys([key.pk], at=at)
    record_admin_action(
        actor=actor,
        action="ai_helper.key_stopped",
        target=key,
        before={"state": "live"},
        after={"state": "stopped", "why": reason},
        reason=note,
        metadata={"admin": key.admin_id, "kind": key.kind, "hint": key.hint, "changes_expired": expired},
    )


def stop_key(*, actor, key_id, reason: str = "") -> AdminHelperKey:
    """Stop one key. Its own admin may; a Super Admin may stop anyone's, with a reason.

    Stopping a key that already stopped changes nothing and writes nothing.
    """

    if not has_admin_access(actor):
        raise PermissionDenied("Only staff stop helper keys.")
    with transaction.atomic():
        key = AdminHelperKey.objects.select_for_update().filter(pk=key_id).first()
        if key is None:
            raise AdminHelperKey.DoesNotExist
        own = key.admin_id == actor.pk
        if not own and not has_admin_permission(actor, STOP_ANY_PERMISSION):
            raise PermissionDenied("Only a Super Admin stops another admin's key.")
        if key.revoked_at is not None:
            return key
        note = (reason or "").strip()
        if own:
            note = note or "Stopped from the AI helper card."
        elif not note:
            raise HelperKeyError(REASON_REQUIRED_CODE, "A reason is required.")
        _stop(
            key,
            actor=actor,
            reason=(
                AdminHelperKey.StopReason.STOPPED
                if own
                else AdminHelperKey.StopReason.STOPPED_BY_SUPER_ADMIN
            ),
            note=note[:500],
            at=timezone.now(),
        )
    return key


def _stop_live(keys, *, reason: str, at: datetime) -> tuple[list[AdminHelperKey], int]:
    """Stop every live key in ``keys`` (locked first), and expire their waiting
    changes (L16). Returns the keys and how many changes expired."""

    from .prepared import expire_for_keys

    live = list(keys.select_for_update().filter(revoked_at__isnull=True))
    AdminHelperKey.objects.filter(pk__in=[key.pk for key in live]).update(
        revoked_at=at, revoked_reason=reason
    )
    return live, expire_for_keys([key.pk for key in live], at=at)


def stop_all_keys(admin, *, reason: str) -> int:
    """Stop every live key of ``admin`` and return how many stopped.

    For a two-step reset, inside its transaction: the reset's own audit row
    records the number, so no row is written here.
    """

    live, _expired = _stop_live(
        AdminHelperKey.objects.filter(admin=admin), reason=reason, at=timezone.now()
    )
    return len(live)


#: The audit action written when switching the helper off stops keys.
SWITCHED_OFF_ACTION = "ai_helper.keys_stopped"


def stop_keys_if_switched_off(settings_version) -> int:
    """Stop every live key when ``settings_version`` turns the helper off.

    Called by `activate_business_settings` inside its transaction, so every
    way a revision becomes active (the console form, the staff API) stops the
    keys at the moment the switch goes off, or not at all if the activation
    rolls back (spec 20.8). A revision the helper cannot read counts as off,
    the safe side. One audit row says how many keys stopped; none is written
    when there was no live key. `resolve_key` still reads the switch on every
    call, so a key could not act while off even without this.
    """

    try:
        enabled = AdminHelperPolicy.from_settings(settings_version).enabled
    except InvalidAdminHelperPolicy:
        enabled = False
    if enabled:
        return 0
    live, expired = _stop_live(
        AdminHelperKey.objects.all(),
        reason=AdminHelperKey.StopReason.SWITCHED_OFF,
        at=timezone.now(),
    )
    if live:
        record_admin_action(
            actor=settings_version.created_by,
            action=SWITCHED_OFF_ACTION,
            target=settings_version,
            before={"live_keys": len(live)},
            after={"live_keys": 0},
            reason=f"The AI helper was switched off (settings version {settings_version.version}).",
            metadata={
                "keys_stopped": len(live),
                "changes_expired": expired,
                "keys": [
                    {"id": str(key.pk), "admin": key.admin_id, "kind": key.kind, "hint": key.hint}
                    for key in live
                ],
            },
        )
    return len(live)


def key_state(key: AdminHelperKey, *, at: datetime | None = None) -> str:
    """``live``, ``expired`` or ``stopped``, for the console pages."""

    now = at or timezone.now()
    if key.revoked_at is not None:
        return "stopped"
    if key.expires_at <= now:
        return "expired"
    return "live"
