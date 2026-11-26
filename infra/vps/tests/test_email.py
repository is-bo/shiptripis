"""Email activation stays explicit and provider credentials live only in the mounted secret file."""

import importlib.machinery
import json
import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
runtime = importlib.machinery.SourceFileLoader(
    "email_runtime", str(HERE / "runtime.py")
).load_module()


class EmailBoundaryTests(unittest.TestCase):
    def test_both_vps_proxy_layers_preserve_application_referrer_policy(self):
        gateway = (HERE / "gateway.Caddyfile").read_text()
        # A default under the application's own policy, and a fixed value only
        # on errors the proxy answers itself, where there is no application
        # response to preserve (G1).
        self.assertEqual(gateway.count("Referrer-Policy"), 2)
        self.assertIn('?Referrer-Policy "strict-origin-when-cross-origin"', gateway)
        errors = gateway[gateway.index("handle_errors {") :]
        self.assertIn("header Referrer-Policy no-referrer", errors)
        self.assertIn("trusted_proxies static private_ranges", gateway)
        self.assertIn("auto_https off", gateway)
        self.assertIn("?Referrer-Policy strict-origin-when-cross-origin", (HERE / "Caddyfile").read_text())

    def environment(self):
        return {
            "SHIPTRIP_ENVIRONMENT": "production",
            "DJANGO_DEBUG": "false",
            "PAYMENTS_ENVIRONMENT": "test",
            "PAYMENTS_ALLOW_MOCK_PROVIDER": "false",
            "PAYOUT_DZD_EXECUTION_ENABLED": "false",
            "STRIPE_CONNECT_PAYOUTS_ENABLED": "false",
            "STRIPE_CONNECT_NON_STRIPE_FUNDING_ENABLED": "false",
            "STRIPE_CONNECT_EXPECTED_MODE": "test",
            "EMAIL_ENABLED": "false",
        }

    def stack_template(self):
        values = {}
        for line in (HERE / "stack.env.example").read_text().splitlines():
            if line and not line.startswith("#"):
                key, _, value = line.partition("=")
                values[key] = value
        return values

    def test_provider_credentials_can_only_use_secret_injection(self):
        credentials = {"SENDER_NET_API_TOKEN", "EMAIL_SMTP_USERNAME", "EMAIL_SMTP_PASSWORD"}
        self.assertTrue(credentials <= runtime.SECRET_KEYS)
        template = self.stack_template()
        self.assertFalse(credentials & set(template))
        self.assertEqual(template["EMAIL_ENABLED"], "false")
        self.assertEqual(template["EMAIL_ACTIVATION_APPROVED"], "false")
        secrets = json.loads((HERE / "app-secrets.example.json").read_text())
        self.assertEqual(secrets["SENDER_NET_API_TOKEN"], "")
        self.assertFalse(set(secrets) - runtime.SECRET_KEYS)

    def test_the_shipped_example_is_sender_net_from_contact_at_wassla(self):
        template = self.stack_template()
        self.assertEqual(template["EMAIL_PROVIDER"], "sender_net")
        self.assertEqual(template["EMAIL_FROM_ADDR"], "contact@wassla.eu")
        self.assertEqual(template["EMAIL_SUPPORT_ADDR"], "contact@wassla.eu")
        self.assertEqual(template["EMAIL_REPLY_TO"], "")
        self.assertEqual(template["EMAIL_FROM_NAME"], "Wassla")
        self.assertEqual(template["EMAIL_TIMEOUT_SECONDS"], "10")
        # The API needs no SMTP relay; an SMTP host under sender_net is refused.
        for key in ("EMAIL_SMTP_HOST", "EMAIL_SMTP_PORT", "EMAIL_SMTP_TIMEOUT_SECONDS"):
            self.assertNotIn(key, template)

    def test_the_token_reaches_the_environment_only_from_the_secret_file(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "app_secrets").write_text(json.dumps({"SENDER_NET_API_TOKEN": "t" * 32}))
            (folder / "postgres_password").write_text("p" * 64)
            (folder / "redis_password").write_text("r" * 64)
            with patch.dict(os.environ, {}, clear=True):
                runtime.load_secrets(folder)
                self.assertEqual(os.environ["SENDER_NET_API_TOKEN"], "t" * 32)
            with (
                patch.dict(os.environ, {"SENDER_NET_API_TOKEN": "x" * 32}, clear=True),
                self.assertRaises(RuntimeError),
            ):
                runtime.load_secrets(folder)

    def test_email_cannot_be_enabled_by_just_one_flag(self):
        env = {**self.environment(), "EMAIL_ENABLED": "true"}
        with patch.dict(os.environ, env, clear=True), self.assertRaises(RuntimeError):
            runtime.v1_guards()

    def test_eventual_activation_preserves_every_financial_guard(self):
        env = {
            **self.environment(),
            "EMAIL_ENABLED": "true",
            "EMAIL_ACTIVATION_APPROVED": "true",
            "EMAIL_SENDING_DOMAIN_VERIFIED": "true",
            "EMAIL_ACTIVATION_NOT_BEFORE": "2026-10-18T00:00:00Z",
        }
        with patch.dict(os.environ, env, clear=True):
            runtime.v1_guards()
        with (
            patch.dict(os.environ, {**env, "PAYMENTS_ENVIRONMENT": "live"}, clear=True),
            self.assertRaises(RuntimeError),
        ):
            runtime.v1_guards()

    def test_email_credentials_reach_only_django_and_the_email_service(self):
        import importlib.util
        import sys

        spec = importlib.util.spec_from_file_location("email_launcher", HERE / "launcher.py")
        launcher = importlib.util.module_from_spec(spec)
        sys.modules["email_launcher"] = launcher
        try:
            spec.loader.exec_module(launcher)
        finally:
            sys.modules.pop("email_launcher", None)
        credentials = {"SENDER_NET_API_TOKEN": "t" * 32, "EMAIL_SMTP_USERNAME": "u", "EMAIL_SMTP_PASSWORD": "p"}
        seen = {}
        with (
            patch.dict(os.environ, credentials, clear=True),
            patch.object(launcher.subprocess, "Popen", side_effect=lambda *a, env, **k: seen.update({a[0][0]: env})),
        ):
            for name in ("web", "email", "chat", "notification", "kyc", "gateway"):
                launcher.spawn(name, [name])
        for name in ("web", "email"):
            self.assertEqual({key: seen[name].get(key) for key in credentials}, credentials)
        for name in ("chat", "notification", "kyc", "gateway"):
            self.assertFalse(set(credentials) & set(seen[name]), name)

