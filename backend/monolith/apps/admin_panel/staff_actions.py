"""The console's guarded staff actions, one function each (plan L16).

The console view and the AI helper's action registry
(`apps.admin_helper.actions`) call the same function, so an action has one
implementation: the same domain service, the same permission check and the
same audit row, whoever pressed the button. Before L16 the five actions marked
"moved" lived inside their console views; they moved here unchanged in
behaviour. The other functions are new in L16:

* `add_note`: an internal note on a delivery, a dispute or a person.
* `set_account_ban`: ban an account, or restore it, with a reason.

Every function checks the capability it needs with the fresh check
(`has_all_admin_permissions`) and refuses with `PermissionDenied`, so a caller
that forgot its own gate still cannot act.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction

from apps.deals.models import Deal
from apps.disputes.models import Dispute
from apps.finance.models import ScheduledJob

from .models import AdminNote
from .people_links import PROFILE_CAPABILITIES
from .permissions import has_all_admin_permissions, has_admin_permission
from .services import record_admin_action

User = get_user_model()

REASON_MAX_LENGTH = 500


class StaffActionError(RuntimeError):
    """A refusal with a stable machine code, shown to staff as its message."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _require(actor, *codes: str) -> None:
    """Any of ``codes``, read fresh (a downgrade or ban applies at once)."""

    if not any(has_all_admin_permissions(actor, code) for code in codes):
        raise PermissionDenied("Your staff role does not allow this.")


def _reason(reason: str) -> str:
    reason = (reason or "").strip()
    if not reason:
        raise StaffActionError("reason_required", "A reason is required.")
    return reason[:REASON_MAX_LENGTH]


# --- disputes (moved from `console_views.dispute_detail`) ---------------------------


def change_dispute_status(*, actor, dispute_id: int, status: str, note: str = "") -> Dispute:
    """Move a dispute's review state (open, awaiting evidence, under review)."""

    from apps.disputes.services import set_dispute_status

    _require(actor, "manage_disputes")
    with transaction.atomic():
        before = Dispute.objects.values_list("status", flat=True).get(pk=dispute_id)
        updated = set_dispute_status(
            dispute_id=dispute_id,
            status=status,
            admin_actor_id=actor.pk,
            note=note,
        )
        record_admin_action(
            actor=actor,
            action="dispute.status_changed",
            target=updated,
            before={"status": before},
            after={"status": updated.status},
            reason=note,
        )
    return updated


def resolve_dispute(
    *,
    actor,
    dispute_id: int,
    resolution: str,
    sender_refund_eur_cents: int | None,
    traveler_payout_eur_cents: int | None,
    note: str = "",
) -> Dispute:
    """Decide a dispute through the settlement engine, and audit the outcome."""

    from apps.disputes.services import resolve_dispute as settle

    _require(actor, "resolve_disputes")
    with transaction.atomic():
        current = Dispute.objects.values("status", "resolution").get(pk=dispute_id)
        updated = settle(
            dispute_id=dispute_id,
            admin_actor_id=actor.pk,
            resolution=resolution,
            sender_refund_eur_cents=sender_refund_eur_cents,
            traveler_payout_eur_cents=traveler_payout_eur_cents,
            note=note,
        )
        record_admin_action(
            actor=actor,
            action="dispute.resolved",
            target=updated,
            before={"status": current["status"], "resolution": current["resolution"]},
            after={
                "status": updated.status,
                "resolution": updated.resolution,
                "sender_refund_eur_cents": updated.sender_refund_eur_cents,
                "traveler_payout_eur_cents": updated.traveler_payout_eur_cents,
                "platform_fee_eur_cents": updated.platform_fee_eur_cents,
            },
            reason=note,
        )
    return updated


# --- refunds (moved from `console_views.refund_request`) ----------------------------


