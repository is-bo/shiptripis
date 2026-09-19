"""Production entrypoint and retired-payment safety checks."""

from __future__ import annotations

import base64
import fnmatch
import importlib.util
import json
import os
import runpy
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

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
    "SHIPTRIP_ENVIRONMENT": "production",
    "DJANGO_SECRET_KEY": "s" * 48,
    "DJANGO_DEBUG": "false",
    "DJANGO_ALLOWED_HOSTS": "shiptrip.invalid",
    "POSTGRES_DB": "shiptrip",
    "POSTGRES_USER": "shiptrip",
    "POSTGRES_PASSWORD": "test",
    "POSTGRES_HOST": "db.invalid",
    "REDIS_URL": "redis://redis.invalid:6379/0",
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
    "TRANSACTIONAL_EMAIL_SECRET": "e" * 48,
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


def load_combined_launcher():
    """Load `backend/railway/start.py`'s definitions without running it.

    The launcher is a script, not an importable package module, and everything
    below the definitions is guarded by `__main__`. Executing it by path keeps
    these assertions on the real deployed file rather than on a copy.
    """

    name = "shiptrip_combined_launcher"
    spec = importlib.util.spec_from_file_location(
        name, BACKEND / "railway" / "start.py"
    )
    module = importlib.util.module_from_spec(spec)
    # `@dataclass` resolves string annotations through `sys.modules`, so the
    # module has to be registered before it executes.
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module


SERVICE_ACCOUNT_FIXTURE = {
    "type": "service_account",
    "project_id": "shiptrip-test",
    "private_key_id": "0" * 40,
    "private_key": "not-a-real-private-key",
    "client_email": "firebase-adminsdk@shiptrip-test.iam.gserviceaccount.com",
}


