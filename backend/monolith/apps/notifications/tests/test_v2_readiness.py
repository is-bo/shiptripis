"""V2 render, activation, secrecy and local SMTP regression contracts."""

import ast
import io
import json
import smtplib
import socketserver
import threading
import time
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from apps.accounts.models import User, PasswordResetCode
from apps.admin_panel.models import AdminAuditLog
from apps.core.locale_format import format_utc_datetime
from apps.notifications import outbox
from apps.notifications.backlog import classify, fingerprint, review
from apps.notifications.models import OutboundMessage, OutboundSecret


@pytest.mark.parametrize("kind", OutboundMessage.Kind.values)
@pytest.mark.parametrize("locale", ["en", "fr", "ar", "invalid"])
@pytest.mark.django_db
def test_entire_inventory_has_branded_localized_alternatives(kind, locale):
    context = {
        "frontend_base_url": "https://app.example.invalid",
        "role": "support",
        "status": "succeeded",
        "payment_reference": "PAY-test",
        "amount_eur_cents": 1234,
        "event": "password_reset_completed",
        "recipient_name": '<script>alert("x")</script>',
    }
    message = OutboundMessage(kind=kind, language=locale, context=context)
    with patch.object(outbox, "resolve_secret", return_value="483921"):
        subject, text, html = outbox.render_parts(message)
    resolved = locale if locale in {"en", "fr", "ar"} else "en"
    assert (
        f'<html lang="{resolved}" dir="{"rtl" if resolved == "ar" else "ltr"}">' in html
    )
    for value in (subject, text, html):
        assert value and "ShipTrip" not in value and "Waçla" not in value
    for value in (text, html):
        assert "Wassla" in value
    assert "<script>" not in html and "<img" not in html
    assert "http://" not in html
    if kind in {"email_verification", "password_reset", "recipient_delivery_code"}:
        assert "483921" in text and "483921" in html
    if locale in {"fr", "ar"}:
        with patch.object(outbox, "resolve_secret", return_value="483921"):
            english = outbox.render_parts(
                OutboundMessage(kind=kind, language="en", context=context)
            )
        assert subject != english[0]


def test_every_literal_has_a_translation_and_placeholders_match():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "tools"))
    from compile_po import _catalog

    root = Path(__file__).resolve().parents[3]
    sources = set()
    for path in (
        Path(outbox.__file__),
        Path(outbox.__file__).with_name("email_layout.py"),
    ):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_"
                and isinstance(node.args[0], ast.Constant)
            ):
                sources.add(node.args[0].value)
    import re

    for locale in ("fr", "ar"):
        catalog = _catalog(root / f"locale/{locale}/LC_MESSAGES/django.po")
        assert not sources - catalog.keys()
        for source in sources:
            assert catalog[source]
            assert sorted(re.findall(r"%\([^)]+\)[a-z]", source)) == sorted(
                re.findall(r"%\([^)]+\)[a-z]", catalog[source])
            )


@pytest.mark.django_db
def test_guest_receipt_never_echoes_private_deal_context():
    message = OutboundMessage(
        kind="guest_payment",
        context={
            "status": "succeeded",
            "tracking_number": "WSL-PRIVATE9",
            "recipient_name": "PRIVATE-NAME",
            "payment_reference": "PAY-test",
            "amount_eur_cents": 1200,
        },
    )
    _, text, html = outbox.render_parts(message)
    assert "PRIVATE" not in text + html
    assert "PAY-test" in text and "PAY-test" in html


@pytest.mark.django_db
@pytest.mark.parametrize(
    "base",
    [
        "javascript:alert(1)",
        "https://user:pass@example.invalid",
        "https://app.example.invalid/?token=private",
        "http://app.example.invalid",
    ],
)
def test_invitation_rejects_untrusted_origins(base):
    with pytest.raises(outbox.SecretUnavailable):
        outbox.render_parts(
            OutboundMessage(
                kind="admin_invitation", context={"frontend_base_url": base}
            )
        )


def obligation(**kwargs):
    return outbox.enqueue_message(
        kind="kyc_status",
        key=f"v2:{time.monotonic_ns()}",
        to_email="only@example.invalid",
        context={"status": "approved"},
        **kwargs,
    )


