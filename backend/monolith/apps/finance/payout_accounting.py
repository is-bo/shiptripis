"""Where a Traveler's EUR actually is, in double entry.

Before H3 the ledger knew two positions for a funded Deal: the platform holds
the money (`provider_clearing`) or it has been paid out. That was true while the
only rail was an operator's bank transfer, which is atomic from ShipTrip's point
of view. The Stripe rail is not: money leaves the platform balance at the
Transfer, sits in the Traveler's connected account, leaves *that* at the bank
payout, and only lands days later.

Three of those are distinct positions and each one is a different answer to
"where is this money and who is owed it":

``connect_funds``
    The Transfer succeeded. The cash is no longer in ShipTrip's Stripe balance
    and cannot fund a refund to the Sender, but the Traveler has not been paid —
    the payable is untouched.

``payout_in_transit``
    A bank payout has taken it out of the connected account. Still owed, still
    recoverable only through a provider-confirmed return.

discharged
    The provider says `paid`. Only then does the traveler payable go down.

Every posting here is idempotent on its own key, which is the public reference
of the operation or disbursement that caused it. A replayed webhook, a duplicate
reconciliation job and an operator refresh all resolve to the same key, so the
second one records nothing. Corrections are new compensating transactions —
`record_bank_payout_returned` deliberately does not undo the paid posting, it
posts against it, because a genuine late bank return is a real event on a real
date and rewriting it away would make the books lie about both.
"""

from __future__ import annotations

from . import ledger
from .models import LedgerAccount


def _pair(allocations, *, debit: str, credit: str, debit_note: str, credit_note: str):
    """Two legs per allocated Payout, not two legs per disbursement.

    A disbursement may cover more than one Payout, and each Payout belongs to a
    different Deal. Tagging both sides of every movement with the payout and the
    Deal keeps each Deal's own sub-ledger summing to zero, which is what
    `assert_deal_reconciles` checks and what a Finance drill-down reads.
    """

    legs = []
    for allocation in allocations:
        amount = int(allocation.amount_eur_cents)
        payout = allocation.payout
        legs.append(
            ledger.Leg(
                account=debit,
                amount_eur_cents=amount,
                user_id=payout.traveler_id,
                payout_id=payout.pk,
                deal_id=payout.deal_id,
                note=debit_note,
            )
        )
        legs.append(
            ledger.Leg(
                account=credit,
                amount_eur_cents=-amount,
                user_id=payout.traveler_id,
                payout_id=payout.pk,
                deal_id=payout.deal_id,
                note=credit_note,
            )
        )
    return legs


def record_transfer_accepted(*, operation, payout, amount_eur_cents: int):
    """Platform Stripe balance → this Traveler's connected-account balance.

    The traveler payable is deliberately untouched. A Transfer is ShipTrip
    moving its own asset between two of its own positions; the Traveler is not
    paid by it and cannot spend it until a bank payout completes.
    """

    return ledger.post(
        key=f"payout_transfer:{operation.public_reference}",
        kind="payout",
        note=f"Transfer for payout #{payout.pk}",
        legs=[
            ledger.Leg(
                account=LedgerAccount.CONNECT_FUNDS,
                amount_eur_cents=int(amount_eur_cents),
                user_id=payout.traveler_id,
                payout_id=payout.pk,
                deal_id=payout.deal_id,
                note="Funds moved to the connected account",
            ),
            ledger.Leg(
                account=LedgerAccount.PROVIDER_CLEARING,
                amount_eur_cents=-int(amount_eur_cents),
                payout_id=payout.pk,
                deal_id=payout.deal_id,
                note="Platform balance debited for transfer",
            ),
        ],
    )


def record_transfer_reversed(*, operation, payout, amount_eur_cents: int, sequence: int):
    """Connected-account balance → platform balance, for a confirmed reversal.

    Keyed on the reversal's own sequence, because a Transfer may be reversed
    more than once (partially) and each recovery is its own cash movement.
    """

    return ledger.post(
        key=f"payout_transfer_reversed:{operation.public_reference}:{sequence}",
        kind="correction",
        note=f"Transfer reversal for payout #{payout.pk}",
        legs=[
            ledger.Leg(
                account=LedgerAccount.PROVIDER_CLEARING,
                amount_eur_cents=int(amount_eur_cents),
                payout_id=payout.pk,
                deal_id=payout.deal_id,
                note="Platform balance restored by reversal",
            ),
            ledger.Leg(
                account=LedgerAccount.CONNECT_FUNDS,
                amount_eur_cents=-int(amount_eur_cents),
                user_id=payout.traveler_id,
                payout_id=payout.pk,
                deal_id=payout.deal_id,
                note="Connected account balance recovered",
            ),
        ],
    )


def record_bank_payout_submitted(*, disbursement, allocations):
    """Connected-account balance → in transit. Still owed to the Traveler."""

    return ledger.post(
        key=f"payout_bank_submitted:{disbursement.public_reference}",
        kind="payout",
        note=f"Bank payout submitted for disbursement {disbursement.pk}",
        legs=_pair(
            allocations,
            debit=LedgerAccount.PAYOUT_IN_TRANSIT,
            credit=LedgerAccount.CONNECT_FUNDS,
            debit_note="Bank payout submitted",
            credit_note="Connected account debited for bank payout",
        ),
    )


def record_bank_payout_paid(*, disbursement, allocations):
    """The provider says the money arrived. This is the only discharge."""

    return ledger.post(
        key=f"payout_bank_paid:{disbursement.public_reference}",
        kind="payout",
        note=f"Bank payout paid for disbursement {disbursement.pk}",
        legs=_pair(
            allocations,
            debit=LedgerAccount.TRAVELER_PAYABLE,
            credit=LedgerAccount.PAYOUT_IN_TRANSIT,
            debit_note="Traveler payable discharged by bank payout",
            credit_note="Bank payout settled",
        ),
    )


def record_bank_payout_failed(*, disbursement, allocations):
    """The bank refused before settlement; Stripe returns it to the account.

    The payable is untouched because it was never discharged. What changes is
    only where the asset sits, which is what makes a bank-payout-only retry the
    correct recovery and re-creating the Transfer a double spend.
    """

    return ledger.post(
        key=f"payout_bank_failed:{disbursement.public_reference}",
        kind="correction",
        note=f"Bank payout failed for disbursement {disbursement.pk}",
        legs=_pair(
            allocations,
            debit=LedgerAccount.CONNECT_FUNDS,
            credit=LedgerAccount.PAYOUT_IN_TRANSIT,
            debit_note="Funds returned to the connected account",
            credit_note="Bank payout failed before settlement",
        ),
    )


def record_bank_payout_returned(*, disbursement, allocations):
    """A genuine bank return after `paid`. The obligation comes back.

    Compensating, never corrective-by-erasure: the paid posting keeps its own
    date and stays in the period it happened in, and this restores the liability
    on the date the money actually came back.
    """

    return ledger.post(
        key=f"payout_bank_returned:{disbursement.public_reference}",
        kind="correction",
        note=f"Bank payout returned for disbursement {disbursement.pk}",
        legs=_pair(
            allocations,
            debit=LedgerAccount.CONNECT_FUNDS,
            credit=LedgerAccount.TRAVELER_PAYABLE,
            debit_note="Funds returned to the connected account",
            credit_note="Traveler payable restored after a bank return",
        ),
    )
