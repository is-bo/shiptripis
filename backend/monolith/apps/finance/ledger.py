"""Append-only double-entry ledger for V1 money.

Every financial fact is one `LedgerTransaction` holding a balanced set of
`LedgerEntry` rows. Two properties follow, and both are tested rather than
assumed:

*Nothing is created from nothing.* Entries within a transaction sum to zero, so
a bug that funds a Deal without a corresponding capture leaves an unbalanced
transaction that `post` refuses to write.

*History is never rewritten.* Entries and transactions reject `save()` on an
existing row and reject `delete()` outright. A mistake is corrected by posting
a new, linked compensating transaction, so the audit trail shows both the
original fact and its reversal.

`key` is the idempotency handle. A replayed webhook, a re-run scheduled job or
a double-submitted admin action resolves to the same key and is refused by the
unique index — `post` reports that as "already recorded", not as an error.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import IntegrityError, transaction

from .models import LedgerAccount, LedgerEntry, LedgerTransaction


class UnbalancedLedgerTransaction(RuntimeError):
    """The entries of one transaction do not sum to zero."""

    code = "unbalanced_ledger_transaction"


@dataclass(frozen=True, slots=True)
class Leg:
    """One signed leg of a ledger transaction.

    Positive increases an asset; negative increases a liability or recognises
    revenue. See `LedgerAccount` for the convention.
    """

    account: str
    amount_eur_cents: int
    user_id: int | None = None
    order_id: int | None = None
    attempt_id: int | None = None
    refund_id: int | None = None
    payout_id: int | None = None
    deal_id: int | None = None
    note: str = ""


@dataclass(frozen=True, slots=True)
class PostResult:
    transaction_id: int | None
    created: bool


def post(
    *,
    key: str,
    kind: str,
    legs: list[Leg],
    note: str = "",
    reverses_id: int | None = None,
) -> PostResult:
    """Write one balanced transaction. Idempotent on `key`.

    Returns `created=False` when the key was already recorded, which is the
    normal outcome of a duplicate provider event rather than a failure.
    """

    if not legs:
        raise UnbalancedLedgerTransaction("A ledger transaction needs entries.")
    total = sum(int(leg.amount_eur_cents) for leg in legs)
    if total != 0:
        raise UnbalancedLedgerTransaction(
            f"Ledger transaction {key!r} does not balance: net {total} cents."
        )
    if any(int(leg.amount_eur_cents) == 0 for leg in legs):
        raise UnbalancedLedgerTransaction(
            f"Ledger transaction {key!r} carries a zero-amount entry."
        )

    try:
        with transaction.atomic():
            from .models import PaymentAttempt, Payout

            modes = set(
                PaymentAttempt.objects.filter(
                    pk__in=[leg.attempt_id for leg in legs if leg.attempt_id]
                ).values_list("provider_mode", flat=True)
            )
            modes.update(
                Payout.objects.filter(
                    pk__in=[leg.payout_id for leg in legs if leg.payout_id]
                ).values_list("provider_mode", flat=True)
            )
            if not modes:
                modes.update(
                    PaymentAttempt.objects.filter(
                        order_id__in=[leg.order_id for leg in legs if leg.order_id],
                        status="succeeded",
                        is_unapplied=False,
                    ).values_list("provider_mode", flat=True)
                )
            mode = next(iter(modes)) if len(modes) == 1 else "legacy_unknown"
            ledger_transaction = LedgerTransaction.objects.create(
                key=key,
                kind=kind,
                provider_mode=mode,
                note=note[:255],
                reverses_id=reverses_id,
            )
            LedgerEntry.objects.bulk_create(
                [
                    LedgerEntry(
                        transaction=ledger_transaction,
                        account=leg.account,
                        amount_eur_cents=int(leg.amount_eur_cents),
                        user_id=leg.user_id,
                        order_id=leg.order_id,
                        attempt_id=leg.attempt_id,
                        refund_id=leg.refund_id,
                        payout_id=leg.payout_id,
                        deal_id=leg.deal_id,
                        note=leg.note[:255],
                    )
                    for leg in legs
                ]
            )
    except IntegrityError:
        # Replay. The savepoint above isolates the conflict so the caller's
        # surrounding transaction stays usable.
        existing = (
            LedgerTransaction.objects.filter(key=key)
            .values_list("id", flat=True)
            .first()
        )
        return PostResult(transaction_id=existing, created=False)
    return PostResult(transaction_id=ledger_transaction.pk, created=True)


def account_balance(account: str, *, user_id: int | None = None) -> int:
    """Sum one account, optionally for one user. Always computed, never stored."""

    from django.db.models import Sum

    queryset = LedgerEntry.objects.filter(account=account)
    if user_id is not None:
        queryset = queryset.filter(user_id=user_id)
    return int(queryset.aggregate(total=Sum("amount_eur_cents"))["total"] or 0)


def deal_balance(deal_id: int, account: str) -> int:
    from django.db.models import Sum

    return int(
        LedgerEntry.objects.filter(deal_id=deal_id, account=account).aggregate(
            total=Sum("amount_eur_cents")
        )["total"]
        or 0
    )


# --- the six facts the V1 ledger records -------------------------------------


def record_customer_payment(
    *,
    attempt_id: int,
    order_id: int,
    owner_id: int,
    amount_eur_cents: int,
    purpose: str,
    deal_id: int | None = None,
) -> PostResult:
    """Cash arrived at the provider against an obligation.

    Debit the provider clearing asset, credit the liability the money is held
    against: a posting deposit is owed back to the sender until it is credited
    or refunded; a deal balance is held pending delivery.
    """

    holding_account = (
        LedgerAccount.SENDER_DEPOSIT
        if purpose == "posting_deposit"
        else LedgerAccount.DEAL_FUNDS
    )
    return post(
        key=f"customer_payment:attempt:{attempt_id}",
        kind=LedgerTransaction.Kind.CUSTOMER_PAYMENT,
        note=f"Capture for order #{order_id} ({purpose})",
        legs=[
            Leg(
                account=LedgerAccount.PROVIDER_CLEARING,
                amount_eur_cents=amount_eur_cents,
                order_id=order_id,
                attempt_id=attempt_id,
                deal_id=deal_id,
                note="Provider capture",
            ),
            Leg(
                account=holding_account,
                amount_eur_cents=-amount_eur_cents,
                user_id=owner_id,
                order_id=order_id,
                attempt_id=attempt_id,
                deal_id=deal_id,
                note="Funds held",
            ),
        ],
    )


def record_deposit_credit(
    *,
    deposit_order_id: int,
    balance_order_id: int,
    owner_id: int,
    amount_eur_cents: int,
    deal_id: int,
) -> PostResult:
    """A paid posting deposit is applied to the accepted Deal's balance.

    No cash moves: the deposit liability is discharged and the deal-funds
    liability grows by the same amount. This is why the deposit is a credit and
    not a second charge.
    """

    return post(
        key=f"deposit_credit:order:{balance_order_id}",
        kind=LedgerTransaction.Kind.DEPOSIT_CREDIT,
        note=f"Deposit #{deposit_order_id} credited to balance #{balance_order_id}",
        legs=[
            Leg(
                account=LedgerAccount.SENDER_DEPOSIT,
                amount_eur_cents=amount_eur_cents,
                user_id=owner_id,
                order_id=deposit_order_id,
                deal_id=deal_id,
                note="Deposit discharged",
            ),
            Leg(
                account=LedgerAccount.DEAL_FUNDS,
                amount_eur_cents=-amount_eur_cents,
                user_id=owner_id,
                order_id=balance_order_id,
                deal_id=deal_id,
                note="Credited to deal balance",
            ),
        ],
    )


def record_deal_funding(
    *,
    deal_id: int,
    order_id: int,
    traveler_id: int,
    traveler_reward_eur_cents: int,
    platform_fee_eur_cents: int,
) -> PostResult:
    """The Deal is fully funded: split the held funds into what they now owe.

    The pooled deal-funds liability is released and re-recognised as a traveler
    payable plus platform commission. No money leaves the platform here — the
    payout is a separate, Phase 4-gated fact.
    """

    total = traveler_reward_eur_cents + platform_fee_eur_cents
    legs = [
        Leg(
            account=LedgerAccount.DEAL_FUNDS,
            amount_eur_cents=total,
            order_id=order_id,
            deal_id=deal_id,
            note="Deal funded",
        ),
        Leg(
            account=LedgerAccount.TRAVELER_PAYABLE,
            amount_eur_cents=-traveler_reward_eur_cents,
            user_id=traveler_id,
            order_id=order_id,
            deal_id=deal_id,
            note="Traveler liability recognised",
        ),
    ]
    if platform_fee_eur_cents:
        legs.append(
            Leg(
                account=LedgerAccount.PLATFORM_COMMISSION,
                amount_eur_cents=-platform_fee_eur_cents,
                order_id=order_id,
                deal_id=deal_id,
                note="Commission recognised",
            )
        )
    return post(
        key=f"deal_funding:deal:{deal_id}",
        kind=LedgerTransaction.Kind.DEAL_FUNDING,
        note=f"Deal #{deal_id} funded",
        legs=legs,
    )


def record_boost_binding(
    *,
    deal_id: int,
    order_id: int,
    purchase_id: int,
    amount_eur_cents: int,
) -> PostResult:
    """Attribute pre-Deal boost cash to the Deal without recognizing earnings.

    The original capture has neither leg tagged to a Deal because no Deal
    existed then. Reclassify both the provider asset and held-funds liability,
    keeping the unassigned and Deal subledgers independently balanced.
    """

    return post(
        key=f"boost_binding:purchase:{purchase_id}",
        kind=LedgerTransaction.Kind.BOOST_BINDING,
        note=f"Boost purchase #{purchase_id} bound to deal #{deal_id}",
        legs=[
            Leg(
                account=LedgerAccount.DEAL_FUNDS,
                amount_eur_cents=amount_eur_cents,
                order_id=order_id,
                note="Unassigned boost funds discharged on Deal binding",
            ),
            Leg(
                account=LedgerAccount.PROVIDER_CLEARING,
                amount_eur_cents=-amount_eur_cents,
                order_id=order_id,
                note="Unassigned boost clearing discharged on Deal binding",
            ),
            Leg(
                account=LedgerAccount.PROVIDER_CLEARING,
                amount_eur_cents=amount_eur_cents,
                order_id=order_id,
                deal_id=deal_id,
                note="Boost clearing attributed to Deal",
            ),
            Leg(
                account=LedgerAccount.DEAL_FUNDS,
                amount_eur_cents=-amount_eur_cents,
                order_id=order_id,
                deal_id=deal_id,
                note="Boost funds attributed to Deal",
            ),
        ],
    )


def record_boost_allocation(
    *,
    deal_id: int,
    order_id: int,
    purchase_id: int,
    traveler_id: int,
    traveler_boost_eur_cents: int,
    platform_boost_eur_cents: int,
) -> PostResult:
    """Recognise one paid boost's delivery bonus and platform revenue."""

    total = traveler_boost_eur_cents + platform_boost_eur_cents
    legs = [
        Leg(
            account=LedgerAccount.DEAL_FUNDS,
            amount_eur_cents=total,
            order_id=order_id,
            deal_id=deal_id,
            note="Paid boost allocated to delivery economics",
        ),
        Leg(
            account=LedgerAccount.TRAVELER_PAYABLE,
            amount_eur_cents=-traveler_boost_eur_cents,
            user_id=traveler_id,
            order_id=order_id,
            deal_id=deal_id,
            note="Traveler boost bonus recognised",
        ),
    ]
    if platform_boost_eur_cents:
        legs.append(
            Leg(
                account=LedgerAccount.PLATFORM_COMMISSION,
                amount_eur_cents=-platform_boost_eur_cents,
                order_id=order_id,
                deal_id=deal_id,
                note="Platform boost revenue recognised",
            )
        )
    return post(
        key=f"boost_allocation:purchase:{purchase_id}",
        kind=LedgerTransaction.Kind.BOOST_ALLOCATION,
        note=f"Boost purchase #{purchase_id} allocated to deal #{deal_id}",
        legs=legs,
    )


