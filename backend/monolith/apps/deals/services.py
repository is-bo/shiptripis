from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.db import transaction
from django.db.models import Min, Q
from django.utils import timezone

from apps.core import channels, redis_bus
from apps.core.event_resources import deal_resources
from apps.core.financial_locks import lock_deal_aggregate
from apps.matching.models import Match
from apps.parcels.models import ParcelRequest

from . import lifecycle
from .models import Deal, DealEvent, DealLegAllocation, DealTermsSnapshot


RELEASE_REASONS = frozenset(
    {"payment_grace_expired", "deal_cancelled", "journey_cancelled"}
)


@dataclass(frozen=True, slots=True)
class ReservationReleaseResult:
    deal_id: int
    released_allocations: int
    changed: bool


class DealCancellationError(RuntimeError):
    code = "deal_cancellation_error"


@transaction.atomic
def release_pending_deal_reservation(
    *,
    deal_id: int,
    reason: str,
    at: datetime | None = None,
    require_expired: bool = False,
) -> ReservationReleaseResult:
    """Release every pending leg allocation using the acceptance lock order."""

    if reason not in RELEASE_REASONS:
        raise ValueError("Unknown reservation release reason.")
    at = at or timezone.now()
    aggregate = lock_deal_aggregate(deal_id)
    request_row = aggregate.request_graph.request
    request_matches = list(aggregate.request_graph.matches)
    deal = aggregate.deal
    allocations = [
        row
        for row in aggregate.allocations
        if row.status == DealLegAllocation.Status.PENDING_PAYMENT
    ]
    if deal.status != Deal.Status.PAYMENT_REQUIRED or not allocations:
        return ReservationReleaseResult(deal.pk, 0, False)
    if require_expired and not any(
        allocation.expires_at is not None and allocation.expires_at <= at
        for allocation in allocations
    ):
        return ReservationReleaseResult(deal.pk, 0, False)

    allocation_ids = [allocation.pk for allocation in allocations]
    released = DealLegAllocation.objects.filter(pk__in=allocation_ids).update(
        status=DealLegAllocation.Status.RELEASED,
        released_at=at,
        release_reason=reason,
    )
    deal.status = (
        Deal.Status.EXPIRED
        if reason == "payment_grace_expired"
        else Deal.Status.CANCELLED
    )
    deal.save(update_fields=["status", "updated_at"])

    match = next(
        (row for row in request_matches if row.pk == deal.match_id),
        None,
    )
    if match is not None and match.status == Match.Status.ACCEPTED:
        match.status = (
            Match.Status.EXPIRED
            if reason == "payment_grace_expired"
            else Match.Status.CANCELLED
        )
        match.save(update_fields=["status", "updated_at"])
    if request_row.status == ParcelRequest.Status.MATCHED:
        request_row.status = ParcelRequest.Status.OPEN
        request_row.save(update_fields=["status", "updated_at"])

    DealEvent.objects.create(
        deal=deal,
        kind=DealEvent.Kind.CAPACITY_RELEASED,
        payload={
            "reason": reason,
            "allocation_ids": allocation_ids,
            "released_at": at.isoformat(),
        },
    )
    DealEvent.objects.create(
        deal=deal,
        kind=DealEvent.Kind.STATUS_CHANGED,
        payload={"status": deal.status, "reason": reason},
    )

    # Close the balance obligation in the same transaction that releases the
    # capacity. This is what defines late-success handling: once the order is
    # cancelled, a provider success that arrives afterwards is recorded as real
    # money, refunded, and explicitly *not* used to revive a Deal whose
    # reservation is already gone. Imported lazily so `apps.deals` keeps no
    # import-time dependency on the finance app.
    from apps.finance.services import (  # noqa: WPS433 (deliberate late import)
        cancel_deal_balance_orders,
    )
    from apps.finance.models import PaymentOrder  # noqa: WPS433

    bound_boosts = [
        row for row in aggregate.request_graph.boost_purchases if row.deal_id == deal.pk
    ]
    boost_order_ids = [
        row.payment_order_id for row in bound_boosts if row.payment_order_id is not None
    ]
    locked_orders = tuple(
        PaymentOrder.objects.select_for_update(no_key=True)
        .filter(Q(deal_id=deal.pk) | Q(pk__in=boost_order_ids))
        .order_by("pk")
    )
    locked_orders_by_id = {order.pk: order for order in locked_orders}

    cancel_deal_balance_orders(deal_id=deal.pk, reason=reason)
    from apps.boosts.services import unwind_boosts  # noqa: WPS433

    unwind_boosts(
        locked_purchases=bound_boosts,
        reason=reason,
        locked_orders=locked_orders_by_id,
        delivery_request=request_row,
        # Deliberately not `clear_intent`. The request is going back to the
        # open pool, and an unpaid J2 Boost belongs to the request, not to the
        # traveler who never funded it -- so it revives with the request. A
        # Boost that *was* funded is already zero here: `fund_deal` cleared it.
    )
    if (
        request_row.status == ParcelRequest.Status.OPEN
        and int(getattr(request_row, "boost_eur_cents", 0) or 0) > 0
    ):
        from apps.boosts.models import BoostIntentEvent  # noqa: WPS433
        from apps.boosts.services import record_boost_transition  # noqa: WPS433

        # The amount does not change; the ranking columns are rebuilt and the
        # revival is stated on the record rather than inferred from a gap.
        record_boost_transition(
            delivery_request=request_row,
            reason=BoostIntentEvent.Reason.RELEASED_WITH_RESERVATION,
            deal_id=deal.pk,
        )
    redis_bus.publish_after_commit(
        channels.DEAL_UPDATED
        if reason == "payment_grace_expired"
        else channels.DEAL_CANCELLED,
        deal_resources(deal),
        targets=[deal.sender_id, deal.traveler_id],
    )
    return ReservationReleaseResult(deal.pk, released, True)


