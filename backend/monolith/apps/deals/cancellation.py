"""Cancellation after funding, and the no-show foundation.

Before funding, cancelling is free and `release_pending_deal_reservation`
already handles it. After funding there is real money on the platform and a
traveler who may have already rearranged their journey, so the outcome depends
on who cancels and how close to the agreed pickup they are:

* **the traveler cancels** — the sender is made whole. Full refund, no
  compensation, and the decision is recorded as a reliability signal.
* **the sender cancels early** — more than the configured cutoff before the
  agreed pickup, currently 24 hours. Full refund.
* **the sender cancels late** — inside the cutoff. The traveler is compensated
  (10% of their reward, capped at EUR 15, both admin-configurable) and every
  remaining cent goes back to the sender. The platform waives its commission at
  launch, which is a policy value rather than a hard-coded generosity.

**After pickup there is no cancellation.** The parcel is in someone else's hands
and the answer to "something went wrong" is a dispute with an evidence bundle,
not a unilateral refund. `cancel_funded_deal` refuses, and no API exposes a
cancel action once `pickup_confirmed_at` is set.

Every policy value is read from the Deal's frozen `lifecycle_policy`, not from
live settings, so the penalty a sender is quoted is the penalty they are
charged even if an administrator publishes a new revision in between.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from apps.core.financial_locks import LockedLifecycleAggregate, lock_deal_lifecycle
from apps.matching.models import Match, MatchEvent
from apps.parcels.models import ParcelRequest

from . import lifecycle
from .models import Deal, DealEvent, DealLegAllocation

logger = logging.getLogger(__name__)


class CancellationError(RuntimeError):
    code = "deal_cancellation_error"

    def __init__(self, message: str, *, code: str | None = None, **details):
        super().__init__(message)
        if code:
            self.code = code
        self._details = details

    def details(self) -> dict:
        return dict(self._details)


@dataclass(frozen=True, slots=True)
class CancellationQuote:
    """What cancelling right now would cost, computed server-side.

    The client renders this and never derives it. Amounts are canonical EUR
    cents; `is_late` and `cutoff_at` exist so the app can explain *why* a
    penalty applies rather than presenting a number with no reason.
    """

    deal_id: int
    actor_role: str
    allowed: bool
    refusal_code: str
    collected_eur_cents: int
    sender_refund_eur_cents: int
    traveler_compensation_eur_cents: int
    platform_fee_eur_cents: int
    is_late: bool
    cutoff_at: datetime | None
    agreed_pickup_at: datetime | None

    def as_dict(self) -> dict:
        return {
            "deal_id": self.deal_id,
            "actor_role": self.actor_role,
            "allowed": self.allowed,
            "refusal_code": self.refusal_code,
            "collected_eur_cents": self.collected_eur_cents,
            "sender_refund_eur_cents": self.sender_refund_eur_cents,
            "traveler_compensation_eur_cents": self.traveler_compensation_eur_cents,
            "platform_fee_eur_cents": self.platform_fee_eur_cents,
            "is_late": self.is_late,
            "cutoff_at": self.cutoff_at.isoformat() if self.cutoff_at else None,
            "agreed_pickup_at": (
                self.agreed_pickup_at.isoformat() if self.agreed_pickup_at else None
            ),
        }


def _policy(deal: Deal) -> dict:
    snapshot = (deal.lifecycle_policy or {}).get("cancellation")
    if isinstance(snapshot, dict):
        return snapshot
    # A Deal funded before Phase 4 shipped. The documented seed applies, which
    # is the conservative reading: the sender still gets the free window and the
    # traveler still gets the capped compensation.
    return {
        "sender_free_cutoff_seconds": 86_400,
        "sender_late_compensation_bps": 1_000,
        "sender_late_compensation_cap_eur_cents": 1_500,
        "sender_late_platform_fee_bps": 0,
    }


def _int_policy(policy: dict, key: str, default: int) -> int:
    value = policy.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return default
    return value


def _actor_role(deal: Deal, actor_id: int) -> str:
    if actor_id == deal.sender_id:
        return "sender"
    if actor_id == deal.traveler_id:
        return "traveler"
    return ""


def build_quote(
    *, aggregate: LockedLifecycleAggregate, actor_id: int, at: datetime | None = None
) -> CancellationQuote:
    """Price a cancellation without performing one. Pure, given locked state."""

    from apps.finance.settlement import plan_settlement, read_deal_money

    deal = aggregate.deal
    at = at or timezone.now()
    role = _actor_role(deal, actor_id)
    policy = _policy(deal)
    cutoff_seconds = _int_policy(policy, "sender_free_cutoff_seconds", 86_400)
    cutoff_at = (
        deal.agreed_pickup_at - timedelta(seconds=cutoff_seconds)
        if deal.agreed_pickup_at is not None
        else None
    )

    def refuse(code: str) -> CancellationQuote:
        return CancellationQuote(
            deal_id=deal.pk,
            actor_role=role,
            allowed=False,
            refusal_code=code,
            collected_eur_cents=0,
            sender_refund_eur_cents=0,
            traveler_compensation_eur_cents=0,
            platform_fee_eur_cents=0,
            is_late=False,
            cutoff_at=cutoff_at,
            agreed_pickup_at=deal.agreed_pickup_at,
        )

    if not role:
        return refuse("not_authorized")
    if deal.pickup_confirmed_at is not None:
        return refuse("cancellation_not_available_after_pickup")
    if deal.status not in lifecycle.PRE_PICKUP_STATUSES:
        if deal.status == Deal.Status.PAYMENT_REQUIRED:
            return refuse("use_pre_funding_cancellation")
        return refuse("deal_not_cancellable")

    money = read_deal_money(deal)
    compensation = 0
    is_late = False
    if role == "sender":
        # No agreed pickup instant means we cannot prove the sender is inside
        # the cutoff, and charging a penalty we cannot justify is the wrong
        # default. Treat it as early.
        if cutoff_at is not None and at >= cutoff_at:
            is_late = True
            bps = _int_policy(policy, "sender_late_compensation_bps", 1_000)
            cap = _int_policy(policy, "sender_late_compensation_cap_eur_cents", 1_500)
            # Ceiling division in integer cents. The traveler is never short-
            # changed by a rounding decision the sender caused.
            # Cancellation compensation policy applies to the negotiated base
            # reward. The sender-funded boost bonus is protected deal money,
            # but it does not silently enlarge an unrelated penalty formula.
            raw = (int(money.base_traveler_reward_eur_cents) * bps + 9_999) // 10_000
            compensation = min(raw, cap, money.collected_eur_cents)

    plan = plan_settlement(
        money=money,
        sender_refund_eur_cents=money.collected_eur_cents - compensation,
        traveler_payout_eur_cents=compensation,
    )
    return CancellationQuote(
        deal_id=deal.pk,
        actor_role=role,
        allowed=True,
        refusal_code="",
        collected_eur_cents=money.collected_eur_cents,
        sender_refund_eur_cents=plan.sender_refund_eur_cents,
        traveler_compensation_eur_cents=plan.traveler_payout_eur_cents,
        platform_fee_eur_cents=plan.platform_fee_eur_cents,
        is_late=is_late,
        cutoff_at=cutoff_at,
        agreed_pickup_at=deal.agreed_pickup_at,
    )


def quote_cancellation(*, deal_id: int, actor_id: int) -> CancellationQuote:
    """Read-only quote for the confirmation screen."""

    with transaction.atomic():
        aggregate = lock_deal_lifecycle(deal_id)
        return build_quote(aggregate=aggregate, actor_id=actor_id)


def cancel_funded_deal(
    *, deal_id: int, actor_id: int, reason: str = "", at: datetime | None = None
) -> CancellationQuote:
    """Cancel a funded Deal and settle its money in one transaction.

    The whole thing commits together: capacity release, the Deal transition, the
    refunds, the traveler's compensation and the timeline. There is no window in
    which the capacity is free but the money is unresolved, and none in which
    the sender has been refunded but the leg is still reserved.

    Racing a pickup confirmation is resolved by the Deal row lock. Whichever
    commits first wins outright — a cancellation that loses sees
    `pickup_confirmed_at` set and is refused, and a pickup that loses finds the
    Deal cancelled and refuses too.
    """

    from apps.finance.models import PaymentRefund
    from apps.finance.settlement import (
        apply_settlement,
        plan_settlement,
        read_deal_money,
    )

    at = at or timezone.now()
    with transaction.atomic():
        aggregate = lock_deal_lifecycle(deal_id)
        deal = aggregate.deal
        quote = build_quote(aggregate=aggregate, actor_id=actor_id, at=at)
        if not quote.allowed:
            raise CancellationError(
                _refusal_message(quote.refusal_code),
                code=quote.refusal_code,
                deal_status=deal.status,
            )

        lifecycle.record_event(
            deal,
            DealEvent.Kind.CANCELLATION_REQUESTED,
            {
                "actor_role": quote.actor_role,
                "is_late": quote.is_late,
                **quote.as_dict(),
            },
            actor_id=actor_id,
        )

        money = read_deal_money(deal)
        plan = plan_settlement(
            money=money,
            sender_refund_eur_cents=quote.sender_refund_eur_cents,
            traveler_payout_eur_cents=quote.traveler_compensation_eur_cents,
        )
        apply_settlement(
            plan=plan,
            settlement_key=f"deal_cancellation:{deal.pk}",
            refund_reason=PaymentRefund.Reason.DEAL_CANCELLED_FUNDED,
            note=(
                f"Deal #{deal.pk} cancelled after funding by {quote.actor_role}"
                f"{' (late)' if quote.is_late else ''}"
            ),
            actor_id=actor_id,
        )
        if plan.traveler_payout_eur_cents > 0:
            lifecycle.record_event(
                deal,
                DealEvent.Kind.COMPENSATION_APPLIED,
                {
                    "traveler_compensation_eur_cents": plan.traveler_payout_eur_cents,
                    "basis": "late_sender_cancellation",
                },
                actor_id=actor_id,
            )

        _release_capacity(aggregate, reason="deal_cancelled_after_funding", at=at)
        _close_domain_rows(aggregate, actor_id=actor_id, at=at)
        _cancel_live_codes(aggregate, at=at)

        deal.cancelled_at = at
        deal.cancelled_by_id = actor_id
        deal.cancellation_reason = (
            reason or f"{quote.actor_role}_cancelled_after_funding"
        )[:64]
        target = (
            Deal.Status.REFUNDED
            if plan.traveler_payout_eur_cents == 0
            and plan.sender_refund_eur_cents == money.collected_eur_cents
            else Deal.Status.PARTIALLY_REFUNDED
        )
        if money.collected_eur_cents == 0:
            target = Deal.Status.CANCELLED
        deal.status = target
        deal.save(
            update_fields=[
                "status",
                "cancelled_at",
                "cancelled_by",
                "cancellation_reason",
                "updated_at",
            ]
        )
        lifecycle.record_event(
            deal,
            DealEvent.Kind.CANCELLED_AFTER_FUNDING,
            {
                "actor_role": quote.actor_role,
                "status": deal.status,
                **plan.as_dict(),
            },
            actor_id=actor_id,
        )
        lifecycle.record_event(
            deal,
            DealEvent.Kind.STATUS_CHANGED,
            {"status": deal.status, "reason": deal.cancellation_reason},
            actor_id=actor_id,
        )
        _notify_cancelled(aggregate, quote)
    return quote


def _refusal_message(code: str) -> str:
    return {
        "not_authorized": "Only a party to this delivery can cancel it.",
        "cancellation_not_available_after_pickup": (
            "This parcel has already been picked up. Open a dispute instead."
        ),
        "use_pre_funding_cancellation": (
            "This delivery has not been funded yet; use the standard cancel action."
        ),
        "deal_not_cancellable": "This delivery can no longer be cancelled.",
    }.get(code, "This delivery cannot be cancelled.")


def _release_capacity(
    aggregate: LockedLifecycleAggregate, *, reason: str, at: datetime
) -> None:
    allocation_ids = [
        row.pk
        for row in aggregate.deal_aggregate.allocations
        if row.status
        in (
            DealLegAllocation.Status.PENDING_PAYMENT,
            DealLegAllocation.Status.FUNDED,
        )
    ]
    if not allocation_ids:
        return
    DealLegAllocation.objects.filter(pk__in=allocation_ids).update(
        status=DealLegAllocation.Status.RELEASED,
        released_at=at,
        release_reason=reason[:64],
    )
    lifecycle.record_event(
        aggregate.deal,
        DealEvent.Kind.CAPACITY_RELEASED,
        {"reason": reason, "allocation_ids": allocation_ids},
    )


def _close_domain_rows(
    aggregate: LockedLifecycleAggregate, *, actor_id: int, at: datetime
) -> None:
    """Close the Match and retire the request.

    The request is *cancelled* rather than reopened. Reopening it would leave a
    published request whose posting deposit has just been refunded, which breaks
    the deposit-before-publication rule; the sender creates a fresh request, and
    pays a fresh deposit, if they still want to ship.
    """

    deal = aggregate.deal
    match = next(
        (row for row in aggregate.request_graph.matches if row.pk == deal.match_id),
        None,
    )
    if match is not None and match.status in (
        Match.Status.ACCEPTED,
        Match.Status.PENDING,
    ):
        match.status = Match.Status.CANCELLED
        match.save(update_fields=["status", "updated_at"])
        MatchEvent.objects.create(
            match=match,
            actor_id=actor_id,
            kind=MatchEvent.Kind.MATCH_CANCELLED,
            payload={"reason": "deal_cancelled_after_funding"},
        )
    request_row = aggregate.request_graph.request
    parcel = request_row.parcelrequest_ptr
    if parcel.status in (
        ParcelRequest.Status.MATCHED,
        ParcelRequest.Status.OPEN,
    ):
        parcel.status = ParcelRequest.Status.CANCELLED
        parcel.save(update_fields=["status", "updated_at"])


def _cancel_live_codes(aggregate: LockedLifecycleAggregate, *, at: datetime) -> None:
    """Retire any code that could still open a handover on a dead Deal."""

    from apps.handover.models import DealHandoverCode

    live_ids = [
        row.pk
        for row in aggregate.handover_codes
        if row.status in DealHandoverCode.LIVE_STATUSES
    ]
    if live_ids:
        DealHandoverCode.objects.filter(pk__in=live_ids).update(
            status=DealHandoverCode.Status.CANCELLED,
            superseded_at=at,
            updated_at=at,
        )


def _notify_cancelled(
    aggregate: LockedLifecycleAggregate, quote: CancellationQuote
) -> None:
    from apps.notifications.models import OutboundMessage
    from apps.notifications.outbox import enqueue_message

    deal = aggregate.deal
    context = {
        "deal_reference": f"ST-{deal.pk}",
        "cancelled_by_role": quote.actor_role,
    }
    for user_id, email in (
        (deal.sender_id, getattr(deal.sender, "email", "")),
        (deal.traveler_id, getattr(deal.traveler, "email", "")),
    ):
        if not email:
            continue
        enqueue_message(
            kind=OutboundMessage.Kind.DEAL_CANCELLED,
            key=f"deal_cancelled:{deal.pk}:{user_id}",
            to_email=email,
            recipient_user_id=user_id,
            deal_id=deal.pk,
            context=context,
        )
    from apps.core.channels import DEAL_CANCELLED
    from apps.core.redis_bus import publish_after_commit

    publish_after_commit(
        DEAL_CANCELLED,
        {"deal_id": deal.pk},
        targets=[deal.sender_id, deal.traveler_id],
    )


# --- no-show ------------------------------------------------------------------


def record_no_show(
    *,
    deal_id: int,
    party: str,
    admin_actor_id: int,
    note: str = "",
    refund_sender: bool | None = None,
) -> dict:
    """Record an admin-reviewed no-show, and settle it when it is the traveler's.

    Launch policy is deliberately manual: no automated risk scoring, no
    heuristics deciding who failed to appear. What Phase 4 owns is the record —
    who decided, when, about whom — and the one financial consequence the
    specification names: a verified traveler no-show refunds the sender in full.

    `refund_sender` defaults to that rule and can be overridden by an
    administrator who has a reason to; the override is stored on the timeline
    alongside their note.
    """

    from apps.finance.models import PaymentRefund
    from apps.finance.settlement import (
        apply_settlement,
        plan_settlement,
        read_deal_money,
    )

    if party not in (Deal.NoShowParty.SENDER, Deal.NoShowParty.TRAVELER):
        raise CancellationError(
            "A no-show must name the sender or the traveler.",
            code="no_show_party_invalid",
        )
    at = timezone.now()
    with transaction.atomic():
        aggregate = lock_deal_lifecycle(deal_id)
        deal = aggregate.deal
        if deal.no_show_party:
            return {
                "deal_id": deal.pk,
                "party": deal.no_show_party,
                "changed": False,
                "recorded_at": deal.no_show_recorded_at,
            }
        if deal.pickup_confirmed_at is not None:
            raise CancellationError(
                "A no-show cannot be recorded once pickup was confirmed.",
                code="pickup_already_confirmed",
            )
        if deal.status not in lifecycle.PRE_PICKUP_STATUSES:
            raise CancellationError(
                "A no-show can only be recorded on a funded, pre-pickup delivery.",
                code="deal_not_cancellable",
                deal_status=deal.status,
            )

        should_refund = (
            refund_sender
            if refund_sender is not None
            else party == Deal.NoShowParty.TRAVELER
        )
        deal.no_show_party = party
        deal.no_show_recorded_at = at
        deal.no_show_recorded_by_id = admin_actor_id
        deal.no_show_note = note[:255]
        deal.save(
            update_fields=[
                "no_show_party",
                "no_show_recorded_at",
                "no_show_recorded_by",
                "no_show_note",
                "updated_at",
            ]
        )
        lifecycle.record_event(
            deal,
            DealEvent.Kind.NO_SHOW_RECORDED,
            {
                "party": party,
                "refund_sender": should_refund,
                "note": note[:255],
            },
            actor_id=admin_actor_id,
        )

        if should_refund:
            money = read_deal_money(deal)
            plan = plan_settlement(
                money=money,
                sender_refund_eur_cents=money.collected_eur_cents,
                traveler_payout_eur_cents=0,
            )
            apply_settlement(
                plan=plan,
                settlement_key=f"no_show:{deal.pk}",
                refund_reason=PaymentRefund.Reason.NO_SHOW,
                note=f"Verified {party} no-show on deal #{deal.pk}",
                actor_id=admin_actor_id,
            )
            _release_capacity(aggregate, reason="no_show", at=at)
            _close_domain_rows(aggregate, actor_id=admin_actor_id, at=at)
            _cancel_live_codes(aggregate, at=at)
            deal.cancelled_at = at
            deal.cancelled_by_id = admin_actor_id
            deal.cancellation_reason = f"{party}_no_show"[:64]
            deal.status = (
                Deal.Status.REFUNDED
                if money.collected_eur_cents > 0
                else Deal.Status.CANCELLED
            )
            deal.save(
                update_fields=[
                    "status",
                    "cancelled_at",
                    "cancelled_by",
                    "cancellation_reason",
                    "updated_at",
                ]
            )
            lifecycle.record_event(
                deal,
                DealEvent.Kind.STATUS_CHANGED,
                {"status": deal.status, "reason": deal.cancellation_reason},
                actor_id=admin_actor_id,
            )
    return {
        "deal_id": deal.pk,
        "party": party,
        "changed": True,
        "recorded_at": at,
        "sender_refunded": should_refund,
    }
