"""Matching API — the routed V1 reads and the party-side closing writes.

Routed here (see `urls.py`):
  GET  /api/matches                          — list (mine, ?role=sender|traveler, ?status=)
  GET  /api/matches/<id>                     — detail (party-only)
  POST /api/matches/<id>/cancel              — either party cancels (only while pending)
  GET  /api/matches/<id>/offers              — list offers on a match (party-only)
  GET  /api/matches/<id>/chat-eligibility    — whether chat is open on this match
  POST /api/offers/<id>/decline              — counterparty declines
  POST /api/offers/<id>/withdraw             — proposer withdraws their own offer

Every V1 *negotiation write* lives in `v1_views.py` and `v1_services.py`
instead: `SenderProposeV1View`, `CounterOfferV1View` and `OfferAcceptV1View`.
L1A deleted the pre-V1 traveler-first write classes that used to sit in this
module; their paths are no longer routed.

Row locks here use `select_for_update(no_key=True)`, the canonical mode
asserted by `apps/finance/tests/test_phase8df_lock_order.py`.

State machine details in `models.py`.

CLAUDE.md G6: every state change publishes via `redis_bus.publish_after_commit`.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import channels, redis_bus
from apps.core.event_resources import match_resources
from apps.core.pagination import paginated_array_response
from apps.parcels.models import ParcelRequest

from .models import Match, MatchEvent, Offer
from .offer_economics import OfferEconomicsReader
from .serializers import (
    MatchListSerializer,
    MatchSerializer,
    OfferSerializer,
)
from .services import chat_eligibility


# ---------- helpers ----------


def _is_party(match: Match, user_id: int) -> bool:
    return user_id in (match.sender_id, match.traveler_id)


def _product_retired_response() -> Response:
    return _domain_error(
        code="product_request_retired",
        detail="ProductRequest/Kaba business flows are retired in Wassla V1.",
        status_code=http.HTTP_410_GONE,
    )


def _domain_error(
    *,
    code: str,
    detail: str,
    status_code: int,
    **extra: object,
) -> Response:
    """Emit the V1 structured negotiation-failure envelope.

    Decline and withdraw share the machine-code vocabulary defined by
    `apps.matching.v1_services` (`not_authorized`, `offer_not_pending`,
    `match_not_pending`, ...) so a client switches on `code` and never parses
    an English sentence. The status split is unchanged: 403 separates
    authorization from 409 state, and 410 marks a retired contract.
    """

    payload: dict[str, object] = {"code": code, "detail": detail}
    payload.update(extra)
    return Response(payload, status=status_code)


def _refetch_match(pk: int) -> Match:
    return _match_read_queryset().get(pk=pk)


def _match_read_queryset():
    return Match.objects.select_related(
        "parcel",
        "parcel__deliveryrequest",
        "parcel__deliveryrequest__pickup_location",
        "parcel__deliveryrequest__delivery_location",
        "parcel__deliveryrequest__pickup_place",
        "parcel__deliveryrequest__delivery_place",
        "trip",
        "sender",
        "traveler",
        "deal",
    ).prefetch_related(
        Prefetch(
            "offers",
            # An accepted offer's Boost economics are read from its Deal's
            # frozen terms (J6.1), so they are joined here rather than fetched
            # once per row.
            queryset=Offer.objects.select_related("deal__terms").order_by(
                "-created_at"
            ),
            to_attr="_ordered_offers",
        )
    )


# ---------- views ----------


class MatchListView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        role = request.query_params.get("role")
        qs = _match_read_queryset().filter(parcel__kind=ParcelRequest.Kind.DELIVERY)
        if role == "sender":
            qs = qs.filter(sender=request.user)
        elif role == "traveler":
            qs = qs.filter(traveler=request.user)
        else:
            qs = qs.filter(sender=request.user) | qs.filter(traveler=request.user)
        if s := request.query_params.get("status"):
            qs = qs.filter(status=s)
        def serialize(page):
            matches = list(page)
            # One read of the retired paid-package rows for every open
            # negotiation on this page, instead of one per serialized row.
            economics = OfferEconomicsReader()
            economics.prime(matches)
            return MatchListSerializer(
                matches,
                many=True,
                context={"request": request, "offer_economics": economics},
            ).data

        # No `.distinct()`: every join here is single-valued (forward foreign
        # keys and the one-to-one Deal) and the role union is one OR'd WHERE,
        # so a Match cannot repeat. DISTINCT over this wide select only cost
        # PostgreSQL about 65 ms of planning per page (K7 D).
        return paginated_array_response(
            request,
            qs.order_by("-created_at", "-pk"),
            serialize=serialize,
        )


class MatchDetailView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, pk: int) -> Response:
        match = get_object_or_404(
            _match_read_queryset(),
            pk=pk,
        )
        if match.parcel.kind == ParcelRequest.Kind.PRODUCT:
            return Response(
                {"detail": "ProductRequest history is admin-only in Wassla V1."},
                status=http.HTTP_410_GONE,
            )
        if not _is_party(match, request.user.id):
            return Response(
                {"detail": "Not a party to this match."}, status=http.HTTP_403_FORBIDDEN
            )
        return Response(MatchSerializer(match, context={"request": request}).data)


class MatchCancelView(APIView):
    """Either party cancels a Match while it's still pending."""

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: int) -> Response:
        with transaction.atomic():
            match = get_object_or_404(
                Match.objects.select_for_update(no_key=True).select_related("parcel"), pk=pk
            )
            if not _is_party(match, request.user.id):
                return Response(
                    {"detail": "Not a party."}, status=http.HTTP_403_FORBIDDEN
                )
            if match.parcel.kind == ParcelRequest.Kind.PRODUCT:
                return _product_retired_response()
            if match.status != Match.Status.PENDING:
                return Response(
                    {"detail": f"Cannot cancel match in status '{match.status}'."},
                    status=http.HTTP_409_CONFLICT,
                )

            match.status = Match.Status.CANCELLED
            match.save(update_fields=["status", "updated_at"])
            # Cancel any still-pending offer.
            Offer.objects.filter(match=match, status=Offer.Status.PENDING).update(
                status=Offer.Status.WITHDRAWN,
                responded_at=timezone.now(),
            )
            MatchEvent.objects.create(
                match=match,
                actor=request.user,
                kind=MatchEvent.Kind.MATCH_CANCELLED,
                payload={"by_user_id": request.user.id},
            )
            recipient = (
                match.traveler_id
                if request.user.id == match.sender_id
                else match.sender_id
            )
            redis_bus.publish_after_commit(
                channels.OFFER_UPDATED,
                {
                    **match_resources(match),
                    "status": "cancelled",
                    "recipient_id": recipient,
                },
                targets=[recipient],
            )

        return Response(
            MatchSerializer(_refetch_match(match.pk), context={"request": request}).data
        )


