"""Chargily Pay v2 adapter, written against Chargily's own HTTP contract.

Chargily is a **settlement rail**, not a source of marketplace truth. The
canonical obligation stays in EUR cents; this adapter is handed an already
converted DZD amount and charges exactly that. It never converts, never reads
the FX rate, and never decides what is owed.

Contract used (https://dev.chargily.com/pay-v2):

* base URL  ``https://pay.chargily.net/api/v2`` live,
  ``https://pay.chargily.net/test/api/v2`` test — the URL *and* the key decide
  the mode
* auth      ``Authorization: Bearer <api secret key>``
* checkout  ``POST /checkouts`` with ``amount`` + ``currency`` (``dzd``),
  ``success_url`` (required), ``failure_url``, ``webhook_endpoint``,
  ``description``, ``metadata``; the response carries ``id`` and
  ``checkout_url``, and ``created_at`` as a Unix time; a checkout expires 30
  minutes after it was created
* webhook   header ``signature`` = HMAC-SHA256 hex digest of the **raw body**
  keyed with the API secret key; events are ``checkout.paid``,
  ``checkout.failed``, ``checkout.canceled``, ``checkout.expired``

``amount`` is expressed in whole dinars: DZD has no circulating minor unit, so
`apps.finance.money` treats it as exponent 0 and rounds conversions up.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from datetime import UTC, datetime, timedelta

import requests
from django.conf import settings
from django.utils import timezone

from .base import (
    CHECKOUT_CLOSED,
    CHECKOUT_COLLECTED,
    MODE_LIVE,
    MODE_NOT_CONFIGURED,
    MODE_TEST,
    MODE_UNKNOWN,
    AttemptSnapshot,
    CheckoutRequest,
    CheckoutResult,
    ProviderCheckoutRejected,
    ProviderError,
    ProviderEvent,
    ProviderNotConfigured,
    ProviderSignatureError,
    ProviderUnavailable,
    RefundNotSupported,
    RefundRequest,
    RefundResult,
)
from .http import log_provider_timing, provider_session, provider_timeout

logger = logging.getLogger(__name__)

LIVE_API_BASE = "https://pay.chargily.net/api/v2"
TEST_API_BASE = "https://pay.chargily.net/test/api/v2"

MAX_WEBHOOK_BYTES = 512 * 1024

#: How long a checkout can be paid. Chargily expires a checkout 30 minutes
#: after it was created unless it is told otherwise, and no request here tells
#: it otherwise (G1).
CHECKOUT_LIFETIME = timedelta(minutes=30)

#: Chargily maps its checkout lifecycle onto these event types.
_EVENT_OUTCOMES = {
    "checkout.paid": "succeeded",
    "checkout.failed": "failed",
    "checkout.canceled": "cancelled",
    "checkout.cancelled": "cancelled",
    "checkout.expired": "expired",
}

_STATUS_OUTCOMES = {
    "paid": "succeeded",
    "failed": "failed",
    "canceled": "cancelled",
    "cancelled": "cancelled",
    "expired": "expired",
    "pending": "ignored",
    "processing": "ignored",
}


#: A SHA-256 hex digest and nothing else.
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def _is_hex_signature(value: str) -> bool:
    return bool(value) and len(value) <= 128 and all(c in _HEX_DIGITS for c in value)


def verify_chargily_signature(
    *, raw_body: bytes, signature_header: str, secret: str
) -> None:
    """Verify Chargily's `signature` header or raise `ProviderSignatureError`."""

    if not secret:
        raise ProviderNotConfigured("Chargily webhook secret is not configured.")
    if not signature_header:
        raise ProviderSignatureError("Missing Chargily signature header.")
    if len(raw_body) > MAX_WEBHOOK_BYTES:
        raise ProviderSignatureError("Webhook body exceeds the accepted size.")
    supplied = signature_header.strip()
    # A signature Chargily could have produced is lowercase hex.
    # `hmac.compare_digest` raises TypeError on a non-ASCII string, so
    # anything else is rejected as a signature failure rather than allowed to
    # become an unhandled 500 that makes the provider retry forever.
    if not _is_hex_signature(supplied):
        raise ProviderSignatureError("Chargily signature is malformed.")
    expected = hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        raise ProviderSignatureError("Chargily signature did not match the payload.")


