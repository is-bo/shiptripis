from __future__ import annotations

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Location
from .permissions import IsLocationCreatorOrReadOnly
from .serializers import PrivateLocationSerializer, serialize_location_for_user


def _locations_queryset():
    return Location.objects.select_related("airport", "created_by", "owner")


class LocationListCreateView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        # This collection is an address book, not a globally enumerable place
        # directory. Public route serializers expose other users' coarse
        # locations only in the context of a Journey or DeliveryRequest.
        locations = _locations_queryset().filter(
            Q(owner=request.user)
            | Q(
                owner__isnull=True,
                kind=Location.Kind.AIRPORT,
                coordinates_trusted=True,
            )
        )[:100]
        data = [
            serialize_location_for_user(location, request.user)
            for location in locations
        ]
        return Response(data)

    def post(self, request: Request) -> Response:
        serializer = PrivateLocationSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        location = serializer.save(created_by=request.user, owner=request.user)
        return Response(
            PrivateLocationSerializer(location).data,
            status=status.HTTP_201_CREATED,
        )


class LocationDetailView(APIView):
    permission_classes = (IsAuthenticated, IsLocationCreatorOrReadOnly)

    def get(self, request: Request, pk: int) -> Response:
        location = get_object_or_404(_locations_queryset(), pk=pk)
        self.check_object_permissions(request, location)
        return Response(serialize_location_for_user(location, request.user))
