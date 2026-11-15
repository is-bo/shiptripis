"""L10 final acceptance: the switch matrix (plan L10 item 4, plan 1.5 rule 6).

Every switch the L-series added, turned off on the server the way staff turn
it off (a new settings revision), each in the same world: the capability
refuses on the server with its stable code, or simply stops happening when it
is a background effect. The app's unavailable states are proved by the Flutter
suites named in `docs/WASSLA_L_SERIES_RELEASE_REPORT.md`. Sea legs ship off and
are covered with their "on" run in `test_l10_same_day`.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta

from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from apps.admin_helper.models import AdminHelperKey
from apps.admin_helper.tests.world import bearer, new_key
from apps.core import channels
from apps.core.business_settings import activate_business_settings, get_active_business_settings
from apps.core.models import BusinessSettingsVersion
from apps.deals.tests.phase4_factories import freeze_at
from apps.discovery.tests.support import activate_marketplace
from apps.finance.jobs import run_due_jobs
from apps.notifications.models import Notification

from .l10_world import FLIGHT, SEA, AcceptanceWorld, api

GUIDE = "/api/admin/helper/v1/guide"


def code_of(response) -> str:
    code = response.data.get("code")
    return code[0] if isinstance(code, list) else code


class SwitchMatrixTests(AcceptanceWorld, TestCase):
    def setUp(self):
        cache.clear()
        self.build_acceptance_world()
        self.depart = self.now + timedelta(hours=10)
        self.journey = self.post_trip([self.leg_payload(FLIGHT, self.alg, self.cdg, self.depart, hours=3)])
        self.leg = self.journey.legs.get()
        self.approve_ticket(self.upload_ticket(self.leg))
        self.publish(self.journey)
        self.set_price(self.journey, 600, 1_200)

    def open_parcel(self):
        parcel = self.post_parcel(
            self.algiers,
            self.paris,
            ready_from=self.depart - timedelta(hours=2),
            ready_until=self.depart + timedelta(minutes=30),
            deliver_by=self.depart + timedelta(hours=12),
        )
        self.pay_deposit(parcel)
        return parcel

    def off(self, **discovery_or_sections) -> None:
        activate_marketplace(discovery_or_sections)

    # -- discovery ----------------------------------------------------------

    def test_listings_off_closes_home_lists_and_i_can_carry_this(self):
        parcel = self.open_parcel()
        self.off(discovery={"listings_enabled": False})
        for name in ("discovery-trips", "discovery-requests"):
            response = api(self.sender).get(reverse(name))
            assert response.status_code == 200 and response.data["state"] == "disabled", (name, response.data)
        interest = api(self.traveler).post(
            reverse("discovery-request-interest", args=(parcel.pk,)), {"journey_id": self.journey.pk}, format="json"
        )
        assert code_of(interest) == "discovery_listings_disabled", interest.data

    def test_profiles_off_closes_people_and_the_own_profile(self):
        self.off(discovery={"profiles_enabled": False})
        people = api(self.sender).get(reverse("discovery-people"), {"role": "traveler"})
        assert people.data["state"] == "disabled", people.data
        me = api(self.traveler).get(reverse("discovery-profile-me"))
        assert me.data["state"] == "disabled", me.data
        changed = api(self.traveler).put(reverse("discovery-profile-me"), {"is_discoverable": True}, format="json")
        assert code_of(changed) == "discovery_profiles_disabled", changed.data

    def test_trip_fit_alerts_off_tells_nobody(self):
        self.off(discovery={"trip_fit_alerts_enabled": False})
        self.open_parcel()
        run_due_jobs(limit=50)
        assert not Notification.objects.filter(channel=channels.DISCOVERY_REQUEST_FITS_TRIP).exists()

    def test_trip_fit_alerts_on_tell_the_traveler(self):
        self.open_parcel()
        run_due_jobs(limit=50)
        assert Notification.objects.filter(
            channel=channels.DISCOVERY_REQUEST_FITS_TRIP, recipient=self.traveler
        ).exists()

    # -- routes and prices --------------------------------------------------

    def test_sea_legs_off_refuses_a_sea_leg(self):
        response = api(self.traveler).post(
            reverse("journeys-list-create"),
            {
                "start_place_id": self.marseille.pk,
                "destination_place_id": self.algiers.pk,
                "notes": "",
                "legs": [{**self.leg_payload(SEA, self.marseille, self.algiers, self.depart, hours=20), "position": 0}],
            },
            format="json",
        )
        assert response.status_code == 400 and response.data["reason"] == ["sea_legs_disabled"], response.data

    def test_traveler_pricing_off_refuses_a_price_and_lists_none(self):
        parcel = self.open_parcel()
        self.off(traveler_pricing={"enabled": False})
        refused = api(self.traveler).patch(
            reverse("journeys-pricing", args=(self.journey.pk,)),
            {"price_per_kg_eur_cents": 700, "min_price_eur_cents": 1_200},
            format="json",
        )
        assert code_of(refused) == "traveler_pricing_disabled", refused.data
        found = api(self.sender).get(reverse("matches-find-travelers-v1"), {"parcel_id": parcel.pk})
        row = next(r for r in found.data["results"] if r["journey_id"] == self.journey.pk)
        assert row["economics"]["listed"] is None

    # -- proposals and progress ---------------------------------------------

    def test_the_response_deadline_off_gives_a_proposal_no_deadline(self):
        parcel = self.open_parcel()
        self.off(offers={"response_deadline_enabled": False, "response_hours": 6, "reminder_before_hours": 1})
        offer = self.propose(parcel, self.journey, self.leg, self.leg, 3_000)
        assert offer["expires_at"] is None, offer

    def funded_and_past_departure(self, *, reminders: bool) -> None:
        parcel = self.open_parcel()
        deal = self.accept(self.propose(parcel, self.journey, self.leg, self.leg, 3_000))
        self.pay_balance(deal)
        self.off(reminders={"enabled": reminders})
        with freeze_at(self.leg.depart_at + timedelta(hours=2)):
            run_due_jobs(limit=50)

    def test_reminders_off_asks_the_traveler_nothing(self):
        self.funded_and_past_departure(reminders=False)
        assert not Notification.objects.filter(channel=channels.JOURNEY_LEG_REMINDER).exists()

    def test_reminders_on_ask_the_traveler_whether_they_left(self):
        self.funded_and_past_departure(reminders=True)
        assert Notification.objects.filter(channel=channels.JOURNEY_LEG_REMINDER, recipient=self.traveler).exists()

    # -- the AI helper ------------------------------------------------------

    def test_the_helper_off_refuses_every_key_at_once(self):
        read, change = new_key(self.ops), new_key(self.finance, kind=AdminHelperKey.Kind.CHANGE)
        client = Client()
        assert client.get(GUIDE, **bearer(read)).status_code == 200
        assert client.get(GUIDE, **bearer(change)).status_code == 200

        active = get_active_business_settings()
        policy = deepcopy(active.policy)
        policy.setdefault("admin_helper", {})["enabled"] = False
        latest = BusinessSettingsVersion.objects.order_by("-version").first()
        activate_business_settings(
            BusinessSettingsVersion.objects.create(
                version=latest.version + 1,
                commission_rate_bps=active.commission_rate_bps,
                pricing_version=active.pricing_version,
                policy=policy,
            )
        )
        for plain in (read, change):
            response = client.get(GUIDE, **bearer(plain))
            assert response.status_code == 401, response.content
        assert not AdminHelperKey.objects.filter(revoked_at__isnull=True).exists()
