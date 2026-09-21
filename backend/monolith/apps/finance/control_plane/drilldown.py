"""Bounded safe projections of the exact rows used by each metric."""

from dataclasses import replace
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import connection
from django.utils import timezone

from .definitions import VERSION
from .queries import Queries
from .snapshot import consistent_read


def drilldown(
    scope,
    *,
    metric,
    page=1,
    page_size=50,
    queries=None,
    as_of=None,
    include_totals=True,
    compact=False,
):
    try:
        page, page_size = int(page), int(page_size)
    except (ValueError, TypeError):
        raise ValidationError("Invalid page bounds.") from None
    if not 1 <= page <= 100 or not 1 <= page_size <= 100:
        raise ValidationError(
            "Page must be 1..100 and page_size 1..100; narrow the filters for deeper history."
        )
    if queries is not None:
        if not connection.in_atomic_block or as_of is None:
            raise RuntimeError(
                "A shared Finance query projection requires its active snapshot."
            )
        return _drilldown(
            scope,
            metric=metric,
            page=page,
            page_size=page_size,
            queries=queries,
            as_of=as_of,
            include_totals=include_totals,
            compact=compact,
        )
    with consistent_read():
        current_as_of = timezone.now()
        return _drilldown(
            scope,
            metric=metric,
            page=page,
            page_size=page_size,
            queries=Queries(scope, as_of=current_as_of),
            as_of=current_as_of,
            include_totals=include_totals,
            compact=compact,
        )


def _drilldown(
    scope,
    *,
    metric,
    page,
    page_size,
    queries,
    as_of,
    include_totals,
    compact,
):
    # Reuse the caller's transaction and timestamp, not a queryset built for a
    # different snapshot. Queue cards only add a stage and, for the dedicated
    # DZD page, a rail to the page scope. Apply those two annotations to the
    # already-built projection; any broader difference gets its own Queries.
    refinements = {
        field
        for field in ("operation", "rail")
        if getattr(scope, field) != getattr(queries.scope, field)
    }
    other_scope_changed = any(
        getattr(scope, field) != getattr(queries.scope, field)
        for field in (
            "mode",
            "start",
            "end",
            "provider",
            "state",
            "held",
            "search",
            "currency",
        )
    )
    if other_scope_changed or any(
        getattr(queries.scope, field) for field in refinements
    ):
        queries = Queries(scope, as_of=as_of)
        refinements = set()
    query = queries.metrics().get(
        "payout_operations" if metric == "payout_attention" else metric
    )
    if query is not None and refinements:
        rows = query.rows
        if "operation" in refinements:
            rows = rows.filter(operation_stage=scope.operation)
        if "rail" in refinements:
            rows = rows.filter(rail=scope.rail)
        query = replace(query, rows=rows)
    if metric == "payout_attention":
        from .attention import attention_projection

        query = replace(
            query, rows=query.rows.filter(pk__in=attention_projection(queries.payouts))
        )
    if query is None:
        raise ValidationError(
            "Unknown metric; net funded drills through its two components."
        )
    fields = {"pk", query.amount}
    if query.kind == "payout":
        fields |= {
            "public_reference",
            "deal_id",
            "traveler_id",
            "status",
            "bucket",
            "rail",
            "operation_stage",
            "funding_mix",
            "payout_amount_minor",
            "payout_currency",
            "payout_amount_exponent",
            "fx_rate_micros",
            "fx_snapshot_at",
            "has_hold",
            "has_user_dispute",
            "has_provider_dispute",
            "connected",
            "transit",
            "exposed",
        }
        if compact:
            fields -= {
                "bucket",
                "funding_mix",
                "fx_rate_micros",
                "fx_snapshot_at",
                "connected",
                "transit",
                "exposed",
            }
    elif query.kind == "refund":
        fields |= {
            "order__public_reference",
            "order__deal_id",
            "status",
            "provider",
            "succeeded_at",
        }
    elif query.kind == "allocation":
        fields |= {
            "payout__public_reference",
            "source_attempt__order__public_reference",
            "provider",
            "purpose",
        }
    elif query.kind == "provider_dispute":
        fields |= {"source_attempt__order__public_reference", "provider", "status"}
    else:
        fields |= {
            "order__public_reference",
            "payout__public_reference",
            "deal_id",
            "transaction__kind",
            "transaction__created_at",
            "account",
        }
        if metric == "recognized_revenue":
            fields |= {"recognition_at", "effective_at"}
        if metric == "payouts_settled":
            fields.add("settlement_at")
        if metric in {"gross_funded", "deposits_collected", "boost_funded"}:
            fields.add("attempt__succeeded_at")
    offset = (page - 1) * page_size
    selected = list(
        query.rows.order_by("pk").values(*sorted(fields))[
            offset : offset + page_size + 1
        ]
    )
    attention = {}
    if query.kind == "payout":
        from apps.finance.models import Payout
        from apps.finance.payout_mobile import (
            page_context,
            payout_attention,
            payout_read_rows,
        )

        payouts = list(
            payout_read_rows(
                Payout.objects.filter(
                    pk__in=[row["pk"] for row in selected[:page_size]]
                )
            )
        )
        context = page_context(payouts, include_actions=False)
        attention = {p.pk: payout_attention(p, context=context) for p in payouts}
    result = []
    for row in selected[:page_size]:
        identifier = row.pop("pk")
        amount = row.pop(query.amount)
        item = {
            "amount_eur_cents": int(amount) * query.sign if amount is not None else None
        }
        for key, value in row.items():
            if key in {"deal_id", "order__deal_id"}:
                item["deal_reference"] = f"ST-{value}" if value else None
            elif key == "traveler_id":
                item["traveler_reference"] = f"TR-{value}"
            elif key == "public_reference":
                item["payout_reference"] = str(value)
            elif key.endswith("public_reference"):
                item[
                    key.replace("__public_reference", "_reference").replace("__", "_")
                ] = str(value) if value else None
            elif hasattr(value, "isoformat"):
                item[key.replace("__", "_")] = value.isoformat()
            elif isinstance(value, Decimal):
                item[key.replace("__", "_")] = int(value)
            else:
                item[key.replace("__", "_")] = value
        # These legacy tables have no UUID. Staff-safe display refs avoid
        # serializing provider IDs, transaction keys or arbitrary notes.
        item["row_reference"] = f"{query.kind.upper()}-{identifier}"
        if query.kind == "payout":
            item.update(attention[identifier])
        result.append(item)
    return {
        "definition_version": VERSION,
        "mode": scope.mode,
        "as_of": as_of.isoformat(),
        "metric": metric,
        "page": page,
        "page_size": page_size,
        "has_next": len(selected) > page_size,
        "totals": query.aggregate() if include_totals else None,
        "rows": result,
    }
