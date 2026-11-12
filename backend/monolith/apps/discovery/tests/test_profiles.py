"""L2A People tier, the person page and a member's own public profile."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.discovery.models import PublicProfile
from apps.discovery.profiles import PROFILE_CONSENT_VERSION, set_profile_hidden
from apps.trips.models import Journey

from .support import DiscoveryWorld, activate_marketplace, client_for

ME = "discovery-profile-me"
PEOPLE = "discovery-people"
PERSON = "discovery-person"


class OwnProfileTests(DiscoveryWorld, TestCase):
    def setUp(self):
        self.build_discovery_world()
        self.client = client_for(self.traveler)

    def me(self):
        response = self.client.get(reverse(ME))
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def put(self, body, status=200):
        response = self.client.put(reverse(ME), body, format="json")
        self.assertEqual(response.status_code, status, response.data)
        return response.data

    def test_a_member_who_never_opened_discovery_is_off_and_sees_the_prompt(self):
        payload = self.me()

        self.assertEqual(payload["state"], "not_visible")
        self.assertFalse(payload["is_discoverable"])
        self.assertTrue(payload["show_prompt"])
        self.assertEqual(payload["consent_version"], PROFILE_CONSENT_VERSION)
        self.assertEqual(payload["card"]["display_name"], "Yacine")
        self.assertIsNone(payload["card"]["id"])
        # Reading never writes.
        self.assertFalse(PublicProfile.objects.filter(user=self.traveler).exists())

    def test_turning_it_on_records_consent_and_the_card_is_the_public_card(self):
        payload = self.put(
            {
                "is_discoverable": True,
                "usual_routes": [
                    {"origin_place_id": self.cdg.pk, "destination_place_id": self.jijel.pk}
                ],
            }
        )

        self.assertEqual(payload["state"], "visible")
        self.assertFalse(payload["show_prompt"])
        profile = PublicProfile.objects.get(user=self.traveler)
        self.assertEqual(profile.consent_version, PROFILE_CONSENT_VERSION)
        self.assertIsNotNone(profile.consented_at)
        # The airport resolved to the city behind it.
        self.assertEqual(
            payload["usual_routes"],
            [
                {
                    "origin": {"place_id": self.paris.pk, "label": "Paris", "country_code": "FR"},
                    "destination": {
                        "place_id": self.jijel.pk,
                        "label": "Jijel",
                        "country_code": "DZ",
                    },
                }
            ],
        )
        public = client_for(self.sender).get(reverse(PERSON, args=(profile.public_id,)))
        self.assertEqual(public.data["profile"], payload["card"])

    def test_turning_it_off_takes_it_out_of_people_at_once(self):
        self.put({"is_discoverable": True})
        self.assertEqual(self._people_ids(), [str(self.traveler.public_profile.public_id)])

        self.put({"is_discoverable": False})

        self.assertEqual(self._people_ids(), [])
        self.assertEqual(self.me()["state"], "not_visible")

    def _people_ids(self):
        rows = client_for(self.sender).get(reverse(PEOPLE), {"role": "sender"}).data["results"]
        return [row["id"] for row in rows if row["id"]]

    def test_dismissing_the_prompt_hides_it_for_good(self):
        payload = self.put({"prompt_dismissed": True})
        self.assertFalse(payload["show_prompt"])
        self.assertFalse(payload["is_discoverable"])

    def test_usual_routes_are_validated(self):
        same = {"origin_place_id": self.cdg.pk, "destination_place_id": self.paris.pk}
        pair = {"origin_place_id": self.paris.pk, "destination_place_id": self.jijel.pk}
        airport_pair = {"origin_place_id": self.cdg.pk, "destination_place_id": self.jijel.pk}
        unknown = {"origin_place_id": 999_999, "destination_place_id": self.jijel.pk}
        cases = (
            ([same], "usual_route_same_city"),
            ([pair, airport_pair], "usual_route_duplicate"),
            ([unknown], "place_not_found"),
        )
        for routes, code in cases:
            with self.subTest(code):
                self.assertEqual(self.put({"usual_routes": routes}, status=400)["code"], code)
        four = [pair] * 4
        self.put({"usual_routes": four}, status=400)

    def test_an_empty_change_is_refused(self):
        self.put({}, status=400)

    def test_replacing_routes_keeps_their_order(self):
        first = {"origin_place_id": self.algiers.pk, "destination_place_id": self.jijel.pk}
        second = {"origin_place_id": self.paris.pk, "destination_place_id": self.algiers.pk}
        self.put({"usual_routes": [first, second]})
        payload = self.put({"usual_routes": [second]})
        self.assertEqual(
            [route["origin"]["label"] for route in payload["usual_routes"]], ["Paris"]
        )

    def test_profiles_switched_off_refuses_turning_on_but_allows_turning_off(self):
        self.put({"is_discoverable": True})
        activate_marketplace({"discovery": {"profiles_enabled": False}})

        self.assertEqual(self.me()["state"], "disabled")
        self.assertFalse(self.me()["show_prompt"])
        self.put({"is_discoverable": False})
        self.assertEqual(
            self.put({"is_discoverable": True}, status=409)["code"],
            "discovery_profiles_disabled",
        )

    def test_a_hidden_profile_reads_not_currently_visible_without_the_reason(self):
        self.put({"is_discoverable": True})
        staff = self.new_traveler("l2a-staff@example.com")
        set_profile_hidden(user=self.traveler, actor=staff, hidden=True, reason="Spam reports")

        payload = self.me()

        self.assertEqual(payload["state"], "hidden")
        self.assertTrue(payload["is_discoverable"])  # their own choice is kept
        self.assertNotIn("Spam", str(payload))


class PeopleTierTests(DiscoveryWorld, TestCase):
    def setUp(self):
        self.build_discovery_world()
        self.traveler_profile = self.opt_in(self.traveler)
        self.sender_profile = self.opt_in(self.sender)

    def people(self, viewer, **query):
        response = client_for(viewer).get(reverse(PEOPLE), query)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def ids(self, viewer, **query):
        return [row["id"] for row in self.people(viewer, **query)["results"]]

    def test_a_sender_sees_travelers_and_a_traveler_sees_senders(self):
        self.assertEqual(
            self.ids(self.other, role="sender"), [str(self.traveler_profile.public_id)]
        )
        self.assertEqual(
            self.ids(self.other, role="traveler"), [str(self.sender_profile.public_id)]
        )

    def test_the_caller_is_never_listed(self):
        self.assertEqual(self.ids(self.traveler, role="sender"), [])

    def test_opted_out_hidden_banned_and_inactive_members_are_absent(self):
        expected = [str(self.traveler_profile.public_id)]
        changes = (
            lambda: PublicProfile.objects.filter(pk=self.traveler_profile.pk).update(
                is_discoverable=False
            ),
            lambda: PublicProfile.objects.filter(pk=self.traveler_profile.pk).update(
                hidden_at=timezone.now(), hidden_reason="test"
            ),
            lambda: type(self.traveler).objects.filter(pk=self.traveler.pk).update(
                is_banned=True
            ),
            lambda: type(self.traveler).objects.filter(pk=self.traveler.pk).update(
                is_active=False
            ),
        )
        for index, change in enumerate(changes):
            with self.subTest(index):
                change()
                self.assertEqual(self.ids(self.other, role="sender"), [])
                PublicProfile.objects.filter(pk=self.traveler_profile.pk).update(
                    is_discoverable=True, hidden_at=None, hidden_reason=""
                )
                type(self.traveler).objects.filter(pk=self.traveler.pk).update(
                    is_banned=False, is_active=True
                )
                self.assertEqual(self.ids(self.other, role="sender"), expected)

    def test_an_opted_in_member_with_no_activity_and_no_route_is_not_a_traveler(self):
        Journey.objects.filter(traveler=self.traveler).update(
            published_at=timezone.now() - timedelta(days=400)
        )
        self.assertEqual(self.ids(self.other, role="sender"), [])
        self.traveler_profile.usual_routes.create(
            position=0, origin_locality=self.algiers, destination_locality=self.jijel
        )
        self.assertEqual(
            self.ids(self.other, role="sender"), [str(self.traveler_profile.public_id)]
        )

    def test_route_filters_match_usual_routes_and_recent_activity(self):
        # Activity: the journey goes Paris (CDG) → Algiers → Jijel.
        self.assertEqual(len(self.ids(self.other, role="sender", origin_place_id=self.cdg.pk)), 1)
        self.assertEqual(
            self.ids(self.other, role="sender", origin_place_id=self.jijel.pk), []
        )
        # A usual route alone puts a member on a route their trips never took.
        self.traveler_profile.usual_routes.create(
            position=0, origin_locality=self.jijel, destination_locality=self.paris
        )
        self.assertEqual(
            len(
                self.ids(
                    self.other,
                    role="sender",
                    origin_place_id=self.jijel.pk,
                    destination_place_id=self.cdg.pk,
                )
            ),
            1,
        )

    def test_profiles_switched_off_answers_disabled(self):
        activate_marketplace({"discovery": {"profiles_enabled": False}})
        self.assertEqual(self.people(self.other, role="sender")["state"], "disabled")

    def test_the_card_counts_deliveries_on_both_sides_of_the_person(self):
        from apps.deals.models import Deal
        from apps.matching.v1_services import accept_offer

        accepted = accept_offer(pending_offer=self.propose(), actor=self.traveler)
        Deal.objects.filter(pk=accepted.deal.pk).update(status=Deal.Status.COMPLETED)

        [traveler_card] = self.people(self.other, role="sender")["results"]
        [sender_card] = self.people(self.other, role="traveler")["results"]
        self.assertEqual(traveler_card["completed_deliveries"], 1)
        self.assertEqual(sender_card["completed_deliveries"], 1)


class PersonPageTests(DiscoveryWorld, TestCase):
    def setUp(self):
        self.build_discovery_world()
        self.profile = self.opt_in(self.traveler, (self.algiers, self.jijel))

    def get(self, public_id=None):
        return client_for(self.other).get(
            reverse(PERSON, args=(public_id or self.profile.public_id,))
        )

    def test_the_page_shows_the_card_and_their_listed_trips(self):
        response = self.get()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["profile"]["display_name"], "Yacine")
        self.assertTrue(response.data["profile"]["identity_verified"])
        self.assertEqual(
            [trip["journey_id"] for trip in response.data["trips"]], [self.journey.pk]
        )
        self.assertEqual(response.data["requests"], [])

    def test_an_unknown_or_not_visible_profile_is_not_found(self):
        self.assertEqual(self.get(uuid4()).status_code, 404)
        PublicProfile.objects.filter(pk=self.profile.pk).update(is_discoverable=False)
        response = self.get()
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["code"], "profile_not_found")

    def test_listings_switched_off_keeps_the_card_without_items(self):
        activate_marketplace({"discovery": {"listings_enabled": False}})
        response = self.get()
        self.assertEqual(response.data["trips"], [])
        self.assertEqual(response.data["profile"]["display_name"], "Yacine")

    def test_profiles_switched_off_answers_disabled(self):
        activate_marketplace({"discovery": {"profiles_enabled": False}})
        self.assertEqual(self.get().data, {"state": "disabled"})

    def test_an_opted_out_traveler_still_has_their_trips_listed(self):
        """Spec 4.3: the profile is opt-in; published trips stay in Listings."""

        PublicProfile.objects.filter(pk=self.profile.pk).update(is_discoverable=False)
        trips = client_for(self.other).get(reverse("discovery-trips")).data["results"]
        self.assertEqual([row["journey_id"] for row in trips], [self.journey.pk])
