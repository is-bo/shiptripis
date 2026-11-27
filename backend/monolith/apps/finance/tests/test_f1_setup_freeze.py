"""F1 rule F-C: a Stripe account is created only for the declaration that is current.

The freeze is a row, not a lock held across Stripe. While the method's account
creation is prepared, committed or unknown (`payout_accounts.OUTSTANDING`), a
write that would change the euro method's "enabled" or its country is refused
with `payout_setup_in_progress`. Onboarding commits that row (its intent) under
the method's row lock before it sends anything, and every preference write
reads it under the same lock, so one always sees the other. No lock is held
while Stripe answers, so nothing waits on Stripe and a dropped database
connection releases nothing that matters.

The freeze ends when Stripe settles the creation: an account recorded and
bound, the request refused, or (past the 23-hour replay window) a complete
listing of the accounts created around the request that holds none for it.
A call that finds its rows changed under it reads them again and runs once
more; a second change answers `payout_preference_changed`.

Real threads run on PostgreSQL only, in the shape of
`test_f1_payout_method_set_race`. Every worker exception is re-raised in the
main thread.
"""

from __future__ import annotations

import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from threading import Event
from unittest.mock import patch

from django.db import connection, connections
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.core.tests.business_settings_seed import seed_business_settings
from apps.finance.models import PayoutMethodVersion, StripePayoutAccount, TravelerPayoutMethod

from .factories import make_user
from .test_phase8fh2_accounts import H2, FakeGateway, snapshot

POSTGRES_ONLY = unittest.skipUnless(
    connection.vendor == "postgresql", "Connections, snapshots and row locks are PostgreSQL's."
)

ONBOARDING = "/api/payouts/methods/stripe/onboarding"
METHODS = "/api/payouts/methods"


class Answering(FakeGateway):
    """Stripe opening the account for the country it was asked for.

    Every call fails the test when it is made inside a transaction: no
    transaction is open while Stripe answers (plan rule R1).
    """

    def _outside(self, name):
        if connection.in_atomic_block:
            raise AssertionError(f"{name} was called inside a transaction.")

    def platform_identity(self):
        self._outside("platform_identity")
        return super().platform_identity()

    def create_account(self, **kwargs):
        self._outside("create_account")
        self.calls.append(("create_account", kwargs))
        return snapshot(country=kwargs["country"])

    def retrieve_account(self, account_id):
        self._outside("retrieve_account")
        return super().retrieve_account(account_id)

    def find_account_by_metadata(self, **kwargs):
        self._outside("find_account_by_metadata")
        return super().find_account_by_metadata(**kwargs)

    def set_payout_schedule(self, **kwargs):
        self._outside("set_payout_schedule")
        return super().set_payout_schedule(**kwargs)

    def create_account_link(self, **kwargs):
        self._outside("create_account_link")
        return super().create_account_link(**kwargs)


def in_own_connection(fn):
    """Run `fn` on this thread's own connection and always close it after."""

    def run():
        try:
            return fn()
        finally:
            connections.close_all()

    return run


