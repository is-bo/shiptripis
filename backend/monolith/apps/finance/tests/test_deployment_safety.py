"""Production entrypoint and retired-payment safety checks."""

from __future__ import annotations

import base64
import fnmatch
import importlib.util
import json
import os
import re
import runpy
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase


MONOLITH = Path(__file__).resolve().parents[3]
BACKEND = MONOLITH.parent
REPO = BACKEND.parent
VPS = REPO / "infra" / "vps"
#: The process launcher the VPS application image runs (`runtime.py serve`).
LAUNCHER = VPS / "launcher.py"

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
    # Phase 4: handover code secrecy has its own key, and production refuses to
    # boot without one that is long enough and distinct from SECRET_KEY.
    "HANDOVER_CODE_SECRET": "h" * 48,
    "TRANSACTIONAL_EMAIL_SECRET": "e" * 48,
    # L14: staff two-step keys are sealed with the payout keyring, so
    # production refuses to start without a valid one.
    "PAYOUT_DATA_KEYRING": '{"k1": "' + base64.b64encode(b"k" * 32).decode() + '"}',
    "PAYOUT_DATA_ACTIVE_KEY_ID": "k1",
    "PAYOUT_ACCOUNT_FINGERPRINT_KEY": base64.b64encode(b"f" * 32).decode(),
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
    """Load `infra/vps/launcher.py`'s definitions without running it.

    The launcher is a script, not an importable package module, and everything
    below the definitions is guarded by `__main__`. Executing it by path keeps
    these assertions on the real deployed file rather than on a copy.
    """

    name = "shiptrip_combined_launcher"
    spec = importlib.util.spec_from_file_location(name, LAUNCHER)
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
    """The mounted secret document holds a string; the worker wants a file.

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

    def test_the_launcher_selects_production_settings_explicitly(self):
        combined = LAUNCHER.read_text(encoding="utf-8")
        assert 'DJANGO_SETTINGS_MODULE="config.settings.prod"' in combined

    def test_the_vps_container_lets_the_launcher_drain_before_sigkill(self):
        """Docker SIGKILLs a container `stop_grace_period` after SIGTERM, so
        that window must outlast the launcher's own child drain."""

        compose = (VPS / "compose.yml").read_text(encoding="utf-8")
        anchor = compose[: compose.index("\nservices:")]
        grace = re.search(r"^  stop_grace_period: (\d+)s$", anchor, re.MULTILINE)
        assert grace is not None, "the application anchor sets no stop_grace_period"
        launcher = load_combined_launcher()
        assert int(grace.group(1)) > launcher.CHILD_STOP_TIMEOUT_SECONDS

    def test_email_send_budget_fits_inside_the_child_stop_window(self):
        """The email worker detaches each SMTP send from shutdown so it is not
        cut mid-DATA; that send (plus its 3s ack) must finish inside both the
        Go service's own 15s drain and the launcher's SIGKILL window, or a
        deploy turns an accepted email into an unacked duplicate."""

        source = (
            BACKEND / "services" / "internal" / "email" / "consumer.go"
        ).read_text(encoding="utf-8")
        send = int(re.search(r"\bsendTimeout = (\d+) \* time\.Second", source).group(1))
        ack = int(re.search(r"\backTimeout = (\d+) \* time\.Second", source).group(1))
        launcher = load_combined_launcher()
        assert send + ack <= 15
        assert send + ack < launcher.CHILD_STOP_TIMEOUT_SECONDS

    def test_production_bounds_django_smtp_and_logs_access_safely(self):
        """A stalled SMTP relay must not wedge the finance worker's loop, and
        the access/ops loggers must reach the production JSON handler."""

        result = boot_production(
            "from config.wsgi import application; "
            "from django.conf import settings; "
            "assert 0 < settings.EMAIL_TIMEOUT <= 60, settings.EMAIL_TIMEOUT; "
            "assert settings.PERFORMANCE_ACCESS_LOG_ENABLED; "
            "loggers = settings.LOGGING['loggers']; "
            "assert loggers['shiptrip.access']['level'] == 'INFO'; "
            "assert loggers['shiptrip.ops']['level'] == 'INFO'"
        )
        assert result.returncode == 0, result.stderr

    def test_no_gunicorn_access_log_writes_concrete_paths(self):
        """Gunicorn's request line carries guest payment capabilities; the
        middleware's route-template `http_request` line is the access log."""

        launcher = LAUNCHER.read_text(encoding="utf-8")
        assert "--access-logfile" not in launcher
        assert "--access-logformat" not in launcher

    def test_container_images_pin_production_settings(self):
        """The image itself carries the module, not just the start command."""

        for relative in ("backend/monolith/Dockerfile", "infra/vps/Dockerfile"):
            source = (REPO / relative).read_text(encoding="utf-8")
            assert "DJANGO_SETTINGS_MODULE=config.settings.prod" in source, relative
            assert "config.settings.dev" not in source, relative

    def test_wsgi_really_boots_prod_when_the_environment_omits_the_module(self):
        result = boot_production(
            "from config.wsgi import application; "
            "from django.conf import settings; "
            "assert settings.SETTINGS_MODULE == 'config.settings.prod'; "
            "assert not settings.PAYMENTS_ALLOW_MOCK_PROVIDER"
        )
        assert result.returncode == 0, result.stderr

    def test_production_refuses_to_boot_with_the_mock_payment_rail_open(self):
        """A boot-time refusal, so a misconfigured deploy never serves a single
        request rather than serving one with a fake rail.

        L1A removed the legacy DZD webhook and mutation switches together with
        the only code that read them; the mock rail is the one hatch left.
        """

        result = boot_production(
            PROD_ENTRYPOINT_BOOT, PAYMENTS_ALLOW_MOCK_PROVIDER="true"
        )
        assert result.returncode != 0, "the mock rail did not stop the boot"
        assert "PAYMENTS_ALLOW_MOCK_PROVIDER" in result.stderr, result.stderr

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

    def test_production_route_cache_uses_the_same_shared_redis(self):
        result = boot_production(
            "import config.settings.prod as settings; "
            "assert settings.CACHES['default']['LOCATION'] == settings.REDIS_URL; "
            "assert settings.CACHES['routing']['LOCATION'] == settings.REDIS_URL; "
            "assert settings.CACHES['default']['OPTIONS']['socket_timeout'] == 1; "
            "assert settings.CACHES['routing']['OPTIONS']['socket_connect_timeout'] == 1"
        )
        assert result.returncode == 0, result.stderr

        result = boot_production(
            PROD_ENTRYPOINT_BOOT,
            ROUTE_PROVIDER_CACHE_URL="redis://other-cache.invalid:6379/0",
        )
        assert result.returncode != 0
        assert "ROUTE_PROVIDER_CACHE_URL" in result.stderr

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


