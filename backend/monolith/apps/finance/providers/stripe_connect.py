"""Stripe Connect adapter for Traveler payout accounts.

Deliberately separate from `providers/stripe.py`. That module owns Sender
Checkout on the platform's own account and keeps its own API version; this one
owns the connected-account surface and pins its own. Mixing them would mean one
version bump to the payout rail silently re-versioning every Sender payment.

Three properties define this boundary:

* **It decides nothing.** No earnings, no eligibility, no routing, no FX, no
  rail choice. It turns typed requests into Stripe's documented HTTP contract
  and Stripe's answers into typed results. Every judgement lives in the Django
  finance domain.
* **It executes, it does not authorise.** H3 added the four money-moving calls
  Stripe's separate charges-and-transfers flow needs — platform Transfer,
  connected-account bank Payout, payout cancel and transfer reversal — plus the
  reads that reconcile them. Every one of them requires the caller to supply an
  amount, a destination, an account scope and an idempotency key that the
  finance domain computed under lock. Nothing here decides that a payout is due,
  and nothing here retries: an ambiguous answer is raised as such so the caller
  can recover the *same* operation rather than issue a second one.
* **It pins its own API version.** Every request carries
  `Stripe-Version: STRIPE_CONNECT_API_VERSION` explicitly, so the connected
  account contract is the one this code was written and tested against rather
  than whatever default the platform account happens to be on.

Account-scoped operations send the `Stripe-Account` header. The scope is always
supplied by the caller, never inferred here, because "which account is this
request for" is a financial-authority question.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import urlencode

import requests
from django.conf import settings

from .base import (
    MODE_LIVE,
    MODE_NOT_CONFIGURED,
    MODE_TEST,
    MODE_UNKNOWN,
    ProviderCheckoutRejected,
    ProviderError,
    ProviderNotConfigured,
    ProviderUnavailable,
)

logger = logging.getLogger(__name__)

#: H0's pinned contract. Overridable by settings so a deliberate, tested
#: version amendment is a configuration change, never an accident.
DEFAULT_CONNECT_API_VERSION = "2026-03-25.dahlia"

#: The controller configuration H0 selected, expressed as Stripe documents it
#: for accounts created with controller properties rather than the deprecated
#: `type=express` shorthand.
CONTROLLER = {
    "controller[stripe_dashboard][type]": "express",
    "controller[requirement_collection]": "stripe",
    "controller[fees][payer]": "application",
    "controller[losses][payments]": "application",
}

#: What `GET /v1/accounts/{acct}` must report back for the controller to be the
#: one this platform asked for. Compared field by field. Note that an account
#: created with the legacy `type=express` shorthand reports
#: `fees.payer=application_express` instead, so such an account is reported as
#: unexpected rather than silently treated as equivalent.
EXPECTED_CONTROLLER = {
    "stripe_dashboard.type": "express",
    "requirement_collection": "stripe",
    "fees.payer": "application",
    "losses.payments": "application",
}

#: The only external-account object type that can receive a EUR bank payout.
BANK_ACCOUNT_OBJECT = "bank_account"

#: The one `business_profile` field this adapter will ever send.
#:
#: Stripe lists `business_profile.url` in `currently_due` for a FR
#: `business_type=individual` account with only `transfers` requested, and
#: Stripe's own guidance is: "If you onboard an account and your platform
#: provides it with a URL, prefill the account's `business_profile.url`. If the
#: business doesn't have a URL, you can prefill its
#: `business_profile.product_description` instead."
#:
#: ShipTrip does not provide Travelers with a website, so `url` is the field
#: this adapter must never send: it is documented as "the business's publicly
#: available website", and a Traveler carrying parcels has no such website. The
#: platform's own marketing site is not theirs to assert. `product_description`
#: is documented as an "internal-only description of the product sold by, or
#: service provided by, the business", which is exactly what ShipTrip can state
#: truthfully on their behalf.
#:
#: There is deliberately no `url` parameter anywhere in this module. A field
#: that cannot be passed cannot be faked, injected by a client, or reached by a
#: future caller that means well.
PRODUCT_DESCRIPTION_PARAM = "business_profile[product_description]"

#: Stripe does not publish a maximum for `product_description`. This is a
#: conservative local ceiling so an accidental blob can never be posted.
MAX_PRODUCT_DESCRIPTION_CHARS = 500


class ConnectPlatformMismatch(ProviderError):
    """The credential answers for an account this deployment is not configured for."""

    code = "connect_platform_mismatch"


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    """One Stripe answer, plus the provenance needed to reconcile it later.

    `request_id` is Stripe's own `Request-Id` header. It is safe to log and it
    is the only handle support can correlate on, so it is captured on success
    and failure alike.
    """

    body: dict
    request_id: str = ""
    status_code: int = 0


@dataclass(frozen=True, slots=True)
class PlatformIdentity:
    """What `GET /v1/account` says about the credential in use."""

    account_id: str
    country: str
    default_currency: str
    mode: str
    request_id: str = ""


@dataclass(frozen=True, slots=True)
class ConnectedAccountSnapshot:
    """Safe projection of one connected account. No PII, no bank numbers.

    Everything here is either a boolean, an enum-like code, an opaque provider
    id or a list of Stripe's own requirement *keys*. The raw Account object is
    never carried past this dataclass, so nothing downstream can accidentally
    persist a legal name, an address or an IBAN.
    """

    account_id: str
    livemode: bool | None
    country: str
    default_currency: str
    details_submitted: bool
    payouts_enabled: bool
    charges_enabled: bool
    transfers_capability: str
    controller: dict
    disabled_reason: str
    requirement_codes: list[str]
    past_due_codes: list[str]
    pending_verification_codes: list[str]
    current_deadline: int | None
    payout_schedule_interval: str
    eur_bank_account_id: str
    eur_bank_present: bool
    external_account_count: int
    metadata: dict = field(default_factory=dict)
    request_id: str = ""


@dataclass(frozen=True, slots=True)
class HostedLink:
    """A short-lived Stripe-hosted URL. Never persisted, never logged."""

    url: str
    expires_at: int | None = None
    request_id: str = ""


@dataclass(frozen=True, slots=True)
class ChargeSnapshot:
    """Safe projection of one platform charge, for `source_transaction`.

    Stripe requires a **charge** id here, never a PaymentIntent id, so this is
    the object that has to be resolved and verified before a Transfer is built.
    Nothing about the cardholder survives the projection.
    """

    charge_id: str
    payment_intent_id: str
    status: str
    paid: bool
    captured: bool
    refunded: bool
    livemode: bool | None
    currency: str
    amount_minor: int
    amount_refunded_minor: int
    balance_transaction_id: str
    transfer_group: str
    request_id: str = ""

    @property
    def is_transferable(self) -> bool:
        return bool(
            self.charge_id.startswith("ch_")
            and self.status == "succeeded"
            and self.paid
            and self.captured
        )

    @property
    def net_available_minor(self) -> int:
        return max(0, int(self.amount_minor) - int(self.amount_refunded_minor))


@dataclass(frozen=True, slots=True)
class TransferSnapshot:
    """Safe projection of one platform → connected-account Transfer.

    A Transfer that exists is money that has left the platform balance. It is
    emphatically *not* a bank payment: `destination_payment` lands in the
    connected account's own balance and a separate Payout object is what puts it
    in a bank.
    """

    transfer_id: str
    amount_minor: int
    currency: str
    destination: str
    source_transaction: str
    destination_payment: str
    balance_transaction_id: str
    transfer_group: str
    reversed: bool
    amount_reversed_minor: int
    livemode: bool | None
    metadata: dict = field(default_factory=dict)
    request_id: str = ""


@dataclass(frozen=True, slots=True)
class BankPayoutSnapshot:
    """Safe projection of one connected-account bank Payout.

    Stripe's documented statuses are `pending`, `in_transit`, `paid`, `failed`
    and `canceled`. `paid` is the only one that discharges a Traveler's
    obligation, and even that can later become `failed` on a genuine bank
    return — which is why `failure_balance_transaction` is carried here.
    """

    payout_id: str
    amount_minor: int
    currency: str
    status: str
    method: str
    destination: str
    automatic: bool
    balance_transaction_id: str
    failure_balance_transaction_id: str
    failure_code: str
    arrival_date: int | None
    livemode: bool | None
    metadata: dict = field(default_factory=dict)
    request_id: str = ""


@dataclass(frozen=True, slots=True)
class BalanceSnapshot:
    """One currency's available/pending amounts for one account scope.

    The scope matters more than the numbers: a platform balance says nothing
    about whether a connected account can pay its bank, and H0 forbids inferring
    one from the other. `account_id` records which scope produced this.
    """

    account_id: str
    currency: str
    available_minor: int
    pending_minor: int
    livemode: bool | None
    request_id: str = ""


@dataclass(frozen=True, slots=True)
class ReversalSnapshot:
    """Safe projection of one Transfer reversal."""

    reversal_id: str
    transfer_id: str
    amount_minor: int
    currency: str
    balance_transaction_id: str
    request_id: str = ""


def _flatten(value: object, prefix: str = "") -> dict:
    """Form-encode a nested dict the way Stripe's API expects."""

    if not isinstance(value, dict):
        return {prefix: value}
    data: dict = {}
    for key, item in value.items():
        path = f"{prefix}[{key}]" if prefix else str(key)
        data.update(_flatten(item, path))
    return data


