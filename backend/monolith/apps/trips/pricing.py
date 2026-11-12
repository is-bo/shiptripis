"""The traveler's own price on a journey (spec 8, plan L4A).

A traveler may set a price per kg and a minimum per parcel, both or neither.
This module owns the three things that touch that price:

* **The switch and the bounds.** `traveler_pricing_policy()` reads
  `marketplace.traveler_pricing` from the settings revision at the moment of
  the action. An unreadable revision answers "off", exactly as the sea switch
  does: a configuration fault must never be what turns a capability on.
* **The rules for a new price** (`check_price`): both or neither, each within
  the policy's bounds, and no new price at all while the switch is off.
  Clearing a price, or re-sending the one already stored, is always allowed,
  so turning the switch off never traps a traveler's route edit.
* **The write** (`apply_journey_price`): stores the pair and appends a
  `JourneyPriceChange` row. Callers hold the journey row lock, which is the
  lock every offer write takes first, so an offer is snapshotted against
  either the old price or the new one and never a mix.

The price is a default the sender sees pre-filled. It is never a floor:
`apps.matching.listed_price` turns it into the listed reward and
`create_sender_offer` still accepts any reward at or above Wassla's minimum.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import transaction

from apps.core.marketplace_policy import TravelerPricingPolicy

from .lifecycle import with_lifecycle
from .models import Journey, JourneyPriceChange

logger = logging.getLogger("apps.trips")

#: Machine codes. `PRICE_INVALID_CODE` always carries a `reason`.
PRICE_INVALID_CODE = "journey_price_invalid"
PRICING_DISABLED_CODE = "traveler_pricing_disabled"
PRICE_NOT_EDITABLE_CODE = "journey_price_not_editable"

REASON_INCOMPLETE = "price_incomplete"
REASON_PER_KG_ABOVE_MAXIMUM = "price_per_kg_above_maximum"
REASON_MIN_ABOVE_MAXIMUM = "min_price_above_maximum"

#: Lifecycle states in which the price may change. A journey still takes new
#: offers while active and while in progress (a later leg stays sellable), so
#: its price stays editable for exactly as long as it can be offered on.
PRICE_EDITABLE_STATUSES = frozenset(
    {
        Journey.Status.DRAFT,
        Journey.Status.PENDING_VERIFICATION,
        Journey.Status.ACTIVE,
        Journey.Status.IN_PROGRESS,
    }
)


class JourneyPriceError(RuntimeError):
    def __init__(self, code: str, message: str, *, extra: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra or {}

    def as_payload(self) -> dict:
        return {"code": self.code, "detail": self.message, **self.extra}


@dataclass(frozen=True, slots=True)
class JourneyPrice:
    """A journey's price pair. ``None`` on both sides is "no price"."""

    price_per_kg_eur_cents: int | None
    min_price_eur_cents: int | None

    @classmethod
    def of(cls, journey: Journey) -> "JourneyPrice":
        return cls(journey.price_per_kg_eur_cents, journey.min_price_eur_cents)

    @property
    def is_set(self) -> bool:
        return self.price_per_kg_eur_cents is not None

    def as_public_dict(self) -> dict | None:
        """The public block every surface shows: the two numbers, or null."""

        if not self.is_set:
            return None
        return {
            "price_per_kg_eur_cents": self.price_per_kg_eur_cents,
            "min_price_eur_cents": self.min_price_eur_cents,
        }


NO_PRICE = JourneyPrice(None, None)


def traveler_pricing_policy(settings_version=None) -> TravelerPricingPolicy | None:
    """The traveler-pricing section, or ``None`` when pricing is off.

    With ``settings_version`` the section is parsed from that revision with no
    query, which is how a matching scan reads the switch from the same
    revision that priced the match. Without it the active revision is read.
    """

    from apps.core.business_settings import (
        NoActiveBusinessSettings,
        get_active_business_settings,
    )
    from apps.core.marketplace_policy import (
        InvalidMarketplacePolicy,
        MarketplacePolicy,
    )

    try:
        revision = settings_version or get_active_business_settings()
        section = MarketplacePolicy.from_settings(revision).traveler_pricing
    except (NoActiveBusinessSettings, InvalidMarketplacePolicy):
        logger.warning("trips.traveler_pricing_unreadable; traveler pricing treated as off")
        return None
    return section if section.enabled else None


