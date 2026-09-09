"""Stripe: signature verification, checkout creation, and webhook handling.

The adapter speaks Stripe's documented HTTP contract, so these tests attack
that contract directly rather than a wrapper. The signature verifier gets a
tampered body, a stale timestamp, a downgraded scheme and a rolled secret; the
checkout builder is checked for the exact form fields Stripe expects; and the
webhook path is exercised through the real endpoint with real HMACs.

No network is involved. A fake `requests`-shaped session records what the
adapter *would* have sent, which is the part of the integration under test —
the rest is Stripe's job and is verified against their published contract.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from urllib.parse import parse_qs

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.finance.models import PaymentProviderEvent
from apps.finance.services import _reference_uuid

from apps.finance.providers.base import (
    CheckoutRequest,
    ProviderError,
    ProviderNotConfigured,
    ProviderSignatureError,
    ProviderUnavailable,
    RefundRequest,
)
from apps.finance.providers.stripe import (
    DEFAULT_SIGNATURE_TOLERANCE_SECONDS,
    StripeGateway,
    verify_stripe_signature,
)

SECRET = "whsec_test_secret_value"


def stripe_signature(body: bytes, *, secret: str = SECRET, timestamp: int | None = None) -> str:
    stamp = str(timestamp if timestamp is not None else int(time.time()))
    digest = hmac.new(
        secret.encode("utf-8"), f"{stamp}.".encode("utf-8") + body, hashlib.sha256
    ).hexdigest()
    return f"t={stamp},v1={digest}"


class _FakeResponse:
    def __init__(self, status_code: int, body: dict | str):
        self.status_code = status_code
        self._body = body

    def json(self):
        if isinstance(self._body, str):
            raise ValueError("not json")
        return self._body


class _FakeSession:
    """Records outbound calls and replays canned provider responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, *, headers=None, data=None, timeout=None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers or {},
                "data": data,
                "timeout": timeout,
            }
        )
        if not self.responses:
            raise AssertionError(f"No canned response for {method} {url}")
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _gateway(responses=None) -> StripeGateway:
    return StripeGateway(
        secret_key="sk_test_key",
        webhook_secret=SECRET,
        api_base="https://api.stripe.test",
        session=_FakeSession(responses or []),
    )


class StripeSignatureTests(TestCase):
    """The manual verification Stripe documents, attacked directly."""

    body = b'{"id":"evt_1","type":"checkout.session.completed"}'

    def test_a_correct_signature_passes(self):
        verify_stripe_signature(
            raw_body=self.body,
            signature_header=stripe_signature(self.body),
            secret=SECRET,
        )

    def test_a_tampered_body_is_rejected(self):
        header = stripe_signature(self.body)

        with self.assertRaises(ProviderSignatureError):
            verify_stripe_signature(
                raw_body=self.body.replace(b"evt_1", b"evt_2"),
                signature_header=header,
                secret=SECRET,
            )

    def test_the_wrong_secret_is_rejected(self):
        with self.assertRaises(ProviderSignatureError):
            verify_stripe_signature(
                raw_body=self.body,
                signature_header=stripe_signature(self.body, secret="whsec_other"),
                secret=SECRET,
            )

    def test_a_stale_timestamp_is_rejected_as_a_replay(self):
        stale = int(time.time()) - (DEFAULT_SIGNATURE_TOLERANCE_SECONDS + 60)

        with self.assertRaises(ProviderSignatureError):
            verify_stripe_signature(
                raw_body=self.body,
                signature_header=stripe_signature(self.body, timestamp=stale),
                secret=SECRET,
            )

    def test_a_v0_only_signature_is_refused_as_a_downgrade(self):
        """v0 is Stripe's test scheme; honouring it would be a downgrade."""

        stamp = str(int(time.time()))
        digest = hmac.new(
            SECRET.encode("utf-8"),
            f"{stamp}.".encode("utf-8") + self.body,
            hashlib.sha256,
        ).hexdigest()

        with self.assertRaises(ProviderSignatureError):
            verify_stripe_signature(
                raw_body=self.body,
                signature_header=f"t={stamp},v0={digest}",
                secret=SECRET,
            )

    def test_any_matching_v1_wins_while_a_secret_is_being_rolled(self):
        stamp = str(int(time.time()))
        good = hmac.new(
            SECRET.encode("utf-8"),
            f"{stamp}.".encode("utf-8") + self.body,
            hashlib.sha256,
        ).hexdigest()

        verify_stripe_signature(
            raw_body=self.body,
            signature_header=f"t={stamp},v1=deadbeef,v1={good}",
            secret=SECRET,
        )

    def test_a_missing_or_malformed_header_is_rejected(self):
        for header in ("", "garbage", "t=123", "v1=abc"):
            with self.assertRaises(ProviderSignatureError):
                verify_stripe_signature(
                    raw_body=self.body, signature_header=header, secret=SECRET
                )

    def test_an_unconfigured_secret_refuses_rather_than_accepts(self):
        with self.assertRaises(ProviderNotConfigured):
            verify_stripe_signature(
                raw_body=self.body,
                signature_header=stripe_signature(self.body),
                secret="",
            )

    def test_a_non_ascii_signature_is_a_signature_failure_not_a_crash(self):
        """`hmac.compare_digest` raises TypeError on non-ASCII strings.

        Left unguarded, one line of header from an unauthenticated caller
        becomes a 500 — and a 5xx tells a real provider to retry forever.
        """

        stamp = str(int(time.time()))

        with self.assertRaises(ProviderSignatureError):
            verify_stripe_signature(
                raw_body=self.body,
                signature_header=f"t={stamp},v1=café",
                secret=SECRET,
            )

    def test_a_non_hex_signature_is_refused(self):
        stamp = str(int(time.time()))

        for bogus in ("!!!", "zz" * 32, "a" * 300):
            with self.assertRaises(ProviderSignatureError):
                verify_stripe_signature(
                    raw_body=self.body,
                    signature_header=f"t={stamp},v1={bogus}",
                    secret=SECRET,
                )

    def test_an_oversized_body_is_refused_before_hashing(self):
        with self.assertRaises(ProviderSignatureError):
            verify_stripe_signature(
                raw_body=b"x" * (600 * 1024),
                signature_header=stripe_signature(b"x"),
                secret=SECRET,
            )


