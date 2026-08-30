"""API surface: authorization, server authority, and provider availability.

Two things are being defended. First, object-level authorization on every
financial read and write — an order belongs to its owner, a payout to its
traveler, and neither leaks to the counterparty or a stranger. Second, that the
client is a renderer, not a calculator: it picks a rail and the server decides
every number.
"""

from __future__ import annotations

import json
from copy import deepcopy

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.business_settings import get_active_business_settings
from apps.core.models import BusinessSettingsVersion
from apps.finance.models import PaymentAttempt, PaymentOrder, Payout
from apps.finance.providers import (
    ProviderError,
    ProviderNotConfigured,
    available_providers,
    get_gateway,
    mock_allowed,
    resolve_gateway_for_checkout,
)
from apps.finance.policy import Phase3Policy, phase3_policy

from .factories import build_scenario, pay_order_with_mock


def _enable_mock():
    settings_version = get_active_business_settings()
    policy = deepcopy(settings_version.policy)
    policy["payments"]["providers"]["mock_enabled"] = True
    BusinessSettingsVersion.objects.filter(pk=settings_version.pk).update(policy=policy)


class FinanceApiTestCase(TestCase):
    def setUp(self):
        _enable_mock()
        self.scenario = build_scenario(prefix="api")
        self.scenario.accept(reward_eur_cents=3_200)
        self.order = self.scenario.balance_order()
        self.reference = str(self.order.public_reference)

    def client_for(self, user) -> APIClient:
        client = APIClient()
        client.force_authenticate(user=user)
        return client


class OrderAuthorizationTests(FinanceApiTestCase):
    def test_the_owner_sees_their_own_order_in_full(self):
        response = self.client_for(self.scenario.sender).get(
            reverse("finance-order-detail", args=[self.reference])
        )

        assert response.status_code == 200, response.data
        assert response.data["outstanding_eur_cents"] == (
            self.order.outstanding_eur_cents
        )
        assert "attempts" in response.data

    def test_a_stranger_cannot_read_the_order(self):
        response = self.client_for(self.scenario.outsider).get(
            reverse("finance-order-detail", args=[self.reference])
        )

        assert response.status_code == 403
        assert response.data["code"] == "not_authorized"

    def test_the_traveler_cannot_read_the_senders_payment_order(self):
        response = self.client_for(self.scenario.traveler).get(
            reverse("finance-order-detail", args=[self.reference])
        )

        assert response.status_code == 403

    def test_an_anonymous_caller_cannot_read_an_order(self):
        response = APIClient().get(
            reverse("finance-order-detail", args=[self.reference])
        )

        assert response.status_code in (401, 403)

    def test_the_order_list_only_shows_my_own_obligations(self):
        other = build_scenario(prefix="api-other")
        other.accept()

        response = self.client_for(self.scenario.sender).get(reverse("finance-orders"))

        assert response.status_code == 200
        references = {row["public_reference"] for row in response.data}
        assert str(other.balance_order().public_reference) not in references

    def test_a_stranger_cannot_open_a_checkout_on_someone_elses_order(self):
        response = self.client_for(self.scenario.outsider).post(
            reverse("finance-order-checkout", args=[self.reference]),
            {"provider": "mock"},
            format="json",
        )

        assert response.status_code == 403
        assert PaymentAttempt.objects.filter(order=self.order).count() == 0

    def test_no_provider_secrets_or_internal_keys_are_serialized(self):
        pay_order_with_mock(self.client, self.order)
        response = self.client_for(self.scenario.sender).get(
            reverse("finance-order-detail", args=[self.reference])
        )
        body = json.dumps(response.data, default=str)

        for forbidden in (
            "idempotency_key",
            "provider_session_id",
            "token_hash",
            "webhook_secret",
            "secret_key",
            "terms_snapshot",
        ):
            assert forbidden not in body, forbidden