def check_price(new: JourneyPrice, *, current: JourneyPrice) -> None:
    """Refuse a price the server would not store. Reads the switch only if needed."""

    if (new.price_per_kg_eur_cents is None) != (new.min_price_eur_cents is None):
        raise JourneyPriceError(
            PRICE_INVALID_CODE,
            "Set both a price per kg and a minimum per parcel, or neither.",
            extra={"reason": REASON_INCOMPLETE},
        )
    if not new.is_set or new == current:
        return
    policy = traveler_pricing_policy()
    if policy is None:
        raise JourneyPriceError(
            PRICING_DISABLED_CODE, "Setting a price on a route is not available right now."
        )
    if new.price_per_kg_eur_cents > policy.max_price_per_kg_eur_cents:
        raise JourneyPriceError(
            PRICE_INVALID_CODE,
            "The price per kg is above the largest Wassla allows.",
            extra={
                "reason": REASON_PER_KG_ABOVE_MAXIMUM,
                "max_price_per_kg_eur_cents": policy.max_price_per_kg_eur_cents,
            },
        )
    if new.min_price_eur_cents > policy.max_min_price_eur_cents:
        raise JourneyPriceError(
            PRICE_INVALID_CODE,
            "The minimum per parcel is above the largest Wassla allows.",
            extra={
                "reason": REASON_MIN_ABOVE_MAXIMUM,
                "max_min_price_eur_cents": policy.max_min_price_eur_cents,
            },
        )


def apply_journey_price(*, journey: Journey, actor, price: JourneyPrice) -> bool:
    """Store ``price`` on a journey the caller has locked; record any change.

    Returns whether anything changed. The caller has already run
    `check_price` and holds the row lock.
    """

    before = JourneyPrice.of(journey)
    if before == price:
        return False
    journey.price_per_kg_eur_cents = price.price_per_kg_eur_cents
    journey.min_price_eur_cents = price.min_price_eur_cents
    journey.save(update_fields=["price_per_kg_eur_cents", "min_price_eur_cents", "updated_at"])
    JourneyPriceChange.objects.create(
        journey=journey,
        actor=actor,
        price_per_kg_eur_cents_before=before.price_per_kg_eur_cents,
        min_price_eur_cents_before=before.min_price_eur_cents,
        price_per_kg_eur_cents_after=price.price_per_kg_eur_cents,
        min_price_eur_cents_after=price.min_price_eur_cents,
    )
    return True


@transaction.atomic
def set_own_journey_price(*, journey_id: int, actor, price: JourneyPrice) -> Journey:
    """`PATCH /api/journeys/<id>/pricing`: the owner changes the price.

    Allowed for as long as the journey can still be offered on, independent
    of whether the route itself is still editable. Existing offers and deals
    keep the listed price they froze; only offers created afterwards see the
    new one.
    """

    locked = Journey.objects.select_for_update(no_key=True).get(pk=journey_id)
    if locked.traveler_id != getattr(actor, "pk", None):
        raise JourneyPriceError("journey_not_owned", "Only the journey owner can price it.")
    lifecycle = (
        with_lifecycle(Journey.objects.filter(pk=locked.pk))
        .values_list("lifecycle_status", flat=True)
        .get()
    )
    if lifecycle not in PRICE_EDITABLE_STATUSES:
        raise JourneyPriceError(
            PRICE_NOT_EDITABLE_CODE,
            f"A journey in status '{lifecycle}' can no longer be priced.",
            extra={"status": lifecycle},
        )
    check_price(price, current=JourneyPrice.of(locked))
    apply_journey_price(journey=locked, actor=actor, price=price)
    return locked
