"""Sender Boost: the J2 reward intent, its economics, and the retired package.

One rule outranks everything else in this module and survives both models:

    a boost changes where a *compatible* request appears in a list.
    It never makes an incompatible request compatible.

Nothing here reads or writes KYC, capacity, route eligibility, timing, safety or
verification, and the only columns a boost ever touches on a request are the
three named in `BOOST_FIELDS`. `apps.matching.ranking` applies the resulting
weight as a capped points bonus *after* hard compatibility has already passed --
it raises if asked to rank a candidate that failed -- so "a boost bought its way
past a gate" is not a state this system can be argued into.

**J2 Boost is extra reward, not a purchase.** The sender names an amount; the
Traveler receives all of it; ShipTrip's commission on it is charged on top, at a
rate the Admin sets separately from the base commission. Four properties are
structural:

*No timer.* A Boost lives exactly as long as the request is eligible to be
matched. There is no Boost expiry, no countdown and no package window. The
ranking pair's expiry is the request's own `deadline_at`, which is the instant
the request stops being matchable anyway.

*Editable until it is committed, immutable after.* `set_boost_intent` refuses
on any status but `open` or `awaiting_deposit`, so the moment an offer is
accepted the amount the Traveler was shown is the amount that binds. A sender
cannot reduce Traveler compensation after commitment.

*Frozen once, consumed once.* Acceptance copies the amount and the rate into
`DealTermsSnapshot`; funding clears `boost_eur_cents` on the request. An unfunded
reservation release therefore revives an unpaid Boost with the request, and a
Boost the sender has actually paid can never revive onto a reopened one --
because by then the column is zero. That is a structural answer to the rematch
question, not a policy one.

*Collected with the reward it belongs to.* There is no Boost payment order in
J2. The amount and its commission ride inside the Deal balance, so the Boost
funds, refunds, settles and reconciles through exactly the same path as the base
reward, and no orphan Boost revenue can exist.

**The retired package.** `BoostPurchase`, its payment order and its
Traveler/platform split were the J1-era paid visibility product. Purchasing is
gone -- the endpoint answers 410. Existing rows keep their snapshot, keep their
ranking effect until they expire, and a payment already in flight still
reconciles through `activate_paid_boost`. `recompute_request_boost` derives the
request's ranking columns from whichever of the two is stronger, so the two
models cannot fight over the same column.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.core.financial_locks import lock_request_graph
from apps.core.phase4_policy import Phase4Policy, phase4_policy
from apps.finance.models import PaymentOrder, PaymentRefund, ScheduledJob
from apps.finance.services import refund_order_in_full, schedule_job
from apps.parcels.models import DeliveryRequest, ParcelRequest

from .models import BoostIntentEvent, BoostPurchase

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


class BoostBelowPrepaidDeposit(BoostError):
    """Lowering the Boost would leave a deposit pre-paying more than is owed."""

    code = "boost_below_prepaid_deposit"


#: The only columns a boost may ever write on a `DeliveryRequest`. Anything a
#: future change wants to add here has to argue with the module docstring first.
BOOST_FIELDS = ("boost_eur_cents", "ranking_boost_weight", "ranking_boost_expires_at")
#: The two ranking columns alone, under the name earlier phases used.
RANKING_FIELDS = ("ranking_boost_weight", "ranking_boost_expires_at")

#: The request statuses in which a sender may still change their Boost. Both
#: are pre-commitment: `awaiting_deposit` is the sender's own unpublished
#: request, `open` is published and unmatched. Everything else is either
#: committed to a Traveler or terminal.
EDITABLE_STATUSES = (
    ParcelRequest.Status.AWAITING_DEPOSIT,
    ParcelRequest.Status.OPEN,
)

#: Statuses that are already decided. Activation is a no-op for all of them.
_SETTLED_STATUSES = (
    BoostPurchase.Status.ACTIVE,
    BoostPurchase.Status.EXPIRED,
    BoostPurchase.Status.REFUNDED,
    BoostPurchase.Status.UNUSABLE,
)

# PostgreSQL BIGINT storage ceiling. A representation guard, not a product
# limit: the product band is `boost.minimum_intent_eur_cents` to
# `boost.maximum_intent_eur_cents` and lives in the settings revision.
MAX_EUR_CENTS = 9_223_372_036_854_775_807


# --- J2 boost economics -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BoostReward:
    """One Boost amount priced under the J2 additive-commission model.

    The Traveler receives the whole Boost. ShipTrip's commission is charged on
    top of it, so the sender pays `amount + platform_fee` -- structurally the
    same shape as the base reward, where the sender pays reward + commission and
    the Traveler is never quietly shorted what they agreed to carry for.
    """

    amount_eur_cents: int
    commission_rate_bps: int
    traveler_bonus_eur_cents: int
    platform_fee_eur_cents: int

    @property
    def sender_cost_eur_cents(self) -> int:
        return self.amount_eur_cents + self.platform_fee_eur_cents

    def as_dict(self) -> dict:
        return {
            "economics_version": "additive_commission_v2",
            "currency": "EUR",
            "boost_eur_cents": self.amount_eur_cents,
            "boost_commission_rate_bps": self.commission_rate_bps,
            "boost_traveler_bonus_eur_cents": self.traveler_bonus_eur_cents,
            "boost_platform_fee_eur_cents": self.platform_fee_eur_cents,
            "boost_sender_cost_eur_cents": self.sender_cost_eur_cents,
            "rounding_rule": "platform_ceiling_traveler_receives_full_boost",
        }


def calculate_boost_reward(
    *, amount_eur_cents: int, policy: Phase4Policy
) -> BoostReward:
    """Price one Boost amount. Integer cents, ceiling to the platform.

    Deliberately the same rounding rule as `calculate_offer_economics`: the fee
    is `ceil(amount x rate / 10,000)` and the Traveler's side is never reduced
    by a rounding decision. No float ever touches this arithmetic.
    """

    amount = int(amount_eur_cents)
    if amount < 0:
        raise BoostError(
            "A boost cannot be negative.", code="boost_amount_out_of_range"
        )
    rate = int(policy.boost.commission_rate_bps)
    if amount == 0:
        return BoostReward(
            amount_eur_cents=0,
            commission_rate_bps=rate,
            traveler_bonus_eur_cents=0,
            platform_fee_eur_cents=0,
        )
    fee = (amount * rate + 9_999) // 10_000
    return BoostReward(
        amount_eur_cents=amount,
        commission_rate_bps=rate,
        traveler_bonus_eur_cents=amount,
        platform_fee_eur_cents=fee,
    )


def validate_boost_amount(*, amount_eur_cents: int, policy: Phase4Policy) -> int:
    """Refuse an amount outside the configured band. Zero is always allowed."""

    amount = int(amount_eur_cents)
    if amount < 0 or amount > MAX_EUR_CENTS:
        raise BoostError(
            "That boost amount cannot be represented in EUR cents.",
            code="boost_amount_out_of_range",
        )
    if amount == 0:
        return 0
    minimum = int(policy.boost.minimum_intent_eur_cents)
    maximum = int(policy.boost.maximum_intent_eur_cents)
    if amount < minimum:
        raise BoostError(
            "That boost is below the minimum.",
            code="boost_amount_below_minimum",
            minimum_boost_eur_cents=minimum,
            maximum_boost_eur_cents=maximum,
        )
    if amount > maximum:
        raise BoostError(
            "That boost is above the maximum.",
            code="boost_amount_above_maximum",
            minimum_boost_eur_cents=minimum,
            maximum_boost_eur_cents=maximum,
        )
    return amount


def boost_policy_payload(policy: Phase4Policy) -> dict:
    """The bounds and the rate a client may show before the sender chooses."""

    return {
        "currency": "EUR",
        "enabled": policy.boost.enabled,
        "minimum_boost_eur_cents": policy.boost.minimum_intent_eur_cents,
        "maximum_boost_eur_cents": policy.boost.maximum_intent_eur_cents,
        "boost_commission_rate_bps": policy.boost.commission_rate_bps,
        "settings_version": policy.settings_version.version,
        "affects_compatibility": False,
        "has_expiry": False,
    }


# --- J2 boost intent ----------------------------------------------------------


def _assert_editable(request, *, actor_id: int) -> None:
    """Refuse every reason this request's Boost may not be changed right now."""

    if request.sender_id != actor_id:
        raise NotAuthorized("Only the sender may change their own request's boost.")
    if request.schema_version not in (2, 3):
        raise BoostError(
            "Only V1 delivery requests carry a boost.",
            code="boost_request_not_eligible",
        )
    if request.status not in EDITABLE_STATUSES:
        # Includes every committed state. Once an offer is accepted the amount
        # the Traveler was shown is the amount that binds, so no path here can
        # reduce Traveler compensation after commitment.
        raise BoostError(
            "This request's boost is no longer editable.",
            code="boost_request_not_active",
            request_status=request.status,
        )
    if request.deadline_at is None or request.deadline_at <= timezone.now():
        raise BoostError(
            "This request has passed its deadline.",
            code="boost_request_expired",
        )


