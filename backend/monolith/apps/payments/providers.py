"""Payment provider abstraction.

V1: only `MockProvider` is wired. It instantly returns succeeded results.

V2: add `StripeProvider` and `EdahabiaProvider` that hit real APIs. The
calling code (views, webhook handler) doesn't change — it goes through
`get_provider(name)` and uses the same interface.

Keep this file SDK-free for V1 so test runs don't need network or extra
deps. Real SDKs are imported lazily inside their subclass.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CreateIntentResult:
    """What the provider returned when we asked it to create/confirm an intent.

    `client_action` would carry redirect URLs / 3DS challenges for real
    providers; for mock it's always None.
    """
    provider_intent_id: str
    status: str           # one of PaymentIntent.Status values
    client_action: dict | None = None


@dataclass(frozen=True, slots=True)
class RefundResult:
    provider_refund_id: str
    status: str           # one of Refund.Status values


class PaymentProvider(Protocol):
    """Minimal interface every concrete provider must implement.

    `currency_supported` lets the chooser route DZD senders to Edahabia and
    EUR senders to Stripe (in V2). In V1, mock supports everything.
    """

    name: str

    def currency_supported(self, currency: str) -> bool: ...

    def create_intent(
        self,
        *,
        amount_minor: int,
        currency: str,
        payer_user_id: int,
        idempotency_key: str,
    ) -> CreateIntentResult: ...

    def refund(
        self,
        *,
        provider_intent_id: str,
        amount_minor: int,
        currency: str,
        reason: str = "",
    ) -> RefundResult: ...


class MockProvider:
    """V1 stub provider — instantly succeeds, looks like Stripe on the wire.

    Returns IDs in `pi_mock_*` / `re_mock_*` shape so they're visually
    distinguishable from real Stripe IDs but otherwise behave identically.
    """

    name = "mock"

    def currency_supported(self, currency: str) -> bool:
        return currency in {"DZD", "EUR"}

    def create_intent(
        self,
        *,
        amount_minor: int,
        currency: str,
        payer_user_id: int,
        idempotency_key: str,
    ) -> CreateIntentResult:
        # Deterministic-ish but unique per call; uses a token so the API
        # surface mirrors Stripe's stochastic IDs.
        suffix = f"{int(time.time() * 1000):x}_{secrets.token_hex(4)}"
        return CreateIntentResult(
            provider_intent_id=f"pi_mock_{suffix}",
            status="succeeded",
            client_action=None,
        )

    def refund(
        self,
        *,
        provider_intent_id: str,
        amount_minor: int,
        currency: str,
        reason: str = "",
    ) -> RefundResult:
        return RefundResult(
            provider_refund_id=f"re_mock_{secrets.token_hex(6)}",
            status="succeeded",
        )


_REGISTRY: dict[str, PaymentProvider] = {"mock": MockProvider()}


def get_provider(name: str) -> PaymentProvider:
    """Return the named provider. V1 only knows `mock`; V2 will add stripe/edahabia."""
    if name not in _REGISTRY:
        raise ValueError(f"Unknown payment provider: {name!r}")
    return _REGISTRY[name]


def choose_provider(currency: str) -> PaymentProvider:
    """Pick a provider for the currency.

    V1: always mock. V2: EUR→Stripe, DZD→Edahabia.
    """
    return _REGISTRY["mock"]
