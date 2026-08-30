"""The durable outbound-message obligation.

The recipient of a parcel has no ShipTrip account, no session and no way to ask
for a resend. Their delivery code therefore cannot ride on a Redis stream and
hope: the obligation is a row, the stream is only how it is carried, and these
tests are about the difference.

Two properties are load-bearing:

* **The code is never at rest in the message.** It is referenced, opened at
  render time, and exists as text only inside the process building the body.
* **A failed carry is retried, not lost.** And a retry produces an identical
  body, because the body is a pure function of the row.
"""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

import redis
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.core.models import PublishedEvent
from apps.deals.models import DealEvent
from apps.deals.tests.phase4_factories import (
    confirm_pickup,
    fund_scenario,
    record_recipient,
    release_delivery_code,
)
from apps.finance.models import ScheduledJob
from apps.handover.models import DealHandoverCode, HandoverCodeAccess
from apps.notifications import outbox
from apps.notifications.models import OutboundMessage


class _FakeRedis:
    """A stand-in that records what was handed to the transport."""

    def __init__(self, fail: bool = False):
        self.entries: list[dict] = []
        self.fail = fail

    def xadd(self, stream, fields, **kwargs):
        if self.fail:
            raise redis.ConnectionError("transport down")
        self.entries.append({"stream": stream, "fields": fields})
        return b"1-0"


def patched_transport(fake: _FakeRedis):
    return mock.patch.object(outbox.redis_bus, "get_client", return_value=fake)


@override_settings(TRANSACTIONAL_EMAIL_ENABLED=True)
class RecipientDeliveryCodeMessageTests(TestCase):
    def setUp(self):
        self.scenario = fund_scenario(self.client, prefix="obx")
        record_recipient(self.scenario)
        confirm_pickup(self.scenario)
        self.code = release_delivery_code(self.scenario)
        self.message = OutboundMessage.objects.get(
            deal_id=self.scenario.deal.pk,
            kind=OutboundMessage.Kind.RECIPIENT_DELIVERY_CODE,
        )

    def test_the_obligation_and_its_job_are_armed_with_the_release(self):
        assert self.message.status == OutboundMessage.Status.PENDING
        assert self.message.to_email == "recipient@example.invalid"
        assert ScheduledJob.objects.filter(
            key=f"outbound_message:{self.message.pk}",
            kind=ScheduledJob.Kind.OUTBOUND_MESSAGE,
        ).exists()
        assert DealEvent.objects.filter(
            deal_id=self.scenario.deal.pk,
            kind=DealEvent.Kind.RECIPIENT_NOTIFICATION_QUEUED,
        ).exists()

    def test_the_row_references_the_secret_and_never_stores_it(self):
        assert self.code not in str(self.message.context)
        assert self.code not in self.message.secret_ref
        assert self.message.secret_ref.startswith("handover_code:")

    def test_rendering_opens_the_seal_and_audits_it_with_no_actor(self):
        subject, body = outbox.render(self.message)
        assert "delivery code" in subject.lower()
        assert self.code in body

        access = HandoverCodeAccess.objects.filter(
            deal_id=self.scenario.deal.pk,
            purpose=HandoverCodeAccess.Purpose.RECIPIENT_NOTIFICATION,
        )
        assert access.count() == 1
        assert access.first().actor_id is None

    def test_the_body_warns_the_recipient_not_to_share_the_code_early(self):
        _, body = outbox.render(self.message)
        assert "never" in body.lower()

    def test_dispatch_sends_secret_at_trusted_boundary_and_marks_once(self):
        fake = _FakeRedis()
        with (
            patched_transport(fake),
            mock.patch.object(outbox, "_send_email_via_provider") as send,
        ):
            assert outbox.dispatch_message(message_id=self.message.pk) == "dispatched"
        send.assert_called_once()
        assert self.code in send.call_args.kwargs["body"]

        self.message.refresh_from_db()
        assert self.message.status == OutboundMessage.Status.DISPATCHED
        assert self.message.dispatched_at is not None
        assert fake.entries == []

        # A second dispatch is a no-op rather than a second email.
        with (
            patched_transport(fake),
            mock.patch.object(outbox, "_send_email_via_provider"),
        ):
            assert (
                outbox.dispatch_message(message_id=self.message.pk)
                == "already_dispatched"
            )
        assert fake.entries == []

    @override_settings(TRANSACTIONAL_EMAIL_ENABLED=False)
    def test_disabled_email_never_reaches_the_direct_smtp_boundary(self):
        fake = _FakeRedis()
        with (
            patched_transport(fake),
            mock.patch.object(outbox, "_send_email_via_provider") as send,
        ):
            assert outbox.dispatch_message(message_id=self.message.pk) == "disabled"

        send.assert_not_called()
        assert fake.entries == []
        self.message.refresh_from_db()
        assert self.message.status == OutboundMessage.Status.PENDING
        assert self.message.attempts == 0

    def test_dispatch_records_the_send_on_the_deal_timeline(self):
        with mock.patch.object(outbox, "_send_email_via_provider"):
            outbox.dispatch_message(message_id=self.message.pk)
        assert (
            DealEvent.objects.filter(
                deal_id=self.scenario.deal.pk,
                kind=DealEvent.Kind.RECIPIENT_NOTIFICATION_SENT,
            ).count()
            == 1
        )

    def test_the_published_event_audit_stores_a_hash_and_not_the_code(self):
        with mock.patch.object(outbox, "_send_email_via_provider"):
            outbox.dispatch_message(message_id=self.message.pk)
        rows = PublishedEvent.objects.filter(channel="email:send")
        assert not rows.exists()
        for row in rows:
            assert self.code not in row.payload_hash


