"""Query-time lifecycle: elapsed inventory never depends on a worker tick.

A later leg remains sellable. Pickup is evidence of travel beginning; a clock
alone is not. Funded dependencies retain their lifecycle and frozen snapshots.
"""
from django.db.models import Case, CharField, Exists, OuterRef, Q, Value, When
from django.utils import timezone

from .models import Journey, JourneyLeg


def with_lifecycle(queryset, *, at=None):
    from apps.deals.activity import activity_q
    from apps.deals.models import Deal

    at = at or timezone.now()
    legs = JourneyLeg.objects.filter(journey_id=OuterRef("pk"))
    deals = Deal.objects.filter(journey_id=OuterRef("pk"), funded_at__isnull=False)
    return queryset.alias(
        remaining_inventory=Exists(legs.filter(
            Q(depart_at__gt=at)
            # Legacy DRIVE matching permits pickup along a leg. Canonical V2
            # matching uses departure nodes; do not reinterpret either model.
            | Q(journey__schema_version=1, mode="DRIVE", arrive_at__gt=at)
        )),
        travel_begun=Exists(deals.filter(pickup_confirmed_at__isnull=False)),
        funded_dependency=Exists(deals.filter(activity_q("active"))),
        unfinished_leg=Exists(legs.filter(Q(arrive_at__isnull=True) | Q(arrive_at__gt=at))),
        any_leg=Exists(legs),
    ).annotate(lifecycle_status=Case(
        When(~Q(status__in=[Journey.Status.ACTIVE, Journey.Status.IN_PROGRESS]), then="status"),
        When(Q(status=Journey.Status.IN_PROGRESS) | Q(travel_begun=True), then=Case(
            When(any_leg=True, unfinished_leg=False, then=Value(Journey.Status.COMPLETED)),
            default=Value(Journey.Status.IN_PROGRESS),
        )),
        When(remaining_inventory=False, funded_dependency=False, then=Value(Journey.Status.EXPIRED)),
        default="status", output_field=CharField(),
    ))


def discoverable(queryset, *, at=None):
    return with_lifecycle(queryset, at=at).filter(
        lifecycle_status__in=[Journey.Status.ACTIVE, Journey.Status.IN_PROGRESS],
        remaining_inventory=True,
    )
