"""Chargily: EUR stays canonical, DZD is a settlement representation.

The load-bearing property here is immutability. A Chargily attempt snapshots
the EUR amount, the DZD amount and the exact rate at the moment of checkout.
Changing the admin rate afterwards must be invisible to that payment forever —
its reconciliation, its refund and its reporting all read its own row.

The second property is that disabling Chargily stops *new* checkouts without
stranding money already in flight.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from copy import deepcopy

from django.test import TestCase
from django.urls import reverse

from apps.core.business_settings import get_active_business_settings
from apps.core.models import BusinessSettingsVersion
from apps.finance.models import PaymentAttempt, PaymentOrder
from apps.finance.money import convert_eur_cents, format_rate
from apps.finance.policy import Phase3Policy
from apps.finance.providers import (
    NewCheckoutsDisabled,
    ProviderDisabled,
    resolve_gateway_for_checkout,
)
from apps.finance.providers.base import (
    CheckoutRequest,
    ProviderError,
    ProviderNotConfigured,
    ProviderSignatureError,
    RefundRequest,
)
from apps.finance.providers.chargily import (
    ChargilyGateway,
    verify_chargily_signature,
)
from apps.finance.services import chargily_display, start_checkout

from .factories import build_scenario, pay_order_with_mock
from .test_stripe import _FakeResponse, _FakeSession

SECRET = "test_sk_chargily_secret"


def chargily_signature(body: bytes, *, secret: str = SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _gateway(responses=None) -> ChargilyGateway:
    return ChargilyGateway(
        secret_key=SECRET,
        webhook_secret=SECRET,
        api_base="https://pay.chargily.test/test/api/v2",
        session=_FakeSession(responses or []),
    )


class ChargilySignatureTests(TestCase):
    body = b'{"id":"evt_1","type":"checkout.paid"}'

    def test_a_correct_signature_passes(self):
        verify_chargily_signature(
            raw_body=self.body,
            signature_header=chargily_signature(self.body),
            secret=SECRET,
        )

    def test_a_tampered_body_is_rejected(self):
        with self.assertRaises(ProviderSignatureError):
            verify_chargily_signature(
                raw_body=self.body + b" ",
                signature_header=chargily_signature(self.body),
                secret=SECRET,
            )

    def test_the_wrong_secret_is_rejected(self):
        with self.assertRaises(ProviderSignatureError):
            verify_chargily_signature(
                raw_body=self.body,
                signature_header=chargily_signature(self.body, secret="other"),
                secret=SECRET,
            )

    def test_a_missing_signature_is_rejected(self):
        with self.assertRaises(ProviderSignatureError):
            verify_chargily_signature(
                raw_body=self.body, signature_header="", secret=SECRET
            )

    def test_a_non_ascii_signature_is_a_signature_failure_not_a_crash(self):
        with self.assertRaises(ProviderSignatureError):
            verify_chargily_signature(
                raw_body=self.body,
                signature_header="café",
                secret=SECRET,
            )

    def test_a_non_hex_signature_is_refused(self):
        for bogus in ("!!!", "zz" * 32, "a" * 300):
            with self.assertRaises(ProviderSignatureError):
                verify_chargily_signature(
                    raw_body=self.body, signature_header=bogus, secret=SECRET
                )

    def test_an_unconfigured_secret_refuses_rather_than_accepts(self):
        with self.assertRaises(ProviderNotConfigured):
            verify_chargily_signature(
                raw_body=self.body,
                signature_header=chargily_signature(self.body),
                secret="",
            )


class ChargilyCheckoutTests(TestCase):
    def _request(self, **overrides) -> CheckoutRequest:
        base = {
            "reference": "ref-9",
            "amount_minor": 9_375,
            "currency": "DZD",
            "amount_exponent": 0,
            "idempotency_key": "shiptrip-order-9-x",
            "success_url": "https://shiptrip.test/ok",
            "failure_url": "https://shiptrip.test/no",
            "webhook_url": "https://shiptrip.test/api/payments/webhooks/chargily",
            "description": "ShipTrip delivery payment",
            "metadata": {"order_reference": "ref-9"},
        }
        base.update(overrides)
        return CheckoutRequest(**base)

    def test_the_checkout_charges_exactly_the_amount_the_server_computed(self):
        gateway = _gateway(
            [
                _FakeResponse(
                    200,
                    {
                        "id": "01checkout",
                        "checkout_url": "https://pay.chargily.test/01checkout",
                        "status": "pending",
                    },
                )
            ]
        )

        result = gateway.create_checkout(self._request())

        call = gateway._session.calls[0]
        payload = json.loads(call["data"])
        assert call["url"].endswith("/checkouts")
        assert call["headers"]["Authorization"] == f"Bearer {SECRET}"
        assert payload["amount"] == 9_375
        assert payload["currency"] == "dzd"
        assert payload["success_url"] == "https://shiptrip.test/ok"
        assert payload["webhook_endpoint"].endswith("/webhooks/chargily")
        assert payload["metadata"] == [{"reference": "ref-9"}]
        assert result.provider_session_id == "01checkout"

    def test_a_eur_checkout_is_refused_rather_than_converted_by_the_adapter(self):
        with self.assertRaises(ProviderError):
            _gateway().create_checkout(self._request(currency="EUR"))

    def test_refunds_are_refused_rather_than_faked(self):
        """Chargily Pay v2 has no refund API; pretending otherwise would lie."""

        from apps.finance.providers.base import RefundNotSupported

        with self.assertRaises(RefundNotSupported) as caught:
            _gateway().refund(
                RefundRequest(
                    provider_payment_id="01checkout",
                    provider_session_id="01checkout",
                    amount_minor=9_375,
                    currency="DZD",
                    idempotency_key="k",
                )
            )

        # A distinct type, not a string the caller has to match on.
        assert caught.exception.code == "refund_not_supported"
        assert isinstance(caught.exception, ProviderError)

    def test_a_paid_event_is_a_success_and_carries_our_reference(self):
        body = json.dumps(
            {
                "id": "evt_paid",
                "type": "checkout.paid",
                "data": {
                    "id": "01checkout",
                    "status": "paid",
                    "amount": 9_375,
                    "currency": "dzd",
                    "metadata": [{"reference": "ref-9"}],
                },
            },
            separators=(",", ":"),
        ).encode("utf-8")

        event = _gateway().parse_webhook(
            raw_body=body, headers={"signature": chargily_signature(body)}
        )

        assert event.outcome == "succeeded"
        assert event.provider_session_id == "01checkout"
        assert event.amount_minor == 9_375
        assert event.currency == "DZD"
        assert event.reference == "ref-9"

    def test_a_paid_label_over_an_unpaid_object_is_not_trusted(self):
        body = json.dumps(
            {
                "id": "evt_lying",
                "type": "checkout.paid",
                "data": {"id": "01checkout", "status": "pending"},
            },
            separators=(",", ":"),
        ).encode("utf-8")

        event = _gateway().parse_webhook(
            raw_body=body, headers={"signature": chargily_signature(body)}
        )

        assert event.outcome == "ignored"

    def test_failure_cancellation_and_expiry_map_to_distinct_outcomes(self):
        for event_type, expected in (
            ("checkout.failed", "failed"),
            ("checkout.canceled", "cancelled"),
            ("checkout.expired", "expired"),
        ):
            body = json.dumps(
                {"id": f"evt_{event_type}", "type": event_type, "data": {"id": "c1"}},
                separators=(",", ":"),
            ).encode("utf-8")

            event = _gateway().parse_webhook(
                raw_body=body, headers={"signature": chargily_signature(body)}
            )

            assert event.outcome == expected, event_type


class ChargilyFxSnapshotTests(TestCase):
    """The rate an attempt used is frozen on that attempt, forever."""

    def setUp(self):
        settings_version = get_active_business_settings()
        policy = deepcopy(settings_version.policy)
        policy["payments"]["providers"]["mock_enabled"] = True
        BusinessSettingsVersion.objects.filter(pk=settings_version.pk).update(
            policy=policy
        )
        self.scenario = build_scenario(prefix="fx")
        self.scenario.accept(reward_eur_cents=3_200)
        self.order = self.scenario.balance_order()

    def _policy_at_rate(self, rate_micros: int) -> Phase3Policy:
        settings_version = get_active_business_settings()
        policy = deepcopy(settings_version.policy)
        policy["payments"]["chargily"]["eur_dzd_rate_micros"] = rate_micros
        settings_version.policy = policy
        return Phase3Policy.from_settings(settings_version)

    def test_the_display_figures_are_all_server_calculated(self):
        display = chargily_display(
            amount_eur_cents=6_250, policy=self._policy_at_rate(150_000_000)
        )

        assert display["canonical_currency"] == "EUR"
        assert display["canonical_amount_eur_cents"] == 6_250
        assert display["payment_currency"] == "DZD"
        assert display["payment_amount_dzd"] == 9_375
        assert display["eur_dzd_rate"] == "150"

    def test_an_attempt_snapshots_the_eur_amount_dzd_amount_and_rate(self):
        gateway_responses = [
            _FakeResponse(
                200,
                {
                    "id": "chk_A",
                    "checkout_url": "https://pay.chargily.test/chk_A",
                    "status": "pending",
                },
            )
        ]
        attempt = self._checkout(150_000_000, gateway_responses)

        expected_dzd = convert_eur_cents(
            self.order.outstanding_eur_cents,
            to_currency="DZD",
            rate_micros=150_000_000,
        )
        assert attempt.payment_currency == "DZD"
        assert attempt.amount_eur_cents == self.order.outstanding_eur_cents
        assert attempt.provider_amount_minor == expected_dzd
        assert attempt.provider_amount_exponent == 0
        assert attempt.fx_rate_micros == 150_000_000
        assert attempt.fx_settings_version_id is not None
        assert attempt.fx_snapshot_at is not None
        assert "eur_dzd_rate_micros" in attempt.fx_source

    def test_changing_the_admin_rate_does_not_change_an_existing_payment(self):
        """Payment A at rate X; admin moves to Y; A still reads X."""

        first = self._checkout(
            150_000_000,
            [
                _FakeResponse(
                    200,
                    {
                        "id": "chk_A",
                        "checkout_url": "https://pay.chargily.test/chk_A",
                        "status": "pending",
                    },
                )
            ],
        )
        first_rate = first.fx_rate_micros
        first_amount = first.provider_amount_minor

        # An operator publishes a new rate.
        settings_version = get_active_business_settings()
        policy = deepcopy(settings_version.policy)
        policy["payments"]["chargily"]["eur_dzd_rate_micros"] = 200_000_000
        BusinessSettingsVersion.objects.filter(pk=settings_version.pk).update(
            policy=policy
        )

        first.refresh_from_db()
        assert first.fx_rate_micros == first_rate == 150_000_000
        assert first.provider_amount_minor == first_amount

        # A new attempt on a fresh order picks up the new rate.
        other = build_scenario(prefix="fx-second")
        other.accept(reward_eur_cents=3_200)
        second = self._checkout(
            200_000_000,
            [
                _FakeResponse(
                    200,
                    {
                        "id": "chk_B",
                        "checkout_url": "https://pay.chargily.test/chk_B",
                        "status": "pending",
                    },
                )
            ],
            order=other.balance_order(),
        )

        assert second.fx_rate_micros == 200_000_000
        assert second.provider_amount_minor > first_amount
        first.refresh_from_db()
        assert first.fx_rate_micros == 150_000_000

    def test_a_refund_uses_the_attempts_own_rate_not_todays(self):
        from apps.finance.services import _refund_provider_amount
        from apps.finance.models import PaymentRefund

        attempt = self._checkout(
            150_000_000,
            [
                _FakeResponse(
                    200,
                    {
                        "id": "chk_C",
                        "checkout_url": "https://pay.chargily.test/chk_C",
                        "status": "pending",
                    },
                )
            ],
        )
        refund = PaymentRefund(
            order=self.order,
            attempt=attempt,
            amount_eur_cents=attempt.amount_eur_cents,
            provider="chargily",
            idempotency_key="k",
            reason=PaymentRefund.Reason.ADMIN,
        )

        # A full refund returns exactly the dinars that were charged.
        assert _refund_provider_amount(refund, attempt) == attempt.provider_amount_minor

        # A partial refund converts at the attempt's frozen rate, not today's.
        refund.amount_eur_cents = attempt.amount_eur_cents // 2
        assert _refund_provider_amount(refund, attempt) == convert_eur_cents(
            refund.amount_eur_cents, to_currency="DZD", rate_micros=150_000_000
        )

    def _checkout(self, rate_micros, responses, order: PaymentOrder | None = None):
        from unittest.mock import patch

        order = order or self.order
        gateway = ChargilyGateway(
            secret_key=SECRET,
            webhook_secret=SECRET,
            api_base="https://pay.chargily.test/test/api/v2",
            session=_FakeSession(responses),
        )
        with patch(
            "apps.finance.services.resolve_gateway_for_checkout", return_value=gateway
        ):
            session = start_checkout(
                order_id=order.pk,
                provider="chargily",
                actor_id=order.owner_id,
                policy=self._policy_at_rate(rate_micros),
            )
        return session.attempt


class ChargilyAvailabilityTests(TestCase):
    """Disabling Chargily must not strand money already in flight."""

    def setUp(self):
        self.settings_version = get_active_business_settings()

    def _policy(self, mutate) -> Phase3Policy:
        settings_version = get_active_business_settings()
        policy = deepcopy(settings_version.policy)
        mutate(policy)
        settings_version.policy = policy
        return Phase3Policy.from_settings(settings_version)

    def test_disabling_new_checkouts_refuses_a_new_checkout(self):
        policy = self._policy(
            lambda p: p["payments"]["chargily"].__setitem__(
                "new_checkouts_enabled", False
            )
        )

        with self.assertRaises(NewCheckoutsDisabled):
            resolve_gateway_for_checkout(policy, "chargily")

    def test_disabling_the_provider_entirely_refuses_a_new_checkout(self):
        policy = self._policy(
            lambda p: p["payments"]["providers"].__setitem__(
                "chargily_enabled", False
            )
        )

        with self.assertRaises(ProviderDisabled):
            resolve_gateway_for_checkout(policy, "chargily")

    def test_webhook_processing_never_consults_business_availability(self):
        """A disabled provider still reconciles money that already exists."""

        from apps.finance.providers import get_gateway

        # `get_gateway` is what the webhook path uses; it takes no policy at all.
        gateway = get_gateway("chargily")
        assert gateway.name == "chargily"

        body = json.dumps(
            {
                "id": "evt_after_disable",
                "type": "checkout.paid",
                "data": {"id": "c9", "status": "paid", "amount": 100, "currency": "dzd"},
            },
            separators=(",", ":"),
        ).encode("utf-8")
        parsed = ChargilyGateway(
            secret_key=SECRET, webhook_secret=SECRET, session=_FakeSession([])
        ).parse_webhook(
            raw_body=body, headers={"signature": chargily_signature(body)}
        )

        assert parsed.outcome == "succeeded"

    def test_an_unconfigured_chargily_is_reported_unavailable_not_substituted(self):
        from apps.finance.providers import availability

        policy = self._policy(lambda p: p)
        with self.settings(CHARGILY_SECRET_KEY=""):
            row = availability(policy, "chargily")

        assert row.configured is False
        assert row.as_dict()["available"] is False
        assert row.unavailable_reason == "provider_not_configured"


class ChargilyFundingPayoutTests(TestCase):
    """A Chargily customer payment does not imply a Chargily traveler payout."""

    def setUp(self):
        settings_version = get_active_business_settings()
        policy = deepcopy(settings_version.policy)
        policy["payments"]["providers"]["mock_enabled"] = True
        BusinessSettingsVersion.objects.filter(pk=settings_version.pk).update(
            policy=policy
        )
        self.scenario = build_scenario(prefix="chg-payout")

    def test_a_chargily_funded_deal_enters_the_manual_payout_queue(self):
        from apps.finance.models import Payout

        self.scenario.accept(reward_eur_cents=3_200)
        order = self.scenario.balance_order()
        attempt = pay_order_with_mock(self.client, order)
        PaymentAttempt.objects.filter(pk=attempt.pk).update(provider="chargily")

        payout = Payout.objects.get(deal=self.scenario.deal)

        assert payout.method == Payout.Method.MANUAL
        assert payout.status == Payout.Status.NOT_ELIGIBLE
        assert payout.amount_eur_cents == int(
            self.scenario.deal.terms.traveler_reward_minor
        )


class ChargilyRateDisplayTests(TestCase):
    def test_the_rate_is_rendered_exactly_from_its_stored_micros(self):
        assert format_rate(150_250_000) == "150.25"
        assert format_rate(1_000_000) == "1"

    def test_the_provider_list_publishes_the_active_rate(self):
        from rest_framework.test import APIClient

        scenario = build_scenario(prefix="rate-display")
        client = APIClient()
        client.force_authenticate(user=scenario.sender)
        response = client.get(reverse("finance-providers"))

        assert response.status_code == 200, response.content
        body = json.loads(response.content)
        assert body["canonical_currency"] == "EUR"
        assert "chargily_rate" in body
