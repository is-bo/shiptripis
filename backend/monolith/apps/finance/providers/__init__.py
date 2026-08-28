"""Server-authoritative provider registry and availability.

Two rules this module exists to enforce:

1. **Availability is decided here, not by the client.** A provider is offered
   only when the versioned business policy enables it *and* the deployment
   actually holds its credentials. A Flutter button is not a capability.

2. **MOCK cannot function as a production payment provider.** It is returned
   only when `settings.PAYMENTS_ALLOW_MOCK_PROVIDER` is explicitly on, and
   `config.settings.prod` refuses to start when that flag is set. There is no
   code path anywhere that falls back from Stripe or Chargily to mock: a
   misconfigured real provider raises `ProviderNotConfigured` and the checkout
   fails, which is the safe outcome.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from ..models import PaymentProvider
from ..policy import Phase3Policy
from .base import (
    AttemptSnapshot,
    CheckoutRequest,
    CheckoutResult,
    PaymentGateway,
    PayoutCapability,
    ProviderError,
    ProviderEvent,
    ProviderNotConfigured,
    ProviderSignatureError,
    ProviderUnavailable,
    RefundNotSupported,
    RefundRequest,
    RefundResult,
)
from .chargily import ChargilyGateway
from .mock import MockGateway
from .stripe import StripeGateway

__all__ = [
    "AttemptSnapshot",
    "CheckoutRequest",
    "CheckoutResult",
    "ChargilyGateway",
    "MockGateway",
    "PaymentGateway",
    "PayoutCapability",
    "ProviderAvailability",
    "ProviderError",
    "ProviderEvent",
    "ProviderNotConfigured",
    "ProviderSignatureError",
    "ProviderUnavailable",
    "RefundNotSupported",
    "RefundRequest",
    "RefundResult",
    "StripeGateway",
    "available_providers",
    "get_gateway",
    "mock_allowed",
    "resolve_gateway_for_checkout",
]


class ProviderDisabled(ProviderError):
    """The provider exists but this deployment or policy will not use it."""

    code = "provider_disabled"


class NewCheckoutsDisabled(ProviderError):
    """The provider still processes events and refunds, but takes no new work."""

    code = "provider_new_checkouts_disabled"


@dataclass(frozen=True, slots=True)
class ProviderAvailability:
    provider: str
    enabled: bool
    configured: bool
    accepts_new_checkouts: bool
    payment_currency: str
    supports_guest_payment: bool
    unavailable_reason: str = ""

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "available": self.enabled and self.configured and self.accepts_new_checkouts,
            "payment_currency": self.payment_currency,
            "supports_guest_payment": self.supports_guest_payment,
            "unavailable_reason": self.unavailable_reason,
        }


def mock_allowed() -> bool:
    """Whether this deployment may hand out the mock rail at all."""

    return bool(getattr(settings, "PAYMENTS_ALLOW_MOCK_PROVIDER", False))


def _build(provider: str) -> PaymentGateway:
    if provider == PaymentProvider.STRIPE:
        return StripeGateway()
    if provider == PaymentProvider.CHARGILY:
        return ChargilyGateway()
    if provider == PaymentProvider.MOCK:
        if not mock_allowed():
            raise ProviderNotConfigured(
                "The mock payment provider is not enabled in this deployment."
            )
        return MockGateway()
    raise ProviderNotConfigured(f"Unknown payment provider {provider!r}.")


def get_gateway(provider: str) -> PaymentGateway:
    """Return the adapter for a provider without consulting business policy.

    Used by webhook and refund paths, which must keep working for money that
    already exists even after the provider is disabled for new checkouts.
    """

    return _build(provider)


def _policy_enabled(policy: Phase3Policy, provider: str) -> bool:
    if provider == PaymentProvider.STRIPE:
        return policy.providers.stripe_enabled
    if provider == PaymentProvider.CHARGILY:
        return policy.providers.chargily_enabled
    if provider == PaymentProvider.MOCK:
        return policy.providers.mock_enabled and mock_allowed()
    return False


def _accepts_new_checkouts(policy: Phase3Policy, provider: str) -> bool:
    if provider == PaymentProvider.CHARGILY:
        return policy.chargily.new_checkouts_enabled
    return True


def availability(policy: Phase3Policy, provider: str) -> ProviderAvailability:
    enabled = _policy_enabled(policy, provider)
    configured = False
    payment_currency = ""
    supports_guest = False
    reason = ""
    try:
        gateway = _build(provider)
        configured = gateway.is_configured()
        payment_currency = gateway.payment_currency
        supports_guest = gateway.supports_guest_payment
    except ProviderNotConfigured as exc:
        reason = exc.code
    accepts_new = _accepts_new_checkouts(policy, provider)
    if not reason:
        if not enabled:
            reason = "disabled_by_policy"
        elif not configured:
            reason = "provider_not_configured"
        elif not accepts_new:
            reason = "new_checkouts_disabled"
    return ProviderAvailability(
        provider=provider,
        enabled=enabled,
        configured=configured,
        accepts_new_checkouts=accepts_new,
        payment_currency=payment_currency,
        supports_guest_payment=supports_guest,
        unavailable_reason=reason,
    )


def available_providers(
    policy: Phase3Policy, *, guest_only: bool = False
) -> list[ProviderAvailability]:
    """The server's answer to 'what may this caller pay with right now?'."""

    rows = [
        availability(policy, provider)
        for provider in (
            PaymentProvider.STRIPE,
            PaymentProvider.CHARGILY,
            PaymentProvider.MOCK,
        )
    ]
    if guest_only:
        rows = [row for row in rows if row.supports_guest_payment]
    return rows


def resolve_gateway_for_checkout(
    policy: Phase3Policy, provider: str, *, guest: bool = False
) -> PaymentGateway:
    """Return a gateway for a *new* checkout, or refuse with a reason.

    Every refusal is explicit. Nothing here silently substitutes a different
    rail, and in particular nothing substitutes the mock.
    """

    if provider not in dict(PaymentProvider.choices):
        raise ProviderNotConfigured(f"Unknown payment provider {provider!r}.")
    if not _policy_enabled(policy, provider):
        raise ProviderDisabled(f"{provider} is disabled for this deployment.")
    if not _accepts_new_checkouts(policy, provider):
        raise NewCheckoutsDisabled(
            f"{provider} is not accepting new checkouts right now."
        )
    gateway = _build(provider)
    if not gateway.is_configured():
        raise ProviderNotConfigured(f"{provider} credentials are not configured.")
    if guest and not gateway.supports_guest_payment:
        raise ProviderDisabled(f"{provider} cannot take a third-party payment.")
    return gateway
