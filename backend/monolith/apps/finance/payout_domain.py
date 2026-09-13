"""Locked H1 primitives. These functions never dispatch provider operations."""

from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.db.models import Sum, Q, Max
from django.utils import timezone

from apps.core.financial_locks import lock_deal_lifecycle
from apps.admin_panel.services import record_admin_action
from .models import (
    Payout,
    PayoutEvent,
    PayoutAmountRevision,
    PayoutInstructionAmendment,
    PayoutInstructionConfirmation,
    PayoutFundingAllocation,
    PaymentAttempt,
    PaymentOrder,
    FinanceHold,
    PayoutMethodVersion,
    TravelerPayoutMethod,
    StripePayoutAccount,
)
from .money import convert_eur_cents, require_positive_cents
from .payout_profiles import require_capabilities
from .payout_profiles import require_profiles

TRANSITIONS = {
    "not_eligible": {"eligible", "blocked", "frozen", "cancelled"},
    "eligible": {"scheduled", "blocked", "frozen", "cancelled"},
    "scheduled": {"processing", "blocked", "eligible", "frozen", "cancelled"},
    "blocked": {"eligible", "scheduled", "frozen", "cancelled"},
    "processing": {"sent", "paid", "failed", "frozen"},
    "sent": {"paid", "failed", "frozen"},
    # A genuine bank return after settlement. The paid history stays; the
    # obligation comes back.
    "paid": {"failed"},
    "failed": {"scheduled", "processing", "blocked", "eligible", "frozen", "cancelled"},
    # A freeze stops new instructions, not callbacks. An already-committed bank
    # payout may still complete or fail underneath a hold, and pretending
    # otherwise would leave the aggregate claiming money that has moved.
    "frozen": {"not_eligible", "eligible", "blocked", "paid", "failed", "cancelled"},
    "cancelled": set(),
}

#: Attempt statuses in which an external instruction exists, or may exist. From
#: the first of these onwards the amount is treated as unavailable to anyone
#: else — a refund, a settlement or a second dispatch — until the provider says
#: otherwise.
COMMITTED_ATTEMPT_STATUSES = (
    "dispatch_committed",
    "unknown",
    "accepted",
    "sent",
    "succeeded",
)


def validate_transition(previous, new):
    if new not in TRANSITIONS.get(previous, set()):
        raise ValidationError("Invalid payout transition.")


def append_event_locked(
    payout, *, previous, reason, actor=None, ledger_transaction_id=None
):
    if previous != payout.status:
        validate_transition(previous, payout.status)
    payout.state_version += 1
    payout.save(update_fields=["state_version"])
    return PayoutEvent.objects.create(
        payout=payout,
        sequence=payout.state_version,
        previous_state=previous,
        new_state=payout.status,
        reason_code=reason,
        actor=actor,
        ledger_transaction_id=ledger_transaction_id,
    )


def require_uncommitted(payout):
    if payout.attempts.exclude(
        status__in=["prepared", "cancelled", "returned"]
    ).exists():
        raise ValidationError("Payout has committed or unrecovered external exposure.")


def committed_exposure_cents(payout) -> int:
    """How much of this payout is already outside the platform's control.

    Not "how much has been paid". A Transfer that Stripe accepted has left the
    platform's balance even though the Traveler has not seen it, and a dispatch
    whose HTTP result was lost may have done the same. Both are money a
    settlement can no longer re-allocate to the Sender, so both count here.

    Returns zero for a payout with only prepared, cancelled or returned
    attempts, which is the ordinary case.
    """

    if not payout.pk:
        return 0
    committed = payout.attempts.filter(status__in=COMMITTED_ATTEMPT_STATUSES)
    return int(
        committed.aggregate(total=Sum("amount_eur_cents"))["total"]
        or (int(payout.amount_eur_cents) if payout.status == "paid" else 0)
    )


def source_reserved_cents(source_attempt) -> int:
    """Cents of one capture currently earmarked for some Traveler payout.

    Allocations are immutable, so a reservation that never executed is undone by
    an append-only `PayoutFundingRelease` rather than by deleting the row. Only
    unreleased allocations bind the source.
    """

    from .models import PayoutFundingAllocation

    return int(
        PayoutFundingAllocation.objects.filter(
            source_attempt=source_attempt, release__isnull=True
        ).aggregate(total=Sum("amount_eur_cents"))["total"]
        or 0
    )


def source_refunded_cents(source_attempt) -> int:
    """Cents of one capture already promised back to the payer."""

    return int(
        source_attempt.refunds.exclude(status__in=["failed", "cancelled"]).aggregate(
            total=Sum("amount_eur_cents")
        )["total"]
        or 0
    )


