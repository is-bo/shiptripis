"""Stop options of a Journey route (spec 5.1).

A stop is a node of the leg chain: position 0 is where the first leg departs
and position ``n`` is where the last leg arrives. Each stop may accept pickup,
drop-off, both or neither, and may carry a handover window and a short note.
A stop with no stored row accepts both, so a journey written before L3A, or
without options, behaves exactly as it did.

Two facts are inherent rather than chosen: nothing can be dropped off at the
first stop (nothing has been picked up yet) and nothing can be picked up at
the last one. Payloads therefore publish the *effective* options, and the
write rules refuse the two choices that would leave an end stop serving
nothing it was asked to.
"""

from __future__ import annotations

from rest_framework import serializers

from .models import Journey, JourneyStopDetail

STOP_INVALID_CODE = "journey_stop_invalid"


def _refuse(reason: str, index: int, field: str, message: str) -> None:
    raise serializers.ValidationError(
        {
            "code": STOP_INVALID_CODE,
            "reason": reason,
            "stops": {index: {field: message}},
        }
    )


def _is_default(stop: dict) -> bool:
    return (
        stop["accepts_pickup"]
        and stop["accepts_dropoff"]
        and not stop["handover_note"]
        and stop["window_start"] is None
        and stop["window_end"] is None
    )


def validate_stops(stops: list[dict], legs: list[dict]) -> list[dict]:
    """Check the requested stop options against the validated, ordered legs.

    Returns the rows worth storing: a stop left at its defaults is not
    stored, because no row already means "accepts both, no note".
    """

    last = len(legs)
    seen: set[int] = set()
    rows: list[dict] = []
    for index, stop in enumerate(stops):
        position = stop["position"]
        if position > last:
            _refuse(
                "stop_position_unknown",
                index,
                "position",
                f"This route has stops 0 to {last}.",
            )
        if position in seen:
            _refuse(
                "stop_position_duplicated",
                index,
                "position",
                "Each stop can appear only once.",
            )
        seen.add(position)
        if position == 0 and stop["accepts_dropoff"] and not stop["accepts_pickup"]:
            _refuse(
                "first_stop_dropoff_only",
                index,
                "accepts_pickup",
                "Nothing can be dropped off where the trip starts.",
            )
        if position == last and stop["accepts_pickup"] and not stop["accepts_dropoff"]:
            _refuse(
                "last_stop_pickup_only",
                index,
                "accepts_dropoff",
                "Nothing can be picked up where the trip ends.",
            )
        start, end = stop["window_start"], stop["window_end"]
        if (start is None) != (end is None):
            _refuse(
                "stop_window_incomplete",
                index,
                "window_end" if end is None else "window_start",
                "A handover window needs both a start and an end.",
            )
        if start is not None:
            if end <= start:
                _refuse(
                    "stop_window_invalid",
                    index,
                    "window_end",
                    "The handover window must end after it starts.",
                )
            arrives = legs[position - 1].get("arrive_at") if position > 0 else None
            leaves = legs[position]["depart_at"] if position < last else None
            if (arrives is not None and start < arrives) or (
                leaves is not None and end > leaves
            ):
                _refuse(
                    "stop_window_outside_stop",
                    index,
                    "window_start",
                    "The handover window must fit between arriving at and "
                    "leaving this stop.",
                )
        if not _is_default(stop):
            rows.append(dict(stop))
    rows.sort(key=lambda row: row["position"])
    return rows


def effective_stops(
    journey: Journey, *, legs: list, include_handover_detail: bool
) -> list[dict]:
    """Every stop of the route with what it really accepts.

    ``legs`` are the journey's legs in route order (prefetched by the caller),
    and the stop rows come from the ``stop_details`` prefetch.
    """

    if not legs:
        return []
    details: dict[int, JourneyStopDetail] = {
        row.position: row for row in journey.stop_details.all()
    }
    last = len(legs)
    stops = []
    for position in range(last + 1):
        place = legs[0].origin_place if position == 0 else legs[position - 1].destination_place
        row = details.get(position)
        entry = {
            "position": position,
            "place_id": place.pk if place is not None else None,
            "accepts_pickup": position < last and (row is None or row.accepts_pickup),
            "accepts_dropoff": position > 0 and (row is None or row.accepts_dropoff),
        }
        if include_handover_detail:
            entry.update(
                {
                    "handover_note": row.handover_note if row else "",
                    "window_start": (
                        row.window_start.isoformat()
                        if row and row.window_start
                        else None
                    ),
                    "window_end": (
                        row.window_end.isoformat() if row and row.window_end else None
                    ),
                }
            )
        stops.append(entry)
    return stops
