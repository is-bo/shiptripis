"""The listed price: what a sender sees pre-filled for one parcel (spec 8).

The only place it is computed (plan 2.5). For a priced journey and one
request's pricing quote it is the largest of

* the traveler's price per kg times the request's chargeable weight, rounded
  up to a whole cent;
* the traveler's minimum per parcel;
* Wassla's own minimum for this match (`PricingQuote.minimum_reward_eur_cents`).

The fee and the sender's total come from `calculate_offer_economics`, at the
commission rate of the same settings revision that produced the quote, so the
listed economics are exactly what an offer of that reward would freeze.

The listed price is a default, never a floor: `create_sender_offer` accepts any
reward at or above Wassla's minimum, as it always has. A journey without a
price, or any journey while traveler pricing is switched off, has no listed
price and behaves exactly as before.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from types import SimpleNamespace

from apps.core.business_settings import calculate_offer_economics
from apps.trips.models import Journey

from .pricing import PricingQuote

#: Which of the three terms decided the listed reward. On a tie the
#: traveler's own terms are named first: the price is theirs whenever it is
#: at least Wassla's minimum.
BASIS_PER_KG = "per_kg"
BASIS_TRAVELER_MINIMUM = "traveler_minimum"
BASIS_WASSLA_MINIMUM = "wassla_minimum"
BASIS_VALUES: tuple[str, ...] = (
    BASIS_PER_KG,
    BASIS_TRAVELER_MINIMUM,
    BASIS_WASSLA_MINIMUM,
)


@dataclass(frozen=True, slots=True)
class ListedPrice:
    reward_eur_cents: int
    economics: dict[str, int]
    price_per_kg_eur_cents: int
    min_price_eur_cents: int
    basis: str

    def as_dict(self) -> dict:
        """The public block, as Find Travelers and offer snapshots carry it."""

        return {
            "reward_eur_cents": self.reward_eur_cents,
            "economics": dict(self.economics),
            "price_per_kg_eur_cents": self.price_per_kg_eur_cents,
            "min_price_eur_cents": self.min_price_eur_cents,
            "basis": self.basis,
        }


def listed_reward(
    journey: Journey,
    pricing_quote: PricingQuote | None,
    *,
    enabled: bool,
) -> ListedPrice | None:
    """The listed price of ``journey`` for the parcel ``pricing_quote`` priced.

    ``enabled`` is the traveler-pricing switch, read by the caller from the
    same settings revision as the quote. ``None`` when it is off, when the
    journey has no price, or when there is no quote (an incompatible pair has
    none, and nothing can be offered on it).
    """

    per_kg = journey.price_per_kg_eur_cents
    minimum = journey.min_price_eur_cents
    if not enabled or pricing_quote is None or per_kg is None or minimum is None:
        return None
    weighted = int(
        (Decimal(per_kg) * pricing_quote.chargeable_weight_kg).to_integral_value(
            rounding=ROUND_CEILING
        )
    )
    # `max` keeps the first of equal terms, which is the tie order above.
    reward, basis = max(
        (
            (weighted, BASIS_PER_KG),
            (minimum, BASIS_TRAVELER_MINIMUM),
            (pricing_quote.minimum_reward_eur_cents, BASIS_WASSLA_MINIMUM),
        ),
        key=lambda term: term[0],
    )
    economics = calculate_offer_economics(
        reward, SimpleNamespace(commission_rate_bps=pricing_quote.commission_rate_bps)
    )
    return ListedPrice(
        reward_eur_cents=reward,
        economics=economics,
        price_per_kg_eur_cents=per_kg,
        min_price_eur_cents=minimum,
        basis=basis,
    )
