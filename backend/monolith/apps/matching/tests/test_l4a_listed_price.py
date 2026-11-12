"""L4A: the listed price, Find Travelers and offers on a priced journey.

The package's "done when", proved end to end: a deal created at the listed
price carries exactly the amounts of the same deal created today by typing
that amount by hand. Around it, the one formula (`listed_reward`) is held at
every boundary, Find Travelers shows and sorts by it without a single extra
query, and an offer stays negotiable: anything at or above Wassla's minimum
is accepted, and a later price change never touches an offer already made.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from django.core.cache import cache
from django.db import connection
from django.test import Client, SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.business_settings import calculate_offer_economics
from apps.deals.models import Deal
from apps.deals.tests.phase4_factories import enable_mock_rail
from apps.discovery.tests.support import activate_marketplace
from apps.finance.models import LedgerEntry, PaymentAttempt, PaymentOrder
from apps.finance.tests.factories import pay_order_with_mock
from apps.matching.discovery import compatible_journeys_for_request, phase2_policy
from apps.matching.find_travelers import SORT_LISTED_PRICE
from apps.matching.listed_price import (
    BASIS_PER_KG,
    BASIS_TRAVELER_MINIMUM,
    BASIS_WASSLA_MINIMUM,
    listed_reward,
)
from apps.matching.models import Offer
from apps.matching.v1_services import (
    PriceBelowMinimum,
    accept_offer,
    counter_offer,
    create_sender_offer,
)
from apps.trips.models import Journey
from apps.trips.tests.sea_world import DRIVE, SeaWorld

FIND = "matches-find-travelers-v1"


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def quote(*, chargeable: str, minimum: int, commission_bps: int = 2_500):
    """Just the three quote fields the formula reads."""

    return SimpleNamespace(
        chargeable_weight_kg=Decimal(chargeable),
        minimum_reward_eur_cents=minimum,
        commission_rate_bps=commission_bps,
    )


def priced(per_kg: int | None, minimum: int | None) -> Journey:
    return Journey(price_per_kg_eur_cents=per_kg, min_price_eur_cents=minimum)


# ---------------------------------------------------------------------------
# The formula
# ---------------------------------------------------------------------------


class ListedRewardFormulaTests(SimpleTestCase):
    def listed(self, journey, pricing_quote, *, enabled=True):
        return listed_reward(journey, pricing_quote, enabled=enabled)

    def test_price_per_kg_times_chargeable_weight_wins_when_largest(self):
        listed = self.listed(priced(500, 1_000), quote(chargeable="2.500", minimum=900))
        assert (listed.reward_eur_cents, listed.basis) == (1_250, BASIS_PER_KG)

    def test_the_weighted_price_is_rounded_up_to_a_whole_cent(self):
        # 333 x 1.5 = 499.5 cents.
        listed = self.listed(priced(333, 100), quote(chargeable="1.500", minimum=100))
        assert listed.reward_eur_cents == 500
        # The smallest fraction still rounds up.
        listed = self.listed(priced(1_001, 100), quote(chargeable="1.001", minimum=100))
        assert listed.reward_eur_cents == 1_003  # 1002.001

    def test_an_exact_product_is_not_rounded(self):
        listed = self.listed(priced(400, 100), quote(chargeable="2.000", minimum=100))
        assert listed.reward_eur_cents == 800

    def test_the_travelers_minimum_wins_on_a_light_parcel(self):
        listed = self.listed(priced(200, 1_500), quote(chargeable="0.500", minimum=900))
        assert (listed.reward_eur_cents, listed.basis) == (1_500, BASIS_TRAVELER_MINIMUM)

    def test_wasslas_minimum_wins_when_the_travelers_price_is_lower(self):
        listed = self.listed(priced(100, 300), quote(chargeable="2.000", minimum=1_800))
        assert (listed.reward_eur_cents, listed.basis) == (1_800, BASIS_WASSLA_MINIMUM)

    def test_a_tie_names_the_travelers_own_terms(self):
        tie = self.listed(priced(500, 1_000), quote(chargeable="2.000", minimum=1_000))
        assert (tie.reward_eur_cents, tie.basis) == (1_000, BASIS_PER_KG)
        tie = self.listed(priced(100, 1_000), quote(chargeable="1.000", minimum=1_000))
        assert tie.basis == BASIS_TRAVELER_MINIMUM
        one_cent_over = self.listed(priced(100, 999), quote(chargeable="1.000", minimum=1_000))
        assert one_cent_over.basis == BASIS_WASSLA_MINIMUM

    def test_economics_are_the_offer_economics_of_the_listed_reward(self):
        listed = self.listed(
            priced(500, 1_000), quote(chargeable="2.500", minimum=900, commission_bps=1_234)
        )
        expected = calculate_offer_economics(
            1_250, SimpleNamespace(commission_rate_bps=1_234)
        )
        assert listed.economics == expected
        assert listed.as_dict() == {
            "reward_eur_cents": 1_250,
            "economics": expected,
            "price_per_kg_eur_cents": 500,
            "min_price_eur_cents": 1_000,
            "basis": BASIS_PER_KG,
        }

    def test_there_is_no_listed_price_without_a_price_a_quote_or_the_switch(self):
        some_quote = quote(chargeable="1.000", minimum=500)
        assert self.listed(priced(None, None), some_quote) is None
        assert self.listed(priced(500, 1_000), None) is None
        assert self.listed(priced(500, 1_000), some_quote, enabled=False) is None


# ---------------------------------------------------------------------------
# A world with a priced and an unpriced trip on the same road
# ---------------------------------------------------------------------------


class PricedWorld(SeaWorld):
    def build_priced_world(self) -> None:
        cache.clear()
        self.build_sea_world()
        self.policy = phase2_policy()
        self.sender = self.person("l4a-sender@example.com")
        self.sender.full_name = "Samia Sender"
        self.sender.save(update_fields=["full_name"])
        self.traveler = self.person("l4a-traveler@example.com")
        self.journey = self.road_trip(self.traveler)
        self.parcel = self.request_over(self.sender, self.journey, 0, 0, weight="2.40")

    def road_trip(self, traveler, *, per_kg=None, minimum=None) -> Journey:
        journey = self.make_journey(traveler, [(DRIVE, self.algiers, self.setif)])
        if per_kg is not None:
            Journey.objects.filter(pk=journey.pk).update(
                price_per_kg_eur_cents=per_kg, min_price_eur_cents=minimum
            )
            journey.refresh_from_db()
        return journey

    def set_price(self, journey, per_kg, minimum) -> None:
        response = client_for(journey.traveler).patch(
            reverse("journeys-pricing", args=(journey.pk,)),
            {"price_per_kg_eur_cents": per_kg, "min_price_eur_cents": minimum},
            format="json",
        )
        assert response.status_code == 200, response.data
        journey.refresh_from_db()

    def evaluation(self, delivery_request, journey):
        return next(
            row
            for row in compatible_journeys_for_request(
                delivery_request=delivery_request, policy=self.policy
            )
            if row.journey.pk == journey.pk
        )

    def find(self, delivery_request=None, **query) -> dict:
        query.setdefault("parcel_id", (delivery_request or self.parcel).pk)
        response = client_for(self.sender).get(reverse(FIND), query)
        assert response.status_code == 200, response.data
        return response.json()

    def row_for(self, page: dict, journey) -> dict:
        return next(row for row in page["results"] if row["journey_id"] == journey.pk)

    def propose(self, delivery_request, journey, reward: int) -> Offer:
        leg = journey.legs.get()
        return create_sender_offer(
            sender=delivery_request.sender,
            delivery_request=delivery_request,
            journey=journey,
            start_leg_id=leg.pk,
            end_leg_id=leg.pk,
            traveler_reward_eur_cents=reward,
        )


# ---------------------------------------------------------------------------
# Find Travelers
# ---------------------------------------------------------------------------


class FindTravelersListedPriceTests(PricedWorld, TestCase):
    def setUp(self):
        self.build_priced_world()

    def test_a_priced_journey_lists_the_one_formulas_answer(self):
        self.set_price(self.journey, 900, 1_000)
        evaluation = self.evaluation(self.parcel, self.journey)
        expected = listed_reward(self.journey, evaluation.pricing, enabled=True)

        row = self.row_for(self.find(), self.journey)

        listed = row["economics"]["listed"]
        assert listed == expected.as_dict()
        assert listed["price_per_kg_eur_cents"] == 900
        assert listed["min_price_eur_cents"] == 1_000
        # Fee and total on top of the listed reward, as on any offer.
        assert listed["economics"]["traveler_reward_minor"] == listed["reward_eur_cents"]
        assert (
            listed["economics"]["sender_total_minor"]
            == listed["reward_eur_cents"] + listed["economics"]["platform_fee_minor"]
        )
        # The Wassla minimum next to it is unchanged by the price.
        assert row["economics"]["minimum_reward_eur_cents"] == (
            evaluation.pricing.minimum_reward_eur_cents
        )

    def test_the_listed_price_never_goes_below_wasslas_minimum(self):
        self.set_price(self.journey, 1, 1)
        row = self.row_for(self.find(), self.journey)

        listed = row["economics"]["listed"]
        assert listed["basis"] == BASIS_WASSLA_MINIMUM
        assert listed["reward_eur_cents"] == row["economics"]["minimum_reward_eur_cents"]

    def test_an_unpriced_journey_has_no_listed_price(self):
        row = self.row_for(self.find(), self.journey)
        assert row["economics"]["listed"] is None

    def test_switching_pricing_off_removes_every_listed_price(self):
        self.set_price(self.journey, 900, 1_000)
        activate_marketplace({"traveler_pricing": {"enabled": False}})

        row = self.row_for(self.find(), self.journey)

        assert row["economics"]["listed"] is None
        # Matching itself is untouched: the row is there, with its minimum.
        assert row["economics"]["minimum_reward_eur_cents"] > 0

    def test_an_unreadable_marketplace_section_reads_as_pricing_off(self):
        self.set_price(self.journey, 900, 1_000)
        revision = activate_marketplace({})
        revision.__class__.objects.filter(pk=revision.pk).update(
            policy={**revision.policy, "marketplace": {"no_such_switch": True}}
        )
        self.policy = phase2_policy()

        assert self.evaluation(self.parcel, self.journey).listed is None

    def test_the_listed_price_sort_puts_the_cheapest_first_and_unpriced_last(self):
        cheap = self.road_trip(self.person("l4a-cheap@example.com"), per_kg=100, minimum=100)
        dear = self.road_trip(self.person("l4a-dear@example.com"), per_kg=5_000, minimum=100)
        unpriced = self.journey
        best_match = [row["journey_id"] for row in self.find()["results"]]
        assert set(best_match) == {cheap.pk, dear.pk, unpriced.pk}

        page = self.find(sort=SORT_LISTED_PRICE)

        assert page["sort"] == SORT_LISTED_PRICE
        assert [row["journey_id"] for row in page["results"]] == [cheap.pk, dear.pk, unpriced.pk]
        rewards = [row["economics"]["listed"] for row in page["results"]]
        assert rewards[0]["reward_eur_cents"] < rewards[1]["reward_eur_cents"]

    def test_equal_listed_prices_keep_best_match_order(self):
        twin = self.road_trip(self.person("l4a-twin@example.com"), per_kg=900, minimum=100)
        self.set_price(self.journey, 900, 100)
        best_match = [row["journey_id"] for row in self.find()["results"]]

        by_price = [row["journey_id"] for row in self.find(sort=SORT_LISTED_PRICE)["results"]]

        assert set(by_price) == {twin.pk, self.journey.pk}
        assert by_price == best_match

    def test_with_pricing_off_the_listed_price_sort_is_best_match(self):
        self.road_trip(self.person("l4a-other@example.com"), per_kg=100, minimum=100)
        activate_marketplace({"traveler_pricing": {"enabled": False}})

        best_match = [row["journey_id"] for row in self.find()["results"]]
        by_price = [row["journey_id"] for row in self.find(sort=SORT_LISTED_PRICE)["results"]]

        assert by_price == best_match

    def test_pricing_every_journey_adds_no_query(self):
        for index in range(3):
            self.road_trip(self.person(f"l4a-count-{index}@example.com"))

        def read():
            return self.find()

        read()
        with CaptureQueriesContext(connection) as unpriced:
            assert all(row["economics"]["listed"] is None for row in read()["results"])
        Journey.objects.update(price_per_kg_eur_cents=700, min_price_eur_cents=500)
        read()
        with CaptureQueriesContext(connection) as priced_reads:
            assert all(row["economics"]["listed"] for row in read()["results"])

        assert len(priced_reads.captured_queries) == len(unpriced.captured_queries)


# ---------------------------------------------------------------------------
# Offers stay negotiable and keep their snapshot
# ---------------------------------------------------------------------------


class OfferOnPricedJourneyTests(PricedWorld, TestCase):
    def setUp(self):
        self.build_priced_world()
        self.set_price(self.journey, 900, 1_000)
        self.evaluated = self.evaluation(self.parcel, self.journey)
        self.minimum = self.evaluated.pricing.minimum_reward_eur_cents
        self.listed = self.evaluated.listed
        assert self.listed.reward_eur_cents > self.minimum + 1

    def test_an_offer_below_wasslas_minimum_is_refused_exactly_as_before(self):
        with self.assertRaises(PriceBelowMinimum) as caught:
            self.propose(self.parcel, self.journey, self.minimum - 1)

        assert caught.exception.code == "reward_below_minimum"
        assert caught.exception.details() == {"minimum_reward_eur_cents": self.minimum}
        assert not Offer.objects.exists()

    def test_an_offer_below_the_listed_price_but_at_the_minimum_is_accepted(self):
        offer = self.propose(self.parcel, self.journey, self.minimum)

        assert offer.status == Offer.Status.PENDING
        assert offer.traveler_reward_minor == self.minimum
        assert offer.terms_snapshot["listed_price"] == self.listed.as_dict()

    def test_the_traveler_may_accept_an_offer_below_their_own_price(self):
        offer = self.propose(self.parcel, self.journey, self.minimum)

        deal = accept_offer(pending_offer=offer, actor=self.traveler).deal

        assert deal.terms.traveler_reward_minor == self.minimum

    def test_changing_the_price_leaves_an_existing_offers_snapshot_identical(self):
        offer = self.propose(self.parcel, self.journey, self.listed.reward_eur_cents)
        before = Offer.objects.values().get(pk=offer.pk)

        self.set_price(self.journey, 2_000, 4_000)
        self.set_price(self.journey, None, None)

        assert Offer.objects.values().get(pk=offer.pk) == before

    def test_a_counter_made_after_a_price_change_records_the_new_price(self):
        offer = self.propose(self.parcel, self.journey, self.minimum)
        self.set_price(self.journey, 2_000, 4_000)

        counter = counter_offer(
            pending_offer=offer,
            actor=self.traveler,
            traveler_reward_eur_cents=self.minimum + 500,
        )

        assert counter.terms_snapshot["listed_price"]["price_per_kg_eur_cents"] == 2_000
        offer.refresh_from_db()
        assert offer.terms_snapshot["listed_price"]["price_per_kg_eur_cents"] == 900

    def test_an_offer_on_an_unpriced_journey_snapshots_no_listed_price(self):
        self.set_price(self.journey, None, None)

        offer = self.propose(self.parcel, self.journey, self.minimum)

        assert offer.terms_snapshot["listed_price"] is None

    def test_the_parties_never_see_the_listed_price_in_the_public_snapshot(self):
        offer = self.propose(self.parcel, self.journey, self.minimum)

        body = client_for(self.sender).get(reverse("matches-detail", args=(offer.match_id,)))

        assert body.status_code == 200
        assert "listed_price" not in str(body.json())


# ---------------------------------------------------------------------------
# Done when: a deal at the listed price equals the deal typed by hand
# ---------------------------------------------------------------------------


def _amounts(instance) -> dict:
    """Every stored money column of a row, by name."""

    return {
        field.attname: getattr(instance, field.attname)
        for field in instance._meta.concrete_fields
        if field.attname.endswith(("_cents", "_minor", "_dzd", "_bps"))
    }


class ListedPriceDealEquivalenceTests(PricedWorld, TestCase):
    def setUp(self):
        enable_mock_rail()
        self.build_priced_world()

    def funded_deal(self, journey, delivery_request, reward: int) -> Deal:
        offer = self.propose(delivery_request, journey, reward)
        deal = accept_offer(pending_offer=offer, actor=journey.traveler).deal
        order = PaymentOrder.objects.get(deal=deal, purpose=PaymentOrder.Purpose.DEAL_BALANCE)
        pay_order_with_mock(Client(), order)
        deal.refresh_from_db()
        assert deal.status == Deal.Status.FUNDED
        return deal

    def every_amount(self, deal: Deal) -> dict:
        orders = PaymentOrder.objects.filter(deal=deal).order_by("purpose", "pk")
        attempts = PaymentAttempt.objects.filter(order__deal=deal).order_by("pk")
        entries = LedgerEntry.objects.filter(deal=deal).order_by("account", "amount_eur_cents")
        return {
            "offer": _amounts(deal.accepted_offer),
            "terms": {
                **_amounts(deal.terms),
                "traveler_total_minor": deal.terms.traveler_total_minor,
                "sender_total_with_boost_minor": deal.terms.sender_total_with_boost_minor,
            },
            "orders": [(order.purpose, _amounts(order)) for order in orders],
            "attempts": [_amounts(attempt) for attempt in attempts],
            "ledger": [(entry.account, entry.amount_eur_cents) for entry in entries],
        }

    def test_a_deal_at_the_listed_price_equals_the_same_deal_typed_by_hand(self):
        # Two travelers on the same road, one with a price. Two parcels that
        # are the same parcel, so Wassla's minimum is the same for both.
        self.set_price(self.journey, 900, 1_000)
        by_hand_journey = self.road_trip(self.person("l4a-by-hand@example.com"))
        by_hand_parcel = self.request_over(self.sender, by_hand_journey, 0, 0, weight="2.40")

        listed = self.row_for(self.find(), self.journey)["economics"]["listed"]
        assert self.row_for(self.find(by_hand_parcel), by_hand_journey)["economics"]["listed"] is None
        reward = listed["reward_eur_cents"]

        at_listed = self.funded_deal(self.journey, self.parcel, reward)
        typed = self.funded_deal(by_hand_journey, by_hand_parcel, reward)

        listed_amounts = self.every_amount(at_listed)
        assert listed_amounts == self.every_amount(typed)
        assert listed_amounts["terms"]["traveler_reward_minor"] == reward
        assert listed_amounts["terms"]["sender_total_minor"] == listed["economics"]["sender_total_minor"]
        assert listed_amounts["ledger"], "the funded deal posted ledger entries"
        # The only difference is the audit record of what was pre-filled.
        assert at_listed.terms.policy_snapshot["listed_price"] == listed
        assert typed.terms.policy_snapshot["listed_price"] is None