def source_available_cents(source_attempt) -> int:
    """What is left of one capture after refunds and live reservations."""

    return max(
        0,
        int(source_attempt.amount_eur_cents)
        - source_refunded_cents(source_attempt)
        - source_reserved_cents(source_attempt),
    )


def cancel_prepared_locked(payout):
    """A changed award/destination invalidates local, undispatched intents."""
    payout.attempts.filter(status="prepared").update(status="cancelled")


def revise_amount_locked(
    payout,
    *,
    amount,
    settlement_reference,
    reason_code,
    actor=None,
    ledger_transaction_id=None,
):
    """Caller owns lifecycle/order/Payout locks and settlement ledger decision."""
    if (
        type(amount) is not int
        or amount < 0
        or not settlement_reference
        or not reason_code
    ):
        raise ValidationError(
            "Explicit integer award and settlement decision required."
        )
    if not payout.snapshot_version:
        raise ValidationError("Legacy payout requires reviewed migration.")
    if amount > payout.funded_amount_eur_cents:
        raise ValidationError(
            "Settlement award exceeds the original funded obligation."
        )
    prior = payout.amount_revisions.filter(
        settlement_reference=settlement_reference
    ).first()
    if prior:
        if prior.amount_eur_cents != amount:
            raise ValidationError("Settlement replay conflicts with original award.")
        return prior
    require_uncommitted(payout)
    if payout.status in ("paid", "cancelled"):
        raise ValidationError("Terminal payout cannot be revised.")
    settlement = (
        amount
        if payout.payout_currency == "EUR"
        else (
            convert_eur_cents(
                amount, to_currency="DZD", rate_micros=payout.fx_rate_micros
            )
            if amount and payout.fx_rate_micros
            else 0
            if amount == 0
            else None
        )
    )
    if payout.block_reason == "fx_snapshot_missing":
        settlement = None
    revision = PayoutAmountRevision.objects.create(
        payout=payout,
        revision=(payout.amount_revisions.aggregate(n=Max("revision"))["n"] or 0) + 1,
        previous_amount_eur_cents=payout.amount_eur_cents,
        amount_eur_cents=amount,
        previous_settlement_amount_minor=payout.payout_amount_minor,
        settlement_amount_minor=settlement,
        fx_rate_micros=payout.fx_rate_micros,
        fx_settings_version=payout.fx_settings_version,
        settlement_reference=settlement_reference,
        ledger_transaction_id=ledger_transaction_id,
        actor=actor,
        reason_code=reason_code,
    )
    previous = payout.status
    cancel_prepared_locked(payout)
    payout.amount_eur_cents = amount
    payout.payout_amount_minor = settlement
    payout.eligibility_decision_reference = settlement_reference
    if amount == 0:
        payout.status = "cancelled"
        # Missing FX stays missing even for zero liability; original snapshot
        # provenance is not retroactively fabricated.
        if payout.block_reason == "fx_snapshot_missing":
            payout.payout_amount_minor = None
    payout.save(
        update_fields=[
            "amount_eur_cents",
            "payout_amount_minor",
            "eligibility_decision_reference",
            "status",
            "updated_at",
        ]
    )
    append_event_locked(
        payout,
        previous=previous,
        reason=reason_code,
        actor=actor,
        ledger_transaction_id=ledger_transaction_id,
    )
    return revision


@transaction.atomic
def confirm_instruction(*, actor, payout_id, new_version_id, expected_state_version):
    require_profiles()
    seed = Payout.objects.get(pk=payout_id)
    from .mode_safety import require_object_mode

    require_object_mode(seed.provider_mode)
    from .payout_profiles import _traveler

    actor = _traveler(actor)
    if seed.traveler_id != actor.pk:
        raise PermissionDenied("Payout owner confirmation required.")
    lock_deal_lifecycle(seed.deal_id)
    payout = Payout.objects.select_for_update(no_key=True).get(pk=payout_id)
    version = PayoutMethodVersion.objects.select_related("method").get(
        pk=new_version_id
    )
    if (
        payout.state_version != expected_state_version
        or version.method.traveler_id != actor.pk
        or version.rail != payout.method
        or version.currency != payout.payout_currency
    ):
        raise ValidationError("Current same-rail payout instruction required.")
    require_uncommitted(payout)
    confirmation = PayoutInstructionConfirmation.objects.create(
        payout=payout,
        new_version=version,
        traveler=actor,
        expected_state_version=expected_state_version,
    )
    record_admin_action(
        actor=actor, action="payout.instruction_confirmed", target=confirmation
    )
    return confirmation


