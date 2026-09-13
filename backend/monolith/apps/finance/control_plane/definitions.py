"""The versioned vocabulary shared by queries, JSON and H5.1 consumers."""

from dataclasses import asdict, dataclass

VERSION = "h5.v1"
REPORTING_TIMEZONE = "Europe/Paris"
LIABILITY_BUCKETS = (
    "disputed",
    "held",
    "blocked",
    "processing",
    "sent",
    "protection",
    "pre_delivery",
    "scheduled",
    "eligible",
    "awaiting_release",
    "inconsistent",
)
OPERATION_STAGES = (
    "settled",
    "disputed",
    "held",
    "failed_or_returned",
    "blocked_or_failed",
    "transfer_sent",
    "transfer_processing",
    "claimed",
    "waiting_for_finance",
    "bank_in_transit",
    "bank_processing",
    "connected_balance_pending",
    "connected_funds",
    "transfer_committed_or_unknown",
    *LIABILITY_BUCKETS,
)


@dataclass(frozen=True)
class Definition:
    name: str
    definition: str
    source: str
    inclusion: str
    exclusion: str
    time_basis: str
    reconciliation: str
    unit: str = "EUR cents"


DEFINITIONS = {
    "payout_attention": Definition(
        "Payouts needing action",
        "Unique payouts with needs_attention from the shared payout_attention projection.",
        "Bound destination readiness, bank allocation, disputes and holds",
        "One primary safe blocker and nullable owner per payout, including setup before delivery.",
        "Normal delivery/protection and balance waiting; no addition of overlapping hold/dispute counts.",
        "Current snapshot; bounded to 5,000 payouts per scope, otherwise narrow filters.",
        "The same authoritative projection supplies the Overview count and this drilldown.",
    ),
    "payout_operations": Definition(
        "Payout operation records",
        "Current non-cancelled Payout awards, including settled records.",
        "Payout, local attempts and latest bank allocation",
        "One row per Payout; optional operation-stage filter.",
        "Cancelled rows. This is an operational cohort, not additional liability or period paid flow.",
        "Current snapshot.",
        "Exact rows behind rail_operations, grouped by rail and operation_stage.",
    ),
    "gross_funded": Definition(
        "Gross funded volume",
        "Successfully applied canonical funding before refunds.",
        "LedgerEntry: customer_payment/provider_clearing, linked PaymentAttempt",
        "Positive capture leg; succeeded, applied attempt; selected mode.",
        "Unapplied/failed attempts, deposit credit and Boost binding/allocation transfers.",
        "PaymentAttempt.succeeded_at",
        "Applied capture records = capture ledger legs.",
    ),
    "net_funded": Definition(
        "Net funded volume",
        "Period gross funded minus period finalized applied refunds.",
        "gross_funded and refunds_applied",
        "Same mode and scope; cash-flow period.",
        "Unapplied refunds; pending/processing/failed refunds; no second subtraction.",
        "Capture succeeded_at minus refund succeeded_at; may be negative in a period.",
        "net_funded = gross_funded - refunds_applied",
    ),
    "recognized_revenue": Definition(
        "Recognized ShipTrip revenue",
        "Net platform-share credits with final earning evidence.",
        "PLATFORM_COMMISSION entries + Deal.completed_at or final settlement evidence",
        "Clean completion or final settlement; later correction at its own posting time.",
        "Traveler principal, refundable funds, funding-time allocation without close evidence.",
        "Later of entry posting and first clean completion/final settlement timestamp.",
        "All-time recognized + pending platform earnings = net allocated platform share.",
    ),
    "pending_earnings": Definition(
        "Pending platform earnings",
        "Net allocated platform share without final earning evidence.",
        "PLATFORM_COMMISSION entries",
        "No clean completion/final settlement evidence.",
        "Recognized entries; unbound Boost held funds are not allocated platform earnings.",
        "Current consistent snapshot; period filter does not apply.",
        "Recognized + pending = allocated platform share.",
    ),
    "traveler_outstanding": Definition(
        "Traveler liability outstanding",
        "Negative net traveler payable, including bank returns.",
        "TRAVELER_PAYABLE ledger per Deal, selected mode",
        "All funded awards, including pre-delivery and restored obligations.",
        "Discharged cents; zero balances. Nonzero cancelled/paid balances remain visible.",
        "Current consistent snapshot; period filter does not apply.",
        "Ledger payable = current authorized unpaid Payout awards = exclusive bucket sum.",
    ),
    "payouts_settled": Definition(
        "Traveler payouts settled",
        "Gross historical positive payable discharge movements.",
        "payout/TRAVELER_PAYABLE positive legs",
        "Bank-paid allocations and operator-attested manual settlements.",
        "Transfers, bank submissions, returns, corrections and current-state-only inference.",
        "Matching bank disbursement paid_at or manual Payout.paid_at; missing evidence is excluded and reconciled.",
        "Discharge ledger = bank paid allocations + manual paid records; returns separate.",
    ),
    "payout_returns": Definition(
        "Traveler payout returns",
        "Historical restoration of a previously discharged payable.",
        "payout_bank_returned correction/TRAVELER_PAYABLE negative legs",
        "Authoritatively posted late returns.",
        "Failures before payment; Transfer reversals.",
        "Return ledger posting time.",
        "Net settled = gross settled - returns.",
    ),
    "connected_funds": Definition(
        "Connected-account funds",
        "Net local asset at connected accounts, still owed or recoverable.",
        "CONNECT_FUNDS ledger",
        "All signed movements, including returns and reversals.",
        "Provider live balances and platform clearing.",
        "Current consistent snapshot.",
        "Transfer accepted - bank submissions + bank failures/returns - Transfer reversals.",
    ),
    "bank_in_transit": Definition(
        "Bank payout in transit",
        "Local asset removed from connected funds awaiting outcome.",
        "PAYOUT_IN_TRANSIT ledger",
        "Net submissions, paid and failed corrections.",
        "Transfer success alone; manual DZD instructions.",
        "Current consistent snapshot.",
        "Submitted - settled - failed before settlement.",
    ),
    "externally_committed": Definition(
        "Externally committed Traveler funds",
        "Outstanding awards with external/unknown commitment.",
        "PayoutAttempt plus connected/transit ledger per Payout",
        "Committed/unknown/accepted/sent attempts or nonzero connected/transit balances.",
        "Prepared-only instructions; fully discharged obligations. Overlaps liability buckets.",
        "Current consistent snapshot.",
        "Orthogonal exposure; never added to total liability.",
    ),
    "source_reserved": Definition(
        "Source funding reserved",
        "Canonical source allocations whose reservation was not released.",
        "PayoutFundingAllocation without PayoutFundingRelease",
        "Same-mode allocation/source/Payout; selected actual funding provider.",
        "Released allocations. Settled allocations remain consumed, not available cash.",
        "Current consistent snapshot.",
        "Exact source attribution; not provider wallet balance.",
    ),
    "provider_disputes": Definition(
        "Provider disputes requiring recovery",
        "Locally attributable disputed canonical principal.",
        "ProviderDispute",
        "Open/review/warning or lost, in selected mode.",
        "Won/closed. Unknown canonical amount stays null/partial; never convert current FX.",
        "Current state, not created_at period.",
        "Exposure overlaps holds; never added to liability.",
    ),
}