class OfferListView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, pk: int) -> Response:
        match = get_object_or_404(
            Match.objects.select_related("parcel", "parcel__deliveryrequest"), pk=pk
        )
        if not _is_party(match, request.user.id):
            return Response({"detail": "Not a party."}, status=http.HTTP_403_FORBIDDEN)
        if match.parcel.kind == ParcelRequest.Kind.PRODUCT:
            return _product_retired_response()
        offers = match.offers.select_related("deal__terms")
        return Response(
            OfferSerializer(
                offers, many=True, context={"request": request, "match": match}
            ).data
        )


class OfferDeclineView(APIView):
    """Counterparty declines a pending offer (Match stays open for new offers)."""

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: int) -> Response:
        with transaction.atomic():
            initial_offer = get_object_or_404(
                Offer.objects.select_related("match__parcel"), pk=pk
            )
            match = get_object_or_404(
                Match.objects.select_for_update(no_key=True), pk=initial_offer.match_id
            )
            offer = get_object_or_404(
                Offer.objects.select_for_update(no_key=True), pk=initial_offer.pk
            )
            if not _is_party(match, request.user.id):
                return _domain_error(
                    code="not_authorized",
                    detail="Only a party to this match may decline its offer.",
                    status_code=http.HTTP_403_FORBIDDEN,
                )
            if initial_offer.match.parcel.kind == ParcelRequest.Kind.PRODUCT:
                return _product_retired_response()
            if offer.proposer_id == request.user.id:
                return _domain_error(
                    code="not_authorized",
                    detail="Cannot decline your own offer; withdraw instead.",
                    status_code=http.HTTP_403_FORBIDDEN,
                )
            if offer.status != Offer.Status.PENDING:
                return _domain_error(
                    code="offer_not_pending",
                    detail="The offer is no longer pending.",
                    status_code=http.HTTP_409_CONFLICT,
                    offer_status=offer.status,
                )

            offer.status = Offer.Status.DECLINED
            offer.responded_at = timezone.now()
            offer.save(update_fields=["status", "responded_at", "updated_at"])
            if offer.economics_version == Offer.EconomicsVersion.V1_EUR:
                # A declined and a withdrawn negotiation are the same
                # user-visible outcome, so both terminate the Match as
                # CANCELLED. EXPIRED is reserved for system-driven endings
                # (superseded by a competing acceptance, reservation lapse).
                # Who ended it stays recorded on the MatchEvent and the Offer.
                match.status = Match.Status.CANCELLED
                match.save(update_fields=["status", "updated_at"])
            MatchEvent.objects.create(
                match=match,
                offer=offer,
                actor=request.user,
                kind=MatchEvent.Kind.OFFER_DECLINED,
                payload={},
            )
            redis_bus.publish_after_commit(
                channels.OFFER_UPDATED,
                {
                    **match_resources(match),
                    "offer_id": offer.id,
                    "status": "declined",
                    "recipient_id": offer.proposer_id,
                },
                targets=[offer.proposer_id],
            )

        return Response(
            OfferSerializer(offer, context={"request": request, "match": match}).data
        )


