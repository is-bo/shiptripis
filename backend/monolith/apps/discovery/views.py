"""`/api/discovery/*`: the three Home tiers, a member's public profile, alerts.

Contract: `docs/PHASE_L2A_DISCOVERY_CONTRACT.md`. Two kinds of endpoint, each
with its own base class so the rule is visible where a view is declared:

- **Public reads** (`_PublicDiscoveryView`): trips, requests, people, one
  person, a person's reviews, a trip's reviews. A guest reads them without an
  account (plan EGS, decision 10) and gets the same allowlisted cards a member
  gets; a member who sends a token is still authenticated, so their own items
  stay out of their lists. Every guest branch is written out, never a query
  run with a missing viewer.
- **Member endpoints** (`_MemberDiscoveryView`): matches, "I can carry this",
  the own profile and alerts. They are about the caller and need an account.

Every endpoint is throttled on the existing `matching_discovery` scope (per
member, or per address for a guest, who is also held to the anonymous rate)
and reads its switch from the marketplace policy at the moment of the request.
A tier that is switched off answers HTTP 200 with `state: "disabled"`,
because "this section is not offered" is a designed state, not a failure.
"""

from __future__ import annotations

import logging

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle, UserRateThrottle
from rest_framework.views import APIView

from apps.core.business_settings import NoActiveBusinessSettings
from apps.core.marketplace_policy import (
    InvalidMarketplacePolicy,
    MarketplacePolicy,
    marketplace_policy,
)
from apps.matching.discovery import phase2_policy
from apps.matching.find_travelers import TRUST_AS_TRAVELER, trust_signals
from apps.matching.policy import InvalidPhase2Policy
from apps.matching.pricing import PricingError
from apps.ratings.public import (
    ACCESS_DISABLED,
    ACCESS_OK,
    SIDE_TRAVELER,
    public_reviews,
    trip_reviews_access,
)

from . import alerts as alert_service
from .errors import DiscoveryError
from .interest import IncompatibleInterest, register_interest
from .listings import (
    RouteFilter,
    journey_route_exists,
    listable_journeys,
    listable_requests,
    request_card,
    request_route_q,
    trip_card,
    window,
)
from .matches import sender_matches, traveler_matches
from .places import PlaceNotFound, place_ids_for_locality, resolve_locality
from .profiles import (
    PROFILE_CONSENT_VERSION,
    ROLE_SENDER,
    ROLE_TRAVELER,
    ProfileUpdate,
    own_profile,
    own_state,
    people,
    profile_card,
    show_prompt,
    update_own_profile,
    visible_profiles,
)
from .serializers import (
    AlertCreateSerializer,
    InterestCreateSerializer,
    ListingQuerySerializer,
    MatchesQuerySerializer,
    PeopleQuerySerializer,
    ProfileUpdateSerializer,
    ReviewsQuerySerializer,
)

logger = logging.getLogger(__name__)

STATE_RESULTS = "results"
STATE_EMPTY = "empty"
STATE_DISABLED = "disabled"

#: How many of one person's own trips and requests their profile page shows.
PERSON_ITEMS_LIMIT = 10

_UNAVAILABLE = (
    NoActiveBusinessSettings,
    InvalidMarketplacePolicy,
    InvalidPhase2Policy,
    PricingError,
)


