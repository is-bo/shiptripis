"""Boot-time refusals and combined-container secret hygiene for H2.

Two questions this file answers.

With the Connect flags off: does the existing production deployment still boot,
with no new secret and no new required configuration? It must, because H2 ships
dormant and a deployment that suddenly demanded a Stripe Connect webhook secret
would take the running service down.

With the flags on: does an incomplete or self-contradicting configuration stop
the boot rather than surfacing at the first Traveler's onboarding attempt?
"""

from __future__ import annotations

import pytest

from config.settings.connect import (
    CONNECT_COUNTRY_CEILING,
    PINNED_CONNECT_API_VERSION,
    ConnectConfigurationError,
    credential_mode,
    validate_connect_configuration,
)
from .test_deployment_safety import PROD_ENTRYPOINT_BOOT, boot_production, load_combined_launcher

BASE = "https://api.shiptrip.invalid"

VALID = dict(
    enabled=True,
    expected_mode="test",
    platform_account_id="acct_1TESTplatform",
    api_version=PINNED_CONNECT_API_VERSION,
    webhook_secret="whsec_connect",
    allowed_countries=["FR"],
    return_url=f"{BASE}/payouts/stripe/return",
    refresh_url=f"{BASE}/payouts/stripe/refresh",
    public_base_url=BASE,
    stripe_secret_key="sk_test_key",
)


def refuse(**overrides):
    with pytest.raises(ConnectConfigurationError) as caught:
        validate_connect_configuration(**{**VALID, **overrides})
    return str(caught.value)


class TestDisabledDeployment:
    def test_the_flag_off_needs_no_connect_secret_or_country(self):
        validate_connect_configuration(
            enabled=False,
            expected_mode="",
            platform_account_id="",
            api_version="",
            webhook_secret="",
            allowed_countries=[],
            return_url="",
            refresh_url="",
            public_base_url="",
            stripe_secret_key="",
        )

    def test_the_country_ceiling_applies_even_with_the_flag_off(self):
        message = refuse(enabled=False, allowed_countries=["US"])
        assert "STRIPE_CONNECT_ALLOWED_COUNTRIES" in message and "US" in message

    def test_payout_execution_flags_may_not_be_on_in_this_release(self):
        assert "STRIPE_CONNECT_PAYOUTS_ENABLED" in refuse(
            enabled=False, payouts_enabled=True
        )
        assert "NON_STRIPE_FUNDING" in refuse(
            enabled=False, non_stripe_funding_enabled=True
        )

    def test_the_architecture_ceiling_is_fr_de_es(self):
        assert CONNECT_COUNTRY_CEILING == ("FR", "DE", "ES")


class TestEnabledDeployment:
    def test_a_complete_test_configuration_is_accepted(self):
        validate_connect_configuration(**VALID)

    def test_a_missing_webhook_secret_stops_the_boot(self):
        assert "STRIPE_CONNECT_WEBHOOK_SECRET" in refuse(webhook_secret="")

    def test_a_secret_that_is_not_a_signing_secret_stops_the_boot(self):
        assert "STRIPE_CONNECT_WEBHOOK_SECRET" in refuse(webhook_secret="sk_test_oops")

    def test_a_missing_platform_account_stops_the_boot(self):
        assert "PLATFORM_ACCOUNT_ID" in refuse(platform_account_id="")

    def test_a_platform_id_that_is_not_an_account_stops_the_boot(self):
        assert "PLATFORM_ACCOUNT_ID" in refuse(platform_account_id="acc_typo")

    def test_an_unpinned_api_version_stops_the_boot(self):
        assert "STRIPE_CONNECT_API_VERSION" in refuse(api_version="")

    def test_a_live_key_under_a_test_expectation_stops_the_boot(self):
        assert "EXPECTED_MODE" in refuse(stripe_secret_key="sk_live_key")

    def test_a_test_key_under_a_live_expectation_stops_the_boot(self):
        assert "EXPECTED_MODE" in refuse(
            expected_mode="live", stripe_secret_key="sk_test_key"
        )

    def test_an_unrecognised_key_shape_stops_the_boot(self):
        assert "EXPECTED_MODE" in refuse(stripe_secret_key="whatever")

    def test_an_invalid_mode_label_stops_the_boot(self):
        assert "EXPECTED_MODE" in refuse(expected_mode="staging")

    def test_a_return_url_on_another_origin_stops_the_boot(self):
        assert "RETURN_URL" in refuse(
            return_url="https://attacker.invalid/payouts/stripe/return"
        )

    def test_an_http_return_url_stops_the_boot(self):
        assert "RETURN_URL" in refuse(return_url="http://api.shiptrip.invalid/x")

    def test_a_return_url_carrying_a_query_stops_the_boot(self):
        assert "RETURN_URL" in refuse(return_url=f"{BASE}/x?next=https://elsewhere")

    def test_identical_return_and_refresh_routes_stop_the_boot(self):
        assert "REFRESH_URL" in refuse(refresh_url=f"{BASE}/payouts/stripe/return")

    def test_a_country_outside_the_ceiling_stops_the_boot(self):
        assert "DZ" in refuse(allowed_countries=["FR", "DZ"])

    @pytest.mark.parametrize(
        "key,mode",
        [
            ("sk_test_x", "test"),
            ("rk_test_x", "test"),
            ("sk_live_x", "live"),
            ("rk_live_x", "live"),
            ("", "not_configured"),
            ("nonsense", "unknown"),
        ],
    )
    def test_the_credential_mode_comes_from_the_documented_prefix(self, key, mode):
        assert credential_mode(key) == mode


