"""The guest read API (plan EGS, decision 10, Part B items 5 and 6).

Six discovery reads are public: a guest, a caller without an account, gets
exactly what a member who owns nothing gets, switches included. The five
endpoints about the caller still answer 401 to a guest and write nothing.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.test import APIClient
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle
from rest_framework_simplejwt.tokens import AccessToken

from apps.core.throttles import GuestRateThrottle
from apps.discovery import urls as discovery_urls
from apps.discovery import views
from apps.discovery.models import PublicProfile, PublicProfileRoute, RouteAlert, TravelerInterest
from apps.ratings.tests.test_l13a_reviews import ReviewsWorld

from .support import DiscoveryWorld, activate_marketplace, client_for

PUBLIC_READS = {
    "TripsView",
    "RequestsView",
    "PeopleView",
    "PersonView",
    "PersonReviewsView",
    "TripReviewsView",
}
MEMBER_ENDPOINTS = {
    "MatchesView",
    "InterestView",
    "OwnProfileView",
    "AlertsView",
    "AlertDetailView",
}
TRIP_NOT_FOUND = {"code": "trip_not_found", "detail": "This trip is not available."}


class GuestReadTests(ReviewsWorld, TestCase):
    """A guest reads what a member who owns nothing (`self.other`) reads."""

    def setUp(self):
        self.build_reviews_world()
        self.sender_profile = self.opt_in(self.sender, (self.paris, self.jijel))
        self.rate(4)

    def reads(self) -> dict[str, tuple[str, dict]]:
        traveler, sender = self.traveler_profile.public_id, self.sender_profile.public_id
        return {
            "trips": (reverse("discovery-trips"), {}),
            "requests": (reverse("discovery-requests"), {}),
            "travelers": (reverse("discovery-people"), {"role": "sender"}),
            "senders": (reverse("discovery-people"), {"role": "traveler"}),
            "traveler page": (reverse("discovery-person", args=(traveler,)), {}),
            "sender page": (reverse("discovery-person", args=(sender,)), {}),
            "person reviews": (reverse("discovery-person-reviews", args=(traveler,)), {}),
            "trip reviews": (reverse("discovery-trip-reviews", args=(self.journey.pk,)), {}),
        }

    def answers(self, client) -> dict[str, tuple[int, dict]]:
        answers = {}
        for label, (url, query) in self.reads().items():
            response = client.get(url, query)
            answers[label] = (response.status_code, response.data)
        return answers

    def assertGuestReadsAsAMember(self) -> dict[str, tuple[int, dict]]:
        guest = self.answers(APIClient())
        self.assertEqual(guest, self.answers(client_for(self.other)))
        return guest

    def test_a_guest_reads_every_public_tier_as_a_member_who_owns_nothing(self):
        guest = self.assertGuestReadsAsAMember()

        self.assertEqual(
            {label: (code, data["state"]) for label, (code, data) in guest.items()},
            {label: (200, "results") for label in self.reads()},
        )

    def test_a_guest_has_no_own_items_to_leave_out(self):
        def ids(client, name, key, **query):
            response = client.get(reverse(name), query)
            self.assertEqual(response.status_code, 200, response.data)
            return [row[key] for row in response.data["results"]]

        traveler, sender = client_for(self.traveler), client_for(self.sender)
        traveler_id = str(self.traveler_profile.public_id)
        sender_id = str(self.sender_profile.public_id)

        self.assertIn(self.journey.pk, ids(APIClient(), "discovery-trips", "journey_id"))
        self.assertNotIn(self.journey.pk, ids(traveler, "discovery-trips", "journey_id"))
        self.assertIn(self.request.pk, ids(APIClient(), "discovery-requests", "request_id"))
        self.assertNotIn(self.request.pk, ids(sender, "discovery-requests", "request_id"))
        self.assertIn(traveler_id, ids(APIClient(), "discovery-people", "id", role="sender"))
        self.assertNotIn(traveler_id, ids(traveler, "discovery-people", "id", role="sender"))
        self.assertIn(sender_id, ids(APIClient(), "discovery-people", "id", role="traveler"))
        self.assertNotIn(sender_id, ids(sender, "discovery-people", "id", role="traveler"))

    def test_switched_off_tiers_answer_a_guest_the_same_disabled_states(self):
        activate_marketplace({"discovery": {"listings_enabled": False}})
        guest = self.assertGuestReadsAsAMember()
        self.assertEqual(
            guest["trips"], (200, {"state": "disabled", "results": [], "next_offset": None})
        )
        self.assertEqual(guest["requests"], guest["trips"])
        self.assertEqual(guest["trip reviews"][1]["state"], "disabled")
        # A person page still opens, without the listed trips and requests.
        self.assertEqual(guest["traveler page"][1]["trips"], [])

        activate_marketplace({"discovery": {"profiles_enabled": False}})
        guest = self.assertGuestReadsAsAMember()
        for label in ("travelers", "senders", "person reviews"):
            self.assertEqual(guest[label][1]["state"], "disabled", label)
        for label in ("traveler page", "sender page"):
            self.assertEqual(guest[label], (200, {"state": "disabled"}), label)

    def test_a_guest_naming_a_request_reads_as_an_unknown_trip(self):
        finder, request = self.finder()
        url = reverse("discovery-trip-reviews", args=(self.journey.pk,))
        for listings_enabled in (True, False):
            with self.subTest(listings_enabled=listings_enabled):
                activate_marketplace({"discovery": {"listings_enabled": listings_enabled}})
                # The same request opens the member's Find Travelers door.
                member = client_for(finder).get(url, {"request": request.pk})
                self.assertEqual(member.status_code, 200, member.data)
                self.assertEqual(member.data["state"], "results")

                for request_id in (request.pk, self.request.pk, 999_999):
                    response = APIClient().get(url, {"request": request_id})
                    self.assertEqual((response.status_code, response.data), (404, TRIP_NOT_FOUND))


class GuestMemberEndpointTests(DiscoveryWorld, TestCase):
    """The five endpoints about the caller answer 401 to a guest."""

    def setUp(self):
        self.build_discovery_world()
        self.opt_in(self.traveler, (self.algiers, self.jijel))
        self.alert = RouteAlert.objects.create(
            user=self.other,
            watches=RouteAlert.Watches.TRIPS,
            origin_locality=self.paris,
            destination_locality=self.jijel,
        )

    def state(self):
        return (
            list(RouteAlert.objects.values().order_by("pk")),
            list(TravelerInterest.objects.values().order_by("pk")),
            list(PublicProfile.objects.values().order_by("pk")),
            list(PublicProfileRoute.objects.values().order_by("pk")),
        )

    def test_every_member_endpoint_refuses_a_guest_and_writes_nothing(self):
        route = {"origin_place_id": self.paris.pk, "destination_place_id": self.jijel.pk}
        calls = [
            ("get", reverse("discovery-matches"), {"role": "sender"}),
            ("get", reverse("discovery-matches"), {"role": "traveler"}),
            (
                "post",
                reverse("discovery-request-interest", args=(self.request.pk,)),
                {"journey_id": self.journey.pk},
            ),
            ("get", reverse("discovery-profile-me"), {}),
            (
                "put",
                reverse("discovery-profile-me"),
                {"is_discoverable": True, "prompt_dismissed": True, "usual_routes": [route]},
            ),
            ("get", reverse("discovery-alerts"), {}),
            ("post", reverse("discovery-alerts"), {"watches": "trips", **route}),
            ("delete", reverse("discovery-alert", args=(self.alert.pk,)), {}),
        ]
        before = self.state()
        for method, url, body in calls:
            with self.subTest(method=method, url=url):
                client = APIClient()
                if method == "get":
                    response = client.get(url, body)
                else:
                    response = getattr(client, method)(url, body, format="json")
                self.assertEqual(response.status_code, 401, response.data)
                self.assertEqual(
                    response.data, {"detail": "Authentication credentials were not provided."}
                )
        self.assertEqual(self.state(), before)

    def test_every_routed_view_is_public_or_member_by_its_base_class(self):
        routed = {pattern.callback.view_class for pattern in discovery_urls.urlpatterns}
        public = {view for view in routed if issubclass(view, views._PublicDiscoveryView)}
        member = {view for view in routed if issubclass(view, views._MemberDiscoveryView)}

        self.assertEqual({view.__name__ for view in public}, PUBLIC_READS)
        self.assertEqual({view.__name__ for view in member}, MEMBER_ENDPOINTS)
        self.assertEqual(public | member, routed)
        for view in public:
            self.assertEqual(view.permission_classes, (AllowAny,), view.__name__)
            self.assertIn(GuestRateThrottle, view.throttle_classes, view.__name__)
            self.assertNotIn(AnonRateThrottle, view.throttle_classes, view.__name__)
            self.assertEqual(view.throttle_scope, "matching_discovery", view.__name__)
        for view in member:
            self.assertEqual(view.permission_classes, (IsAuthenticated,), view.__name__)
            self.assertEqual(view.throttle_scope, "matching_discovery", view.__name__)

    def test_a_bad_or_expired_token_on_a_public_read_is_refused_not_read_as_a_guest(self):
        expired = AccessToken.for_user(self.other)
        expired.set_exp(from_time=timezone.now() - timedelta(hours=1), lifetime=timedelta(minutes=5))
        for token in ("not-a-token", str(expired)):
            with self.subTest(token=token[:12]):
                client = APIClient()
                client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
                response = client.get(reverse("discovery-trips"))
                self.assertEqual(response.status_code, 401, response.data)
                self.assertEqual(response.data["code"], "token_not_valid")


class GuestThrottleTests(DiscoveryWorld, TestCase):
    """A guest is counted by address on `discovery_guest` only; a member never is.

    Rewritten for the carrier-NAT review of plan EGS: a guest used to be
    counted on `matching_discovery` by address and on the shared `anon` rate,
    which hundreds of people behind one mobile carrier address would exhaust.
    """

    ADDRESS = "198.51.100.7"

    def setUp(self):
        self.build_discovery_world()
        cache.clear()
        self.addCleanup(cache.clear)

    def reads(self, client, times):
        return [client.get(reverse("discovery-trips")).status_code for _ in range(times)]

    def member_at(self, address):
        client = APIClient(REMOTE_ADDR=address)
        client.force_authenticate(user=self.other)
        return client

    def test_a_guest_is_counted_by_address_on_the_guest_scope(self):
        with patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"discovery_guest": "2/min"}):
            self.assertEqual(self.reads(APIClient(REMOTE_ADDR=self.ADDRESS), 3), [200, 200, 429])
            # The same address is the same guest, whatever the client.
            self.assertEqual(self.reads(APIClient(REMOTE_ADDR=self.ADDRESS), 1), [429])
            self.assertEqual(self.reads(APIClient(REMOTE_ADDR="198.51.100.8"), 2), [200, 200])
            # A member at that address is not a guest.
            self.assertEqual(self.reads(self.member_at(self.ADDRESS), 3), [200, 200, 200])

    def test_a_guest_is_not_counted_on_the_anonymous_or_member_scopes(self):
        tight = {"anon": "1/min", "user": "1/min", "matching_discovery": "1/min"}
        with patch.dict(ScopedRateThrottle.THROTTLE_RATES, tight):
            self.assertEqual(
                self.reads(APIClient(REMOTE_ADDR=self.ADDRESS), 4), [200, 200, 200, 200]
            )

    def test_a_member_keeps_the_per_member_discovery_scope(self):
        with patch.dict(
            ScopedRateThrottle.THROTTLE_RATES,
            {"matching_discovery": "2/min", "discovery_guest": "1/min"},
        ):
            self.assertEqual(self.reads(self.member_at(self.ADDRESS), 3), [200, 200, 429])
            # Counted per member, not per address, and not on the guest scope.
            self.assertEqual(self.reads(APIClient(REMOTE_ADDR=self.ADDRESS), 1), [200])
            self.assertEqual(self.reads(self.member_at("198.51.100.9"), 1), [429])