@POSTGRES_ONLY
@override_settings(**{**H2, "STRIPE_CONNECT_ALLOWED_COUNTRIES": ["FR", "DE"]})
class SetupFreezeThreadsTest(TransactionTestCase):
    def setUp(self):
        publisher = patch("apps.core.redis_bus.publish_after_commit")
        publisher.start()
        self.addCleanup(publisher.stop)
        seed_business_settings()
        self.traveler = make_user("f1freeze-threads@f1.test", is_email_verified=True)
        self.gateway = Answering()
        for module in ("payout_accounts", "payout_account_api"):
            patcher = patch(f"apps.finance.{module}.get_connect_gateway",
                            return_value=self.gateway)
            patcher.start()
            self.addCleanup(patcher.stop)
        declared = self.client_for().patch(METHODS, self.body("eur_only", "FR", 0, 0),
                                           format="json")
        self.assertEqual(declared.status_code, 200, declared.data)

    def client_for(self):
        client = APIClient()
        client.force_authenticate(self.traveler)
        return client

    @staticmethod
    def body(preference, country, eur, dzd):
        return {"preference": preference, "eur_revision": eur, "dzd_revision": dzd,
                "country": country, "consent_policy": "payout_profile_v1"}

    def declare(self, country, preference="eur_only"):
        """A second session reading the setup, then sending its PATCH."""

        client = self.client_for()

        def run():
            revisions = client.get(METHODS).data["revisions"]
            return client.patch(
                METHODS, self.body(preference, country, revisions["EUR"], revisions["DZD"]),
                format="json")

        return run

    def onboard(self):
        client = self.client_for()
        return lambda: client.post(ONBOARDING, {}, format="json")

    def creations(self):
        return [kwargs["country"] for name, kwargs in self.gateway.calls
                if name == "create_account"]

    def eur(self):
        return TravelerPayoutMethod.objects.get(traveler=self.traveler, currency="EUR")

    def bound(self, onboarded, country="FR"):
        """The one request was for `country`, answered for it, and bound."""

        self.assertEqual(onboarded.status_code, 201, onboarded.data)
        account = StripePayoutAccount.objects.get(traveler=self.traveler)
        bound = PayoutMethodVersion.objects.get(stripe_account=account)
        self.assertEqual((bound.country, account.declared_country), (country, country))
        self.assertEqual(self.eur().current_version_id, bound.pk)
        self.assertEqual(onboarded.data["method"]["version"], str(bound.public_reference))
        return bound

    def assert_refused_in_progress(self, response):
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data["code"], "payout_setup_in_progress")

    def test_a_dropped_connection_releases_nothing_that_keeps_the_declaration(self):
        """Round-5 blocker: the intent is committed, onboarding's connection dies
        while the FR request is on its way, and a DE preference tries to commit.
        """

        answers = {}
        create = Answering.create_account

        def connection_lost_on_the_way(gateway, **kwargs):
            connection.close()
            with ThreadPoolExecutor(max_workers=1) as pool:
                answers["declared"] = pool.submit(
                    in_own_connection(self.declare("DE"))).result(timeout=30)
            return create(gateway, **kwargs)

        with patch.object(Answering, "create_account", connection_lost_on_the_way):
            onboarded = self.onboard()()
        self.assert_refused_in_progress(answers["declared"])
        self.bound(onboarded)
        self.assertEqual(self.creations(), ["FR"])

    def test_nothing_waits_for_an_onboarding_call_in_flight(self):
        """Round-5 should-fix: no wait on another call's Stripe request, so no deadline is needed.

        While one call's request is on its way, a PATCH changing the country,
        a PATCH switching euros off, a PATCH that changes nothing, a DZD-only
        change and a second onboarding call each answer at once.
        """

        holding, release = Event(), Event()
        create = Answering.create_account
        held = []

        def paused(gateway, **kwargs):
            if not held:
                held.append(True)
                holding.set()
                if not release.wait(60):
                    raise AssertionError("The first call was never released.")
            return create(gateway, **kwargs)

        seconds = {
            "country": self.declare("DE"),
            "euros_off": self.declare("", "dzd_only"),
            "unchanged": self.declare("FR"),
            "dzd_only_change": self.declare("FR", "both"),
            "second_onboarding": self.onboard(),
        }
        answers = {}
        with ThreadPoolExecutor(max_workers=2) as pool, \
                patch.object(Answering, "create_account", paused):
            first = pool.submit(in_own_connection(self.onboard()))
            try:
                self.assertTrue(holding.wait(30), "The first call never reached Stripe.")
                for name, second in seconds.items():
                    started = time.monotonic()
                    try:
                        answers[name] = pool.submit(in_own_connection(second)).result(timeout=10)
                    except FutureTimeout:
                        self.fail(f"{name} waited for the onboarding call in flight.")
                    self.assertLess(time.monotonic() - started, 10)
            finally:
                release.set()
            onboarded = first.result(timeout=60)
        self.assert_refused_in_progress(answers["country"])
        self.assert_refused_in_progress(answers["euros_off"])
        self.assertEqual(answers["unchanged"].status_code, 200, answers["unchanged"].data)
        self.assertEqual(answers["dzd_only_change"].status_code, 200,
                         answers["dzd_only_change"].data)
        self.assertEqual(answers["second_onboarding"].status_code, 201,
                         answers["second_onboarding"].data)
        self.assertEqual(onboarded.status_code, 201, onboarded.data)
        self.assertEqual(self.creations(), ["FR", "FR"])
        self.assertEqual(StripePayoutAccount.objects.filter(traveler=self.traveler).count(), 1)
        account = StripePayoutAccount.objects.get(traveler=self.traveler)
        self.assertEqual(PayoutMethodVersion.objects.filter(stripe_account=account).count(), 1)
