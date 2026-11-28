"""The sign-out contract (`POST /api/auth/sign-out`) and what a sign-out writes.

A refresh token this server signed proves its sign-in, whatever else is true of
it, and the answer is 205: the sign-in is ended, now or earlier, and every push
device it registered is off. A token that cannot be verified as ours, or none,
is 400 `sign_out_proof_invalid`. The phone's session core keeps resending a
sign-out until it gets one of these two answers (S1), so nothing else may
answer them. A sign-out records nothing in an installation's order (N-B):
ending the sign-in switches off its own devices, and a repeat writes nothing.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import jwt
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.throttling import AnonRateThrottle
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.accounts import sessions
from apps.accounts.models import SignInSession, User
from apps.accounts.sessions import end_all_sessions
from apps.notifications.models import PushDevice, PushInstallationBinding
from apps.notifications.tests.factories import signed_in

SIGN_OUT = "/api/auth/sign-out"
PASSWORD = "Test-password-123!"
WRITES = ("INSERT", "UPDATE", "DELETE")


def _user(email: str) -> User:
    return User.objects.create_user(
        username=email, email=email, password=PASSWORD, full_name="Sign Out"
    )


def _writes(queries) -> list[str]:
    return [q["sql"] for q in queries if q["sql"].lstrip().upper().startswith(WRITES)]


def _refresh(token: str):
    return APIClient().post("/api/auth/refresh", {"refresh": token}, format="json")


def _expired(access: str) -> str:
    """``access`` re-signed with an expiry past the 30 second leeway (G2)."""

    token = AccessToken(access)
    token.set_exp(from_time=timezone.now() - timedelta(minutes=10))
    return str(token)


def _expired_refresh(refresh: str) -> str:
    """``refresh`` re-signed as if its lifetime ran out a day ago: the phone
    left unopened longer than the refresh lifetime."""

    token = RefreshToken(refresh)
    token.set_exp(from_time=timezone.now() - token.lifetime - timedelta(days=1))
    return str(token)


def _issued_ahead(refresh: str, seconds: int) -> str:
    """``refresh`` re-signed as issued ``seconds`` from now: what a server whose
    clock runs that far behind the issuer's reads."""

    token = RefreshToken(refresh)
    token["iat"] = int(timezone.now().timestamp()) + seconds
    return str(token)


def _signed_elsewhere(refresh: str) -> str:
    """``refresh`` with the same claims, signed with a key this server does not
    hold."""

    claims = jwt.decode(refresh, options={"verify_signature": False})
    return jwt.encode(claims, "a-key-this-server-does-not-hold", algorithm="HS256")


class _Phone(TestCase):
    """One installation, and the requests its app sends."""

    def setUp(self):
        self.user = _user("sign-out-one@example.com")
        self.other = _user("sign-out-two@example.com")
        self.installation = uuid4()

    def _register(self, session, sequence):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {session['access']}")
        return client.post(
            "/api/notifications/devices",
            {
                "installation_id": str(self.installation),
                "binding_sequence": sequence,
                "token": "fcm-token-sign-out-1234567890",
                "platform": "android",
            },
            format="json",
        )

    def _sign_out(self, *, refresh, access=None, sequence=2):
        # The body the phone sends today: its refresh token, its installation
        # and the next number of its counter, which the server no longer reads.
        client = APIClient()
        if access is not None:
            client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        return client.post(
            SIGN_OUT,
            {
                "refresh": refresh,
                "installation_id": str(self.installation),
                "binding_sequence": sequence,
            },
            format="json",
        )

    def _device(self) -> PushDevice:
        return PushDevice.objects.get()

    def _live(self, session) -> bool:
        return SignInSession.live(user_id=self.user.pk, session_id=session["sid"]) is not None


