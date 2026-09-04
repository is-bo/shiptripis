"""The provider contract every payment rail implements.

The domain speaks only these dataclasses. A provider adapter translates them to
and from one external API and does nothing else — it never touches a model,
never decides an amount, and never advances an order. That separation is what
lets Stripe, Chargily and the test mock share one reconciliation path.

Provider adapters raise `ProviderUnavailable` for transport-level problems and
`ProviderError` for a definite provider-side rejection. The caller distinguishes
them: unavailable means "try again", error means "this attempt failed".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class ProviderError(RuntimeError):
    """The provider rejected the request definitively."""

    code = "provider_error"

    def __init__(self, message: str, *, provider_code: str = ""):
        super().__init__(message)
        self.provider_code = provider_code


class ProviderUnavailable(ProviderError):
    """The provider could not be reached, or answered with a transient fault."""

    code = "provider_unavailable"


class ProviderNotConfigured(ProviderError):
    """The deployment has not been given the credentials this rail needs."""

    code = "provider_not_configured"


class ProviderSignatureError(ProviderError):
    """A webhook did not carry a signature this provider could have produced."""

    code = "invalid_webhook_signature"


class ProviderCheckoutRejected(ProviderError):
    """The provider understood the request and refused to open a checkout.

    Separate from the bare `ProviderError` so a payer can be told the truth —
    the payment could not be started — instead of the catch-all "something went
    wrong, try again", which is both useless and, for a definite rejection,
    wrong: retrying will fail identically.
    """

    code = "provider_checkout_failed"


class ProviderConfigurationInvalid(ProviderError):
    """Credentials are present but describe a configuration nobody should use.

    Distinct from `ProviderNotConfigured`, and the distinction matters: "no key"
    is an incomplete deployment, while "a key and a base URL that disagree about
    which environment they are" is a deployment that will happily attempt a
    transaction against the wrong one. The safe answer to the second is to
    refuse new checkouts, not to guess which half is right.
    """

    code = "provider_configuration_invalid"


class RefundNotSupported(ProviderError):
    """This rail has no refund API; the refund is an operator action.

    A distinct class rather than a magic string, so the caller can branch on
    the type and cannot silently stop matching if a message changes. Chargily
    Pay v2 is the case that needs it.
    """

    code = "refund_not_supported"


@dataclass(frozen=True, slots=True)
class CheckoutRequest:
    """Everything a provider needs to open a hosted checkout.

    `amount_minor` and `currency` are already resolved by the domain: the
    adapter charges exactly what it is given and never recomputes or converts.
    """

    reference: str
    amount_minor: int
    currency: str
    amount_exponent: int
    idempotency_key: str
    success_url: str
    failure_url: str
    webhook_url: str
    description: str
    metadata: dict[str, str] = field(default_factory=dict)
    customer_email: str = ""


@dataclass(frozen=True, slots=True)
class CheckoutResult:
    provider_session_id: str
    checkout_url: str
    #: Provider's own state right after creation. Never treated as success.
    provider_status: str = "pending"
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RefundRequest:
    provider_payment_id: str
    provider_session_id: str
    amount_minor: int
    currency: str
    idempotency_key: str
    reason: str = ""


@dataclass(frozen=True, slots=True)
class RefundResult:
    provider_refund_id: str
    succeeded: bool
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderEvent:
    """A verified, normalised inbound provider event.

    `outcome` is the only thing the reconciliation service reads. Provider
    vocabulary stops here.
    """

    provider: str
    event_id: str
    event_type: str
    outcome: str  # one of: succeeded | failed | expired | cancelled | ignored
    provider_session_id: str = ""
    provider_payment_id: str = ""
    reference: str = ""
    amount_minor: int | None = None
    currency: str = ""
    guest_email: str = ""
    failure_code: str = ""
    payload: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AttemptSnapshot:
    """The provider's current view of one attempt, used for reconciliation."""

    outcome: str
    provider_payment_id: str = ""
    amount_minor: int | None = None
    currency: str = ""
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PayoutCapability:
    """What a provider actually reports about paying one traveler.

    Never inferred from a country. `available` is true only when the provider
    itself says transfers and payouts are enabled for that account.
    """

    available: bool
    reason: str = ""
    account_id: str = ""
    country_code: str = ""
    raw: dict = field(default_factory=dict)


#: What a rail's configured credentials point at. Derived from the credential's
#: own documented shape, never from a value anybody has to read or log: an
#: operator must be able to see that a deployment is pointed at real money
#: without being shown the key that moves it.
MODE_TEST = "test"
MODE_LIVE = "live"
#: Configured, but the credential does not carry a shape this code recognises.
#: Reported rather than guessed — assuming "test" here is how a live rail gets
#: transacted against by accident.
MODE_UNKNOWN = "unknown"
MODE_NOT_CONFIGURED = "not_configured"


class PaymentGateway(Protocol):
    """The full rail interface. Not every rail supports every capability."""

    name: str
    supports_guest_payment: bool
    payment_currency: str

    def is_configured(self) -> bool: ...

    def credential_mode(self) -> str: ...

    def configuration_problem(self) -> str:
        """A machine code for a configuration that is present but unusable.

        Empty means the configuration is coherent. A non-empty code is a stop
        condition for *new* checkouts only: webhooks, reconciliation and refunds
        for money that already exists keep working, because refusing those would
        strand real payments rather than prevent one.
        """
        ...

    def create_checkout(self, request: CheckoutRequest) -> CheckoutResult: ...

    def fetch_attempt(
        self, *, provider_session_id: str, provider_payment_id: str
    ) -> AttemptSnapshot: ...

    def refund(self, request: RefundRequest) -> RefundResult: ...

    def parse_webhook(
        self, *, raw_body: bytes, headers: dict[str, str]
    ) -> ProviderEvent: ...
