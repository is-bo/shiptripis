"""The Stripe Connect adapter's HTTP contract, in isolation.

Every test here drives a fake transport, so nothing reaches Stripe. What is
asserted is exactly the boundary H0 fixed: which headers go out, which
parameters go out, what comes back as a safe projection, and what happens on
each failure shape. The last test in the file is the money guard.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import parse_qs

import pytest
import requests
from django.test import override_settings

from apps.finance.providers.base import (
    ProviderCheckoutRejected,
    ProviderError,
    ProviderNotConfigured,
    ProviderUnavailable,
)
from apps.finance.providers.stripe_connect import (
    DEFAULT_CONNECT_API_VERSION,
    ConnectPlatformMismatch,
    StripeConnectGateway,
)

PLATFORM = "acct_1TESTplatform"

CONNECT_SETTINGS = dict(
    STRIPE_SECRET_KEY="sk_test_adapter",
    STRIPE_CONNECT_PLATFORM_ACCOUNT_ID=PLATFORM,
    STRIPE_CONNECT_API_VERSION="2026-03-25.dahlia",
    STRIPE_CONNECT_EXPECTED_MODE="test",
    STRIPE_CONNECT_ENABLED=True,
    STRIPE_CONNECT_ALLOWED_COUNTRIES=["FR"],
)


class FakeResponse:
    def __init__(self, status_code=200, body=None, *, text=None, request_id="req_1"):
        self.status_code = status_code
        self._body = body
        self._text = text
        self.headers = {"Request-Id": request_id}

    def json(self):
        if self._text is not None:
            raise ValueError("not json")
        return self._body


class FakeSession:
    """Records every outbound call and replays a scripted answer."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def request(self, method, url, *, headers, data, timeout):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "data": parse_qs(data, keep_blank_values=True),
                "timeout": timeout,
            }
        )
        answer = self.answers.pop(0) if self.answers else FakeResponse()
        if isinstance(answer, Exception):
            raise answer
        return answer


def account_body(**overrides):
    body = {
        "id": "acct_1TESTconnected",
        "object": "account",
        "livemode": False,
        "country": "FR",
        "default_currency": "eur",
        "details_submitted": False,
        "payouts_enabled": False,
        "charges_enabled": False,
        "capabilities": {"transfers": "pending"},
        "controller": {
            "type": "application",
            "is_controller": True,
            "losses": {"payments": "application"},
            "requirement_collection": "stripe",
            "fees": {"payer": "application"},
            "stripe_dashboard": {"type": "express"},
        },
        "requirements": {
            "currently_due": ["external_account"],
            "past_due": [],
            "pending_verification": [],
            "disabled_reason": "requirements.past_due",
            "current_deadline": None,
            "errors": [
                {
                    "requirement": "individual.first_name",
                    "reason": "The name Jean Dupont could not be verified",
                }
            ],
        },
        "settings": {"payouts": {"schedule": {"interval": "manual", "delay_days": 2}}},
        "external_accounts": {"object": "list", "data": []},
        "metadata": {"shiptrip_method": "method-uuid"},
    }
    body.update(overrides)
    return body


def gateway(*answers):
    return StripeConnectGateway(
        secret_key="sk_test_adapter",
        api_base="https://api.stripe.test",
        api_version="2026-03-25.dahlia",
        platform_account_id=PLATFORM,
        timeout_seconds=7,
        session=FakeSession(*answers),
    )


