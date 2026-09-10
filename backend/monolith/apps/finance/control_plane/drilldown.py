"""Bounded safe projections of the exact rows used by each metric."""

from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal

from .definitions import VERSION
from .queries import Queries
from .snapshot import consistent_read


def drilldown(scope, *, metric, page=1, page_size=50):
    try:
        page, page_size = int(page), int(page_size)
    except (ValueError, TypeError):
        raise ValidationError("Invalid page bounds.") from None
    if not 1 <= page <= 100 or not 1 <= page_size <= 100:
        raise ValidationError(
            "Page must be 1..100 and page_size 1..100; narrow the filters for deeper history."
        )
    with consistent_read():
        as_of = timezone.now()
        query = Queries(scope, as_of=as_of).metrics().get(metric)
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
        result = []
        for row in selected[:page_size]:
            identifier = row.pop("pk")
            amount = row.pop(query.amount)
            item = {
                "amount_eur_cents": int(amount) * query.sign
                if amount is not None
                else None
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
                        key.replace("__public_reference", "_reference").replace(
                            "__", "_"
                        )
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
            result.append(item)
        return {
            "definition_version": VERSION,
            "mode": scope.mode,
            "as_of": as_of.isoformat(),
            "metric": metric,
            "page": page,
            "page_size": page_size,
            "has_next": len(selected) > page_size,
            "totals": query.aggregate(),
            "rows": result,
        }
