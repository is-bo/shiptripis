"""Changes the helper does or prepares, and the admin's decision on them (spec 20.4, plan L16).

* `take` is ``POST actions`` once the view has read the body: the fresh
  permission, the target, the parameters and the console's own validation,
  then either the direct action, run at once, or a `PreparedAction` stored for
  the admin. Preparing changes nothing else: no domain row, no money row.
* `confirm` is the console's "Confirm" on one waiting change. It locks the
  row, checks the admin, the two-step session, the expiry and the switch, the
  permission again, the console's validation again and the stored basis, then
  runs the registry's ``run``, the console's own function, as that admin. Any
  difference is "This no longer applies" and the change is marked failed.
* `reject` closes one without running it. `expire_due` (the
  ``admin_helper_action_expiry`` job) and `expire_for_keys` (a key stopped
  early) close the ones that may no longer be confirmed.

Lock order. Preparing locks the key row, then the waiting change. Stopping a
key locks the key rows, then updates their waiting changes. Confirming and
rejecting lock only the change row (``FOR UPDATE OF`` that table alone), then,
for a refund, the payment its basis reads, then whatever the console's
function locks; they never lock a key, so they cannot deadlock with a stop or
a prepare. A stop that waits on a confirmation sees the change confirmed and
leaves it.

Audit. Direct and confirmed actions write the console action's own rows, with
``{"via": "ai_helper", "key", "prepared_action"}`` merged in by
`apps.admin_panel.services.audit_via` around ``run`` and nowhere else.
Preparing, rejecting and a confirmation that no longer applies write their
own rows. An expiry writes none: nothing was decided.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.admin_panel.services import audit_via, record_admin_action
from apps.admin_panel.two_step import two_step_satisfied

from . import actions
from .actions import Refused
from .keys import current_policy
from .models import AdminHelperKey, PreparedAction

EXPIRY_JOB_PREFIX = "admin_helper_action_expiry"

# Answers of ``POST actions`` beyond the registry's own refusal codes.
UNKNOWN = "admin_helper_action_unknown"
TARGET_NOT_FOUND = "admin_helper_not_found"
FORBIDDEN = "admin_helper_forbidden"
ALREADY_WAITING = "admin_helper_action_already_waiting"
KEY_GONE = "admin_helper_key_invalid"
CHANGED = "admin_helper_action_changed"

#: What the assistant and the admin read when a change cannot run any more.
NO_LONGER_APPLIES = "This no longer applies"
SWITCHED_OFF = "The AI helper is switched off, so nothing it prepared can be confirmed or rejected."


def _json(value) -> object:
    """``value`` as the JSON column stores it, so a fresh value compares equal."""

    return json.loads(json.dumps(value, cls=DjangoJSONEncoder, sort_keys=True))


def marker(key_id, prepared_action_id=None, **extra) -> dict:
    """The audit metadata of a helper-run action (plan L16)."""

    return {
        "via": "ai_helper",
        "key": str(key_id),
        "prepared_action": str(prepared_action_id) if prepared_action_id else None,
        **extra,
    }


def confirm_url(request, prepared: PreparedAction) -> str:
    return request.build_absolute_uri(
        reverse("admin_console:ai-helper-change", args=(prepared.pk,))
    )


# --- POST actions ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Taken:
    """What ``POST actions`` answers: a direct result, or the waiting change."""

    entry: actions.Action
    done: str = ""
    prepared: PreparedAction | None = None
    #: The waiting change existed already, with the same parameters.
    repeat: bool = False


class AlreadyWaiting(Refused):
    def __init__(self, prepared: PreparedAction):
        super().__init__(
            ALREADY_WAITING,
            "A change of this kind on this record is already waiting for the admin, with "
            "other values. It must be confirmed or rejected on the console first.",
        )
        self.prepared = prepared


def _reason(entry: actions.Action, raw) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise Refused(actions.INVALID, "reason is required: why this change, in one or two sentences.",
                      fields={"reason": "required"})
    reason = raw.strip()
    if len(reason) > entry.reason_max_length:
        raise Refused(
            actions.INVALID,
            f"reason holds at most {entry.reason_max_length} characters for {entry.code}.",
            fields={"reason": "max_length"},
        )
    return reason


def _target(raw) -> tuple[str, int]:
    if not isinstance(raw, dict) or set(raw) != {"type", "id"}:
        raise Refused(actions.INVALID, 'target must be {"type": ..., "id": ...}.', fields={"target": "shape"})
    target_type, target_id = raw["type"], raw["id"]
    if not isinstance(target_type, str) or isinstance(target_id, bool) or not isinstance(target_id, int):
        raise Refused(actions.INVALID, "target.type is text and target.id a whole number.",
                      fields={"target": "shape"})
    if target_id < 1:
        raise Refused(actions.INVALID, "target.id must be at least 1.", fields={"target": "id"})
    return target_type, target_id


def read_body(data) -> tuple[actions.Action, str, int, object, str]:
    """``(entry, target type, target id, raw params, reason)`` from the body, or `Refused`.

    The body is ``{"action", "target": {"type", "id"}, "params", "reason"}``
    and nothing else.
    """

    if not isinstance(data, dict):
        raise Refused(actions.INVALID, "The body must be a JSON object.")
    unknown = sorted(set(data) - {"action", "target", "params", "reason"})
    if unknown:
        raise Refused(actions.INVALID, f"Unknown fields: {', '.join(unknown)}.",
                      fields={name: "unknown" for name in unknown})
    code = data.get("action")
    entry = actions.get(code) if isinstance(code, str) else None
    if entry is None:
        raise Refused(UNKNOWN, "There is no such action. guide lists the ones this key may take.")
    target_type, target_id = _target(data.get("target"))
    if target_type not in entry.target_types:
        raise Refused(
            actions.INVALID,
            f"{entry.code} takes a target of type {', '.join(entry.target_types)}.",
            fields={"target": "type"},
        )
    return entry, target_type, target_id, data.get("params"), _reason(entry, data.get("reason"))


def take(*, request, key: AdminHelperKey, data) -> Taken:
    """``POST actions``: run a direct action or store a prepared one. Raises `Refused`."""

    admin = request.user
    entry, target_type, target_id, raw_params, reason = read_body(data)
    # Fresh, before anything is read: a refused admin learns nothing about the record.
    if not entry.permitted(admin, target_type):
        raise Refused(FORBIDDEN, "Your role does not allow this. The console would refuse it too.")
    params = entry.parse(raw_params)
    obj = entry.load(target_type, target_id)
    if obj is None:
        raise Refused(TARGET_NOT_FOUND, f"No such {target_type}.")
    if entry.allowed is not None and not entry.allowed(admin, obj):
        raise Refused(FORBIDDEN, "Your role does not decide this record. The console would refuse it too.")
    cleaned = entry.check(admin, obj, params, reason)
    if entry.mode == actions.DIRECT:
        return Taken(entry=entry, done=_run_direct(entry, admin, obj, cleaned, reason, key))
    prepared, repeat = prepare(
        key=key,
        admin=admin,
        entry=entry,
        target_type=target_type,
        obj=obj,
        params=params,
        cleaned=cleaned,
        helper_reason=reason,
        valid_hours=_valid_hours(request),
    )
    return Taken(entry=entry, prepared=prepared, repeat=repeat)


def _valid_hours(request) -> int:
    policy = getattr(request, "helper_policy", None) or current_policy()
    if policy is None or not policy.enabled:
        raise Refused(KEY_GONE, "The AI helper is switched off.")
    return policy.prepared_action_valid_hours


def _run_direct(entry, admin, obj, cleaned, reason, key) -> str:
    try:
        with transaction.atomic(), audit_via(marker(key.pk)):
            return entry.run(admin, obj, cleaned, reason, None)
    except actions.domain_errors() as exc:
        raise actions.refusal_of(exc) from None


def prepare(
    *,
    key: AdminHelperKey,
    admin,
    entry: actions.Action,
    target_type: str,
    obj,
    params: dict,
    cleaned: dict,
    helper_reason: str,
    valid_hours: int,
) -> tuple[PreparedAction, bool]:
    """Store one change for ``admin`` to confirm; ``(change, repeat)``.

    The same change prepared again while it waits answers the waiting one
    (``repeat``); other values for the same action and record raise
    `AlreadyWaiting`. Nothing but this row, its expiry job and its audit row
    is written.
    """

    stored_params = _json(params)
    basis = _json(entry.basis(obj, cleaned))
    summary = entry.summary(obj, cleaned)[:500]
    with transaction.atomic():
        # The key row first: a stop that won made it unusable; a stop that
        # comes after waits, then expires what this created.
        live = AdminHelperKey.objects.select_for_update().filter(pk=key.pk).first()
        now = timezone.now()
        if live is None or live.revoked_at is not None or live.expires_at <= now:
            raise Refused(KEY_GONE, "This key no longer works.")
        waiting = (
            PreparedAction.objects.select_for_update()
            .filter(
                admin=admin,
                action=entry.code,
                target_type=target_type,
                target_id=obj.pk,
                status=PreparedAction.Status.WAITING,
            )
            .first()
        )
        if waiting is not None and waiting.expires_at <= now:
            _close(waiting, PreparedAction.Status.EXPIRED, _expired_outcome(), at=now)
            waiting = None
        if waiting is not None:
            if waiting.params == stored_params:
                return waiting, True
            raise AlreadyWaiting(waiting)
        try:
            with transaction.atomic():
                prepared = PreparedAction.objects.create(
                    admin=admin,
                    key=live,
                    action=entry.code,
                    target_type=target_type,
                    target_id=obj.pk,
                    params=stored_params,
                    helper_reason=helper_reason,
                    summary=summary,
                    basis=basis,
                    created_at=now,
                    expires_at=now + timedelta(hours=valid_hours),
                )
        except IntegrityError:
            # Another call of the same admin won the one waiting slot.
            raise Refused(ALREADY_WAITING, "This change is already waiting for the admin.") from None
        _schedule_expiry(prepared)
        record_admin_action(
            actor=admin,
            action="ai_helper.action_prepared",
            target=prepared,
            after={
                "action": entry.code,
                "target_type": target_type,
                "target_id": obj.pk,
                "summary": summary,
                "expires_at": prepared.expires_at.isoformat(),
            },
            reason=helper_reason,
            metadata=marker(live.pk, prepared.pk),
        )
    return prepared, False


def _schedule_expiry(prepared: PreparedAction) -> None:
    from apps.finance.models import ScheduledJob
    from apps.finance.services import schedule_job

    schedule_job(
        kind=ScheduledJob.Kind.ADMIN_HELPER_ACTION_EXPIRY,
        key=f"{EXPIRY_JOB_PREFIX}:{prepared.pk}",
        run_at=prepared.expires_at,
        payload={"prepared_action": str(prepared.pk)},
    )


# --- closing a change ----------------------------------------------------------------------


def _expired_outcome() -> dict:
    return {"code": "expired", "message": "Nobody confirmed it in time."}


def _close(prepared: PreparedAction, status: str, outcome: dict, *, at: datetime) -> None:
    prepared.status = status
    prepared.decided_at = at
    prepared.outcome = outcome
    prepared.save(update_fields=("status", "decided_at", "outcome"))


#: What the admin reads on a change that expired because its key stopped early.
_STOPPED_BECAUSE = {
    AdminHelperKey.StopReason.STOPPED_BY_SUPER_ADMIN: "A Super Admin stopped the key that prepared it.",
    AdminHelperKey.StopReason.TWO_STEP_RESET: (
        "Your two-step sign-in was reset, which stopped the key that prepared it."
    ),
    AdminHelperKey.StopReason.SWITCHED_OFF: "The AI helper was switched off.",
}
_STOPPED = "The key that prepared it was stopped."


def expire_for_keys(key_ids, *, reason: str, at: datetime | None = None) -> int:
    """Close the waiting changes of these keys (ids or a subquery); return how many.

    Called inside a stop's transaction, after its key rows are locked, with
    the stop's reason, which the admin reads on each change.
    """

    return PreparedAction.objects.filter(
        key_id__in=key_ids, status=PreparedAction.Status.WAITING
    ).update(
        status=PreparedAction.Status.EXPIRED,
        decided_at=at or timezone.now(),
        outcome={"code": "key_stopped", "message": _STOPPED_BECAUSE.get(reason, _STOPPED)},
    )


class NotDue(Exception):
    """The expiry job ran before the change's time; try again after ``delay``."""

    def __init__(self, delay: timedelta):
        super().__init__("The prepared change has not expired yet.")
        self.delay = delay