class StripeCheckoutTests(TestCase):
    def _request(self, **overrides) -> CheckoutRequest:
        base = {
            "reference": "ref-123",
            "amount_minor": 6_250,
            "currency": "EUR",
            "amount_exponent": 2,
            "idempotency_key": "shiptrip-order-7-abc",
            "success_url": "https://shiptrip.test/pay/ok",
            "failure_url": "https://shiptrip.test/pay/no",
            "webhook_url": "https://shiptrip.test/api/payments/webhooks/stripe",
            "description": "ShipTrip delivery payment",
            "metadata": {"order_reference": "ref-123"},
        }
        base.update(overrides)
        return CheckoutRequest(**base)

    def test_a_checkout_sends_the_server_calculated_amount_and_idempotency_key(self):
        gateway = _gateway(
            [
                _FakeResponse(
                    200,
                    {"id": "cs_test_1", "url": "https://checkout.stripe.test/cs_test_1"},
                )
            ]
        )

        result = gateway.create_checkout(self._request())

        call = gateway._session.calls[0]
        form = parse_qs(call["data"])
        assert call["url"] == "https://api.stripe.test/v1/checkout/sessions"
        assert call["headers"]["Idempotency-Key"] == "shiptrip-order-7-abc"
        assert call["headers"]["Authorization"] == "Bearer sk_test_key"
        assert form["line_items[0][price_data][unit_amount]"] == ["6250"]
        assert form["line_items[0][price_data][currency]"] == ["eur"]
        assert form["client_reference_id"] == ["ref-123"]
        assert result.provider_session_id == "cs_test_1"
        assert result.checkout_url.startswith("https://checkout.stripe.test/")

    def test_a_non_eur_checkout_is_refused_rather_than_converted(self):
        gateway = _gateway()

        with self.assertRaises(ProviderError):
            gateway.create_checkout(self._request(currency="DZD"))

    def test_missing_credentials_refuse_the_checkout(self):
        gateway = StripeGateway(secret_key="", webhook_secret="", session=_FakeSession([]))

        assert gateway.is_configured() is False
        with self.assertRaises(ProviderNotConfigured):
            gateway.create_checkout(self._request())

    def test_a_provider_outage_is_reported_as_retryable(self):
        gateway = _gateway([_FakeResponse(503, {"error": {"message": "down"}})])

        with self.assertRaises(ProviderUnavailable):
            gateway.create_checkout(self._request())

    def test_a_provider_rejection_is_reported_as_a_definite_failure(self):
        gateway = _gateway(
            [_FakeResponse(400, {"error": {"message": "bad", "code": "card_declined"}})]
        )

        with self.assertRaises(ProviderError) as caught:
            gateway.create_checkout(self._request())

        assert caught.exception.provider_code == "card_declined"
        assert not isinstance(caught.exception, ProviderUnavailable)

    def test_a_transport_timeout_is_retryable_not_a_failure(self):
        import requests as requests_module

        gateway = _gateway([requests_module.Timeout("timed out")])

        with self.assertRaises(ProviderUnavailable):
            gateway.create_checkout(self._request())

    def test_a_refund_targets_the_payment_intent_with_an_idempotency_key(self):
        gateway = _gateway([_FakeResponse(200, {"id": "re_1", "status": "succeeded"})])

        result = gateway.refund(
            RefundRequest(
                provider_payment_id="pi_1",
                provider_session_id="cs_1",
                amount_minor=6_250,
                currency="EUR",
                idempotency_key="refund:attempt:9:deposit_expiry",
                reason="deposit_expiry",
            )
        )

        call = gateway._session.calls[0]
        form = parse_qs(call["data"])
        assert call["url"].endswith("/v1/refunds")
        assert form["payment_intent"] == ["pi_1"]
        assert form["amount"] == ["6250"]
        assert call["headers"]["Idempotency-Key"] == "refund:attempt:9:deposit_expiry"
        assert result.succeeded is True

    def test_a_pending_refund_is_not_reported_as_returned_money(self):
        gateway = _gateway([_FakeResponse(200, {"id": "re_2", "status": "pending"})])

        result = gateway.refund(
            RefundRequest(
                provider_payment_id="pi_1",
                provider_session_id="cs_1",
                amount_minor=100,
                currency="EUR",
                idempotency_key="k",
            )
        )

        assert result.succeeded is False