def record_deal_boost_allocation(
    *,
    deal_id: int,
    order_id: int,
    traveler_id: int,
    traveler_boost_eur_cents: int,
    platform_boost_eur_cents: int,
) -> PostResult:
    """Recognise a J2 Boost and its commission out of the funded deal balance.

    The Boost arrived inside the Deal's own balance order, so the held deal
    funds already contain it. This releases exactly that portion and splits it
    the way J2 defines: the Traveler receives the whole Boost as a bonus, and
    ShipTrip's Boost commission -- a separately configured rate, charged on top
    -- is recognised as platform revenue.

    Kept as its own transaction rather than folded into `deal_funding` for one
    reason: H5 has to be able to say how much of the platform's commission came
    from delivery and how much from Boost, and a merged entry cannot answer
    that. Keyed per Deal, so a replayed funding recognises it once.
    """

    total = int(traveler_boost_eur_cents) + int(platform_boost_eur_cents)
    legs = [
        Leg(
            account=LedgerAccount.DEAL_FUNDS,
            amount_eur_cents=total,
            order_id=order_id,
            deal_id=deal_id,
            note="Boost reward released from funded deal balance",
        ),
        Leg(
            account=LedgerAccount.TRAVELER_PAYABLE,
            amount_eur_cents=-int(traveler_boost_eur_cents),
            user_id=traveler_id,
            order_id=order_id,
            deal_id=deal_id,
            note="Traveler boost bonus recognised",
        ),
    ]
    if platform_boost_eur_cents:
        legs.append(
            Leg(
                account=LedgerAccount.PLATFORM_COMMISSION,
                amount_eur_cents=-int(platform_boost_eur_cents),
                order_id=order_id,
                deal_id=deal_id,
                note="Platform boost commission recognised",
            )
        )
    return post(
        key=f"deal_boost_allocation:deal:{deal_id}",
        kind=LedgerTransaction.Kind.BOOST_ALLOCATION,
        note=f"Deal #{deal_id} boost reward allocated",
        legs=legs,
    )