class TestProductionBoot:
    """The real settings module, in a clean interpreter."""

    def test_production_still_boots_with_connect_off_and_no_new_secret(self):
        result = boot_production(PROD_ENTRYPOINT_BOOT)
        assert result.returncode == 0, result.stderr

    def test_production_refuses_connect_enabled_without_its_secret(self):
        result = boot_production(
            PROD_ENTRYPOINT_BOOT,
            STRIPE_CONNECT_ENABLED="true",
            STRIPE_CONNECT_PLATFORM_ACCOUNT_ID="acct_1TESTplatform",
            STRIPE_SECRET_KEY="sk_test_x",
            STRIPE_WEBHOOK_SECRET="whsec_x",
        )
        assert result.returncode != 0
        assert "STRIPE_CONNECT_WEBHOOK_SECRET" in result.stderr

    def test_production_refuses_a_mode_mismatch(self):
        result = boot_production(
            PROD_ENTRYPOINT_BOOT,
            STRIPE_CONNECT_ENABLED="true",
            STRIPE_CONNECT_EXPECTED_MODE="test",
            STRIPE_CONNECT_PLATFORM_ACCOUNT_ID="acct_1TESTplatform",
            STRIPE_CONNECT_WEBHOOK_SECRET="whsec_x",
            STRIPE_CONNECT_ONBOARDING_RETURN_URL=f"{BASE}/payouts/stripe/return",
            STRIPE_CONNECT_ONBOARDING_REFRESH_URL=f"{BASE}/payouts/stripe/refresh",
            STRIPE_SECRET_KEY="sk_live_x",
            STRIPE_WEBHOOK_SECRET="whsec_x",
        )
        assert result.returncode != 0
        assert "STRIPE_CONNECT_EXPECTED_MODE" in result.stderr

    def test_production_refuses_payout_execution_being_switched_on(self):
        result = boot_production(
            PROD_ENTRYPOINT_BOOT, STRIPE_CONNECT_PAYOUTS_ENABLED="true"
        )
        assert result.returncode != 0
        assert "STRIPE_CONNECT_PAYOUTS_ENABLED" in result.stderr

    def test_a_complete_test_configuration_boots(self):
        result = boot_production(
            PROD_ENTRYPOINT_BOOT,
            STRIPE_CONNECT_ENABLED="true",
            STRIPE_CONNECT_EXPECTED_MODE="test",
            STRIPE_CONNECT_PLATFORM_ACCOUNT_ID="acct_1TESTplatform",
            STRIPE_CONNECT_WEBHOOK_SECRET="whsec_x",
            STRIPE_CONNECT_ALLOWED_COUNTRIES="FR",
            STRIPE_CONNECT_ONBOARDING_RETURN_URL=f"{BASE}/payouts/stripe/return",
            STRIPE_CONNECT_ONBOARDING_REFRESH_URL=f"{BASE}/payouts/stripe/refresh",
            STRIPE_SECRET_KEY="sk_test_x",
            STRIPE_WEBHOOK_SECRET="whsec_x",
        )
        assert result.returncode == 0, result.stderr


class TestCombinedContainerSecrets:
    """Payment and payout secrets must not reach the Go children."""

    SECRETS = (
        "STRIPE_CONNECT_WEBHOOK_SECRET",
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "PAYOUT_DATA_KEYRING",
        "PAYOUT_ACCOUNT_FINGERPRINT_KEY",
    )

    def _spawn(self, name, environment):
        """Run the real launcher's `spawn` with a fake process factory.

        The filtering under test lives in the deployed file, so the file is
        loaded and called rather than reimplemented; only `Popen` is replaced,
        on this freshly loaded module object, so nothing global is touched.
        """

        import subprocess as real_subprocess
        import types

        launcher = load_combined_launcher()
        captured = {}

        class FakeProcess:
            pid = 1234

            def poll(self):
                return None

        def fake_popen(command, *, cwd, env, start_new_session):
            captured["env"] = env
            return FakeProcess()

        launcher.subprocess = types.SimpleNamespace(
            Popen=fake_popen,
            TimeoutExpired=real_subprocess.TimeoutExpired,
            run=real_subprocess.run,
        )
        launcher.CHILDREN.clear()
        launcher.spawn(name, ["/bin/true"], env=dict(environment))
        return captured["env"]

    @pytest.mark.parametrize(
        "child", ["chat", "notification", "kyc", "email", "gateway"]
    )
    def test_no_go_child_inherits_a_payment_or_payout_secret(self, child):
        environment = {name: "secret-value" for name in self.SECRETS}
        environment["REDIS_URL"] = "redis://127.0.0.1:6379/0"
        env = self._spawn(child, environment)
        for name in self.SECRETS:
            assert name not in env, f"{child} inherited {name}"
        assert env["REDIS_URL"] == "redis://127.0.0.1:6379/0"

    @pytest.mark.parametrize("child", ["django-web", "finance-jobs", "django-grpc"])
    def test_djangos_own_children_keep_what_django_needs(self, child):
        environment = {name: "secret-value" for name in self.SECRETS}
        env = self._spawn(child, environment)
        for name in self.SECRETS:
            assert env[name] == "secret-value"

    def test_the_fcm_credential_path_handling_is_untouched(self):
        launcher = load_combined_launcher()
        assert launcher.FCM_CREDENTIALS_ENV == "FCM_CREDENTIALS_JSON_BASE64"
        environment = {
            "FCM_CREDENTIALS_PATH": "/tmp/shiptrip/firebase-admin.json",
            "STRIPE_CONNECT_WEBHOOK_SECRET": "whsec_x",
        }
        env = self._spawn("notification", environment)
        assert env["FCM_CREDENTIALS_PATH"] == "/tmp/shiptrip/firebase-admin.json"
        assert "STRIPE_CONNECT_WEBHOOK_SECRET" not in env
