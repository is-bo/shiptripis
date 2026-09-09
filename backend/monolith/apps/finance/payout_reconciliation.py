"""One place where every source of truth about a payout converges.

An HTTP response, a webhook, a polling job, an operator's refresh and the
sweeper all say the same kind of thing — *this is what the provider currently
reports* — and they can arrive in any order, more than once, and years apart in
clock terms. If each of them had its own state-transition logic they would
eventually disagree, and the disagreement would be about money.

So none of them transition anything. They all call the `apply_*` functions here,
which are:

* **idempotent**, keyed on the operation or disbursement's own public reference,
  so a duplicate webhook and a re-run job record nothing the second time;
* **monotonic**, guarded on an observation timestamp so a slow old `GET` cannot
  overwrite what a newer one already established;
* **append-only in the ledger**, so a bank return after `paid` posts a
  compensating entry rather than deleting the settlement that really happened.

The Payout aggregate is what a person reads; the events, operations,
disbursements and ledger rows are what actually happened. When a hold freezes
the aggregate, the history keeps recording — a freeze stops new instructions,
not callbacks.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from django.db import transaction
from django.utils import timezone

from apps.core.financial_locks import lock_deal_lifecycle
from . import payout_accounting
from .models import (
    PayoutAttempt,
    PayoutProviderOperation,
    Payout,
    StripeDisbursement,
    StripeDisbursementAllocation,
)
from .payout_domain import active_holds, append_event_locked
from .providers.base import ProviderError, ProviderUnavailable
from .providers.stripe_connect import get_connect_gateway

logger = logging.getLogger(__name__)

#: The user-facing vocabulary H0 fixed for payout notifications. Anything not in
#: here is an internal reason code and never reaches a Traveler.
NOTIFIABLE_CODES = frozenset(
    {"eligible", "setup_required", "processing", "sent", "paid", "needs_attention", "returned"}
)

#: Stripe's documented payout statuses mapped onto the local disbursement
#: vocabulary. `paid` is the only one that discharges an obligation, and even it
#: can be followed by `failed` on a genuine bank return.
PROVIDER_STATUS = {
    "pending": StripeDisbursement.Status.PENDING,
    "in_transit": StripeDisbursement.Status.IN_TRANSIT,
    "paid": StripeDisbursement.Status.PAID,
    "failed": StripeDisbursement.Status.FAILED,
    "canceled": StripeDisbursement.Status.CANCELED,
}


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


def notify_payout_state(payout, code: str) -> None:
    """Emit one safe, deduplicated state signal for a Traveler.

    Deliberately carries no amount, no account, no Transfer id and no Payout id
    into the push payload: a lock-screen notification is the least private
    surface this system has. The in-app detail view is where an authorised owner
    sees the numbers.
    """

    if code not in NOTIFIABLE_CODES:
        return
    from apps.core import channels
    from apps.core.event_resources import deal_resources
    from apps.core.redis_bus import publish_after_commit
    from apps.notifications.models import OutboundMessage
    from apps.notifications.outbox import enqueue_message

    deal = payout.deal
    email = getattr(deal.traveler, "email", "")
    if email:
        # Keyed on the payout's own state version, so a re-run of the same
        # transition enqueues nothing and a genuine later transition gets its
        # own message. `EMAIL_ENABLED=false` leaves the row pending.
        enqueue_message(
            kind=OutboundMessage.Kind.PAYOUT_STATUS,
            key=f"payout_event:{payout.public_reference}:{payout.state_version}:{code}",
            to_email=email,
            recipient_user_id=deal.traveler_id,
            deal_id=deal.pk,
            context={
                "deal_reference": f"ST-{deal.pk}",
                "payout_status": payout.status,
                "payout_event": code,
            },
        )
    publish_after_commit(
        channels.PAYOUT_STATUS_CHANGED,
        {**deal_resources(deal), "status": payout.status, "event": code},
        targets=[deal.traveler_id],
    )


def _transition(payout, *, target: str, reason: str, code: str = "") -> str:
    """Move the aggregate, record the event, and tell the Traveler once.

    A payout under an active hold does not move to an intermediate state: the
    fact is recorded as an event either way, but `frozen` keeps meaning "no new
    instruction may be issued". Settlement facts — `paid` and `failed` — are the
    exception, because they describe money that already moved.
    """

    if payout.status == target:
        return target
    if (
        payout.status == "frozen"
        and target not in ("paid", "failed")
    ):
        append_event_locked(payout, previous=payout.status, reason=f"{reason}_frozen")
        return payout.status
    previous = payout.status
    payout.status = target
    payout.save(update_fields=["status", "updated_at"])
    append_event_locked(payout, previous=previous, reason=reason)
    if code:
        notify_payout_state(payout, code)
    return target


def _locked_payout(payout_id: int):
    seed = Payout.objects.get(pk=payout_id)
    lock_deal_lifecycle(seed.deal_id)
    return (
        # See `payout_execution._lock_payout_aggregate`: the joined destination
        # is nullable, so the lock names the Payout row explicitly.
        Payout.objects.select_for_update(no_key=True, of=("self",))
        .select_related("deal", "active_instruction_version__stripe_account")
        .get(pk=payout_id)
    )


# ---------------------------------------------------------------------------
# Platform transfers
# ---------------------------------------------------------------------------


def mark_operation_unknown(operation, *, reason: str, disbursement=None) -> None:
    """An ambiguous external result. The reservation stands; the key stands.

    This is the state H0 insists must never be flattened into "failed". Nothing
    is released, no new idempotency key is minted, and the next run recovers
    *this* operation rather than issuing another instruction.
    """

    now = timezone.now()
    PayoutProviderOperation.objects.filter(pk=operation.pk).update(
        status="unknown",
        failure_code=reason[:64],
        last_request_at=now,
        # Cleared so the recovery path is claimable immediately; the lease
        # exists to stop two concurrent POSTs, not to delay a resolution.
        retry_after=now + timedelta(minutes=1),
    )
    if disbursement is not None:
        StripeDisbursement.objects.filter(pk=disbursement.pk).update(
            status=StripeDisbursement.Status.UNKNOWN, failure_code=reason[:64]
        )
    with transaction.atomic():
        payout = _locked_payout(operation.attempt.payout_id)
        PayoutAttempt.objects.filter(
            pk=operation.attempt_id, status=PayoutAttempt.Status.DISPATCH_COMMITTED
        ).update(status=PayoutAttempt.Status.UNKNOWN)
        append_event_locked(
            payout, previous=payout.status, reason=f"external_result_unknown:{reason}"[:64]
        )
    logger.error(
        "finance.payout_operation_unknown operation=%s kind=%s reason=%s",
        operation.public_reference,
        operation.kind,
        reason,
    )


def apply_transfer_rejected(operation, *, reason: str) -> None:
    """Stripe refused before executing. The slice becomes spendable again."""

    from .payout_execution import open_execution_hold, release_allocation

    with transaction.atomic():
        payout = _locked_payout(operation.attempt.payout_id)
        PayoutProviderOperation.objects.filter(pk=operation.pk).update(
            status="failed",
            failure_code=reason[:64],
            retry_after=None,
            last_request_at=timezone.now(),
        )
        if operation.funding_allocation_id:
            release_allocation(operation.funding_allocation, reason=reason)
        siblings = PayoutProviderOperation.objects.filter(
            attempt_id=operation.attempt_id, kind="transfer_create"
        )
        accepted = siblings.filter(status__in=["accepted", "reconciled"]).exists()
        attempt = PayoutAttempt.objects.select_for_update(no_key=True).get(
            pk=operation.attempt_id
        )
        if accepted:
            # Part of this obligation is already at the connected account and
            # part was refused. That is not something to retry blindly: the
            # amounts no longer agree, so the next stage is stopped and a person
            # decides.
            open_execution_hold(payout, reason="transfer_slice_failed")
            _transition(
                payout,
                target="failed",
                reason=f"transfer_partial:{reason}"[:64],
                code="needs_attention",
            )
        else:
            attempt.status = PayoutAttempt.Status.FAILED
            attempt.failure_code = reason[:64]
            attempt.result_at = timezone.now()
            attempt.save(update_fields=["status", "failure_code", "result_at"])
            _transition(
                payout,
                target="failed",
                reason=f"transfer_rejected:{reason}"[:64],
                code="needs_attention",
            )


def apply_transfer_accepted(operation, snapshot) -> None:
    """Stripe accepted the Transfer. The money has left the platform balance."""

    now = timezone.now()
    with transaction.atomic():
        payout = _locked_payout(operation.attempt.payout_id)
        current = PayoutProviderOperation.objects.select_for_update(no_key=True).get(
            pk=operation.pk
        )
        if current.provider_object_id and current.provider_object_id != snapshot.transfer_id:
            raise ProviderError(
                "Stripe returned a different transfer for this operation identity."
            )
        first_acceptance = current.status not in ("accepted", "reconciled")
        PayoutProviderOperation.objects.filter(pk=current.pk).update(
            status="accepted",
            provider_object_id=snapshot.transfer_id,
            provider_object_status="accepted",
            provider_request_id=snapshot.request_id[:255],
            balance_transaction_id=snapshot.balance_transaction_id[:255],
            destination_payment_id=snapshot.destination_payment[:255],
            amount_reversed_minor=int(snapshot.amount_reversed_minor),
            failure_code="",
            retry_after=None,
            last_request_at=now,
            last_observed_at=now,
            observation_generation=int(current.observation_generation) + 1,
        )
        if first_acceptance:
            payout_accounting.record_transfer_accepted(
                operation=current,
                payout=payout,
                amount_eur_cents=int(current.amount_minor),
            )
        outstanding = PayoutProviderOperation.objects.filter(
            attempt_id=current.attempt_id, kind="transfer_create"
        ).exclude(status__in=["accepted", "reconciled", "failed"])
        if not outstanding.exists():
            PayoutAttempt.objects.filter(pk=current.attempt_id).exclude(
                status__in=[
                    PayoutAttempt.Status.SENT,
                    PayoutAttempt.Status.SUCCEEDED,
                    PayoutAttempt.Status.RETURNED,
                    PayoutAttempt.Status.CANCELLED,
                ]
            ).update(status=PayoutAttempt.Status.ACCEPTED, result_at=now)
            payout.next_action_at = now
            payout.save(update_fields=["next_action_at", "updated_at"])
            append_event_locked(
                payout, previous=payout.status, reason="transfer_accepted"
            )


def apply_transfer_observation(operation, snapshot) -> str:
    """Reconcile a Transfer's current provider state, including reversals."""

    now = timezone.now()
    with transaction.atomic():
        payout = _locked_payout(operation.attempt.payout_id)
        current = PayoutProviderOperation.objects.select_for_update(no_key=True).get(
            pk=operation.pk
        )
        if current.last_observed_at and current.last_observed_at > now:
            return "superseded_by_newer_observation"
        previously_reversed = int(current.amount_reversed_minor)
        reversed_now = int(snapshot.amount_reversed_minor)
        PayoutProviderOperation.objects.filter(pk=current.pk).update(
            provider_object_id=snapshot.transfer_id,
            provider_object_status="reversed" if snapshot.reversed else "accepted",
            amount_reversed_minor=reversed_now,
            balance_transaction_id=snapshot.balance_transaction_id[:255],
            destination_payment_id=snapshot.destination_payment[:255],
            last_observed_at=now,
            observation_generation=int(current.observation_generation) + 1,
            reconciled_at=now,
        )
        if reversed_now > previously_reversed:
            payout_accounting.record_transfer_reversed(
                operation=current,
                payout=payout,
                amount_eur_cents=reversed_now - previously_reversed,
                sequence=reversed_now,
            )
            append_event_locked(
                payout, previous=payout.status, reason="transfer_reversed"
            )
            return "transfer_reversed"
    return "transfer_observed"