def handle_expiry_job(payload: dict) -> str:
    """The ``admin_helper_action_expiry`` job: close one change past its time.

    Run early (a manual retry, clock skew), it raises `NotDue` so the job
    runner keeps the job and tries again, instead of counting it done.
    """

    with transaction.atomic():
        prepared = (
            PreparedAction.objects.select_for_update()
            .filter(pk=payload.get("prepared_action"))
            .first()
        )
        now = timezone.now()
        if prepared is None or prepared.status != PreparedAction.Status.WAITING:
            return "already_closed"
        if prepared.expires_at > now:
            raise NotDue(prepared.expires_at - now)
        _close(prepared, PreparedAction.Status.EXPIRED, _expired_outcome(), at=now)
    return "expired"


def waiting_for(admin, *, at: datetime | None = None):
    """``admin``'s changes that wait and may still be confirmed, oldest first."""

    return PreparedAction.objects.filter(
        admin=admin,
        status=PreparedAction.Status.WAITING,
        expires_at__gt=at or timezone.now(),
    ).order_by("created_at", "pk")


# --- the admin's decision on the console ------------------------------------------------------


class NotDecidable(Exception):
    """The change cannot be decided now; nothing was changed."""


@dataclass(frozen=True, slots=True)
class Decision:
    status: str
    message: str


