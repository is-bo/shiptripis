"""The Deal API.

Everything a party does to a Deal that is not handover, disputes, ratings or
boosts lives here: reading it, recording the recipient, pricing a cancellation
and performing one.

Two things about the cancel endpoint are worth stating plainly, because they are
the reason it looks the way it does.

**One endpoint, two policies.** `POST /api/deals/<id>/cancel` covers cancelling
before funding and cancelling after it. They are genuinely different operations
-- one releases a reservation, the other releases a reservation *and* settles
money -- but from the client's side they are one button whose consequences the
server explains. Splitting them into two URLs would make the client decide which
policy applies, and the client is exactly the party that must not be deciding.

**The quote is separate from the act.** `GET /api/deals/<id>/cancellation`
prices a cancellation without performing one, so the confirmation screen can
show a real number, computed server-side from the Deal's frozen policy, before
anybody commits to it.
"""

from __future__ import annotations

import logging

from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from rest_framework import generics, status as http
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.business_settings import NoActiveBusinessSettings
from apps.core.phase4_policy import InvalidPhase4Policy

from .activity import ACTIVITY_STATES, activity_q
from .arrival import ArrivalError, decide_early_arrival, report_early_arrival
from .cancellation import CancellationError, cancel_funded_deal, quote_cancellation
from .lifecycle import DealLifecycleError, PRE_PICKUP_STATUSES
from .models import Deal, DealLegAllocation
from .recipient import RecipientError, set_recipient
from .serializers import (
    DealRecipientWriteSerializer,
    DealSerializer,
    DealSummarySerializer,
)
from .services import DealCancellationError, cancel_pending_deal

logger = logging.getLogger(__name__)


def _deal_error_response(exc: Exception) -> Response:
    """Map a Deal-domain failure to its machine code and HTTP status.

    Every branch is explicit and an unrecognised exception becomes a generic
    `internal_error` with its message suppressed, so a stack detail can never
    reach a client through this path.
    """

    from apps.finance.settlement import SettlementError

    if isinstance(exc, RecipientError) and exc.code == "not_authorized":
        status_code = http.HTTP_403_FORBIDDEN
    elif isinstance(exc, ArrivalError) and exc.code in ("not_traveler", "not_sender"):
        # An arrival action attempted by the wrong party is an authorization
        # failure, not a state conflict, and is answered as one. It says which
        # party may act and nothing about the Deal's internals.
        status_code = http.HTTP_403_FORBIDDEN
    elif isinstance(
        exc, (RecipientError, CancellationError, DealLifecycleError, ArrivalError)
    ):
        status_code = http.HTTP_409_CONFLICT
    elif isinstance(exc, SettlementError):
        status_code = http.HTTP_409_CONFLICT
    elif isinstance(exc, (InvalidPhase4Policy, NoActiveBusinessSettings)):
        status_code = http.HTTP_503_SERVICE_UNAVAILABLE
    else:
        logger.error("Unmapped deal failure", exc_info=True)
        return Response(
            {"code": "internal_error", "detail": "The request could not be completed."},
            status=http.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    payload = {"code": getattr(exc, "code", "deal_error"), "detail": str(exc)}
    details = getattr(exc, "details", None)
    if callable(details):
        payload.update(details())
    return Response(payload, status=status_code)


def _party_deals(user_id: int):
    """The list queryset. Kept to a bounded number of queries on purpose."""

    return (
        Deal.objects.filter(Q(sender_id=user_id) | Q(traveler_id=user_id))
        .select_related(
            "terms",
            "terms__business_settings_version",
            "journey",
            "delivery_request",
        )
        .prefetch_related(
            Prefetch(
                "leg_allocations",
                queryset=DealLegAllocation.objects.select_related("journey_leg"),
            ),
        )
    )


def _detail_deals(user_id: int):
    """The detail queryset: the list one plus everything the rich projection reads."""

    return (
        _party_deals(user_id)
        .select_related("recipient", "payout", "sender", "traveler")
        .prefetch_related("events", "arrival_reports")
    )


class DealListView(generics.ListAPIView):
    """The party's Deals, optionally narrowed to one activity bucket.

    `?activity=active|completed|cancelled` is the fix for delivered Deals
    lingering under active "Sending". The client asks for a bucket by name and
    the server decides which Deals are in it, using the same rule
    `activity_state` reports on every row -- so a list filtered to `active`
    and a row that says `completed` cannot both be right.

    `?status=` is retained unchanged for the screens that genuinely want one
    lifecycle status.
    """

    serializer_class = DealSummarySerializer
    permission_classes = (IsAuthenticated,)

    def get_queryset(self):
        queryset = _party_deals(self.request.user.id)
        if requested_status := self.request.query_params.get("status"):
            queryset = queryset.filter(status=requested_status)
        activity = self.request.query_params.get("activity")
        if activity:
            if activity not in ACTIVITY_STATES:
                raise ValidationError(
                    {
                        "activity": (
                            "Unknown activity filter. Expected one of: "
                            + ", ".join(ACTIVITY_STATES)
                            + "."
                        )
                    }
                )
            queryset = queryset.filter(activity_q(activity))
        return queryset


class DealDetailView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, pk: int) -> Response:
        deal = get_object_or_404(_detail_deals(request.user.id), pk=pk)
        return Response(DealSerializer(deal, context={"request": request}).data)


