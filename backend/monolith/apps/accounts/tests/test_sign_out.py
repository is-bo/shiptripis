"""The sign-out contract (`POST /api/auth/sign-out`) and what a sign-out writes.

A refresh token this server signed proves its sign-in, whatever else is true of
it, and the answer is 205: the sign-in is ended, now or earlier, and every push
device it registered is off. A token that cannot be verified as ours, or none,
is 400 `sign_out_proof_invalid`. A sign-out records nothing in an
installation's order (N-B): ending the sign-in switches off its own devices.
"""

from __future__ import annotations

from uuid import uuid4

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.notifications.models import PushDevice, PushInstallationBinding
from apps.notifications.tests.factories import signed_in

SIGN_OUT = "/api/auth/sign-out"
WRITES = ("INSERT", "UPDATE", "DELETE")


def _user(email: str) -> User:
    return User.objects.create_user(
        username=email, email=email, password="Test-password-123!", full_name="Sign Out"
    )


def _writes(queries) -> list[str]:
    return [q["sql"] for q in queries if q["sql"].lstrip().upper().startswith(WRITES)]


class SignOutWritesTests(TestCase):
    def setUp(self):
        self.user = _user("sign-out-one@example.com")
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

    def _sign_out(self, session, sequence):
        # The body the phone sends today: its installation and the next
        # number of its counter, which the server no longer reads.
        return APIClient().post(
            SIGN_OUT,
            {
                "refresh": session["refresh"],
                "installation_id": str(self.installation),
                "binding_sequence": sequence,
            },
            format="json",
        )

    def test_a_repeated_sign_out_of_an_ended_sign_in_writes_nothing(self):
        # N1 round 5, should-fix: the repeat still advanced the installation's
        # order, so the next registration of whoever signs in next on that
        # phone could be refused as stale.
        a = signed_in(self.user)
        assert self._register(a, 1).status_code == 200
        assert self._sign_out(a, 2).status_code == 205
        assert PushDevice.objects.get().active is False

        with CaptureQueriesContext(connection) as queries:
            again = self._sign_out(a, 5)

        assert again.status_code == 205
        assert _writes(queries) == []
        assert PushInstallationBinding.objects.get().sequence == 1
