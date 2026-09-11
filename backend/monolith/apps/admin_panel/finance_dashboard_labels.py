"""Operator wording for the H5 Finance vocabulary.

Every key here names something the H5 backend already returns. Nothing in this
module computes, converts or combines money: it maps an enum the database
stores to the words a Finance operator reads, and says what each state means
in one sentence. When H5 adds a state this file has no wording for, the
presenter falls back to the raw key with its underscores removed, so an unknown
state stays visible rather than being silently dropped.
"""

from __future__ import annotations

MODES = {
    "test": "TEST",
    "live": "LIVE",
    "legacy_unknown": "Legacy / unknown",
}

MODE_HELP = {
    "test": "Provider sandbox money. Nothing counted here is real cash.",
    "live": "Real money.",
    "legacy_unknown": (
        "Historical rows whose provider environment was never recorded. They "
        "are reported on their own and are never counted as TEST or LIVE."
    ),
}

PERIODS = (
    ("today", "Today"),
    ("7d", "Last 7 days"),
    ("30d", "Last 30 days"),
    ("custom", "Custom range"),
)

PROVIDERS = {"stripe": "Stripe", "chargily": "Chargily"}

RAILS = {
    "stripe_eur": "Stripe EUR transfer",
    "manual_dzd": "Manual DZD transfer",
    "legacy_unclassified": "Unclassified rail",
}

RAIL_HELP = {
    "stripe_eur": (
        "ShipTrip moves euros to the Traveler's connected account, and then the "
        "bank pays them out. Those are two different steps."
    ),
    "manual_dzd": (
        "A person at ShipTrip sends Algerian dinars by hand, against a "
        "settlement amount frozen when the instruction was created."
    ),
    "legacy_unclassified": (
        "Awards created before the rail was stored as a frozen method and "
        "currency. They belong to neither rail and are shown here so they are "
        "not quietly missing from both."
    ),
}

HELD_CHOICES = (
    ("", "Any"),
    ("true", "Held or disputed"),
    ("false", "Not held and not disputed"),
    ("disputed", "Disputed only"),
)

FUNDING_MIX = {
    "stripe": "Stripe-funded",
    "chargily": "Chargily-funded",
    "mixed": "Mixed funding",
    "unclassified": "Unclassified funding",
}

#: Exclusive Traveler-liability buckets, ordered the way an obligation normally
#: travels rather than in the backend's precedence order.
LIABILITY_ORDER = (
    "pre_delivery",
    "protection",
    "awaiting_release",
    "scheduled",
    "eligible",
    "processing",
    "sent",
    "held",
    "disputed",
    "blocked",
    "inconsistent",
)

LIABILITY_LABELS = {
    "pre_delivery": "Funded, not yet delivered",
    "protection": "In the protection period",
    "awaiting_release": "Awaiting a release decision",
    "scheduled": "Scheduled for payout",
    "eligible": "Ready for payout",
    "processing": "Processing or externally committed",
    "sent": "Marked sent",
    "held": "On hold",
    "disputed": "Disputed",
    "blocked": "Blocked",
    "inconsistent": "Inconsistent, needs review",
}

LIABILITY_HELP = {
    "pre_delivery": "The Deal is funded and delivery has not been confirmed.",
    "protection": "Delivered, with the stored protection deadline still running.",
    "awaiting_release": (
        "Nonzero payable with no authoritative release yet. Time passing on its "
        "own does not release it."
    ),
    "scheduled": "Released and queued for execution.",
    "eligible": "Released, nothing blocking it, waiting for the rail to take it.",
    "processing": (
        "An instruction is out, or ShipTrip money is already sitting at the "
        "provider."
    ),
    "sent": "Recorded as sent on its rail.",
    "held": "An active Finance hold stops this award.",
    "disputed": "A ShipTrip or provider dispute freezes this award.",
    "blocked": "Blocked or failed for a substantive reason.",
    "inconsistent": (
        "The payable and the payout state disagree. This is a reconciliation "
        "defect, not a work queue."
    ),
}

#: Operational rail stages, ordered along each rail's real lifecycle.
STRIPE_STAGE_ORDER = (
    "pre_delivery",
    "protection",
    "awaiting_release",
    "scheduled",
    "eligible",
    "transfer_committed_or_unknown",
    "connected_funds",
    "connected_balance_pending",
    "bank_processing",
    "bank_in_transit",
    "settled",
    "failed_or_returned",
    "blocked_or_failed",
    "held",
    "disputed",
    "sent",
    "processing",
    "inconsistent",
)

