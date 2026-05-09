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

from .models import DeliveryRequest, ParcelRequest, ProductRequest
from .serializers import (
    DeliveryCreateSerializer,
    ParcelRequestSerializer,
    ProductCreateSerializer,
)


def _refetch(pk: int) -> ParcelRequest:
    return (
        ParcelRequest.objects.select_related("origin", "destination")
        .prefetch_related("media")
        .get(pk=pk)
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
            )

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
            )

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
            )
        return Response(ParcelRequestSerializer(_refetch(parcel.pk)).data)