# ---------------------------------------------------------------------------
# Bank payouts
# ---------------------------------------------------------------------------


def _active_allocations(disbursement):
    return list(
        StripeDisbursementAllocation.objects.select_related("payout")
        .filter(disbursement=disbursement, active=True)
        .order_by("pk")
    )


def apply_bank_payout_rejected(operation, disbursement, *, reason: str) -> None:
    """Stripe refused the bank payout before executing it.

    The transferred money is still in the connected account — no ledger movement
    was ever posted for this disbursement — so the correct recovery is another
    *bank payout*, after the destination or the account state is fixed. The
    Transfer is never re-created.
    """

    now = timezone.now()
    with transaction.atomic():
        payout = _locked_payout(operation.attempt.payout_id)
        PayoutProviderOperation.objects.filter(pk=operation.pk).update(
            status="failed",
            failure_code=reason[:64],
            retry_after=None,
            last_request_at=now,
        )
        StripeDisbursement.objects.filter(pk=disbursement.pk).update(
            status=StripeDisbursement.Status.FAILED,
            failure_code=reason[:64],
            failed_at=now,
        )
        StripeDisbursementAllocation.objects.filter(
            disbursement=disbursement, active=True
        ).update(active=False, released_reason=reason[:64], released_at=now)
        _transition(
            payout,
            target="failed",
            reason=f"bank_payout_rejected:{reason}"[:64],
            code="needs_attention",
        )


