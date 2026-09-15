"""The pricing contract a sender sees before, during and after posting.

Three endpoints, one job: make sure the minimum, the recommendation and the
sender's own choice are all on the wire together, and that no client ever has to
compute a money figure to render a screen.

    POST /api/parcels/pricing-quote     price a draft, before anything is saved
    GET  /api/parcels/<id>/pricing      one request's full money picture

The draft endpoint exists because of an ordering rule J2 makes explicit: the
recommendation must be visible *before* the sender chooses, not returned as a
correction after they submit one. It takes the fields the posting form has
already collected and prices them without writing a row.

The per-request endpoint is the frozen J3 contract. It carries the reward band,
the Boost, the total offered reward, the deposit band and what is still owed --
and it deliberately does not carry internal accounting. A sender learns what
they pay and what the traveler earns; they do not get the ledger.
"""

from __future__ import annotations

from decimal import Decimal

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle, UserRateThrottle
from rest_framework.views import APIView

from apps.core.business_settings import NoActiveBusinessSettings
from apps.core.phase4_policy import InvalidPhase4Policy, phase4_policy
from apps.finance.models import PaymentOrder
from apps.finance.policy import InvalidPaymentPolicy, phase3_policy
from apps.finance.services import FinanceError, deposit_quote_payload
from apps.locations.models import Place
from apps.matching.policy import InvalidPhase2Policy
from apps.matching.posting_pricing import (
    PostingPriceQuote,
    draft_request,
    quote_posting_price,
)
from apps.matching.pricing import PricingError

from .models import DeliveryRequest

PRICING_FAILURES = (
    PricingError,
    NoActiveBusinessSettings,
    InvalidPhase2Policy,
    InvalidPhase4Policy,
    InvalidPaymentPolicy,
    FinanceError,
)


def _pricing_error_response(exc: Exception) -> Response:
    code = getattr(exc, "code", None) or "pricing_unavailable"
    details = getattr(exc, "details", None)
    payload = {"code": code, "detail": str(exc)}
    if callable(details):
        payload.update(details())
    unavailable = isinstance(
        exc,
        (
            NoActiveBusinessSettings,
            InvalidPhase2Policy,
            InvalidPhase4Policy,
            InvalidPaymentPolicy,
        ),
    )
    return Response(
        payload,
        status=(
            status.HTTP_503_SERVICE_UNAVAILABLE
            if unavailable
            else status.HTTP_409_CONFLICT
        ),
    )


class PricingQuoteDraftSerializer(serializers.Serializer):
    """The posting form's own fields, priced without saving anything.

    Deliberately a subset of the create contract rather than a parallel one:
    every field here is a field the sender has already filled in by the time a
    price has to appear on screen.
    """

    pickup_place_id = serializers.PrimaryKeyRelatedField(
        queryset=Place.objects.filter(active=True)
    )
    delivery_place_id = serializers.PrimaryKeyRelatedField(
        queryset=Place.objects.filter(active=True)
    )
    actual_weight_kg = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        min_value=Decimal("0.01"),
        max_value=Decimal("100.00"),
    )
    length_cm = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        min_value=Decimal("0.01"),
        max_value=Decimal("500.00"),
        required=False,
        allow_null=True,
    )
    width_cm = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        min_value=Decimal("0.01"),
        max_value=Decimal("500.00"),
        required=False,
        allow_null=True,
    )
    height_cm = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        min_value=Decimal("0.01"),
        max_value=Decimal("500.00"),
        required=False,
        allow_null=True,
    )
    ready_window_end = serializers.DateTimeField()
    deadline_at = serializers.DateTimeField()
    #: Optional. Supplying it adds `chosen_economics` and says whether the
    #: choice clears the floor; omitting it asks only "what may I charge?".
    chosen_reward_eur_cents = serializers.IntegerField(
        required=False, min_value=1, max_value=100_000_000
    )
    boost_eur_cents = serializers.IntegerField(
        required=False, min_value=0, max_value=100_000_000
    )

    def validate(self, attrs: dict) -> dict:
        dimensions = [
            attrs.get(name) for name in ("length_cm", "width_cm", "height_cm")
        ]
        if any(value is not None for value in dimensions) and any(
            value is None for value in dimensions
        ):
            raise serializers.ValidationError(
                {
                    "dimensions": (
                        "Enter length, width and height together, or leave all "
                        "three empty."
                    )
                }
            )
        if attrs["ready_window_end"] > attrs["deadline_at"]:
            raise serializers.ValidationError(
                {"deadline_at": "Deadline must be at or after the ready window end."}
            )
        return attrs


def _boost_block(*, amount_eur_cents: int, base_reward_eur_cents: int | None) -> dict:
    """The Boost, its commission, and the reward a traveler is actually offered.

    `total_offered_reward_eur_cents` is the number a traveler should see: the
    base reward plus the whole Boost, because under J2 the Boost goes to them
    intact and ShipTrip's commission on it is charged to the sender on top.
    Computing it here rather than in the client is the point of the field.
    """

    from apps.boosts.services import boost_policy_payload, calculate_boost_reward

    policy = phase4_policy()
    reward = calculate_boost_reward(
        amount_eur_cents=int(amount_eur_cents or 0), policy=policy
    )
    block = {**reward.as_dict(), "policy": boost_policy_payload(policy)}
    if base_reward_eur_cents is not None:
        block["base_reward_eur_cents"] = int(base_reward_eur_cents)
        block["total_offered_reward_eur_cents"] = int(base_reward_eur_cents) + int(
            reward.amount_eur_cents
        )
    return block