def _own_locked(request, action_id) -> PreparedAction | None:
    # The change row only: never the key (see "Lock order" above).
    return (
        PreparedAction.objects.select_for_update(of=("self",))
        .filter(pk=action_id, admin=request.user)
        .first()
    )


def _decidable(prepared: PreparedAction, now: datetime) -> Decision | None:
    """``None`` when ``prepared`` still waits; else closes an expired one and says so."""

    if prepared.status != PreparedAction.Status.WAITING:
        raise NotDecidable(f"This change is already decided: {prepared.get_status_display().lower()}.")
    if prepared.expires_at <= now:
        _close(prepared, PreparedAction.Status.EXPIRED, _expired_outcome(), at=now)
        return Decision(PreparedAction.Status.EXPIRED, "This change expired before it was confirmed.")
    return None


def _fail(prepared: PreparedAction, code: str, why: str, *, reason: str, at: datetime) -> Decision:
    message = f"{NO_LONGER_APPLIES}: {why}"
    _close(prepared, PreparedAction.Status.FAILED, {"code": code, "message": message, "reason": reason}, at=at)
    record_admin_action(
        actor=prepared.admin,
        action="ai_helper.action_failed",
        target=prepared,
        before={"status": PreparedAction.Status.WAITING},
        after={"status": PreparedAction.Status.FAILED, "why": why},
        reason=reason,
        metadata=marker(prepared.key_id, prepared.pk),
    )
    return Decision(PreparedAction.Status.FAILED, message)


