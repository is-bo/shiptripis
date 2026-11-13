"""Reporting, reading and handling problems (spec 12, plan L9A).

Everything here reads the deal and appends to its timeline; nothing writes a
`Deal` column or calls a lifecycle transition (plan 1.5 rule 3, plan 2.6). A
no-show report is a request for a staff decision: only staff record a no-show,
through the existing action (`apps.deals.cancellation.record_no_show`), and
recording it closes the open reports with a reference to the audit row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core import channels, redis_bus
from apps.core.event_resources import deal_resources
from apps.parcels import tracking

from .models import ShipmentProblem

Kind = ShipmentProblem.Kind
Status = ShipmentProblem.Status
Role = ShipmentProblem.Role

#: Staff authority, reused from the disputes area: a problem is the lighter
#: sibling of a dispute and the same people look at both.
VIEW_PROBLEMS_PERMISSION = "view_disputes"
MANAGE_PROBLEMS_PERMISSION = "manage_disputes"

NOTE_MAX_LENGTH = 1000
REASON_MAX_LENGTH = 500

#: Which party may report each no-show kind: the one who was left waiting.
NO_SHOW_REPORTER = {
    Kind.SENDER_UNAVAILABLE: Role.TRAVELER,
    Kind.TRAVELER_NO_SHOW: Role.SENDER,
}
#: And, the other way round, the no-show kind each party can report.
NO_SHOW_KIND_FOR = {role: kind for kind, role in NO_SHOW_REPORTER.items()}

# Stable machine codes.
NOT_A_PARTY = "not_a_party"
KIND_INVALID = "problem_kind_invalid"
NOTE_TOO_LONG = "problem_note_too_long"
REPORT_NOT_ALLOWED = "problem_report_not_allowed"
KIND_NOT_ALLOWED_FOR_ROLE = "problem_kind_not_allowed_for_role"
NO_SHOW_NOT_ALLOWED = "no_show_report_not_allowed"
NOT_FOUND = "problem_not_found"
ALREADY_CLOSED = "problem_already_closed"
NOT_ACKNOWLEDGEABLE = "problem_not_acknowledgeable"
REASON_REQUIRED = "reason_required"
NOT_PERMITTED = "not_permitted"

# Why a no-show report is not possible right now (the `reason` of
# `no_show_report_not_allowed`, and `no_show_reason` on the read).
NO_SHOW_DEAL_NOT_FUNDED = "deal_not_funded"
NO_SHOW_DEAL_NOT_ACTIVE = "deal_not_active"
NO_SHOW_PICKUP_TIME_UNKNOWN = "pickup_time_unknown"
NO_SHOW_TOO_EARLY = "pickup_time_not_reached"
NO_SHOW_PICKED_UP = "pickup_already_confirmed"
NO_SHOW_ALREADY_RECORDED = "no_show_already_recorded"
NO_SHOW_ALREADY_REPORTED = "already_reported"


class ProblemError(RuntimeError):
    def __init__(self, code: str, message: str, *, http_status: int = 409, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.extra = extra

    def as_payload(self) -> dict:
        return {"code": self.code, "detail": self.message, **self.extra}


def _reportable_statuses():
    from apps.deals.lifecycle import IN_CARRIAGE_STATUSES, PRE_PICKUP_STATUSES

    return (*PRE_PICKUP_STATUSES, *IN_CARRIAGE_STATUSES)


def party_role(deal, user) -> str:
    user_id = getattr(user, "pk", None)
    if user_id is not None and user_id == deal.sender_id:
        return Role.SENDER
    if user_id is not None and user_id == deal.traveler_id:
        return Role.TRAVELER
    return ""


def _other_party_id(deal, role: str) -> int:
    return deal.traveler_id if role == Role.SENDER else deal.sender_id


# --- the no-show window --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NoShowWindow:
    allowed: bool
    reason: str = ""
    available_at: datetime | None = None


def no_show_window(deal, *, now: datetime | None = None) -> NoShowWindow:
    """Whether either party may report a no-show on ``deal`` right now (spec 12).

    From the agreed pickup time until the pickup is confirmed, on a funded deal
    that staff have not already decided on. ``available_at`` is set when the
    window is still ahead, so the app can say when.
    """

    from apps.deals.lifecycle import PRE_PICKUP_STATUSES

    now = now or timezone.now()
    if deal.pickup_confirmed_at is not None:
        return NoShowWindow(False, NO_SHOW_PICKED_UP)
    if deal.funded_at is None:
        return NoShowWindow(False, NO_SHOW_DEAL_NOT_FUNDED)
    if deal.status not in PRE_PICKUP_STATUSES:
        return NoShowWindow(False, NO_SHOW_DEAL_NOT_ACTIVE)
    if deal.no_show_party:
        return NoShowWindow(False, NO_SHOW_ALREADY_RECORDED)
    if deal.agreed_pickup_at is None:
        return NoShowWindow(False, NO_SHOW_PICKUP_TIME_UNKNOWN)
    if now < deal.agreed_pickup_at:
        return NoShowWindow(False, NO_SHOW_TOO_EARLY, deal.agreed_pickup_at)
    return NoShowWindow(True)


# --- reporting -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReportResult:
    problem: ShipmentProblem
    created: bool


def _live(deal_id: int, reporter_id: int, kind: str) -> ShipmentProblem | None:
    return (
        ShipmentProblem.objects.filter(
            deal_id=deal_id,
            reported_by_id=reporter_id,
            kind=kind,
            status__in=ShipmentProblem.LIVE_STATUSES,
        )
        .order_by("pk")
        .first()
    )


@transaction.atomic
def report_problem(*, deal_id: int, actor, kind: str, note: str = "") -> ReportResult:
    """`POST /api/deals/<id>/problems`. A repeat of a live report returns it."""

    from apps.deals.lifecycle import record_event
    from apps.deals.models import Deal, DealEvent

    if kind not in Kind.values:
        raise ProblemError(KIND_INVALID, "Unknown problem kind.", http_status=400)
    note = (note or "").strip()
    if len(note) > NOTE_MAX_LENGTH:
        raise ProblemError(
            NOTE_TOO_LONG,
            f"A note can be {NOTE_MAX_LENGTH} characters at most.",
            http_status=400,
            max_length=NOTE_MAX_LENGTH,
        )
    # The lock serialises a report with a pickup confirmation or a staff
    # no-show decision, so the window is judged on the row as it stands. The
    # report never writes this row.
    deal = (
        Deal.objects.select_for_update(no_key=True, of=("self",))
        .select_related("delivery_request")
        .filter(pk=deal_id)
        .first()
    )
    role = party_role(deal, actor) if deal is not None else ""
    if not role:
        raise ProblemError(NOT_A_PARTY, "No such delivery.", http_status=404)

    named = NO_SHOW_REPORTER.get(kind)
    if named is not None and named != role:
        raise ProblemError(
            KIND_NOT_ALLOWED_FOR_ROLE,
            "Only the person who was left waiting can report this.",
            http_status=403,
            kind=kind,
        )
    existing = _live(deal.pk, actor.pk, kind)
    if existing is not None:
        return ReportResult(existing, created=False)
    if named is not None:
        window = no_show_window(deal)
        if not window.allowed:
            raise ProblemError(
                NO_SHOW_NOT_ALLOWED,
                "This cannot be reported right now.",
                reason=window.reason,
                available_at=(
                    window.available_at.isoformat() if window.available_at else None
                ),
            )
    elif deal.status not in _reportable_statuses():
        raise ProblemError(
            REPORT_NOT_ALLOWED,
            "Problems can be reported from funding until delivery. "
            "After delivery, open a dispute instead.",
            reason=NO_SHOW_DEAL_NOT_FUNDED
            if deal.funded_at is None
            else NO_SHOW_DEAL_NOT_ACTIVE,
        )

    now = timezone.now()
    escalated = kind in ShipmentProblem.ESCALATED_KINDS
    try:
        with transaction.atomic():
            problem = ShipmentProblem.objects.create(
                deal=deal,
                reported_by=actor,
                reporter_role=role,
                kind=kind,
                note=note,
                status=Status.ESCALATED if escalated else Status.OPEN,
                escalated_at=now if escalated else None,
            )
    except IntegrityError:
        # A concurrent duplicate won the unique index; answer with its row.
        existing = _live(deal.pk, actor.pk, kind)
        if existing is None:
            raise
        return ReportResult(existing, created=False)

    record_event(
        deal,
        DealEvent.Kind.PROBLEM_REPORTED,
        _event_payload(problem),
        actor_id=actor.pk,
    )
    redis_bus.publish_after_commit(
        channels.DEAL_PROBLEM_REPORTED,
        {
            **deal_resources(deal),
            "problem_id": problem.pk,
            "problem_kind": problem.kind,
            "tracking_number": tracking.for_deal(deal),
        },
        targets=[_other_party_id(deal, role)],
        idempotency_key=f"problem_reported:{problem.pk}",
    )
    return ReportResult(problem, created=True)


def _event_payload(problem: ShipmentProblem) -> dict:
    """Identifiers and tokens only: never the note or a staff reason."""

    return {
        "problem_id": problem.pk,
        "problem_kind": problem.kind,
        "problem_status": problem.status,
        "reporter_role": problem.reporter_role,
    }


# --- reading -------------------------------------------------------------------


def problem_row(problem: ShipmentProblem, *, viewer_id: int) -> dict:
    """One report as a party sees it. Staff reasons stay internal."""

    return {
        "id": problem.pk,
        "kind": problem.kind,
        "status": problem.status,
        "reporter_role": problem.reporter_role,
        "reported_by_me": problem.reported_by_id == viewer_id,
        "note": problem.note,
        "escalated": problem.escalated_at is not None,
        "created_at": problem.created_at,
        "acknowledged_at": problem.acknowledged_at,
        "closed_at": problem.closed_at,
    }


def problems_view(deal, *, viewer, now: datetime | None = None) -> dict:
    """`GET /api/deals/<id>/problems` for one party.

    Says, for this caller, which kinds can be reported now and, for the no-show
    report, why not and from when, so the app never works out the window.
    """

    now = now or timezone.now()
    role = party_role(deal, viewer)
    rows = list(
        ShipmentProblem.objects.filter(deal=deal).order_by("-created_at", "-pk")
    )
    own_no_show_kind = NO_SHOW_KIND_FOR[role]
    window = no_show_window(deal, now=now)
    already = any(
        row.kind == own_no_show_kind
        and row.reported_by_id == viewer.pk
        and row.status in ShipmentProblem.LIVE_STATUSES
        for row in rows
    )
    can_report_no_show = window.allowed and not already
    no_show_reason = (
        ""
        if can_report_no_show
        else (NO_SHOW_ALREADY_REPORTED if window.allowed else window.reason)
    )
    general_allowed = deal.status in _reportable_statuses()
    reportable = []
    for kind in Kind.values:
        if kind in ShipmentProblem.NO_SHOW_KINDS:
            if kind == own_no_show_kind and can_report_no_show:
                reportable.append(kind)
        elif general_allowed:
            reportable.append(kind)
    return {
        "deal_id": deal.pk,
        "tracking_number": tracking.for_deal(deal),
        "viewer_role": role,
        "no_show_kind": own_no_show_kind,
        "can_report_no_show": can_report_no_show,
        "no_show_reason": no_show_reason,
        "no_show_available_at": window.available_at,
        "reportable_kinds": reportable,
        "results": [problem_row(row, viewer_id=viewer.pk) for row in rows],
    }


# --- staff -----------------------------------------------------------------------


def _require_manager(actor) -> None:
    from apps.admin_panel.permissions import has_all_admin_permissions

    if not has_all_admin_permissions(actor, MANAGE_PROBLEMS_PERMISSION):
        raise ProblemError(
            NOT_PERMITTED,
            "Your staff role cannot handle problem reports.",
            http_status=403,
        )


def _staff_reason(reason: str) -> str:
    reason = (reason or "").strip()
    if not reason:
        raise ProblemError(REASON_REQUIRED, "A reason is required.", http_status=400)
    return reason[:REASON_MAX_LENGTH]


def _lock_problem(problem_id: int) -> ShipmentProblem:
    problem = (
        ShipmentProblem.objects.select_for_update()
        .select_related("deal")
        .filter(pk=problem_id)
        .first()
    )
    if problem is None:
        raise ProblemError(NOT_FOUND, "No such problem report.", http_status=404)
    return problem


def _state(problem: ShipmentProblem) -> dict:
    return {"status": problem.status, "kind": problem.kind}


def _after_staff_change(problem: ShipmentProblem, kind: str, *, actor_id: int) -> None:
    from apps.deals.lifecycle import record_event

    deal = problem.deal
    record_event(deal, kind, _event_payload(problem), actor_id=actor_id)
    # A neutral refresh so an open delivery screen shows the new state; no push.
    redis_bus.publish_after_commit(
        channels.DEAL_UPDATED,
        deal_resources(deal),
        targets=[deal.sender_id, deal.traveler_id],
        idempotency_key=f"problem_{problem.status}:{problem.pk}",
    )


@transaction.atomic
def acknowledge_problem(*, problem_id: int, actor, reason: str) -> ShipmentProblem:
    """Staff have looked at a report and are on it. Audited, with a reason."""

    from apps.admin_panel.services import record_admin_action
    from apps.deals.models import DealEvent

    _require_manager(actor)
    reason = _staff_reason(reason)
    problem = _lock_problem(problem_id)
    if problem.status == Status.ACKNOWLEDGED:
        return problem
    if problem.status not in (Status.OPEN, Status.ESCALATED):
        raise ProblemError(NOT_ACKNOWLEDGEABLE, "This report is already closed.")
    before = _state(problem)
    problem.status = Status.ACKNOWLEDGED
    problem.acknowledged_by = actor
    problem.acknowledged_at = timezone.now()
    problem.acknowledged_reason = reason
    problem.save(
        update_fields=[
            "status",
            "acknowledged_by",
            "acknowledged_at",
            "acknowledged_reason",
            "updated_at",
        ]
    )
    record_admin_action(
        actor=actor,
        action="problem.acknowledged",
        target=problem,
        before=before,
        after=_state(problem),
        reason=reason,
        reference=tracking.for_deal(problem.deal),
    )
    _after_staff_change(problem, DealEvent.Kind.PROBLEM_ACKNOWLEDGED, actor_id=actor.pk)
    return problem


def _close(problem: ShipmentProblem, *, actor, reason: str, audit=None) -> None:
    from apps.deals.models import DealEvent

    problem.status = Status.CLOSED
    problem.closed_by = actor
    problem.closed_at = timezone.now()
    problem.closed_reason = reason
    problem.closed_by_audit = audit
    problem.save(
        update_fields=[
            "status",
            "closed_by",
            "closed_at",
            "closed_reason",
            "closed_by_audit",
            "updated_at",
        ]
    )
    _after_staff_change(problem, DealEvent.Kind.PROBLEM_CLOSED, actor_id=actor.pk)


@transaction.atomic
def close_problem(*, problem_id: int, actor, reason: str) -> ShipmentProblem:
    """Staff close a report. Audited, with a reason. Closing changes no deal."""

    from apps.admin_panel.services import record_admin_action

    _require_manager(actor)
    reason = _staff_reason(reason)
    problem = _lock_problem(problem_id)
    if problem.status == Status.CLOSED:
        raise ProblemError(ALREADY_CLOSED, "This report is already closed.")
    before = _state(problem)
    _close(problem, actor=actor, reason=reason)
    record_admin_action(
        actor=actor,
        action="problem.closed",
        target=problem,
        before=before,
        after=_state(problem),
        reason=reason,
        reference=tracking.for_deal(problem.deal),
    )
    return problem


def close_no_show_reports(*, deal_id: int, actor, audit, party: str) -> list[int]:
    """Close every live no-show report on a deal once staff recorded a no-show.

    Called inside the transaction that recorded it, with its audit row, so the
    report and the decision commit together and the report points at it.
    """

    closed = []
    for problem in (
        ShipmentProblem.objects.select_for_update()
        .select_related("deal")
        .filter(
            deal_id=deal_id,
            kind__in=ShipmentProblem.NO_SHOW_KINDS,
            status__in=ShipmentProblem.LIVE_STATUSES,
        )
        .order_by("pk")
    ):
        _close(
            problem,
            actor=actor,
            reason=f"No-show recorded by staff: {party}.",
            audit=audit,
        )
        closed.append(problem.pk)
    return closed


def record_no_show_link_party(problem: ShipmentProblem) -> str:
    """The party a "Record a no-show" link pre-selects for a no-show report."""

    if problem.kind == Kind.SENDER_UNAVAILABLE:
        return "sender"
    if problem.kind == Kind.TRAVELER_NO_SHOW:
        return "traveler"
    return ""
