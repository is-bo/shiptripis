"""Re-allocating a funded Deal's money: dispute resolution and late cancellation.

Funding split the sender's payment into two liabilities -- the traveler's reward
and the platform's commission. Two Phase 4 events can change that split after
the fact: an administrator resolving a dispute, and a cancellation after the
Deal was funded. Both land here, because both have to satisfy the same
invariant:

    every cent the platform collected is returned to the sender, paid to the
    traveler, or kept as commission. Nothing is created and nothing disappears.

That is checked three times over. `plan_settlement` refuses a split that does
not sum to the collected total; `apps.finance.ledger.post` refuses a transaction
whose entries do not sum to zero; and `disputes_resolution_reconciles` refuses
to store a resolution whose three amounts disagree with the total.

**Idempotency.** Every write is keyed on the caller's `settlement_key`: the
ledger correction, the deposit-credit release and each refund. Two
administrators resolving the same dispute at the same moment serialize on the
Dispute row lock, and a retry of the winner is a no-op rather than a second
refund.

**The posting deposit.** A funded Deal's money can sit in two obligations: the
balance order, and the posting-deposit order whose cash was credited into it.
Refunds are taken from the balance order first and only reach the deposit when
the sender's share exceeds it. The deposit credit is then released in *exactly*
the amount being refunded out of it -- not all of it -- because releasing more
would leave a phantom deposit liability against a sender who is owed nothing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.db.models import Sum
from django.utils import timezone

from apps.deals.models import Deal, DealTermsSnapshot

from . import ledger
from .models import (
    LedgerAccount,
    LedgerTransaction,
    PaymentAttempt,
    PaymentOrder,
    PaymentRefund,
    Payout,
)

logger = logging.getLogger(__name__)


class SettlementError(RuntimeError):
    """A settlement was refused because it would not reconcile."""

    code = "settlement_error"

    def __init__(self, message: str, *, code: str | None = None, **details):
        super().__init__(message)
        if code:
            self.code = code
        self._details = details

    def details(self) -> dict:
        return dict(self._details)


@dataclass(frozen=True, slots=True)
class DealMoney:
    """What one Deal actually holds, read from locked finance rows."""

    deal_id: int
    balance_order_id: int | None
    deposit_order_id: int | None
    #: Cash captured and applied against the balance order, net of refunds.
    balance_cash_eur_cents: int
    #: Cash captured on the deposit order and credited into this balance.
    deposit_cash_eur_cents: int
    #: How much of the balance obligation the deposit currently discharges.
    credited_eur_cents: int
    traveler_reward_eur_cents: int
    platform_fee_eur_cents: int
    sender_total_eur_cents: int
    #: Already sent to the traveler and gone. A settlement cannot claw a bank
    #: transfer back, so this is money the platform no longer has to allocate.
    paid_out_eur_cents: int = 0

    @property
    def collected_eur_cents(self) -> int:
        """Everything the platform ever collected for this Deal, in EUR cents."""

        return self.balance_cash_eur_cents + self.deposit_cash_eur_cents

    @property
    def settleable_eur_cents(self) -> int:
        """What the platform can still move.

        Collected money minus anything already paid out. Refunding against
        `collected` after a payout has settled is how a Deal pays the same euro
        to two people, so every bound in `plan_settlement` is against this.
        """

        return max(0, self.collected_eur_cents - int(self.paid_out_eur_cents))


@dataclass(frozen=True, slots=True)
class SettlementPlan:
    money: DealMoney
    sender_refund_eur_cents: int
    traveler_payout_eur_cents: int
    platform_fee_eur_cents: int

    def as_dict(self) -> dict:
        return {
            "collected_eur_cents": self.money.collected_eur_cents,
            "sender_refund_eur_cents": self.sender_refund_eur_cents,
            "traveler_payout_eur_cents": self.traveler_payout_eur_cents,
            "platform_fee_eur_cents": self.platform_fee_eur_cents,
        }


@dataclass(slots=True)
class SettlementResult:
    plan: SettlementPlan
    refund_ids: list[int] = field(default_factory=list)
    ledger_transaction_id: int | None = None
    payout_status: str = ""
    changed: bool = False


# --- reading ------------------------------------------------------------------


def _applied_cash(order_id: int) -> int:
    """Captured, applied, not-yet-refunded cash on one order.

    `is_unapplied` attempts are excluded: that money is real but was never
    applied to this obligation, and Phase 3 already owns refunding it
    separately. Counting it here would let a settlement give the sender back
    money a different refund is already returning.
    """

    captured = int(
        PaymentAttempt.objects.filter(
            order_id=order_id,
            status=PaymentAttempt.Status.SUCCEEDED,
            is_unapplied=False,
        ).aggregate(total=Sum("amount_eur_cents"))["total"]
        or 0
    )
    refunded = int(
        PaymentRefund.objects.filter(
            order_id=order_id,
            status__in=(
                PaymentRefund.Status.PENDING,
                PaymentRefund.Status.PROCESSING,
                PaymentRefund.Status.SUCCEEDED,
            ),
            attempt__is_unapplied=False,
        ).aggregate(total=Sum("amount_eur_cents"))["total"]
        or 0
    )
    return max(0, captured - refunded)


def read_deal_money(deal: Deal) -> DealMoney:
    """Snapshot the Deal's finances. Call with the Deal aggregate held."""

    terms = DealTermsSnapshot.objects.filter(deal_id=deal.pk).first()
    if terms is None:
        raise SettlementError(
            "This deal has no economic terms snapshot.",
            code="deal_terms_missing",
        )
    balance = (
        PaymentOrder.objects.filter(
            deal_id=deal.pk, purpose=PaymentOrder.Purpose.DEAL_BALANCE
        )
        .order_by("-pk")
        .first()
    )
    deposit_id = None
    deposit_cash = 0
    credited = 0
    if balance is not None:
        credited = int(balance.credited_eur_cents)
        if balance.credit_source_id is not None:
            deposit_id = balance.credit_source_id
            deposit_cash = _applied_cash(deposit_id)
    settled_payout = (
        Payout.objects.filter(deal_id=deal.pk, status=Payout.Status.PAID)
        .values_list("amount_eur_cents", flat=True)
        .first()
    )
    return DealMoney(
        deal_id=deal.pk,
        paid_out_eur_cents=int(settled_payout or 0),
        balance_order_id=balance.pk if balance else None,
        deposit_order_id=deposit_id,
        balance_cash_eur_cents=_applied_cash(balance.pk) if balance else 0,
        deposit_cash_eur_cents=min(deposit_cash, credited) if deposit_id else 0,
        credited_eur_cents=credited,
        traveler_reward_eur_cents=int(terms.traveler_reward_minor),
        platform_fee_eur_cents=int(terms.platform_fee_minor),
        sender_total_eur_cents=int(terms.sender_total_minor),
    )