class _Stale(Exception):
    def __init__(self, code: str, why: str):
        super().__init__(why)
        self.code = code
        self.why = why


def _assess(admin, prepared: PreparedAction, reason: str, *, confirming: bool = False):
    """``(entry, record, cleaned)`` when the change may run now as ``admin``.

    The permission (fresh), the record, the per-record rule, the console's
    own validation with ``reason``, then the stored basis: the first that
    fails raises `_Stale` with why, in words. When ``confirming``, an entry
    with a ``lock`` first locks what its basis reads, so nothing changes
    between the comparison and the run.
    """

    entry = actions.get(prepared.action)
    if entry is None or not entry.permitted(admin, prepared.target_type):
        raise _Stale(FORBIDDEN, "your role no longer allows this change.")
    obj = entry.load(prepared.target_type, prepared.target_id)
    if obj is not None and confirming and entry.lock is not None:
        entry.lock(obj)
        obj = entry.load(prepared.target_type, prepared.target_id)
    if obj is None:
        raise _Stale(TARGET_NOT_FOUND, "the record no longer exists.")
    if entry.allowed is not None and not entry.allowed(admin, obj):
        raise _Stale(FORBIDDEN, "your role does not decide this record.")
    try:
        cleaned = entry.check(admin, obj, dict(prepared.params), reason)
    except Refused as refused:
        raise _Stale(refused.code, _sentence(refused.message)) from None
    if _json(entry.basis(obj, cleaned)) != prepared.basis:
        raise _Stale(
            CHANGED,
            "the record changed after the AI helper prepared this change. Look at it again.",
        )
    return entry, obj, cleaned