class SignOutContractTests(_Phone):
    def test_a_live_refresh_token_alone_ends_the_sign_in_and_its_phone(self):
        a = signed_in(self.user)
        assert self._register(a, 1).status_code == 200

        response = self._sign_out(refresh=a["refresh"])

        assert response.status_code == 205
        assert not self._live(a)
        assert self._device().active is False
        assert _refresh(a["refresh"]).status_code == 401

    def test_an_expired_access_token_leaves_the_proof_to_the_refresh_token(self):
        a = signed_in(self.user)
        assert self._register(a, 1).status_code == 200

        response = self._sign_out(access=_expired(a["access"]), refresh=a["refresh"])

        assert response.status_code == 205
        assert not self._live(a)
        assert self._device().active is False

    def test_an_expired_refresh_token_still_ends_its_sign_in(self):
        # The phone was left unopened past the refresh lifetime: the refresh
        # is refused, and the sign-out with that token still ends the sign-in.
        a = signed_in(self.user)
        assert self._register(a, 1).status_code == 200
        expired = _expired_refresh(a["refresh"])
        assert _refresh(expired).status_code == 401

        response = self._sign_out(refresh=expired)

        assert response.status_code == 205
        assert not self._live(a)
        assert self._device().active is False

    def test_a_rotated_refresh_token_still_ends_its_sign_in(self):
        # A refresh rotated the token the phone holds, and its answer may never
        # have arrived: the older token still names the same sign-in.
        for access in (None, "valid", "expired"):
            with self.subTest(access=access):
                a = signed_in(self.user)
                assert self._register(a, 1).status_code == 200
                rotated = _refresh(a["refresh"])
                assert rotated.status_code == 200
                bearer = {"valid": a["access"], "expired": _expired(a["access"])}.get(access)

                response = self._sign_out(access=bearer, refresh=a["refresh"])

                assert response.status_code == 205
                assert not self._live(a)
                assert self._device().active is False
                assert _refresh(rotated.data["refresh"]).status_code == 401
                PushDevice.objects.all().delete()
                PushInstallationBinding.objects.all().delete()

    def test_a_proof_of_a_deleted_account_answers_205(self):
        a = signed_in(self.user)
        assert self._register(a, 1).status_code == 200
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {a['access']}")
        assert client.post("/api/me/deletion", {"password": PASSWORD}, format="json").status_code == 204

        response = self._sign_out(refresh=a["refresh"])

        assert response.status_code == 205
        assert not self._live(a)

        b = signed_in(self.other)
        User.objects.filter(pk=self.other.pk).delete()
        with CaptureQueriesContext(connection) as queries:
            gone = self._sign_out(refresh=b["refresh"])
        assert gone.status_code == 205
        assert _writes(queries) == []

    # The final review of N1: three ways a genuine proof got another answer
    # than 205, which leaves the sign-in live and its phone on.
    def test_a_fresh_proof_read_by_a_clock_a_few_seconds_behind_is_a_proof(self):
        a = signed_in(self.user)
        assert self._register(a, 1).status_code == 200

        response = self._sign_out(refresh=_issued_ahead(a["refresh"], 10))

        assert response.status_code == 205
        assert not self._live(a)
        assert self._device().active is False

    def test_the_shared_guest_quota_does_not_stop_a_sign_out(self):
        a = signed_in(self.user)
        cache.clear()
        self.addCleanup(cache.clear)
        with patch.dict(AnonRateThrottle.THROTTLE_RATES, {"anon": "1/min"}):
            # Another guest behind the same address spent the shared bucket.
            assert _refresh("not-a-token").status_code == 401
            assert _refresh("not-a-token").status_code == 429

            response = self._sign_out(refresh=a["refresh"])

        assert response.status_code == 205
        assert not self._live(a)

    def test_an_account_deleted_during_the_sign_out_answers_205(self):
        a = signed_in(self.user)
        lock = sessions.lock_account

        def deleted_first(user):
            User.objects.filter(pk=user.pk).delete()
            return lock(user)

        with patch.object(sessions, "lock_account", deleted_first):
            response = self._sign_out(refresh=a["refresh"])

        assert response.status_code == 205
        assert not User.objects.filter(pk=self.user.pk).exists()

    def test_a_proof_that_cannot_be_verified_as_ours_is_400(self):
        a = signed_in(self.user)
        assert self._register(a, 1).status_code == 200

        for access, refresh in (
            (None, "not-a-token"),
            # An access token is not a refresh token, even a valid one.
            (None, a["access"]),
            # Only this server's signature proves a sign-in, whatever its age.
            (None, _signed_elsewhere(a["refresh"])),
            (None, _signed_elsewhere(_expired_refresh(a["refresh"]))),
            (_expired(a["access"]), _signed_elsewhere(a["refresh"])),
        ):
            response = self._sign_out(access=access, refresh=refresh)
            assert response.status_code == 400
            assert response.data["code"] == "sign_out_proof_invalid"
        assert self._live(a)
        assert self._device().active is True

    def test_no_proof_is_400(self):
        a = signed_in(self.user)
        for body in ({}, {"refresh": ""}, {"refresh": None}, ["not", "an", "object"]):
            response = APIClient().post(SIGN_OUT, body, format="json")
            assert response.status_code == 400
            assert response.data["code"] == "sign_out_proof_invalid"
        expired_access_only = APIClient()
        expired_access_only.credentials(HTTP_AUTHORIZATION=f"Bearer {_expired(a['access'])}")
        response = expired_access_only.post(SIGN_OUT, {}, format="json")
        assert response.status_code == 400
        assert self._live(a)

    def test_a_valid_access_token_alone_is_a_proof(self):
        a = signed_in(self.user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {a['access']}")

        assert client.post(SIGN_OUT, {}, format="json").status_code == 205

        assert not self._live(a)
        assert _refresh(a["refresh"]).status_code == 401

    def test_a_valid_access_token_proves_its_own_sign_in_only(self):
        # B's sign-out carrying A's refresh token ends B's sign-in; A's is not
        # touched.
        a, b = signed_in(self.user), signed_in(self.other)
        assert self._register(a, 1).status_code == 200

        response = self._sign_out(access=b["access"], refresh=a["refresh"])

        assert response.status_code == 205
        assert self._live(a)
        assert self._device().active is True
        assert SignInSession.live(user_id=self.other.pk, session_id=b["sid"]) is None
        assert _refresh(a["refresh"]).status_code == 200

    def test_a_repeat_after_a_205_writes_nothing(self):
        a = signed_in(self.user)
        assert self._register(a, 1).status_code == 200
        assert self._sign_out(access=a["access"], refresh=a["refresh"]).status_code == 205

        for access in (a["access"], _expired(a["access"]), None):
            with CaptureQueriesContext(connection) as queries:
                again = self._sign_out(access=access, refresh=a["refresh"], sequence=3)
            assert again.status_code == 205
            assert _writes(queries) == []
        assert self._device().active is False


class SignOutWritesTests(_Phone):
    def test_a_repeated_sign_out_of_an_ended_sign_in_writes_nothing(self):
        # N1 round 5, should-fix: the repeat still advanced the installation's
        # order, so the next registration of whoever signs in next on that
        # phone could be refused as stale.
        a = signed_in(self.user)
        assert self._register(a, 1).status_code == 200
        assert self._sign_out(refresh=a["refresh"], sequence=2).status_code == 205
        assert self._device().active is False

        with CaptureQueriesContext(connection) as queries:
            again = self._sign_out(refresh=a["refresh"], sequence=5)

        assert again.status_code == 205
        assert _writes(queries) == []
        assert PushInstallationBinding.objects.get().sequence == 1
        b = signed_in(self.other)
        assert self._register(b, 3).status_code == 200

    def test_a_sign_out_of_a_sign_in_a_reset_already_ended_writes_nothing(self):
        a = signed_in(self.user)
        assert self._register(a, 1).status_code == 200
        end_all_sessions(self.user)
        assert self._device().active is False

        with CaptureQueriesContext(connection) as queries:
            response = self._sign_out(access=a["access"], refresh=a["refresh"], sequence=4)

        assert response.status_code == 205
        assert _writes(queries) == []
        assert PushInstallationBinding.objects.get().sequence == 1

    def test_a_late_sign_out_leaves_the_next_members_phone_on(self):
        # A signed out on the phone, but the request was slow; B signed in on
        # the same phone and registered before it arrived.
        a, b = signed_in(self.user), signed_in(self.other)
        assert self._register(a, 1).status_code == 200
        assert self._register(b, 3).status_code == 200

        response = self._sign_out(refresh=a["refresh"], sequence=2)

        assert response.status_code == 205
        assert not self._live(a)
        device = self._device()
        assert device.user == self.other
        assert device.active is True
        assert PushInstallationBinding.objects.get().sequence == 3

    def test_a_late_sign_out_leaves_the_same_members_newer_sign_in_on(self):
        # One account, two sign-ins on one phone: the older sign-in's sign-out
        # arrives after the newer one registered.
        older, newer = signed_in(self.user), signed_in(self.user)
        assert self._register(older, 1).status_code == 200
        assert self._register(newer, 3).status_code == 200

        assert self._sign_out(refresh=older["refresh"], sequence=2).status_code == 205

        assert self._device().session_id.hex == newer["sid"]
        assert self._device().active is True
        assert self._sign_out(refresh=newer["refresh"], sequence=4).status_code == 205
        assert self._device().active is False

    def test_a_registration_arriving_after_its_sign_out_is_refused(self):
        a = signed_in(self.user)
        assert self._sign_out(refresh=a["refresh"]).status_code == 205

        late = self._register(a, 1)

        assert late.status_code == 409
        assert late.data["code"] == "push_session_ended"
        assert PushDevice.objects.count() == 0
        assert PushInstallationBinding.objects.count() == 0