def record_refund(
    *,
    refund_id: int,
    order_id: int,
    owner_id: int,
    amount_eur_cents: int,
    purpose: str,
    deal_id: int | None = None,
) -> PostResult:
    """Money returned to the payer. The original capture is never touched."""

    holding_account = (
        LedgerAccount.SENDER_DEPOSIT
        if purpose == "posting_deposit"
        else LedgerAccount.DEAL_FUNDS
    )
    return post(
        key=f"refund:{refund_id}",
        kind=LedgerTransaction.Kind.REFUND,
        note=f"Refund #{refund_id} on order #{order_id}",
        legs=[
            Leg(
                account=holding_account,
                amount_eur_cents=amount_eur_cents,
                user_id=owner_id,
                order_id=order_id,
                refund_id=refund_id,
                deal_id=deal_id,
                note="Held funds released",
            ),
            Leg(
                account=LedgerAccount.PROVIDER_CLEARING,
                amount_eur_cents=-amount_eur_cents,
                order_id=order_id,
                refund_id=refund_id,
                deal_id=deal_id,
                note="Returned through provider",
            ),
        ],
    )


def record_payout(
    *,
    payout_id: int,
    deal_id: int,
    traveler_id: int,
    amount_eur_cents: int,
) -> PostResult:
    """Traveler earnings actually sent. Phase 4 owns when this may happen."""

    return post(
        key=f"payout:{payout_id}",
        kind=LedgerTransaction.Kind.PAYOUT,
        note=f"Payout #{payout_id} for deal #{deal_id}",
        legs=[
            Leg(
                account=LedgerAccount.TRAVELER_PAYABLE,
                amount_eur_cents=amount_eur_cents,
                user_id=traveler_id,
                payout_id=payout_id,
                deal_id=deal_id,
                note="Payable discharged",
            ),
            Leg(
                account=LedgerAccount.PROVIDER_CLEARING,
                amount_eur_cents=-amount_eur_cents,
                payout_id=payout_id,
                deal_id=deal_id,
                note="Funds sent",
            ),
        ],
    )


def record_correction(
    *,
    key: str,
    legs: list[Leg],
    note: str,
    reverses_id: int | None = None,
) -> PostResult:
    """Post a compensating transaction. The only way to change the past."""

    return post(
        key=key,
        kind=LedgerTransaction.Kind.CORRECTION,
        legs=legs,
        note=note,
        reverses_id=reverses_id,
    )
