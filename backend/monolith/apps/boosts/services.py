"""Sender Boost: the J2 reward intent and its economics.

One rule outranks everything else in this module:

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

There is no paid Boost. The J1-era paid visibility package (`BoostPurchase`) is
gone from the code; a paid in-app boost would need Apple and Google billing, and
it does not come back.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core import channels, redis_bus
from apps.core.financial_locks import lock_request_graph
from apps.core.phase4_policy import Phase4Policy, phase4_policy
from apps.finance.models import PaymentOrder
from apps.parcels.models import DeliveryRequest, ParcelRequest

from .models import BoostIntentEvent


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
        _signal_open_offer_economics(request)
    return boost_state(delivery_request=request, viewer_id=actor_id)


def _signal_open_offer_economics(request) -> None:
    """J6.2 -- tell each Traveler holding a pending offer that its money moved.

    A pending offer's totals are provisional: they include whatever Boost the
    request carries right now (J6.1), so this edit just changed them. Without a
    signal, a Traveler with the offer already open kept reading the old figure
    until they refreshed or their accept was refused.

    A hint, not a figure. The payload is identifiers only; the client re-reads
    the offer from the API that owns its numbers, and acceptance still refuses
    stale totals with `offer_economics_changed` whether or not this arrives.

    Scope is exactly the offers whose figures this edit moved: pending V1 offers
    on pending matches for this request, unexpired. Closed and accepted offers
    publish no provisional total, and a legacy DZD offer carries no Boost, so
    none of those is told anything. The sender is not a target -- their own
    save already refreshes their screens.

    Called inside `set_boost_intent`'s transaction, so the publish is scheduled
    on commit and a rolled-back edit signals nothing. The read takes no lock:
    the request row is already held, and acceptance, which is the only writer
    that could close one of these offers concurrently, serialises on it.
    """

    from apps.matching.models import Match, Offer  # noqa: WPS433

    open_offers = (
        Offer.objects.filter(
            match__parcel_id=request.pk,
            match__status=Match.Status.PENDING,
            status=Offer.Status.PENDING,
            economics_version=Offer.EconomicsVersion.V1_EUR,
        )
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
        .order_by("match_id", "pk")
        .values_list("pk", "match_id", "match__traveler_id")
    )
    for offer_id, match_id, traveler_id in open_offers:
        redis_bus.publish_after_commit(
            channels.OFFER_ECONOMICS_CHANGED,
            {"match_id": match_id, "offer_id": offer_id},
            targets=[traveler_id],
        )


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


@dataclass(frozen=True, slots=True)
class CommittedBoost:
    """The Boost an acceptance commits right now.

    `resolve_committed_boost` is the only place that decides it. Acceptance
    freezes its result into `DealTermsSnapshot`, and the Offer projection
    publishes the same result before acceptance, so the two cannot disagree
    about what it costs.
    """

    economics_version: str
    amount_eur_cents: int
    traveler_bonus_eur_cents: int
    platform_fee_eur_cents: int
    commission_rate_bps: int
    snapshot: dict
    #: The J2 reward when one was priced; `None` for no Boost.
    reward: BoostReward | None


def resolve_committed_boost(
    *, boost_intent_eur_cents: int, policy_loader=None
) -> CommittedBoost:
    """Decide the Boost terms a commitment freezes. Integer cents only.

    A J2 reward Boost is unpaid and rides into the Deal balance.

    The Phase 4 policy is read only when there is a Boost to price. An offer
    negotiated under a revision that predates Phase 4 still accepts cleanly,
    and a request could not have acquired a Boost under such a revision in the
    first place, because `set_boost_intent` fails closed on one.
    """

    from apps.deals.models import DealTermsSnapshot  # noqa: WPS433

    intent = int(boost_intent_eur_cents or 0)
    load_policy = policy_loader or phase4_policy
    reward = (
        calculate_boost_reward(amount_eur_cents=intent, policy=load_policy())
        if intent > 0
        else None
    )
    return CommittedBoost(
        economics_version=DealTermsSnapshot.BoostEconomics.ADDITIVE_COMMISSION_V2,
        amount_eur_cents=reward.amount_eur_cents if reward else 0,
        traveler_bonus_eur_cents=reward.traveler_bonus_eur_cents if reward else 0,
        platform_fee_eur_cents=reward.platform_fee_eur_cents if reward else 0,
        commission_rate_bps=reward.commission_rate_bps if reward else 0,
        snapshot=(
            reward.as_dict()
            if reward
            else {"economics_version": "additive_commission_v2", "boost_eur_cents": 0}
        ),
        reward=reward,
    )


def close_request_boost(*, delivery_request, actor_id: int | None = None) -> None:
    """The request itself has ended: its unpaid J2 Boost ends with it.

    Called where the *request* ends -- sender cancellation, expiry unmatched --
    and deliberately not where an unfunded reservation is released, because
    there the request returns to the open pool and an unpaid Boost belongs to
    it, not to the traveler who walked away. Caller holds the request.
    """

    if int(delivery_request.boost_eur_cents or 0) > 0:
        record_boost_transition(
            delivery_request=delivery_request,
            reason=BoostIntentEvent.Reason.REQUEST_CLOSED,
            amount_eur_cents=0,
            actor_id=actor_id,
        )
    else:
        recompute_request_boost(delivery_request)


# --- the ranking columns ------------------------------------------------------


def recompute_request_boost(
    delivery_request: DeliveryRequest | None,
    *,
    at: datetime | None = None,
    policy: Phase4Policy | None = None,
) -> None:
    """Derive the request's two ranking columns from its J2 Boost.

    Derived, never incremented. The weight is what the Boost amount is worth
    and the expiry is the request's own deadline. With no Boost, or a deadline
    already passed, both columns are cleared together, which is what
    `parcels_ranking_boost_pair` requires.

    The Boost deliberately has no expiry of its own: `deadline_at` is the
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
    weight = 0
    if intent > 0 and deadline is not None and deadline > at:
        if policy is None:
            try:
                policy = phase4_policy()
            except Exception:  # noqa: BLE001 - a broken revision must not strand
                policy = None
        weight = (
            policy.boost.ranking_weight_for(intent)
            if policy is not None
            else int(delivery_request.ranking_boost_weight or 0)
        )
    expires_at = deadline if weight else None

    DeliveryRequest.objects.filter(pk=delivery_request.pk).update(
        ranking_boost_weight=weight, ranking_boost_expires_at=expires_at
    )
    # Keep the in-memory row in step with the columns just written, so a caller
    # that goes on to serialise it does not report the previous state.
    delivery_request.ranking_boost_weight = weight
    delivery_request.ranking_boost_expires_at = expires_at


# --- read model ---------------------------------------------------------------


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
    }
