"""Integer-only money arithmetic for the V1 financial architecture.

Nothing in this module uses `float`. Every helper takes and returns `int`, and
every rounding decision is stated rather than inherited from a floating-point
mode. The rule throughout is: round in the direction that never leaves ShipTrip
short, and never invent precision the source amount did not have.

Currency units
--------------
EUR is canonical and stored as integer cents (exponent 2).

DZD is a provider settlement representation only. Chargily's API expresses DZD
as whole dinars (exponent 0), which is also how the currency circulates: there
is no sub-dinar denomination in practice. Converting therefore *loses*
precision, and the residual is a rounding difference we absorb deliberately
rather than a discrepancy to reconcile.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

#: Minor units per major unit, expressed as the base-10 exponent.
CURRENCY_EXPONENTS: dict[str, int] = {
    "EUR": 2,
    "DZD": 0,
}

#: Scaling factor for a stored FX rate. A rate of 150.25 DZD per EUR is stored
#: as 150_250_000, so a rate is exact to six decimal places with no float in
#: the path.
FX_RATE_SCALE = 1_000_000

CANONICAL_CURRENCY = "EUR"


class MoneyError(ValueError):
    """A money value or conversion is not representable."""

    code = "invalid_money"


def currency_exponent(currency: str) -> int:
    try:
        return CURRENCY_EXPONENTS[currency.upper()]
    except KeyError as exc:
        raise MoneyError(f"Unsupported currency {currency!r}.") from exc


def require_positive_cents(value: object, *, name: str = "amount") -> int:
    """Validate an integer EUR-cent amount coming from anywhere but a column."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise MoneyError(f"{name} must be an integer number of cents.")
    if value <= 0:
        raise MoneyError(f"{name} must be greater than zero.")
    return value


def clamp(value: int, *, minimum: int, maximum: int) -> int:
    """Clamp an integer into an inclusive range, validating the range itself."""

    if minimum > maximum:
        raise MoneyError("Clamp minimum cannot exceed the maximum.")
    return max(minimum, min(maximum, value))


def percentage_of(amount_cents: int, *, bps: int) -> int:
    """Take `bps` basis points of `amount_cents`, rounded half up.

    Half-up rather than ceiling: a posting deposit is not a fee, it is a
    prepayment of the sender's own balance, so there is no reason to round it
    against them. The clamp around it is what actually bounds the value.
    """

    if isinstance(bps, bool) or not isinstance(bps, int) or bps < 0:
        raise MoneyError("Basis points must be a non-negative integer.")
    if isinstance(amount_cents, bool) or not isinstance(amount_cents, int):
        raise MoneyError("Amount must be an integer number of cents.")
    scaled = Decimal(amount_cents) * Decimal(bps) / Decimal(10_000)
    return int(scaled.to_integral_value(rounding=ROUND_HALF_UP))


def convert_eur_cents(
    amount_eur_cents: int,
    *,
    to_currency: str,
    rate_micros: int,
) -> int:
    """Convert canonical EUR cents into another currency's minor units.

    `rate_micros` is target-currency major units per one EUR, scaled by
    `FX_RATE_SCALE`. The result is rounded **up**: charging a fraction of a
    dinar is impossible, and rounding down would collect less than the EUR
    obligation requires.

    The whole computation is exact integer arithmetic, so the stored provider
    amount is reproducible from the stored rate forever.
    """

    amount_eur_cents = require_positive_cents(
        amount_eur_cents, name="amount_eur_cents"
    )
    if isinstance(rate_micros, bool) or not isinstance(rate_micros, int):
        raise MoneyError("FX rate must be an integer number of micros.")
    if rate_micros <= 0:
        raise MoneyError("FX rate must be greater than zero.")

    target_exponent = currency_exponent(to_currency)
    source_exponent = CURRENCY_EXPONENTS[CANONICAL_CURRENCY]

    # major EUR = amount_eur_cents / 10**source_exponent
    # major target = major EUR * rate_micros / FX_RATE_SCALE
    # minor target = major target * 10**target_exponent, rounded up
    #
    # Plain Python ints, not Decimal: Decimal's // truncates toward zero, so the
    # usual -(-a // b) ceiling trick silently rounds *down* there. Integer
    # floor division is exact and has no such edge.
    numerator = amount_eur_cents * rate_micros * (10**target_exponent)
    denominator = FX_RATE_SCALE * (10**source_exponent)
    result = -(-numerator // denominator)  # exact integer ceiling division
    if result <= 0:
        raise MoneyError("Converted amount rounded to zero.")
    return result


def format_rate(rate_micros: int) -> str:
    """Render a stored rate for display, e.g. '150.250000'."""

    return str(Decimal(rate_micros) / Decimal(FX_RATE_SCALE))


def format_minor(amount_minor: int, *, exponent: int) -> str:
    """Render a minor-unit amount as a decimal string for display/audit."""

    if exponent == 0:
        return str(int(amount_minor))
    return str(Decimal(amount_minor) / (Decimal(10) ** exponent))
