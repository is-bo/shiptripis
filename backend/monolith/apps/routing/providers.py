from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import isfinite
from typing import Protocol, Sequence, runtime_checkable

from django.conf import settings
from django.core.cache import caches
from django.core.cache.backends.base import InvalidCacheBackendError
from django.utils.module_loading import import_string

from .geometry import GeoPoint, haversine_meters, project_to_corridor


class RouteProviderError(RuntimeError):
    code = "route_provider_error"


class RouteProviderUnavailable(RouteProviderError):
    code = "route_provider_unavailable"


@dataclass(frozen=True, slots=True)
class GeocodeResult:
    point: GeoPoint
    normalized_label: str
    provider_place_id: str
    precision: str
    metadata: dict


@dataclass(frozen=True, slots=True)
class RouteResult:
    distance_meters: int
    duration_seconds: int | None
    polyline: str
    corridor_points: tuple[GeoPoint, ...]
    provider: str
    profile: str
    metadata: dict


@runtime_checkable
class RouteProvider(Protocol):
    name: str

    def capabilities(self) -> frozenset[str]: ...

    def geocode(
        self,
        query: str,
        *,
        country_code: str | None = None,
    ) -> tuple[GeocodeResult, ...]: ...

    def reverse_geocode(self, point: GeoPoint) -> GeocodeResult: ...

    def directions(
        self,
        points: Sequence[GeoPoint],
        *,
        profile: str,
    ) -> RouteResult: ...


class UnavailableRouteProvider:
    name = "unavailable"

    def __init__(self, reason: str = "No route provider is configured.") -> None:
        self.reason = reason

    def capabilities(self) -> frozenset[str]:
        return frozenset()

    def _raise(self):
        raise RouteProviderUnavailable(self.reason)

    def geocode(self, query: str, *, country_code: str | None = None):
        del query, country_code
        self._raise()

    def reverse_geocode(self, point: GeoPoint):
        del point
        self._raise()

    def directions(self, points: Sequence[GeoPoint], *, profile: str):
        del points, profile
        self._raise()


class BudgetedRouteProvider:
    """Limit external misses; the cache decorator must wrap this object."""

    def __init__(self, provider: RouteProvider, max_calls: int) -> None:
        if max_calls <= 0 or max_calls > 500:
            raise ValueError("Route provider call budget must be between 1 and 500.")
        self.provider = provider
        self.name = provider.name
        self.max_calls = max_calls
        self.calls = 0

    def capabilities(self) -> frozenset[str]:
        return self.provider.capabilities()

    def _consume(self) -> None:
        if self.calls >= self.max_calls:
            raise RouteProviderUnavailable(
                "The route-provider call budget for this request was exhausted."
            )
        self.calls += 1

    def geocode(self, query: str, *, country_code: str | None = None):
        self._consume()
        return self.provider.geocode(query, country_code=country_code)

    def reverse_geocode(self, point: GeoPoint):
        self._consume()
        return self.provider.reverse_geocode(point)

    def directions(self, points: Sequence[GeoPoint], *, profile: str):
        self._consume()
        return self.provider.directions(points, profile=profile)