def request_refund(*, actor, attempt_id: int, amount_eur_cents: int, reason: str):
    """Ask for a refund of one captured payment. ``reason`` is a refund reason code."""

    from apps.finance.models import PaymentAttempt
    from apps.finance.services import request_refund as create_refund

    _require(actor, "issue_refunds")
    order_id = PaymentAttempt.objects.values_list("order_id", flat=True).get(pk=attempt_id)
    with transaction.atomic():
        refund = create_refund(
            order_id=order_id,
            attempt_id=attempt_id,
            amount_eur_cents=amount_eur_cents,
            reason=reason,
            requested_by_id=actor.pk,
        )
        record_admin_action(
            actor=actor,
            action="refund.requested",
            target=refund,
            after={"status": refund.status, "amount_eur_cents": refund.amount_eur_cents},
            reason=reason,
        )
    return refund


# --- background jobs (moved from `console_views.background_job_*`) -----------------

#: The jobs whose retry or resolution is Finance's call alone.
FINANCE_JOB_KINDS = frozenset(
    {
        ScheduledJob.Kind.DEPOSIT_EXPIRY_REFUND,
        ScheduledJob.Kind.PAYMENT_GRACE_RELEASE,
        ScheduledJob.Kind.ATTEMPT_EXPIRY,
        ScheduledJob.Kind.CHECKOUT_CLOSE,
        ScheduledJob.Kind.PROVIDER_RECONCILE,
        ScheduledJob.Kind.PROVIDER_EVENT_PROCESS,
        ScheduledJob.Kind.REFUND_RECONCILE,
        ScheduledJob.Kind.PAYOUT_RELEASE_CHECK,
    }
)


def can_manage_job(user, job: ScheduledJob) -> bool:
    """Finance decides money jobs; Finance or lifecycle staff decide the rest."""

    if job.kind in FINANCE_JOB_KINDS:
        return has_admin_permission(user, "reconcile_finance")
    return has_admin_permission(user, "manage_lifecycle") or has_admin_permission(
        user, "reconcile_finance"
    )


def needs_decision(job: ScheduledJob) -> bool:
    """A failure nobody has retried or archived yet: the job page offers both."""

    return job.status == ScheduledJob.Status.FAILED and not job.resolution


def _require_job(actor, job: ScheduledJob, verb: str) -> None:
    _require(actor, "reconcile_finance", "manage_lifecycle")
    if not can_manage_job(actor, job):
        raise PermissionDenied(f"Your role cannot {verb} this kind of job.")


def retry_job(*, actor, job_id: int, reason: str) -> ScheduledJob:
    """Queue a failed job for one more run through its idempotent handler."""

    from apps.finance.operations import retry_failed_job

    job = ScheduledJob.objects.get(pk=job_id)
    _require_job(actor, job, "retry")
    with transaction.atomic():
        before = {"status": job.status, "attempts": job.attempts, "error_code": job.last_error_code}
        requeued = retry_failed_job(job_id=job.pk)
        record_admin_action(
            actor=actor,
            action="scheduled_job.retry_queued",
            target=requeued,
            before=before,
            after={"status": requeued.status, "run_at": requeued.run_at},
            reason=reason,
        )
    return requeued


def resolve_job(*, actor, job_id: int, resolution: str, reason: str) -> ScheduledJob:
    """Archive a failed job's failure without running it again."""

    from apps.finance.operations import resolve_failed_job

    job = ScheduledJob.objects.get(pk=job_id)
    _require_job(actor, job, "resolve")
    with transaction.atomic():
        resolved = resolve_failed_job(
            job_id=job.pk,
            actor_id=actor.pk,
            resolution=resolution,
            reason=reason,
        )
        record_admin_action(
            actor=actor,
            action="scheduled_job.resolved",
            target=resolved,
            before={"status": job.status, "resolution": job.resolution},
            after={"status": resolved.status, "resolution": resolved.resolution},
            reason=reason,
        )
    return resolved


# --- internal notes (new in L16) -----------------------------------------------------

#: What a note can be written on: the record, and the capabilities of its
#: console page (any of them opens the page, and so lets staff add a note).
NOTE_TARGETS: dict[str, tuple[type, tuple[str, ...]]] = {
    AdminNote.TargetType.DEAL: (Deal, ("view_deals",)),
    AdminNote.TargetType.DISPUTE: (Dispute, ("view_disputes",)),
    AdminNote.TargetType.PERSON: (User, PROFILE_CAPABILITIES),
}


