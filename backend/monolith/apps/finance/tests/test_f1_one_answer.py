"""F1 rule F-G: one answer per response.

A payout read computes each rail's projection once and gives the same object
to the method list and to the summary, and it reads every row inside one
snapshot (`consistent_read`), so a commit between two of its reads cannot
split the response. A write builds its response from rows read in its own last
transaction.
"""

from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

import pytest
from django.db import connection, connections
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.core.tests.business_settings_seed import seed_business_settings
from apps.finance import payout_mobile
from apps.finance.models import StripePayoutAccount, TravelerPayoutMethod

from .factories import make_user
from .test_phase8fh2_accounts import H2, PLATFORM
from .test_phase8fh4_manual import configured_h4  # noqa: F401
from .test_phase8fh6a_mobile import client_for, preference, setup  # noqa: F401


def standing_de_account(user):
    """An active DE account of this platform, as a recording onboarding call leaves it."""
    return StripePayoutAccount.objects.create(
        traveler=user, platform_id=PLATFORM, provider_account_id=f"acct_1TESTde{user.pk}",
        provider_mode="test", declared_country="DE", status="setup_required",
        status_reason="onboarding_required")


@pytest.mark.django_db
@pytest.mark.parametrize("url", ["/api/payouts/methods", "/api/payouts/profiles/dzd"])
def test_each_rail_is_computed_once_per_response(configured_h4, url):
    """Round-5 should-fix: the method list and the summary carry one computation.

    The account appears after the first computation, as an onboarding call
    recording it would. One computation cannot disagree with itself.
    """
    user = make_user(f"f1once-{url.rsplit('/', 1)[-1]}@f1.test", is_email_verified=True)
    client = client_for(user)
    assert preference(client, "both").status_code == 200
    calls = {"eur_method": 0, "dzd_method": 0}

    def counted(name):
        real = getattr(payout_mobile, name)

        def run(method, gate):
            calls[name] += 1
            answer = real(method, gate)
            if name == "eur_method" and calls[name] == 1:
                standing_de_account(user)
            return answer

        return run

    with patch.object(payout_mobile, "eur_method", counted("eur_method")), \
            patch.object(payout_mobile, "dzd_method", counted("dzd_method")):
        body = client.get(url).data
    if url.endswith("methods"):
        assert calls == {"eur_method": 1, "dzd_method": 1}
        by_currency = {m["currency"]: m["mobile"] for m in body["methods"]}
        assert by_currency == {"EUR": body["eur"], "DZD": body["dzd"]}
    else:
        assert calls["dzd_method"] == 1
        assert body["method"]["mobile"] == body["dzd"]


def in_own_connection(fn):
    def run():
        try:
            return fn()
        finally:
            connections.close_all()

    return run


@unittest.skipUnless(connection.vendor == "postgresql", "A snapshot is PostgreSQL behaviour.")
@override_settings(**{**H2, "STRIPE_CONNECT_ALLOWED_COUNTRIES": ["FR", "DE"]})
class OneSnapshotTest(TransactionTestCase):
    """A commit between two of a read's queries does not split its response."""

    def setUp(self):
        publisher = patch("apps.core.redis_bus.publish_after_commit")
        publisher.start()
        self.addCleanup(publisher.stop)
        seed_business_settings()
        self.traveler = make_user("f1snapshot@f1.test", is_email_verified=True)
        self.client_api = APIClient()
        self.client_api.force_authenticate(self.traveler)
        saved = preference(self.client_api, "eur_only", country="FR")
        self.assertEqual(saved.status_code, 200, saved.data)

    def test_a_commit_between_reads_is_not_seen_by_the_rest_of_the_read(self):
        before = self.client_api.get("/api/payouts/methods").data
        paused, release = Event(), Event()
        summary = payout_mobile.payout_summary

        def after_the_method_rows(*args, **kwargs):
            paused.set()
            if not release.wait(30):
                raise AssertionError("The read was never released.")
            return summary(*args, **kwargs)

        with ThreadPoolExecutor(max_workers=1) as pool, \
                patch.object(payout_mobile, "payout_summary", after_the_method_rows):
            reading = pool.submit(in_own_connection(
                lambda: self.client_api.get("/api/payouts/methods")))
            try:
                self.assertTrue(paused.wait(30), "The read never reached its pause.")
                standing_de_account(self.traveler)
            finally:
                release.set()
            during = reading.result(timeout=60)
        self.assertEqual(during.status_code, 200, during.data)
        self.assertEqual(during.data, before)
        after = self.client_api.get("/api/payouts/methods").data
        self.assertEqual(after["eur"]["account_country"], "DE")
        self.assertEqual(after["eur"]["unavailable_reason"], "stripe_account_country_mismatch")
        self.assertEqual(
            TravelerPayoutMethod.objects.get(traveler=self.traveler, currency="EUR").revision,
            before["revisions"]["EUR"])
