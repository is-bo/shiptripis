"""Consistent read-only PostgreSQL snapshots for the Finance control plane."""

from contextlib import contextmanager
from dataclasses import asdict

from django.db import connection, transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from .definitions import VERSION, definitions
from .attention import snapshot_attention
from .queries import MetricQuery, Queries
from .reconciliation import reconcile


@contextmanager
def consistent_read():
    if connection.vendor != "postgresql" or connection.in_atomic_block:
        raise RuntimeError(
            "Finance reporting requires a standalone PostgreSQL snapshot."
        )
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '10s'")
        yield


def payout_groups(queries):
    """One GROUP BY query, not a queryset evaluation per payout."""
    rows = (
        queries.payouts.exclude(payable=0)
        .values("rail", "bucket", "funding_mix")
        .annotate(
            count=Count("pk"),
            amount_eur_cents=Sum("payable"),
            amount_dzd=Sum("payout_amount_minor", filter=Q(rail="manual_dzd")),
            dzd_known=Count("payout_amount_minor", filter=Q(rail="manual_dzd")),
        )
    )
    result = []
    for row in rows:
        row["amount_eur_cents"] = int(row["amount_eur_cents"] or 0)
        known = row.pop("dzd_known")
        if row["rail"] == "manual_dzd":
            row["dzd_missing_count"] = row["count"] - known
            if known != row["count"]:
                row["amount_dzd"] = None
            else:
                row["amount_dzd"] = int(row["amount_dzd"] or 0)
        else:
            row.pop("amount_dzd")
        result.append(row)
    return result


def operational_groups(queries):
    """Orthogonal rail states, including settled rows and local commitment."""
    groups = (
        queries.payouts.exclude(status="cancelled")
        .values("rail", "operation_stage")
        .annotate(
            count=Count("pk"),
            amount_eur_cents=Sum("amount_eur_cents"),
            amount_dzd=Sum("payout_amount_minor"),
            known=Count("payout_amount_minor"),
        )
    )
    result = []
    for row in groups:
        row["amount_eur_cents"] = int(row["amount_eur_cents"] or 0)
        known = row.pop("known")
        if row["rail"] == "manual_dzd":
            row["dzd_missing_count"] = row["count"] - known
            if known != row["count"]:
                row["amount_dzd"] = None
            else:
                row["amount_dzd"] = int(row["amount_dzd"] or 0)
        else:
            row.pop("amount_dzd")
        result.append(row)
    return result


def build_snapshot(scope):
    with consistent_read():
        as_of = timezone.now()
        queries = Queries(scope, as_of=as_of)
        registry = queries.metrics()
        metrics = {key: query.aggregate() for key, query in registry.items()}
        metrics["net_funded"] = {
            "count": None,
            "amount_eur_cents": metrics["gross_funded"]["amount_eur_cents"]
            - metrics["refunds_applied"]["amount_eur_cents"],
            "status": "available",
            "components": ["gross_funded", "refunds_applied"],
        }
        providers = {}
        # Funding/refunds use actual source provider, independent of outgoing
        # rail. A mixed-source payout cohort is explicitly non-additive.
        for provider in ("stripe", "chargily"):
            captures = scope.period(
                queries.captures().filter(provider=provider), "succeeded_at"
            )
            rows = registry["gross_funded"].rows.filter(
                attempt_id__in=captures.values("pk")
            )
            providers[provider] = {
                "gross_funded": MetricQuery(rows).aggregate(),
                "refunds_outstanding": MetricQuery(
                    queries.refunds().filter(
                        provider=provider, status__in=("pending", "processing")
                    )
                ).aggregate(),
                "refunds_finalized": MetricQuery(
                    scope.period(
                        queries.refunds().filter(provider=provider, status="succeeded"),
                        "succeeded_at",
                    )
                ).aggregate(),
                "source_reserved": MetricQuery(
                    registry["source_reserved"].rows.filter(provider=provider)
                ).aggregate(),
                "balance": {
                    "status": "unavailable",
                    "amount": None,
                    "retrieved_at": None,
                },
            }
        return {
            "definition_version": VERSION,
            "as_of": as_of.isoformat(),
            "scope": {
                key: value.isoformat() if hasattr(value, "isoformat") else value
                for key, value in asdict(scope).items()
            },
            "reporting_timezone": "Europe/Paris",
            "balance_basis": "current",
            "provider_filter_semantics": "Exact source for cash/refunds/reservations; any-source Deal cohort for revenue/liability. Mixed cohorts overlap and are not additive.",
            "metrics": metrics,
            "definitions": definitions(),
            "payouts": payout_groups(queries),
            "rail_operations": operational_groups(queries),
            "payout_attention": snapshot_attention(queries.payouts),
            "providers": providers,
            "integrity": reconcile(queries, metrics),
            "provider_costs": {"status": "unavailable", "amount_eur_cents": None},
            "revenue_categories": {
                "status": "unavailable",
                "reason": "Existing ledger does not preserve category attribution of final settlement corrections.",
            },
            "limitations": [
                "No physical provider cash or available-to-spend assertion.",
                "Recognition is a read-only H0 earning-evidence projection; no new earned-revenue accounts or statutory/tax ledger.",
                "Failed refund executions are separate; current reservation semantics do not establish remaining entitlement.",
                "Legacy/unknown mode requires its own explicit query; no name-based QA exclusions.",
            ],
        }