class StripeWebhookParsingTests(TestCase):
    def _event(self, event_type: str, obj: dict, event_id: str = "evt_1") -> bytes:
        return json.dumps(
            {"id": event_id, "type": event_type, "data": {"object": obj}},
            separators=(",", ":"),
        ).encode("utf-8")

    def _parse(self, body: bytes, header: str | None = None):
        gateway = _gateway()
        return gateway.parse_webhook(
            raw_body=body,
            headers={"stripe-signature": header or stripe_signature(body)},
        )

    def test_a_paid_checkout_session_is_a_success(self):
        body = self._event(
            "checkout.session.completed",
            {
                "object": "checkout.session",
                "id": "cs_1",
                "payment_status": "paid",
                "payment_intent": "pi_1",
                "amount_total": 6_250,
                "currency": "eur",
                "client_reference_id": "ref-1",
            },
        )

        event = self._parse(body)

        assert event.outcome == "succeeded"
        assert event.provider_session_id == "cs_1"
        assert event.provider_payment_id == "pi_1"
        assert event.amount_minor == 6_250
        assert event.currency == "EUR"
        assert event.reference == "ref-1"

    def test_a_completed_but_unpaid_session_is_not_a_success(self):
        """`completed` describes the session, not the money."""

        body = self._event(
            "checkout.session.completed",
            {
                "object": "checkout.session",
                "id": "cs_2",
                "payment_status": "unpaid",
            },
        )

        outcome = self._parse(body).outcome
        assert outcome != "succeeded"
        # Reported as still in flight rather than as nothing at all, so the
        # attempt stays open for the async result that follows.
        assert outcome == "processing"

    def test_an_expired_session_is_reported_as_expired(self):
        body = self._event(
            "checkout.session.expired",
            {"object": "checkout.session", "id": "cs_3"},
        )

        assert self._parse(body).outcome == "expired"

    def test_a_failed_payment_intent_is_reported_as_failed(self):
        body = self._event(
            "payment_intent.payment_failed",
            {"object": "payment_intent", "id": "pi_9", "last_payment_error": {"code": "card_declined"}},
        )
        event = self._parse(body)

        assert event.outcome == "failed"
        assert event.failure_code == "card_declined"

    def test_a_delayed_payment_method_is_reported_as_processing(self):
        """SEPA and bank transfer complete the session before the money lands."""

        body = self._event(
            "checkout.session.completed",
            {
                "object": "checkout.session",
                "id": "cs_async",
                "payment_status": "unpaid",
                "payment_intent": "pi_async",
                "amount_total": 6_250,
                "currency": "eur",
            },
        )

        event = self._parse(body)

        assert event.outcome == "processing"

    def test_the_later_async_success_settles_it(self):
        body = self._event(
            "checkout.session.async_payment_succeeded",
            {
                "object": "checkout.session",
                "id": "cs_async",
                "payment_status": "paid",
                "amount_total": 6_250,
                "currency": "eur",
            },
            event_id="evt_async_ok",
        )

        assert self._parse(body).outcome == "succeeded"

    def test_an_unrelated_event_type_is_ignored_rather_than_guessed(self):
        body = self._event("customer.created", {"object": "customer", "id": "cus_1"})

        assert self._parse(body).outcome == "ignored"

    def test_the_stored_payload_carries_no_customer_pii(self):
        body = self._event(
            "checkout.session.completed",
            {
                "object": "checkout.session",
                "id": "cs_4",
                "payment_status": "paid",
                "customer_details": {"email": "guest@example.com", "name": "A Guest"},
                "billing_details": {"address": {"line1": "1 Secret Street"}},
            },
        )

        event = self._parse(body)
        stored = json.dumps(event.payload)

        # The email is used to label the attempt but is scrubbed from storage.
        assert event.guest_email == "guest@example.com"
        assert "guest@example.com" not in stored
        assert "1 Secret Street" not in stored
        assert "[redacted]" in stored

    def test_a_body_that_is_not_json_is_rejected(self):
        body = b"not json at all"

        with self.assertRaises(ProviderSignatureError):
            self._parse(body)

    def test_an_event_without_an_id_is_rejected(self):
        body = json.dumps({"type": "checkout.session.completed"}).encode("utf-8")

        with self.assertRaises(ProviderSignatureError):
            self._parse(body)


