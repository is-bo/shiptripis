"""Public (pre-funding) projections of the internal matching snapshots.

`CompatibilityResult.as_dict()`, `PricingQuote.as_dict()`, the ranking payload
and the `BusinessSettingsVersion.policy` object are the *internal* Phase 2
representation. They stay persisted on Match/Offer/Deal for audit and are
served to admins, but they must never reach a counterparty before funding:

* `pickup_route_position` / `delivery_route_position` are full-precision
  progress values along a corridor the counterparty already owns.
* `pickup_detour_meters` / `delivery_detour_meters` are the exact perpendicular
  (or routed) offset from that corridor.
* `distance_components[].distance_meters` is measured from the exact private
  endpoint whenever `partial_start`/`partial_end` is set.
* `pickup_at` / `delivery_at` are interpolated from the route position, so a
  second-resolution timestamp is itself a metre-resolution position.
* `checks[].details` repeats the positions and the raw detour metres.
* `capacity_remaining_by_leg` discloses the traveler's other bookings.
* `ranking.factors` are linear functions of detour, added distance and delivery
  time, so they re-encode the same geometry and expose the ranking weights.

Any one of those, combined with the corridor, resolves an exact address far
below the 0.1-degree (~11 km) coarse-location cell. See
`docs/PHASE2_MATCHING_PRICING.md` for the threat model and the accepted
residual.

Every projection here operates on plain dictionaries so a snapshot persisted by
an earlier build is filtered by exactly the same rules as a freshly computed
one; a key that is missing is treated as absent, never as safe.
"""

from __future__ import annotations

from typing import Iterable


#: Bucketed detour disclosure. Deliberately coarse: the finest bucket is wider
#: than the coarse-location cell is deep, so a band cannot narrow a candidate
#: below city precision.
DETOUR_BANDS: tuple[tuple[int | None, str], ...] = (
    (5_000, "under_5km"),
    (15_000, "5_15km"),
    (None, "over_15km"),
)

#: The privacy ladder for carried-distance disclosure. This tuple — not the
#: versioned pricing configuration — owns how finely a published payload may
#: resolve a carried distance, and it is deliberately hard-coded: an admin
#: editing commercial pricing must never be able to reduce pre-funding location
#: privacy as a side effect.
#:
#: The coupling runs the other way instead. `distance_band_base_cents` is
#: published, so a pricing band boundary that is *not* also a boundary here
#: would let a counterparty distinguish two distances that
#: `matched_distance_band` claims are indistinguishable.
#: `apps.matching.policy.assert_pricing_bands_preserve_location_privacy`
#: therefore rejects any settings revision whose pricing distance bands
#: subdivide one of these buckets. Coarser pricing (fewer boundaries) is always
#: allowed; finer pricing is refused at activation and again on every read.
PUBLIC_DISTANCE_BAND_MAXIMA: tuple[int, ...] = (
    100_000,
    300_000,
    750_000,
    1_500_000,
    3_000_000,
    5_000_000,
)

#: The privacy-owned band ladder, derived from `PUBLIC_DISTANCE_BAND_MAXIMA`
#: so the labels and the enforced invariant can never drift apart.
PUBLIC_DISTANCE_BANDS: tuple[tuple[int | None, str], ...] = tuple(
    (maximum, label)
    for maximum, label in (
        *(
            (
                maximum,
                (
                    f"under_{maximum // 1_000}km"
                    if index == 0
                    else (
                        f"{PUBLIC_DISTANCE_BAND_MAXIMA[index - 1] // 1_000}_"
                        f"{maximum // 1_000}km"
                    )
                ),
            )
            for index, maximum in enumerate(PUBLIC_DISTANCE_BAND_MAXIMA)
        ),
        (None, f"over_{PUBLIC_DISTANCE_BAND_MAXIMA[-1] // 1_000}km"),
    )
)

#: JSON-safe mirror of `PublicLocationSerializer`. This module owns the list so
#: the privacy boundary has one home; `apps.matching.compatibility` imports it
#: to build the snapshot, and `public_compatibility_payload` re-projects through
#: it on the way out. `Phase2PublicContractTests` fails loudly if the public
#: serializer ever grows a field this mirror does not carry.
PUBLIC_LOCATION_SUMMARY_FIELDS: tuple[str, ...] = (
    "id",
    "kind",
    "public_label",
    "city",
    "region",
    "country_code",
    "coarse_latitude",
    "coarse_longitude",
    "precision",
    "coordinates_trusted",
    "coordinate_dataset_version",
    "airport",
)

#: Counterparty-visible keys of one covered-leg summary. Explicit rather than
#: pass-through: a field added to the internal leg summary tomorrow is invisible
#: to a counterparty by default, exactly like every other projection here.
PUBLIC_LEG_SUMMARY_FIELDS: tuple[str, ...] = (
    "journey_leg_id",
    "position",
    "mode",
    "origin",
    "destination",
    "origin_place",
    "destination_place",
    "depart_at",
    "arrive_at",
)

