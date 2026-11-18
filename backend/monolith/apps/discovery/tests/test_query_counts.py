"""L2A performance contract: every endpoint's query count is flat in its rows.

Each test reads the endpoint once at one row and once at twenty, with the same
viewer and the same query, and asserts the same number of queries. The number
is also pinned, so a new field cannot quietly add a read per page either.
The public reads are counted for a guest, without an account, too (plan EGS).
"""

from __future__ import annotations

from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from apps.parcels.models import DeliveryRequest

from .support import DiscoveryWorld, client_for

ROWS = 20


class QueryCountTests(DiscoveryWorld, TestCase):
    def setUp(self):
        self.build_discovery_world()
        self.viewer = self.other

    def count(self, name, *args, viewer=None, guest=False, rows=None, **query):
        client = APIClient() if guest else client_for(viewer or self.viewer)
        url = reverse(name, args=args)
        client.get(url, query)  # warm the policy and settings reads
        with CaptureQueriesContext(connection) as captured:
            response = client.get(url, query)
        self.assertEqual(response.status_code, 200, response.data)
        if rows is not None:
            self.assertEqual(len(rows(response.data)), rows.expected)
        return len(captured.captured_queries)

    def assertFlat(
        self, name, *args, grow, results, pinned, viewer=None, guest=False, most=ROWS, **query
    ):
        def rows_of(expected):
            def rows(data):
                return results(data)

            rows.expected = expected
            return rows

        at_one = self.count(name, *args, viewer=viewer, guest=guest, rows=rows_of(1), **query)
        grow()
        at_many = self.count(
            name, *args, viewer=viewer, guest=guest, rows=rows_of(most), **query
        )
        self.assertEqual(at_one, at_many)
        self.assertEqual(at_one, pinned)

    # -- growth --------------------------------------------------------------

    def _travelers(self, count, *, opt_in=False):
        made = []
        for index in range(count):
            traveler = self.new_traveler(f"l2a-qc-t{index}@example.com", name=f"Tariq {index}")
            self.drive_journey(traveler, days=3 + index % 5)
            if opt_in:
                self.opt_in(traveler, (self.algiers, self.jijel))
            made.append(traveler)
        return made

    def _requests(self, count, *, sender=None, opt_in=False):
        for index in range(count):
            owner = sender or self.new_traveler(
                f"l2a-qc-s{index}@example.com", name=f"Sofia {index}"
            )
            request = self._request(self.paris, self.jijel, title=f"Parcel {index}")
            DeliveryRequest.objects.filter(pk=request.pk).update(
                sender=owner, created_at=self.now - timedelta(minutes=index)
            )
            if opt_in:
                self.opt_in(owner)

    # -- tiers ---------------------------------------------------------------

    def assertTripsFlat(self, *, guest):
        self.assertFlat(
            "discovery-trips",
            guest=guest,
            grow=lambda: self._travelers(ROWS - 1),
            results=lambda data: data["results"],
            pinned=7,
            limit=ROWS,
        )

    def assertRequestsFlat(self, *, guest):
        self.assertFlat(
            "discovery-requests",
            guest=guest,
            grow=lambda: self._requests(ROWS - 1),
            results=lambda data: data["results"],
            pinned=4,
            limit=ROWS,
        )

    def assertPeopleFlat(self, *, guest):
        self.opt_in(self.traveler, (self.algiers, self.jijel))
        self.assertFlat(
            "discovery-people",
            guest=guest,
            grow=lambda: self._travelers(ROWS - 1, opt_in=True),
            results=lambda data: data["results"],
            pinned=6,
            role="sender",
            limit=ROWS,
        )

    def assertPersonFlat(self, *, guest):
        profile = self.opt_in(self.sender, (self.paris, self.jijel))
        self.assertFlat(
            "discovery-person",
            profile.public_id,
            guest=guest,
            grow=lambda: self._requests(ROWS - 1, sender=self.sender),
            results=lambda data: data["requests"],
            # The page shows at most ten of a person's own requests.
            most=10,
            pinned=10,
        )

    def test_trips(self):
        self.assertTripsFlat(guest=False)

    def test_requests(self):
        self.assertRequestsFlat(guest=False)

    def test_people(self):
        self.assertPeopleFlat(guest=False)

    def test_person_detail(self):
        self.assertPersonFlat(guest=False)

    # A guest's reads cost what a member's do: leaving out a viewer's own rows
    # is a condition in the same query, not a query of its own.

    def test_trips_for_a_guest(self):
        self.assertTripsFlat(guest=True)

    def test_requests_for_a_guest(self):
        self.assertRequestsFlat(guest=True)

    def test_people_for_a_guest(self):
        self.assertPeopleFlat(guest=True)

    def test_person_detail_for_a_guest(self):
        self.assertPersonFlat(guest=True)

    def test_own_profile_does_not_grow_with_usual_routes(self):
        self.opt_in(self.traveler, (self.algiers, self.jijel))
        one = self.count("discovery-profile-me", viewer=self.traveler)
        profile = self.traveler.public_profile
        profile.usual_routes.create(
            position=1, origin_locality=self.paris, destination_locality=self.jijel
        )
        profile.usual_routes.create(
            position=2, origin_locality=self.paris, destination_locality=self.algiers
        )
        many = self.count("discovery-profile-me", viewer=self.traveler)
        self.assertEqual(one, many)

    def test_sender_matches_do_not_grow_with_candidates(self):
        request = self._request(self.algiers, self.jijel, title="Matches")
        self.request.delete()

        def results(data):
            [group] = data["groups"]
            self.assertEqual(group["request"]["id"], request.pk)
            return group["results"]

        self.drive_journey(self.new_traveler("l2a-qc-m@example.com"), days=2)
        self.journey.delete()
        self.assertFlat(
            "discovery-matches",
            viewer=self.sender,
            grow=lambda: [
                self.drive_journey(
                    self.new_traveler(f"l2a-qc-m{index}@example.com"), days=2
                )
                for index in range(ROWS - 1)
            ],
            results=results,
            most=3,
            pinned=11,
            role="sender",
        )

    def test_traveler_matches_do_not_grow_with_candidates(self):
        journey = self.drive_journey(self.traveler, days=2)
        self.journey.delete()
        self.request.delete()

        def results(data):
            [group] = data["groups"]
            self.assertEqual(group["journey"]["id"], journey.pk)
            return group["results"]

        def grow():
            for index in range(ROWS - 1):
                sender = self.new_traveler(f"l2a-qc-r{index}@example.com")
                row = self._request(self.algiers, self.jijel, title=f"R{index}")
                DeliveryRequest.objects.filter(pk=row.pk).update(sender=sender)

        self._request(self.algiers, self.jijel, title="First")
        self.assertFlat(
            "discovery-matches",
            viewer=self.traveler,
            grow=grow,
            results=results,
            most=3,
            pinned=11,
            role="traveler",
        )

    def test_alerts(self):
        from apps.discovery.models import RouteAlert

        def alert(origin, destination, watches=RouteAlert.Watches.TRIPS):
            RouteAlert.objects.create(
                user=self.viewer,
                watches=watches,
                origin_locality=origin,
                destination_locality=destination,
            )

        alert(self.paris, self.jijel)
        one = self.count("discovery-alerts")
        for origin, destination in (
            (self.algiers, self.jijel),
            (self.paris, self.algiers),
            (self.jijel, self.paris),
        ):
            alert(origin, destination)
            alert(origin, destination, RouteAlert.Watches.REQUESTS)
        self.assertEqual(one, self.count("discovery-alerts"))
