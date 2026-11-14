"""L4A: the traveler's price on a journey (spec 8).

Setting it: both or neither, within the policy's bounds, never while the
switch is off. Changing it: through the route write and through its own
endpoint while the journey can still be offered on, each change written to the
price's audit trail. Showing it: the owner always sees what they stored;
anyone else, on the journey and on the discovery trip card, only while
traveler pricing is on. Staff change the switch and the bounds in the console
and see each journey's price history.
"""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.admin_panel.permissions import assign_admin_roles
from apps.discovery.tests.support import STATIC_STORES, activate_marketplace
from apps.matching.v1_services import create_sender_offer
from apps.trips.models import Journey, JourneyPriceChange
from apps.trips.services import cancel_journey

from .sea_world import DRIVE, SeaWorld
from .test_l3a_routes import RouteApiMixin, client_for
from apps.admin_panel.tests.two_step_helpers import staff_login


def first(value):
    """A serializer refusal wraps each value in a list; a view's does not."""

    return value[0] if isinstance(value, list) else value


def history(journey) -> list[tuple]:
    return list(
        JourneyPriceChange.objects.filter(journey=journey)
        .order_by("pk")
        .values_list(
            "price_per_kg_eur_cents_before",
            "min_price_eur_cents_before",
            "price_per_kg_eur_cents_after",
            "min_price_eur_cents_after",
        )
    )


class PricedRouteMixin(RouteApiMixin):
    def road(self, **extra) -> dict:
        return self.route((DRIVE, self.algiers, self.setif), **extra)

    def priced(self, per_kg=500, minimum=1_500) -> dict:
        return self.road(price_per_kg_eur_cents=per_kg, min_price_eur_cents=minimum)

    def edit(self, journey, payload):
        for leg, existing in zip(payload["legs"], journey.legs.order_by("position"), strict=True):
            leg["id"] = existing.pk
        return self.client.patch(
            reverse("journeys-detail", args=(journey.pk,)), payload, format="json"
        )

    def set_price(self, journey, per_kg, minimum, *, client=None):
        return (client or self.client).patch(
            reverse("journeys-pricing", args=(journey.pk,)),
            {"price_per_kg_eur_cents": per_kg, "min_price_eur_cents": minimum},
            format="json",
        )

    def live(self, journey) -> Journey:
        Journey.objects.filter(pk=journey.pk).update(status=Journey.Status.ACTIVE)
        journey.refresh_from_db()
        return journey


# ---------------------------------------------------------------------------
# Setting a price with the route
# ---------------------------------------------------------------------------


class RoutePriceWriteTests(PricedRouteMixin, APITestCase):
    def test_a_route_is_created_with_its_price_and_the_change_is_recorded(self):
        journey = self.created(self.priced())

        assert (journey.price_per_kg_eur_cents, journey.min_price_eur_cents) == (500, 1_500)
        assert history(journey) == [(None, None, 500, 1_500)]
        change = JourneyPriceChange.objects.get(journey=journey)
        assert change.actor == self.owner
        assert self.detail(journey).data["price"] == {
            "price_per_kg_eur_cents": 500,
            "min_price_eur_cents": 1_500,
        }

    def test_a_route_without_a_price_behaves_as_before(self):
        journey = self.created(self.road())

        assert journey.price_per_kg_eur_cents is None
        assert history(journey) == []
        assert self.detail(journey).data["price"] is None

    def test_both_or_neither(self):
        for fields in (
            {"price_per_kg_eur_cents": 500},
            {"min_price_eur_cents": 1_500},
            {"price_per_kg_eur_cents": 500, "min_price_eur_cents": None},
        ):
            with self.subTest(fields=fields):
                response = self.create(self.road(**fields))
                assert response.status_code == 400
                assert first(response.data["code"]) == "journey_price_invalid"
                assert first(response.data["reason"]) == "price_incomplete"
        assert not Journey.objects.exists()

    def test_a_price_must_be_at_least_one_cent(self):
        for fields in ({"price_per_kg_eur_cents": 0}, {"min_price_eur_cents": 0}):
            with self.subTest(fields=fields):
                payload = self.priced()
                payload.update(fields)
                response = self.create(payload)
                assert response.status_code == 400
                assert set(response.data) == set(fields)

    def test_each_part_stays_within_the_policy_bounds(self):
        at_limit = self.created(self.priced(per_kg=10_000, minimum=50_000))
        assert at_limit.price_per_kg_eur_cents == 10_000

        per_kg = self.create(self.priced(per_kg=10_001))
        assert per_kg.status_code == 400
        assert first(per_kg.data["reason"]) == "price_per_kg_above_maximum"
        assert int(first(per_kg.data["max_price_per_kg_eur_cents"])) == 10_000

        minimum = self.create(self.priced(minimum=50_001))
        assert minimum.status_code == 400
        assert first(minimum.data["reason"]) == "min_price_above_maximum"
        assert int(first(minimum.data["max_min_price_eur_cents"])) == 50_000

    def test_staff_tighten_the_bounds_for_the_next_price_only(self):
        journey = self.created(self.priced(per_kg=5_000))
        activate_marketplace({"traveler_pricing": {"max_price_per_kg_eur_cents": 1_000}})

        refused = self.create(self.priced(per_kg=1_001))
        assert first(refused.data["reason"]) == "price_per_kg_above_maximum"
        journey.refresh_from_db()
        # A price already stored is not rewritten, and an edit may keep it.
        assert journey.price_per_kg_eur_cents == 5_000
        assert self.edit(journey, self.priced(per_kg=5_000)).status_code == 200

    def test_an_edit_that_leaves_the_price_out_clears_it(self):
        journey = self.created(self.priced())

        response = self.edit(journey, self.road())

        assert response.status_code == 200, response.data
        assert response.data["price"] is None
        assert history(journey) == [(None, None, 500, 1_500), (500, 1_500, None, None)]

    def test_an_edit_that_resends_the_same_price_records_nothing(self):
        journey = self.created(self.priced())

        assert self.edit(journey, self.priced()).status_code == 200

        assert len(history(journey)) == 1

    def test_the_database_refuses_half_a_price(self):
        journey = self.created(self.road())
        with transaction.atomic(), self.assertRaises(IntegrityError):
            Journey.objects.filter(pk=journey.pk).update(price_per_kg_eur_cents=500)
        with transaction.atomic(), self.assertRaises(IntegrityError):
            Journey.objects.filter(pk=journey.pk).update(
                price_per_kg_eur_cents=0, min_price_eur_cents=0
            )