#: Sub-keys of a covered leg that are themselves location objects and must be
#: re-projected through `PUBLIC_LOCATION_SUMMARY_FIELDS`.
PUBLIC_LEG_LOCATION_KEYS: frozenset[str] = frozenset({"origin", "destination"})
PUBLIC_LEG_PLACE_KEYS: frozenset[str] = frozenset({"origin_place", "destination_place"})

#: Policy keys a party is entitled to see because they are terms of their own
#: deal. Everything else in the policy object (ranking weights, boost points,
#: detour/duration limits, scan caps) is operational tuning that would let a
#: user reverse-engineer ranking, so it stays internal.
PUBLIC_RESERVATION_POLICY_KEYS = frozenset({"payment_grace_seconds"})


def _bucket(meters: object, bands: Iterable[tuple[int | None, str]]) -> str | None:
    if isinstance(meters, bool) or not isinstance(meters, (int, float)):
        return None
    value = max(0, int(meters))
    for maximum, label in bands:
        if maximum is None or value <= maximum:
            return label
    return None


def detour_band(meters: object) -> str | None:
    """Bucket a detour distance for counterparty disclosure."""

    return _bucket(meters, DETOUR_BANDS)


def distance_band(meters: object) -> dict | None:
    """Bucket a carried distance, returning the band and its bounds."""

    label = _bucket(meters, PUBLIC_DISTANCE_BANDS)
    if label is None:
        return None
    minimum = 0
    for maximum, band_label in PUBLIC_DISTANCE_BANDS:
        if band_label == label:
            return {
                "label": label,
                "min_meters": minimum,
                "max_meters": maximum,
            }
        minimum = (maximum or 0) + 1
    return None


def distance_precision(method: object) -> str:
    """Collapse an internal distance method to a non-diagnostic precision tag.

    The raw method names distinguish partial (private-endpoint) routing from
    whole-leg routing, which is itself a hint about where the endpoint sits.
    """

    if not isinstance(method, str) or not method:
        return "unavailable"
    if method.startswith("mixed:"):
        return "mixed"
    if "fallback" in method or "great_circle" in method:
        return "estimated"
    if "routed" in method:
        return "routed"
    return "unavailable"


def public_location_summary(location: object) -> dict | None:
    """Re-project a location sub-dict through the public field allowlist."""

    if not isinstance(location, dict):
        return None
    return {field: location.get(field) for field in PUBLIC_LOCATION_SUMMARY_FIELDS}


def public_place_summary(place: object) -> dict | None:
    """Project canonical place data safe for pre-funding counterparties."""

    if not isinstance(place, dict):
        return None
    return {
        key: place.get(key)
        for key in (
            "id",
            "name",
            "display_label",
            "place_type",
            "country_code",
            "iata_code",
            "matching_locality_id",
        )
    }


def public_leg_summary(leg: object) -> dict | None:
    """Re-project one covered-leg summary through the public field allowlist.

    Missing keys become `None` rather than being dropped, so the shape a client
    sees is stable no matter which build wrote the snapshot, and an unknown key
    can never survive the round trip.
    """

    if not isinstance(leg, dict):
        return None
    projected: dict = {}
    for field in PUBLIC_LEG_SUMMARY_FIELDS:
        value = leg.get(field)
        projected[field] = (
            public_location_summary(value)
            if field in PUBLIC_LEG_LOCATION_KEYS
            else public_place_summary(value)
            if field in PUBLIC_LEG_PLACE_KEYS
            else value
        )
    return projected


def _leg_window(leg: object) -> dict | None:
    if not isinstance(leg, dict):
        return None
    start = leg.get("depart_at")
    end = leg.get("arrive_at")
    if start is None and end is None:
        return None
    return {"start": start, "end": end}


def public_compatibility_payload(internal: object) -> dict | None:
    """Project an internal compatibility snapshot to its pre-funding form.

    Route positions, exact detour metres, per-component distances, interpolated
    pickup/delivery instants, raw gate details and remaining capacity are all
    dropped. Timing is reported as the covered legs' own published schedule,
    which carries no information about where on a leg the parcel joins it.
    """

    if not isinstance(internal, dict):
        return None
    covered_leg_ids = internal.get("covered_leg_ids") or []
    covered_legs = [
        projected
        for projected in (
            public_leg_summary(leg) for leg in (internal.get("covered_legs") or [])
        )
        if projected is not None
    ]
    rejection_codes = list(internal.get("rejection_codes") or [])
    compatible = bool(internal.get("compatible"))
    return {
        "matching_version": internal.get("matching_version"),
        "compatible": compatible,
        "rejection_codes": rejection_codes,
        "start_leg_id": covered_leg_ids[0] if covered_leg_ids else None,
        "end_leg_id": covered_leg_ids[-1] if covered_leg_ids else None,
        "covered_leg_ids": list(covered_leg_ids),
        "covered_leg_positions": list(internal.get("covered_leg_positions") or []),
        "covered_legs": covered_legs,
        "estimated_pickup_window": _leg_window(
            covered_legs[0] if covered_legs else None
        ),
        "estimated_delivery_window": _leg_window(
            covered_legs[-1] if covered_legs else None
        ),
        "matched_distance_band": distance_band(internal.get("matched_distance_meters")),
        "matched_distance_precision": distance_precision(
            internal.get("matched_distance_method")
        ),
        "pickup_detour_band": detour_band(internal.get("pickup_detour_meters")),
        "delivery_detour_band": detour_band(internal.get("delivery_detour_meters")),
        "total_added_distance_band": detour_band(
            internal.get("estimated_added_distance_meters")
        ),
        "capacity_available_on_every_covered_leg": (
            compatible or "capacity_available_on_every_leg" not in rejection_codes
        ),
        "limitations": list(internal.get("limitations") or []),
        "route_provider": internal.get("route_provider"),
    }