def _assert_deposit_still_covered(request, *, amount_eur_cents: int) -> None:
    """Refuse a Boost cut that would strand money already committed to a deposit.

    A posting deposit is paid *against* a total: the sender's chosen reward, its
    commission, and their Boost with its own. Lowering the Boost lowers that
    total, and `apply_posting_deposit_credit` only ever credits
    `min(deposit paid, balance owed)` -- so a deposit larger than the new total
    would leave the difference discharging nothing, neither credited nor
    refunded. That is real money quietly stuck, so the reduction is refused
    instead.

    The order is locked, and it is acquired after the request and its boost rows,
    which is the canonical financial lock order.
    """

    from apps.finance.services import maximum_chosen_deposit
    from apps.finance.policy import phase3_policy

    deposit = (
        PaymentOrder.objects.select_for_update(no_key=True)
        .filter(
            delivery_request_id=request.pk,
            purpose=PaymentOrder.Purpose.POSTING_DEPOSIT,
        )
        .exclude(status=PaymentOrder.Status.CANCELLED)
        .order_by("pk")
        .first()
    )
    if deposit is None:
        return
    committed = int(deposit.amount_eur_cents)
    if committed <= 0:
        return

    # Evaluate the ceiling as it would be *after* the change.
    previous = int(request.boost_eur_cents)
    request.boost_eur_cents = amount_eur_cents
    try:
        ceiling = maximum_chosen_deposit(
            delivery_request=request, policy=phase3_policy()
        )
    except Exception:  # noqa: BLE001 - a finance failure is not a boost refusal
        return
    finally:
        request.boost_eur_cents = previous

    if committed > ceiling:
        raise BoostBelowPrepaidDeposit(
            "Your posting deposit already covers more than that. Lower the "
            "deposit first, or keep the boost at or above this amount.",
            deposit_eur_cents=committed,
            minimum_boost_eur_cents=int(amount_eur_cents) + (committed - ceiling),
        )


