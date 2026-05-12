"""Single source of truth for ShipTrip pricing.

Per CLAUDE.md §6:
- Delivery: 25% flat commission (sender pays total)
- Product: 2,500 DZD base fee + tiered commission
- All amounts are integer DZD. No floats. No fractional currency.
- Pricing is FROZEN on the Offer row at creation time.
  Rate changes never retroactively rewrite Offers.

The mobile app may mirror these values for previews, but only the Offer row
written by `quote_*` here is authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- Delivery (parcel-style: someone hands you a parcel; you deliver it) ---
DELIVERY_COMMISSION_PCT = 25  # integer percent, sender pays total

# Suggested delivery floor — used to compute an anchor the UI shows when the
# sender posts a request and when the traveler dials in their counter. It is
# NOT enforced (travelers can quote whatever they want — the marketplace
# clears at the accepted price). It anchors expectations and prevents
# obviously-wrong inputs (50 DZD for 10 kg).
#
# Shape: minimum_pickup_fee + (per_kg_rate * weight_kg). Tune from real
# market data once we have any.
DELIVERY_SUGGESTED_MIN_DZD = 1_500            # pickup/handling floor
DELIVERY_SUGGESTED_PER_KG_DZD = 600           # per kg

# Some routes cost more (DZ↔FR carries international risk + longer flight).
# Keys are frozensets so the suggestion is symmetric: ALG↔CDG == CDG↔ALG.
# Unknown country pairs fall back to 1x.
DELIVERY_ROUTE_MULTIPLIER: dict[frozenset[str], float] = {
    frozenset({"DZ", "FR"}): 1.6,
}

# --- Product (traveler buys an item, sender reimburses + tip) ---
PRODUCT_BASE_FEE_DZD = 2_500
# Tiers: (min_inclusive, max_exclusive_or_None, commission_percent)
PRODUCT_COMMISSION_TIERS: tuple[tuple[int, int | None, int], ...] = (
    (0,        30_000,  0),
    (30_000,   55_000,  7),
    (55_000,  100_000,  5),
    (100_000,  None,    3),
)


@dataclass(frozen=True, slots=True)
class DeliveryQuote:
    """Frozen breakdown for a delivery offer.

    `total_dzd` is what the sender pays. `commission_dzd` is what the
    platform keeps. `traveler_payout_dzd` is what the traveler receives.
    """
    base_amount_dzd: int        # the traveler's asking price
    commission_dzd: int
    total_dzd: int              # sender pays
    traveler_payout_dzd: int    # base_amount_dzd

    def as_offer_fields(self) -> dict[str, int]:
        return {
            "base_fee_dzd": 0,
            "commission_dzd": self.commission_dzd,
            "total_dzd": self.total_dzd,
        }


@dataclass(frozen=True, slots=True)
class ProductQuote:
    """Frozen breakdown for a product-purchase offer.

    `total_dzd` is sender's bill: product price + base fee + tiered commission.
    `traveler_payout_dzd` is product price + base_fee_dzd (no commission cut).
    """
    product_price_dzd: int
    base_fee_dzd: int
    commission_dzd: int
    total_dzd: int
    traveler_payout_dzd: int

    def as_offer_fields(self) -> dict[str, int]:
        return {
            "base_fee_dzd": self.base_fee_dzd,
            "commission_dzd": self.commission_dzd,
            "total_dzd": self.total_dzd,
        }


def _check_positive_int(name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be int (got {type(value).__name__})")
    if value < 0:
        raise ValueError(f"{name} must be >= 0 (got {value})")


def _product_commission_pct(price_dzd: int) -> int:
    for lo, hi, pct in PRODUCT_COMMISSION_TIERS:
        if price_dzd >= lo and (hi is None or price_dzd < hi):
            return pct
    raise AssertionError("unreachable: tiers cover all non-negative ints")


@dataclass(frozen=True, slots=True)
class DeliverySuggestion:
    """Non-binding price anchor for a delivery request.

    `suggested_base_dzd` is the traveler-payout we recommend given weight
    + route. `suggested_total_dzd` is what the sender would pay if the
    traveler accepted the suggestion verbatim (base + 25% commission).
    Both `min_floor_dzd` and `max_ceiling_dzd` are soft limits — the UI
    should warn outside this band but not block.
    """
    weight_kg: int
    suggested_base_dzd: int
    suggested_total_dzd: int
    min_floor_dzd: int
    max_ceiling_dzd: int
    route_multiplier_x100: int  # integer-ified for transport


def suggest_delivery_quote(
    *,
    weight_kg: int,
    origin_country: str = "",
    destination_country: str = "",
) -> DeliverySuggestion:
    """Suggest a fair traveler-payout for a delivery, weight + route aware.

    All math stays integer. The route multiplier is stored as a float in
    the constant table but applied as `* mul_x100 // 100` so we never let
    a float touch a money figure.

    The suggestion is informational only — Offers can be created at any
    `base_amount_dzd` the parties agree on.
    """
    _check_positive_int("weight_kg", weight_kg)
    if weight_kg < 1:
        raise ValueError("weight_kg must be >= 1")

    pair = frozenset({(origin_country or "").upper(), (destination_country or "").upper()})
    mul = DELIVERY_ROUTE_MULTIPLIER.get(pair, 1.0)
    mul_x100 = int(round(mul * 100))

    raw_base = DELIVERY_SUGGESTED_MIN_DZD + (DELIVERY_SUGGESTED_PER_KG_DZD * weight_kg)
    suggested_base = raw_base * mul_x100 // 100

    # Soft band: ±40% around the suggestion. Beyond that, UI warns.
    min_floor = suggested_base * 60 // 100
    max_ceiling = suggested_base * 140 // 100

    sender_total = quote_delivery(suggested_base).total_dzd

    return DeliverySuggestion(
        weight_kg=weight_kg,
        suggested_base_dzd=suggested_base,
        suggested_total_dzd=sender_total,
        min_floor_dzd=min_floor,
        max_ceiling_dzd=max_ceiling,
        route_multiplier_x100=mul_x100,
    )


def quote_delivery(base_amount_dzd: int) -> DeliveryQuote:
    """Compute the sender-pays total for a delivery offer.

    `base_amount_dzd` is the traveler's asking price. The sender pays
    base + 25% commission. The traveler is paid the base.
    """
    _check_positive_int("base_amount_dzd", base_amount_dzd)
    # Integer math: floor division. Round-up policy can change later, but
    # be deterministic now and keep it documented.
    commission = base_amount_dzd * DELIVERY_COMMISSION_PCT // 100
    total = base_amount_dzd + commission
    return DeliveryQuote(
        base_amount_dzd=base_amount_dzd,
        commission_dzd=commission,
        total_dzd=total,
        traveler_payout_dzd=base_amount_dzd,
    )


def quote_product(product_price_dzd: int) -> ProductQuote:
    """Compute the sender-pays total for a product-purchase offer.

    Sender pays: product_price + base_fee (2,500) + tiered commission.
    Traveler receives: product_price + base_fee (commission goes to platform).
    """
    _check_positive_int("product_price_dzd", product_price_dzd)
    pct = _product_commission_pct(product_price_dzd)
    commission = product_price_dzd * pct // 100
    total = product_price_dzd + PRODUCT_BASE_FEE_DZD + commission
    payout = product_price_dzd + PRODUCT_BASE_FEE_DZD
    return ProductQuote(
        product_price_dzd=product_price_dzd,
        base_fee_dzd=PRODUCT_BASE_FEE_DZD,
        commission_dzd=commission,
        total_dzd=total,
        traveler_payout_dzd=payout,
    )