@dataclass(frozen=True, slots=True)
class Look:
    """What the console shows of one change: its values in words, the record,
    and, while it waits, whether it would still run."""

    entry: actions.Action | None
    record: object | None
    details: list
    #: Empty, or "This no longer applies: ..." for a waiting change.
    problem: str
    #: ``details`` were computed again just now (the change still applies).
    fresh: bool


def look(admin, prepared: PreparedAction) -> Look:
    entry = actions.get(prepared.action)
    record = entry.load(prepared.target_type, prepared.target_id) if entry else None
    stored = (
        entry.details(record, entry.restore(dict(prepared.params), prepared.basis))
        if entry is not None and record is not None
        else []
    )
    if prepared.status != PreparedAction.Status.WAITING or prepared.expires_at <= timezone.now():
        return Look(entry, record, stored, "", False)
    try:
        entry, record, cleaned = _assess(admin, prepared, prepared.helper_reason)
    except _Stale as stale:
        return Look(entry, record, stored, f"{NO_LONGER_APPLIES}: {stale.why}", False)
    return Look(entry, record, entry.details(record, cleaned), "", True)


def confirm(*, request, action_id, reason: str) -> Decision | None:
    """Run one waiting change as the signed-in admin. ``None``: not theirs, or none.

    ``reason`` is the admin's own, already checked by the confirm form.
    Raises `NotDecidable` when nothing may happen now (decided already, no
    two-step session, switch off).
    """

    with transaction.atomic():
        prepared = _own_locked(request, action_id)
        if prepared is None:
            return None
        if not two_step_satisfied(request):
            raise NotDecidable("Confirming needs a console session that passed the second step.")
        now = timezone.now()
        closed = _decidable(prepared, now)
        if closed is not None:
            return closed
        policy = current_policy()
        if policy is None or not policy.enabled:
            raise NotDecidable(SWITCHED_OFF)
        try:
            entry, obj, cleaned = _assess(request.user, prepared, reason, confirming=True)
        except _Stale as stale:
            return _fail(prepared, stale.code, stale.why, reason=reason, at=now)
        extra = {"confirmed_reason": reason} if entry.reason_in_metadata else {}
        try:
            with transaction.atomic(), audit_via(marker(prepared.key_id, prepared.pk, **extra)):
                done = entry.run(request.user, obj, cleaned, reason, prepared.basis)
        except actions.domain_errors() as exc:
            refused = actions.refusal_of(exc)
            return _fail(prepared, refused.code, _sentence(refused.message), reason=reason, at=now)
        _close(
            prepared,
            PreparedAction.Status.CONFIRMED,
            {"code": "done", "message": done, "reason": reason},
            at=now,
        )
    return Decision(PreparedAction.Status.CONFIRMED, done)


def _sentence(message: str) -> str:
    """A refusal's message, to follow "This no longer applies: "."""

    text = (message or "").strip() or "It cannot be done now."
    if len(text) > 1 and text[1].isupper():  # It starts with an acronym, such as "EUR".
        return text
    return text[0].lower() + text[1:]


def reject(*, request, action_id) -> Decision | None:
    """Close one waiting change without running it. No reason is asked.

    With the helper switched off the list is read only: nothing is decided,
    rejections included (spec 20.8).
    """

    with transaction.atomic():
        prepared = _own_locked(request, action_id)
        if prepared is None:
            return None
        now = timezone.now()
        closed = _decidable(prepared, now)
        if closed is not None:
            return closed
        policy = current_policy()
        if policy is None or not policy.enabled:
            raise NotDecidable(SWITCHED_OFF)
        _close(prepared, PreparedAction.Status.REJECTED,
               {"code": "rejected", "message": "You rejected it on the console."}, at=now)
        record_admin_action(
            actor=request.user,
            action="ai_helper.action_rejected",
            target=prepared,
            before={"status": PreparedAction.Status.WAITING},
            after={"status": PreparedAction.Status.REJECTED},
            reason="Rejected on the console.",
            metadata=marker(prepared.key_id, prepared.pk),
        )
    return Decision(PreparedAction.Status.REJECTED, "The change is rejected. Nothing was done.")
