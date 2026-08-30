"""Additive Phase 6C language columns preserve legacy rows and reverse cleanly."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class Phase6CLanguageMigrationTests(TransactionTestCase):
    migrate_from = [
        ("accounts", "0004_emailverificationcode"),
        ("deals", "0005_alter_deal_options"),
        ("finance", "0005_alter_payout_options"),
        ("notifications", "0003_alter_outboundmessage_kind_outboundsecret"),
    ]
    migrate_to = [
        ("accounts", "0005_user_preferred_language"),
        ("deals", "0006_dealrecipient_communication_language"),
        ("finance", "0006_guestpaymentlink_communication_language"),
        ("notifications", "0004_outboundmessage_language"),
    ]

    def _migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def setUp(self):
        super().setUp()
        self.latest_targets = MigrationExecutor(connection).loader.graph.leaf_nodes()
        self.addCleanup(self._migrate, self.latest_targets)
        old_apps = self._migrate(self.migrate_from)
        User = old_apps.get_model("accounts", "User")
        OutboundMessage = old_apps.get_model("notifications", "OutboundMessage")
        self.user_id = User.objects.create(
            username="phase6c-legacy@example.test",
            email="phase6c-legacy@example.test",
            password="!",
        ).pk
        self.message_id = OutboundMessage.objects.create(
            key="phase6c:migration:legacy-message",
            kind="security_event",
            to_email="phase6c-legacy@example.test",
            context={"summary": "Legacy row"},
        ).pk

    def test_forward_defaults_are_deterministic_and_reverse_preserves_rows(self):
        new_apps = self._migrate(self.migrate_to)
        User = new_apps.get_model("accounts", "User")
        DealRecipient = new_apps.get_model("deals", "DealRecipient")
        GuestPaymentLink = new_apps.get_model("finance", "GuestPaymentLink")
        OutboundMessage = new_apps.get_model("notifications", "OutboundMessage")

        self.assertEqual(User.objects.get(pk=self.user_id).preferred_language, "")
        self.assertEqual(
            OutboundMessage.objects.get(pk=self.message_id).language, "en"
        )
        self.assertEqual(
            DealRecipient._meta.get_field("communication_language").default, ""
        )
        self.assertEqual(
            GuestPaymentLink._meta.get_field("communication_language").default,
            "en",
        )

        old_apps = self._migrate(self.migrate_from)
        OldUser = old_apps.get_model("accounts", "User")
        OldMessage = old_apps.get_model("notifications", "OutboundMessage")
        self.assertTrue(OldUser.objects.filter(pk=self.user_id).exists())
        self.assertTrue(OldMessage.objects.filter(pk=self.message_id).exists())
