"""Automatic EUR payout execution: reserve, commit, send, recover.

This is the module that actually spends money, so it is written around one
question: *after a crash, can this code tell the difference between "nothing was
sent" and "something might have been sent"?* Everything else follows from that.

The protocol is H0's — **record intent → commit → provider call → reconcile** —
and it is three transactions, not one:

1. **Reserve.** Under the Deal lifecycle aggregate, plan which Stripe charges
   support this obligation, write immutable `PayoutFundingAllocation` rows, a
   `PayoutAttempt` and one `PayoutProviderOperation` per slice, all `prepared`,
   and move the Payout to `scheduled`. Nothing external exists yet, so this is
   fully revocable: a crash here leaves reservations a later run resumes or an
   authorised service releases.

2. **Commit.** A short guarded transition to `dispatch_committed` immediately
   before the first byte leaves. **This is the linearization point.** From here
   the amount is treated as externally exposed even though no HTTP request has
   been made yet, because a crash between this commit and the response is
   indistinguishable from a lost answer.

3. **Send and reconcile.** Provider I/O happens with no database lock held. A
   confirmed answer is recorded once. A timeout is `unknown` — never "failed,
   safe to resend with a new key" — and is resolved by replaying the *same*
   idempotency key inside Stripe's retention window, or by a bounded search
   past it, or by blocking for Finance.

Two external operations, not one. A platform Transfer moves ShipTrip's EUR into
the Traveler's connected account; a connected-account bank Payout moves it to
their bank. A Traveler is paid when the second one settles, and a failed bank
payout is retried by creating another bank payout — never by creating the
Transfer again, because the Transfer's money is already at the connected
account.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.financial_locks import lock_deal_lifecycle
from .models import (
    FinanceHold,
    PayoutAttempt,
    PayoutFundingAllocation,
    PayoutFundingRelease,
    PayoutProviderOperation,
    PaymentAttempt,
    PaymentOrder,
    Payout,
    StripeDisbursement,
    StripeDisbursementAllocation,
)
from .payout_accounts import expected_mode, evaluate_readiness, refresh_account
from .payout_domain import (
    active_holds,
    append_event_locked,
    source_available_cents,
)
from .payout_snapshots import source_order_ids
from .policy import InvalidPaymentPolicy, phase3_policy
from .providers.base import (
    ProviderCheckoutRejected,
    ProviderError,
    ProviderNotConfigured,
    ProviderUnavailable,
)
from .providers.stripe_connect import get_connect_gateway

logger = logging.getLogger(__name__)

#: Stripe's published minimum for a standard EUR payout in France is 1 EUR.
#: Configurable so a validated DE/ES rollout is a settings change rather than a
#: code change, and floored at one cent so a misconfiguration cannot authorise a
#: zero-value provider payout.
DEFAULT_MINIMUM_PAYOUT_EUR_CENTS = 100

#: Stripe keeps an idempotency key's stored result for at least 24 hours. H0
#: allows an automatic byte-identical replay only inside a conservative window
#: below that; past it the answer must be *retrieved*, never re-POSTed.
IDEMPOTENT_REPLAY_SECONDS = 23 * 3600

#: How long one worker owns an in-flight external operation. A second worker
#: that finds a fresher lease defers rather than racing the same POST.
OPERATION_LEASE_SECONDS = 120

#: How long a readiness observation may be reused before a dispatch re-reads it.
READINESS_MAX_AGE_SECONDS = 15 * 60


class PayoutExecutionError(RuntimeError):
    """A refusal that carries a safe machine reason."""

    code = "payout_execution_error"

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        if code:
            self.code = code


class PayoutDeferred(PayoutExecutionError):
    """An expected wait. Never a failure, never a consumed retry budget.

    Protection still open, onboarding incomplete, transferred funds still
    pending at the provider, another worker holding the operation lease: all of
    these mean "not yet", and treating them as errors would burn a payout's
    retry budget on the system working correctly.
    """

    code = "payout_deferred"

    def __init__(self, message: str, *, code: str | None = None, delay=None):
        super().__init__(message, code=code)
        self.delay = delay or timedelta(minutes=15)


class PayoutBlocked(PayoutExecutionError):
    """The obligation stands but cannot progress without a human or a change."""

    code = "payout_blocked"


class PayoutUnresolved(PayoutExecutionError):
    """An external operation's outcome is unknown and could not be established.

    Deliberately not retryable-by-resending. The money may already be gone, so
    this ends in a Finance investigation rather than a second instruction.
    """

    code = "payout_unresolved"


# ---------------------------------------------------------------------------
# Configuration gates
# ---------------------------------------------------------------------------


def minimum_payout_cents() -> int:
    configured = int(
        getattr(
            settings,
            "STRIPE_CONNECT_MINIMUM_PAYOUT_EUR_CENTS",
            DEFAULT_MINIMUM_PAYOUT_EUR_CENTS,
        )
    )
    return max(1, configured)


def execution_enabled() -> tuple[bool, str]:
    """Both switches H0 requires, and the reason when either is off.

    The deployment flag says this release may move money at all; the versioned
    business setting says the *business* has authorised it. Neither alone is
    enough, and a malformed settings revision fails closed rather than
    defaulting to on.
    """

    if not getattr(settings, "PAYOUT_PROFILES_ENABLED", False):
        return False, "payout_profiles_disabled"
    if not getattr(settings, "STRIPE_CONNECT_ENABLED", False):
        return False, "stripe_connect_disabled"
    if not getattr(settings, "STRIPE_CONNECT_PAYOUTS_ENABLED", False):
        return False, "payout_execution_disabled"
    try:
        authorised = phase3_policy().payout.auto_stripe_enabled
    except InvalidPaymentPolicy:
        return False, "payment_policy_invalid"
    except Exception:  # noqa: BLE001 - an unreadable policy never means "yes"
        return False, "payment_policy_unavailable"
    if not authorised:
        return False, "auto_stripe_disabled"
    return True, ""


def require_execution_enabled() -> None:
    enabled, reason = execution_enabled()
    if not enabled:
        raise PayoutDeferred(
            "Automatic EUR payout execution is switched off.",
            code=reason,
            delay=timedelta(hours=6),
        )


# ---------------------------------------------------------------------------
# Identity: stable keys and immutable request fingerprints
# ---------------------------------------------------------------------------


def _platform_id() -> str:
    return str(getattr(settings, "STRIPE_CONNECT_PLATFORM_ACCOUNT_ID", "") or "")


def safe_reason(exc) -> str:
    """The most specific safe code a provider failure carries.

    `provider_code` is Stripe's own word for what happened — `timeout`, `429`,
    `account_invalid` — and it is what an operator actually needs. The class
    code is the fallback, so a reason is never empty.
    """

    return str(getattr(exc, "provider_code", "") or getattr(exc, "code", "") or "error")[
        :64
    ]


def _fingerprint(*parts) -> str:
    return hashlib.sha256(
        json.dumps(list(parts), sort_keys=True, default=str).encode()
    ).hexdigest()


def transfer_group(payout) -> str:
    """Opaque, stable, and derived from nothing a person can read."""

    return f"shiptrip_payout_{payout.public_reference}"


def _attempt_key(payout, sequence: int) -> str:
    return f"payout_dispatch:{expected_mode()}:{payout.public_reference}:v{sequence}"


def _allocation_key(payout, attempt_sequence: int, source_attempt_id: int) -> str:
    return (
        f"alloc:{payout.public_reference}:a{attempt_sequence}:s{source_attempt_id}"
    )


def _transfer_key(payout, attempt_sequence: int, source_attempt_id: int) -> str:
    return (
        f"tr:{expected_mode()}:{payout.public_reference}"
        f":a{attempt_sequence}:s{source_attempt_id}"
    )


def _bank_payout_key(disbursement) -> str:
    return f"po:{expected_mode()}:{disbursement.public_reference}"


def _operation_metadata(operation, payout) -> dict:
    """Opaque internal references only. No names, no Deal contents, no emails."""

    return {
        "shiptrip_operation": str(operation.public_reference),
        "shiptrip_payout": str(payout.public_reference),
        "shiptrip_env": expected_mode(),
    }


# ---------------------------------------------------------------------------
# Source funding: which Stripe charges actually support this obligation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceSlice:
    source_attempt: object
    amount_eur_cents: int
    purpose: str


@dataclass(slots=True)
class DispatchPlan:
    payout_id: int
    attempt_id: int
    attempt_sequence: int
    fencing_generation: int
    operation_ids: list = field(default_factory=list)


def plan_source_slices(payout, *, balance_order, locked_sources) -> list[SourceSlice]:
    """Deterministically cover the obligation from eligible Stripe captures.

    H0 fixes the order — the balance capture first, then the credited posting
    deposit, then bound Boost purchases by id — so two workers, a retry and a
    Finance review all compute the same answer for the same state.

    Every candidate must be a succeeded, applied, same-mode Stripe capture, and
    every slice is bounded by what that capture still has after refunds and
    after any live reservation on it. Nothing here borrows another Traveler's
    earmarked money, and a shortfall is reported as a shortfall rather than
    quietly paying part of a normal obligation.
    """

    needed = int(payout.amount_eur_cents)
    if needed <= 0:
        return []
    order_ids = source_order_ids(balance_order)
    by_order = {order_id: [] for order_id in order_ids}
    for attempt in locked_sources:
        if attempt.order_id in by_order:
            by_order[attempt.order_id].append(attempt)

    slices: list[SourceSlice] = []
    credited_budget = int(balance_order.credited_eur_cents)
    for order_id in order_ids:
        if needed <= 0:
            break
        candidates = sorted(
            by_order.get(order_id, []),
            key=lambda row: (row.succeeded_at or row.created_at, row.pk),
        )
        for source in candidates:
            if needed <= 0:
                break
            if (
                source.status != "succeeded"
                or source.succeeded_at is None
                or source.is_unapplied
                or source.provider != "stripe"
                or source.provider_mode != payout.provider_mode
                or source.payment_currency != "EUR"
            ):
                continue
            available = source_available_cents(source)
            if order_id == balance_order.credit_source_id:
                # A posting deposit only supports the Deal to the extent it was
                # actually credited into the balance. The rest of that capture
                # is still the Sender's and may be owed back to them.
                available = min(available, credited_budget)
            if available <= 0:
                continue
            take = min(available, needed)
            slices.append(
                SourceSlice(
                    source_attempt=source,
                    amount_eur_cents=take,
                    purpose=source.order.purpose,
                )
            )
            if order_id == balance_order.credit_source_id:
                credited_budget -= take
            needed -= take
    if needed > 0:
        raise PayoutBlocked(
            "This obligation is not fully supported by eligible Stripe funds.",
            code="funding_route_unavailable",
        )
    return slices


def resolve_source_charge(source_attempt, *, gateway) -> str:
    """Find and verify the `ch_…` a Transfer may name as its source.

    Stripe's `source_transaction` takes a **charge** id. ShipTrip's checkout
    rail stores the PaymentIntent, so the charge has to be resolved once and
    persisted. Passing a `pi_…` here is the mistake this function exists to make
    impossible, and the verification below is what stops a resolved charge from
    being the wrong one: it must be succeeded, captured, EUR, in this
    deployment's mode, belong to the recorded PaymentIntent, and still have
    enough unrefunded amount behind it.
    """

    charge_id = str(source_attempt.provider_charge_id or "")
    if not charge_id.startswith("ch_"):
        intent = str(source_attempt.provider_payment_id or "")
        if not intent.startswith("pi_"):
            raise PayoutBlocked(
                "This capture has no resolvable Stripe charge.",
                code="source_charge_unresolved",
            )
        charge_id = gateway.latest_charge_for_intent(intent)
        if not charge_id:
            raise PayoutBlocked(
                "Stripe did not identify a single succeeded charge for this payment.",
                code="source_charge_unresolved",
            )
    charge = gateway.retrieve_charge(charge_id)
    expected_live = expected_mode() == "live"
    if (
        not charge.is_transferable
        or charge.currency != "EUR"
        or (charge.livemode is not None and charge.livemode is not expected_live)
        or (
            source_attempt.provider_payment_id
            and charge.payment_intent_id
            and charge.payment_intent_id != source_attempt.provider_payment_id
        )
        or charge.net_available_minor < int(source_attempt.amount_eur_cents)
        - _refunded_minor(source_attempt)
    ):
        raise PayoutBlocked(
            "The Stripe charge behind this capture cannot support a transfer.",
            code="source_charge_ineligible",
        )
    if source_attempt.provider_charge_id != charge.charge_id:
        PaymentAttempt.objects.filter(pk=source_attempt.pk).update(
            provider_charge_id=charge.charge_id
        )
        source_attempt.provider_charge_id = charge.charge_id
    return charge.charge_id


def _refunded_minor(source_attempt) -> int:
    from .payout_domain import source_refunded_cents

    return source_refunded_cents(source_attempt)


# ---------------------------------------------------------------------------
# Locking
# ---------------------------------------------------------------------------


def _lock_payout_aggregate(payout_id: int):
    """Canonical order: Deal lifecycle → orders → captures → Payout.

    Exactly the order `apps.core.financial_locks` documents and
    `payout_domain.allocate_source` already takes, so a dispatch, a refund, a
    dispute and a settlement all approach the same rows from the same
    direction.
    """

    seed = Payout.objects.get(pk=payout_id)
    lock_deal_lifecycle(seed.deal_id)
    balance = (
        PaymentOrder.objects.filter(deal_id=seed.deal_id, purpose="deal_balance")
        .exclude(status="cancelled")
        .order_by("-pk")
        .first()
    )
    if balance is None:
        raise PayoutBlocked(
            "This Deal has no live balance obligation.", code="balance_order_missing"
        )
    order_ids = source_order_ids(balance)
    list(
        PaymentOrder.objects.select_for_update(no_key=True)
        .filter(pk__in=order_ids)
        .order_by("pk")
    )
    sources = list(
        PaymentAttempt.objects.select_for_update(no_key=True)
        .select_related("order")
        .filter(order_id__in=order_ids)
        .order_by("pk")
    )
    payout = (
        # `of=("self",)` because `active_instruction_version` is nullable and
        # PostgreSQL refuses a row lock on the nullable side of an outer join.
        # Only the Payout row needs locking; the destination is read, and its
        # own row is protected by the immutable-version contract.
        Payout.objects.select_for_update(no_key=True, of=("self",))
        .select_related("deal", "active_instruction_version__stripe_account")
        .get(pk=payout_id)
    )
    balance.refresh_from_db()
    return payout, balance, sources


# ---------------------------------------------------------------------------
# Gate checks
# ---------------------------------------------------------------------------


def _assert_dispatchable(payout) -> None:
    """Every condition H0 requires, rechecked under the aggregate lock.

    Deliberately verbose and deliberately not short-circuited into one boolean:
    each refusal has its own machine reason, because "this payout did not go
    out" is a question an operator has to be able to answer precisely.
    """

    from .mode_safety import require_object_mode

    require_object_mode(payout.provider_mode)
    if not payout.snapshot_version:
        raise PayoutBlocked("Legacy payout requires reviewed migration.", code="legacy")
    if payout.method != "stripe_transfer" or payout.payout_currency != "EUR":
        raise PayoutBlocked("This payout is not on the Stripe EUR rail.", code="rail")
    if payout.provider_mode != expected_mode() or payout.provider_mode not in (
        "test",
        "live",
    ):
        raise PayoutBlocked("Payout mode does not match this deployment.", code="mode")
    if payout.status in ("paid", "cancelled"):
        raise PayoutBlocked("Terminal payout.", code=f"payout_{payout.status}")
    if payout.status == "frozen":
        raise PayoutBlocked("A hold or dispute freezes this payout.", code="frozen")
    if payout.block_reason:
        raise PayoutBlocked(
            "This payout carries a block reason.", code=payout.block_reason
        )
    if int(payout.amount_eur_cents) <= 0:
        raise PayoutBlocked("No positive obligation remains.", code="zero_award")
    if not payout.eligible_at or payout.status not in (
        "eligible",
        "scheduled",
        "processing",
        "sent",
        "failed",
    ):
        raise PayoutDeferred(
            "This payout has not been released for settlement.",
            code=f"payout_{payout.status}",
        )
    deal = payout.deal
    if deal.delivery_confirmed_at is None:
        raise PayoutDeferred("Delivery is not confirmed.", code="delivery_not_confirmed")
    if deal.protection_ends_at is None:
        raise PayoutDeferred("Protection is not armed.", code="protection_not_armed")
    if timezone.now() < deal.protection_ends_at:
        raise PayoutDeferred(
            "The 48-hour protection window is still open.",
            code="protection_open",
            delay=deal.protection_ends_at - timezone.now(),
        )
    from apps.deals.arrival import payout_release_gate_at

    gate = payout_release_gate_at(deal)
    if gate is not None and timezone.now() < gate:
        raise PayoutDeferred("The funded arrival floor is still open.", code="scheduled_arrival_floor_open", delay=gate - timezone.now())
    if active_holds(payout).exists():
        raise PayoutBlocked("A Finance hold is active.", code="finance_hold_active")
    from apps.disputes.models import Dispute

    if deal.disputes.filter(status__in=Dispute.ACTIVE_STATUSES).exists():
        raise PayoutBlocked("A dispute is active.", code="dispute_active")
    version = payout.active_instruction_version
    account = version.stripe_account if version else None
    if not account or not account.active:
        raise PayoutBlocked("No connected account is bound.", code="account_missing")
    if (
        account.traveler_id != payout.traveler_id
        or account.provider_mode != payout.provider_mode
        or account.platform_id != _platform_id()
    ):
        raise PayoutBlocked("Destination ownership mismatch.", code="account_mismatch")
    verdict = evaluate_readiness(account)
    if not verdict.ready:
        raise PayoutDeferred(
            "The connected account is not ready to receive earnings.",
            code=f"account_{verdict.reason or verdict.status}",
            delay=timedelta(hours=6),
        )


def _refresh_readiness(payout):
    """Read authoritative provider readiness with no database lock held."""

    version = payout.active_instruction_version
    account = version.stripe_account if version else None
    if account is None:
        return None
    stale = (
        account.readiness_checked_at is None
        or (timezone.now() - account.readiness_checked_at).total_seconds()
        > READINESS_MAX_AGE_SECONDS
    )
    if not stale:
        return account
    try:
        account, _ = refresh_account(account)
    except ProviderUnavailable as exc:
        # A provider outage is never a reason to reroute, to fall back, or to
        # dispatch on stale readiness. It is a reason to come back later.
        raise PayoutDeferred(
            "Stripe readiness could not be refreshed.",
            code=f"readiness_{exc.code}"[:64],
            delay=timedelta(minutes=30),
        ) from exc
    except (ProviderNotConfigured, ProviderError) as exc:
        raise PayoutBlocked(
            "Stripe refused the readiness refresh.", code=f"readiness_{exc.code}"[:64]
        ) from exc
    return account


# ---------------------------------------------------------------------------
# Stage 1 — reserve
# ---------------------------------------------------------------------------


def _reserve_dispatch(payout_id: int, charge_ids: dict) -> DispatchPlan:
    """Write the whole intent, still revocable, in one transaction."""

    with transaction.atomic():
        payout, balance, sources = _lock_payout_aggregate(payout_id)
        _assert_dispatchable(payout)

        live = payout.attempts.filter(
            status__in=["dispatch_committed", "unknown", "accepted", "sent"]
        ).first()
        if live is not None:
            return _plan_from_attempt(live)
        prepared = payout.attempts.filter(status="prepared").first()
        if prepared is not None:
            return _plan_from_attempt(prepared)

        slices = plan_source_slices(
            payout, balance_order=balance, locked_sources=sources
        )
        missing = [
            s.source_attempt.pk
            for s in slices
            if not str(charge_ids.get(s.source_attempt.pk, "")).startswith("ch_")
        ]
        if missing:
            # The charge ids are resolved before this transaction opens, so a
            # gap here means the plan changed underneath the provider read. Do
            # not guess: recompute on the next run.
            raise PayoutDeferred(
                "Source charge identity changed while planning.",
                code="source_plan_changed",
                delay=timedelta(minutes=1),
            )

        sequence = payout.attempts.count() + 1
        version = payout.active_instruction_version
        attempt = PayoutAttempt.objects.create(
            payout=payout,
            sequence=sequence,
            instruction_version=version,
            amount_revision=payout.amount_revisions.order_by("-revision").first(),
            amount_eur_cents=payout.amount_eur_cents,
            currency="EUR",
            rail="stripe_transfer",
            provider_mode=payout.provider_mode,
            status=PayoutAttempt.Status.PREPARED,
            idempotency_key=_attempt_key(payout, sequence),
            request_fingerprint=_fingerprint(
                "payout_dispatch",
                str(payout.public_reference),
                payout.amount_eur_cents,
                "EUR",
                str(version.public_reference),
                version.stripe_account.provider_account_id,
                payout.provider_mode,
            ),
        )
        operation_ids = []
        for index, item in enumerate(slices, start=1):
            allocation = PayoutFundingAllocation.objects.create(
                allocation_key=_allocation_key(
                    payout, sequence, item.source_attempt.pk
                ),
                payout=payout,
                attempt=attempt,
                source_attempt=item.source_attempt,
                source_charge_id=charge_ids[item.source_attempt.pk],
                provider="stripe",
                provider_mode=payout.provider_mode,
                purpose=item.purpose,
                currency="EUR",
                amount_eur_cents=item.amount_eur_cents,
            )
            operation = PayoutProviderOperation.objects.create(
                attempt=attempt,
                kind="transfer_create",
                account_scope=_platform_id(),
                provider_mode=payout.provider_mode,
                sequence=index,
                idempotency_key=_transfer_key(
                    payout, sequence, item.source_attempt.pk
                ),
                request_fingerprint=_fingerprint(
                    "transfer_create",
                    item.amount_eur_cents,
                    "EUR",
                    allocation.source_charge_id,
                    version.stripe_account.provider_account_id,
                    _platform_id(),
                    payout.provider_mode,
                    payout.state_version,
                    str(version.public_reference),
                ),
                amount_minor=item.amount_eur_cents,
                currency="EUR",
                funding_allocation=allocation,
            )
            operation_ids.append(operation.pk)

        if payout.status != "scheduled":
            previous = payout.status
            payout.status = "scheduled"
            payout.next_action_at = timezone.now()
            payout.save(update_fields=["status", "next_action_at", "updated_at"])
            append_event_locked(payout, previous=previous, reason="dispatch_reserved")
        return DispatchPlan(
            payout_id=payout.pk,
            attempt_id=attempt.pk,
            attempt_sequence=sequence,
            fencing_generation=attempt.fencing_generation,
            operation_ids=operation_ids,
        )


def _plan_from_attempt(attempt) -> DispatchPlan:
    return DispatchPlan(
        payout_id=attempt.payout_id,
        attempt_id=attempt.pk,
        attempt_sequence=attempt.sequence,
        fencing_generation=attempt.fencing_generation,
        operation_ids=list(
            attempt.operations.filter(kind="transfer_create")
            .exclude(status__in=["accepted", "reconciled"])
            .order_by("sequence")
            .values_list("pk", flat=True)
        ),
    )


# ---------------------------------------------------------------------------
# Stage 2 — commit (the linearization point)
# ---------------------------------------------------------------------------


def _commit_dispatch(plan: DispatchPlan) -> DispatchPlan:
    """Guarded transition to `dispatch_committed`, then nothing is safe to undo.

    Short on purpose: every gate was rechecked a moment ago under the same lock
    order, and this transaction exists only to make the commitment durable
    before the first byte leaves. After it commits, a crash is
    indistinguishable from a lost response and the amount stays reserved until
    the provider is asked.
    """

    with transaction.atomic():
        payout, _, _ = _lock_payout_aggregate(plan.payout_id)
        _assert_dispatchable(payout)
        attempt = PayoutAttempt.objects.select_for_update(no_key=True).get(
            pk=plan.attempt_id
        )
        if attempt.status == PayoutAttempt.Status.PREPARED:
            attempt.status = PayoutAttempt.Status.DISPATCH_COMMITTED
            attempt.committed_at = timezone.now()
            attempt.fencing_generation = int(attempt.fencing_generation) + 1
            attempt.save(
                update_fields=["status", "committed_at", "fencing_generation"]
            )
        elif attempt.status not in (
            PayoutAttempt.Status.DISPATCH_COMMITTED,
            PayoutAttempt.Status.UNKNOWN,
            PayoutAttempt.Status.ACCEPTED,
            PayoutAttempt.Status.SENT,
        ):
            raise PayoutBlocked(
                "This dispatch attempt is no longer live.",
                code=f"attempt_{attempt.status}",
            )
        now = timezone.now()
        operations = list(
            PayoutProviderOperation.objects.select_for_update(no_key=True)
            .filter(pk__in=plan.operation_ids)
            .order_by("sequence")
        )
        claimable = []
        for operation in operations:
            if operation.status in ("accepted", "reconciled", "failed"):
                continue
            if operation.retry_after and operation.retry_after > now:
                raise PayoutDeferred(
                    "Another worker holds this operation.",
                    code="operation_leased",
                    delay=operation.retry_after - now,
                )
            PayoutProviderOperation.objects.filter(pk=operation.pk).update(
                status="committed" if operation.status == "prepared" else operation.status,
                first_request_at=operation.first_request_at or now,
                last_request_at=now,
                retry_after=now + timedelta(seconds=OPERATION_LEASE_SECONDS),
            )
            claimable.append(operation.pk)
        if payout.status in ("eligible", "scheduled", "failed"):
            previous = payout.status
            payout.status = "processing"
            payout.next_action_at = now
            payout.save(update_fields=["status", "next_action_at", "updated_at"])
            append_event_locked(payout, previous=previous, reason="dispatch_committed")
            from .payout_reconciliation import notify_payout_state

            notify_payout_state(payout, "processing")
        plan.operation_ids = claimable
        plan.fencing_generation = attempt.fencing_generation
        return plan


# ---------------------------------------------------------------------------
# Stage 3 — send the Transfers
# ---------------------------------------------------------------------------


def _send_transfers(plan: DispatchPlan, *, gateway) -> str:
    from .payout_reconciliation import (
        apply_transfer_accepted,
        apply_transfer_rejected,
        mark_operation_unknown,
    )

    results = []
    for operation_id in plan.operation_ids:
        operation = PayoutProviderOperation.objects.select_related(
            "attempt__payout", "funding_allocation"
        ).get(pk=operation_id)
        payout = operation.attempt.payout
        allocation = operation.funding_allocation
        account = operation.attempt.instruction_version.stripe_account
        try:
            snapshot = gateway.create_transfer(
                amount_minor=int(operation.amount_minor),
                destination=account.provider_account_id,
                source_transaction=allocation.source_charge_id,
                transfer_group=transfer_group(payout),
                idempotency_key=operation.idempotency_key,
                metadata=_operation_metadata(operation, payout),
            )
        except ProviderUnavailable as exc:
            # Timeout, 429, 5xx or an idempotency key still in flight. Stripe
            # may already have created this Transfer, so it is `unknown` and it
            # keeps its reservation and its key.
            mark_operation_unknown(operation, reason=safe_reason(exc))
            results.append(f"transfer_unknown:{safe_reason(exc)}")
            continue
        except (ProviderCheckoutRejected, ProviderNotConfigured) as exc:
            # Stripe validated and refused before executing. This is the one
            # case where the reservation may safely be handed back.
            apply_transfer_rejected(operation, reason=safe_reason(exc))
            results.append(f"transfer_rejected:{safe_reason(exc)}")
            continue
        apply_transfer_accepted(operation, snapshot)
        results.append("transfer_accepted")
    return ",".join(results) or "no_transfer_work"


def _recover_unknown_transfer(operation, *, gateway) -> str:
    """Resolve an ambiguous Transfer without ever creating a second one."""

    from .payout_reconciliation import apply_transfer_accepted

    payout = operation.attempt.payout
    allocation = operation.funding_allocation
    account = operation.attempt.instruction_version.stripe_account
    first = operation.first_request_at or operation.created_at
    age = (timezone.now() - first).total_seconds()
    if age <= IDEMPOTENT_REPLAY_SECONDS:
        try:
            snapshot = gateway.create_transfer(
                amount_minor=int(operation.amount_minor),
                destination=account.provider_account_id,
                source_transaction=allocation.source_charge_id,
                transfer_group=transfer_group(payout),
                idempotency_key=operation.idempotency_key,
                metadata=_operation_metadata(operation, payout),
            )
        except ProviderUnavailable as exc:
            raise PayoutDeferred(
                "Stripe is still unavailable for this recovery.",
                code=f"recover_{exc.code}"[:64],
                delay=timedelta(minutes=10),
            ) from exc
        except (ProviderCheckoutRejected, ProviderNotConfigured) as exc:
            # Past the point of ambiguity: an idempotent replay that Stripe
            # rejects outright means no Transfer was created under this key.
            from .payout_reconciliation import apply_transfer_rejected

            apply_transfer_rejected(operation, reason=safe_reason(exc))
            return f"transfer_rejected:{safe_reason(exc)}"
        apply_transfer_accepted(operation, snapshot)
        return "transfer_recovered_by_replay"

    found = gateway.find_transfer_by_metadata(
        key="shiptrip_operation",
        value=str(operation.public_reference),
        transfer_group=transfer_group(payout),
    )
    if found is None:
        raise PayoutUnresolved(
            "A previous Stripe transfer for this payout has an unresolved outcome.",
            code="transfer_unresolved",
        )
    apply_transfer_accepted(operation, found)
    return "transfer_recovered_by_search"


# ---------------------------------------------------------------------------
# Stage 4 — the bank payout
# ---------------------------------------------------------------------------


def _connected_available_cents(account, *, gateway) -> int:
    try:
        balance = gateway.retrieve_balance(
            account_id=account.provider_account_id, currency="eur"
        )
    except ProviderUnavailable as exc:
        raise PayoutDeferred(
            "The connected account balance could not be read.",
            code=f"balance_{exc.code}"[:64],
            delay=timedelta(minutes=15),
        ) from exc
    expected_live = expected_mode() == "live"
    if balance.livemode is not None and balance.livemode is not expected_live:
        raise PayoutBlocked(
            "The connected balance answered in the wrong provider mode.",
            code="balance_mode_mismatch",
        )
    return int(balance.available_minor)


def _plan_bank_payout(payout_id: int, *, attempt_id: int):
    """Create the disbursement intent, still revocable, under the lock."""

    with transaction.atomic():
        payout, _, _ = _lock_payout_aggregate(payout_id)
        _assert_dispatchable(payout)
        attempt = PayoutAttempt.objects.select_for_update(no_key=True).get(
            pk=attempt_id
        )
        if attempt.status not in (
            PayoutAttempt.Status.ACCEPTED,
            PayoutAttempt.Status.SENT,
        ):
            raise PayoutDeferred(
                "The platform transfer is not complete yet.",
                code=f"attempt_{attempt.status}",
                delay=timedelta(minutes=5),
            )
        existing = StripeDisbursementAllocation.objects.filter(
            payout=payout, active=True
        ).first()
        if existing is not None:
            disbursement = existing.disbursement
            if disbursement.status in StripeDisbursement.LIVE_STATUSES:
                return disbursement.pk, None
            if disbursement.status == StripeDisbursement.Status.PLANNED:
                operation = disbursement.operations.filter(
                    kind="bank_payout_create"
                ).first()
                return disbursement.pk, (operation.pk if operation else None)
        account = payout.active_instruction_version.stripe_account
        amount = int(attempt.amount_eur_cents)
        disbursement = StripeDisbursement.objects.create(
            account=account,
            provider_mode=payout.provider_mode,
            currency="EUR",
            amount_minor=amount,
            method="standard",
            external_account_id=account.external_account_id,
        )
        StripeDisbursementAllocation.objects.create(
            disbursement=disbursement,
            payout=payout,
            attempt=attempt,
            amount_eur_cents=amount,
        )
        operation = PayoutProviderOperation.objects.create(
            attempt=attempt,
            kind="bank_payout_create",
            account_scope=account.provider_account_id,
            provider_mode=payout.provider_mode,
            sequence=attempt.operations.count() + 1,
            idempotency_key=_bank_payout_key(disbursement),
            request_fingerprint=_fingerprint(
                "bank_payout_create",
                amount,
                "EUR",
                account.provider_account_id,
                account.external_account_id,
                payout.provider_mode,
                str(disbursement.public_reference),
                payout.state_version,
            ),
            amount_minor=amount,
            currency="EUR",
            disbursement=disbursement,
        )
        return disbursement.pk, operation.pk


def _commit_bank_payout(payout_id: int, *, disbursement_id: int, operation_id: int):
    with transaction.atomic():
        payout, _, _ = _lock_payout_aggregate(payout_id)
        # Rechecked here and not only at planning time: H0 requires the holds to
        # be re-read immediately before the bank stage, because a Transfer
        # having been accepted is not authority to pay a bank after a dispute
        # opened in between.
        _assert_dispatchable(payout)
        disbursement = StripeDisbursement.objects.select_for_update(no_key=True).get(
            pk=disbursement_id
        )
        operation = PayoutProviderOperation.objects.select_for_update(no_key=True).get(
            pk=operation_id
        )
        now = timezone.now()
        if operation.retry_after and operation.retry_after > now:
            raise PayoutDeferred(
                "Another worker holds this bank payout.",
                code="operation_leased",
                delay=operation.retry_after - now,
            )
        if disbursement.status == StripeDisbursement.Status.PLANNED:
            StripeDisbursement.objects.filter(pk=disbursement.pk).update(
                status=StripeDisbursement.Status.COMMITTED
            )
        PayoutProviderOperation.objects.filter(pk=operation.pk).update(
            status="committed" if operation.status == "prepared" else operation.status,
            first_request_at=operation.first_request_at or now,
            last_request_at=now,
            retry_after=now + timedelta(seconds=OPERATION_LEASE_SECONDS),
        )
        return payout.pk


def _send_bank_payout(*, disbursement_id: int, operation_id: int, gateway) -> str:
    from .payout_reconciliation import (
        apply_bank_payout_accepted,
        apply_bank_payout_rejected,
        mark_operation_unknown,
    )

    operation = PayoutProviderOperation.objects.select_related(
        "attempt__payout", "disbursement__account"
    ).get(pk=operation_id)
    disbursement = StripeDisbursement.objects.select_related("account").get(
        pk=disbursement_id
    )
    payout = operation.attempt.payout
    try:
        snapshot = gateway.create_bank_payout(
            account_id=disbursement.account.provider_account_id,
            amount_minor=int(disbursement.amount_minor),
            destination=disbursement.external_account_id,
            idempotency_key=operation.idempotency_key,
            metadata=_operation_metadata(operation, payout),
        )
    except ProviderUnavailable as exc:
        mark_operation_unknown(
            operation, reason=safe_reason(exc), disbursement=disbursement
        )
        return f"bank_payout_unknown:{safe_reason(exc)}"
    except (ProviderCheckoutRejected, ProviderNotConfigured) as exc:
        apply_bank_payout_rejected(operation, disbursement, reason=safe_reason(exc))
        return f"bank_payout_rejected:{safe_reason(exc)}"
    apply_bank_payout_accepted(operation, disbursement, snapshot)
    return f"bank_payout_{snapshot.status}"


def _recover_unknown_bank_payout(operation, disbursement, *, gateway) -> str:
    from .payout_reconciliation import (
        apply_bank_payout_accepted,
        apply_bank_payout_rejected,
    )

    payout = operation.attempt.payout
    account = disbursement.account
    first = operation.first_request_at or operation.created_at
    age = (timezone.now() - first).total_seconds()
    if age <= IDEMPOTENT_REPLAY_SECONDS:
        try:
            snapshot = gateway.create_bank_payout(
                account_id=account.provider_account_id,
                amount_minor=int(disbursement.amount_minor),
                destination=disbursement.external_account_id,
                idempotency_key=operation.idempotency_key,
                metadata=_operation_metadata(operation, payout),
            )
        except ProviderUnavailable as exc:
            raise PayoutDeferred(
                "Stripe is still unavailable for this recovery.",
                code=f"recover_{exc.code}"[:64],
                delay=timedelta(minutes=10),
            ) from exc
        except (ProviderCheckoutRejected, ProviderNotConfigured) as exc:
            apply_bank_payout_rejected(
                operation, disbursement, reason=safe_reason(exc)
            )
            return f"bank_payout_rejected:{safe_reason(exc)}"
        apply_bank_payout_accepted(operation, disbursement, snapshot)
        return "bank_payout_recovered_by_replay"

    found = gateway.find_bank_payout_by_metadata(
        account_id=account.provider_account_id,
        key="shiptrip_operation",
        value=str(operation.public_reference),
        created_gte=int(first.timestamp()) - 60,
    )
    if found is None:
        raise PayoutUnresolved(
            "A previous bank payout for this payout has an unresolved outcome.",
            code="bank_payout_unresolved",
        )
    apply_bank_payout_accepted(operation, disbursement, found)
    return "bank_payout_recovered_by_search"


# ---------------------------------------------------------------------------
# The worker entry point
# ---------------------------------------------------------------------------


def execute_payout(payout_id: int, *, gateway=None) -> str:
    """Advance one Stripe EUR payout by exactly one external stage.

    Idempotent and resumable at every point. Called by the `payout_execute`
    job, by the sweeper's re-arm, and by an operator's audited retry; all three
    converge on the same state machine, and none of them can shorten a stage.
    """

    require_execution_enabled()
    gateway = gateway or get_connect_gateway()
    payout = Payout.objects.select_related(
        "deal", "active_instruction_version__stripe_account"
    ).get(pk=payout_id)
    _assert_dispatchable(payout)
    _refresh_readiness(payout)
    payout.refresh_from_db()

    # An ambiguous operation outranks new work: nothing new is dispatched for a
    # payout whose last instruction's outcome is unknown.
    unresolved = list(
        PayoutProviderOperation.objects.select_related(
            "attempt__payout__active_instruction_version__stripe_account",
            "funding_allocation",
            "disbursement__account",
        )
        .filter(attempt__payout_id=payout_id, status="unknown")
        .order_by("kind", "sequence")
    )
    if unresolved:
        notes = []
        for operation in unresolved:
            if operation.kind == "transfer_create":
                notes.append(_recover_unknown_transfer(operation, gateway=gateway))
            elif operation.kind == "bank_payout_create":
                notes.append(
                    _recover_unknown_bank_payout(
                        operation, operation.disbursement, gateway=gateway
                    )
                )
        return ",".join(notes)

    attempt = (
        Payout.objects.get(pk=payout_id)
        .attempts.filter(
            status__in=["prepared", "dispatch_committed", "unknown", "accepted", "sent"]
        )
        .order_by("-sequence")
        .first()
    )
    if attempt is not None and attempt.status == PayoutAttempt.Status.ACCEPTED:
        return _advance_to_bank_payout(payout_id, attempt, gateway=gateway)
    if attempt is not None and attempt.status == PayoutAttempt.Status.SENT:
        return "bank_payout_in_flight"

    if attempt is None:
        if int(payout.amount_eur_cents) < minimum_payout_cents():
            # Checked *before* the Transfer, not after it. Moving money into a
            # connected account that cannot then pay it out to a bank would
            # strand the Traveler's earnings one step further from them for no
            # benefit, and would leave the aggregate claiming committed
            # exposure it did not need to take.
            _block(payout_id, reason="payout_below_minimum")
            return "payout_below_minimum"
        # Nothing is reserved yet, so the source plan is computed from scratch —
        # with the provider reads outside every lock.
        plan = _reserve_dispatch(
            payout_id, _resolve_charges(payout_id, gateway=gateway)
        )
    else:
        # A reservation already exists. It is deliberately *not* re-planned:
        # this payout's own allocations bound its sources, so recomputing would
        # find its own reservation in the way and refuse to fund the obligation
        # it already reserved.
        plan = _plan_from_attempt(attempt)
    plan = _commit_dispatch(plan)
    return _send_transfers(plan, gateway=gateway)


def _resolve_charges(payout_id: int, *, gateway) -> dict:
    """Resolve and verify every candidate source charge outside every lock."""

    payout = Payout.objects.get(pk=payout_id)
    balance = (
        PaymentOrder.objects.filter(deal_id=payout.deal_id, purpose="deal_balance")
        .exclude(status="cancelled")
        .order_by("-pk")
        .first()
    )
    if balance is None:
        raise PayoutBlocked(
            "This Deal has no live balance obligation.", code="balance_order_missing"
        )
    sources = list(
        PaymentAttempt.objects.select_related("order")
        .filter(order_id__in=source_order_ids(balance))
        .order_by("pk")
    )
    slices = plan_source_slices(payout, balance_order=balance, locked_sources=sources)
    resolved = {}
    for item in slices:
        try:
            resolved[item.source_attempt.pk] = resolve_source_charge(
                item.source_attempt, gateway=gateway
            )
        except ProviderUnavailable as exc:
            raise PayoutDeferred(
                "Stripe could not confirm the source charge.",
                code=f"charge_{exc.code}"[:64],
                delay=timedelta(minutes=15),
            ) from exc
    return resolved


def _advance_to_bank_payout(payout_id: int, attempt, *, gateway) -> str:
    payout = Payout.objects.select_related(
        "active_instruction_version__stripe_account"
    ).get(pk=payout_id)
    account = payout.active_instruction_version.stripe_account
    amount = int(attempt.amount_eur_cents)
    if amount < minimum_payout_cents():
        # Only reachable if the minimum changed after a Transfer was already
        # accepted. The money is at the connected account, so this is not a
        # `blocked` reservation any more — it is committed exposure that needs a
        # person. Never rounded up, never forfeited, never marked paid.
        open_execution_hold(payout, reason="payout_below_minimum", kind="treasury")
        raise PayoutBlocked(
            "The remaining award is below the provider's minimum bank payout.",
            code="payout_below_minimum",
        )

    available = _connected_available_cents(account, gateway=gateway)
    if available < amount:
        # Expected: a Transfer made against an unsettled charge lands in the
        # connected account's *pending* balance and becomes available when the
        # source charge settles. Waiting is correct behaviour, so it must not
        # consume this payout's retry budget.
        raise PayoutDeferred(
            "Transferred funds are not available in the connected account yet.",
            code="connected_balance_pending",
            delay=timedelta(hours=1),
        )
    disbursement_id, operation_id = _plan_bank_payout(payout_id, attempt_id=attempt.pk)
    if operation_id is None:
        return "bank_payout_in_flight"
    _commit_bank_payout(
        payout_id, disbursement_id=disbursement_id, operation_id=operation_id
    )
    return _send_bank_payout(
        disbursement_id=disbursement_id, operation_id=operation_id, gateway=gateway
    )


def _block(payout_id: int, *, reason: str) -> None:
    """Record a persistent, still-owed blocked state with a safe reason."""

    with transaction.atomic():
        payout, _, _ = _lock_payout_aggregate(payout_id)
        if payout.status in ("paid", "cancelled", "blocked"):
            return
        previous = payout.status
        payout.status = "blocked"
        payout.block_reason = reason[:64]
        payout.next_action_at = timezone.now() + timedelta(days=1)
        payout.save(
            update_fields=["status", "block_reason", "next_action_at", "updated_at"]
        )
        append_event_locked(payout, previous=previous, reason=reason)
        from .payout_reconciliation import notify_payout_state

        notify_payout_state(payout, "needs_attention")


# ---------------------------------------------------------------------------
# Releasing a reservation that provably never executed
# ---------------------------------------------------------------------------


def release_allocation(allocation, *, reason: str, actor=None):
    """Hand one reserved slice back. Only for a definitive pre-execution refusal.

    Append-only: the allocation itself is never edited or deleted, so the record
    that these cents were once earmarked survives the release.
    """

    if PayoutFundingRelease.objects.filter(allocation=allocation).exists():
        return
    PayoutFundingRelease.objects.create(
        allocation=allocation, reason_code=reason[:64], actor=actor
    )


def open_execution_hold(payout, *, reason: str, kind: str = "manual"):
    """Stop the next stage without pretending the previous one did not happen."""

    hold, _ = FinanceHold.objects.get_or_create(
        payout=payout,
        kind=kind,
        reason_code=reason[:64],
        cleared_at=None,
        defaults={"source_reference": f"payout:{payout.public_reference}"},
    )
    return hold


# ---------------------------------------------------------------------------
# Operator recovery — state-safe actions only
# ---------------------------------------------------------------------------


def admin_refresh_payout(*, actor, payout_id: int) -> str:
    """Re-read every live provider object for one payout. Changes no decision.

    The safe action, and the one an operator should reach for first: it asks
    Stripe what is true and lets the same reconciler that a webhook uses record
    the answer.
    """

    from apps.admin_panel.services import record_admin_action
    from .payout_profiles import require_capabilities
    from .payout_reconciliation import reconcile_payout

    require_capabilities(actor, "reconcile_finance", "view_payouts")
    payout = Payout.objects.get(pk=payout_id)
    result = reconcile_payout(payout_id)
    account = (
        payout.active_instruction_version.stripe_account
        if payout.active_instruction_version_id
        else None
    )
    if account is not None:
        try:
            refresh_account(account)
        except ProviderError:
            result = f"{result},account_refresh_failed"
    record_admin_action(
        actor=actor,
        action="payout.reconcile_refreshed",
        target=payout,
        after={"result": result[:255]},
    )
    return result


def admin_retry_bank_payout(*, actor, payout_id: int, expected_state_version: int) -> str:
    """Retry the **bank payout stage only**, after a verified failure.

    Deliberately narrow. There is no operator action that creates a Transfer
    again, no "mark paid", no "reset to eligible", no amount or destination
    edit, and no way to act on an operation whose result is unknown. The money
    from the original Transfer is already at the connected account; the only
    legitimate recovery is another bank payout, and only once the previous one
    is provably not in flight.
    """

    from apps.admin_panel.services import record_admin_action
    from .payout_profiles import require_capabilities

    require_capabilities(actor, "retry_payouts", "view_payouts")
    with transaction.atomic():
        payout, _, _ = _lock_payout_aggregate(payout_id)
        from .mode_safety import require_object_mode

        require_object_mode(payout.provider_mode)
        if payout.state_version != expected_state_version:
            raise PayoutBlocked(
                "This payout changed while the page was open.", code="state_conflict"
            )
        if payout.status != "failed":
            raise PayoutBlocked(
                "Only a failed bank payout can be retried.",
                code=f"payout_{payout.status}",
            )
        if active_holds(payout).exists():
            raise PayoutBlocked("A Finance hold is active.", code="finance_hold_active")
        if PayoutProviderOperation.objects.filter(
            attempt__payout_id=payout_id, status="unknown"
        ).exists():
            raise PayoutBlocked(
                "An external operation for this payout has an unknown outcome.",
                code="operation_unresolved",
            )
        attempt = payout.attempts.filter(
            status=PayoutAttempt.Status.ACCEPTED
        ).order_by("-sequence").first()
        if attempt is None:
            raise PayoutBlocked(
                "There is no completed platform transfer to pay out.",
                code="no_accepted_transfer",
            )
        if StripeDisbursementAllocation.objects.filter(
            payout=payout, active=True
        ).exists():
            raise PayoutBlocked(
                "A bank payout for this payout is still live.",
                code="disbursement_live",
            )
        previous = payout.status
        payout.status = "processing"
        payout.failure_code = ""
        # Clearing the block reason is the whole authorisation. A failed bank
        # payout sets it precisely so nothing automatic picks the payout back
        # up; this is the audited human decision that the destination has been
        # corrected and another bank attempt is legitimate.
        payout.block_reason = ""
        payout.next_action_at = timezone.now()
        payout.save(
            update_fields=[
                "status",
                "failure_code",
                "block_reason",
                "next_action_at",
                "updated_at",
            ]
        )
        append_event_locked(
            payout, previous=previous, reason="bank_payout_retry_authorised", actor=actor
        )
        record_admin_action(
            actor=actor,
            action="payout.bank_payout_retry",
            target=payout,
            after={"attempt": attempt.sequence},
        )
    from .services import schedule_job
    from .models import ScheduledJob

    schedule_job(
        kind=ScheduledJob.Kind.PAYOUT_EXECUTE,
        key=f"payout_execute:{payout_id}",
        run_at=timezone.now(),
        payload={"payout_id": payout_id},
        max_attempts=32,
        reactivate_failed=True,
    )
    return "bank_payout_retry_armed"


def admin_flag_unresolved_operation(*, actor, payout_id: int, reason: str) -> str:
    """Put an ambiguous external operation in front of Finance.

    This does not resolve anything and does not touch the reservation. H0 is
    explicit that clearing an operational alert must leave the financial
    reservation intact, so the only effect is a hold that stops the next stage
    and an audited record that a person is looking at it.
    """

    from apps.admin_panel.services import record_admin_action
    from .payout_profiles import require_capabilities

    require_capabilities(actor, "manage_payout_holds", "view_payouts")
    with transaction.atomic():
        payout, _, _ = _lock_payout_aggregate(payout_id)
        hold = open_execution_hold(payout, reason=reason or "operation_under_review",
                                   kind="compliance")
        record_admin_action(
            actor=actor,
            action="payout.operation_flagged",
            target=hold,
            after={"reason": (reason or "operation_under_review")[:64]},
        )
    return "operation_flagged"
