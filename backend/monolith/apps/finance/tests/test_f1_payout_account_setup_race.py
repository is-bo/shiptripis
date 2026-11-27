"""F1 round 5: an onboarding call and a preference change never overlap.

Onboarding commits its account-creation intent, then asks Stripe outside every
transaction. A preference change committed in between would let the call open
an account for the country the Traveler had just left, which then holds their
only active slot. A second onboarding call starting while the first binds would
see a newer version and report a preference change nobody made. Both writers
now take the traveler's account-setup lock first: onboarding holds it from
reading the declaration to handing out the link
(`hold_payout_account_setup`), the EUR preference write before User
(`lock_payout_account_setup`). One side waits for the other.

Real threads, real connections, real locks, on PostgreSQL only, in the shape of
`test_f1_payout_method_set_race`: one side is paused inside a Stripe call or
inside its transaction, the test proves the other side's backend waits for this
traveler's setup lock and that the first side's backend holds it, then lets
both finish. Every worker exception is re-raised in the main thread.
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

from apps.admin_panel.models import AdminAuditLog
from apps.core.financial_locks import PAYOUT_ACCOUNT_SETUP_LOCK
from apps.core.tests.business_settings_seed import seed_business_settings
from apps.finance.models import (
    PayoutMethodVersion,
    PayoutProviderOperation,
    StripePayoutAccount,
    TravelerPayoutMethod,
)
from apps.finance import payout_profile_api

from .factories import make_user
from .test_phase8fh2_accounts import H2, FakeGateway, snapshot

POSTGRES_ONLY = unittest.skipUnless(
    connection.vendor == "postgresql",
    "The setup guarantee is PostgreSQL lock behaviour.",
)

ONBOARDING = "/api/payouts/methods/stripe/onboarding"
METHODS = "/api/payouts/methods"


class Answering(FakeGateway):
    """Stripe opening the account for the country it was asked for."""

    def create_account(self, **kwargs):
        self.calls.append(("create_account", kwargs))
        return snapshot(country=kwargs["country"])


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
class PayoutAccountSetupRaceTest(TransactionTestCase):
    def setUp(self):
        publisher = patch("apps.core.redis_bus.publish_after_commit")
        publisher.start()
        self.addCleanup(publisher.stop)
        seed_business_settings()
        self.traveler = make_user("f1setup-race@h6a.test", is_email_verified=True)
        self.gateway = Answering()
        for module in ("payout_accounts", "payout_account_api"):
            patcher = patch(f"apps.finance.{module}.get_connect_gateway",
                            return_value=self.gateway)
            patcher.start()
            self.addCleanup(patcher.stop)
        declared = self.client_for().patch(METHODS, self.preference("FR", 0, 0), format="json")
        self.assertEqual(declared.status_code, 200, declared.data)

    def client_for(self):
        client = APIClient()
        client.force_authenticate(self.traveler)
        return client

    def preference(self, country, eur, dzd):
        return {"preference": "eur_only", "eur_revision": eur, "dzd_revision": dzd,
                "country": country, "consent_policy": "payout_profile_v1"}

    def declare(self, country):
        """A second session reading the setup, then sending its PATCH."""

        client = self.client_for()

        def run():
            revisions = client.get(METHODS).data["revisions"]
            return client.patch(
                METHODS, self.preference(country, revisions["EUR"], revisions["DZD"]),
                format="json")

        return run

    def onboard(self):
        client = self.client_for()
        return lambda: client.post(ONBOARDING, {}, format="json")

    def creations(self):
        return [kwargs for name, kwargs in self.gateway.calls if name == "create_account"]

    def wait_until_blocked_on_the_setup(self, pids):
        """Prove the trailing backend waits for this traveler's setup, held by the leader.

        Its own ungranted advisory lock on this traveler's setup key, and the
        leading backend among the ones blocking it. A trailing side that waits
        on a row lock instead, or never waits at all, does not satisfy it.
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
                        [pids["leading"], pids["trailing"], PAYOUT_ACCOUNT_SETUP_LOCK,
                         self.traveler.pk & 0x7FFFFFFF],
                    )
                    row = cursor.fetchone()
                if row is not None:
                    self.assertTrue(row[0], "The setup was held by another backend.")
                    return
            time.sleep(0.05)
        self.fail("The second side never waited on the traveler's account setup.")

    def race(self, first, second, *, pause):
        """Start `first`, hold it at `pause`, then start `second`; return both results."""

        holding, release = Event(), Event()
        target, attribute = pause
        original = getattr(target, attribute)
        pids = {}
        paused_once = []

        def paused(*args, **kwargs):
            if not paused_once:
                paused_once.append(True)
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
                self.assertTrue(holding.wait(30), "The first side never reached its pause.")
                trailing = pool.submit(in_own_connection(tracked("trailing", second)))
                self.wait_until_blocked_on_the_setup(pids)
            finally:
                release.set()
            return leading.result(timeout=60), trailing.result(timeout=60)

    def eur(self):
        return TravelerPayoutMethod.objects.get(traveler=self.traveler, currency="EUR")

    def bound_fr(self, onboarded):
        """The one FR request was sent and answered for FR, and bound."""

        self.assertEqual(onboarded.status_code, 201, onboarded.data)
        self.assertEqual([kwargs["country"] for kwargs in self.creations()], ["FR"])
        account = StripePayoutAccount.objects.get(traveler=self.traveler)
        bound = PayoutMethodVersion.objects.get(stripe_account=account)
        self.assertEqual(bound.country, "FR")
        # The response describes the declaration the call served, bound.
        self.assertEqual(onboarded.data["method"]["version"], str(bound.public_reference))
        return bound

    def assert_the_account_is_seen(self, declared, bound):
        """A DE choice made after the FR account exists is told about it at once."""

        self.assertEqual(declared.status_code, 200, declared.data)
        current = self.eur().current_version
        self.assertEqual((current.country, current.stripe_account_id), ("DE", None))
        self.assertGreater(current.sequence, bound.sequence)
        eur = declared.data["eur"]
        self.assertEqual(eur["unavailable_reason"], "stripe_account_country_mismatch")
        self.assertEqual(eur["account_country"], "FR")

    def test_a_preference_change_waits_for_the_creation_it_would_supersede(self):
        """Blocker: the intent is committed and the POST is on its way to Stripe.

        The change read the setup before the account was bound, so once the
        call has answered, its revision is stale and nothing changes. Read
        again, the Traveler sees the FR account, and a DE choice is told so.
        """

        onboarded, declared = self.race(
            self.onboard(), self.declare("DE"), pause=(Answering, "create_account"))
        bound = self.bound_fr(onboarded)
        self.assertEqual(declared.status_code, 400, declared.data)
        self.assertEqual(declared.data["code"], "payout_profile_invalid")
        self.assertEqual(self.eur().current_version_id, bound.pk)
        self.assert_the_account_is_seen(self.declare("DE")(), bound)
        self.assertEqual(len(self.creations()), 1)

    def test_a_preference_change_waits_until_the_link_is_handed_out(self):
        """Should-fix: the link and the method in one response describe one declaration.

        The change read the setup after the binding, so it commits once the
        link is out, and the response it gets shows the FR account.
        """

        onboarded, declared = self.race(
            self.onboard(), self.declare("DE"), pause=(FakeGateway, "create_account_link"))
        bound = self.bound_fr(onboarded)
        self.assertTrue(onboarded.data["onboarding_url"])
        self.assert_the_account_is_seen(declared, bound)

    def test_onboarding_waits_for_a_preference_change_and_serves_it(self):
        """A change that wins is the declaration served: no FR request is ever sent."""

        declared, onboarded = self.race(
            self.declare("DE"), self.onboard(), pause=(payout_profile_api, "set_preference"))
        self.assertEqual(declared.status_code, 200, declared.data)
        self.assertEqual(onboarded.status_code, 201, onboarded.data)
        self.assertEqual([kwargs["country"] for kwargs in self.creations()], ["DE"])
        current = TravelerPayoutMethod.objects.get(
            traveler=self.traveler, currency="EUR").current_version
        self.assertEqual(current.country, "DE")
        self.assertEqual(current.stripe_account.declared_country, "DE")

    def test_two_calls_for_one_declaration_create_once_and_both_succeed(self):
        """Should-fix: the second call finds the first one's account, bound."""

        first, second = self.race(
            self.onboard(), self.onboard(), pause=(Answering, "create_account"))
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(len(self.creations()), 1)
        account = StripePayoutAccount.objects.get(traveler=self.traveler)
        self.assertEqual(PayoutMethodVersion.objects.filter(stripe_account=account).count(), 1)
        self.assertEqual(PayoutProviderOperation.objects.get(kind="account_create").status,
                         "accepted")
        self.assertEqual(
            list(AdminAuditLog.objects.filter(
                action__in=("payout_account.bound", "payout_account.kept_unbound"))
                .values_list("action", flat=True)),
            ["payout_account.bound"])
        self.assertEqual(second.data["method"]["version"], first.data["method"]["version"])
