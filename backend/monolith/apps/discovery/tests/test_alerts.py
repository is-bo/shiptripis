"""L2A route alerts: the member's own alerts and the durable fan-out."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core import channels
from apps.discovery.alerts import ALERT_QUIET_PERIOD, handle_route_alert_fanout
from apps.discovery.models import MAX_ACTIVE_ALERTS, PublicProfile, RouteAlert
from apps.finance.jobs import HANDLERS, PermanentJobError
from apps.finance.models import ScheduledJob
from apps.trips.models import Journey, JourneyLeg
from apps.trips.services import publish_journey

from .support import DiscoveryWorld, activate_marketplace, client_for

ALERTS = "discovery-alerts"
PUBLISH = "apps.discovery.alerts.redis_bus.publish_after_commit"


class AlertApiTests(DiscoveryWorld, TestCase):
    def setUp(self):
        self.build_discovery_world()
        self.client = client_for(self.sender)

    def create(self, status=201, **body):
        body = {
            "watches": "trips",
            "origin_place_id": self.cdg.pk,
            "destination_place_id": self.jijel.pk,
            **body,
        }
        response = self.client.post(reverse(ALERTS), body, format="json")
        self.assertEqual(response.status_code, status, response.data)
        return response.data

    def test_create_list_and_delete(self):
        alert = self.create()

        self.assertEqual(alert["watches"], "trips")
        self.assertEqual(alert["origin"]["label"], "Paris")  # CDG resolved to its city
        self.assertIsNone(alert["subject"])
        listed = self.client.get(reverse(ALERTS)).data["results"]
        self.assertEqual([row["id"] for row in listed], [alert["id"]])

        deleted = self.client.delete(reverse("discovery-alert", args=(alert["id"],)))
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(self.client.get(reverse(ALERTS)).data["results"], [])
        again = self.client.delete(reverse("discovery-alert", args=(alert["id"],)))
        self.assertEqual(again.status_code, 404)

    def test_the_same_alert_twice_is_one_alert(self):
        first = self.create()
        second = self.create(status=200, origin_place_id=self.paris.pk)
        self.assertEqual(first["id"], second["id"])

    def test_another_members_alert_cannot_be_deleted(self):
        alert = self.create()
        response = client_for(self.other).delete(reverse("discovery-alert", args=(alert["id"],)))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(RouteAlert.objects.get(pk=alert["id"]).is_active)

    def test_at_most_ten_active_alerts(self):
        places = [self.paris, self.algiers, self.jijel]
        pairs = [(a, b) for a in places for b in places if a != b]  # six routes
        for watches in ("trips", "requests"):
            for origin, destination in pairs:
                if RouteAlert.objects.filter(user=self.sender, is_active=True).count() == 10:
                    break
                self.create(
                    watches=watches,
                    origin_place_id=origin.pk,
                    destination_place_id=destination.pk,
                )
        self.assertEqual(
            RouteAlert.objects.filter(user=self.sender, is_active=True).count(),
            MAX_ACTIVE_ALERTS,
        )
        refused = self.create(
            status=409,
            watches="requests",
            origin_place_id=self.jijel.pk,
            destination_place_id=self.algiers.pk,
        )
        self.assertEqual(refused["code"], "route_alert_limit_reached")

    def test_an_alert_needs_two_cities(self):
        refused = self.create(status=400, origin_place_id=self.paris.pk, destination_place_id=self.cdg.pk)
        self.assertEqual(refused["code"], "route_alert_same_city")

    def test_following_a_person_needs_their_visible_profile(self):
        profile = self.opt_in(self.traveler)

        alert = self.create(subject_profile_id=str(profile.public_id))

        self.assertEqual(
            alert["subject"], {"id": str(profile.public_id), "display_name": "Yacine"}
        )
        PublicProfile.objects.filter(pk=profile.pk).update(is_discoverable=False)
        refused = self.create(
            status=404, watches="requests", subject_profile_id=str(profile.public_id)
        )
        self.assertEqual(refused["code"], "profile_not_found")

    def test_a_member_cannot_follow_themselves(self):
        profile = self.opt_in(self.sender)
        refused = self.create(status=400, subject_profile_id=str(profile.public_id))
        self.assertEqual(refused["code"], "route_alert_self")

    def test_listings_switched_off_refuses_new_alerts(self):
        activate_marketplace({"discovery": {"listings_enabled": False}})
        self.assertEqual(self.create(status=409)["code"], "discovery_listings_disabled")


class AlertFanOutTests(DiscoveryWorld, TestCase):
    def setUp(self):
        self.build_discovery_world()
        self.watcher = self.other
        self.alert = RouteAlert.objects.create(
            user=self.watcher,
            watches=RouteAlert.Watches.TRIPS,
            origin_locality=self.algiers,
            destination_locality=self.jijel,
        )

    def draft_journey(self, traveler):
        journey = self.drive_journey(traveler)
        Journey.objects.filter(pk=journey.pk).update(
            status=Journey.Status.DRAFT, published_at=None
        )
        return journey

    def fan_out(self, **payload):
        with patch(PUBLISH) as publish:
            outcome = handle_route_alert_fanout(payload)
        return outcome, publish

    def test_publishing_a_journey_records_the_fan_out_and_notifies_the_watcher(self):
        traveler = self.new_traveler("l2a-alert@example.com")
        journey = self.draft_journey(traveler)

        publish_journey(journey=journey, actor=traveler)

        job = ScheduledJob.objects.get(kind=ScheduledJob.Kind.DISCOVERY_ROUTE_ALERTS)
        self.assertEqual(job.key, f"discovery_route_alerts:journey:{journey.pk}")
        self.assertIn(job.kind, HANDLERS)
        outcome, publish = self.fan_out(**job.payload)
        self.assertEqual(outcome, "notified:1")
        publish.assert_called_once_with(
            channels.DISCOVERY_ROUTE_ALERT,
            {"alert_id": self.alert.pk, "journey_id": journey.pk},
            targets=[self.watcher.pk],
            idempotency_key=f"route_alert:{self.alert.pk}:journey_id:{journey.pk}",
        )

    def test_a_multi_stop_journey_notifies_every_pair_of_stops_ahead(self):
        paris_alert = RouteAlert.objects.create(
            user=self.sender,
            watches=RouteAlert.Watches.TRIPS,
            origin_locality=self.paris,
            destination_locality=self.jijel,
        )
        RouteAlert.objects.filter(pk=self.alert.pk).update(user=self.new_traveler("w@example.com"))
        outcome, publish = self.fan_out(journey_id=self.journey.pk)

        self.assertEqual(outcome, "notified:2")
        notified = {call.args[1]["alert_id"] for call in publish.call_args_list}
        self.assertEqual(notified, {self.alert.pk, paris_alert.pk})

    def test_one_notification_per_alert_per_quiet_period(self):
        second = self.drive_journey(self.new_traveler("l2a-second@example.com"))

        first_outcome, _ = self.fan_out(journey_id=self.journey.pk)
        second_outcome, publish = self.fan_out(journey_id=second.pk)

        self.assertEqual((first_outcome, second_outcome), ("notified:1", "notified:0"))
        publish.assert_not_called()
        RouteAlert.objects.filter(pk=self.alert.pk).update(
            last_notified_at=timezone.now() - ALERT_QUIET_PERIOD - timedelta(minutes=1)
        )
        self.assertEqual(self.fan_out(journey_id=second.pk)[0], "notified:1")

    def test_a_replayed_job_notifies_nobody_twice(self):
        self.fan_out(journey_id=self.journey.pk)
        outcome, publish = self.fan_out(journey_id=self.journey.pk)
        self.assertEqual(outcome, "notified:0")
        publish.assert_not_called()

    def test_the_owner_of_the_item_is_never_notified(self):
        RouteAlert.objects.filter(pk=self.alert.pk).update(user=self.traveler)
        self.assertEqual(self.fan_out(journey_id=self.journey.pk)[0], "notified:0")

    def test_inactive_banned_and_wrong_kind_alerts_stay_quiet(self):
        for change in (
            lambda: RouteAlert.objects.filter(pk=self.alert.pk).update(
                is_active=False, deactivated_at=timezone.now()
            ),
            lambda: type(self.watcher).objects.filter(pk=self.watcher.pk).update(
                is_banned=True
            ),
            lambda: RouteAlert.objects.filter(pk=self.alert.pk).update(
                watches=RouteAlert.Watches.REQUESTS
            ),
        ):
            with self.subTest(change):
                RouteAlert.objects.filter(pk=self.alert.pk).update(
                    is_active=True, deactivated_at=None, watches=RouteAlert.Watches.TRIPS
                )
                type(self.watcher).objects.filter(pk=self.watcher.pk).update(is_banned=False)
                change()
                self.assertEqual(self.fan_out(journey_id=self.journey.pk)[0], "notified:0")

    def test_an_item_no_longer_listed_notifies_nobody(self):
        Journey.objects.filter(pk=self.journey.pk).update(status=Journey.Status.CANCELLED)
        self.assertEqual(self.fan_out(journey_id=self.journey.pk)[0], "not_listed")

    def test_listings_switched_off_notifies_nobody(self):
        activate_marketplace({"discovery": {"listings_enabled": False}})
        self.assertEqual(self.fan_out(journey_id=self.journey.pk)[0], "listings_disabled")

    def test_a_followed_person_fires_only_while_their_profile_is_visible(self):
        RouteAlert.objects.filter(pk=self.alert.pk).update(subject_user=self.traveler)
        self.assertEqual(self.fan_out(journey_id=self.journey.pk)[0], "notified:0")

        self.opt_in(self.traveler)
        self.assertEqual(self.fan_out(journey_id=self.journey.pk)[0], "notified:1")

    def test_a_follow_of_someone_else_does_not_fire(self):
        RouteAlert.objects.filter(pk=self.alert.pk).update(subject_user=self.sender)
        self.opt_in(self.sender)
        self.assertEqual(self.fan_out(journey_id=self.journey.pk)[0], "notified:0")

    def test_a_request_opening_notifies_request_watchers(self):
        alert = RouteAlert.objects.create(
            user=self.traveler,
            watches=RouteAlert.Watches.REQUESTS,
            origin_locality=self.paris,
            destination_locality=self.jijel,
        )
        outcome, publish = self.fan_out(request_id=self.request.pk)
        self.assertEqual(outcome, "notified:1")
        self.assertEqual(
            publish.call_args.args[1], {"alert_id": alert.pk, "request_id": self.request.pk}
        )

    def test_a_departed_stop_is_not_a_pickup(self):
        JourneyLeg.objects.filter(pk=self.flight_leg.pk).update(
            depart_at=timezone.now() - timedelta(hours=1),
            arrive_at=timezone.now() + timedelta(hours=1),
        )
        paris_alert = RouteAlert.objects.create(
            user=self.sender,
            watches=RouteAlert.Watches.TRIPS,
            origin_locality=self.paris,
            destination_locality=self.jijel,
        )
        outcome, publish = self.fan_out(journey_id=self.journey.pk)
        notified = {call.args[1]["alert_id"] for call in publish.call_args_list}
        self.assertNotIn(paris_alert.pk, notified)
        self.assertEqual(outcome, "notified:1")

    def test_a_malformed_payload_is_a_permanent_failure(self):
        for payload in ({}, {"journey_id": 1, "request_id": 2}, {"journey_id": "1"}):
            with self.subTest(payload), self.assertRaises(PermanentJobError):
                handle_route_alert_fanout(payload)