def _intent_reason(previous: int, amount: int) -> str:
    if amount == 0:
        return BoostIntentEvent.Reason.SENDER_REMOVED
    if previous == 0:
        return BoostIntentEvent.Reason.SENDER_SET
    if amount > previous:
        return BoostIntentEvent.Reason.SENDER_INCREASED
    if amount < previous:
        return BoostIntentEvent.Reason.SENDER_DECREASED
    return BoostIntentEvent.Reason.SENDER_SET


def set_boost_intent(
    *,
    delivery_request_id: int,
    actor_id: int,
    amount_eur_cents: int,
) -> dict:
    """Set, raise, lower or remove the sender's Boost on one open request.

    Enters through `lock_request_graph`, which takes the request row itself, so
    a Traveler accepting an offer and a sender editing their Boost serialise on
    the same row: whichever commits second reads the first one's state. An edit
    that arrives after acceptance finds a `matched` request and is refused,
    which is exactly the guarantee the frozen Deal terms depend on.

    Idempotent in the sense that matters: setting the amount it already holds
    writes no event and touches no column.
    """

    policy = phase4_policy()
    if not policy.boost.enabled:
        raise BoostError(
            "Boosts are not available at the moment.", code="boost_disabled"
        )
    amount = validate_boost_amount(amount_eur_cents=amount_eur_cents, policy=policy)

    with transaction.atomic():
        try:
            graph = lock_request_graph(delivery_request_id, include_negotiation=False)
        except DeliveryRequest.DoesNotExist as exc:
            raise BoostError(
                "Only V1 delivery requests carry a boost.",
                code="boost_request_not_eligible",
            ) from exc
        request = graph.request
        _assert_editable(request, actor_id=actor_id)

        previous = int(request.boost_eur_cents)
        if previous == amount:
            return boost_state(delivery_request=request, viewer_id=actor_id)
        if amount < previous:
            _assert_deposit_still_covered(request, amount_eur_cents=amount)

        reward = calculate_boost_reward(amount_eur_cents=amount, policy=policy)
        # `QuerySet.update`, not `save`: `DeliveryRequest.save` runs
        # `full_clean`, and a boost edit has no business failing because some
        # unrelated field on a months-old request no longer validates.
        DeliveryRequest.objects.filter(pk=request.pk).update(boost_eur_cents=amount)
        request.boost_eur_cents = amount
        recompute_request_boost(request, policy=policy)
        BoostIntentEvent.objects.create(
            delivery_request_id=request.pk,
            actor_id=actor_id,
            reason=_intent_reason(previous, amount),
            previous_eur_cents=previous,
            amount_eur_cents=amount,
            commission_rate_bps=reward.commission_rate_bps,
            ranking_weight=int(request.ranking_boost_weight),
            business_settings_version=policy.settings_version,
            request_status=request.status,
        )
    return boost_state(delivery_request=request, viewer_id=actor_id)


