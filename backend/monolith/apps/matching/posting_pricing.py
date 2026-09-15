"""What a sender may charge, priced before any journey exists.

`apps.matching.pricing` prices a *matched* candidate: it needs the journey's
sub-route, its detour and its arrival time. At posting time none of those exist,
and the sender still has to be shown what the reward may be before they type a
number. This module is that answer.

The estimate is deliberately conservative. Distance is the great-circle line
between the request's own endpoints, detour is zero and urgency is zero, so the
minimum it produces is a lower bound: every real matched route is at least this
long, and every real match therefore prices at or above this floor. Two things
depend on that direction being right:

* the posting-time refusal below the minimum can never reject a price a real
  match would have accepted, and
* the posting deposit -- a tenth of the *recommended sender total* -- can never
  exceed a tenth of what the sender ends up owing.

Three numbers come out of here and the contract names all three, up front:

``minimum_reward_eur_cents``
    The lowest reward the platform permits for this request. Enforced.
``recommended_reward_eur_cents``
    What ShipTrip suggests. Guidance, never enforced in either direction.
``chosen_reward_eur_cents``
    What the sender actually picked. May sit below, at, or above the
    recommendation; may never sit below the minimum.

A matched offer is validated a second time, against the real sub-route, by
`apps.matching.v1_services`. This module never replaces that check -- a sender
who posts at the posting-time floor may still find a particular long journey
prices above it, and that is correct.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone

from apps.core.business_settings import calculate_offer_economics
from apps.core.models import BusinessSettingsVersion

from .policy import Phase2Policy
from .pricing import PricingError, calculate_pricing_quote


@dataclass(frozen=True, slots=True)
class RouteEstimate:
    """The journey-free route figure a posting-time price is built on."""

    distance_meters: int
    method: str


def estimate_request_route(delivery_request) -> RouteEstimate:
    """Great-circle distance between the request's own endpoints.

    Schema version 3 requests carry canonical places; version 2 carries
    `Location` rows. Either may legitimately lack coordinates -- many
    authoritative municipal catalogues publish no centroid, and a preferred pin
    is optional operational data, never a pricing identity. When there are no
    coordinates the distance is zero, which lands the estimate on the global
    pricing floor: the fail-safe answer, not an error, because refusing to price
    would leave a sender unable to post at all.
    """

    if getattr(delivery_request, "schema_version", 2) >= 3:
        pickup = delivery_request.pickup_place
        dropoff = delivery_request.delivery_place
        method = "posting_estimate:canonical_place_great_circle"
    else:
        pickup = delivery_request.pickup_location
        dropoff = delivery_request.delivery_location
        method = "posting_estimate:great_circle"
    if pickup is None or dropoff is None:
        raise PricingError("A V1 delivery request needs both route endpoints.")

    if (
        pickup.latitude is not None
        and pickup.longitude is not None
        and dropoff.latitude is not None
        and dropoff.longitude is not None
    ):
        from apps.routing.geometry import GeoPoint, haversine_meters

        meters = int(
            haversine_meters(
                GeoPoint(float(pickup.latitude), float(pickup.longitude)),
                GeoPoint(float(dropoff.latitude), float(dropoff.longitude)),
            )
        )
        return RouteEstimate(distance_meters=max(0, meters), method=method)
    return RouteEstimate(
        distance_meters=0, method="posting_estimate:canonical_place_floor"
    )


@dataclass(frozen=True, slots=True)
class PostingPriceQuote:
    """Minimum, recommendation and -- when there is one -- the chosen price."""

    minimum_reward_eur_cents: int
    recommended_reward_eur_cents: int
    chosen_reward_eur_cents: int | None
    estimate: RouteEstimate
    commission_rate_bps: int
    pricing_version: str
    business_settings_version: int
    minimum_economics: dict
    recommended_economics: dict
    chosen_economics: dict | None

    def as_dict(self) -> dict:
        """The sender-facing contract. Every money value is EUR cents.

        `*_economics` each carry `traveler_reward_minor`, `platform_fee_minor`
        and `sender_total_minor`, so a client renders "you pay" and "they earn"
        without doing arithmetic of its own.

        The route estimate is reported as a method name only. The distance is
        derived from the sender's own exact endpoints, and publishing it would
        put a metre-accurate figure about a private address into a payload that
        exists to show a price.
        """

        return {
            "currency": "EUR",
            "minimum_reward_eur_cents": self.minimum_reward_eur_cents,
            "recommended_reward_eur_cents": self.recommended_reward_eur_cents,
            "chosen_reward_eur_cents": self.chosen_reward_eur_cents,
            "minimum_economics": self.minimum_economics,
            "recommended_economics": self.recommended_economics,
            "chosen_economics": self.chosen_economics,
            "commission_rate_bps": self.commission_rate_bps,
            "pricing_version": self.pricing_version,
            "business_settings_version": self.business_settings_version,
            "estimate_method": self.estimate.method,
            "estimate_basis": (
                "route_free_lower_bound_a_matched_journey_can_only_exceed"
            ),
        }


class _DraftRequest:
    """The pricing inputs of a request that may not exist yet.

    `calculate_pricing_quote` reads attributes, not rows, so a draft the sender
    is still filling in prices exactly as the saved request would. That is the
    point: the three numbers must be on screen *before* anything is written.
    """

    __slots__ = (
        "schema_version",
        "pickup_place",
        "delivery_place",
        "pickup_location",
        "delivery_location",
        "actual_weight_kg",
        "length_cm",
        "width_cm",
        "height_cm",
        "deadline_at",
        "ready_window_end",
    )

    def __init__(self, **fields):
        for name in self.__slots__:
            setattr(self, name, fields.get(name))


def draft_request(**fields) -> _DraftRequest:
    """Build the pricing inputs for a request the sender has not posted yet."""

    return _DraftRequest(**fields)


def quote_posting_price(
    *,
    delivery_request,
    chosen_reward_eur_cents: int | None = None,
    settings_version: BusinessSettingsVersion | None = None,
    at: datetime | None = None,
) -> PostingPriceQuote:
    """Price one request's reward band without choosing a journey for it."""

    from apps.core.business_settings import get_active_business_settings

    settings_version = settings_version or get_active_business_settings()
    policy = Phase2Policy.from_settings(settings_version)
    estimate = estimate_request_route(delivery_request)
    arrival_estimate = (
        getattr(delivery_request, "ready_window_end", None) or at or timezone.now()
    )
    quote = calculate_pricing_quote(
        delivery_request=delivery_request,
        matched_distance_meters=estimate.distance_meters,
        matched_distance_method=estimate.method,
        added_distance_meters=0,
        estimated_arrival_at=arrival_estimate,
        policy=policy,
    )
    chosen_economics = None
    if chosen_reward_eur_cents is not None and int(chosen_reward_eur_cents) > 0:
        chosen_economics = calculate_offer_economics(
            int(chosen_reward_eur_cents), settings_version
        )
    return PostingPriceQuote(
        minimum_reward_eur_cents=quote.minimum_reward_eur_cents,
        recommended_reward_eur_cents=quote.recommended_reward_eur_cents,
        chosen_reward_eur_cents=(
            int(chosen_reward_eur_cents)
            if chosen_reward_eur_cents is not None
            else None
        ),
        estimate=estimate,
        commission_rate_bps=quote.commission_rate_bps,
        pricing_version=quote.pricing_version,
        business_settings_version=quote.business_settings_version,
        minimum_economics=calculate_offer_economics(
            quote.minimum_reward_eur_cents, settings_version
        ),
        recommended_economics=calculate_offer_economics(
            quote.recommended_reward_eur_cents, settings_version
        ),
        chosen_economics=chosen_economics,
    )


class PriceBelowPostingMinimum(PricingError):
    """The sender chose a reward under the platform floor for this request."""

    code = "price_below_minimum"

    def __init__(self, message: str, *, minimum_reward_eur_cents: int):
        super().__init__(message)
        self.minimum_reward_eur_cents = int(minimum_reward_eur_cents)

    def details(self) -> dict:
        return {"minimum_reward_eur_cents": self.minimum_reward_eur_cents}


def assert_chosen_price_allowed(
    *, quote: PostingPriceQuote, chosen_reward_eur_cents: int
) -> None:
    """Enforce the one price rule that binds: never below the minimum.

    Above or below the *recommendation* is the sender's business and is not
    checked here, on purpose. The recommendation is advice; the minimum is the
    platform's floor, and the server owns it because a client that computed it
    would be a client that could be edited.
    """

    chosen = int(chosen_reward_eur_cents)
    if chosen < quote.minimum_reward_eur_cents:
        raise PriceBelowPostingMinimum(
            "The reward is below the minimum for this request.",
            minimum_reward_eur_cents=quote.minimum_reward_eur_cents,
        )
