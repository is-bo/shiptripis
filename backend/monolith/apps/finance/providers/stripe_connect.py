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
* **It moves no money, and it cannot.** There is no transfer, payout, reversal
  or cancel call in this file, and `test_phase8fh2_adapter.py` asserts the
  module's own source contains no such path. H3 owns execution.
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
        try:
            response = self._session.request(
                method,
                url,
                headers=headers,
                data=urlencode(data or {}, doseq=True),
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
    ) -> ConnectedAccountSnapshot:
        """Create one connected account with H0's explicit controller hash.

        `card_payments` is deliberately not requested. This account never sells
        anything; it receives platform transfers and pays them to a bank. Asking
        for a capability the product does not use would add verification the
        Traveler cannot complete and requirements that would hold payouts.
        """

        data = {
            "country": country.upper(),
            "default_currency": default_currency.lower(),
            "business_type": business_type,
            "capabilities[transfers][requested]": "true",
        }
        data.update(CONTROLLER)
        if email:
            data["email"] = email
        for key, value in metadata.items():
            data[f"metadata[{key}]"] = value
        response = self._request(
            "POST", "/v1/accounts", data=data, idempotency_key=idempotency_key
        )
        return self._snapshot(response)

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


def get_connect_gateway(**overrides) -> StripeConnectGateway:
    """Build the adapter from deployment settings."""

    return StripeConnectGateway(**overrides)
