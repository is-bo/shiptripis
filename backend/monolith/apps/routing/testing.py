from __future__ import annotations

from typing import Sequence

from .geometry import GeoPoint, haversine_meters
from .providers import GeocodeResult, RouteResult


class DeterministicFixtureRouteProvider:
    """Deterministic fake intended only for automated tests."""

    name = "deterministic_fixture"

    def __init__(
        self,
        *,
        road_distance_multiplier: str = "1.20",
        speed_kph: int = 60,
        geocodes: dict | None = None,
    ) -> None:
        self.road_distance_multiplier = float(road_distance_multiplier)
        self.speed_kph = speed_kph
        self.geocodes = geocodes or {}
        self.call_counts = {"geocode": 0, "reverse_geocode": 0, "directions": 0}

    def capabilities(self) -> frozenset[str]:
        return frozenset(
            {
                "geocoding",
                "reverse_geocoding",
                "directions",
                "road_distance",
                "duration",
                "corridor",
            }
        )

    def geocode(
        self,
        query: str,
        *,
        country_code: str | None = None,
    ) -> tuple[GeocodeResult, ...]:
        self.call_counts["geocode"] += 1
        raw = self.geocodes.get((query, country_code)) or self.geocodes.get(query)
        if raw is None:
            return ()
        point = GeoPoint(float(raw[0]), float(raw[1]))
        return (
            GeocodeResult(
                point=point,
                normalized_label=query,
                provider_place_id=f"fixture:{query}",
                precision="exact",
                metadata={"fixture": True},
            ),
        )

    def reverse_geocode(self, point: GeoPoint) -> GeocodeResult:
        self.call_counts["reverse_geocode"] += 1
        return GeocodeResult(
            point=point,
            normalized_label=f"{point.latitude:.6f},{point.longitude:.6f}",
            provider_place_id=f"fixture:{point.latitude:.6f}:{point.longitude:.6f}",
            precision="exact",
            metadata={"fixture": True},
        )

    def directions(
        self,
        points: Sequence[GeoPoint],
        *,
        profile: str,
    ) -> RouteResult:
        self.call_counts["directions"] += 1
        base = sum(
            haversine_meters(first, second)
            for first, second in zip(points, points[1:], strict=False)
        )
        distance = round(base * self.road_distance_multiplier)
        duration = round(distance / max(1, self.speed_kph * 1000 / 3600))
        return RouteResult(
            distance_meters=distance,
            duration_seconds=duration,
            polyline="",
            corridor_points=tuple(points),
            provider=self.name,
            profile=profile,
            metadata={"fixture": True},
        )
