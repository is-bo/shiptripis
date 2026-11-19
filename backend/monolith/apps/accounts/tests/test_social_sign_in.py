"""The one social sign-in rule (plan EGS, decisions 12 and 13), for Google and Apple.

Both providers reach `apps.accounts.social.sign_in_with_identity` through their
own endpoint: Google with its verifier patched, Apple with a token signed by
the local key `apple_support` publishes.
"""

from __future__ import annotations

import threading
from unittest.mock import patch

from django.db import IntegrityError, connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts import social
from apps.accounts.models import OAuthIdentity, User

from .apple_support import BUNDLE_ID, RAW_NONCE, identity_token, serve_keys

GOOGLE_URL = reverse("auth-oauth-google")
APPLE_URL = reverse("auth-oauth-apple")
PASSWORD = "Sup3rStrongPass!"
EMAIL = "social.person@example.com"
SUBJECT = "social-subject-0001"


def google_sign_in(*, sub=SUBJECT, email=EMAIL, name="Social Person", **body):
    claims = {"sub": sub, "email": email, "email_verified": True}
    if name is not None:
        claims["name"] = name
    with patch("apps.accounts.views.verify_id_token", return_value=claims):
        return APIClient().post(GOOGLE_URL, {"id_token": "fake", **body}, format="json")


def apple_sign_in(*, sub=SUBJECT, email=EMAIL, name="Social Person", **body):
    if name is not None:
        body["full_name"] = name
    return APIClient().post(
        APPLE_URL,
        {"identity_token": identity_token(sub=sub, email=email), "nonce": RAW_NONCE, **body},
        format="json",
    )


PROVIDERS = {"google": google_sign_in, "apple": apple_sign_in}


@override_settings(APPLE_SIGN_IN_CLIENT_IDS=[BUNDLE_ID])
class SwitchedOffAccountTests(TestCase):
    """A banned or disabled account gets no token, by identity or by email."""

    def setUp(self):
        self.enterContext(serve_keys())

    def account(self, *, verified=True):
        return User.objects.create_user(
            username=EMAIL,
            email=EMAIL,
            password=PASSWORD,
            full_name="Whoever Holds It",
            phone="+213555000123",
            is_email_verified=verified,
        )

    def switch_off(self, user, how):
        change = {"banned": {"is_banned": True}, "inactive": {"is_active": False}}[how]
        User.objects.filter(pk=user.pk).update(**change)

    def assertRefused(self, response):
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(
            response.data, {"code": "account_disabled", "detail": "This account is disabled."}
        )

    def test_a_known_identity_of_a_switched_off_account_is_refused(self):
        for provider, sign_in in PROVIDERS.items():
            for how in ("banned", "inactive"):
                with self.subTest(provider=provider, how=how):
                    user = self.account()
                    OAuthIdentity.objects.create(user=user, provider=provider, subject=SUBJECT)
                    self.switch_off(user, how)

                    self.assertRefused(sign_in())
                    user.delete()

    def test_a_switched_off_account_is_not_linked_or_claimed_by_email(self):
        for provider, sign_in in PROVIDERS.items():
            for how in ("banned", "inactive"):
                for verified in (True, False):
                    with self.subTest(provider=provider, how=how, verified=verified):
                        user = self.account(verified=verified)
                        self.switch_off(user, how)
                        before = User.objects.values().get(pk=user.pk)

                        self.assertRefused(sign_in(name="Someone Else", phone="+33600000000"))

                        self.assertEqual(User.objects.values().get(pk=user.pk), before)
                        self.assertFalse(OAuthIdentity.objects.exists())
                        user.delete()

    def test_a_restored_account_signs_in_again(self):
        for provider, sign_in in PROVIDERS.items():
            with self.subTest(provider):
                user = self.account()
                self.switch_off(user, "banned")
                self.assertRefused(sign_in())
                User.objects.filter(pk=user.pk).update(is_banned=False, is_active=True)
                response = sign_in()
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data["user"]["id"], user.pk)
                user.delete()


