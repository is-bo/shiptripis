"""Stripe adapter, written against Stripe's own HTTP contract.

There is no `stripe` SDK in this project's dependency set, so this adapter
speaks the documented REST API directly: form-encoded requests to
`https://api.stripe.com/v1`, an `Idempotency-Key` header on every mutation, and
manual `Stripe-Signature` verification exactly as Stripe documents it for
integrations that do not use an official library
(https://docs.stripe.com/webhooks#verify-manually):

1. split the header on ``,`` then ``=`` to recover ``t`` and every ``v1``
2. build ``signed_payload = f"{t}.{raw_body}"``
3. HMAC-SHA256 it with the endpoint's ``whsec_`` signing secret
4. compare in constant time, and reject a timestamp outside the tolerance

Only the ``v1`` scheme is honoured; ``v0`` is a test-only scheme and accepting
it would be a downgrade. Several ``v1`` signatures may be present while a
secret is being rolled, so any one match is sufficient.

Nothing in this module decides an amount, and nothing here writes to a model.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from urllib.parse import urlencode

import requests
from django.conf import settings

from .base import (
    MODE_LIVE,
    MODE_NOT_CONFIGURED,
    MODE_TEST,
    MODE_UNKNOWN,
    AttemptSnapshot,
    CheckoutRequest,
    CheckoutResult,
    PayoutCapability,
    ProviderCheckoutRejected,
    ProviderError,
    ProviderEvent,
    ProviderNotConfigured,
    ProviderSignatureError,
    ProviderUnavailable,
    RefundRequest,
    RefundResult,
)

logger = logging.getLogger(__name__)

#: Stripe rejects a request body larger than this long before we would; the cap
#: exists so a hostile webhook cannot make us hash an unbounded buffer.
MAX_WEBHOOK_BYTES = 512 * 1024

#: Stripe's own libraries default to five minutes.
DEFAULT_SIGNATURE_TOLERANCE_SECONDS = 300


#: A SHA-256 hex digest and nothing else.
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def _is_hex_signature(value: str) -> bool:
    return bool(value) and len(value) <= 128 and all(c in _HEX_DIGITS for c in value)


def _stripe_signature_payload(raw_body: bytes, timestamp: str) -> bytes:
    return timestamp.encode("utf-8") + b"." + raw_body


def verify_stripe_signature(
    *,
    raw_body: bytes,
    signature_header: str,
    secret: str,
    tolerance_seconds: int = DEFAULT_SIGNATURE_TOLERANCE_SECONDS,
    now: int | None = None,
) -> None:
    """Verify a `Stripe-Signature` header or raise `ProviderSignatureError`.

    Exposed separately from the gateway so tests can attack the verifier
    directly with tampered bodies, stale timestamps and downgraded schemes.
    """

    if not secret:
        raise ProviderNotConfigured("Stripe webhook secret is not configured.")
    if not signature_header:
        raise ProviderSignatureError("Missing Stripe-Signature header.")
    if len(raw_body) > MAX_WEBHOOK_BYTES:
        raise ProviderSignatureError("Webhook body exceeds the accepted size.")

    timestamp = ""
    candidates: list[str] = []
    for element in signature_header.split(","):
        prefix, _, value = element.strip().partition("=")
        if prefix == "t":
            timestamp = value
        elif prefix == "v1":
            # Only the v1 scheme is honoured. v0 is a test scheme and
            # accepting it would be a downgrade attack.
            #
            # A signature Stripe could have produced is lowercase hex.
            # Discarding anything else here is not cosmetic:
            # `hmac.compare_digest` raises TypeError on a non-ASCII string, so
            # an unauthenticated caller could otherwise turn a one-line header
            # into a 500 — and a 5xx makes a real provider retry forever.
            if _is_hex_signature(value):
                candidates.append(value)
    if not timestamp or not candidates:
        raise ProviderSignatureError("Malformed Stripe-Signature header.")

    try:
        signed_at = int(timestamp)
    except ValueError as exc:
        raise ProviderSignatureError("Stripe-Signature timestamp is not an integer.") from exc

    expected = hmac.new(
        secret.encode("utf-8"),
        _stripe_signature_payload(raw_body, timestamp),
        hashlib.sha256,
    ).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in candidates):
        raise ProviderSignatureError("No Stripe signature matched the payload.")

    # Signature first, replay window second: the timestamp is only meaningful
    # once we know it was signed by the endpoint secret.
    if tolerance_seconds > 0:
        current = int(time.time()) if now is None else now
        if abs(current - signed_at) > tolerance_seconds:
            raise ProviderSignatureError("Stripe-Signature timestamp is outside tolerance.")


class StripeGateway:
    """EUR-native customer checkout, refunds, and payout-capability lookup."""

    name = "stripe"
    supports_guest_payment = True
    payment_currency = "EUR"

    def __init__(
        self,
        *,
        secret_key: str | None = None,
        webhook_secret: str | None = None,
        api_base: str | None = None,
        api_version: str | None = None,
        timeout_seconds: int | None = None,
        session: requests.Session | None = None,
    ):
        self.secret_key = (
            secret_key
            if secret_key is not None
            else getattr(settings, "STRIPE_SECRET_KEY", "")
        )
        self.webhook_secret = (
            webhook_secret
            if webhook_secret is not None
            else getattr(settings, "STRIPE_WEBHOOK_SECRET", "")
        )
        self.api_base = (
            api_base
            if api_base is not None
            else getattr(settings, "STRIPE_API_BASE", "https://api.stripe.com")
        ).rstrip("/")
        self.api_version = (
            api_version
            if api_version is not None
            else getattr(settings, "STRIPE_API_VERSION", "")
        )
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else getattr(settings, "PAYMENTS_PROVIDER_TIMEOUT_SECONDS", 15)
        )
        self._session = session or requests

    # -- configuration ----------------------------------------------------

    def is_configured(self) -> bool:
        return bool(self.secret_key and self.webhook_secret)

    def credential_mode(self) -> str:
        """Whether the configured key points at Stripe test or live money.

        Read from the key's documented prefix only. Nothing here logs, returns
        or compares the key itself, so an operator (and this deployment's own
        health endpoint) can confirm which rail is armed without a secret ever
        leaving the settings object.
        """

        key = self.secret_key
        if not key:
            return MODE_NOT_CONFIGURED
        # Restricted keys carry the same test/live segment as secret keys.
        if key.startswith(("sk_test_", "rk_test_")):
            return MODE_TEST
        if key.startswith(("sk_live_", "rk_live_")):
            return MODE_LIVE
        return MODE_UNKNOWN

    def configuration_problem(self) -> str:
        """Why this Stripe configuration must not take a new checkout.

        Symmetric with Chargily on purpose. A key whose prefix this code does
        not recognise cannot be reported as test, and "we could not tell whether
        this is real money" is not a state to open a checkout in.
        """

        if not self.secret_key:
            return ""  # Not configured at all — a different, earlier answer.
        if self.credential_mode() == MODE_UNKNOWN:
            return "stripe_credential_unidentified"
        return ""

    def _require_configured(self) -> None:
        if not self.secret_key:
            raise ProviderNotConfigured("STRIPE_SECRET_KEY is not configured.")
        if not self.webhook_secret:
            raise ProviderNotConfigured("STRIPE_WEBHOOK_SECRET is not configured.")

    # -- transport --------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        data: dict | None = None,
        idempotency_key: str = "",
    ) -> dict:
        self._require_configured()
        headers = {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        if self.api_version:
            headers["Stripe-Version"] = self.api_version
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
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
            # Never log the body or the key; the URL and class are enough.
            logger.warning("stripe transport failure on %s %s", method, path)
            raise ProviderUnavailable(f"Stripe request failed: {type(exc).__name__}") from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderUnavailable("Stripe returned a non-JSON response.") from exc

        if response.status_code >= 500:
            raise ProviderUnavailable(
                f"Stripe returned {response.status_code}.",
                provider_code=str(response.status_code),
            )
        if response.status_code == 429:
            raise ProviderUnavailable("Stripe rate limited the request.", provider_code="429")
        error = body.get("error", {}) if isinstance(body, dict) else {}
        if response.status_code in (401, 403):
            # Stripe refused this deployment's key. That is a configuration
            # fact, not a transient one; "try again in a moment" would be false.
            logger.error(
                "stripe auth rejected status=%s credential_mode=%s",
                response.status_code,
                self.credential_mode(),
            )
            raise ProviderNotConfigured(
                "Stripe rejected this deployment's API credentials.",
                provider_code=str(response.status_code),
            )
        if response.status_code >= 400:
            raise ProviderCheckoutRejected(
                error.get("message", "Stripe rejected the request."),
                provider_code=error.get("code", str(response.status_code)),
            )
        return body if isinstance(body, dict) else {}

    # -- checkout ---------------------------------------------------------

    def create_checkout(self, request: CheckoutRequest) -> CheckoutResult:
        if request.currency.upper() != "EUR":
            raise ProviderError(
                "Stripe checkout in this deployment is EUR-native only.",
                provider_code="unsupported_currency",
            )
        data = {
            "mode": "payment",
            "success_url": request.success_url,
            "cancel_url": request.failure_url,
            "client_reference_id": request.reference,
            "line_items[0][quantity]": 1,
            "line_items[0][price_data][currency]": request.currency.lower(),
            "line_items[0][price_data][unit_amount]": request.amount_minor,
            "line_items[0][price_data][product_data][name]": request.description,
            "payment_intent_data[description]": request.description,
            # Adaptive Pricing off, explicitly, on every session.
            #
            # It is a Stripe *Dashboard* setting, and with it on Stripe's hosted
            # page offers the payer a "Choose currency" control — on this
            # corridor, DZD beside the EUR price — converted at Stripe's own
            # rate with a 2-4% fee it charges the customer. Settlement stays
            # EUR, so no ledger or canonical amount is at risk. What is at risk
            # is the product rule: DZD is a Chargily/manual settlement
            # representation at a rate this server controls and snapshots onto
            # the attempt, and a Stripe-set rate is none of those things. It
            # also puts two very different dinar prices for one obligation in
            # front of the same sender.
            #
            # Asserted per session rather than left to the Dashboard, because a
            # product invariant should not depend on a toggle in someone
            # else's console.
            "adaptive_pricing[enabled]": "false",
        }
        if request.customer_email:
            data["customer_email"] = request.customer_email
        for key, value in request.metadata.items():
            data[f"metadata[{key}]"] = value
            data[f"payment_intent_data[metadata][{key}]"] = value

        body = self._request(
            "POST",
            "/v1/checkout/sessions",
            data=data,
            idempotency_key=request.idempotency_key,
        )
        session_id = body.get("id", "")
        checkout_url = body.get("url", "")
        if not session_id or not checkout_url:
            raise ProviderError("Stripe did not return a usable checkout session.")
        return CheckoutResult(
            provider_session_id=session_id,
            checkout_url=checkout_url,
            provider_status=body.get("status", "open"),
            raw=_scrub(body),
        )

    def fetch_attempt(
        self, *, provider_session_id: str, provider_payment_id: str
    ) -> AttemptSnapshot:
        """Poll the provider for the true state of an attempt.

        The reconciliation safety net for a webhook that never arrived. A
        redirect never reaches this code path; only the provider's own answer
        does.
        """

        if not provider_session_id:
            raise ProviderError("No Stripe session to reconcile.")
        body = self._request("GET", f"/v1/checkout/sessions/{provider_session_id}")
        payment_status = body.get("payment_status", "")
        session_status = body.get("status", "")
        payment_intent = body.get("payment_intent") or ""
        if isinstance(payment_intent, dict):
            payment_intent = payment_intent.get("id", "")
        if payment_status == "paid":
            outcome = "succeeded"
        elif session_status == "expired":
            outcome = "expired"
        elif session_status == "complete" and payment_status == "unpaid":
            outcome = "processing"
        elif session_status == "complete":
            outcome = "failed"
        else:
            outcome = "ignored"
        return AttemptSnapshot(
            outcome=outcome,
            provider_payment_id=payment_intent or provider_payment_id,
            amount_minor=body.get("amount_total"),
            currency=(body.get("currency") or "").upper(),
            raw=_scrub(body),
        )

    # -- refunds ----------------------------------------------------------

    def refund(self, request: RefundRequest) -> RefundResult:
        if not request.provider_payment_id:
            raise ProviderError("A Stripe refund needs the PaymentIntent id.")
        body = self._request(
            "POST",
            "/v1/refunds",
            data={
                "payment_intent": request.provider_payment_id,
                "amount": request.amount_minor,
                "metadata[shiptrip_reason]": request.reason[:64],
            },
            idempotency_key=request.idempotency_key,
        )
        refund_id = body.get("id", "")
        status = body.get("status", "")
        if not refund_id:
            raise ProviderError("Stripe did not return a refund id.")
        return RefundResult(
            provider_refund_id=refund_id,
            # `pending` is a real Stripe state for some methods; only
            # `succeeded` is treated as money returned.
            succeeded=status == "succeeded",
            raw=_scrub(body),
        )

    # -- webhooks ---------------------------------------------------------

    def parse_webhook(self, *, raw_body: bytes, headers: dict[str, str]) -> ProviderEvent:
        verify_stripe_signature(
            raw_body=raw_body,
            signature_header=headers.get("stripe-signature", ""),
            secret=self.webhook_secret,
            tolerance_seconds=getattr(
                settings,
                "STRIPE_WEBHOOK_TOLERANCE_SECONDS",
                DEFAULT_SIGNATURE_TOLERANCE_SECONDS,
            ),
        )
        import json

        try:
            event = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ProviderSignatureError("Stripe webhook body is not valid JSON.") from exc
        if not isinstance(event, dict):
            raise ProviderSignatureError("Stripe webhook body is not an object.")

        event_id = str(event.get("id") or "")
        event_type = str(event.get("type") or "")
        if not event_id:
            raise ProviderSignatureError("Stripe webhook carries no event id.")

        obj = ((event.get("data") or {}).get("object") or {})
        if not isinstance(obj, dict):
            obj = {}

        outcome = "ignored"
        if event_type in {
            "checkout.session.completed",
            "checkout.session.async_payment_succeeded",
        }:
            payment_status = obj.get("payment_status")
            if payment_status == "paid":
                outcome = "succeeded"
            elif payment_status == "unpaid":
                # A delayed method (SEPA debit, bank transfer): the session
                # completed but the money has not settled. Stripe follows with
                # `async_payment_succeeded` or `async_payment_failed`. Reporting
                # this as `processing` keeps the attempt open and truthful
                # rather than pretending nothing happened.
                outcome = "processing"
        elif event_type == "checkout.session.expired":
            outcome = "expired"
        elif event_type == "checkout.session.async_payment_failed":
            outcome = "failed"
        elif event_type == "payment_intent.payment_failed":
            outcome = "failed"

        payment_intent = obj.get("payment_intent") or obj.get("id") or ""
        if isinstance(payment_intent, dict):
            payment_intent = payment_intent.get("id", "")
        session_id = obj.get("id", "") if str(obj.get("object", "")) == "checkout.session" else ""
        customer_details = obj.get("customer_details") or {}
        guest_email = ""
        if isinstance(customer_details, dict):
            guest_email = str(customer_details.get("email") or "")

        return ProviderEvent(
            provider=self.name,
            event_id=event_id,
            event_type=event_type,
            outcome=outcome,
            provider_session_id=str(session_id or ""),
            provider_payment_id=str(payment_intent or ""),
            reference=str(obj.get("client_reference_id") or ""),
            amount_minor=obj.get("amount_total"),
            currency=str(obj.get("currency") or "").upper(),
            guest_email=guest_email,
            failure_code=str(
                ((obj.get("last_payment_error") or {}) or {}).get("code") or ""
            ),
            payload=_scrub(event),
        )

    # -- payout capability -------------------------------------------------

    def payout_capability(self, *, account_id: str) -> PayoutCapability:
        """Ask Stripe what this connected account can actually receive.

        Deliberately no country heuristics: the answer is whatever Stripe
        reports for `payouts_enabled` and the `transfers` capability. An
        unreachable Stripe yields `available=False`, so the manual queue is the
        safe default rather than the error case.
        """

        if not account_id:
            return PayoutCapability(available=False, reason="no_connected_account")
        try:
            body = self._request("GET", f"/v1/accounts/{account_id}")
        except ProviderError as exc:
            return PayoutCapability(
                available=False,
                reason=f"provider_unavailable:{exc.code}",
                account_id=account_id,
            )
        capabilities = body.get("capabilities") or {}
        transfers_active = (
            isinstance(capabilities, dict) and capabilities.get("transfers") == "active"
        )
        payouts_enabled = bool(body.get("payouts_enabled"))
        return PayoutCapability(
            available=bool(payouts_enabled and transfers_active),
            reason="" if (payouts_enabled and transfers_active) else "capability_inactive",
            account_id=account_id,
            country_code=str(body.get("country") or ""),
            raw=_scrub(body),
        )


#: Keys that must never be persisted from a provider payload.
_SENSITIVE_KEYS = frozenset(
    {
        "client_secret",
        "secret",
        "card",
        "payment_method_details",
        "source",
        "customer_details",
        "billing_details",
        "shipping_details",
        "receipt_email",
        "email",
        "phone",
        "address",
        "name",
    }
)


def _scrub(value: object, *, depth: int = 0) -> dict:
    """Drop PII and secret-bearing keys before a payload is persisted."""

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
