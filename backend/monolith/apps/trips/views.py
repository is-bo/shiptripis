"""Trip API.

Endpoints:
  GET  /api/airports                 — list (filter by ?country=DZ)
  GET  /api/trips                    — list (mine, with ?status=active)
  GET  /api/trips/search             — public search (active trips, not mine)
  POST /api/trips                    — create
  GET  /api/trips/<id>               — retrieve (any auth user)
  POST /api/trips/<id>/cancel        — cancel (owner only, while active)

Per CLAUDE.md G6, every Trip lifecycle change publishes via
`redis_bus.publish_after_commit` so the Go services can fan out.
"""

from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import channels, redis_bus
from apps.core.storage import (
    ext_for_content_type,
    image_bytes_match_extension,
    make_key,
    put_object,
)

from .models import Airport, Trip, TripMedia, TripStopover
from .serializers import (
    AirportSerializer,
    TripCreateSerializer,
    TripSerializer,
)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class AirportListView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request: Request) -> Response:
        qs = Airport.objects.all()
        country = request.query_params.get("country")
        if country:
            qs = qs.filter(country=country.upper())
        return Response(AirportSerializer(qs, many=True).data)


class TripListCreateView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        qs = (
            Trip.objects.filter(traveler=request.user)
            .select_related("origin", "destination", "traveler")
            .prefetch_related("stopovers__airport")
        )
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return Response(TripSerializer(qs, many=True).data)

    def post(self, request: Request) -> Response:
        s = TripCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data

        with transaction.atomic():
            trip = Trip.objects.create(
                traveler=request.user,
                origin_id=d["origin"],
                destination_id=d["destination"],
                departure_at=d["departure_at"],
                capacity_kg=d["capacity_kg"],
                flight_number=d.get("flight_number", ""),
                notes=d.get("notes", ""),
            )
            for i, stop in enumerate(d.get("stopovers", [])):
                TripStopover.objects.create(
                    trip=trip,
                    position=i,
                    airport_id=stop["airport"].upper(),
                    arrives_at=stop.get("arrives_at"),
                    departs_at=stop.get("departs_at"),
                )
            redis_bus.publish_after_commit(
                channels.TRIP_CREATED,
                {
                    "trip_id": trip.id,
                    "traveler_id": request.user.id,
                    "origin": trip.origin_id,
                    "destination": trip.destination_id,
                },
                targets=[request.user.id],
            )

        trip = (
            Trip.objects.select_related("origin", "destination", "traveler")
            .prefetch_related("stopovers__airport")
            .get(pk=trip.pk)
        )
        return Response(TripSerializer(trip).data, status=status.HTTP_201_CREATED)


class TripSearchView(APIView):
    """Public trip search for senders looking for travelers.

    Only returns trips in ACTIVE status that are NOT the caller's own. Filters:
      ?origin=ALG&destination=CDG     IATA codes (uppercased)
      ?departure_after=2026-05-20T00:00:00Z   ISO 8601, accepts naive
      ?min_capacity_kg=2              integer
    Results are ordered by earliest departure first; capped at 100 rows.
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        qs = (
            Trip.objects.filter(status=Trip.Status.ACTIVE)
            .exclude(traveler=request.user)
            .select_related("origin", "destination", "traveler")
            .prefetch_related("stopovers__airport")
        )
        if (o := request.query_params.get("origin")):
            qs = qs.filter(origin_id=o.upper())
        if (d := request.query_params.get("destination")):
            qs = qs.filter(destination_id=d.upper())
        if (after := request.query_params.get("departure_after")):
            dt = parse_datetime(after)
            if dt is not None:
                qs = qs.filter(departure_at__gte=dt)
        if (cap := request.query_params.get("min_capacity_kg")):
            try:
                qs = qs.filter(capacity_kg__gte=int(cap))
            except ValueError:
                pass
        qs = qs.order_by("departure_at")[:100]
        return Response(TripSerializer(qs, many=True).data)


class TripDetailView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, pk: int) -> Response:
        trip = get_object_or_404(
            Trip.objects.select_related("origin", "destination", "traveler")
            .prefetch_related("stopovers__airport"),
            pk=pk,
        )
        return Response(TripSerializer(trip).data)


class TripCancelView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: int) -> Response:
        trip = get_object_or_404(Trip, pk=pk)
        if trip.traveler_id != request.user.id:
            return Response(
                {"detail": "Only the trip owner can cancel."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if trip.status not in {Trip.Status.DRAFT, Trip.Status.ACTIVE}:
            return Response(
                {"detail": f"Cannot cancel a trip in status '{trip.status}'."},
                status=status.HTTP_409_CONFLICT,
            )
        with transaction.atomic():
            trip.status = Trip.Status.CANCELLED
            trip.save(update_fields=["status", "updated_at"])
            redis_bus.publish_after_commit(
                channels.TRIP_CANCELLED,
                {"trip_id": trip.id, "traveler_id": trip.traveler_id},
                targets=[trip.traveler_id],
            )
        trip = (
            Trip.objects.select_related("origin", "destination", "traveler")
            .prefetch_related("stopovers__airport")
            .get(pk=trip.pk)
        )
        return Response(TripSerializer(trip).data)


class TripMediaUploadView(APIView):
    permission_classes = (IsAuthenticated,)
    parser_classes = (MultiPartParser,)

    def post(self, request: Request, pk: int) -> Response:
        trip = get_object_or_404(Trip, pk=pk)
        if trip.traveler_id != request.user.id:
            return Response(
                {"detail": "Only the trip owner can attach photos."},
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
        kind = (request.data.get("kind") or "ticket")[:24]
        bucket = settings.S3_BUCKET_PARCEL  # share bucket; key prefix scopes
        key = make_key(f"trips/{trip.id}", ext)
        put_object(
            bucket=bucket, key=key, body=body, content_type=f.content_type
        )
        media = TripMedia.objects.create(
            trip=trip,
            bucket=bucket,
            object_key=key,
            content_type=f.content_type,
            bytes=len(body),
            kind=kind,
        )
        return Response(
            {
                "id": media.id,
                "bucket": media.bucket,
                "object_key": media.object_key,
                "content_type": media.content_type,
                "bytes": media.bytes,
                "kind": media.kind,
            },
            status=status.HTTP_201_CREATED,
        )
