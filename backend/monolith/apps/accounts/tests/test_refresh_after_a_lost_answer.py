"""S2: a token refresh survives a lost answer.

Every refresh rotates the refresh token and blacklists the one presented. When
the answer is lost on a weak network, the phone still holds the token it sent
and presents it again. Of one sign-in, two refresh tokens are accepted: the
current one, and the one it was rotated from. A repeat of that older one gets a
fresh pair; once the phone uses a token it was given, the older one is refused.
An ended sign-in refuses both.
"""

from __future__ import annotations

import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from unittest.mock import patch

from django.db import connection, connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.accounts.models import PasswordResetCode, SignInSession, User
from apps.accounts.sessions import SessionRefreshToken
from apps.admin_helper.tests.world import make_staff
from apps.admin_panel.permissions import AdminRole
from apps.admin_panel.staff_actions import set_account_ban
from apps.notifications.tests.factories import signed_in

PASSWORD = "Lost-answer-123!"


def _user(email: str) -> User:
    return User.objects.create_user(
        username=email, email=email, password=PASSWORD, full_name="Weak Network"
    )


def refresh(token: str):
    return APIClient().post("/api/auth/refresh", {"refresh": token}, format="json")


def rotate(token: str) -> dict:
    response = refresh(token)
    assert response.status_code == 200, response.data
    return response.data


def reads_the_account(access: str) -> bool:
    phone = APIClient()
    phone.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return phone.get("/api/me").status_code == 200


def jti(token: str) -> str:
    return RefreshToken(token, verify=False)[api_settings.JTI_CLAIM]


def sign_in_of(token: str) -> SignInSession:
    return SignInSession.objects.get(pk=RefreshToken(token, verify=False)["sid"])


class LostAnswerTests(TestCase):
    def setUp(self):
        self.user = _user("lost-answer@example.com")
        self.first = signed_in(self.user)["refresh"]

    def test_a_repeat_after_a_lost_answer_gets_a_working_pair(self):
        rotate(self.first)  # the answer never reaches the phone

        again = refresh(self.first)

        assert again.status_code == 200, again.data
        assert reads_the_account(again.data["access"])
        # A repeat leaves the sign-in as the rotation left it.
        assert sign_in_of(self.first).previous_refresh_jti == jti(self.first)
        assert reads_the_account(rotate(again.data["refresh"])["access"])

    def test_each_repeat_after_answers_lost_twice_in_a_row_gets_a_working_pair(self):
        answers = [refresh(self.first) for _ in range(3)]

        assert [answer.status_code for answer in answers] == [200, 200, 200]
        assert all(reads_the_account(answer.data["access"]) for answer in answers)
        assert sign_in_of(self.first).previous_refresh_jti == jti(self.first)
        # The phone keeps the last answer, the only one that reached it.
        kept = answers[-1].data["refresh"]
        assert reads_the_account(rotate(kept)["access"])

    def test_once_the_phone_used_the_new_token_the_older_one_is_refused(self):
        rotate(self.first)  # lost
        kept = rotate(self.first)["refresh"]

        rotate(kept)

        assert refresh(self.first).status_code == 401
        assert sign_in_of(self.first).previous_refresh_jti == jti(kept)

    def test_a_token_two_rotations_old_is_refused(self):
        second = rotate(self.first)["refresh"]
        rotate(second)

        assert refresh(self.first).status_code == 401
        # The token the current one was rotated from is still accepted.
        assert refresh(second).status_code == 200

    def test_a_token_never_rotated_is_refused_once_blacklisted_by_other_means(self):
        """Only a rotation records the older token: a blacklist alone is a refusal."""

        RefreshToken(self.first).blacklist()

        assert refresh(self.first).status_code == 401