def apply_bank_payout_accepted(operation, disbursement, snapshot) -> str:
    """Stripe created the bank payout. In transit is not paid."""

    now = timezone.now()
    with transaction.atomic():
        payout = _locked_payout(operation.attempt.payout_id)
        current = StripeDisbursement.objects.select_for_update(no_key=True).get(
            pk=disbursement.pk
        )
        if current.provider_payout_id and current.provider_payout_id != snapshot.payout_id:
            raise ProviderError(
                "Stripe returned a different payout for this operation identity."
            )
        first = current.submitted_at is None
        StripeDisbursement.objects.filter(pk=current.pk).update(
            provider_payout_id=snapshot.payout_id,
            balance_transaction_id=snapshot.balance_transaction_id[:255],
            external_account_id=snapshot.destination[:255]
            or current.external_account_id,
            submitted_at=current.submitted_at or now,
        )
        PayoutProviderOperation.objects.filter(pk=operation.pk).update(
            status="accepted",
            provider_object_id=snapshot.payout_id,
            provider_object_status=snapshot.status[:32],
            provider_request_id=snapshot.request_id[:255],
            balance_transaction_id=snapshot.balance_transaction_id[:255],
            failure_code="",
            retry_after=None,
            last_request_at=now,
        )
        if first:
            current.refresh_from_db()
            payout_accounting.record_bank_payout_submitted(
                disbursement=current, allocations=_active_allocations(current)
            )
            # Recorded as its own fact even when the aggregate is already
            # `processing`: "the bank payout was submitted" is a different
            # event from "the transfer was accepted", and the timeline is what
            # an operator reads to tell them apart.
            append_event_locked(
                payout, previous=payout.status, reason="bank_payout_submitted"
            )
        _transition(
            payout, target="processing", reason="bank_payout_submitted", code="processing"
        )
    return apply_bank_payout_observation(
        StripeDisbursement.objects.get(pk=disbursement.pk), snapshot, observed_at=now
    )


