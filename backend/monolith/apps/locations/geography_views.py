from __future__ import annotations

import math

from django.db.models import Case, IntegerField, Prefetch, Q, Subquery, When
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination

from .geography import normalize_search_name
from .geography_serializers import GeographyCountrySerializer, GeographyPlaceSerializer
from .models import AirportLocalityMapping, Country, Place, PlaceAlternateName


# Search discovery only.  Matching continues to use Place.resolve_matching_locality().
# Eight seeds prevent a broad prefix such as "sa" from expanding through an
# unbounded set of towns, while three airports keeps enrichment useful rather
# than letting it displace direct place matches on a phone-sized result page.
AIRPORT_RECOMMENDATION_SEED_LIMIT = 8
AIRPORT_RECOMMENDATION_LIMIT = 3
NEARBY_AIRPORT_MAX_DISTANCE_KM = 100.0
EARTH_MEAN_RADIUS_KM = 6_371.0088


def _haversine_km(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    """Return deterministic great-circle distance in kilometres."""

    lat_a, lon_a, lat_b, lon_b = map(
        math.radians,
        (latitude_a, longitude_a, latitude_b, longitude_b),
    )
    delta_latitude = lat_b - lat_a
    delta_longitude = lon_b - lon_a
    haversine = (
        math.sin(delta_latitude / 2) ** 2
        + math.cos(lat_a)
        * math.cos(lat_b)
        * math.sin(delta_longitude / 2) ** 2
    )
    return 2 * EARTH_MEAN_RADIUS_KM * math.asin(min(1.0, math.sqrt(haversine)))


def _name_lookup(normalized: str) -> dict[str, str]:
    return (
        {"normalized_name": normalized}
        if len(normalized) == 1
        else {"normalized_name__startswith": normalized}
    )


def _airport_recommendations(
    *,
    normalized: str,
    country: str,
) -> tuple[list[int], list[int], list[int], dict[int, dict]]:
    """Find served airports, then bounded proximity fallbacks, for a place query.

    Explicit active ``SERVED`` mappings win.  Distance is considered only for
    matched localities with no such mapping, never as marketplace identity.
    The only runtime distance scan is over the active selectable airport rows
    in the matched countries (161 rows for the entire V1 catalogue, and 31–49
    when the mobile client's required country filter is present).
    """

    name_lookup = _name_lookup(normalized)
    alternate_locality_ids = PlaceAlternateName.objects.filter(
        active=True,
        place__active=True,
        place__place_type=Place.PlaceType.LOCALITY,
        **name_lookup,
    )
    seed_query = Place.objects.filter(
        Q(**name_lookup) | Q(pk__in=Subquery(alternate_locality_ids.values("place_id"))),
        active=True,
        place_type=Place.PlaceType.LOCALITY,
    )
    if country:
        seed_query = seed_query.filter(country_id=country)

    exact_alternate_ids = PlaceAlternateName.objects.filter(
        active=True,
        place__active=True,
        place__place_type=Place.PlaceType.LOCALITY,
        normalized_name=normalized,
    )
    if country:
        exact_alternate_ids = exact_alternate_ids.filter(place__country_id=country)
    seed_query = seed_query.annotate(
        _seed_rank=Case(
            When(normalized_name=normalized, then=0),
            When(pk__in=Subquery(exact_alternate_ids.values("place_id")), then=1),
            When(normalized_name__startswith=normalized, then=2),
            default=3,
            output_field=IntegerField(),
        )
    ).order_by("_seed_rank", "name", "id")
    seeds = list(seed_query[:AIRPORT_RECOMMENDATION_SEED_LIMIT])
    if not seeds:
        return [], [], [], {}
    # When an exact canonical/alias hit exists, a merely prefix-matching town
    # is broader search noise, not another city the airport expansion should
    # fan out from.  For ambiguous equal-rank prefixes (for example the two
    # Frankfurts), keep the bounded cohort and let their own names disambiguate.
    best_seed_rank = seeds[0]._seed_rank
    seeds = [seed for seed in seeds if seed._seed_rank == best_seed_rank]
    seed_ids = [seed.id for seed in seeds]

    seed_by_id = {seed.id: seed for seed in seeds}
    seed_order = {seed.id: index for index, seed in enumerate(seeds)}
    mappings = list(
        AirportLocalityMapping.objects.filter(
            active=True,
            relationship_type=AirportLocalityMapping.RelationshipType.SERVED,
            locality_id__in=seed_by_id,
            locality__active=True,
            airport__active=True,
            airport__place_type=Place.PlaceType.AIRPORT,
        )
        .select_related("airport", "locality", "locality__parent")
        .order_by("airport__name", "airport_id")
    )
    mappings.sort(
        key=lambda mapping: (
            seed_order[mapping.locality_id],
            not mapping.is_primary,
            mapping.airport.name,
            mapping.airport_id,
        )
    )

    served_ids: list[int] = []
    metadata: dict[int, dict] = {}
    seeds_with_served_airports: set[int] = set()
    for mapping in mappings:
        seeds_with_served_airports.add(mapping.locality_id)
        if mapping.airport_id in metadata:
            continue
        if len(served_ids) >= AIRPORT_RECOMMENDATION_LIMIT:
            break
        served_ids.append(mapping.airport_id)
        metadata[mapping.airport_id] = {
            "relation": "serves_place",
            "context": mapping.locality,
            "distance_km": None,
        }

    fallback_seeds = [
        seed
        for seed in seeds
        if seed.id not in seeds_with_served_airports
        and seed.latitude is not None
        and seed.longitude is not None
    ]
    remaining = AIRPORT_RECOMMENDATION_LIMIT - len(served_ids)
    if not fallback_seeds or remaining <= 0:
        return seed_ids, served_ids, [], metadata

    airport_query = (
        Place.objects.filter(
            active=True,
            place_type=Place.PlaceType.AIRPORT,
            country_id__in={seed.country_id for seed in fallback_seeds},
            latitude__isnull=False,
            longitude__isnull=False,
            airport_mappings__active=True,
            airport_mappings__is_primary=True,
            airport_mappings__relationship_type=AirportLocalityMapping.RelationshipType.SERVED,
            airport_mappings__locality__active=True,
        )
        .exclude(pk__in=served_ids)
        .distinct()
        .values("id", "country_id", "name", "latitude", "longitude")
    )
    nearby_candidates: list[tuple[float, str, int, Place]] = []
    for airport in airport_query:
        for seed in fallback_seeds:
            if seed.country_id != airport["country_id"]:
                continue
            distance = _haversine_km(
                float(seed.latitude),
                float(seed.longitude),
                float(airport["latitude"]),
                float(airport["longitude"]),
            )
            if distance <= NEARBY_AIRPORT_MAX_DISTANCE_KM:
                nearby_candidates.append(
                    (distance, airport["name"], airport["id"], seed)
                )

    nearby_ids: list[int] = []
    for distance, _name, airport_id, seed in sorted(nearby_candidates):
        if airport_id in metadata:
            continue
        nearby_ids.append(airport_id)
        metadata[airport_id] = {
            "relation": "nearby",
            "context": seed,
            "distance_km": round(distance, 1),
        }
        if len(nearby_ids) >= remaining:
            break
    return seed_ids, served_ids, nearby_ids, metadata


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

        if len(query) > 255:
            return Response(
                {"detail": "q must be 255 characters or fewer."},
                status=status.HTTP_400_BAD_REQUEST,
            )
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
            name_lookup = _name_lookup(normalized)
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
            direct_filter = Q(pk__in=Subquery(matching_ids))
            seed_ids: list[int] = []
            served_ids: list[int] = []
            nearby_ids: list[int] = []
            search_metadata: dict[int, dict] = {}
            airport_requested = not place_types or Place.PlaceType.AIRPORT in place_types
            if (
                active == "true"
                and airport_requested
                and not parent
                and len(normalized) > 1
            ):
                (
                    seed_ids,
                    served_ids,
                    nearby_ids,
                    search_metadata,
                ) = _airport_recommendations(normalized=normalized, country=country)
            places = places.filter(
                direct_filter | Q(pk__in=served_ids) | Q(pk__in=nearby_ids)
            )

            exact_alternate_ids = PlaceAlternateName.objects.filter(
                active=True,
                normalized_name=normalized,
            ).order_by()
            if active == "true":
                exact_alternate_ids = exact_alternate_ids.filter(place__active=True)
            elif active == "false":
                exact_alternate_ids = exact_alternate_ids.filter(place__active=False)
            places = places.annotate(
                _search_rank=Case(
                    When(normalized_name=normalized, then=0),
                    When(
                        pk__in=Subquery(exact_alternate_ids.values("place_id")),
                        then=1,
                    ),
                    When(pk__in=seed_ids, then=2),
                    When(pk__in=served_ids, then=3),
                    When(pk__in=nearby_ids, then=4),
                    When(normalized_name__startswith=normalized, then=5),
                    When(pk__in=Subquery(alternate_ids.values("place_id")), then=6),
                    default=7,
                    output_field=IntegerField(),
                ),
                _search_type_rank=Case(
                    When(place_type=Place.PlaceType.LOCALITY, then=0),
                    When(place_type=Place.PlaceType.AIRPORT, then=1),
                    default=2,
                    output_field=IntegerField(),
                ),
            ).order_by("_search_rank", "_search_type_rank", "name", "id")
        else:
            search_metadata = {}
            places = places.order_by("name", "id")

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(places, request, view=self)
        serializer = GeographyPlaceSerializer(
            page,
            many=True,
            context={"search_metadata": search_metadata},
        )
        return paginator.get_paginated_response(serializer.data)