def release_expired_reservations(
    *,
    at: datetime | None = None,
    limit: int = 100,
) -> list[ReservationReleaseResult]:
    """Idempotent database-backed sweep; Redis is not an obligation store."""

    if limit <= 0 or limit > 10_000:
        raise ValueError("Release sweep limit must be between 1 and 10,000.")
    at = at or timezone.now()
    deal_ids = list(
        DealLegAllocation.objects.filter(
            status=DealLegAllocation.Status.PENDING_PAYMENT,
            expires_at__isnull=False,
            expires_at__lte=at,
            deal__status=Deal.Status.PAYMENT_REQUIRED,
        )
        .values("deal_id")
        .annotate(first_expiry=Min("expires_at"))
        .order_by("first_expiry", "deal_id")
        .values_list("deal_id", flat=True)[:limit]
    )
    return [
        release_pending_deal_reservation(
            deal_id=deal_id,
            reason="payment_grace_expired",
            at=at,
            require_expired=True,
        )
        for deal_id in deal_ids
    ]


def cancel_pending_deal(*, deal_id: int, actor_id: int) -> ReservationReleaseResult:
    identity = Deal.objects.values("sender_id", "traveler_id").get(pk=deal_id)
    if actor_id not in (identity["sender_id"], identity["traveler_id"]):
        raise DealCancellationError("Only a deal party may cancel before funding.")
    result = release_pending_deal_reservation(
        deal_id=deal_id,
        reason="deal_cancelled",
    )
    if not result.changed:
        deal_status = Deal.objects.values_list("status", flat=True).get(pk=deal_id)
        if deal_status != Deal.Status.CANCELLED:
            raise DealCancellationError(
                "Only a payment-required deal with a pending reservation may be cancelled."
            )
    return result


@dataclass(frozen=True, slots=True)
class DealFundingResult:
    deal_id: int
    changed: bool
    traveler_id: int
    sender_id: int
    terms: dict


class DealFundingError(RuntimeError):
    code = "deal_funding_error"


def ensure_pickup_code(deal: Deal):
    """Issue the sender's pickup code. Late import keeps app deps one-way."""

    from apps.handover.services import ensure_pickup_code as _ensure

    return _ensure(deal)


