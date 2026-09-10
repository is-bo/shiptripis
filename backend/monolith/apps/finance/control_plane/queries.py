"""One contributing-row query per KPI, reused for totals and drilldowns.

Existence/subqueries preserve one row per economic fact across multiple holds,
funding sources and bank allocations. No service that mutates money is imported.
"""

from dataclasses import dataclass

from django.db.models import (
    BigIntegerField,
    Case,
    CharField,
    Count,
    Exists,
    F,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Cast, Coalesce, Concat, Greatest, Least

from apps.deals.models import DealEvent
from apps.disputes.models import Dispute
from apps.finance.models import (
    FinanceHold,
    LedgerEntry,
    PaymentAttempt,
    PaymentOrder,
    PaymentProviderEvent,
    PaymentRefund,
    Payout,
    PayoutAttempt,
    PayoutFundingAllocation,
    ProviderDispute,
    StripeDisbursementAllocation,
)

ACTIVE_DISPUTES = ("open", "awaiting_evidence", "under_review")
ACTIVE_PROVIDER_DISPUTES = (
    "warning_needs_response",
    "warning_under_review",
    "needs_response",
    "under_review",
    "lost",
)
COMMITTED = ("dispatch_committed", "unknown", "accepted", "sent", "succeeded")


def mode_ledger(mode):
    """Resolve a narrow existing legacy metadata gap using explicit row evidence.

    record_refund historically inferred transaction mode from *applied* order
    captures, so refunding an entirely unapplied capture can leave the ledger
    mode unknown. The refund and its capture still carry agreeing explicit
    modes. Attribute those rows in SQL and disclose the fallback in integrity;
    never infer from names, current credentials or a different known mode.
    """
    # H1 migration 0012 classified old attempts, but deliberately did not
    # rewrite immutable ledger transactions introduced with unknown mode.
    # Re-prove that evidence rather than trusting a mode label or credentials.
    events = PaymentProviderEvent.objects.filter(
        attempt_id=OuterRef("attempt_id"),
        order_id=OuterRef("order_id"),
        provider=OuterRef("attempt__provider"),
        signature_verified=True,
    )
    evidence = events.filter(processing_result="applied").filter(
        Q(payload__livemode=False, attempt__provider_mode="test")
        | Q(payload__livemode=True, attempt__provider_mode="live")
    )
    conflicts = events.filter(
        Q(payload__livemode=True, attempt__provider_mode="test")
        | Q(payload__livemode=False, attempt__provider_mode="live")
        | Q(payload__data__object__livemode=True, attempt__provider_mode="test")
        | Q(payload__data__object__livemode=False, attempt__provider_mode="live")
        | Q(provider_mode="live", attempt__provider_mode="test")
        | Q(provider_mode="test", attempt__provider_mode="live")
    )
    other_links = LedgerEntry.objects.filter(
        transaction_id=OuterRef("transaction_id")
    ).exclude(attempt_id=OuterRef("attempt_id"), order_id=OuterRef("order_id"))
    rows = LedgerEntry.objects.annotate(
        proven_capture=Exists(evidence),
        conflicting_capture=Exists(conflicts),
        ambiguous_capture=Exists(other_links),
    ).annotate(
        mode_provenance=Case(
            When(
                transaction__provider_mode="legacy_unknown",
                transaction__kind="customer_payment",
                attempt__provider_mode__in=("test", "live"),
                attempt__mode_evidence="historical_provider_evidence",
                attempt__status="succeeded",
                attempt__order_id=F("order_id"),
                proven_capture=True,
                conflicting_capture=False,
                ambiguous_capture=False,
                then=Value("derived_from_authoritative_payment_attempt"),
            ),
            default=Value("stored"),
            output_field=CharField(),
        )
    )
    return rows.annotate(
        accounting_mode=Case(
            When(
                mode_provenance="derived_from_authoritative_payment_attempt",
                then=F("attempt__provider_mode"),
            ),
            When(
                transaction__provider_mode="legacy_unknown",
                refund__provider_mode__in=("test", "live"),
                refund__attempt__provider_mode=F("refund__provider_mode"),
                then=F("refund__provider_mode"),
            ),
            default=F("transaction__provider_mode"),
            output_field=CharField(),
        )
    ).filter(accounting_mode=mode)


def sum_subquery(queryset, group, field="amount_eur_cents"):
    return Coalesce(
        Subquery(
            queryset.order_by()
            .values(group)
            .annotate(total=Sum(field))
            .values("total")[:1],
            output_field=BigIntegerField(),
        ),
        Value(0),
        output_field=BigIntegerField(),
    )


def source_deal(prefix=""):
    """Deposits keep their original order; credited_into supplies Deal lineage."""
    return Coalesce(
        F(prefix + "order__deal_id"), F(prefix + "order__credited_into__deal_id")
    )


@dataclass(frozen=True)
class MetricQuery:
    rows: object
    amount: str = "amount_eur_cents"
    sign: int = 1
    kind: str = "ledger"
    dzd: str = ""

    def aggregate(self):
        fields = {
            "count": Count("pk"),
            "amount": Sum(self.amount),
            "known": Count(self.amount),
        }
        if self.dzd:
            fields.update(dzd=Sum(self.dzd), dzd_known=Count(self.dzd))
        value = self.rows.aggregate(**fields)
        complete = value["known"] == value["count"]
        result = {
            "count": value["count"],
            "amount_eur_cents": int(value["amount"] or 0) * self.sign
            if complete
            else None,
            "status": "available" if complete else "partial",
        }
        if not complete:
            result["known_amount_eur_cents"] = int(value["amount"] or 0) * self.sign
        if self.dzd:
            result["amount_dzd"] = (
                int(value["dzd"] or 0) if value["dzd_known"] == value["count"] else None
            )
            result["dzd_missing_count"] = value["count"] - value["dzd_known"]
        return result


class Queries:
    def __init__(self, scope, *, as_of):
        self.scope, self.as_of = scope, as_of
        self.payouts = self._payouts()
        self.has_cohort = bool(
            scope.rail
            or scope.state
            or scope.held
            or scope.search
            or scope.currency
            or scope.operation
        )

    def _payouts(self):
        mode, scope = self.scope.mode, self.scope
        ledger = mode_ledger(mode).filter(deal_id=OuterRef("deal_id"))
        holds = FinanceHold.objects.filter(cleared_at__isnull=True).filter(
            Q(payout_id=OuterRef("pk"))
            | Q(deal_id=OuterRef("deal_id"))
            | Q(account_id=OuterRef("stripe_account_id"), account_id__isnull=False)
            | Q(
                account_id=OuterRef("active_instruction_version__stripe_account_id"),
                account_id__isnull=False,
            )
            | Q(
                source_attempt_id=OuterRef("funding_attempt_id"),
                source_attempt_id__isnull=False,
            )
            | Q(
                source_attempt__payout_allocations__payout_id=OuterRef("pk"),
                source_attempt__payout_allocations__provider_mode=mode,
            )
        )
        sources = PaymentAttempt.objects.filter(
            provider_mode=mode, status="succeeded", is_unapplied=False
        ).filter(
            Q(order__deal_id=OuterRef("deal_id"))
            | Q(order__credited_into__deal_id=OuterRef("deal_id"))
        )
        provider_disputes = ProviderDispute.objects.filter(
            provider_mode=mode, status__in=ACTIVE_PROVIDER_DISPUTES
        ).filter(
            Q(source_attempt__order__deal_id=OuterRef("deal_id"))
            | Q(source_attempt__order__credited_into__deal_id=OuterRef("deal_id"))
        )
        rows = (
            Payout.objects.filter(provider_mode=mode)
            .annotate(
                payable=-sum_subquery(
                    ledger.filter(account="traveler_payable"), "deal_id"
                ),
                connected=sum_subquery(
                    ledger.filter(account="connect_funds"), "deal_id"
                ),
                transit=sum_subquery(
                    ledger.filter(account="payout_in_transit"), "deal_id"
                ),
                has_hold=Exists(holds),
                has_user_dispute=Exists(
                    Dispute.objects.filter(
                        deal_id=OuterRef("deal_id"), status__in=ACTIVE_DISPUTES
                    )
                ),
                has_provider_dispute=Exists(provider_disputes),
                has_dispute_hold=Exists(
                    holds.filter(kind__in=("dispute", "provider_dispute"))
                ),
                has_commitment=Exists(
                    PayoutAttempt.objects.filter(
                        payout_id=OuterRef("pk"),
                        provider_mode=mode,
                        status__in=COMMITTED,
                    )
                ),
                has_prepared=Exists(
                    PayoutAttempt.objects.filter(
                        payout_id=OuterRef("pk"), provider_mode=mode, status="prepared"
                    )
                ),
                stripe_source=Exists(sources.filter(provider="stripe")),
                chargily_source=Exists(sources.filter(provider="chargily")),
            )
            .annotate(
                is_disputed=Case(
                    When(
                        Q(has_user_dispute=True)
                        | Q(has_provider_dispute=True)
                        | Q(has_dispute_hold=True)
                        | Q(status="frozen"),
                        then=True,
                    ),
                    default=False,
                ),
                exposed=Case(
                    When(
                        Q(has_commitment=True) | ~Q(connected=0) | ~Q(transit=0),
                        then=True,
                    ),
                    default=False,
                ),
                rail=Case(
                    When(
                        method="stripe_transfer",
                        payout_currency="EUR",
                        then=Value("stripe_eur"),
                    ),
                    When(
                        method="manual", payout_currency="DZD", then=Value("manual_dzd")
                    ),
                    default=Value("legacy_unclassified"),
                    output_field=CharField(),
                ),
                funding_mix=Case(
                    When(stripe_source=True, chargily_source=True, then=Value("mixed")),
                    When(stripe_source=True, then=Value("stripe")),
                    When(chargily_source=True, then=Value("chargily")),
                    default=Value("unclassified"),
                    output_field=CharField(),
                ),
            )
            .annotate(
                bucket=Case(
                    When(
                        Q(payable__lt=0)
                        | (Q(status__in=("paid", "cancelled")) & ~Q(payable=0)),
                        then=Value("inconsistent"),
                    ),
                    When(is_disputed=True, then=Value("disputed")),
                    When(has_hold=True, then=Value("held")),
                    When(
                        Q(status__in=("blocked", "failed"))
                        | (
                            ~Q(block_reason="")
                            & ~Q(block_reason="connected_balance_pending")
                        ),
                        then=Value("blocked"),
                    ),
                    When(status="sent", then=Value("sent")),
                    When(
                        Q(exposed=True) | Q(status="processing"),
                        then=Value("processing"),
                    ),
                    When(
                        deal__delivery_confirmed_at__isnull=False,
                        deal__protection_ends_at__gt=self.as_of,
                        then=Value("protection"),
                    ),
                    When(
                        deal__delivery_confirmed_at__isnull=True,
                        eligibility_basis__in=("", "delivery_protection"),
                        then=Value("pre_delivery"),
                    ),
                    When(
                        status="scheduled",
                        eligible_at__isnull=False,
                        then=Value("scheduled"),
                    ),
                    When(
                        status="eligible",
                        eligible_at__isnull=False,
                        then=Value("eligible"),
                    ),
                    default=Value("awaiting_release"),
                    output_field=CharField(),
                )
            )
        )
        bank = (
            StripeDisbursementAllocation.objects.filter(
                payout_id=OuterRef("pk"),
                disbursement__provider_mode=mode,
            )
            .order_by("-disbursement__created_at", "-pk")
            .values("disbursement__status")[:1]
        )
        rows = rows.annotate(bank_stage=Subquery(bank)).annotate(
            operation_stage=Case(
                When(status="paid", then=Value("settled")),
                When(is_disputed=True, then=Value("disputed")),
                When(has_hold=True, then=Value("held")),
                When(
                    bank_stage__in=("failed", "canceled", "returned"),
                    then=Value("failed_or_returned"),
                ),
                When(status__in=("blocked", "failed"), then=Value("blocked_or_failed")),
                When(rail="manual_dzd", status="sent", then=Value("transfer_sent")),
                When(
                    rail="manual_dzd",
                    status="processing",
                    then=Value("transfer_processing"),
                ),
                When(rail="manual_dzd", has_prepared=True, then=Value("claimed")),
                When(
                    rail="manual_dzd",
                    status__in=("eligible", "scheduled"),
                    then=Value("waiting_for_finance"),
                ),
                When(bank_stage="in_transit", then=Value("bank_in_transit")),
                When(
                    bank_stage__in=("committed", "unknown", "pending"),
                    then=Value("bank_processing"),
                ),
                When(
                    connected__gt=0,
                    block_reason="connected_balance_pending",
                    then=Value("connected_balance_pending"),
                ),
                When(connected__gt=0, then=Value("connected_funds")),
                When(exposed=True, then=Value("transfer_committed_or_unknown")),
                default=F("bucket"),
                output_field=CharField(),
            )
        )
        if scope.operation:
            rows = rows.filter(operation_stage=scope.operation)
        if scope.provider:
            rows = rows.filter(**{scope.provider + "_source": True})
        if scope.rail:
            rows = rows.filter(rail=scope.rail)
        if scope.currency:
            rows = rows.filter(payout_currency=scope.currency)
        if scope.state:
            rows = rows.filter(status=scope.state)
        if scope.held:
            condition = Q(has_hold=True) | Q(is_disputed=True)
            rows = (
                rows.filter(is_disputed=True)
                if scope.held == "disputed"
                else rows.filter(condition if scope.held == "true" else ~condition)
            )
        if scope.search:
            if scope.search.startswith("ST-"):
                rows = rows.filter(deal_id=int(scope.search[3:]))
            elif scope.search.startswith("TR-"):
                rows = rows.filter(traveler_id=int(scope.search[3:]))
            else:
                order_deals = (
                    PaymentOrder.objects.filter(public_reference=scope.search)
                    .annotate(linked_deal=Coalesce("deal_id", "credited_into__deal_id"))
                    .values("linked_deal")
                )
                rows = rows.filter(
                    Q(public_reference=scope.search) | Q(deal_id__in=order_deals)
                )
        return rows.order_by()

    def captures(self, *, applied=True):
        rows = PaymentAttempt.objects.filter(
            provider_mode=self.scope.mode, status="succeeded"
        )
        if applied:
            rows = rows.filter(is_unapplied=False)
        if self.scope.provider:
            rows = rows.filter(provider=self.scope.provider)
        if self.has_cohort:
            rows = rows.annotate(linked_deal=source_deal())
            cohort = Q(linked_deal__in=self.payouts.values("deal_id"))
            # Unbound deposit/Boost can still be looked up by their own UUID.
            if (
                self.scope.search
                and not any(
                    (
                        self.scope.rail,
                        self.scope.state,
                        self.scope.held,
                        self.scope.currency,
                        self.scope.operation,
                    )
                )
                and not self.scope.search.startswith(("ST-", "TR-"))
            ):
                cohort |= Q(order__public_reference=self.scope.search)
            rows = rows.filter(cohort)
        return rows.order_by()

    def refunds(self):
        rows = PaymentRefund.objects.filter(
            provider_mode=self.scope.mode, attempt__provider_mode=self.scope.mode
        )
        if self.scope.provider:
            rows = rows.filter(
                provider=self.scope.provider, attempt__provider=self.scope.provider
            )
        if self.has_cohort:
            rows = rows.filter(attempt_id__in=self.captures(applied=False).values("pk"))
        return rows.order_by()

    def ledger(self):
        rows = mode_ledger(self.scope.mode)
        if self.has_cohort or self.scope.provider:
            rows = rows.filter(deal_id__in=self.payouts.values("deal_id"))
        return rows.order_by()

    def revenue(self):
        # Final settlement can be authoritative even when no reallocation was
        # necessary. The immutable lifecycle event covers that zero-delta case.
        events = (
            DealEvent.objects.filter(
                deal_id=OuterRef("deal_id"),
                kind__in=(
                    "dispute_resolved",
                    "cancelled_after_funding",
                    "compensation_applied",
                ),
            )
            .order_by("created_at", "pk")
            .values("created_at")[:1]
        )
        settlements = (
            LedgerEntry.objects.filter(
                deal_id=OuterRef("deal_id"),
                transaction__provider_mode=self.scope.mode,
                transaction__key__startswith="settlement:",
            )
            .order_by("transaction__created_at")
            .values("transaction__created_at")[:1]
        )
        return (
            self.ledger()
            .filter(account="platform_commission")
            .annotate(
                recognition_at=Least(
                    F("deal__completed_at"), Subquery(events), Subquery(settlements)
                ),
            )
            .annotate(
                effective_at=Greatest("recognition_at", "transaction__created_at")
            )
        )

    def metrics(self):
        scope = self.scope
        funding = mode_ledger(scope.mode).filter(
            transaction__kind="customer_payment",
            account="provider_clearing",
            amount_eur_cents__gt=0,
            attempt_id__in=scope.period(self.captures(), "succeeded_at").values("pk"),
        )
        refunds = self.refunds()
        finalized = scope.period(refunds.filter(status="succeeded"), "succeeded_at")
        revenue = self.revenue()
        payable = self.payouts.exclude(payable=0)
        ledger = self.ledger()
        bank_paid = (
            StripeDisbursementAllocation.objects.filter(
                payout_id=OuterRef("payout_id"),
                disbursement__provider_mode=scope.mode,
            )
            .annotate(
                posting_key=Concat(
                    Value("payout_bank_paid:"),
                    Cast("disbursement__public_reference", CharField()),
                )
            )
            .filter(posting_key=OuterRef("transaction__key"))
            .values("disbursement__paid_at")[:1]
        )
        paid_ledger = ledger.filter(
            account="traveler_payable",
            transaction__kind="payout",
            amount_eur_cents__gt=0,
        ).annotate(
            settlement_at=Coalesce(Subquery(bank_paid), F("payout__paid_at")),
        )
        allocations = PayoutFundingAllocation.objects.filter(
            provider_mode=scope.mode,
            source_attempt__provider_mode=scope.mode,
            payout__provider_mode=scope.mode,
            release__isnull=True,
            payout_id__in=self.payouts.values("pk"),
        )
        if scope.provider:
            allocations = allocations.filter(provider=scope.provider)
        disputes = ProviderDispute.objects.filter(
            provider_mode=scope.mode, status__in=ACTIVE_PROVIDER_DISPUTES
        )
        if scope.provider:
            disputes = disputes.filter(provider=scope.provider)
        if self.has_cohort:
            disputes = disputes.filter(
                source_attempt_id__in=self.captures(applied=False).values("pk")
            )
        metrics = {
            "payout_operations": MetricQuery(
                self.payouts.exclude(status="cancelled"),
                kind="payout",
                dzd="payout_amount_minor" if scope.rail == "manual_dzd" else "",
            ),
            "gross_funded": MetricQuery(funding),
            "deposits_collected": MetricQuery(
                funding.filter(order__purpose="posting_deposit")
            ),
            "boost_funded": MetricQuery(funding.filter(order__purpose="boost")),
            "recognized_revenue": MetricQuery(
                scope.period(
                    revenue.filter(recognition_at__isnull=False), "effective_at"
                ),
                sign=-1,
            ),
            "pending_earnings": MetricQuery(
                revenue.filter(recognition_at__isnull=True), sign=-1
            ),
            "traveler_outstanding": MetricQuery(payable, "payable", kind="payout"),
            "payouts_settled": MetricQuery(scope.period(paid_ledger, "settlement_at")),
            "payout_returns": MetricQuery(
                scope.period(
                    ledger.filter(
                        account="traveler_payable",
                        transaction__key__startswith="payout_bank_returned:",
                        amount_eur_cents__lt=0,
                    ),
                    "transaction__created_at",
                ),
                sign=-1,
            ),
            "connected_funds": MetricQuery(ledger.filter(account="connect_funds")),
            "bank_in_transit": MetricQuery(ledger.filter(account="payout_in_transit")),
            "externally_committed": MetricQuery(
                payable.filter(exposed=True), "payable", kind="payout"
            ),
            "source_reserved": MetricQuery(allocations, kind="allocation"),
            "provider_disputes": MetricQuery(
                disputes, "canonical_amount_eur_cents", kind="provider_dispute"
            ),
            "refunds_requested": MetricQuery(
                refunds.filter(status="pending"), kind="refund"
            ),
            "refunds_processing": MetricQuery(
                refunds.filter(status="processing"), kind="refund"
            ),
            "refunds_failed": MetricQuery(
                refunds.filter(status="failed"), kind="refund"
            ),
            "refunds_outstanding": MetricQuery(
                refunds.filter(status__in=("pending", "processing")), kind="refund"
            ),
            "refunds_finalized": MetricQuery(finalized, kind="refund"),
            "refunds_applied": MetricQuery(
                finalized.filter(attempt__is_unapplied=False), kind="refund"
            ),
            "deposits_refunded": MetricQuery(
                finalized.filter(
                    attempt__is_unapplied=False, order__purpose="posting_deposit"
                ),
                kind="refund",
            ),
            "user_disputed_payouts": MetricQuery(
                payable.filter(has_user_dispute=True), "payable", kind="payout"
            ),
            "held_payouts": MetricQuery(
                payable.filter(has_hold=True), "payable", kind="payout"
            ),
            "provider_disputed_payouts": MetricQuery(
                payable.filter(has_provider_dispute=True), "payable", kind="payout"
            ),
        }
        deposits = mode_ledger(scope.mode).filter(
            account="sender_deposit",
            order_id__in=self.captures()
            .filter(order__purpose="posting_deposit")
            .values("order_id"),
        )
        metrics["deposits_credited"] = MetricQuery(
            scope.period(
                deposits.filter(
                    transaction__kind="deposit_credit", amount_eur_cents__gt=0
                ),
                "transaction__created_at",
            )
        )
        metrics["deposits_held"] = MetricQuery(deposits, sign=-1)
        from .definitions import LIABILITY_BUCKETS

        for bucket in LIABILITY_BUCKETS:
            metrics["liability_" + bucket] = MetricQuery(
                payable.filter(bucket=bucket), "payable", kind="payout"
            )
        return metrics

    def paid_records(self):
        """Independent settlement evidence; preserve paid allocation after return."""
        scope = self.scope
        bank = StripeDisbursementAllocation.objects.filter(
            payout_id__in=self.payouts.values("pk"),
            disbursement__provider_mode=scope.mode,
            disbursement__paid_at__isnull=False,
        )
        manual = self.payouts.exclude(method="stripe_transfer").filter(
            paid_at__isnull=False
        )
        return (
            scope.period(bank, "disbursement__paid_at"),
            scope.period(manual, "paid_at"),
        )
