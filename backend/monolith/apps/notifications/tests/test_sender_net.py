"""Sender.net's REST API as Django's trusted email backend (`sender_net.py`).

Every test mocks `requests.post`: nothing here reaches Sender.net. The backend
carries the secret-bearing messages (verification, reset, invitation and the
recipient's delivery code), so the properties under test are the request
contract, the permanent/retryable split the outbox acts on, and that no token,
recipient, subject or body reaches an exception, a stored error or a log.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from email.utils import formataddr
from unittest import mock

import pytest
import requests
from django.core.mail import EmailMultiAlternatives, get_connection
from django.test import override_settings
from django.utils import timezone

from apps.accounts.models import EmailVerificationCode, PasswordResetCode, User
from apps.deals.models import DealEvent
from apps.notifications import outbox
from apps.notifications.models import OutboundMessage, OutboundSecret
from apps.notifications.sender_net import (
    SENDER_NET_SEND_URL,
    SenderNetEmailBackend,
    SenderNetRejected,
    SenderNetUnavailable,
)

TOKEN = "test-only-sender-net-token-0123456789"
RECIPIENT = "private.person@example.invalid"
SUBJECT = "Your code 483921"
BODY = "Use 483921 to confirm."
HTML = "<p>Use 483921 to confirm.</p>"
BACKEND = "apps.notifications.sender_net.SenderNetEmailBackend"

SENDER_SETTINGS = {
    "EMAIL_BACKEND": BACKEND,
    "SENDER_NET_API_TOKEN": TOKEN,
    "EMAIL_TIMEOUT": 10,
    "DEFAULT_FROM_EMAIL": "Wassla <contact@wassla.eu>",
    "EMAIL_REPLY_TO": "contact@wassla.eu",
    "EMAIL_FROM_NAME": "Wassla",
}

ACCEPTED = {"success": True, "message": "Email sent", "emailId": "abc"}


class FakeResponse:
    def __init__(self, status: int, answer=None, *, raw: str | None = None):
        self.status_code = status
        self._answer = answer
        self._raw = raw

    def json(self):
        if self._raw is not None or self._answer is None:
            raise requests.JSONDecodeError("not json", self._raw or "", 0)
        return self._answer


def api(status=200, answer=ACCEPTED, **kwargs):
    return mock.patch(
        "apps.notifications.sender_net.requests.post",
        return_value=FakeResponse(status, answer, **kwargs),
    )


def message(**overrides) -> EmailMultiAlternatives:
    fields = {
        "subject": SUBJECT,
        "body": BODY,
        "from_email": "Wassla <contact@wassla.eu>",
        "to": [RECIPIENT],
        "reply_to": ["contact@wassla.eu"],
        **overrides,
    }
    email = EmailMultiAlternatives(**fields)
    email.attach_alternative(HTML, "text/html")
    return email


def send(email) -> int:
    with override_settings(**SENDER_SETTINGS):
        return SenderNetEmailBackend().send_messages([email])


# --- the request ------------------------------------------------------------


def test_a_text_and_html_message_is_one_documented_api_call():
    with api() as post:
        assert send(message()) == 1
    post.assert_called_once()
    args, kwargs = post.call_args
    assert args == (SENDER_NET_SEND_URL,)
    assert SENDER_NET_SEND_URL == "https://api.sender.net/v2/message/send"
    assert kwargs["json"] == {
        "from": {"email": "contact@wassla.eu", "name": "Wassla"},
        "to": {"email": RECIPIENT},
        "subject": SUBJECT,
        "text": BODY,
        "html": HTML,
    }
    assert kwargs["headers"] == {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    assert kwargs["timeout"] == (10.0, 10.0)
    assert kwargs["allow_redirects"] is False


def test_the_token_travels_in_the_authorization_header_and_nowhere_else():
    with api() as post:
        send(message())
    args, kwargs = post.call_args
    assert TOKEN not in json.dumps(kwargs["json"])
    assert TOKEN not in args[0]
    assert [key for key, value in kwargs["headers"].items() if TOKEN in value] == [
        "Authorization"
    ]


@pytest.mark.parametrize(
    "reply_to,expected",
    [
        ([], None),
        (["contact@wassla.eu"], None),
        (["CONTACT@Wassla.eu"], None),
        (["help@wassla.eu"], {"Reply-To": "help@wassla.eu"}),
        (["Wassla Help <help@wassla.eu>"], {"Reply-To": "Wassla Help <help@wassla.eu>"}),
    ],
)
def test_reply_to_is_a_custom_header_only_when_it_differs_from_from(reply_to, expected):
    with api() as post:
        send(message(reply_to=reply_to))
    assert post.call_args.kwargs["json"].get("headers") == expected


def test_an_encoded_display_name_is_sent_readable():
    with api() as post:
        send(message(from_email=formataddr(("Wassla Équipe", "contact@wassla.eu"))))
    assert post.call_args.kwargs["json"]["from"] == {
        "email": "contact@wassla.eu",
        "name": "Wassla Équipe",
    }


def test_a_plain_text_message_has_no_html_part():
    with api() as post:
        send(EmailMultiAlternatives(SUBJECT, BODY, "Wassla <contact@wassla.eu>", [RECIPIENT]))
    payload = post.call_args.kwargs["json"]
    assert payload["text"] == BODY and "html" not in payload


@pytest.mark.parametrize(
    "overrides",
    [
        {"to": [RECIPIENT, "other@example.invalid"]},
        {"cc": ["other@example.invalid"]},
        {"bcc": ["other@example.invalid"]},
        {"subject": "Hello\r\nBcc: other@example.invalid"},
        {"subject": ""},
        {"from_email": "not an address"},
    ],
)
def test_what_the_outbox_never_sends_is_refused_before_the_network(overrides):
    with api() as post, pytest.raises(SenderNetRejected) as raised:
        send(message(**overrides))
    post.assert_not_called()
    assert RECIPIENT not in str(raised.value) and "483921" not in str(raised.value)


def test_attachments_are_refused_before_the_network():
    email = message()
    email.attach("note.txt", "x", "text/plain")
    with api() as post, pytest.raises(SenderNetRejected):
        send(email)
    post.assert_not_called()


def test_a_missing_token_is_retryable_and_never_calls_the_api():
    with api() as post, override_settings(**{**SENDER_SETTINGS, "SENDER_NET_API_TOKEN": ""}):
        with pytest.raises(SenderNetUnavailable):
            SenderNetEmailBackend().send_messages([message()])
    post.assert_not_called()


def test_the_backend_is_what_django_mail_resolves():
    with override_settings(**SENDER_SETTINGS), api() as post:
        assert message(connection=get_connection()).send(fail_silently=False) == 1
    post.assert_called_once()


def test_fail_silently_counts_nothing_sent():
    with api(status=503) as post, override_settings(**SENDER_SETTINGS):
        assert SenderNetEmailBackend(fail_silently=True).send_messages([message()]) == 0
    post.assert_called_once()


# --- the answer -------------------------------------------------------------


@pytest.mark.parametrize(
    "status,answer,raw,expected",
    [
        (200, ACCEPTED, None, None),
        (201, ACCEPTED, None, None),
        (200, {"success": False, "message": "queued?"}, None, SenderNetUnavailable),
        (200, {"success": "true"}, None, SenderNetUnavailable),
        (200, None, "Email sent", SenderNetUnavailable),
        (302, None, "", SenderNetUnavailable),
        (400, {"message": "bad request"}, None, SenderNetRejected),
        (401, {"message": "Unauthenticated."}, None, SenderNetUnavailable),
        (403, None, "", SenderNetUnavailable),
        (404, None, "", SenderNetUnavailable),
        (408, None, "", SenderNetUnavailable),
        (
            422,
            {"message": "invalid", "errors": {"to.email": [f"{RECIPIENT} is invalid"]}},
            None,
            SenderNetRejected,
        ),
        (429, {"message": "Too Many Attempts."}, None, SenderNetUnavailable),
        (500, None, "", SenderNetUnavailable),
        (503, None, "", SenderNetUnavailable),
    ],
)
def test_each_answer_maps_to_its_class_and_never_leaks(status, answer, raw, expected, caplog):
    caplog.set_level(logging.DEBUG)
    with api(status=status, answer=answer, raw=raw):
        if expected is None:
            assert send(message()) == 1
            return
        with pytest.raises(expected) as raised:
            send(message())
    assert raised.value.status == status
    assert f"HTTP {status}" in str(raised.value)
    assert_log_safe(str(raised.value) + repr(raised.value) + caplog.text)


@pytest.mark.parametrize(
    "failure",
    [
        requests.ConnectTimeout(f"timed out {TOKEN}"),
        requests.ReadTimeout(f"timed out {RECIPIENT}"),
        requests.ConnectionError(f"refused {RECIPIENT}"),
        requests.exceptions.InvalidHeader(f"bad header {TOKEN}"),
    ],
)
def test_transport_failures_are_retryable_and_drop_the_original_text(failure, caplog):
    caplog.set_level(logging.DEBUG)
    with (
        mock.patch("apps.notifications.sender_net.requests.post", side_effect=failure),
        pytest.raises(SenderNetUnavailable) as raised,
    ):
        send(message())
    assert raised.value.__cause__ is None and raised.value.__suppress_context__
    assert raised.value.status == 0
    assert_log_safe(str(raised.value) + repr(raised.value) + caplog.text)


def assert_log_safe(text: str) -> None:
    for private in (TOKEN, RECIPIENT, SUBJECT, BODY, "483921"):
        assert private not in text


# --- through the outbox, on the transport each kind uses today ----------------


def _user(email: str) -> User:
    user = User(email=email, username=email, full_name="Sender Test")
    user.set_password("Sup3rStrongPass!")
    user.save()
    return user


def _verification():
    user = _user("verify.sender@example.invalid")
    row, code = EmailVerificationCode.issue(user)
    message = outbox.enqueue_secret_message(
        kind=OutboundMessage.Kind.EMAIL_VERIFICATION,
        key=f"email_verification:{row.pk}",
        to_email=user.email,
        recipient_user_id=user.pk,
        secret=code,
        secret_expires_at=row.expires_at,
    )
    return message, code


def _password_reset():
    user = _user("reset.sender@example.invalid")
    row, code = PasswordResetCode.issue(user)
    message = outbox.enqueue_secret_message(
        kind=OutboundMessage.Kind.PASSWORD_RESET,
        key=f"password_reset:{row.pk}",
        to_email=user.email,
        recipient_user_id=user.pk,
        secret=code,
        secret_expires_at=row.expires_at,
    )
    return message, code


def _invitation():
    from apps.admin_panel.services import create_admin_invitation

    owner = _user("owner.sender@example.invalid")
    User.objects.filter(pk=owner.pk).update(is_staff=True, is_superuser=True)
    owner.refresh_from_db()
    with override_settings(FRONTEND_BASE_URL="https://app.example.invalid"):
        invitation, token = create_admin_invitation(
            actor=owner, email="invitee.sender@example.invalid", role="support"
        )
    message = OutboundMessage.objects.get(key=f"admin_invitation:{invitation.pk}")
    return message, token


def _delivery_code(client):
    from apps.deals.tests.phase4_factories import (
        confirm_pickup,
        fund_scenario,
        record_recipient,
        release_delivery_code,
    )

    scenario = fund_scenario(client, prefix="snd")
    record_recipient(scenario)
    confirm_pickup(scenario)
    code = release_delivery_code(scenario)
    message = OutboundMessage.objects.get(
        deal_id=scenario.deal.pk, kind=OutboundMessage.Kind.RECIPIENT_DELIVERY_CODE
    )
    return message, code


SECRET_KINDS = {
    OutboundMessage.Kind.EMAIL_VERIFICATION: _verification,
    OutboundMessage.Kind.PASSWORD_RESET: _password_reset,
    OutboundMessage.Kind.ADMIN_INVITATION: _invitation,
    OutboundMessage.Kind.RECIPIENT_DELIVERY_CODE: _delivery_code,
}


def _arm(kind, client):
    factory = SECRET_KINDS[kind]
    return factory(client) if kind == OutboundMessage.Kind.RECIPIENT_DELIVERY_CODE else factory()


def test_every_secret_bearing_kind_is_covered():
    assert set(SECRET_KINDS) == set(outbox._SECRET_PROVIDER_KINDS)


@pytest.mark.django_db
@pytest.mark.parametrize("kind", sorted(SECRET_KINDS))
def test_each_secret_bearing_kind_is_sent_through_the_api_and_consumes_its_secret(
    kind, client, caplog
):
    from urllib.parse import quote

    message, secret = _arm(kind, client)
    caplog.set_level(logging.DEBUG)
    with (
        override_settings(TRANSACTIONAL_EMAIL_ENABLED=True, **SENDER_SETTINGS),
        mock.patch.object(outbox, "_xadd_email") as stream,
        api() as post,
    ):
        assert outbox.dispatch_message(message_id=message.pk) == "dispatched"
    # Secret-bearing mail never enters Redis.
    stream.assert_not_called()
    post.assert_called_once()
    payload = post.call_args.kwargs["json"]
    assert payload["to"] == {"email": message.to_email}
    assert payload["from"] == {"email": "contact@wassla.eu", "name": "Wassla"}
    assert "headers" not in payload
    shown = quote(secret, safe="") if kind == OutboundMessage.Kind.ADMIN_INVITATION else secret
    assert shown in payload["text"] and shown in payload["html"]
    assert secret not in payload["subject"]

    message.refresh_from_db()
    assert message.status == OutboundMessage.Status.DISPATCHED and message.last_error == ""
    if message.secret_ref.startswith("outbound_secret:"):
        vault = OutboundSecret.objects.get(key=message.key)
        assert vault.consumed_at is not None and vault.sealed_value == ""
    else:
        assert DealEvent.objects.filter(
            deal_id=message.deal_id, kind=DealEvent.Kind.RECIPIENT_NOTIFICATION_SENT
        ).exists()
    assert secret not in caplog.text and TOKEN not in caplog.text

    # A second dispatch is a no-op, never a second email.
    with override_settings(TRANSACTIONAL_EMAIL_ENABLED=True, **SENDER_SETTINGS), api() as again:
        assert outbox.dispatch_message(message_id=message.pk) == "already_dispatched"
    again.assert_not_called()


@pytest.mark.django_db
def test_a_permanent_rejection_fails_the_obligation_with_a_neutral_error(caplog):
    message, secret = _password_reset()
    caplog.set_level(logging.DEBUG)
    with (
        override_settings(TRANSACTIONAL_EMAIL_ENABLED=True, **SENDER_SETTINGS),
        api(status=422, answer={"errors": {"to.email": [f"{message.to_email} invalid"]}}),
        pytest.raises(outbox.EmailDeliveryError) as raised,
    ):
        outbox.dispatch_message(message_id=message.pk)
    assert str(raised.value) == "provider_permanent"
    message.refresh_from_db()
    assert message.status == OutboundMessage.Status.FAILED
    assert message.last_error == "provider_permanent"
    assert message.next_attempt_at is None
    for private in (secret, message.to_email, TOKEN):
        assert private not in caplog.text + str(raised.value)


@pytest.mark.django_db
@pytest.mark.parametrize("status", [401, 429, 503])
def test_a_transient_failure_keeps_the_obligation_pending_with_backoff(status):
    message, _secret = _password_reset()
    with (
        override_settings(TRANSACTIONAL_EMAIL_ENABLED=True, **SENDER_SETTINGS),
        api(status=status, answer={"message": "later"}),
        pytest.raises(outbox.EmailDeliveryError, match="provider_transient"),
    ):
        outbox.dispatch_message(message_id=message.pk)
    message.refresh_from_db()
    assert message.status == OutboundMessage.Status.PENDING
    assert message.last_error == "provider_transient"
    assert message.next_attempt_at > timezone.now() + timedelta(seconds=50)
    with override_settings(TRANSACTIONAL_EMAIL_ENABLED=True, **SENDER_SETTINGS), api() as post:
        assert outbox.dispatch_message(message_id=message.pk) == "retry_wait"
    post.assert_not_called()

    OutboundMessage.objects.filter(pk=message.pk).update(next_attempt_at=timezone.now())
    with override_settings(TRANSACTIONAL_EMAIL_ENABLED=True, **SENDER_SETTINGS), api() as post:
        assert outbox.dispatch_message(message_id=message.pk) == "dispatched"
    post.assert_called_once()


@pytest.mark.django_db
def test_a_provider_failure_spends_the_shared_minute_budget():
    first, _ = _password_reset()
    second, _ = _verification()
    with (
        override_settings(
            TRANSACTIONAL_EMAIL_ENABLED=True, EMAIL_RATE_LIMIT_PER_MINUTE=1, **SENDER_SETTINGS
        ),
        api(status=503, answer=None, raw=""),
        pytest.raises(outbox.EmailDeliveryError),
    ):
        outbox.dispatch_message(message_id=first.pk)
    with (
        override_settings(
            TRANSACTIONAL_EMAIL_ENABLED=True, EMAIL_RATE_LIMIT_PER_MINUTE=1, **SENDER_SETTINGS
        ),
        api() as post,
    ):
        assert outbox.dispatch_message(message_id=second.pk) == "rate_limited"
    post.assert_not_called()


@pytest.mark.django_db
def test_email_disabled_sends_nothing_and_keeps_the_obligation():
    message, _secret = _verification()
    with (
        override_settings(TRANSACTIONAL_EMAIL_ENABLED=False, **SENDER_SETTINGS),
        api() as post,
    ):
        assert outbox.dispatch_message(message_id=message.pk) == "disabled"
        assert outbox.dispatch_due_messages() == 0
    post.assert_not_called()
    message.refresh_from_db()
    assert message.status == OutboundMessage.Status.PENDING and message.attempts == 0
    assert OutboundSecret.objects.get(key=message.key).sealed_value


ORDINARY_CONTEXT = {
    "status": "approved",
    "protection_ends_at": "2099-01-01T00:00:00+00:00",
    "payment_reference": "PAY-test",
    "amount_eur_cents": 1234,
}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "kind",
    sorted(set(OutboundMessage.Kind.values) - set(outbox._SECRET_PROVIDER_KINDS)),
)
def test_every_ordinary_kind_travels_the_stream_in_the_go_sender_contract(kind):
    """The Go service's Sender.net sender reads exactly this payload
    (`internal/email` EmailPayload; `sender_net_test.go` sends it)."""

    message = outbox.enqueue_message(
        kind=kind,
        key=f"egs:stream:{kind}",
        to_email=RECIPIENT,
        context=ORDINARY_CONTEXT,
        language="ar",
    )
    client = mock.Mock()
    with (
        override_settings(TRANSACTIONAL_EMAIL_ENABLED=True, **SENDER_SETTINGS),
        mock.patch.object(outbox.redis_bus, "get_client", return_value=client),
        api() as post,
    ):
        assert outbox.dispatch_message(message_id=message.pk) == "transported"
    post.assert_not_called()
    stream, fields = client.xadd.call_args.args
    assert stream == "email:send"
    payload = json.loads(fields["payload"])
    assert set(payload) == {"event_id", "to", "subject", "body", "html", "kind"}
    assert payload["to"] == RECIPIENT and payload["kind"] == kind
    assert payload["subject"] and payload["body"] and payload["html"]
    assert payload["event_id"] == fields["event_id"]