class DealRecipientView(APIView):
    """Who receives the parcel. Sender-only, funded, before pickup.

    `PUT` is idempotent in the ordinary REST sense -- the same body twice leaves
    the same recipient -- but each write bumps a revision and appends a timeline
    event, because "the recipient changed the day before pickup" is exactly the
    kind of fact a dispute needs to be able to see.
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, pk: int) -> Response:
        deal = get_object_or_404(_detail_deals(request.user.id), pk=pk)
        from .recipient import recipient_projection

        projection = recipient_projection(
            deal=deal,
            recipient=getattr(deal, "recipient", None),
            viewer_id=request.user.id,
            is_staff=bool(request.user.is_staff),
        )
        if projection is None:
            return Response(
                {"code": "recipient_not_set", "detail": "No recipient recorded yet."},
                status=http.HTTP_404_NOT_FOUND,
            )
        return Response(projection)

    def put(self, request: Request, pk: int) -> Response:
        get_object_or_404(_party_deals(request.user.id), pk=pk)
        payload = DealRecipientWriteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            result = set_recipient(
                deal_id=pk, actor_id=request.user.id, **payload.validated_data
            )
        except (RecipientError, DealLifecycleError) as exc:
            return _deal_error_response(exc)
        deal = get_object_or_404(_detail_deals(request.user.id), pk=pk)
        return Response(
            {
                "deal": DealSerializer(deal, context={"request": request}).data,
                "created": result.created,
                "revision": result.revision,
            },
            status=http.HTTP_201_CREATED if result.created else http.HTTP_200_OK,
        )

    def post(self, request: Request, pk: int) -> Response:
        return self.put(request, pk)


class DealCancellationQuoteView(APIView):
    """Price a cancellation without performing one."""

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, pk: int) -> Response:
        get_object_or_404(_party_deals(request.user.id), pk=pk)
        try:
            quote = quote_cancellation(deal_id=pk, actor_id=request.user.id)
        except Exception as exc:  # noqa: BLE001 - mapped below, never re-raised
            if isinstance(exc, (CancellationError, DealLifecycleError)):
                return _deal_error_response(exc)
            raise
        return Response(quote.as_dict())


class DealCancelView(APIView):
    """Cancel a Deal under whichever policy its current state implies."""

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: int) -> Response:
        deal = get_object_or_404(_party_deals(request.user.id), pk=pk)

        # An already-cancelled Deal answers the same way it did the first time.
        # Cancelling is the one action a client is most likely to retry after a
        # dropped response, and turning that retry into a 409 would tell the
        # user their cancellation failed when it did not.
        if deal.status in (Deal.Status.PAYMENT_REQUIRED, Deal.Status.CANCELLED):
            return self._cancel_before_funding(request, pk)
        if deal.status in PRE_PICKUP_STATUSES:
            return self._cancel_after_funding(request, pk)
        if deal.pickup_confirmed_at is not None:
            return Response(
                {
                    "code": "cancellation_not_available_after_pickup",
                    "detail": (
                        "This parcel has already been picked up. Open a dispute "
                        "instead."
                    ),
                    "deal_status": deal.status,
                },
                status=http.HTTP_409_CONFLICT,
            )
        return Response(
            {
                "code": "deal_not_cancellable",
                "detail": "This delivery can no longer be cancelled.",
                "deal_status": deal.status,
            },
            status=http.HTTP_409_CONFLICT,
        )

    def _cancel_before_funding(self, request: Request, pk: int) -> Response:
        try:
            result = cancel_pending_deal(deal_id=pk, actor_id=request.user.id)
        except DealCancellationError as exc:
            return Response(
                {"code": exc.code, "detail": str(exc)},
                status=http.HTTP_409_CONFLICT,
            )
        deal = get_object_or_404(_detail_deals(request.user.id), pk=pk)
        return Response(
            {
                "deal": DealSerializer(deal, context={"request": request}).data,
                "mode": "pre_funding",
                "released_allocations": result.released_allocations,
                "changed": result.changed,
            }
        )

    def _cancel_after_funding(self, request: Request, pk: int) -> Response:
        reason = str(request.data.get("reason", ""))[:64]
        try:
            quote = cancel_funded_deal(
                deal_id=pk, actor_id=request.user.id, reason=reason
            )
        except Exception as exc:  # noqa: BLE001 - mapped below, never re-raised
            from apps.finance.settlement import SettlementError

            if isinstance(
                exc, (CancellationError, DealLifecycleError, SettlementError)
            ):
                return _deal_error_response(exc)
            raise
        deal = get_object_or_404(_detail_deals(request.user.id), pk=pk)
        return Response(
            {
                "deal": DealSerializer(deal, context={"request": request}).data,
                "mode": "after_funding",
                "settlement": quote.as_dict(),
                "changed": True,
            }
        )


class DealArrivalView(APIView):
    """Report, confirm or decline a materially early arrival.

    One resource, three verbs' worth of intent, and the server decides who may
    do which. The traveler reports; the sender answers. Neither can perform the
    other's action, and neither learns anything new about the other's secrets by
    trying.

    Every response is the Deal detail projection, so the client re-renders from
    one authoritative document rather than patching its own state from a
    success code. `changed` says whether this call was the one that moved
    anything: a retried report or a repeated confirmation answers 200 with
    `changed: false` rather than an error, because a dropped response must not
    look like a failure to the person who tapped the button.
    """

    permission_classes = (IsAuthenticated,)

    #: URL suffix -> what it means. Declared rather than branched on a body
    #: field, so an action is never chosen by client-supplied data.
    ACTIONS = ("report", "confirm", "decline")

    def post(self, request: Request, pk: int, action: str) -> Response:
        get_object_or_404(_party_deals(request.user.id), pk=pk)
        if action not in self.ACTIONS:
            return Response(
                {"code": "unknown_arrival_action", "detail": "Unsupported action."},
                status=http.HTTP_404_NOT_FOUND,
            )
        try:
            if action == "report":
                result = report_early_arrival(deal_id=pk, actor_id=request.user.id)
            else:
                result = decide_early_arrival(
                    deal_id=pk,
                    actor_id=request.user.id,
                    confirm=action == "confirm",
                )
        except (ArrivalError, DealLifecycleError) as exc:
            return _deal_error_response(exc)
        deal = get_object_or_404(_detail_deals(request.user.id), pk=pk)
        return Response(
            {
                "deal": DealSerializer(deal, context={"request": request}).data,
                "arrival_report_id": result.report_id,
                "arrival_report_status": result.status,
                "changed": result.changed,
            }
        )
