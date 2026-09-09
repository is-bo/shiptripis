"""Domain services for V1 money.

Every state change to a `PaymentOrder`, `PaymentAttempt`, `PaymentRefund` or
`Payout` happens through a function in this module. Views do not mutate
financial rows, provider adapters do not mutate financial rows, and webhook
handlers reconcile through `apply_provider_event` rather than writing anything
directly.

Three properties this module is built to hold:

**The server decides every amount.** A client supplies a provider choice and
nothing else. Deposits, balances, credits, conversions and refunds are all
computed here from versioned policy.

**Money is recomputed, not incremented.** `_recompute_order_money` derives an
order's captured and refunded totals by summing its own attempts and refunds.
A replayed webhook therefore converges on the same numbers instead of adding a
second time, and a partially-applied crash self-heals on the next event.

**A redirect is never authority.** The only inputs that move an order forward
are a signature-verified provider event and a provider-polled reconciliation.

Lock order
----------
Cross-domain transitions use the complete canonical order documented in
``apps.core.financial_locks``: request/negotiation rows, journey rows, Deal and
allocations, then PaymentOrder, PaymentAttempt, provider event/refund/payout,
ledger and finally ScheduledJob. Event/job claims commit before entering that
graph. Finance-only operations may start at PaymentOrder because they never
acquire an earlier domain row afterwards.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core import channels, redis_bus
from apps.core.event_resources import deal_resources, payment_resources
from apps.core.business_settings import calculate_offer_economics
from apps.core.financial_locks import lock_payment_order_aggregate
from apps.deals.models import Deal
from apps.parcels.models import DeliveryRequest, ParcelRequest

from . import ledger
from .money import (
    CURRENCY_EXPONENTS,
    clamp,
    convert_eur_cents,
    format_minor,
    format_rate,
    percentage_of,
    require_positive_cents,
)
from .models import (
    GuestPaymentLink,
    LedgerAccount,
    LedgerTransaction,
    PaymentAttempt,
    PaymentOrder,
    PaymentProviderEvent,
    PaymentRefund,
    Payout,
    ScheduledJob,
    TravelerPayoutMethod,
)
from .policy import Phase3Policy, phase3_policy
from .providers import (
    CheckoutRequest,
    ProviderError,
    ProviderEvent,
    ProviderNotConfigured,
    ProviderUnavailable,
    RefundNotSupported,
    RefundRequest,
    available_providers,
    get_gateway,
    resolve_gateway_for_checkout,
)

logger = logging.getLogger(__name__)

GUEST_TOKEN_BYTES = 32

#: After this many failed provider attempts a refund stops being an automatic
#: retry and becomes an operator obligation. The retries continue — the flag is
#: additive — but the row now appears in the manual queue instead of only in a
#: failed ScheduledJob an operator has to think to look at.
REFUND_MANUAL_ESCALATION_ATTEMPTS = 8


# --- errors ------------------------------------------------------------------


class FinanceError(RuntimeError):
    """Base for every V1 financial failure. `code` is the machine contract."""

    code = "finance_error"

    def details(self) -> dict:
        return {}


class NotAuthorized(FinanceError):
    code = "not_authorized"


class OrderNotCollectable(FinanceError):
    code = "order_not_collectable"

    def __init__(self, message: str, *, order_status: str = ""):
        super().__init__(message)
        self.order_status = order_status

    def details(self) -> dict:
        return {"order_status": self.order_status} if self.order_status else {}


class NothingOutstanding(FinanceError):
    code = "nothing_outstanding"


class DepositNotRequired(FinanceError):
    code = "deposit_not_required"


class RequestNotDepositable(FinanceError):
    code = "request_not_depositable"


class GuestLinkInvalid(FinanceError):
    code = "guest_link_invalid"


class RefundNotPermitted(FinanceError):
    code = "refund_not_permitted"


class RefundExceedsCapture(FinanceError):
    code = "refund_exceeds_capture"

    def __init__(
        self,
        message: str,
        *,
        captured: int,
        already_refunded: int,
        reserved_for_payout: int = 0,
    ):
        super().__init__(message)
        self.captured = captured
        self.already_refunded = already_refunded
        self.reserved_for_payout = reserved_for_payout

    def details(self) -> dict:
        detail = {
            "captured_eur_cents": self.captured,
            "already_refunded_eur_cents": self.already_refunded,
        }
        if self.reserved_for_payout:
            detail["reserved_for_payout_eur_cents"] = self.reserved_for_payout
        return detail


class PayoutNotReleasable(FinanceError):
    """Phase 3 has no path to release traveler money. Phase 4 owns the gate."""

    code = "payout_not_releasable"

    def __init__(self, message: str, *, payout_status: str = ""):
        super().__init__(message)
        self.payout_status = payout_status

    def details(self) -> dict:
        return {"payout_status": self.payout_status} if self.payout_status else {}


# --- results -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DepositQuote:
    amount_eur_cents: int
    percent_bps: int
    min_eur_cents: int
    max_eur_cents: int
    estimated_sender_total_eur_cents: int
    clamped: str  # "" | "min" | "max"
    inputs: dict

    def as_dict(self) -> dict:
        return {
            "amount_eur_cents": self.amount_eur_cents,
            "currency": "EUR",
            "percent_bps": self.percent_bps,
            "min_eur_cents": self.min_eur_cents,
            "max_eur_cents": self.max_eur_cents,
            "estimated_sender_total_eur_cents": self.estimated_sender_total_eur_cents,
            "clamped": self.clamped,
        }


@dataclass(frozen=True, slots=True)
class CheckoutSession:
    attempt: PaymentAttempt
    created: bool


@dataclass(frozen=True, slots=True)
class EventOutcome:
    handled: bool
    duplicate: bool
    note: str


# --- helpers -----------------------------------------------------------------


def _publish(channel: str, payload: dict, *, targets: list[int]) -> None:
    redis_bus.publish_after_commit(channel, payload, targets=targets)


def _enqueue_payment_failed_email(
    *, attempt: PaymentAttempt, order: PaymentOrder
) -> None:
    """Arm mail only for a real terminal failure, never expiry/cancellation."""

    if attempt.status != PaymentAttempt.Status.FAILED:
        return
    from apps.notifications.models import OutboundMessage
    from apps.notifications.outbox import enqueue_message

    context = {
        "payment_reference": str(order.public_reference),
        "amount_eur_cents": int(attempt.amount_eur_cents),
        "currency": "EUR",
        "status": "failed",
    }
    enqueue_message(
        kind=OutboundMessage.Kind.PAYMENT_FAILED,
        key=f"payment_failed:attempt:{attempt.pk}:owner",
        to_email=order.owner.email,
        recipient_user_id=order.owner_id,
        deal_id=order.deal_id,
        context=context,
    )
    if attempt.guest_link_id and attempt.guest_email:
        enqueue_message(
            kind=OutboundMessage.Kind.GUEST_PAYMENT,
            key=f"guest_payment:attempt:{attempt.pk}:failed",
            to_email=attempt.guest_email,
            language=attempt.guest_link.communication_language,
            context=context,
        )


def _cancel_payment_failed_emails(*, attempt: PaymentAttempt) -> None:
    """Withdraw retry notices when a provider later proves the payment succeeded."""

    from apps.notifications.outbox import cancel_message

    cancel_message(
        key=f"payment_failed:attempt:{attempt.pk}:owner",
        reason="superseded by authoritative payment success",
    )
    cancel_message(
        key=f"guest_payment:attempt:{attempt.pk}:failed",
        reason="superseded by authoritative payment success",
    )


def _enqueue_guest_payment_receipt(
    *, attempt: PaymentAttempt, order: PaymentOrder
) -> None:
    """Give a guest payer a minimal receipt without making them a Deal party."""

    if not attempt.guest_link_id or not attempt.guest_email:
        return
    from apps.notifications.models import OutboundMessage
    from apps.notifications.outbox import enqueue_message

    enqueue_message(
        kind=OutboundMessage.Kind.GUEST_PAYMENT,
        key=f"guest_payment:attempt:{attempt.pk}:succeeded",
        to_email=attempt.guest_email,
        language=attempt.guest_link.communication_language,
        context={
            "payment_reference": str(order.public_reference),
            "amount_eur_cents": int(attempt.amount_eur_cents),
            "currency": "EUR",
            "status": "succeeded",
        },
    )


def _enqueue_refund_status_email(*, refund: PaymentRefund, status: str) -> None:
    """Notify the account owner and, when applicable, the actual guest payer."""

    from apps.notifications.models import OutboundMessage
    from apps.notifications.outbox import enqueue_message

    order = refund.order
    attempt = refund.attempt
    context = {
        "payment_reference": str(order.public_reference),
        "amount_eur_cents": int(refund.amount_eur_cents),
        "currency": "EUR",
        "status": status,
    }
    enqueue_message(
        kind=OutboundMessage.Kind.REFUND_STATUS,
        key=f"refund_status:refund:{refund.pk}:{status}:owner",
        to_email=order.owner.email,
        recipient_user_id=order.owner_id,
        deal_id=order.deal_id,
        context=context,
    )
    if attempt.guest_link_id and attempt.guest_email:
        enqueue_message(
            kind=OutboundMessage.Kind.REFUND_STATUS,
            key=f"refund_status:refund:{refund.pk}:{status}:guest",
            to_email=attempt.guest_email,
            language=attempt.guest_link.communication_language,
            context=context,
        )


def hash_guest_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _order_for_update(order_id: int) -> PaymentOrder:
    return PaymentOrder.objects.select_for_update(no_key=True).get(pk=order_id)


def _recompute_order_money(order: PaymentOrder, *, at: datetime | None = None) -> None:
    """Derive an order's money columns from its own attempts and refunds.

    Deliberately a recomputation, not an increment. A duplicate provider event
    that reaches this point converges on the same totals, and a crash between
    two writes heals on the next event rather than leaving a permanent drift.

    Attempts and refunds flagged `is_unapplied` are excluded: that money is real
    but was never applied to this obligation (the order was already covered or
    cancelled when it landed), so it is carried on the attempt row and in the
    ledger and refunded separately.
    """

    at = at or timezone.now()
    paid = int(
        PaymentAttempt.objects.filter(
            order=order,
            status=PaymentAttempt.Status.SUCCEEDED,
            is_unapplied=False,
        ).aggregate(total=Sum("amount_eur_cents"))["total"]
        or 0
    )
    refunded = int(
        PaymentRefund.objects.filter(
            order=order,
            status=PaymentRefund.Status.SUCCEEDED,
            attempt__is_unapplied=False,
        ).aggregate(total=Sum("amount_eur_cents"))["total"]
        or 0
    )
    has_pending_refund = PaymentRefund.objects.filter(
        order=order,
        status__in=(
            PaymentRefund.Status.PENDING,
            PaymentRefund.Status.PROCESSING,
        ),
        attempt__is_unapplied=False,
    ).exists()

    order.paid_eur_cents = paid
    order.refunded_eur_cents = min(refunded, paid)

    covered = int(order.credited_eur_cents) + paid >= int(order.amount_eur_cents)
    if order.cancelled_at is not None:
        status = PaymentOrder.Status.CANCELLED
    elif paid > 0 and refunded >= paid:
        status = PaymentOrder.Status.REFUNDED
    elif refunded > 0:
        status = PaymentOrder.Status.PARTIALLY_REFUNDED
    elif has_pending_refund:
        status = PaymentOrder.Status.REFUND_PENDING
    elif covered:
        status = PaymentOrder.Status.PAID
    elif paid > 0 or int(order.credited_eur_cents) > 0:
        status = PaymentOrder.Status.PARTIALLY_PAID
    else:
        status = PaymentOrder.Status.PENDING

    order.status = status
    if status == PaymentOrder.Status.PAID and order.paid_at is None:
        order.paid_at = at
    order.save(
        update_fields=[
            "paid_eur_cents",
            "refunded_eur_cents",
            "status",
            "paid_at",
            "updated_at",
        ]
    )


def _public_base_url() -> str:
    base = getattr(settings, "PAYMENTS_PUBLIC_BASE_URL", "")
    if not base:
        raise ProviderNotConfigured(
            "PAYMENTS_PUBLIC_BASE_URL must be configured to create a checkout."
        )
    return base.rstrip("/")


def _checkout_urls(order: PaymentOrder, provider: str) -> tuple[str, str, str]:
    base = _public_base_url()
    reference = str(order.public_reference)
    return (
        f"{base}/pay/{reference}/return?result=success",
        f"{base}/pay/{reference}/return?result=failure",
        f"{base}/api/payments/webhooks/{provider}",
    )


# --- posting deposit ---------------------------------------------------------


def quote_posting_deposit(
    *,
    delivery_request: DeliveryRequest,
    policy: Phase3Policy | None = None,
) -> DepositQuote:
    """Compute the server-authoritative posting deposit for a request.

    `deposit = clamp(percent_bps of the recommended sender total, min, max)`.

    At posting time no journey is chosen, so there is no matched sub-route to
    price against. The estimate uses the request's own straight-line pickup ->
    delivery distance with no detour and no urgency premium, which is the
    conservative reading: a real matched route is at least this long, so the
    deposit never exceeds a tenth of what the sender will actually owe.

    The whole computation is server-side and its inputs are snapshotted onto the
    order, so a later settings change cannot alter what was charged.
    """

    from apps.matching.pricing import calculate_pricing_quote
    from apps.matching.policy import Phase2Policy
    from apps.routing.geometry import GeoPoint, haversine_meters

    policy = policy or phase3_policy()
    pricing_policy = Phase2Policy.from_settings(policy.settings_version)

    if delivery_request.schema_version >= 3:
        pickup = delivery_request.pickup_place
        dropoff = delivery_request.delivery_place
        estimate_method = "posting_deposit_estimate:canonical_place_great_circle"
    else:
        pickup = delivery_request.pickup_location
        dropoff = delivery_request.delivery_location
        estimate_method = "posting_deposit_estimate:great_circle"
    if pickup is None or dropoff is None:
        raise RequestNotDepositable("A V1 delivery request needs both route endpoints.")
    if (
        pickup.latitude is not None
        and pickup.longitude is not None
        and dropoff.latitude is not None
        and dropoff.longitude is not None
    ):
        straight_line_meters = int(
            haversine_meters(
                GeoPoint(float(pickup.latitude), float(pickup.longitude)),
                GeoPoint(float(dropoff.latitude), float(dropoff.longitude)),
            )
        )
    else:
        # Many authoritative municipal catalogues do not publish centroids.
        # Exact preferred pins are optional operational data, so they must not
        # become a hidden prerequisite or pricing identity. The global pricing
        # floor is the fail-safe posting estimate until a journey is matched.
        straight_line_meters = 0
        estimate_method = "posting_deposit_estimate:canonical_place_floor"
    arrival_estimate = delivery_request.ready_window_end or timezone.now()
    quote = calculate_pricing_quote(
        delivery_request=delivery_request,
        matched_distance_meters=max(0, straight_line_meters),
        matched_distance_method=estimate_method,
        added_distance_meters=0,
        estimated_arrival_at=arrival_estimate,
        policy=pricing_policy,
    )
    economics = calculate_offer_economics(
        quote.recommended_reward_eur_cents, policy.settings_version
    )
    sender_total = int(economics["sender_total_minor"])

    deposit_policy = policy.posting_deposit
    raw = percentage_of(sender_total, bps=deposit_policy.percent_bps)
    amount = clamp(
        raw,
        minimum=deposit_policy.min_eur_cents,
        maximum=deposit_policy.max_eur_cents,
    )
    clamped = ""
    if raw < deposit_policy.min_eur_cents:
        clamped = "min"
    elif raw > deposit_policy.max_eur_cents:
        clamped = "max"

    return DepositQuote(
        amount_eur_cents=amount,
        percent_bps=deposit_policy.percent_bps,
        min_eur_cents=deposit_policy.min_eur_cents,
        max_eur_cents=deposit_policy.max_eur_cents,
        estimated_sender_total_eur_cents=sender_total,
        clamped=clamped,
        inputs={
            "estimate_method": estimate_method,
            "estimate_distance_meters": max(0, straight_line_meters),
            "recommended_reward_eur_cents": quote.recommended_reward_eur_cents,
            "recommended_sender_total_eur_cents": sender_total,
            "raw_percentage_eur_cents": raw,
            "clamped": clamped,
        },
    )


def posting_deposit_quote_from_order(order: PaymentOrder) -> DepositQuote:
    """Rebuild the guidance from the immutable order snapshot, not live policy."""

    snapshot = dict(order.terms_snapshot or {})
    deposit = snapshot.get("payments", {}).get("posting_deposit", {})
    inputs = snapshot.get("posting_deposit_inputs", {})
    try:
        sender_total = int(inputs["recommended_sender_total_eur_cents"])
        percent_bps = int(deposit["percent_bps"])
        minimum = int(deposit["min_eur_cents"])
        maximum = int(deposit["max_eur_cents"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RequestNotDepositable(
            "This deposit order has no reproducible guidance snapshot."
        ) from exc
    return DepositQuote(
        amount_eur_cents=int(order.amount_eur_cents),
        percent_bps=percent_bps,
        min_eur_cents=minimum,
        max_eur_cents=maximum,
        estimated_sender_total_eur_cents=sender_total,
        clamped=str(inputs.get("clamped", "")),
        inputs=dict(inputs),
    )


@transaction.atomic
def ensure_posting_deposit_order(
    *,
    delivery_request: DeliveryRequest,
    policy: Phase3Policy | None = None,
) -> PaymentOrder:
    """Create (or return) the posting-deposit obligation for a request.

    Idempotent: the partial unique index guarantees at most one live deposit
    order per request, so a retried creation returns the existing row rather
    than pricing a second deposit.
    """

    policy = policy or phase3_policy()
    if not policy.deposit_required:
        raise DepositNotRequired(
            "The platform is in after-acceptance payment timing mode."
        )
    if delivery_request.schema_version not in (2, 3):
        raise RequestNotDepositable(
            "Only V1 delivery requests carry a posting deposit."
        )

    existing = (
        PaymentOrder.objects.select_for_update(no_key=True)
        .filter(
            delivery_request_id=delivery_request.pk,
            purpose=PaymentOrder.Purpose.POSTING_DEPOSIT,
        )
        .exclude(status=PaymentOrder.Status.CANCELLED)
        .first()
    )
    if existing is not None:
        return existing

    quote = quote_posting_deposit(delivery_request=delivery_request, policy=policy)
    snapshot = policy.snapshot()
    snapshot["posting_deposit_inputs"] = quote.inputs
    return PaymentOrder.objects.create(
        owner_id=delivery_request.sender_id,
        purpose=PaymentOrder.Purpose.POSTING_DEPOSIT,
        amount_eur_cents=quote.amount_eur_cents,
        delivery_request_id=delivery_request.pk,
        business_settings_version=policy.settings_version,
        terms_snapshot=snapshot,
    )


def _publish_request_after_deposit(order: PaymentOrder, *, at: datetime) -> None:
    """Move a deposited request from awaiting_deposit to open, once.

    Publication is the *effect* of a paid deposit, never a client assertion.
    The scheduled expiry refund is armed in the same transaction, so a request
    can never become publicly discoverable without its refund obligation also
    existing in the database.
    """

    request_row = (
        ParcelRequest.objects.select_for_update(no_key=True)
        .filter(pk=order.delivery_request_id)
        .first()
    )
    if request_row is None:
        return
    if request_row.status != ParcelRequest.Status.AWAITING_DEPOSIT:
        return
    request_row.status = ParcelRequest.Status.OPEN
    request_row.save(update_fields=["status", "updated_at"])

    delivery = DeliveryRequest.objects.filter(pk=order.delivery_request_id).first()
    deadline = getattr(delivery, "deadline_at", None)
    if deadline is not None:
        policy_grace = 0
        snapshot = order.terms_snapshot.get("payments", {})
        deposit_policy = snapshot.get("posting_deposit", {})
        if isinstance(deposit_policy.get("expiry_grace_seconds"), int):
            policy_grace = int(deposit_policy["expiry_grace_seconds"])
        schedule_job(
            kind=ScheduledJob.Kind.DEPOSIT_EXPIRY_REFUND,
            key=f"deposit_expiry_refund:request:{order.delivery_request_id}",
            run_at=deadline + timedelta(seconds=policy_grace),
            payload={"delivery_request_id": order.delivery_request_id},
        )

    _publish(
        channels.PARCEL_CREATED,
        {
            "parcel_id": order.delivery_request_id,
            "sender_id": order.owner_id,
            "status": ParcelRequest.Status.OPEN,
            "reason": "posting_deposit_paid",
        },
        targets=[order.owner_id],
    )


# --- deal balance ------------------------------------------------------------


def create_deal_balance_order(
    *,
    deal: Deal,
    sender_total_eur_cents: int,
    policy: Phase3Policy,
) -> PaymentOrder:
    """Create the accepted Deal's balance obligation and apply any deposit.

    Called inside the acceptance transaction, so the obligation and the Deal
    come into existence together. The deposit credit is applied here and can
    only be applied here: `credit_source` is a one-to-one link, so a second
    attempt to spend the same deposit fails on the unique index rather than
    discounting the balance twice.

    Eligibility for a credit is narrow on purpose — same owner, same delivery
    request, a *paid* deposit order, nothing already refunded, and not yet
    credited anywhere.
    """

    sender_total_eur_cents = require_positive_cents(
        sender_total_eur_cents, name="sender_total_eur_cents"
    )
    order = PaymentOrder.objects.create(
        owner_id=deal.sender_id,
        purpose=PaymentOrder.Purpose.DEAL_BALANCE,
        amount_eur_cents=sender_total_eur_cents,
        deal_id=deal.pk,
        delivery_request_id=deal.delivery_request_id,
        business_settings_version=policy.settings_version,
        terms_snapshot=policy.snapshot(),
    )
    apply_posting_deposit_credit(order=order, deal=deal)
    return order


@transaction.atomic
def apply_posting_deposit_credit(*, order: PaymentOrder, deal: Deal) -> int:
    """Credit an eligible paid posting deposit into a deal balance. Idempotent.

    Atomic in its own right rather than relying on an ambient transaction: it
    takes a row lock on the deposit order, and a service that quietly requires
    its caller to have opened a transaction is a trap for the next caller. When
    it is invoked from inside acceptance the decorator is a savepoint, which is
    also what lets the `IntegrityError` below be caught without poisoning the
    surrounding transaction.
    """

    if order.purpose != PaymentOrder.Purpose.DEAL_BALANCE:
        return 0
    if order.credit_source_id is not None:
        return int(order.credited_eur_cents)

    # "Not already credited anywhere" is expressed as a subquery rather than
    # `credited_into__isnull=True`: the reverse one-to-one lookup forces a LEFT
    # OUTER JOIN, and PostgreSQL refuses `FOR UPDATE` on the nullable side of an
    # outer join. The lock has to hold here, so the join has to go.
    already_credited = PaymentOrder.objects.filter(credit_source__isnull=False).values(
        "credit_source_id"
    )
    deposit = (
        PaymentOrder.objects.select_for_update(no_key=True)
        .filter(
            owner_id=order.owner_id,
            delivery_request_id=order.delivery_request_id,
            purpose=PaymentOrder.Purpose.POSTING_DEPOSIT,
            status=PaymentOrder.Status.PAID,
            refunded_eur_cents=0,
        )
        .exclude(pk__in=already_credited)
        .first()
    )
    if deposit is None:
        return 0

    credit = min(int(deposit.paid_eur_cents), int(order.amount_eur_cents))
    if credit <= 0:
        return 0

    try:
        with transaction.atomic():
            order.credit_source = deposit
            order.credited_eur_cents = credit
            order.save(
                update_fields=["credit_source", "credited_eur_cents", "updated_at"]
            )
    except IntegrityError:
        # Another acceptance claimed the same deposit first. Re-read and take
        # whatever the winner left us: no credit for this order.
        order.refresh_from_db()
        return int(order.credited_eur_cents)

    ledger.record_deposit_credit(
        deposit_order_id=deposit.pk,
        balance_order_id=order.pk,
        owner_id=order.owner_id,
        amount_eur_cents=credit,
        deal_id=deal.pk,
    )
    _recompute_order_money(order)
    if order.status == PaymentOrder.Status.PAID:
        _fund_deal_if_covered(order)
    return credit


def _fund_deal_if_covered(order: PaymentOrder) -> bool:
    """Hand a fully covered balance order to the Deal funding service."""

    if order.purpose != PaymentOrder.Purpose.DEAL_BALANCE or order.deal_id is None:
        return False
    if order.outstanding_eur_cents > 0 or order.cancelled_at is not None:
        return False

    from apps.deals.services import fund_deal

    result = fund_deal(deal_id=order.deal_id, order_id=order.pk)
    if result.changed:
        terms = result.terms
        ledger.record_deal_funding(
            deal_id=order.deal_id,
            order_id=order.pk,
            traveler_id=result.traveler_id,
            traveler_reward_eur_cents=int(terms["traveler_reward_minor"]),
            platform_fee_eur_cents=int(terms["platform_fee_minor"]),
        )
        from apps.boosts.models import BoostPurchase

        for boost in BoostPurchase.objects.filter(deal_id=order.deal_id).order_by("pk"):
            ledger.record_boost_allocation(
                deal_id=order.deal_id,
                order_id=boost.payment_order_id,
                purchase_id=boost.pk,
                traveler_id=result.traveler_id,
                traveler_boost_eur_cents=int(boost.traveler_boost_eur_cents),
                platform_boost_eur_cents=int(boost.platform_boost_eur_cents),
            )
        ensure_payout_for_deal(
            deal_id=order.deal_id,
            traveler_id=result.traveler_id,
            amount_eur_cents=int(terms["traveler_total_minor"]),
            funding_provider=_funding_provider(order),
            query_provider_capability=False,
        )
    return result.changed


def _activate_boost_if_paid(order: PaymentOrder) -> bool:
    """Hand a covered boost order to the boost domain. Idempotent.

    Late import so `apps.finance` keeps no import-time dependency on
    `apps.boosts`, exactly as `_fund_deal_if_covered` does for `apps.deals`.
    The boost row was locked with the request graph before this order, so the
    ordering is the canonical one.
    """

    if order.status != PaymentOrder.Status.PAID:
        return False
    from apps.boosts.services import activate_paid_boost

    return activate_paid_boost(order_id=order.pk)


def _funding_provider(order: PaymentOrder) -> str:
    attempt = (
        PaymentAttempt.objects.filter(
            order=order,
            status=PaymentAttempt.Status.SUCCEEDED,
            is_unapplied=False,
        )
        .order_by("-succeeded_at", "-id")
        .first()
    )
    return attempt.provider if attempt is not None else ""


# --- checkout ----------------------------------------------------------------


def settlement_amounts(
    *,
    payment_currency: str,
    amount_eur_cents: int,
    policy: Phase3Policy,
) -> dict:
    """What one rail would collect for a canonical EUR obligation.

    **The settlement currency is the rail's, not the payer's.** It arrives here
    from `gateway.payment_currency` and nowhere else; the checkout contract
    refuses a request that so much as names a currency. There is therefore no
    Stripe-in-dinars and no Chargily-in-euros to construct, from a client or
    from an admin screen.

    Shared by `_resolve_amounts` — which freezes the result onto an attempt —
    and by the availability preview the payment screen renders. One function so
    the figure a payer is shown and the figure a provider is charged cannot
    drift apart.
    """

    payment_currency = payment_currency.upper()
    if payment_currency == "EUR":
        return {
            "amount_eur_cents": amount_eur_cents,
            "payment_currency": "EUR",
            "provider_amount_minor": amount_eur_cents,
            "provider_amount_exponent": CURRENCY_EXPONENTS["EUR"],
            "fx_rate_micros": None,
            "fx_source": "",
            "fx_settings_version": None,
        }

    if payment_currency != "DZD":
        raise ProviderError(
            f"No configured FX policy for {payment_currency}.",
            provider_code="unsupported_currency",
        )
    rate_micros = policy.chargily.eur_dzd_rate_micros
    provider_amount = convert_eur_cents(
        amount_eur_cents, to_currency="DZD", rate_micros=rate_micros
    )
    if provider_amount < policy.chargily.min_amount_dzd:
        raise ProviderError(
            "The converted amount is below the provider's minimum charge.",
            provider_code="amount_below_provider_minimum",
        )
    return {
        "amount_eur_cents": amount_eur_cents,
        "payment_currency": "DZD",
        "provider_amount_minor": provider_amount,
        "provider_amount_exponent": CURRENCY_EXPONENTS["DZD"],
        "fx_rate_micros": rate_micros,
        "fx_source": (
            f"business_settings_v{policy.settings_version.version}"
            ".payments.chargily.eur_dzd_rate_micros"
        ),
        "fx_settings_version": policy.settings_version,
    }


def provider_options(
    policy: Phase3Policy,
    *,
    amount_eur_cents: int | None = None,
    guest_only: bool = False,
) -> list[dict]:
    """The payer-facing rail list, with what each rail would actually charge.

    One list, one authority. The client picks a rail from this and renders the
    figures in it; it does not know that Stripe means euros, does not convert
    anything, and has no currency of its own to offer. That is the whole repair
    for a screen that read as "choose a payment method, then choose a currency"
    — a combination like Stripe-in-dinars was never orderable, and now it is not
    presentable either.

    `amount_eur_cents` is optional because the standalone providers endpoint has
    no obligation in hand. With it, each row carries a settlement preview.

    The preview is **indicative**. A Chargily row shows today's admin rate; the
    rate that binds is snapshotted onto the PaymentAttempt when the checkout is
    created, and changing the admin setting afterwards does not move it.
    """

    rows: list[dict] = []
    for item in available_providers(policy, guest_only=guest_only):
        row = item.as_dict()
        if amount_eur_cents is not None and amount_eur_cents > 0:
            row.update(
                _settlement_preview(
                    item=item, amount_eur_cents=amount_eur_cents, policy=policy
                )
            )
        rows.append(row)
    return rows


def _settlement_preview(*, item, amount_eur_cents: int, policy: Phase3Policy) -> dict:
    """One rail's charge for one obligation, or why it cannot take it."""

    preview: dict = {
        "canonical_currency": "EUR",
        "canonical_amount_eur_cents": amount_eur_cents,
        "settlement_currency": item.payment_currency,
    }
    if not item.payment_currency:
        return preview
    try:
        amounts = settlement_amounts(
            payment_currency=item.payment_currency,
            amount_eur_cents=amount_eur_cents,
            policy=policy,
        )
    except ProviderError as exc:
        # A rail that cannot take *this* amount — a dinar total under
        # Chargily's floor — is unavailable for this obligation specifically.
        # Showing it as tappable and failing at the tap is the behaviour this
        # phase exists to remove.
        preview["available"] = False
        # Only when nothing else was already wrong: a rail that is switched off
        # *and* below its floor should still say it is switched off, which is
        # the fact an operator acts on.
        if item.available:
            preview["unavailable_reason"] = exc.provider_code or exc.code
        return preview
    preview.update(
        {
            "settlement_amount_minor": amounts["provider_amount_minor"],
            "settlement_amount_exponent": amounts["provider_amount_exponent"],
            "settlement_amount": format_minor(
                amounts["provider_amount_minor"],
                exponent=amounts["provider_amount_exponent"],
            ),
        }
    )
    if amounts["fx_rate_micros"]:
        preview.update(
            {
                "fx_rate_micros": amounts["fx_rate_micros"],
                "eur_dzd_rate": format_rate(amounts["fx_rate_micros"]),
                "rate_settings_version": policy.settings_version.version,
                # The rate on this row is today's. The binding one is frozen
                # onto the attempt at checkout creation.
                "rate_is_indicative": True,
            }
        )
    return preview