# --- planning -----------------------------------------------------------------


def plan_settlement(
    *,
    money: DealMoney,
    sender_refund_eur_cents: int,
    traveler_payout_eur_cents: int | None = None,
    fee_mode: str = "proportional",
) -> SettlementPlan:
    """Turn an administrator's decision into three amounts that reconcile.

    The caller states what goes back to the sender. What is left is split
    between the traveler and the platform:

    ``proportional``
        in the ratio the parties originally agreed, so a half refund leaves the
        traveler and the platform each with half of what they expected.
    ``platform_waives``
        the traveler is made whole first and the platform absorbs the shortfall.
        This is the mode a late-cancellation compensation uses.

    An explicit `traveler_payout_eur_cents` overrides the mode; the platform
    then keeps whatever remains, and a negative remainder is refused rather
    than quietly turned into a platform loss nobody approved.
    """

    total = money.collected_eur_cents
    already_paid = int(money.paid_out_eur_cents)
    settleable = money.settleable_eur_cents
    refund = int(sender_refund_eur_cents)
    if refund < 0 or refund > settleable:
        # Bounded by what is still here, not by what was once collected. A Deal
        # whose payout has already settled holds less than it collected, and
        # refunding the difference would send the same euro to two people --
        # silently, because each half looks correct on its own.
        raise SettlementError(
            "The sender refund must be between zero and the amount the platform "
            "still holds.",
            code="settlement_refund_out_of_range",
            collected_eur_cents=total,
            settleable_eur_cents=settleable,
            already_paid_out_eur_cents=already_paid,
            requested_eur_cents=refund,
        )
    remaining = total - refund

    if traveler_payout_eur_cents is not None:
        payout = int(traveler_payout_eur_cents)
        if payout < 0 or payout > remaining:
            raise SettlementError(
                "The traveler payout must fit inside what is left after the refund.",
                code="settlement_payout_out_of_range",
                remaining_eur_cents=remaining,
                requested_eur_cents=payout,
            )
        fee = remaining - payout
    elif fee_mode == "platform_waives":
        payout = min(remaining, int(money.traveler_reward_eur_cents))
        fee = remaining - payout
    else:
        reward = int(money.traveler_reward_eur_cents)
        basis = reward + int(money.platform_fee_eur_cents)
        if basis <= 0:
            payout = remaining
        else:
            # Integer arithmetic only. The traveler takes the floor and the
            # platform absorbs the rounding remainder, so the three amounts sum
            # to the total exactly, every time, with no fractional cent.
            payout = (remaining * reward) // basis
        fee = remaining - payout

    if already_paid > payout:
        # Money already in the traveler's hands is part of their share whatever
        # the decision says. Raising the floor and taking the difference out of
        # the platform's fee keeps the three amounts summing to the collected
        # total without inventing cash to cover it.
        shortfall = already_paid - payout
        if fee < shortfall:
            raise SettlementError(
                "This settlement cannot be applied: more has already been paid "
                "to the traveler than the decision leaves them, and the "
                "platform's share cannot cover the difference. Operator "
                "recovery is required.",
                code="settlement_exceeds_paid_out",
                collected_eur_cents=total,
                already_paid_out_eur_cents=already_paid,
                requested_payout_eur_cents=payout,
            )
        payout = already_paid
        fee -= shortfall

    if refund + payout + fee != total:
        raise SettlementError(
            "The settlement does not reconcile.",
            code="settlement_does_not_reconcile",
            collected_eur_cents=total,
        )
    return SettlementPlan(
        money=money,
        sender_refund_eur_cents=refund,
        traveler_payout_eur_cents=payout,
        platform_fee_eur_cents=fee,
    )


