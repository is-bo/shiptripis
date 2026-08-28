from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from apps.core.models import BusinessSettingsVersion

from .public_contract import PUBLIC_DISTANCE_BAND_MAXIMA


class InvalidPhase2Policy(RuntimeError):
    code = "invalid_phase2_policy"


class PricingBandsReduceLocationPrivacy(InvalidPhase2Policy):
    """A settings revision would publish a finer distance resolution.

    `distance_band_base_cents` is part of the counterparty-visible pricing
    payload, so a pricing distance band that subdivides one of the privacy
    buckets in `PUBLIC_DISTANCE_BAND_MAXIMA` lets a counterparty distinguish
    two carried distances that `matched_distance_band` reports as identical.
    That is a location-privacy regression reachable purely through commercial
    configuration, so it is refused rather than silently accepted.
    """

    code = "pricing_bands_reduce_location_privacy"

    def __init__(self, message: str, *, offending_max_meters: list[int]):
        super().__init__(message)
        self.offending_max_meters = list(offending_max_meters)

    def details(self) -> dict:
        return {
            "offending_max_meters": list(self.offending_max_meters),
            "allowed_max_meters": list(PUBLIC_DISTANCE_BAND_MAXIMA),
        }


def assert_pricing_bands_preserve_location_privacy(policy: object) -> None:
    """Refuse pricing distance bands finer than the published privacy ladder.

    Every finite pricing band maximum must also be a published band boundary.
    Coarser pricing (a strict subset of the boundaries, including a single open
    band) is always allowed; only subdivision is refused. Called both when a
    settings revision is activated and on every policy read, so a row inserted
    outside the service boundary still fails closed instead of leaking.
    """

    if not isinstance(policy, dict):
        return
    pricing = policy.get("pricing")
    if not isinstance(pricing, dict):
        return
    raw_bands = pricing.get("distance_bands")
    if not isinstance(raw_bands, list):
        return
    allowed = set(PUBLIC_DISTANCE_BAND_MAXIMA)
    offending = [
        band["max_meters"]
        for band in raw_bands
        if isinstance(band, dict)
        and isinstance(band.get("max_meters"), int)
        and not isinstance(band.get("max_meters"), bool)
        and band["max_meters"] not in allowed
    ]
    if offending:
        raise PricingBandsReduceLocationPrivacy(
            "Pricing distance bands must not subdivide a published privacy band.",
            offending_max_meters=offending,
        )


def _object(value: object, name: str) -> dict:
    if not isinstance(value, dict):
        raise InvalidPhase2Policy(f"Business setting '{name}' must be an object.")
    return value


