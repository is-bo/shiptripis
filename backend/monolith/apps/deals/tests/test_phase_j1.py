"""J1 boundary regressions, using the real funded-deal scaffold."""
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.db import transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.chat.models import ChatMessage
from apps.core.redis_bus import publish_after_commit
from apps.deals.activity import activity_q
from apps.deals.models import Deal
from apps.disputes.services import can_open_dispute
from apps.finance.models import ScheduledJob
from apps.notifications.models import Notification
from apps.notifications.resolution import resolved_notifications
from apps.trips.lifecycle import discoverable, with_lifecycle
from apps.trips.models import Journey, JourneyLeg
from .phase4_factories import fund_scenario


class J1Contracts(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.finance.tests.test_phase4_concurrency import _seed_phase4_settings
        _seed_phase4_settings()
        from importlib import import_module
        from django.apps import apps
        import_module("apps.core.migrations.0009_seed_boost_economics").seed_boost_economics(apps, None)
        cls.scenario = fund_scenario(APIClient(), prefix="j1")
        cls.deal_id = cls.scenario.deal.pk

    def setUp(self):
        self.deal = Deal.objects.get(pk=self.deal_id)
        self.client = APIClient()
        self.client.force_authenticate(self.scenario.sender)

    def test_chat_ack_replay_conflict_and_party_boundary(self):
        path = f"/api/matches/{self.deal.match_id}/chat/messages"
        body = {"body": "Synthetic J1 message", "client_message_id": str(uuid4())}
        with patch("apps.notifications.transport.dispatch_promptly"):
            first = self.client.post(path, body, format="json")
            replay = self.client.post(path, body, format="json")
            self.assertEqual(first.status_code, 201, first.data)
            self.assertEqual(replay.status_code, 200, replay.data)
            self.assertEqual(first.data["id"], replay.data["id"])
            self.assertEqual(self.client.post(path, {**body, "body": "Different"}, format="json").status_code, 409)
        self.assertEqual(ChatMessage.objects.filter(match_id=self.deal.match_id).count(), 1)
        inbox = Notification.objects.get(channel="chat.message.new", recipient=self.scenario.traveler)
        self.assertEqual(set(inbox.payload["targets"]), {self.deal.sender_id, self.deal.traveler_id})
        self.assertFalse(Notification.objects.filter(channel="chat.message.new", recipient=self.scenario.sender).exists())
        self.client.force_authenticate(self.scenario.traveler)
        delta = self.client.get(path, {"after_id": 0})
        self.assertEqual(delta.data["results"][0]["id"], first.data["id"])
        self.client.force_authenticate(self.scenario.outsider)
        self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(self.client.post(path, body, format="json").status_code, 403)

    def test_dispute_deadline_and_completed_history(self):
        from .phase4_factories import record_recipient, confirm_pickup, release_delivery_code, confirm_delivery
        record_recipient(self.scenario)
        confirm_pickup(self.scenario)
        release_delivery_code(self.scenario)
        confirm_delivery(self.scenario)
        self.deal.refresh_from_db()
        now = timezone.now()
        self.deal.protection_ends_at = now
        self.deal.save(update_fields=["protection_ends_at"])
        self.assertTrue(can_open_dispute(deal=self.deal, viewer_id=self.deal.sender_id, at=now-timedelta(microseconds=1)))
        self.assertFalse(can_open_dispute(deal=self.deal, viewer_id=self.deal.sender_id, at=now))
        self.assertFalse(Deal.objects.filter(pk=self.deal.pk).filter(activity_q("active")).exists())
        self.assertTrue(Deal.objects.filter(pk=self.deal.pk).filter(activity_q("completed")).exists())
        response = self.client.get(f"/api/deals/{self.deal.pk}")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("open_dispute", response.data["available_actions"])

    def test_expiry_multileg_and_funded_dependency(self):
        now = timezone.now()
        journey = self.deal.journey
        JourneyLeg.objects.filter(journey=journey).update(depart_at=now-timedelta(hours=3), arrive_at=now-timedelta(hours=1))
        rows = Journey.objects.filter(pk=journey.pk)
        self.assertFalse(discoverable(rows).exists())
        from apps.matching.discovery import compatible_journeys_for_request, phase2_policy
        self.assertEqual(compatible_journeys_for_request(
            delivery_request=self.scenario.delivery_request, policy=phase2_policy(), at=now), [])
        self.assertEqual(with_lifecycle(rows).get().lifecycle_status, "active")
        Deal.objects.filter(pk=self.deal.pk).update(status="cancelled")
        self.assertEqual(with_lifecycle(rows).get().lifecycle_status, "expired")
        leg = journey.legs.first()
        leg.pk = None
        leg.position += 1
        leg.origin_id = leg.destination_id
        leg.destination_id = self.scenario.delivery_request.pickup_location_id
        leg.depart_at = now + timedelta(hours=1)
        leg.arrive_at = now + timedelta(hours=2)
        leg.save()
        journey.destination_location_id = leg.destination_id
        journey.save(update_fields=["destination_location"])
        self.assertTrue(discoverable(rows).exists())
        request = self.scenario.delivery_request
        request.pickup_location_id = leg.origin_id
        request.delivery_location_id = leg.destination_id
        request.status = "open"
        request.save(update_fields=["pickup_location", "delivery_location", "status"])
        candidates = compatible_journeys_for_request(delivery_request=request, policy=phase2_policy(), at=now)
        self.assertIn(journey.pk, [candidate.journey.pk for candidate in candidates])
        Deal.objects.filter(pk=self.deal.pk).update(status="picked_up", pickup_confirmed_at=now)
        self.assertEqual(with_lifecycle(rows).get().lifecycle_status, "in_progress")
        JourneyLeg.objects.filter(journey=journey).update(depart_at=now-timedelta(hours=3), arrive_at=now-timedelta(hours=1))
        self.assertEqual(with_lifecycle(rows).get().lifecycle_status, "completed")
        self.assertTrue(Deal.objects.filter(pk=self.deal.pk, funded_at__isnull=False).exists())

    def test_route_frozen_and_historical_unavailable(self):
        from apps.deals.route import funded_route
        route = funded_route(deal=self.deal, viewer_id=self.deal.sender_id)
        self.assertTrue(route["legs"])
        self.assertEqual(route["basis"], "funded_snapshot")
        self.assertIsNone(funded_route(deal=self.deal, viewer_id=self.scenario.outsider.pk))
        self.deal.arrival_snapshot = {}
        self.assertIsNone(funded_route(deal=self.deal, viewer_id=self.deal.sender_id))

    def test_rating_submission_resolves_prompt_and_preserves_blindness(self):
        from .phase4_factories import record_recipient, confirm_pickup, release_delivery_code, confirm_delivery
        from apps.ratings.services import rating_state, submit_rating
        record_recipient(self.scenario)
        confirm_pickup(self.scenario)
        release_delivery_code(self.scenario)
        confirm_delivery(self.scenario)
        self.deal.refresh_from_db()
        sender, traveler = self.deal.sender_id, self.deal.traveler_id
        prompt = Notification.objects.create(recipient_id=sender, channel="rating.prompt",
                                             event_id=uuid4().hex, payload={"deal_id": self.deal.pk})
        self.assertEqual(rating_state(deal=self.deal, viewer_id=sender)["state"], "available")
        self.assertFalse(resolved_notifications(self.scenario.sender).get(pk=prompt.pk).resolved)
        # Pre-column delivery rows use the same frozen policy fallback.
        Deal.objects.filter(pk=self.deal.pk).update(rating_window_ends_at=None)
        self.assertFalse(resolved_notifications(self.scenario.sender).get(pk=prompt.pk).resolved)
        Deal.objects.filter(pk=self.deal.pk).update(rating_window_ends_at=self.deal.rating_window_ends_at)
        submit_rating(deal_id=self.deal.pk, actor_id=sender, score=5)
        self.assertEqual(rating_state(deal=self.deal, viewer_id=sender)["state"], "submitted_waiting")
        self.assertFalse(rating_state(deal=self.deal, viewer_id=sender)["can_rate"])
        self.assertEqual(rating_state(deal=self.deal, viewer_id=traveler)["ratings"], [])
        self.assertTrue(resolved_notifications(self.scenario.sender).get(pk=prompt.pk).resolved)
        submit_rating(deal_id=self.deal.pk, actor_id=traveler, score=4)
        state = rating_state(deal=self.deal, viewer_id=sender)
        self.assertEqual(state["state"], "revealed")
        self.assertEqual(len(state["ratings"]), 2)

    def test_notifications_resolve_without_read_and_keep_read_actions(self):
        n = Notification.objects.create(recipient=self.scenario.sender, channel="payment.required", event_id=uuid4().hex,
                                        payload={"deal_id": self.deal.pk})
        self.assertTrue(resolved_notifications(self.scenario.sender).get(pk=n.pk).resolved)
        self.assertIsNone(Notification.objects.get(pk=n.pk).read_at)
        Deal.objects.filter(pk=self.deal.pk).update(funded_at=None, funded_scheduled_arrival_floor_at=None, arrival_snapshot={}, status="awaiting_payment")
        n.read_at = timezone.now()
        n.save(update_fields=["read_at"])
        self.assertFalse(resolved_notifications(self.scenario.sender).get(pk=n.pk).resolved)
        badge = self.client.get("/api/notifications/unread-count").data
        self.assertGreaterEqual(badge["active"], 1)
        self.assertEqual(badge["unread"], badge["active"])
        self.assertIn(n.pk, [r["id"] for r in self.client.get("/api/notifications").data["results"]])
        Deal.objects.filter(pk=self.deal.pk).update(funded_at=timezone.now())
        self.assertIn(n.pk, [r["id"] for r in self.client.get("/api/notifications", {"bucket": "history"}).data["results"]])
        self.client.force_authenticate(self.scenario.outsider)
        self.assertEqual(self.client.post(f"/api/notifications/{n.pk}/read").status_code, 404)
        self.assertNotIn(n.pk, [r["id"] for r in self.client.get("/api/notifications", {"bucket": "all"}).data["results"]])

    def test_dzd_validation_reports_fields_without_sensitive_values(self):
        from apps.finance.payout_profile_api import DzdInput
        serializer = DzdInput(data={"expected_revision": 0, "first_name": "Test", "last_name": "Traveler",
                                    "ccp_number": "private-invalid", "ccp_key": "123", "rip": "too-short",
                                    "proof_reference": str(uuid4()), "consent_policy": "payout_profile_v1"})
        self.assertFalse(serializer.is_valid())
        self.assertEqual(set(serializer.errors), {"ccp_number", "ccp_key", "rip"})
        self.assertNotIn("private-invalid", str(serializer.errors))

    def test_existing_dispute_survives_deadline_and_has_no_new_action(self):
        from .phase4_factories import record_recipient, confirm_pickup
        from apps.disputes.models import Dispute
        from apps.disputes.services import open_dispute
        record_recipient(self.scenario)
        confirm_pickup(self.scenario)
        dispute = open_dispute(deal_id=self.deal.pk, actor_id=self.deal.sender_id,
                               category=Dispute.Category.NOT_DELIVERED, reason_text="Synthetic test")
        self.deal.refresh_from_db()
        self.assertFalse(can_open_dispute(deal=self.deal, viewer_id=self.deal.sender_id))
        self.assertEqual(open_dispute(deal_id=self.deal.pk, actor_id=self.deal.sender_id,
                                     category=Dispute.Category.NOT_DELIVERED, reason_text="Retry").pk, dispute.pk)
        self.assertTrue(Dispute.objects.filter(pk=dispute.pk, status=Dispute.Status.OPEN).exists())

    def test_durable_transport_rollback_and_retry(self):
        with transaction.atomic():
            event_id = publish_after_commit("deal.updated", {"deal_id": self.deal.pk}, targets=[self.deal.sender_id])
            self.assertTrue(Notification.objects.filter(event_id=event_id).exists())
            self.assertTrue(ScheduledJob.objects.filter(key=f"notification:{event_id}").exists())
            transaction.set_rollback(True)
        self.assertFalse(Notification.objects.filter(event_id=event_id).exists())
        with patch("apps.core.redis_bus.get_client") as redis:
            with self.captureOnCommitCallbacks(execute=True):
                redis.return_value.publish.side_effect = RuntimeError("transport unavailable")
                event_id = publish_after_commit("deal.updated", {"deal_id": self.deal.pk}, targets=[self.deal.sender_id])
            self.assertEqual(ScheduledJob.objects.get(key=f"notification:{event_id}").status, "pending")
            redis.return_value.publish.side_effect = None
            from apps.notifications.transport import dispatch_promptly
            dispatch_promptly(event_id)
            self.assertEqual(ScheduledJob.objects.get(key=f"notification:{event_id}").status, "succeeded")
            redis.return_value.publish.reset_mock()
            with patch("apps.notifications.push.enqueue_fcm_for_event", side_effect=RuntimeError("push unavailable")):
                with self.captureOnCommitCallbacks(execute=True):
                    second = publish_after_commit("deal.updated", {"deal_id": self.deal.pk}, targets=[self.deal.sender_id])
            redis.return_value.publish.assert_called_once()
            self.assertEqual(ScheduledJob.objects.get(key=f"notification:{second}").status, "pending")