class TestTransport:
    def test_every_request_pins_the_configured_api_version(self):
        client = gateway(FakeResponse(body={"id": PLATFORM, "country": "FR"}))
        client.platform_identity()
        assert client._session.calls[0]["headers"]["Stripe-Version"] == (
            "2026-03-25.dahlia"
        )

    def test_the_pinned_default_is_h0s_version(self):
        with override_settings(**CONNECT_SETTINGS):
            assert DEFAULT_CONNECT_API_VERSION == "2026-03-25.dahlia"

    def test_an_empty_configured_version_falls_back_to_the_pin_not_the_account(self):
        client = StripeConnectGateway(
            secret_key="sk_test_adapter",
            api_version="",
            platform_account_id=PLATFORM,
            session=FakeSession(FakeResponse(body={"id": PLATFORM})),
        )
        client.platform_identity()
        assert client._session.calls[0]["headers"]["Stripe-Version"] == (
            DEFAULT_CONNECT_API_VERSION
        )

    def test_the_finite_timeout_is_passed_to_every_call(self):
        client = gateway(FakeResponse(body=account_body()))
        client.retrieve_account("acct_1TESTconnected")
        assert client._session.calls[0]["timeout"] == 7

    def test_the_request_id_is_captured_and_the_secret_is_not_returned(self):
        client = gateway(FakeResponse(body=account_body(), request_id="req_abc"))
        snapshot = client.retrieve_account("acct_1TESTconnected")
        assert snapshot.request_id == "req_abc"
        assert "sk_test_adapter" not in json.dumps(
            {
                "country": snapshot.country,
                "requirements": snapshot.requirement_codes,
                "controller": snapshot.controller,
            }
        )

    def test_nothing_logs_the_secret_key(self, caplog):
        client = gateway(requests.ConnectionError("boom"))
        with caplog.at_level("WARNING"), pytest.raises(ProviderUnavailable):
            client.retrieve_account("acct_1TESTconnected")
        assert "sk_test_adapter" not in caplog.text

    def test_an_unconfigured_platform_refuses_before_any_call(self):
        client = StripeConnectGateway(
            secret_key="sk_test_adapter",
            platform_account_id="",
            session=FakeSession(FakeResponse(body={})),
        )
        with pytest.raises(ProviderNotConfigured):
            client.retrieve_account("acct_x")
        assert client._session.calls == []


class TestAccountScope:
    """Scope is always the caller's decision, never inferred from the path."""

    def test_h2_operations_are_platform_scoped_and_send_no_account_header(self):
        client = gateway(
            FakeResponse(body=account_body()),
            FakeResponse(body={"object": "login_link", "url": "https://x"}),
        )
        client.retrieve_account("acct_1TESTconnected")
        client.create_login_link(account_id="acct_1TESTconnected")
        for call in client._session.calls:
            assert "Stripe-Account" not in call["headers"]

    def test_an_explicit_scope_is_sent_verbatim_when_a_caller_asks_for_one(self):
        client = gateway(FakeResponse(body={"object": "balance"}))
        client._request(
            "GET", "/v1/some/connected/read", stripe_account="acct_1TESTconnected"
        )
        assert client._session.calls[0]["headers"]["Stripe-Account"] == (
            "acct_1TESTconnected"
        )


class TestCheckoutAdapterIsolation:
    """The Sender rail keeps its own version and its own behaviour.

    H2 adds a payout capability beside Checkout; it does not re-version it. A
    change to `STRIPE_CONNECT_API_VERSION` must be invisible to the Checkout
    adapter, or one payout decision would silently re-version every payment.
    """

    def test_the_checkout_adapter_does_not_read_the_connect_version(self):
        from apps.finance.providers.stripe import StripeGateway

        with override_settings(**{**CONNECT_SETTINGS, "STRIPE_API_VERSION": ""}):
            assert StripeGateway().api_version == ""
            assert StripeConnectGateway().api_version == "2026-03-25.dahlia"

    def test_the_checkout_adapter_has_no_connect_account_surface(self):
        from apps.finance.providers.stripe import StripeGateway

        for name in ("create_account", "create_account_link", "create_login_link"):
            assert not hasattr(StripeGateway, name)

    def test_a_checkout_session_is_still_eur_with_adaptive_pricing_off(self):
        from apps.finance.providers.base import CheckoutRequest
        from apps.finance.providers.stripe import StripeGateway

        session = FakeSession(
            FakeResponse(body={"id": "cs_1", "url": "https://pay.test/x"})
        )
        StripeGateway(
            secret_key="sk_test_x",
            webhook_secret="whsec_x",
            api_base="https://api.stripe.test",
            session=session,
        ).create_checkout(
            CheckoutRequest(
                reference="ref",
                amount_minor=6000,
                currency="EUR",
                amount_exponent=2,
                idempotency_key="idem",
                success_url="https://s",
                failure_url="https://f",
                webhook_url="https://w",
                description="ShipTrip delivery",
            )
        )
        data = session.calls[0]["data"]
        assert data["line_items[0][price_data][currency]"] == ["eur"]
        assert data["adaptive_pricing[enabled]"] == ["false"]