class EndedSignInTests(TestCase):
    """A sign-out, a password reset and a ban each end the sign-in: the current
    token and the one it was rotated from are both refused afterwards."""

    def setUp(self):
        self.user = _user("lost-answer-ended@example.com")
        self.older = signed_in(self.user)["refresh"]
        self.current = rotate(self.older)

    def assert_both_refused(self):
        assert refresh(self.current["refresh"]).status_code == 401
        assert refresh(self.older).status_code == 401

    def test_a_sign_out(self):
        phone = APIClient()
        phone.credentials(HTTP_AUTHORIZATION=f"Bearer {self.current['access']}")
        assert phone.post("/api/auth/sign-out", {}, format="json").status_code == 205

        self.assert_both_refused()

    def test_a_password_reset(self):
        _, code = PasswordResetCode.issue(self.user)
        response = APIClient().post(
            "/api/auth/password/reset/confirm",
            {"email": self.user.email, "code": code, "new_password": "BrandNewPass99!"},
            format="json",
        )
        assert response.status_code == 204, response.data

        self.assert_both_refused()

    def test_a_ban(self):
        staff = make_staff("lost-answer-staff@example.test", AdminRole.SUPER_ADMIN)
        set_account_ban(
            actor=staff, user_id=self.user.pk, banned=True, reason="Threatened a traveler."
        )

        self.assert_both_refused()


class AccessLifetimeTests(TestCase):
    def test_a_repeat_issues_the_same_access_lifetime_with_thirty_seconds_of_leeway(self):
        first = signed_in(_user("lost-answer-lifetime@example.com"))["refresh"]
        rotate(first)  # lost
        access = AccessToken(rotate(first)["access"])

        assert access["exp"] - access["iat"] == 300

        def expired(seconds: int) -> str:
            late = AccessToken(str(access))
            late.set_exp(from_time=timezone.now() - timedelta(seconds=300 + seconds))
            return str(late)

        assert reads_the_account(expired(20))
        assert not reads_the_account(expired(40))


POSTGRES_ONLY = unittest.skipUnless(
    connection.vendor == "postgresql", "The refresh's guarantee is PostgreSQL row locking."
)


def in_own_connection(fn):
    """Run ``fn`` on this thread's own connection and always close it after."""

    def run():
        try:
            return fn()
        finally:
            connections.close_all()

    return run


@POSTGRES_ONLY
class ConcurrentRefreshTests(TransactionTestCase):
    """Real threads, real connections, real locks.

    The leading refresh is held while it blacklists the token, inside its
    transaction; the test proves the trailing one's backend is blocked by the
    leading one's, then lets both finish.
    """

    def wait_until_blocked(self, pids):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if "trailing" in pids:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT %s = ANY(pg_blocking_pids(%s))",
                        [pids["leading"], pids["trailing"]],
                    )
                    if cursor.fetchone()[0]:
                        return
            time.sleep(0.05)
        self.fail("The second refresh never waited for the first.")

    def race(self, token: str):
        holding, release = Event(), Event()
        original = SessionRefreshToken.blacklist
        pids = {}

        def paused(self, *args, **kwargs):
            holding.set()
            if not release.wait(30):
                raise AssertionError("The race was never released.")
            return original(self, *args, **kwargs)

        def tracked(name):
            def run():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids[name] = cursor.fetchone()[0]
                return refresh(token)

            return run

        with ThreadPoolExecutor(max_workers=2) as pool, patch.object(
            SessionRefreshToken, "blacklist", paused
        ):
            leading = pool.submit(in_own_connection(tracked("leading")))
            try:
                assert holding.wait(30), "The first refresh never blacklisted."
                trailing = pool.submit(in_own_connection(tracked("trailing")))
                self.wait_until_blocked(pids)
            finally:
                release.set()
            return leading.result(timeout=60), trailing.result(timeout=60)

    def test_two_refreshes_of_one_token_both_get_a_working_pair(self):
        first = signed_in(_user("lost-answer-race@example.com"))["refresh"]

        answers = self.race(first)

        assert [answer.status_code for answer in answers] == [200, 200], [
            answer.data for answer in answers
        ]
        assert sign_in_of(first).previous_refresh_jti == jti(first)
        assert BlacklistedToken.objects.filter(token__jti=jti(first)).count() == 1
        for answer in answers:
            assert reads_the_account(answer.data["access"])
            assert reads_the_account(rotate(answer.data["refresh"])["access"])
