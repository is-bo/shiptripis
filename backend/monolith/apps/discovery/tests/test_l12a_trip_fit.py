"""L12A trip-fit alerts: "a parcel fits your trip" (spec 17.2).

Run by the request's route-alert fan-out job, before the route alerts. Only
journeys the matching engine finds really compatible are told, in the engine's
ranking order, at most ``trip_fit_max_travelers`` per request and
``trip_fit_daily_cap`` per traveler a day, never twice for one request and
journey; a traveler told this way gets no route alert for the same request.
"""

from __future__ import annotations

import json
from datetime import timedelta

from django.db import connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.core import channels, redis_bus
from apps.discovery.alerts import handle_route_alert_fanout
from apps.discovery.models import RouteAlert, TripFitAlert
from apps.finance.models import ScheduledJob
from apps.matching.discovery import compatible_journeys_for_request, phase2_policy
from apps.notifications.models import Notification
from apps.notifications.push import _PUSH_SPECS
from apps.trips.models import Journey

from .support import DiscoveryWorld, activate_marketplace

#: What a trip-fit notification may carry: the envelope and two ids.
ALLOWED_KEYS = {"event_id", "ts", "targets", "request_id", "journey_id"}
FORBIDDEN_SUBSTRINGS = ("WSL-", "Paris", "Jijel", "Samira", "@example.com", "eur_cents")


class TripFitWorld(DiscoveryWorld):
    def setUp(self):
        self.build_discovery_world()

    def fitting_traveler(self, index: int):
        traveler = self.new_traveler(f"l12a-fit-{index}@example.com", name=f"Nadir {index}")
        journey, _, _ = self._journey(traveler)
        return traveler, journey

    def fan_out(self) -> str:
        return handle_route_alert_fanout({"request_id": self.request.pk})

    def told(self) -> list[tuple[int, int]]:
        return sorted(
            TripFitAlert.objects.filter(delivery_request=self.request).values_list(
                "traveler_id", "journey_id"
            )
        )

    def notifications(self):
        return Notification.objects.filter(channel=channels.DISCOVERY_REQUEST_FITS_TRIP)


