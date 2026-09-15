"""Request status is a projection of the latest Deal, never a second machine.

Services already hold the request graph lock before changing the Deal. They
persist this projection in that transaction; reads also project old stale rows
without rewriting history. Unfunded reservation release keeps its existing
reopen semantics. No payout, rating, or wall-clock inference belongs here.
"""

from django.db.models import Case, CharField, F, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.deals.activity import CANCELLED_STATUSES, COMPLETED_STATUSES
from apps.deals.models import Deal

from .models import ParcelRequest


def with_lifecycle(queryset):
    """Annotate before filtering/pagination, with indexed latest-Deal subqueries."""
    status = ParcelRequest.Status
    latest = (
        Deal.objects.filter(delivery_request_id=OuterRef("pk"))
        .order_by("-created_at", "-pk")
        .annotate(
            request_status=Case(
                # These reservations were released back to the open pool.
                When(
                    status__in=(Deal.Status.CANCELLED, Deal.Status.EXPIRED),
                    funded_at__isnull=True,
                    pickup_confirmed_at__isnull=True,
                    delivery_confirmed_at__isnull=True,
                    completed_at__isnull=True,
                    then=Value(None),
                ),
                When(status__in=CANCELLED_STATUSES, then=Value(status.CANCELLED)),
                When(status=Deal.Status.COMPLETED, then=Value(status.COMPLETED)),
                When(
                    Q(status__in=COMPLETED_STATUSES)
                    | Q(delivery_confirmed_at__isnull=False),
                    then=Value(status.DELIVERED),
                ),
                When(
                    Q(
                        status__in=(
                            Deal.Status.PICKED_UP,
                            Deal.Status.IN_TRANSIT,
                            Deal.Status.DELIVERY_READY,
                        )
                    )
                    | Q(pickup_confirmed_at__isnull=False),
                    then=Value(status.IN_TRANSIT),
                ),
                default=Value(status.MATCHED),
                output_field=CharField(),
            )
        )
        .values("request_status")[:1]
    )
    queryset = queryset.alias(_deal_request_status=Subquery(latest))
    return queryset.annotate(
        lifecycle_status=Case(
            When(~Q(kind=ParcelRequest.Kind.DELIVERY), then=F("status")),
            When(status__in=(status.CANCELLED, status.EXPIRED), then=F("status")),
            When(_deal_request_status=status.CANCELLED, then=Value(status.CANCELLED)),
            # Preserve already recorded progress on incomplete historical data.
            When(status=status.COMPLETED, then=F("status")),
            When(
                status=status.DELIVERED,
                _deal_request_status__in=(status.MATCHED, status.IN_TRANSIT),
                then=F("status"),
            ),
            When(
                status=status.IN_TRANSIT,
                _deal_request_status=status.MATCHED,
                then=F("status"),
            ),
            default=Coalesce(F("_deal_request_status"), F("status")),
            output_field=CharField(),
        )
    )


def sync_request_status(deal):
    """Persist current authority under the caller's existing request/Deal locks.

    Read the database authority, not a potentially replayed in-memory event.
    Equal values do not write updated_at or create any additional side effects.
    """
    rows = with_lifecycle(ParcelRequest.objects.filter(pk=deal.delivery_request_id))
    return rows.exclude(status=F("lifecycle_status")).update(
        status=F("lifecycle_status"), updated_at=timezone.now()
    )
