"""New times for an active journey (spec 12 "Route changes", plan L9A).

A traveler may move the times of the legs of an active journey. Nothing else:
the legs, stops and places stay as they are, and adding or removing a stop on
an active journey is not part of this build.

How a change runs:

* Every parcel on a changed leg is **affected**. An affected parcel is
  **material** when its new arrival at its drop-off stop is after the request's
  deadline (and later than agreed), or is more than
  `marketplace.route_change.material_shift_minutes` away from the arrival its
  sender last agreed to (the arrival of the last change they accepted, else the
  one frozen at funding). A parcel not collected yet is also material when the
  departure from its pickup stop moves more than the same threshold from the
  agreed pickup, or earlier to before the deal's agreed pickup time.
* A **collected** parcel is informed, never asked: its sender can no longer
  cancel, so it never holds a change back (advisor, 2026-11-13).
* With no material parcel the change applies at once and the affected senders
  are told. Otherwise it waits: each material parcel's sender accepts or
  declines, and the change applies once every material parcel is accepted,
  collected or no longer active. The traveler may withdraw it while it waits.
* A sender who declines may cancel through the existing cancellation flow; that
  cancellation is caused by the traveler and settles exactly as a traveler's
  own cancellation does (`apps.deals.cancellation`). No new refund rule exists.

What a change never does: write a `Deal` column or call a lifecycle transition
(plan 1.5 rule 3). The arrival snapshot, the payout floor and the agreed pickup
time stay what funding froze. Applying re-times the legs, sends a re-timed
ticket back to review exactly as a route edit does, and re-records the leg
reminders (`progress.schedule_leg_reminders`).

Lock order: the journey row first, as acceptance and every deal transition do,
then the change and its consents, then the legs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.core import channels, redis_bus
from apps.core.event_resources import deal_resources
from apps.core.marketplace_policy import marketplace_policy
from apps.parcels import tracking

from .models import (
    Journey,
    JourneyLeg,
    JourneyLegProgress,
    JourneyScheduleChange,
    JourneyScheduleChangeConsent,
)

logger = logging.getLogger(__name__)

Change = JourneyScheduleChange
Consent = JourneyScheduleChangeConsent
Reason = Consent.Reason

#: Journeys whose times may still change: published and not finished.
LIVE_JOURNEY_STATUSES = (Journey.Status.ACTIVE, Journey.Status.IN_PROGRESS)
#: How often a waiting change is looked at again, to catch a parcel that left
#: by a path that does not settle it directly (expiry, delivery, a dispute).
SETTLE_EVERY = timedelta(minutes=30)
REASON_MAX_LENGTH = 500

# Stable machine codes.
NOT_OWNED = "journey_not_owned"
NOT_RESCHEDULABLE = "journey_not_reschedulable"
INVALID = "schedule_change_invalid"
EMPTY = "schedule_change_empty"
ALREADY_PENDING = "schedule_change_pending"
LEG_ARRIVED = "leg_already_arrived"
LEG_DEPARTED = "leg_already_departed"
DEPARTURE_IN_PAST = "leg_departure_in_past"
NOT_FOUND = "schedule_change_not_found"
NOT_PENDING = "schedule_change_not_pending"
NO_ANSWER_NEEDED = "schedule_change_answer_not_needed"


class ScheduleChangeError(RuntimeError):
    def __init__(self, code: str, message: str, *, http_status: int = 409, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.extra = extra

    def as_payload(self) -> dict:
        return {"code": self.code, "detail": self.message, **self.extra}


def _affected_deal_statuses():
    """Deals whose parcel has not been delivered yet, funded or not."""

    from apps.deals.lifecycle import IN_CARRIAGE_STATUSES, PRE_PICKUP_STATUSES
    from apps.deals.models import Deal

    return (
        Deal.Status.OFFER_ACCEPTED,
        Deal.Status.PAYMENT_REQUIRED,
        *PRE_PICKUP_STATUSES,
        *IN_CARRIAGE_STATUSES,
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse(raw) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    parsed = parse_datetime(raw)
    if parsed is None or timezone.is_naive(parsed):
        return None
    return parsed


# --- the schedule ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LegTimes:
    """One leg of a schedule: what the time rules need, nothing else."""

    leg_id: int
    position: int
    depart_at: datetime
    arrive_at: datetime | None

    def as_dict(self) -> dict:
        return {
            "leg_id": self.leg_id,
            "position": self.position,
            "depart_at": _iso(self.depart_at),
            "arrive_at": _iso(self.arrive_at),
        }

    @classmethod
    def of(cls, leg: JourneyLeg) -> "LegTimes":
        return cls(leg.pk, int(leg.position), leg.depart_at, leg.arrive_at)


def _schedule(legs: list[JourneyLeg]) -> list[LegTimes]:
    return [LegTimes.of(leg) for leg in legs]


def _stored(rows: list[dict]) -> dict[int, LegTimes]:
    return {
        int(row["leg_id"]): LegTimes(
            int(row["leg_id"]),
            int(row["position"]),
            _parse(row["depart_at"]),
            _parse(row["arrive_at"]),
        )
        for row in rows
    }


def _ordered_legs(journey_id: int, *, lock: bool) -> list[JourneyLeg]:
    queryset = JourneyLeg.objects.filter(journey_id=journey_id)
    if lock:
        queryset = queryset.select_for_update(no_key=True, of=("self",))
    return list(
        queryset.select_related("origin_place", "destination_place").order_by(
            "position", "pk"
        )
    )


def _parse_request(legs: list[JourneyLeg], payload) -> list[LegTimes]:
    """The whole proposed schedule: the request's times over the current ones.

    ``payload`` lists the legs that change, each ``{id, depart_at, arrive_at}``
    with timezone-aware ISO instants. A leg not listed keeps its times.
    """

    if not isinstance(payload, list) or not payload:
        raise ScheduleChangeError(
            INVALID, "List the legs whose times change.", http_status=400
        )
    by_id = {leg.pk: leg for leg in legs}
    proposed: dict[int, LegTimes] = {}
    for index, row in enumerate(payload):
        leg_id = row.get("id") if isinstance(row, dict) else None
        if (
            isinstance(leg_id, bool)
            or not isinstance(leg_id, int)
            or leg_id not in by_id
        ):
            raise ScheduleChangeError(
                INVALID,
                "This leg is not part of the journey.",
                http_status=400,
                index=index,
            )
        if leg_id in proposed:
            raise ScheduleChangeError(
                INVALID, "A leg is listed twice.", http_status=400, index=index
            )
        depart, arrive = _parse(row.get("depart_at")), _parse(row.get("arrive_at"))
        if depart is None or arrive is None:
            raise ScheduleChangeError(
                INVALID,
                "Each leg needs a departure and an arrival, with a time zone.",
                http_status=400,
                index=index,
            )
        proposed[leg_id] = LegTimes(leg_id, int(by_id[leg_id].position), depart, arrive)
    return [proposed.get(leg.pk) or LegTimes.of(leg) for leg in legs]


def _changed_leg_ids(before: list[LegTimes], after: list[LegTimes]) -> set[int]:
    old = {row.leg_id: row for row in before}
    return {
        row.leg_id
        for row in after
        if (row.depart_at, row.arrive_at)
        != (old[row.leg_id].depart_at, old[row.leg_id].arrive_at)
    }


def _check_fits_trip(
    legs: list[JourneyLeg],
    before: list[LegTimes],
    after: list[LegTimes],
    *,
    now: datetime,
    proposing: bool,
) -> None:
    """Refuse times the trip has already lived past, then the time rules.

    A leg reported arrived cannot move; a leg reported departed keeps its
    departure. When proposing, a leg that has not departed must depart in the
    future. The whole chain then has to satisfy the publication time rules.
    """

    from .services import JourneyDomainError, validate_leg_times

    live = {
        (row.leg_id, row.kind)
        for row in JourneyLegProgress.objects.filter(
            leg__in=legs, retracted_at__isnull=True
        )
    }
    old = {row.leg_id: row for row in before}
    for row in after:
        previous = old[row.leg_id]
        if (row.depart_at, row.arrive_at) == (previous.depart_at, previous.arrive_at):
            continue
        if (row.leg_id, JourneyLegProgress.Kind.ARRIVED) in live:
            raise ScheduleChangeError(
                LEG_ARRIVED,
                "A leg you reported arrived cannot change.",
                leg_id=row.leg_id,
            )
        departed = (row.leg_id, JourneyLegProgress.Kind.DEPARTED) in live
        if departed and row.depart_at != previous.depart_at:
            raise ScheduleChangeError(
                LEG_DEPARTED,
                "A leg you reported departed keeps its departure time.",
                leg_id=row.leg_id,
            )
        if proposing and not departed and row.depart_at <= now:
            raise ScheduleChangeError(
                DEPARTURE_IN_PAST,
                "A new departure must be in the future.",
                leg_id=row.leg_id,
            )
    try:
        validate_leg_times(after)
    except JourneyDomainError as exc:
        raise ScheduleChangeError(exc.code, str(exc.message)) from exc


# --- which parcels, and which need an answer ---------------------------------


@dataclass(slots=True)
class ParcelImpact:
    deal: object
    arrival_before: datetime
    arrival_after: datetime
    agreed_arrival: datetime
    pickup_before: datetime
    pickup_after: datetime
    deadline_at: datetime | None
    #: Collected already: the sender is told, never asked, and never holds
    #: the change back (they can no longer cancel).
    informed: bool = False
    reasons: list[str] = field(default_factory=list)

    @property
    def material(self) -> bool:
        return bool(self.reasons)

    def as_dict(self) -> dict:
        return {
            "deal_id": self.deal.pk,
            "tracking_number": tracking.for_deal(self.deal),
            "material": self.material,
            "informed": self.informed,
            "reasons": list(self.reasons),
            "arrival_before": _iso(self.arrival_before),
            "arrival_after": _iso(self.arrival_after),
            "agreed_arrival": _iso(self.agreed_arrival),
            "pickup_before": _iso(self.pickup_before),
            "pickup_after": _iso(self.pickup_after),
            "deadline_at": _iso(self.deadline_at),
        }


def _last_accepted(deal) -> Consent | None:
    """The answer of the latest change this deal's sender accepted that applied."""

    return (
        Consent.objects.filter(
            deal=deal,
            state=Consent.State.ACCEPTED,
            change__status=Change.Status.APPLIED,
        )
        .order_by("-change__applied_at", "-pk")
        .first()
    )


