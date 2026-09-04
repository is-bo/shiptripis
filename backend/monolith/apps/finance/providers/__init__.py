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
    MODE_LIVE,
    MODE_NOT_CONFIGURED,
    MODE_TEST,
    MODE_UNKNOWN,
    AttemptSnapshot,
    CheckoutRequest,
    CheckoutResult,
    PaymentGateway,
    PayoutCapability,
    ProviderCheckoutRejected,
    ProviderConfigurationInvalid,
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
    "MODE_LIVE",
    "MODE_NOT_CONFIGURED",
    "MODE_TEST",
    "MODE_UNKNOWN",
    "AttemptSnapshot",
    "CheckoutRequest",
    "CheckoutResult",
    "ChargilyGateway",
    "MockGateway",
    "PaymentGateway",
    "PayoutCapability",
    "ProviderAvailability",
    "ProviderCheckoutRejected",
    "ProviderConfigurationInvalid",
    "ProviderDisabled",
    "ProviderError",
    "ProviderEvent",
    "ProviderNotConfigured",
    "ProviderSignatureError",
    "ProviderUnavailable",
    "NewCheckoutsDisabled",
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
    #: The currency this rail settles in, decided by the rail. Stripe is EUR,
    #: Chargily is DZD. It is never a payer's choice and never a client's
    #: input: `_resolve_amounts` reads it from the gateway, and the checkout
    #: contract refuses a request that states a currency at all.
    payment_currency: str
    supports_guest_payment: bool
    unavailable_reason: str = ""
    #: `test`, `live`, `unknown` or `not_configured`, from the credential's
    #: documented shape. Configuration and enablement are separate facts and
    #: this is a third: a rail can be configured for live money and disabled,
    #: and an operator has to be able to see all three at once.
    credential_mode: str = MODE_NOT_CONFIGURED
    #: Empty when the configuration is coherent; otherwise the machine code for
    #: why credentials that exist still must not open a checkout.
    configuration_problem: str = ""

    @property
    def configuration_valid(self) -> bool:
        return not self.configuration_problem

    @property
    def available(self) -> bool:
        """The single gate a "pay with this" control may be enabled from."""

        return (
            self.enabled
            and self.configured
            and self.configuration_valid
            and self.accepts_new_checkouts
        )

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "available": self.available,
            "payment_currency": self.payment_currency,
            "supports_guest_payment": self.supports_guest_payment,
            "unavailable_reason": self.unavailable_reason,
        }

    def as_operator_dict(self) -> dict:
        """The admin/health view: enablement, configuration and mode apart.

        Never served to a payer. `as_dict` stays the payer-facing contract, so
        adding an operational fact here cannot leak one into a checkout.
        """

        return {
            **self.as_dict(),
            "enabled": self.enabled,
            "configured": self.configured,
            "configuration_valid": self.configuration_valid,
            "configuration_problem": self.configuration_problem,
            "accepts_new_checkouts": self.accepts_new_checkouts,
            "credential_mode": self.credential_mode,
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
    credential_mode = MODE_NOT_CONFIGURED
    problem = ""
    reason = ""
    try:
        gateway = _build(provider)
        configured = gateway.is_configured()
        payment_currency = gateway.payment_currency
        supports_guest = gateway.supports_guest_payment
        credential_mode = gateway.credential_mode()
        problem = gateway.configuration_problem() if configured else ""
    except ProviderNotConfigured as exc:
        reason = exc.code
    accepts_new = _accepts_new_checkouts(policy, provider)
    if not reason:
        if not enabled:
            reason = "disabled_by_policy"
        elif not configured:
            reason = "provider_not_configured"
        elif problem:
            # An enabled, credentialled rail whose environment cannot be
            # identified reports *that*, not "disabled". An operator who turned
            # it on needs to see the difference between a switch and a fault.
            reason = "provider_configuration_invalid"
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
        credential_mode=credential_mode,
        configuration_problem=problem,
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
    # Credentials that exist but describe an environment nobody can identify
    # stop here, before any money moves. This is deliberately *not* enforced in
    # `get_gateway`: webhooks, reconciliation and refunds for payments that
    # already exist must keep working while an operator repairs the setting.
    if problem := gateway.configuration_problem():
        raise ProviderConfigurationInvalid(
            f"{provider} configuration is incomplete or inconsistent.",
            provider_code=problem,
        )
    if guest and not gateway.supports_guest_payment:
        raise ProviderDisabled(f"{provider} cannot take a third-party payment.")
    return gateway
