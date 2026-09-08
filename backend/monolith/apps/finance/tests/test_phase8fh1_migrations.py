"""Disposable PostgreSQL backward/forward rehearsal with historical rows."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
import unittest

from .factories import build_scenario
from apps.finance.models import Payout, PaymentAttempt


@unittest.skipUnless(
    connection.vendor == "postgresql", "PostgreSQL migration rehearsal"
)
class PayoutMigrationTests(TransactionTestCase):
    @override_settings(PAYOUT_PROFILES_ENABLED=False)
    def test_reverse_reapply_preserves_legacy_paid_and_unknown(self):
        from .test_concurrency import _seed_settings

        _seed_settings()
        scenario = build_scenario(prefix="h1migration")
        scenario.accept()
        payout = Payout.objects.create(
            deal=scenario.deal,
            traveler=scenario.traveler,
            amount_eur_cents=2000,
            method="manual",
            status="paid",
            eligible_at=timezone.now(),
            paid_at=timezone.now(),
            admin_actor=scenario.admin,
            reference="historical-proof",
            payout_currency="EUR",
            payout_amount_minor=2000,
            payout_amount_exponent=2,
        )
        other = build_scenario(prefix="h1migration-unpaid")
        other.accept()
        unpaid = Payout.objects.create(
            deal=other.deal,
            traveler=other.traveler,
            amount_eur_cents=2000,
            method="manual",
        )
        attempt = PaymentAttempt.objects.create(
            order=other.balance_order(),
            provider="stripe",
            amount_eur_cents=2500,
            payment_currency="EUR",
            provider_amount_minor=2500,
            status="failed",
            provider_session_id="cs_test_historical_fixture",
            idempotency_key="historical-mode",
        )
        executor = MigrationExecutor(connection)
        leaves = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate(
                [("finance", "0008_paymentattempt_operational_resolution_and_more")]
            )
            old = (
                MigrationExecutor(connection)
                .loader.project_state(
                    [("finance", "0008_paymentattempt_operational_resolution_and_more")]
                )
                .apps
            )
            historic = old.get_model("finance", "Payout").objects.get(pk=payout.pk)
            assert historic.reference == "historical-proof"
            assert historic.status == "paid"
        finally:
            MigrationExecutor(connection).migrate(leaves)
        payout.refresh_from_db()
        assert payout.amount_eur_cents == 2000
        assert payout.payout_currency == "EUR"
        assert payout.reference == "historical-proof"
        assert payout.legacy_classification == "legacy_paid"
        assert payout.provider_mode == "legacy_unknown"
        assert payout.snapshot_version == 0
        assert payout.funded_amount_eur_cents is None
        assert payout.fx_rate_micros is None
        assert payout.public_reference is not None
        unpaid.refresh_from_db()
        attempt.refresh_from_db()
        assert unpaid.status == "blocked"
        assert unpaid.block_reason == "legacy_instruction_required"
        assert unpaid.amount_eur_cents == 2000 and unpaid.fx_rate_micros is None
        assert unpaid.public_reference != payout.public_reference
        assert attempt.provider_mode == "test"
        assert attempt.mode_evidence == "historical_provider_evidence"
