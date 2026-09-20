"""K1 transport safety for the real Stripe and Chargily adapters."""

from __future__ import annotations

from django.test import SimpleTestCase, override_settings

from apps.finance.providers.chargily import ChargilyGateway
from apps.finance.providers.http import POOL_CONNECTIONS, POOL_MAXSIZE
from apps.finance.providers.stripe import StripeGateway
from apps.finance.providers.stripe_connect import StripeConnectGateway, _timing_operation

from .test_stripe import _FakeResponse, _FakeSession


class ProviderSessionPoolTests(SimpleTestCase):
    def test_gateways_reuse_one_bounded_session_per_provider_and_thread(self):
        first_stripe = StripeGateway(secret_key="sk_test_one")
        second_stripe = StripeGateway(secret_key="sk_test_two")
        stripe_connect = StripeConnectGateway(
            secret_key="sk_test_three", platform_account_id="acct_platform"
        )
        first_chargily = ChargilyGateway(secret_key="test_sk_one")
        second_chargily = ChargilyGateway(secret_key="test_sk_two")

        assert first_stripe._session is second_stripe._session
        assert first_stripe._session is stripe_connect._session
        assert first_chargily._session is second_chargily._session
        assert first_stripe._session is not first_chargily._session

        for session in (first_stripe._session, first_chargily._session):
            for scheme in ("https://", "http://"):
                adapter = session.adapters[scheme]
                assert adapter._pool_connections == POOL_CONNECTIONS
                assert adapter._pool_maxsize == POOL_MAXSIZE
                assert adapter._pool_block is True
                assert adapter.max_retries.total == 0
            assert session.auth is None
            assert "Authorization" not in session.headers
            assert session.cookies.get_policy().set_ok(None, None) is False

    @override_settings(
        PAYMENTS_PROVIDER_CONNECT_TIMEOUT_SECONDS=2.5,
        PAYMENTS_PROVIDER_READ_TIMEOUT_SECONDS=12.0,
    )
    def test_default_transport_uses_separate_bounded_connect_and_read_timeouts(self):
        stripe = StripeGateway(secret_key="sk_test_one", session=_FakeSession([]))
        chargily = ChargilyGateway(secret_key="test_sk_one", session=_FakeSession([]))

        assert stripe.timeout == (2.5, 12.0)
        assert chargily.timeout == (2.5, 12.0)

    def test_explicit_legacy_timeout_override_remains_compatible(self):
        stripe = StripeGateway(
            secret_key="sk_test_one", session=_FakeSession([]), timeout_seconds=7
        )
        chargily = ChargilyGateway(
            secret_key="test_sk_one", session=_FakeSession([]), timeout_seconds=7
        )

        assert stripe.timeout == 7
        assert chargily.timeout == 7

    def test_connect_timing_operation_never_contains_path_identifiers(self):
        operation = _timing_operation(
            "POST", "/v1/accounts/acct_private/external_accounts"
        )

        assert operation == "connect_connected_account_mutate"
        assert "acct_private" not in operation


class ProviderTimingTests(SimpleTestCase):
    def test_stripe_timing_is_structured_without_auth_url_or_payload(self):
        secret = "sk_test_never_log_this"
        session = _FakeSession([_FakeResponse(200, {"id": "acct_1"})])
        gateway = StripeGateway(
            secret_key=secret,
            webhook_secret="whsec_test_never_log_this",
            session=session,
        )

        with self.assertLogs("shiptrip.provider", level="INFO") as captured:
            gateway._request("GET", "/v1/accounts/acct_private", operation="account_fetch")

        record = captured.records[0]
        assert record.event == "provider_http_call"
        assert record.provider == "stripe"
        assert record.operation == "account_fetch"
        assert record.outcome == "success"
        assert record.duration_ms >= 0
        serialized_record = str(record.__dict__)
        assert secret not in serialized_record
        assert "acct_private" not in serialized_record
        assert "Authorization" not in serialized_record

    def test_chargily_timing_is_structured_without_auth_url_or_payload(self):
        secret = "test_sk_never_log_this"
        session = _FakeSession([_FakeResponse(200, {"id": "checkout_private"})])
        gateway = ChargilyGateway(secret_key=secret, session=session)

        with self.assertLogs("shiptrip.provider", level="INFO") as captured:
            gateway._request("GET", "/checkouts/private", operation="checkout_fetch")

        record = captured.records[0]
        assert record.event == "provider_http_call"
        assert record.provider == "chargily"
        assert record.operation == "checkout_fetch"
        assert record.outcome == "success"
        assert record.duration_ms >= 0
        serialized_record = str(record.__dict__)
        assert secret not in serialized_record
        assert "checkout_private" not in serialized_record
        assert "Authorization" not in serialized_record