@transaction.atomic
def amend_instruction(
    *,
    actor,
    traveler,
    payout_id,
    new_version_id,
    expected_state_version,
    reason_code,
    confirmed_at,
    confirmation_reference,
):
    require_capabilities(actor, "review_payout_profiles", "view_payout_sensitive")
    seed = Payout.objects.get(pk=payout_id)
    from .mode_safety import require_object_mode

    require_object_mode(seed.provider_mode)
    lock_deal_lifecycle(seed.deal_id)
    payout = Payout.objects.select_for_update(no_key=True).get(pk=payout_id)
    from .payout_profiles import _traveler

    traveler = _traveler(traveler)
    if payout.traveler_id != traveler.pk:
        raise PermissionDenied("Traveler confirmation required.")
    confirmation = PayoutInstructionConfirmation.objects.filter(
        public_reference=confirmation_reference,
        payout=payout,
        traveler=traveler,
        new_version_id=new_version_id,
        expected_state_version=expected_state_version,
        confirmed_at=confirmed_at,
    ).first()
    if confirmation is None:
        raise PermissionDenied("Recorded traveler confirmation required.")
    if (
        not confirmed_at
        or confirmed_at > timezone.now()
        or not reason_code
        or payout.state_version != expected_state_version
    ):
        raise ValidationError("Confirmation and current payout version required.")
    require_uncommitted(payout)
    if not payout.snapshot_version or payout.status in ("paid", "cancelled"):
        raise ValidationError("Payout instruction cannot be amended.")
    version = PayoutMethodVersion.objects.select_related(
        "method", "stripe_account"
    ).get(pk=new_version_id)
    version.method = TravelerPayoutMethod.objects.select_for_update(no_key=True).get(
        pk=version.method_id
    )
    if version.stripe_account_id:
        version.stripe_account = StripePayoutAccount.objects.select_for_update(
            no_key=True
        ).get(pk=version.stripe_account_id)
    if (
        version.method.traveler_id != payout.traveler_id
        or version.rail != payout.method
        or version.currency != payout.payout_currency
    ):
        raise ValidationError("Amendment must retain owner, rail and currency.")
    if (
        version.stripe_account
        and version.stripe_account.provider_mode != payout.provider_mode
    ):
        raise ValidationError("Payout mode mismatch.")
    if (
        version.method.status != "ready"
        or version.method.current_version_id != version.pk
    ):
        raise ValidationError("Reviewed current destination required.")
    old = payout.active_instruction_version
    if old is None or old.pk == version.pk:
        raise ValidationError("A different same-rail destination is required.")
    amendment = PayoutInstructionAmendment.objects.create(
        payout=payout,
        sequence=payout.instruction_amendments.count() + 1,
        old_version=old,
        new_version=version,
        traveler=traveler,
        confirmed_at=confirmed_at,
        reviewed_by=actor,
        reason_code=reason_code,
        expected_state=payout.status,
        expected_state_version=expected_state_version,
    )
    cancel_prepared_locked(payout)
    payout.active_instruction_version = version
    payout.save(update_fields=["active_instruction_version"])
    append_event_locked(
        payout, previous=payout.status, reason="instruction_amended", actor=actor
    )
    record_admin_action(
        actor=actor, action="payout.instruction_amended", target=amendment
    )
    return amendment


