"""L18A item 5: proving the email ends what an unproven person held.

Anyone can sign up with someone else's address. The moment the address is
proved (Google sign-in on an unconfirmed account, or a completed password
reset), `end_all_sessions` revokes every refresh token and switches off every
push device, the password is the prover's, and the email is confirmed.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import PasswordResetCode, User
from apps.accounts.sessions import end_all_sessions
from apps.notifications.models import PushDevice
from apps.notifications.push import register_push_device

SIGN_UP = reverse("auth-sign-up")
SIGN_IN = reverse("auth-sign-in")
REFRESH = reverse("auth-refresh")
GOOGLE = reverse("auth-oauth-google")
RESET = reverse("auth-password-reset-confirm")
PASSWORD = "Sup3rStrongPass!"


class Account:
    """An account opened over HTTP, with a live refresh token and a phone."""

    def __init__(self, email: str, *, phone: str = "+213555111444"):
        response = APIClient().post(
            SIGN_UP,
            {
                "email": email,
                "password": PASSWORD,
                "full_name": "Whoever Typed This",
                "phone": phone,
                "wilaya": "16",
                "preferred_language": "fr",
            },
            format="json",
        )
        assert response.status_code == 201, response.data
        self.user = User.objects.get(email=email)
        self.refresh = response.data["refresh"]
        self.device = register_push_device(
            user=self.user,
            token=f"fcm-token-{uuid.uuid4().hex}",
            installation_id=uuid.uuid4(),
            platform="android",
        )

    def refresh_works(self) -> bool:
        return APIClient().post(REFRESH, {"refresh": self.refresh}, format="json").status_code == 200

    def password_works(self, password: str = PASSWORD) -> bool:
        response = APIClient().post(
            SIGN_IN, {"email": self.user.email, "password": password}, format="json"
        )
        return response.status_code == 200

    def device_active(self) -> bool:
        return PushDevice.objects.get(pk=self.device.pk).active


def google(email: str, **extra):
    payload = {"sub": f"sub-{email}", "email": email, "email_verified": True, "name": "Real Owner"}
    with patch("apps.accounts.views.verify_id_token", return_value=payload):
        return APIClient().post(GOOGLE, {"id_token": "fake", **extra}, format="json")


class EndAllSessionsTests(TestCase):
    def test_it_revokes_refresh_tokens_and_devices_of_that_account_only(self):
        mine = Account("l18a-mine@example.com")
        theirs = Account("l18a-theirs@example.com", phone="+213555111555")

        end_all_sessions(mine.user)

        assert mine.refresh_works() is False
        assert mine.device_active() is False
        assert theirs.refresh_works() is True
        assert theirs.device_active() is True

    def test_it_can_run_twice(self):
        mine = Account("l18a-twice@example.com")
        end_all_sessions(mine.user)
        end_all_sessions(mine.user)
        assert mine.refresh_works() is False


class GoogleClaimTests(TestCase):
    def test_google_claims_an_unconfirmed_account_from_whoever_opened_it(self):
        squatter = Account("l18a-owner@example.com")

        response = google(
            "l18a-owner@example.com",
            phone="+33600000001",
            wilaya="",
            preferred_language="ar",
        )

        assert response.status_code == 200, response.data
        assert squatter.refresh_works() is False
        assert squatter.device_active() is False
        assert squatter.password_works() is False
        account = User.objects.get(pk=squatter.user.pk)
        assert account.is_email_verified is True
        assert account.has_usable_password() is False
        # What the unproven person typed is replaced, as for a new account.
        assert account.full_name == "Real Owner"
        assert account.phone == "+33600000001"
        assert account.wilaya == ""
        assert account.preferred_language == "ar"
        assert account.is_phone_verified is False
        # The owner's own new session works.
        assert APIClient().post(
            REFRESH, {"refresh": response.data["refresh"]}, format="json"
        ).status_code == 200

    def test_a_claim_clears_a_phone_flag_the_stranger_held(self):
        squatter = Account("l18a-phone@example.com")
        User.objects.filter(pk=squatter.user.pk).update(is_phone_verified=True)
        assert google("l18a-phone@example.com").status_code == 200
        account = User.objects.get(pk=squatter.user.pk)
        assert (account.is_phone_verified, account.phone) == (False, "")

    def test_a_confirmed_account_links_google_and_nothing_of_it_changes(self):
        owner = Account("l18a-confirmed@example.com")
        User.objects.filter(pk=owner.user.pk).update(is_email_verified=True)
        before = User.objects.values(
            "full_name", "phone", "wilaya", "preferred_language", "is_phone_verified", "password"
        ).get(pk=owner.user.pk)

        assert google("l18a-confirmed@example.com", phone="+33600000002").status_code == 200

        after = User.objects.values(
            "full_name", "phone", "wilaya", "preferred_language", "is_phone_verified", "password"
        ).get(pk=owner.user.pk)
        assert after == before
        assert owner.refresh_works() is True
        assert owner.device_active() is True
        assert owner.password_works() is True


class PasswordResetEndsSessionsTests(TestCase):
    def reset(self, account: Account, new_password: str = "BrandNewPass99!"):
        _, code = PasswordResetCode.issue(account.user)
        return APIClient().post(
            RESET,
            {"email": account.user.email, "code": code, "new_password": new_password},
            format="json",
        )

    def test_a_reset_ends_every_older_session_and_confirms_the_email(self):
        account = Account("l18a-reset@example.com")

        assert self.reset(account).status_code == 204

        assert account.refresh_works() is False
        assert account.device_active() is False
        assert account.password_works() is False
        assert account.password_works("BrandNewPass99!") is True
        assert User.objects.get(pk=account.user.pk).is_email_verified is True

    def test_a_confirmed_account_is_signed_out_everywhere_too(self):
        account = Account("l18a-reset-confirmed@example.com")
        User.objects.filter(pk=account.user.pk).update(is_email_verified=True)

        assert self.reset(account).status_code == 204

        assert account.refresh_works() is False
        assert account.device_active() is False

    def test_a_wrong_code_changes_nothing(self):
        account = Account("l18a-reset-wrong@example.com")
        _, code = PasswordResetCode.issue(account.user)
        wrong = "000000" if code != "000000" else "111111"
        response = APIClient().post(
            RESET,
            {"email": account.user.email, "code": wrong, "new_password": "BrandNewPass99!"},
            format="json",
        )
        assert response.status_code == 400
        assert account.refresh_works() is True
        assert account.device_active() is True
        assert account.password_works() is True
        assert User.objects.get(pk=account.user.pk).is_email_verified is False
