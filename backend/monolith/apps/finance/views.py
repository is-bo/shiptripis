"""V1 payment API.

    GET  /api/payments/providers                          server-authoritative rails
    GET  /api/payments/orders                             my obligations
    GET  /api/payments/orders/<reference>                 one obligation
    POST /api/payments/orders/<reference>/checkout        open a hosted checkout
    GET  /api/payments/orders/<reference>/guest-link      my "someone else can pay" link
    POST /api/payments/orders/<reference>/guest-link      share it (reuses the live one)
    POST /api/payments/orders/<reference>/guest-link/revoke
    GET  /api/parcels/<id>/posting-deposit                deposit quote + status
    GET  /api/deals/<id>/payment                          outstanding balance
    GET  /api/payouts                                     my traveler earnings
    POST /api/admin/payouts/<id>/complete                 admin manual settlement
    POST /api/admin/payments/orders/<reference>/refund    admin refund
    GET  /api/payments/guest/<token>                      minimal guest surface
    POST /api/payments/guest/<token>/checkout             guest checkout

Authorization is object-level everywhere: an order is visible to its owner and
to staff, a payout to its traveler and to staff, and the guest surface is
reachable only by presenting an unguessable capability that carries no identity.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from rest_framework import status as http
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.business_settings import NoActiveBusinessSettings
from apps.core.permissions import CanSettlePayouts
from apps.admin_panel.permissions import CanIssueRefunds, CanSettleManualRefunds
from apps.admin_panel.services import record_admin_action
from apps.deals.models import Deal
from apps.parcels.models import DeliveryRequest

from .models import (
    PaymentAttempt,
    PaymentOrder,
    PaymentRefund,
    Payout,
)
from .policy import InvalidPaymentPolicy, phase3_policy
from .providers import ProviderError, available_providers
from .serializers import (
    CheckoutCreateSerializer,
    GuestCheckoutCreateSerializer,
    GuestLinkCreateSerializer,
    ManualPayoutCompleteSerializer,
    ManualRefundSettleSerializer,
    PaymentAttemptSerializer,
    PaymentOrderSerializer,
    PaymentOrderSummarySerializer,
    PostingDepositCreateSerializer,
    PayoutSerializer,
    RefundRequestSerializer,
)
from .services import (
    FinanceError,
    GuestLinkInvalid,
    NotAuthorized,
    chargily_display,
    create_guest_link,
    ensure_posting_deposit_order,
    deposit_quote_payload,
    guest_link_status,
    guest_payment_view,
    provider_options,
    request_refund,
    resolve_guest_link,
    settle_refund_manually,
    revoke_guest_link,
    start_checkout,
    complete_manual_payout,
)

logger = logging.getLogger(__name__)


class GuestPaymentThrottle(AnonRateThrottle):
    """Bound token-guessing attempts against the unauthenticated surface."""

    scope = "guest_payment"


def _finance_error_response(exc: Exception) -> Response:
    """Map a domain failure to its machine code and structured detail.

    Every branch is explicit, and an unrecognised exception becomes a generic
    `internal_error` with its message suppressed rather than echoed.
    """

    if isinstance(exc, NotAuthorized):
        status_code = http.HTTP_403_FORBIDDEN
    elif isinstance(exc, GuestLinkInvalid):
        # Uniform 404 for every invalid-link reason so a prober cannot tell
        # "expired" from "never existed".
        return Response(
            {"code": exc.code, "detail": "This payment link is not valid."},
            status=http.HTTP_404_NOT_FOUND,
        )
    elif isinstance(exc, FinanceError):
        status_code = http.HTTP_409_CONFLICT
    elif isinstance(exc, (NoActiveBusinessSettings, InvalidPaymentPolicy)):
        status_code = http.HTTP_503_SERVICE_UNAVAILABLE
    elif isinstance(exc, ProviderError):
        status_code = http.HTTP_503_SERVICE_UNAVAILABLE
    else:
        logger.error("Unmapped finance failure", exc_info=True)
        return Response(
            {"code": "internal_error", "detail": "The request could not be completed."},
            status=http.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    payload = {"code": getattr(exc, "code", "finance_error"), "detail": str(exc)}
    details = getattr(exc, "details", None)
    if callable(details):
        payload.update(details())
    return Response(payload, status=status_code)


def _with_payment_options(payload: dict, order: PaymentOrder) -> dict:
    """Attach the rail list, with per-rail amounts, to a payable order.

    Every surface that can start a checkout serves the same shape, because the
    payment section is the same widget on all of them and the amount it shows
    must come from the server that will charge it — not from the client pairing
    a rail with a currency of its own choosing.
    """

    if order.outstanding_eur_cents <= 0:
        return payload
    try:
        policy = phase3_policy()
    except (NoActiveBusinessSettings, InvalidPaymentPolicy):
        return payload
    payload["providers"] = provider_options(
        policy, amount_eur_cents=order.outstanding_eur_cents
    )
    if policy.providers.chargily_enabled:
        payload["chargily_quote"] = chargily_display(
            amount_eur_cents=order.outstanding_eur_cents, policy=policy
        )
    return payload


def _order_queryset():
    return PaymentOrder.objects.select_related(
        "deal", "delivery_request"
    ).prefetch_related(
        Prefetch("attempts", queryset=PaymentAttempt.objects.order_by("-created_at")),
        Prefetch("refunds", queryset=PaymentRefund.objects.order_by("-created_at")),
    )


def _owned_order(request: Request, reference: str) -> PaymentOrder:
    order = get_object_or_404(_order_queryset(), public_reference=reference)
    if order.owner_id != request.user.id and not request.user.is_staff:
        raise NotAuthorized("This payment does not belong to you.")
    return order


# --- provider availability ---------------------------------------------------


class PaymentProvidersView(APIView):
    """What this caller may actually pay with, decided by the server.

    A provider appears as available only when policy enables it *and* the
    deployment holds its credentials *and* it is accepting new checkouts. A
    button in the client is not a capability.
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        try:
            policy = phase3_policy()
        except (NoActiveBusinessSettings, InvalidPaymentPolicy) as exc:
            return _finance_error_response(exc)
        rows = available_providers(policy)
        payload = {
            "timing_mode": policy.timing_mode,
            "canonical_currency": "EUR",
            # No obligation in hand here, so the rows carry settlement currency
            # and readiness but no amount. The order endpoints below add the
            # amount each rail would charge for that specific obligation.
            "providers": provider_options(policy),
        }
        chargily = next((row for row in rows if row.provider == "chargily"), None)
        if chargily is not None and chargily.enabled:
            payload["chargily_rate"] = {
                "eur_dzd_rate": chargily_display(amount_eur_cents=100, policy=policy)[
                    "eur_dzd_rate"
                ],
                "rate_settings_version": policy.settings_version.version,
            }
        return Response(payload)