def _agreed_arrival(deal, accepted: Consent | None, *, current: datetime) -> datetime:
    """The drop-off arrival this deal's sender last agreed to.

    The arrival of the latest change they accepted that applied; otherwise the
    drop-off leg's arrival frozen at funding; otherwise, for a deal not funded
    yet, the arrival in force. A change that applied without asking does not
    move it. Comparing with what the sender agreed to, rather than with
    whatever is in force, means a schedule cannot drift a parcel's arrival past
    the threshold in steps that each look small.
    """

    if accepted is not None:
        return accepted.arrival_after
    route = (deal.arrival_snapshot or {}).get("route") or []
    if deal.funded_at is not None and route:
        frozen = _parse(route[-1].get("arrive_at"))
        if frozen is not None:
            return frozen
    return current


def _agreed_pickup(deal, accepted: Consent | None, *, current: datetime) -> datetime:
    """The pickup time this deal's sender last agreed to.

    The pickup of the latest change they accepted that applied; otherwise the
    pickup the match computed when the two agreed; otherwise the one in force.
    """

    if accepted is not None:
        return accepted.pickup_after
    snapshot = getattr(deal.match, "compatibility_snapshot", None) or {}
    agreed = _parse(snapshot.get("pickup_at"))
    return agreed if agreed is not None else current