# --- applying -----------------------------------------------------------------


def apply_settlement(
    *,
    plan: SettlementPlan,
    settlement_key: str,
    refund_reason: str,
    note: str,
    actor_id: int | None,
) -> SettlementResult:
    """Move the money. Call inside the caller's transaction, aggregate held.

    Order of operations matters and is fixed:

    1. re-recognise the liabilities at the resolved split (one correction),
    2. release only the deposit credit that is about to be refunded,
    3. raise the refunds, balance order first,
    4. set the traveler's payout to what they are actually owed.

    Doing (1) first means the ledger never briefly shows a refund against funds
    that are still recognised as the traveler's.
    """

    money = plan.money
    result = SettlementResult(plan=plan)
    if money.balance_order_id is None:
        raise SettlementError(
            "This deal has no balance obligation to settle.",
            code="deal_balance_order_missing",
        )

    result.ledger_transaction_id = _post_reallocation(
        plan=plan, settlement_key=settlement_key, note=note
    )
    if plan.sender_refund_eur_cents > 0:
        result.refund_ids = _refund_sender_share(
            plan=plan,
            settlement_key=settlement_key,
            refund_reason=refund_reason,
            actor_id=actor_id,
        )
    result.payout_status = _apply_payout_share(
        plan=plan, settlement_key=settlement_key, note=note
    )
    result.changed = True
    return result


def _post_reallocation(
    *, plan: SettlementPlan, settlement_key: str, note: str
) -> int | None:
    """Undo the funded split and recognise the resolved one. Idempotent on key.

    Funding recognised the whole sender payment as `traveler_payable` plus
    `platform_commission`. This moves whatever is no longer theirs back into
    `deal_funds`, which is the account the refunds then draw down. It is a
    compensating transaction: the original funding entry is never edited.
    """

    money = plan.money
    # Derived from the ledger's current position, not from the price frozen at
    # acceptance. Those two agree on a Deal's first settlement and diverge on
    # every one after it -- a second settlement computed from the frozen price
    # re-releases liabilities that the first one already released, and the
    # books end up claiming a pool twice the size of anything ever collected.
    # Recomputing instead of incrementing is the same discipline
    # `_recompute_order_money` applies to an order's cash.
    recognised_traveler = -ledger.deal_balance(
        money.deal_id, LedgerAccount.TRAVELER_PAYABLE
    )
    recognised_platform = -ledger.deal_balance(
        money.deal_id, LedgerAccount.PLATFORM_COMMISSION
    )
    # What the traveler should still be owed, as opposed to what they have
    # already been sent.
    outstanding_traveler = (
        plan.traveler_payout_eur_cents - int(money.paid_out_eur_cents)
    )
    delta_traveler = recognised_traveler - outstanding_traveler
    delta_platform = recognised_platform - plan.platform_fee_eur_cents
    released = delta_traveler + delta_platform
    if delta_traveler == 0 and delta_platform == 0:
        return None

    deal = Deal.objects.get(pk=money.deal_id)
    legs = []
    if delta_traveler:
        legs.append(
            ledger.Leg(
                account=LedgerAccount.TRAVELER_PAYABLE,
                amount_eur_cents=delta_traveler,
                user_id=deal.traveler_id,
                order_id=money.balance_order_id,
                deal_id=deal.pk,
                note="Traveler liability re-recognised at settlement",
            )
        )
    if delta_platform:
        legs.append(
            ledger.Leg(
                account=LedgerAccount.PLATFORM_COMMISSION,
                amount_eur_cents=delta_platform,
                order_id=money.balance_order_id,
                deal_id=deal.pk,
                note="Commission re-recognised at settlement",
            )
        )
    if released:
        legs.append(
            ledger.Leg(
                account=LedgerAccount.DEAL_FUNDS,
                amount_eur_cents=-released,
                order_id=money.balance_order_id,
                deal_id=deal.pk,
                note="Funds returned to the deal pool for settlement",
            )
        )
    original = LedgerTransaction.objects.filter(
        key=f"deal_funding:deal:{deal.pk}"
    ).first()
    posted = ledger.record_correction(
        key=f"settlement:{settlement_key}",
        legs=legs,
        note=note[:255],
        reverses_id=original.pk if original is not None else None,
    )
    return posted.transaction_id


