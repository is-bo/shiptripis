"""Paid sender boosts: purchase, activation, expiry and the ranking recompute.

One rule outranks everything else in this module:

    a boost changes where a *compatible* request appears in a list.
    It never makes an incompatible request compatible.

Nothing here reads or writes KYC, capacity, route eligibility, timing, safety or
verification, and the only columns a purchase ever touches on a request are the
two named in `RANKING_FIELDS`. `apps.matching.ranking` applies the resulting
weight as a capped points bonus *after* hard compatibility has already passed --
it raises if asked to rank a candidate that failed -- so "a boost bought its way
past a gate" is not a state this system can be argued into.

Three further properties are structural rather than conventional:

**Money activates a boost; a client never does.** `purchase_boost` creates a
`PaymentOrder` and stops. Activation happens inside `reconcile_attempt`, from
the authoritative provider event, exactly as deposit publication and Deal
funding already do.

**A paid boost that cannot be used is refunded, not stranded.** If the request
stopped being boostable while the money was in flight -- matched, cancelled,
expired, past its deadline -- the purchase is marked `unusable`, refunded in
full and marked `refunded`. There is no branch that keeps the cash and no branch
that activates a boost on a request that can no longer receive offers.

**The ranking columns are derived, never incremented.** `recompute_request_boost`
takes the maximum weight and the latest expiry across the currently active
purchases and writes both, or clears both. Stacking three purchases therefore
buys duration and redundancy, not an unbounded weight, and the pair can never
drift out of the state `parcels_ranking_boost_pair` demands.

The buyer keeps what they were quoted: package, duration, price, weight and the
settings version are snapshotted onto the purchase, so a later revision may
reprice or withdraw a package without touching a boost already sold.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.core.financial_locks import lock_request_graph
from apps.core.phase4_policy import (
    BoostPackage,
    InvalidPhase4Policy,
    Phase4Policy,
    phase4_policy,
)
from apps.finance.models import PaymentOrder, PaymentRefund, ScheduledJob
from apps.finance.services import refund_order_in_full, schedule_job
from apps.parcels.models import DeliveryRequest, ParcelRequest

from .models import BoostPurchase

logger = logging.getLogger(__name__)


class BoostError(RuntimeError):
    """A boost operation was refused. Carries a stable machine code."""

    code = "boost_error"

    def __init__(self, message: str, *, code: str | None = None, **details):
        super().__init__(message)
        if code:
            self.code = code
        self._details = details

    def details(self) -> dict:
        return dict(self._details)


class NotAuthorized(BoostError):
    code = "not_authorized"


#: The only columns a boost may ever write on a `DeliveryRequest`. Anything a
#: future change wants to add here has to argue with the module docstring first.
RANKING_FIELDS = ("ranking_boost_weight", "ranking_boost_expires_at")

#: Statuses that are already decided. Activation is a no-op for all of them.
_SETTLED_STATUSES = (
    BoostPurchase.Status.ACTIVE,
    BoostPurchase.Status.EXPIRED,
    BoostPurchase.Status.REFUNDED,
    BoostPurchase.Status.UNUSABLE,
)


# --- packages -----------------------------------------------------------------


def list_packages(*, policy: Phase4Policy | None = None) -> list[dict]:
    """The purchasable packages, priced by the server.

    Prices come from the active settings revision and are echoed back as
    snapshots, never accepted from a client: the checkout amount is whatever
    this list says it is at the moment of purchase.
    """

    policy = policy or phase4_policy()
    return [
        {**package.snapshot(), "currency": "EUR"} for package in policy.boost.packages
    ]


def _package(policy: Phase4Policy, code: str) -> BoostPackage:
    """One package by code, refusing an unknown code as a client error.

    `BoostPolicy.package` raises `InvalidPhase4Policy`, which the API maps to a
    fail-closed 503. That is the right answer for a malformed revision and the
    wrong one for a client asking for a package that simply is not offered, so
    the two are separated here.
    """

    try:
        return policy.boost.package(code)
    except InvalidPhase4Policy as exc:
        raise BoostError(
            "That boost package is not offered.",
            code="boost_package_unknown",
            package_code=str(code)[:32],
            available=[package.code for package in policy.boost.packages],
        ) from exc


# --- purchase -----------------------------------------------------------------


def purchase_boost(
    *, delivery_request_id: int, actor_id: int, package_code: str
) -> BoostPurchase:
    """Buy one package for one open request, creating the payment obligation.

    Enters through `lock_request_graph`, which takes the request and then this
    request's boost rows in the canonical order, so the slot count that decides
    `boost_limit_reached` cannot be read stale while another purchase commits.

    Returns with the boost still `pending_payment`. The client takes the linked
    order's reference to the existing `/api/payments/orders/<reference>/checkout`
    route; nothing here opens a second payment path, and returning from a
    checkout page activates nothing.
    """

    policy = phase4_policy()
    if not policy.boost.enabled:
        raise BoostError(
            "Boosts are not available at the moment.", code="boost_disabled"
        )
    package = _package(policy, package_code)

    with transaction.atomic():
        try:
            graph = lock_request_graph(delivery_request_id, include_negotiation=False)
        except DeliveryRequest.DoesNotExist as exc:
            # A legacy `ParcelRequest` or a `ProductRequest` id lands here. It
            # is the same refusal as a schema_version 1 row: not boostable.
            raise BoostError(
                "Only V1 delivery requests can be boosted.",
                code="boost_request_not_eligible",
            ) from exc
        request = graph.request

        if request.sender_id != actor_id:
            raise NotAuthorized("Only the sender may boost their own request.")
        if request.schema_version != 2:
            raise BoostError(
                "Only V1 delivery requests can be boosted.",
                code="boost_request_not_eligible",
            )
        if request.status != ParcelRequest.Status.OPEN:
            raise BoostError(
                "Only an open request can be boosted.",
                code="boost_request_not_active",
                request_status=request.status,
            )
        if request.deadline_at is None or request.deadline_at <= timezone.now():
            raise BoostError(
                "This request has passed its deadline.",
                code="boost_request_expired",
            )

        occupying = [
            row
            for row in graph.boost_purchases
            if row.status in BoostPurchase.OCCUPYING_STATUSES
        ]
        if len(occupying) >= policy.boost.max_active_per_request:
            raise BoostError(
                "This request already holds as many boosts as it may.",
                code="boost_limit_reached",
                max_active_per_request=policy.boost.max_active_per_request,
            )

        snapshot = package.snapshot()
        purchase = BoostPurchase.objects.create(
            delivery_request=request,
            buyer_id=actor_id,
            package_code=package.code,
            package_snapshot=snapshot,
            duration_seconds=package.duration_seconds,
            price_eur_cents=package.price_eur_cents,
            ranking_weight=package.ranking_weight,
            business_settings_version=policy.settings_version,
        )
        order = PaymentOrder.objects.create(
            owner_id=actor_id,
            purpose=PaymentOrder.Purpose.BOOST,
            amount_eur_cents=package.price_eur_cents,
            delivery_request_id=request.pk,
            boost_reference=str(purchase.public_reference),
            business_settings_version=policy.settings_version,
            terms_snapshot={
                "boost_package": snapshot,
                "business_settings_version": policy.settings_version.version,
            },
        )
        purchase.payment_order = order
        purchase.save(update_fields=["payment_order", "updated_at"])
    return purchase


# --- activation ---------------------------------------------------------------


def _unusable_reason(request: DeliveryRequest | None, *, at: datetime) -> str:
    """Why this request can no longer carry a boost, or an empty string."""

    if request is None:
        return "request_missing"
    if request.status != ParcelRequest.Status.OPEN:
        return f"request_{request.status}"[:64]
    if request.deadline_at is None or request.deadline_at <= at:
        return "request_deadline_passed"
    return ""


def _refund_unusable(purchase: BoostPurchase, *, order_id: int, reason: str) -> None:
    """Mark a paid-but-unusable purchase and send every captured cent back.

    Two saves rather than one, in this order: the purchase is `unusable` with
    its reason recorded *before* the refund is raised, so a failure between the
    two leaves an operator a row that says what happened and why, rather than a
    purchase that still looks payable.
    """

    purchase.status = BoostPurchase.Status.UNUSABLE
    purchase.disposition_reason = reason[:64]
    purchase.save(update_fields=["status", "disposition_reason", "updated_at"])
    logger.warning(
        "boosts.paid_but_unusable purchase=%s order=%s reason=%s",
        purchase.pk,
        order_id,
        reason,
    )
    refund_order_in_full(
        order_id=order_id, reason=PaymentRefund.Reason.BOOST_UNUSABLE
    )
    purchase.status = BoostPurchase.Status.REFUNDED
    purchase.save(update_fields=["status", "updated_at"])


def activate_paid_boost(*, order_id: int) -> bool:
    """Start the paid window for one boost order. Idempotent.

    Called from inside `reconcile_attempt`'s transaction, with the request
    graph and the order already locked, so this neither opens a transaction nor
    acquires a lock out of order.

    Returns True only when this call is the one that made the boost active. A
    replayed webhook, a duplicated provider event and a manual re-reconcile all
    return False without moving an expiry or re-arming a job.
    """

    purchase = BoostPurchase.objects.filter(payment_order_id=order_id).first()
    if purchase is None:
        # A BOOST order with no purchase behind it is a data defect, not a
        # payment problem: the money is real, so it stays visible rather than
        # being silently absorbed.
        logger.error("boosts.order_without_purchase order=%s", order_id)
        return False
    if purchase.status in _SETTLED_STATUSES:
        return False

    at = timezone.now()
    request = DeliveryRequest.objects.filter(
        pk=purchase.delivery_request_id
    ).first()

    if purchase.status == BoostPurchase.Status.CANCELLED:
        # Cancelled before the money landed. Activating it would sell something
        # the buyer withdrew from, so the cash goes back instead.
        _refund_unusable(purchase, order_id=order_id, reason="purchase_cancelled")
        return False

    reason = _unusable_reason(request, at=at)
    if reason:
        _refund_unusable(purchase, order_id=order_id, reason=reason)
        return False

    purchase.status = BoostPurchase.Status.ACTIVE
    purchase.activated_at = at
    purchase.expires_at = at + timedelta(seconds=int(purchase.duration_seconds))
    purchase.save(
        update_fields=["status", "activated_at", "expires_at", "updated_at"]
    )
    recompute_request_boost(request, at=at)
    # The expiry is an obligation in the database, not a timer in a worker's
    # memory: stop every process for a week and the boost still retires.
    schedule_job(
        kind=ScheduledJob.Kind.BOOST_EXPIRY,
        key=f"boost_expiry:{purchase.pk}",
        run_at=purchase.expires_at,
        payload={"boost_purchase_id": purchase.pk},
    )
    return True


# --- expiry -------------------------------------------------------------------


def expire_boost(*, purchase_id: int, at: datetime | None = None) -> str:
    """Retire a boost whose paid window has ended. Idempotent.

    Refuses to expire early: the stored `expires_at` is the authority, not the
    schedule, so a job whose `run_at` was moved forward or a worker whose clock
    drifted cannot cut a paid window short.

    History is never deleted. The row stays, `expired`, with its snapshot -- the
    ranking effect goes away because `recompute_request_boost` stops counting
    it, not because the evidence was removed.
    """

    at = at or timezone.now()
    snapshot = (
        BoostPurchase.objects.filter(pk=purchase_id)
        .values("delivery_request_id")
        .first()
    )
    if snapshot is None:
        return "purchase_missing"

    with transaction.atomic():
        # Through the request graph so boost rows are taken after the request,
        # in the canonical order, exactly as a purchase takes them.
        graph = lock_request_graph(
            snapshot["delivery_request_id"], include_negotiation=False
        )
        purchase = next(
            (row for row in graph.boost_purchases if row.pk == purchase_id), None
        )
        if purchase is None:
            return "purchase_missing"
        if purchase.status != BoostPurchase.Status.ACTIVE:
            return f"purchase_{purchase.status}"
        if purchase.expires_at is not None and purchase.expires_at > at:
            return "not_due"

        purchase.status = BoostPurchase.Status.EXPIRED
        purchase.save(update_fields=["status", "updated_at"])
        recompute_request_boost(graph.request, at=at)
    return "expired"


# --- the ranking columns ------------------------------------------------------


def recompute_request_boost(
    delivery_request: DeliveryRequest | None, *, at: datetime | None = None
) -> None:
    """Derive the request's two ranking columns from its active purchases.

    Derived, never incremented: the weight is the maximum across the purchases
    that are active right now and the expiry is the latest of theirs, so a
    replayed activation, a double-counted refund or a lost expiry job cannot
    accumulate a weight nobody bought. With none active both columns are
    cleared together, which is what `parcels_ranking_boost_pair` requires.

    The write goes through `QuerySet.update` on purpose. `DeliveryRequest.save`
    calls `full_clean`, so saving the instance would re-validate the whole V1
    contract -- and a boost has no business failing because some unrelated field
    on a months-old request no longer validates.
    """

    if delivery_request is None:
        return
    at = at or timezone.now()
    totals = BoostPurchase.objects.filter(
        delivery_request_id=delivery_request.pk,
        status=BoostPurchase.Status.ACTIVE,
        expires_at__gt=at,
    ).aggregate(weight=Max("ranking_weight"), expires_at=Max("expires_at"))

    weight = int(totals["weight"] or 0)
    expires_at = totals["expires_at"] if weight else None
    if weight and expires_at is None:
        # Cannot happen while `boosts_active_requires_window` holds, but the
        # pair constraint is absolute: an unpaired weight is dropped rather
        # than written.
        logger.error(
            "boosts.active_without_expiry request=%s", delivery_request.pk
        )
        weight = 0

    DeliveryRequest.objects.filter(pk=delivery_request.pk).update(
        ranking_boost_weight=weight, ranking_boost_expires_at=expires_at
    )
    # Keep the in-memory row in step with the columns just written, so a caller
    # that goes on to serialise it does not report the previous state.
    delivery_request.ranking_boost_weight = weight
    delivery_request.ranking_boost_expires_at = expires_at


# --- read model ---------------------------------------------------------------


def _projection(purchase: BoostPurchase, *, at: datetime) -> dict:
    order = purchase.payment_order
    return {
        "public_reference": str(purchase.public_reference),
        "package_code": purchase.package_code,
        "package_snapshot": dict(purchase.package_snapshot or {}),
        "status": purchase.status,
        "is_active": purchase.is_active(at=at),
        "price_eur_cents": int(purchase.price_eur_cents),
        "currency": "EUR",
        "duration_seconds": int(purchase.duration_seconds),
        "ranking_weight": int(purchase.ranking_weight),
        "activated_at": purchase.activated_at,
        "expires_at": purchase.expires_at,
        "cancelled_at": purchase.cancelled_at,
        "disposition_reason": purchase.disposition_reason,
        "created_at": purchase.created_at,
        "payment_order_reference": (
            str(order.public_reference) if order is not None else None
        ),
        "payment_status": order.status if order is not None else None,
        "payment_outstanding_eur_cents": (
            order.outstanding_eur_cents if order is not None else None
        ),
    }


def boost_state(*, delivery_request: DeliveryRequest, viewer_id: int) -> dict:
    """The boost history and current ranking effect for one request.

    Deliberately reads no policy: this is the owner's history view, and it must
    keep working while the packages endpoint is failing closed on a settings
    revision that cannot drive Phase 4.

    `affects_compatibility` is stated explicitly and is always false. It is a
    contract the client can assert against and a line any future change would
    have to consciously edit.
    """

    at = timezone.now()
    rows = list(
        BoostPurchase.objects.filter(delivery_request_id=delivery_request.pk)
        .select_related("payment_order")
        .order_by("-created_at", "-id")
    )
    return {
        "delivery_request_id": delivery_request.pk,
        "request_status": delivery_request.status,
        "is_owner": delivery_request.sender_id == viewer_id,
        "ranking_boost_active": delivery_request.is_ranking_boost_active(at=at),
        "ranking_boost_weight": int(delivery_request.ranking_boost_weight),
        "ranking_boost_expires_at": delivery_request.ranking_boost_expires_at,
        "affects_compatibility": False,
        "active_count": sum(1 for row in rows if row.is_active(at=at)),
        "occupied_slots": sum(
            1 for row in rows if row.status in BoostPurchase.OCCUPYING_STATUSES
        ),
        "purchases": [_projection(row, at=at) for row in rows],
    }