@override_settings(APPLE_SIGN_IN_CLIENT_IDS=[BUNDLE_ID])
class NameTests(TestCase):
    """No name from the provider means an empty name, never the email's local part."""

    def setUp(self):
        self.enterContext(serve_keys())

    def test_a_new_account_without_a_name_has_an_empty_name(self):
        for provider, sign_in in PROVIDERS.items():
            for name in (None, "", "   "):
                with self.subTest(provider=provider, name=name):
                    response = sign_in(name=name)
                    self.assertEqual(response.status_code, 200, response.data)
                    self.assertEqual(User.objects.get(email=EMAIL).full_name, "")
                    User.objects.all().delete()

    def test_a_provider_name_is_trimmed_and_bounded(self):
        response = google_sign_in(name="  " + "N" * 130 + "  ")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(User.objects.get(email=EMAIL).full_name, "N" * 120)

    def test_a_claim_without_a_name_empties_what_the_stranger_typed(self):
        for provider, sign_in in PROVIDERS.items():
            with self.subTest(provider):
                User.objects.create_user(
                    username=EMAIL, email=EMAIL, password=PASSWORD, full_name="Whoever Typed This"
                )
                self.assertEqual(sign_in(name=None).status_code, 200)
                self.assertEqual(User.objects.get(email=EMAIL).full_name, "")
                User.objects.all().delete()


class RuleTests(TestCase):
    """`sign_in_with_identity` itself, for what a verifier cannot rule out."""

    DATA = {"preferred_language": "en"}

    def sign_in(self, **overrides):
        values = {
            "provider": OAuthIdentity.Provider.GOOGLE,
            "subject": SUBJECT,
            "email": EMAIL,
            "email_verified": True,
            "name": "Social Person",
            "data": self.DATA,
        }
        values.update(overrides)
        return social.sign_in_with_identity(**values)

    def assertRefused(self, status, code, **overrides):
        with self.assertRaises(social.SocialSignInRefused) as caught:
            self.sign_in(**overrides)
        self.assertEqual((caught.exception.status, caught.exception.payload["code"]), (status, code))
        self.assertFalse(User.objects.exists())
        self.assertFalse(OAuthIdentity.objects.exists())
        return caught.exception

    def test_a_subject_must_be_a_real_identifier(self):
        for subject in (None, "", 123, "s" * 129):
            with self.subTest(subject=subject):
                self.assertRefused(401, "identity_invalid", subject=subject)

    def test_linking_needs_a_verified_email(self):
        refusal = self.assertRefused(401, "email_not_verified", email_verified=False)
        self.assertEqual(refusal.payload["detail"], "Google account email is not verified.")
        self.assertRefused(401, "email_not_verified", email_verified="true")
        refusal = self.assertRefused(
            400, "email_missing", provider=OAuthIdentity.Provider.APPLE, email=None
        )
        self.assertEqual(refusal.payload["detail"], "Apple account has no verified email.")
        self.assertRefused(400, "email_missing", email="   ")

    def test_the_email_is_compared_without_case_and_stored_lower_case(self):
        owner = User.objects.create_user(
            username="owner", email="Social.Person@Example.com", password=PASSWORD,
            is_email_verified=True,
        )
        self.assertEqual(self.sign_in(email="  SOCIAL.PERSON@example.COM "), owner)
        self.assertEqual(OAuthIdentity.objects.get().email_at_link, EMAIL)

    def test_the_same_email_links_each_provider_to_one_account(self):
        google_user = self.sign_in()
        apple_user = self.sign_in(provider=OAuthIdentity.Provider.APPLE, subject="apple-sub")
        self.assertEqual(google_user, apple_user)
        self.assertEqual(
            sorted(OAuthIdentity.objects.values_list("provider", flat=True)), ["apple", "google"]
        )

    def test_a_known_identity_signs_in_without_its_email(self):
        user = self.sign_in()
        self.assertEqual(self.sign_in(email=None, email_verified=False), user)

    def test_no_email_is_refused_as_missing_before_the_verified_flag_is_read(self):
        for email in (None, ""):
            with self.subTest(email=email):
                self.assertRefused(400, "email_missing", email=email, email_verified=False)

    def test_a_known_identity_with_an_empty_name_takes_the_next_name_once(self):
        user = self.sign_in(name="")
        self.assertEqual(user.full_name, "")
        self.assertEqual(self.sign_in(name="  ").full_name, "")
        filled = self.sign_in(name="Later Name", email=None, email_verified=False)
        self.assertEqual(filled.full_name, "Later Name")
        self.assertEqual(self.sign_in(name="Another Name").full_name, "Later Name")
        user.refresh_from_db()
        self.assertEqual(user.full_name, "Later Name")

    def test_a_linked_confirmed_account_with_an_empty_name_takes_the_providers_name(self):
        owner = User.objects.create_user(
            username=EMAIL, email=EMAIL, password=PASSWORD, is_email_verified=True
        )
        self.assertEqual(self.sign_in(name="Social Person"), owner)
        owner.refresh_from_db()
        self.assertEqual(owner.full_name, "Social Person")
        self.assertTrue(owner.check_password(PASSWORD))

    def test_a_set_name_is_never_overwritten(self):
        owner = User.objects.create_user(
            username=EMAIL, email=EMAIL, password=PASSWORD, full_name="Owner Name",
            is_email_verified=True,
        )
        self.sign_in(name="Social Person")
        self.sign_in(name="Social Person Again")
        owner.refresh_from_db()
        self.assertEqual(owner.full_name, "Owner Name")

    def test_a_switched_off_account_is_refused_before_its_name_is_filled(self):
        user = self.sign_in(name="")
        User.objects.filter(pk=user.pk).update(is_banned=True)
        with self.assertRaises(social.SocialSignInRefused):
            self.sign_in(name="Late Name")
        user.refresh_from_db()
        self.assertEqual(user.full_name, "")

    def test_losing_the_identity_race_resolves_to_the_identity_that_won(self):
        winner = User.objects.create_user(
            username=EMAIL, email=EMAIL, password=PASSWORD, is_email_verified=True
        )
        OAuthIdentity.objects.create(user=winner, provider="google", subject=SUBJECT)
        real = social._linked_identity
        # The first look misses the identity a concurrent sign-in had not yet
        # committed; the insert then meets it.
        with patch.object(
            social, "_linked_identity", side_effect=[None, real(provider="google", subject=SUBJECT)]
        ) as looked:
            self.assertEqual(self.sign_in(), winner)
        self.assertEqual(looked.call_count, 2)
        self.assertEqual(OAuthIdentity.objects.count(), 1)

    def test_losing_the_account_race_links_the_account_that_won(self):
        winner = User.objects.create_user(
            username=EMAIL, email=EMAIL, password=PASSWORD, is_email_verified=True
        )
        real = social._locked_account
        with patch.object(
            social, "_locked_account", side_effect=[None, real(email=EMAIL)]
        ) as looked:
            self.assertEqual(self.sign_in(), winner)
        self.assertEqual(looked.call_count, 2)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(OAuthIdentity.objects.get().user, winner)

    def test_an_integrity_error_that_is_not_a_race_is_not_retried_forever(self):
        with (
            patch.object(
                social.OAuthIdentity.objects, "create", side_effect=IntegrityError("broken")
            ) as created,
            self.assertRaises(IntegrityError),
        ):
            self.sign_in()
        self.assertEqual(created.call_count, 3)
        # Every attempt was rolled back whole: not even the account stayed.
        self.assertFalse(User.objects.exists())