def apply_bank_payout_observation(disbursement, snapshot, *, observed_at=None) -> str:
    """The single convergence point for every bank-payout status source.

    Called with exactly the same arguments whether the fact arrived as an HTTP
    response, a `payout.*` webhook, a polling job, a sweeper pass or an
    operator's refresh. Ordering comes from the observation clock, never from
    the order events happened to arrive in.
    """

    observed_at = observed_at or timezone.now()
    target = PROVIDER_STATUS.get(snapshot.status)
    if target is None:
        logger.warning(
            "finance.bank_payout_unknown_status disbursement=%s status=%s",
            disbursement.public_reference,
            snapshot.status,
        )
        return "unknown_provider_status"

    with transaction.atomic():
        # Canonical lock order, and the reason this reads awkwardly: Deal
        # lifecycle and Payout come *before* the disbursement, so the payout ids
        # have to be read unlocked first. `apply_bank_payout_accepted` reaches
        # these same two rows from an HTTP response while a `payout.*` webhook
        # reaches them from here; taking them in opposite orders is a deadlock
        # between two paths that will routinely run at the same moment.
        payout_ids = sorted(
            set(
                StripeDisbursementAllocation.objects.filter(
                    disbursement_id=disbursement.pk
                ).values_list("payout_id", flat=True)
            )
        )
        for payout_id in payout_ids:
            _locked_payout(payout_id)
        current = StripeDisbursement.objects.select_for_update(no_key=True).get(
            pk=disbursement.pk
        )
        if current.last_observed_at and current.last_observed_at > observed_at:
            return "superseded_by_newer_observation"
        allocations = _active_allocations(current)
        if not allocations:
            allocations = list(
                StripeDisbursementAllocation.objects.select_related("payout")
                .filter(disbursement=current)
                .order_by("pk")
            )
        # Membership revalidated after locking. Allocations are written only
        # under the payout lock so this cannot change in practice, but a
        # silently unlocked payout is not something to assume away.
        for payout_id in sorted(
            {row.payout_id for row in allocations} - set(payout_ids)
        ):
            _locked_payout(payout_id)

        was_paid = current.status == StripeDisbursement.Status.PAID
        fields = {
            "status": target,
            "provider_payout_id": snapshot.payout_id[:255],
            "failure_code": snapshot.failure_code[:64],
            "failure_balance_transaction_id": snapshot.failure_balance_transaction_id[
                :255
            ],
            "last_observed_at": observed_at,
            "observation_generation": int(current.observation_generation) + 1,
        }
        if snapshot.balance_transaction_id:
            fields["balance_transaction_id"] = snapshot.balance_transaction_id[:255]
        if snapshot.arrival_date:
            fields["arrival_estimate"] = datetime.fromtimestamp(
                snapshot.arrival_date, tz=UTC
            )
        note = "bank_payout_observed"

        if target == StripeDisbursement.Status.PAID:
            fields["paid_at"] = current.paid_at or observed_at
            note = "bank_payout_paid"
        elif target == StripeDisbursement.Status.FAILED and was_paid:
            # A genuine late bank return. The paid history is preserved and a
            # compensating entry restores the obligation.
            fields["status"] = StripeDisbursement.Status.RETURNED
            fields["returned_at"] = observed_at
            note = "bank_payout_returned"
        elif target in (
            StripeDisbursement.Status.FAILED,
            StripeDisbursement.Status.CANCELED,
        ):
            fields["failed_at"] = observed_at
            note = (
                "bank_payout_failed"
                if target == StripeDisbursement.Status.FAILED
                else "bank_payout_canceled"
            )
        StripeDisbursement.objects.filter(pk=current.pk).update(**fields)
        current.refresh_from_db()

        if note == "bank_payout_paid" and not was_paid:
            payout_accounting.record_bank_payout_paid(
                disbursement=current, allocations=allocations
            )
        elif note == "bank_payout_returned":
            payout_accounting.record_bank_payout_returned(
                disbursement=current, allocations=allocations
            )
        elif note in ("bank_payout_failed", "bank_payout_canceled"):
            if current.submitted_at is not None:
                payout_accounting.record_bank_payout_failed(
                    disbursement=current, allocations=allocations
                )

        if note in ("bank_payout_returned", "bank_payout_failed", "bank_payout_canceled"):
            # The transferred money is back in the connected account, so the
            # allocation is released and a *bank payout only* retry becomes
            # legitimate. The Transfer is untouched and is never re-created.
            StripeDisbursementAllocation.objects.filter(
                disbursement=current, active=True
            ).update(
                active=False,
                released_reason=note[:64],
                released_at=observed_at,
            )

        for allocation in allocations:
            _apply_payout_side(allocation, note=note, snapshot=snapshot, at=observed_at)
    return note


