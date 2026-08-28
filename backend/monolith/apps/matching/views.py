"""Matching API.

Endpoints:
  GET  /api/matches                          — list (mine, ?role=sender|traveler, ?status=)
  GET  /api/matches/<id>                     — detail (party-only)
  POST /api/matches/apply                    — traveler creates Match + first Offer
  POST /api/matches/apply-to-trip            — sender applies existing parcel to a trip
  POST /api/matches/<id>/cancel              — either party cancels (only while pending)
  GET  /api/matches/<id>/offers              — list offers on a match (party-only)
  POST /api/matches/<id>/offers/counter      — counter the current pending offer
  POST /api/offers/<id>/accept               — counterparty accepts (locks pricing)
  POST /api/offers/<id>/decline              — counterparty declines
  POST /api/offers/<id>/withdraw             — proposer withdraws their own offer

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
from apps.core.pricing import quote_delivery, quote_product
from apps.parcels.models import ParcelRequest
from apps.trips.models import Trip

from .models import Match, MatchEvent, Offer
from .serializers import (
    CounterOfferSerializer,
    MatchSerializer,
    OfferSerializer,
    SenderApplySerializer,
    TravelerApplySerializer,
)
from .services import chat_eligibility


# ---------- helpers ----------


def _quote_for_parcel(parcel: ParcelRequest, base_amount_dzd: int | None) -> dict:
    """Run the pricing engine for the parcel kind, return frozen-fields dict.

    `base_amount_dzd` semantics differ by kind:
      delivery: traveler's asking payout. Defaults to the sender's posted base.
      product:  product price the traveler will pay at the store.
                Defaults to the sender's posted product price.

    Returns dict suitable for `Offer.objects.create(**fields)`:
      base_amount_dzd, base_fee_dzd, commission_dzd, total_dzd
    """
    if parcel.kind == ParcelRequest.Kind.DELIVERY:
        # Lazy import to avoid circular issues at startup.
        from apps.parcels.models import DeliveryRequest

        delivery = DeliveryRequest.objects.get(pk=parcel.pk)
        amount = base_amount_dzd if base_amount_dzd is not None else delivery.base_amount_dzd
        q = quote_delivery(amount)
        return {
            "base_amount_dzd": q.base_amount_dzd,
            "base_fee_dzd": 0,
            "commission_dzd": q.commission_dzd,
            "total_dzd": q.total_dzd,
            "economics_version": Offer.EconomicsVersion.LEGACY_DZD,
            "currency": Offer.Currency.DZD,
        }

    # product
    from apps.parcels.models import ProductRequest

    product = ProductRequest.objects.get(pk=parcel.pk)
    amount = base_amount_dzd if base_amount_dzd is not None else product.product_price_dzd
    q = quote_product(amount)
    return {
        "base_amount_dzd": q.product_price_dzd,
        "base_fee_dzd": q.base_fee_dzd,
        "commission_dzd": q.commission_dzd,
        "total_dzd": q.total_dzd,
        "economics_version": Offer.EconomicsVersion.LEGACY_DZD,
        "currency": Offer.Currency.DZD,
    }


def _is_party(match: Match, user_id: int) -> bool:
    return user_id in (match.sender_id, match.traveler_id)


def _product_retired_response() -> Response:
    return _domain_error(
        code="product_request_retired",
        detail="ProductRequest/Kaba business flows are retired in ShipTrip V1.",
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
    return (
        _match_read_queryset()
        .get(pk=pk)
    )


def _match_read_queryset():
    return Match.objects.select_related(
        "parcel",
        "parcel__deliveryrequest",
        "parcel__deliveryrequest__pickup_location",
        "parcel__deliveryrequest__delivery_location",
        "trip",
        "sender",
        "traveler",
        "deal",
    ).prefetch_related(
        Prefetch(
            "offers",
            queryset=Offer.objects.order_by("-created_at"),
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
        if (s := request.query_params.get("status")):
            qs = qs.filter(status=s)
        return Response(
            MatchSerializer(
                qs.distinct()[:100], many=True, context={"request": request}
            ).data
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
                {"detail": "ProductRequest history is admin-only in ShipTrip V1."},
                status=http.HTTP_410_GONE,
            )
        if not _is_party(match, request.user.id):
            return Response(
                {"detail": "Not a party to this match."}, status=http.HTTP_403_FORBIDDEN
            )
        return Response(MatchSerializer(match, context={"request": request}).data)


class TravelerApplyView(APIView):
    """Traveler applies to carry a parcel.

    Creates Match + first Offer in one transaction. The traveler is the
    proposer; the sender is the one who must accept/decline/counter.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        s = TravelerApplySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data

        parcel = get_object_or_404(ParcelRequest, pk=d["parcel_id"])
        trip = get_object_or_404(Trip, pk=d["trip_id"])

        if trip.traveler_id != request.user.id:
            return Response(
                {"detail": "Only the trip's traveler can apply with it."},
                status=http.HTTP_403_FORBIDDEN,
            )
        if parcel.sender_id == request.user.id:
            return Response(
                {"detail": "Cannot apply to your own parcel."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        if parcel.status != ParcelRequest.Status.OPEN:
            return Response(
                {"detail": f"Parcel is not open (status={parcel.status})."},
                status=http.HTTP_409_CONFLICT,
            )
        if trip.status not in {Trip.Status.DRAFT, Trip.Status.ACTIVE}:
            return Response(
                {"detail": f"Trip is not bookable (status={trip.status})."},
                status=http.HTTP_409_CONFLICT,
            )
        if (parcel.origin_id, parcel.destination_id) != (trip.origin_id, trip.destination_id):
            return Response(
                {"detail": "Parcel and trip must share origin and destination."},
                status=http.HTTP_400_BAD_REQUEST,
            )

        pricing = _quote_for_parcel(parcel, d.get("base_amount_dzd"))

        with transaction.atomic():
            # Re-check uniqueness inside the txn — partial unique index will
            # also catch races. Friendly 409 first.
            existing = Match.objects.filter(
                parcel=parcel, trip=trip, status=Match.Status.PENDING
            ).first()
            if existing is not None:
                return Response(
                    {"detail": "A pending match already exists.", "match_id": existing.id},
                    status=http.HTTP_409_CONFLICT,
                )

            match = Match.objects.create(
                parcel=parcel,
                trip=trip,
                sender_id=parcel.sender_id,
                traveler_id=trip.traveler_id,
                status=Match.Status.PENDING,
            )
            offer = Offer.objects.create(
                match=match,
                proposed_by=Offer.ProposedBy.TRAVELER,
                proposer=request.user,
                note=d.get("note", ""),
                **pricing,
            )
            MatchEvent.objects.create(
                match=match,
                offer=offer,
                actor=request.user,
                kind=MatchEvent.Kind.MATCH_CREATED,
                payload={"trip_id": trip.id, "parcel_id": parcel.id},
            )
            MatchEvent.objects.create(
                match=match,
                offer=offer,
                actor=request.user,
                kind=MatchEvent.Kind.OFFER_CREATED,
                payload={"by": "traveler", "total_dzd": offer.total_dzd},
            )

            redis_bus.publish_after_commit(
                channels.MATCH_CREATED,
                {
                    "match_id": match.id,
                    "parcel_id": parcel.id,
                    "trip_id": trip.id,
                    "sender_id": match.sender_id,
                    "traveler_id": match.traveler_id,
                },
                targets=[match.sender_id, match.traveler_id],
            )
            redis_bus.publish_after_commit(
                channels.OFFER_CREATED,
                {
                    "match_id": match.id,
                    "offer_id": offer.id,
                    "proposed_by": offer.proposed_by,
                    "total_dzd": offer.total_dzd,
                    "recipient_id": match.sender_id,
                },
                targets=[match.sender_id],
            )

        return Response(
            MatchSerializer(
                _refetch_match(match.pk), context={"request": request}
            ).data,
            status=http.HTTP_201_CREATED,
        )


class SenderApplyView(APIView):
    """Sender applies an existing parcel to one specific traveler's trip.

    The mirror image of `TravelerApplyView`: the sender is the proposer and
    the traveler must accept/decline/counter. This is what makes a suggested
    trip actionable — the parcel is already posted, so the sender picks a
    trip instead of filling the request form again.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        s = SenderApplySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data

        parcel = get_object_or_404(ParcelRequest, pk=d["parcel_id"])
        trip = get_object_or_404(Trip, pk=d["trip_id"])

        if parcel.sender_id != request.user.id:
            return Response(
                {"detail": "Only the parcel's sender can apply with it."},
                status=http.HTTP_403_FORBIDDEN,
            )
        if trip.traveler_id == request.user.id:
            return Response(
                {"detail": "Cannot apply to your own trip."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        if parcel.status != ParcelRequest.Status.OPEN:
            return Response(
                {"detail": f"Parcel is not open (status={parcel.status})."},
                status=http.HTTP_409_CONFLICT,
            )
        if trip.status not in {Trip.Status.DRAFT, Trip.Status.ACTIVE}:
            return Response(
                {"detail": f"Trip is not bookable (status={trip.status})."},
                status=http.HTTP_409_CONFLICT,
            )
        if (parcel.origin_id, parcel.destination_id) != (trip.origin_id, trip.destination_id):
            return Response(
                {"detail": "Parcel and trip must share origin and destination."},
                status=http.HTTP_400_BAD_REQUEST,
            )

        pricing = _quote_for_parcel(parcel, d.get("base_amount_dzd"))

        with transaction.atomic():
            existing = Match.objects.filter(
                parcel=parcel, trip=trip, status=Match.Status.PENDING
            ).first()
            if existing is not None:
                return Response(
                    {"detail": "A pending match already exists.", "match_id": existing.id},
                    status=http.HTTP_409_CONFLICT,
                )

            # Reaching out to one named traveler makes this a direct request,
            # not a broadcast — and CounterOfferView only permits countering on
            # direct requests. Without this the traveler could accept or decline
            # but never negotiate, which is precisely the flow the sender is
            # opening here. Only set it when the parcel is still un-targeted so
            # we never retarget a parcel the sender aimed elsewhere.
            if parcel.target_traveler_id is None:
                parcel.target_traveler_id = trip.traveler_id
                parcel.save(update_fields=["target_traveler", "updated_at"])

            match = Match.objects.create(
                parcel=parcel,
                trip=trip,
                sender_id=parcel.sender_id,
                traveler_id=trip.traveler_id,
                status=Match.Status.PENDING,
            )
            offer = Offer.objects.create(
                match=match,
                proposed_by=Offer.ProposedBy.SENDER,
                proposer=request.user,
                note=d.get("note", ""),
                **pricing,
            )
            MatchEvent.objects.create(
                match=match,
                offer=offer,
                actor=request.user,
                kind=MatchEvent.Kind.MATCH_CREATED,
                payload={"trip_id": trip.id, "parcel_id": parcel.id, "directed": True},
            )
            MatchEvent.objects.create(
                match=match,
                offer=offer,
                actor=request.user,
                kind=MatchEvent.Kind.OFFER_CREATED,
                payload={"by": "sender", "total_dzd": offer.total_dzd},
            )

            redis_bus.publish_after_commit(
                channels.MATCH_CREATED,
                {
                    "match_id": match.id,
                    "parcel_id": parcel.id,
                    "trip_id": trip.id,
                    "sender_id": match.sender_id,
                    "traveler_id": match.traveler_id,
                },
                targets=[match.sender_id, match.traveler_id],
            )
            # The traveler is the one who must respond, so they get the ping.
            redis_bus.publish_after_commit(
                channels.OFFER_CREATED,
                {
                    "match_id": match.id,
                    "offer_id": offer.id,
                    "proposed_by": offer.proposed_by,
                    "total_dzd": offer.total_dzd,
                    "recipient_id": match.traveler_id,
                },
                targets=[match.traveler_id],
            )

        return Response(
            MatchSerializer(
                _refetch_match(match.pk), context={"request": request}
            ).data,
            status=http.HTTP_201_CREATED,
        )


class MatchCancelView(APIView):
    """Either party cancels a Match while it's still pending."""

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: int) -> Response:
        with transaction.atomic():
            match = get_object_or_404(
                Match.objects.select_for_update().select_related("parcel"), pk=pk
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
                    "match_id": match.id,
                    "status": "cancelled",
                    "recipient_id": recipient,
                },
                targets=[recipient],
            )

        return Response(
            MatchSerializer(
                _refetch_match(match.pk), context={"request": request}
            ).data
        )


