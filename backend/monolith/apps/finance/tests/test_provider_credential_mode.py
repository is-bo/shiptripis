"""Which rail a deployment is armed against, without reading a secret.

"Configured", "enabled" and "test or live" are three different facts, and a
pre-launch operator has to be able to check all three. The first two were
already reported. The third was only knowable by reading the key itself, which
is the one thing nobody should have to do to answer it — so the gateways derive
it from the credential's documented *shape* and report a word.

The property under test is that the derivation is conservative: it says `live`
only when the credential unambiguously says live, and `unknown` — never `test`
— whenever it cannot tell. A wrong `test` is how a live rail gets transacted
against by accident.
"""

from __future__ import annotations

from dataclasses import replace

from django.test import TestCase, override_settings

from apps.finance.providers import (
    MODE_LIVE,
    MODE_NOT_CONFIGURED,
    MODE_TEST,
    MODE_UNKNOWN,
    MockGateway,
    availability,
)
from apps.finance.providers.chargily import (
    LIVE_API_BASE,
    TEST_API_BASE,
    ChargilyGateway,
)
from apps.finance.providers.stripe import StripeGateway
from apps.finance.policy import phase3_policy


class StripeCredentialModeTests(TestCase):
    def test_the_documented_prefixes_are_recognised(self):
        for key, expected in (
            ("sk_test_51abcdef", MODE_TEST),
            ("rk_test_51abcdef", MODE_TEST),
            ("sk_live_51abcdef", MODE_LIVE),
            ("rk_live_51abcdef", MODE_LIVE),
        ):
            with self.subTest(key=key[:8]):
                gateway = StripeGateway(secret_key=key, webhook_secret="whsec_x")
                assert gateway.credential_mode() == expected

    def test_an_unrecognised_or_absent_key_never_reports_test(self):
        assert (
            StripeGateway(secret_key="", webhook_secret="").credential_mode()
            == MODE_NOT_CONFIGURED
        )
        assert (
            StripeGateway(
                secret_key="something_else_entirely", webhook_secret="whsec_x"
            ).credential_mode()
            == MODE_UNKNOWN
        )

    def test_the_mode_never_carries_the_key(self):
        key = "sk_live_51_this_must_not_appear"
        mode = StripeGateway(secret_key=key, webhook_secret="whsec_x").credential_mode()

        assert mode == MODE_LIVE
        assert key not in mode


class ChargilyCredentialModeTests(TestCase):
    def test_key_and_api_base_must_agree(self):
        assert (
            ChargilyGateway(
                secret_key="test_sk_abc", api_base=TEST_API_BASE
            ).credential_mode()
            == MODE_TEST
        )
        assert (
            ChargilyGateway(
                secret_key="live_sk_abc", api_base=LIVE_API_BASE
            ).credential_mode()
            == MODE_LIVE
        )

    def test_a_mixed_environment_is_unknown_rather_than_guessed(self):
        # A live key against the test base (or the reverse) is a deployment
        # mistake. Reporting either half of it as the answer would hide it.
        assert (
            ChargilyGateway(
                secret_key="live_sk_abc", api_base=TEST_API_BASE
            ).credential_mode()
            == MODE_UNKNOWN
        )
        assert (
            ChargilyGateway(
                secret_key="test_sk_abc", api_base=LIVE_API_BASE
            ).credential_mode()
            == MODE_UNKNOWN
        )
        assert (
            ChargilyGateway(
                secret_key="test_sk_abc", api_base="https://proxy.invalid/api/v2"
            ).credential_mode()
            == MODE_UNKNOWN
        )

    def test_an_absent_key_is_not_configured(self):
        assert (
            ChargilyGateway(secret_key="", api_base=LIVE_API_BASE).credential_mode()
            == MODE_NOT_CONFIGURED
        )


class MockCredentialModeTests(TestCase):
    def test_the_mock_rail_is_always_test(self):
        assert MockGateway().credential_mode() == MODE_TEST


class OperatorViewTests(TestCase):
    """Enablement and configuration stay separate facts in the operator view."""

    @staticmethod
    def _policy(**provider_flags):
        """The active seeded policy with only the provider switches changed."""

        policy = phase3_policy()
        return replace(
            policy, providers=replace(policy.providers, **provider_flags)
        )

    @override_settings(
        STRIPE_SECRET_KEY="sk_live_abc",
        STRIPE_WEBHOOK_SECRET="whsec_abc",
        PAYMENTS_ALLOW_MOCK_PROVIDER=False,
    )
    def test_a_configured_live_rail_that_is_switched_off_says_so(self):
        policy = self._policy(stripe_enabled=False)

        row = availability(policy, "stripe").as_operator_dict()

        assert row["configured"] is True
        assert row["credential_mode"] == MODE_LIVE
        assert row["enabled"] is False
        assert row["available"] is False
        assert row["unavailable_reason"] == "disabled_by_policy"

    @override_settings(STRIPE_SECRET_KEY="", STRIPE_WEBHOOK_SECRET="")
    def test_an_enabled_but_unconfigured_rail_is_not_available(self):
        policy = self._policy(stripe_enabled=True)

        row = availability(policy, "stripe").as_operator_dict()

        assert row["enabled"] is True
        assert row["configured"] is False
        assert row["credential_mode"] == MODE_NOT_CONFIGURED
        assert row["available"] is False

    @override_settings(STRIPE_SECRET_KEY="sk_live_abc", STRIPE_WEBHOOK_SECRET="whsec_x")
    def test_the_payer_contract_does_not_gain_operational_fields(self):
        # `as_dict` is what reaches a payer. An operational fact added here
        # must not follow it into a checkout response.
        policy = self._policy(stripe_enabled=True)

        payer = availability(policy, "stripe").as_dict()

        assert "credential_mode" not in payer
        assert "enabled" not in payer
        assert "configured" not in payer