@override_settings(APPLE_SIGN_IN_CLIENT_IDS=[BUNDLE_ID])
class ConcurrentFirstSignInTests(TransactionTestCase):
    """Two first sign-ins for one subject, at the same moment, in two threads."""

    def race(self, sign_in):
        # Both requests have looked and found no identity and no account
        # before either inserts anything.
        barrier = threading.Barrier(2, timeout=10)
        real = social._open_account

        def open_account_together(**kwargs):
            barrier.wait()
            return real(**kwargs)

        answers, failures = [], []

        def run():
            try:
                answers.append(sign_in())
            except Exception as exc:  # pragma: no cover - reported below
                failures.append(exc)
            finally:
                connection.close()

        with patch.object(social, "_open_account", side_effect=open_account_together):
            threads = [threading.Thread(target=run) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
        self.assertEqual(failures, [])
        return answers

    def assertOneAccountAndOneIdentity(self, answers, provider):
        self.assertEqual([answer.status_code for answer in answers], [200, 200], answers)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(OAuthIdentity.objects.filter(provider=provider).count(), 1)
        user = User.objects.get()
        self.assertEqual({answer.data["user"]["id"] for answer in answers}, {user.pk})
        self.assertEqual(OAuthIdentity.objects.get().user, user)

    def test_google(self):
        claims = {"sub": SUBJECT, "email": EMAIL, "email_verified": True, "name": "Social Person"}
        # Patched once, here: two threads entering and leaving one patch could
        # leave the fake verifier installed for every later test.
        with patch("apps.accounts.views.verify_id_token", return_value=claims):
            answers = self.race(
                lambda: APIClient().post(GOOGLE_URL, {"id_token": "fake"}, format="json")
            )
        self.assertOneAccountAndOneIdentity(answers, "google")

    def test_apple(self):
        with serve_keys():
            answers = self.race(apple_sign_in)
        self.assertOneAccountAndOneIdentity(answers, "apple")