def _refusal(exc: Exception) -> Response:
    if isinstance(exc, DiscoveryError):
        payload = {"code": exc.code, "detail": str(exc)}
        if isinstance(exc, IncompatibleInterest):
            payload["rejection_codes"] = exc.compatibility["rejection_codes"]
        return Response(payload, status=exc.status)
    logger.warning("discovery: policy unavailable", exc_info=True)
    return Response(
        {
            "code": getattr(exc, "code", "discovery_unavailable"),
            "detail": "Discovery is temporarily unavailable.",
        },
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def _page(state_rows: list, next_offset: int | None) -> dict:
    return {
        "state": STATE_RESULTS if state_rows else STATE_EMPTY,
        "results": state_rows,
        "next_offset": next_offset,
    }


_DISABLED_PAGE = {"state": STATE_DISABLED, "results": [], "next_offset": None}


def _route_filter(values: dict) -> RouteFilter:
    """Resolve the client's place ids to the cities matching uses."""

    def ids(key: str):
        place_id = values.get(key)
        if place_id is None:
            return None
        return place_ids_for_locality(resolve_locality(place_id).pk)

    return RouteFilter(
        origin_place_ids=ids("origin_place_id"),
        destination_place_ids=ids("destination_place_id"),
        origin_country=values.get("origin_country"),
        destination_country=values.get("destination_country"),
    )


def _trip_cards(journeys: list, *, at, policy: MarketplacePolicy) -> list[dict]:
    traveler_ids = list(dict.fromkeys(journey.traveler_id for journey in journeys))
    trust = trust_signals(traveler_ids, at=at, side=TRUST_AS_TRAVELER)
    pricing_enabled = policy.traveler_pricing.enabled
    return [
        trip_card(
            journey,
            trust=trust[journey.traveler_id],
            at=at,
            pricing_enabled=pricing_enabled,
        )
        for journey in journeys
    ]


def _profile_cards(profiles: list, *, at) -> list[dict]:
    trust = trust_signals([profile.user_id for profile in profiles], at=at, side=None)
    return [profile_card(profile, trust=trust[profile.user_id]) for profile in profiles]


def _viewer_id(request: Request) -> int | None:
    """The member reading a public endpoint, or `None` for a guest."""

    return request.user.pk if request.user.is_authenticated else None


class _PublicDiscoveryView(APIView):
    """A public read: open to a guest, the same cards for everyone."""

    permission_classes = (AllowAny,)
    throttle_classes = (AnonRateThrottle, UserRateThrottle, ScopedRateThrottle)
    throttle_scope = "matching_discovery"


class _MemberDiscoveryView(APIView):
    """About the caller: needs an account."""

    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle, ScopedRateThrottle)
    throttle_scope = "matching_discovery"


class MatchesView(_MemberDiscoveryView):
    """`GET /api/discovery/matches?role=sender|traveler`."""

    def get(self, request: Request) -> Response:
        query = MatchesQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        at = timezone.now()
        try:
            policy = phase2_policy()
            builder = (
                sender_matches if query.validated_data["role"] == ROLE_SENDER else traveler_matches
            )
            return Response(builder(user=request.user, policy=policy, at=at))
        except _UNAVAILABLE as exc:
            return _refusal(exc)


class TripsView(_PublicDiscoveryView):
    """`GET /api/discovery/trips`: published journeys, soonest departure first."""

    def get(self, request: Request) -> Response:
        query = ListingQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
        at = timezone.now()
        try:
            policy = marketplace_policy()
            if not policy.discovery.listings_enabled:
                return Response(_DISABLED_PAGE)
            route = _route_filter(values)
        except PlaceNotFound as exc:
            return Response({"code": exc.code, "detail": str(exc)}, status=400)
        except _UNAVAILABLE as exc:
            return _refusal(exc)
        departing_after = max(at, values.get("departing_after") or at)
        queryset = listable_journeys(at=at, sea_legs_enabled=policy.sea_legs_enabled)
        if (viewer_id := _viewer_id(request)) is not None:
            queryset = queryset.exclude(traveler_id=viewer_id)
        queryset = (
            # With an origin, "departing after" is about the pickup stop's own
            # leg; the trip may have started earlier somewhere else.
            queryset.filter(journey_route_exists(route, departing_after=departing_after))
            .order_by("next_departure", "pk")
        )
        if not route.has_origin:
            queryset = queryset.filter(next_departure__gte=departing_after)
        rows, next_offset = window(queryset, limit=values["limit"], offset=values["offset"])
        return Response(_page(_trip_cards(rows, at=at, policy=policy), next_offset))


class RequestsView(_PublicDiscoveryView):
    """`GET /api/discovery/requests`: open requests, newest first."""

    def get(self, request: Request) -> Response:
        query = ListingQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
        at = timezone.now()
        try:
            if not marketplace_policy().discovery.listings_enabled:
                return Response(_DISABLED_PAGE)
            route = _route_filter(values)
        except PlaceNotFound as exc:
            return Response({"code": exc.code, "detail": str(exc)}, status=400)
        except _UNAVAILABLE as exc:
            return _refusal(exc)
        queryset = listable_requests(at=at)
        if (viewer_id := _viewer_id(request)) is not None:
            queryset = queryset.exclude(sender_id=viewer_id)
        queryset = queryset.filter(request_route_q(route)).order_by("-created_at", "-pk")
        if departing_after := values.get("departing_after"):
            # "Ready to leave on or after": the parcel can still be handed over then.
            queryset = queryset.filter(ready_window_end__gte=departing_after)
        rows, next_offset = window(queryset, limit=values["limit"], offset=values["offset"])
        return Response(_page([request_card(row) for row in rows], next_offset))