@transaction.atomic
def allocate_source(*, payout_id, source_attempt_id, amount_eur_cents, allocation_key):
    """Reserve a supported source, bounded under canonical aggregate locks.

    No disbursement is created. H3 must add reviewed release/recovery entries
    before reusing any allocation; H1 conservatively never releases one.
    """
    require_positive_cents(amount_eur_cents)
    seed = Payout.objects.get(pk=payout_id)
    lock_deal_lifecycle(seed.deal_id)
    balance = (
        PaymentOrder.objects.filter(deal_id=seed.deal_id, purpose="deal_balance")
        .exclude(status="cancelled")
        .get()
    )
    from .payout_snapshots import source_order_ids

    ids = source_order_ids(balance)
    list(
        PaymentOrder.objects.select_for_update(no_key=True)
        .filter(pk__in=ids)
        .order_by("pk")
    )
    sources = list(
        PaymentAttempt.objects.select_for_update(no_key=True)
        .filter(order_id__in=ids)
        .order_by("pk")
    )
    payout = Payout.objects.select_for_update(no_key=True).get(pk=payout_id)
    source = next((s for s in sources if s.pk == source_attempt_id), None)
    existing = PayoutFundingAllocation.objects.filter(
        allocation_key=allocation_key
    ).first()
    if existing:
        if (
            existing.payout_id,
            existing.source_attempt_id,
            existing.amount_eur_cents,
        ) != (payout.pk, source_attempt_id, amount_eur_cents):
            raise ValidationError("Allocation replay conflict.")
        return existing
    if (
        not source
        or source.status != "succeeded"
        or source.succeeded_at is None
        or source.is_unapplied
        or source.provider_mode != payout.provider_mode
        or payout.provider_mode not in ("test", "live")
        or payout.status in ("paid", "cancelled")
    ):
        raise ValidationError("Applied same-mode funding source required.")
    if payout.payout_currency == "EUR" and (
        source.provider != "stripe" or not source.provider_charge_id.startswith("ch_")
    ):
        raise ValidationError("EUR source requires a verified Stripe charge.")
    # Released reservations do not bind the source. H1 never released one, so
    # this was the same number; H3 hands a slice back when its provider
    # operation is definitively rejected before execution, and the source must
    # become spendable again.
    used = source_reserved_cents(source)
    refunds = source_refunded_cents(source)
    payout_used = (
        payout.funding_allocations.filter(release__isnull=True).aggregate(
            total=Sum("amount_eur_cents")
        )["total"]
        or 0
    )
    if (
        used + refunds + amount_eur_cents > source.amount_eur_cents
        or payout_used + amount_eur_cents > payout.amount_eur_cents
    ):
        raise ValidationError("Funding allocation exceeds available obligation/source.")
    if source.order_id == balance.credit_source_id:
        credited_used = (
            payout.funding_allocations.filter(
                source_attempt__order_id=balance.credit_source_id,
                release__isnull=True,
            ).aggregate(total=Sum("amount_eur_cents"))["total"]
            or 0
        )
        if credited_used + amount_eur_cents > balance.credited_eur_cents:
            raise ValidationError("Allocation exceeds credited deposit share.")
    return PayoutFundingAllocation.objects.create(
        allocation_key=allocation_key,
        payout=payout,
        source_attempt=source,
        source_charge_id=source.provider_charge_id,
        provider=source.provider,
        provider_mode=source.provider_mode,
        purpose=source.order.purpose,
        currency=source.payment_currency,
        amount_eur_cents=amount_eur_cents,
    )


def active_holds(payout):
    current_account_id = (
        payout.active_instruction_version.stripe_account_id
        if payout.active_instruction_version_id
        else None
    )
    return FinanceHold.objects.filter(
        Q(payout=payout)
        | Q(deal_id=payout.deal_id)
        | Q(account_id=payout.stripe_account_id, account_id__isnull=False)
        | Q(account_id=current_account_id, account_id__isnull=False)
        | Q(
            source_attempt_id__in=payout.funding_allocations.values("source_attempt_id")
        )
        | Q(
            source_attempt_id=payout.funding_attempt_id, source_attempt_id__isnull=False
        ),
        cleared_at__isnull=True,
    )


@transaction.atomic
def open_hold(*, actor, payout_id, kind, reason_code, source_reference):
    require_capabilities(actor, "manage_payout_holds", "view_payouts")
    if (
        kind not in {"manual", "treasury", "compliance"}
        or not reason_code
        or not source_reference
    ):
        raise ValidationError("Invalid operator hold.")
    seed = Payout.objects.get(pk=payout_id)
    lock_deal_lifecycle(seed.deal_id)
    payout = Payout.objects.select_for_update(no_key=True).get(pk=payout_id)
    hold = FinanceHold.objects.create(
        payout=payout,
        kind=kind,
        reason_code=reason_code,
        source_reference=source_reference,
        opened_by=actor,
        amount_exposure_eur_cents=committed_exposure_cents(payout),
    )
    append_event_locked(
        payout, previous=payout.status, reason="hold_opened", actor=actor
    )
    record_admin_action(actor=actor, action="payout.hold_opened", target=hold)
    return hold


@transaction.atomic
def clear_hold(*, actor, hold_id, expected_generation):
    require_capabilities(actor, "manage_payout_holds", "view_payouts")
    seed = FinanceHold.objects.get(pk=hold_id)
    if (
        not seed.payout_id
        or seed.kind not in ("manual", "treasury", "compliance")
        or seed.opened_by_id != actor.pk
    ):
        raise PermissionDenied("Only the owning operator may clear this hold source.")
    payout_seed = Payout.objects.get(pk=seed.payout_id)
    lock_deal_lifecycle(payout_seed.deal_id)
    payout = Payout.objects.select_for_update(no_key=True).get(pk=seed.payout_id)
    from .mode_safety import require_object_mode

    require_object_mode(payout.provider_mode)
    hold = FinanceHold.objects.select_for_update(no_key=True).get(pk=hold_id)
    if hold.generation != expected_generation:
        raise ValidationError("Hold generation conflict.")
    if hold.cleared_at:
        return hold
    hold.cleared_at, hold.cleared_by = timezone.now(), actor
    hold.generation += 1
    hold.save(update_fields=["cleared_at", "cleared_by", "generation"])
    append_event_locked(
        payout, previous=payout.status, reason="hold_cleared", actor=actor
    )
    record_admin_action(actor=actor, action="payout.hold_cleared", target=hold)
    return hold
