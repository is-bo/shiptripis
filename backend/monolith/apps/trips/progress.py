"""Progress updates and leg reminders (spec 11, plan L5A).

The traveler tells Wassla "at the port", "departed" and "arrived" for each leg.
A report is the traveler's statement: it is copied onto the timeline of every
funded parcel on the leg, labelled as reported by the traveler, and tells each
sender. It writes no `Deal` column, calls no lifecycle transition and moves no
money (plan 1.5 rule 3); early arrival stays the separate fact in
`apps.deals.arrival`.

Reminders are a durable obligation, not an after-commit callback. Publishing a
journey records one `ScheduledJob` per leg and kind (`schedule_leg_reminders`);
`handle_leg_reminder` re-reads every gate when it runs and does nothing if the
question is no longer worth asking.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from apps.core import channels, redis_bus
from apps.core.event_resources import deal_resources
from apps.core.marketplace_policy import marketplace_policy

from .models import Journey, JourneyLeg, JourneyLegProgress

Kind = JourneyLegProgress.Kind

#: A report can be taken back for this long (plan L5A).
RETRACT_WINDOW = timedelta(minutes=10)
#: A leg can be reported on no earlier than this before its planned time.
EARLY_LIMIT = timedelta(hours=24)
#: The server-authored label the sender reads on every projected report.
SOURCE_TRAVELER_REPORTED = "traveler_reported"

REPORTABLE_STATUSES = (Journey.Status.ACTIVE, Journey.Status.IN_PROGRESS)

# Stable machine codes.
NOT_OWNED = "journey_not_owned"
NOT_REPORTABLE = "journey_not_reportable"
KIND_NOT_ALLOWED = "progress_kind_not_allowed"
OUT_OF_ORDER = "progress_out_of_order"
TOO_EARLY = "progress_too_early"
NOT_FOUND = "progress_not_found"
RETRACT_CLOSED = "progress_retract_window_closed"
HAS_FOLLOWUP = "progress_has_followup"


class ProgressError(RuntimeError):
    def __init__(self, code: str, message: str, *, http_status: int, extra: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.extra = extra or {}

    def as_payload(self) -> dict:
        return {"code": self.code, "detail": self.message, **self.extra}


def _refuse(code: str, message: str, http_status: int = 409, **extra) -> ProgressError:
    return ProgressError(code, message, http_status=http_status, extra=extra)


# --- the rules ---------------------------------------------------------------


def planned_at(leg: JourneyLeg, kind: str) -> datetime:
    """The planned instant a report of ``kind`` is about."""

    if kind == Kind.ARRIVED:
        return leg.arrive_at or leg.depart_at
    return leg.depart_at


def _live(legs: list[JourneyLeg]) -> dict[tuple[int, str], JourneyLegProgress]:
    return {
        (row.leg_id, row.kind): row
        for row in JourneyLegProgress.objects.filter(
            leg__in=legs, retracted_at__isnull=True
        )
    }


def kind_blocker(
    leg: JourneyLeg,
    kind: str,
    *,
    previous: JourneyLeg | None,
    live: dict[tuple[int, str], JourneyLegProgress],
) -> str | None:
    """Why ``kind`` cannot be reported on ``leg`` yet, ignoring time. None if it can."""

    if kind == Kind.AT_PORT:
        if leg.mode != JourneyLeg.Mode.SEA:
            return KIND_NOT_ALLOWED
        if (leg.pk, Kind.DEPARTED) in live:
            return OUT_OF_ORDER
        return None
    if kind == Kind.DEPARTED:
        if previous is not None and (previous.pk, Kind.ARRIVED) not in live:
            return OUT_OF_ORDER
        return None
    if kind == Kind.ARRIVED:
        return None if (leg.pk, Kind.DEPARTED) in live else OUT_OF_ORDER
    return KIND_NOT_ALLOWED


def _ordered_legs(journey_id: int) -> list[JourneyLeg]:
    return list(
        JourneyLeg.objects.filter(journey_id=journey_id)
        .select_related("origin_place", "destination_place")
        .order_by("position", "pk")
    )


def _previous(legs: list[JourneyLeg], leg: JourneyLeg) -> JourneyLeg | None:
    index = next(i for i, row in enumerate(legs) if row.pk == leg.pk)
    return legs[index - 1] if index else None


# --- reporting ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReportResult:
    progress: JourneyLegProgress
    created: bool


@transaction.atomic
def report_progress(*, journey_id: int, leg_id: int, actor, kind: str) -> ReportResult:
    """`POST /api/journeys/<id>/legs/<leg_id>/progress`. Idempotent per leg and kind."""

    journey = Journey.objects.select_for_update(no_key=True).get(pk=journey_id)
    if journey.traveler_id != getattr(actor, "pk", None):
        raise _refuse(NOT_OWNED, "Only the journey owner can report progress.", 403)
    if journey.status not in REPORTABLE_STATUSES:
        raise _refuse(
            NOT_REPORTABLE,
            f"A journey in status '{journey.status}' takes no progress reports.",
            status=journey.status,
        )
    legs = _ordered_legs(journey.pk)
    leg = next((row for row in legs if row.pk == leg_id), None)
    if leg is None:
        raise _refuse(NOT_FOUND, "This leg is not part of the journey.", 404)

    live = _live(legs)
    existing = live.get((leg.pk, kind))
    if existing is not None:
        return ReportResult(existing, created=False)
    blocker = kind_blocker(leg, kind, previous=_previous(legs, leg), live=live)
    if blocker:
        raise _refuse(blocker, "This report does not fit the order of the trip.", kind=kind)
    at = timezone.now()
    earliest = planned_at(leg, kind) - EARLY_LIMIT
    if at < earliest:
        raise _refuse(
            TOO_EARLY,
            "It is too early to report this.",
            kind=kind,
            available_at=earliest.isoformat(),
        )

    progress = JourneyLegProgress.objects.create(
        leg=leg, kind=kind, reported_by=actor, reported_at=at
    )
    _fan_out(progress, leg=leg, actor=actor)
    if kind == Kind.DEPARTED:
        # The arrival question may already have been skipped as "not yet
        # departed"; asking again is keyed to this report so it is a new chain.
        _schedule_one(leg, Kind.ARRIVED, attempt=0, after_report=progress.pk)
    return ReportResult(progress, created=True)


def _funded_deals(leg: JourneyLeg):
    """Deals with a funded or in-transit allocation on ``leg``."""

    from apps.deals.models import Deal, DealLegAllocation

    return (
        Deal.objects.filter(
            pk__in=DealLegAllocation.objects.filter(
                journey_leg=leg,
                status__in=(
                    DealLegAllocation.Status.FUNDED,
                    DealLegAllocation.Status.IN_TRANSIT,
                ),
            ).values("deal_id")
        )
        .order_by("pk")
    )


def _fan_out(progress: JourneyLegProgress, *, leg: JourneyLeg, actor) -> None:
    from apps.deals.lifecycle import record_event
    from apps.deals.models import DealEvent

    for deal in _funded_deals(leg):
        record_event(
            deal,
            DealEvent.Kind.TRAVELER_PROGRESS,
            {
                "source": SOURCE_TRAVELER_REPORTED,
                "progress_id": progress.pk,
                "progress_kind": progress.kind,
                "leg_id": leg.pk,
                "reported_at": progress.reported_at.isoformat(),
            },
            actor_id=actor.pk,
        )
        redis_bus.publish_after_commit(
            channels.DEAL_PROGRESS_REPORTED,
            {**deal_resources(deal), "progress_kind": progress.kind},
            targets=[deal.sender_id],
            idempotency_key=f"progress:{progress.pk}:{deal.pk}",
        )


# --- retracting --------------------------------------------------------------


@transaction.atomic
def retract_progress(*, journey_id: int, progress_id: int, actor) -> JourneyLegProgress:
    """`POST .../progress/<id>/retract`: take a report back within ten minutes."""

    journey = Journey.objects.select_for_update(no_key=True).get(pk=journey_id)
    if journey.traveler_id != getattr(actor, "pk", None):
        raise _refuse(NOT_OWNED, "Only the journey owner can retract a report.", 403)
    progress = (
        JourneyLegProgress.objects.select_for_update()
        .select_related("leg")
        .filter(pk=progress_id, leg__journey_id=journey.pk)
        .first()
    )
    if progress is None:
        raise _refuse(NOT_FOUND, "No such report on this journey.", 404)
    if progress.retracted_at is not None:
        return progress
    at = timezone.now()
    if at > progress.reported_at + RETRACT_WINDOW:
        raise _refuse(RETRACT_CLOSED, "A report can be retracted for ten minutes only.")
    legs = _ordered_legs(journey.pk)
    live = _live(legs)
    if _has_followup(progress, legs, live):
        raise _refuse(HAS_FOLLOWUP, "A later report depends on this one.")

    progress.retracted_at = at
    progress.save(update_fields=["retracted_at"])
    _record_retraction(progress, actor=actor, at=at)
    return progress


def _has_followup(
    progress: JourneyLegProgress,
    legs: list[JourneyLeg],
    live: dict[tuple[int, str], JourneyLegProgress],
) -> bool:
    if progress.kind == Kind.DEPARTED:
        return (progress.leg_id, Kind.ARRIVED) in live
    if progress.kind == Kind.ARRIVED:
        ids = [row.pk for row in legs]
        index = ids.index(progress.leg_id)
        return index + 1 < len(ids) and (ids[index + 1], Kind.DEPARTED) in live
    return False


def _record_retraction(progress: JourneyLegProgress, *, actor, at: datetime) -> None:
    from apps.deals.lifecycle import record_event
    from apps.deals.models import Deal, DealEvent

    deals = Deal.objects.filter(
        pk__in=DealEvent.objects.filter(
            kind=DealEvent.Kind.TRAVELER_PROGRESS,
            payload__progress_id=progress.pk,
        ).values("deal_id")
    ).order_by("pk")
    for deal in deals:
        record_event(
            deal,
            DealEvent.Kind.TRAVELER_PROGRESS_RETRACTED,
            {
                "source": SOURCE_TRAVELER_REPORTED,
                "progress_id": progress.pk,
                "progress_kind": progress.kind,
                "leg_id": progress.leg_id,
                "decided_at": at.isoformat(),
            },
            actor_id=actor.pk,
        )
        # A neutral refresh so an open timeline drops the line; no push.
        redis_bus.publish_after_commit(
            channels.DEAL_UPDATED,
            deal_resources(deal),
            targets=[deal.sender_id],
            idempotency_key=f"progress_retracted:{progress.pk}:{deal.pk}",
        )


# --- reading -----------------------------------------------------------------


def progress_view(journey: Journey, *, now: datetime | None = None) -> dict:
    """`GET /api/journeys/<id>/progress`: reports and server-authored next actions."""

    now = now or timezone.now()
    legs = _ordered_legs(journey.pk)
    reports: dict[int, list[JourneyLegProgress]] = {}
    for row in JourneyLegProgress.objects.filter(leg__in=legs).order_by("reported_at", "pk"):
        reports.setdefault(row.leg_id, []).append(row)
    live = _live(legs)
    reportable = journey.status in REPORTABLE_STATUSES
    out = []
    for index, leg in enumerate(legs):
        previous = legs[index - 1] if index else None
        actions = []
        for kind in (Kind.AT_PORT, Kind.DEPARTED, Kind.ARRIVED):
            if (leg.pk, kind) in live or kind_blocker(
                leg, kind, previous=previous, live=live
            ):
                continue
            available_at = planned_at(leg, kind) - EARLY_LIMIT
            actions.append(
                {
                    "kind": kind,
                    "available_at": available_at,
                    "can_report_now": reportable and now >= available_at,
                }
            )
        out.append(
            {
                "leg_id": leg.pk,
                "position": leg.position,
                "mode": leg.mode,
                "origin_name": leg.origin_place.name if leg.origin_place else "",
                "destination_name": (
                    leg.destination_place.name if leg.destination_place else ""
                ),
                "depart_at": leg.depart_at,
                "arrive_at": leg.arrive_at,
                "reports": [
                    {
                        "id": row.pk,
                        "kind": row.kind,
                        "source": row.source,
                        "reported_at": row.reported_at,
                        "retracted_at": row.retracted_at,
                        "can_retract": reportable
                        and row.retracted_at is None
                        and now <= row.reported_at + RETRACT_WINDOW
                        and not _has_followup(row, legs, live),
                        "retractable_until": row.reported_at + RETRACT_WINDOW,
                    }
                    for row in reports.get(leg.pk, [])
                ],
                "next_actions": actions,
            }
        )
    return {"journey_id": journey.pk, "status": journey.status, "legs": out}


def carries_funded_parcel(leg: JourneyLeg) -> bool:
    return _funded_deals(leg).exists()


def pending_questions(user, *, now: datetime | None = None) -> list[dict]:
    """The reminder questions due for ``user`` right now (Home's "needs attention")."""

    policy = marketplace_policy().reminders
    if not policy.enabled:
        return []
    now = now or timezone.now()
    journeys = Journey.objects.filter(traveler=user, status__in=REPORTABLE_STATUSES)
    questions = []
    for journey in journeys.order_by("pk"):
        legs = _ordered_legs(journey.pk)
        live = _live(legs)
        for index, leg in enumerate(legs):
            previous = legs[index - 1] if index else None
            for kind, after in (
                (Kind.DEPARTED, policy.depart_after_minutes),
                (Kind.ARRIVED, policy.arrive_after_minutes),
            ):
                if (leg.pk, kind) in live or kind_blocker(
                    leg, kind, previous=previous, live=live
                ):
                    continue
                due = planned_at(leg, kind) + timedelta(minutes=after)
                if now < due or not carries_funded_parcel(leg):
                    continue
                place = leg.origin_place if kind == Kind.DEPARTED else leg.destination_place
                questions.append(
                    {
                        "journey_id": journey.pk,
                        "leg_id": leg.pk,
                        "kind": kind,
                        "place_name": place.name if place else "",
                        "planned_at": planned_at(leg, kind),
                    }
                )
    return questions


# --- reminders ---------------------------------------------------------------


def _schedule_one(
    leg: JourneyLeg,
    kind: str,
    *,
    attempt: int,
    after_report: int | None = None,
    run_at: datetime | None = None,
) -> None:
    from apps.finance.models import ScheduledJob
    from apps.finance.services import schedule_job

    policy = marketplace_policy().reminders
    planned = planned_at(leg, kind)
    if run_at is None:
        after = policy.depart_after_minutes if kind == Kind.DEPARTED else policy.arrive_after_minutes
        run_at = max(planned + timedelta(minutes=after), timezone.now())
    key = f"leg_reminder:{leg.pk}:{kind}:{int(planned.timestamp())}:{attempt}"
    if after_report is not None:
        key += f":after{after_report}"
    schedule_job(
        kind=ScheduledJob.Kind.LEG_REMINDER,
        key=key,
        run_at=run_at,
        payload={
            "leg_id": leg.pk,
            "kind": kind,
            "planned_at": planned.isoformat(),
            "attempt": attempt,
            **({"after_report": after_report} if after_report is not None else {}),
        },
    )


def schedule_leg_reminders(journey: Journey) -> None:
    """Record the first "departed" and "arrived" question of every leg.

    Call inside the transaction that publishes or re-times the journey.
    Idempotent: the job key names the leg, kind and planned time, so calling it
    again with unchanged times adds nothing, and a changed time adds a new job
    while the old one finds the time moved and does nothing.
    """

    for leg in JourneyLeg.objects.filter(journey=journey):
        _schedule_one(leg, Kind.DEPARTED, attempt=0)
        _schedule_one(leg, Kind.ARRIVED, attempt=0)


def handle_leg_reminder(payload: dict) -> str:
    """`ScheduledJob` handler. Idempotent; re-reads every gate it depends on."""

    from apps.finance.jobs import PermanentJobError

    leg_id, kind, planned, attempt = (
        payload.get("leg_id"),
        payload.get("kind"),
        payload.get("planned_at"),
        payload.get("attempt"),
    )
    try:
        planned_instant = datetime.fromisoformat(planned)
    except (TypeError, ValueError):
        planned_instant = None
    if (
        not isinstance(leg_id, int)
        or isinstance(leg_id, bool)
        or kind not in (Kind.DEPARTED, Kind.ARRIVED)
        or planned_instant is None
        or not isinstance(attempt, int)
        or isinstance(attempt, bool)
        or attempt < 0
    ):
        raise PermanentJobError(
            "leg_reminder needs leg_id, kind, planned_at and attempt.",
            code="invalid_payload",
        )
    after_report = payload.get("after_report")
    if after_report is not None and (
        not isinstance(after_report, int) or isinstance(after_report, bool)
    ):
        raise PermanentJobError("leg_reminder after_report must be an id.", code="invalid_payload")
    policy = marketplace_policy().reminders
    if not policy.enabled:
        return "reminders_disabled"
    with transaction.atomic():
        leg = (
            JourneyLeg.objects.select_related("journey")
            .filter(pk=leg_id)
            .first()
        )
        if leg is None:
            return "leg_gone"
        journey = leg.journey
        if journey.status not in REPORTABLE_STATUSES:
            return "journey_not_live"
        if planned_at(leg, kind) != planned_instant:
            return "schedule_changed"
        if not carries_funded_parcel(leg):
            return "no_funded_parcel"
        legs = _ordered_legs(journey.pk)
        live = _live(legs)
        if (leg.pk, kind) in live:
            return "already_reported"
        if kind_blocker(leg, kind, previous=_previous(legs, leg), live=live):
            # The earlier question comes first; reporting it re-arms this one.
            return "not_yet_askable"
        redis_bus.publish_after_commit(
            channels.JOURNEY_LEG_REMINDER,
            {
                "journey_id": journey.pk,
                "leg_id": leg.pk,
                "progress_kind": kind,
                "attempt": attempt,
            },
            targets=[journey.traveler_id],
            idempotency_key=(
                f"leg_reminder:{leg.pk}:{kind}:{int(planned_instant.timestamp())}:{attempt}"
                + (f":after{after_report}" if after_report is not None else "")
            ),
        )
        if attempt < policy.max_repeats:
            _schedule_one(
                leg,
                kind,
                attempt=attempt + 1,
                after_report=after_report,
                run_at=timezone.now() + timedelta(minutes=policy.repeat_after_minutes),
            )
    return "notified"