for key, status in (
    ("refunds_requested", "pending"),
    ("refunds_processing", "processing"),
    ("refunds_failed", "failed"),
    ("refunds_finalized", "succeeded"),
    ("refunds_applied", "succeeded applied"),
    ("refunds_outstanding", "pending/processing"),
):
    DEFINITIONS[key] = Definition(
        key.replace("_", " ").title(),
        "Canonical refund rows in the named execution state.",
        "PaymentRefund",
        status + "; refund and capture modes must agree.",
        "Unapplied captures excluded only from refunds_applied. Failed execution reported separately: "
        "existing reservation service excludes failed refunds; unresolved entitlement is uncertain.",
        "succeeded_at for finalized/applied; current state for other buckets.",
        "Finalized records = refund ledger debits; applied finalized subtracted once from funded.",
    )

for key, purpose in (
    ("deposits_collected", "posting_deposit"),
    ("boost_funded", "boost"),
):
    DEFINITIONS[key] = Definition(
        key.replace("_", " ").title(),
        "Applied capture component of gross funded volume.",
        "gross_funded filtered by PaymentOrder.purpose",
        purpose,
        "Credits, binding and allocation entries; not an additional amount to add to gross.",
        "PaymentAttempt.succeeded_at",
        "Subset of gross funded, not separate revenue.",
    )

for key, basis, description in (
    (
        "deposits_credited",
        "Deposit credit ledger posting time",
        "Positive sender_deposit discharge for deposit_credit; no new funding.",
    ),
    (
        "deposits_held",
        "Current snapshot",
        "Negative net sender_deposit ledger for applied source orders; includes refunded/credited discharge.",
    ),
    (
        "deposits_refunded",
        "PaymentRefund.succeeded_at",
        "Finalized applied refunds on posting-deposit orders; subset of refunds_applied.",
    ),
    (
        "user_disputed_payouts",
        "Current snapshot",
        "Distinct outstanding payouts with an active ShipTrip user dispute.",
    ),
    (
        "provider_disputed_payouts",
        "Current snapshot",
        "Distinct outstanding payouts with attributable active/lost provider disputes.",
    ),
    (
        "held_payouts",
        "Current snapshot",
        "Distinct outstanding payouts affected by scoped active FinanceHold rows.",
    ),
):
    DEFINITIONS[key] = Definition(
        key.replace("_", " ").title(),
        description,
        "Existing ledger/refund/Payout rows; queries.metrics is the executable inclusion contract.",
        "Selected mode and scope.",
        "Other modes; duplicate join rows; no invented deposit forfeiture state.",
        basis,
        "Component/overlap only; never added again to funded or liability totals.",
    )

for bucket in LIABILITY_BUCKETS:
    DEFINITIONS[f"liability_{bucket}"] = Definition(
        f"Traveler liability: {bucket}",
        "Exclusive current payable bucket; precedence is registry order.",
        "Per-Deal payable and Payout lifecycle/holds/commitment",
        "Nonzero payable classified once by queries.payouts; final-settlement eligibility may precede delivery.",
        "Other liability buckets; paid/zero. External location remains a separate dimension.",
        "Current consistent snapshot.",
        "Sum of all exclusive buckets = traveler_outstanding.",
    )


def definitions():
    return {key: asdict(value) for key, value in DEFINITIONS.items()}