class TestPlatformIdentity:
    def test_a_matching_platform_is_accepted_with_its_country_and_currency(self):
        client = gateway(
            FakeResponse(
                body={"id": PLATFORM, "country": "FR", "default_currency": "eur"}
            )
        )
        identity = client.platform_identity()
        assert identity.account_id == PLATFORM
        assert (identity.country, identity.default_currency) == ("FR", "eur")
        assert identity.mode == "test"

    def test_a_different_platform_account_is_a_stop_condition(self):
        client = gateway(FakeResponse(body={"id": "acct_someone_else"}))
        with pytest.raises(ConnectPlatformMismatch):
            client.platform_identity()


class TestAccountCreation:
    def _create(self):
        client = gateway(FakeResponse(body=account_body()))
        client.create_account(
            country="fr",
            idempotency_key="acct_create:key",
            metadata={"shiptrip_method": "method-uuid"},
        )
        return client._session.calls[0]

    def test_the_controller_hash_is_h0s_explicit_configuration(self):
        call = self._create()
        assert call["data"]["controller[stripe_dashboard][type]"] == ["express"]
        assert call["data"]["controller[requirement_collection]"] == ["stripe"]
        assert call["data"]["controller[fees][payer]"] == ["application"]
        assert call["data"]["controller[losses][payments]"] == ["application"]

    def test_the_deprecated_type_shorthand_is_never_sent(self):
        assert "type" not in self._create()["data"]

    def test_only_transfers_is_requested_never_card_payments(self):
        data = self._create()["data"]
        assert data["capabilities[transfers][requested]"] == ["true"]
        assert not [key for key in data if "card_payments" in key]

    def test_country_currency_and_business_type_are_explicit(self):
        data = self._create()["data"]
        assert data["country"] == ["FR"]
        assert data["default_currency"] == ["eur"]
        assert data["business_type"] == ["individual"]

    def test_the_idempotency_key_is_sent_as_a_header(self):
        assert self._create()["headers"]["Idempotency-Key"] == "acct_create:key"

    def test_metadata_carries_only_opaque_internal_references(self):
        data = self._create()["data"]
        assert data["metadata[shiptrip_method]"] == ["method-uuid"]
        assert not [key for key in data if "email" in key or "name" in key]


