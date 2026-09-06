"""The payout release gate: the only normal way out of `not_eligible`.

Phase 3 built a payout record that could not be released, and made that
structural with `fin_payout_release_requires_eligibility`. This is the key, and
it is deliberately the only one. Four conditions must all hold, checked together
under one lock:

1. delivery was confirmed by a verified delivery code,
2. the stored `protection_ends_at` has passed,
3. no dispute on the Deal is active,
4. the money reconciles -- the balance obligation is paid, and nothing is being
   refunded out from under it.

**The race this is built around.** The protection timer expiring and a sender
opening a dispute are two writers competing for the same money at the same
instant. Both enter through `lock_deal_lifecycle`, which takes the Deal row
before it takes disputes and the payout. Whichever transaction commits first,
the second one blocks on the Deal row and then reads the first one's committed
state -- so "the timer released the payout because it read stale dispute state"
is not a reachable interleaving, and a dispute that arrives after eligibility
pulls the payout straight back to `frozen`.

There is no path here that pays anybody. Eligibility only opens the door;
`complete_manual_payout` and the payout rails still have to walk through it,
with their own evidence requirements.
"""

from __future__ import annotations

import logging
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from apps.core.financial_locks import LockedLifecycleAggregate, lock_deal_lifecycle
from apps.core.event_resources import deal_resources
from apps.deals import lifecycle
from apps.deals.models import Deal, DealEvent

from .models import PaymentOrder, PaymentRefund, Payout

logger = logging.getLogger(__name__)


class PayoutReleaseRefused(RuntimeError):
    """Release was refused. The message names which condition failed."""

    code = "payout_release_refused"


def _financial_state_is_clean(deal_id: int) -> tuple[bool, str]:
    """Is the Deal's money in a state that can support a payout?

    Called with the Deal aggregate already held, so this takes the order rows
    in ascending id — the canonical order for two rows of the same type.
    """

    orders = list(
        PaymentOrder.objects.select_for_update(no_key=True)
        .filter(deal_id=deal_id, purpose=PaymentOrder.Purpose.DEAL_BALANCE)
        .order_by("pk")
    )
    if not orders:
        return False, "balance_order_missing"
    balance = orders[-1]
    if balance.outstanding_eur_cents > 0:
        return False, "balance_outstanding"
    if int(balance.refunded_eur_cents) > 0:
        return False, "balance_refunded"
    pending_refund = PaymentRefund.objects.filter(
        order_id=balance.pk,
        status__in=(PaymentRefund.Status.PENDING, PaymentRefund.Status.PROCESSING),
    ).exists()
    if pending_refund:
        return False, "refund_in_flight"
    return True, ""


def freeze_payout(
    aggregate: LockedLifecycleAggregate, *, reason: str, dispute_id: int | None = None
) -> str:
    """Pull the payout back out of any releasable state. Idempotent.

    Called by dispute opening while the same lifecycle aggregate is held. A
    payout that has already been paid cannot be frozen; the caller records that
    on the dispute so an operator sees it, rather than pretending the money is
    still here.
    """

    deal = aggregate.deal
    payout = Payout.objects.select_for_update(no_key=True).filter(deal_id=deal.pk).first()
    if payout is None:
        return "no_payout"
    if payout.status == Payout.Status.PAID:
        logger.warning(
            "finance.dispute_after_payout_paid deal=%s payout=%s dispute=%s",
            deal.pk,
            payout.pk,
            dispute_id,
        )
        return Payout.Status.PAID
    if payout.status in (Payout.Status.CANCELLED, Payout.Status.FROZEN):
        return payout.status

    previous = payout.status
    payout.status = Payout.Status.FROZEN
    payout.scheduled_for = None
    payout.notes = f"Frozen by dispute #{dispute_id or ''}: {reason}"[:2000]
    payout.save(update_fields=["status", "scheduled_for", "notes", "updated_at"])
    lifecycle.record_event(
        deal,
        DealEvent.Kind.PAYOUT_STATUS_CHANGED,
        {
            "payout_id": payout.pk,
            "status": payout.status,
            "previous_status": previous,
            "reason": reason,
            "dispute_id": dispute_id,
        },
    )
    return payout.status