class FirebaseAdminCredentialInstallTests(SimpleTestCase):
    """The Railway secret store holds a string; the worker wants a file.

    These cover the seam that turns one into the other, because a mistake here
    either leaks a private key into a child process's environment or silently
    arms push against the wrong Firebase project.
    """

    def setUp(self):
        self.launcher = load_combined_launcher()
        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.directory, True)
        self.path = self.directory / "firebase-admin.json"

    def encoded(self, document=None):
        payload = json.dumps(document or SERVICE_ACCOUNT_FIXTURE).encode("utf-8")
        return base64.b64encode(payload).decode("ascii")

    def test_absent_variable_leaves_push_configuration_untouched(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.launcher.install_fcm_credentials()
            assert "FCM_CREDENTIALS_PATH" not in os.environ

    def test_credential_lands_privately_and_the_payload_leaves_the_environment(self):
        environment = {
            "FCM_CREDENTIALS_JSON_BASE64": self.encoded(),
            "FCM_CREDENTIALS_PATH": str(self.path),
            "FCM_PROJECT_ID": "shiptrip-test",
        }
        with mock.patch.dict(os.environ, environment, clear=True):
            self.launcher.install_fcm_credentials()
            # The base64 payload must not survive into any `child_env()` copy.
            assert "FCM_CREDENTIALS_JSON_BASE64" not in os.environ
            assert os.environ["FCM_CREDENTIALS_PATH"] == str(self.path)
            assert self.launcher.child_env().get("FCM_CREDENTIALS_JSON_BASE64") is None
        assert json.loads(self.path.read_text(encoding="utf-8")) == (
            SERVICE_ACCOUNT_FIXTURE
        )
        if os.name == "posix":
            assert stat.S_IMODE(self.path.stat().st_mode) == 0o600

    def test_default_path_is_used_when_the_deployment_names_none(self):
        environment = {
            "FCM_CREDENTIALS_JSON_BASE64": self.encoded(),
            "FCM_CREDENTIALS_PATH": "",
        }
        written = self.directory / "default" / "firebase-admin.json"
        with mock.patch.dict(os.environ, environment, clear=True):
            with mock.patch.object(
                self.launcher, "FCM_CREDENTIALS_DEFAULT_PATH", str(written)
            ):
                self.launcher.install_fcm_credentials()
            assert os.environ["FCM_CREDENTIALS_PATH"] == str(written)
        assert written.exists()

    def test_a_credential_for_another_firebase_project_is_refused(self):
        environment = {
            "FCM_CREDENTIALS_JSON_BASE64": self.encoded(),
            "FCM_CREDENTIALS_PATH": str(self.path),
            "FCM_PROJECT_ID": "some-other-project",
        }
        with mock.patch.dict(os.environ, environment, clear=True):
            with self.assertRaises(RuntimeError):
                self.launcher.install_fcm_credentials()
        assert not self.path.exists()

    def test_malformed_credentials_fail_without_echoing_the_payload(self):
        secret = "s3cr3t-private-key-material"
        cases = {
            "not base64": base64.b64encode(secret.encode("utf-8")).decode("ascii")[:-1]
            + "!",
            "not json": base64.b64encode(secret.encode("utf-8")).decode("ascii"),
            "wrong type": self.encoded({"type": "authorized_user", "secret": secret}),
            "no project": self.encoded({"type": "service_account", "secret": secret}),
        }
        for label, encoded in cases.items():
            with self.subTest(case=label):
                environment = {
                    "FCM_CREDENTIALS_JSON_BASE64": encoded,
                    "FCM_CREDENTIALS_PATH": str(self.path),
                }
                with mock.patch.dict(os.environ, environment, clear=True):
                    with self.assertRaises(RuntimeError) as caught:
                        self.launcher.install_fcm_credentials()
                assert secret not in str(caught.exception)
                assert not self.path.exists()


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

    def test_public_railway_entrypoints_gate_traffic_on_readiness(self):
        for path in (
            REPO / "railway.json",
            BACKEND / "gateway" / "railway.json",
            MONOLITH / "railway.web.json",
        ):
            document = json.loads(path.read_text(encoding="utf-8"))
            assert document["deploy"]["healthcheckPath"] == "/readyz", path

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

    def test_production_refuses_a_nonproduction_environment_label(self):
        result = boot_production(
            PROD_ENTRYPOINT_BOOT, SHIPTRIP_ENVIRONMENT="development"
        )
        assert result.returncode != 0
        assert "SHIPTRIP_ENVIRONMENT" in result.stderr

    def test_production_refuses_debug(self):
        result = boot_production(PROD_ENTRYPOINT_BOOT, DJANGO_DEBUG="true")
        assert result.returncode != 0
        assert "DJANGO_DEBUG" in result.stderr

    def test_production_refuses_a_deployment_with_no_public_base_url(self):
        result = boot_production(
            PROD_ENTRYPOINT_BOOT, PAYMENTS_PUBLIC_BASE_URL=""
        )
        assert result.returncode != 0
        assert "PAYMENTS_PUBLIC_BASE_URL" in result.stderr

    def test_production_refuses_a_public_base_url_with_a_path(self):
        result = boot_production(
            PROD_ENTRYPOINT_BOOT,
            PAYMENTS_PUBLIC_BASE_URL="https://api.shiptrip.invalid/not-an-origin",
        )
        assert result.returncode != 0
        assert "PAYMENTS_PUBLIC_BASE_URL" in result.stderr

    def test_production_refuses_credentials_in_public_origins(self):
        for variable, value in (
            (
                "PAYMENTS_PUBLIC_BASE_URL",
                "https://operator:password@api.shiptrip.invalid",
            ),
            (
                "CORS_ALLOWED_ORIGINS",
                "https://operator:password@web.shiptrip.invalid",
            ),
        ):
            result = boot_production(PROD_ENTRYPOINT_BOOT, **{variable: value})
            assert result.returncode != 0
            assert variable in result.stderr

        result = boot_production(
            PROD_ENTRYPOINT_BOOT,
            S3_ENDPOINT_URL="https://storage.invalid?access_token=do-not-embed",
        )
        assert result.returncode != 0
        assert "S3_ENDPOINT_URL" in result.stderr

    def test_production_requires_explicit_well_formed_allowed_hosts(self):
        for value in (
            "*",
            ".shiptrip.invalid",
            "https://api.shiptrip.invalid",
            "api.shiptrip.invalid:443",
        ):
            result = boot_production(
                PROD_ENTRYPOINT_BOOT, DJANGO_ALLOWED_HOSTS=value
            )
            assert result.returncode != 0
            assert "DJANGO_ALLOWED_HOSTS" in result.stderr

    def test_production_refuses_missing_core_infrastructure(self):
        for variable in (
            "POSTGRES_DB",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
            "POSTGRES_HOST",
            "REDIS_URL",
            "S3_ENDPOINT_URL",
            "S3_ACCESS_KEY",
            "S3_SECRET_KEY",
            "TRANSACTIONAL_EMAIL_SECRET",
        ):
            result = boot_production(PROD_ENTRYPOINT_BOOT, **{variable: ""})
            assert result.returncode != 0, f"{variable} did not stop the boot"
            assert variable in result.stderr

    def test_production_refuses_invalid_redis_urls(self):
        for value in ("http://redis.invalid", "redis://", "not-a-url"):
            result = boot_production(PROD_ENTRYPOINT_BOOT, REDIS_URL=value)
            assert result.returncode != 0
            assert "REDIS_URL" in result.stderr

    def test_production_refuses_insecure_or_malformed_storage_urls(self):
        for value in (
            "http://storage.invalid",
            "https://storage.invalid:bad-port",
            "not-a-url",
        ):
            result = boot_production(PROD_ENTRYPOINT_BOOT, S3_ENDPOINT_URL=value)
            assert result.returncode != 0
            assert "S3_ENDPOINT_URL" in result.stderr

    def test_production_refuses_weak_or_reused_secrets(self):
        cases = (
            ({"DJANGO_SECRET_KEY": "short"}, "DJANGO_SECRET_KEY"),
            ({"DJANGO_SECRET_KEY": "insecure-production-secret-that-is-long"}, "DJANGO_SECRET_KEY"),
            ({"JWT_HS256_SECRET": "short"}, "JWT_HS256_SECRET"),
            ({"JWT_HS256_SECRET": "s" * 48}, "JWT_HS256_SECRET"),
            ({"TRANSACTIONAL_EMAIL_SECRET": "short"}, "TRANSACTIONAL_EMAIL_SECRET"),
            ({"TRANSACTIONAL_EMAIL_SECRET": "s" * 48}, "TRANSACTIONAL_EMAIL_SECRET"),
            ({"TRANSACTIONAL_EMAIL_SECRET": "j" * 48}, "TRANSACTIONAL_EMAIL_SECRET"),
            ({"GRPC_BEARER_TOKEN": "short"}, "GRPC_BEARER_TOKEN"),
            ({"GRPC_BEARER_TOKEN": "s" * 48}, "GRPC_BEARER_TOKEN"),
        )
        for overrides, variable in cases:
            result = boot_production(PROD_ENTRYPOINT_BOOT, **overrides)
            assert result.returncode != 0, f"{variable} did not stop the boot"
            assert variable in result.stderr

    def test_production_request_formatter_redacts_concrete_capability_paths(self):
        result = boot_production(
            "import logging; "
            "from types import SimpleNamespace; "
            "from config.settings.prod import _JsonFormatter; "
            "record = logging.LogRecord('django.request', logging.ERROR, '', 0, "
            "'failed /api/payments/guest/do-not-log-this', (), None); "
            "record.request = SimpleNamespace(resolver_match=SimpleNamespace("
            "route='api/payments/guest/<str:token>')); "
            "record.status_code = 500; "
            "output = _JsonFormatter().format(record); "
            "assert 'do-not-log-this' not in output; "
            "assert '<str:token>' in output"
        )
        assert result.returncode == 0, result.stderr

    def test_production_refuses_unsafe_origins(self):
        for variable, value in (
            ("CORS_ALLOWED_ORIGINS", "*"),
            ("CSRF_TRUSTED_ORIGINS", "http://admin.shiptrip.invalid"),
        ):
            result = boot_production(PROD_ENTRYPOINT_BOOT, **{variable: value})
            assert result.returncode != 0
            assert variable in result.stderr


class CombinedLauncherGeographyTests(SimpleTestCase):
    """The catalogue import in the boot sequence, and where it must sit.

    The active V1 write contract refuses a request or a journey without a
    canonical Place, so the release ships the reviewed catalogue and applies it
    on first boot. Two properties keep that from being a liability, and both are
    positional rather than behavioural — which is exactly the kind of thing a
    later edit moves without noticing.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.launcher = (BACKEND / "railway" / "start.py").read_text(encoding="utf-8")

    def test_the_import_is_guarded_so_a_restart_is_not_a_reimport(self):
        assert '"import_geography"' in self.launcher
        assert '"--skip-if-current"' in self.launcher
        # No `--deactivate-missing` on the boot path: a boot must never be able
        # to retire catalogue rows that a running deployment is matching on.
        assert "--deactivate-missing" not in self.launcher

    def test_the_import_runs_after_readiness_not_before_it(self):
        ready = self.launcher.index('print("ShipTrip is ready"')
        applied = self.launcher.index("apply_geography_catalogue(base_env)")
        gateway = self.launcher.index('wait_for_port(gateway')

        # A first import takes minutes. Ahead of the gateway it would fail the
        # platform health check and roll the deployment back.
        assert gateway < ready < applied

    def test_the_catalogue_actually_reaches_the_image(self):
        from apps.locations.management.commands.import_geography import (
            BUNDLED_MANIFEST,
        )

        assert BUNDLED_MANIFEST.exists()
        # A `.dockerignore` pattern that excluded the artefact would fail only
        # in production, as an empty catalogue — the one failure mode the local
        # suite cannot otherwise see.
        relative = BUNDLED_MANIFEST.relative_to(REPO).as_posix()
        for ignore in (REPO / ".dockerignore", MONOLITH / ".dockerignore"):
            for line in ignore.read_text(encoding="utf-8").splitlines():
                pattern = line.strip()
                if not pattern or pattern.startswith("#") or pattern.startswith("!"):
                    continue
                assert not fnmatch.fnmatch(relative, pattern.rstrip("/") + "*"), (
                    f"{ignore.name} pattern {pattern!r} would drop the catalogue"
                )
                assert not fnmatch.fnmatch(
                    BUNDLED_MANIFEST.name, pattern
                ), f"{ignore.name} pattern {pattern!r} would drop the catalogue"

    def test_a_failed_import_does_not_take_the_service_down(self):
        body = self.launcher[
            self.launcher.index("def apply_geography_catalogue") : self.launcher.index(
                "def run() -> int:"
            )
        ]
        # Serving without a catalogue is degraded; refusing to serve is worse.
        assert "check=True" not in body
        assert "FAILED" in body
        assert "raise" not in body


class CombinedLauncherKycLimiterTests(SimpleTestCase):
    def _kyc_env(self) -> dict[str, str]:
        launcher = runpy.run_path(str(BACKEND / "railway" / "start.py"))
        return launcher["kyc_env"]()

    def test_combined_launcher_requires_external_shared_kyc_redis(self):
        for value in (
            "",
            "not-a-url",
            "https://cache.invalid",
            "redis://127.0.0.1:6379/0",
            "redis://localhost:6379/0",
            "redis://cache.invalid:bad-port/0",
        ):
            with self.subTest(value=value), mock.patch.dict(
                os.environ,
                {"KYC_RATE_LIMIT_REDIS_URL": value},
                clear=True,
            ):
                with self.assertRaisesRegex(RuntimeError, "KYC_RATE_LIMIT_REDIS_URL"):
                    self._kyc_env()

    def test_combined_launcher_maps_only_shared_redis_into_kyc(self):
        shared_url = "rediss://user:secret@shared-cache.invalid:6380/4"
        with mock.patch.dict(
            os.environ,
            {
                "REDIS_URL": "redis://127.0.0.1:6379/0",
                "KYC_RATE_LIMIT_REDIS_URL": shared_url,
                "KYC_S3_ACCESS_KEY": "kyc-only-access-key",
            },
            clear=True,
        ):
            env = self._kyc_env()

        assert env["REDIS_URL"] == shared_url
        assert env["S3_ACCESS_KEY"] == "kyc-only-access-key"
        assert env["KYC_HTTP_ADDR"] == "127.0.0.1:8083"

    def test_combined_launcher_allows_explicit_single_replica_local_mode(self):
        with mock.patch.dict(
            os.environ,
            {"KYC_RATE_LIMIT_LOCAL_MODE": "true"},
            clear=True,
        ):
            env = self._kyc_env()

        assert env["REDIS_URL"] == "redis://127.0.0.1:6379/0"

    def test_combined_launcher_rejects_local_mode_with_external_url(self):
        with mock.patch.dict(
            os.environ,
            {
                "KYC_RATE_LIMIT_LOCAL_MODE": "true",
                "KYC_RATE_LIMIT_REDIS_URL": "rediss://cache.invalid:6380/0",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "LOCAL_MODE"):
                self._kyc_env()


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


class PublicEdgeRoutingTests(SimpleTestCase):
    """The canonical public legal URLs must resolve cleanly at the edge."""

    def test_caddyfiles_define_clean_legal_rewrites(self):
        caddyfiles = [
            REPO / "backend" / "railway" / "Caddyfile",
            REPO / "backend" / "gateway" / "Caddyfile",
        ]
        for caddyfile in caddyfiles:
            assert caddyfile.exists(), f"Missing {caddyfile}"
            text = caddyfile.read_text(encoding="utf-8")
            assert "/terms" in text
            assert "/privacy" in text
            assert "rewrite /terms /terms.html" in text
            assert "rewrite /privacy /privacy.html" in text

    def test_legal_documents_exist_with_valid_titles(self):
        terms = REPO / "web" / "terms.html"
        privacy = REPO / "web" / "privacy.html"
        assert terms.exists()
        assert privacy.exists()
        assert "Terms of Service" in terms.read_text(encoding="utf-8")
        assert "Privacy Policy" in privacy.read_text(encoding="utf-8")

    def test_public_matcher_does_not_shadow_protected_routes(self):
        import re
        caddyfile = REPO / "backend" / "railway" / "Caddyfile"
        text = caddyfile.read_text(encoding="utf-8")
        match = re.search(r"@public\s+path\s+([^\n]+)", text)
        assert match is not None
        public_paths = match.group(1).split()
        for protected in ("/api", "/admin", "/pay", "/payouts", "/healthz", "/readyz", "/ws", "/kyc"):
            assert not any(p.startswith(protected) for p in public_paths)
