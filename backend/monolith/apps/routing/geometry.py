from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from typing import Iterable, Sequence


EARTH_RADIUS_METERS = 6_371_008.8


@dataclass(frozen=True, slots=True)
class GeoPoint:
    latitude: float
    longitude: float

    def as_pair(self) -> tuple[float, float]:
        return (self.latitude, self.longitude)


@dataclass(frozen=True, slots=True)
class CorridorProjection:
    distance_meters: int
    progress: float
    point: GeoPoint


def haversine_meters(first: GeoPoint, second: GeoPoint) -> int:
    """Return great-circle distance using one documented Earth radius."""

    lat1 = radians(first.latitude)
    lat2 = radians(second.latitude)
    delta_lat = lat2 - lat1
    delta_lon = radians(second.longitude - first.longitude)
    value = sin(delta_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
    return round(2 * EARTH_RADIUS_METERS * asin(min(1.0, sqrt(value))))


def _local_xy(point: GeoPoint, *, reference_latitude: float) -> tuple[float, float]:
    """Project a point locally for corridor-distance/progress estimates."""

    latitude_scale = EARTH_RADIUS_METERS * radians(1)
    longitude_scale = latitude_scale * cos(radians(reference_latitude))
    return (point.longitude * longitude_scale, point.latitude * latitude_scale)


def project_to_corridor(
    point: GeoPoint,
    corridor: Sequence[GeoPoint],
) -> CorridorProjection:
    """Project onto a route corridor and return distance plus 0..1 progress.

    This is an explicitly approximate spatial fallback, not a routed-road
    distance. It is accurate enough for conservative candidate narrowing and
    is always labelled as such by the matching engine.
    """

    if len(corridor) < 2:
        raise ValueError("A corridor requires at least two points.")

    segment_lengths = [
        haversine_meters(start, end)
        for start, end in zip(corridor, corridor[1:], strict=False)
    ]
    total_length = sum(segment_lengths)
    if total_length <= 0:
        return CorridorProjection(
            distance_meters=haversine_meters(point, corridor[0]),
            progress=0.0,
            point=corridor[0],
        )

    best_distance = float("inf")
    best_progress_meters = 0.0
    best_point = corridor[0]
    traversed = 0.0
    for start, end, segment_length in zip(
        corridor[:-1],
        corridor[1:],
        segment_lengths,
        strict=True,
    ):
        reference_latitude = (start.latitude + end.latitude + point.latitude) / 3
        start_x, start_y = _local_xy(start, reference_latitude=reference_latitude)
        end_x, end_y = _local_xy(end, reference_latitude=reference_latitude)
        point_x, point_y = _local_xy(point, reference_latitude=reference_latitude)
        delta_x = end_x - start_x
        delta_y = end_y - start_y
        denominator = delta_x * delta_x + delta_y * delta_y
        fraction = 0.0
        if denominator > 0:
            fraction = max(
                0.0,
                min(
                    1.0,
                    ((point_x - start_x) * delta_x + (point_y - start_y) * delta_y)
                    / denominator,
                ),
            )
        projected_x = start_x + fraction * delta_x
        projected_y = start_y + fraction * delta_y
        distance = sqrt((point_x - projected_x) ** 2 + (point_y - projected_y) ** 2)
        if distance < best_distance:
            best_distance = distance
            best_progress_meters = traversed + fraction * segment_length
            best_point = GeoPoint(
                latitude=start.latitude + fraction * (end.latitude - start.latitude),
                longitude=start.longitude
                + fraction * (end.longitude - start.longitude),
            )
        traversed += segment_length

    return CorridorProjection(
        distance_meters=max(0, round(best_distance)),
        progress=max(0.0, min(1.0, best_progress_meters / total_length)),
        point=best_point,
    )


def parse_corridor_points_with_fallback(
    raw_points: object,
    *,
    fallback: Iterable[GeoPoint],
) -> tuple[tuple[GeoPoint, ...], bool]:
    points: list[GeoPoint] = []
    if isinstance(raw_points, list):
        for raw in raw_points:
            try:
                if isinstance(raw, dict):
                    latitude = float(raw["latitude"])
                    longitude = float(raw["longitude"])
                elif isinstance(raw, (list, tuple)) and len(raw) == 2:
                    latitude = float(raw[0])
                    longitude = float(raw[1])
                else:
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            if -90 <= latitude <= 90 and -180 <= longitude <= 180:
                points.append(GeoPoint(latitude, longitude))
    if len(points) >= 2:
        return tuple(points), False
    return tuple(fallback), True


def parse_corridor_points(
    raw_points: object,
    *,
    fallback: Iterable[GeoPoint],
) -> tuple[GeoPoint, ...]:
    points, _used_fallback = parse_corridor_points_with_fallback(
        raw_points,
        fallback=fallback,
    )
    return points
