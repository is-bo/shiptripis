"""Phase 6C language snapshots and recipient-email confidentiality."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase

from apps.accounts.models import User
from apps.deals.models import DealRecipient
from apps.deals.serializers import DealRecipientWriteSerializer
from apps.deals.tests.phase4_factories import (
    confirm_delivery,
    confirm_pickup,
    fund_scenario,
    record_recipient,
    release_delivery_code,
)
from apps.disputes.models import Dispute
from apps.disputes.services import open_dispute
from apps.finance.models import ScheduledJob
from apps.notifications.email_layout import EmailDocument, to_html, to_text
from apps.notifications.models import OutboundMessage
from apps.notifications.outbox import (
    dispatch_message,
    enqueue_message,
    render,
    render_parts,
)


class LanguageSnapshotTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="locale@example.test",
            email="locale@example.test",
            password="Strong-pass-123!",
            full_name="Locale Test",
            preferred_language="fr",
        )

    def test_queued_message_keeps_language_after_profile_change(self):
        message = enqueue_message(
            kind=OutboundMessage.Kind.KYC_STATUS,
            key="phase6c:language-snapshot",
            to_email=self.user.email,
            recipient_user_id=self.user.pk,
            context={"status": "approved"},
        )
        User.objects.filter(pk=self.user.pk).update(preferred_language="ar")

        message.refresh_from_db()
        subject, body = render(message)
        self.assertEqual(message.language, "fr")
        self.assertIn("identité", subject.lower())
        self.assertIn("approuvée", body.lower())

    def test_internal_invalid_language_falls_back_to_complete_english(self):
        message = enqueue_message(
            kind=OutboundMessage.Kind.KYC_STATUS,
            key="phase6c:invalid-language-fallback",
            to_email=self.user.email,
            language="de",
            context={"status": "approved"},
        )

        self.assertEqual(message.language, "en")
        subject, _ = render(message)
        self.assertIn("identity", subject.lower())

    def test_same_logical_key_does_not_change_the_snapshot(self):
        first = enqueue_message(
            kind=OutboundMessage.Kind.KYC_STATUS,
            key="phase6c:idempotent-language",
            to_email=self.user.email,
            language="fr",
            context={"status": "approved"},
        )
        second = enqueue_message(
            kind=OutboundMessage.Kind.KYC_STATUS,
            key="phase6c:idempotent-language",
            to_email=self.user.email,
            language="ar",
            context={"status": "action_required"},
        )

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(second.language, "fr")
        self.assertEqual(second.context, {"status": "approved"})

    def test_launch_templates_render_localized_subject_body_and_footer(self):
        cases = (
            (OutboundMessage.Kind.EMAIL_VERIFICATION, {}),
            (OutboundMessage.Kind.PASSWORD_RESET, {}),
            (OutboundMessage.Kind.KYC_STATUS, {"status": "approved"}),
            (OutboundMessage.Kind.KYC_STATUS, {"status": "action_required"}),
            (OutboundMessage.Kind.FLIGHT_PROOF_STATUS, {"status": "approved"}),
            (
                OutboundMessage.Kind.FLIGHT_PROOF_STATUS,
                {"status": "action_required"},
            ),
            (OutboundMessage.Kind.PAYMENT_FAILED, {"status": "failed"}),
            (OutboundMessage.Kind.GUEST_PAYMENT, {"status": "succeeded"}),
            (OutboundMessage.Kind.GUEST_PAYMENT, {"status": "failed"}),
            (OutboundMessage.Kind.REFUND_STATUS, {"status": "pending"}),
            (OutboundMessage.Kind.REFUND_STATUS, {"status": "succeeded"}),
            (
                OutboundMessage.Kind.SECURITY_EVENT,
                {"event": "password_reset_completed"},
            ),
            (
                OutboundMessage.Kind.PROTECTION_ENDING,
                {"protection_ends_at": "2026-09-01T10:00:00Z"},
            ),
        )
        footer_markers = {
            "fr": "message transactionnel",
            "ar": "رسالة معاملات",
        }
        for kind, context in cases:
            english_subject, _, _ = render_parts(
                OutboundMessage(kind=kind, language="en", context=context)
            )
            for language in ("fr", "ar"):
                with self.subTest(kind=kind, language=language, context=context):
                    subject, text, html = render_parts(
                        OutboundMessage(
                            kind=kind,
                            language=language,
                            context=context,
                        )
                    )
                    self.assertNotEqual(subject, english_subject)
                    self.assertIn(footer_markers[language], text)
                    self.assertIn(footer_markers[language], html)
                    expected_direction = "rtl" if language == "ar" else "ltr"
                    self.assertIn(
                        f'<html lang="{language}" dir="{expected_direction}">',
                        html,
                    )


class RecipientLanguageContractTests(TestCase):
    def test_serializer_accepts_only_supported_recipient_languages(self):
        valid = DealRecipientWriteSerializer(
            data={
                "full_name": "Recipient",
                "email": "recipient@example.test",
                "communication_language": "ar",
            }
        )
        self.assertTrue(valid.is_valid(), valid.errors)
        self.assertEqual(valid.validated_data["communication_language"], "ar")

        invalid = DealRecipientWriteSerializer(
            data={
                "full_name": "Recipient",
                "email": "recipient@example.test",
                "communication_language": "de",
            }
        )
        self.assertFalse(invalid.is_valid())
        self.assertIn("communication_language", invalid.errors)

    def test_explicit_recipient_language_controls_the_delivery_code_email(self):
        expected = {
            "en": "Your parcel is on its way",
            "fr": "Votre colis est en route",
            "ar": "طردك في الطريق",
        }
        for language, heading in expected.items():
            with self.subTest(language=language):
                scenario = fund_scenario(self.client, prefix=f"p6c-{language}")
                record_recipient(scenario, communication_language=language)
                confirm_pickup(scenario)
                code = release_delivery_code(scenario)
                message = OutboundMessage.objects.get(
                    deal_id=scenario.deal.pk,
                    kind=OutboundMessage.Kind.RECIPIENT_DELIVERY_CODE,
                )

                subject, text, html = render_parts(message)
                self.assertEqual(message.language, language)
                self.assertIn(heading, html)
                self.assertIn(code, text)
                self.assertIn(code, html)
                self.assertNotIn(code, str(message.context))
                self.assertNotIn(code, message.secret_ref)
                self.assertNotIn(code, message.key)
                if language == "ar":
                    self.assertIn('<html lang="ar" dir="rtl">', html)
                    self.assertIn('class="st-code" dir="ltr"', html)
                    self.assertIn(f"\u2066{code}\u2069", text)
                else:
                    self.assertIn(f'<html lang="{language}" dir="ltr">', html)
                self.assertTrue(subject)

    def test_legacy_recipient_without_language_uses_english(self):
        scenario = fund_scenario(self.client, prefix="p6c-legacy-recipient")
        record_recipient(scenario, communication_language="fr")
        DealRecipient.objects.filter(deal_id=scenario.deal.pk).update(
            communication_language=""
        )
        confirm_pickup(scenario)
        release_delivery_code(scenario)

        message = OutboundMessage.objects.get(
            deal_id=scenario.deal.pk,
            kind=OutboundMessage.Kind.RECIPIENT_DELIVERY_CODE,
        )
        subject, _ = render(message)
        self.assertEqual(message.language, "en")
        self.assertEqual(subject, "Your ShipTrip delivery code")


class ProtectionEndingReminderTests(TestCase):
    def test_delivery_confirmation_arms_one_durable_24_hour_reminder_per_party(self):
        scenario = fund_scenario(self.client, prefix="p6c-protection")
        scenario.sender.preferred_language = "fr"
        scenario.sender.save(update_fields=("preferred_language",))
        scenario.traveler.preferred_language = "ar"
        scenario.traveler.save(update_fields=("preferred_language",))
        record_recipient(scenario)
        confirm_pickup(scenario)
        release_delivery_code(scenario)
        confirm_delivery(scenario)

        deadline = scenario.deal.protection_ends_at
        self.assertIsNotNone(deadline)
        messages = OutboundMessage.objects.filter(
            deal_id=scenario.deal.pk,
            kind=OutboundMessage.Kind.PROTECTION_ENDING,
        ).order_by("recipient_user_id")
        self.assertEqual(messages.count(), 2)
        self.assertEqual({row.language for row in messages}, {"fr", "ar"})
        self.assertEqual(
            {row.context["reminder_seconds"] for row in messages}, {86_400}
        )
        for message in messages:
            self.assertEqual(message.next_attempt_at, deadline - timedelta(hours=24))
            job = ScheduledJob.objects.get(
                kind=ScheduledJob.Kind.OUTBOUND_MESSAGE,
                key=f"outbound_message:{message.pk}",
            )
            self.assertEqual(job.run_at, deadline - timedelta(hours=24))

    def test_open_dispute_cancels_pending_reminders_and_jobs(self):
        scenario = fund_scenario(self.client, prefix="p6c-protection-dispute")
        record_recipient(scenario)
        confirm_pickup(scenario)
        release_delivery_code(scenario)
        confirm_delivery(scenario)
        messages = list(
            OutboundMessage.objects.filter(
                deal_id=scenario.deal.pk,
                kind=OutboundMessage.Kind.PROTECTION_ENDING,
            )
        )

        open_dispute(
            deal_id=scenario.deal.pk,
            actor_id=scenario.sender.pk,
            category=Dispute.Category.DAMAGED,
            reason_text="The parcel arrived damaged.",
        )

        self.assertEqual(len(messages), 2)
        self.assertEqual(
            OutboundMessage.objects.filter(
                pk__in=[message.pk for message in messages],
                status=OutboundMessage.Status.CANCELLED,
            ).count(),
            2,
        )
        self.assertEqual(
            ScheduledJob.objects.filter(
                key__in=[f"outbound_message:{message.pk}" for message in messages],
                status=ScheduledJob.Status.CANCELLED,
            ).count(),
            2,
        )
        with patch("apps.notifications.outbox._xadd_email") as transport:
            for message in messages:
                self.assertEqual(dispatch_message(message_id=message.pk), "cancelled")
        transport.assert_not_called()


class ArabicMixedDirectionTests(TestCase):
    def test_plain_text_isolates_machine_values_and_html_does_not_track_arabic(self):
        document = EmailDocument(
            subject="اختبار",
            heading="اختبار",
            eyebrow="الأمان",
            highlight=("الرمز", "AB12CD"),
            action=("افتح ShipTrip", "https://example.test/path?q=123"),
            facts=(("المرجع", "ST-1234"),),
        )

        text = to_text(
            document,
            support_email="support@example.test",
            language="ar",
        )
        html = to_html(
            document,
            support_email="support@example.test",
            site_url="https://example.test",
            language="ar",
        )

        for value in (
            "AB12CD",
            "https://example.test/path?q=123",
            "ST-1234",
            "support@example.test",
        ):
            self.assertIn(f"\u2066{value}\u2069", text)
        self.assertIn("letter-spacing:0;text-transform:none;", html)
        self.assertIn('href="mailto:support@example.test" dir="ltr"', html)
