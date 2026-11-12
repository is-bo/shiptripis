"""L2A "I can carry this": a proven, capped, one-time signal to the sender."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from apps.core import channels
from apps.deals.models import DealLegAllocation
from apps.discovery.models import TravelerInterest
from apps.matching.models import Match, Offer
from apps.parcels.models import DeliveryRequest

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
        self.assertTrue(body["rejection_codes"])
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
