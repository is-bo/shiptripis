"""Transactional domain services for ParcelRequest lifecycle changes."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.core import channels, redis_bus
from apps.core.financial_locks import lock_request_graph
from apps.finance.models import PaymentOrder, PaymentRefund
from apps.finance.services import cancel_order, refund_order_in_full
from apps.matching.models import Match, MatchEvent, Offer

from .models import ParcelRequest


CANCELLABLE_STATUSES = frozenset(
    {ParcelRequest.Status.OPEN, ParcelRequest.Status.AWAITING_DEPOSIT}
)


class ParcelCancellationError(RuntimeError):
    code = "parcel_cancellation_failed"


class ParcelCancellationForbidden(ParcelCancellationError):
    code = "parcel_cancellation_forbidden"


class ParcelHasDeal(ParcelCancellationError):
    code = "deal_cancellation_not_available"


class ParcelNotCancellable(ParcelCancellationError):
    code = "parcel_not_cancellable"

    def __init__(self, parcel_status: str):
        super().__init__(f"Cannot cancel a parcel in status '{parcel_status}'.")
        self.parcel_status = parcel_status


@dataclass(frozen=True, slots=True)
class ParcelCancellationResult:
    parcel_id: int


@transaction.atomic
def cancel_delivery_request(
    *, request_id: int, actor_id: int
) -> ParcelCancellationResult:
    """Cancel a request and make its current payment truth part of that commit.

    The request/negotiation graph is locked before its PaymentOrder. Payment
    reconciliation uses the same order, so payment success either commits
    first and creates a refund obligation here, or cancellation commits first
    and the later success is recorded as unapplied and creates the obligation.
    """

    graph = lock_request_graph(request_id, include_negotiation=True)
    delivery = graph.request
    parcel = delivery.parcelrequest_ptr
    if parcel.sender_id != actor_id:
        raise ParcelCancellationForbidden("Only the sender can cancel.")
    if delivery.deals.exists():
        raise ParcelHasDeal(
            "A request with a Deal must use the Deal cancellation workflow."
        )
    if parcel.status not in CANCELLABLE_STATUSES:
        raise ParcelNotCancellable(parcel.status)

    now = timezone.now()
    pending_matches = tuple(
        row for row in graph.matches if row.status == Match.Status.PENDING
    )
    pending_ids = [row.pk for row in pending_matches]
    if pending_ids:
        Offer.objects.filter(
            match_id__in=pending_ids,
            status=Offer.Status.PENDING,
        ).update(status=Offer.Status.WITHDRAWN, responded_at=now)
        Match.objects.filter(pk__in=pending_ids).update(status=Match.Status.CANCELLED)
        MatchEvent.objects.bulk_create(
            [
                MatchEvent(
                    match=row,
                    actor_id=actor_id,
                    kind=MatchEvent.Kind.MATCH_CANCELLED,
                    payload={"reason": "parcel_cancelled"},
                )
                for row in pending_matches
            ]
        )

    parcel.status = ParcelRequest.Status.CANCELLED
    parcel.save(update_fields=["status", "updated_at"])

    locked_orders = tuple(
        PaymentOrder.objects.select_for_update(no_key=True)
        .filter(delivery_request_id=parcel.pk)
        .exclude(status=PaymentOrder.Status.CANCELLED)
        .order_by("pk")
    )
    locked_orders_by_id = {order.pk: order for order in locked_orders}

    from apps.boosts.services import unwind_boosts  # noqa: WPS433

    unwind_boosts(
        locked_purchases=graph.boost_purchases,
        reason="sender_cancelled_request",
        requested_by_id=actor_id,
        locked_orders=locked_orders_by_id,
        delivery_request=delivery,
    )

    deposit_orders = tuple(
        order
        for order in locked_orders
        if order.purpose == PaymentOrder.Purpose.POSTING_DEPOSIT
    )
    for order in deposit_orders:
        if int(order.paid_eur_cents) > 0:
            refund_order_in_full(
                order_id=order.pk,
                reason=PaymentRefund.Reason.SENDER_CANCELLED,
                requested_by_id=actor_id,
            )
        cancel_order(order_id=order.pk, reason="sender_cancelled_request")

    redis_bus.publish_after_commit(
        channels.PARCEL_CANCELLED,
        {"parcel_id": parcel.pk, "sender_id": parcel.sender_id},
        targets=[parcel.sender_id],
    )
    return ParcelCancellationResult(parcel_id=parcel.pk)