class TestSnapshot:
    def test_requirement_error_prose_is_never_projected(self):
        client = gateway(FakeResponse(body=account_body()))
        snapshot = client.retrieve_account("acct_1TESTconnected")
        assert snapshot.requirement_codes == ["external_account"]
        assert "Jean Dupont" not in json.dumps(
            [
                snapshot.requirement_codes,
                snapshot.past_due_codes,
                snapshot.pending_verification_codes,
                snapshot.disabled_reason,
            ]
        )

    def test_a_eur_bank_yields_its_id_and_nothing_else_about_it(self):
        body = account_body(
            external_accounts={
                "object": "list",
                "data": [
                    {
                        "id": "ba_1TESTbank",
                        "object": "bank_account",
                        "currency": "eur",
                        "default_for_currency": True,
                        "status": "new",
                        "account_holder_name": "Jean Dupont",
                        "last4": "3000",
                        "routing_number": "30003",
                    }
                ],
            }
        )
        snapshot = gateway(FakeResponse(body=body)).retrieve_account("acct_x")
        assert snapshot.eur_bank_present is True
        assert snapshot.eur_bank_account_id == "ba_1TESTbank"
        # The whole projection, rendered: the holder's name, the last four and
        # the routing number were in the response and are in none of it.
        rendered = json.dumps(
            {
                field: getattr(snapshot, field)
                for field in snapshot.__slots__
                if field != "metadata"
            },
            default=str,
        )
        for leaked in ("Dupont", "3000", "30003"):
            assert leaked not in rendered

    def test_a_debit_card_is_not_a_eur_bank_destination(self):
        body = account_body(
            external_accounts={
                "object": "list",
                "data": [
                    {"id": "card_1", "object": "card", "currency": "eur"},
                ],
            }
        )
        snapshot = gateway(FakeResponse(body=body)).retrieve_account("acct_x")
        assert snapshot.eur_bank_present is False
        assert snapshot.eur_bank_account_id == ""

    def test_a_non_eur_bank_is_not_an_eligible_destination(self):
        body = account_body(
            external_accounts={
                "object": "list",
                "data": [
                    {
                        "id": "ba_usd",
                        "object": "bank_account",
                        "currency": "usd",
                        "status": "new",
                    }
                ],
            }
        )
        snapshot = gateway(FakeResponse(body=body)).retrieve_account("acct_x")
        assert snapshot.eur_bank_present is False

    def test_the_default_for_currency_bank_wins_over_a_second_one(self):
        body = account_body(
            external_accounts={
                "object": "list",
                "data": [
                    {
                        "id": "ba_secondary",
                        "object": "bank_account",
                        "currency": "eur",
                        "status": "new",
                    },
                    {
                        "id": "ba_default",
                        "object": "bank_account",
                        "currency": "eur",
                        "status": "new",
                        "default_for_currency": True,
                    },
                ],
            }
        )
        snapshot = gateway(FakeResponse(body=body)).retrieve_account("acct_x")
        assert snapshot.eur_bank_account_id == "ba_default"

    def test_an_errored_bank_is_not_counted_as_present(self):
        body = account_body(
            external_accounts={
                "object": "list",
                "data": [
                    {
                        "id": "ba_bad",
                        "object": "bank_account",
                        "currency": "eur",
                        "status": "errored",
                    }
                ],
            }
        )
        assert gateway(FakeResponse(body=body)).retrieve_account("a").eur_bank_present is False

    def test_a_body_that_is_not_an_account_is_refused(self):
        with pytest.raises(ProviderError):
            gateway(FakeResponse(body={"id": "cus_notanaccount"})).retrieve_account("a")

    def test_livemode_is_carried_through_rather_than_assumed(self):
        snapshot = gateway(
            FakeResponse(body=account_body(livemode=True))
        ).retrieve_account("a")
        assert snapshot.livemode is True
        missing = gateway(
            FakeResponse(body={k: v for k, v in account_body().items() if k != "livemode"})
        ).retrieve_account("a")
        assert missing.livemode is None


class TestHostedLinks:
    def test_the_account_link_uses_account_onboarding(self):
        client = gateway(
            FakeResponse(
                body={
                    "object": "account_link",
                    "url": "https://connect.stripe.test/setup/c/acct/abc",
                    "expires_at": 1700000300,
                }
            )
        )
        link = client.create_account_link(
            account_id="acct_1TESTconnected",
            return_url="https://api.shiptrip.test/payouts/stripe/return?state=s",
            refresh_url="https://api.shiptrip.test/payouts/stripe/refresh?state=s",
        )
        data = client._session.calls[0]["data"]
        assert data["type"] == ["account_onboarding"]
        assert data["account"] == ["acct_1TESTconnected"]
        assert data["return_url"][0].startswith("https://api.shiptrip.test/")
        assert data["refresh_url"][0].startswith("https://api.shiptrip.test/")
        assert link.expires_at == 1700000300

    def test_a_link_response_without_a_url_is_refused(self):
        with pytest.raises(ProviderError):
            gateway(FakeResponse(body={"object": "account_link"})).create_account_link(
                account_id="a", return_url="r", refresh_url="f"
            )

    def test_the_login_link_targets_the_account_and_returns_a_url(self):
        client = gateway(
            FakeResponse(
                body={"object": "login_link", "url": "https://connect.stripe.test/x"}
            )
        )
        link = client.create_login_link(account_id="acct_1TESTconnected")
        assert client._session.calls[0]["url"].endswith(
            "/v1/accounts/acct_1TESTconnected/login_links"
        )
        assert link.url == "https://connect.stripe.test/x"


