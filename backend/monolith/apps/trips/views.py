"""Trip API.

Endpoints:
  GET  /api/airports                 — list (filter by ?country=DZ)
  GET  /api/trips                    — list (mine, with ?status=active)
  POST /api/trips                    — create
  GET  /api/trips/<id>               — retrieve (any auth user)
  POST /api/trips/<id>/cancel        — cancel (owner only, while active)

Per CLAUDE.md G6, every Trip lifecycle change publishes via
`redis_bus.publish_after_commit` so the Go services can fan out.
"""

from __future__ import annotations

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import channels, redis_bus

from .models import Airport, Trip, TripStopover
from .serializers import (
    AirportSerializer,
    TripCreateSerializer,
    TripSerializer,
)


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
            .select_related("origin", "destination")
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
            )

        trip = (
            Trip.objects.select_related("origin", "destination")
            .prefetch_related("stopovers__airport")
            .get(pk=trip.pk)
        )
        return Response(TripSerializer(trip).data, status=status.HTTP_201_CREATED)


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
            )
        trip = (
            Trip.objects.select_related("origin", "destination")
            .prefetch_related("stopovers__airport")
            .get(pk=trip.pk)
        )
        return Response(TripSerializer(trip).data)
