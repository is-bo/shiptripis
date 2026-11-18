"""Sign in with Apple (plan EGS, Part B): the verifier and `POST /api/auth/oauth/apple`.

Every token is signed in the test by a local RSA key that `apple_support.serve_keys`
publishes as Apple's key set; nothing reaches Apple.
"""

from __future__ import annotations

import hashlib
import json
import socket
import time
from unittest.mock import patch
from urllib.error import URLError

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase
from rest_framework.throttling import ScopedRateThrottle

from apps.accounts import apple, google
from apps.accounts.models import OAuthIdentity, User

from .apple_support import (
    BUNDLE_ID,
    DROP,
    EMAIL,
    FOREIGN_KEY,
    KEY_ID,
    RAW_NONCE,
    SUBJECT,
    forged_token,
    hs256_with_public_key,
    identity_token,
    key_set,
    public_jwk,
    serve_keys,
    sha256_hex,
)

URL = reverse("auth-oauth-apple")
SIGN_UP = reverse("auth-sign-up")
PASSWORD = "Sup3rStrongPass!"


@override_settings(APPLE_SIGN_IN_CLIENT_IDS=[BUNDLE_ID])
class VerifierTests(SimpleTestCase):
    """`verify_identity_token` alone: what it accepts and what it refuses."""

    def setUp(self):
        self.opener = self.enterContext(serve_keys())

    def verify(self, token, nonce=RAW_NONCE):
        return apple.verify_identity_token(token, raw_nonce=nonce)

    def assertRefused(self, token, nonce=RAW_NONCE, message=None):
        with self.assertRaises(apple.AppleAuthError) as caught:
            self.verify(token, nonce)
        if message is not None:
            self.assertEqual(str(caught.exception), message)
        return caught.exception

    def test_a_valid_token_gives_its_claims(self):
        verified = self.verify(identity_token())
        self.assertEqual(verified["sub"], SUBJECT)
        self.assertEqual(verified["email"], EMAIL)
        self.assertIs(verified["email_verified"], True)
        self.assertEqual(verified["aud"], BUNDLE_ID)

    def test_the_nonce_is_the_sha256_hex_of_the_raw_nonce(self):
        self.assertEqual(
            apple.nonce_digest("abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )
        self.assertEqual(apple.nonce_digest(RAW_NONCE), hashlib.sha256(RAW_NONCE.encode()).hexdigest())

    def test_email_verified_as_the_string_true_is_normalized(self):
        self.assertIs(self.verify(identity_token(email_verified="true"))["email_verified"], True)

    def test_any_listed_audience_is_accepted(self):
        with override_settings(APPLE_SIGN_IN_CLIENT_IDS=["com.example.other", BUNDLE_ID]):
            self.assertEqual(self.verify(identity_token())["aud"], BUNDLE_ID)

    def test_the_clock_leeway_is_thirty_seconds(self):
        now = int(time.time())
        self.verify(identity_token(exp=now - 10, iat=now - 600))
        self.verify(identity_token(iat=now + 10))
        self.assertRefused(
            identity_token(exp=now - 60, iat=now - 600),
            message="The Apple identity token has expired.",
        )
        self.assertRefused(identity_token(iat=now + 120))

    def test_a_wrong_audience_is_refused(self):
        self.assertRefused(
            identity_token(aud="com.example.someone-else"),
            message="The Apple identity token is not for this app.",
        )

    def test_a_list_of_audiences_is_refused_even_when_it_names_ours(self):
        self.assertRefused(
            identity_token(aud=[BUNDLE_ID, "com.example.other"]),
            message="The Apple identity token is not for this app.",
        )

    def test_a_wrong_issuer_is_refused(self):
        for issuer in ("https://appleid.apple.com/", "appleid.apple.com", "https://evil.example"):
            with self.subTest(issuer):
                self.assertRefused(
                    identity_token(iss=issuer),
                    message="The Apple identity token was not issued by Apple.",
                )

    def test_alg_none_is_refused_without_fetching_keys(self):
        self.assertRefused(forged_token({"alg": "none", "kid": KEY_ID}))
        self.assertRefused(forged_token({"alg": "None", "kid": KEY_ID}))
        self.opener.open.assert_not_called()

    def test_hs256_keyed_with_apples_public_key_is_refused(self):
        self.assertRefused(hs256_with_public_key())
        self.opener.open.assert_not_called()

    def test_a_token_signed_by_another_key_is_refused(self):
        self.assertRefused(identity_token(key=FOREIGN_KEY))

    def test_an_unknown_or_missing_key_id_is_refused(self):
        self.assertRefused(identity_token(kid="a-key-apple-never-published"))
        self.assertRefused(identity_token(kid=None))

    def test_a_wrong_or_missing_nonce_is_refused(self):
        message = "The Apple identity token does not belong to this sign-in."
        self.assertRefused(identity_token(), nonce=RAW_NONCE + "x", message=message)
        self.assertRefused(identity_token(nonce=RAW_NONCE), message=message)
        self.assertRefused(identity_token(nonce=sha256_hex(RAW_NONCE).upper()), message=message)
        self.assertRefused(identity_token(nonce=DROP), message=message)
        self.assertRefused(identity_token(nonce=12345), message=message)
        self.assertRefused(identity_token(nonce="\u00e9" * 64), message=message)

    def test_an_unverified_email_is_refused(self):
        for value in (False, "false", DROP, 1, "True"):
            with self.subTest(value):
                self.assertRefused(
                    identity_token(email_verified=value),
                    message="Apple account email is not verified.",
                )

    def test_an_email_present_but_unverified_is_still_refused(self):
        self.assertRefused(
            identity_token(email="someone@example.com", email_verified=False),
            message="Apple account email is not verified.",
        )

    def test_a_token_without_an_email_passes_with_no_email(self):
        for verified in (DROP, False, True, "true"):
            with self.subTest(verified):
                claims = self.verify(identity_token(email=DROP, email_verified=verified))
                self.assertIsNone(claims["email"])
                self.assertIs(claims["email_verified"], False)
                self.assertEqual(claims["sub"], SUBJECT)
        claims = self.verify(identity_token(email=None, email_verified=DROP))
        self.assertEqual((claims["email"], claims["email_verified"]), (None, False))

    def test_every_required_claim_must_be_present(self):
        for claim in ("iss", "aud", "exp", "iat", "sub"):
            with self.subTest(claim):
                self.assertRefused(identity_token(**{claim: DROP}))
        self.assertRefused(identity_token(sub=""))

    def test_a_malformed_token_is_refused(self):
        for token in ("", "not-a-jwt", "a.b.c", identity_token()[:-20]):
            with self.subTest(token=token[:12]):
                self.assertRefused(token)

    def test_no_refusal_carries_the_token_the_nonce_or_a_claim(self):
        token = identity_token(aud="com.example.someone-else")
        refusal = self.assertRefused(token)
        for secret in (token, RAW_NONCE, sha256_hex(RAW_NONCE), EMAIL, SUBJECT):
            self.assertNotIn(secret, str(refusal))


class KeysTests(SimpleTestCase):
    """Apple's keys: fetched with a bounded timeout, cached, and an outage is a 503."""

    def test_the_keys_come_from_apple_with_a_bounded_timeout(self):
        with override_settings(APPLE_SIGN_IN_CLIENT_IDS=[BUNDLE_ID]), serve_keys() as opener:
            apple.verify_identity_token(identity_token(), raw_nonce=RAW_NONCE)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://appleid.apple.com/auth/keys")
        self.assertEqual(opener.open.call_args.kwargs["timeout"], apple.KEYS_TIMEOUT_SECONDS)
        # The same budget as Google's certificate fetch.
        self.assertLessEqual(apple.KEYS_TIMEOUT_SECONDS, max(google.CERTS_TIMEOUT_SECONDS))

    def test_the_key_set_is_cached_between_sign_ins(self):
        with override_settings(APPLE_SIGN_IN_CLIENT_IDS=[BUNDLE_ID]), serve_keys() as opener:
            for _ in range(3):
                apple.verify_identity_token(identity_token(), raw_nonce=RAW_NONCE)
        self.assertEqual(opener.open.call_count, 1)

    def test_the_process_client_is_bounded_and_caches_the_key_set(self):
        client = apple._keys
        self.assertEqual(client.uri, "https://appleid.apple.com/auth/keys")
        self.assertEqual(client.timeout, apple.KEYS_TIMEOUT_SECONDS)
        self.assertEqual(client.jwk_set_cache.lifespan, apple.KEYS_CACHE_SECONDS)

    def test_unreachable_apple_is_unavailable_not_an_invalid_token(self):
        failures = (
            URLError("unreachable"),
            socket.timeout("timed out"),
            ConnectionResetError("reset"),
        )
        for failure in failures:
            with (
                self.subTest(type(failure).__name__),
                override_settings(APPLE_SIGN_IN_CLIENT_IDS=[BUNDLE_ID]),
                serve_keys(error=failure),
                self.assertRaises(apple.AppleAuthUnavailable),
            ):
                apple.verify_identity_token(identity_token(), raw_nonce=RAW_NONCE)

    def test_an_unreadable_key_set_is_unavailable(self):
        bodies = (
            b"<html>busy</html>",
            b"[]",
            json.dumps({"keys": []}).encode(),
            json.dumps(key_set({**public_jwk(), "use": "enc"})).encode(),
        )
        for body in bodies:
            with (
                self.subTest(body=body[:16]),
                override_settings(APPLE_SIGN_IN_CLIENT_IDS=[BUNDLE_ID]),
                serve_keys(body),
                self.assertRaises(apple.AppleAuthUnavailable),
            ):
                apple.verify_identity_token(identity_token(), raw_nonce=RAW_NONCE)

    def test_not_configured_is_unavailable_and_asks_apple_nothing(self):
        with override_settings(APPLE_SIGN_IN_CLIENT_IDS=[]), serve_keys() as opener:
            with self.assertRaises(apple.AppleAuthUnavailable) as caught:
                apple.verify_identity_token(identity_token(), raw_nonce=RAW_NONCE)
        self.assertEqual(str(caught.exception), "Sign in with Apple is not available right now.")
        opener.open.assert_not_called()


@override_settings(APPLE_SIGN_IN_CLIENT_IDS=[BUNDLE_ID])
class AppleSignInViewTests(APITestCase):
    def setUp(self):
        self.opener = self.enterContext(serve_keys())

    def sign_in(self, token=None, *, nonce=RAW_NONCE, **body):
        return APIClient().post(
            URL,
            {"identity_token": token or identity_token(), "nonce": nonce, **body},
            format="json",
        )

    def assertNothingWritten(self):
        self.assertFalse(User.objects.exists())
        self.assertFalse(OAuthIdentity.objects.exists())

    def test_a_first_sign_in_opens_an_account_with_the_name_apple_gave(self):
        response = self.sign_in(
            full_name="  Amina Benali  ",
            phone="+33600000009",
            wilaya="16",
            preferred_language="fr",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(set(response.data), {"user", "access", "refresh"})
        user = User.objects.get(email=EMAIL)
        self.assertEqual(response.data["user"]["id"], user.pk)
        self.assertEqual(user.full_name, "Amina Benali")
        self.assertEqual((user.phone, user.wilaya, user.preferred_language), ("+33600000009", "16", "fr"))
        self.assertTrue(user.is_email_verified)
        self.assertFalse(user.has_usable_password())
        identity = OAuthIdentity.objects.get()
        self.assertEqual(
            (identity.user, identity.provider, identity.subject, identity.email_at_link),
            (user, "apple", SUBJECT, EMAIL),
        )

    def test_without_a_name_the_account_has_an_empty_name(self):
        response = self.sign_in()
        self.assertEqual(response.status_code, 200, response.data)
        user = User.objects.get(email=EMAIL)
        self.assertEqual(user.full_name, "")
        self.assertEqual(response.data["user"]["full_name"], "")
        self.assertEqual(user.preferred_language, "en")

    def test_a_known_identity_signs_in_with_a_token_without_an_email(self):
        first = self.sign_in(full_name="Amina Benali")
        again = self.sign_in(identity_token(email=DROP, email_verified=DROP))
        self.assertEqual(again.status_code, 200, again.data)
        self.assertEqual(again.data["user"]["id"], first.data["user"]["id"])
        self.assertEqual((User.objects.count(), OAuthIdentity.objects.count()), (1, 1))

    def test_an_unknown_identity_without_an_email_is_refused(self):
        response = self.sign_in(identity_token(email=DROP, email_verified=DROP))
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(
            response.data,
            {"code": "email_missing", "detail": "Apple account has no verified email."},
        )
        self.assertNothingWritten()

    def test_an_unknown_identity_with_an_unverified_email_is_refused(self):
        response = self.sign_in(identity_token(email_verified=False))
        self.assertEqual(response.status_code, 401, response.data)
        self.assertEqual(response.data, {"detail": "Apple account email is not verified."})
        self.assertNothingWritten()

    def test_a_returning_sign_in_fills_an_empty_name_only(self):
        self.sign_in()
        self.assertEqual(User.objects.get().full_name, "")
        filled = self.sign_in(full_name="  Amina Benali ")
        self.assertEqual(filled.status_code, 200, filled.data)
        self.assertEqual(filled.data["user"]["full_name"], "Amina Benali")
        again = self.sign_in(full_name="Someone Else")
        self.assertEqual(again.data["user"]["full_name"], "Amina Benali")
        self.assertEqual(User.objects.get().full_name, "Amina Benali")

    def test_a_returning_sign_in_uses_the_identity_and_changes_nothing(self):
        self.sign_in(full_name="Amina Benali")
        again = self.sign_in(identity_token(email="relay.changed@privaterelay.appleid.com"))
        self.assertEqual(again.status_code, 200, again.data)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(OAuthIdentity.objects.count(), 1)
        self.assertEqual(User.objects.get().full_name, "Amina Benali")

    def test_it_links_a_confirmed_account_with_the_same_email(self):
        owner = User.objects.create_user(
            username=EMAIL, email=EMAIL.upper(), password=PASSWORD, full_name="Amina Owner",
            phone="+213555000001", is_email_verified=True,
        )
        response = self.sign_in(full_name="Someone Else", phone="+33600000000")
        self.assertEqual(response.status_code, 200, response.data)
        owner.refresh_from_db()
        self.assertEqual(response.data["user"]["id"], owner.pk)
        self.assertEqual((owner.full_name, owner.phone), ("Amina Owner", "+213555000001"))
        self.assertTrue(owner.check_password(PASSWORD))
        self.assertEqual(OAuthIdentity.objects.get().user, owner)

    def test_it_claims_an_unconfirmed_account_with_the_same_email(self):
        opened = APIClient().post(
            SIGN_UP,
            {"email": EMAIL, "password": PASSWORD, "full_name": "Whoever Typed This",
             "phone": "+213555111444", "preferred_language": "fr"},
            format="json",
        )
        self.assertEqual(opened.status_code, 201, opened.data)

        response = self.sign_in(full_name="Real Owner", preferred_language="ar")

        self.assertEqual(response.status_code, 200, response.data)
        account = User.objects.get(email=EMAIL)
        self.assertTrue(account.is_email_verified)
        self.assertFalse(account.has_usable_password())
        self.assertEqual(
            (account.full_name, account.phone, account.preferred_language),
            ("Real Owner", "", "ar"),
        )
        stale = APIClient().post(
            reverse("auth-refresh"), {"refresh": opened.data["refresh"]}, format="json"
        )
        self.assertEqual(stale.status_code, 401)

    def test_a_claim_without_a_name_leaves_the_name_empty(self):
        User.objects.create_user(
            username=EMAIL, email=EMAIL, password=PASSWORD, full_name="Whoever Typed This"
        )
        self.assertEqual(self.sign_in().status_code, 200)
        self.assertEqual(User.objects.get(email=EMAIL).full_name, "")

    def test_every_refused_token_writes_nothing(self):
        now = int(time.time())
        refused = {
            "wrong audience": identity_token(aud="com.example.someone-else"),
            "wrong issuer": identity_token(iss="https://evil.example"),
            "alg none": forged_token({"alg": "none", "kid": KEY_ID}),
            "HS256": hs256_with_public_key(),
            "expired": identity_token(exp=now - 120, iat=now - 720),
            "unverified email": identity_token(email_verified=False),
            "missing sub": identity_token(sub=DROP),
            "foreign key": identity_token(key=FOREIGN_KEY),
        }
        for reason, token in refused.items():
            with self.subTest(reason):
                response = self.sign_in(token)
                self.assertEqual(response.status_code, 401, response.data)
                self.assertEqual(set(response.data), {"detail"})
        wrong_nonce = self.sign_in(identity_token(), nonce="a-different-raw-nonce-0001")
        self.assertEqual(wrong_nonce.status_code, 401)
        self.assertNothingWritten()

    def test_unreachable_apple_answers_the_stable_unavailable_code(self):
        with serve_keys(error=URLError("unreachable")):
            response = self.sign_in()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.data,
            {"code": "apple_sign_in_unavailable", "detail": "Sign in with Apple is temporarily unavailable."},
        )
        self.assertNothingWritten()

    @override_settings(APPLE_SIGN_IN_CLIENT_IDS=[])
    def test_an_empty_client_list_answers_the_stable_unavailable_code(self):
        response = self.sign_in()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.data,
            {"code": "apple_sign_in_unavailable", "detail": "Sign in with Apple is not available right now."},
        )
        self.opener.open.assert_not_called()
        self.assertNothingWritten()

    def test_the_body_is_validated(self):
        cases = {
            "no token": {"nonce": RAW_NONCE},
            "no nonce": {"identity_token": identity_token()},
            "short nonce": {"identity_token": identity_token(), "nonce": "too-short"},
            "long nonce": {"identity_token": identity_token(), "nonce": "n" * 129},
            "long name": {"identity_token": identity_token(), "nonce": RAW_NONCE, "full_name": "A" * 121},
            "bad wilaya": {"identity_token": identity_token(), "nonce": RAW_NONCE, "wilaya": "99"},
            "bad language": {"identity_token": identity_token(), "nonce": RAW_NONCE, "preferred_language": "de"},
            "huge token": {"identity_token": "x" * 8193, "nonce": RAW_NONCE},
        }
        for case, body in cases.items():
            with self.subTest(case):
                self.assertEqual(APIClient().post(URL, body, format="json").status_code, 400)
        self.opener.open.assert_not_called()
        self.assertNothingWritten()

    def test_the_nonce_is_never_trimmed(self):
        padded = f" {RAW_NONCE} "
        refused = self.sign_in(identity_token(), nonce=padded)
        self.assertEqual(refused.status_code, 401)
        accepted = self.sign_in(identity_token(nonce=sha256_hex(padded)), nonce=padded)
        self.assertEqual(accepted.status_code, 200, accepted.data)

    def test_it_has_its_own_throttle(self):
        cache.clear()
        self.addCleanup(cache.clear)
        with patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"apple_signin": "2/min"}):
            self.assertEqual(self.sign_in().status_code, 200)
            self.assertEqual(self.sign_in().status_code, 200)
            self.assertEqual(self.sign_in().status_code, 429)

    def test_the_route_reads_only_what_its_key_set_publishes(self):
        rotated = key_set(public_jwk(FOREIGN_KEY, kid="apple-test-key-2"))
        with serve_keys(rotated):
            self.assertEqual(self.sign_in().status_code, 401)
            self.assertEqual(
                self.sign_in(identity_token(key=FOREIGN_KEY, kid="apple-test-key-2")).status_code,
                200,
            )
