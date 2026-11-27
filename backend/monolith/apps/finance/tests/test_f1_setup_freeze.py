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
from datetime import timedelta
from threading import Event
from unittest.mock import patch

from django.db import connection, connections, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.admin_panel.models import AdminAuditLog
from apps.core.tests.business_settings_seed import seed_business_settings
from apps.finance import payout_accounts, payout_profiles
from apps.finance.models import (
    PayoutMethodVersion,
    PayoutProviderOperation,
    StripePayoutAccount,
    TravelerPayoutMethod,
)
from apps.finance.payout_accounts import ensure_account

from .factories import make_user
from .test_f1_setup_eligibility import staff_change
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


def wait_for_a_lock_wait(seconds=30):
    """Until a session of this database waits for a lock another one holds."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                "AND cardinality(pg_blocking_pids(pid)) > 0")
            if cursor.fetchone()[0]:
                return
        time.sleep(0.05)
    raise AssertionError("No session waited for a row lock.")


def pausing(real, paused, release, *, after=False, when=lambda *a, **k: True):
    """`real`, stopping once before (or after) it runs until `release` is set."""
    held = []

    def run(*args, **kwargs):
        stop = not held and when(*args, **kwargs)
        if stop:
            held.append(True)
        if stop and not after:
            paused.set()
            if not release.wait(30):
                raise AssertionError("Never released.")
        answer = real(*args, **kwargs)
        if stop and after:
            paused.set()
            if not release.wait(30):
                raise AssertionError("Never released.")
        return answer

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

    def links_issued(self):
        return AdminAuditLog.objects.filter(
            actor=self.traveler, action="payout_account.onboarding_link_issued").count()

    def keys(self):
        return {kwargs["idempotency_key"] for name, kwargs in self.gateway.calls
                if name == "create_account"}

    # Real threads, both orders. Each second session is seen waiting for a
    # row lock (`pg_blocking_pids`) before the first one goes on.

    def test_an_intent_committed_first_is_read_by_the_preference_write_that_waited(self):
        paused, release = Event(), Event()
        with ThreadPoolExecutor(max_workers=2) as pool, patch.object(
            payout_accounts, "_creation_identity",
            pausing(payout_accounts._creation_identity, paused, release),
        ):
            onboarding = pool.submit(in_own_connection(self.onboard()))
            try:
                self.assertTrue(paused.wait(30), "Onboarding never held the method.")
                declared = pool.submit(in_own_connection(self.declare("DE")))
                wait_for_a_lock_wait()
            finally:
                release.set()
            self.assert_refused_in_progress(declared.result(timeout=60))
            onboarded = onboarding.result(timeout=60)
        self.bound(onboarded)
        self.assertEqual(self.creations(), ["FR"])

    def test_a_preference_write_committed_first_is_the_declaration_onboarding_serves(self):
        paused, release = Event(), Event()
        with ThreadPoolExecutor(max_workers=2) as pool, patch.object(
            payout_profiles, "_version",
            pausing(payout_profiles._version, paused, release, after=True),
        ):
            declared = pool.submit(in_own_connection(self.declare("DE")))
            try:
                self.assertTrue(paused.wait(30), "The write never reached its version.")
                onboarding = pool.submit(in_own_connection(self.onboard()))
                wait_for_a_lock_wait()
            finally:
                release.set()
            self.assertEqual(declared.result(timeout=60).status_code, 200)
            onboarded = onboarding.result(timeout=60)
        # The call planned on FR, found DE under the lock, and ran once more.
        self.bound(onboarded, "DE")
        self.assertEqual(self.creations(), ["DE"])

    def test_a_second_onboarding_waits_for_the_first_intent_then_sends_the_same_key(self):
        paused, release = Event(), Event()
        with ThreadPoolExecutor(max_workers=2) as pool, patch.object(
            payout_accounts, "_creation_identity",
            pausing(payout_accounts._creation_identity, paused, release),
        ):
            first = pool.submit(in_own_connection(self.onboard()))
            try:
                self.assertTrue(paused.wait(30), "The first call never held the method.")
                second = pool.submit(in_own_connection(self.onboard()))
                wait_for_a_lock_wait()
            finally:
                release.set()
            answers = [first.result(timeout=60), second.result(timeout=60)]
        for answer in answers:
            self.assertEqual(answer.status_code, 201, answer.data)
        self.assertEqual(self.creations(), ["FR", "FR"])
        self.assertEqual(len(self.keys()), 1)
        account = StripePayoutAccount.objects.get(traveler=self.traveler)
        self.assertEqual(PayoutMethodVersion.objects.filter(stripe_account=account).count(), 1)

    def test_a_ban_committed_while_the_link_handoff_waits_is_the_one_it_reads(self):
        paused, release = Event(), Event()
        with ThreadPoolExecutor(max_workers=1) as pool, patch.object(
            Answering, "create_account_link",
            pausing(Answering.create_account_link, paused, release, after=True),
        ):
            onboarding = pool.submit(in_own_connection(self.onboard()))
            try:
                self.assertTrue(paused.wait(30), "No link was minted.")
                with transaction.atomic():
                    staff_change(self.traveler, "ban")
                    release.set()
                    wait_for_a_lock_wait()
            finally:
                release.set()
            refused = onboarding.result(timeout=60)
        self.assertEqual(refused.status_code, 403, refused.data)
        self.assertEqual(refused.data["code"], "payout_traveler_required")
        self.assertNotIn("connect.stripe.test", str(refused.data))
        self.assertEqual(self.links_issued(), 0)

    def test_a_link_handed_out_before_the_ban_commits_is_the_last_thing_it_does(self):
        paused, release = Event(), Event()
        issued = "payout_account.onboarding_link_issued"
        with ThreadPoolExecutor(max_workers=2) as pool, patch.object(
            payout_accounts, "record_admin_action",
            pausing(payout_accounts.record_admin_action, paused, release, after=True,
                    when=lambda **kwargs: kwargs.get("action") == issued),
        ):
            onboarding = pool.submit(in_own_connection(self.onboard()))
            try:
                self.assertTrue(paused.wait(30), "The link was never being handed out.")
                banning = pool.submit(in_own_connection(
                    lambda: staff_change(self.traveler, "ban")))
                wait_for_a_lock_wait()
            finally:
                release.set()
            onboarded = onboarding.result(timeout=60)
            banning.result(timeout=60)
        self.assertEqual(onboarded.status_code, 201, onboarded.data)
        self.assertEqual(self.links_issued(), 1)
        self.traveler.refresh_from_db()
        self.assertTrue(self.traveler.is_banned)

    # Crash points. The process dies, and its database connection with it;
    # what the next call needs is in committed rows.

    def test_a_crash_after_the_intent_commit_keeps_the_declaration_frozen(self):
        def died(gateway, **kwargs):
            connection.close()
            raise RuntimeError("the worker died before the request left")

        with patch.object(Answering, "create_account", died), self.assertRaises(RuntimeError):
            ensure_account(actor=self.traveler, gateway=self.gateway)
        operation = PayoutProviderOperation.objects.get(kind="account_create")
        self.assertEqual(operation.status, "committed")
        self.assert_refused_in_progress(self.declare("DE")())
        self.bound(self.onboard()())
        self.assertEqual(self.keys(), {operation.idempotency_key})

    def crash_after_the_request(self):
        made = Answering.create_account

        def answered_then_died(gateway, **kwargs):
            made(gateway, **kwargs)
            connection.close()
            raise RuntimeError("the worker died with Stripe's answer")

        with patch.object(Answering, "create_account", answered_then_died), \
                self.assertRaises(RuntimeError):
            ensure_account(actor=self.traveler, gateway=self.gateway)
        self.assertFalse(StripePayoutAccount.objects.exists())
        self.assert_refused_in_progress(self.declare("DE")())
        return PayoutProviderOperation.objects.get(kind="account_create")

    def test_a_crash_after_the_request_replays_it_inside_the_window(self):
        operation = self.crash_after_the_request()
        self.bound(self.onboard()())
        self.assertEqual(self.creations(), ["FR", "FR"])
        self.assertEqual(self.keys(), {operation.idempotency_key})

    def test_a_crash_after_the_request_finds_the_account_past_the_window(self):
        operation = self.crash_after_the_request()
        PayoutProviderOperation.objects.filter(pk=operation.pk).update(
            first_request_at=timezone.now() - timedelta(days=2))
        self.gateway._found = [snapshot(country="FR")]
        self.bound(self.onboard()())
        self.assertEqual(self.creations(), ["FR"])

    def test_a_crash_after_the_record_leaves_the_account_bound_and_the_freeze_over(self):
        def died(gateway, **kwargs):
            connection.close()
            raise RuntimeError("the worker died before the link")

        with patch.object(Answering, "create_account_link", died), \
                self.assertRaises(RuntimeError):
            self.onboard()()
        operation = PayoutProviderOperation.objects.get(kind="account_create")
        self.assertEqual(operation.status, "accepted")
        account = StripePayoutAccount.objects.get(traveler=self.traveler)
        self.assertEqual(self.eur().current_version.stripe_account_id, account.pk)
        self.bound(self.onboard()())
        self.assertEqual(self.creations(), ["FR"])
        self.assertEqual(self.declare("DE")().status_code, 200)

    def test_no_session_level_advisory_lock_is_taken_in_the_setup_path(self):
        """The lock this round removes; the transaction-level method-set lock stays."""
        client = self.client_for()
        with CaptureQueriesContext(connection) as captured:
            self.assertEqual(self.onboard()().status_code, 201)
            self.assertEqual(client.post("/api/payouts/methods/stripe/refresh", {},
                                         format="json").status_code, 200)
            self.assertEqual(self.declare("FR", "both")().status_code, 200)
            revision = client.get(METHODS).data["revisions"]["EUR"]
            self.assertEqual(client.post(METHODS, {
                "currency": "EUR", "enabled": True, "country": "DE",
                "expected_revision": revision, "consent_policy": "payout_profile_v1",
            }, format="json").status_code, 200)
        sql = " ".join(query["sql"] for query in captured).lower()
        self.assertNotIn("pg_advisory_lock(", sql)
        self.assertNotIn("pg_try_advisory_lock(", sql)
        self.assertIn("pg_advisory_xact_lock(", sql)
