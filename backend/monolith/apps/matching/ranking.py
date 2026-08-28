from __future__ import annotations

from datetime import datetime

from django.utils import timezone

from apps.parcels.models import DeliveryRequest

from .compatibility import CompatibilityResult
from .policy import Phase2Policy


def rank_compatible_candidate(
    *,
    compatibility: CompatibilityResult,
    delivery_request: DeliveryRequest,
    policy: Phase2Policy,
    at: datetime | None = None,
) -> dict:
    if not compatibility.compatible:
        raise ValueError("Hard compatibility must pass before ranking.")
    at = at or timezone.now()
    total_added = compatibility.added_distance_meters
    route_fit = max(
        0,
        1000
        - round(1000 * total_added / max(1, policy.max_total_added_distance_meters)),
    )
    pickup_ratio = compatibility.pickup_detour_meters / max(
        1, policy.max_pickup_detour_meters
    )
    delivery_ratio = compatibility.delivery_detour_meters / max(
        1, policy.max_dropoff_detour_meters
    )
    detour_score = max(0, 1000 - round(500 * (pickup_ratio + delivery_ratio)))

    if compatibility.delivery_at and delivery_request.deadline_at:
        slack_seconds = max(
            0,
            (delivery_request.deadline_at - compatibility.delivery_at).total_seconds(),
        )
        time_fit = min(1000, round(slack_seconds / (7 * 24 * 3600) * 1000))
    else:
        time_fit = 0
    age_seconds = max(0, (at - delivery_request.created_at).total_seconds())
    freshness = max(0, 1000 - round(age_seconds / (30 * 24 * 3600) * 1000))

    raw_factors = {
        "route_fit": (route_fit, True, "matched route and added-distance fit"),
        "detour": (detour_score, True, "pickup/drop detour headroom"),
        "time_fit": (time_fit, True, "deadline slack"),
        "verification": (1000, True, "hard KYC and flight-proof gates passed"),
        "freshness": (freshness, True, "request age"),
        "neutral_reputation": (
            500,
            False,
            "rating, reliability, cancellation, and response signals are not active",
        ),
    }
    factors = {}
    weighted_total = 0
    weight_total = sum(policy.ranking_weights.values())
    for name, (score, available, reason) in raw_factors.items():
        weight = policy.ranking_weights[name]
        weighted = score * weight
        weighted_total += weighted
        factors[name] = {
            "score": score,
            "weight": weight,
            "weighted_score": weighted,
            "available": available,
            "reason": reason,
        }

    base_score = weighted_total // max(1, weight_total)
    boost_active = delivery_request.is_ranking_boost_active(at=at)
    boost_points = 0
    if boost_active:
        boost_points = min(
            policy.max_boost_points,
            delivery_request.ranking_boost_weight * policy.boost_points_per_weight,
        )
    return {
        "score": base_score + boost_points,
        "base_score": base_score,
        "factors": factors,
        "boost": {
            "active": boost_active,
            "weight": delivery_request.ranking_boost_weight if boost_active else 0,
            "points": boost_points,
            "compatibility_override": False,
        },
        "tie_break": "lower_detour_then_earlier_departure_then_stable_id",
    }