#: Where each reconciled bank-payout fact leaves the local aggregate.
_PAYOUT_TARGET = {
    "bank_payout_paid": "paid",
    "bank_payout_failed": "failed",
    "bank_payout_canceled": "failed",
    "bank_payout_returned": "failed",
}


def _apply_payout_side(allocation, *, note: str, snapshot, at) -> None:
    payout = Payout.objects.select_for_update(no_key=True).get(pk=allocation.payout_id)
    target = _PAYOUT_TARGET.get(note)
    if note == "bank_payout_observed" and snapshot.status == "in_transit":
        target = "sent"
    if target is None or payout.status == target:
        # Either the provider said nothing that changes the local state, or a
        # duplicate delivery is re-reporting a fact already recorded. Neither
        # writes a second ledger effect or a second notification.
        return
    attempt = (
        PayoutAttempt.objects.select_for_update(no_key=True).get(pk=allocation.attempt_id)
        if allocation.attempt_id
        else None
    )
    if note == "bank_payout_paid":
        payout.paid_at = payout.paid_at or at
        payout.settled_at = at
        payout.settlement_basis = "stripe_bank_payout"
        payout.provider_payout_id = snapshot.payout_id[:255]
        payout.failure_code = ""
        payout.save(
            update_fields=[
                "paid_at",
                "settled_at",
                "settlement_basis",
                "provider_payout_id",
                "failure_code",
                "updated_at",
            ]
        )
        if attempt is not None:
            attempt.status = PayoutAttempt.Status.SUCCEEDED
            attempt.result_at = at
            attempt.save(update_fields=["status", "result_at"])
        _transition(payout, target="paid", reason="bank_payout_paid", code="paid")
        return
    if note == "bank_payout_observed" and snapshot.status == "in_transit":
        payout.sent_at = payout.sent_at or at
        payout.save(update_fields=["sent_at", "updated_at"])
        if attempt is not None and attempt.status == PayoutAttempt.Status.ACCEPTED:
            attempt.status = PayoutAttempt.Status.SENT
            attempt.save(update_fields=["status"])
        _transition(payout, target="sent", reason="bank_payout_in_transit", code="sent")
        return
    if note in ("bank_payout_failed", "bank_payout_canceled", "bank_payout_returned"):
        payout.failure_code = (snapshot.failure_code or note)[:64]
        # **Not** re-armed for automatic dispatch.
        #
        # A bank payout fails for a reason the platform cannot fix by trying
        # again: a closed account, a wrong holder name, an unusable IBAN. The
        # destination is Stripe's to hold and the Traveler's to correct, so an
        # automatic retry would hammer the provider against the same broken
        # account until someone noticed. The block reason is what stops the
        # worker and the sweeper from picking this up; an operator's audited
        # `Retry bank payout` is what clears it, once the destination has
        # actually been fixed.
        payout.block_reason = (snapshot.failure_code or note)[:64]
        payout.next_action_at = None
        payout.save(
            update_fields=[
                "failure_code",
                "block_reason",
                "next_action_at",
                "updated_at",
            ]
        )
        if attempt is not None:
            # The Transfer's money is back at the connected account, so the
            # attempt returns to `accepted`: the funding transfer stands and
            # only the bank stage has to be retried.
            attempt.status = PayoutAttempt.Status.ACCEPTED
            attempt.failure_code = (snapshot.failure_code or note)[:64]
            attempt.save(update_fields=["status", "failure_code"])
        _transition(
            payout,
            target="failed",
            reason=note,
            code="returned" if note == "bank_payout_returned" else "needs_attention",
        )


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------