def record_boost_transition(
    *,
    delivery_request,
    reason: str,
    amount_eur_cents: int | None = None,
    deal_id: int | None = None,
    actor_id: int | None = None,
    commission_rate_bps: int = 0,
) -> None:
    """Append one platform-driven Boost transition. Caller holds the request.

    Used by the commitment, funding and closure boundaries. `amount_eur_cents`
    is the value the column is being moved to; omit it to record the current
    value without changing it, which is what a freeze does.
    """

    previous = int(delivery_request.boost_eur_cents)
    amount = previous if amount_eur_cents is None else int(amount_eur_cents)
    if amount != previous:
        DeliveryRequest.objects.filter(pk=delivery_request.pk).update(
            boost_eur_cents=amount
        )
        delivery_request.boost_eur_cents = amount
    # Unconditionally, even when the amount did not move. The ranking columns
    # are derived, and a transition that leaves the amount alone can still
    # change what it is worth -- a reservation release puts the request back in
    # the pool, and the deadline it is paired with may have moved on since.
    recompute_request_boost(delivery_request)
    BoostIntentEvent.objects.create(
        delivery_request_id=delivery_request.pk,
        actor_id=actor_id,
        deal_id=deal_id,
        reason=reason,
        previous_eur_cents=previous,
        amount_eur_cents=amount,
        commission_rate_bps=commission_rate_bps,
        ranking_weight=int(delivery_request.ranking_boost_weight),
        request_status=delivery_request.status,
    )


# --- the retired package ------------------------------------------------------


class BoostPurchaseRetired(BoostError):
    """The J1-era paid visibility package is no longer sold."""

    code = "boost_package_retired"


