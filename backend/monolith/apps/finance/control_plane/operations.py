"""Narrow authoritative reads for the Finance operations pages.

The comprehensive H5 snapshot is an accounting/reconciliation product.  It
intentionally evaluates every metric, provider split, integrity comparison,
and stated limitation under one repeatable-read snapshot.  Operational pages
must not pay that cost merely to show three totals or payout queue counts.

Callers own one short :func:`consistent_read` block and may use the returned
``Queries`` object for the rows shown on that same page.  No value is cached;
all money and queue state is read from PostgreSQL for the request.
"""

from django.utils import timezone

from .attention import snapshot_attention
from .snapshot import operational_groups, snapshot_metadata
from .queries import Queries


def build_operational_snapshot(
    scope,
    *,
    metric_names=(),
    include_rail_operations=False,
    include_payout_attention=False,
):
    """Return exactly the financial projections one operations page renders.

    The caller must invoke this inside ``consistent_read``.  Keeping that
    transaction at the page boundary lets queue counts and their first rows
    share one database snapshot without nesting one transaction per stage.
    """

    as_of = timezone.now()
    queries = Queries(scope, as_of=as_of)
    registry = queries.metrics()
    unknown = set(metric_names) - set(registry)
    if unknown:
        raise ValueError(f"Unknown Finance operational metrics: {sorted(unknown)}")
    snapshot = {
        **snapshot_metadata(scope, as_of=as_of),
        "metrics": {name: registry[name].aggregate() for name in metric_names},
        "rail_operations": (
            operational_groups(queries) if include_rail_operations else []
        ),
        "payout_attention": (
            snapshot_attention(queries.payouts) if include_payout_attention else None
        ),
    }
    return snapshot, queries