class InterestView(_MemberDiscoveryView):
    """`POST /api/discovery/requests/<id>/interest`: "I can carry this"."""

    def post(self, request: Request, pk: int) -> Response:
        body = InterestCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            interest, created = register_interest(
                traveler=request.user,
                request_id=pk,
                journey_id=body.validated_data["journey_id"],
            )
        except (DiscoveryError, *_UNAVAILABLE) as exc:
            return _refusal(exc)
        return Response(
            {
                "request_id": interest.delivery_request_id,
                "journey_id": interest.journey_id,
                "sent_at": interest.created_at.isoformat(),
                "created": created,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class PeopleView(_PublicDiscoveryView):
    """`GET /api/discovery/people?role=`: visible members on the other side."""

    def get(self, request: Request) -> Response:
        query = PeopleQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
        at = timezone.now()
        try:
            if not marketplace_policy().discovery.profiles_enabled:
                return Response(_DISABLED_PAGE)
            route = _route_filter(values)
        except PlaceNotFound as exc:
            return Response({"code": exc.code, "detail": str(exc)}, status=400)
        except _UNAVAILABLE as exc:
            return _refusal(exc)
        side = ROLE_TRAVELER if values["role"] == ROLE_SENDER else ROLE_SENDER
        queryset = people(side=side, route=route, viewer_id=_viewer_id(request), at=at)
        rows, next_offset = window(queryset, limit=values["limit"], offset=values["offset"])
        return Response(_page(_profile_cards(rows, at=at), next_offset))


class PersonView(_PublicDiscoveryView):
    """`GET /api/discovery/people/<public id>`: one card and what they have listed."""

    def get(self, request: Request, public_id) -> Response:
        at = timezone.now()
        try:
            policy = marketplace_policy()
        except _UNAVAILABLE as exc:
            return _refusal(exc)
        if not policy.discovery.profiles_enabled:
            return Response({"state": STATE_DISABLED})
        profile = visible_profiles().filter(public_id=public_id).first()
        if profile is None:
            return Response(
                {"code": "profile_not_found", "detail": "This profile is not available."},
                status=status.HTTP_404_NOT_FOUND,
            )
        trips: list[dict] = []
        requests: list[dict] = []
        if policy.discovery.listings_enabled:
            journeys = list(
                listable_journeys(at=at, sea_legs_enabled=policy.sea_legs_enabled)
                .filter(traveler_id=profile.user_id)
                .order_by("next_departure", "pk")[:PERSON_ITEMS_LIMIT]
            )
            trips = _trip_cards(journeys, at=at, policy=policy)
            requests = [
                request_card(row)
                for row in listable_requests(at=at)
                .filter(sender_id=profile.user_id)
                .order_by("-created_at", "-pk")[:PERSON_ITEMS_LIMIT]
            ]
        return Response(
            {
                "state": STATE_RESULTS,
                "profile": _profile_cards([profile], at=at)[0],
                "trips": trips,
                "requests": requests,
            }
        )


def _reviews_page(subject_id: int, *, side, viewer_id: int | None, values: dict, at) -> dict:
    """One page of a person's reviews, with the rating their card shows.

    The summary is `trust_signals` itself, so the number above the list is the
    number on the card: both are computed over `apps.ratings.public.countable`.
    """

    trust = trust_signals([subject_id], at=at, side=side)[subject_id]
    rows, next_offset = public_reviews(
        subject_id,
        side=side,
        viewer_id=viewer_id,
        at=at,
        limit=values["limit"],
        offset=values["offset"],
    )
    return {**_page(rows, next_offset), "rating": trust["rating"]}


_DISABLED_REVIEWS = {**_DISABLED_PAGE, "rating": None}


class PersonReviewsView(_PublicDiscoveryView):
    """`GET /api/discovery/people/<public id>/reviews`: both sides, like the profile card."""

    def get(self, request: Request, public_id) -> Response:
        query = ReviewsQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        at = timezone.now()
        try:
            policy = marketplace_policy()
        except _UNAVAILABLE as exc:
            return _refusal(exc)
        if not policy.discovery.profiles_enabled:
            return Response(_DISABLED_REVIEWS)
        profile = visible_profiles().filter(public_id=public_id).only("user_id").first()
        if profile is None:
            return Response(
                {"code": "profile_not_found", "detail": "This profile is not available."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            _reviews_page(
                profile.user_id,
                side=None,
                viewer_id=_viewer_id(request),
                values=query.validated_data,
                at=at,
            )
        )


class TripReviewsView(_PublicDiscoveryView):
    """`GET /api/discovery/trips/<journey id>/reviews[?request=<id>]`.

    The traveler's ratings as a traveler, like the trip card and Find
    Travelers. Who may read them is `apps.ratings.public.trip_reviews_access`:
    the listings switch closes only the public path, and a sender coming from
    Find Travelers names their own open request (settled by the advisor on
    2026-11-14). A guest has the public path only.
    """

    def get(self, request: Request, pk: int) -> Response:
        query = ReviewsQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
        viewer_id = _viewer_id(request)
        at = timezone.now()
        try:
            policy = marketplace_policy()
            access, owner_id = trip_reviews_access(
                viewer_id=viewer_id,
                journey_id=pk,
                request_id=values.get("request"),
                at=at,
                listings_enabled=policy.discovery.listings_enabled,
                sea_legs_enabled=policy.sea_legs_enabled,
            )
        except _UNAVAILABLE as exc:
            return _refusal(exc)
        if access == ACCESS_DISABLED:
            return Response(_DISABLED_REVIEWS)
        if access != ACCESS_OK:
            return Response(
                {"code": "trip_not_found", "detail": "This trip is not available."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            _reviews_page(
                owner_id, side=SIDE_TRAVELER, viewer_id=viewer_id, values=values, at=at
            )
        )


class OwnProfileView(_MemberDiscoveryView):
    """`GET`/`PUT /api/discovery/profile/me`: settings and the exact public card."""

    def _payload(self, user) -> dict:
        policy = marketplace_policy()
        enabled = policy.discovery.profiles_enabled
        profile = own_profile(user)
        card = _profile_cards([profile], at=timezone.now())[0]
        return {
            "state": own_state(profile, profiles_enabled=enabled),
            "is_discoverable": profile.is_discoverable,
            "show_prompt": show_prompt(profile, profiles_enabled=enabled),
            "consent_version": PROFILE_CONSENT_VERSION,
            "usual_routes": card["usual_routes"],
            "card": card,
        }

    def get(self, request: Request) -> Response:
        try:
            return Response(self._payload(request.user))
        except _UNAVAILABLE as exc:
            return _refusal(exc)

    def put(self, request: Request) -> Response:
        body = ProfileUpdateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        routes = data.get("usual_routes")
        try:
            update_own_profile(
                request.user,
                ProfileUpdate(
                    is_discoverable=data.get("is_discoverable"),
                    usual_routes=(
                        None
                        if routes is None
                        else [(r["origin_place_id"], r["destination_place_id"]) for r in routes]
                    ),
                    prompt_dismissed=data["prompt_dismissed"],
                ),
                profiles_enabled=marketplace_policy().discovery.profiles_enabled,
            )
            return Response(self._payload(request.user))
        except (DiscoveryError, *_UNAVAILABLE) as exc:
            return _refusal(exc)


class AlertsView(_MemberDiscoveryView):
    """`GET`/`POST /api/discovery/alerts`."""

    def get(self, request: Request) -> Response:
        return Response(
            {
                "results": [
                    alert_service.alert_payload(alert)
                    for alert in alert_service.own_alerts(request.user)
                ]
            }
        )

    def post(self, request: Request) -> Response:
        body = AlertCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        try:
            alert, created = alert_service.create_alert(
                user=request.user,
                watches=data["watches"],
                origin_place_id=data["origin_place_id"],
                destination_place_id=data["destination_place_id"],
                subject_profile_id=data.get("subject_profile_id"),
            )
        except (DiscoveryError, *_UNAVAILABLE) as exc:
            return _refusal(exc)
        alert = alert_service.own_alerts(request.user).get(pk=alert.pk)
        return Response(
            alert_service.alert_payload(alert),
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class AlertDetailView(_MemberDiscoveryView):
    """`DELETE /api/discovery/alerts/<id>`."""

    def delete(self, request: Request, pk: int) -> Response:
        if not alert_service.deactivate_alert(user=request.user, alert_id=pk):
            return Response(
                {"code": "route_alert_not_found", "detail": "No such alert."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)
