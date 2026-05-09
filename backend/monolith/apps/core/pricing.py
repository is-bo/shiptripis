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