def classify(
    journey: Journey, before: list[LegTimes], after: list[LegTimes]
) -> list[ParcelImpact]:
    """Every live parcel on a changed leg, with what makes it material.

    For every parcel: the new drop-off arrival is after the deadline (and
    later than agreed), or moved more than the threshold either way from the
    agreed arrival. For a parcel not collected yet, also: the departure from
    its pickup stop moved more than the threshold either way from the agreed
    pickup, or moved earlier to before the deal's agreed pickup time. A
    collected parcel is informed, never material.
    """

    from apps.deals.models import Deal, DealLegAllocation

    changed = _changed_leg_ids(before, after)
    if not changed:
        return []
    shift = timedelta(minutes=marketplace_policy().route_change.material_shift_minutes)
    old = {row.leg_id: row for row in before}
    new = {row.leg_id: row for row in after}
    carrying: dict[int, list[int]] = {}
    for deal_id, leg_id in (
        DealLegAllocation.objects.filter(
            deal__journey=journey,
            deal__status__in=_affected_deal_statuses(),
            status__in=(
                DealLegAllocation.Status.PENDING_PAYMENT,
                DealLegAllocation.Status.FUNDED,
                DealLegAllocation.Status.IN_TRANSIT,
            ),
        )
        .order_by("journey_leg__position", "pk")
        .values_list("deal_id", "journey_leg_id")
    ):
        carrying.setdefault(deal_id, []).append(leg_id)
    deals = {
        deal.pk: deal
        for deal in Deal.objects.filter(pk__in=carrying).select_related(
            "delivery_request", "match"
        )
    }
    impacts = []
    for deal_id in sorted(carrying):
        legs = carrying[deal_id]
        if not changed.intersection(legs):
            continue
        deal = deals[deal_id]
        pickup, dropoff = legs[0], legs[-1]
        arrival_before = old[dropoff].arrive_at or old[dropoff].depart_at
        arrival_after = new[dropoff].arrive_at or new[dropoff].depart_at
        pickup_before, pickup_after = old[pickup].depart_at, new[pickup].depart_at
        accepted = _last_accepted(deal)
        agreed = _agreed_arrival(deal, accepted, current=arrival_before)
        deadline = deal.delivery_request.deadline_at
        impact = ParcelImpact(
            deal,
            arrival_before,
            arrival_after,
            agreed,
            pickup_before,
            pickup_after,
            deadline,
            informed=deal.pickup_confirmed_at is not None,
        )
        impacts.append(impact)
        if impact.informed:
            continue
        if deadline is not None and arrival_after > deadline and arrival_after > agreed:
            impact.reasons.append(Reason.DEADLINE)
        if abs(arrival_after - agreed) > shift:
            impact.reasons.append(Reason.SHIFT)
        agreed_pickup = _agreed_pickup(deal, accepted, current=pickup_before)
        leaves_before_agreed = (
            deal.agreed_pickup_at is not None
            and pickup_after < pickup_before
            and pickup_after < deal.agreed_pickup_at
        )
        if abs(pickup_after - agreed_pickup) > shift or leaves_before_agreed:
            impact.reasons.append(Reason.PICKUP)
    return impacts