class ChargilyGateway:
    """DZD settlement checkout against a canonical EUR obligation."""

    name = "chargily"
    supports_guest_payment = False
    payment_currency = "DZD"

    def __init__(
        self,
        *,
        secret_key: str | None = None,
        webhook_secret: str | None = None,
        api_base: str | None = None,
        timeout_seconds: int | None = None,
        session: requests.Session | None = None,
    ):
        self.secret_key = (
            secret_key
            if secret_key is not None
            else getattr(settings, "CHARGILY_SECRET_KEY", "")
        )
        # Chargily signs webhooks with the API secret key. A separate override
        # exists so a deployment can rotate them independently if Chargily ever
        # splits them.
        self.webhook_secret = (
            webhook_secret
            if webhook_secret is not None
            else (
                getattr(settings, "CHARGILY_WEBHOOK_SECRET", "") or self.secret_key
            )
        )
        self.api_base = (
            api_base
            if api_base is not None
            else getattr(settings, "CHARGILY_API_BASE", LIVE_API_BASE)
        ).rstrip("/")
        self.timeout = provider_timeout(timeout_seconds)
        self._session = session if session is not None else provider_session("chargily")

    def is_configured(self) -> bool:
        return bool(self.secret_key and self.api_base)

    def credential_mode(self) -> str:
        """Whether this deployment is pointed at Chargily test or live money.

        Chargily decides the environment twice — once in the key prefix
        (`test_sk_` / `live_sk_`) and once in the API base (`/test/api/v2`).
        Both must agree; a deployment that mixes a live key with the test base
        (or the reverse) is a misconfiguration, and saying `unknown` is the
        only honest answer to it. The key itself is never returned or logged.
        """

        key = self.secret_key
        if not key:
            return MODE_NOT_CONFIGURED
        by_key = (
            MODE_TEST
            if key.startswith("test_sk_")
            else MODE_LIVE
            if key.startswith("live_sk_")
            else MODE_UNKNOWN
        )
        by_base = self._api_base_environment()
        if by_key == MODE_UNKNOWN or by_base == MODE_UNKNOWN:
            return MODE_UNKNOWN
        return by_key if by_key == by_base else MODE_UNKNOWN

    def configuration_problem(self) -> str:
        """Why this Chargily configuration must not take a new checkout.

        Chargily states its environment twice — in the key prefix and in the API
        base — and a deployment that mixes them is not "probably test". A test
        key against the live base is rejected by Chargily with a 401 the payer
        sees as a generic failure; a live key against the test base would create
        checkouts nobody can settle. Neither is a state to transact in, and
        neither can be resolved by guessing which half was intended.

        This is the exact condition that was live on the deployed environment:
        `test_sk_` against `https://pay.chargily.net/api/v2`.
        """

        if not self.secret_key:
            return ""  # Not configured at all — a different, earlier answer.
        if self.credential_mode() == MODE_UNKNOWN:
            return "chargily_environment_unidentified"
        from ..mode_safety import require_provider_mode
        from .base import ProviderConfigurationInvalid

        try:
            require_provider_mode(self.credential_mode())
        except ProviderConfigurationInvalid:
            return "payment_environment_mismatch"
        return ""

    def _require_configured(self) -> None:
        from ..mode_safety import require_provider_mode

        require_provider_mode(self.credential_mode())
        if not self.secret_key:
            raise ProviderNotConfigured("CHARGILY_SECRET_KEY is not configured.")

    def _request(
        self,
        method: str,
        path: str,
        *,
        operation: str = "request",
        payload: dict | None = None,
    ) -> dict:
        self._require_configured()
        headers = {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        started = time.monotonic()
        outcome = "internal_error"
        try:
            try:
                response = self._session.request(
                    method,
                    f"{self.api_base}{path}",
                    headers=headers,
                    data=json.dumps(payload) if payload is not None else None,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                outcome = "transport_error"
                logger.warning("chargily transport failure operation=%s", operation)
                raise ProviderUnavailable(
                    f"Chargily request failed: {type(exc).__name__}"
                ) from exc

            try:
                body = response.json()
            except ValueError as exc:
                outcome = "invalid_response"
                raise ProviderUnavailable(
                    "Chargily returned a non-JSON response."
                ) from exc

            if response.status_code >= 500:
                outcome = "provider_unavailable"
                raise ProviderUnavailable(
                    f"Chargily returned {response.status_code}.",
                    provider_code=str(response.status_code),
                )
            if response.status_code == 429:
                outcome = "rate_limited"
                raise ProviderUnavailable(
                    "Chargily rate limited the request.", provider_code="429"
                )
            if response.status_code in (401, 403):
                outcome = "auth_rejected"
                # Only derived mode is logged; never URL, body or credential.
                logger.error(
                    "chargily auth rejected status=%s credential_mode=%s api_base_mode=%s",
                    response.status_code,
                    self.credential_mode(),
                    self._api_base_environment(),
                )
                raise ProviderNotConfigured(
                    "Chargily rejected this deployment's API credentials.",
                    provider_code=str(response.status_code),
                )
            if response.status_code >= 400:
                outcome = "rejected"
                provider_code = ""
                if isinstance(body, dict):
                    provider_code = str(body.get("code") or "")
                logger.warning(
                    "chargily rejected operation=%s status=%s provider_code=%s",
                    operation,
                    response.status_code,
                    provider_code or "-",
                )
                # Raw provider detail remains internal; payer errors are
                # sanitized at the service boundary.
                message = "Chargily rejected the request."
                if isinstance(body, dict):
                    message = str(body.get("message") or message)
                raise ProviderCheckoutRejected(
                    message, provider_code=provider_code or str(response.status_code)
                )
            outcome = "success"
            return body if isinstance(body, dict) else {}
        finally:
            log_provider_timing(
                provider="chargily",
                operation=operation,
                started=started,
                outcome=outcome,
            )

    def _api_base_environment(self) -> str:
        """Which environment the configured base URL points at. Not a secret."""

        base = self.api_base.rstrip("/")
        if base == TEST_API_BASE.rstrip("/"):
            return MODE_TEST
        if base == LIVE_API_BASE.rstrip("/"):
            return MODE_LIVE
        return MODE_UNKNOWN

    def create_checkout(self, request: CheckoutRequest) -> CheckoutResult:
        if request.currency.upper() != "DZD":
            raise ProviderError(
                "Chargily settles in DZD only.", provider_code="unsupported_currency"
            )
        payload = {
            "amount": int(request.amount_minor),
            "currency": "dzd",
            "success_url": request.success_url,
            "failure_url": request.failure_url,
            "webhook_endpoint": request.webhook_url,
            "description": request.description[:255],
            "metadata": [{"reference": request.reference}],
        }
        requested_at = timezone.now()
        body = self._request(
            "POST", "/checkouts", operation="checkout_create", payload=payload
        )
        checkout_id = str(body.get("id") or "")
        checkout_url = str(body.get("checkout_url") or "")
        if not checkout_id or not checkout_url:
            raise ProviderError("Chargily did not return a usable checkout.")
        created_at = body.get("created_at")
        if type(created_at) is int and created_at > 0:
            created = datetime.fromtimestamp(created_at, UTC)
        else:
            # It was created no earlier than it was asked for.
            created = requested_at
        return CheckoutResult(
            provider_session_id=checkout_id,
            checkout_url=checkout_url,
            provider_status=str(body.get("status") or "pending"),
            expires_at=created + CHECKOUT_LIFETIME,
            raw=_scrub(body),
        )

    def close_checkout(self, *, provider_session_id: str) -> str:
        """Expire a pending checkout, or learn why it cannot be expired.

        Chargily expires only a `pending` checkout (`POST
        /checkouts/{id}/expire`) and answers success only once it has. It
        refuses an expired one with 400 and any other status with 403, which
        `_request` cannot tell from a credential refusal, so every refusal is
        answered by reading the checkout.
        """

        if not provider_session_id:
            raise ProviderError("No Chargily checkout to close.")
        path = f"/checkouts/{provider_session_id}"
        try:
            self._request("POST", f"{path}/expire", operation="checkout_expire")
        except ProviderUnavailable:
            raise
        except ProviderError:
            body = self._request("GET", path, operation="checkout_fetch")
        else:
            return CHECKOUT_CLOSED
        status = str(body.get("status") or "").lower()
        if status in {"expired", "failed", "canceled", "cancelled"}:
            return CHECKOUT_CLOSED
        if status in {"paid", "processing"}:
            return CHECKOUT_COLLECTED
        raise ProviderError(
            "Chargily did not confirm the checkout closed.",
            provider_code="checkout_open",
        )

    def fetch_attempt(
        self, *, provider_session_id: str, provider_payment_id: str
    ) -> AttemptSnapshot:
        if not provider_session_id:
            raise ProviderError("No Chargily checkout to reconcile.")
        body = self._request(
            "GET", f"/checkouts/{provider_session_id}", operation="checkout_fetch"
        )
        status = str(body.get("status") or "").lower()
        return AttemptSnapshot(
            outcome=_STATUS_OUTCOMES.get(status, "ignored"),
            provider_payment_id=str(body.get("id") or provider_payment_id),
            amount_minor=body.get("amount"),
            currency=str(body.get("currency") or "").upper(),
            raw=_with_boolean_livemode(_scrub(body)),
        )

    def refund(self, request: RefundRequest) -> RefundResult:
        """Chargily Pay v2 exposes no programmatic refund endpoint.

        Refusing loudly is the honest behaviour: fabricating a success here
        would put the ledger out of step with reality. A Chargily refund is an
        operator action, and the caller records it as a manual refund with its
        own evidence.
        """

        raise RefundNotSupported(
            "Chargily refunds are settled manually; no API refund exists.",
            provider_code="refund_not_supported",
        )

    def parse_webhook(self, *, raw_body: bytes, headers: dict[str, str]) -> ProviderEvent:
        verify_chargily_signature(
            raw_body=raw_body,
            signature_header=headers.get("signature", ""),
            secret=self.webhook_secret,
        )
        try:
            event = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ProviderSignatureError(
                "Chargily webhook body is not valid JSON."
            ) from exc
        if not isinstance(event, dict):
            raise ProviderSignatureError("Chargily webhook body is not an object.")

        event_id = str(event.get("id") or "")
        event_type = str(event.get("type") or "")
        if not event_id:
            raise ProviderSignatureError("Chargily webhook carries no event id.")

        data = event.get("data")
        if not isinstance(data, dict):
            data = {}

        outcome = _EVENT_OUTCOMES.get(
            event_type,
            _STATUS_OUTCOMES.get(str(data.get("status") or "").lower(), "ignored"),
        )
        # A `checkout.paid` whose object does not actually say `paid` is not a
        # success; trust the object, not the label.
        if outcome == "succeeded" and str(data.get("status") or "paid").lower() != "paid":
            outcome = "ignored"

        reference = ""
        metadata = data.get("metadata")
        if isinstance(metadata, list):
            for entry in metadata:
                if isinstance(entry, dict) and entry.get("reference"):
                    reference = str(entry["reference"])
                    break

        return ProviderEvent(
            provider=self.name,
            event_id=event_id,
            event_type=event_type,
            outcome=outcome,
            provider_session_id=str(data.get("id") or ""),
            provider_payment_id=str(data.get("id") or ""),
            reference=reference,
            amount_minor=data.get("amount"),
            currency=str(data.get("currency") or "").upper(),
            failure_code=str(data.get("failure_reason") or ""),
            payload=_with_boolean_livemode(_scrub(event)),
        )


_SENSITIVE_KEYS = frozenset(
    {
        "customer",
        "shipping_address",
        "email",
        "phone",
        "name",
        "address",
        "secret",
        # A checkout's hosted URL lets whoever holds it pay: it is handed to
        # its payer and never kept anywhere else (G1).
        "url",
        "checkout_url",
    }
)

#: How Chargily writes `livemode`: a boolean on a checkout, and the string
#: "true" or "false" at the top of a webhook event.
_LIVEMODE_VALUES = {True: True, False: False, "true": True, "false": False}


def _with_boolean_livemode(payload: dict) -> dict:
    """`payload` with each `livemode` Chargily wrote as a string made a boolean.

    Applied to a body only once it is authenticated (a verified signature, or
    Chargily's own API), so the mode checks read one type from every provider
    (G1). A value that is neither stays as it is, and those checks refuse it.
    """

    for target in (payload, payload.get("data")):
        if isinstance(target, dict) and "livemode" in target:
            value = target["livemode"]
            if isinstance(value, str):
                value = value.strip().lower()
            if isinstance(value, (bool, str)) and value in _LIVEMODE_VALUES:
                target["livemode"] = _LIVEMODE_VALUES[value]
    return payload


def _scrub(value: object, *, depth: int = 0) -> dict:
    if depth > 6 or not isinstance(value, dict):
        return {}
    cleaned: dict = {}
    for key, item in value.items():
        if key in _SENSITIVE_KEYS:
            cleaned[key] = "[redacted]"
            continue
        if isinstance(item, dict):
            cleaned[key] = _scrub(item, depth=depth + 1)
        elif isinstance(item, list):
            cleaned[key] = [
                _scrub(entry, depth=depth + 1) if isinstance(entry, dict) else entry
                for entry in item[:20]
            ]
        else:
            cleaned[key] = item
    return cleaned
