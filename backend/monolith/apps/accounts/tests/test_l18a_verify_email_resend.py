"""L18A: `POST /api/auth/verify-email/resend` sends a fresh email code.

The sign-up code expires and has an attempt cap, and posting a parcel now needs
a verified email, so a member must be able to ask again. Always 204; a verified
account is sent nothing; otherwise unused codes are retired and their pending
emails withdrawn, and one new code goes out through the sign-up outbox path.
"""

from __future__ import annotations

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from apps.accounts.models import EmailVerificationCode, User
from apps.notifications.models import OutboundMessage

URL = reverse("auth-verify-email-resend")
VERIFY_URL = reverse("auth-verify-email")
SIGN_UP_URL = reverse("auth-sign-up")


def _messages(user: User):
    return OutboundMessage.objects.filter(
        kind=OutboundMessage.Kind.EMAIL_VERIFICATION, recipient_user_id=user.pk
    )


class ResendVerificationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="l18a-resend@example.com",
            email="l18a-resend@example.com",
            password="Sup3rStrongPass!",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_sign_in_is_required(self):
        assert APIClient().post(URL).status_code == 401

    def test_a_fresh_code_replaces_the_old_one(self):
        old_row, old_code = EmailVerificationCode.issue(self.user)

        response = self.client.post(URL)

        assert response.status_code == 204
        old_row.refresh_from_db()
        assert old_row.used_at is not None
        live = self.user.email_verification_codes.filter(used_at__isnull=True)
        assert live.count() == 1
        message = _messages(self.user).get()
        assert message.key == f"email_verification:{live.get().pk}"
        assert message.status == OutboundMessage.Status.PENDING
        # The retired code no longer verifies anything.
        refused = APIClient().post(
            VERIFY_URL, {"email": self.user.email, "code": old_code}, format="json"
        )
        assert refused.status_code == 400
        self.user.refresh_from_db()
        assert self.user.is_email_verified is False

    def test_the_sign_up_email_still_waiting_is_withdrawn(self):
        signed_up = APIClient().post(
            SIGN_UP_URL,
            {
                "email": "l18a-signup@example.com",
                "password": "Sup3rStrongPass!",
                "full_name": "Sign Up",
                "phone": "+213555111333",
                "wilaya": "16",
            },
            format="json",
        )
        assert signed_up.status_code == 201, signed_up.data
        user = User.objects.get(email="l18a-signup@example.com")
        first = _messages(user).get()

        client = APIClient()
        client.force_authenticate(user=user)
        assert client.post(URL).status_code == 204

        first.refresh_from_db()
        assert first.status == OutboundMessage.Status.CANCELLED
        pending = _messages(user).filter(status=OutboundMessage.Status.PENDING)
        assert pending.count() == 1
        assert pending.get().pk != first.pk

    def test_a_verified_account_is_sent_nothing(self):
        User.objects.filter(pk=self.user.pk).update(is_email_verified=True)
        assert self.client.post(URL).status_code == 204
        assert not _messages(self.user).exists()
        assert not self.user.email_verification_codes.exists()

    def test_it_has_its_own_throttle(self):
        with patch.dict(
            ScopedRateThrottle.THROTTLE_RATES, {"email_verify_resend": "2/hour"}
        ):
            try:
                assert self.client.post(URL).status_code == 204
                assert self.client.post(URL).status_code == 204
                assert self.client.post(URL).status_code == 429
            finally:
                cache.clear()