class DealPaymentVisibilityTests(FinanceApiTestCase):
    def test_the_sender_sees_the_full_balance_state(self):
        response = self.client_for(self.scenario.sender).get(
            reverse("finance-deal-payment", args=[self.scenario.deal.pk])
        )

        assert response.status_code == 200, response.data
        assert response.data["sender_total_eur_cents"] == int(
            self.scenario.deal.terms.sender_total_minor
        )
        assert response.data["order"]["outstanding_eur_cents"] > 0
        assert "attempts" in response.data["order"]

    def test_the_traveler_learns_only_whether_it_is_funded(self):
        response = self.client_for(self.scenario.traveler).get(
            reverse("finance-deal-payment", args=[self.scenario.deal.pk])
        )

        assert response.status_code == 200, response.data
        assert set(response.data["order"]) == {"status", "outstanding_eur_cents"}
        assert "attempts" not in response.data["order"]

    def test_a_stranger_cannot_read_a_deal_payment(self):
        response = self.client_for(self.scenario.outsider).get(
            reverse("finance-deal-payment", args=[self.scenario.deal.pk])
        )

        assert response.status_code == 403


class ServerAuthorityTests(FinanceApiTestCase):
    """The client may pick a rail. It may not pick a number."""

    def test_a_client_supplied_amount_is_rejected_not_ignored(self):
        response = self.client_for(self.scenario.sender).post(
            reverse("finance-order-checkout", args=[self.reference]),
            {"provider": "mock", "amount_eur_cents": 1},
            format="json",
        )

        assert response.status_code == 400
        detail = response.data
        assert "client_supplied_amount_rejected" in json.dumps(detail, default=str)
        assert PaymentAttempt.objects.filter(order=self.order).count() == 0

    def test_a_client_supplied_fx_rate_is_rejected(self):
        response = self.client_for(self.scenario.sender).post(
            reverse("finance-order-checkout", args=[self.reference]),
            {"provider": "mock", "eur_dzd_rate": "1.0"},
            format="json",
        )

        assert response.status_code == 400

    def test_a_client_supplied_currency_is_rejected(self):
        response = self.client_for(self.scenario.sender).post(
            reverse("finance-order-checkout", args=[self.reference]),
            {"provider": "mock", "currency": "USD"},
            format="json",
        )

        assert response.status_code == 400

    def test_the_checkout_charges_the_server_calculated_outstanding(self):
        response = self.client_for(self.scenario.sender).post(
            reverse("finance-order-checkout", args=[self.reference]),
            {"provider": "mock"},
            format="json",
        )

        assert response.status_code == 201, response.data
        attempt = PaymentAttempt.objects.get(order=self.order)
        assert int(attempt.amount_eur_cents) == self.order.outstanding_eur_cents

    def test_repeating_a_checkout_reuses_the_open_attempt(self):
        client = self.client_for(self.scenario.sender)
        url = reverse("finance-order-checkout", args=[self.reference])

        first = client.post(url, {"provider": "mock"}, format="json")
        second = client.post(url, {"provider": "mock"}, format="json")

        assert first.status_code == 201
        assert second.status_code == 200
        assert first.data["id"] == second.data["id"]
        assert PaymentAttempt.objects.filter(order=self.order).count() == 1

    def test_a_covered_order_refuses_a_further_checkout(self):
        pay_order_with_mock(self.client, self.order)

        response = self.client_for(self.scenario.sender).post(
            reverse("finance-order-checkout", args=[self.reference]),
            {"provider": "mock"},
            format="json",
        )

        assert response.status_code == 409
        assert response.data["code"] in {
            "order_not_collectable",
            "nothing_outstanding",
        }