class StripeWebhookEndpointTests(TestCase):
    """The HTTP surface: unsigned and misfiled events must change nothing."""

    def test_an_unsigned_webhook_is_rejected_without_detail(self):
        response = self.client.post(
            reverse("finance-webhook-stripe"),
            data=b'{"id":"evt_x","type":"checkout.session.completed"}',
            content_type="application/json",
        )

        assert response.status_code in (400, 503)
        body = json.loads(response.content)
        # No hint about whether the referenced payment exists.
        assert set(body) <= {"code"}

    def test_the_endpoint_needs_no_authentication_but_grants_none(self):
        """An anonymous POST is accepted for parsing and then refused."""

        response = self.client.post(
            reverse("finance-webhook-stripe"),
            data=b"{}",
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="t=1,v1=deadbeef",
        )

        assert response.status_code in (400, 503)

    @override_settings(STRIPE_WEBHOOK_SECRET=SECRET)
    def test_a_reference_that_is_not_an_order_reference_does_not_wedge_the_endpoint(
        self,
    ):
        """`client_reference_id` is free text, and our references are UUIDs.

        Anything that can open a Checkout Session on this account chooses that
        string. Handing it to a `UUIDField` lookup raised `ValidationError` out
        of the view, which answered 500 and asked Stripe to redeliver the same
        poisoned event forever — one malformed value stalling every event queued
        behind it. It must simply match no order.
        """

        body = json.dumps(
            {
                "id": "evt_bad_reference",
                "type": "checkout.session.expired",
                "livemode": False,
                "data": {
                    "object": {
                        "object": "checkout.session",
                        "id": "cs_bad_reference",
                        "client_reference_id": "not-a-uuid",
                    }
                },
            },
            separators=(",", ":"),
        ).encode("utf-8")

        response = self.client.post(
            reverse("finance-webhook-stripe"),
            data=body,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE=stripe_signature(body),
        )

        assert response.status_code == 200
        # Receipt is durable, so a redelivery is a duplicate rather than a
        # second economic identity.
        assert PaymentProviderEvent.objects.filter(
            provider_event_id="evt_bad_reference"
        ).exists()

    def test_a_reference_that_is_not_a_uuid_matches_no_order(self):
        assert _reference_uuid("not-a-uuid") is None
        assert _reference_uuid("") is None
        assert _reference_uuid(None) is None
        reference = uuid.uuid4()
        assert _reference_uuid(str(reference)) == reference