def purchase_boost(*args, **kwargs):
    """Refuse. J2 replaced the paid package with the sender's reward Boost.

    Kept as an explicit refusal rather than deleted: a caller that still reaches
    for it gets a named answer instead of an `AttributeError`, and the
    retirement stays visible where the old product lived.
    """

    del args, kwargs
    raise BoostPurchaseRetired(
        "Boost packages are retired. Set the request's boost reward instead."
    )


def bind_paid_boosts_to_deal(*, locked_purchases, deal) -> dict:
    """Freeze paid economic boosts into a Deal; caller holds request/boost rows.

    Payment orders are acquired only after the Deal exists, preserving the
    canonical request -> boost -> journey -> deal -> payment order lock order.
    """

    candidates = [
        row
        for row in locked_purchases
        if row.deal_id is None
        and row.economics_version == BoostPurchase.EconomicsVersion.TRAVELER_SPLIT_V1
        and row.status in (BoostPurchase.Status.ACTIVE, BoostPurchase.Status.EXPIRED)
        and row.payment_order_id is not None
    ]
    order_ids = sorted(row.payment_order_id for row in candidates)
    paid_order_ids = set(
        PaymentOrder.objects.select_for_update(no_key=True)
        .filter(pk__in=order_ids, status=PaymentOrder.Status.PAID)
        .values_list("pk", flat=True)
    )
    bound = [row for row in candidates if row.payment_order_id in paid_order_ids]
    for row in bound:
        row.deal = deal
        row.save(update_fields=["deal", "updated_at"])
    if paid_order_ids:
        PaymentOrder.objects.filter(pk__in=paid_order_ids).update(deal=deal)
        from apps.finance import ledger  # noqa: WPS433

        for row in bound:
            ledger.record_boost_binding(
                deal_id=deal.pk,
                order_id=row.payment_order_id,
                purchase_id=row.pk,
                amount_eur_cents=int(row.amount_eur_cents),
            )
    return {
        "purchase_ids": [row.pk for row in bound],
        "amount_eur_cents": sum(int(row.amount_eur_cents) for row in bound),
        "traveler_boost_eur_cents": sum(
            int(row.traveler_boost_eur_cents) for row in bound
        ),
        "platform_boost_eur_cents": sum(
            int(row.platform_boost_eur_cents) for row in bound
        ),
    }