# --- proposing ----------------------------------------------------------------


def _lock_live_journey(journey_id: int, actor) -> Journey:
    from .lifecycle import with_lifecycle

    journey = (
        Journey.objects.select_for_update(no_key=True).filter(pk=journey_id).first()
    )
    if journey is None or journey.traveler_id != getattr(actor, "pk", None):
        raise ScheduleChangeError(
            NOT_OWNED, "Only the journey owner can change its times.", http_status=403
        )
    lifecycle = (
        with_lifecycle(Journey.objects.filter(pk=journey.pk))
        .values_list("lifecycle_status", flat=True)
        .first()
    )
    if lifecycle not in LIVE_JOURNEY_STATUSES:
        raise ScheduleChangeError(
            NOT_RESCHEDULABLE,
            "Only an active journey's times can change.",
            status=lifecycle or journey.status,
        )
    return journey


def _reason(text) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        raise ScheduleChangeError(INVALID, "The reason must be text.", http_status=400)
    text = text.strip()
    if len(text) > REASON_MAX_LENGTH:
        raise ScheduleChangeError(
            INVALID,
            f"A reason can be {REASON_MAX_LENGTH} characters at most.",
            http_status=400,
        )
    return text


def preview_change(*, journey_id: int, actor, legs) -> dict:
    """What proposing these times would do, without doing it (the review step)."""

    with transaction.atomic():
        journey = _lock_live_journey(journey_id, actor)
        stored = _ordered_legs(journey.pk, lock=False)
        before = _schedule(stored)
        after = _parse_request(stored, legs)
        if not _changed_leg_ids(before, after):
            raise ScheduleChangeError(EMPTY, "These are the times already in force.")
        _check_fits_trip(stored, before, after, now=timezone.now(), proposing=True)
        impacts = classify(journey, before, after)
        return {
            "journey_id": journey.pk,
            "legs": _legs_view(stored, before, after),
            "parcels": [impact.as_dict() for impact in impacts],
            "applies_at_once": not any(impact.material for impact in impacts),
            "notices": _notices(stored, before, after),
        }


#: Server text the traveler's review step shows, by code.
TICKET_RECHECK = "ticket_recheck"
_NOTICE_TEXT = {
    TICKET_RECHECK: (
        "Your ticket will be checked again. Until staff approve it, this trip "
        "takes no new proposals. Deliveries already paid for continue."
    ),
}


def _notices(
    legs: list[JourneyLeg], before: list[LegTimes], after: list[LegTimes]
) -> list[dict]:
    """What applying these times will set off beyond the times themselves."""

    from .proofs import leg_requires_proof

    changed = _changed_leg_ids(before, after)
    if any(leg.pk in changed and leg_requires_proof(leg) for leg in legs):
        return [{"code": TICKET_RECHECK, "text": _NOTICE_TEXT[TICKET_RECHECK]}]
    return []


@transaction.atomic
def propose_change(*, journey_id: int, actor, legs, reason=None) -> Change:
    """`POST /api/journeys/<id>/schedule-changes`. One waiting change at a time."""

    journey = _lock_live_journey(journey_id, actor)
    pending = Change.objects.filter(
        journey=journey, status=Change.Status.PENDING_SENDERS
    ).first()
    if pending is not None:
        raise ScheduleChangeError(
            ALREADY_PENDING,
            "New times are already waiting for senders. Withdraw them first.",
            schedule_change_id=pending.pk,
        )
    reason = _reason(reason)
    stored = _ordered_legs(journey.pk, lock=True)
    before = _schedule(stored)
    after = _parse_request(stored, legs)
    if not _changed_leg_ids(before, after):
        raise ScheduleChangeError(EMPTY, "These are the times already in force.")
    _check_fits_trip(stored, before, after, now=timezone.now(), proposing=True)
    change = Change.objects.create(
        journey=journey,
        proposed_by=actor,
        reason=reason,
        original=[row.as_dict() for row in before],
        proposed=[row.as_dict() for row in after],
    )
    _settle_locked(change, journey=journey, legs=stored, proposing=True)
    return change


# --- settling: wait, apply or withdraw ---------------------------------------


def _record(deal, kind: str, payload: dict, *, actor_id: int | None) -> None:
    from apps.deals.lifecycle import record_event

    record_event(deal, kind, payload, actor_id=actor_id)