def _codes(container: object, key: str) -> list:
    """Requirement *keys* only, capped. Never the `errors` hash.

    Stripe's `requirements.errors[].reason` is human prose that can quote the
    submitted value, so only the machine keys in `currently_due`/`past_due`/
    `pending_verification` are safe to store.
    """

    if not isinstance(container, dict):
        return []
    values = container.get(key)
    if not isinstance(values, list):
        return []
    return [str(entry) for entry in values if isinstance(entry, str)][:60]


def _controller_summary(body: dict) -> dict:
    controller = body.get("controller")
    if not isinstance(controller, dict):
        return {}

    def nested(key: str, inner: str) -> str:
        hash_ = controller.get(key)
        if not isinstance(hash_, dict):
            return ""
        return str(hash_.get(inner) or "")

    return {
        "stripe_dashboard.type": nested("stripe_dashboard", "type"),
        "requirement_collection": str(controller.get("requirement_collection") or ""),
        "fees.payer": nested("fees", "payer"),
        "losses.payments": nested("losses", "payments"),
        "is_controller": bool(controller.get("is_controller")),
    }


def _eur_bank(body: dict) -> tuple:
    """Find an eligible EUR bank destination without keeping the bank object.

    Only the opaque `ba_...` id and a boolean survive. Cards are ignored: a
    debit card is not a EUR bank destination for a standard payout, and
    treating one as such would be a readiness lie.
    """

    external = body.get("external_accounts")
    entries = external.get("data") if isinstance(external, dict) else None
    if not isinstance(entries, list):
        return "", False, 0
    eligible = [
        entry
        for entry in entries
        if isinstance(entry, dict)
        and entry.get("object") == BANK_ACCOUNT_OBJECT
        and str(entry.get("currency") or "").lower() == "eur"
        and str(entry.get("status") or "new") not in {"errored", "verification_failed"}
    ]
    # Stripe marks exactly one default per currency; prefer it so the id stored
    # here is the one a payout would actually use.
    default = next(
        (entry for entry in eligible if entry.get("default_for_currency")), None
    )
    chosen = default or (eligible[0] if eligible else None)
    return str((chosen or {}).get("id") or ""), bool(chosen), len(entries)