class MatchChatEligibilityView(APIView):
    """Whether the caller may open chat for this match.

    Chat is gated on funding for the match's accepted offer: V1 checks the
    Deal's ``funded_at`` and legacy matches check a succeeded PaymentIntent.
    No funding, no chat. This protects both parties (no pre-payment harassment
    funnel) and matches our user-privacy obligation -- counterparty PII flows
    only after both have committed money + acceptance.

    Returned shape is stable so the Go chat-service can call it before
    upgrading a WebSocket without parsing free-form errors:

      { "eligible": bool, "reason": str, "match_id": int }

    Reasons (caller may surface verbatim):
      ok                    -- chat allowed
      not_a_party           -- caller is not sender/traveler on this match
      no_accepted_offer     -- match has no accepted offer yet
      payment_pending       -- accepted offer exists but its payment is not funded
      match_closed          -- match cancelled / expired
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, pk: int) -> Response:
        match = get_object_or_404(
            Match.objects.select_related("parcel").only(
                "id",
                "sender_id",
                "traveler_id",
                "status",
                "journey_id",
                "parcel__kind",
            ),
            pk=pk,
        )
        # 200 with eligible=false (not 403) -- caller may be the Go chat-service
        # calling on behalf of a user; we want a uniform shape it can cache.
        eligible, reason = chat_eligibility(match, request.user.id)
        return Response({"eligible": eligible, "reason": reason, "match_id": match.id})


class OfferWithdrawView(APIView):
    """Proposer withdraws their own pending offer."""

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: int) -> Response:
        with transaction.atomic():
            initial_offer = get_object_or_404(
                Offer.objects.select_related("match__parcel"), pk=pk
            )
            match = get_object_or_404(
                Match.objects.select_for_update(no_key=True), pk=initial_offer.match_id
            )
            offer = get_object_or_404(
                Offer.objects.select_for_update(no_key=True).select_related("match"),
                pk=initial_offer.pk,
            )
            if offer.proposer_id != request.user.id:
                return _domain_error(
                    code="not_authorized",
                    detail="Only the proposer may withdraw this offer.",
                    status_code=http.HTTP_403_FORBIDDEN,
                )
            if initial_offer.match.parcel.kind == ParcelRequest.Kind.PRODUCT:
                return _product_retired_response()
            if offer.status != Offer.Status.PENDING:
                return _domain_error(
                    code="offer_not_pending",
                    detail="The offer is no longer pending.",
                    status_code=http.HTTP_409_CONFLICT,
                    offer_status=offer.status,
                )
            if match.status != Match.Status.PENDING:
                return _domain_error(
                    code="match_not_pending",
                    detail="The match is no longer pending.",
                    status_code=http.HTTP_409_CONFLICT,
                    match_status=match.status,
                )

            offer.status = Offer.Status.WITHDRAWN
            offer.responded_at = timezone.now()
            offer.save(update_fields=["status", "responded_at", "updated_at"])
            if offer.economics_version == Offer.EconomicsVersion.V1_EUR:
                match.status = Match.Status.CANCELLED
                match.save(update_fields=["status", "updated_at"])
            MatchEvent.objects.create(
                match=offer.match,
                offer=offer,
                actor=request.user,
                kind=MatchEvent.Kind.OFFER_WITHDRAWN,
                payload={},
            )
            recipient = (
                offer.match.sender_id
                if request.user.id == offer.match.traveler_id
                else offer.match.traveler_id
            )
            redis_bus.publish_after_commit(
                channels.OFFER_UPDATED,
                {
                    **match_resources(match),
                    "offer_id": offer.id,
                    "status": "withdrawn",
                    "recipient_id": recipient,
                },
                targets=[recipient],
            )

        return Response(
            OfferSerializer(offer, context={"request": request, "match": match}).data
        )
