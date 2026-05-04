from unittest.mock import patch

from django.core import mail
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import OAuthIdentity, PasswordResetCode, User


SIGN_UP_PAYLOAD = {
    "full_name": "Amina Test",
    "email": "amina@example.com",
    "password": "Sup3rStrongPass!",
    "phone": "+213555111222",
    "wilaya": "16",  # Alger
}


class SignUpTests(APITestCase):
    url = reverse("auth-sign-up")

    def test_happy_path_creates_user_and_returns_tokens(self):
        resp = self.client.post(self.url, SIGN_UP_PAYLOAD, format="json")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertIn("access", resp.data)
        self.assertIn("refresh", resp.data)
        self.assertEqual(resp.data["user"]["email"], SIGN_UP_PAYLOAD["email"])
        user = User.objects.get(email=SIGN_UP_PAYLOAD["email"])
        self.assertTrue(user.check_password(SIGN_UP_PAYLOAD["password"]))
        self.assertEqual(user.wilaya, "16")

    def test_duplicate_email_rejected(self):
        self.client.post(self.url, SIGN_UP_PAYLOAD, format="json")
        resp = self.client.post(self.url, SIGN_UP_PAYLOAD, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", resp.data)

    def test_invalid_wilaya_rejected(self):
        payload = {**SIGN_UP_PAYLOAD, "wilaya": "99"}
        resp = self.client.post(self.url, payload, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("wilaya", resp.data)


class SignInTests(APITestCase):
    sign_in_url = reverse("auth-sign-in")

    def setUp(self):
        self.client.post(reverse("auth-sign-up"), SIGN_UP_PAYLOAD, format="json")

    def test_happy_path(self):
        resp = self.client.post(
            self.sign_in_url,
            {"email": SIGN_UP_PAYLOAD["email"], "password": SIGN_UP_PAYLOAD["password"]},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("access", resp.data)

    def test_wrong_password(self):
        resp = self.client.post(
            self.sign_in_url,
            {"email": SIGN_UP_PAYLOAD["email"], "password": "wrong-password"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class SignOutTests(APITestCase):
    def setUp(self):
        resp = self.client.post(reverse("auth-sign-up"), SIGN_UP_PAYLOAD, format="json")
        self.access = resp.data["access"]
        self.refresh = resp.data["refresh"]

    def test_blacklists_refresh_token(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access}")
        resp = client.post(
            reverse("auth-sign-out"), {"refresh": self.refresh}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_205_RESET_CONTENT)

        # Refresh now blacklisted: trying to refresh should fail.
        resp = self.client.post(
            reverse("auth-refresh"), {"refresh": self.refresh}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_refresh_returns_400(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access}")
        resp = client.post(reverse("auth-sign-out"), {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class PasswordResetTests(APITestCase):
    request_url = reverse("auth-password-reset-request")
    confirm_url = reverse("auth-password-reset-confirm")

    def setUp(self):
        self.client.post(reverse("auth-sign-up"), SIGN_UP_PAYLOAD, format="json")
        mail.outbox = []

    def test_request_for_known_email_sends_mail_and_returns_202(self):
        resp = self.client.post(
            self.request_url, {"email": SIGN_UP_PAYLOAD["email"]}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(PasswordResetCode.objects.count(), 1)

    def test_request_for_unknown_email_still_returns_202(self):
        resp = self.client.post(
            self.request_url, {"email": "nobody@example.com"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(PasswordResetCode.objects.count(), 0)

    def test_confirm_with_valid_code_updates_password(self):
        user = User.objects.get(email=SIGN_UP_PAYLOAD["email"])
        _, plaintext = PasswordResetCode.issue(user)

        new_password = "BrandNewPass99!"
        resp = self.client.post(
            self.confirm_url,
            {
                "email": SIGN_UP_PAYLOAD["email"],
                "code": plaintext,
                "new_password": new_password,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        user.refresh_from_db()
        self.assertTrue(user.check_password(new_password))

    def test_confirm_with_invalid_code_rejected(self):
        user = User.objects.get(email=SIGN_UP_PAYLOAD["email"])
        PasswordResetCode.issue(user)

        resp = self.client.post(
            self.confirm_url,
            {
                "email": SIGN_UP_PAYLOAD["email"],
                "code": "000000",
                "new_password": "BrandNewPass99!",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_confirm_unknown_email_returns_400(self):
        resp = self.client.post(
            self.confirm_url,
            {
                "email": "nobody@example.com",
                "code": "123456",
                "new_password": "BrandNewPass99!",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class GoogleOAuthTests(APITestCase):
    url = reverse("auth-oauth-google")

    @patch("apps.accounts.views.verify_id_token")
    def test_first_time_creates_user_and_identity(self, mock_verify):
        mock_verify.return_value = {
            "sub": "google-sub-12345",
            "email": "newuser@example.com",
            "email_verified": True,
            "name": "New User",
        }
        resp = self.client.post(
            self.url,
            {"id_token": "fake", "phone": "+213555000111", "wilaya": "31"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("access", resp.data)

        user = User.objects.get(email="newuser@example.com")
        self.assertEqual(user.wilaya, "31")
        self.assertTrue(user.is_email_verified)
        self.assertFalse(user.has_usable_password())

        identity = OAuthIdentity.objects.get(subject="google-sub-12345")
        self.assertEqual(identity.user, user)
        self.assertEqual(identity.provider, OAuthIdentity.Provider.GOOGLE)

    @patch("apps.accounts.views.verify_id_token")
    def test_returning_user_reuses_existing_identity(self, mock_verify):
        mock_verify.return_value = {
            "sub": "google-sub-12345",
            "email": "newuser@example.com",
            "email_verified": True,
            "name": "New User",
        }
        self.client.post(self.url, {"id_token": "fake"}, format="json")
        self.client.post(self.url, {"id_token": "fake"}, format="json")
        self.assertEqual(User.objects.filter(email="newuser@example.com").count(), 1)
        self.assertEqual(OAuthIdentity.objects.count(), 1)

    @patch("apps.accounts.views.verify_id_token")
    def test_links_existing_email_account(self, mock_verify):
        self.client.post(reverse("auth-sign-up"), SIGN_UP_PAYLOAD, format="json")
        mock_verify.return_value = {
            "sub": "google-sub-67890",
            "email": SIGN_UP_PAYLOAD["email"],
            "email_verified": True,
            "name": "Amina Test",
        }
        resp = self.client.post(self.url, {"id_token": "fake"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(User.objects.filter(email=SIGN_UP_PAYLOAD["email"]).count(), 1)
        self.assertEqual(OAuthIdentity.objects.count(), 1)

    @patch("apps.accounts.views.verify_id_token")
    def test_invalid_token_rejected(self, mock_verify):
        from apps.accounts.google import GoogleAuthError

        mock_verify.side_effect = GoogleAuthError("bad token")
        resp = self.client.post(self.url, {"id_token": "fake"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class MeTests(APITestCase):
    url = reverse("me")

    def test_unauthenticated_rejected(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authenticated_returns_profile(self):
        resp = self.client.post(reverse("auth-sign-up"), SIGN_UP_PAYLOAD, format="json")
        access = resp.data["access"]
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        resp = client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["email"], SIGN_UP_PAYLOAD["email"])
        self.assertEqual(resp.data["full_name"], SIGN_UP_PAYLOAD["full_name"])
        self.assertEqual(resp.data["wilaya"], "16")
