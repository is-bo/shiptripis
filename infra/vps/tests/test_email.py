"""V2 keeps activation explicit and SMTP credentials in the mounted secret file."""

import importlib.machinery
import os
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
        self.assertEqual(gateway.count("Referrer-Policy"), 1)
        self.assertIn('?Referrer-Policy "strict-origin-when-cross-origin"', gateway)
        self.assertIn("trusted_proxies static private_ranges", gateway)
        self.assertIn("auto_https off", gateway)
        self.assertIn("?Referrer-Policy strict-origin-when-cross-origin", (HERE / "Caddyfile").read_text())

    def environment(self):
        return {
            "SHIPTRIP_ENVIRONMENT": "production",
            "DJANGO_DEBUG": "false",
            "PAYMENTS_ENVIRONMENT": "test",
            "PAYMENTS_ALLOW_MOCK_PROVIDER": "false",
            "PAYMENTS_MOCK_WEBHOOK_ENABLED": "false",
            "PAYMENTS_LEGACY_MUTATIONS_ENABLED": "false",
            "PAYOUT_DZD_EXECUTION_ENABLED": "false",
            "STRIPE_CONNECT_PAYOUTS_ENABLED": "false",
            "STRIPE_CONNECT_NON_STRIPE_FUNDING_ENABLED": "false",
            "STRIPE_CONNECT_EXPECTED_MODE": "test",
            "EMAIL_ENABLED": "false",
        }

    def test_smtp_credentials_can_only_use_secret_injection(self):
        self.assertTrue(
            {"EMAIL_SMTP_USERNAME", "EMAIL_SMTP_PASSWORD"} <= runtime.SECRET_KEYS
        )
        template = (HERE / "stack.env.example").read_text()
        self.assertNotIn("EMAIL_SMTP_PASSWORD=", template)
        self.assertIn("EMAIL_ENABLED=false", template)
        self.assertIn("EMAIL_ACTIVATION_APPROVED=false", template)

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
