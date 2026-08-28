"""Production entrypoint and retired-payment safety checks."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.payments.providers import (
    LegacyPaymentDisabled,
    choose_provider,
    get_provider,
)


MONOLITH = Path(__file__).resolve().parents[3]
BACKEND = MONOLITH.parent
REPO = BACKEND.parent

#: Everything `config.settings.prod` needs to boot, with every payment escape
#: hatch closed. Individual tests open one at a time and assert the refusal.
PROD_BOOT_ENV = {
    "DJANGO_SECRET_KEY": "s" * 48,
    "DJANGO_DEBUG": "false",
    "DJANGO_ALLOWED_HOSTS": "shiptrip.invalid",
    "POSTGRES_DB": "shiptrip",
    "POSTGRES_USER": "shiptrip",
    "POSTGRES_PASSWORD": "test",
    "JWT_HS256_SECRET": "j" * 48,
    "S3_ENDPOINT_URL": "https://storage.invalid",
    "S3_ACCESS_KEY": "test",
    "S3_SECRET_KEY": "test",
    "GRPC_AUTH_MODE": "bearer",
    "GRPC_ALLOW_PRIVATE_BEARER": "true",
    "GRPC_BEARER_TOKEN": "g" * 48,
    "PAYMENTS_PUBLIC_BASE_URL": "https://api.shiptrip.invalid",
    "PAYMENTS_ALLOW_MOCK_PROVIDER": "false",
    "PAYMENTS_MOCK_WEBHOOK_ENABLED": "false",
    "PAYMENTS_LEGACY_MUTATIONS_ENABLED": "false",
    # Phase 4: handover code secrecy has its own key, and production refuses to
    # boot without one that is long enough and distinct from SECRET_KEY.
    "HANDOVER_CODE_SECRET": "h" * 48,
}


#: The real production entrypoint. `django.setup()` would need the module in
#: the environment, which is exactly the crutch these tests exist to remove.
PROD_ENTRYPOINT_BOOT = "from config.wsgi import application"


def boot_production(snippet: str, **overrides: str) -> subprocess.CompletedProcess:
    """Import production settings in a clean interpreter and run `snippet`.

    A subprocess, not `override_settings`: the guards under test are module-level
    `raise` statements that only run when `config.settings.prod` is imported, and
    this process already imported the test settings.
    """

    environment = os.environ.copy()
    environment.pop("DJANGO_SETTINGS_MODULE", None)
    environment.update(PROD_BOOT_ENV)
    environment.update(overrides)
    return subprocess.run(
        [sys.executable, "-c", snippet],
        cwd=MONOLITH,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


class ProductionEntrypointTests(SimpleTestCase):
    def test_default_python_entrypoints_select_production_settings(self):
        for relative in ("manage.py", "config/asgi.py", "config/wsgi.py"):
            source = (MONOLITH / relative).read_text(encoding="utf-8")
            assert '"config.settings.prod"' in source, relative
            assert '"config.settings.dev"' not in source, relative

    def test_every_railway_command_selects_production_settings_explicitly(self):
        for relative in ("railway.web.json", "railway.grpc.json"):
            document = json.loads((MONOLITH / relative).read_text(encoding="utf-8"))
            commands = " ".join(
                str(value)
                for key, value in document["deploy"].items()
                if key.endswith("Command")
            )
            assert "DJANGO_SETTINGS_MODULE=config.settings.prod" in commands
        combined = (BACKEND / "railway" / "start.py").read_text(encoding="utf-8")
        assert 'DJANGO_SETTINGS_MODULE="config.settings.prod"' in combined

    def test_container_images_pin_production_settings(self):
        """The image itself carries the module, not just the start command."""

        for relative in ("backend/monolith/Dockerfile", "backend/railway/Dockerfile"):
            source = (REPO / relative).read_text(encoding="utf-8")
            assert "DJANGO_SETTINGS_MODULE=config.settings.prod" in source, relative
            assert "config.settings.dev" not in source, relative

    def test_wsgi_really_boots_prod_when_the_environment_omits_the_module(self):
        result = boot_production(
            "from config.wsgi import application; "
            "from django.conf import settings; "
            "assert settings.SETTINGS_MODULE == 'config.settings.prod'; "
            "assert not settings.PAYMENTS_ALLOW_MOCK_PROVIDER; "
            "assert not settings.PAYMENTS_LEGACY_MUTATIONS_ENABLED"
        )
        assert result.returncode == 0, result.stderr

    def test_production_refuses_to_boot_with_any_payment_escape_hatch_open(self):
        """Each switch is a boot-time refusal, so a misconfigured deploy never
        serves a single request rather than serving one with a fake rail."""

        for variable in (
            "PAYMENTS_ALLOW_MOCK_PROVIDER",
            "PAYMENTS_MOCK_WEBHOOK_ENABLED",
            "PAYMENTS_LEGACY_MUTATIONS_ENABLED",
        ):
            result = boot_production(
                PROD_ENTRYPOINT_BOOT, **{variable: "true"}
            )
            assert result.returncode != 0, f"{variable} did not stop the boot"
            assert variable in result.stderr, result.stderr

    def test_production_refuses_a_deployment_with_no_public_base_url(self):
        result = boot_production(
            PROD_ENTRYPOINT_BOOT, PAYMENTS_PUBLIC_BASE_URL=""
        )
        assert result.returncode != 0
        assert "PAYMENTS_PUBLIC_BASE_URL" in result.stderr


class LegacyProviderFirewallTests(SimpleTestCase):
    @override_settings(PAYMENTS_LEGACY_MUTATIONS_ENABLED=False)
    def test_legacy_provider_registry_cannot_return_the_mock(self):
        with self.assertRaises(LegacyPaymentDisabled):
            choose_provider("DZD")
        with self.assertRaises(LegacyPaymentDisabled):
            get_provider("mock")


class LegacyMockWebhookFirewallTests(TestCase):
    """The unauthenticated legacy mock webhook must not exist off dev."""

    @override_settings(
        PAYMENTS_MOCK_WEBHOOK_ENABLED=True, PAYMENTS_LEGACY_MUTATIONS_ENABLED=False
    )
    def test_the_legacy_mock_webhook_is_absent_without_the_legacy_switch(self):
        response = self.client.post(
            reverse("payments-webhook-mock"),
            {"provider_intent_id": "anything", "event": "succeeded"},
            content_type="application/json",
        )

        # 404, not 403: an anonymous caller learns nothing about a
        # development-only mutation endpoint that does not serve them.
        assert response.status_code == 404

    @override_settings(
        PAYMENTS_MOCK_WEBHOOK_ENABLED=False, PAYMENTS_LEGACY_MUTATIONS_ENABLED=True
    )
    def test_either_switch_alone_is_enough_to_hide_it(self):
        response = self.client.post(
            reverse("payments-webhook-mock"),
            {"provider_intent_id": "anything", "event": "succeeded"},
            content_type="application/json",
        )

        assert response.status_code == 404


class HandoverSecretBootTests(SimpleTestCase):
    """Production will not start unless parcel handover has its own key.

    Falling back to `SECRET_KEY` would make one rotation event -- or one leaked
    session-signing key -- also a compromise of every pickup and delivery code
    in flight. The refusal is at boot rather than at first use so a
    misconfigured deploy never serves a request, instead of serving them until
    somebody tries to hand over a parcel.
    """

    def test_production_refuses_to_boot_without_a_handover_secret(self):
        result = boot_production(
            "import config.settings.prod", HANDOVER_CODE_SECRET=""
        )
        assert result.returncode != 0
        assert "HANDOVER_CODE_SECRET" in result.stderr

    def test_production_refuses_a_handover_secret_that_is_too_short(self):
        result = boot_production(
            "import config.settings.prod", HANDOVER_CODE_SECRET="short"
        )
        assert result.returncode != 0
        assert "32 characters" in result.stderr

    def test_production_refuses_a_handover_secret_equal_to_the_django_key(self):
        result = boot_production(
            "import config.settings.prod",
            HANDOVER_CODE_SECRET="s" * 48,
        )
        assert result.returncode != 0
        assert "differ from DJANGO_SECRET_KEY" in result.stderr