# --- orders ------------------------------------------------------------------


class PaymentOrderListView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        queryset = PaymentOrder.objects.filter(owner=request.user)
        if purpose := request.query_params.get("purpose"):
            queryset = queryset.filter(purpose=purpose)
        if order_status := request.query_params.get("status"):
            queryset = queryset.filter(status=order_status)
        return Response(PaymentOrderSummarySerializer(queryset[:100], many=True).data)


class PaymentOrderDetailView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, reference: str) -> Response:
        try:
            order = _owned_order(request, reference)
        except NotAuthorized as exc:
            return _finance_error_response(exc)
        return Response(
            _with_payment_options(PaymentOrderSerializer(order).data, order)
        )


class PaymentCheckoutView(APIView):
    """Open a hosted checkout for an obligation the caller owns."""

    permission_classes = (IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "payment_checkout"

    def post(self, request: Request, reference: str) -> Response:
        serializer = CheckoutCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            order = _owned_order(request, reference)
            if order.owner_id != request.user.id:
                raise NotAuthorized("Only the owner may pay this obligation.")
            session = start_checkout(
                order_id=order.pk,
                provider=serializer.validated_data["provider"],
                actor_id=request.user.id,
            )
        except (
            FinanceError,
            ProviderError,
            NoActiveBusinessSettings,
            InvalidPaymentPolicy,
        ) as exc:
            return _finance_error_response(exc)
        return Response(
            PaymentAttemptSerializer(session.attempt).data,
            status=http.HTTP_201_CREATED if session.created else http.HTTP_200_OK,
        )


def _guest_link_payload(status) -> dict:
    """The owner's view of their guest link, the same shape on every verb.

    One shape for read, share and revoke, so the app renders whatever the
    server last said instead of stitching state together from three replies.
    The link itself appears only while it is live and can be shown; every
    other state carries no token at all.
    """

    order = status.order
    link = status.link
    shows_expiry = link is not None and status.state in ("active", "expired")
    return {
        "state": status.state,
        "token": status.token,
        # The whole shareable address, built by the server. A client that
        # assembled this itself would be a client that could get the host wrong
        # and send a payer somewhere else.
        "payment_link": status.url,
        "expires_at": link.expires_at if shows_expiry else None,
        "amount_eur_cents": order.outstanding_eur_cents,
        "currency": "EUR",
        "purpose": order.purpose,
        "communication_language": link.communication_language if link else None,
        "checkout_in_progress": status.checkout_in_progress,
        "can_create": status.can_create,
        "can_revoke": status.can_revoke,
    }


class GuestLinkCreateView(APIView):
    """The owner's "someone else can pay" link for one order.

    `GET` reads it and issues nothing. `POST` shares it: the live link if there
    is one the owner can be shown again, otherwise a new one. Opening the sheet
    twice therefore hands back the same link rather than breaking the one a
    relative is already holding.
    """

    permission_classes = (IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "payment_checkout"

    def get_throttles(self):
        # Reading is not issuing; only the write shares the checkout budget.
        if self.request.method == "GET":
            return []
        return super().get_throttles()

    def get(self, request: Request, reference: str) -> Response:
        try:
            order = _owned_order(request, reference)
            status = guest_link_status(order_id=order.pk, actor_id=request.user.id)
        except FinanceError as exc:
            return _finance_error_response(exc)
        return Response(_guest_link_payload(status))

    def post(self, request: Request, reference: str) -> Response:
        serializer = GuestLinkCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            order = _owned_order(request, reference)
            issued = create_guest_link(
                order_id=order.pk,
                actor_id=request.user.id,
                label=serializer.validated_data.get("label", ""),
                communication_language=serializer.validated_data.get(
                    "communication_language"
                ),
                reuse_live=True,
            )
            status = guest_link_status(order_id=order.pk, actor_id=request.user.id)
        except (FinanceError, NoActiveBusinessSettings, InvalidPaymentPolicy) as exc:
            return _finance_error_response(exc)
        return Response(
            {
                **_guest_link_payload(status),
                "token": issued.token,
                "payment_link": issued.url,
                # True when this replaced a link the owner had already sent.
                "reissued": issued.reissued,
                # True when nothing was issued: this is the link already shared.
                "reused": issued.reused,
            },
            status=http.HTTP_200_OK if issued.reused else http.HTTP_201_CREATED,
        )


class GuestLinkRevokeView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, reference: str) -> Response:
        try:
            order = _owned_order(request, reference)
            revoked = revoke_guest_link(order_id=order.pk, actor_id=request.user.id)
            status = guest_link_status(order_id=order.pk, actor_id=request.user.id)
        except FinanceError as exc:
            return _finance_error_response(exc)
        return Response({"revoked": revoked, **_guest_link_payload(status)})


# --- guest surface -----------------------------------------------------------


class GuestPaymentView(APIView):
    """The unauthenticated payer's view of one obligation.

    Holding the token permits exactly one thing: paying. It confers no Deal
    ownership, no chat, no dispute authority and no sight of the recipient or
    the counterparty — and this payload is the proof, because there is nothing
    else in it.
    """

    permission_classes = (AllowAny,)
    authentication_classes = ()
    throttle_classes = (GuestPaymentThrottle,)

    def get(self, request: Request, token: str) -> Response:
        try:
            link = resolve_guest_link(token)
            policy = phase3_policy()
        except (FinanceError, NoActiveBusinessSettings, InvalidPaymentPolicy) as exc:
            return _finance_error_response(exc)
        return Response(guest_payment_view(link, policy=policy))


class GuestCheckoutView(APIView):
    permission_classes = (AllowAny,)
    authentication_classes = ()
    throttle_classes = (GuestPaymentThrottle,)

    def post(self, request: Request, token: str) -> Response:
        serializer = GuestCheckoutCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            link = resolve_guest_link(token)
            session = start_checkout(
                order_id=link.order_id,
                provider=serializer.validated_data["provider"],
                actor_id=None,
                guest_link=link,
                guest_email=serializer.validated_data["email"],
            )
        except (
            FinanceError,
            ProviderError,
            NoActiveBusinessSettings,
            InvalidPaymentPolicy,
        ) as exc:
            return _finance_error_response(exc)
        attempt = session.attempt
        # A guest sees the URL they must visit and the amount they will be
        # charged. Nothing about the order, the deal or the parties.
        return Response(
            {
                "checkout_url": attempt.checkout_url,
                "amount_eur_cents": attempt.amount_eur_cents,
                "payment_currency": attempt.payment_currency,
                "provider": attempt.provider,
                "expires_at": attempt.expires_at,
            },
            status=http.HTTP_201_CREATED if session.created else http.HTTP_200_OK,
        )


# --- posting deposit ---------------------------------------------------------


class PostingDepositView(APIView):
    """The sender's deposit quote and its payment state for one request."""

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, pk: int) -> Response:
        delivery_request = get_object_or_404(
            DeliveryRequest.objects.select_related(
                "pickup_location", "delivery_location"
            ),
            pk=pk,
        )
        if delivery_request.sender_id != request.user.id and not request.user.is_staff:
            return _finance_error_response(
                NotAuthorized("Only the sender may see this deposit.")
            )
        try:
            policy = phase3_policy()
        except (NoActiveBusinessSettings, InvalidPaymentPolicy) as exc:
            return _finance_error_response(exc)

        payload: dict = {
            "timing_mode": policy.timing_mode,
            "deposit_required": policy.deposit_required,
            "request_status": delivery_request.status,
        }
        order = (
            PaymentOrder.objects.filter(
                delivery_request_id=delivery_request.pk,
                purpose=PaymentOrder.Purpose.POSTING_DEPOSIT,
            )
            .exclude(status=PaymentOrder.Status.CANCELLED)
            .first()
        )
        if order is not None:
            payload["order"] = _with_payment_options(
                PaymentOrderSummarySerializer(order).data, order
            )
            try:
                payload["quote"] = deposit_quote_payload(
                    delivery_request=delivery_request, order=order, policy=policy
                )
            except FinanceError as exc:
                return _finance_error_response(exc)
            return Response(payload)
        if not policy.deposit_required:
            return Response(payload)
        try:
            payload["quote"] = deposit_quote_payload(
                delivery_request=delivery_request, order=None, policy=policy
            )
        except FinanceError as exc:
            return _finance_error_response(exc)
        return Response(payload)

    def post(self, request: Request, pk: int) -> Response:
        """Create, return, or reprice the deposit obligation for a request.

        The body may carry `amount_eur_cents`: the sender's own choice, which
        the server bounds below by the configured floor and above by the
        obligation it pre-pays. Omitting it takes the recommendation. A client
        never invents either limit -- both come back in the quote.
        """

        delivery_request = get_object_or_404(
            DeliveryRequest.objects.select_related(
                "pickup_location", "delivery_location"
            ),
            pk=pk,
        )
        if delivery_request.sender_id != request.user.id:
            return _finance_error_response(
                NotAuthorized("Only the sender may create this deposit.")
            )
        serializer = PostingDepositCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            order = ensure_posting_deposit_order(
                delivery_request=delivery_request,
                chosen_amount_eur_cents=serializer.validated_data.get(
                    "amount_eur_cents"
                ),
            )
        except (FinanceError, NoActiveBusinessSettings, InvalidPaymentPolicy) as exc:
            return _finance_error_response(exc)
        payload = _with_payment_options(
            PaymentOrderSummarySerializer(order).data, order
        )
        try:
            payload["quote"] = deposit_quote_payload(
                delivery_request=delivery_request, order=order
            )
        except FinanceError as exc:
            return _finance_error_response(exc)
        return Response(payload, status=http.HTTP_201_CREATED)


