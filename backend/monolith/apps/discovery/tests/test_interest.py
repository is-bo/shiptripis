"""L2A "I can carry this": a proven, capped, one-time signal to the sender."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from apps.core import channels
from apps.deals.models import DealLegAllocation
from apps.discovery.models import TravelerInterest
from apps.matching.models import Match, Offer
from apps.matching.tests.test_phase8c_canonical import (
    INCIDENT_ARRIVE,
    INCIDENT_AT,
    INCIDENT_DEADLINE,
    INCIDENT_DEPART,
    INCIDENT_READY_END,
    INCIDENT_READY_START,
)
from apps.parcels.models import DeliveryRequest
from apps.trips.models import Journey, JourneyLeg, JourneyLegProof

from .support import DiscoveryWorld, activate_marketplace, client_for

PUBLISH = "apps.discovery.interest.redis_bus.publish_after_commit"


class InterestTests(DiscoveryWorld, TestCase):
    def setUp(self):
        self.build_discovery_world()

    def signal(self, request_id=None, journey_id=None, *, traveler=None, status=201):
        with patch(PUBLISH) as publish:
            response = client_for(traveler or self.traveler).post(
                reverse("discovery-request-interest", args=(request_id or self.request.pk,)),
                {"journey_id": journey_id or self.journey.pk},
                format="json",
            )
        self.assertEqual(response.status_code, status, response.data)
        return response.data, publish

    def test_a_compatible_journey_notifies_the_sender_once_with_two_ids(self):
        body, publish = self.signal()

        self.assertTrue(body["created"])
        self.assertEqual(
            (body["request_id"], body["journey_id"]), (self.request.pk, self.journey.pk)
        )
        publish.assert_called_once()
        channel, payload = publish.call_args.args
        self.assertEqual(channel, channels.DISCOVERY_TRAVELER_INTERESTED)
        self.assertEqual(payload, {"request_id": self.request.pk, "journey_id": self.journey.pk})
        self.assertEqual(publish.call_args.kwargs["targets"], [self.sender.pk])

    def test_it_creates_no_match_no_offer_and_no_reservation(self):
        self.signal()
        self.assertEqual(Match.objects.count(), 0)
        self.assertEqual(Offer.objects.count(), 0)
        self.assertEqual(DealLegAllocation.objects.count(), 0)

    def test_a_repeat_tap_is_the_same_signal_and_sends_nothing(self):
        self.signal()
        body, publish = self.signal(status=200)
        self.assertFalse(body["created"])
        publish.assert_not_called()
        self.assertEqual(TravelerInterest.objects.count(), 1)

    def test_an_incompatible_journey_answers_the_engines_rejection_codes(self):
        elsewhere = self.drive_journey(self.traveler)  # Algiers → Jijel, no Paris pickup
        body, publish = self.signal(journey_id=elsewhere.pk, status=409)
        self.assertEqual(body["code"], "incompatible_candidate")
        self.assertEqual(body["rejection_codes"], ["pickup_stop_on_route"])
        publish.assert_not_called()
        self.assertFalse(TravelerInterest.objects.exists())

    def test_someone_elses_journey_is_refused(self):
        body, _ = self.signal(traveler=self.other, status=404)
        self.assertEqual(body["code"], "journey_not_found")

    def test_an_unlisted_or_own_request_is_refused(self):
        own = self._request(self.paris, self.jijel, title="Mine")
        DeliveryRequest.objects.filter(pk=own.pk).update(sender=self.traveler)
        body, _ = self.signal(request_id=own.pk, status=404)
        self.assertEqual(body["code"], "request_not_found")
        DeliveryRequest.objects.filter(pk=self.request.pk).update(target_traveler=self.other)
        self.assertEqual(self.signal(status=404)[0]["code"], "request_not_found")

    def test_the_daily_cap_is_enforced(self):
        activate_marketplace({"discovery": {"interest_daily_cap": 1}})
        second = self._request(self.paris, self.jijel, title="Second")
        self.signal()

        body, publish = self.signal(request_id=second.pk, status=429)

        self.assertEqual(body["code"], "interest_daily_cap_reached")
        publish.assert_not_called()
        # A repeat of a signal already sent is not a new one, so the cap allows it.
        self.signal(status=200)

    def test_listings_switched_off_refuses_the_signal(self):
        activate_marketplace({"discovery": {"listings_enabled": False}})
        self.assertEqual(self.signal(status=409)[0]["code"], "discovery_listings_disabled")


class IncidentInterestTests(DiscoveryWorld, TestCase):
    """Phone test 2 (M1): "I can carry this" from journey 11 (ALG → CDG) to
    request 1 (Jijel → Paris), on the clock of the test.

    The signal stays refused, Boost or not, and the refusal now names the
    missing pickup stop instead of a code the app read as a date problem.
    """

    signal = InterestTests.signal

    def setUp(self):
        clock = patch("django.utils.timezone.now", return_value=INCIDENT_AT)
        clock.start()
        self.addCleanup(clock.stop)
        self.build_discovery_world()
        self.journey_11 = Journey.objects.create(
            traveler=self.traveler,
            schema_version=2,
            start_place=self.algiers,
            destination_place=self.paris,
            status=Journey.Status.ACTIVE,
            published_at=INCIDENT_AT,
        )
        flight = JourneyLeg.objects.create(
            journey=self.journey_11,
            position=0,
            mode=JourneyLeg.Mode.FLIGHT,
            origin_place=self.alg,
            destination_place=self.cdg,
            depart_at=INCIDENT_DEPART,
            arrive_at=INCIDENT_ARRIVE,
            capacity_kg=Decimal("8.00"),
            flight_number="AH1000",
        )
        JourneyLegProof.objects.create(
            leg=flight,
            bucket="private",
            object_key=f"discovery/m1-{self.journey_11.pk}.jpg",
            status=JourneyLegProof.Status.APPROVED,
            reviewer=self.sender,
            reviewed_at=INCIDENT_AT,
        )
        self.request_1 = self.request_from(self.jijel)

    def request_from(self, origin) -> DeliveryRequest:
        request = self._request(origin, self.paris, title="Phone test 2")
        request.ready_window_start = INCIDENT_READY_START
        request.ready_window_end = INCIDENT_READY_END
        request.deadline_at = INCIDENT_DEADLINE
        request.save(
            update_fields=["ready_window_start", "ready_window_end", "deadline_at"]
        )
        return request

    def test_the_signal_is_refused_with_the_missing_pickup_stop_even_with_a_boost(self):
        for boosted in (False, True):
            if boosted:
                self.request_1.boost_eur_cents = 100_000
                self.request_1.ranking_boost_weight = 20
                self.request_1.ranking_boost_expires_at = self.request_1.deadline_at
                self.request_1.save(
                    update_fields=[
                        "boost_eur_cents",
                        "ranking_boost_weight",
                        "ranking_boost_expires_at",
                    ]
                )
            with self.subTest(boosted=boosted):
                body, publish = self.signal(
                    self.request_1.pk, self.journey_11.pk, status=409
                )
                self.assertEqual(set(body), {"code", "detail", "rejection_codes"})
                self.assertEqual(body["code"], "incompatible_candidate")
                self.assertEqual(body["rejection_codes"], ["pickup_stop_on_route"])
                publish.assert_not_called()
        self.assertFalse(TravelerInterest.objects.exists())
        self.assertEqual(Offer.objects.count(), 0)

    def test_the_same_dates_from_algiers_are_a_real_signal(self):
        algiers = self.request_from(self.algiers)
        body, publish = self.signal(algiers.pk, self.journey_11.pk)
        self.assertTrue(body["created"])
        publish.assert_called_once()
