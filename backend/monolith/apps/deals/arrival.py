"""Phase I1A: the funded arrival basis, early arrival, and the payout floor.

Three separate facts are kept separate here, because conflating any two of them
is how a delivery marketplace loses money:

``the traveler arrived``
    A claim about where a person is. Reported by the traveler, confirmed by the
    sender, recorded in `DealArrivalReport`. It changes no Deal status, releases
    no code and moves no money.

``the parcel was delivered``
    A verified delivery code, consumed by `apps.handover`. This is the only
    thing that starts the protection window.

``the payout may be released``
    `apps.finance.payout_release`, gated on *both* the protection window and
    the arrival floor below.

**Why a floor exists at all.** Protection is measured forward from the actual
delivery, so the earlier a delivery is confirmed the earlier the money moves. A
traveler who can make the platform believe they delivered on day one of a
fifteen-day schedule can collect on day three, before the sender has any real
chance to notice a problem. The funded schedule is the natural brake: whatever
else happens, this Deal does not pay out before the arrival its two parties
agreed to when the money was taken.

**Why it is frozen.** The floor is read from `Deal.arrival_snapshot` and
`Deal.funded_scheduled_arrival_floor_at`, both written once inside the funding
transaction. Nothing in this module re-reads a `Journey` or `JourneyLeg` row
after funding. Journey edits are already refused while a Deal exists
(`apps.trips.services.journey_editability`), so the snapshot is belt and
braces -- but it is the belt that holds if an operator, a data migration or a
future feature ever moves a leg time under a live Deal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from apps.core.financial_locks import LockedLifecycleAggregate, lock_deal_lifecycle

from .models import Deal, DealArrivalReport

#: The version stamped into every snapshot this module writes. Bump it only
#: alongside a documented change to what the keys mean; the reader below must
#: keep understanding every version it has ever written.
ARRIVAL_POLICY_VERSION = "i1a.v1"

#: How much earlier than the funded schedule an arrival must be before the
#: platform treats it as a *material* early arrival worth the sender's
#: attention.
#:
#: Six hours, and this is the only place the number exists. The reasoning:
#:
#: * It has to clear ordinary en-route jitter. A flight landing forty minutes
#:   ahead of schedule, or a drive leg finishing an hour early, is not news; a
#:   confirmation flow for it would train both parties to ignore the flow.
#: * It has to clear the handover machinery that already exists. The
#:   delivery-code buffer is thirty minutes and the parties still have to reach
#:   a meeting point, so anything inside a few hours is handled by the normal
#:   pickup/delivery flow without a separate announcement.
#: * It has to be short enough to be useful. "I am here a day early" is exactly
#:   the case the sender needs to hear about, because a recipient has to be
#:   found. Six hours catches every same-day-earlier and every earlier-day
#:   arrival while excluding the noise.
#:
#: It is server-authoritative. Flutter is told *whether* an arrival is
#: materially early, never how to work it out.
MATERIAL_EARLY_ARRIVAL_THRESHOLD_SECONDS = 21_600

#: Where a funded arrival instant may come from, most specific first. The value
#: is stored in `arrival_snapshot["basis"]` so an audit can reproduce it.
BASIS_MATCH_DELIVERY = "match_delivery_interpolation"
BASIS_ALLOCATED_LEG_ARRIVAL = "allocated_leg_arrival"
BASIS_MATCHED_END_LEG_ARRIVAL = "matched_end_leg_arrival"
BASIS_UNAVAILABLE = "unavailable"

#: Provenance values. `funding` is the only one this module writes; the other is
#: written by the I1A backfill migration and never by application code.
PROVENANCE_FUNDING = "funding"
PROVENANCE_LEGACY_MATCH_SNAPSHOT = "legacy_match_snapshot_v1"

#: Machine reasons an early-arrival report is unavailable. The client renders
#: copy for these; it never derives one.
REASON_NOT_TRAVELER = "not_traveler"
REASON_NOT_SENDER = "not_sender"
REASON_ARRIVAL_BASIS_MISSING = "arrival_basis_missing"
REASON_REQUIRES_CARRIAGE = "arrival_requires_carriage"
REASON_DELIVERY_CONFIRMED = "delivery_already_confirmed"
REASON_DEAL_CLOSED = "deal_closed"
REASON_DISPUTE_ACTIVE = "dispute_active"
REASON_NOT_MATERIALLY_EARLY = "not_materially_early"
REASON_REPORT_PENDING = "arrival_report_pending"
REASON_ALREADY_CONFIRMED = "arrival_already_confirmed"
REASON_NO_OPEN_REPORT = "no_open_arrival_report"

ACTION_REPORT = "report_early_arrival"
ACTION_CONFIRM = "confirm_early_arrival"
ACTION_DECLINE = "decline_early_arrival"

#: Arrival states the mobile contract exposes.
STATE_NOT_REPORTED = "not_reported"
STATE_PENDING_CONFIRMATION = "pending_confirmation"
STATE_CONFIRMED = "confirmed"
STATE_DECLINED = "declined"

#: Deal statuses that are closed for good, in which no arrival claim is
#: meaningful any more.
_CLOSED_STATUSES = (
    Deal.Status.CANCELLED,
    Deal.Status.EXPIRED,
    Deal.Status.REFUNDED,
    Deal.Status.PARTIALLY_REFUNDED,
    Deal.Status.PAYMENT_FAILED,
    Deal.Status.COMPLETED,
)


class ArrivalError(RuntimeError):
    """An arrival request was refused. `code` says which condition failed."""

    code = "arrival_error"

    def __init__(self, message: str, *, code: str | None = None, **details):
        super().__init__(message)
        if code:
            self.code = code
        self._details = details

    def details(self) -> dict:
        return dict(self._details)


# --- the funded snapshot ------------------------------------------------------


def material_threshold(deal: Deal) -> int:
    """The materiality threshold in force for one Deal.

    Read from the Deal's own frozen snapshot so a later change to the constant
    cannot retroactively make a already-reported arrival trivial, or make a
    trivial one material. A Deal funded before I1A has no snapshot and falls
    back to the current constant, which is the conservative answer: it is the
    same number every new Deal gets.
    """

    raw = (deal.arrival_snapshot or {}).get("material_early_threshold_seconds")
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        return MATERIAL_EARLY_ARRIVAL_THRESHOLD_SECONDS
    return raw


def arrival_basis(deal: Deal) -> str:
    basis = (deal.arrival_snapshot or {}).get("basis")
    return basis if isinstance(basis, str) and basis else BASIS_UNAVAILABLE


def build_funding_snapshot(
    *,
    deal: Deal,
    match,
    journey,
    journey_legs,
    allocations,
    at: datetime,
) -> tuple[datetime | None, dict]:
    """Freeze this Deal's arrival basis and its carrying route.

    Returns `(floor_instant_or_None, snapshot)`. Called once, from
    `apps.deals.lifecycle.snapshot_on_funding`, inside the funding transaction
    while the whole aggregate is held.

    The instant is resolved in this order, most specific first:

    1. ``match.compatibility_snapshot["delivery_at"]`` -- the server's own
       interpolated arrival at *this sender's* delivery anchor, computed by
       `apps.matching.compatibility` when the match was made and never
       recomputed. It is the instant the compatibility decision was actually
       taken against, which makes it the honest answer to "what arrival did
       these two parties agree to?".
    2. The latest ``arrive_at`` among the legs this Deal's capacity is allocated
       on -- the parcel's last carrying leg.
    3. The matched ``end_leg.arrive_at``.

    If none of the three yields an instant the snapshot records
    `basis="unavailable"` and the floor is `None`. A null floor is not a
    fabricated one: `payout_release_gate_at` then reduces to the pre-I1A rule,
    which is exactly the behaviour such a Deal had before.

    Where a future phase replaces the single `arrive_at` with a *window*, the
    floor takes the window's **end**. The floor exists to resist early-arrival
    abuse, so it must never be reducible by widening a schedule.
    """

    allocated_leg_ids = {row.journey_leg_id for row in allocations}
    legs_by_id = {leg.pk: leg for leg in journey_legs}
    carrying = [
        legs_by_id[leg_id] for leg_id in allocated_leg_ids if leg_id in legs_by_id
    ]
    carrying.sort(key=lambda leg: (leg.position, leg.pk))

    snapshot: dict = {
        "policy_version": ARRIVAL_POLICY_VERSION,
        "provenance": PROVENANCE_FUNDING,
        "snapshot_at": at.isoformat(),
        "stored_timezone": "UTC",
        "material_early_threshold_seconds": MATERIAL_EARLY_ARRIVAL_THRESHOLD_SECONDS,
        "journey_id": getattr(journey, "pk", None),
        "journey_schema_version": getattr(journey, "schema_version", None),
        "match_id": getattr(match, "pk", None),
        "matching_version": str(getattr(match, "matching_version", "") or ""),
        "route": [_leg_snapshot(leg) for leg in carrying],
    }

    instant, basis, leg = _resolve_scheduled_arrival(
        match=match, carrying=carrying, legs_by_id=legs_by_id
    )
    snapshot["basis"] = basis
    snapshot["scheduled_arrival_at"] = instant.isoformat() if instant else None
    snapshot["arrival_leg_id"] = leg.pk if leg is not None else None
    snapshot["arrival_leg_position"] = leg.position if leg is not None else None
    return instant, snapshot


def _leg_snapshot(leg) -> dict:
    """One carrying leg, frozen. Identifiers and times only.

    No polyline, no route metadata, no airport metadata, no capacity and no
    distance: those are the traveler's private route detail, and
    `apps.trips.serializers` already withholds them from a non-owner. The
    sender's funded route is built from what is here and nothing else.
    """

    return {
        "leg_id": leg.pk,
        "position": int(leg.position),
        "mode": leg.mode,
        "origin_place_id": leg.origin_place_id,
        "destination_place_id": leg.destination_place_id,
        "origin_location_id": leg.origin_id,
        "destination_location_id": leg.destination_id,
        "depart_at": leg.depart_at.isoformat() if leg.depart_at else None,
        "arrive_at": leg.arrive_at.isoformat() if leg.arrive_at else None,
    }


def _resolve_scheduled_arrival(*, match, carrying, legs_by_id):
    snapshot = getattr(match, "compatibility_snapshot", None) or {}
    raw = snapshot.get("delivery_at")
    if isinstance(raw, str) and raw:
        parsed = parse_instant(raw)
        if parsed is not None:
            # The interpolated instant belongs to whichever leg carries the
            # delivery anchor; the last carrying leg is that leg by
            # construction, and is recorded for audit rather than used.
            return parsed, BASIS_MATCH_DELIVERY, (carrying[-1] if carrying else None)
    with_arrival = [leg for leg in carrying if leg.arrive_at is not None]
    if with_arrival:
        leg = max(with_arrival, key=lambda row: row.arrive_at)
        return leg.arrive_at, BASIS_ALLOCATED_LEG_ARRIVAL, leg
    end_leg = legs_by_id.get(getattr(match, "end_leg_id", None))
    if end_leg is not None and end_leg.arrive_at is not None:
        return end_leg.arrive_at, BASIS_MATCHED_END_LEG_ARRIVAL, end_leg
    return None, BASIS_UNAVAILABLE, None


def parse_instant(raw: str) -> datetime | None:
    from django.utils.dateparse import parse_datetime

    parsed = parse_datetime(raw)
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_default_timezone())
    return parsed


# --- the payout floor ---------------------------------------------------------


def payout_release_gate_at(deal: Deal) -> datetime | None:
    """The earliest instant this Deal's payout may become eligible.

    ``max(delivery_confirmed_at + protection_window, funded_arrival_floor)``

    Stated as the two stored columns rather than as durations, because both of
    them were already computed and written once:
    `Deal.protection_ends_at` at delivery confirmation and
    `Deal.funded_scheduled_arrival_floor_at` at funding. Recomputing either from
    a duration here would give two places that can disagree.

    Returns `None` before a delivery is confirmed: there is no gate instant yet,
    only an unstarted protection window.
    """

    protection = deal.protection_ends_at
    if protection is None:
        return None
    floor = deal.funded_scheduled_arrival_floor_at
    if floor is None or floor <= protection:
        return protection
    return floor


def payout_release_gate_basis(deal: Deal) -> str:
    """Which of the two constraints is the binding one. 32 chars or fewer."""

    gate = payout_release_gate_at(deal)
    if gate is None:
        return ""
    floor = deal.funded_scheduled_arrival_floor_at
    if floor is not None and gate == floor and floor > (deal.protection_ends_at):
        return "schedule_floor"
    return "delivery_protection"


# --- availability -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Availability:
    allowed: bool
    reason: str = ""
    details: dict | None = None

    def as_dict(self) -> dict:
        return {
            "available": self.allowed,
            "reason": self.reason or None,
            **(self.details or {}),
        }


def report_availability(
    *,
    deal: Deal,
    viewer_id: int | None,
    open_report=None,
    confirmed_report=None,
    dispute_active: bool = False,
    at: datetime | None = None,
) -> Availability:
    """May *this* viewer report an early arrival on *this* Deal, right now?

    Every condition in the I1A contract is checked here, once, and the answer is
    a machine reason the client renders. The service performs the same checks
    again under the row lock -- this function is the projection, not the
    authority.
    """

    at = at or timezone.now()
    if viewer_id != deal.traveler_id:
        return Availability(False, REASON_NOT_TRAVELER)
    if deal.status in _CLOSED_STATUSES:
        return Availability(False, REASON_DEAL_CLOSED)
    if deal.delivery_confirmed_at is not None:
        return Availability(False, REASON_DELIVERY_CONFIRMED)
    if dispute_active or deal.status == Deal.Status.DISPUTED:
        return Availability(False, REASON_DISPUTE_ACTIVE)
    scheduled = deal.funded_scheduled_arrival_floor_at
    if scheduled is None:
        return Availability(False, REASON_ARRIVAL_BASIS_MISSING)
    from .lifecycle import IN_CARRIAGE_STATUSES

    if deal.status not in IN_CARRIAGE_STATUSES:
        return Availability(False, REASON_REQUIRES_CARRIAGE)
    if confirmed_report is not None:
        return Availability(False, REASON_ALREADY_CONFIRMED)
    if open_report is not None:
        return Availability(False, REASON_REPORT_PENDING)
    threshold = material_threshold(deal)
    early_by = int((scheduled - at).total_seconds())
    if early_by < threshold:
        return Availability(
            False,
            REASON_NOT_MATERIALLY_EARLY,
            {
                "early_by_seconds": max(0, early_by),
                "threshold_seconds": threshold,
            },
        )
    return Availability(
        True, "", {"early_by_seconds": early_by, "threshold_seconds": threshold}
    )


def decision_availability(
    *, deal: Deal, viewer_id: int | None, open_report=None
) -> Availability:
    """May this viewer answer an open early-arrival claim?"""

    if viewer_id != deal.sender_id:
        return Availability(False, REASON_NOT_SENDER)
    if open_report is None:
        return Availability(False, REASON_NO_OPEN_REPORT)
    if deal.status in _CLOSED_STATUSES:
        return Availability(False, REASON_DEAL_CLOSED)
    if deal.delivery_confirmed_at is not None:
        # The parcel arrived at the recipient while the claim was outstanding.
        # Answering it now decides nothing, so the action is withdrawn and the
        # claim stays on the record as what it was: unanswered.
        return Availability(False, REASON_DELIVERY_CONFIRMED)
    return Availability(True)


# --- services -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ArrivalResult:
    deal_id: int
    report_id: int
    status: str
    changed: bool


def report_early_arrival(*, deal_id: int, actor_id: int) -> ArrivalResult:
    """The traveler's "I arrived early". Idempotent on the open claim.

    A second call while a claim is still pending returns that claim with
    `changed=False`; it does not append a second timeline event, does not send a
    second notification and cannot exist as a second row -- the database refuses
    it too, via `deals_arrival_one_open_per_deal`.
    """

    from . import lifecycle

    with transaction.atomic():
        aggregate = lock_deal_lifecycle(deal_id)
        deal = aggregate.deal
        existing = aggregate.open_arrival_report()
        if existing is not None and existing.reported_by_id == actor_id:
            return ArrivalResult(deal.pk, existing.pk, existing.status, False)
        verdict = report_availability(
            deal=deal,
            viewer_id=actor_id,
            open_report=existing,
            confirmed_report=aggregate.confirmed_arrival_report(),
            dispute_active=aggregate.active_dispute() is not None,
        )
        if not verdict.allowed:
            raise ArrivalError(
                _REFUSALS[verdict.reason],
                code=verdict.reason,
                **(verdict.details or {}),
            )
        report = lifecycle.apply_early_arrival_reported(aggregate, actor_id=actor_id)
        _notify_reported(deal, report)
        return ArrivalResult(deal.pk, report.pk, report.status, True)


def decide_early_arrival(
    *, deal_id: int, actor_id: int, confirm: bool
) -> ArrivalResult:
    """The sender's answer. Idempotent on the decision already recorded.

    A repeated confirmation returns the confirmed row with `changed=False`. A
    confirmation that arrives after a decline -- or the reverse -- is refused
    rather than silently overwritten: the sender already answered, and a claim
    whose answer can flip is not an audit record.
    """

    from . import lifecycle

    with transaction.atomic():
        aggregate = lock_deal_lifecycle(deal_id)
        deal = aggregate.deal
        if actor_id != deal.sender_id:
            raise ArrivalError(
                _REFUSALS[REASON_NOT_SENDER], code=REASON_NOT_SENDER
            )
        open_report = aggregate.open_arrival_report()
        if open_report is None:
            settled = _latest_settled(aggregate)
            target = (
                DealArrivalReport.Status.CONFIRMED
                if confirm
                else DealArrivalReport.Status.DECLINED
            )
            if settled is not None and settled.status == target:
                return ArrivalResult(deal.pk, settled.pk, settled.status, False)
            raise ArrivalError(
                _REFUSALS[REASON_NO_OPEN_REPORT],
                code=REASON_NO_OPEN_REPORT,
                arrival_state=arrival_state_of(settled),
            )
        verdict = decision_availability(
            deal=deal, viewer_id=actor_id, open_report=open_report
        )
        if not verdict.allowed:
            raise ArrivalError(
                _REFUSALS[verdict.reason],
                code=verdict.reason,
                **(verdict.details or {}),
            )
        report = lifecycle.apply_early_arrival_decision(
            aggregate, report=open_report, actor_id=actor_id, confirm=confirm
        )
        _notify_decision(deal, report)
        return ArrivalResult(deal.pk, report.pk, report.status, True)


def _latest_settled(aggregate: LockedLifecycleAggregate):
    settled = [
        row
        for row in aggregate.arrival_reports
        if row.status not in DealArrivalReport.OPEN_STATUSES
    ]
    if not settled:
        return None
    return max(settled, key=lambda row: (row.decided_at or row.reported_at, row.pk))


_REFUSALS = {
    REASON_NOT_TRAVELER: "Only the matched traveler can report an arrival.",
    REASON_NOT_SENDER: "Only this delivery's sender can answer an arrival report.",
    REASON_ARRIVAL_BASIS_MISSING: (
        "This delivery has no funded arrival schedule to measure against."
    ),
    REASON_REQUIRES_CARRIAGE: (
        "An arrival can only be reported while the parcel is being carried."
    ),
    REASON_DELIVERY_CONFIRMED: "This delivery has already been confirmed.",
    REASON_DEAL_CLOSED: "This delivery is closed.",
    REASON_DISPUTE_ACTIVE: (
        "A dispute is open on this delivery. Arrival reporting is unavailable."
    ),
    REASON_NOT_MATERIALLY_EARLY: (
        "This arrival is not materially earlier than the funded schedule."
    ),
    REASON_REPORT_PENDING: (
        "An arrival report is already awaiting the sender's confirmation."
    ),
    REASON_ALREADY_CONFIRMED: "An early arrival has already been confirmed.",
    REASON_NO_OPEN_REPORT: "There is no arrival report awaiting an answer.",
}


# --- notifications ------------------------------------------------------------


def _notify_reported(deal: Deal, report: DealArrivalReport) -> None:
    """Tell the sender, once per report.

    The payload carries resource ids only. No route, no place, no schedule and
    no provider data: `apps.notifications.push` allowlists what may reach a lock
    screen, and this event has nothing else it needs to say.
    """

    from apps.core.channels import DEAL_ARRIVAL_REPORTED
    from apps.core.redis_bus import publish_after_commit
    from apps.core.event_resources import deal_resources

    publish_after_commit(
        DEAL_ARRIVAL_REPORTED,
        deal_resources(deal),
        targets=[deal.sender_id],
        idempotency_key=f"arrival_reported:{report.pk}",
    )


def _notify_decision(deal: Deal, report: DealArrivalReport) -> None:
    from apps.core.channels import DEAL_ARRIVAL_CONFIRMED, DEAL_ARRIVAL_DECLINED
    from apps.core.redis_bus import publish_after_commit
    from apps.core.event_resources import deal_resources

    confirmed = report.status == DealArrivalReport.Status.CONFIRMED
    publish_after_commit(
        DEAL_ARRIVAL_CONFIRMED if confirmed else DEAL_ARRIVAL_DECLINED,
        deal_resources(deal),
        targets=[deal.traveler_id],
        idempotency_key=(
            f"arrival_{'confirmed' if confirmed else 'declined'}:{report.pk}"
        ),
    )


# --- projection ---------------------------------------------------------------


def arrival_state_of(report) -> str:
    if report is None:
        return STATE_NOT_REPORTED
    if report.status == DealArrivalReport.Status.CONFIRMED:
        return STATE_CONFIRMED
    if report.status == DealArrivalReport.Status.DECLINED:
        return STATE_DECLINED
    return STATE_PENDING_CONFIRMATION


def latest_report(deal: Deal):
    """The report the client should be looking at.

    An open claim always wins: it is the one with an outstanding action. Failing
    that, the most recently decided one.
    """

    rows = list(deal.arrival_reports.all())
    if not rows:
        return None
    open_rows = [row for row in rows if row.status in DealArrivalReport.OPEN_STATUSES]
    if open_rows:
        return max(open_rows, key=lambda row: (row.reported_at, row.pk))
    return max(rows, key=lambda row: (row.decided_at or row.reported_at, row.pk))


def arrival_projection(*, deal: Deal, viewer_id: int | None, at: datetime | None = None):
    """The whole journey-timing contract for one viewer, server-derived.

    Everything the client needs in order to render the arrival experience
    without knowing a single rule: which state the arrival is in, what the
    funded schedule is, whether an action is available right now, and why not
    when it is not.
    """

    at = at or timezone.now()
    report = latest_report(deal)
    state = arrival_state_of(report)
    scheduled = deal.funded_scheduled_arrival_floor_at
    open_report = report if state == STATE_PENDING_CONFIRMATION else None
    confirmed = report if state == STATE_CONFIRMED else None
    dispute_active = deal.status == Deal.Status.DISPUTED

    report_verdict = report_availability(
        deal=deal,
        viewer_id=viewer_id,
        open_report=open_report,
        confirmed_report=confirmed,
        dispute_active=dispute_active,
        at=at,
    )
    decision_verdict = decision_availability(
        deal=deal, viewer_id=viewer_id, open_report=open_report
    )
    actions: list[str] = []
    if report_verdict.allowed:
        actions.append(ACTION_REPORT)
    if decision_verdict.allowed:
        actions.extend((ACTION_CONFIRM, ACTION_DECLINE))

    threshold = material_threshold(deal)
    remaining = None if scheduled is None else int((scheduled - at).total_seconds())
    return {
        "state": state,
        "basis": arrival_basis(deal),
        "funded_scheduled_arrival_at": scheduled,
        "material_early_threshold_seconds": threshold,
        # Server-computed, deliberately. The client must not decide what "early"
        # means, and must not compare its own clock to a schedule.
        "is_materially_early_now": bool(
            scheduled is not None and remaining is not None and remaining >= threshold
        ),
        "seconds_until_scheduled_arrival": remaining,
        "server_time": at,
        "reported_at": report.reported_at if report else None,
        "reported_early_by_seconds": (
            int(report.early_by_seconds) if report else None
        ),
        "decided_at": report.decided_at if report else None,
        "arrival_confirmed_at": deal.arrival_confirmed_at,
        # Stated, not implied. A confirmed arrival is a person being somewhere;
        # the protection window and the payout still wait for a verified
        # delivery code. This flag is a contract the client can assert against.
        "confirmed_arrival_is_not_delivery": True,
        "delivery_confirmed_at": deal.delivery_confirmed_at,
        "report_available": report_verdict.allowed,
        "report_unavailable_reason": report_verdict.reason or None,
        "decision_available": decision_verdict.allowed,
        "decision_unavailable_reason": decision_verdict.reason or None,
        "available_actions": actions,
    }


def payout_floor_projection(*, deal: Deal, at: datetime | None = None) -> dict:
    """The two constraints on payout timing, and which one binds.

    Both parties may read it: the traveler needs to know when they will be paid
    and the sender needs to know how long their money stays protected.
    """

    at = at or timezone.now()
    gate = payout_release_gate_at(deal)
    return {
        "protection_ends_at": deal.protection_ends_at,
        "funded_scheduled_arrival_floor_at": deal.funded_scheduled_arrival_floor_at,
        "payout_eligible_from": gate,
        "basis": payout_release_gate_basis(deal) or None,
        "gate_open": bool(gate is not None and at >= gate),
        "server_time": at,
    }