def note_permission(target_type: str) -> tuple[str, ...]:
    return NOTE_TARGETS[target_type][1]


def may_add_note(user, target_type: str) -> bool:
    return any(has_admin_permission(user, code) for code in note_permission(target_type))


def add_note(
    *,
    actor,
    target_type: str,
    target_id: int,
    body: str,
    reason: str = "",
    via_helper: bool = False,
) -> AdminNote:
    """Append an internal note, audited.

    The audit row's reason is ``reason`` when one is given (the AI helper says
    why it adds a note), otherwise the note itself: a console note has one
    field, and what it says is why it was written.
    """

    if target_type not in NOTE_TARGETS:
        raise StaffActionError("note_target_invalid", "A note goes on a delivery, a dispute or a person.")
    _require(actor, *note_permission(target_type))
    body = (body or "").strip()
    if not body:
        raise StaffActionError("note_empty", "Write the note first.")
    if len(body) > AdminNote.BODY_MAX_LENGTH:
        raise StaffActionError(
            "note_too_long", f"A note holds at most {AdminNote.BODY_MAX_LENGTH} characters."
        )
    model = NOTE_TARGETS[target_type][0]
    if not model.objects.filter(pk=target_id).exists():
        raise StaffActionError("note_target_missing", "That record does not exist.")
    with transaction.atomic():
        note = AdminNote.objects.create(
            target_type=target_type,
            target_id=target_id,
            author=actor,
            body=body,
            via_helper=via_helper,
        )
        record_admin_action(
            actor=actor,
            action="admin_note.added",
            target=note,
            after={
                "target_type": target_type,
                "target_id": target_id,
                "characters": len(body),
            },
            reason=(reason or "").strip() or body,
        )
    return note


def notes_for(target_type: str, target_id: int):
    return (
        AdminNote.objects.filter(target_type=target_type, target_id=target_id)
        .select_related("author")
        .order_by("-created_at", "-id")
    )


# --- account ban (new in L16) --------------------------------------------------------

BAN_PERMISSION = "manage_users"


def ban_refusal(actor, person, *, banned: bool) -> StaffActionError | None:
    """Why ``actor`` may not set ``person``'s ban to ``banned`` now, or ``None``."""

    if person.pk == actor.pk:
        return StaffActionError("account_ban_self", "You cannot ban or restore your own account.")
    if person.deleted_at is not None:
        # The member deleted it; a restore would bring back an emptied account.
        return StaffActionError("account_deleted", "This account was deleted by its owner.")
    if person.is_staff:
        return StaffActionError(
            "account_ban_staff",
            "This is a staff account. Staff access is changed on Staff & access, not here.",
        )
    if person.is_banned == banned:
        return StaffActionError(
            "account_ban_unchanged",
            "This account is already banned." if banned else "This account is not banned.",
        )
    return None


def set_account_ban(*, actor, user_id: int, banned: bool, reason: str):
    """Ban a member's account, or restore it, with a reason (audited).

    It changes exactly what the technical admin's bulk action changed: a ban
    sets ``is_banned`` and clears ``is_active``, which signs the person out; a
    restore does the opposite. Nothing else moves: no delivery is cancelled,
    no money is touched, no payout is released.
    """

    _require(actor, BAN_PERMISSION)
    reason = _reason(reason)
    with transaction.atomic():
        person = User.objects.select_for_update().get(pk=user_id)
        refusal = ban_refusal(actor, person, banned=banned)
        if refusal is not None:
            raise refusal
        before = {"is_banned": person.is_banned, "is_active": person.is_active}
        person.is_banned = banned
        person.is_active = not banned
        person.save(update_fields=["is_banned", "is_active"])
        record_admin_action(
            actor=actor,
            action="account.banned" if banned else "account.restored",
            target=person,
            before=before,
            after={"is_banned": person.is_banned, "is_active": person.is_active},
            reason=reason,
        )
    return person