MANUAL_STAGE_ORDER = (
    "pre_delivery",
    "protection",
    "awaiting_release",
    "scheduled",
    "waiting_for_finance",
    "claimed",
    "transfer_processing",
    "transfer_sent",
    "settled",
    "blocked_or_failed",
    "failed_or_returned",
    "held",
    "disputed",
    "eligible",
    "processing",
    "inconsistent",
)

STAGE_LABELS = {
    "settled": "Paid",
    "failed_or_returned": "Bank payout failed or returned",
    "blocked_or_failed": "Blocked or failed",
    # The bucket fallback and the rail stage are different facts and must not
    # share a label: one is a stored block reason, the other a blocked or
    # failed payout record. Two identical options in the stage filter would be
    # unusable with a screen reader and ambiguous with one.
    "blocked": "Blocked by a stored reason",
    "transfer_sent": "Transfer sent",
    "transfer_processing": "Being sent",
    "claimed": "Claimed by Finance",
    "waiting_for_finance": "Waiting for Finance",
    "bank_in_transit": "Bank payout in transit",
    "bank_processing": "Bank payout processing",
    "connected_balance_pending": "Connected balance not yet available",
    "connected_funds": "Money at the connected account",
    "transfer_committed_or_unknown": "Transfer committed, outcome unconfirmed",
    **{key: label for key, label in LIABILITY_LABELS.items() if key != "blocked"},
}

STAGE_HELP = {
    "settled": (
        "Money has reached the Traveler. This is a current-state count, not the "
        "period's paid flow."
    ),
    "failed_or_returned": (
        "The bank refused or returned the payout. The Traveler is still owed."
    ),
    "transfer_sent": "A person recorded the dinar transfer as sent.",
    "transfer_processing": "A person is sending the dinar transfer now.",
    "claimed": "A Finance operator has taken this instruction.",
    "waiting_for_finance": "Released, and no operator has picked it up yet.",
    "bank_in_transit": "The bank holds the money and is moving it.",
    "bank_processing": "The bank payout exists and has not started moving.",
    "connected_balance_pending": (
        "The transfer landed, and the connected balance is not yet available to "
        "pay out."
    ),
    "connected_funds": (
        "ShipTrip's euros are at the Traveler's connected account. The Traveler "
        "has not been paid."
    ),
    "transfer_committed_or_unknown": (
        "An instruction was accepted, or its outcome is unknown. Nothing new "
        "will be sent for it."
    ),
    **LIABILITY_HELP,
}

#: `integrity.comparisons`.
COMPARISON_LABELS = {
    "traveler_state_to_ledger": "Payout state vs ledger payable",
    "traveler_dashboard_to_ledger": "Reported Traveler liability vs ledger payable",
    "applied_funding": "Applied funding vs captured ledger",
    "finalized_refunds": "Finalised refunds vs refund ledger",
    "paid_settlements": "Paid settlements vs discharge ledger",
    "platform_recognition_partition": "Recognised + pending vs allocated platform share",
}

COMPARISON_HELP = {
    "traveler_state_to_ledger": (
        "Each unpaid award compared with its own Deal's ledger balance, so two "
        "opposite gaps cannot cancel each other out."
    ),
    "traveler_dashboard_to_ledger": (
        "The liability reported above compared with the complete scoped ledger, "
        "which catches payable that no award owns."
    ),
    "applied_funding": (
        "Successful applied captures compared with the money legs they wrote."
    ),
    "finalized_refunds": (
        "Successful refund records compared with the refund legs they wrote."
    ),
    "paid_settlements": (
        "Paid bank allocations and manual paid records compared with the "
        "payable actually discharged."
    ),
    "platform_recognition_partition": (
        "Recognised revenue plus pending earnings must equal the whole "
        "platform-share ledger."
    ),
}

WARNING_LABELS = {
    "legacy_refund_ledger_mode_attributed_from_agreeing_refund_and_capture": (
        "Some ledger rows were attributed to this mode from an agreeing refund "
        "and capture rather than from a stored mode."
    ),
    "failed_refund_entitlement_requires_review": (
        "Refund executions failed. Whether the Sender is still entitled to that "
        "money has to be decided by a person."
    ),
    "provider_dispute_canonical_amount_incomplete": (
        "At least one provider dispute has no canonical euro amount, so the "
        "dispute total is partial."
    ),
    "unclassified_funding_provenance": (
        "At least one award's funding source could not be classified as Stripe "
        "or Chargily."
    ),
    "legacy_mode_not_test_or_live": (
        "This is the legacy/unknown cohort. These rows were never recorded as "
        "TEST or LIVE and are reported separately on purpose."
    ),
}

DATA_ISSUE_LABELS = {
    "successful_capture_missing_timestamp": (
        "Successful captures with no success timestamp"
    ),
    "successful_refund_missing_timestamp": (
        "Successful refunds with no success timestamp"
    ),
    "discharge_without_payout_evidence": (
        "Payable discharged with no paid evidence on the payout"
    ),
}