@pytest.mark.django_db
def test_disabled_keeps_every_obligation_without_transport():
    with (
        override_settings(TRANSACTIONAL_EMAIL_ENABLED=False),
        patch.object(outbox, "_xadd_email") as stream,
        patch.object(outbox, "_send_email_via_provider") as smtp,
    ):
        for kind in OutboundMessage.Kind.values:
            row = OutboundMessage.objects.create(
                key=f"disabled:{kind}", kind=kind, to_email="only@example.invalid"
            )
            assert outbox.dispatch_message(message_id=row.pk) == "disabled"
        stream.assert_not_called()
        smtp.assert_not_called()
    assert not OutboundMessage.objects.exclude(attempts=0).exists()


@pytest.mark.django_db
def test_cutoff_holds_old_rows_without_starving_new_obligations():
    old = obligation()
    cutoff = timezone.now()
    fresh = obligation()
    with (
        override_settings(
            TRANSACTIONAL_EMAIL_ENABLED=True, EMAIL_ACTIVATION_NOT_BEFORE=cutoff
        ),
        patch.object(outbox, "_xadd_email", return_value="test-event") as send,
    ):
        assert outbox.dispatch_message(message_id=old.pk) == "activation_held"
        assert outbox.dispatch_due_messages(limit=1) == 1
        assert send.call_count == 1
        assert outbox.dispatch_message(message_id=fresh.pk) == "awaiting_receipt"
    old.refresh_from_db()
    assert old.attempts == 0


@pytest.mark.django_db
def test_backlog_audit_is_read_only_and_review_is_explicit_and_audited():
    row = obligation()
    output = io.StringIO()
    call_command("audit_email_backlog", stdout=output)
    report = json.loads(output.getvalue())["messages"][0]
    assert report["id"] == row.pk
    assert row.to_email not in output.getvalue() and not AdminAuditLog.objects.exists()
    actor = User.objects.create_superuser(
        username="operator", email="operator@example.invalid", password=None
    )
    review(
        message_id=row.pk,
        expected_fingerprint=report["fingerprint"],
        action="release",
        actor=actor,
    )
    row.refresh_from_db()
    assert (
        row.activation_reviewed_at
        and AdminAuditLog.objects.filter(action="email_backlog.release").exists()
    )
    with pytest.raises(ValueError):
        review(
            message_id=row.pk,
            expected_fingerprint=report["fingerprint"],
            action="cancel",
            actor=actor,
        )
    review(
        message_id=row.pk,
        expected_fingerprint=fingerprint(row),
        action="cancel",
        actor=actor,
    )
    assert OutboundMessage.objects.get(pk=row.pk).status == "cancelled"


@pytest.mark.django_db
def test_expired_capability_cannot_be_released_and_audit_never_decrypts():
    row = outbox.enqueue_secret_message(
        kind="password_reset",
        key="v2:expired",
        to_email="only@example.invalid",
        secret="483921",
        secret_expires_at=timezone.now() + timedelta(minutes=1),
    )
    OutboundSecret.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
    with patch(
        "apps.notifications.secrets.unseal",
        side_effect=AssertionError("must not decrypt"),
    ):
        assert classify(row)["category"] == "expired"
    actor = User.objects.create_superuser(username="operator", password=None)
    with pytest.raises(ValueError):
        review(
            message_id=row.pk,
            expected_fingerprint=fingerprint(row),
            action="release",
            actor=actor,
        )


