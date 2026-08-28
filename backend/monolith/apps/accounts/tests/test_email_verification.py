"""EmailVerificationCode model + signup verify-email flow.

The email is armed as a PostgreSQL-backed outbound obligation; tests patch the
outbox boundary so no real Redis/SMTP is needed.
"""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import EmailVerificationCode, User
from apps.notifications.models import OutboundMessage

SIGN_UP_PAYLOAD = {
    "full_name": "Amina Test",
    "email": "amina@example.com",
    "password": "Sup3rStrongPass!",
    "phone": "+213555111222",
    "wilaya": "16",
}


def _make_user(email: str = "verify@example.com") -> User:
    user = User(email=email, username=email, full_name="V User")
    user.set_password("Sup3rStrongPass!")
    user.save()
    return user


class EmailVerificationCodeModelTests(TestCase):
    def test_issue_returns_plaintext_and_active_row(self):
        user = _make_user()
        obj, plaintext = EmailVerificationCode.issue(user)
        assert len(plaintext) == 6 and plaintext.isdigit()
        assert obj.is_active()
        # Stored as a hash, never the plaintext.
        assert obj.code_hash != plaintext

    def test_verify_correct_code_marks_used(self):
        user = _make_user()
        obj, plaintext = EmailVerificationCode.issue(user)
        assert obj.verify(plaintext) is True
        obj.refresh_from_db()
        assert obj.used_at is not None
        # A used code is no longer active and cannot be replayed.
        assert obj.is_active() is False
        assert obj.verify(plaintext) is False

    def test_verify_wrong_code_increments_attempts(self):
        user = _make_user()
        obj, _ = EmailVerificationCode.issue(user)
        assert obj.verify("000000") is False
        obj.refresh_from_db()
        assert obj.attempts == 1
        assert obj.used_at is None

    @override_settings(EMAIL_VERIFY_MAX_ATTEMPTS=3)
    def test_locks_after_max_attempts(self):
        user = _make_user()
        obj, plaintext = EmailVerificationCode.issue(user)
        for _ in range(3):
            obj.verify("000000")
        obj.refresh_from_db()
        # Attempts exhausted → inactive even with the right code.
        assert obj.is_active() is False
        assert obj.verify(plaintext) is False

    def test_expired_code_is_inactive(self):
        user = _make_user()
        obj, plaintext = EmailVerificationCode.issue(user)
        obj.expires_at = timezone.now() - timedelta(seconds=1)
        obj.save(update_fields=("expires_at",))
        assert obj.is_active() is False
        assert obj.verify(plaintext) is False


class SignUpEnqueuesVerifyEmailTests(TransactionTestCase):
    """Signup must issue a verify code and XADD a verify email after commit."""

    url = reverse("auth-sign-up")

    def test_signup_issues_code_and_arms_durable_email(self):
        with patch("apps.accounts.views.enqueue_secret_message") as enqueue:
            resp = self.client.post(self.url, SIGN_UP_PAYLOAD, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        user = User.objects.get(email=SIGN_UP_PAYLOAD["email"])
        assert user.is_email_verified is False
        assert EmailVerificationCode.objects.filter(user=user).count() == 1
        enqueue.assert_called_once()
        assert enqueue.call_args.kwargs["kind"] == OutboundMessage.Kind.EMAIL_VERIFICATION
        assert enqueue.call_args.kwargs["to_email"] == SIGN_UP_PAYLOAD["email"]

    def test_signup_still_succeeds_returns_tokens(self):
        with patch("apps.accounts.views.enqueue_secret_message"):
            resp = self.client.post(self.url, SIGN_UP_PAYLOAD, format="json")
        assert "access" in resp.data
        assert "refresh" in resp.data


class VerifyEmailEndpointTests(APITestCase):
    url = reverse("auth-verify-email")

    def test_valid_code_sets_is_email_verified(self):
        user = _make_user(email=SIGN_UP_PAYLOAD["email"])
        _, plaintext = EmailVerificationCode.issue(user)
        resp = self.client.post(
            self.url,
            {"email": user.email, "code": plaintext},
            format="json",
        )
        assert resp.status_code == status.HTTP_204_NO_CONTENT
        user.refresh_from_db()
        assert user.is_email_verified is True

    def test_invalid_code_rejected(self):
        user = _make_user(email=SIGN_UP_PAYLOAD["email"])
        EmailVerificationCode.issue(user)
        resp = self.client.post(
            self.url,
            {"email": user.email, "code": "000000"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        user.refresh_from_db()
        assert user.is_email_verified is False

    def test_unknown_email_returns_400(self):
        resp = self.client.post(
            self.url,
            {"email": "nobody@example.com", "code": "123456"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_already_verified_is_idempotent_ok(self):
        user = _make_user(email=SIGN_UP_PAYLOAD["email"])
        user.is_email_verified = True
        user.save(update_fields=("is_email_verified",))
        _, plaintext = EmailVerificationCode.issue(user)
        resp = self.client.post(
            self.url,
            {"email": user.email, "code": plaintext},
            format="json",
        )
        assert resp.status_code == status.HTTP_204_NO_CONTENT