INTEGRITY_STATES = {
    "ok": (
        "Finance data reconciles",
        "ok",
        "Every required comparison agrees and every selected ledger transaction "
        "balances.",
    ),
    "warning": (
        "Reconciled, with a stated limitation",
        "wait",
        "The totals reconcile. One or more explicit limitations apply to how "
        "they were derived.",
    ),
    "mismatch": (
        "Finance data does not reconcile",
        "bad",
        "At least one required comparison disagrees. Treat the totals on this "
        "page as unreliable until it is resolved.",
    ),
}

#: Metric key → the noun its `count` counts. H5 is explicit that ledger-entry,
#: payout and refund counts are not interchangeable, so no bare number is ever
#: printed next to an amount.
COUNT_NOUNS = {
    "gross_funded": ("funding entry", "funding entries"),
    "deposits_collected": ("deposit entry", "deposit entries"),
    "deposits_credited": ("credit entry", "credit entries"),
    "deposits_held": ("deposit entry", "deposit entries"),
    "deposits_refunded": ("refund", "refunds"),
    "boost_funded": ("Boost entry", "Boost entries"),
    "recognized_revenue": ("ledger entry", "ledger entries"),
    "pending_earnings": ("ledger entry", "ledger entries"),
    "traveler_outstanding": ("payout", "payouts"),
    "payouts_settled": ("discharge entry", "discharge entries"),
    "payout_returns": ("return entry", "return entries"),
    "connected_funds": ("ledger entry", "ledger entries"),
    "bank_in_transit": ("ledger entry", "ledger entries"),
    "externally_committed": ("payout", "payouts"),
    "source_reserved": ("reservation", "reservations"),
    "provider_disputes": ("dispute", "disputes"),
    "refunds_requested": ("refund", "refunds"),
    "refunds_processing": ("refund", "refunds"),
    "refunds_outstanding": ("refund", "refunds"),
    "refunds_failed": ("refund", "refunds"),
    "refunds_finalized": ("refund", "refunds"),
    "refunds_applied": ("refund", "refunds"),
    "user_disputed_payouts": ("payout", "payouts"),
    "held_payouts": ("payout", "payouts"),
    "provider_disputed_payouts": ("payout", "payouts"),
    "payout_operations": ("payout", "payouts"),
}

#: Column wording for the drilldown tables, keyed by the field name H5 emits.
FIELD_LABELS = {
    "amount_eur_cents": "Amount",
    "deal_reference": "Deal",
    "traveler_reference": "Traveler",
    "payout_reference": "Payout",
    "order_reference": "Order",
    "payout_reference_link": "Payout",
    "source_attempt_order_reference": "Source order",
    "row_reference": "Row",
    "status": "State",
    "bucket": "Liability bucket",
    "rail": "Rail",
    "operation_stage": "Stage",
    "funding_mix": "Funding source",
    "payout_amount_minor": "Frozen settlement",
    "payout_currency": "Settlement currency",
    "payout_amount_exponent": "Settlement exponent",
    "fx_rate_micros": "Frozen rate",
    "fx_snapshot_at": "Rate frozen at",
    "provider": "Provider",
    "purpose": "Purpose",
    "account": "Ledger account",
    "transaction_kind": "Posting",
    "transaction_created_at": "Posted",
    "succeeded_at": "Succeeded",
    "settlement_at": "Settled",
    "recognition_at": "Earning evidence",
    "effective_at": "Recognised",
    "attempt_succeeded_at": "Captured",
    "has_hold": "On hold",
    "has_user_dispute": "ShipTrip dispute",
    "has_provider_dispute": "Provider dispute",
    "connected": "At connected account",
    "transit": "In bank transit",
    "exposed": "Externally committed",
}

LEDGER_ACCOUNTS = {
    "provider_clearing": "Provider clearing",
    "traveler_payable": "Traveler payable",
    "platform_commission": "Platform share",
    "connect_funds": "Connected-account funds",
    "payout_in_transit": "Bank payout in transit",
    "sender_deposit": "Sender deposit",
    "deal_funds": "Deal funds",
}

TRANSACTION_KINDS = {
    "customer_payment": "Customer payment",
    "refund": "Refund",
    "payout": "Payout",
    "deposit_credit": "Deposit credit",
    "settlement": "Settlement",
    "correction": "Correction",
}

PURPOSES = {
    "posting_deposit": "Posting deposit",
    "boost": "Boost",
    "deal_balance": "Deal balance",
}


def humanise(value) -> str:
    """A safe last resort for a key this module has no wording for."""

    text = str(value if value is not None else "").replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else "—"
