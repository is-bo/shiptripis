"""Parcels API.

Endpoints:
  GET  /api/parcels                    — list (mine, ?status=, ?kind=)
  POST /api/parcels/delivery           — legacy airport/DZD compatibility write
  POST /api/parcels/delivery/v1        — create a V1 location/EUR delivery request
  POST /api/parcels/product            — retired (410 Gone)
  GET  /api/parcels/<id>               — retrieve
  POST /api/parcels/<id>/cancel        — cancel (owner only, while open)

Per CLAUDE.md G6: every state change publishes via
`redis_bus.publish_after_commit`.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import channels, redis_bus
from apps.core.business_settings import NoActiveBusinessSettings
from apps.core.storage import (
    ext_for_content_type,
    image_bytes_match_extension,
    make_key,
    put_object,
)

from apps.finance.policy import InvalidPaymentPolicy, phase3_policy
from apps.finance.serializers import PaymentOrderSummarySerializer
from apps.finance.services import (
    ensure_posting_deposit_order,
)

from .models import DeliveryRequest, ParcelMedia, ParcelRequest
from .serializers import (
    DeliveryV1CreateSerializer,
    ParcelRequestSerializer,
)
from .services import (
    ParcelCancellationForbidden,
    ParcelHasDeal,
    ParcelNotCancellable,
    cancel_delivery_request,
)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MiB cap, V1 (client should pre-resize)


def _read_queryset():
    return ParcelRequest.objects.select_related(
        "origin",
        "destination",
        "sender",
        "deliveryrequest",
        "deliveryrequest__pickup_location",
        "deliveryrequest__delivery_location",
        "productrequest",
    ).prefetch_related("media", "deliveryrequest__deals")


def _refetch(pk: int) -> ParcelRequest:
    return _read_queryset().get(pk=pk)


def _serialize(parcel, request: Request, *, many: bool = False):
    return ParcelRequestSerializer(
        parcel,
        many=many,
        context={"request": request},
    )


class ParcelListView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        qs = _read_queryset().filter(
            sender=request.user,
            kind=ParcelRequest.Kind.DELIVERY,
        )
        if s := request.query_params.get("status"):
            qs = qs.filter(status=s)
        if k := request.query_params.get("kind"):
            qs = qs.filter(kind=k)
        return Response(_serialize(qs[:100], request, many=True).data)


class OpenParcelSearchView(APIView):
    """Public open-parcel feed for travelers looking for shipments to carry.

    Returns untargeted OPEN delivery requests not owned by the caller. Filters:
      ?max_weight_kg=5                decimal (parcel weight <= cap)
    `?origin=`/`?destination=` IATA filtering is retired and returns 400: V1
    requests carry Locations, not airports. Route-aware discovery lives at
    GET /api/matches/compatible-requests.
    ProductRequest history and targeted requests are never part of this feed.
    Results ordered newest-first; capped at 100 rows.
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        qs = (
            _read_queryset()
            .filter(
                status=ParcelRequest.Status.OPEN,
                kind=ParcelRequest.Kind.DELIVERY,
                deliveryrequest__schema_version=2,
                deadline_at__gt=timezone.now(),
                target_traveler__isnull=True,
            )
            .exclude(sender=request.user)
        )
        # V1 delivery requests are created with origin/destination NULL and are
        # routed by Location instead, so an IATA filter could only ever return
        # an empty list. Reject it loudly rather than answering 200 with a
        # silently impossible result set.
        retired_filters = sorted(
            {"origin", "destination"}.intersection(request.query_params)
        )
        if retired_filters:
            return Response(
                {
                    "code": "airport_filter_retired",
                    "detail": (
                        "Airport origin/destination filtering is retired for V1 "
                        "delivery requests. Use GET /api/matches/compatible-requests."
                    ),
                    "retired_parameters": retired_filters,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if w := request.query_params.get("max_weight_kg"):
            try:
                max_weight = Decimal(w)
                qs = qs.filter(
                    Q(weight_kg__lte=max_weight)
                    | Q(deliveryrequest__actual_weight_kg__lte=max_weight)
                )
            except (InvalidOperation, ValueError):
                pass
        qs = qs.order_by("-created_at")[:100]
        return Response(_serialize(qs, request, many=True).data)


class DeliveryCreateView(APIView):
    """Retired legacy airport/DZD write endpoint."""

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        return Response(
            {
                "code": "legacy_delivery_flow_retired",
                "detail": "Use POST /api/parcels/delivery/v1 with Location IDs and EUR cents.",
            },
            status=status.HTTP_410_GONE,
        )


class DeliveryV1CreateView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        serializer = DeliveryV1CreateSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        pickup_location = data["pickup_location"]
        delivery_location = data["delivery_location"]

        # Publication timing is a server decision read from versioned policy.
        # In posting-deposit mode the request is created unpublished and only
        # becomes discoverable when a reconciled payment says so — the client
        # never asserts that it paid.
        try:
            payment_policy = phase3_policy()
        except (NoActiveBusinessSettings, InvalidPaymentPolicy) as exc:
            return Response(
                {"code": getattr(exc, "code", "payment_policy_unavailable"),
                 "detail": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        deposit_required = payment_policy.deposit_required
        initial_status = (
            ParcelRequest.Status.AWAITING_DEPOSIT
            if deposit_required
            else ParcelRequest.Status.OPEN
        )

        with transaction.atomic():
            parcel = DeliveryRequest.objects.create(
                sender=request.user,
                kind=ParcelRequest.Kind.DELIVERY,
                schema_version=2,
                status=initial_status,
                origin=None,
                destination=None,
                pickup_location=pickup_location,
                delivery_location=delivery_location,
                weight_kg=None,
                item_type=data["category"],
                description=data["description"],
                deadline_at=data["deadline_at"],
                target_traveler=data.get("target_traveler"),
                ready_window_start=data["ready_window_start"],
                ready_window_end=data["ready_window_end"],
                actual_weight_kg=data["actual_weight_kg"],
                length_cm=data.get("length_cm"),
                width_cm=data.get("width_cm"),
                height_cm=data.get("height_cm"),
                declared_value_eur_cents=data["declared_value_eur_cents"],
                traveler_reward_eur_cents=data["traveler_reward_eur_cents"],
                title=data["title"],
                category=data["category"],
                handling_notes=data.get("handling_notes", ""),
                fragile=data.get("fragile", False),
                description_is_accurate=data["description_is_accurate"],
                item_is_legal=data["item_is_legal"],
                no_prohibited_goods=data["no_prohibited_goods"],
                declared_value_is_accurate=data["declared_value_is_accurate"],
                customs_responsibilities_understood=data[
                    "customs_responsibilities_understood"
                ],
                base_amount_dzd=None,
            )
            deposit_order = None
            if deposit_required:
                deposit_order = ensure_posting_deposit_order(
                    delivery_request=parcel, policy=payment_policy
                )
            redis_bus.publish_after_commit(
                channels.PARCEL_CREATED,
                {
                    "parcel_id": parcel.id,
                    "kind": parcel.kind,
                    "sender_id": request.user.id,
                    "schema_version": parcel.schema_version,
                    "currency": "EUR",
                    "status": parcel.status,
                },
                targets=[request.user.id],
            )

        payload = _serialize(_refetch(parcel.pk), request).data
        payload["posting_deposit"] = (
            PaymentOrderSummarySerializer(deposit_order).data
            if deposit_order is not None
            else None
        )
        return Response(payload, status=status.HTTP_201_CREATED)


class ProductCreateView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        return Response(
            {"detail": "ProductRequest creation is retired in ShipTrip V1."},
            status=status.HTTP_410_GONE,
        )


class ParcelDetailView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, pk: int) -> Response:
        parcel = get_object_or_404(
            _read_queryset(),
            pk=pk,
        )
        if parcel.kind == ParcelRequest.Kind.PRODUCT:
            return Response(
                {"detail": "ProductRequest history is admin-only in ShipTrip V1."},
                status=status.HTTP_410_GONE,
            )
        if (
            parcel.target_traveler_id is not None
            and request.user.id not in {parcel.sender_id, parcel.target_traveler_id}
        ):
            return Response(
                {"detail": "This targeted request is private."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(_serialize(parcel, request).data)


class ParcelCancelView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: int) -> Response:
        base = get_object_or_404(ParcelRequest.objects.only("kind"), pk=pk)
        if base.kind == ParcelRequest.Kind.PRODUCT:
            return Response(
                {
                    "detail": "ProductRequest is retired and preserved as read-only history."
                },
                status=status.HTTP_410_GONE,
            )
        try:
            result = cancel_delivery_request(request_id=pk, actor_id=request.user.id)
        except ParcelCancellationForbidden as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ParcelHasDeal as exc:
            return Response(
                {"detail": str(exc), "code": exc.code},
                status=status.HTTP_409_CONFLICT,
            )
        except ParcelNotCancellable as exc:
            return Response(
                {
                    "code": exc.code,
                    "detail": str(exc),
                    "parcel_status": exc.parcel_status,
                },
                status=status.HTTP_409_CONFLICT,
            )
        return Response(_serialize(_refetch(result.parcel_id), request).data)


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
        return Response(
            {
                "code": "legacy_dzd_quote_retired",
                "detail": "DZD pricing is not a ShipTrip V1 marketplace contract.",
            },
            status=status.HTTP_410_GONE,
        )


class ParcelMediaUploadView(APIView):
    permission_classes = (IsAuthenticated,)
    parser_classes = (MultiPartParser,)

    def post(self, request: Request, pk: int) -> Response:
        parcel = get_object_or_404(ParcelRequest, pk=pk)
        if parcel.kind == ParcelRequest.Kind.PRODUCT:
            return Response(
                {
                    "detail": "ProductRequest is retired and preserved as read-only history."
                },
                status=status.HTTP_410_GONE,
            )
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
        if not image_bytes_match_extension(body, ext):
            return Response(
                {"detail": "File content is not a valid image of the declared type."},
                status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )
        bucket = settings.S3_BUCKET_PARCEL
        key = make_key(f"parcels/{parcel.id}", ext)
        put_object(bucket=bucket, key=key, body=body, content_type=f.content_type)
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