# --- deal balance ------------------------------------------------------------


class DealPaymentView(APIView):
    """The Deal's outstanding balance, computed entirely server-side."""

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, pk: int) -> Response:
        deal = get_object_or_404(Deal.objects.select_related("terms"), pk=pk)
        if (
            request.user.id not in (deal.sender_id, deal.traveler_id)
            and not request.user.is_staff
        ):
            return _finance_error_response(
                NotAuthorized("Only a party may see this deal's payment state.")
            )
        order = (
            _order_queryset()
            .filter(deal_id=deal.pk, purpose=PaymentOrder.Purpose.DEAL_BALANCE)
            .exclude(status=PaymentOrder.Status.CANCELLED)
            .first()
        )
        terms = getattr(deal, "terms", None)
        payload: dict = {
            "deal_id": deal.pk,
            "deal_status": deal.status,
            "currency": "EUR",
            "sender_total_eur_cents": int(terms.sender_total_minor) if terms else None,
            "traveler_reward_eur_cents": (
                int(terms.traveler_reward_minor) if terms else None
            ),
            "platform_fee_eur_cents": int(terms.platform_fee_minor) if terms else None,
            "boost_amount_eur_cents": int(terms.boost_amount_minor) if terms else None,
            "traveler_boost_bonus_eur_cents": (
                int(terms.boost_traveler_bonus_minor) if terms else None
            ),
            "platform_boost_revenue_eur_cents": (
                int(terms.boost_platform_fee_minor) if terms else None
            ),
            "traveler_total_eur_cents": terms.traveler_total_minor if terms else None,
            "platform_total_eur_cents": terms.platform_total_minor if terms else None,
            "sender_total_with_boost_eur_cents": (
                terms.sender_total_with_boost_minor if terms else None
            ),
        }
        if order is None:
            payload["order"] = None
            return Response(payload)

        # The traveler is a party to the Deal but not to the sender's payment.
        # They learn that it is funded, not how it was paid.
        if request.user.id == deal.traveler_id and not request.user.is_staff:
            payload["order"] = {
                "status": order.status,
                "outstanding_eur_cents": order.outstanding_eur_cents,
            }
            return Response(payload)

        payload["order"] = _with_payment_options(
            PaymentOrderSerializer(order).data, order
        )
        return Response(payload)