def _resolve_amounts(
    *,
    order: PaymentOrder,
    gateway,
    policy: Phase3Policy,
) -> dict:
    """Decide what this attempt collects, in canonical and provider units.

    The canonical figure is the order's outstanding EUR. Any conversion is done
    from the versioned admin rate and then frozen onto the attempt: the provider
    is told an amount, never a rate, and the rate that was used is reproducible
    from the attempt row alone forever after.

    The currency comes from `gateway.payment_currency` — the rail decides what
    it settles in. No caller passes one, and none may.
    """

    outstanding = order.outstanding_eur_cents
    if outstanding <= 0:
        raise NothingOutstanding("This order has nothing left to collect.")
    return settlement_amounts(
        payment_currency=gateway.payment_currency,
        amount_eur_cents=outstanding,
        policy=policy,
    )


def start_checkout(
    *,
    order_id: int,
    provider: str,
    actor_id: int | None,
    guest_link: GuestPaymentLink | None = None,
    policy: Phase3Policy | None = None,
    guest_email: str = "",
) -> CheckoutSession:
    """Open a hosted checkout for an order.

    The provider call happens outside the database transaction on purpose: an
    external HTTP round trip must never be holding a row lock on a financial
    obligation. The attempt row is written first so its id is the stable
    idempotency key we hand the provider, which is what makes a retried
    checkout reuse the provider's own session instead of creating a second one.
    """

    policy = policy or phase3_policy()
    gateway = resolve_gateway_for_checkout(
        policy, provider, guest=guest_link is not None
    )
    now = timezone.now()

    with transaction.atomic():
        order = _order_for_update(order_id)
        if not order.is_collectable:
            raise OrderNotCollectable(
                "This obligation is no longer collecting payment.",
                order_status=order.status,
            )
        if order.outstanding_eur_cents <= 0:
            raise NothingOutstanding("This order has nothing left to collect.")

        amounts = _resolve_amounts(order=order, gateway=gateway, policy=policy)
        from .payout_snapshots import preflight

        preflight(order=order, provider=provider, policy=policy)

        open_attempt = (
            PaymentAttempt.objects.select_for_update(no_key=True)
            .filter(order=order, status__in=PaymentAttempt.OPEN_STATUSES)
            .first()
        )
        if open_attempt is not None:
            same_rail = open_attempt.provider == provider
            same_amount = (
                int(open_attempt.amount_eur_cents) == amounts["amount_eur_cents"]
            )
            same_payer = (
                open_attempt.payer_id == actor_id
                and open_attempt.guest_link_id
                == (guest_link.pk if guest_link is not None else None)
            )
            still_valid = (
                open_attempt.expires_at is None or open_attempt.expires_at > now
            )
            if (
                same_rail
                and same_amount
                and same_payer
                and still_valid
                and open_attempt.checkout_url
            ):
                if guest_link is not None and open_attempt.guest_email != guest_email:
                    open_attempt.guest_email = guest_email[:254]
                    open_attempt.save(update_fields=["guest_email", "updated_at"])
                return CheckoutSession(attempt=open_attempt, created=False)
            # Switching rail, amount or a stale session: close the old attempt
            # so the one-open-attempt-per-order invariant holds and two live
            # checkouts can never race to fund the same obligation.
            open_attempt.status = PaymentAttempt.Status.CANCELLED
            open_attempt.failure_code = "superseded"
            open_attempt.save(update_fields=["status", "failure_code", "updated_at"])

        attempt = PaymentAttempt.objects.create(
            order=order,
            provider=provider,
            provider_mode=gateway.credential_mode()
            if gateway.credential_mode() in ("test", "live")
            else "legacy_unknown",
            mode_evidence="checkout_credential_mode",
            payer_id=actor_id,
            guest_link=guest_link,
            guest_email=guest_email[:254],
            amount_eur_cents=amounts["amount_eur_cents"],
            payment_currency=amounts["payment_currency"],
            provider_amount_minor=amounts["provider_amount_minor"],
            provider_amount_exponent=amounts["provider_amount_exponent"],
            fx_rate_micros=amounts["fx_rate_micros"],
            fx_source=amounts["fx_source"],
            fx_settings_version=amounts["fx_settings_version"],
            fx_snapshot_at=now if amounts["fx_rate_micros"] else None,
            idempotency_key=f"shiptrip-order-{order.pk}-{secrets.token_hex(8)}",
            status=PaymentAttempt.Status.CREATED,
            expires_at=now + timedelta(seconds=policy.attempt_ttl_seconds),
        )
        schedule_job(
            kind=ScheduledJob.Kind.ATTEMPT_EXPIRY,
            key=f"attempt_expiry:{attempt.pk}",
            run_at=attempt.expires_at or (timezone.now() + timedelta(hours=1)),
            payload={"attempt_id": attempt.pk},
        )
        schedule_job(
            kind=ScheduledJob.Kind.PROVIDER_RECONCILE,
            key=f"provider_reconcile:{attempt.pk}",
            run_at=(attempt.expires_at or timezone.now()) + timedelta(minutes=5),
            payload={"attempt_id": attempt.pk},
            max_attempts=32,
        )

    success_url, failure_url, webhook_url = _checkout_urls(order, provider)
    checkout_request = CheckoutRequest(
        reference=str(order.public_reference),
        amount_minor=attempt.provider_amount_minor,
        currency=attempt.payment_currency,
        amount_exponent=attempt.provider_amount_exponent,
        idempotency_key=attempt.idempotency_key,
        success_url=success_url,
        failure_url=failure_url,
        webhook_url=webhook_url,
        description=_checkout_description(order),
        metadata={
            "order_reference": str(order.public_reference),
            "attempt_id": str(attempt.pk),
            "purpose": order.purpose,
        },
        customer_email=guest_email,
    )

    try:
        result = gateway.create_checkout(checkout_request)
    except ProviderError as exc:
        with transaction.atomic():
            failed = PaymentAttempt.objects.select_for_update(no_key=True).get(
                pk=attempt.pk
            )
            failed.status = PaymentAttempt.Status.FAILED
            failed.failure_code = exc.code
            failed.failure_message = str(exc)[:255]
            failed.save(
                update_fields=[
                    "status",
                    "failure_code",
                    "failure_message",
                    "updated_at",
                ]
            )
            _enqueue_payment_failed_email(attempt=failed, order=order)
        logger.warning(
            "finance.checkout_failed order=%s provider=%s code=%s",
            order_id,
            provider,
            exc.code,
        )
        raise

    with transaction.atomic():
        stored = PaymentAttempt.objects.select_for_update(no_key=True).get(
            pk=attempt.pk
        )
        if stored.status == PaymentAttempt.Status.CREATED:
            stored.provider_session_id = result.provider_session_id
            stored.checkout_url = result.checkout_url
            stored.status = PaymentAttempt.Status.CHECKOUT_PENDING
            stored.save(
                update_fields=[
                    "provider_session_id",
                    "checkout_url",
                    "status",
                    "updated_at",
                ]
            )
        schedule_job(
            kind=ScheduledJob.Kind.ATTEMPT_EXPIRY,
            key=f"attempt_expiry:{stored.pk}",
            run_at=stored.expires_at or (timezone.now() + timedelta(hours=1)),
            payload={"attempt_id": stored.pk},
        )
        # Safety net for a webhook that never arrives: poll the provider a
        # little after the checkout should have resolved.
        schedule_job(
            kind=ScheduledJob.Kind.PROVIDER_RECONCILE,
            key=f"provider_reconcile:{stored.pk}",
            run_at=(stored.expires_at or timezone.now()) + timedelta(minutes=5),
            payload={"attempt_id": stored.pk},
            max_attempts=32,
        )
    return CheckoutSession(attempt=stored, created=True)