class ProviderAvailabilityTests(FinanceApiTestCase):
    def test_availability_is_server_authoritative(self):
        response = self.client_for(self.scenario.sender).get(
            reverse("finance-providers")
        )

        assert response.status_code == 200
        rows = {row["provider"]: row for row in response.data["providers"]}
        assert set(rows) == {"stripe", "chargily", "mock"}
        assert response.data["timing_mode"] == "posting_deposit"
        assert response.data["canonical_currency"] == "EUR"

    @override_settings(STRIPE_SECRET_KEY="", STRIPE_WEBHOOK_SECRET="")
    def test_an_unconfigured_provider_is_reported_unavailable(self):
        settings_version = get_active_business_settings()
        policy = deepcopy(settings_version.policy)
        policy["payments"]["providers"]["stripe_enabled"] = True
        BusinessSettingsVersion.objects.filter(pk=settings_version.pk).update(
            policy=policy
        )
        response = self.client_for(self.scenario.sender).get(
            reverse("finance-providers")
        )

        stripe_row = next(
            row for row in response.data["providers"] if row["provider"] == "stripe"
        )
        assert stripe_row["available"] is False
        assert stripe_row["unavailable_reason"] == "provider_not_configured"

    @override_settings(STRIPE_SECRET_KEY="", STRIPE_WEBHOOK_SECRET="")
    def test_an_unconfigured_provider_never_falls_back_to_mock(self):
        settings_version = get_active_business_settings()
        policy_dict = deepcopy(settings_version.policy)
        policy_dict["payments"]["providers"]["stripe_enabled"] = True
        settings_version.policy = policy_dict
        policy = Phase3Policy.from_settings(settings_version)

        with self.assertRaises(ProviderNotConfigured):
            resolve_gateway_for_checkout(policy, "stripe")

    def test_a_disabled_provider_is_reported_with_a_reason(self):
        settings_version = get_active_business_settings()
        policy_dict = deepcopy(settings_version.policy)
        policy_dict["payments"]["providers"]["chargily_enabled"] = False
        settings_version.policy = policy_dict
        rows = {
            row.provider: row
            for row in available_providers(Phase3Policy.from_settings(settings_version))
        }

        assert rows["chargily"].as_dict()["available"] is False
        assert rows["chargily"].unavailable_reason == "disabled_by_policy"


class MockProviderProductionSafetyTests(TestCase):
    """MOCK must be impossible to use as a production payment rail."""

    def test_the_test_settings_opt_in_is_what_makes_mock_reachable(self):
        assert mock_allowed() is True

    @override_settings(PAYMENTS_ALLOW_MOCK_PROVIDER=False)
    def test_without_the_opt_in_the_registry_refuses_to_build_it(self):
        assert mock_allowed() is False
        with self.assertRaises(ProviderNotConfigured):
            get_gateway("mock")

    @override_settings(PAYMENTS_ALLOW_MOCK_PROVIDER=False)
    def test_without_the_opt_in_a_mock_checkout_is_refused(self):
        """Business policy asking for mock is not enough; the deployment wins."""

        _enable_mock()
        policy = phase3_policy()
        assert policy.providers.mock_enabled is True

        with self.assertRaises(ProviderError) as caught:
            resolve_gateway_for_checkout(policy, "mock")

        # Refused, with a named reason. Never silently substituted.
        assert caught.exception.code in {
            "provider_disabled",
            "provider_not_configured",
        }

    @override_settings(PAYMENTS_ALLOW_MOCK_PROVIDER=False)
    def test_without_the_opt_in_the_mock_webhook_endpoint_moves_no_money(self):
        response = self.client.post(
            reverse("finance-webhook-mock"),
            data=b'{"id":"evt_x","outcome":"succeeded"}',
            content_type="application/json",
            HTTP_X_MOCK_SIGNATURE="deadbeef",
        )

        assert response.status_code == 503
        assert response.json()["code"] == "provider_not_configured"

    @override_settings(PAYMENTS_ALLOW_MOCK_PROVIDER=False)
    def test_mock_is_not_advertised_when_the_deployment_forbids_it(self):
        _enable_mock()
        rows = {row.provider: row for row in available_providers(phase3_policy())}

        assert rows["mock"].as_dict()["available"] is False

    def test_the_production_settings_module_refuses_the_mock_opt_in(self):
        """A deployment that enables mock does not start at all."""

        source = (
            __import__("pathlib")
            .Path(__file__)
            .resolve()
            .parents[3]
            .joinpath("config", "settings", "prod.py")
            .read_text(encoding="utf-8")
        )

        assert "PAYMENTS_ALLOW_MOCK_PROVIDER" in source
        assert "raise RuntimeError" in source
        assert "PAYMENTS_MOCK_WEBHOOK_ENABLED" in source
        assert "PAYMENTS_LEGACY_MUTATIONS_ENABLED" in source

    def test_a_signed_mock_webhook_is_still_rejected_without_the_flag(self):
        """Even a correctly signed event cannot move money when mock is off."""

        from apps.finance.providers.mock import sign_mock_webhook

        body = b'{"id":"evt_y","outcome":"succeeded","data":{}}'
        with override_settings(PAYMENTS_ALLOW_MOCK_PROVIDER=False):
            response = self.client.post(
                reverse("finance-webhook-mock"),
                data=body,
                content_type="application/json",
                HTTP_X_MOCK_SIGNATURE=sign_mock_webhook(body),
            )

        assert response.status_code == 503


