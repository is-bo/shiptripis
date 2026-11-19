"""The guest and member throttles of the public reads (`apps.core.throttles`).

The rates are module-level settings, so their defaults and the environment
variables that change them are read in a clean interpreter, as
`apps.finance.tests.test_deployment_safety` does for production settings.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.throttles import (
    PUBLIC_READ_THROTTLES,
    GuestRateThrottle,
    MemberRateThrottle,
    MemberScopedRateThrottle,
)

MONOLITH = Path(__file__).resolve().parents[3]
SCOPES = (
    "discovery_guest",
    "matching_discovery",
    "registration",
    "login",
    "google_signin",
    "apple_signin",
    "anon",
)
VARIABLES = {
    "discovery_guest": "DRF_DISCOVERY_GUEST_THROTTLE_RATE",
    "matching_discovery": "DRF_MATCHING_DISCOVERY_THROTTLE_RATE",
    "registration": "DRF_REGISTRATION_THROTTLE_RATE",
    "login": "DRF_LOGIN_THROTTLE_RATE",
    "google_signin": "DRF_GOOGLE_SIGNIN_THROTTLE_RATE",
    "apple_signin": "DRF_APPLE_SIGNIN_THROTTLE_RATE",
    "anon": "DRF_ANON_THROTTLE_RATE",
}


def base_rates(**environment: str) -> dict:
    """The throttle rates `config.settings.base` builds from this environment."""

    env = {
        key: value for key, value in os.environ.items() if not key.startswith("DRF_")
    }
    env.pop("DJANGO_SETTINGS_MODULE", None)
    env.update(environment)
    snippet = (
        "import json; from config.settings import base; "
        "print(json.dumps(base.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']))"
    )
    result = subprocess.run(
        [sys.executable, "-c", snippet],
        cwd=MONOLITH,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


class _View(APIView):
    throttle_scope = "matching_discovery"


class ThrottleRateSettingsTests(SimpleTestCase):
    def test_the_carrier_nat_defaults(self):
        rates = base_rates()
        self.assertEqual(
            {scope: rates[scope] for scope in SCOPES},
            {
                "discovery_guest": "300/min",
                "matching_discovery": "60/min",
                "registration": "30/hour",
                # Password sign-in has no per-account lockout: it stays tight.
                "login": "10/min",
                "google_signin": "30/min",
                "apple_signin": "30/min",
                # Every endpoint other than the public reads keeps it.
                "anon": "60/min",
            },
        )

    def test_each_rate_is_read_from_its_environment_variable(self):
        rates = base_rates(
            **{
                VARIABLES[scope]: f"{index + 2}/min"
                for index, scope in enumerate(SCOPES)
            }
        )
        for index, scope in enumerate(SCOPES):
            self.assertEqual(rates[scope], f"{index + 2}/min", scope)

    def test_the_guest_throttle_uses_the_configured_guest_rate(self):
        configured = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"][
            "discovery_guest"
        ]
        self.assertEqual(GuestRateThrottle().get_rate(), configured)
        with patch.dict(
            ScopedRateThrottle.THROTTLE_RATES, {"discovery_guest": "7/min"}
        ):
            self.assertEqual(GuestRateThrottle().rate, "7/min")


class ThrottleKeyTests(SimpleTestCase):
    """Who each throttle counts: `None` means "not counted here"."""

    def request(self, *, member: bool):
        request = APIRequestFactory().get("/", REMOTE_ADDR="198.51.100.30")
        if member:
            user = type("Member", (), {"is_authenticated": True, "pk": 42})()
            force_authenticate(request, user=user)
        view = _View()
        drf_request = view.initialize_request(request)
        if not member:
            drf_request.user = AnonymousUser()
        return drf_request, view

    def test_a_guest_is_counted_by_address_on_the_guest_scope_only(self):
        request, view = self.request(member=False)
        self.assertEqual(
            GuestRateThrottle().get_cache_key(request, view),
            "throttle_discovery_guest_198.51.100.30",
        )
        self.assertIsNone(MemberRateThrottle().get_cache_key(request, view))
        scoped = MemberScopedRateThrottle()
        self.assertTrue(scoped.allow_request(request, view))
        self.assertIsNone(scoped.get_cache_key(request, view))

    def test_a_member_is_never_counted_on_the_guest_scope(self):
        request, view = self.request(member=True)
        self.assertIsNone(GuestRateThrottle().get_cache_key(request, view))
        self.assertEqual(
            MemberRateThrottle().get_cache_key(request, view), "throttle_user_42"
        )
        scoped = MemberScopedRateThrottle()
        scoped.scope = view.throttle_scope
        self.assertEqual(
            scoped.get_cache_key(request, view), "throttle_matching_discovery_42"
        )

    def test_the_public_reads_count_a_guest_on_the_guest_scope_and_a_member_per_member(
        self,
    ):
        self.assertEqual(PUBLIC_READ_THROTTLES, (GuestRateThrottle, MemberRateThrottle))