class TripFitTests(TripFitWorld, TestCase):
    def test_the_fitting_traveler_is_told_with_two_ids_and_nothing_else(self):
        self.fan_out()

        self.assertEqual(self.told(), [(self.traveler.pk, self.journey.pk)])
        (row,) = self.notifications()
        self.assertEqual(row.recipient_id, self.traveler.pk)
        self.assertEqual(row.payload["request_id"], self.request.pk)
        self.assertEqual(row.payload["journey_id"], self.journey.pk)
        self.assertEqual(set(row.payload), ALLOWED_KEYS)
        rendered = json.dumps(row.payload)
        for forbidden in FORBIDDEN_SUBSTRINGS:
            self.assertNotIn(forbidden, rendered)

    def test_only_journeys_the_engine_finds_compatible_are_told(self):
        wrong_route = self.drive_journey(self.new_traveler("l12a-road@example.com"))
        unproven = self.unproven_flight_journey(self.new_traveler("l12a-ticket@example.com"))
        paused_traveler, paused = self.fitting_traveler(1)
        Journey.objects.filter(pk=paused.pk).update(paused_at=timezone.now())

        self.fan_out()

        journeys = {journey for _, journey in self.told()}
        self.assertEqual(journeys, {self.journey.pk})
        self.assertNotIn(wrong_route.pk, journeys)
        self.assertNotIn(unproven.pk, journeys)
        self.assertNotIn(paused.pk, journeys)
        self.assertNotIn(self.sender.pk, {traveler for traveler, _ in self.told()})

    def test_the_cap_per_request_keeps_the_engine_ranking_order(self):
        for index in range(3):
            self.fitting_traveler(index)
        activate_marketplace({"discovery": {"trip_fit_max_travelers": 2}})
        ranked = [
            row.journey.traveler_id
            for row in compatible_journeys_for_request(
                delivery_request=self.request, policy=phase2_policy()
            )
        ]
        self.assertEqual(len(ranked), 4)

        self.fan_out()

        self.assertEqual({t for t, _ in self.told()}, set(ranked[:2]))

    def test_a_traveler_with_two_fitting_trips_is_told_once(self):
        second, _, _ = self._journey(self.traveler)

        self.fan_out()

        self.assertEqual(len(self.told()), 1)
        self.assertEqual(self.notifications().count(), 1)
        best = compatible_journeys_for_request(
            delivery_request=self.request, policy=phase2_policy()
        )[0].journey.pk
        self.assertEqual(self.told()[0][1], best)

    def test_the_daily_cap_counts_the_last_24_hours(self):
        activate_marketplace({"discovery": {"trip_fit_daily_cap": 2}})
        for index in range(2):
            other = self._request(self.paris, self.jijel, title=f"Earlier {index}")
            TripFitAlert.objects.create(
                delivery_request=other, journey=self.journey, traveler=self.traveler
            )

        self.fan_out()
        self.assertEqual(self.told(), [])

        TripFitAlert.objects.filter(traveler=self.traveler).update(
            created_at=timezone.now() - timedelta(hours=24, minutes=1)
        )
        self.fan_out()
        self.assertEqual(self.told(), [(self.traveler.pk, self.journey.pk)])

    def test_a_replay_notifies_nobody_twice(self):
        self.fan_out()
        self.fan_out()

        self.assertEqual(len(self.told()), 1)
        self.assertEqual(self.notifications().count(), 1)

    def test_a_traveler_told_by_trip_fit_gets_no_route_alert_for_that_request(self):
        fitting = RouteAlert.objects.create(
            user=self.traveler,
            watches=RouteAlert.Watches.REQUESTS,
            origin_locality=self.paris,
            destination_locality=self.jijel,
        )
        watcher = RouteAlert.objects.create(
            user=self.new_traveler("l12a-watcher@example.com"),
            watches=RouteAlert.Watches.REQUESTS,
            origin_locality=self.paris,
            destination_locality=self.jijel,
        )

        self.assertEqual(self.fan_out(), "notified:1")
        # A replay keeps leaving the same traveler out.
        RouteAlert.objects.update(last_notified_at=None)
        self.assertEqual(self.fan_out(), "notified:1")

        fitting.refresh_from_db()
        watcher.refresh_from_db()
        self.assertIsNone(fitting.last_notified_at)
        self.assertIsNotNone(watcher.last_notified_at)
        self.assertFalse(
            Notification.objects.filter(
                channel=channels.DISCOVERY_ROUTE_ALERT, recipient=self.traveler
            ).exists()
        )

    def test_with_the_switch_off_nobody_is_told_and_route_alerts_go_out(self):
        activate_marketplace({"discovery": {"trip_fit_alerts_enabled": False}})
        RouteAlert.objects.create(
            user=self.traveler,
            watches=RouteAlert.Watches.REQUESTS,
            origin_locality=self.paris,
            destination_locality=self.jijel,
        )

        self.assertEqual(self.fan_out(), "notified:1")
        self.assertEqual(self.told(), [])
        self.assertFalse(self.notifications().exists())

    def test_with_listings_off_nobody_is_told(self):
        activate_marketplace({"discovery": {"listings_enabled": False}})
        self.assertEqual(self.fan_out(), "listings_disabled")
        self.assertEqual(self.told(), [])

    def test_a_request_no_longer_listable_tells_nobody(self):
        from apps.parcels.models import ParcelRequest

        type(self.request).objects.filter(pk=self.request.pk).update(
            status=ParcelRequest.Status.CANCELLED
        )
        self.assertEqual(self.fan_out(), "not_listed")
        self.assertEqual(self.told(), [])

    def test_the_channel_is_a_marketplace_push_in_three_languages(self):
        category, android_channel, _, copy = _PUSH_SPECS[channels.DISCOVERY_REQUEST_FITS_TRIP]
        self.assertEqual(category, "marketplace")
        self.assertEqual(android_channel, "deliveries")
        self.assertEqual(set(copy), {"en", "fr", "ar"})


class TripFitQueryCountTests(TripFitWorld, TestCase):
    """Choosing whom to tell is flat; each traveler told costs one inbox write."""

    @staticmethod
    def _forget() -> None:
        TripFitAlert.objects.all().delete()
        Notification.objects.all().delete()
        ScheduledJob.objects.filter(kind=ScheduledJob.Kind.NOTIFICATION_DISPATCH).delete()

    def _count(self) -> int:
        self._forget()
        self.fan_out()  # warm the policy and settings reads
        self._forget()
        with CaptureQueriesContext(connection) as captured:
            self.fan_out()
        return len(captured.captured_queries)

    def _one_inbox_write(self) -> int:
        user = self.new_traveler("l12a-qc-probe@example.com")
        with transaction.atomic(), CaptureQueriesContext(connection) as captured:
            redis_bus.publish_after_commit(
                channels.DISCOVERY_REQUEST_FITS_TRIP,
                {"request_id": 1, "journey_id": 1},
                targets=[user.pk],
                idempotency_key="l12a-query-count-probe",
            )
        return len(captured.captured_queries)

    def test_one_and_twenty_journeys(self):
        at_one = self._count()
        self.assertEqual(len(self.told()), 1)
        for index in range(19):
            self.fitting_traveler(index)
        at_twenty = self._count()
        self.assertEqual(len(self.told()), 20)

        self.assertEqual(at_twenty - at_one, 19 * self._one_inbox_write())
