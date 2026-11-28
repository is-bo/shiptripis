"""F1: funding reads a traveler's payout methods as one set.

A preference change from DZD only to EUR only disables the DZD row and inserts
the EUR one in one transaction. Row locks alone do not make that atomic for a
reader: funding's method query waits for the DZD row, then sees it disabled,
and never sees the EUR row the change inserted after the query began. It would
fund the payout with no rail (`payout_preference_required`), a state that
neither committed preference had. Both sides now take the traveler's method-set
lock (`apps.core.financial_locks.lock_payout_method_set`) first.

Real threads, real connections, real locks, on PostgreSQL only. Each test pauses
one side while it holds the set, proves the other side's backend is waiting for
this traveler's set lock and that the first side's backend is the one blocking
it, then lets both finish. Every worker exception is re-raised in the main
thread.
"""

from __future__ import annotations

import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from django.db import connection, connections
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.core.financial_locks import PAYOUT_METHOD_SET_LOCK
from apps.core.tests.business_settings_seed import seed_business_settings
from apps.finance import payout_snapshots
from apps.finance.models import Payout
from apps.finance.payout_profile_api import PayoutMethodsView
from apps.finance.payout_profiles import set_preference
from apps.finance.payout_snapshots import create_snapshot

from .factories import build_scenario
from .test_phase8fh2_accounts import H2

POSTGRES_ONLY = unittest.skipUnless(
    connection.vendor == "postgresql",
    "The method-set guarantee is PostgreSQL lock behaviour.",
)


def in_own_connection(fn):
    """Run `fn` on this thread's own connection and always close it after."""

    def run():
        try:
            return fn()
        finally:
            connections.close_all()

    return run


@POSTGRES_ONLY
@override_settings(**H2)
class PayoutMethodSetRaceTest(TransactionTestCase):
    def setUp(self):
        publisher = patch("apps.core.redis_bus.publish_after_commit")
        publisher.start()
        self.addCleanup(publisher.stop)
        seed_business_settings()
        scenario = build_scenario(prefix="f1race")
        self.deal = scenario.accept(reward_eur_cents=6_000)
        self.traveler = scenario.traveler
        # Only an enabled DZD row exists, as the single-currency POST leaves it.
        self.dzd = set_preference(
            actor=self.traveler, currency="DZD", enabled=True, expected_revision=0
        )

    def change_to_eur_only(self):
        client = APIClient()
        client.force_authenticate(self.traveler)
        return client.patch(
            "/api/payouts/methods",
            {
                "preference": "eur_only",
                "eur_revision": 0,
                "dzd_revision": self.dzd.revision,
                "country": "FR",
                "consent_policy": "payout_profile_v1",
            },
            format="json",
        )

    def fund(self):
        return create_snapshot(
            deal_id=self.deal.pk, traveler_id=self.traveler.pk, amount_eur_cents=6_000
        )

    def wait_until_blocked_on_the_set(self, pids):
        """Prove the trailing backend waits for this traveler's set, held by the leader.

        Its own ungranted advisory lock on this traveler's key, and the leading
        backend among the ones blocking it: no other waiter in the database can
        satisfy this, and neither can a trailing side that already finished.
        """

        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if "trailing" in pids:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT %s = ANY(pg_blocking_pids(l.pid)) FROM pg_locks l "
                        "WHERE l.pid = %s AND l.locktype = 'advisory' AND NOT l.granted "
                        "AND l.classid::bigint = %s AND l.objid::bigint = %s "
                        "AND l.objsubid = 2",
                        [pids["leading"], pids["trailing"], PAYOUT_METHOD_SET_LOCK,
                         self.traveler.pk & 0x7FFFFFFF],
                    )
                    row = cursor.fetchone()
                if row is not None:
                    self.assertTrue(row[0], "The set was held by another backend.")
                    return
            time.sleep(0.05)
        self.fail("The second transaction never waited on the traveler's method set.")

    def race(self, first, second, *, pause):
        """Start `first`, hold it inside its transaction, then start `second`.

        `pause` is patched to block `first` while it holds the method set. Both
        results are returned; an exception in either is raised here.
        """

        holding, release = Event(), Event()
        target, attribute = pause
        original = getattr(target, attribute)
        pids = {}

        def paused(*args, **kwargs):
            holding.set()
            if not release.wait(30):
                raise AssertionError("The race was never released.")
            return original(*args, **kwargs)

        def tracked(name, fn):
            def run():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    pids[name] = cursor.fetchone()[0]
                return fn()

            return run

        with ThreadPoolExecutor(max_workers=2) as pool, patch.object(target, attribute, paused):
            leading = pool.submit(in_own_connection(tracked("leading", first)))
            try:
                self.assertTrue(holding.wait(30), "The first side never held the set.")
                trailing = pool.submit(in_own_connection(tracked("trailing", second)))
                self.wait_until_blocked_on_the_set(pids)
            finally:
                release.set()
            return leading.result(timeout=60), trailing.result(timeout=60)

    def test_funding_waits_for_a_whole_preference_change_and_funds_the_new_rail(self):
        # The change has disabled DZD and inserted EUR, and has not committed.
        response, payout = self.race(
            self.change_to_eur_only, self.fund, pause=(PayoutMethodsView, "get")
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["preference"], "eur_only")
        self.assertEqual((payout.method, payout.payout_currency), ("stripe_transfer", "EUR"))
        self.assertNotEqual(payout.block_reason, "payout_preference_required")
        self.assertEqual(Payout.objects.filter(deal_id=self.deal.pk).count(), 1)

    def test_a_preference_change_waits_for_funding_and_funding_keeps_the_old_rail(self):
        # Funding holds the set and has not chosen yet; the change must wait
        # for it rather than deadlock on the Deal or the User row.
        payout, response = self.race(
            self.fund, self.change_to_eur_only, pause=(payout_snapshots, "choose_method")
        )
        self.assertEqual((payout.method, payout.payout_currency), ("manual", "DZD"))
        self.assertNotEqual(payout.block_reason, "payout_preference_required")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["preference"], "eur_only")