def recover_checkout_attempt(*, attempt_id: int) -> str:
    """Recover a checkout created remotely before its handle committed locally.

    Repeating create with the attempt's stable provider idempotency key returns
    the same provider-side checkout. The network call occurs before the short
    transaction that stores the recovered handle.
    """

    attempt = PaymentAttempt.objects.select_related("order").get(pk=attempt_id)
    if attempt.provider_session_id:
        return "checkout_handle_present"
    order = attempt.order
    success_url, failure_url, webhook_url = _checkout_urls(order, attempt.provider)
    gateway = get_gateway(attempt.provider)
    result = gateway.create_checkout(
        CheckoutRequest(
            reference=str(order.public_reference),
            amount_minor=attempt.provider_amount_minor,
            currency=attempt.payment_currency,
            amount_exponent=attempt.provider_amount_exponent,
            idempotency_key=attempt.idempotency_key,
            success_url=success_url,
            failure_url=failure_url,
            webhook_url=webhook_url,
            description=_checkout_description(order),
            metadata={
                "order_reference": str(order.public_reference),
                "attempt_id": str(attempt.pk),
                "purpose": order.purpose,
            },
            customer_email=attempt.guest_email,
        )
    )
    with transaction.atomic():
        row = PaymentAttempt.objects.select_for_update(no_key=True).get(pk=attempt_id)
        if not row.provider_session_id:
            row.provider_session_id = result.provider_session_id
            row.checkout_url = result.checkout_url
            update_fields = ["provider_session_id", "checkout_url", "updated_at"]
            if row.status == PaymentAttempt.Status.CREATED:
                row.status = PaymentAttempt.Status.CHECKOUT_PENDING
                update_fields.append("status")
            row.save(update_fields=update_fields)
    return "checkout_handle_recovered"


