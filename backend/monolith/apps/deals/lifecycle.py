"""The V1 Deal state machine.

Every Phase 4 transition lives here, and nothing outside this module writes a
lifecycle field on a `Deal`. Views and serializers call services; services call
these functions; these functions write the column, append the immutable timeline
event and arm the durable obligation that carries the Deal forward.

The canonical progression is::

    offer_accepted -> payment_required -> funded -> pickup_ready -> picked_up
    -> in_transit -> delivery_ready -> delivery_confirmed -> protection_window
    -> completed

with `cancelled`, `expired`, `payment_failed`, `disputed`, `refunded` and
`partially_refunded` as side or terminal states.

Three rules hold throughout:

* **Callers arrive holding the lock.** Each `apply_*` takes an already-locked
  `LockedLifecycleAggregate` from `apps.core.financial_locks`. Acquiring locks
  here would let two callers take them in two orders.
* **Transitions are idempotent.** A second call for a transition that already
  happened returns `changed=False` rather than appending a second event, moving
  a deadline or re-arming a job. That is what makes a replayed webhook, a
  duplicated ScheduledJob and a retried client request all safe.
* **Deadlines come from the Deal's frozen policy, never from live settings.**
  `Deal.lifecycle_policy` is snapshotted once, at funding.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.utils import timezone

from apps.core import channels, redis_bus
from apps.core.event_resources import deal_resources
from apps.core.financial_locks import LockedLifecycleAggregate

from .models import Deal, DealEvent, DealLegAllocation

logger = logging.getLogger(__name__)


class DealLifecycleError(RuntimeError):
    """A transition was requested from a state that does not allow it."""

    code = "deal_lifecycle_error"

    def __init__(self, message: str, *, code: str | None = None, **details):
        super().__init__(message)
        if code:
            self.code = code
        self._details = details

    def details(self) -> dict:
        return dict(self._details)


@dataclass(frozen=True, slots=True)
class TransitionResult:
    deal_id: int
    status: str
    changed: bool


#: Statuses in which the parcel is still with the sender and a cancellation is
#: therefore still a commercial decision rather than a dispute.
PRE_PICKUP_STATUSES = (
    Deal.Status.FUNDED,
    Deal.Status.PICKUP_READY,
)
#: Statuses in which the traveler is carrying the parcel.
IN_CARRIAGE_STATUSES = (
    Deal.Status.PICKED_UP,
    Deal.Status.IN_TRANSIT,
    Deal.Status.DELIVERY_READY,
)
#: Statuses after a confirmed delivery, before the Deal is closed out.
POST_DELIVERY_STATUSES = (
    Deal.Status.DELIVERY_CONFIRMED,
    Deal.Status.PROTECTION_WINDOW,
    Deal.Status.DISPUTED,
)


# --- timeline ----------------------------------------------------------------


def record_event(
    deal: Deal,
    kind: str,
    payload: dict | None = None,
    *,
    actor_id: int | None = None,
) -> DealEvent:
    """Append one immutable timeline row.

    Payloads carry ids, amounts and statuses. They never carry a handover code
    in any form, and never recipient contact details: the timeline is read by
    both parties and by admins, and a secret in it would be a secret everywhere.
    """

    return DealEvent.objects.create(
        deal=deal, kind=kind, payload=payload or {}, actor_id=actor_id
    )


def _set_status(
    deal: Deal,
    status: str,
    *,
    reason: str,
    actor_id: int | None = None,
    extra_fields: list[str] | None = None,
    payload: dict | None = None,
) -> None:
    deal.status = status
    deal.save(update_fields=["status", "updated_at", *(extra_fields or [])])
    record_event(
        deal,
        DealEvent.Kind.STATUS_CHANGED,
        {"status": status, "reason": reason, **(payload or {})},
        actor_id=actor_id,
    )


# --- policy snapshot ----------------------------------------------------------


def lifecycle_value(deal: Deal, key: str, default: int) -> int:
    """Read one duration from the Deal's frozen policy.

    A Deal funded before Phase 4 shipped has an empty snapshot. Falling back to
    the documented default is the conservative answer: it keeps the 30-minute
    buffer and the 48-hour protection window in force rather than treating an
    old row as having no safety rules at all.
    """

    value = (deal.lifecycle_policy or {}).get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return default
    return value


def delivery_code_buffer(deal: Deal) -> timedelta:
    return timedelta(
        seconds=lifecycle_value(deal, "delivery_code_buffer_seconds", 1_800)
    )


def protection_window(deal: Deal) -> timedelta:
    return timedelta(seconds=lifecycle_value(deal, "protection_window_seconds", 172_800))


def rating_window(deal: Deal) -> timedelta:
    return timedelta(
        seconds=lifecycle_value(deal, "rating_review_window_seconds", 1_209_600)
    )


# --- funding ------------------------------------------------------------------


def snapshot_on_funding(deal: Deal, *, agreed_pickup_at: datetime | None) -> None:
    """Freeze the Deal's remaining timeline rules at the moment money lands.

    Called from `fund_deal`, inside the funding transaction. After this the Deal
    stops reading live business settings: a revision published tomorrow cannot
    shorten today's safety buffer, move today's protection deadline or change
    the cancellation compensation a party has already been quoted.
    """

    from apps.core.business_settings import NoActiveBusinessSettings
    from apps.core.phase4_policy import InvalidPhase4Policy, phase4_policy

    try:
        deal.lifecycle_policy = phase4_policy().lifecycle_snapshot()
    except (InvalidPhase4Policy, NoActiveBusinessSettings):
        # A settings revision without Phase 4 policy can still fund a Deal --
        # payments are a Phase 3 concern. The Deal then runs on the documented
        # defaults in `lifecycle_value`, and every Phase 4 endpoint refuses
        # until an operator activates a Phase 4 revision.
        logger.warning(
            "deals.lifecycle_policy_unavailable deal=%s; defaults apply", deal.pk
        )
        deal.lifecycle_policy = {}
    deal.agreed_pickup_at = agreed_pickup_at


def resolve_agreed_pickup_at(*, deal: Deal, match, journey_legs) -> datetime | None:
    """The instant the cancellation cutoff is measured against.

    Preference order, most specific first: the server's own interpolated pickup
    instant from the compatibility snapshot, the sender's declared ready-window
    start, then the matched start leg's departure. All three are server-computed;
    none of them is client-supplied.
    """

    snapshot = getattr(match, "compatibility_snapshot", None) or {}
    raw = snapshot.get("pickup_at")
    if isinstance(raw, str) and raw:
        parsed = _parse_instant(raw)
        if parsed is not None:
            return parsed
    ready_start = getattr(deal.delivery_request, "ready_window_start", None)
    if ready_start is not None:
        return ready_start
    start_leg_id = getattr(match, "start_leg_id", None)
    for leg in journey_legs:
        if leg.pk == start_leg_id:
            return leg.depart_at
    return None


def _parse_instant(raw: str) -> datetime | None:
    from django.utils.dateparse import parse_datetime

    parsed = parse_datetime(raw)
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_default_timezone())
    return parsed


def apply_pickup_ready(
    aggregate: LockedLifecycleAggregate, *, actor_id: int | None = None
) -> TransitionResult:
    """`funded` -> `pickup_ready` once the recipient is on file.

    The recipient is required before pickup because the delivery-code
    notification has nowhere to go without them, and discovering that 30 minutes
    after the parcel has left the sender's hands is too late to fix.
    """

    deal = aggregate.deal
    if deal.status == Deal.Status.PICKUP_READY:
        return TransitionResult(deal.pk, deal.status, False)
    if deal.status != Deal.Status.FUNDED:
        return TransitionResult(deal.pk, deal.status, False)
    if aggregate.recipient is None:
        return TransitionResult(deal.pk, deal.status, False)
    _set_status(
        deal,
        Deal.Status.PICKUP_READY,
        reason="recipient_recorded",
        actor_id=actor_id,
    )
    return TransitionResult(deal.pk, deal.status, True)


# --- handover -----------------------------------------------------------------


def apply_pickup_confirmed(
    aggregate: LockedLifecycleAggregate,
    *,
    actor_id: int,
    at: datetime | None = None,
) -> TransitionResult:
    """A verified pickup code moves the Deal into carriage and starts the buffer.

    Two timeline entries are appended, not one: `picked_up` is the physical fact
    and `in_transit` is the state the parcel is then in. The Deal settles on
    `in_transit`, which is what the traveler's app and the capacity allocations
    both mean by "carrying".

    This is also where the 30-minute obligation is created. The window start is
    stored (`delivery_code_available_at`), so the buffer is a fact about this
    Deal rather than a fact about whichever process happens to look at it.
    """

    deal = aggregate.deal
    if deal.pickup_confirmed_at is not None:
        return TransitionResult(deal.pk, deal.status, False)
    if deal.status not in PRE_PICKUP_STATUSES:
        raise DealLifecycleError(
            "Pickup can only be confirmed on a funded deal that is ready for pickup.",
            code="deal_not_pickup_ready",
            deal_status=deal.status,
        )
    at = at or timezone.now()
    deal.pickup_confirmed_at = at
    deal.delivery_code_available_at = at + delivery_code_buffer(deal)
    deal.status = Deal.Status.PICKED_UP
    deal.save(
        update_fields=[
            "status",
            "pickup_confirmed_at",
            "delivery_code_available_at",
            "updated_at",
        ]
    )
    record_event(
        deal,
        DealEvent.Kind.PICKUP_CONFIRMED,
        {"pickup_confirmed_at": at.isoformat()},
        actor_id=actor_id,
    )
    record_event(
        deal,
        DealEvent.Kind.DELIVERY_BUFFER_STARTED,
        {
            "delivery_code_available_at": deal.delivery_code_available_at.isoformat(),
            "buffer_seconds": lifecycle_value(
                deal, "delivery_code_buffer_seconds", 1_800
            ),
        },
    )
    _set_status(
        deal,
        Deal.Status.IN_TRANSIT,
        reason="pickup_confirmed",
        actor_id=actor_id,
    )

    allocation_ids = [
        row.pk
        for row in aggregate.deal_aggregate.allocations
        if row.status == DealLegAllocation.Status.FUNDED
    ]
    if allocation_ids:
        DealLegAllocation.objects.filter(pk__in=allocation_ids).update(
            status=DealLegAllocation.Status.IN_TRANSIT
        )
    return TransitionResult(deal.pk, deal.status, True)


def apply_delivery_code_released(
    aggregate: LockedLifecycleAggregate, *, at: datetime | None = None
) -> TransitionResult:
    """The safety buffer has elapsed: `in_transit` -> `delivery_ready`.

    Refuses early. The comparison is against the stored
    `delivery_code_available_at`, under the Deal row lock, so neither a job that
    fires early nor a clock that drifts can shorten the window.
    """

    deal = aggregate.deal
    if deal.delivery_code_released_at is not None:
        return TransitionResult(deal.pk, deal.status, False)
    if deal.pickup_confirmed_at is None or deal.delivery_code_available_at is None:
        raise DealLifecycleError(
            "The delivery code cannot be released before pickup is confirmed.",
            code="pickup_not_confirmed",
            deal_status=deal.status,
        )
    at = at or timezone.now()
    if at < deal.delivery_code_available_at:
        raise DealLifecycleError(
            "The delivery-code safety window has not elapsed.",
            code="delivery_code_buffer_open",
            delivery_code_available_at=deal.delivery_code_available_at.isoformat(),
        )
    if deal.status not in IN_CARRIAGE_STATUSES:
        raise DealLifecycleError(
            "This deal is no longer in carriage.",
            code="deal_not_in_transit",
            deal_status=deal.status,
        )
    deal.delivery_code_released_at = at
    deal.status = Deal.Status.DELIVERY_READY
    deal.save(
        update_fields=["status", "delivery_code_released_at", "updated_at"]
    )
    record_event(
        deal,
        DealEvent.Kind.DELIVERY_CODE_RELEASED,
        {"released_at": at.isoformat()},
    )
    record_event(
        deal,
        DealEvent.Kind.STATUS_CHANGED,
        {"status": deal.status, "reason": "delivery_code_released"},
    )
    return TransitionResult(deal.pk, deal.status, True)


def apply_delivery_confirmed(
    aggregate: LockedLifecycleAggregate,
    *,
    actor_id: int,
    at: datetime | None = None,
) -> TransitionResult:
    """A verified delivery code closes carriage and opens payment protection.

    The protection deadline is computed once and stored. Everything downstream
    -- the payout gate, the dispute window, the client countdown -- reads that
    column rather than recomputing from a duration, so they cannot disagree.
    """

    deal = aggregate.deal
    if deal.delivery_confirmed_at is not None:
        return TransitionResult(deal.pk, deal.status, False)
    if deal.status != Deal.Status.DELIVERY_READY:
        raise DealLifecycleError(
            "Delivery can only be confirmed once the delivery code is released.",
            code="deal_not_delivery_ready",
            deal_status=deal.status,
        )
    at = at or timezone.now()
    deal.delivery_confirmed_at = at
    deal.protection_ends_at = at + protection_window(deal)
    deal.rating_window_ends_at = at + rating_window(deal)
    deal.status = Deal.Status.DELIVERY_CONFIRMED
    deal.save(
        update_fields=[
            "status",
            "delivery_confirmed_at",
            "protection_ends_at",
            "rating_window_ends_at",
            "updated_at",
        ]
    )
    record_event(
        deal,
        DealEvent.Kind.DELIVERY_CONFIRMED,
        {"delivery_confirmed_at": at.isoformat()},
        actor_id=actor_id,
    )
    _set_status(
        deal,
        Deal.Status.PROTECTION_WINDOW,
        reason="delivery_confirmed",
        actor_id=actor_id,
    )
    record_event(
        deal,
        DealEvent.Kind.PROTECTION_STARTED,
        {
            "protection_ends_at": deal.protection_ends_at.isoformat(),
            "protection_window_seconds": lifecycle_value(
                deal, "protection_window_seconds", 172_800
            ),
        },
    )

    allocation_ids = [
        row.pk
        for row in aggregate.deal_aggregate.allocations
        if row.status
        in (DealLegAllocation.Status.IN_TRANSIT, DealLegAllocation.Status.FUNDED)
    ]
    if allocation_ids:
        DealLegAllocation.objects.filter(pk__in=allocation_ids).update(
            status=DealLegAllocation.Status.COMPLETED
        )
    return TransitionResult(deal.pk, deal.status, True)


def apply_completed(
    aggregate: LockedLifecycleAggregate,
    *,
    reason: str,
    at: datetime | None = None,
) -> TransitionResult:
    """Close the delivery contract.

    Reached when the protection window expires with no dispute, or when a
    dispute resolves in the traveler's favour. The traveler's payout has its own
    lifecycle from here -- eligible, scheduled, paid -- and its states are
    recorded on this timeline as `payout_status_changed` events. Holding the
    Deal open until an operator's bank transfer clears would misreport a
    finished delivery as unfinished for days.
    """

    deal = aggregate.deal
    if deal.status == Deal.Status.COMPLETED:
        return TransitionResult(deal.pk, deal.status, False)
    if deal.delivery_confirmed_at is None:
        raise DealLifecycleError(
            "A deal cannot complete without a confirmed delivery.",
            code="delivery_not_confirmed",
            deal_status=deal.status,
        )
    at = at or timezone.now()
    deal.completed_at = at
    _set_status(
        deal,
        Deal.Status.COMPLETED,
        reason=reason,
        extra_fields=["completed_at"],
    )
    redis_bus.publish_after_commit(
        channels.MATCH_COMPLETED,
        deal_resources(deal),
        targets=[deal.sender_id, deal.traveler_id],
    )
    return TransitionResult(deal.pk, deal.status, True)


# --- durable obligations ------------------------------------------------------


def schedule_delivery_code_release(deal: Deal) -> None:
    from apps.finance.models import ScheduledJob
    from apps.finance.services import schedule_job

    if deal.delivery_code_available_at is None:
        raise DealLifecycleError(
            "Cannot schedule a release without an availability instant.",
            code="delivery_code_not_armed",
        )
    schedule_job(
        kind=ScheduledJob.Kind.DELIVERY_CODE_RELEASE,
        key=f"delivery_code_release:{deal.pk}",
        run_at=deal.delivery_code_available_at,
        payload={"deal_id": deal.pk},
        max_attempts=24,
    )


def schedule_protection_expiry(deal: Deal) -> None:
    from apps.finance.models import ScheduledJob
    from apps.finance.services import schedule_job

    if deal.protection_ends_at is None:
        raise DealLifecycleError(
            "Cannot schedule protection expiry without a deadline.",
            code="protection_not_armed",
        )
    schedule_job(
        kind=ScheduledJob.Kind.PROTECTION_EXPIRY,
        key=f"protection_expiry:{deal.pk}",
        run_at=deal.protection_ends_at,
        payload={"deal_id": deal.pk},
        max_attempts=24,
    )


def schedule_rating_reveal(deal: Deal) -> None:
    from apps.finance.models import ScheduledJob
    from apps.finance.services import schedule_job

    if deal.rating_window_ends_at is None:
        return
    schedule_job(
        kind=ScheduledJob.Kind.RATING_REVEAL,
        key=f"rating_reveal:{deal.pk}",
        run_at=deal.rating_window_ends_at,
        payload={"deal_id": deal.pk},
        max_attempts=12,
    )


# --- disputes -----------------------------------------------------------------


#: Terminal statuses an administrator's dispute resolution may land on.
DISPUTE_RESOLUTION_STATUSES = (
    Deal.Status.COMPLETED,
    Deal.Status.REFUNDED,
    Deal.Status.PARTIALLY_REFUNDED,
)


def apply_disputed(
    aggregate: LockedLifecycleAggregate,
    *,
    dispute_id: int,
    actor_id: int | None = None,
    at: datetime | None = None,
) -> TransitionResult:
    """Mark the Deal disputed, remembering what it was doing beforehand.

    `disputed` is a side state, not a step forward: the parcel may be in
    carriage or already delivered and inside its protection window. The previous
    status is written into the timeline event because the resolution has to know
    whether a delivery was ever confirmed, and a status column can only hold one
    answer at a time.

    Idempotent. A second dispute-open call on an already disputed Deal appends
    nothing.
    """

    deal = aggregate.deal
    if deal.status == Deal.Status.DISPUTED:
        return TransitionResult(deal.pk, deal.status, False)
    if deal.status in (
        Deal.Status.CANCELLED,
        Deal.Status.EXPIRED,
        Deal.Status.REFUNDED,
        Deal.Status.PARTIALLY_REFUNDED,
        Deal.Status.PAYMENT_FAILED,
    ):
        raise DealLifecycleError(
            "This delivery is already closed and cannot be disputed.",
            code="deal_closed",
            deal_status=deal.status,
        )
    previous = deal.status
    _set_status(
        deal,
        Deal.Status.DISPUTED,
        reason="dispute_opened",
        actor_id=actor_id,
        payload={"dispute_id": dispute_id, "previous_status": previous},
    )
    return TransitionResult(deal.pk, deal.status, True)


def apply_dispute_resolved(
    aggregate: LockedLifecycleAggregate,
    *,
    status: str,
    reason: str,
    dispute_id: int,
    actor_id: int | None = None,
    at: datetime | None = None,
) -> TransitionResult:
    """Close a disputed Deal on the terminal status the resolution implies.

    This is the one path to `completed` that does not require a confirmed
    delivery. A dispute opened while the parcel was still in carriage can be
    decided in the traveler's favour -- the platform has ruled that they
    performed -- and reporting that Deal as anything other than completed would
    misstate the outcome. `apply_completed` keeps its own stricter rule for the
    ordinary protection-window path, where a missing delivery confirmation is a
    bug rather than a decision.
    """

    if status not in DISPUTE_RESOLUTION_STATUSES:
        raise DealLifecycleError(
            "A dispute resolution must close the deal as completed, refunded or "
            "partially refunded.",
            code="dispute_resolution_status_invalid",
        )
    deal = aggregate.deal
    if deal.status == status:
        return TransitionResult(deal.pk, deal.status, False)
    at = at or timezone.now()
    extra_fields: list[str] = []
    if status == Deal.Status.COMPLETED:
        deal.completed_at = deal.completed_at or at
        extra_fields.append("completed_at")
    else:
        deal.cancelled_at = deal.cancelled_at or at
        deal.cancellation_reason = (deal.cancellation_reason or reason)[:64]
        extra_fields.extend(["cancelled_at", "cancellation_reason"])
    _set_status(
        deal,
        status,
        reason=reason,
        actor_id=actor_id,
        extra_fields=extra_fields,
        payload={"dispute_id": dispute_id},
    )
    return TransitionResult(deal.pk, deal.status, True)
