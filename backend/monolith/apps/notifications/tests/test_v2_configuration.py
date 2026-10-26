"""Production settings import only; these tests never dial SMTP or a database."""

import pytest

from apps.finance.tests.test_deployment_safety import boot_production

SMTP = {
    "EMAIL_ENABLED": "true",
    "EMAIL_PROVIDER": "sender_net",
    "EMAIL_SMTP_HOST": "smtp.sender.net",
    "EMAIL_SMTP_PORT": "587",
    "EMAIL_USE_TLS": "true",
    "EMAIL_SMTP_USERNAME": "test-only-placeholder",
    "EMAIL_SMTP_PASSWORD": "test-only-placeholder",
    "EMAIL_FROM_ADDR": "notifications@example.invalid",
    "EMAIL_FROM_NAME": "Wassla",
    "EMAIL_SUPPORT_ADDR": "support@example.invalid",
    "EMAIL_REPLY_TO": "support@example.invalid",
    "EMAIL_SENDING_DOMAIN_VERIFIED": "true",
    "EMAIL_ACTIVATION_NOT_BEFORE": "2026-10-18T00:00:00Z",
}


def test_production_sender_settings_are_shared_and_require_no_live_credentials():
    snippet = """from config.settings import prod as s
from email.header import decode_header,make_header
from email.utils import parseaddr
name,address=parseaddr(s.DEFAULT_FROM_EMAIL)
assert str(make_header(decode_header(name)))=='Wassla'
assert address=='notifications@example.invalid'
assert s.EMAIL_REPLY_TO=='support@example.invalid'
assert s.EMAIL_TIMEOUT==10
"""
    result = boot_production(snippet, **SMTP)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "field,value",
    [
        ("EMAIL_ACTIVATION_NOT_BEFORE", ""),
        ("EMAIL_ACTIVATION_NOT_BEFORE", "2026-10-18"),
        ("EMAIL_SENDING_DOMAIN_VERIFIED", "false"),
        ("EMAIL_USE_TLS", "false"),
        ("EMAIL_SMTP_HOST", "smtp.invalid"),
        ("EMAIL_SMTP_PORT", "465"),
        ("EMAIL_SUPPORT_ADDR", ""),
        ("EMAIL_FROM_ADDR", "invalid\r\nBcc: other@example.invalid"),
        ("EMAIL_SMTP_TIMEOUT_SECONDS", "0"),
        ("EMAIL_RATE_LIMIT_PER_MINUTE", "0"),
    ],
)
def test_production_refuses_incomplete_or_insecure_smtp_configuration(field, value):
    result = boot_production(
        "from config.settings import prod", **{**SMTP, field: value}
    )
    assert result.returncode != 0
    assert SMTP["EMAIL_SMTP_PASSWORD"] not in result.stderr


def test_disabled_production_needs_no_smtp_credentials():
    result = boot_production(
        "from config.settings import prod as s; assert not s.TRANSACTIONAL_EMAIL_ENABLED",
        EMAIL_ENABLED="false",
        EMAIL_SMTP_USERNAME="",
        EMAIL_SMTP_PASSWORD="",
    )
    assert result.returncode == 0, result.stderr