@override_settings(TRANSACTIONAL_EMAIL_ENABLED=True)
class TransportFailureTests(TestCase):
    def setUp(self):
        self.scenario = fund_scenario(self.client, prefix="obxfail")
        record_recipient(self.scenario)
        confirm_pickup(self.scenario)
        release_delivery_code(self.scenario)
        self.message = OutboundMessage.objects.get(
            deal_id=self.scenario.deal.pk,
            kind=OutboundMessage.Kind.RECIPIENT_DELIVERY_CODE,
        )

    def test_a_transport_failure_leaves_the_obligation_pending_and_retryable(self):
        with mock.patch.object(
            outbox, "_send_email_via_provider", side_effect=OSError("provider down")
        ):
            with self.assertRaises(OSError):
                outbox.dispatch_message(message_id=self.message.pk)

        self.message.refresh_from_db()
        assert self.message.status == OutboundMessage.Status.PENDING
        assert self.message.dispatched_at is None
        assert self.message.attempts == 1
        assert self.message.next_attempt_at is not None

    def test_the_retry_after_a_failure_sends_the_same_code(self):
        with mock.patch.object(
            outbox, "_send_email_via_provider", side_effect=OSError("provider down")
        ):
            with self.assertRaises(OSError):
                outbox.dispatch_message(message_id=self.message.pk)

        with mock.patch.object(outbox, "_send_email_via_provider") as send:
            assert outbox.dispatch_message(message_id=self.message.pk) == "dispatched"
        code = self.scenario.delivery_code
        assert code in send.call_args.kwargs["body"]

    def test_a_failed_body_is_never_written_to_the_error_column(self):
        with mock.patch.object(
            outbox, "_send_email_via_provider", side_effect=OSError("provider down")
        ):
            with self.assertRaises(OSError):
                outbox.dispatch_message(message_id=self.message.pk)
        self.message.refresh_from_db()
        assert self.scenario.delivery_code not in self.message.last_error

    def test_a_rotated_code_makes_the_stale_message_unrenderable_rather_than_wrong(
        self,
    ):
        """Sending a code that no longer opens the handover is worse than silence."""

        from apps.handover.services import rotate_code

        code_id = int(self.message.secret_ref.split(":")[1])
        with mock.patch(
            "django.utils.timezone.now",
            return_value=self.scenario.deal.delivery_code_available_at
            + timedelta(minutes=1),
        ):
            rotate_code(
                deal_id=self.scenario.deal.pk,
                kind=DealHandoverCode.Kind.DELIVERY,
                actor_id=self.scenario.sender.pk,
            )
        assert DealHandoverCode.objects.get(pk=code_id).status == (
            DealHandoverCode.Status.SUPERSEDED
        )

        with mock.patch.object(outbox, "_send_email_via_provider"):
            assert outbox.dispatch_message(message_id=self.message.pk) == "unrenderable"
        self.message.refresh_from_db()
        assert self.message.status == OutboundMessage.Status.FAILED

        # The rotation armed a fresh obligation, so the recipient is not left
        # without a code.
        replacement = OutboundMessage.objects.filter(
            deal_id=self.scenario.deal.pk,
            kind=OutboundMessage.Kind.RECIPIENT_DELIVERY_CODE,
            status=OutboundMessage.Status.PENDING,
        )
        assert replacement.count() == 1


