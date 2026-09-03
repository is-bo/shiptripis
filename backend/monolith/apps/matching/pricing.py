from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_CEILING
from types import SimpleNamespace

from apps.core.business_settings import calculate_offer_economics
from apps.parcels.models import DeliveryRequest

from .policy import Phase2Policy


class PricingError(RuntimeError):
    code = "pricing_error"


def _ceil_decimal(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_CEILING))


def _round_up_increment(value: int, increment: int) -> int:
    return ((value + increment - 1) // increment) * increment


@dataclass(frozen=True, slots=True)
class PricingQuote:
    matched_distance_meters: int
    matched_distance_method: str
    actual_weight_kg: Decimal
    volumetric_weight_kg: Decimal
    chargeable_weight_kg: Decimal
    weight_increment_kg: Decimal
    distance_band_base_cents: int
    weight_component_cents: int
    global_floor_cents: int
    global_floor_applied: bool
    detour_adjustment_cents: int
    urgency_adjustment_cents: int
    minimum_reward_eur_cents: int
    recommended_reward_eur_cents: int
    commission_rate_bps: int
    pricing_version: str
    business_settings_version: int

    def as_dict(self) -> dict:
        policy_stub = SimpleNamespace(commission_rate_bps=self.commission_rate_bps)
        minimum_economics = calculate_offer_economics(
            self.minimum_reward_eur_cents,
            policy_stub,
        )
        recommended_economics = calculate_offer_economics(
            self.recommended_reward_eur_cents,
            policy_stub,
        )
        return {
            "currency": "EUR",
            "matched_distance_meters": self.matched_distance_meters,
            "matched_distance_method": self.matched_distance_method,
            "actual_weight_kg": str(self.actual_weight_kg),
            "volumetric_weight_kg": str(self.volumetric_weight_kg),
            "chargeable_weight_kg": str(self.chargeable_weight_kg),
            "weight_increment_kg": str(self.weight_increment_kg),
            "distance_band_base_cents": self.distance_band_base_cents,
            "weight_component_cents": self.weight_component_cents,
            "global_floor_cents": self.global_floor_cents,
            "global_floor_applied": self.global_floor_applied,
            "detour_adjustment_cents": self.detour_adjustment_cents,
            "urgency_adjustment_cents": self.urgency_adjustment_cents,
            "minimum_reward_eur_cents": self.minimum_reward_eur_cents,
            "recommended_reward_eur_cents": self.recommended_reward_eur_cents,
            "minimum_economics": minimum_economics,
            "recommended_economics": recommended_economics,
            "commission_rate_bps": self.commission_rate_bps,
            "pricing_version": self.pricing_version,
            "business_settings_version": self.business_settings_version,
        }


def calculate_pricing_quote(
    *,
    delivery_request: DeliveryRequest,
    matched_distance_meters: int,
    matched_distance_method: str,
    added_distance_meters: int,
    estimated_arrival_at: datetime,
    policy: Phase2Policy,
) -> PricingQuote:
    if delivery_request.actual_weight_kg is None:
        raise PricingError("The delivery request has no actual weight.")
    if matched_distance_meters < 0 or added_distance_meters < 0:
        raise PricingError("Distance inputs cannot be negative.")

    actual_weight = Decimal(delivery_request.actual_weight_kg)
    dimensions = (
        delivery_request.length_cm,
        delivery_request.width_cm,
        delivery_request.height_cm,
    )
    # Dimensions are optional from Phase 8F-B, so a request may legitimately
    # arrive here with none. Volumetric weight is then zero and the chargeable
    # weight is the actual weight — the ordinary freight rule for an unmeasured
    # consignment, and the same number a small dense box would produce. It is
    # deliberately not an error: refusing to price would leave a posted request
    # undiscoverable and unmatched, which is a worse outcome than pricing a
    # light bulky parcel on its weight alone. Weight itself stays required, and
    # a partial set is refused before a request is ever written.
    if any(value is None for value in dimensions):
        volumetric_weight = Decimal(0)
    else:
        volumetric_weight = (
            Decimal(dimensions[0])
            * Decimal(dimensions[1])
            * Decimal(dimensions[2])
            / policy.volumetric_divisor
        )
    raw_chargeable = max(actual_weight, volumetric_weight)
    chargeable_weight = (raw_chargeable / policy.weight_increment_kg).to_integral_value(
        rounding=ROUND_CEILING
    ) * policy.weight_increment_kg

    distance_base = next(
        band.base_cents
        for band in policy.distance_bands
        if band.max_meters is None or matched_distance_meters <= band.max_meters
    )
    weight_component = _ceil_decimal(
        chargeable_weight * policy.weight_rate_cents_per_kg
    )
    calculated_floor = distance_base + weight_component
    minimum = max(policy.global_floor_cents, calculated_floor)

    detour_adjustment = _ceil_decimal(
        Decimal(added_distance_meters)
        / Decimal(1000)
        * policy.detour_adjustment_cents_per_km
    )
    deadline = delivery_request.deadline_at
    if deadline is None:
        raise PricingError("The delivery request has no delivery deadline.")
    slack_minutes = max(0, int((deadline - estimated_arrival_at).total_seconds() // 60))
    urgency_adjustment = 0
    for band in policy.urgency_bands:
        if slack_minutes <= band.max_slack_minutes:
            urgency_adjustment = band.cents
            break

    recommendation_before_rounding = (
        _ceil_decimal(
            Decimal(minimum) * policy.recommendation_multiplier_bps / Decimal(10_000)
        )
        + detour_adjustment
        + urgency_adjustment
    )
    recommended = _round_up_increment(
        recommendation_before_rounding,
        policy.reward_rounding_increment_cents,
    )
    recommended = max(minimum, recommended)

    return PricingQuote(
        matched_distance_meters=matched_distance_meters,
        matched_distance_method=matched_distance_method,
        actual_weight_kg=actual_weight,
        volumetric_weight_kg=volumetric_weight.quantize(Decimal("0.001")),
        chargeable_weight_kg=chargeable_weight.quantize(Decimal("0.001")),
        weight_increment_kg=policy.weight_increment_kg,
        distance_band_base_cents=distance_base,
        weight_component_cents=weight_component,
        global_floor_cents=policy.global_floor_cents,
        global_floor_applied=policy.global_floor_cents > calculated_floor,
        detour_adjustment_cents=detour_adjustment,
        urgency_adjustment_cents=urgency_adjustment,
        minimum_reward_eur_cents=minimum,
        recommended_reward_eur_cents=recommended,
        commission_rate_bps=policy.settings_version.commission_rate_bps,
        pricing_version=policy.settings_version.pricing_version,
        business_settings_version=policy.settings_version.version,
    )
