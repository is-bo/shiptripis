"""Versioned marketplace policy: the L-series switches and settings.

One section of `BusinessSettingsVersion.policy`, parsed by one strict reader in
the style of `apps.core.phase4_policy`. Every L-series capability that can be
switched off asks `marketplace_policy()` at the moment of the action; nothing
caches a switch and the client never decides one.

The full shape, with the defaults a revision that has no ``marketplace``
section stands for::

    "marketplace": {
      "discovery":        {"listings_enabled": true, "profiles_enabled": true,
                           "interest_daily_cap": 10,
                           "trip_fit_alerts_enabled": true,
                           "trip_fit_max_travelers": 30, "trip_fit_daily_cap": 5},
      "sea_legs_enabled": false,
      "traveler_pricing": {"enabled": true, "max_price_per_kg_eur_cents": 10000,
                           "max_min_price_eur_cents": 50000},
      "reminders":        {"enabled": true, "depart_after_minutes": 30,
                           "arrive_after_minutes": 60, "repeat_after_minutes": 180,
                           "max_repeats": 2},
      "route_change":     {"material_shift_minutes": 360},
      "offers":           {"response_deadline_enabled": true, "response_hours": 6,
                           "reminder_before_hours": 1}
    }

Three rules, all from the plan (section 2.1):

* **Absent means defaults.** A revision written before this section existed is
  valid and behaves exactly as the defaults, so no stored row needs rewriting.
  The same holds for an absent sub-section or an absent key inside one.
* **Unknown keys are refused.** A misspelt switch would otherwise be silently
  ignored and the operator would believe a capability was off when it is on.
  The refusal happens when a revision is saved (`AdminSettingsCreateSerializer`
  runs this parser), so a bad revision never becomes active.
* **Sea legs ship off.** Everything else ships on.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import BusinessSettingsVersion


class InvalidMarketplacePolicy(RuntimeError):
    """The active settings revision cannot drive marketplace behaviour."""

    code = "marketplace_policy_unavailable"


@dataclass(frozen=True, slots=True)
class DiscoveryPolicy:
    listings_enabled: bool
    profiles_enabled: bool
    #: How many "I can carry this" signals one traveler may send in 24 hours.
    interest_daily_cap: int
    #: L12A (spec 17.2): tell travelers whose trip really fits a new request.
    trip_fit_alerts_enabled: bool
    #: At most this many travelers are told about one request, best ranked first.
    trip_fit_max_travelers: int
    #: At most this many trip-fit alerts reach one traveler in 24 hours.
    trip_fit_daily_cap: int


@dataclass(frozen=True, slots=True)
class TravelerPricingPolicy:
    enabled: bool
    max_price_per_kg_eur_cents: int
    max_min_price_eur_cents: int


@dataclass(frozen=True, slots=True)
class ReminderPolicy:
    enabled: bool
    depart_after_minutes: int
    arrive_after_minutes: int
    repeat_after_minutes: int
    max_repeats: int


@dataclass(frozen=True, slots=True)
class RouteChangePolicy:
    material_shift_minutes: int


@dataclass(frozen=True, slots=True)
class OfferDeadlinePolicy:
    """L12A (spec 17.1): how long a proposal waits for an answer."""

    response_deadline_enabled: bool
    #: The deadline is the offer's time plus this, or the pickup time if sooner.
    response_hours: int
    #: One reminder this long before the deadline; 0 means no reminder.
    reminder_before_hours: int


@dataclass(frozen=True, slots=True)
class MarketplacePolicy:
    discovery: DiscoveryPolicy
    sea_legs_enabled: bool
    traveler_pricing: TravelerPricingPolicy
    reminders: ReminderPolicy
    route_change: RouteChangePolicy
    offers: OfferDeadlinePolicy

    @classmethod
    def from_settings(
        cls, settings_version: BusinessSettingsVersion
    ) -> "MarketplacePolicy":
        policy = settings_version.policy
        if not isinstance(policy, dict):
            raise InvalidMarketplacePolicy("Business setting 'policy' must be an object.")
        return cls.from_section(policy.get("marketplace"))

    @classmethod
    def from_section(cls, raw: object) -> "MarketplacePolicy":
        section = _Section(raw, "marketplace", keys=_SCHEMA.keys())
        discovery = _Section(
            section.raw("discovery"), "marketplace.discovery", keys=_DISCOVERY_KEYS
        )
        pricing = _Section(
            section.raw("traveler_pricing"),
            "marketplace.traveler_pricing",
            keys=_PRICING_KEYS,
        )
        reminders = _Section(
            section.raw("reminders"), "marketplace.reminders", keys=_REMINDER_KEYS
        )
        route_change = _Section(
            section.raw("route_change"),
            "marketplace.route_change",
            keys=_ROUTE_CHANGE_KEYS,
        )
        offers = _Section(section.raw("offers"), "marketplace.offers", keys=_OFFER_KEYS)
        response_hours = offers.integer("response_hours", 6, minimum=1, maximum=7 * 24)
        reminder_before_hours = offers.integer(
            "reminder_before_hours", 1, minimum=0, maximum=7 * 24 - 1
        )
        if reminder_before_hours >= response_hours:
            raise InvalidMarketplacePolicy(
                "Business setting 'marketplace.offers.reminder_before_hours' must be "
                "smaller than 'response_hours', or 0 for no reminder."
            )
        return cls(
            discovery=DiscoveryPolicy(
                listings_enabled=discovery.boolean("listings_enabled", True),
                profiles_enabled=discovery.boolean("profiles_enabled", True),
                interest_daily_cap=discovery.integer(
                    "interest_daily_cap", 10, minimum=1, maximum=100
                ),
                trip_fit_alerts_enabled=discovery.boolean("trip_fit_alerts_enabled", True),
                trip_fit_max_travelers=discovery.integer(
                    "trip_fit_max_travelers", 30, minimum=1, maximum=100
                ),
                trip_fit_daily_cap=discovery.integer(
                    "trip_fit_daily_cap", 5, minimum=1, maximum=50
                ),
            ),
            sea_legs_enabled=section.boolean("sea_legs_enabled", False),
            traveler_pricing=TravelerPricingPolicy(
                enabled=pricing.boolean("enabled", True),
                # The same ceiling every sender-chosen money field carries is
                # far above any honest per-kg price; these two are typo guards
                # an operator can tighten, never a commercial rule.
                max_price_per_kg_eur_cents=pricing.integer(
                    "max_price_per_kg_eur_cents", 10_000, minimum=100, maximum=100_000
                ),
                max_min_price_eur_cents=pricing.integer(
                    "max_min_price_eur_cents", 50_000, minimum=100, maximum=1_000_000
                ),
            ),
            reminders=ReminderPolicy(
                enabled=reminders.boolean("enabled", True),
                depart_after_minutes=reminders.integer(
                    "depart_after_minutes", 30, minimum=5, maximum=24 * 60
                ),
                arrive_after_minutes=reminders.integer(
                    "arrive_after_minutes", 60, minimum=5, maximum=24 * 60
                ),
                repeat_after_minutes=reminders.integer(
                    "repeat_after_minutes", 180, minimum=15, maximum=24 * 60
                ),
                max_repeats=reminders.integer("max_repeats", 2, minimum=0, maximum=5),
            ),
            route_change=RouteChangePolicy(
                material_shift_minutes=route_change.integer(
                    "material_shift_minutes", 360, minimum=30, maximum=7 * 24 * 60
                ),
            ),
            offers=OfferDeadlinePolicy(
                response_deadline_enabled=offers.boolean("response_deadline_enabled", True),
                response_hours=response_hours,
                reminder_before_hours=reminder_before_hours,
            ),
        )


_DISCOVERY_KEYS = frozenset(
    {
        "listings_enabled",
        "profiles_enabled",
        "interest_daily_cap",
        "trip_fit_alerts_enabled",
        "trip_fit_max_travelers",
        "trip_fit_daily_cap",
    }
)
_PRICING_KEYS = frozenset(
    {"enabled", "max_price_per_kg_eur_cents", "max_min_price_eur_cents"}
)
_REMINDER_KEYS = frozenset(
    {
        "enabled",
        "depart_after_minutes",
        "arrive_after_minutes",
        "repeat_after_minutes",
        "max_repeats",
    }
)
_ROUTE_CHANGE_KEYS = frozenset({"material_shift_minutes"})
_OFFER_KEYS = frozenset({"response_deadline_enabled", "response_hours", "reminder_before_hours"})
_SCHEMA = {
    "discovery": _DISCOVERY_KEYS,
    "sea_legs_enabled": None,
    "traveler_pricing": _PRICING_KEYS,
    "reminders": _REMINDER_KEYS,
    "route_change": _ROUTE_CHANGE_KEYS,
    "offers": _OFFER_KEYS,
}


class _Section:
    """One object of the section: absent is empty, unknown keys are refused."""

    def __init__(self, raw: object, name: str, *, keys) -> None:
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise InvalidMarketplacePolicy(f"Business setting {name!r} must be an object.")
        unknown = sorted(set(raw) - set(keys))
        if unknown:
            raise InvalidMarketplacePolicy(
                f"Business setting {name!r} has unknown keys: {', '.join(unknown)}."
            )
        self._raw = raw
        self._name = name

    def raw(self, key: str) -> object:
        return self._raw.get(key)

    def boolean(self, key: str, default: bool) -> bool:
        value = self._raw.get(key, default)
        if not isinstance(value, bool):
            raise InvalidMarketplacePolicy(
                f"Business setting '{self._name}.{key}' must be boolean."
            )
        return value

    def integer(self, key: str, default: int, *, minimum: int, maximum: int) -> int:
        value = self._raw.get(key, default)
        name = f"{self._name}.{key}"
        if isinstance(value, bool) or not isinstance(value, int):
            raise InvalidMarketplacePolicy(f"Business setting {name!r} must be an integer.")
        if value < minimum or value > maximum:
            raise InvalidMarketplacePolicy(
                f"Business setting {name!r} must be between {minimum} and {maximum}."
            )
        return value


def marketplace_policy() -> MarketplacePolicy:
    """Load the marketplace policy from the single active settings revision.

    Raises `NoActiveBusinessSettings` when there is no active revision and
    `InvalidMarketplacePolicy` when the active one cannot be parsed; callers
    answer both as a fail-closed 503.
    """

    from .business_settings import get_active_business_settings

    return MarketplacePolicy.from_settings(get_active_business_settings())