def _publish(
    channel: str, change: Change, *, targets: list[int], key: str, deal=None, **extra
) -> None:
    payload = {
        "journey_id": change.journey_id,
        "schedule_change_id": change.pk,
        **extra,
    }
    if deal is not None:
        payload.update(deal_resources(deal))
        payload["tracking_number"] = tracking.for_deal(deal)
    redis_bus.publish_after_commit(
        channel, payload, targets=targets, idempotency_key=f"{key}:{change.pk}"
    )


def _settle_locked(
    change: Change, *, journey: Journey, legs: list[JourneyLeg], proposing: bool = False
) -> str:
    """Bring a waiting change up to date. Caller holds the journey and leg locks.

    Re-checks that the times still fit the trip, re-classifies the parcels (a
    deal may have been accepted, funded, cancelled or delivered meanwhile),
    asks every newly material parcel's sender, and applies the change when no
    material parcel is left without an acceptance.
    """

    from apps.deals.models import DealEvent

    if change.status != Change.Status.PENDING_SENDERS:
        return change.status
    if journey.status not in LIVE_JOURNEY_STATUSES:
        _withdraw(change, by=Change.WithdrawnBy.NO_LONGER_VALID)
        return "withdrawn"
    before = _schedule(legs)
    after_by_id = _stored(change.proposed)
    if set(after_by_id) != {leg.pk for leg in legs}:
        _withdraw(change, by=Change.WithdrawnBy.NO_LONGER_VALID)
        return "withdrawn"
    after = [after_by_id[leg.pk] for leg in legs]
    try:
        _check_fits_trip(legs, before, after, now=timezone.now(), proposing=False)
    except ScheduleChangeError:
        _withdraw(change, by=Change.WithdrawnBy.NO_LONGER_VALID)
        return "withdrawn"

    impacts = classify(journey, before, after)
    consents = {
        row.deal_id: row
        for row in Consent.objects.select_for_update().filter(change=change)
    }
    waiting = []
    for impact in impacts:
        if not impact.material:
            continue
        consent = consents.get(impact.deal.pk)
        if consent is None:
            consent = Consent.objects.create(
                change=change,
                deal=impact.deal,
                reasons=list(impact.reasons),
                arrival_before=impact.arrival_before,
                arrival_after=impact.arrival_after,
                pickup_before=impact.pickup_before,
                pickup_after=impact.pickup_after,
            )
            consents[impact.deal.pk] = consent
            _record(
                impact.deal,
                DealEvent.Kind.SCHEDULE_CHANGE_PROPOSED,
                _deal_event_payload(change, impact, consent_state=consent.state),
                actor_id=change.proposed_by_id,
            )
            _publish(
                channels.JOURNEY_SCHEDULE_CHANGE_PROPOSED,
                change,
                targets=[impact.deal.sender_id],
                key=f"schedule_change_proposed:{impact.deal.pk}",
                deal=impact.deal,
            )
        if consent.state != Consent.State.ACCEPTED:
            waiting.append(impact.deal.pk)
    change.affected = [impact.as_dict() for impact in impacts]
    if waiting:
        change.save(update_fields=["affected", "updated_at"])
        _schedule_settle(change)
        return "waiting"
    _apply(
        change,
        journey=journey,
        legs=legs,
        before=before,
        after=after,
        impacts=impacts,
        at_once=proposing,
    )
    return "applied"


def _deal_event_payload(
    change: Change, impact: ParcelImpact, *, consent_state: str = ""
) -> dict:
    payload = {
        "schedule_change_id": change.pk,
        "material": impact.material,
        "informed": impact.informed,
        "material_reasons": list(impact.reasons),
        "arrival_before": _iso(impact.arrival_before),
        "arrival_after": _iso(impact.arrival_after),
    }
    if consent_state:
        payload["consent_state"] = consent_state
    return payload


def _apply(
    change: Change,
    *,
    journey: Journey,
    legs: list[JourneyLeg],
    before: list[LegTimes],
    after: list[LegTimes],
    impacts: list[ParcelImpact],
    at_once: bool,
) -> None:
    from apps.deals.models import DealEvent

    from .progress import schedule_leg_reminders
    from .proofs import leg_requires_proof
    from .services import _invalidate_leg_proofs

    new = {row.leg_id: row for row in after}
    old = {row.leg_id: row for row in before}
    for leg in legs:
        times = new[leg.pk]
        changed = [
            name
            for name in ("depart_at", "arrive_at")
            if getattr(times, name) != getattr(old[leg.pk], name)
        ]
        if not changed:
            continue
        leg.depart_at, leg.arrive_at = times.depart_at, times.arrive_at
        leg.save(update_fields=["depart_at", "arrive_at", "updated_at"])
        # A ticket evidences a departure and an arrival: a re-timed ticket
        # leg goes back to staff review, exactly as a route edit sends it.
        if leg_requires_proof(leg):
            _invalidate_leg_proofs(leg, changed_fields=changed)
    change.status = Change.Status.APPLIED
    change.applied_at = timezone.now()
    change.save(update_fields=["status", "applied_at", "affected", "updated_at"])
    # The old reminder jobs find their planned time moved and do nothing; the
    # new times need their own (L5A's carry-over).
    schedule_leg_reminders(journey)
    for impact in impacts:
        _record(
            impact.deal,
            DealEvent.Kind.SCHEDULE_CHANGE_APPLIED,
            _deal_event_payload(change, impact),
            actor_id=change.proposed_by_id,
        )
        _publish(
            channels.JOURNEY_SCHEDULE_CHANGE_APPLIED,
            change,
            targets=[impact.deal.sender_id],
            key=f"schedule_change_applied:{impact.deal.pk}",
            deal=impact.deal,
        )
    if not at_once:
        # The traveler proposed and waited; tell them it is in force.
        _publish(
            channels.JOURNEY_SCHEDULE_CHANGE_APPLIED,
            change,
            targets=[journey.traveler_id],
            key="schedule_change_applied:traveler",
        )


