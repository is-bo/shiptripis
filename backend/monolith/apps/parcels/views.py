"""Parcels API.

Endpoints:
  GET  /api/parcels                    — list (mine, ?status=, ?kind=)
  POST /api/parcels/delivery           — create a delivery request
  POST /api/parcels/product            — create a product request
  GET  /api/parcels/<id>               — retrieve
  POST /api/parcels/<id>/cancel        — cancel (owner only, while open)

Per CLAUDE.md G6: every state change publishes via
`redis_bus.publish_after_commit`.
"""

from __future__ import annotations

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import channels, redis_bus
from apps.core.storage import ext_for_content_type, make_key, put_object
from django.conf import settings
from rest_framework.parsers import MultiPartParser

from .models import DeliveryRequest, ParcelMedia, ParcelRequest, ProductRequest
from .serializers import (
    DeliveryCreateSerializer,
    ParcelRequestSerializer,
    ProductCreateSerializer,
)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MiB cap, V1 (client should pre-resize)


def _refetch(pk: int) -> ParcelRequest:
    return (
        ParcelRequest.objects.select_related("origin", "destination")
        .prefetch_related("media")
        .get(pk=pk)
    )


def _auto_match_targeted_traveler(parcel: ParcelRequest) -> None:
    # When a sender directs a parcel at a specific traveler, find that
    # traveler's first bookable trip on the same corridor and create a
    # sender-proposed Match + Offer. Without this the parcel sits idle and
    # the traveler never sees it. If no trip matches, the parcel still lives
    # as a targeted broadcast (no Match yet) — the traveler can apply later
    # when they post a trip on the corridor.
    if parcel.target_traveler_id is None:
        return
    from apps.matching.models import Match, MatchEvent, Offer
    from apps.matching.views import _quote_for_parcel
    from apps.trips.models import Trip

    trip = (
        Trip.objects.filter(
            traveler_id=parcel.target_traveler_id,
            origin_id=parcel.origin_id,
            destination_id=parcel.destination_id,
            status__in=[Trip.Status.DRAFT, Trip.Status.ACTIVE],
        )
        .order_by("departure_at")
        .first()
    )
    if trip is None:
        return

    pricing = _quote_for_parcel(parcel, None)
    match = Match.objects.create(
        parcel=parcel,
        trip=trip,
        sender_id=parcel.sender_id,
        traveler_id=parcel.target_traveler_id,
        status=Match.Status.PENDING,
    )
    offer = Offer.objects.create(
        match=match,
        proposed_by=Offer.ProposedBy.SENDER,
        proposer_id=parcel.sender_id,
        note="",
        **pricing,
    )
    MatchEvent.objects.create(
        match=match,
        offer=offer,
        actor_id=parcel.sender_id,
        kind=MatchEvent.Kind.MATCH_CREATED,
        payload={"trip_id": trip.id, "parcel_id": parcel.id, "directed": True},
    )
    MatchEvent.objects.create(
        match=match,
        offer=offer,
        actor_id=parcel.sender_id,
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


class ParcelListView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        qs = (
            ParcelRequest.objects.filter(sender=request.user)
            .select_related("origin", "destination")
            .prefetch_related("media")
        )
        if (s := request.query_params.get("status")):
            qs = qs.filter(status=s)
        if (k := request.query_params.get("kind")):
            qs = qs.filter(kind=k)
        return Response(ParcelRequestSerializer(qs, many=True).data)


class OpenParcelSearchView(APIView):
    """Public open-parcel feed for travelers looking for shipments to carry.

    Returns OPEN parcels not owned by the caller. Filters:
      ?origin=ALG&destination=CDG     IATA codes
      ?max_weight_kg=5                integer (parcel weight <= cap)
      ?kind=delivery|product
    Results ordered newest-first; capped at 100 rows.
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        qs = (
            ParcelRequest.objects.filter(status=ParcelRequest.Status.OPEN)
            .exclude(sender=request.user)
            .select_related("origin", "destination")
            .prefetch_related("media")
        )
        if (o := request.query_params.get("origin")):
            qs = qs.filter(origin_id=o.upper())
        if (d := request.query_params.get("destination")):
            qs = qs.filter(destination_id=d.upper())
        if (k := request.query_params.get("kind")):
            qs = qs.filter(kind=k)
        if (w := request.query_params.get("max_weight_kg")):
            try:
                qs = qs.filter(weight_kg__lte=int(w))
            except ValueError:
                pass
        qs = qs.order_by("-created_at")[:100]
        return Response(ParcelRequestSerializer(qs, many=True).data)


class DeliveryCreateView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        s = DeliveryCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data

        with transaction.atomic():
            parcel = DeliveryRequest.objects.create(
                sender=request.user,
                kind=ParcelRequest.Kind.DELIVERY,
                origin_id=d["origin"],
                destination_id=d["destination"],
                pickup_city=d.get("pickup_city", ""),
                delivery_city=d.get("delivery_city", ""),
                weight_kg=d["weight_kg"],
                item_type=d["item_type"],
                description=d.get("description", ""),
                deadline_at=d.get("deadline_at"),
                target_traveler_id=d.get("target_traveler_id"),
                base_amount_dzd=d["base_amount_dzd"],
            )
            redis_bus.publish_after_commit(
                channels.PARCEL_CREATED,
                {
                    "parcel_id": parcel.id,
                    "kind": parcel.kind,
                    "sender_id": request.user.id,
                    "origin": parcel.origin_id,
                    "destination": parcel.destination_id,
                },
                targets=[request.user.id],
            )
            _auto_match_targeted_traveler(parcel)

        return Response(
            ParcelRequestSerializer(_refetch(parcel.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class ProductCreateView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        s = ProductCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data

        with transaction.atomic():
            parcel = ProductRequest.objects.create(
                sender=request.user,
                kind=ParcelRequest.Kind.PRODUCT,
                origin_id=d["origin"],
                destination_id=d["destination"],
                pickup_city=d.get("pickup_city", ""),
                delivery_city=d.get("delivery_city", ""),
                weight_kg=d["weight_kg"],
                item_type=d["item_type"],
                description=d.get("description", ""),
                deadline_at=d.get("deadline_at"),
                target_traveler_id=d.get("target_traveler_id"),
                product_url=d.get("product_url", ""),
                store_name=d.get("store_name", ""),
                product_price_dzd=d["product_price_dzd"],
            )
            redis_bus.publish_after_commit(
                channels.PARCEL_CREATED,
                {
                    "parcel_id": parcel.id,
                    "kind": parcel.kind,
                    "sender_id": request.user.id,
                    "origin": parcel.origin_id,
                    "destination": parcel.destination_id,
                },
                targets=[request.user.id],
            )
            _auto_match_targeted_traveler(parcel)

        return Response(
            ParcelRequestSerializer(_refetch(parcel.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class ParcelDetailView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, pk: int) -> Response:
        parcel = get_object_or_404(
            ParcelRequest.objects.select_related("origin", "destination", "sender")
            .prefetch_related("media"),
            pk=pk,
        )
        return Response(ParcelRequestSerializer(parcel).data)


class ParcelCancelView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: int) -> Response:
        parcel = get_object_or_404(ParcelRequest, pk=pk)
        if parcel.sender_id != request.user.id:
            return Response(
                {"detail": "Only the sender can cancel."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if parcel.status not in {ParcelRequest.Status.OPEN, ParcelRequest.Status.MATCHED}:
            return Response(
                {"detail": f"Cannot cancel a parcel in status '{parcel.status}'."},
                status=status.HTTP_409_CONFLICT,
            )
        with transaction.atomic():
            parcel.status = ParcelRequest.Status.CANCELLED
            parcel.save(update_fields=["status", "updated_at"])
            redis_bus.publish_after_commit(
                channels.PARCEL_CANCELLED,
                {"parcel_id": parcel.id, "sender_id": parcel.sender_id},
                targets=[parcel.sender_id],
            )
        return Response(ParcelRequestSerializer(_refetch(parcel.pk)).data)


class DeliveryQuoteView(APIView):
    """Non-binding weight + route price suggestion for a delivery.

    GET /api/parcels/quote/delivery?weight_kg=3&origin=ALG&destination=CDG

    Returns the suggested traveler payout + sender total, plus a soft
    floor/ceiling band the UI uses to warn on outlier offers. Authenticated
    so we keep our pricing curve out of the public domain; rate-limited
    naturally by DRF defaults.
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        from apps.core.pricing import suggest_delivery_quote
        from apps.trips.models import Airport

        try:
            weight_kg = int(request.query_params.get("weight_kg", ""))
        except (TypeError, ValueError):
            return Response(
                {"detail": "weight_kg must be a positive integer."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if weight_kg < 1 or weight_kg > 50:
            return Response(
                {"detail": "weight_kg must be between 1 and 50."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        origin_iata = (request.query_params.get("origin") or "").upper()
        dest_iata = (request.query_params.get("destination") or "").upper()
        origin_country = ""
        dest_country = ""
        if origin_iata:
            o = Airport.objects.filter(iata=origin_iata).only("country").first()
            if o:
                origin_country = o.country
        if dest_iata:
            d = Airport.objects.filter(iata=dest_iata).only("country").first()
            if d:
                dest_country = d.country

        q = suggest_delivery_quote(
            weight_kg=weight_kg,
            origin_country=origin_country,
            destination_country=dest_country,
        )
        return Response(
            {
                "weight_kg": q.weight_kg,
                "suggested_base_dzd": q.suggested_base_dzd,
                "suggested_total_dzd": q.suggested_total_dzd,
                "min_floor_dzd": q.min_floor_dzd,
                "max_ceiling_dzd": q.max_ceiling_dzd,
                "route_multiplier_x100": q.route_multiplier_x100,
                "currency": "DZD",
            }
        )


class ParcelMediaUploadView(APIView):
    permission_classes = (IsAuthenticated,)
    parser_classes = (MultiPartParser,)

    def post(self, request: Request, pk: int) -> Response:
        parcel = get_object_or_404(ParcelRequest, pk=pk)
        if parcel.sender_id != request.user.id:
            return Response(
                {"detail": "Only the sender can attach photos."},
                status=status.HTTP_403_FORBIDDEN,
            )
        f = request.FILES.get("photo")
        if f is None:
            return Response(
                {"detail": "Send the file under the 'photo' field."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if f.size > MAX_UPLOAD_BYTES:
            return Response(
                {"detail": "File exceeds 10 MiB."},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        ext = ext_for_content_type(f.content_type or "")
        if ext is None:
            return Response(
                {"detail": "Only JPEG / PNG / WebP images are allowed."},
                status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )
        body = f.read()
        bucket = settings.S3_BUCKET_PARCEL
        key = make_key(f"parcels/{parcel.id}", ext)
        put_object(
            bucket=bucket, key=key, body=body, content_type=f.content_type
        )
        media = ParcelMedia.objects.create(
            parcel=parcel,
            bucket=bucket,
            object_key=key,
            content_type=f.content_type,
            bytes=len(body),
        )
        return Response(
            {
                "id": media.id,
                "bucket": media.bucket,
                "object_key": media.object_key,
                "content_type": media.content_type,
                "bytes": media.bytes,
            },
            status=status.HTTP_201_CREATED,
        )