def _refund_sender_share(
    *, plan: SettlementPlan, settlement_key: str, refund_reason: str, actor_id: int | None
) -> list[int]:
    """Return the sender's share as cash, balance order first.

    The balance order is closed to further collection before anything is
    refunded. Releasing deposit credit restores its outstanding amount, and an
    order that is both settled and collectable would let a stray provider
    success re-fund a Deal that has just been unwound.
    """

    from .services import close_order_to_collection

    money = plan.money
    outstanding_refund = plan.sender_refund_eur_cents
    refund_ids: list[int] = []

    close_order_to_collection(
        order_id=money.balance_order_id, reason=refund_reason[:64]
    )

    outstanding_refund, ids = _refund_from_order(
        order_id=money.balance_order_id,
        amount=outstanding_refund,
        settlement_key=settlement_key,
        refund_reason=refund_reason,
        actor_id=actor_id,
    )
    refund_ids.extend(ids)

    if outstanding_refund > 0 and money.deposit_order_id is not None:
        released = _release_deposit_credit_share(
            plan=plan,
            settlement_key=settlement_key,
            amount=min(outstanding_refund, int(money.credited_eur_cents)),
        )
        if released > 0:
            close_order_to_collection(
                order_id=money.deposit_order_id, reason=refund_reason[:64]
            )
            outstanding_refund, ids = _refund_from_order(
                order_id=money.deposit_order_id,
                amount=min(outstanding_refund, released),
                settlement_key=settlement_key,
                refund_reason=refund_reason,
                actor_id=actor_id,
            )
            refund_ids.extend(ids)

    if outstanding_refund > 0:
        # Reachable only if captured cash disagrees with the terms snapshot,
        # which means something upstream is already wrong. Refuse loudly rather
        # than resolving a dispute with money that is not there.
        raise SettlementError(
            "The deal does not hold enough refundable cash for this settlement.",
            code="settlement_insufficient_cash",
            shortfall_eur_cents=outstanding_refund,
        )
    return refund_ids


def _refund_from_order(
    *,
    order_id: int,
    amount: int,
    settlement_key: str,
    refund_reason: str,
    actor_id: int | None,
) -> tuple[int, list[int]]:
    """Spend `amount` across one order's captures, ascending attempt id."""

    from .services import request_refund

    remaining = amount
    refund_ids: list[int] = []
    if remaining <= 0:
        return remaining, refund_ids

    attempts = list(
        PaymentAttempt.objects.filter(
            order_id=order_id,
            status=PaymentAttempt.Status.SUCCEEDED,
            is_unapplied=False,
        ).order_by("pk")
    )
    for attempt in attempts:
        if remaining <= 0:
            break
        already = int(
            PaymentRefund.objects.filter(
                attempt=attempt,
                status__in=(
                    PaymentRefund.Status.PENDING,
                    PaymentRefund.Status.PROCESSING,
                    PaymentRefund.Status.SUCCEEDED,
                ),
            ).aggregate(total=Sum("amount_eur_cents"))["total"]
            or 0
        )
        available = int(attempt.amount_eur_cents) - already
        if available <= 0:
            continue
        chunk = min(available, remaining)
        refund = request_refund(
            order_id=order_id,
            attempt_id=attempt.pk,
            amount_eur_cents=chunk,
            reason=refund_reason,
            requested_by_id=actor_id,
            idempotency_key=f"settlement:{settlement_key}:attempt:{attempt.pk}",
        )
        refund_ids.append(refund.pk)
        remaining -= chunk
    return remaining, refund_ids