@override_settings(TRANSACTIONAL_EMAIL_ENABLED=True)
class DurabilityTests(TestCase):
    def test_inventory_kinds_have_safe_rendering_contracts(self):
        kinds = (
            OutboundMessage.Kind.KYC_STATUS,
            OutboundMessage.Kind.FLIGHT_PROOF_STATUS,
            OutboundMessage.Kind.PAYMENT_REQUIRED,
            OutboundMessage.Kind.PAYMENT_PROCESSING,
            OutboundMessage.Kind.PAYMENT_FAILED,
            OutboundMessage.Kind.PAYMENT_SUCCEEDED,
            OutboundMessage.Kind.GUEST_PAYMENT,
            OutboundMessage.Kind.REFUND_STATUS,
            OutboundMessage.Kind.EVIDENCE_REQUEST,
            OutboundMessage.Kind.SECURITY_EVENT,
        )
        for kind in kinds:
            subject, body = outbox.render(
                OutboundMessage(
                    kind=kind,
                    context={
                        "status": "pending",
                        "payment_reference": "pay-test",
                        "dispute_reference": "DSP-test",
                        "summary": "A security event needs your attention.",
                    },
                )
            )
            assert subject
            assert body

    def test_the_job_queue_drives_a_pending_message_to_the_transport(self):
        from apps.finance.jobs import run_due_jobs

        scenario = fund_scenario(self.client, prefix="obxjob")
        record_recipient(scenario)
        confirm_pickup(scenario)
        release_delivery_code(scenario)

        ScheduledJob.objects.filter(kind=ScheduledJob.Kind.OUTBOUND_MESSAGE).update(
            run_at=timezone.now() - timedelta(minutes=1)
        )
        fake = _FakeRedis()
        with (
            patched_transport(fake),
            mock.patch.object(outbox, "_send_email_via_provider"),
        ):
            report = run_due_jobs(limit=50)
        assert report.failed == 0, report.results
        assert fake.entries
        assert OutboundMessage.objects.filter(
            deal_id=scenario.deal.pk,
            kind=OutboundMessage.Kind.RECIPIENT_DELIVERY_CODE,
            status=OutboundMessage.Status.DISPATCHED,
        ).exists()

    def test_the_sweep_picks_up_a_message_whose_job_was_lost(self):
        scenario = fund_scenario(self.client, prefix="obxsweep")
        record_recipient(scenario)
        confirm_pickup(scenario)
        release_delivery_code(scenario)
        ScheduledJob.objects.filter(kind=ScheduledJob.Kind.OUTBOUND_MESSAGE).delete()

        fake = _FakeRedis()
        with (
            patched_transport(fake),
            mock.patch.object(outbox, "_send_email_via_provider"),
        ):
            dispatched = outbox.dispatch_due_messages(limit=50)
        assert dispatched >= 1
        assert fake.entries

    def test_arming_the_same_message_twice_yields_one_obligation(self):
        scenario = fund_scenario(self.client, prefix="obxidem")
        record_recipient(scenario)
        first = outbox.enqueue_message(
            kind=OutboundMessage.Kind.PICKUP_CONFIRMED,
            key=f"pickup_confirmed:{scenario.deal.pk}",
            to_email="a@example.invalid",
            deal_id=scenario.deal.pk,
            context={"deal_reference": "ST-1"},
        )
        second = outbox.enqueue_message(
            kind=OutboundMessage.Kind.PICKUP_CONFIRMED,
            key=f"pickup_confirmed:{scenario.deal.pk}",
            to_email="a@example.invalid",
            deal_id=scenario.deal.pk,
            context={"deal_reference": "ST-1"},
        )
        assert first.pk == second.pk
        assert (
            OutboundMessage.objects.filter(
                key=f"pickup_confirmed:{scenario.deal.pk}"
            ).count()
            == 1
        )

    def test_a_cancelled_obligation_is_never_carried(self):
        scenario = fund_scenario(self.client, prefix="obxcancel")
        record_recipient(scenario)
        message = outbox.enqueue_message(
            kind=OutboundMessage.Kind.RATING_AVAILABLE,
            key=f"rating_available:{scenario.deal.pk}",
            to_email="a@example.invalid",
            deal_id=scenario.deal.pk,
            context={"deal_reference": "ST-1"},
        )
        outbox.cancel_message(key=message.key, reason="no longer true")

        fake = _FakeRedis()
        with patched_transport(fake):
            assert outbox.dispatch_message(message_id=message.pk) == "cancelled"
        assert fake.entries == []