def _withdraw(change: Change, *, by: str) -> None:
    from apps.deals.models import DealEvent

    change.status = Change.Status.WITHDRAWN
    change.withdrawn_at = timezone.now()
    change.withdrawn_by = by
    change.save(update_fields=["status", "withdrawn_at", "withdrawn_by", "updated_at"])
    for consent in (
        Consent.objects.filter(change=change).select_related("deal").order_by("pk")
    ):
        deal = consent.deal
        _record(
            deal,
            DealEvent.Kind.SCHEDULE_CHANGE_WITHDRAWN,
            {
                "schedule_change_id": change.pk,
                "consent_state": consent.state,
                "reason": by,
            },
            actor_id=change.proposed_by_id
            if by == Change.WithdrawnBy.TRAVELER
            else None,
        )
        _publish(
            channels.JOURNEY_SCHEDULE_CHANGE_WITHDRAWN,
            change,
            targets=[deal.sender_id],
            key=f"schedule_change_withdrawn:{deal.pk}",
            deal=deal,
        )
    if by == Change.WithdrawnBy.NO_LONGER_VALID:
        _publish(
            channels.JOURNEY_SCHEDULE_CHANGE_WITHDRAWN,
            change,
            targets=[change.journey.traveler_id],
            key="schedule_change_withdrawn:traveler",
        )


def _schedule_settle(change: Change) -> None:
    from apps.finance.models import ScheduledJob
    from apps.finance.services import schedule_job

    run_at = timezone.now() + SETTLE_EVERY
    schedule_job(
        kind=ScheduledJob.Kind.SCHEDULE_CHANGE_SETTLE,
        key=f"schedule_change_settle:{change.pk}:{int(run_at.timestamp()) // 60}",
        run_at=run_at,
        payload={"schedule_change_id": change.pk},
    )


def _lock_change(change_id: int) -> tuple[Change, Journey, list[JourneyLeg]] | None:
    """Lock a change in the canonical order: journey, change, legs."""

    journey_id = (
        Change.objects.filter(pk=change_id).values_list("journey_id", flat=True).first()
    )
    if journey_id is None:
        return None
    journey = Journey.objects.select_for_update(no_key=True).get(pk=journey_id)
    change = (
        Change.objects.select_for_update(of=("self",))
        .select_related("journey")
        .get(pk=change_id)
    )
    return change, journey, _ordered_legs(journey.pk, lock=True)


def settle(change_id: int) -> str:
    with transaction.atomic():
        locked = _lock_change(change_id)
        if locked is None:
            return "change_gone"
        change, journey, legs = locked
        return _settle_locked(change, journey=journey, legs=legs)


def settle_for_journey(journey_id: int) -> None:
    """Settle the journey's waiting change, if any. Used after a deal closes."""

    pending = (
        Change.objects.filter(
            journey_id=journey_id, status=Change.Status.PENDING_SENDERS
        )
        .values_list("pk", flat=True)
        .first()
    )
    if pending is not None:
        settle(pending)


def settle_after_commit(journey_id: int) -> None:
    """Settle once the caller's transaction commits; the job catches a failure."""

    def run() -> None:
        try:
            settle_for_journey(journey_id)
        except Exception:  # noqa: BLE001 - the periodic settle job retries
            logger.exception("schedule_changes.settle_failed journey=%s", journey_id)

    transaction.on_commit(run)


def handle_settle_job(payload: dict) -> str:
    """`ScheduledJob` handler. Re-reads everything; reschedules itself while waiting."""

    from apps.finance.jobs import PermanentJobError

    change_id = payload.get("schedule_change_id")
    if isinstance(change_id, bool) or not isinstance(change_id, int):
        raise PermanentJobError(
            "schedule_change_settle needs schedule_change_id.", code="invalid_payload"
        )
    return settle(change_id)


# --- answering and withdrawing -----------------------------------------------


