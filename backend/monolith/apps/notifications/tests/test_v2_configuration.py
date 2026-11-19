"""Production email settings, imported only: no provider, SMTP relay or database is contacted.

`EMAIL_PROVIDER=sender_net` is Sender.net's REST API with a bearer token;
`EMAIL_PROVIDER=smtp` is any SMTP relay. Each refuses an incomplete enabled
configuration at boot with a message that names the setting and never echoes
a credential.
"""

import pytest

from apps.finance.tests.test_deployment_safety import boot_production

TOKEN = "test-only-sender-net-token-0123456789"

SENDER_NET = {
    "EMAIL_ENABLED": "true",
    "EMAIL_PROVIDER": "sender_net",
    "SENDER_NET_API_TOKEN": TOKEN,
    "EMAIL_SMTP_HOST": "",
    "EMAIL_FROM_ADDR": "contact@wassla.eu",
    "EMAIL_FROM_NAME": "Wassla",
    "EMAIL_SUPPORT_ADDR": "contact@wassla.eu",
    "EMAIL_REPLY_TO": "",
    "EMAIL_SENDING_DOMAIN_VERIFIED": "true",
    "EMAIL_ACTIVATION_NOT_BEFORE": "2026-10-18T00:00:00Z",
}

SMTP = {
    "EMAIL_ENABLED": "true",
    "EMAIL_PROVIDER": "smtp",
    "EMAIL_SMTP_HOST": "smtp.example.invalid",
    "EMAIL_SMTP_PORT": "587",
    "EMAIL_USE_TLS": "true",
    "EMAIL_SMTP_USERNAME": "test-only-placeholder",
    "EMAIL_SMTP_PASSWORD": "test-only-smtp-password",
    "EMAIL_FROM_ADDR": "notifications@example.invalid",
    "EMAIL_FROM_NAME": "Wassla",
    "EMAIL_SUPPORT_ADDR": "support@example.invalid",
    "EMAIL_REPLY_TO": "support@example.invalid",
    "EMAIL_SENDING_DOMAIN_VERIFIED": "true",
    "EMAIL_ACTIVATION_NOT_BEFORE": "2026-10-18T00:00:00Z",
}


def test_production_sender_net_uses_the_api_backend_and_one_address():
    snippet = """from config.settings import prod as s
from email.header import decode_header,make_header
from email.utils import parseaddr
name,address=parseaddr(s.DEFAULT_FROM_EMAIL)
assert str(make_header(decode_header(name)))=='Wassla'
assert address=='contact@wassla.eu'
assert s.EMAIL_SUPPORT_ADDR=='contact@wassla.eu'
assert s.EMAIL_REPLY_TO=='contact@wassla.eu'
assert s.EMAIL_BACKEND=='apps.notifications.sender_net.SenderNetEmailBackend'
assert s.EMAIL_TIMEOUT==10
"""
    result = boot_production(snippet, **SENDER_NET)
    assert result.returncode == 0, result.stderr


def test_blank_identity_settings_mean_contact_at_wassla():
    snippet = """from config.settings import prod as s
assert s.EMAIL_FROM_ADDR==s.EMAIL_SUPPORT_ADDR==s.EMAIL_REPLY_TO=='contact@wassla.eu'
assert s.DEFAULT_FROM_EMAIL=='Wassla <contact@wassla.eu>'
"""
    result = boot_production(
        snippet,
        EMAIL_ENABLED="false",
        EMAIL_FROM_ADDR="",
        EMAIL_SUPPORT_ADDR="  ",
        EMAIL_REPLY_TO="",
        EMAIL_FROM_NAME="",
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "field,value,named",
    [
        ("SENDER_NET_API_TOKEN", "", "SENDER_NET_API_TOKEN"),
        ("SENDER_NET_API_TOKEN", "too-short-token", "SENDER_NET_API_TOKEN"),
        ("SENDER_NET_API_TOKEN", "test-only sender-net-token-0123456789", "SENDER_NET_API_TOKEN"),
        ("EMAIL_SMTP_HOST", "smtp.sender.net", "EMAIL_SMTP_HOST"),
        ("EMAIL_SENDING_DOMAIN_VERIFIED", "false", "EMAIL_SENDING_DOMAIN_VERIFIED"),
        ("EMAIL_ACTIVATION_NOT_BEFORE", "", "EMAIL_ACTIVATION_NOT_BEFORE"),
        ("EMAIL_ACTIVATION_NOT_BEFORE", "2026-10-18", "EMAIL_ACTIVATION_NOT_BEFORE"),
        ("EMAIL_FROM_ADDR", "invalid\r\nBcc: other@example.invalid", "EMAIL_FROM_ADDR"),
        ("EMAIL_REPLY_TO", "not-an-address", "EMAIL_REPLY_TO"),
        ("EMAIL_SUPPORT_ADDR", "not-an-address", "EMAIL_SUPPORT_ADDR"),
        ("EMAIL_TIMEOUT_SECONDS", "0", "timeout"),
        ("EMAIL_TIMEOUT_SECONDS", "11", "timeout"),
        ("EMAIL_RATE_LIMIT_PER_MINUTE", "0", "rate"),
        ("EMAIL_PROVIDER", "sender.net", "EMAIL_PROVIDER"),
        ("EMAIL_PROVIDER", "mailchimp", "EMAIL_PROVIDER"),
    ],
)
def test_production_refuses_each_incomplete_sender_net_configuration(field, value, named):
    result = boot_production("from config.settings import prod", **{**SENDER_NET, field: value})
    assert result.returncode != 0
    assert named in result.stderr
    assert TOKEN not in result.stderr


def test_production_smtp_keeps_its_contract():
    snippet = """from config.settings import prod as s
assert s.EMAIL_BACKEND=='django.core.mail.backends.smtp.EmailBackend'
assert s.EMAIL_HOST=='smtp.example.invalid' and s.EMAIL_PORT==587 and s.EMAIL_USE_TLS
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
        ("EMAIL_SMTP_HOST", ""),
        ("EMAIL_SUPPORT_ADDR", "not-an-address"),
        ("EMAIL_FROM_ADDR", "invalid\r\nBcc: other@example.invalid"),
        ("EMAIL_TIMEOUT_SECONDS", "0"),
        ("EMAIL_RATE_LIMIT_PER_MINUTE", "0"),
    ],
)
def test_production_refuses_incomplete_or_insecure_smtp_configuration(field, value):
    result = boot_production(
        "from config.settings import prod", **{**SMTP, field: value}
    )
    assert result.returncode != 0
    assert SMTP["EMAIL_SMTP_PASSWORD"] not in result.stderr


@pytest.mark.parametrize("provider", ["sender_net", "smtp"])
def test_disabled_production_needs_no_provider_credentials(provider):
    result = boot_production(
        "from config.settings import prod as s; assert not s.TRANSACTIONAL_EMAIL_ENABLED",
        EMAIL_ENABLED="false",
        EMAIL_PROVIDER=provider,
        SENDER_NET_API_TOKEN="",
        EMAIL_SMTP_HOST="",
        EMAIL_SMTP_USERNAME="",
        EMAIL_SMTP_PASSWORD="",
    )
    assert result.returncode == 0, result.stderr