def _checkout_description(order: PaymentOrder) -> str:
    """A description safe to show a guest and safe to send to a provider.

    Deliberately generic: it names the platform and the kind of payment and
    nothing about the parcel, the route, the recipient or the counterparty.
    """

    labels = {
        PaymentOrder.Purpose.POSTING_DEPOSIT: "ShipTrip posting deposit",
        PaymentOrder.Purpose.DEAL_BALANCE: "ShipTrip delivery payment",
        PaymentOrder.Purpose.BOOST: "ShipTrip listing boost",
    }
    return labels.get(order.purpose, "ShipTrip payment")


# --- provider event reconciliation -------------------------------------------


def apply_provider_event(event) -> EventOutcome:
    """Persist a verified event, then apply it through recoverable state.

    Receipt and successful application are deliberately different facts. The
    event and its recovery job commit first. If economic reconciliation fails,
    the event becomes retryable and the same provider event (or the durable
    job) may re-drive it. Provider uniqueness prevents duplicate effects; it no
    longer suppresses recovery.
    """

    record, duplicate, fingerprint_matches = _persist_provider_event(event)
    if not fingerprint_matches:
        return EventOutcome(
            handled=True,
            duplicate=True,
            note="event_id_payload_mismatch",
        )
    if record.processing_result in (
        PaymentProviderEvent.ProcessingResult.APPLIED,
        PaymentProviderEvent.ProcessingResult.IGNORED,
    ):
        return EventOutcome(handled=True, duplicate=True, note="duplicate_event")

    # Re-arm the durable job *before* trying inline. A redelivery of an event
    # whose recovery job had already exhausted its attempts would otherwise
    # depend entirely on this process surviving: if it is killed between here
    # and `_mark_event_retryable`, the job stays FAILED and nothing re-drives
    # the event. Re-arming first means the obligation is live in the database
    # even if this process never returns.
    _schedule_event_processing(record.pk, run_at=timezone.now())

    try:
        note = process_provider_event(event_id=record.pk)
    except Exception as exc:  # noqa: BLE001 - durable state owns the retry
        _mark_event_retryable(record.pk, exc)
        logger.exception(
            "finance.provider_event_retry_scheduled provider=%s event=%s",
            event.provider,
            event.event_id,
        )
        return EventOutcome(
            handled=True,
            duplicate=duplicate,
            note="retry_scheduled",
        )
    return EventOutcome(handled=True, duplicate=duplicate, note=note)


def _normalized_provider_event(event) -> dict:
    """Safe fields sufficient to replay reconciliation after a process crash."""

    return {
        "outcome": event.outcome,
        "provider_session_id": event.provider_session_id,
        "provider_payment_id": event.provider_payment_id,
        "reference": event.reference,
        "amount_minor": event.amount_minor,
        "currency": event.currency,
        "guest_email": event.guest_email,
        "failure_code": event.failure_code,
    }


