"""Plan L19 item 2: a payout carries the mode of the money that funded it.

With payout profiles off (the shipped example configuration, and every test
that does not turn them on), `ensure_payout_for_deal` created the payout with
no mode, so it took the column's default `legacy_unknown` while its funding was
in test mode. The finance dashboard then split one deal's traveler balance
across two modes (release report, section 14, finding 2). The payout now takes
its funding attempt's mode, through the same lookup the profile path uses.
"""

from __future__ import annotations

import base64
import csv
import io
import json
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.admin_panel.tests.two_step_helpers import staff_login
from apps.core.tests.business_settings_seed import seed_business_settings
from apps.core.tests.l10_world import DRIVE, AcceptanceWorld
from apps.core.tests.test_l10_staff_and_accounts import seed_admin_roles
from apps.deals.tests.phase4_factories import enable_mock_rail, freeze_at
from apps.discovery.tests.support import STATIC_STORES
from apps.finance.control_plane.filters import Scope
from apps.finance.control_plane.snapshot import build_snapshot
from apps.finance.models import (
    LedgerTransaction,
    PaymentAttempt,
    PaymentOrder,
    Payout,
)
from apps.finance.payout_snapshots import deal_funding_order, funding_attempt
from apps.finance.services import ensure_payout_for_deal

from .factories import build_scenario

KEYRING = {
    "PAYOUT_DATA_KEYRING": json.dumps({"l19": base64.b64encode(b"n" * 32).decode()}),
    "PAYOUT_DATA_ACTIVE_KEY_ID": "l19",
    "PAYOUT_ACCOUNT_FINGERPRINT_KEY": base64.b64encode(b"o" * 32).decode(),
}


@override_settings(PAYOUT_PROFILES_ENABLED=False)
class UnfundedPayoutTests(TestCase):
    def test_a_payout_with_no_capture_behind_it_stays_legacy_unknown(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="l19")
        scenario.accept(reward_eur_cents=3_200)
        assert scenario.balance_order() is not None
        assert not PaymentAttempt.objects.filter(
            order__deal=scenario.deal, status="succeeded"
        ).exists()

        payout = ensure_payout_for_deal(
            deal_id=scenario.deal.pk,
            traveler_id=scenario.traveler.pk,
            amount_eur_cents=3_200,
        )

        assert payout.provider_mode == "legacy_unknown"


@override_settings(STORAGES=STATIC_STORES, PAYOUT_PROFILES_ENABLED=False)
class FundedPayoutModeTests(AcceptanceWorld, TransactionTestCase):
    """A transaction test: the dashboard reads its own standalone snapshot."""

    def setUp(self):
        cache.clear()
        seed_business_settings()
        seed_admin_roles()
        self.build_acceptance_world()

    def download(self, kind: str, mode: str) -> list[dict]:
        today = timezone.now().date()
        response = self.client.post(
            reverse("admin_console:finance-exports"),
            {
                "kind": kind,
                "mode": mode,
                "start": (today - timedelta(days=5)).isoformat(),
                "end": today.isoformat(),
            },
        )
        assert response.status_code == 200, response.content[:500]
        text = b"".join(response.streaming_content).decode("utf-8")
        return list(csv.DictReader(io.StringIO(text.lstrip("﻿"), newline="")))

    @staticmethod
    def cents(text: str) -> int:
        return int(Decimal(text) * 100)

    def test_a_deal_settled_by_hand_is_in_its_funding_mode_everywhere(self):
        depart = self.now + timedelta(hours=3)
        journey = self.post_trip(
            [self.leg_payload(DRIVE, self.algiers, self.setif, depart, hours=3)]
        )
        self.publish(journey)
        self.set_price(journey, 400, 1_000)
        journey.refresh_from_db()
        (leg,) = journey.legs.all()
        parcel = self.post_parcel(
            self.algiers,
            self.setif,
            ready_from=leg.depart_at - timedelta(hours=1),
            ready_until=leg.depart_at + timedelta(minutes=30),
            deliver_by=leg.arrive_at + timedelta(hours=6),
        )
        self.pay_deposit(parcel)
        # Funding, delivery, protection and the payout settled by hand.
        deal = self.carry(journey, parcel, leg, leg)

        payout = Payout.objects.get(deal=deal)
        assert payout.status == Payout.Status.PAID
        assert payout.snapshot_version == 0, "the path without payout profiles"
        source = funding_attempt(deal_funding_order(deal.pk))
        assert source is not None and source.provider_mode == "test"
        assert payout.provider_mode == source.provider_mode

        # Nothing of this deal is in another mode: its payments, its payout
        # and every ledger transaction that touches it.
        attempts = PaymentAttempt.objects.filter(
            order__in=PaymentOrder.objects.filter(deal=deal), status="succeeded"
        )
        assert set(attempts.values_list("provider_mode", flat=True)) == {"test"}
        transactions = LedgerTransaction.objects.filter(
            entries__deal_id=deal.pk
        ).distinct()
        kinds = set(transactions.values_list("kind", flat=True))
        assert {"deal_funding", "payout"} <= kinds, kinds
        assert set(transactions.values_list("provider_mode", flat=True)) == {"test"}

        with (
            override_settings(**KEYRING),
            freeze_at(deal.protection_ends_at + timedelta(days=1)),
        ):
            staff_login(self.client, self.finance)
            payouts = self.download("payouts", "test")
            exports_unknown = {
                kind: self.download(kind, "legacy_unknown")
                for kind in ("transactions", "commissions", "payouts")
            }
            transactions_file = self.download("transactions", "test")
            commissions = self.download("commissions", "test")
            board = build_snapshot(Scope.parse({"mode": "test"}))
            unknown = build_snapshot(Scope.parse({"mode": "legacy_unknown"}))

        def amount(snapshot, key):
            return snapshot["metrics"][key]["amount_eur_cents"]

        reward = deal.terms.traveler_reward_minor
        # The dashboard in test mode holds the whole deal: the traveler was
        # owed the reward and has been paid it, so nothing is outstanding.
        assert amount(board, "payouts_settled") == reward
        assert amount(board, "traveler_outstanding") == 0
        # And nothing of it is in `legacy_unknown`.
        for key, metric in unknown["metrics"].items():
            assert metric.get("amount_eur_cents", 0) == 0, (key, metric)
        assert not any(exports_unknown.values()), exports_unknown

        # The three exports reconcile with the dashboard for that mode.
        (row,) = payouts
        assert row["Tracking number"] == deal.delivery_request.tracking_number
        assert row["Status"] == "paid"
        assert self.cents(row["Amount"]) == reward == amount(board, "payouts_settled")
        assert sum(self.cents(r["Fee kept"]) for r in commissions) == amount(
            board, "recognized_revenue"
        )
        assert sum(
            self.cents(r["Amount"])
            for r in transactions_file
            if r["Type"] == "payment" and r["Status"] == "succeeded"
        ) == amount(board, "gross_funded")