# --- payouts -----------------------------------------------------------------


class PayoutListView(APIView):
    """A traveler's own earnings state. Always gated in Phase 3."""

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        from .payout_mobile import page_context, payouts_for
        from apps.notifications.views import _Pagination

        queryset = payouts_for(request.user)
        if payout_status := request.query_params.get("status"):
            queryset = queryset.filter(status=payout_status)
        paginator = None
        if "page" in request.query_params or "page_size" in request.query_params:
            paginator = _Pagination()
            page = list(paginator.paginate_queryset(queryset, request))
        else:
            page = list(queryset[:100])
        # The page's dispute, hold and setup facts are read once for the whole
        # list, so a hundred rows cost the same queries as one.
        context = {"payout_page": page_context(page, user=request.user)}
        data = PayoutSerializer(page, many=True, context=context).data
        response = (
            paginator.get_paginated_response(data) if paginator else Response(data)
        )
        response["Cache-Control"] = "no-store, private"
        return response


class PayoutDetailView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request, reference):
        from django.shortcuts import get_object_or_404
        from .payout_mobile import payouts_for, payout_status

        payout = get_object_or_404(payouts_for(request.user), public_reference=reference)
        response = Response(payout_status(payout))
        response["Cache-Control"] = "no-store, private"
        return response


