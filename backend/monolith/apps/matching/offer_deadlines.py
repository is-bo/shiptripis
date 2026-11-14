"""Proposal response deadlines (spec 17.1, plan L12A).

Every proposal and counter-proposal written while the switch is on carries a
deadline: the moment it was sent plus ``marketplace.offers.response_hours``, or
the pickup time of that match if that comes first. The pickup time is the
matching engine's own (``CompatibilityResult.pickup_at``, computed by the same
evaluation the offer write runs); nothing here computes a time of its own.

The deadline is fixed on the row when it is written (``Offer.expires_at`` is
immutable) and drives three things:

* **Refusal.** From the deadline on, the offer can no longer be accepted,
  countered, declined or withdrawn; every write path asks `deadline_passed`
  inside its row locks and refuses with ``offer_expired``, whether or not the
  expiry job has run yet.
* **One reminder**, to the person who must answer, ``reminder_before_hours``
  before the deadline (`handle_response_reminder`). Not scheduled when that
  moment is not after the offer was sent.
* **Expiry** at the deadline (`handle_offer_expiry`): the offer becomes
  ``expired`` and the negotiation ends exactly as a decline ends it. Expiry is
  neutral: no reservation, deal, order, ledger row or reliability signal is
  touched.

Both are durable ``ScheduledJob`` rows written in the transaction that writes
the offer, so a crash loses neither. Each handler re-reads the offer under the
decline path's locks and does nothing once the work is no longer needed.
Turning the switch off only stops new deadlines; an offer that has one keeps it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from apps.core import channels, redis_bus
from apps.core.event_resources import match_resources
from apps.core.marketplace_policy import MarketplacePolicy
from apps.core.models import BusinessSettingsVersion
from apps.parcels import tracking

from .models import Match, MatchEvent, Offer

#: Statuses an offer can have when its deadline is what ended it: still
#: pending (the job has not run yet) or already expired by the job.
_LAPSIBLE = frozenset({Offer.Status.PENDING, Offer.Status.EXPIRED})


@dataclass(frozen=True, slots=True)
class ResponseDeadline:
    expires_at: datetime
    #: When to remind the person who must answer; None for no reminder.
    remind_at: datetime | None


def response_deadline(
    *,
    sent_at: datetime,
    pickup_at: datetime,
    settings_version: BusinessSettingsVersion,
) -> ResponseDeadline | None:
    """The deadline an offer written now gets, or None with the switch off.

    ``settings_version`` is the revision the offer is priced under, so one
    write never mixes two revisions. ``pickup_at`` is the engine's pickup time
    for this match, which the engine guarantees is after ``sent_at``.
    """

    policy = MarketplacePolicy.from_settings(settings_version).offers
    if not policy.response_deadline_enabled:
        return None
    expires_at = min(sent_at + timedelta(hours=policy.response_hours), pickup_at)
    remind_at = None
    if policy.reminder_before_hours:
        candidate = expires_at - timedelta(hours=policy.reminder_before_hours)
        if candidate > sent_at:
            remind_at = candidate
    return ResponseDeadline(expires_at=expires_at, remind_at=remind_at)


def schedule_deadline_jobs(offer: Offer, deadline: ResponseDeadline) -> None:
    """Record the reminder and the expiry. Call inside the offer's transaction."""

    from apps.finance.models import ScheduledJob
    from apps.finance.services import schedule_job

    stamp = deadline.expires_at.isoformat()
    payload = {"offer_id": offer.pk, "expires_at": stamp}
    if deadline.remind_at is not None:
        schedule_job(
            kind=ScheduledJob.Kind.OFFER_RESPONSE_REMINDER,
            key=f"offer_response_reminder:{offer.pk}:{stamp}",
            run_at=deadline.remind_at,
            payload=payload,
        )
    schedule_job(
        kind=ScheduledJob.Kind.OFFER_EXPIRY,
        key=f"offer_expiry:{offer.pk}:{stamp}",
        run_at=deadline.expires_at,
        payload=payload,
    )


def deadline_passed(offer: Offer, *, at: datetime) -> bool:
    """Whether the offer's deadline ended it: from the deadline on, inclusive."""

    return (
        offer.status in _LAPSIBLE
        and offer.expires_at is not None
        and offer.expires_at <= at
    )


