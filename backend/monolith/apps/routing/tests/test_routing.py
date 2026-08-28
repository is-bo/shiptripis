from __future__ import annotations

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from apps.routing.geometry import (
    GeoPoint,
    haversine_meters,
    parse_corridor_points,
    project_to_corridor,
)
from apps.routing.providers import (
    CachedRouteProvider,
    RouteProviderError,
    RouteProviderUnavailable,
    RouteResult,
    UnavailableRouteProvider,
    route_provider_status,
)
from apps.routing.testing import DeterministicFixtureRouteProvider


class _NegativeRouteProvider(DeterministicFixtureRouteProvider):
    name = "negative_fixture"

    def directions(self, points, *, profile):
        return RouteResult(
            distance_meters=-1,
            duration_seconds=60,
            polyline="malformed",
            corridor_points=tuple(points),
            provider=self.name,
            profile=profile,
            metadata={},
        )


class _MalformedPointRouteProvider(DeterministicFixtureRouteProvider):
    name = "malformed_point_fixture"

    def __init__(self, malformed_point):
        super().__init__()
        self.malformed_point = malformed_point

    def directions(self, points, *, profile):
        return RouteResult(
            distance_meters=1_000,
            duration_seconds=60,
            polyline="malformed",
            corridor_points=(points[0], self.malformed_point, points[-1]),
            provider=self.name,
            profile=profile,
            metadata={},
        )


class _DisconnectedCorridorProvider(DeterministicFixtureRouteProvider):
    name = "disconnected_corridor_fixture"

    def directions(self, points, *, profile):
        return RouteResult(
            distance_meters=1_000,
            duration_seconds=60,
            polyline="disconnected",
            corridor_points=(GeoPoint(0, 0), GeoPoint(0, 1)),
            provider=self.name,
            profile=profile,
            metadata={},
        )


class _IgnoredWaypointRouteProvider(DeterministicFixtureRouteProvider):
    name = "ignored_waypoint_fixture"

    def directions(self, points, *, profile):
        return RouteResult(
            distance_meters=1_000,
            duration_seconds=60,
            polyline="ignored-waypoint",
            corridor_points=(points[0], points[-1]),
            provider=self.name,
            profile=profile,
            metadata={},
        )


class _ReorderedWaypointsRouteProvider(DeterministicFixtureRouteProvider):
    name = "reordered_waypoints_fixture"

    def directions(self, points, *, profile):
        return RouteResult(
            distance_meters=1_000,
            duration_seconds=60,
            polyline="reordered-waypoints",
            corridor_points=(points[0], points[2], points[1], points[-1]),
            provider=self.name,
            profile=profile,
            metadata={},
        )