class AdminManualPayoutView(APIView):
    """Record an operator settlement. Refused until Phase 4 releases the payout."""

    permission_classes = (CanSettlePayouts,)

    def post(self, request: Request, pk: int) -> Response:
        serializer = ManualPayoutCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            payout = complete_manual_payout(
                payout_id=pk,
                admin_actor_id=request.user.id,
                payout_currency=data["payout_currency"],
                payout_amount_minor=data["payout_amount_minor"],
                reference=data["reference"],
                fx_rate_micros=data.get("fx_rate_micros"),
                receipt_url=data.get("receipt_url", ""),
                notes=data.get("notes", ""),
            )
        except Payout.DoesNotExist:
            return Response(
                {"code": "payout_not_found", "detail": "No such payout."},
                status=http.HTTP_404_NOT_FOUND,
            )
        except FinanceError as exc:
            return _finance_error_response(exc)
        return Response(PayoutSerializer(payout).data)


class AdminRefundView(APIView):
    """Administrative refund against one captured attempt."""

    permission_classes = (CanIssueRefunds,)

    def post(self, request: Request, reference: str) -> Response:
        serializer = RefundRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        order = get_object_or_404(PaymentOrder, public_reference=reference)
        try:
            with transaction.atomic():
                refund = request_refund(
                    order_id=order.pk,
                    attempt_id=data["attempt_id"],
                    amount_eur_cents=data["amount_eur_cents"],
                    reason=data["reason"],
                    requested_by_id=request.user.id,
                    idempotency_key=(
                        f"admin_refund:order:{order.pk}:attempt:{data['attempt_id']}"
                        f":{data['amount_eur_cents']}"
                    ),
                )
                record_admin_action(
                    actor=request.user,
                    action="refund.requested",
                    target=refund,
                    after={
                        "status": refund.status,
                        "amount_eur_cents": refund.amount_eur_cents,
                    },
                    reason=data["reason"],
                )
        except PaymentAttempt.DoesNotExist:
            return Response(
                {"code": "attempt_not_found", "detail": "No such payment attempt."},
                status=http.HTTP_404_NOT_FOUND,
            )
        except (FinanceError, ProviderError) as exc:
            return _finance_error_response(exc)
        order.refresh_from_db()
        return Response(
            {
                "refund": {
                    "id": refund.pk,
                    "status": refund.status,
                    "amount_eur_cents": refund.amount_eur_cents,
                    "reason": refund.reason,
                },
                "order": PaymentOrderSummarySerializer(order).data,
            },
            status=http.HTTP_201_CREATED,
        )