def _positive_int(value: object, name: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidPhase2Policy(f"Business setting '{name}' must be an integer.")
    minimum = 0 if allow_zero else 1
    if value < minimum:
        raise InvalidPhase2Policy(
            f"Business setting '{name}' must be at least {minimum}."
        )
    return value


def _positive_decimal(value: object, name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InvalidPhase2Policy(
            f"Business setting '{name}' must be a decimal value."
        ) from exc
    if not parsed.is_finite() or parsed <= 0:
        raise InvalidPhase2Policy(f"Business setting '{name}' must be positive.")
    return parsed


@dataclass(frozen=True, slots=True)
class DistanceBand:
    max_meters: int | None
    base_cents: int


@dataclass(frozen=True, slots=True)
class UrgencyBand:
    max_slack_minutes: int
    cents: int


@dataclass(frozen=True, slots=True)
class Phase2Policy:
    settings_version: BusinessSettingsVersion
    max_pickup_detour_meters: int
    max_dropoff_detour_meters: int
    max_total_added_distance_meters: int
    max_total_added_duration_seconds: int
    candidate_scan_limit: int
    result_limit: int
    spatial_fallback_enabled: bool
    volumetric_divisor: Decimal
    weight_increment_kg: Decimal
    weight_rate_cents_per_kg: int
    global_floor_cents: int
    recommendation_multiplier_bps: int
    reward_rounding_increment_cents: int
    detour_adjustment_cents_per_km: int
    distance_bands: tuple[DistanceBand, ...]
    urgency_bands: tuple[UrgencyBand, ...]
    ranking_weights: dict[str, int]
    boost_points_per_weight: int
    max_boost_points: int
    payment_grace_seconds: int

    @classmethod
    def from_settings(cls, settings_version: BusinessSettingsVersion) -> "Phase2Policy":
        policy = _object(settings_version.policy, "policy")
        matching = _object(policy.get("matching"), "matching")
        pricing = _object(policy.get("pricing"), "pricing")
        ranking = _object(policy.get("ranking"), "ranking")
        reservation = _object(policy.get("reservation"), "reservation")

        raw_bands = pricing.get("distance_bands")
        if not isinstance(raw_bands, list) or not raw_bands:
            raise InvalidPhase2Policy(
                "Business setting 'pricing.distance_bands' must be a non-empty list."
            )
        bands: list[DistanceBand] = []
        previous_max = -1
        for index, raw_band in enumerate(raw_bands):
            band = _object(raw_band, f"pricing.distance_bands[{index}]")
            raw_max = band.get("max_meters")
            max_meters = None
            if raw_max is not None:
                max_meters = _positive_int(
                    raw_max, f"pricing.distance_bands[{index}].max_meters"
                )
                if max_meters <= previous_max:
                    raise InvalidPhase2Policy(
                        "Pricing distance-band maxima must be strictly increasing."
                    )
                previous_max = max_meters
            elif index != len(raw_bands) - 1:
                raise InvalidPhase2Policy(
                    "Only the final pricing distance band may have no maximum."
                )
            bands.append(
                DistanceBand(
                    max_meters=max_meters,
                    base_cents=_positive_int(
                        band.get("base_cents"),
                        f"pricing.distance_bands[{index}].base_cents",
                        allow_zero=True,
                    ),
                )
            )
        if bands[-1].max_meters is not None:
            raise InvalidPhase2Policy(
                "Pricing distance bands require a final open band."
            )
        assert_pricing_bands_preserve_location_privacy(policy)

        raw_urgency = pricing.get("urgency_adjustments", [])
        if not isinstance(raw_urgency, list):
            raise InvalidPhase2Policy(
                "Business setting 'pricing.urgency_adjustments' must be a list."
            )
        urgency_bands = tuple(
            sorted(
                (
                    UrgencyBand(
                        max_slack_minutes=_positive_int(
                            _object(raw, f"pricing.urgency_adjustments[{index}]").get(
                                "max_slack_minutes"
                            ),
                            f"pricing.urgency_adjustments[{index}].max_slack_minutes",
                        ),
                        cents=_positive_int(
                            _object(raw, f"pricing.urgency_adjustments[{index}]").get(
                                "cents"
                            ),
                            f"pricing.urgency_adjustments[{index}].cents",
                            allow_zero=True,
                        ),
                    )
                    for index, raw in enumerate(raw_urgency)
                ),
                key=lambda item: item.max_slack_minutes,
            )
        )

        raw_weights = _object(ranking.get("weights"), "ranking.weights")
        required_weights = {
            "route_fit",
            "detour",
            "time_fit",
            "verification",
            "freshness",
            "neutral_reputation",
        }
        if set(raw_weights) != required_weights:
            raise InvalidPhase2Policy(
                "Ranking weights must define exactly the documented Phase 2 factors."
            )
        weights = {
            name: _positive_int(
                value,
                f"ranking.weights.{name}",
                allow_zero=True,
            )
            for name, value in raw_weights.items()
        }
        if sum(weights.values()) <= 0:
            raise InvalidPhase2Policy("At least one ranking weight must be positive.")

        spatial_fallback = matching.get("spatial_fallback_enabled")
        if not isinstance(spatial_fallback, bool):
            raise InvalidPhase2Policy(
                "Business setting 'matching.spatial_fallback_enabled' must be boolean."
            )

        result = cls(
            settings_version=settings_version,
            max_pickup_detour_meters=_positive_int(
                matching.get("max_pickup_detour_meters"),
                "matching.max_pickup_detour_meters",
            ),
            max_dropoff_detour_meters=_positive_int(
                matching.get("max_dropoff_detour_meters"),
                "matching.max_dropoff_detour_meters",
            ),
            max_total_added_distance_meters=_positive_int(
                matching.get("max_total_added_distance_meters"),
                "matching.max_total_added_distance_meters",
            ),
            max_total_added_duration_seconds=_positive_int(
                matching.get("max_total_added_duration_seconds"),
                "matching.max_total_added_duration_seconds",
            ),
            candidate_scan_limit=_positive_int(
                matching.get("candidate_scan_limit"),
                "matching.candidate_scan_limit",
            ),
            result_limit=_positive_int(
                matching.get("result_limit"),
                "matching.result_limit",
            ),
            spatial_fallback_enabled=spatial_fallback,
            volumetric_divisor=_positive_decimal(
                pricing.get("volumetric_divisor"), "pricing.volumetric_divisor"
            ),
            weight_increment_kg=_positive_decimal(
                pricing.get("weight_increment_kg"), "pricing.weight_increment_kg"
            ),
            weight_rate_cents_per_kg=_positive_int(
                pricing.get("weight_rate_cents_per_kg"),
                "pricing.weight_rate_cents_per_kg",
                allow_zero=True,
            ),
            global_floor_cents=_positive_int(
                pricing.get("global_floor_cents"),
                "pricing.global_floor_cents",
                allow_zero=True,
            ),
            recommendation_multiplier_bps=_positive_int(
                pricing.get("recommendation_multiplier_bps"),
                "pricing.recommendation_multiplier_bps",
            ),
            reward_rounding_increment_cents=_positive_int(
                pricing.get("reward_rounding_increment_cents"),
                "pricing.reward_rounding_increment_cents",
            ),
            detour_adjustment_cents_per_km=_positive_int(
                pricing.get("detour_adjustment_cents_per_km"),
                "pricing.detour_adjustment_cents_per_km",
                allow_zero=True,
            ),
            distance_bands=tuple(bands),
            urgency_bands=urgency_bands,
            ranking_weights=weights,
            boost_points_per_weight=_positive_int(
                ranking.get("boost_points_per_weight"),
                "ranking.boost_points_per_weight",
                allow_zero=True,
            ),
            max_boost_points=_positive_int(
                ranking.get("max_boost_points"),
                "ranking.max_boost_points",
                allow_zero=True,
            ),
            payment_grace_seconds=_positive_int(
                reservation.get("payment_grace_seconds"),
                "reservation.payment_grace_seconds",
            ),
        )
        if result.candidate_scan_limit > 1_000:
            raise InvalidPhase2Policy("Candidate scan limit cannot exceed 1,000.")
        if (
            result.result_limit > 100
            or result.result_limit > result.candidate_scan_limit
        ):
            raise InvalidPhase2Policy(
                "Result limit cannot exceed 100 or the candidate scan limit."
            )
        if (
            result.max_pickup_detour_meters > 200_000
            or result.max_dropoff_detour_meters > 200_000
            or result.max_total_added_distance_meters > 500_000
            or result.max_total_added_duration_seconds > 86_400
        ):
            raise InvalidPhase2Policy("Matching detour limits exceed safe bounds.")
        if not 10_000 <= result.recommendation_multiplier_bps <= 100_000:
            raise InvalidPhase2Policy(
                "Recommendation multiplier must be between 10,000 and 100,000 bps."
            )
        if result.reward_rounding_increment_cents > 10_000:
            raise InvalidPhase2Policy(
                "Reward rounding increment cannot exceed EUR 100."
            )
        if result.payment_grace_seconds > 7 * 24 * 60 * 60:
            raise InvalidPhase2Policy("Payment grace cannot exceed seven days.")
        urgency_thresholds = [band.max_slack_minutes for band in result.urgency_bands]
        if len(urgency_thresholds) != len(set(urgency_thresholds)):
            raise InvalidPhase2Policy("Urgency thresholds must be unique.")
        return result

    def snapshot(self) -> dict:
        return {
            "business_settings_version": self.settings_version.version,
            "pricing_version": self.settings_version.pricing_version,
            "canonical_currency": self.settings_version.canonical_currency,
            "commission_rate_bps": self.settings_version.commission_rate_bps,
            "policy": deepcopy(self.settings_version.policy),
        }