class StripeConnectGateway:
    """The connected-account surface: identity, accounts, links, readiness."""

    name = "stripe_connect"

    def __init__(
        self,
        *,
        secret_key: str | None = None,
        api_base: str | None = None,
        api_version: str | None = None,
        platform_account_id: str | None = None,
        timeout_seconds: int | None = None,
        session: requests.Session | None = None,
    ):
        self.secret_key = (
            secret_key
            if secret_key is not None
            else getattr(settings, "STRIPE_SECRET_KEY", "")
        )
        self.api_base = (
            api_base
            if api_base is not None
            else getattr(settings, "STRIPE_API_BASE", "https://api.stripe.com")
        ).rstrip("/")
        self.api_version = (
            api_version
            if api_version is not None
            else getattr(
                settings, "STRIPE_CONNECT_API_VERSION", DEFAULT_CONNECT_API_VERSION
            )
        ) or DEFAULT_CONNECT_API_VERSION
        self.platform_account_id = (
            platform_account_id
            if platform_account_id is not None
            else getattr(settings, "STRIPE_CONNECT_PLATFORM_ACCOUNT_ID", "")
        )
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else getattr(settings, "PAYMENTS_PROVIDER_TIMEOUT_SECONDS", 15)
        )
        self._session = session or requests

    # -- configuration ----------------------------------------------------

    def is_configured(self) -> bool:
        return bool(self.secret_key and self.platform_account_id)

    def credential_mode(self) -> str:
        """Which rail the configured key points at, from its prefix alone."""

        key = self.secret_key
        if not key:
            return MODE_NOT_CONFIGURED
        if key.startswith(("sk_test_", "rk_test_")):
            return MODE_TEST
        if key.startswith(("sk_live_", "rk_live_")):
            return MODE_LIVE
        return MODE_UNKNOWN

    def _require_configured(self) -> None:
        from ..mode_safety import require_provider_mode

        require_provider_mode(self.credential_mode())
        if not self.secret_key:
            raise ProviderNotConfigured("STRIPE_SECRET_KEY is not configured.")
        if not self.platform_account_id:
            raise ProviderNotConfigured(
                "STRIPE_CONNECT_PLATFORM_ACCOUNT_ID is not configured."
            )

    # -- transport --------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        data: dict | None = None,
        idempotency_key: str = "",
        stripe_account: str = "",
    ) -> ProviderResponse:
        self._require_configured()
        if self.credential_mode() == "live" and method.upper() == "POST" and path in ("/v1/transfers", "/v1/payouts"):
            # Re-read the platform before issuing LIVE money instructions. This
            # GET recurses only into the transport, never into this POST guard.
            self.platform_identity()
        headers = {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/x-www-form-urlencoded",
            # Explicit on every request. Inheriting the account default would
            # mean a Dashboard version change silently rewrote the payout
            # contract this code was tested against.
            "Stripe-Version": self.api_version,
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if stripe_account:
            headers["Stripe-Account"] = stripe_account
        url = f"{self.api_base}{path}"
        encoded = urlencode(data or {}, doseq=True)
        body = encoded
        if method.upper() == "GET":
            # Stripe reads GET filters from the query string. Sending them as a
            # form body works by accident at best, and `find_*` recovery
            # searches depend on the filter actually being applied — an
            # unfiltered first page is how a recovery picks the wrong object.
            if encoded:
                url = f"{url}?{encoded}"
            body = ""
            headers.pop("Content-Type", None)
        try:
            response = self._session.request(
                method,
                url,
                headers=headers,
                data=body,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            # Never the body, never the key: the method, path and exception
            # class are the whole safe record of a transport failure.
            logger.warning(
                "stripe_connect transport failure on %s %s scope=%s",
                method,
                path,
                stripe_account or "platform",
            )
            raise ProviderUnavailable(
                f"Stripe Connect request failed: {type(exc).__name__}"
            ) from exc

        request_id = str(getattr(response, "headers", {}).get("Request-Id") or "")
        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderUnavailable(
                "Stripe Connect returned a non-JSON response.",
                provider_code=str(response.status_code),
            ) from exc
        if not isinstance(body, dict):
            raise ProviderUnavailable("Stripe Connect returned a non-object response.")

        if response.status_code >= 500:
            raise ProviderUnavailable(
                f"Stripe Connect returned {response.status_code}.",
                provider_code=str(response.status_code),
            )
        if response.status_code == 429:
            raise ProviderUnavailable(
                "Stripe Connect rate limited the request.", provider_code="429"
            )
        error = body.get("error") if isinstance(body.get("error"), dict) else {}
        if (
            response.status_code == 409
            or error.get("code") == "idempotency_key_in_use"
            or error.get("type") == "idempotency_error"
        ):
            # Another request under this identity may still create the account.
            # It must remain unknown, never eligible for a fresh creation key.
            raise ProviderUnavailable(
                "Stripe Connect request is still in progress.",
                provider_code=str(error.get("code") or "idempotency_error"),
            )
        if response.status_code in (401, 403):
            logger.error(
                "stripe_connect auth rejected status=%s credential_mode=%s request_id=%s",
                response.status_code,
                self.credential_mode(),
                request_id,
            )
            raise ProviderNotConfigured(
                "Stripe rejected this deployment's API credentials.",
                provider_code=str(response.status_code),
            )
        if response.status_code >= 400:
            raise ProviderCheckoutRejected(
                str(error.get("message") or "Stripe Connect rejected the request."),
                provider_code=str(
                    error.get("code") or error.get("type") or response.status_code
                ),
            )
        return ProviderResponse(
            body=body, request_id=request_id, status_code=response.status_code
        )

    # -- platform identity -------------------------------------------------

    def platform_identity(self) -> PlatformIdentity:
        """Assert who this credential actually is before any mutation.

        A configured platform id that does not match the retrieved account means
        the deployment is pointed at somebody else's Stripe account. That is a
        stop condition, not a warning: creating a connected account under the
        wrong platform is not reversible by editing a setting afterwards.
        """

        response = self._request("GET", "/v1/account")
        body = response.body
        account_id = str(body.get("id") or "")
        if account_id != self.platform_account_id:
            logger.error(
                "stripe_connect platform assertion failed configured=%s returned=%s",
                self.platform_account_id,
                account_id,
            )
            raise ConnectPlatformMismatch(
                "Stripe returned a platform account this deployment is not "
                "configured for.",
                provider_code="platform_account_mismatch",
            )
        if self.credential_mode() == "live" and not all(
            body.get(key) is True for key in ("details_submitted", "charges_enabled", "payouts_enabled")
        ):
            raise ProviderUnavailable("Stripe platform activation is incomplete.", provider_code="platform_not_ready")
        return PlatformIdentity(
            account_id=account_id,
            country=str(body.get("country") or "").upper(),
            default_currency=str(body.get("default_currency") or "").lower(),
            mode=self.credential_mode(),
            request_id=response.request_id,
        )

    # -- connected accounts -----------------------------------------------

    def create_account(
        self,
        *,
        country: str,
        idempotency_key: str,
        metadata: dict,
        business_type: str = "individual",
        default_currency: str = "eur",
        email: str = "",
        product_description: str = "",
    ) -> ConnectedAccountSnapshot:
        """Create one connected account with H0's explicit controller hash.

        `card_payments` is deliberately not requested. This account never sells
        anything; it receives platform transfers and pays them to a bank. Asking
        for a capability the product does not use would add verification the
        Traveler cannot complete and requirements that would hold payouts.

        `product_description` is the only business-profile context sent, and it
        is sent *here* rather than in a later update because Stripe stops
        accepting business-profile writes for a `requirement_collection=stripe`
        account once its first Account Link exists. Prefill is a creation-time
        decision or it is nothing.

        No MCC is sent. Stripe does not ask for `business_profile.mcc` in this
        transfers-only configuration, and asserting a merchant category the
        provider never requested would be a claim about the Traveler's trade
        that ShipTrip has not verified.
        """

        data = {
            "country": country.upper(),
            "default_currency": default_currency.lower(),
            "business_type": business_type,
            "capabilities[transfers][requested]": "true",
        }
        description = self._business_description(product_description)
        if description:
            data[PRODUCT_DESCRIPTION_PARAM] = description
        data.update(CONTROLLER)
        if email:
            data["email"] = email
        for key, value in metadata.items():
            data[f"metadata[{key}]"] = value
        response = self._request(
            "POST", "/v1/accounts", data=data, idempotency_key=idempotency_key
        )
        return self._snapshot(response)

    @staticmethod
    def _business_description(value: object) -> str:
        """Accept one plain, bounded sentence or refuse the whole request.

        The caller is the finance domain passing a module constant, never a
        request body, so anything that is not a short piece of plain text here
        means a caller is wrong. Refusing is safer than truncating: a silently
        shortened description would be a different assertion to Stripe than the
        one the product reviewed.
        """

        if value in (None, ""):
            return ""
        if not isinstance(value, str):
            raise ProviderError("The product description must be text.")
        description = " ".join(value.split())
        if not description:
            return ""
        if len(description) > MAX_PRODUCT_DESCRIPTION_CHARS:
            raise ProviderError("The product description is too long to send.")
        return description

    def retrieve_account(self, account_id: str) -> ConnectedAccountSnapshot:
        """Read current readiness. Platform scope: this account is ours."""

        if not account_id:
            raise ProviderError("A connected account id is required.")
        return self._snapshot(self._request("GET", f"/v1/accounts/{account_id}"))

    def find_account_by_metadata(
        self, *, key: str, value: str, created_gte: int, limit: int = 100
    ):
        """Bounded recovery search for an ambiguous account creation.

        Stripe cannot filter accounts by metadata, so this is a single bounded
        page anchored on the creation time of the operation being recovered. It
        exists so a timed-out create is *resolved*, never guessed: no match
        means the caller blocks for investigation, and no account id from
        outside this platform is ever accepted.
        """

        response = self._request(
            "GET",
            "/v1/accounts",
            data={"limit": min(int(limit), 100), "created[gte]": int(created_gte)},
        )
        entries = response.body.get("data")
        if not isinstance(entries, list):
            return None
        matches = [
            entry
            for entry in entries
            if isinstance(entry, dict)
            and isinstance(entry.get("metadata"), dict)
            and str(entry["metadata"].get(key) or "") == value
        ]
        if len(matches) != 1:
            # Zero is unresolved; more than one is a contradiction. Neither is
            # something to pick a winner from.
            return None
        return self._snapshot(
            ProviderResponse(body=matches[0], request_id=response.request_id)
        )

    def set_payout_schedule(
        self, *, account_id: str, interval: str = "manual"
    ) -> ConnectedAccountSnapshot:
        """Provision the application-controlled payout schedule.

        Configuration only. Setting `interval=manual` tells Stripe to hold the
        connected account's balance until the platform explicitly creates a
        payout; it does not create one, and this adapter has no call that could.
        """

        if interval not in {"manual", "daily", "weekly", "monthly"}:
            raise ProviderError("Unsupported payout schedule interval.")
        return self._snapshot(
            self._request(
                "POST",
                f"/v1/accounts/{account_id}",
                data=_flatten(
                    {"settings": {"payouts": {"schedule": {"interval": interval}}}}
                ),
            )
        )

    # -- hosted links ------------------------------------------------------

    def create_account_link(
        self, *, account_id: str, refresh_url: str, return_url: str
    ) -> HostedLink:
        """Stripe-hosted onboarding. Stripe collects identity and bank details."""

        response = self._request(
            "POST",
            "/v1/account_links",
            data={
                "account": account_id,
                "type": "account_onboarding",
                "refresh_url": refresh_url,
                "return_url": return_url,
                "collection_options[fields]": "currently_due",
            },
        )
        url = str(response.body.get("url") or "")
        if not url:
            raise ProviderError("Stripe did not return an onboarding URL.")
        expires = response.body.get("expires_at")
        return HostedLink(
            url=url,
            expires_at=expires if isinstance(expires, int) else None,
            request_id=response.request_id,
        )

    def create_login_link(self, *, account_id: str) -> HostedLink:
        """Single-use Express Dashboard access for the account holder."""

        response = self._request(
            "POST", f"/v1/accounts/{account_id}/login_links", data={}
        )
        url = str(response.body.get("url") or "")
        if not url:
            raise ProviderError("Stripe did not return a dashboard URL.")
        return HostedLink(url=url, request_id=response.request_id)

    # -- source charge resolution -----------------------------------------

    def retrieve_charge(self, charge_id: str) -> ChargeSnapshot:
        """Read one platform charge so a Transfer can name it safely."""

        if not charge_id:
            raise ProviderError("A charge id is required.")
        return _charge_snapshot(self._request("GET", f"/v1/charges/{charge_id}"))

    def latest_charge_for_intent(self, payment_intent_id: str) -> str:
        """Resolve `pi_…` → `ch_…`, which is what `source_transaction` needs.

        Stripe documents two ways to get there: the PaymentIntent's
        `latest_charge`, or listing charges filtered by `payment_intent`. This
        uses the first and falls back to the second, and returns an empty string
        rather than guessing when neither answers.
        """

        if not payment_intent_id.startswith("pi_"):
            raise ProviderError("A PaymentIntent id is required.")
        body = self._request(
            "GET", f"/v1/payment_intents/{payment_intent_id}"
        ).body
        latest = body.get("latest_charge")
        if isinstance(latest, dict):
            latest = latest.get("id")
        if isinstance(latest, str) and latest.startswith("ch_"):
            return latest
        listed = self._request(
            "GET", "/v1/charges", data={"payment_intent": payment_intent_id, "limit": 5}
        ).body.get("data")
        if not isinstance(listed, list):
            return ""
        charges = [
            str(entry.get("id") or "")
            for entry in listed
            if isinstance(entry, dict)
            and str(entry.get("id") or "").startswith("ch_")
            and entry.get("status") == "succeeded"
        ]
        # Exactly one succeeded charge resolves. Zero is unresolved and more
        # than one is ambiguous; neither is something to pick a winner from.
        return charges[0] if len(charges) == 1 else ""

    # -- platform transfers ------------------------------------------------

    def create_transfer(
        self,
        *,
        amount_minor: int,
        destination: str,
        source_transaction: str,
        transfer_group: str,
        idempotency_key: str,
        metadata: dict,
        currency: str = "eur",
    ) -> TransferSnapshot:
        """Move platform EUR into one connected account's Stripe balance.

        `source_transaction` is a charge id and Stripe rejects a PaymentIntent
        id here, so this refuses a `pi_` locally rather than discovering it at
        the provider. It is also what stops the request failing on an
        unsettled platform balance: Stripe accepts the Transfer and releases the
        funds into the destination when the source charge settles.

        Deliberately absent: `application_fee_amount`, `on_behalf_of` and any
        destination-charge parameter. This platform charges on its own account
        and transfers afterwards; H0 selected that and nothing here may drift.
        """

        if int(amount_minor) <= 0:
            raise ProviderError("A transfer amount must be positive.")
        if not destination.startswith("acct_"):
            raise ProviderError("A transfer destination must be a connected account.")
        if not source_transaction.startswith("ch_"):
            raise ProviderError(
                "A transfer source must be a Stripe charge id, not a PaymentIntent."
            )
        if not idempotency_key:
            raise ProviderError("A transfer requires a stable idempotency key.")
        data = {
            "amount": int(amount_minor),
            "currency": currency.lower(),
            "destination": destination,
            "source_transaction": source_transaction,
            "transfer_group": transfer_group,
        }
        for key, value in metadata.items():
            data[f"metadata[{key}]"] = value
        return _transfer_snapshot(
            self._request(
                "POST", "/v1/transfers", data=data, idempotency_key=idempotency_key
            )
        )

    def retrieve_transfer(self, transfer_id: str) -> TransferSnapshot:
        if not transfer_id:
            raise ProviderError("A transfer id is required.")
        return _transfer_snapshot(self._request("GET", f"/v1/transfers/{transfer_id}"))

    def find_transfer_by_metadata(
        self, *, key: str, value: str, transfer_group: str, limit: int = 100
    ):
        """Bounded recovery search for an ambiguous Transfer creation.

        Anchored on the transfer group, which H3 derives from the payout's own
        opaque reference, so the page is small and cannot contain another
        Traveler's money. Zero matches is unresolved and two is a contradiction;
        both leave the caller blocked rather than guessing.
        """

        response = self._request(
            "GET",
            "/v1/transfers",
            data={"transfer_group": transfer_group, "limit": min(int(limit), 100)},
        )
        entries = response.body.get("data")
        if not isinstance(entries, list):
            return None
        matches = [
            entry
            for entry in entries
            if isinstance(entry, dict)
            and isinstance(entry.get("metadata"), dict)
            and str(entry["metadata"].get(key) or "") == value
        ]
        if len(matches) != 1:
            return None
        return _transfer_snapshot(
            ProviderResponse(body=matches[0], request_id=response.request_id)
        )

    def reverse_transfer(
        self, *, transfer_id: str, amount_minor: int, idempotency_key: str, metadata: dict
    ) -> ReversalSnapshot:
        """Recover an exact amount from a connected account to the platform.

        Only ever called with an amount an authorised policy decided and the
        connected balance can actually cover. Stripe refuses a reversal larger
        than the connected account's available balance, and this adapter does
        not soften that into a partial reversal of its own choosing.
        """

        if int(amount_minor) <= 0:
            raise ProviderError("A reversal amount must be positive.")
        if not idempotency_key:
            raise ProviderError("A reversal requires a stable idempotency key.")
        data = {"amount": int(amount_minor)}
        for key, value in metadata.items():
            data[f"metadata[{key}]"] = value
        response = self._request(
            "POST",
            f"/v1/transfers/{transfer_id}/reversals",
            data=data,
            idempotency_key=idempotency_key,
        )
        body = response.body
        reversal_id = str(body.get("id") or "")
        if not reversal_id:
            raise ProviderError("Stripe did not return a transfer reversal.")
        return ReversalSnapshot(
            reversal_id=reversal_id,
            transfer_id=str(body.get("transfer") or transfer_id),
            amount_minor=int(body.get("amount") or 0),
            currency=str(body.get("currency") or "").upper(),
            balance_transaction_id=_object_id(body.get("balance_transaction")),
            request_id=response.request_id,
        )

    # -- connected-account balance and bank payouts ------------------------

    def retrieve_balance(self, *, account_id: str = "", currency: str = "eur"):
        """One currency's balance in an explicit account scope.

        `account_id` empty means the platform's own balance. H0 forbids reading
        one and reasoning about the other, so the scope is always the caller's
        explicit choice and is recorded on the answer.
        """

        response = self._request("GET", "/v1/balance", stripe_account=account_id)
        body = response.body
        wanted = currency.lower()

        def total(bucket: str) -> int:
            entries = body.get(bucket)
            if not isinstance(entries, list):
                return 0
            return sum(
                int(entry.get("amount") or 0)
                for entry in entries
                if isinstance(entry, dict)
                and str(entry.get("currency") or "").lower() == wanted
            )

        livemode = body.get("livemode")
        return BalanceSnapshot(
            account_id=account_id or self.platform_account_id,
            currency=wanted.upper(),
            available_minor=total("available"),
            pending_minor=total("pending"),
            livemode=livemode if type(livemode) is bool else None,
            request_id=response.request_id,
        )

    def create_bank_payout(
        self,
        *,
        account_id: str,
        amount_minor: int,
        destination: str,
        idempotency_key: str,
        metadata: dict,
        currency: str = "eur",
        method: str = "standard",
    ) -> BankPayoutSnapshot:
        """Send transferred EUR from a connected account to its bank.

        Always in connected-account scope: the `Stripe-Account` header is what
        makes this the Traveler's payout rather than a withdrawal from the
        platform's own balance. `method` stays `standard`; Instant Payouts were
        not selected and would change both the fee model and the failure modes.
        """

        if not account_id.startswith("acct_"):
            raise ProviderError("A bank payout requires a connected account scope.")
        if int(amount_minor) <= 0:
            raise ProviderError("A bank payout amount must be positive.")
        if method != "standard":
            raise ProviderError("Only standard bank payouts are supported.")
        if not idempotency_key:
            raise ProviderError("A bank payout requires a stable idempotency key.")
        data = {
            "amount": int(amount_minor),
            "currency": currency.lower(),
            "method": method,
        }
        if destination:
            data["destination"] = destination
        for key, value in metadata.items():
            data[f"metadata[{key}]"] = value
        return _bank_payout_snapshot(
            self._request(
                "POST",
                "/v1/payouts",
                data=data,
                idempotency_key=idempotency_key,
                stripe_account=account_id,
            )
        )

    def retrieve_bank_payout(
        self, *, account_id: str, payout_id: str
    ) -> BankPayoutSnapshot:
        if not payout_id:
            raise ProviderError("A payout id is required.")
        return _bank_payout_snapshot(
            self._request(
                "GET", f"/v1/payouts/{payout_id}", stripe_account=account_id
            )
        )

    def find_bank_payout_by_metadata(
        self, *, account_id: str, key: str, value: str, created_gte: int, limit: int = 100
    ):
        """Bounded recovery search for an ambiguous bank-payout creation."""

        response = self._request(
            "GET",
            "/v1/payouts",
            data={"limit": min(int(limit), 100), "created[gte]": int(created_gte)},
            stripe_account=account_id,
        )
        entries = response.body.get("data")
        if not isinstance(entries, list):
            return None
        matches = [
            entry
            for entry in entries
            if isinstance(entry, dict)
            and isinstance(entry.get("metadata"), dict)
            and str(entry["metadata"].get(key) or "") == value
        ]
        if len(matches) != 1:
            return None
        return _bank_payout_snapshot(
            ProviderResponse(body=matches[0], request_id=response.request_id)
        )

    def cancel_bank_payout(
        self, *, account_id: str, payout_id: str
    ) -> BankPayoutSnapshot:
        """Cancel a bank payout Stripe still reports as `pending`.

        Stripe's contract is explicit that only a `pending` payout can be
        cancelled, so a caller that has seen `in_transit` must not promise
        cancellation. This adapter passes the refusal straight through rather
        than translating it into something reassuring.
        """

        return _bank_payout_snapshot(
            self._request(
                "POST",
                f"/v1/payouts/{payout_id}/cancel",
                data={},
                stripe_account=account_id,
            )
        )

    # -- platform refund and dispute reads ---------------------------------

    def retrieve_refund(self, refund_id: str) -> dict:
        """Safe fields of one platform refund, for provider-refund ingestion."""

        body = self._request("GET", f"/v1/refunds/{refund_id}").body
        return {
            "id": str(body.get("id") or ""),
            "charge": _object_id(body.get("charge")),
            "payment_intent": _object_id(body.get("payment_intent")),
            "amount": int(body.get("amount") or 0),
            "currency": str(body.get("currency") or "").upper(),
            "status": str(body.get("status") or ""),
            "livemode": body.get("livemode")
            if type(body.get("livemode")) is bool
            else None,
        }

    def retrieve_dispute(self, dispute_id: str) -> dict:
        """Safe fields of one platform dispute. No evidence, no cardholder."""

        body = self._request("GET", f"/v1/disputes/{dispute_id}").body
        return {
            "id": str(body.get("id") or ""),
            "charge": _object_id(body.get("charge")),
            "payment_intent": _object_id(body.get("payment_intent")),
            "amount": int(body.get("amount") or 0),
            "currency": str(body.get("currency") or "").upper(),
            "status": str(body.get("status") or ""),
            "livemode": body.get("livemode")
            if type(body.get("livemode")) is bool
            else None,
        }

    # -- projection --------------------------------------------------------

    def _snapshot(self, response: ProviderResponse) -> ConnectedAccountSnapshot:
        body = response.body
        account_id = str(body.get("id") or "")
        if not account_id.startswith("acct_"):
            raise ProviderError("Stripe did not return a connected account object.")
        capabilities = body.get("capabilities")
        transfers = ""
        if isinstance(capabilities, dict):
            transfers = str(capabilities.get("transfers") or "")
        requirements = body.get("requirements")
        requirements = requirements if isinstance(requirements, dict) else {}
        settings_hash = body.get("settings")
        payouts = (
            settings_hash.get("payouts") if isinstance(settings_hash, dict) else None
        )
        schedule = payouts.get("schedule") if isinstance(payouts, dict) else None
        deadline = requirements.get("current_deadline")
        bank_id, bank_present, external_count = _eur_bank(body)
        metadata = body.get("metadata")
        livemode = body.get("livemode")
        return ConnectedAccountSnapshot(
            account_id=account_id,
            livemode=livemode if type(livemode) is bool else None,
            country=str(body.get("country") or "").upper(),
            default_currency=str(body.get("default_currency") or "").lower(),
            details_submitted=bool(body.get("details_submitted")),
            payouts_enabled=bool(body.get("payouts_enabled")),
            charges_enabled=bool(body.get("charges_enabled")),
            transfers_capability=transfers or "unrequested",
            controller=_controller_summary(body),
            disabled_reason=str(requirements.get("disabled_reason") or ""),
            requirement_codes=_codes(requirements, "currently_due"),
            past_due_codes=_codes(requirements, "past_due"),
            pending_verification_codes=_codes(requirements, "pending_verification"),
            current_deadline=deadline if isinstance(deadline, int) else None,
            payout_schedule_interval=str(
                (schedule or {}).get("interval") if isinstance(schedule, dict) else ""
            ),
            eur_bank_account_id=bank_id,
            eur_bank_present=bank_present,
            external_account_count=external_count,
            metadata={str(k): str(v) for k, v in (metadata or {}).items()}
            if isinstance(metadata, dict)
            else {},
            request_id=response.request_id,
        )


def _object_id(value: object) -> str:
    """Stripe returns either an id string or an expanded object. Take the id."""

    if isinstance(value, dict):
        return str(value.get("id") or "")
    return str(value or "")


def _charge_snapshot(response: ProviderResponse) -> ChargeSnapshot:
    body = response.body
    charge_id = str(body.get("id") or "")
    if not charge_id.startswith("ch_"):
        raise ProviderError("Stripe did not return a charge object.")
    livemode = body.get("livemode")
    return ChargeSnapshot(
        charge_id=charge_id,
        payment_intent_id=_object_id(body.get("payment_intent")),
        status=str(body.get("status") or ""),
        paid=bool(body.get("paid")),
        captured=bool(body.get("captured")),
        refunded=bool(body.get("refunded")),
        livemode=livemode if type(livemode) is bool else None,
        currency=str(body.get("currency") or "").upper(),
        amount_minor=int(body.get("amount") or 0),
        amount_refunded_minor=int(body.get("amount_refunded") or 0),
        balance_transaction_id=_object_id(body.get("balance_transaction")),
        transfer_group=str(body.get("transfer_group") or ""),
        request_id=response.request_id,
    )


def _transfer_snapshot(response: ProviderResponse) -> TransferSnapshot:
    body = response.body
    transfer_id = str(body.get("id") or "")
    if not transfer_id.startswith("tr_"):
        raise ProviderError("Stripe did not return a transfer object.")
    metadata = body.get("metadata")
    livemode = body.get("livemode")
    return TransferSnapshot(
        transfer_id=transfer_id,
        amount_minor=int(body.get("amount") or 0),
        currency=str(body.get("currency") or "").upper(),
        destination=_object_id(body.get("destination")),
        source_transaction=_object_id(body.get("source_transaction")),
        destination_payment=_object_id(body.get("destination_payment")),
        balance_transaction_id=_object_id(body.get("balance_transaction")),
        transfer_group=str(body.get("transfer_group") or ""),
        reversed=bool(body.get("reversed")),
        amount_reversed_minor=int(body.get("amount_reversed") or 0),
        livemode=livemode if type(livemode) is bool else None,
        metadata={str(k): str(v) for k, v in (metadata or {}).items()}
        if isinstance(metadata, dict)
        else {},
        request_id=response.request_id,
    )


def _bank_payout_snapshot(response: ProviderResponse) -> BankPayoutSnapshot:
    body = response.body
    payout_id = str(body.get("id") or "")
    if not payout_id.startswith("po_"):
        raise ProviderError("Stripe did not return a payout object.")
    metadata = body.get("metadata")
    livemode = body.get("livemode")
    arrival = body.get("arrival_date")
    return BankPayoutSnapshot(
        payout_id=payout_id,
        amount_minor=int(body.get("amount") or 0),
        currency=str(body.get("currency") or "").upper(),
        status=str(body.get("status") or ""),
        method=str(body.get("method") or ""),
        destination=_object_id(body.get("destination")),
        automatic=bool(body.get("automatic")),
        balance_transaction_id=_object_id(body.get("balance_transaction")),
        failure_balance_transaction_id=_object_id(
            body.get("failure_balance_transaction")
        ),
        failure_code=str(body.get("failure_code") or "")[:64],
        arrival_date=arrival if isinstance(arrival, int) else None,
        livemode=livemode if type(livemode) is bool else None,
        metadata={str(k): str(v) for k, v in (metadata or {}).items()}
        if isinstance(metadata, dict)
        else {},
        request_id=response.request_id,
    )


def get_connect_gateway(**overrides) -> StripeConnectGateway:
    """Build the adapter from deployment settings."""

    return StripeConnectGateway(**overrides)
