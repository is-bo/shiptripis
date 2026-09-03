"""Parcels API.

Endpoints:
  GET  /api/parcels                         — list (mine, ?status=, ?kind=)
  POST /api/parcels/media                   — stage the required item photo
  POST /api/parcels/delivery                — legacy airport/DZD compat write
  POST /api/parcels/delivery/v1             — create a canonical-place request
  POST /api/parcels/product                 — retired (410 Gone)
  GET  /api/parcels/<id>                    — retrieve
  POST /api/parcels/<id>/cancel             — cancel (owner only, while open)
  POST /api/parcels/<id>/media              — attach a further photo
  GET  /api/parcels/<id>/media/<mid>/url    — short-lived signed read

Per CLAUDE.md G6: every state change publishes via
`redis_bus.publish_after_commit`.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core import channels, redis_bus
from apps.core.business_settings import NoActiveBusinessSettings
from apps.core.storage import (
    ext_for_content_type,
    image_bytes_match_extension,
    make_key,
    put_object,
    s3_client,
)

from apps.finance.policy import InvalidPaymentPolicy, phase3_policy
from apps.finance.serializers import PaymentOrderSummarySerializer
from apps.finance.services import (
    ensure_posting_deposit_order,
)
from apps.locations.models import AirportLocalityMapping

from .models import DeliveryRequest, ParcelMedia, ParcelRequest
from .serializers import (
    DeliveryV1CreateSerializer,
    ParcelMediaSerializer,
    ParcelRequestSerializer,
)
from .services import (
    ParcelCancellationForbidden,
    ParcelHasDeal,
    ParcelNotCancellable,
    cancel_delivery_request,
)

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MiB cap, V1 (client should pre-resize)


def _error(code: str, detail: str, http_status: int, **extra) -> Response:
    """A refusal the client can branch on without reading English."""

    return Response({"code": code, "detail": detail, **extra}, status=http_status)


class _RejectedUpload(Exception):
    """An image the server will not accept, with the answer already shaped."""

    def __init__(self, response: Response):
        self.response = response


def _read_image_upload(request: Request, *, field: str = "photo"):
    """Validate one uploaded image and return ``(upload, bytes, extension)``.

    Three parcel endpoints accept an image and each has to make the same four
    judgements. Sharing them is not only less code: it is the only way the
    *bytes* check cannot be forgotten on one of them. A declared content type
    is a claim by the caller, so Pillow parses the real header and the
    declaration is believed only when it agrees.
    """

    upload = request.FILES.get(field)
    if upload is None:
        raise _RejectedUpload(
            _error(
                "parcel_photo_missing",
                "Send the file under the '" + field + "' field.",
                status.HTTP_400_BAD_REQUEST,
            )
        )
    if upload.size > MAX_UPLOAD_BYTES:
        raise _RejectedUpload(
            _error(
                "parcel_photo_too_large",
                "File exceeds 10 MiB.",
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                max_bytes=MAX_UPLOAD_BYTES,
            )
        )
    ext = ext_for_content_type(upload.content_type or "")
    if ext is None:
        raise _RejectedUpload(
            _error(
                "parcel_photo_media_type_unsupported",
                "Only JPEG / PNG / WebP images are allowed.",
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )
        )
    body = upload.read()
    if not image_bytes_match_extension(body, ext):
        raise _RejectedUpload(
            _error(
                "parcel_photo_media_type_unsupported",
                "File content is not a valid image of the declared type.",
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )
        )
    return upload, body, ext


def _store_image(*, key_prefix: str, body: bytes, ext: str, content_type: str):
    """Write one image to the private parcel bucket, or refuse cleanly.

    The bucket is ``S3_BUCKET_PARCEL`` — Django's own credential, the same
    private media bucket that already holds flight proof and dispute
    evidence. Emphatically **not** ``S3_BUCKET_KYC``: that bucket belongs to
    the Go KYC service's key, and pointing Django at it is precisely the
    mistake that made every deployed flight-proof upload answer 500 before
    Phase 8F-A. An item photo is marketplace evidence, not identity evidence,
    and the two must not share a credential or a retention policy.
    """

    bucket = settings.S3_BUCKET_PARCEL
    key = make_key(key_prefix, ext)
    try:
        put_object(bucket=bucket, key=key, body=body, content_type=content_type)
    except Exception:
        # The provider's message names buckets, keys and credentials. It goes
        # to the log with the request id and never to the phone.
        logger.exception("parcel photo upload failed", extra={"prefix": key_prefix})
        raise _RejectedUpload(
            _error(
                "parcel_photo_storage_unavailable",
                "Photo storage is temporarily unavailable.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        ) from None
    return bucket, key


def _read_queryset():
    active_mapping = AirportLocalityMapping.objects.filter(
        active=True,
        is_primary=True,
        relationship_type=AirportLocalityMapping.RelationshipType.SERVED,
        locality__active=True,
    ).select_related("locality", "locality__parent")
    return ParcelRequest.objects.select_related(
        "origin",
        "destination",
        "sender",
        "deliveryrequest",
        "deliveryrequest__pickup_location",
        "deliveryrequest__delivery_location",
        "deliveryrequest__pickup_place",
        "deliveryrequest__delivery_place",
        "productrequest",
    ).prefetch_related(
        "media",
        "deliveryrequest__deals",
        Prefetch(
            "deliveryrequest__pickup_place__airport_mappings",
            queryset=active_mapping,
            to_attr="_active_matching_mappings",
        ),
        Prefetch(
            "deliveryrequest__delivery_place__airport_mappings",
            queryset=active_mapping,
            to_attr="_active_matching_mappings",
        ),
    )


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
                deliveryrequest__schema_version__in=(2, 3),
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
                "detail": (
                    "Use POST /api/parcels/delivery/v1 with canonical Place IDs "
                    "and EUR cents. Preferred Location IDs are optional."
                ),
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
        pickup_location = data.get("pickup_location")
        delivery_location = data.get("delivery_location")
        pickup_place = data["pickup_place"]
        delivery_place = data["delivery_place"]

        # Publication timing is a server decision read from versioned policy.
        # In posting-deposit mode the request is created unpublished and only
        # becomes discoverable when a reconciled payment says so — the client
        # never asserts that it paid.
        try:
            payment_policy = phase3_policy()
        except (NoActiveBusinessSettings, InvalidPaymentPolicy) as exc:
            return Response(
                {
                    "code": getattr(exc, "code", "payment_policy_unavailable"),
                    "detail": str(exc),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        deposit_required = payment_policy.deposit_required
        initial_status = (
            ParcelRequest.Status.AWAITING_DEPOSIT
            if deposit_required
            else ParcelRequest.Status.OPEN
        )

        with transaction.atomic():
            # Re-read the staged photo under a row lock. The serializer
            # already checked that it is this sender's and unattached, but
            # two creates racing on one staged id would otherwise both pass
            # validation and the second would silently steal the first
            # request's photo. Locking here makes the loser lose visibly.
            photo = (
                ParcelMedia.objects.select_for_update()
                .filter(
                    pk=data["item_photo_media"].pk,
                    uploaded_by_id=request.user.pk,
                    purpose=ParcelMedia.Purpose.ITEM_PHOTO,
                    parcel__isnull=True,
                )
                .first()
            )
            if photo is None:
                return Response(
                    {
                        "item_photo_media_id": [
                            "This item photo is no longer available. "
                            "Upload the photo again."
                        ],
                        "code": "parcel_item_photo_unavailable",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            parcel = DeliveryRequest.objects.create(
                sender=request.user,
                kind=ParcelRequest.Kind.DELIVERY,
                schema_version=3,
                status=initial_status,
                origin=None,
                destination=None,
                pickup_place=pickup_place,
                delivery_place=delivery_place,
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
            # The photo is attached in the same commit as the request it
            # belongs to. There is therefore no window in which a request
            # exists — published or awaiting its deposit — without the image
            # V1 requires, and no failed upload can leave one behind: a photo
            # that never stored never produced an id to send here.
            photo.parcel_id = parcel.parcelrequest_ptr_id
            photo.save(update_fields=["parcel"])

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
        if parcel.target_traveler_id is not None and request.user.id not in {
            parcel.sender_id,
            parcel.target_traveler_id,
        }:
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


class ParcelItemPhotoStageView(APIView):
    """Upload the required item photo *before* the request exists.

    V1 requires every delivery request to carry a photograph of the actual
    thing being sent, and the order of operations is what makes that rule
    safe rather than merely stated. Creating the request first and uploading
    afterwards leaves a live, discoverable request with no photo every time
    the second call fails — on a corridor whose senders are frequently on a
    poor connection, that is not a rare case. So the photo is stored first,
    and `POST /api/parcels/delivery/v1` consumes the id it returns.

    A staged row belongs to the uploader and to nothing else. It becomes part
    of a request only when a create call claims it, and it is never visible
    to anyone but its uploader until then.

    `idempotency_key` identifies the *file*, not the attempt: a phone that
    times out mid-upload retries with the same key and gets the row the first
    attempt may already have written, instead of leaving an orphan object in
    the bucket for every dropped connection.
    """

    permission_classes = (IsAuthenticated,)
    parser_classes = (MultiPartParser,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "media_upload"

    def post(self, request: Request) -> Response:
        key_value = str(request.data.get("idempotency_key") or "").strip()[:64]
        if key_value:
            existing = ParcelMedia.objects.filter(
                uploaded_by=request.user, idempotency_key=key_value
            ).first()
            if existing is not None:
                return Response(
                    ParcelMediaSerializer(existing).data, status=status.HTTP_200_OK
                )

        try:
            upload, body, ext = _read_image_upload(request)
            bucket, object_key = _store_image(
                key_prefix=f"parcels/staged/{request.user.pk}",
                body=body,
                ext=ext,
                content_type=upload.content_type,
            )
        except _RejectedUpload as rejected:
            return rejected.response

        try:
            media = ParcelMedia.objects.create(
                parcel=None,
                uploaded_by=request.user,
                purpose=ParcelMedia.Purpose.ITEM_PHOTO,
                idempotency_key=key_value,
                bucket=bucket,
                object_key=object_key,
                content_type=upload.content_type,
                bytes=len(body),
            )
        except IntegrityError:
            # Two retries raced. The first one's row is the answer; the object
            # this attempt wrote is an orphan the purge command reclaims.
            media = ParcelMedia.objects.filter(
                uploaded_by=request.user, idempotency_key=key_value
            ).first()
            if media is None:
                raise
            return Response(
                ParcelMediaSerializer(media).data, status=status.HTTP_200_OK
            )
        return Response(
            ParcelMediaSerializer(media).data, status=status.HTTP_201_CREATED
        )


class ParcelMediaUploadView(APIView):
    """Attach a further photo to a request that already exists.

    The item photo does not come through here — it is staged before creation
    and consumed by it. Anything added afterwards is an extra, recorded as
    `attachment` so nothing can mistake it for the required one.
    """

    permission_classes = (IsAuthenticated,)
    parser_classes = (MultiPartParser,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "media_upload"

    def post(self, request: Request, pk: int) -> Response:
        parcel = get_object_or_404(ParcelRequest, pk=pk)
        if parcel.kind == ParcelRequest.Kind.PRODUCT:
            return _error(
                "product_request_retired",
                "ProductRequest is retired and preserved as read-only history.",
                status.HTTP_410_GONE,
            )
        if parcel.sender_id != request.user.id:
            return _error(
                "not_authorized",
                "Only the sender can attach photos.",
                status.HTTP_403_FORBIDDEN,
            )
        try:
            upload, body, ext = _read_image_upload(request)
            bucket, object_key = _store_image(
                key_prefix=f"parcels/{parcel.id}",
                body=body,
                ext=ext,
                content_type=upload.content_type,
            )
        except _RejectedUpload as rejected:
            return rejected.response

        media = ParcelMedia.objects.create(
            parcel=parcel,
            uploaded_by=request.user,
            purpose=ParcelMedia.Purpose.ATTACHMENT,
            bucket=bucket,
            object_key=object_key,
            content_type=upload.content_type,
            bytes=len(body),
        )
        return Response(
            ParcelMediaSerializer(media).data, status=status.HTTP_201_CREATED
        )


def may_view_parcel_media(user, parcel: ParcelRequest) -> bool:
    """Who may read the bytes of a parcel photo.

    An item photo is marketplace information, not identity evidence, so the
    policy is deliberately looser than KYC's and deliberately tighter than
    "public URL":

    * the sender, always — it is their parcel;
    * staff, for support and trust review;
    * the addressee of a targeted request, and nobody else on one;
    * any authenticated user on a request that has actually been published,
      because that is the audience the photo exists for — a traveller
      deciding whether to carry it.

    A request still `awaiting_deposit` has never been published, so its photo
    stays with its sender. Everything above is enforced per read, against a
    private bucket, through a URL that expires in minutes.
    """

    if not user.is_authenticated:
        return False
    if parcel.sender_id == user.id:
        return True
    if user.is_staff:
        return True
    if parcel.target_traveler_id is not None:
        return parcel.target_traveler_id == user.id
    return parcel.status != ParcelRequest.Status.AWAITING_DEPOSIT


class ParcelMediaUrlView(APIView):
    """Issue a short-lived signed URL for one parcel photo.

    The bucket is private and the object key is never serialized, so this is
    the only route from an authorised caller to the bytes. Minutes, not
    hours: a link pasted into a support chat should stop working long before
    the conversation is over.
    """

    permission_classes = (IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "media_upload"

    def get(self, request: Request, pk: int, media_id: int) -> Response:
        parcel = get_object_or_404(ParcelRequest, pk=pk)
        media = get_object_or_404(ParcelMedia, pk=media_id, parcel_id=parcel.pk)
        if not may_view_parcel_media(request.user, parcel):
            return _error(
                "not_authorized",
                "This parcel photo belongs to someone else's request.",
                status.HTTP_403_FORBIDDEN,
            )
        ttl = int(getattr(settings, "PARCEL_MEDIA_URL_TTL_SECONDS", 300) or 300)
        try:
            url = s3_client().generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": media.bucket,
                    "Key": media.object_key,
                    "ResponseContentDisposition": "inline",
                },
                ExpiresIn=ttl,
            )
        except Exception:
            logger.exception(
                "parcel media presign failed",
                extra={"parcel_id": parcel.pk, "parcel_media_id": media.pk},
            )
            return _error(
                "parcel_photo_storage_unavailable",
                "Photo storage is temporarily unavailable.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        response = Response({"url": url, "expires_in": ttl})
        response["Cache-Control"] = "no-store"
        response["Referrer-Policy"] = "no-referrer"
        return response