def _provider_event_fingerprint(event, normalized: dict) -> str:
    canonical = json.dumps(
        {
            "provider": event.provider,
            "provider_event_id": event.event_id,
            "event_type": event.event_type,
            "normalized": normalized,
            "safe_payload": event.payload,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _persist_provider_event(event) -> tuple[PaymentProviderEvent, bool, bool]:
    attempt = _match_attempt(event)
    live_flag = (
        event.payload.get("livemode") if isinstance(event.payload, dict) else None
    )
    event_mode = (
        ("live" if live_flag else "test")
        if type(live_flag) is bool
        else "legacy_unknown"
    )
    normalized = _normalized_provider_event(event)
    fingerprint = _provider_event_fingerprint(event, normalized)
    # Which provider object this event was about, so a payout-domain event can
    # be correlated without re-reading the payload. Opaque ids only.
    payload_object = (event.payload or {}).get("data") or {}
    payload_object = payload_object.get("object") or {}
    payload_object = payload_object if isinstance(payload_object, dict) else {}
    duplicate = False
    try:
        with transaction.atomic():
            record = PaymentProviderEvent.objects.create(
                provider=event.provider,
                provider_event_id=event.event_id,
                provider_mode=event_mode,
                event_type=event.event_type,
                object_type=str(payload_object.get("object") or "")[:64],
                object_id=str(payload_object.get("id") or "")[:255],
                attempt=attempt,
                order=attempt.order if attempt else None,
                signature_verified=True,
                payload=event.payload,
                payload_fingerprint=fingerprint,
                normalized_event=normalized,
            )
            schedule_job(
                kind=ScheduledJob.Kind.PROVIDER_EVENT_PROCESS,
                key=f"provider_event_process:{record.pk}",
                run_at=timezone.now(),
                payload={"event_id": record.pk},
                max_attempts=32,
            )
    except IntegrityError:
        duplicate = True
        record = PaymentProviderEvent.objects.get(
            provider=event.provider,
            provider_event_id=event.event_id,
        )
        logger.info(
            "finance.duplicate_provider_event provider=%s event=%s state=%s",
            event.provider,
            event.event_id,
            record.processing_result,
        )

    fingerprint_matches = not record.payload_fingerprint or (
        record.payload_fingerprint == fingerprint
    )
    if not fingerprint_matches:
        PaymentProviderEvent.objects.filter(pk=record.pk).exclude(
            processing_result__in=(
                PaymentProviderEvent.ProcessingResult.APPLIED,
                PaymentProviderEvent.ProcessingResult.IGNORED,
            )
        ).update(
            processing_result=PaymentProviderEvent.ProcessingResult.FAILED,
            last_error_code="event_id_payload_mismatch",
            last_error_message=(
                "The provider reused an event id with a different safe payload."
            ),
            processed_at=timezone.now(),
        )
    return record, duplicate, fingerprint_matches


def _provider_event_from_record(record: PaymentProviderEvent) -> ProviderEvent:
    data = dict(record.normalized_event or {})
    return ProviderEvent(
        provider=record.provider,
        event_id=record.provider_event_id,
        event_type=record.event_type,
        outcome=str(data.get("outcome") or "ignored"),
        provider_session_id=str(data.get("provider_session_id") or ""),
        provider_payment_id=str(data.get("provider_payment_id") or ""),
        reference=str(data.get("reference") or ""),
        amount_minor=data.get("amount_minor"),
        currency=str(data.get("currency") or ""),
        guest_email=str(data.get("guest_email") or ""),
        failure_code=str(data.get("failure_code") or ""),
        payload=dict(record.payload or {}),
    )


def process_provider_event(*, event_id: int) -> str:
    """Apply one durable event at least once; every economic effect is idempotent."""

    with transaction.atomic():
        record = PaymentProviderEvent.objects.select_for_update(no_key=True).get(
            pk=event_id
        )
        if record.processing_result in (
            PaymentProviderEvent.ProcessingResult.APPLIED,
            PaymentProviderEvent.ProcessingResult.IGNORED,
        ):
            return f"event_{record.processing_result}"
        record.processing_result = PaymentProviderEvent.ProcessingResult.PROCESSING
        record.processing_attempts = int(record.processing_attempts) + 1
        record.processing_started_at = timezone.now()
        record.next_retry_at = None
        record.save(
            update_fields=[
                "processing_result",
                "processing_attempts",
                "processing_started_at",
                "next_retry_at",
            ]
        )

    from .payout_provider_events import PLATFORM_PAYOUT_EVENTS, handle_platform_event

    if record.event_type in PLATFORM_PAYOUT_EVENTS:
        # Transfers, refunds, disputes and platform liquidity. These are payout
        # domain facts, not checkout attempts, so they never reach
        # `reconcile_attempt` and can never be matched against an order.
        note = handle_platform_event(record)
        # An event that was deliberately not acted on is `ignored`, not
        # `applied`. The distinction is what an operator reads when asking
        # whether a wrong-mode or unrecognised object had any effect.
        result = (
            PaymentProviderEvent.ProcessingResult.IGNORED
            if note
            in (
                "mode_isolated",
                "event_not_subscribed",
                "unknown_transfer",
                "unknown_refund_source",
                "known_refund",
                "external_refund_not_settled",
                "transfer_id_missing",
                "refund_id_missing",
                "dispute_id_missing",
            )
            else PaymentProviderEvent.ProcessingResult.APPLIED
        )
        _finish_event(record.pk, result, note)
        return note

    durable_event = _provider_event_from_record(record)
    attempt = record.attempt or _match_attempt(durable_event)
    if attempt is None:
        if durable_event.outcome == "ignored":
            _finish_event(
                record.pk,
                PaymentProviderEvent.ProcessingResult.IGNORED,
                "no_op_event",
            )
            return "no_op_event"
        raise FinanceError("A money-moving provider event has no matching attempt.")

    if record.attempt_id != attempt.pk:
        PaymentProviderEvent.objects.filter(pk=record.pk).update(
            attempt=attempt,
            order_id=attempt.order_id,
        )
    if (
        record.provider_mode in ("test", "live")
        and attempt.provider_mode in ("test", "live")
        and record.provider_mode != attempt.provider_mode
    ):
        _finish_event(
            record.pk,
            PaymentProviderEvent.ProcessingResult.IGNORED,
            "provider_mode_mismatch",
        )
        return "provider_mode_mismatch"
    if durable_event.outcome == "ignored":
        _finish_event(
            record.pk,
            PaymentProviderEvent.ProcessingResult.IGNORED,
            "no_op_event",
        )
        return "no_op_event"

    note = reconcile_attempt(
        attempt_id=attempt.pk,
        outcome=durable_event.outcome,
        provider_payment_id=durable_event.provider_payment_id,
        provider_amount_minor=durable_event.amount_minor,
        provider_currency=durable_event.currency,
        guest_email=durable_event.guest_email,
        failure_code=durable_event.failure_code,
    )
    _finish_event(record.pk, PaymentProviderEvent.ProcessingResult.APPLIED, note)
    return note


def _reference_uuid(reference) -> uuid.UUID | None:
    """Read a provider-echoed reference as an order reference, or as nothing.

    `client_reference_id` is free text the provider hands back verbatim, and
    anything able to open a Checkout Session on this account chooses it. Our
    own references are UUIDs, so a value that is not one cannot name an order.
    Passing it to a `UUIDField` lookup raises `ValidationError` out of the
    webhook view, which answers 500 and asks the provider to redeliver the same
    poisoned event forever. Refusing it here keeps one malformed reference from
    wedging the whole endpoint for every other event behind it.
    """

    if not reference:
        return None
    try:
        return uuid.UUID(str(reference))
    except (AttributeError, TypeError, ValueError):
        return None


def _match_attempt(event) -> PaymentAttempt | None:
    queryset = PaymentAttempt.objects.select_related("order")
    if event.provider_session_id:
        found = queryset.filter(
            provider=event.provider, provider_session_id=event.provider_session_id
        ).first()
        if found is not None:
            return found
    if event.provider_payment_id:
        found = queryset.filter(
            provider=event.provider, provider_payment_id=event.provider_payment_id
        ).first()
        if found is not None:
            return found
    reference = _reference_uuid(event.reference)
    if reference is not None:
        # The provider echoed our order reference. This fallback exists for one
        # case only: an event that arrives before we managed to store the
        # session id. It is therefore restricted to an attempt that has no
        # session id yet, so a late event can never be bound to the wrong
        # attempt on an order that has several.
        order = PaymentOrder.objects.filter(public_reference=reference).first()
        if order is not None:
            return (
                queryset.filter(
                    order=order, provider=event.provider, provider_session_id=""
                )
                .order_by("-created_at")
                .first()
            )
    return None


def _finish_event(event_id: int, result: str, note: str) -> None:
    PaymentProviderEvent.objects.filter(pk=event_id).update(
        processing_result=result,
        processing_note=note[:255],
        last_error_code="",
        last_error_message="",
        next_retry_at=None,
        processed_at=timezone.now(),
    )
    ScheduledJob.objects.filter(
        key=f"provider_event_process:{event_id}",
        status__in=(ScheduledJob.Status.PENDING, ScheduledJob.Status.RUNNING),
    ).update(
        status=ScheduledJob.Status.SUCCEEDED,
        last_result=note[:255],
        last_error="",
        locked_at=None,
        locked_by="",
        completed_at=timezone.now(),
        updated_at=timezone.now(),
    )


def _schedule_event_processing(event_id: int, *, run_at: datetime) -> None:
    """Ensure a live durable obligation to finish applying one event."""

    schedule_job(
        kind=ScheduledJob.Kind.PROVIDER_EVENT_PROCESS,
        key=f"provider_event_process:{event_id}",
        run_at=run_at,
        payload={"event_id": event_id},
        max_attempts=32,
        reactivate_failed=True,
    )


def _mark_event_retryable(event_id: int, exc: Exception) -> None:
    record = PaymentProviderEvent.objects.filter(pk=event_id).first()
    if record is None or record.processing_result in (
        PaymentProviderEvent.ProcessingResult.APPLIED,
        PaymentProviderEvent.ProcessingResult.IGNORED,
    ):
        return
    attempts = max(1, int(record.processing_attempts))
    retry_at = timezone.now() + timedelta(
        seconds=min(60 * (2 ** max(0, attempts - 1)), 6 * 3_600)
    )
    PaymentProviderEvent.objects.filter(pk=event_id).exclude(
        processing_result__in=(
            PaymentProviderEvent.ProcessingResult.APPLIED,
            PaymentProviderEvent.ProcessingResult.IGNORED,
        )
    ).update(
        processing_result=PaymentProviderEvent.ProcessingResult.RETRYABLE,
        last_error_code=type(exc).__name__[:64],
        last_error_message=str(exc)[:500],
        next_retry_at=retry_at,
        processed_at=None,
    )
    _schedule_event_processing(event_id, run_at=retry_at)


@transaction.atomic
def reconcile_attempt(
    *,
    attempt_id: int,
    outcome: str,
    provider_payment_id: str = "",
    provider_amount_minor: int | None = None,
    provider_currency: str = "",
    guest_email: str = "",
    failure_code: str = "",
) -> str:
    """Move one attempt to a terminal state and reconcile its order.

    Amount and currency are verified against what the server asked for. A
    success whose provider amount does not match the attempt is not applied:
    that is either a tampered redirect-driven forgery or a provider-side
    mismatch, and in both cases silently funding a Deal would be the wrong
    answer.
    """

    # Read only immutable foreign keys first, then acquire the complete domain
    # aggregate before finance rows. This is the global cross-domain order used
    # by grace expiry, Deal cancellation, request cancellation and payment.
    order_id = PaymentAttempt.objects.values_list("order_id", flat=True).get(
        pk=attempt_id
    )
    locked = lock_payment_order_aggregate(order_id)
    order = locked.order
    attempt = PaymentAttempt.objects.select_for_update(no_key=True).get(pk=attempt_id)

    if attempt.guest_link_id and guest_email and attempt.guest_email != guest_email:
        attempt.guest_email = guest_email[:254]
        attempt.save(update_fields=["guest_email", "updated_at"])

    if outcome == "processing":
        # A delayed payment method has been authorised but has not settled. The
        # attempt stays open and no money moves; the provider will follow with a
        # success or a failure.
        if attempt.status in PaymentAttempt.TERMINAL_STATUSES:
            return "already_terminal"
        if attempt.status != PaymentAttempt.Status.PROCESSING:
            attempt.status = PaymentAttempt.Status.PROCESSING
            attempt.save(update_fields=["status", "updated_at"])
        return "attempt_processing"

    if attempt.status in PaymentAttempt.TERMINAL_STATUSES:
        if attempt.status == PaymentAttempt.Status.SUCCEEDED:
            # A late duplicate success. Recompute rather than re-apply so the
            # totals converge instead of doubling.
            _recompute_order_money(order)
            return "already_succeeded"
        if outcome != "succeeded":
            return "already_terminal"
        # A success arriving after we locally expired or cancelled the attempt
        # is still real money. Fall through and apply it, possibly unapplied.

    if outcome != "succeeded":
        attempt.status = {
            "failed": PaymentAttempt.Status.FAILED,
            "expired": PaymentAttempt.Status.EXPIRED,
            "cancelled": PaymentAttempt.Status.CANCELLED,
        }.get(outcome, PaymentAttempt.Status.FAILED)
        attempt.failure_code = (failure_code or outcome)[:64]
        attempt.save(update_fields=["status", "failure_code", "updated_at"])
        _recompute_order_money(order)
        _enqueue_payment_failed_email(attempt=attempt, order=order)
        # An attempt that ended without money travels on `payment.failed`.
        # Announcing a failure on `payment.captured` would let a client render
        # success for a payment that never happened.
        _publish(
            channels.PAYMENT_FAILED,
            {
                **payment_resources(order),
                "order_reference": str(order.public_reference),
                "attempt_id": attempt.pk,
                "status": attempt.status,
                "failure_code": attempt.failure_code,
                "purpose": order.purpose,
            },
            targets=[order.owner_id],
        )
        return f"attempt_{attempt.status}"

    # A success has to state what was charged. Applying an unverifiable amount
    # would mean trusting the outcome label alone, which is exactly the
    # tampering surface the amount check exists to close.
    if provider_amount_minor is None:
        attempt.status = PaymentAttempt.Status.FAILED
        attempt.failure_code = "amount_unverifiable"
        attempt.failure_message = "The provider reported no amount for a success."
        attempt.save(
            update_fields=["status", "failure_code", "failure_message", "updated_at"]
        )
        _enqueue_payment_failed_email(attempt=attempt, order=order)
        logger.error(
            "finance.amount_unverifiable attempt=%s provider=%s",
            attempt.pk,
            attempt.provider,
        )
        return "amount_unverifiable"
    if provider_amount_minor is not None:
        expected = int(attempt.provider_amount_minor)
        if int(provider_amount_minor) != expected:
            attempt.status = PaymentAttempt.Status.FAILED
            attempt.failure_code = "amount_mismatch"
            attempt.failure_message = (
                f"Provider reported {provider_amount_minor}, expected {expected}."
            )[:255]
            attempt.save(
                update_fields=[
                    "status",
                    "failure_code",
                    "failure_message",
                    "updated_at",
                ]
            )
            _enqueue_payment_failed_email(attempt=attempt, order=order)
            logger.error(
                "finance.amount_mismatch attempt=%s provider=%s",
                attempt.pk,
                attempt.provider,
            )
            return "amount_mismatch"
    if provider_currency and provider_currency.upper() != attempt.payment_currency:
        attempt.status = PaymentAttempt.Status.FAILED
        attempt.failure_code = "currency_mismatch"
        attempt.save(update_fields=["status", "failure_code", "updated_at"])
        _enqueue_payment_failed_email(attempt=attempt, order=order)
        logger.error(
            "finance.currency_mismatch attempt=%s provider=%s",
            attempt.pk,
            attempt.provider,
        )
        return "currency_mismatch"

    now = timezone.now()
    # Money that the obligation cannot absorb is recorded honestly and refunded,
    # never quietly dropped and never allowed to fund anything twice.
    absorbable = order.cancelled_at is None and order.outstanding_eur_cents >= int(
        attempt.amount_eur_cents
    )
    attempt.status = PaymentAttempt.Status.SUCCEEDED
    attempt.succeeded_at = now
    attempt.is_unapplied = not absorbable
    if provider_payment_id:
        attempt.provider_payment_id = provider_payment_id[:255]
    if guest_email:
        attempt.guest_email = guest_email[:254]
    attempt.save(
        update_fields=[
            "status",
            "succeeded_at",
            "is_unapplied",
            "provider_payment_id",
            "guest_email",
            "updated_at",
        ]
    )
    _cancel_payment_failed_emails(attempt=attempt)

    ledger.record_customer_payment(
        attempt_id=attempt.pk,
        order_id=order.pk,
        owner_id=order.owner_id,
        amount_eur_cents=int(attempt.amount_eur_cents),
        purpose=order.purpose,
        deal_id=order.deal_id,
    )

    if attempt.guest_link_id is not None:
        GuestPaymentLink.objects.filter(
            pk=attempt.guest_link_id, consumed_at__isnull=True
        ).update(consumed_at=now)

    if not absorbable:
        logger.warning(
            "finance.unapplied_payment attempt=%s order=%s status=%s",
            attempt.pk,
            order.pk,
            order.status,
        )
        request_refund(
            order_id=order.pk,
            attempt_id=attempt.pk,
            amount_eur_cents=int(attempt.amount_eur_cents),
            reason=PaymentRefund.Reason.UNAPPLIED_PAYMENT,
            requested_by_id=None,
        )
        return "unapplied_payment_refunded"

    _recompute_order_money(order, at=now)

    if order.purpose == PaymentOrder.Purpose.POSTING_DEPOSIT:
        if order.status == PaymentOrder.Status.PAID:
            _publish_request_after_deposit(order, at=now)
    elif order.purpose == PaymentOrder.Purpose.DEAL_BALANCE:
        _fund_deal_if_covered(order)
    elif order.purpose == PaymentOrder.Purpose.BOOST:
        # The authoritative payment activates the boost. A client returning
        # from a checkout page never does, which is the same rule the deposit
        # and the deal balance already follow.
        _activate_boost_if_paid(order)

    _publish(
        channels.PAYMENT_CAPTURED,
        {
            **payment_resources(order),
            "order_reference": str(order.public_reference),
            "attempt_id": attempt.pk,
            "purpose": order.purpose,
            "amount_eur_cents": int(attempt.amount_eur_cents),
            "currency": "EUR",
        },
        targets=[order.owner_id],
    )
    _enqueue_guest_payment_receipt(attempt=attempt, order=order)
    return "applied"


# --- refunds -----------------------------------------------------------------


def request_refund(
    *,
    order_id: int,
    attempt_id: int,
    amount_eur_cents: int,
    reason: str,
    requested_by_id: int | None,
    idempotency_key: str | None = None,
) -> PaymentRefund:
    """Refund captured money against one attempt. Idempotent on the key.

    The guard is deliberately layered. This function refuses to exceed the
    attempt's own captured amount, `_recompute_order_money` clamps the order's
    refunded total, and the `fin_order_refund_within_capture` check constraint
    makes the invariant true at the database even if both were bypassed.
    """

    amount_eur_cents = require_positive_cents(amount_eur_cents)
    key = idempotency_key or f"refund:attempt:{attempt_id}:{reason}"

    existing = PaymentRefund.objects.filter(idempotency_key=key).first()
    if existing is not None:
        if existing.status == PaymentRefund.Status.FAILED:
            PaymentRefund.objects.filter(pk=existing.pk).update(
                status=PaymentRefund.Status.PENDING,
                requires_manual_action=True,
                next_retry_at=timezone.now(),
                updated_at=timezone.now(),
            )
            existing.refresh_from_db()
        if existing.status in (
            PaymentRefund.Status.PENDING,
            PaymentRefund.Status.PROCESSING,
        ):
            _schedule_refund_reconciliation(existing.pk, run_at=timezone.now())
        return existing

    with transaction.atomic():
        order = _order_for_update(order_id)
        attempt = PaymentAttempt.objects.select_for_update(no_key=True).get(
            pk=attempt_id
        )
        if attempt.order_id != order.pk:
            raise RefundNotPermitted("The attempt does not belong to this order.")
        if attempt.status != PaymentAttempt.Status.SUCCEEDED:
            raise RefundNotPermitted("Only a succeeded attempt can be refunded.")

        # Re-read the key now that the order row is held. The pre-transaction
        # lookup above answers the sequential retry; this one answers the
        # simultaneous one. Without it two operators clicking Refund at the same
        # instant both miss the unlocked read, and the loser is refused with
        # `RefundExceedsCapture` — correct about the money, but a confusing
        # answer to a request that is idempotent by contract.
        duplicate = PaymentRefund.objects.filter(idempotency_key=key).first()
        if duplicate is not None:
            if duplicate.status in (
                PaymentRefund.Status.PENDING,
                PaymentRefund.Status.PROCESSING,
            ):
                _schedule_refund_reconciliation(duplicate.pk, run_at=timezone.now())
            return duplicate

        already = int(
            PaymentRefund.objects.filter(
                attempt=attempt,
                status__in=(
                    PaymentRefund.Status.PENDING,
                    PaymentRefund.Status.PROCESSING,
                    PaymentRefund.Status.SUCCEEDED,
                ),
            ).aggregate(total=Sum("amount_eur_cents"))["total"]
            or 0
        )
        captured = int(attempt.amount_eur_cents)
        if already + amount_eur_cents > captured:
            raise RefundExceedsCapture(
                "A refund cannot exceed the captured amount.",
                captured=captured,
                already_refunded=already,
            )
        # The same euro can fund a Traveler payout or a Sender refund, never
        # both. A live payout reservation on this capture is money that is
        # already committed — or already gone — so it is subtracted here, under
        # the same lock the dispatch path takes, rather than discovered later
        # when the ledger no longer balances.
        from .payout_domain import source_reserved_cents

        reserved = source_reserved_cents(attempt)
        if already + reserved + amount_eur_cents > captured:
            raise RefundExceedsCapture(
                "This capture is reserved for a Traveler payout and cannot also "
                "fund a refund of this size.",
                captured=captured,
                already_refunded=already,
                reserved_for_payout=reserved,
            )

        try:
            refund = PaymentRefund.objects.create(
                order=order,
                attempt=attempt,
                amount_eur_cents=amount_eur_cents,
                provider=attempt.provider,
                provider_mode=attempt.provider_mode,
                idempotency_key=key,
                reason=reason,
                requested_by_id=requested_by_id,
                status=PaymentRefund.Status.PENDING,
            )
        except IntegrityError:
            return PaymentRefund.objects.get(idempotency_key=key)
        schedule_job(
            kind=ScheduledJob.Kind.REFUND_RECONCILE,
            key=f"refund_reconcile:{refund.pk}",
            run_at=timezone.now(),
            payload={"refund_id": refund.pk},
            max_attempts=32,
        )
        _recompute_order_money(order)

        _enqueue_refund_status_email(refund=refund, status="pending")

    # The callback runs only after the outermost transaction commits. If this
    # request originated inside payment reconciliation or request cancellation,
    # no provider I/O can occur while those domain/finance locks are held. The
    # ScheduledJob row above is the crash-safe fallback if the process exits
    # before this callback runs.
    transaction.on_commit(
        lambda refund_id=refund.pk: _drive_refund_after_commit(refund_id),
        robust=True,
    )
    return refund


def _drive_refund_after_commit(refund_id: int) -> None:
    try:
        _settle_refund_with_provider(refund_id=refund_id)
    except Exception:  # noqa: BLE001 - the durable job owns recovery
        logger.exception("finance.refund_post_commit_drive_failed refund=%s", refund_id)


def _schedule_refund_reconciliation(refund_id: int, *, run_at: datetime) -> None:
    schedule_job(
        kind=ScheduledJob.Kind.REFUND_RECONCILE,
        key=f"refund_reconcile:{refund_id}",
        run_at=run_at,
        payload={"refund_id": refund_id},
        max_attempts=32,
        reactivate_failed=True,
    )


def _settle_refund_with_provider(*, refund_id: int) -> str:
    """Ask the provider to return the money, then reconcile the ledger.

    Refunds keep working after a provider has been disabled for new checkouts:
    the gateway is resolved through `get_gateway`, which ignores business
    availability entirely. A rail with no refund API (Chargily) leaves the row
    pending for the manual queue rather than being marked succeeded on faith.
    """

    with transaction.atomic():
        row = PaymentRefund.objects.select_for_update(no_key=True).get(pk=refund_id)
        if row.status == PaymentRefund.Status.SUCCEEDED:
            return "already_succeeded"
        if row.status == PaymentRefund.Status.FAILED:
            return "failed"
        row.status = PaymentRefund.Status.PROCESSING
        row.processing_attempts = int(row.processing_attempts) + 1
        row.processing_started_at = timezone.now()
        row.last_provider_check_at = timezone.now()
        row.next_retry_at = None
        row.save(
            update_fields=[
                "status",
                "processing_attempts",
                "processing_started_at",
                "last_provider_check_at",
                "next_retry_at",
                "updated_at",
            ]
        )

    refund = PaymentRefund.objects.select_related("attempt", "order").get(pk=refund_id)
    attempt = refund.attempt
    provider_amount = _refund_provider_amount(refund, attempt)

    try:
        gateway = get_gateway(refund.provider)
        result = gateway.refund(
            RefundRequest(
                provider_payment_id=attempt.provider_payment_id,
                provider_session_id=attempt.provider_session_id,
                amount_minor=provider_amount,
                currency=attempt.payment_currency,
                idempotency_key=refund.idempotency_key,
                reason=refund.reason,
            )
        )
    except ProviderUnavailable as exc:
        logger.warning(
            "finance.refund_provider_unavailable refund=%s code=%s", refund.pk, exc.code
        )
        _mark_refund_retryable(refund.pk, exc)
        return "provider_unavailable"
    except ProviderError as exc:
        with transaction.atomic():
            order = _order_for_update(refund.order_id)
            row = PaymentRefund.objects.select_for_update(no_key=True).get(pk=refund.pk)
            if row.status == PaymentRefund.Status.SUCCEEDED:
                return "already_succeeded"
            row.failure_code = exc.code[:64]
            row.failure_message = str(exc)[:255]
            if isinstance(exc, RefundNotSupported):
                row.status = PaymentRefund.Status.PENDING
                row.requires_manual_action = True
                row.next_retry_at = timezone.now() + timedelta(hours=6)
                row.save(
                    update_fields=[
                        "status",
                        "failure_code",
                        "failure_message",
                        "requires_manual_action",
                        "next_retry_at",
                        "updated_at",
                    ]
                )
                _recompute_order_money(order)
                logger.warning(
                    "finance.refund_requires_manual_settlement refund=%s provider=%s",
                    row.pk,
                    row.provider,
                )
                _schedule_refund_reconciliation(
                    row.pk, run_at=row.next_retry_at or timezone.now()
                )
                return "manual_action_required"
            # A provider refusal does not erase the customer's entitlement.
            # Keep a visible manual obligation instead of treating the money
            # as resolved merely because the automatic rail rejected it.
            row.status = PaymentRefund.Status.PENDING
            row.requires_manual_action = True
            row.next_retry_at = timezone.now() + timedelta(hours=6)
            row.save(
                update_fields=[
                    "status",
                    "failure_code",
                    "failure_message",
                    "requires_manual_action",
                    "next_retry_at",
                    "updated_at",
                ]
            )
            _recompute_order_money(order)
            _schedule_refund_reconciliation(
                row.pk, run_at=row.next_retry_at or timezone.now()
            )
        return "manual_action_required"

    if not result.succeeded:
        retry_at = timezone.now() + timedelta(minutes=5)
        fields = {
            "status": PaymentRefund.Status.PENDING,
            "provider_refund_id": result.provider_refund_id[:255],
            "next_retry_at": retry_at,
            "updated_at": timezone.now(),
        }
        # Only ever escalate here. Writing the flag unconditionally would clear
        # a manual obligation an earlier provider refusal had already raised.
        if int(refund.processing_attempts) >= REFUND_MANUAL_ESCALATION_ATTEMPTS:
            fields["requires_manual_action"] = True
            logger.error(
                "finance.refund_escalated_to_operator refund=%s provider=%s "
                "attempts=%s code=provider_pending",
                refund.pk,
                refund.provider,
                refund.processing_attempts,
            )
        PaymentRefund.objects.filter(pk=refund.pk).exclude(
            status=PaymentRefund.Status.SUCCEEDED
        ).update(**fields)
        _schedule_refund_reconciliation(refund.pk, run_at=retry_at)
        return "provider_pending"

    mark_refund_succeeded(
        refund_id=refund.pk, provider_refund_id=result.provider_refund_id
    )
    return "succeeded"


def _mark_refund_retryable(refund_id: int, exc: Exception) -> None:
    refund = PaymentRefund.objects.filter(pk=refund_id).first()
    if refund is None or refund.status == PaymentRefund.Status.SUCCEEDED:
        return
    attempts = max(1, int(refund.processing_attempts))
    retry_at = timezone.now() + timedelta(
        seconds=min(60 * (2 ** max(0, attempts - 1)), 6 * 3_600)
    )
    with transaction.atomic():
        order = _order_for_update(refund.order_id)
        row = PaymentRefund.objects.select_for_update(no_key=True).get(pk=refund_id)
        if row.status == PaymentRefund.Status.SUCCEEDED:
            return
        row.status = PaymentRefund.Status.PENDING
        row.failure_code = type(exc).__name__[:64]
        row.failure_message = str(exc)[:255]
        row.next_retry_at = retry_at
        # A rail that has been unreachable this many times is not going to fix
        # itself. Keep retrying, but stop relying on the retry: the customer is
        # owed this money and an operator has to be able to see that.
        if (
            attempts >= REFUND_MANUAL_ESCALATION_ATTEMPTS
            and not row.requires_manual_action
        ):
            row.requires_manual_action = True
            logger.error(
                "finance.refund_escalated_to_operator refund=%s provider=%s "
                "attempts=%s code=%s",
                row.pk,
                row.provider,
                attempts,
                row.failure_code,
            )
        row.save(
            update_fields=[
                "status",
                "failure_code",
                "failure_message",
                "next_retry_at",
                "requires_manual_action",
                "updated_at",
            ]
        )
        _recompute_order_money(order)
    _schedule_refund_reconciliation(refund_id, run_at=retry_at)


def _refund_provider_amount(refund: PaymentRefund, attempt: PaymentAttempt) -> int:
    """Convert a canonical refund amount back into the attempt's own currency.

    Uses the attempt's frozen FX rate, never the current admin rate. Refunding a
    Chargily payment years later returns the dinars that were actually charged.
    """

    if attempt.payment_currency == "EUR":
        return int(refund.amount_eur_cents)
    if int(refund.amount_eur_cents) == int(attempt.amount_eur_cents):
        return int(attempt.provider_amount_minor)
    return convert_eur_cents(
        int(refund.amount_eur_cents),
        to_currency=attempt.payment_currency,
        rate_micros=int(attempt.fx_rate_micros or 0),
    )


@transaction.atomic
def mark_refund_succeeded(
    *,
    refund_id: int,
    provider_refund_id: str = "",
    settled_by_id: int | None = None,
    settlement_reference: str = "",
    settlement_note: str = "",
) -> PaymentRefund:
    """Record that a refund actually completed. Idempotent.

    Two callers reach this. The provider adapter calls it when the rail
    confirms the refund, and an operator calls it through
    `settle_refund_manually` for a rail that has no refund API — Chargily has
    none, so its refunds are bank transfers a human makes and records. Both
    paths land here so the ledger entry and the order recomputation are
    identical either way.
    """

    # Global lock order: PaymentOrder before PaymentRefund.
    order_id = PaymentRefund.objects.values_list("order_id", flat=True).get(
        pk=refund_id
    )
    order = _order_for_update(order_id)
    refund = PaymentRefund.objects.select_for_update(no_key=True).get(pk=refund_id)
    if refund.status == PaymentRefund.Status.SUCCEEDED:
        return refund
    refund.status = PaymentRefund.Status.SUCCEEDED
    refund.provider_refund_id = (provider_refund_id or refund.provider_refund_id)[:255]
    refund.succeeded_at = timezone.now()
    refund.processing_started_at = None
    refund.next_retry_at = None
    refund.requires_manual_action = False
    refund.failure_code = ""
    refund.failure_message = ""
    if settled_by_id is not None:
        refund.settled_by_id = settled_by_id
        refund.settlement_reference = settlement_reference.strip()[:128]
        refund.settlement_note = settlement_note[:255]
    refund.save(
        update_fields=[
            "status",
            "provider_refund_id",
            "succeeded_at",
            "processing_started_at",
            "next_retry_at",
            "requires_manual_action",
            "failure_code",
            "failure_message",
            "settled_by",
            "settlement_reference",
            "settlement_note",
            "updated_at",
        ]
    )
    ledger.record_refund(
        refund_id=refund.pk,
        order_id=order.pk,
        owner_id=order.owner_id,
        amount_eur_cents=int(refund.amount_eur_cents),
        purpose=order.purpose,
        deal_id=order.deal_id,
    )
    _recompute_order_money(order)
    ScheduledJob.objects.filter(
        kind=ScheduledJob.Kind.REFUND_RECONCILE,
        payload__refund_id=refund.pk,
        status__in=(ScheduledJob.Status.PENDING, ScheduledJob.Status.RUNNING),
    ).update(
        status=ScheduledJob.Status.SUCCEEDED,
        last_result="refund_succeeded",
        last_error="",
        locked_at=None,
        locked_by="",
        completed_at=timezone.now(),
        updated_at=timezone.now(),
    )
    _publish(
        channels.PAYMENT_REFUNDED,
        {
            **payment_resources(order),
            "order_reference": str(order.public_reference),
            "refund_id": refund.pk,
            "amount_eur_cents": int(refund.amount_eur_cents),
            "currency": "EUR",
            "purpose": order.purpose,
        },
        targets=[order.owner_id],
    )
    _enqueue_refund_status_email(refund=refund, status="succeeded")
    return refund


def settle_refund_manually(
    *,
    refund_id: int,
    admin_actor_id: int,
    settlement_reference: str,
    settlement_note: str = "",
) -> PaymentRefund:
    """Close a refund an operator settled outside the provider.

    Chargily Pay v2 exposes no refund endpoint, so a Chargily refund is a bank
    transfer a human makes. Without this path the refund would sit `pending`
    forever and the order would stay `refund_pending` with no way to finish it —
    a real obligation the system could see but not discharge.

    The reference is mandatory and enforced by a database constraint: money
    leaving the platform with no actor and no reference is untraceable.
    """

    if not settlement_reference.strip():
        raise RefundNotPermitted("A manual refund settlement requires a reference.")
    refund = PaymentRefund.objects.filter(pk=refund_id).first()
    if refund is None:
        raise RefundNotPermitted("No such refund.")
    if refund.status == PaymentRefund.Status.SUCCEEDED:
        return refund
    if refund.status not in (
        PaymentRefund.Status.PENDING,
        PaymentRefund.Status.PROCESSING,
        PaymentRefund.Status.FAILED,
    ):
        raise RefundNotPermitted(
            "Only an unresolved refund can be settled by hand "
            f"(status={refund.status})."
        )
    return mark_refund_succeeded(
        refund_id=refund_id,
        settled_by_id=admin_actor_id,
        settlement_reference=settlement_reference,
        settlement_note=settlement_note,
    )


def refund_order_in_full(
    *,
    order_id: int,
    reason: str,
    requested_by_id: int | None = None,
) -> list[PaymentRefund]:
    """Refund every applied capture on an order. Idempotent per attempt."""

    attempts = list(
        PaymentAttempt.objects.filter(
            order_id=order_id,
            status=PaymentAttempt.Status.SUCCEEDED,
            is_unapplied=False,
        ).order_by("pk")
    )
    refunds = []
    for attempt in attempts:
        outstanding = int(attempt.amount_eur_cents) - int(
            PaymentRefund.objects.filter(
                attempt=attempt,
                status__in=(
                    PaymentRefund.Status.PENDING,
                    PaymentRefund.Status.PROCESSING,
                    PaymentRefund.Status.SUCCEEDED,
                ),
            ).aggregate(total=Sum("amount_eur_cents"))["total"]
            or 0
        )
        if outstanding <= 0:
            continue
        refunds.append(
            request_refund(
                order_id=order_id,
                attempt_id=attempt.pk,
                amount_eur_cents=outstanding,
                reason=reason,
                requested_by_id=requested_by_id,
            )
        )
    return refunds


# --- order cancellation ------------------------------------------------------


@transaction.atomic
def cancel_order(*, order_id: int, reason: str) -> PaymentOrder:
    """Close an obligation so no further money is collected against it.

    Cancelling does not invent a refund decision. If captured money already
    won a race with this transition, cancellation is a no-op until every
    applied cent has a durable refund obligation. Domain cancellation flows
    that are allowed after payment create that obligation first. Otherwise it
    closes the collection window, which makes a later provider success land as
    an unapplied payment rather than funding a Deal that no longer exists.
    """

    order = lock_payment_order_aggregate(order_id).order
    if order.cancelled_at is not None:
        return order
    refund_obligated = int(
        PaymentRefund.objects.filter(
            order=order,
            status__in=(
                PaymentRefund.Status.PENDING,
                PaymentRefund.Status.PROCESSING,
                PaymentRefund.Status.SUCCEEDED,
            ),
            attempt__is_unapplied=False,
        ).aggregate(total=Sum("amount_eur_cents"))["total"]
        or 0
    )
    if int(order.paid_eur_cents) > refund_obligated:
        logger.info(
            "finance.order_cancellation_lost_to_payment order=%s paid=%s refund_obligated=%s",
            order.pk,
            order.paid_eur_cents,
            refund_obligated,
        )
        return order
    order.cancelled_at = timezone.now()
    # Persist the cancellation before recomputing: `_recompute_order_money`
    # saves an explicit field list that does not include `cancelled_at`, so
    # relying on it here would leave the order collectable and let a late
    # provider success fund a Deal that no longer exists.
    order.save(update_fields=["cancelled_at", "updated_at"])
    _release_deposit_credit(order)
    PaymentAttempt.objects.filter(
        order=order, status__in=PaymentAttempt.OPEN_STATUSES
    ).update(
        status=PaymentAttempt.Status.CANCELLED,
        failure_code=reason[:64],
        updated_at=timezone.now(),
    )
    _recompute_order_money(order)
    ScheduledJob.objects.filter(
        kind=ScheduledJob.Kind.ATTEMPT_EXPIRY,
        status=ScheduledJob.Status.PENDING,
        payload__attempt_id__in=list(
            PaymentAttempt.objects.filter(order=order).values_list("pk", flat=True)
        ),
    ).update(status=ScheduledJob.Status.CANCELLED, updated_at=timezone.now())
    return order


@transaction.atomic
def close_order_to_collection(*, order_id: int, reason: str) -> PaymentOrder:
    """Stop an order collecting, without touching its posting-deposit credit.

    `cancel_order` is the pre-funding path: it closes the window *and* hands the
    whole deposit credit back, because the Deal it belonged to no longer exists.
    A Phase 4 settlement is different. The Deal did happen, the money was
    earned or refunded according to a decision, and only the part of the credit
    that is actually being refunded may be released -- `apps.finance.settlement`
    owns that arithmetic.

    What this shares with `cancel_order` is the important half: once the order
    is closed, a provider success that arrives afterwards lands as an unapplied
    payment and is refunded, instead of re-funding a Deal that has been settled.
    """

    order = _order_for_update(order_id)
    if order.cancelled_at is None:
        order.cancelled_at = timezone.now()
        order.save(update_fields=["cancelled_at", "updated_at"])
    PaymentAttempt.objects.filter(
        order=order, status__in=PaymentAttempt.OPEN_STATUSES
    ).update(
        status=PaymentAttempt.Status.CANCELLED,
        failure_code=reason[:64],
        updated_at=timezone.now(),
    )
    ScheduledJob.objects.filter(
        kind=ScheduledJob.Kind.ATTEMPT_EXPIRY,
        status=ScheduledJob.Status.PENDING,
        payload__attempt_id__in=list(
            PaymentAttempt.objects.filter(order=order).values_list("pk", flat=True)
        ),
    ).update(status=ScheduledJob.Status.CANCELLED, updated_at=timezone.now())
    _recompute_order_money(order)
    return order


def _release_deposit_credit(order: PaymentOrder) -> int:
    """Hand a cancelled order's posting-deposit credit back to the deposit.

    Without this, a sender who paid a deposit, had an offer accepted and then
    missed the payment grace loses the deposit outright: the credit link marks
    it "already credited", so the expiry refund declines to return it and a
    later acceptance declines to re-use it. The money would sit in `deal_funds`
    against a deal that no longer exists.

    Releasing it posts a compensating ledger transaction — the deposit-credit
    move run backwards — and detaches `credit_source`, which makes the deposit
    available again to credit a fresh acceptance on the same request or to be
    refunded when the request expires. The original credit transaction stays on
    the record; nothing is rewritten.
    """

    if order.purpose != PaymentOrder.Purpose.DEAL_BALANCE:
        return 0
    if order.credit_source_id is None:
        return 0
    credited = int(order.credited_eur_cents)
    if credited <= 0:
        order.credit_source = None
        order.save(update_fields=["credit_source", "updated_at"])
        return 0

    deposit_id = order.credit_source_id
    original = LedgerTransaction.objects.filter(
        key=f"deposit_credit:order:{order.pk}"
    ).first()
    ledger.record_correction(
        key=f"deposit_credit_release:order:{order.pk}",
        note=f"Deposit #{deposit_id} released from cancelled balance #{order.pk}",
        reverses_id=original.pk if original is not None else None,
        legs=[
            ledger.Leg(
                account=LedgerAccount.DEAL_FUNDS,
                amount_eur_cents=credited,
                user_id=order.owner_id,
                order_id=order.pk,
                deal_id=order.deal_id,
                note="Deal funds released on cancellation",
            ),
            ledger.Leg(
                account=LedgerAccount.SENDER_DEPOSIT,
                amount_eur_cents=-credited,
                user_id=order.owner_id,
                order_id=deposit_id,
                deal_id=order.deal_id,
                note="Deposit liability restored",
            ),
        ],
    )
    order.credit_source = None
    order.credited_eur_cents = 0
    order.save(update_fields=["credit_source", "credited_eur_cents", "updated_at"])
    logger.info(
        "finance.deposit_credit_released order=%s deposit=%s cents=%s",
        order.pk,
        deposit_id,
        credited,
    )
    return credited


def cancel_deal_balance_orders(*, deal_id: int, reason: str) -> int:
    """Close every live balance obligation for a Deal. Idempotent."""

    # Ascending pk, as the canonical order requires for two rows of the same
    # type. A Deal should only ever carry one live balance order, but two
    # cancellers taking them in opposite orders would deadlock if it ever did.
    order_ids = list(
        PaymentOrder.objects.filter(
            deal_id=deal_id,
            purpose=PaymentOrder.Purpose.DEAL_BALANCE,
            cancelled_at__isnull=True,
        )
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    for order_id in order_ids:
        cancel_order(order_id=order_id, reason=reason)
    return len(order_ids)


# --- guest payment links -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class IssuedGuestLink:
    link: GuestPaymentLink
    token: str


def create_guest_link(
    *,
    order_id: int,
    actor_id: int,
    label: str = "",
    communication_language: str | None = None,
    policy: Phase3Policy | None = None,
) -> IssuedGuestLink:
    """Issue a single-purpose capability to pay one order.

    The plaintext token exists only in this return value. Only its SHA-256
    digest is stored, so a database read cannot reconstruct a working link, and
    the token never appears in a log line.
    """

    policy = policy or phase3_policy()
    with transaction.atomic():
        order = _order_for_update(order_id)
        if order.owner_id != actor_id:
            raise NotAuthorized("Only the order owner may invite someone to pay.")
        if not order.is_collectable:
            raise OrderNotCollectable(
                "This obligation is no longer collecting payment.",
                order_status=order.status,
            )
        if order.outstanding_eur_cents <= 0:
            raise NothingOutstanding("This order has nothing left to collect.")

        # Issuing a new link retires the previous one, so exactly one capability
        # is live per order at any moment.
        GuestPaymentLink.objects.filter(
            order=order, revoked_at__isnull=True, consumed_at__isnull=True
        ).update(revoked_at=timezone.now())

        token = secrets.token_urlsafe(GUEST_TOKEN_BYTES)
        from apps.core.languages import normalize_communication_language

        link = GuestPaymentLink.objects.create(
            order=order,
            token_hash=hash_guest_token(token),
            created_by_id=actor_id,
            label=label[:80],
            communication_language=normalize_communication_language(
                communication_language or getattr(order.owner, "preferred_language", "")
            ),
            expires_at=timezone.now()
            + timedelta(seconds=policy.guest_link_ttl_seconds),
        )
    return IssuedGuestLink(link=link, token=token)


def resolve_guest_link(token: str) -> GuestPaymentLink:
    """Look a guest token up by hash, or refuse with one uniform failure.

    Every rejection — unknown, expired, revoked, already used, or attached to an
    order that has closed — raises the same `guest_link_invalid`. A guest can
    therefore learn nothing about which orders exist by probing.
    """

    if not token or len(token) > 512:
        raise GuestLinkInvalid("This payment link is not valid.")
    link = (
        GuestPaymentLink.objects.select_related("order")
        .filter(token_hash=hash_guest_token(token))
        .first()
    )
    now = timezone.now()
    if (
        link is None
        or link.revoked_at is not None
        or link.consumed_at is not None
        or link.expires_at <= now
        or not link.order.is_collectable
        or link.order.outstanding_eur_cents <= 0
    ):
        raise GuestLinkInvalid("This payment link is not valid.")
    return link


@transaction.atomic
def revoke_guest_link(*, order_id: int, actor_id: int) -> int:
    order = _order_for_update(order_id)
    if order.owner_id != actor_id:
        raise NotAuthorized("Only the order owner may revoke a payment link.")
    return GuestPaymentLink.objects.filter(
        order=order, revoked_at__isnull=True, consumed_at__isnull=True
    ).update(revoked_at=timezone.now())


def guest_payment_view(link: GuestPaymentLink, *, policy: Phase3Policy) -> dict:
    """The entire payload a guest is entitled to see.

    Amount, currency, a generic description and an expiry. No sender, no
    traveler, no recipient, no addresses, no parcel, no deal, no order id.
    """

    order = link.order
    return {
        "amount_eur_cents": order.outstanding_eur_cents,
        "currency": "EUR",
        "description": _checkout_description(order),
        "expires_at": link.expires_at.isoformat(),
        # Guest rails carry the same settlement preview as the signed-in
        # screen. Chargily reports `supports_guest_payment = False`, so it is
        # filtered out here rather than offered and refused at the tap.
        "providers": [
            row
            for row in provider_options(
                policy,
                amount_eur_cents=order.outstanding_eur_cents,
                guest_only=True,
            )
            if row["available"]
        ],
    }


# --- payouts -----------------------------------------------------------------


def resolve_payout_method(
    *,
    traveler_id: int,
    funding_provider: str,
    policy: Phase3Policy,
    query_provider_capability: bool = True,
) -> tuple[str, str]:
    """Decide how a traveler will be paid. Returns (method, reason).

    No country heuristic exists here. An automatic Stripe transfer requires all
    of: the policy allowing it, a Stripe-connected payout method on file, and
    Stripe itself reporting that the account's payouts and transfers are live.
    Anything else — including a Chargily-funded Deal, which does not imply a
    Chargily payout rail — falls back to the manual queue.
    """

    if not policy.payout.auto_stripe_enabled:
        return Payout.Method.MANUAL, "auto_payout_disabled"

    method = (
        TravelerPayoutMethod.objects.filter(
            traveler_id=traveler_id,
            method=TravelerPayoutMethod.Method.STRIPE_CONNECT,
        )
        .order_by("-is_default", "-updated_at")
        .first()
    )
    if method is None or not method.provider_account_id:
        return Payout.Method.MANUAL, "no_connected_account"
    if not method.payouts_enabled:
        return Payout.Method.MANUAL, "capability_not_reported"
    if not query_provider_capability:
        # Deal funding runs while the complete financial/domain aggregate is
        # locked. A provider capability HTTP request does not belong there;
        # keep the payout conservatively manual/not-eligible until a later
        # out-of-transaction capability refresh or Phase 4 release check.
        return Payout.Method.MANUAL, "capability_refresh_deferred"

    from .providers import StripeGateway

    gateway = StripeGateway()
    if not gateway.is_configured():
        return Payout.Method.MANUAL, "stripe_not_configured"
    capability = gateway.payout_capability(account_id=method.provider_account_id)
    if not capability.available:
        return Payout.Method.MANUAL, capability.reason or "capability_unavailable"
    return Payout.Method.STRIPE_TRANSFER, ""


def ensure_payout_for_deal(
    *,
    deal_id: int,
    traveler_id: int,
    amount_eur_cents: int,
    funding_provider: str = "",
    policy: Phase3Policy | None = None,
    query_provider_capability: bool = True,
) -> Payout:
    """Create the traveler's payout record for a funded Deal.

    It is created `not_eligible` and Phase 3 contains no code path that
    advances it. Release depends on delivery confirmation, the 48-hour
    protection window and dispute state, all of which are Phase 4; the
    `fin_payout_release_requires_eligibility` check constraint makes that
    boundary structural rather than a convention.
    """

    if settings.PAYOUT_PROFILES_ENABLED:
        from .payout_snapshots import create_snapshot

        return create_snapshot(
            deal_id=deal_id, traveler_id=traveler_id, amount_eur_cents=amount_eur_cents
        )
    policy = policy or phase3_policy()
    method, reason = resolve_payout_method(
        traveler_id=traveler_id,
        funding_provider=funding_provider,
        policy=policy,
        query_provider_capability=query_provider_capability,
    )
    payout, created = Payout.objects.get_or_create(
        deal_id=deal_id,
        defaults={
            "traveler_id": traveler_id,
            "amount_eur_cents": amount_eur_cents,
            "method": method,
            "status": Payout.Status.NOT_ELIGIBLE,
            "notes": f"Payout method resolved as {method}: {reason or 'capability_available'}",
        },
    )
    if created:
        schedule_job(
            kind=ScheduledJob.Kind.PAYOUT_RELEASE_CHECK,
            key=f"payout_release_check:{payout.pk}",
            run_at=timezone.now()
            + timedelta(seconds=max(policy.payout.protection_window_seconds, 3_600)),
            payload={"payout_id": payout.pk},
        )
    return payout


@transaction.atomic
def complete_manual_payout(
    *,
    payout_id: int,
    admin_actor_id: int,
    payout_currency: str,
    payout_amount_minor: int,
    reference: str,
    fx_rate_micros: int | None = None,
    receipt_url: str = "",
    notes: str = "",
) -> Payout:
    """Record that an operator actually sent a traveler their money.

    Refuses unless Phase 4 has already made the payout eligible. That is not a
    formality: it is the reason Phase 3 cannot pay a traveler before delivery
    confirmation and the protection window, no matter what an admin clicks.

    Every completion carries evidence — actor, reference, currency, amount and
    the rate used — and the `fin_payout_paid_requires_evidence` constraint
    refuses a `paid` row without it. Idempotent: a double submit returns the
    already-settled row.
    """

    payout = Payout.objects.select_for_update(no_key=True).get(pk=payout_id)
    if payout.snapshot_version:
        raise PayoutNotReleasable(
            "Versioned payouts require the future receipt/provider execution service."
        )
    if payout.status == Payout.Status.PAID:
        return payout
    if payout.block_reason == "legacy_instruction_required":
        raise PayoutNotReleasable(
            "Legacy payout instructions require reviewed remediation."
        )
    if payout.status not in (
        Payout.Status.ELIGIBLE,
        Payout.Status.SCHEDULED,
        Payout.Status.PROCESSING,
    ):
        raise PayoutNotReleasable(
            "This payout has not been released for settlement.",
            payout_status=payout.status,
        )
    if not reference.strip():
        raise PayoutNotReleasable("A manual payout requires a transfer reference.")
    if payout_amount_minor <= 0:
        raise PayoutNotReleasable("A manual payout amount must be positive.")

    currency = payout_currency.upper()
    if currency not in CURRENCY_EXPONENTS:
        raise PayoutNotReleasable(f"Unsupported payout currency {currency!r}.")
    if currency != "EUR" and not fx_rate_micros:
        raise PayoutNotReleasable(
            "A non-EUR payout must record the exchange rate that was used."
        )

    payout.status = Payout.Status.PAID
    payout.method = Payout.Method.MANUAL
    payout.payout_currency = currency
    payout.payout_amount_minor = payout_amount_minor
    payout.payout_amount_exponent = CURRENCY_EXPONENTS[currency]
    payout.fx_rate_micros = fx_rate_micros
    payout.reference = reference.strip()[:128]
    payout.receipt_url = receipt_url[:1024]
    payout.admin_actor_id = admin_actor_id
    payout.notes = (notes or payout.notes)[:2000]
    payout.paid_at = timezone.now()
    payout.save()

    ledger.record_payout(
        payout_id=payout.pk,
        deal_id=payout.deal_id,
        traveler_id=payout.traveler_id,
        amount_eur_cents=int(payout.amount_eur_cents),
    )
    _publish(
        channels.PAYOUT_STATUS_CHANGED,
        {**deal_resources(payout.deal), "status": payout.status},
        targets=[payout.traveler_id],
    )
    logger.info(
        "finance.manual_payout_settled payout=%s actor=%s currency=%s",
        payout.pk,
        admin_actor_id,
        currency,
    )
    return payout


# --- durable scheduling ------------------------------------------------------


def schedule_job(
    *,
    kind: str,
    key: str,
    run_at: datetime,
    payload: dict | None = None,
    max_attempts: int = 8,
    reactivate_failed: bool = False,
) -> ScheduledJob:
    """Record a delayed obligation in the database. Idempotent on `key`.

    Redis is never the record. If this row exists the work will eventually run,
    across process restarts, Redis flushes and worker crashes; if it does not,
    the work was never promised.
    """

    job, created = ScheduledJob.objects.get_or_create(
        key=key,
        defaults={
            "kind": kind,
            "run_at": run_at,
            "payload": payload or {},
            "max_attempts": max_attempts,
        },
    )
    if not created and reactivate_failed and job.status == ScheduledJob.Status.FAILED:
        job.status = ScheduledJob.Status.PENDING
        job.run_at = run_at
        job.attempts = 0
        job.locked_at = None
        job.locked_by = ""
        job.completed_at = None
        job.resolution = ""
        job.resolved_at = None
        job.resolved_by = None
        job.resolution_reason = ""
        job.save(
            update_fields=[
                "status",
                "run_at",
                "attempts",
                "locked_at",
                "locked_by",
                "completed_at",
                "resolution",
                "resolved_at",
                "resolved_by",
                "resolution_reason",
                "updated_at",
            ]
        )
    elif (
        not created
        and job.status == ScheduledJob.Status.PENDING
        and job.run_at != run_at
    ):
        # A rescheduled obligation (e.g. the deadline moved) keeps its identity.
        job.run_at = run_at
        job.save(update_fields=["run_at", "updated_at"])
    return job


def chargily_display(*, amount_eur_cents: int, policy: Phase3Policy) -> dict:
    """The Chargily figures a checkout screen must show, computed server-side.

    Canonical EUR, the DZD that will actually be charged, and the exact rate.
    The client renders these; it never derives them and never sends them back.
    """

    rate_micros = policy.chargily.eur_dzd_rate_micros
    return {
        "canonical_currency": "EUR",
        "canonical_amount_eur_cents": amount_eur_cents,
        "payment_currency": "DZD",
        "payment_amount_dzd": convert_eur_cents(
            amount_eur_cents, to_currency="DZD", rate_micros=rate_micros
        ),
        "eur_dzd_rate": format_rate(rate_micros),
        "eur_dzd_rate_micros": rate_micros,
        "rate_settings_version": policy.settings_version.version,
    }
