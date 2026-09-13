"""Unique actionable payouts using the same projection as the H5 row contract."""

from collections import Counter

from django.core.exceptions import ValidationError

from apps.finance.models import Payout
from apps.finance.payout_mobile import page_context, payout_attention, payout_read_rows

MAX_PAYOUTS = 5000
BATCH_SIZE = 200


def attention_projection(queryset):
    # Bound total work and memory. Never turn the first page into a total.
    ids = list(
        queryset.exclude(status="cancelled")
        .order_by("pk")
        .values_list("pk", flat=True)
        .distinct()[: MAX_PAYOUTS + 1]
    )
    if len(ids) > MAX_PAYOUTS:
        raise ValidationError(
            "Attention scope exceeds 5,000 payouts; narrow the filters."
        )
    result = {}
    for offset in range(0, len(ids), BATCH_SIZE):
        rows = list(
            payout_read_rows(
                Payout.objects.filter(pk__in=ids[offset : offset + BATCH_SIZE])
            )
        )
        context = page_context(rows, include_actions=False)
        for payout in rows:
            facts = payout_attention(payout, context=context)
            if facts["needs_attention"]:
                result[payout.pk] = facts
    return result


def attention_summary(projection):
    owners = Counter(row["attention_owner"] for row in projection.values())
    return {
        "status": "available",
        "count": len(projection),
        "groups": [
            {"attention_owner": owner, "count": owners[owner]}
            for owner in ("traveler", "finance", "provider", None)
            if owners[owner]
        ],
        "semantics": "Unique payouts; one primary blocker and nullable owner per payout. Refunds are separate issues.",
    }


def snapshot_attention(queryset):
    try:
        return attention_summary(attention_projection(queryset))
    except ValidationError:
        return {
            "status": "unavailable",
            "count": None,
            "groups": [],
            "reason": "Narrow the scope to at most 5,000 payouts.",
        }
