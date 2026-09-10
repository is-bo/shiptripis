"""Independent state/record comparisons; gaps are reported, never clamped."""

from django.db.models import Case, Count, F, OuterRef, Sum, Value, When, BigIntegerField

from apps.finance.models import LedgerEntry
from .queries import MetricQuery, mode_ledger, sum_subquery


def reconcile(queries, metrics):
    scope = queries.scope
    ledger = queries.ledger()
    comparisons = {}

    def compare(name, reported, authority, *, row_mismatches=0):
        comparisons[name] = {
            "reported_eur_cents": reported,
            "authority_eur_cents": authority,
            "difference_eur_cents": reported - authority,
            "row_mismatches": row_mismatches,
        }

    state = queries.payouts.annotate(
        expected=Case(
            When(status__in=("paid", "cancelled"), then=Value(0)),
            default=F("amount_eur_cents"),
            output_field=BigIntegerField(),
        )
    )
    expected = MetricQuery(state, "expected").aggregate()["amount_eur_cents"]
    payable = MetricQuery(
        ledger.filter(account="traveler_payable"), sign=-1
    ).aggregate()["amount_eur_cents"]
    compare(
        "traveler_state_to_ledger",
        expected,
        payable,
        row_mismatches=state.exclude(expected=F("payable")).count(),
    )
    compare(
        "traveler_dashboard_to_ledger",
        metrics["traveler_outstanding"]["amount_eur_cents"],
        payable,
    )
    captures = scope.period(queries.captures(), "succeeded_at")
    compare(
        "applied_funding",
        metrics["gross_funded"]["amount_eur_cents"],
        MetricQuery(captures).aggregate()["amount_eur_cents"],
    )
    refunds = scope.period(queries.refunds().filter(status="succeeded"), "succeeded_at")
    refund_ledger = mode_ledger(scope.mode).filter(
        account="provider_clearing",
        transaction__kind="refund",
        refund_id__in=refunds.values("pk"),
    )
    compare(
        "finalized_refunds",
        metrics["refunds_finalized"]["amount_eur_cents"],
        MetricQuery(refund_ledger, sign=-1).aggregate()["amount_eur_cents"],
    )
    refund_rows = refunds.annotate(
        posted=sum_subquery(
            mode_ledger(scope.mode).filter(
                refund_id=OuterRef("pk"),
                account="provider_clearing",
                transaction__kind="refund",
            ),
            "refund_id",
        )
    )
    comparisons["finalized_refunds"]["row_mismatches"] = refund_rows.exclude(
        posted=-F("amount_eur_cents")
    ).count()
    capture_rows = captures.annotate(
        posted=sum_subquery(
            mode_ledger(scope.mode).filter(
                attempt_id=OuterRef("pk"),
                account="provider_clearing",
                transaction__kind="customer_payment",
            ),
            "attempt_id",
        )
    )
    comparisons["applied_funding"]["row_mismatches"] = capture_rows.exclude(
        posted=F("amount_eur_cents")
    ).count()
    bank, manual = queries.paid_records()
    settled = (
        MetricQuery(bank).aggregate()["amount_eur_cents"]
        + MetricQuery(manual).aggregate()["amount_eur_cents"]
    )
    compare("paid_settlements", metrics["payouts_settled"]["amount_eur_cents"], settled)
    recognized = MetricQuery(
        queries.revenue().filter(recognition_at__isnull=False), sign=-1
    ).aggregate()["amount_eur_cents"]
    allocated = MetricQuery(
        ledger.filter(account="platform_commission"), sign=-1
    ).aggregate()["amount_eur_cents"]
    compare(
        "platform_recognition_partition",
        recognized + metrics["pending_earnings"]["amount_eur_cents"],
        allocated,
    )
    # A transaction must balance in full; a provider/rail subset of its legs
    # need not. Select transaction identities first, then check every leg.
    unbalanced = (
        LedgerEntry.objects.filter(transaction_id__in=ledger.values("transaction_id"))
        .order_by()
        .values("transaction_id")
        .annotate(net=Sum("amount_eur_cents"))
        .exclude(net=0)
        .aggregate(count=Count("transaction_id"))
    )
    warnings = []
    derived_captures = ledger.filter(
        mode_provenance="derived_from_authoritative_payment_attempt"
    ).count()
    attributed = ledger.exclude(transaction__provider_mode=scope.mode).count()
    if attributed > derived_captures:
        warnings.append(
            "legacy_refund_ledger_mode_attributed_from_agreeing_refund_and_capture"
        )
    if metrics["refunds_failed"]["count"]:
        warnings.append("failed_refund_entitlement_requires_review")
    if metrics["provider_disputes"]["status"] == "partial":
        warnings.append("provider_dispute_canonical_amount_incomplete")
    if queries.payouts.filter(funding_mix="unclassified").exists():
        warnings.append("unclassified_funding_provenance")
    if queries.scope.mode == "legacy_unknown":
        warnings.append("legacy_mode_not_test_or_live")
    data_issues = {
        "successful_capture_missing_timestamp": queries.captures()
        .filter(succeeded_at__isnull=True)
        .count(),
        "successful_refund_missing_timestamp": queries.refunds()
        .filter(status="succeeded", succeeded_at__isnull=True)
        .count(),
        "discharge_without_payout_evidence": ledger.filter(
            account="traveler_payable",
            transaction__kind="payout",
            amount_eur_cents__gt=0,
            payout__paid_at__isnull=True,
        ).count(),
    }
    bad = (
        bool(unbalanced["count"])
        or any(data_issues.values())
        or any(
            value["difference_eur_cents"] or value["row_mismatches"]
            for value in comparisons.values()
        )
    )
    return {
        "status": "mismatch" if bad else "warning" if warnings else "ok",
        "comparisons": comparisons,
        "unbalanced_transaction_count": unbalanced["count"],
        "warnings": warnings,
        "source_attributed_legacy_entry_count": attributed,
        "provenance": {
            "derived_from_authoritative_payment_attempt": {
                "status": "verified",
                "entry_count": derived_captures,
            }
        },
        "data_issues": data_issues,
        "revenue_basis": "read_only_evidence_projection_of_existing_platform_share_ledger",
        "provider_cash_reconciliation": "unavailable_no_provider_balance_observation",
    }
