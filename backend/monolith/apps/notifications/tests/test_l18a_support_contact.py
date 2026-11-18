"""L18A: `GET /api/support` tells the app where a member writes for help.

The answer is the server setting the emails already print, `EMAIL_SUPPORT_ADDR`,
which is contact@wassla.eu unless the deployment names another (plan EGS,
decision 2): never `null`. No sign-in, own throttle.
"""

from __future__ import annotations

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

URL = reverse("support-contact")


class SupportContactTests(TestCase):
    def setUp(self):
        cache.clear()

    @override_settings(EMAIL_SUPPORT_ADDR="help@wassla.invalid")
    def test_the_configured_address_is_answered_without_sign_in(self):
        response = APIClient().get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"email": "help@wassla.invalid"})

    def test_the_shipped_default_is_contact_at_wassla(self):
        # A blank `EMAIL_SUPPORT_ADDR` resolves to this in the settings
        # (`test_v2_configuration.test_blank_identity_settings_mean_contact_at_wassla`),
        # so the answer is never null.
        response = APIClient().get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"email": "contact@wassla.eu"})

    @override_settings(EMAIL_SUPPORT_ADDR="help@wassla.invalid")
    def test_a_stale_token_does_not_break_it(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer not-a-token")
        response = client.get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"email": "help@wassla.invalid"})

    def test_it_only_reads(self):
        self.assertEqual(APIClient().post(URL).status_code, 405)

    def test_it_is_throttled(self):
        with patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"support_contact": "2/min"}):
            try:
                client = APIClient()
                self.assertEqual(client.get(URL).status_code, 200)
                self.assertEqual(client.get(URL).status_code, 200)
                self.assertEqual(client.get(URL).status_code, 429)
            finally:
                cache.clear()