def _sender_deal(deal_id: int, actor):
    from apps.deals.models import Deal

    deal = Deal.objects.filter(pk=deal_id, sender_id=getattr(actor, "pk", None)).first()
    if deal is None:
        raise ScheduleChangeError(NOT_FOUND, "No such delivery.", http_status=404)
    return deal


def decide(*, deal_id: int, actor, accept: bool) -> Consent:
    """The sender accepts or declines new times for their parcel.

    An answer can be changed while the change waits. Accepting the last answer
    it waited for applies it in the same transaction.
    """

    from apps.deals.models import DealEvent

    deal = _sender_deal(deal_id, actor)
    with transaction.atomic():
        journey = Journey.objects.select_for_update(no_key=True).get(pk=deal.journey_id)
        change = (
            Change.objects.select_for_update()
            .filter(journey=journey, status=Change.Status.PENDING_SENDERS)
            .first()
        )
        consent = (
            Consent.objects.select_for_update()
            .filter(change=change, deal_id=deal.pk)
            .first()
            if change is not None
            else None
        )
        if consent is None:
            raise ScheduleChangeError(
                NO_ANSWER_NEEDED, "Nothing is waiting for your answer."
            )
        deal.refresh_from_db()
        # A collected parcel is informed, not asked: its answer no longer holds
        # the change back, and its sender can no longer cancel.
        if deal.status not in _affected_deal_statuses() or deal.pickup_confirmed_at:
            raise ScheduleChangeError(
                NO_ANSWER_NEEDED,
                "This delivery no longer needs an answer.",
                deal_status=deal.status,
            )
        state = Consent.State.ACCEPTED if accept else Consent.State.DECLINED
        if consent.state == state:
            return consent
        consent.state = state
        consent.decided_at = timezone.now()
        consent.save(update_fields=["state", "decided_at", "updated_at"])
        _record(
            deal,
            DealEvent.Kind.SCHEDULE_CHANGE_ACCEPTED
            if accept
            else DealEvent.Kind.SCHEDULE_CHANGE_DECLINED,
            {
                "schedule_change_id": change.pk,
                "consent_state": state,
                "arrival_before": _iso(consent.arrival_before),
                "arrival_after": _iso(consent.arrival_after),
            },
            actor_id=actor.pk,
        )
        _publish(
            channels.JOURNEY_SCHEDULE_CHANGE_ANSWERED,
            change,
            targets=[journey.traveler_id],
            key=f"schedule_change_answered:{deal.pk}:{state}:{int(consent.decided_at.timestamp())}",
            deal=deal,
            consent_state=state,
        )
        if accept:
            _settle_locked(
                change, journey=journey, legs=_ordered_legs(journey.pk, lock=True)
            )
        consent.refresh_from_db()
        return consent


def withdraw(*, journey_id: int, change_id: int, actor) -> Change:
    """The traveler takes a waiting change back; the times stay as they are."""

    with transaction.atomic():
        journey = (
            Journey.objects.select_for_update(no_key=True).filter(pk=journey_id).first()
        )
        if journey is None or journey.traveler_id != getattr(actor, "pk", None):
            raise ScheduleChangeError(
                NOT_OWNED, "Only the journey owner can withdraw it.", http_status=403
            )
        change = (
            Change.objects.select_for_update(of=("self",))
            .select_related("journey")
            .filter(pk=change_id, journey=journey)
            .first()
        )
        if change is None:
            raise ScheduleChangeError(
                NOT_FOUND, "No such schedule change.", http_status=404
            )
        if change.status == Change.Status.WITHDRAWN:
            return change
        if change.status != Change.Status.PENDING_SENDERS:
            raise ScheduleChangeError(NOT_PENDING, "These times are already in force.")
        _withdraw(change, by=Change.WithdrawnBy.TRAVELER)
        return change


def declined_change_for(deal) -> Change | None:
    """The waiting change this deal's sender declined, if any.

    While it exists, the sender's cancellation is caused by the traveler
    (spec 12, Ismail 2026-11-11). Read under the journey lock the
    cancellation already holds.
    """

    consent = (
        Consent.objects.filter(
            deal=deal,
            state=Consent.State.DECLINED,
            change__status=Change.Status.PENDING_SENDERS,
        )
        .select_related("change")
        .first()
    )
    return consent.change if consent is not None else None


# --- reading -------------------------------------------------------------------


def _legs_view(
    legs: list[JourneyLeg], before: list[LegTimes], after: list[LegTimes]
) -> list[dict]:
    old = {row.leg_id: row for row in before}
    new = {row.leg_id: row for row in after}
    return [
        {
            "leg_id": leg.pk,
            "position": leg.position,
            "mode": leg.mode,
            "origin_name": leg.origin_place.name if leg.origin_place else "",
            "destination_name": leg.destination_place.name
            if leg.destination_place
            else "",
            "depart_at_before": _iso(old[leg.pk].depart_at),
            "arrive_at_before": _iso(old[leg.pk].arrive_at),
            "depart_at_after": _iso(new[leg.pk].depart_at),
            "arrive_at_after": _iso(new[leg.pk].arrive_at),
            "changed": (old[leg.pk].depart_at, old[leg.pk].arrive_at)
            != (new[leg.pk].depart_at, new[leg.pk].arrive_at),
        }
        for leg in legs
        if leg.pk in old and leg.pk in new
    ]