@transaction.atomic
def fund_deal(*, deal_id: int, order_id: int) -> DealFundingResult:
    """Move a Deal to FUNDED once its balance obligation is fully covered.

    This is the only path into `Deal.Status.FUNDED`. Provider code never
    reaches in and sets Deal fields: a webhook reconciles a PaymentAttempt, the
    attempt reconciles its PaymentOrder, and only a covered order calls here.

    Idempotent by construction. A Deal already past PAYMENT_REQUIRED returns
    `changed=False`, so two duplicate success events cannot fund twice, and the
    leg allocations move from a pending reservation to a funded one in the same
    transaction as the status change.
    """

    # Acquire the complete business aggregate before any finance caller takes
    # PaymentOrder/PaymentAttempt locks. Re-locking these rows from a nested
    # caller is harmless; acquiring them after a new finance lock is forbidden.
    aggregate = lock_deal_aggregate(deal_id)
    deal = aggregate.deal
    terms = DealTermsSnapshot.objects.filter(deal_id=deal.pk).first()
    if terms is None:
        raise DealFundingError("The deal has no economic terms snapshot.")
    terms_payload = {
        "traveler_reward_minor": int(terms.traveler_reward_minor),
        "platform_fee_minor": int(terms.platform_fee_minor),
        "sender_total_minor": int(terms.sender_total_minor),
        "boost_amount_minor": int(terms.boost_amount_minor),
        "boost_traveler_bonus_minor": int(terms.boost_traveler_bonus_minor),
        "boost_platform_fee_minor": int(terms.boost_platform_fee_minor),
        "boost_economics_version": terms.boost_economics_version,
        "boost_commission_rate_bps": int(terms.boost_commission_rate_bps),
        "traveler_total_minor": terms.traveler_total_minor,
        "platform_total_minor": terms.platform_total_minor,
        "sender_total_with_boost_minor": terms.sender_total_with_boost_minor,
        "commission_rate_bps": int(terms.commission_rate_bps),
        "currency": terms.currency,
    }
    if deal.status != Deal.Status.PAYMENT_REQUIRED:
        return DealFundingResult(
            deal_id=deal.pk,
            changed=False,
            traveler_id=deal.traveler_id,
            sender_id=deal.sender_id,
            terms=terms_payload,
        )

    now = timezone.now()
    allocation_ids = [
        row.pk
        for row in aggregate.allocations
        if row.status == DealLegAllocation.Status.PENDING_PAYMENT
    ]
    if not allocation_ids:
        # The reservation lapsed or was released. Funding a Deal whose capacity
        # is gone would silently oversell a leg, so refuse and let the caller
        # treat the payment as unapplied.
        raise DealFundingError("The deal has no pending capacity reservation.")

    DealLegAllocation.objects.filter(pk__in=allocation_ids).update(
        status=DealLegAllocation.Status.FUNDED,
        expires_at=None,
    )
    # Funding is where the Phase 4 timeline is frozen. Everything the Deal does
    # from here -- the delivery-code buffer, the protection window, the rating
    # window, the cancellation penalty -- reads this snapshot, never live
    # settings, so publishing a new revision tomorrow cannot move a deadline or
    # a price that these two parties have already agreed to.
    match = next(
        (row for row in aggregate.request_graph.matches if row.pk == deal.match_id),
        None,
    )
    lifecycle.snapshot_on_funding(
        deal,
        agreed_pickup_at=lifecycle.resolve_agreed_pickup_at(
            deal=deal, match=match, journey_legs=aggregate.journey_legs
        ),
        match=match,
        journey=aggregate.journey,
        journey_legs=aggregate.journey_legs,
        allocations=aggregate.allocations,
        at=now,
    )
    deal.status = Deal.Status.FUNDED
    deal.funded_at = now
    deal.save(
        update_fields=[
            "status",
            "funded_at",
            "lifecycle_policy",
            "agreed_pickup_at",
            "funded_scheduled_arrival_floor_at",
            "arrival_snapshot",
            "updated_at",
        ]
    )

    # The Boost has now been paid for. Clearing it from the request is what
    # makes "a Boost already consumed can never revive" structural rather than
    # a rule someone has to remember: an unfunded reservation release leaves the
    # column alone and the amount returns to the open pool with the request,
    # while everything past this line has nothing left to return. The frozen
    # copy on `DealTermsSnapshot` remains the authority for this Deal's money.
    request_row = aggregate.request_graph.request
    if int(getattr(request_row, "boost_eur_cents", 0) or 0) > 0:
        from apps.boosts.models import BoostIntentEvent  # noqa: WPS433
        from apps.boosts.services import record_boost_transition  # noqa: WPS433

        record_boost_transition(
            delivery_request=request_row,
            reason=BoostIntentEvent.Reason.CONSUMED_BY_FUNDING,
            amount_eur_cents=0,
            deal_id=deal.pk,
            commission_rate_bps=int(terms.boost_commission_rate_bps),
        )

    # The sender's pickup code exists from the moment the money does. It is a
    # plain insert after the Deal in the lock order; a duplicate loses on
    # `handover_one_live_code_per_kind` and returns the winner.
    ensure_pickup_code(deal)

    DealEvent.objects.create(
        deal=deal,
        kind=DealEvent.Kind.STATUS_CHANGED,
        payload={
            "status": deal.status,
            "reason": "payment_order_covered",
            "payment_order_id": order_id,
        },
    )
    # The arrival basis is part of what these two parties agreed to when the
    # money moved, so it is stated on the record they both read rather than
    # living only in a column. `basis` names which Journey fact produced it.
    DealEvent.objects.create(
        deal=deal,
        kind=DealEvent.Kind.ARRIVAL_SNAPSHOT_FROZEN,
        payload={
            "basis": (deal.arrival_snapshot or {}).get("basis", ""),
            "scheduled_arrival_at": (
                deal.funded_scheduled_arrival_floor_at.isoformat()
                if deal.funded_scheduled_arrival_floor_at
                else None
            ),
            "arrival_leg_id": (deal.arrival_snapshot or {}).get("arrival_leg_id"),
            "arrival_policy_version": (deal.arrival_snapshot or {}).get(
                "policy_version", ""
            ),
            "threshold_seconds": (deal.arrival_snapshot or {}).get(
                "material_early_threshold_seconds"
            ),
        },
    )
    redis_bus.publish_after_commit(
        channels.PAYMENT_CAPTURED,
        {
            **deal_resources(deal),
            "status": deal.status,
            "payment_order_id": order_id,
            "currency": terms_payload["currency"],
        },
        targets=[deal.sender_id, deal.traveler_id],
    )
    return DealFundingResult(
        deal_id=deal.pk,
        changed=True,
        traveler_id=deal.traveler_id,
        sender_id=deal.sender_id,
        terms=terms_payload,
    )
