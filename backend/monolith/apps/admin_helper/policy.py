"""The AI helper switch and its settings (spec 20.8, plan L15).

One top-level section of `BusinessSettingsVersion.policy`, read in the style of
the marketplace policy (plan 2.1)::

    "admin_helper": {"enabled": true, "read_key_hours": 8, "change_key_minutes": 30,
                     "prepared_action_valid_hours": 24, "requests_per_minute": 60}

* **Absent means defaults**, for the section and for each key, so a revision
  written before L15 behaves exactly as the defaults. The helper ships on.
* **Unknown keys are refused** when a revision is saved
  (`AdminSettingsCreateSerializer` runs this parser), so a misspelt switch
  never becomes active.
* **Read at the moment of each call.** Turning the switch off stops every key
  at once (spec 20.2); a new duration applies to keys created from then on,
  because a key's expiry is fixed when it is created.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.core.models import BusinessSettingsVersion

SECTION = "admin_helper"


class InvalidAdminHelperPolicy(RuntimeError):
    """The active settings revision cannot drive the AI helper."""

    code = "admin_helper_policy_unavailable"


#: ``key: (default, minimum, maximum)`` for the integers; bounds from plan L15.
_INTEGERS = {
    "read_key_hours": (8, 1, 8),
    "change_key_minutes": (30, 5, 60),
    "prepared_action_valid_hours": (24, 1, 72),
    "requests_per_minute": (60, 10, 300),
}
_KEYS = frozenset({"enabled", *_INTEGERS})


@dataclass(frozen=True, slots=True)
class AdminHelperPolicy:
    enabled: bool
    #: A read key expires this long after it is created, even while in use.
    read_key_hours: int
    #: A change key's life (L16).
    change_key_minutes: int
    #: How long a change the helper prepared waits for its admin (L16).
    prepared_action_valid_hours: int
    #: Calls one key may make in a minute.
    requests_per_minute: int

    @classmethod
    def from_settings(cls, settings_version: BusinessSettingsVersion) -> "AdminHelperPolicy":
        policy = settings_version.policy
        if not isinstance(policy, dict):
            raise InvalidAdminHelperPolicy("Business setting 'policy' must be an object.")
        return cls.from_section(policy.get(SECTION))

    @classmethod
    def from_section(cls, raw: object) -> "AdminHelperPolicy":
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise InvalidAdminHelperPolicy(f"Business setting {SECTION!r} must be an object.")
        unknown = sorted(set(raw) - _KEYS)
        if unknown:
            raise InvalidAdminHelperPolicy(
                f"Business setting {SECTION!r} has unknown keys: {', '.join(unknown)}."
            )
        enabled = raw.get("enabled", True)
        if not isinstance(enabled, bool):
            raise InvalidAdminHelperPolicy(f"Business setting '{SECTION}.enabled' must be boolean.")
        values = {}
        for key, (default, minimum, maximum) in _INTEGERS.items():
            value = raw.get(key, default)
            name = f"{SECTION}.{key}"
            if isinstance(value, bool) or not isinstance(value, int):
                raise InvalidAdminHelperPolicy(f"Business setting {name!r} must be an integer.")
            if not minimum <= value <= maximum:
                raise InvalidAdminHelperPolicy(
                    f"Business setting {name!r} must be between {minimum} and {maximum}."
                )
            values[key] = value
        return cls(enabled=enabled, **values)


def bounds(key: str) -> tuple[int, int]:
    """``(minimum, maximum)`` of one integer setting, for the console form."""

    _default, minimum, maximum = _INTEGERS[key]
    return minimum, maximum


def admin_helper_policy() -> AdminHelperPolicy:
    """The policy of the single active settings revision.

    Raises `NoActiveBusinessSettings` or `InvalidAdminHelperPolicy`; the helper
    answers both by refusing every key, which is the safe side.
    """

    from apps.core.business_settings import get_active_business_settings

    return AdminHelperPolicy.from_settings(get_active_business_settings())