def evaluate_payout_release(
    *,
    deal_id: int,
    at: datetime | None = None,
    reason: str = "protection_window_expired",
) -> str:
    """Decide whether this Deal's payout may be released, and act on it.

    Returns a short machine string describing what happened. Safe to call as
    often as anything likes: a duplicate `protection_expiry` job, a worker
    restart, and an operator's manual re-check all converge on the same answer.
    """

    at = at or timezone.now()
    with transaction.atomic():
        aggregate = lock_deal_lifecycle(deal_id)
        deal = aggregate.deal

        if deal.status in (
            Deal.Status.CANCELLED,
            Deal.Status.EXPIRED,
            Deal.Status.REFUNDED,
            Deal.Status.PAYMENT_FAILED,
        ):
            return "deal_closed"
        if deal.delivery_confirmed_at is None:
            return "delivery_not_confirmed"
        if deal.protection_ends_at is None:
            return "protection_not_armed"

        dispute = aggregate.active_dispute()
        if dispute is not None:
            freeze_payout(
                aggregate,
                reason="dispute_active_at_protection_expiry",
                dispute_id=dispute.pk,
            )
            return "frozen_by_dispute"

        if at < deal.protection_ends_at:
            return "protection_open"

        clean, problem = _financial_state_is_clean(deal.pk)
        if not clean:
            logger.warning(
                "finance.payout_release_blocked deal=%s reason=%s", deal.pk, problem
            )
            return f"financial_state_{problem}"

        payout = Payout.objects.select_for_update(no_key=True).filter(deal_id=deal.pk).first()
        if payout is None:
            return "no_payout"
        if payout.status in (
            Payout.Status.PAID,
            Payout.Status.CANCELLED,
            Payout.Status.PROCESSING,
            Payout.Status.SCHEDULED,
            Payout.Status.ELIGIBLE,
        ):
            _close_out(aggregate, reason=reason, at=at)
            return f"payout_{payout.status}"

        previous = payout.status
        payout.status = Payout.Status.ELIGIBLE
        payout.eligible_at = at
        payout.scheduled_for = at
        payout.notes = (
            f"Released: protection window closed at "
            f"{deal.protection_ends_at.isoformat()} with no active dispute."
        )[:2000]
        payout.save(
            update_fields=[
                "status",
                "eligible_at",
                "scheduled_for",
                "notes",
                "updated_at",
            ]
        )
        lifecycle.record_event(
            deal,
            DealEvent.Kind.PROTECTION_EXPIRED,
            {"protection_ends_at": deal.protection_ends_at.isoformat()},
        )
        lifecycle.record_event(
            deal,
            DealEvent.Kind.PAYOUT_ELIGIBLE,
            {
                "payout_id": payout.pk,
                "previous_status": previous,
                "amount_eur_cents": int(payout.amount_eur_cents),
            },
        )
        _close_out(aggregate, reason=reason, at=at)
        _notify_protection_ended(aggregate)
        _notify_payout_status(aggregate, payout)
        return "released"


def _close_out(
    aggregate: LockedLifecycleAggregate, *, reason: str, at: datetime
) -> None:
    """Complete the Deal once its protection window has closed cleanly.

    The delivery contract is finished at this point. The payout continues on its
    own lifecycle and every later state change is recorded on this timeline as a
    `payout_status_changed` event, so holding the Deal open until an operator's
    bank transfer clears would misreport a finished delivery for days.
    """

    if aggregate.deal.status in (
        Deal.Status.PROTECTION_WINDOW,
        Deal.Status.DELIVERY_CONFIRMED,
    ):
        lifecycle.apply_completed(aggregate, reason=reason, at=at)


def _notify_protection_ended(aggregate: LockedLifecycleAggregate) -> None:
    from apps.notifications.models import OutboundMessage
    from apps.notifications.outbox import enqueue_message

    deal = aggregate.deal
    context = {"deal_reference": f"ST-{deal.pk}"}
    for user_id, email in (
        (deal.sender_id, getattr(deal.sender, "email", "")),
        (deal.traveler_id, getattr(deal.traveler, "email", "")),
    ):
        if not email:
            continue
        enqueue_message(
            kind=OutboundMessage.Kind.PROTECTION_ENDED,
            key=f"protection_ended:{deal.pk}:{user_id}",
            to_email=email,
            recipient_user_id=user_id,
            deal_id=deal.pk,
            context=context,
        )


def _notify_payout_status(
    aggregate: LockedLifecycleAggregate, payout: Payout
) -> None:
    """Tell the traveler their money is now released for settlement.

    Keyed on the payout and the status, so a re-evaluation that finds the
    payout already eligible does not send a second copy, and a genuine later
    state change gets its own message.
    """

    from apps.notifications.models import OutboundMessage
    from apps.notifications.outbox import enqueue_message

    deal = aggregate.deal
    email = getattr(deal.traveler, "email", "")
    if email:
        enqueue_message(
            kind=OutboundMessage.Kind.PAYOUT_STATUS,
            key=f"payout_status:{payout.pk}:{payout.status}",
            to_email=email,
            recipient_user_id=deal.traveler_id,
            deal_id=deal.pk,
            context={
                "deal_reference": f"ST-{deal.pk}",
                "payout_status": payout.status,
            },
        )
    from apps.core.channels import PAYOUT_STATUS_CHANGED
    from apps.core.redis_bus import publish_after_commit

    publish_after_commit(
        PAYOUT_STATUS_CHANGED,
        {**deal_resources(deal), "status": payout.status},
        targets=[deal.traveler_id],
    )