class CachedRouteProvider:
    """Best-effort cache decorator; cache failure never changes correctness."""

    def __init__(self, provider: RouteProvider) -> None:
        self.provider = provider
        self.name = provider.name
        self.cache_namespace = str(
            getattr(settings, "ROUTE_PROVIDER_CACHE_NAMESPACE", "v1")
        )
        self.ttl_seconds = int(
            getattr(settings, "ROUTE_PROVIDER_CACHE_TTL_SECONDS", 86400)
        )
        alias = getattr(settings, "ROUTE_PROVIDER_CACHE_ALIAS", "default")
        try:
            self.cache = caches[alias]
        except InvalidCacheBackendError:
            self.cache = None

    def capabilities(self) -> frozenset[str]:
        return self.provider.capabilities()

    def _key(self, operation: str, payload: dict) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = sha256(raw.encode("utf-8")).hexdigest()
        return (
            f"route-provider:{self.name}:{self.cache_namespace}:"
            f"{operation}:{digest}"
        )

    def _get(self, key: str):
        if self.cache is None:
            return None
        try:
            return self.cache.get(key)
        except Exception:
            return None

    def _set(self, key: str, value: object) -> None:
        if self.cache is None:
            return
        try:
            self.cache.set(key, value, self.ttl_seconds)
        except Exception:
            return

    @staticmethod
    def _validate_point(point: GeoPoint) -> None:
        if not isinstance(point, GeoPoint):
            raise RouteProviderError("Route provider returned an invalid coordinate.")
        coordinates = (point.latitude, point.longitude)
        if (
            any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                for value in coordinates
            )
            or not all(isfinite(value) for value in coordinates)
            or not -90 <= point.latitude <= 90
            or not -180 <= point.longitude <= 180
        ):
            raise RouteProviderError("Route provider returned an invalid coordinate.")

    def _validate_geocode(self, result: GeocodeResult) -> GeocodeResult:
        if not isinstance(result, GeocodeResult):
            raise RouteProviderError(
                "Route provider returned an invalid geocode result."
            )
        self._validate_point(result.point)
        if (
            not isinstance(result.normalized_label, str)
            or not result.normalized_label.strip()
            or len(result.normalized_label) > 500
            or not isinstance(result.provider_place_id, str)
            or len(result.provider_place_id) > 255
            or not isinstance(result.precision, str)
            or len(result.precision) > 24
            or not isinstance(result.metadata, dict)
        ):
            raise RouteProviderError("Route provider returned malformed geocode data.")
        return result

    def _validate_route(
        self,
        result: RouteResult,
        *,
        profile: str,
        expected_points: Sequence[GeoPoint],
    ) -> RouteResult:
        if not isinstance(result, RouteResult):
            raise RouteProviderError("Route provider returned an invalid route result.")
        distance = result.distance_meters
        duration = result.duration_seconds
        if (
            isinstance(distance, bool)
            or not isinstance(distance, int)
            or distance < 0
            or distance > 50_000_000
            or (
                duration is not None
                and (
                    isinstance(duration, bool)
                    or not isinstance(duration, int)
                    or duration < 0
                    or duration > 31_536_000
                )
            )
            or result.profile != profile
            or result.provider != self.name
            or not isinstance(result.polyline, str)
            or len(result.polyline) > 2_000_000
            or not isinstance(result.corridor_points, tuple)
            or len(result.corridor_points) > 10_000
            or len(result.corridor_points) == 1
            or not isinstance(result.metadata, dict)
        ):
            raise RouteProviderError("Route provider returned malformed route data.")
        for point in result.corridor_points:
            if not isinstance(point, GeoPoint):
                raise RouteProviderError("Route corridor contains an invalid point.")
            self._validate_point(point)
        if result.corridor_points and (
            haversine_meters(result.corridor_points[0], expected_points[0]) > 5_000
            or haversine_meters(result.corridor_points[-1], expected_points[-1])
            > 5_000
        ):
            raise RouteProviderError(
                "Route corridor endpoints do not match the requested route."
            )
        if len(expected_points) > 2:
            if not result.corridor_points:
                raise RouteProviderError(
                    "Route corridor does not cover every requested waypoint."
                )
            previous_progress = 0.0
            for expected_point in expected_points[1:-1]:
                projection = project_to_corridor(
                    expected_point,
                    result.corridor_points,
                )
                if projection.distance_meters > 5_000:
                    raise RouteProviderError(
                        "Route corridor does not cover every requested waypoint."
                    )
                if projection.progress < previous_progress:
                    raise RouteProviderError(
                        "Route corridor does not preserve requested waypoint order."
                    )
                previous_progress = projection.progress
        return result

    @staticmethod
    def _geocode_from_dict(value: dict) -> GeocodeResult:
        point = value.pop("point")
        return GeocodeResult(point=GeoPoint(**point), **value)

    @staticmethod
    def _route_from_dict(value: dict) -> RouteResult:
        corridor = tuple(GeoPoint(**point) for point in value.pop("corridor_points"))
        return RouteResult(corridor_points=corridor, **value)

    def geocode(
        self,
        query: str,
        *,
        country_code: str | None = None,
    ) -> tuple[GeocodeResult, ...]:
        key = self._key(
            "geocode",
            {"query": query.strip(), "country_code": country_code or ""},
        )
        cached = self._get(key)
        if isinstance(cached, list):
            try:
                results = tuple(
                    self._validate_geocode(self._geocode_from_dict(dict(item)))
                    for item in cached
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise RouteProviderError("Cached geocode data is malformed.") from exc
            return results
        results = self.provider.geocode(query, country_code=country_code)
        if not isinstance(results, tuple) or len(results) > 100:
            raise RouteProviderError(
                "Route provider returned too many geocode results."
            )
        results = tuple(self._validate_geocode(result) for result in results)
        self._set(key, [asdict(result) for result in results])
        return results

    def reverse_geocode(self, point: GeoPoint) -> GeocodeResult:
        self._validate_point(point)
        key = self._key("reverse", {"point": point.as_pair()})
        cached = self._get(key)
        if isinstance(cached, dict):
            try:
                return self._validate_geocode(self._geocode_from_dict(dict(cached)))
            except (KeyError, TypeError, ValueError) as exc:
                raise RouteProviderError(
                    "Cached reverse-geocode data is malformed."
                ) from exc
        result = self._validate_geocode(self.provider.reverse_geocode(point))
        self._set(key, asdict(result))
        return result

    def directions(
        self,
        points: Sequence[GeoPoint],
        *,
        profile: str,
    ) -> RouteResult:
        if len(points) < 2:
            raise RouteProviderError("Directions require at least two points.")
        if len(points) > 25 or not profile or len(profile) > 32:
            raise RouteProviderError("Directions input exceeds the provider contract.")
        for point in points:
            self._validate_point(point)
        key = self._key(
            "directions",
            {"profile": profile, "points": [point.as_pair() for point in points]},
        )
        cached = self._get(key)
        if isinstance(cached, dict):
            try:
                return self._validate_route(
                    self._route_from_dict(dict(cached)),
                    profile=profile,
                    expected_points=points,
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise RouteProviderError("Cached route data is malformed.") from exc
        result = self._validate_route(
            self.provider.directions(points, profile=profile),
            profile=profile,
            expected_points=points,
        )
        self._set(key, asdict(result))
        return result


def get_route_provider(*, external_call_budget: int | None = None) -> RouteProvider:
    dotted_path = getattr(settings, "ROUTE_PROVIDER_CLASS", "").strip()
    if not dotted_path:
        return UnavailableRouteProvider()
    options = getattr(settings, "ROUTE_PROVIDER_OPTIONS", {})
    if not isinstance(options, dict):
        return UnavailableRouteProvider("ROUTE_PROVIDER_OPTIONS must be a JSON object.")
    try:
        provider_class = import_string(dotted_path)
        provider = provider_class(**options)
    except Exception as exc:
        return UnavailableRouteProvider(
            f"The configured route provider could not be initialized: {type(exc).__name__}."
        )
    if not isinstance(provider, RouteProvider):
        return UnavailableRouteProvider(
            "The configured route provider does not implement the required contract."
        )
    if external_call_budget is not None:
        provider = BudgetedRouteProvider(provider, external_call_budget)
    return CachedRouteProvider(provider)


def route_provider_status() -> dict:
    provider = get_route_provider()
    available = not isinstance(provider, UnavailableRouteProvider)
    result = {
        "available": available,
        "provider": provider.name if available else None,
        "capabilities": sorted(provider.capabilities()),
    }
    if not available:
        result.update(
            {
                "code": RouteProviderUnavailable.code,
                "detail": provider.reason,
            }
        )
    return result