class PricingQuoteDraftView(APIView):
    """Price a request the sender has not posted yet."""

    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle, ScopedRateThrottle)
    throttle_scope = "matching_discovery"

    def post(self, request: Request) -> Response:
        serializer = PricingQuoteDraftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        chosen = data.get("chosen_reward_eur_cents")
        draft = draft_request(
            schema_version=3,
            pickup_place=data["pickup_place_id"],
            delivery_place=data["delivery_place_id"],
            actual_weight_kg=data["actual_weight_kg"],
            length_cm=data.get("length_cm"),
            width_cm=data.get("width_cm"),
            height_cm=data.get("height_cm"),
            ready_window_end=data["ready_window_end"],
            deadline_at=data["deadline_at"],
        )
        try:
            quote = quote_posting_price(
                delivery_request=draft, chosen_reward_eur_cents=chosen
            )
            payload = _pricing_payload(quote=quote, chosen_reward_eur_cents=chosen)
            payload["boost"] = _boost_block(
                amount_eur_cents=data.get("boost_eur_cents", 0),
                base_reward_eur_cents=chosen,
            )
            payload["deposit"] = _draft_deposit_block(quote)
        except PRICING_FAILURES as exc:
            return _pricing_error_response(exc)
        return Response(payload)


def _pricing_payload(
    *, quote: PostingPriceQuote, chosen_reward_eur_cents: int | None
) -> dict:
    """Minimum, recommendation and choice, with whether the choice is allowed."""

    payload = quote.as_dict()
    payload["chosen_is_below_minimum"] = bool(
        chosen_reward_eur_cents is not None
        and int(chosen_reward_eur_cents) < quote.minimum_reward_eur_cents
    )
    payload["chosen_is_below_recommended"] = bool(
        chosen_reward_eur_cents is not None
        and int(chosen_reward_eur_cents) < quote.recommended_reward_eur_cents
    )
    return payload


def _draft_deposit_block(quote: PostingPriceQuote) -> dict:
    """The deposit a draft would be asked for, and the band around it.

    Built from the *recommended* sender total, exactly as the real deposit quote
    is, so the number the sender sees on the posting screen is the number the
    obligation will carry. Boost is deliberately absent from the basis: it is
    optional extra reward, and letting it move an untouched default would make
    the suggestion jump whenever the sender nudges a slider.
    """

    from apps.finance.money import clamp, percentage_of

    policy = phase3_policy()
    deposit = policy.posting_deposit
    sender_total = int(quote.recommended_economics["sender_total_minor"])
    raw = percentage_of(sender_total, bps=deposit.percent_bps)
    recommended = clamp(
        raw, minimum=deposit.min_eur_cents, maximum=deposit.max_eur_cents
    )
    return {
        "currency": "EUR",
        "required": policy.deposit_required,
        "recommended_eur_cents": recommended,
        "minimum_eur_cents": deposit.chosen_min_eur_cents,
        "percent_bps": deposit.percent_bps,
        "recommendation_basis_eur_cents": sender_total,
        "is_flexible": True,
    }


class RequestPricingView(APIView):
    """One request's whole money picture: reward, Boost, deposit, balance.

    Owner-or-staff. What a sender chose to pay, and what they still owe, is not
    something other users read off their request.
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, pk: int) -> Response:
        delivery_request = get_object_or_404(
            DeliveryRequest.objects.select_related(
                "pickup_place", "delivery_place", "pickup_location", "delivery_location"
            ),
            pk=pk,
        )
        if delivery_request.sender_id != request.user.id and not request.user.is_staff:
            return Response(
                {
                    "code": "not_authorized",
                    "detail": "Only the sender may see this request's pricing.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        chosen = delivery_request.traveler_reward_eur_cents
        try:
            quote = quote_posting_price(
                delivery_request=delivery_request, chosen_reward_eur_cents=chosen
            )
            payload = _pricing_payload(quote=quote, chosen_reward_eur_cents=chosen)
            payload["boost"] = _boost_block(
                amount_eur_cents=int(delivery_request.boost_eur_cents or 0),
                base_reward_eur_cents=chosen,
            )
            payload["deposit"] = _request_deposit_block(delivery_request)
        except PRICING_FAILURES as exc:
            return _pricing_error_response(exc)
        payload["delivery_request_id"] = delivery_request.pk
        payload["request_status"] = delivery_request.status
        payload["actions"] = _permitted_actions(delivery_request)
        return Response(payload)


def _request_deposit_block(delivery_request: DeliveryRequest) -> dict:
    """What the deposit is, what it may be, and what it has discharged."""

    policy = phase3_policy()
    order = (
        PaymentOrder.objects.filter(
            delivery_request_id=delivery_request.pk,
            purpose=PaymentOrder.Purpose.POSTING_DEPOSIT,
        )
        .exclude(status=PaymentOrder.Status.CANCELLED)
        .first()
    )
    block = deposit_quote_payload(
        delivery_request=delivery_request, order=order, policy=policy
    )
    block["required"] = policy.deposit_required
    block["order_status"] = order.status if order is not None else None
    block["paid_eur_cents"] = int(order.paid_eur_cents) if order is not None else 0
    block["outstanding_eur_cents"] = (
        order.outstanding_eur_cents if order is not None else None
    )
    return block


def _permitted_actions(delivery_request: DeliveryRequest) -> dict:
    """What the sender may still do. Server-decided, so no client guesses it."""

    from apps.boosts.services import EDITABLE_STATUSES

    editable = delivery_request.status in EDITABLE_STATUSES
    return {
        "can_edit_boost": editable,
        "can_choose_deposit": (
            delivery_request.status == delivery_request.Status.AWAITING_DEPOSIT
        ),
        "can_cancel": editable,
    }