def public_pricing_payload(
    internal: object,
    *,
    include_recommendation: bool,
) -> dict | None:
    """Project an internal pricing snapshot to its pre-funding form.

    `matched_distance_meters` is measured from the exact private endpoint on a
    partial leg, and `detour_adjustment_cents` resolves the corridor offset to
    roughly 40 m, so neither is ever published. The enforced floor
    (`minimum_reward_eur_cents`) is free of detour and urgency terms and is
    therefore safe in both directions.

    `include_recommendation` is granted only to the request owner. The
    recommendation embeds the detour adjustment, and even at its EUR 0.50
    rounding that leaves a bounded (~2 km, corridor-perpendicular only) signal
    about the *counterparty's* corridor. A traveler browsing other people's
    requests never receives it, which is what closes the bulk-harvest path.
    """

    if not isinstance(internal, dict):
        return None
    payload = {
        "currency": internal.get("currency", "EUR"),
        "matched_distance_band": distance_band(internal.get("matched_distance_meters")),
        "matched_distance_precision": distance_precision(
            internal.get("matched_distance_method")
        ),
        "actual_weight_kg": internal.get("actual_weight_kg"),
        "volumetric_weight_kg": internal.get("volumetric_weight_kg"),
        "chargeable_weight_kg": internal.get("chargeable_weight_kg"),
        "weight_increment_kg": internal.get("weight_increment_kg"),
        "distance_band_base_cents": internal.get("distance_band_base_cents"),
        "weight_component_cents": internal.get("weight_component_cents"),
        "global_floor_cents": internal.get("global_floor_cents"),
        "global_floor_applied": internal.get("global_floor_applied"),
        "minimum_reward_eur_cents": internal.get("minimum_reward_eur_cents"),
        "minimum_economics": internal.get("minimum_economics"),
        "commission_rate_bps": internal.get("commission_rate_bps"),
        "pricing_version": internal.get("pricing_version"),
        "business_settings_version": internal.get("business_settings_version"),
        "detour_adjustment_applied": bool(internal.get("detour_adjustment_cents")),
        "urgency_adjustment_applied": bool(internal.get("urgency_adjustment_cents")),
    }
    if include_recommendation:
        payload["recommended_reward_eur_cents"] = internal.get(
            "recommended_reward_eur_cents"
        )
        payload["recommended_economics"] = internal.get("recommended_economics")
    return payload


def public_policy_payload(policy: object) -> dict:
    """Keep only policy values that are terms of the user's own deal."""

    if not isinstance(policy, dict):
        return {}
    reservation = policy.get("reservation")
    if not isinstance(reservation, dict):
        return {}
    return {
        "reservation": {
            key: value
            for key, value in reservation.items()
            if key in PUBLIC_RESERVATION_POLICY_KEYS
        }
    }


def public_terms_snapshot(
    snapshot: object,
    *,
    include_recommendation: bool = False,
) -> dict | None:
    """Project a persisted Offer/Deal terms snapshot to its party-visible form.

    Storage is unchanged — the full policy, ranking and internal compatibility
    remain in the row for audit and reproducibility. Only serialization is
    narrowed.
    """

    if not isinstance(snapshot, dict):
        return None
    reservation = snapshot.get("reservation")
    return {
        "canonical_currency": snapshot.get("canonical_currency", "EUR"),
        "commission_rate_bps": snapshot.get("commission_rate_bps"),
        "pricing_version": snapshot.get("pricing_version"),
        "business_settings_version": snapshot.get("business_settings_version"),
        "pricing": public_pricing_payload(
            snapshot.get("pricing"),
            include_recommendation=include_recommendation,
        ),
        "compatibility": public_compatibility_payload(snapshot.get("compatibility")),
        "policy": public_policy_payload(snapshot.get("policy")),
        "reservation": {
            key: value
            for key, value in reservation.items()
            if key in PUBLIC_RESERVATION_POLICY_KEYS
        }
        if isinstance(reservation, dict)
        else {},
    }