# ---------------------------------------------------------------------------
# The switch
# ---------------------------------------------------------------------------


class PricingSwitchTests(PricedRouteMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.journey = self.created(self.priced())
        activate_marketplace({"traveler_pricing": {"enabled": False}})

    def test_no_price_can_be_set_while_pricing_is_off(self):
        response = self.create(self.priced())
        assert response.status_code == 400
        assert first(response.data["code"]) == "traveler_pricing_disabled"

        changed = self.set_price(self.live(self.journey), 800, 1_500)
        assert changed.status_code == 409
        assert changed.data["code"] == "traveler_pricing_disabled"

    def test_an_edit_keeps_or_clears_a_stored_price_while_pricing_is_off(self):
        kept = self.edit(self.journey, self.priced())
        assert kept.status_code == 200, kept.data
        # The owner still sees what they stored.
        assert kept.data["price"] == {"price_per_kg_eur_cents": 500, "min_price_eur_cents": 1_500}

        assert self.set_price(self.live(self.journey), None, None).status_code == 200
        self.journey.refresh_from_db()
        assert self.journey.price_per_kg_eur_cents is None

    def test_nobody_else_sees_a_price_while_pricing_is_off(self):
        self.live(self.journey)
        stranger = self.person("l4a-stranger@example.com")

        assert self.detail(self.journey, user=stranger).data["price"] is None
        activate_marketplace({})
        assert self.detail(self.journey, user=stranger).data["price"] == {
            "price_per_kg_eur_cents": 500,
            "min_price_eur_cents": 1_500,
        }

    def test_the_editor_reads_the_switch_and_bounds(self):
        url = reverse("journeys-pricing-policy")

        assert self.client.get(url).data == {
            "enabled": False,
            "currency": "EUR",
            "max_price_per_kg_eur_cents": None,
            "max_min_price_eur_cents": None,
        }
        activate_marketplace({"traveler_pricing": {"max_min_price_eur_cents": 20_000}})
        assert self.client.get(url).data == {
            "enabled": True,
            "currency": "EUR",
            "max_price_per_kg_eur_cents": 10_000,
            "max_min_price_eur_cents": 20_000,
        }


# ---------------------------------------------------------------------------
# Changing the price of a live journey
# ---------------------------------------------------------------------------


class PricingEndpointTests(PricedRouteMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.journey = self.live(self.created(self.road()))

    def test_the_owner_prices_an_active_journey(self):
        response = self.set_price(self.journey, 800, 2_000)

        assert response.status_code == 200, response.data
        assert response.data["price"] == {"price_per_kg_eur_cents": 800, "min_price_eur_cents": 2_000}
        assert history(self.journey) == [(None, None, 800, 2_000)]

        assert self.set_price(self.journey, 800, 2_000).status_code == 200
        assert len(history(self.journey)) == 1, "an unchanged price records nothing"

    def test_only_the_owner_may_price_it(self):
        stranger = self.person("l4a-other@example.com")

        response = self.set_price(self.journey, 800, 2_000, client=client_for(stranger))

        assert response.status_code == 403
        assert response.data["code"] == "journey_not_owned"
        assert history(self.journey) == []

    def test_both_keys_are_required_and_checked(self):
        missing = self.client.patch(
            reverse("journeys-pricing", args=(self.journey.pk,)),
            {"price_per_kg_eur_cents": 800},
            format="json",
        )
        assert missing.status_code == 400
        assert "min_price_eur_cents" in missing.data

        half = self.set_price(self.journey, 800, None)
        assert half.status_code == 400
        assert (half.data["code"], half.data["reason"]) == ("journey_price_invalid", "price_incomplete")

        too_high = self.set_price(self.journey, 10_001, 100)
        assert too_high.status_code == 400
        assert too_high.data["max_price_per_kg_eur_cents"] == 10_000

    def test_a_journey_with_a_pending_offer_can_still_change_its_price(self):
        sender = self.person("l4a-sender@example.com")
        leg = self.journey.legs.get()
        parcel = self.request_over(sender, self.journey, 0, 0)
        create_sender_offer(
            sender=sender,
            delivery_request=parcel,
            journey=self.journey,
            start_leg_id=leg.pk,
            end_leg_id=leg.pk,
            traveler_reward_eur_cents=3_000,
        )
        assert self.detail(self.journey).data["editable"] is False

        response = self.set_price(self.journey, 800, 2_000)

        assert response.status_code == 200, response.data
        assert response.data["editable"] is False

    def test_a_finished_journey_can_no_longer_be_priced(self):
        cancel_journey(journey=self.journey, actor=self.owner)

        response = self.set_price(self.journey, 800, 2_000)

        assert response.status_code == 409
        assert (response.data["code"], response.data["status"]) == (
            "journey_price_not_editable",
            Journey.Status.CANCELLED,
        )

    def test_a_draft_and_a_paused_journey_can_be_priced(self):
        draft = self.created(self.road())
        assert self.set_price(draft, 800, 2_000).status_code == 200

        assert self.client.post(reverse("journeys-pause", args=(self.journey.pk,))).status_code == 200
        assert self.set_price(self.journey, 900, 2_000).status_code == 200


# ---------------------------------------------------------------------------
# The discovery trip card
# ---------------------------------------------------------------------------


class TripCardPriceTests(SeaWorld, APITestCase):
    def setUp(self):
        self.build_sea_world()
        self.viewer = self.person("l4a-viewer@example.com")
        self.priced = self.make_journey(
            self.person("l4a-priced@example.com"), [(DRIVE, self.algiers, self.setif)]
        )
        Journey.objects.filter(pk=self.priced.pk).update(
            price_per_kg_eur_cents=650, min_price_eur_cents=1_200
        )
        self.unpriced = self.make_journey(
            self.person("l4a-unpriced@example.com"), [(DRIVE, self.algiers, self.setif)]
        )

    def cards(self) -> dict:
        response = client_for(self.viewer).get(reverse("discovery-trips"))
        assert response.status_code == 200, response.data
        return {card["journey_id"]: card for card in response.data["results"]}

    def test_a_card_shows_the_travelers_price_and_nothing_computed(self):
        cards = self.cards()

        assert cards[self.priced.pk]["price"] == {
            "price_per_kg_eur_cents": 650,
            "min_price_eur_cents": 1_200,
        }
        assert cards[self.unpriced.pk]["price"] is None
        # Not a listed reward: a card is about no parcel in particular.
        for key in ("listed", "reward_eur_cents", "economics", "basis"):
            assert key not in str(cards[self.priced.pk])

    def test_a_card_shows_no_price_while_pricing_is_off(self):
        activate_marketplace({"traveler_pricing": {"enabled": False}})

        assert self.cards()[self.priced.pk]["price"] is None


# ---------------------------------------------------------------------------
# Console
# ---------------------------------------------------------------------------


@override_settings(STORAGES=STATIC_STORES)
class ConsolePriceTests(PricedRouteMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user(
            username="l4a-ops@example.com",
            email="l4a-ops@example.com",
            password="Sup3rStrongPass!",
            is_staff=True,
        )
        assign_admin_roles(self.admin, ["super_admin"])
        self.console = Client()
        staff_login(self.console, self.admin)

    def test_staff_switch_pricing_off_and_set_the_bounds(self):
        response = self.console.post(
            reverse("admin_console:settings"),
            {
                "action": "marketplace",
                "listings_enabled": "on",
                "profiles_enabled": "on",
                "interest_daily_cap": "10",
                "max_price_per_kg_eur": "25.50",
                "max_min_price_eur": "120.00",
                # L12A put trip-fit alerts and the proposal deadline in the same form.
                "trip_fit_max_travelers": "30",
                "trip_fit_daily_cap": "5",
                "response_hours": "6",
                "reminder_before_hours": "1",
                "reason": "Pricing review",
                "confirm": "on",
            },
        )

        assert response.status_code == 302
        from apps.core.marketplace_policy import marketplace_policy

        pricing = marketplace_policy().traveler_pricing
        assert (pricing.enabled, pricing.max_price_per_kg_eur_cents, pricing.max_min_price_eur_cents) == (
            False,
            2_550,
            12_000,
        )

    def test_the_journey_page_shows_the_price_and_its_history(self):
        journey = self.live(self.created(self.priced()))
        assert self.set_price(journey, 700, 1_500).status_code == 200

        body = self.console.get(reverse("admin_console:journey-detail", args=(journey.pk,)))

        assert body.status_code == 200
        text = body.content.decode()
        assert "€7.00 per kg, minimum €15.00" in text
        assert "€5.00 per kg, minimum €15.00" in text
        assert "No price" in text