class TestSchedule:
    def test_manual_is_sent_as_the_documented_v1_settings_path(self):
        client = gateway(FakeResponse(body=account_body()))
        client.set_payout_schedule(account_id="acct_1TESTconnected", interval="manual")
        data = client._session.calls[0]["data"]
        assert data["settings[payouts][schedule][interval]"] == ["manual"]
        assert client._session.calls[0]["method"] == "POST"

    def test_an_unsupported_interval_never_reaches_the_provider(self):
        client = gateway(FakeResponse(body=account_body()))
        with pytest.raises(ProviderError):
            client.set_payout_schedule(account_id="a", interval="instant")
        assert client._session.calls == []


class TestRecoverySearch:
    def _list(self, *entries):
        return FakeResponse(body={"object": "list", "data": list(entries)})

    def test_exactly_one_metadata_match_resolves(self):
        found = gateway(
            self._list(account_body(metadata={"shiptrip_method": "m-1"}))
        ).find_account_by_metadata(key="shiptrip_method", value="m-1", created_gte=1)
        assert found is not None and found.account_id == "acct_1TESTconnected"

    def test_no_match_resolves_to_nothing_rather_than_a_guess(self):
        assert (
            gateway(self._list()).find_account_by_metadata(
                key="shiptrip_method", value="m-1", created_gte=1
            )
            is None
        )

    def test_two_matches_are_a_contradiction_not_a_first_wins(self):
        assert (
            gateway(
                self._list(
                    account_body(id="acct_a", metadata={"shiptrip_method": "m-1"}),
                    account_body(id="acct_b", metadata={"shiptrip_method": "m-1"}),
                )
            ).find_account_by_metadata(
                key="shiptrip_method", value="m-1", created_gte=1
            )
            is None
        )


class TestFailures:
    def test_a_malformed_non_json_response_is_unavailable(self):
        with pytest.raises(ProviderUnavailable):
            gateway(FakeResponse(text="<html>502</html>")).retrieve_account("a")

    def test_a_non_object_json_response_is_unavailable(self):
        with pytest.raises(ProviderUnavailable):
            gateway(FakeResponse(body=["not", "an", "object"])).retrieve_account("a")

    def test_a_4xx_is_a_definite_rejection_carrying_the_provider_code(self):
        with pytest.raises(ProviderCheckoutRejected) as caught:
            gateway(
                FakeResponse(
                    status_code=400,
                    body={"error": {"code": "country_unsupported", "message": "no"}},
                )
            ).create_account(country="FR", idempotency_key="k", metadata={})
        assert caught.value.provider_code == "country_unsupported"

    def test_a_401_is_a_configuration_fact_not_a_transient_one(self):
        with pytest.raises(ProviderNotConfigured):
            gateway(FakeResponse(status_code=401, body={"error": {}})).retrieve_account(
                "a"
            )

    def test_a_5xx_is_retryable(self):
        with pytest.raises(ProviderUnavailable):
            gateway(FakeResponse(status_code=503, body={})).retrieve_account("a")

    def test_a_429_is_retryable(self):
        with pytest.raises(ProviderUnavailable) as caught:
            gateway(FakeResponse(status_code=429, body={})).retrieve_account("a")
        assert caught.value.provider_code == "429"

    def test_a_network_timeout_is_unavailable_not_failed(self):
        with pytest.raises(ProviderUnavailable):
            gateway(requests.Timeout("timed out")).retrieve_account("a")


class TestNoMoneyExecution:
    """The structural guarantee, not a behavioural one.

    H3 owns transfers and bank payouts. Until then the adapter must contain no
    path that could create, reverse or cancel either — asserted against the
    module's own source so a future edit that adds one fails here first.
    """

    SOURCE = Path(
        __import__("apps.finance.providers.stripe_connect", fromlist=["__file__"]).__file__
    ).read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "forbidden",
        [
            "/v1/transfers",
            "/v1/payouts",
            "/reversals",
            "/v1/topups",
            "/v1/balance",
        ],
    )
    def test_no_money_moving_endpoint_appears_in_the_adapter(self, forbidden):
        assert forbidden not in self.SOURCE

    def test_no_method_is_named_after_moving_money(self):
        names = set(re.findall(r"\n    def (\w+)", self.SOURCE))
        assert not {
            name
            for name in names
            if any(word in name for word in ("transfer", "payout_create", "reverse"))
        }
        assert "set_payout_schedule" in names