def reconcile_payout(payout_id: int, *, gateway=None) -> str:
    """Ask the provider what actually happened to every live operation.

    The safety net behind the webhooks. It runs whether or not execution is
    enabled, because turning off new instructions must never stop the system
    finding out what the existing ones did.
    """

    gateway = gateway or get_connect_gateway()
    notes = []
    operations = (
        PayoutProviderOperation.objects.select_related(
            "attempt__payout", "disbursement__account", "funding_allocation"
        )
        .filter(
            attempt__payout_id=payout_id,
            kind="transfer_create",
            status__in=["accepted", "committed", "unknown"],
        )
        .order_by("sequence")
    )
    for operation in operations:
        if not operation.provider_object_id:
            notes.append(f"{operation.kind}_{operation.status}")
            continue
        try:
            snapshot = gateway.retrieve_transfer(operation.provider_object_id)
        except ProviderUnavailable as exc:
            notes.append(f"transfer_unavailable:{exc.code}")
            continue
        notes.append(apply_transfer_observation(operation, snapshot))

    disbursements = (
        StripeDisbursement.objects.select_related("account")
        .filter(
            allocations__payout_id=payout_id,
            status__in=[
                StripeDisbursement.Status.COMMITTED,
                StripeDisbursement.Status.UNKNOWN,
                StripeDisbursement.Status.PENDING,
                StripeDisbursement.Status.IN_TRANSIT,
                StripeDisbursement.Status.PAID,
            ],
        )
        .distinct()
    )
    for disbursement in disbursements:
        if not disbursement.provider_payout_id:
            notes.append(f"disbursement_{disbursement.status}")
            continue
        try:
            snapshot = gateway.retrieve_bank_payout(
                account_id=disbursement.account.provider_account_id,
                payout_id=disbursement.provider_payout_id,
            )
        except ProviderUnavailable as exc:
            notes.append(f"bank_payout_unavailable:{exc.code}")
            continue
        notes.append(apply_bank_payout_observation(disbursement, snapshot))
    return ",".join(notes) or "nothing_to_reconcile"


def freeze_reason_for(payout) -> str:
    """A safe machine reason for why this payout is not progressing."""

    hold = active_holds(payout).order_by("pk").first()
    if hold is not None:
        return f"hold_{hold.kind}"
    return payout.block_reason or ""