@pytest.mark.django_db
def test_used_and_superseded_password_reset_capabilities_refuse_rendering():
    user = User.objects.create_user(
        username="v2-reset", email="only@example.invalid", password=None
    )
    code, plaintext = PasswordResetCode.issue(user)
    row = outbox.enqueue_secret_message(
        kind="password_reset",
        key=f"password_reset:{code.pk}",
        to_email=user.email,
        recipient_user_id=user.pk,
        secret=plaintext,
        secret_expires_at=code.expires_at,
    )
    newer, _ = PasswordResetCode.issue(user)
    with pytest.raises(outbox.SecretUnavailable):
        outbox.render_parts(row)
    PasswordResetCode.objects.filter(pk=newer.pk).update(used_at=timezone.now())
    with pytest.raises(outbox.SecretUnavailable):
        outbox.render_parts(row)
    PasswordResetCode.objects.filter(pk=code.pk).update(used_at=timezone.now())
    with pytest.raises(outbox.SecretUnavailable):
        outbox.render_parts(row)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "failure,expected",
    [
        (
            smtplib.SMTPDataError(451, b"private token=483921 password=secret"),
            "pending",
        ),
        (smtplib.SMTPDataError(550, b"private token=483921 password=secret"), "failed"),
        (TimeoutError("private secret=483921"), "pending"),
        (smtplib.SMTPAuthenticationError(535, b"private password=483921"), "pending"),
    ],
)
def test_smtp_failures_are_classified_and_never_leak(failure, expected):
    row = outbox.enqueue_secret_message(
        kind="password_reset",
        key=f"v2:error:{expected}",
        to_email="only@example.invalid",
        secret="483921",
        secret_expires_at=timezone.now() + timedelta(minutes=10),
    )
    with (
        override_settings(TRANSACTIONAL_EMAIL_ENABLED=True),
        patch.object(outbox, "_send_email_via_provider", side_effect=failure),
    ):
        with pytest.raises(outbox.EmailDeliveryError) as raised:
            outbox.dispatch_message(message_id=row.pk)
    row.refresh_from_db()
    assert row.status == expected
    assert "483921" not in str(raised.value) + row.last_error
    assert "private" not in row.last_error


