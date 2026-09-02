from __future__ import annotations

from django.db.models import Prefetch, Q, Subquery
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination

from .geography import normalize_search_name
from .geography_serializers import GeographyCountrySerializer, GeographyPlaceSerializer
from .models import AirportLocalityMapping, Country, Place, PlaceAlternateName


class GeographyPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


class GeographyCountryListView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request: Request) -> Response:
        countries = Country.objects.filter(active=True).order_by("name", "code")[:100]
        return Response(GeographyCountrySerializer(countries, many=True).data)


class GeographyPlaceSearchView(APIView):
    permission_classes = (AllowAny,)
    pagination_class = GeographyPagination

    def get(self, request: Request) -> Response:
        query = request.query_params.get("q", "").strip()
        country = request.query_params.get("country", "").strip().upper()
        place_type = request.query_params.get("place_type", "").strip()
        parent = request.query_params.get("parent", "").strip()
        active = request.query_params.get("active", "true").strip().casefold()

        if country and (
            len(country) != 2 or not country.isascii() or not country.isalpha()
        ):
            return Response(
                {"detail": "country must be an ISO alpha-2 code."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        place_types = [
            value.strip() for value in place_type.split(",") if value.strip()
        ]
        if any(value not in Place.PlaceType.values for value in place_types):
            return Response(
                {"detail": "Unknown place_type."}, status=status.HTTP_400_BAD_REQUEST
            )
        if parent and (
            not parent.isascii()
            or not parent.isdecimal()
            or len(parent) > 19
            or int(parent) > 9_223_372_036_854_775_807
        ):
            return Response(
                {"detail": "parent must be a place id."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if active not in {"true", "false", "all"}:
            return Response(
                {"detail": "active must be true, false, or all."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        places = Place.objects.select_related("country", "parent")
        places = places.prefetch_related(
            Prefetch(
                "airport_mappings",
                queryset=AirportLocalityMapping.objects.filter(
                    active=True,
                    is_primary=True,
                    relationship_type=AirportLocalityMapping.RelationshipType.SERVED,
                    locality__active=True,
                ).select_related("locality", "locality__parent"),
            )
        )
        if active != "all":
            places = places.filter(active=active == "true")
        if country:
            places = places.filter(country_id=country)
        if place_types:
            if Place.PlaceType.AIRPORT in place_types:
                non_airport_types = [
                    value for value in place_types if value != Place.PlaceType.AIRPORT
                ]
                selectable = Q(place_type__in=non_airport_types) | Q(
                    place_type=Place.PlaceType.AIRPORT,
                    airport_mappings__active=True,
                    airport_mappings__is_primary=True,
                    airport_mappings__relationship_type=AirportLocalityMapping.RelationshipType.SERVED,
                    airport_mappings__locality__active=True,
                )
                places = places.filter(selectable).distinct()
            else:
                places = places.filter(place_type__in=place_types)
        if parent:
            places = places.filter(parent_id=int(parent))
        if query:
            normalized = normalize_search_name(query)
            if not normalized:
                return Response(
                    {"detail": "q must contain searchable letters or numbers."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            name_lookup = (
                {"normalized_name": normalized}
                if len(normalized) == 1
                else {"normalized_name__startswith": normalized}
            )
            canonical_ids = Place.objects.filter(**name_lookup).order_by()
            alternate_ids = PlaceAlternateName.objects.filter(
                active=True, **name_lookup
            ).order_by()
            if active == "true":
                canonical_ids = canonical_ids.filter(active=True)
                alternate_ids = alternate_ids.filter(place__active=True)
            elif active == "false":
                canonical_ids = canonical_ids.filter(active=False)
                alternate_ids = alternate_ids.filter(place__active=False)
            matching_ids = canonical_ids.values_list("pk").union(
                alternate_ids.values_list("place_id")
            )
            places = places.filter(pk__in=Subquery(matching_ids))
        places = places.order_by("name", "id")

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(places, request, view=self)
        serializer = GeographyPlaceSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)