class PayoutVisibilityTests(FinanceApiTestCase):
    def setUp(self):
        super().setUp()
        pay_order_with_mock(self.client, self.order)
        self.payout = Payout.objects.get(deal=self.scenario.deal)

    def test_a_traveler_sees_their_own_payout_state(self):
        response = self.client_for(self.scenario.traveler).get(
            reverse("finance-payouts")
        )

        assert response.status_code == 200
        assert len(response.data) == 1
        row = response.data[0]
        assert row["status"] == "not_eligible"
        assert row["amount_eur_cents"] == int(self.payout.amount_eur_cents)

    def test_the_sender_does_not_see_the_travelers_payout(self):
        response = self.client_for(self.scenario.sender).get(reverse("finance-payouts"))

        assert response.status_code == 200
        assert response.data == []

    def test_the_payout_payload_hides_operational_internals(self):
        response = self.client_for(self.scenario.traveler).get(
            reverse("finance-payouts")
        )
        body = json.dumps(response.data, default=str)

        for forbidden in ("admin_actor", "notes", "provider_payout_id", "receipt_url"):
            assert forbidden not in body, forbidden

    def test_only_staff_may_reach_the_manual_settlement_route(self):
        for user in (
            self.scenario.sender,
            self.scenario.traveler,
            self.scenario.outsider,
        ):
            response = self.client_for(user).post(
                reverse("finance-admin-payout-complete", args=[self.payout.pk]),
                {
                    "payout_currency": "EUR",
                    "payout_amount_minor": 100,
                    "reference": "X",
                },
                format="json",
            )
            assert response.status_code == 403, user

    def test_only_staff_may_reach_the_refund_route(self):
        response = self.client_for(self.scenario.sender).post(
            reverse("finance-admin-refund", args=[self.reference]),
            {"attempt_id": 1, "amount_eur_cents": 1, "reason": "admin"},
            format="json",
        )

        assert response.status_code == 403


class PostingDepositApiTests(TestCase):
    def setUp(self):
        _enable_mock()
        self.scenario = build_scenario(prefix="api-deposit", open_request=False)

    def client_for(self, user) -> APIClient:
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_the_sender_sees_a_server_calculated_quote(self):
        response = self.client_for(self.scenario.sender).get(
            reverse("finance-posting-deposit", args=[self.scenario.delivery_request.pk])
        )

        assert response.status_code == 200, response.data
        assert response.data["deposit_required"] is True
        assert response.data["quote"]["currency"] == "EUR"
        assert 300 <= response.data["quote"]["amount_eur_cents"] <= 700

    def test_a_stranger_cannot_see_another_senders_deposit(self):
        response = self.client_for(self.scenario.outsider).get(
            reverse("finance-posting-deposit", args=[self.scenario.delivery_request.pk])
        )

        assert response.status_code == 403

    def test_creating_the_deposit_order_is_idempotent_over_http(self):
        url = reverse(
            "finance-posting-deposit", args=[self.scenario.delivery_request.pk]
        )
        client = self.client_for(self.scenario.sender)

        first = client.post(url)
        second = client.post(url)

        assert first.status_code == 201
        assert second.status_code == 201
        assert first.data["public_reference"] == second.data["public_reference"]
        assert (
            PaymentOrder.objects.filter(
                delivery_request=self.scenario.delivery_request
            ).count()
            == 1
        )