def unwind_boosts(
    *,
    locked_purchases,
    reason: str,
    requested_by_id: int | None = None,
    locked_orders: dict[int, PaymentOrder] | None = None,
    delivery_request=None,
    clear_intent: bool = False,
) -> int:
    """Close out a request's boosts. Idempotent.

    Retired purchases are cancelled when unpaid and refunded in full when paid,
    exactly as before -- a settled payment for something that can no longer earn
    goes back.

    `clear_intent` additionally zeroes the J2 reward Boost and records why. It
    is set only where the *request itself* ends -- sender cancellation, expiry
    unmatched -- and deliberately not where an unfunded reservation is released,
    because there the request returns to the open pool and an unpaid Boost
    belongs to it, not to the traveler who walked away.
    """

    from apps.finance.services import cancel_order

    terminal_statuses = (
        BoostPurchase.Status.REFUNDED,
        BoostPurchase.Status.UNUSABLE,
        BoostPurchase.Status.CANCELLED,
    )
    order_ids = sorted(
        purchase.payment_order_id
        for purchase in locked_purchases
        if purchase.payment_order_id is not None
        and purchase.status not in terminal_statuses
    )
    if locked_orders is None:
        locked_orders = {
            order.pk: order
            for order in PaymentOrder.objects.select_for_update(no_key=True)
            .filter(pk__in=order_ids)
            .order_by("pk")
        }
    elif any(order_id not in locked_orders for order_id in order_ids):
        raise ValueError("Every boost PaymentOrder must be locked before unwind.")

    changed = 0
    at = timezone.now()
    for purchase in locked_purchases:
        if purchase.status in terminal_statuses:
            continue
        if purchase.payment_order_id is None:
            purchase.status = BoostPurchase.Status.CANCELLED
            purchase.cancelled_at = at
            purchase.disposition_reason = reason[:64]
            purchase.save(
                update_fields=[
                    "status",
                    "cancelled_at",
                    "disposition_reason",
                    "updated_at",
                ]
            )
            changed += 1
            continue
        order = locked_orders.get(purchase.payment_order_id)
        if order is not None and int(order.paid_eur_cents) > 0:
            refund_order_in_full(
                order_id=order.pk,
                reason=PaymentRefund.Reason.BOOST_UNUSABLE,
                requested_by_id=requested_by_id,
            )
            purchase.status = BoostPurchase.Status.REFUNDED
        else:
            purchase.status = BoostPurchase.Status.CANCELLED
            purchase.cancelled_at = at
        purchase.disposition_reason = reason[:64]
        purchase.save(
            update_fields=["status", "cancelled_at", "disposition_reason", "updated_at"]
        )
        cancel_order(order_id=purchase.payment_order_id, reason=reason[:64])
        changed += 1
    if delivery_request is not None:
        if clear_intent and int(delivery_request.boost_eur_cents or 0) > 0:
            record_boost_transition(
                delivery_request=delivery_request,
                reason=BoostIntentEvent.Reason.REQUEST_CLOSED,
                amount_eur_cents=0,
                actor_id=requested_by_id,
            )
        elif changed or clear_intent:
            recompute_request_boost(delivery_request, at=at)
    return changed


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
    refund_order_in_full(order_id=order_id, reason=PaymentRefund.Reason.BOOST_UNUSABLE)
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
    request = DeliveryRequest.objects.filter(pk=purchase.delivery_request_id).first()

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
    purchase.save(update_fields=["status", "activated_at", "expires_at", "updated_at"])
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
    delivery_request: DeliveryRequest | None,
    *,
    at: datetime | None = None,
    policy: Phase4Policy | None = None,
) -> None:
    """Derive the request's two ranking columns from both Boost models.

    Derived, never incremented. The weight is the larger of what the J2 reward
    Boost is worth and what any still-active historical purchase bought, and the
    expiry is the later of the request's own deadline and those purchases'. With
    neither contributing, both columns are cleared together, which is what
    `parcels_ranking_boost_pair` requires.

    The J2 side deliberately has no expiry of its own: `deadline_at` is the
    instant the request stops being matchable at all, so pairing the weight with
    it is the honest way to say "this lasts as long as the request does" inside
    a constraint that demands a pair. It is not a Boost timer, and no job
    retires it.

    Reading policy is optional so the closure and release paths can call this
    while a settings revision is unparseable: without it the J2 weight falls
    back to the last one recorded, which never invents a weight nobody chose.

    The write goes through `QuerySet.update` on purpose. `DeliveryRequest.save`
    calls `full_clean`, so saving the instance would re-validate the whole V1
    contract -- and a boost has no business failing because some unrelated field
    on a months-old request no longer validates.
    """

    if delivery_request is None:
        return
    at = at or timezone.now()

    intent = int(delivery_request.boost_eur_cents or 0)
    deadline = delivery_request.deadline_at
    intent_weight = 0
    if intent > 0 and deadline is not None and deadline > at:
        if policy is None:
            try:
                policy = phase4_policy()
            except Exception:  # noqa: BLE001 - a broken revision must not strand
                policy = None
        intent_weight = (
            policy.boost.ranking_weight_for(intent)
            if policy is not None
            else int(delivery_request.ranking_boost_weight or 0)
        )

    legacy = BoostPurchase.objects.filter(
        delivery_request_id=delivery_request.pk,
        status=BoostPurchase.Status.ACTIVE,
        expires_at__gt=at,
    ).aggregate(weight=Max("ranking_weight"), expires_at=Max("expires_at"))
    legacy_weight = int(legacy["weight"] or 0)

    weight = max(intent_weight, legacy_weight)
    expires_at = None
    if weight:
        candidates = []
        if intent_weight:
            candidates.append(deadline)
        if legacy_weight and legacy["expires_at"] is not None:
            candidates.append(legacy["expires_at"])
        expires_at = max(candidates) if candidates else None
    if weight and expires_at is None:
        # Cannot happen while both branches above hold, but the pair constraint
        # is absolute: an unpaired weight is dropped rather than written.
        logger.error("boosts.weight_without_expiry request=%s", delivery_request.pk)
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
        "amount_eur_cents": int(purchase.amount_eur_cents),
        "economics_version": purchase.economics_version,
        "traveler_share_bps": int(purchase.traveler_share_bps),
        "traveler_boost_eur_cents": int(purchase.traveler_boost_eur_cents),
        "platform_boost_eur_cents": int(purchase.platform_boost_eur_cents),
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
    """This request's Boost: what it is now, what it costs, and its history.

    The J2 reward block is what a client renders. Economics are priced here so
    Flutter never computes a financial total: `boost_traveler_bonus_eur_cents`
    is what the Traveler gains, `boost_platform_fee_eur_cents` is ShipTrip's
    commission on the Boost, and `boost_sender_cost_eur_cents` is the two
    together -- what the sender will actually owe for boosting.

    Pricing degrades rather than failing: if the active revision cannot drive
    Phase 4 the amount and the history are still returned, with `economics`
    null and `can_edit` false. An owner must always be able to see what they
    have committed to, even during a bad settings revision.

    `affects_compatibility` is stated explicitly and is always false. It is a
    contract the client can assert against and a line any future change would
    have to consciously edit.
    """

    at = timezone.now()
    amount = int(delivery_request.boost_eur_cents or 0)
    is_owner = delivery_request.sender_id == viewer_id
    editable_status = delivery_request.status in EDITABLE_STATUSES
    deadline = delivery_request.deadline_at

    economics: dict | None = None
    policy_payload: dict | None = None
    try:
        policy = phase4_policy()
    except Exception:  # noqa: BLE001 - history must survive a bad revision
        policy = None
    if policy is not None:
        economics = calculate_boost_reward(
            amount_eur_cents=amount, policy=policy
        ).as_dict()
        policy_payload = boost_policy_payload(policy)

    rows = list(
        BoostPurchase.objects.filter(delivery_request_id=delivery_request.pk)
        .select_related("payment_order")
        .order_by("-created_at", "-id")
    )
    events = list(
        BoostIntentEvent.objects.filter(
            delivery_request_id=delivery_request.pk
        ).order_by("-created_at", "-id")[:50]
    )
    return {
        "delivery_request_id": delivery_request.pk,
        "request_status": delivery_request.status,
        "is_owner": is_owner,
        # The J2 reward Boost.
        "boost_eur_cents": amount,
        "economics": economics,
        "policy": policy_payload,
        "can_edit": bool(
            is_owner
            and editable_status
            and deadline is not None
            and deadline > at
            and policy is not None
            and policy.boost.enabled
        ),
        # Boost has no timer. It lasts exactly as long as the request can still
        # be matched, which is what this instant is.
        "eligible_until": deadline,
        "ranking_boost_active": delivery_request.is_ranking_boost_active(at=at),
        "ranking_boost_weight": int(delivery_request.ranking_boost_weight),
        "ranking_boost_expires_at": delivery_request.ranking_boost_expires_at,
        "affects_compatibility": False,
        "history": [
            {
                "reason": row.reason,
                "previous_eur_cents": int(row.previous_eur_cents),
                "amount_eur_cents": int(row.amount_eur_cents),
                "created_at": row.created_at,
            }
            for row in events
        ],
        # The retired paid package, retained for audit. Empty for every request
        # created since J2.
        "active_count": sum(1 for row in rows if row.is_active(at=at)),
        "occupied_slots": sum(
            1 for row in rows if row.status in BoostPurchase.OCCUPYING_STATUSES
        ),
        "purchases": [_projection(row, at=at) for row in rows],
    }