class GeographyCatalogueShippingTests(SimpleTestCase):
    """The reviewed catalogue ships inside the application image.

    The active V1 write contract refuses a request or a journey without a
    canonical Place, and the VPS applies the bundled catalogue as an explicit
    maintenance operation (`runtime.py maintenance import_geography`). A
    `.dockerignore` pattern that excluded the artefact would fail only in
    production, as an empty catalogue.
    """

    def test_the_catalogue_actually_reaches_the_image(self):
        from apps.locations.management.commands.import_geography import (
            BUNDLED_MANIFEST,
        )

        assert BUNDLED_MANIFEST.exists()
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

    def test_starting_the_container_never_migrates_or_imports(self):
        launcher = LAUNCHER.read_text(encoding="utf-8")
        assert '"migrate"' not in launcher
        assert "import_geography" not in launcher
        runtime = (VPS / "runtime.py").read_text(encoding="utf-8")
        assert '"import_geography"' in runtime  # the explicit maintenance path


class CombinedLauncherReliabilityTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.launcher = runpy.run_path(str(LAUNCHER))

    def test_the_launcher_requires_the_shared_redis(self):
        for value in (
            "",
            "not-a-url",
            "https://cache.invalid",
            "redis://127.0.0.1:6379/0",
            "redis://localhost:6379/0",
            "redis://localhost.:6379/0",
            "redis://localhost.localdomain:6379/0",
            "redis://cache.invalid:bad-port/0",
            "redis://user:password@[bad/0",
        ):
            with self.subTest(value=value), mock.patch.dict(
                os.environ, {"REDIS_URL": value}, clear=True
            ):
                with self.assertRaisesRegex(RuntimeError, "REDIS_URL"):
                    self.launcher["shared_redis_url"]()

    def test_every_child_receives_the_same_external_redis(self):
        shared_url = "rediss://user:secret@shared-cache.invalid:6380/4"
        with mock.patch.dict(
            os.environ,
            {"REDIS_URL": shared_url, "KYC_S3_ACCESS_KEY": "kyc-only-access-key"},
            clear=True,
        ):
            redis_url = self.launcher["shared_redis_url"]()
            env = self.launcher["kyc_env"](redis_url)

        assert redis_url == shared_url
        assert env["REDIS_URL"] == shared_url
        assert env["S3_ACCESS_KEY"] == "kyc-only-access-key"
        assert env["KYC_HTTP_ADDR"] == "127.0.0.1:8083"

    def test_no_redis_daemon_is_started_inside_the_container(self):
        source = LAUNCHER.read_text(encoding="utf-8")
        assert "redis-server" not in source
        assert "SHIPTRIP_EMBEDDED_REDIS" not in source

    def shared_redis(self, *, policy="noeviction", appendonly="yes", save="60 1"):
        import redis

        client = mock.MagicMock()
        values = {
            "maxmemory-policy": policy,
            "maxmemory": "0",
            "appendonly": appendonly,
            "appendfsync": "everysec",
            "save": save,
        }

        def config_get(name):
            if values[name] is None:
                raise redis.ResponseError("unknown command 'CONFIG'")
            return {name: values[name]}

        client.config_get.side_effect = config_get
        return client

    def probe(self, client, **kwargs):
        stdout, stderr = mock.MagicMock(), mock.MagicMock()
        with mock.patch("redis.Redis.from_url", return_value=client), mock.patch(
            "sys.stdout", stdout
        ), mock.patch("sys.stderr", stderr):
            try:
                self.launcher["probe_shared_redis"](
                    "redis://default:do-not-print@redis.internal.invalid:6379", **kwargs
                )
            finally:
                printed = "".join(
                    str(call.args[0])
                    for stream in (stdout, stderr)
                    for call in stream.write.call_args_list
                )
        return printed

    def test_shared_redis_is_proven_before_anything_depends_on_it(self):
        source = LAUNCHER.read_text(encoding="utf-8")
        probe = source.index("probe_shared_redis(redis_url)")
        assert source.index("redis_url = shared_redis_url()") < probe
        assert probe < source.index('print("collecting static files"')

    def test_unreachable_shared_redis_fails_startup_without_leaking_the_url(self):
        import redis

        client = self.shared_redis()
        client.ping.side_effect = redis.ConnectionError("connection refused")
        with self.assertRaisesRegex(RuntimeError, "unreachable") as raised:
            self.probe(client, timeout=0)
        assert "redis.internal.invalid:6379" in str(raised.exception)
        assert "do-not-print" not in str(raised.exception)
        client.close.assert_called_once()

    def test_rejected_credentials_fail_immediately(self):
        import redis

        client = self.shared_redis()
        client.ping.side_effect = redis.AuthenticationError("WRONGPASS")
        with self.assertRaisesRegex(RuntimeError, "credentials"):
            self.probe(client, timeout=60)
        assert client.ping.call_count == 1

    def test_an_evicting_policy_fails_startup(self):
        with self.assertRaisesRegex(RuntimeError, "allkeys-lru"):
            self.probe(self.shared_redis(policy="allkeys-lru"))

    def test_a_durable_instance_is_accepted_and_reported(self):
        printed = self.probe(self.shared_redis(policy="noeviction"))
        assert "maxmemory-policy=noeviction" in printed
        assert "appendonly=yes" in printed
        assert "WARNING" not in printed
        assert "do-not-print" not in printed

    def test_volatile_policies_cannot_touch_ttl_less_streams(self):
        printed = self.probe(self.shared_redis(policy="volatile-lru"))
        assert "maxmemory-policy=volatile-lru" in printed

    def test_missing_persistence_or_hidden_config_is_loud_not_fatal(self):
        printed = self.probe(self.shared_redis(appendonly="no", save=""))
        assert "no AOF and no RDB" in printed

        printed = self.probe(
            self.shared_redis(policy=None, appendonly=None, save=None)
        )
        assert "maxmemory-policy=unverifiable" in printed
        assert "hides its configuration" in printed

    def test_a_timeout_while_reading_config_fails_cleanly(self):
        """PING succeeded, then CONFIG GET timed out: a named RuntimeError,
        not a raw traceback, and never the password-bearing URL."""

        import redis

        for error in (
            redis.TimeoutError("Timeout reading from redis.internal.invalid"),
            redis.ConnectionError("Connection reset by peer"),
        ):
            with self.subTest(error=type(error).__name__):
                client = self.shared_redis()
                client.config_get.side_effect = error
                with self.assertRaisesRegex(RuntimeError, "stopped answering") as raised:
                    self.probe(client)
                assert "redis.internal.invalid:6379" in str(raised.exception)
                assert "do-not-print" not in str(raised.exception)
                client.close.assert_called_once()

    def test_default_combined_database_budget_is_rolling_deploy_safe(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            budget = self.launcher["connection_budget"]()

        assert budget == {
            "web_workers": 2,
            "web_threads": 2,
            "grpc_workers": 4,
            "chat_max": 5,
            "notif_max": 5,
            "email_max": 2,
            "steady_min": 11,
            "steady_peak": 22,
            "rolling_peak": 44,
        }

    def test_pool_and_concurrency_values_are_bounded(self):
        for name, value in (
            ("WEB_CONCURRENCY", "0"),
            ("WEB_THREADS", "9"),
            ("CHAT_DB_MAX_CONNS", "100"),
            ("EMAIL_DB_MAX_CONNS", "not-an-int"),
        ):
            with self.subTest(name=name), mock.patch.dict(
                os.environ, {name: value}, clear=True
            ):
                with self.assertRaisesRegex(RuntimeError, name):
                    self.launcher["connection_budget"]()

    def test_combined_overrides_cannot_exhaust_the_rolling_database_budget(self):
        environment = {
            "WEB_CONCURRENCY": "4",
            "WEB_THREADS": "4",
            "KYC_GRPC_WORKERS": "8",
            "CHAT_DB_MAX_CONNS": "15",
            "NOTIF_DB_MAX_CONNS": "10",
            "EMAIL_DB_MAX_CONNS": "5",
        }
        with mock.patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(RuntimeError, "rolling deployment"):
                self.launcher["connection_budget"]()

    def test_go_kyc_has_no_database_pool_used_only_for_readiness(self):
        source = (BACKEND / "services" / "cmd" / "kyc" / "main.go").read_text(
            encoding="utf-8"
        )
        assert "LoadPostgres" not in source
        assert "db.NewPool" not in source
        assert 'Register("postgres"' not in source


class ProviderTimeoutBootSafetyTests(SimpleTestCase):
    def test_production_refuses_unbounded_provider_timeouts(self):
        for variable, value in (
            ("PAYMENTS_PROVIDER_CONNECT_TIMEOUT_SECONDS", "0"),
            ("PAYMENTS_PROVIDER_CONNECT_TIMEOUT_SECONDS", "11"),
            ("PAYMENTS_PROVIDER_READ_TIMEOUT_SECONDS", "0"),
            ("PAYMENTS_PROVIDER_READ_TIMEOUT_SECONDS", "31"),
        ):
            with self.subTest(variable=variable, value=value):
                result = boot_production(PROD_ENTRYPOINT_BOOT, **{variable: value})
                assert result.returncode != 0
                assert variable in result.stderr


class KycEdgeLimitTests(SimpleTestCase):
    def test_valid_kyc_request_fits_while_other_routes_stay_bounded(self):
        handler = (
            BACKEND / "services" / "internal" / "kyc" / "handler.go"
        ).read_text(encoding="utf-8")
        match = re.search(r"MaxRequestBytes int64 = (\d+) << (\d+)", handler)
        assert match is not None
        authoritative_bytes = int(match.group(1)) << int(match.group(2))

        for path in (
            VPS / "gateway.Caddyfile",
            BACKEND / "gateway" / "Caddyfile",
        ):
            text = path.read_text(encoding="utf-8")
            normal = re.search(
                r"request_body @bounded_body\s*\{\s*max_size (\d+)MB", text
            )
            kyc = re.search(
                r"handle @kyc\s*\{.*?request_body\s*\{\s*max_size (\d+)MB",
                text,
                re.DOTALL,
            )
            assert normal is not None and int(normal.group(1)) == 12
            assert kyc is not None and int(kyc.group(1)) * 1_000_000 >= authoritative_bytes
            assert re.search(
                r"@bounded_body\s*\{\s*not path /kyc/\* /api/kyc/\*\s*\}", text
            )


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
            VPS / "gateway.Caddyfile",
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
        caddyfile = VPS / "gateway.Caddyfile"
        text = caddyfile.read_text(encoding="utf-8")
        match = re.search(r"@public\s+path\s+([^\n]+)", text)
        assert match is not None
        public_paths = match.group(1).split()
        for protected in ("/api", "/admin", "/pay", "/payouts", "/healthz", "/readyz", "/ws", "/kyc"):
            assert not any(p.startswith(protected) for p in public_paths)