class Sink(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class SMTPHandler(socketserver.StreamRequestHandler):
    def handle(self):
        time.sleep(getattr(self.server, "greeting_delay", 0))
        self.wfile.write(b"220 local.invalid ESMTP\r\n")
        while line := self.rfile.readline():
            command = line.decode(errors="replace").strip()
            verb = command.partition(" ")[0].upper()
            if verb in ("EHLO", "HELO"):
                reply = b"250 local.invalid\r\n"
            elif verb == "RCPT":
                assert "@example.invalid" in command
                reply = self.server.rcpt_reply
            elif verb == "DATA":
                self.wfile.write(b"354 End with dot\r\n")
                data = b""
                while (part := self.rfile.readline()) != b".\r\n":
                    if not part:
                        return
                    data += part
                self.server.messages.append(data)
                reply = b"250 accepted locally\r\n"
            elif verb == "QUIT":
                self.wfile.write(b"221 bye\r\n")
                return
            else:
                reply = b"250 ok\r\n"
            self.wfile.write(reply)


@pytest.mark.django_db
@pytest.mark.parametrize("locale", ["en", "fr", "ar"])
def test_real_django_smtp_is_multipart_local_and_has_monitored_reply_to(locale):
    from email import policy
    from email.parser import BytesParser

    with Sink(("127.0.0.1", 0), SMTPHandler) as server:
        server.messages = []
        server.rcpt_reply = b"250 accepted\r\n"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            row = outbox.enqueue_secret_message(
                kind="password_reset",
                key=f"v2:smtp:{locale}",
                to_email="only@example.invalid",
                secret="483921",
                secret_expires_at=timezone.now() + timedelta(minutes=7),
                language=locale,
            )
            with override_settings(
                TRANSACTIONAL_EMAIL_ENABLED=True,
                EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
                EMAIL_HOST="127.0.0.1",
                EMAIL_PORT=server.server_address[1],
                EMAIL_HOST_USER="",
                EMAIL_HOST_PASSWORD="",
                EMAIL_USE_TLS=False,
                EMAIL_REPLY_TO="support@example.invalid",
                DEFAULT_FROM_EMAIL="Wassla <notifications@example.invalid>",
            ):
                assert outbox.dispatch_message(message_id=row.pk) == "dispatched"
            mail = BytesParser(policy=policy.default).parsebytes(server.messages[0])
            assert str(mail["Reply-To"]) == "support@example.invalid"
            assert "Wassla" in str(mail["From"])
            assert mail.get_body(preferencelist=("plain",)) and mail.get_body(
                preferencelist=("html",)
            )
            assert "483921" in mail.get_body(preferencelist=("plain",)).get_content()
            assert not OutboundSecret.objects.get(key=row.key).sealed_value
        finally:
            server.shutdown()
            thread.join(timeout=2)


@pytest.mark.django_db
def test_secret_context_is_rejected_and_unknown_context_fails_closed():
    with pytest.raises(ValueError):
        outbox.enqueue_message(
            kind="password_reset",
            key="v2:unsafe",
            to_email="only@example.invalid",
            context={"nested": {"token": "secret"}},
        )
    row = OutboundMessage.objects.create(
        kind="unknown_kind",
        key="v2:unknown",
        to_email="only@example.invalid",
        context=["malformed"],
    )
    with (
        override_settings(TRANSACTIONAL_EMAIL_ENABLED=True),
        patch.object(outbox, "_xadd_email") as send,
    ):
        assert outbox.dispatch_message(message_id=row.pk) == "unrenderable"
        send.assert_not_called()


def independent_call(callback):
    from django.db import connections

    try:
        return callback()
    finally:
        connections.close_all()


@pytest.fixture
def committed_mail(db):
    """Clean up only our committed thread fixtures, preserving migration seeds."""
    from concurrent.futures import ThreadPoolExecutor

    yield

    def cleanup():
        from apps.finance.models import ScheduledJob
        from apps.core.models import PublishedEvent

        rows = OutboundMessage.objects.filter(key__startswith="v2:concurrent")
        identities = list(rows.values_list("pk", flat=True))
        PublishedEvent.objects.filter(
            event_id__in=list(rows.values_list("transport_event_id", flat=True))
        ).delete()
        ScheduledJob.objects.filter(
            key__in=[f"outbound_message:{pk}" for pk in identities]
        ).delete()
        rows.delete()
        OutboundSecret.objects.filter(key__startswith="v2:concurrent").delete()

    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(independent_call, cleanup).result(timeout=10)


@pytest.mark.django_db
@pytest.mark.parametrize("outcome", ["dispatched", "provider_transient"])
@pytest.mark.parametrize("redis_reply_lost", [False, True])
def test_redis_publication_observes_committed_claim_and_preserves_fast_outcome(
    committed_mail, outcome, redis_reply_lost
):
    from concurrent.futures import ThreadPoolExecutor
    from apps.core.models import PublishedEvent

    with ThreadPoolExecutor(max_workers=2) as pool:
        row = pool.submit(
            independent_call,
            lambda: outbox.enqueue_message(
                kind="kyc_status", key="v2:concurrent-handoff",
                to_email="only@example.invalid", context={"status": "approved"},
            ),
        ).result(timeout=10)

        def fast_consumer(*args, **kwargs):
            def consume():
                current = OutboundMessage.objects.get(pk=row.pk)
                assert current.transport_event_id == args[1]["event_id"]
                assert current.attempts == 1 and current.next_attempt_at
                assert PublishedEvent.objects.filter(event_id=current.transport_event_id).exists()
                # Another publisher cannot steal the claim before receipt expiry.
                assert outbox.dispatch_message(message_id=row.pk) == "awaiting_receipt"
                OutboundMessage.objects.filter(pk=row.pk).update(
                    status="dispatched" if outcome == "dispatched" else "pending",
                    dispatched_at=timezone.now() if outcome == "dispatched" else None,
                    last_error="" if outcome == "dispatched" else outcome,
                    next_attempt_at=None if outcome == "dispatched" else timezone.now() + timedelta(minutes=1),
                )
            pool.submit(independent_call, consume).result(timeout=10)
            if redis_reply_lost:
                raise outbox.redis.RedisError("untrusted transport exception")

        with (
            override_settings(TRANSACTIONAL_EMAIL_ENABLED=True),
            patch.object(outbox.redis_bus, "get_client") as redis_client,
        ):
            redis_client.return_value.xadd.side_effect = fast_consumer
            result = pool.submit(
                independent_call, lambda: outbox.dispatch_message(message_id=row.pk)
            )
            if redis_reply_lost:
                with pytest.raises(outbox.EmailDeliveryError, match="email_transport_unavailable"):
                    result.result(timeout=10)
            else:
                assert result.result(timeout=10) == "transported"
            redis_client.return_value.xadd.assert_called_once()
        final = pool.submit(
            independent_call, lambda: OutboundMessage.objects.get(pk=row.pk)
        ).result(timeout=10)
        assert final.status == ("dispatched" if outcome == "dispatched" else "pending")
        assert final.last_error == ("" if outcome == "dispatched" else outcome)


@pytest.mark.django_db
def test_concurrent_django_workers_cannot_send_the_same_capability(committed_mail):
    from concurrent.futures import ThreadPoolExecutor
    from django.db import connection

    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL advisory locks")
    with ThreadPoolExecutor(max_workers=1) as pool:
        row = pool.submit(
            independent_call,
            lambda: outbox.enqueue_secret_message(
                kind="password_reset",
                key="v2:concurrent",
                to_email="only@example.invalid",
                secret="483921",
                secret_expires_at=timezone.now() + timedelta(minutes=10),
            ),
        ).result(timeout=10)
    entered, release = threading.Event(), threading.Event()

    def smtp(**kwargs):
        entered.set()
        assert release.wait(timeout=10)

    def worker():
        return independent_call(lambda: outbox.dispatch_message(message_id=row.pk))

    with (
        override_settings(TRANSACTIONAL_EMAIL_ENABLED=True),
        patch.object(outbox, "_send_email_via_provider", side_effect=smtp) as send,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        future = pool.submit(worker)
        try:
            assert entered.wait(timeout=10)
            assert outbox.dispatch_message(message_id=row.pk) == "busy"
            ordinary = obligation()
            with patch.object(
                outbox, "_xadd_email", return_value="ordinary-event"
            ) as publish:
                assert outbox.dispatch_message(message_id=ordinary.pk) == "transported"
                publish.assert_called_once()
        finally:
            release.set()
        assert future.result(timeout=10) == "dispatched"
        assert send.call_count == 1


@pytest.mark.django_db
def test_direct_smtp_rate_budget_preserves_attempts_and_obligation():
    OutboundMessage.objects.create(
        kind="kyc_status",
        key="v2:accepted",
        to_email="only@example.invalid",
        status="dispatched",
        dispatched_at=timezone.now(),
    )
    row = outbox.enqueue_secret_message(
        kind="password_reset",
        key="v2:rate",
        to_email="only@example.invalid",
        secret="483921",
        secret_expires_at=timezone.now() + timedelta(minutes=10),
    )
    with (
        override_settings(
            TRANSACTIONAL_EMAIL_ENABLED=True, EMAIL_RATE_LIMIT_PER_MINUTE=1
        ),
        patch.object(outbox, "_send_email_via_provider") as send,
    ):
        assert outbox.dispatch_message(message_id=row.pk) == "rate_limited"
        send.assert_not_called()
    row.refresh_from_db()
    assert row.status == "pending" and row.attempts == 0


@pytest.mark.django_db
def test_backlog_review_requires_authority():
    from django.core.exceptions import PermissionDenied

    row = obligation()
    actor = User.objects.create_user(username="unprivileged", password=None)
    with pytest.raises(PermissionDenied):
        review(
            message_id=row.pk,
            expected_fingerprint=fingerprint(row),
            action="release",
            actor=actor,
        )


@pytest.mark.django_db
def test_audit_reports_current_guest_payment_state_without_private_deal_details(client):
    from apps.deals.tests.phase4_factories import fund_scenario
    from apps.finance.models import PaymentAttempt

    scenario = fund_scenario(client, prefix="v2-audit-finance")
    attempt = PaymentAttempt.objects.filter(
        order__deal_id=scenario.deal.pk, status="succeeded"
    ).first()
    assert attempt
    row = outbox.enqueue_message(
        kind="guest_payment",
        key=f"guest_payment:attempt:{attempt.pk}:failed",
        to_email="guest@example.invalid",
        context={"status": "failed"},
    )
    report = classify(row)
    assert report["business_state"] == "payment_attempt:succeeded"
    assert "guest@example.invalid" not in json.dumps(report)
    assert attempt.status == "succeeded"


@pytest.mark.django_db
def test_missing_security_reference_never_reaches_smtp():
    row = OutboundMessage.objects.create(
        kind="password_reset", key="v2:missing-secret", to_email="only@example.invalid"
    )
    assert classify(row)["category"] == "obsolete"
    with (
        override_settings(TRANSACTIONAL_EMAIL_ENABLED=True),
        patch.object(outbox, "_send_email_via_provider") as send,
    ):
        assert outbox.dispatch_message(message_id=row.pk) == "unrenderable"
        send.assert_not_called()
    assert OutboundMessage.objects.get(pk=row.pk).status == "failed"


@pytest.mark.django_db
@pytest.mark.parametrize("identity", ["9" * 50, "١٢٣", "9223372036854775808"])
def test_malformed_handover_identity_fails_safely_in_audit_and_rendering(identity):
    row = OutboundMessage.objects.create(
        kind="recipient_delivery_code", key="v2:invalid-reference",
        to_email="only@example.invalid", secret_ref=f"handover_code:{identity}",
    )
    assert classify(row)["category"] == "obsolete"
    with pytest.raises(outbox.SecretUnavailable):
        outbox.render_parts(row)


@pytest.mark.django_db
@pytest.mark.parametrize("language", ["fr", "ar"])
def test_real_invitation_vault_preserves_explicit_locale_and_actual_expiry(language):
    from apps.admin_panel.services import create_admin_invitation
    from apps.admin_panel.serializers import AdminInvitationCreateSerializer

    actor = User.objects.create_superuser(username="v2-inviter", password=None)
    serializer = AdminInvitationCreateSerializer(
        data={
            "email": "only@example.invalid",
            "role": "support",
            "communication_language": language,
        }
    )
    assert serializer.is_valid(), serializer.errors
    invitation, token = create_admin_invitation(
        actor=actor,
        email=serializer.validated_data["email"],
        role="support",
        communication_language=serializer.validated_data["communication_language"],
        ttl=timedelta(hours=2),
    )
    message = OutboundMessage.objects.get(key=f"admin_invitation:{invitation.pk}")
    # The trusted public origin is deployment configuration, not a user URL.
    message.context["frontend_base_url"] = "https://app.example.invalid"
    subject, text, html = outbox.render_parts(message)
    assert message.language == language
    assert token in text and token in html
    assert format_utc_datetime(invitation.expires_at, language) in text
    if language == "ar":
        assert 'dir="rtl"' in html
    else:
        assert "invité" in subject.lower()
    assert token not in str(OutboundMessage.objects.get(pk=message.pk).context)


@pytest.mark.django_db
def test_unreviewed_mail_after_an_extended_outage_is_held():
    row = obligation()
    OutboundMessage.objects.filter(pk=row.pk).update(
        created_at=timezone.now() - timedelta(days=3)
    )
    with (
        override_settings(TRANSACTIONAL_EMAIL_ENABLED=True),
        patch.object(outbox, "_xadd_email") as send,
    ):
        assert outbox.dispatch_message(message_id=row.pk) == "activation_held"
        send.assert_not_called()


@pytest.mark.django_db
def test_real_django_smtp_timeout_preserves_a_retryable_obligation():
    with Sink(("127.0.0.1", 0), SMTPHandler) as server:
        server.messages = []
        server.rcpt_reply = b"250 accepted\r\n"
        server.greeting_delay = 0.2
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            row = outbox.enqueue_secret_message(
                kind="password_reset",
                key="v2:local-timeout",
                to_email="only@example.invalid",
                secret="483921",
                secret_expires_at=timezone.now() + timedelta(minutes=10),
            )
            with override_settings(
                TRANSACTIONAL_EMAIL_ENABLED=True,
                EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
                EMAIL_HOST="127.0.0.1",
                EMAIL_PORT=server.server_address[1],
                EMAIL_HOST_USER="",
                EMAIL_HOST_PASSWORD="",
                EMAIL_USE_TLS=False,
                EMAIL_TIMEOUT=0.05,
            ):
                with pytest.raises(outbox.EmailDeliveryError):
                    outbox.dispatch_message(message_id=row.pk)
                row.refresh_from_db()
                assert row.status == "pending" and row.last_error == "provider_transient"
                assert not server.messages
                server.greeting_delay = 0
                OutboundMessage.objects.filter(pk=row.pk).update(
                    next_attempt_at=timezone.now()
                )
                assert outbox.dispatch_message(message_id=row.pk) == "dispatched"
                assert len(server.messages) == 1
        finally:
            server.shutdown()
            thread.join(timeout=2)


@pytest.mark.django_db
def test_concurrent_secret_arming_preserves_one_vault_and_one_obligation(
    committed_mail,
):
    from concurrent.futures import ThreadPoolExecutor
    from django.db import connection, connections

    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL uniqueness and concurrent writers")
    barrier = threading.Barrier(2)

    def worker():
        try:
            barrier.wait(timeout=10)
            return outbox.enqueue_secret_message(
                kind="password_reset",
                key="v2:concurrent-arm",
                to_email="only@example.invalid",
                secret="483921",
                secret_expires_at=timezone.now() + timedelta(minutes=10),
            ).pk
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        identities = list(pool.map(lambda _: worker(), range(2)))
    assert identities[0] == identities[1]
    assert OutboundSecret.objects.filter(key="v2:concurrent-arm").count() == 1
    assert OutboundMessage.objects.filter(key="v2:concurrent-arm").count() == 1
