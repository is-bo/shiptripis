"""Versioned Phase 3 payment policy.

Everything commercially tunable about payments lives in the immutable
`BusinessSettingsVersion.policy["payments"]` object, and is read through this
validating parser rather than off raw dictionaries. The parser is strict on
purpose: a malformed or missing payment policy raises, and every money-moving
entry point fails closed rather than guessing a default.

The seeded shape is::

    "payments": {
      "timing_mode": "posting_deposit",
      "posting_deposit": {
        "percent_bps": 1000,
        "min_eur_cents": 300,
        "max_eur_cents": 700,
        "chosen_min_eur_cents": 300,
        "expiry_grace_seconds": 0
      },
      "providers": {
        "stripe_enabled": true,
        "chargily_enabled": true,
        "mock_enabled": false
      },
      "chargily": {
        "eur_dzd_rate_micros": 150000000,
        "new_checkouts_enabled": true,
        "min_amount_dzd": 75
      },
      "checkout": {"attempt_ttl_seconds": 3600},
      "guest": {"link_ttl_seconds": 259200},
      "payout": {"protection_window_seconds": 172800, "auto_stripe_enabled": false}
    }

Two Chargily switches exist deliberately and mean different things.
``providers.chargily_enabled`` removes Chargily from the client's provider list.
``chargily.new_checkouts_enabled`` stops *new* checkouts while leaving webhook
processing, reconciliation, refunds and history fully operational — that is the
switch an operator reaches for during an incident.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from apps.core.models import BusinessSettingsVersion


class InvalidPaymentPolicy(RuntimeError):
    """The active settings revision cannot drive payments."""

    code = "invalid_payment_policy"


def _object(value: object, name: str) -> dict:
    if not isinstance(value, dict):
        raise InvalidPaymentPolicy(f"Business setting '{name}' must be an object.")
    return value


def _int(value: object, name: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidPaymentPolicy(f"Business setting '{name}' must be an integer.")
    if value < minimum:
        raise InvalidPaymentPolicy(
            f"Business setting '{name}' must be at least {minimum}."
        )
    if maximum is not None and value > maximum:
        raise InvalidPaymentPolicy(
            f"Business setting '{name}' must not exceed {maximum}."
        )
    return value


def _bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise InvalidPaymentPolicy(f"Business setting '{name}' must be boolean.")
    return value


class PaymentTimingMode:
    AFTER_ACCEPTANCE = "after_acceptance"
    POSTING_DEPOSIT = "posting_deposit"

    CHOICES = (AFTER_ACCEPTANCE, POSTING_DEPOSIT)


@dataclass(frozen=True, slots=True)
class PostingDepositPolicy:
    """Two different numbers, deliberately not one.

    ``percent_bps`` with ``min_eur_cents``/``max_eur_cents`` produces the
    *recommendation*: a tenth of the recommended sender total, clamped into the
    EUR 3-7 band. It is guidance, and the clamp is what keeps the suggestion
    sensible at both ends of the price range.

    ``chosen_min_eur_cents`` is the floor under a deposit the sender picks for
    themselves (J2). There is deliberately no matching ceiling: a sender may
    pre-pay any amount up to the obligation they are pre-paying against, and
    the recommendation's EUR 7 clamp is not a limit on what they may choose.
    """

    percent_bps: int
    min_eur_cents: int
    max_eur_cents: int
    chosen_min_eur_cents: int
    expiry_grace_seconds: int


@dataclass(frozen=True, slots=True)
class ChargilyPolicy:
    eur_dzd_rate_micros: int
    new_checkouts_enabled: bool
    min_amount_dzd: int


@dataclass(frozen=True, slots=True)
class ProviderPolicy:
    stripe_enabled: bool
    chargily_enabled: bool
    mock_enabled: bool


@dataclass(frozen=True, slots=True)
class PayoutPolicy:
    protection_window_seconds: int
    auto_stripe_enabled: bool


@dataclass(frozen=True, slots=True)
class Phase3Policy:
    settings_version: BusinessSettingsVersion
    timing_mode: str
    posting_deposit: PostingDepositPolicy
    providers: ProviderPolicy
    chargily: ChargilyPolicy
    payout: PayoutPolicy
    attempt_ttl_seconds: int
    guest_link_ttl_seconds: int

    @property
    def deposit_required(self) -> bool:
        return self.timing_mode == PaymentTimingMode.POSTING_DEPOSIT

    @classmethod
    def from_settings(cls, settings_version: BusinessSettingsVersion) -> "Phase3Policy":
        policy = _object(settings_version.policy, "policy")
        payments = _object(policy.get("payments"), "payments")

        timing_mode = payments.get("timing_mode")
        if timing_mode not in PaymentTimingMode.CHOICES:
            raise InvalidPaymentPolicy(
                "Business setting 'payments.timing_mode' must be "
                f"one of {PaymentTimingMode.CHOICES}."
            )

        deposit = _object(payments.get("posting_deposit"), "payments.posting_deposit")
        deposit_policy = PostingDepositPolicy(
            percent_bps=_int(
                deposit.get("percent_bps"),
                "payments.posting_deposit.percent_bps",
                minimum=0,
                maximum=10_000,
            ),
            min_eur_cents=_int(
                deposit.get("min_eur_cents"),
                "payments.posting_deposit.min_eur_cents",
                minimum=1,
                maximum=100_000,
            ),
            max_eur_cents=_int(
                deposit.get("max_eur_cents"),
                "payments.posting_deposit.max_eur_cents",
                minimum=1,
                maximum=100_000,
            ),
            # Defaulted to the recommendation floor so a revision written
            # before J2 keeps taking deposits at exactly the amount it always
            # did, rather than failing closed on a key it never had.
            chosen_min_eur_cents=_int(
                deposit.get(
                    "chosen_min_eur_cents",
                    _int(
                        deposit.get("min_eur_cents"),
                        "payments.posting_deposit.min_eur_cents",
                        minimum=1,
                        maximum=100_000,
                    ),
                ),
                "payments.posting_deposit.chosen_min_eur_cents",
                minimum=1,
                maximum=100_000,
            ),
            expiry_grace_seconds=_int(
                deposit.get("expiry_grace_seconds", 0),
                "payments.posting_deposit.expiry_grace_seconds",
                minimum=0,
                maximum=30 * 24 * 3_600,
            ),
        )
        if deposit_policy.min_eur_cents > deposit_policy.max_eur_cents:
            raise InvalidPaymentPolicy(
                "Posting-deposit minimum cannot exceed the maximum."
            )

        providers = _object(payments.get("providers"), "payments.providers")
        provider_policy = ProviderPolicy(
            stripe_enabled=_bool(
                providers.get("stripe_enabled"), "payments.providers.stripe_enabled"
            ),
            chargily_enabled=_bool(
                providers.get("chargily_enabled"),
                "payments.providers.chargily_enabled",
            ),
            mock_enabled=_bool(
                providers.get("mock_enabled", False),
                "payments.providers.mock_enabled",
            ),
        )

        chargily = _object(payments.get("chargily"), "payments.chargily")
        chargily_policy = ChargilyPolicy(
            eur_dzd_rate_micros=_int(
                chargily.get("eur_dzd_rate_micros"),
                "payments.chargily.eur_dzd_rate_micros",
                minimum=1,
                # A rate above 100_000 DZD per EUR is a data-entry accident,
                # not a market move. Refuse it rather than charge it.
                maximum=100_000 * 1_000_000,
            ),
            new_checkouts_enabled=_bool(
                chargily.get("new_checkouts_enabled"),
                "payments.chargily.new_checkouts_enabled",
            ),
            min_amount_dzd=_int(
                chargily.get("min_amount_dzd", 75),
                "payments.chargily.min_amount_dzd",
                minimum=1,
                maximum=1_000_000,
            ),
        )

        payout = _object(payments.get("payout"), "payments.payout")
        payout_policy = PayoutPolicy(
            protection_window_seconds=_int(
                payout.get("protection_window_seconds"),
                "payments.payout.protection_window_seconds",
                minimum=0,
                maximum=30 * 24 * 3_600,
            ),
            auto_stripe_enabled=_bool(
                payout.get("auto_stripe_enabled", False),
                "payments.payout.auto_stripe_enabled",
            ),
        )

        checkout = _object(payments.get("checkout", {}), "payments.checkout")
        guest = _object(payments.get("guest", {}), "payments.guest")

        return cls(
            settings_version=settings_version,
            timing_mode=timing_mode,
            posting_deposit=deposit_policy,
            providers=provider_policy,
            chargily=chargily_policy,
            payout=payout_policy,
            attempt_ttl_seconds=_int(
                checkout.get("attempt_ttl_seconds", 3_600),
                "payments.checkout.attempt_ttl_seconds",
                minimum=300,
                maximum=7 * 24 * 3_600,
            ),
            guest_link_ttl_seconds=_int(
                guest.get("link_ttl_seconds", 3 * 24 * 3_600),
                "payments.guest.link_ttl_seconds",
                minimum=600,
                maximum=30 * 24 * 3_600,
            ),
        )

    def snapshot(self) -> dict:
        """The immutable record copied onto an order's terms_snapshot.

        The Chargily rate is deliberately *not* here: an order is a canonical
        EUR obligation, and the rate belongs to the individual attempt that
        used it.
        """

        return {
            "business_settings_version": self.settings_version.version,
            "pricing_version": self.settings_version.pricing_version,
            "canonical_currency": "EUR",
            "commission_rate_bps": self.settings_version.commission_rate_bps,
            "payments": deepcopy(
                self.settings_version.policy.get("payments", {})
            ),
        }


def phase3_policy() -> Phase3Policy:
    """Load the Phase 3 policy from the single active settings revision."""

    from apps.core.business_settings import get_active_business_settings

    return Phase3Policy.from_settings(get_active_business_settings())
