"""The geography reads a guest uses while browsing count a guest on `discovery_guest`.

Carrier-grade NAT puts many people behind one address, so a guest picking
places is counted on the one roomy per-address guest bucket the public
discovery reads use, never on the shared `anon` rate. A member keeps the
per-member `user` rate and is never counted on the guest bucket.
"""

from __future__ import annotations

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle

from apps.accounts.models import User
from apps.core.throttles import GuestRateThrottle, MemberRateThrottle
from apps.locations.geography_views import (
    GeographyCountryListView,
    GeographyPlaceSearchView,
    SeaCrossingListView,
)

ADDRESS = "198.51.100.21"
GUEST_READS = (
    reverse("geography-countries"),
    reverse("geography-places") + "?q=al",
    reverse("geography-sea-crossings"),
)


class GeographyGuestThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def member_at(self, address):
        member = User.objects.create_user(
            username="member@example.com",
            email="member@example.com",
            password="Pass-12345!",
        )
        client = APIClient(REMOTE_ADDR=address)
        client.force_authenticate(user=member)
        return client

    def statuses(self, client, paths):
        return [client.get(path).status_code for path in paths]

    def test_each_guest_read_uses_the_public_read_throttles(self):
        for view in (
            GeographyCountryListView,
            GeographyPlaceSearchView,
            SeaCrossingListView,
        ):
            with self.subTest(view.__name__):
                self.assertEqual(
                    view.throttle_classes, (GuestRateThrottle, MemberRateThrottle)
                )
                self.assertNotIn(AnonRateThrottle, view.throttle_classes)

    def test_a_guest_is_counted_by_address_on_the_guest_scope(self):
        with patch.dict(
            ScopedRateThrottle.THROTTLE_RATES, {"discovery_guest": "3/min"}
        ):
            guest = APIClient(REMOTE_ADDR=ADDRESS)
            self.assertEqual(self.statuses(guest, GUEST_READS), [200, 200, 200])
            # One bucket for every public read: discovery is already spent too.
            self.assertEqual(guest.get(reverse("discovery-trips")).status_code, 429)
            self.assertEqual(guest.get(GUEST_READS[0]).status_code, 429)
            self.assertEqual(
                APIClient(REMOTE_ADDR="198.51.100.22").get(GUEST_READS[0]).status_code,
                200,
            )

    def test_a_guest_is_not_counted_on_the_anonymous_rate(self):
        with patch.dict(
            ScopedRateThrottle.THROTTLE_RATES, {"anon": "1/min", "user": "1/min"}
        ):
            guest = APIClient(REMOTE_ADDR=ADDRESS)
            self.assertEqual(self.statuses(guest, GUEST_READS * 2), [200] * 6)

    def test_a_member_is_not_counted_on_the_guest_scope(self):
        member = self.member_at(ADDRESS)
        with patch.dict(
            ScopedRateThrottle.THROTTLE_RATES, {"discovery_guest": "1/min"}
        ):
            self.assertEqual(self.statuses(member, GUEST_READS), [200, 200, 200])
            # The guest at the same address still has the whole guest bucket.
            self.assertEqual(
                APIClient(REMOTE_ADDR=ADDRESS).get(GUEST_READS[0]).status_code, 200
            )

    def test_a_member_keeps_the_per_member_rate(self):
        member = self.member_at(ADDRESS)
        with patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"user": "2/min"}):
            self.assertEqual(self.statuses(member, GUEST_READS), [200, 200, 429])