class RouteGeometryTests(SimpleTestCase):
    def test_haversine_uses_stable_great_circle_distance(self):
        distance = haversine_meters(GeoPoint(0, 0), GeoPoint(0, 1))

        assert 111_190 <= distance <= 111_200
        assert distance == haversine_meters(GeoPoint(0, 1), GeoPoint(0, 0))
        assert haversine_meters(GeoPoint(36.75, 3.04), GeoPoint(36.75, 3.04)) == 0

    def test_corridor_projection_reports_distance_and_ordered_progress(self):
        corridor = (GeoPoint(36.0, 3.0), GeoPoint(36.0, 3.2))

        near_start = project_to_corridor(GeoPoint(36.001, 3.04), corridor)
        near_end = project_to_corridor(GeoPoint(36.001, 3.16), corridor)

        assert 100 <= near_start.distance_meters <= 120
        assert 100 <= near_end.distance_meters <= 120
        assert 0.19 <= near_start.progress <= 0.21
        assert 0.79 <= near_end.progress <= 0.81
        assert near_start.progress < near_end.progress

    def test_corridor_parser_rejects_invalid_points_and_uses_fallback(self):
        fallback = (GeoPoint(1, 2), GeoPoint(3, 4))

        parsed = parse_corridor_points(
            [
                {"latitude": 91, "longitude": 0},
                [0],
                {"latitude": "not-a-number", "longitude": 2},
            ],
            fallback=fallback,
        )

        assert parsed == fallback


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "phase2-routing-tests",
        }
    },
    ROUTE_PROVIDER_CACHE_ALIAS="default",
    ROUTE_PROVIDER_CACHE_TTL_SECONDS=60,
)
class RouteProviderTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_deterministic_provider_exposes_full_contract(self):
        provider = DeterministicFixtureRouteProvider(
            road_distance_multiplier="1.25",
            speed_kph=50,
            geocodes={"Algiers": (36.7525, 3.042)},
        )

        geocoded = provider.geocode("Algiers")
        reverse = provider.reverse_geocode(geocoded[0].point)
        route = provider.directions(
            [GeoPoint(36.7525, 3.042), GeoPoint(36.365, 6.6147)],
            profile="drive",
        )

        assert geocoded[0].provider_place_id == "fixture:Algiers"
        assert reverse.point == geocoded[0].point
        assert route.distance_meters > 0
        assert route.duration_seconds is not None
        assert route.corridor_points == (
            GeoPoint(36.7525, 3.042),
            GeoPoint(36.365, 6.6147),
        )
        assert provider.call_counts == {
            "geocode": 1,
            "reverse_geocode": 1,
            "directions": 1,
        }

    def test_cache_decorator_reuses_geocode_and_direction_results(self):
        fixture = DeterministicFixtureRouteProvider(geocodes={"Setif": (36.19, 5.41)})
        provider = CachedRouteProvider(fixture)
        points = (GeoPoint(36.75, 3.04), GeoPoint(36.19, 5.41))

        assert provider.geocode("Setif") == provider.geocode("Setif")
        assert provider.directions(points, profile="drive") == provider.directions(
            points,
            profile="drive",
        )

        assert fixture.call_counts["geocode"] == 1
        assert fixture.call_counts["directions"] == 1

    def test_cache_boundary_rejects_negative_provider_route_values(self):
        provider = CachedRouteProvider(_NegativeRouteProvider())

        with self.assertRaisesMessage(
            RouteProviderError,
            "Route provider returned malformed route data.",
        ):
            provider.directions(
                [GeoPoint(36.75, 3.04), GeoPoint(36.19, 5.41)],
                profile="drive",
            )

    def test_route_input_rejects_nonnumeric_nonfinite_and_out_of_bounds_points(self):
        provider = CachedRouteProvider(DeterministicFixtureRouteProvider())
        malformed = (
            GeoPoint("36.75", 3.04),
            GeoPoint(float("nan"), 3.04),
            GeoPoint(float("inf"), 3.04),
            GeoPoint(91, 3.04),
            GeoPoint(36.75, 181),
        )

        for point in malformed:
            with self.subTest(point=point), self.assertRaises(RouteProviderError):
                provider.directions(
                    [point, GeoPoint(36.19, 5.41)],
                    profile="drive",
                )

    def test_route_output_rejects_malformed_corridor_points(self):
        malformed = (
            GeoPoint("not-a-number", 3.04),
            GeoPoint(float("nan"), 3.04),
            GeoPoint(float("inf"), 3.04),
            GeoPoint(-91, 3.04),
            GeoPoint(36.75, -181),
        )
        requested = [GeoPoint(36.75, 3.04), GeoPoint(36.19, 5.41)]

        for point in malformed:
            cache.clear()
            provider = CachedRouteProvider(_MalformedPointRouteProvider(point))
            with self.subTest(point=point), self.assertRaises(RouteProviderError):
                provider.directions(requested, profile="drive")

    def test_route_output_rejects_corridor_disconnected_from_requested_endpoints(self):
        provider = CachedRouteProvider(_DisconnectedCorridorProvider())

        with self.assertRaisesMessage(
            RouteProviderError,
            "Route corridor endpoints do not match the requested route.",
        ):
            provider.directions(
                [GeoPoint(36.75, 3.04), GeoPoint(36.19, 5.41)],
                profile="drive",
            )

    def test_route_output_rejects_corridor_that_ignores_a_requested_waypoint(self):
        provider = CachedRouteProvider(_IgnoredWaypointRouteProvider())

        with self.assertRaisesMessage(
            RouteProviderError,
            "Route corridor does not cover every requested waypoint.",
        ):
            provider.directions(
                [GeoPoint(0, 0), GeoPoint(1, 1), GeoPoint(0, 2)],
                profile="drive",
            )

    def test_route_output_rejects_requested_waypoints_returned_out_of_order(self):
        provider = CachedRouteProvider(_ReorderedWaypointsRouteProvider())

        with self.assertRaisesMessage(
            RouteProviderError,
            "Route corridor does not preserve requested waypoint order.",
        ):
            provider.directions(
                [
                    GeoPoint(0, 0),
                    GeoPoint(1, 0),
                    GeoPoint(1, 1),
                    GeoPoint(0, 1),
                ],
                profile="drive",
            )

    @override_settings(ROUTE_PROVIDER_CLASS="")
    def test_unconfigured_provider_fails_closed_with_machine_readable_status(self):
        status = route_provider_status()

        assert status == {
            "available": False,
            "provider": None,
            "capabilities": [],
            "code": "route_provider_unavailable",
            "detail": "No route provider is configured.",
        }
        with self.assertRaises(RouteProviderUnavailable):
            UnavailableRouteProvider().directions(
                [GeoPoint(0, 0), GeoPoint(0, 1)],
                profile="drive",
            )
