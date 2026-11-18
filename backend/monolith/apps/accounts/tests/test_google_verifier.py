"""Google sign-in must not hold a request slot for google-auth's 120s default."""

import logging
import threading
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from google.auth import exceptions as google_exceptions
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts import google


class BoundedTransportTests(SimpleTestCase):
    def test_every_certificate_fetch_uses_the_bounded_timeout(self):
        request = google._BoundedRequest(session=MagicMock())
        request.session.request.return_value = MagicMock(status_code=200)

        # google-auth's `_fetch_certs` calls with no timeout, which would
        # otherwise mean the library's 120-second default.
        request("https://www.googleapis.com/oauth2/v1/certs", method="GET")

        kwargs = request.session.request.call_args.kwargs
        assert kwargs["timeout"] == google.CERTS_TIMEOUT_SECONDS
        connect, read = google.CERTS_TIMEOUT_SECONDS
        assert connect + read <= 10

    def test_transport_is_reused_within_a_thread_and_not_shared_across(self):
        first = google._transport()
        assert google._transport() is first
        other: list = []
        worker = threading.Thread(target=lambda: other.append(google._transport()))
        worker.start()
        worker.join()
        assert other[0] is not first

    @override_settings(GOOGLE_OAUTH_CLIENT_IDS=["client-id"])
    def test_unreachable_google_is_unavailable_not_an_invalid_token(self):
        with patch.object(
            google.id_token,
            "verify_oauth2_token",
            side_effect=google_exceptions.TransportError("timed out"),
        ):
            with self.assertRaises(google.GoogleAuthUnavailable):
                google.verify_id_token("token")


class GoogleUnavailableViewTests(APITestCase):
    @patch("apps.accounts.views.verify_id_token")
    def test_google_outage_is_a_retryable_503(self, mock_verify):
        mock_verify.side_effect = google.GoogleAuthUnavailable(
            "Google sign-in is temporarily unavailable."
        )
        resp = self.client.post(
            reverse("auth-oauth-google"), {"id_token": "fake"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(resp.data["code"], "google_sign_in_unavailable")

    @override_settings(GOOGLE_OAUTH_CLIENT_IDS=[])
    def test_an_empty_client_list_answers_the_stable_code_and_asks_google_nothing(self):
        with patch.object(google.id_token, "verify_oauth2_token") as verify:
            resp = self.client.post(
                reverse("auth-oauth-google"), {"id_token": "fake"}, format="json"
            )
        self.assertEqual(resp.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(
            resp.data,
            {
                "code": "google_sign_in_unavailable",
                "detail": "Sign in with Google is not available right now.",
            },
        )
        verify.assert_not_called()


@override_settings(GOOGLE_OAUTH_CLIENT_IDS=["client-id"])
class GoogleRefusalTextTests(APITestCase):
    """A refusal is fixed text: never google-auth's message, the token or a claim."""

    TOKEN = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJzZWNyZXQtc3ViamVjdCJ9.c2lnbmF0dXJl"

    def post(self):
        with self.assertLogs(level="DEBUG") as logs:
            # A marker, so the capture holds at least one record.
            logging.getLogger(__name__).debug("google refusal")
            resp = self.client.post(
                reverse("auth-oauth-google"), {"id_token": self.TOKEN}, format="json"
            )
        for private in (self.TOKEN, "secret-subject", "someone-else", "evil.example"):
            self.assertNotIn(private, "\n".join(logs.output))
        return resp

    def test_the_librarys_error_text_is_not_echoed_or_logged(self):
        leaky = ValueError(f"Token used too late. Token: {self.TOKEN} sub=secret-subject")
        with patch.object(google.id_token, "verify_oauth2_token", side_effect=leaky):
            resp = self.post()
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(resp.data, {"detail": "The Google ID token is not valid."})

    def test_each_claim_refusal_is_fixed_text(self):
        claims = {"aud": "client-id", "iss": "https://accounts.google.com", "email_verified": True}
        cases = {
            "The Google ID token is not for this app.": {"aud": "someone-else"},
            "The Google ID token was not issued by Google.": {"iss": "https://evil.example"},
            "Google account email is not verified.": {"email_verified": False},
        }
        for detail, change in cases.items():
            with self.subTest(detail):
                with patch.object(
                    google.id_token, "verify_oauth2_token", return_value={**claims, **change}
                ):
                    resp = self.post()
                self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
                self.assertEqual(resp.data, {"detail": detail})
