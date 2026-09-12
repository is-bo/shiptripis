"""The payout release gate: the only normal way out of `not_eligible`.

Phase 3 built a payout record that could not be released, and made that
structural with `fin_payout_release_requires_eligibility`. This is the key, and
it is deliberately the only one. Five conditions must all hold, checked together
under one lock:

1. delivery was confirmed by a verified delivery code,
2. the stored `protection_ends_at` has passed,
3. the Deal's funded arrival floor has passed (Phase I1A),
4. no dispute on the Deal is active,
5. the money reconciles -- the balance obligation is paid, and nothing is being
   refunded out from under it.

**Condition 3, and why it is not the same as condition 2.** Protection runs
forward from the *actual* delivery, so an earlier delivery is an earlier payout.
That is correct for an honest early delivery of a day or two and wrong at the
extreme: a traveler who convinces the platform that a fifteen-day carriage
finished on day one would collect on day three, with the sender given no real
chance to notice. `Deal.funded_scheduled_arrival_floor_at` -- frozen at funding
from the arrival these two parties actually agreed to -- is the brake. The gate
instant is `max` of the two, computed by
`apps.deals.arrival.payout_release_gate_at`, which reads two stored columns and
recomputes neither. A Deal funded before I1A has a null floor and the `max`
reduces to condition 2 exactly, which is the behaviour it already had.

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
    payout = (
        Payout.objects.select_for_update(no_key=True).filter(deal_id=deal.pk).first()
    )
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

    from .payout_domain import committed_exposure_cents

    committed = committed_exposure_cents(payout)
    previous = payout.status
    payout.status = Payout.Status.FROZEN
    payout.scheduled_for = None
    payout.notes = f"Frozen by dispute #{dispute_id or ''}: {reason}"[:2000]
    if committed:
        # A freeze stops the *next* instruction. It cannot recall a Transfer
        # Stripe has already accepted or a bank payout already in transit, and
        # saying otherwise on an operator screen would be a lie about where the
        # money is. Record the exposure instead; recovery is a new provider
        # operation, not a status change.
        payout.notes = (
            f"{payout.notes} External money already committed: "
            f"{committed} EUR cents. Recovery review required."
        )[:2000]
        logger.error(
            "finance.dispute_after_dispatch_commitment deal=%s payout=%s "
            "committed_eur_cents=%s dispute=%s",
            deal.pk,
            payout.pk,
            committed,
            dispute_id,
        )
    payout.save(update_fields=["status", "scheduled_for", "notes", "updated_at"])
    if payout.snapshot_version:
        from .payout_domain import append_event_locked

        append_event_locked(
            payout,
            previous=previous,
            reason="dispute_freeze_with_commitment" if committed else "dispute_freeze",
        )
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

        payout = (
            Payout.objects.select_for_update(no_key=True)
            .filter(deal_id=deal.pk)
            .first()
        )
        if payout is None:
            return "no_payout"

        # The arrival floor. Checked with the Payout row already held, so the
        # deferral below writes `next_action_at` and the ScheduledJob in the
        # canonical order and never acquires a finance row after a job row.
        #
        # The Deal itself is closed out here: its delivery contract finished when
        # protection expired, and holding a delivered shipment open for days
        # because its *payout* is deliberately waiting would misreport it. The
        # payout keeps its own lifecycle, which is what that separation is for.
        from apps.deals.arrival import payout_release_gate_at

        gate = payout_release_gate_at(deal)
        if gate is not None and at < gate:
            if payout.next_action_at != gate:
                payout.next_action_at = gate
                payout.save(update_fields=["next_action_at", "updated_at"])
            _close_out(aggregate, reason=reason, at=at)
            lifecycle.schedule_protection_expiry(deal)
            logger.info(
                "finance.payout_release_arrival_floor deal=%s payout=%s gate=%s",
                deal.pk,
                payout.pk,
                gate.isoformat(),
            )
            return "scheduled_arrival_floor_open"

        if payout.block_reason == "legacy_instruction_required":
            _close_out(aggregate, reason=reason, at=at)
            return "legacy_instruction_required"
        if payout.snapshot_version:
            from .payout_domain import active_holds, append_event_locked

            if active_holds(payout).exists():
                return "finance_hold_active"
            if payout.method == "manual" and payout.block_reason in (
                "",
                "payout_setup_required",
            ):
                from .payout_manual_profiles import approved_profile
                from .models import TravelerPayoutMethod

                version = payout.active_instruction_version
                if version:
                    TravelerPayoutMethod.objects.select_for_update(no_key=True).get(
                        pk=version.method_id
                    )
                ready = version and approved_profile(
                    version.dzd_profile_revision, funded_payout=payout
                )
                reason_code = "" if ready else "payout_setup_required"
                if payout.block_reason != reason_code:
                    payout.block_reason = reason_code
                    payout.save(update_fields=["block_reason"])
            if payout.status in (
                "processing",
                "sent",
                "paid",
                "cancelled",
                "scheduled",
            ):
                _close_out(aggregate, reason=reason, at=at)
                return f"payout_{payout.status}"
            target = "blocked" if payout.block_reason else "eligible"
            if payout.status != target or not payout.eligible_at:
                previous = payout.status
                payout.status = target
                payout.eligible_at = payout.eligible_at or at
                from apps.deals.arrival import payout_release_gate_basis

                payout.eligibility_basis = (
                    payout.eligibility_basis
                    or payout_release_gate_basis(deal)
                    or "delivery_protection"
                )
                payout.save(
                    update_fields=[
                        "status",
                        "eligible_at",
                        "eligibility_basis",
                        "updated_at",
                    ]
                )
                append_event_locked(
                    payout, previous=previous, reason="protection_release"
                )
                from .payout_reconciliation import notify_payout_state

                notify_payout_state(
                    payout, "eligible" if target == "eligible" else "needs_attention"
                )
            if target == "eligible" and payout.method == "stripe_transfer":
                # Automatic from here: no admin "Pay" button exists on this
                # rail. The durable job is the promise; the worker decides
                # nothing this gate has not already decided.
                _arm_execution(payout)
            _close_out(aggregate, reason=reason, at=at)
            return f"payout_{target}"
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
        # Which of the two gates this release actually waited for. Recorded on
        # the legacy row as well as the snapshot one, so an audit of a payout
        # never has to infer it from timestamps.
        from apps.deals.arrival import payout_release_gate_basis

        payout.eligibility_basis = (
            payout.eligibility_basis
            or payout_release_gate_basis(deal)
            or "delivery_protection"
        )
        payout.notes = (
            f"Released: protection window closed at "
            f"{deal.protection_ends_at.isoformat()} with no active dispute."
        )[:2000]
        payout.save(
            update_fields=[
                "status",
                "eligible_at",
                "scheduled_for",
                "eligibility_basis",
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


def _arm_execution(payout: Payout) -> None:
    """Record the durable obligation to attempt this payout automatically."""

    from .models import ScheduledJob
    from .services import schedule_job

    schedule_job(
        kind=ScheduledJob.Kind.PAYOUT_EXECUTE,
        key=f"payout_execute:{payout.pk}",
        run_at=timezone.now(),
        payload={"payout_id": payout.pk},
        max_attempts=32,
        reactivate_failed=True,
    )


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


def _notify_payout_status(aggregate: LockedLifecycleAggregate, payout: Payout) -> None:
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