class AdminRefundSettleView(APIView):
    """Record an operator settlement of a refund the provider cannot make.

    Chargily has no refund API, so its refunds leave the platform as bank
    transfers. Without this route such a refund would stay `pending` and its
    order `refund_pending` forever: an obligation the system could see and not
    discharge. The reference is mandatory, and the database refuses a settled
    refund that does not carry one.
    """

    permission_classes = (CanSettleManualRefunds,)

    def post(self, request: Request, pk: int) -> Response:
        serializer = ManualRefundSettleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                refund = settle_refund_manually(
                    refund_id=pk,
                    admin_actor_id=request.user.id,
                    settlement_reference=serializer.validated_data[
                        "settlement_reference"
                    ],
                    settlement_note=serializer.validated_data.get(
                        "settlement_note", ""
                    ),
                )
                record_admin_action(
                    actor=request.user,
                    action="refund.manually_settled",
                    target=refund,
                    after={"status": refund.status},
                    reference=refund.settlement_reference,
                )
        except FinanceError as exc:
            return _finance_error_response(exc)
        order = PaymentOrder.objects.get(pk=refund.order_id)
        return Response(
            {
                "refund": {
                    "id": refund.pk,
                    "status": refund.status,
                    "amount_eur_cents": refund.amount_eur_cents,
                    "settlement_reference": refund.settlement_reference,
                },
                "order": PaymentOrderSummarySerializer(order).data,
            }
        )