def change_view(change: Change, *, legs: list[JourneyLeg] | None = None) -> dict:
    """A change as its traveler sees it: every leg and every affected parcel."""

    legs = legs if legs is not None else _ordered_legs(change.journey_id, lock=False)
    original = _stored(change.original)
    proposed = _stored(change.proposed)
    before = [original[leg.pk] for leg in legs if leg.pk in original]
    after = [proposed[leg.pk] for leg in legs if leg.pk in proposed]
    consents = {row.deal_id: row.state for row in change.consents.all()}
    parcels = []
    for row in change.affected or []:
        parcels.append(
            {
                "deal_id": row["deal_id"],
                "tracking_number": row["tracking_number"],
                "material": row["material"],
                "informed": row["informed"],
                "reasons": row["reasons"],
                "arrival_before": row["arrival_before"],
                "arrival_after": row["arrival_after"],
                "pickup_before": row["pickup_before"],
                "pickup_after": row["pickup_after"],
                "consent_state": consents.get(row["deal_id"], ""),
            }
        )
    return {
        "id": change.pk,
        "journey_id": change.journey_id,
        "status": change.status,
        "reason": change.reason,
        "created_at": change.created_at,
        "applied_at": change.applied_at,
        "withdrawn_at": change.withdrawn_at,
        "withdrawn_by": change.withdrawn_by,
        "legs": _legs_view(legs, before, after),
        "parcels": parcels,
        "waiting_for": sum(
            1
            for row in parcels
            if row["material"] and row["consent_state"] != Consent.State.ACCEPTED
        ),
    }


def journey_changes(journey: Journey) -> list[dict]:
    legs = _ordered_legs(journey.pk, lock=False)
    return [
        change_view(change, legs=legs)
        for change in Change.objects.filter(journey=journey)
        .prefetch_related("consents")
        .order_by("-created_at", "-pk")
    ]


def _collected_actions(deal) -> list[str]:
    """What a sender whose parcel is collected can do about new times: what exists today."""

    from apps.deals.lifecycle import IN_CARRIAGE_STATUSES

    return (
        ["report_problem", "open_dispute"]
        if deal.status in IN_CARRIAGE_STATUSES
        else []
    )


def sender_view(deal) -> dict:
    """`GET /api/deals/<id>/schedule-change` for the sender of ``deal``.

    The latest change that touched this parcel, its old and new times for the
    parcel's own legs, and whether an answer is wanted. Only this parcel's
    legs: the traveler's other legs are not the sender's business.
    """

    from apps.deals.models import DealLegAllocation

    change = (
        Change.objects.filter(
            journey_id=deal.journey_id, affected__contains=[{"deal_id": deal.pk}]
        )
        .order_by("-created_at", "-pk")
        .first()
    )
    if change is None:
        return {
            "deal_id": deal.pk,
            "tracking_number": tracking.for_deal(deal),
            "change": None,
        }
    leg_ids = set(
        DealLegAllocation.objects.filter(deal=deal).values_list(
            "journey_leg_id", flat=True
        )
    )
    legs = [
        leg for leg in _ordered_legs(deal.journey_id, lock=False) if leg.pk in leg_ids
    ]
    original = _stored(change.original)
    proposed = _stored(change.proposed)
    row = next(item for item in change.affected if item["deal_id"] == deal.pk)
    consent = Consent.objects.filter(change=change, deal=deal).first()
    state = consent.state if consent is not None else ""
    collected = deal.pickup_confirmed_at is not None
    return {
        "deal_id": deal.pk,
        "tracking_number": tracking.for_deal(deal),
        "change": {
            "id": change.pk,
            "status": change.status,
            "reason": change.reason,
            "created_at": change.created_at,
            "applied_at": change.applied_at,
            "withdrawn_at": change.withdrawn_at,
            "material": row["material"],
            "informed": row["informed"] or collected,
            "reasons": row["reasons"],
            "arrival_before": row["arrival_before"],
            "arrival_after": row["arrival_after"],
            "pickup_before": row["pickup_before"],
            "pickup_after": row["pickup_after"],
            "deadline_at": row["deadline_at"],
            "consent_state": state,
            "can_answer": change.status == Change.Status.PENDING_SENDERS
            and consent is not None
            and not collected
            and deal.status in _affected_deal_statuses(),
            "actions": _collected_actions(deal) if collected else [],
            "legs": _legs_view(
                legs,
                [original[leg.pk] for leg in legs if leg.pk in original],
                [proposed[leg.pk] for leg in legs if leg.pk in proposed],
            ),
        },
    }