def effective_status(offer: Offer, *, at: datetime) -> str:
    """The status a party is shown: ``expired`` from the deadline on.

    The row turns ``expired`` when the expiry job runs, a moment later; the
    refusal does not wait for it (spec 17.1), so neither does the payload.
    """

    return Offer.Status.EXPIRED if deadline_passed(offer, at=at) else offer.status


# ---------------------------------------------------------------------------
# Job handlers
# ---------------------------------------------------------------------------


def _parse(payload: dict, kind: str) -> tuple[int, datetime]:
    from apps.finance.jobs import PermanentJobError

    offer_id = payload.get("offer_id")
    try:
        expires_at = datetime.fromisoformat(payload.get("expires_at"))
    except (TypeError, ValueError):
        expires_at = None
    if (
        not isinstance(offer_id, int)
        or isinstance(offer_id, bool)
        or expires_at is None
        or expires_at.tzinfo is None
    ):
        raise PermanentJobError(
            f"{kind} needs an integer offer_id and an aware expires_at.",
            code="invalid_payload",
        )
    return offer_id, expires_at


def _lock_offer(offer_id: int) -> tuple[Match, Offer] | None:
    """Match, then Offer: the decline path's locks, in its order."""

    match_id = Offer.objects.filter(pk=offer_id).values_list("match_id", flat=True).first()
    if match_id is None:
        return None
    # `of=("self",)`: the parcel is joined for its tracking number only and
    # must not be locked here, after the Match (the canonical order puts the
    # request first).
    match = (
        Match.objects.select_for_update(no_key=True, of=("self",))
        .select_related("parcel")
        .get(pk=match_id)
    )
    offer = Offer.objects.select_for_update(no_key=True).get(pk=offer_id)
    return match, offer


def handle_response_reminder(payload: dict) -> str:
    """`ScheduledJob` handler. Idempotent; re-reads the offer under its locks."""

    offer_id, expires_at = _parse(payload, "offer_response_reminder")
    with transaction.atomic():
        locked = _lock_offer(offer_id)
        if locked is None:
            return "offer_gone"
        match, offer = locked
        if offer.expires_at != expires_at:
            return "deadline_changed"
        if offer.status != Offer.Status.PENDING or match.status != Match.Status.PENDING:
            return "not_pending"
        if timezone.now() >= offer.expires_at:
            return "deadline_passed"
        recipient = (
            match.traveler_id
            if offer.proposed_by == Offer.ProposedBy.SENDER
            else match.sender_id
        )
        redis_bus.publish_after_commit(
            channels.OFFER_RESPONSE_REMINDER,
            {
                **match_resources(match),
                "offer_id": offer.pk,
                "tracking_number": tracking.for_request(match.parcel),
            },
            targets=[recipient],
            idempotency_key=f"offer_response_reminder:{offer.pk}",
        )
    return "notified"


def handle_offer_expiry(payload: dict) -> str:
    """`ScheduledJob` handler. Ends an unanswered offer exactly as a decline does."""

    from apps.finance.jobs import JobDeferred

    offer_id, expires_at = _parse(payload, "offer_expiry")
    with transaction.atomic():
        locked = _lock_offer(offer_id)
        if locked is None:
            return "offer_gone"
        match, offer = locked
        if offer.expires_at != expires_at:
            return "deadline_changed"
        if offer.status != Offer.Status.PENDING:
            return "not_pending"
        now = timezone.now()
        if now < offer.expires_at:
            # Claimed early by a worker whose clock runs ahead; keep the work.
            raise JobDeferred(
                "The offer's deadline has not passed yet.",
                code="deadline_not_reached",
                delay=offer.expires_at - now,
            )
        offer.status = Offer.Status.EXPIRED
        offer.responded_at = now
        offer.save(update_fields=["status", "responded_at", "updated_at"])
        if offer.economics_version == Offer.EconomicsVersion.V1_EUR:
            # The same ending as a decline: the negotiation is over and the
            # request stays open, so the sender may propose to someone else.
            match.status = Match.Status.CANCELLED
            match.save(update_fields=["status", "updated_at"])
        MatchEvent.objects.create(
            match=match,
            offer=offer,
            actor=None,
            kind=MatchEvent.Kind.OFFER_EXPIRED,
            payload={"expires_at": offer.expires_at.isoformat()},
        )
        redis_bus.publish_after_commit(
            channels.OFFER_UPDATED,
            {**match_resources(match), "offer_id": offer.pk, "status": "expired"},
            targets=[match.sender_id, match.traveler_id],
            idempotency_key=f"offer_expired:{offer.pk}",
        )
    return "expired"