def _release_deposit_credit_share(
    *, plan: SettlementPlan, settlement_key: str, amount: int
) -> int:
    """Hand back exactly the deposit credit that is about to be refunded.

    Releasing the whole credit when only part is refunded would leave the
    ledger claiming a deposit liability to a sender who is owed nothing, and a
    matching phantom balance in `deal_funds`. So this releases `amount` and no
    more, and only ever runs once per settlement key.
    """

    money = plan.money
    if amount <= 0 or money.deposit_order_id is None:
        return 0

    posted = ledger.record_correction(
        key=f"settlement_deposit_release:{settlement_key}",
        note=f"Deposit credit released for settlement of deal #{money.deal_id}",
        legs=[
            ledger.Leg(
                account=LedgerAccount.DEAL_FUNDS,
                amount_eur_cents=amount,
                order_id=money.balance_order_id,
                deal_id=money.deal_id,
                note="Deal funds released for deposit refund",
            ),
            ledger.Leg(
                account=LedgerAccount.SENDER_DEPOSIT,
                amount_eur_cents=-amount,
                order_id=money.deposit_order_id,
                deal_id=money.deal_id,
                note="Deposit liability restored",
            ),
        ],
    )
    if not posted.created:
        # A retry. The credit was already reduced by the winning run; reducing
        # it again would let the same cents be refunded twice.
        return amount

    order = PaymentOrder.objects.select_for_update().get(pk=money.balance_order_id)
    order.credited_eur_cents = max(0, int(order.credited_eur_cents) - amount)
    fields = ["credited_eur_cents", "updated_at"]
    if order.credited_eur_cents == 0:
        order.credit_source = None
        fields.append("credit_source")
    order.save(update_fields=fields)
    return amount


def _apply_payout_share(
    *, plan: SettlementPlan, settlement_key: str, note: str
) -> str:
    """Set the traveler's payout to what the settlement says they are owed.

    A settlement is a decision, so it releases directly rather than waiting for
    a protection window that has either already run or been overtaken by the
    dispute. A zero share cancels the payout instead of storing a zero amount,
    which the `fin_payout_amount_positive` constraint would refuse anyway.
    """

    payout = Payout.objects.select_for_update().filter(deal_id=plan.money.deal_id).first()
    if payout is None:
        return "no_payout"
    if payout.status == Payout.Status.PAID:
        # The money has left. A settlement cannot claw it back automatically;
        # that is an operator recovery, and the dispute record says so.
        logger.warning(
            "finance.settlement_after_payout_paid deal=%s payout=%s",
            plan.money.deal_id,
            payout.pk,
        )
        return Payout.Status.PAID

    now = timezone.now()
    if plan.traveler_payout_eur_cents <= 0:
        payout.status = Payout.Status.CANCELLED
        payout.notes = f"{note}"[:2000]
        payout.save(update_fields=["status", "notes", "updated_at"])
        return payout.status

    payout.amount_eur_cents = plan.traveler_payout_eur_cents
    payout.status = Payout.Status.ELIGIBLE
    payout.eligible_at = payout.eligible_at or now
    payout.scheduled_for = now
    payout.notes = f"{note}"[:2000]
    payout.save(
        update_fields=[
            "amount_eur_cents",
            "status",
            "eligible_at",
            "scheduled_for",
            "notes",
            "updated_at",
        ]
    )
    return payout.status


def assert_deal_reconciles(deal_id: int) -> dict:
    """Sum every ledger account for one Deal. Used by tests and admin checks.

    After a settled Deal has had its refunds succeed, every account except
    `provider_clearing` (which nets the cash that came in and went back out)
    should be exactly the amounts the settlement decided.
    """

    balances = {
        account: ledger.deal_balance(deal_id, account)
        for account in (
            LedgerAccount.PROVIDER_CLEARING,
            LedgerAccount.SENDER_DEPOSIT,
            LedgerAccount.DEAL_FUNDS,
            LedgerAccount.TRAVELER_PAYABLE,
            LedgerAccount.PLATFORM_COMMISSION,
        )
    }
    balances["net"] = sum(balances.values())
    return balances