class OfferListView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, pk: int) -> Response:
        match = get_object_or_404(Match.objects.select_related("parcel"), pk=pk)
        if not _is_party(match, request.user.id):
            return Response({"detail": "Not a party."}, status=http.HTTP_403_FORBIDDEN)
        if match.parcel.kind == ParcelRequest.Kind.PRODUCT:
            return _product_retired_response()
        offers = match.offers.all()
        return Response(
            OfferSerializer(
                offers, many=True, context={"request": request, "match": match}
            ).data
        )


class CounterOfferView(APIView):
    """Counter the current pending offer.

    Only the side that did NOT propose the current pending offer can counter.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: int) -> Response:
        s = CounterOfferSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data

        with transaction.atomic():
            # Lock the match and its current pending offer before validating
            # the state machine. This prevents two counters from both
            # replacing the same parent offer.
            match = get_object_or_404(
                Match.objects.select_for_update().select_related("parcel"), pk=pk
            )
            if not _is_party(match, request.user.id):
                return Response(
                    {"detail": "Not a party."}, status=http.HTTP_403_FORBIDDEN
                )
            if match.status != Match.Status.PENDING:
                return Response(
                    {"detail": f"Match not pending (status={match.status})."},
                    status=http.HTTP_409_CONFLICT,
                )

            pending = (
                Offer.objects.select_for_update()
                .filter(match=match, status=Offer.Status.PENDING)
                .first()
            )
            if pending is None:
                return Response(
                    {"detail": "No pending offer to counter."},
                    status=http.HTTP_409_CONFLICT,
                )
            if pending.proposer_id == request.user.id:
                return Response(
                    {"detail": "Cannot counter your own offer; withdraw it instead."},
                    status=http.HTTP_403_FORBIDDEN,
                )
            if match.parcel.target_traveler_id is None:
                return Response(
                    {
                        "detail": "Counter not allowed on broadcast requests; "
                        "accept or decline."
                    },
                    status=http.HTTP_409_CONFLICT,
                )

            my_side = (
                Offer.ProposedBy.SENDER
                if request.user.id == match.sender_id
                else Offer.ProposedBy.TRAVELER
            )
            pricing = _quote_for_parcel(match.parcel, d["base_amount_dzd"])
            now = timezone.now()
            pending.status = Offer.Status.COUNTERED
            pending.responded_at = now
            pending.save(update_fields=["status", "responded_at", "updated_at"])

            child = Offer.objects.create(
                match=match,
                parent_offer=pending,
                proposed_by=my_side,
                proposer=request.user,
                note=d.get("note", ""),
                **pricing,
            )
            MatchEvent.objects.create(
                match=match,
                offer=child,
                actor=request.user,
                kind=MatchEvent.Kind.OFFER_COUNTERED,
                payload={"parent_offer_id": pending.id, "total_dzd": child.total_dzd},
            )
            recipient = (
                match.traveler_id if my_side == Offer.ProposedBy.SENDER else match.sender_id
            )
            redis_bus.publish_after_commit(
                channels.OFFER_CREATED,
                {
                    "match_id": match.id,
                    "offer_id": child.id,
                    "proposed_by": child.proposed_by,
                    "total_dzd": child.total_dzd,
                    "recipient_id": recipient,
                },
                targets=[recipient],
            )

        return Response(
            OfferSerializer(
                child, context={"request": request, "match": match}
            ).data,
            status=http.HTTP_201_CREATED,
        )


class OfferAcceptView(APIView):
    """Counterparty accepts a pending offer.

    Side effects:
      - Offer.status = accepted, Match.status = accepted
      - Parcel.status = matched, Trip.status unchanged (capacity logic later)
      - Publishes `offer.accepted` (and reuses `offer.updated`).

    Payment is handled by `apps/payments` against the now-frozen Offer total.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: int) -> Response:
        with transaction.atomic():
            # The parcel row is the cross-match serialization point. The
            # schema can enforce one accepted offer per Match, but only this
            # lock can ensure that two different Matches for the same parcel
            # are not accepted concurrently.
            initial_offer = get_object_or_404(
                Offer.objects.select_related("match"), pk=pk
            )
            parcel = get_object_or_404(
                ParcelRequest.objects.select_for_update(),
                pk=initial_offer.match.parcel_id,
            )
            match = get_object_or_404(
                Match.objects.select_for_update().select_related("trip"),
                pk=initial_offer.match_id,
            )
            offer = get_object_or_404(
                Offer.objects.select_for_update(), pk=initial_offer.pk
            )

            if not _is_party(match, request.user.id):
                return Response(
                    {"detail": "Not a party."}, status=http.HTTP_403_FORBIDDEN
                )
            if offer.proposer_id == request.user.id:
                return Response(
                    {"detail": "Cannot accept your own offer."},
                    status=http.HTTP_403_FORBIDDEN,
                )
            if offer.status != Offer.Status.PENDING:
                return Response(
                    {"detail": f"Offer not pending (status={offer.status})."},
                    status=http.HTTP_409_CONFLICT,
                )
            if match.status != Match.Status.PENDING:
                return Response(
                    {"detail": f"Match not pending (status={match.status})."},
                    status=http.HTTP_409_CONFLICT,
                )
            if parcel.status != ParcelRequest.Status.OPEN:
                return Response(
                    {"detail": "Parcel request is already matched or closed."},
                    status=http.HTTP_409_CONFLICT,
                )

            now = timezone.now()
            offer.status = Offer.Status.ACCEPTED
            offer.responded_at = now
            offer.save(update_fields=["status", "responded_at", "updated_at"])

            match.status = Match.Status.ACCEPTED
            match.save(update_fields=["status", "updated_at"])

            parcel.status = ParcelRequest.Status.MATCHED
            parcel.save(update_fields=["status", "updated_at"])

            MatchEvent.objects.create(
                match=match,
                offer=offer,
                actor=request.user,
                kind=MatchEvent.Kind.OFFER_ACCEPTED,
                payload={"total_dzd": offer.total_dzd},
            )
            redis_bus.publish_after_commit(
                channels.OFFER_ACCEPTED,
                {
                    "match_id": match.id,
                    "offer_id": offer.id,
                    "parcel_id": match.parcel_id,
                    "trip_id": match.trip_id,
                    "sender_id": match.sender_id,
                    "traveler_id": match.traveler_id,
                    "total_dzd": offer.total_dzd,
                },
                targets=[match.sender_id, match.traveler_id],
            )

        return Response(
            OfferSerializer(
                offer, context={"request": request, "match": match}
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
                Match.objects.select_for_update(), pk=initial_offer.match_id
            )
            offer = get_object_or_404(
                Offer.objects.select_for_update(), pk=initial_offer.pk
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
                    "match_id": match.id,
                    "offer_id": offer.id,
                    "status": "declined",
                    "recipient_id": offer.proposer_id,
                },
                targets=[offer.proposer_id],
            )

        return Response(
            OfferSerializer(
                offer, context={"request": request, "match": match}
            ).data
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
        return Response(
            {"eligible": eligible, "reason": reason, "match_id": match.id}
        )


class OfferWithdrawView(APIView):
    """Proposer withdraws their own pending offer."""

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: int) -> Response:
        with transaction.atomic():
            initial_offer = get_object_or_404(
                Offer.objects.select_related("match__parcel"), pk=pk
            )
            match = get_object_or_404(
                Match.objects.select_for_update(), pk=initial_offer.match_id
            )
            offer = get_object_or_404(
                Offer.objects.select_for_update().select_related("match"),
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
                    "match_id": offer.match_id,
                    "offer_id": offer.id,
                    "status": "withdrawn",
                    "recipient_id": recipient,
                },
                targets=[recipient],
            )

        return Response(
            OfferSerializer(
                offer, context={"request": request, "match": match}
            ).data
        )
