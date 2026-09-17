"""J6.3 — the request pricing quote states the Boost-inclusive total.

What is being defended:

**The posting screen's total is the Deal's total.** A €30.00 reward with a
€5.00 Boost owes €43.75, not €37.50. The quote publishes `chosen_terms` --
Traveler total, Boost fee and the sender's Boost-inclusive total -- built by the
same functions an Offer projection and acceptance use, so request quote, Offer
and Deal state one set of numbers.

**The old fields keep their meaning.** `chosen_economics.sender_total_minor` is
still the base total and the `boost` block is unchanged.

**The deposit ceiling is the same total.** The draft quote's deposit
`maximum_eur_cents` is the figure creation enforces.

**Committed means frozen.** Once a Deal exists, the request's pricing reports the
Deal's terms, not the request's Boost column (which funding clears) or a later
Admin rate.
"""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from apps.boosts.services import set_boost_intent
from apps.boosts.tests.test_j2_boost import set_boost_commission
from apps.deals.models import Deal
from apps.deals.tests.phase4_factories import enable_mock_rail
from apps.finance.tests.factories import build_scenario, pay_order_with_mock
from apps.matching.tests.test_phase_j61_offer_boost_projection import (
    TERMS_FIELDS,
    accept,
    client_for,
    confirmed,
    deal_balance_order,
    latest_offer,
    propose,
)
from apps.parcels.models import DeliveryRequest

# Imported as a module so pytest does not collect J2PostingTests a second time.
from apps.parcels.tests import test_j2_posting as j2

MONEY = (
    "traveler_reward_minor",
    "platform_fee_minor",
    "sender_total_minor",
    "boost_amount_minor",
    "boost_traveler_bonus_minor",
    "boost_platform_fee_minor",
    "traveler_total_minor",
    "sender_total_with_boost_minor",
)


def money(terms: dict) -> dict:
    return {field: terms[field] for field in MONEY}


def pricing(user, request_id: int):
    response = client_for(user).get(reverse("parcels-pricing", args=[request_id]))
    assert response.status_code == 200, response.data
    return response.data


@patch("apps.core.redis_bus.publish_after_commit")
class DraftQuoteTotalsTests(TestCase):
    setUp = j2.J2PostingTests.setUp
    _photo = j2.J2PostingTests._photo
    _payload = j2.J2PostingTests._payload
    _create = j2.J2PostingTests._create
    _draft_quote = j2.J2PostingTests._draft_quote

    def _quote(self, **overrides) -> dict:
        response = self._draft_quote(**overrides)
        assert response.status_code == 200, response.data
        return response.data

    def test_zero_boost_total_is_the_base_total(self, _publish):
        data = self._quote(chosen_reward_eur_cents=3_000)

        terms = data["chosen_terms"]
        assert terms["terms_status"] == "provisional"
        assert terms["currency"] == "EUR"
        assert terms["boost_economics_version"] == "additive_commission_v2"
        assert money(terms) == {
            "traveler_reward_minor": 3_000,
            "platform_fee_minor": 750,
            "sender_total_minor": 3_750,
            "boost_amount_minor": 0,
            "boost_traveler_bonus_minor": 0,
            "boost_platform_fee_minor": 0,
            "traveler_total_minor": 3_000,
            "sender_total_with_boost_minor": 3_750,
        }
        assert data["deposit"]["maximum_eur_cents"] == 3_750

    def test_a_boost_is_in_the_travelers_total_and_the_senders_total(self, _publish):
        data = self._quote(chosen_reward_eur_cents=3_000, boost_eur_cents=500)

        assert money(data["chosen_terms"]) == {
            "traveler_reward_minor": 3_000,
            "platform_fee_minor": 750,
            "sender_total_minor": 3_750,
            "boost_amount_minor": 500,
            "boost_traveler_bonus_minor": 500,
            "boost_platform_fee_minor": 125,
            # the whole Boost goes to the Traveler
            "traveler_total_minor": 3_500,
            # 3000 + 750 + 500 + 125: the figure the Deal will freeze
            "sender_total_with_boost_minor": 4_375,
        }
        # Old fields keep their meaning: base economics, and the Boost block.
        assert data["chosen_economics"]["sender_total_minor"] == 3_750
        assert data["boost"]["boost_eur_cents"] == 500
        assert data["boost"]["total_offered_reward_eur_cents"] == 3_500
        # The ceiling is the whole obligation, Boost and fee counted once.
        assert data["deposit"]["maximum_eur_cents"] == 4_375
        # The recommendation stays on the recommended base total.
        assert (
            data["deposit"]["recommendation_basis_eur_cents"]
            == data["recommended_economics"]["sender_total_minor"]
        )

    def test_no_chosen_reward_states_no_total(self, _publish):
        data = self._quote(boost_eur_cents=500)

        assert data["chosen_terms"]["terms_status"] == "unavailable"
        assert all(data["chosen_terms"][field] is None for field in MONEY)
        assert data["deposit"]["maximum_eur_cents"] is None

    def test_a_different_boost_rate_rounds_the_fee_up_and_the_base_rate_is_separate(
        self, _publish
    ):
        set_boost_commission(1_500)
        data = self._quote(chosen_reward_eur_cents=3_001, boost_eur_cents=777)

        terms = data["chosen_terms"]
        # Base: ceil(3001 x 25%) = 751. Boost: ceil(777 x 15%) = ceil(116.55).
        assert terms["platform_fee_minor"] == 751
        assert terms["boost_platform_fee_minor"] == 117
        assert terms["traveler_total_minor"] == 3_001 + 777
        assert terms["sender_total_with_boost_minor"] == 3_001 + 751 + 777 + 117
        assert data["deposit"]["maximum_eur_cents"] == 4_646

    def test_changing_the_reward_or_the_boost_moves_the_totals(self, _publish):
        first = self._quote(chosen_reward_eur_cents=3_000, boost_eur_cents=500)
        reward = self._quote(chosen_reward_eur_cents=4_000, boost_eur_cents=500)
        boost = self._quote(chosen_reward_eur_cents=4_000, boost_eur_cents=1_000)
        removed = self._quote(chosen_reward_eur_cents=4_000, boost_eur_cents=0)

        totals = [
            (
                q["chosen_terms"]["traveler_total_minor"],
                q["chosen_terms"]["sender_total_with_boost_minor"],
                q["deposit"]["maximum_eur_cents"],
            )
            for q in (first, reward, boost, removed)
        ]
        assert totals == [
            (3_500, 4_375, 4_375),
            (4_500, 5_625, 5_625),
            (5_000, 6_250, 6_250),
            (4_000, 5_000, 5_000),
        ]

    def test_an_admin_rate_change_reaches_a_fresh_quote(self, _publish):
        before = self._quote(chosen_reward_eur_cents=3_000, boost_eur_cents=500)
        set_boost_commission(1_000)
        after = self._quote(chosen_reward_eur_cents=3_000, boost_eur_cents=500)

        assert before["chosen_terms"]["boost_platform_fee_minor"] == 125
        assert after["chosen_terms"]["boost_platform_fee_minor"] == 50
        assert after["chosen_terms"]["sender_total_with_boost_minor"] == 4_300

    def test_the_draft_ceiling_is_the_one_creation_enforces(self, _publish):
        quote = self._quote(chosen_reward_eur_cents=3_000, boost_eur_cents=800)
        ceiling = quote["deposit"]["maximum_eur_cents"]
        assert ceiling == 4_750

        over = self._create(boost_eur_cents=800, posting_deposit_eur_cents=ceiling + 1)
        assert over.status_code in (400, 409), over.data
        assert not DeliveryRequest.objects.exists()

        created = self._create(boost_eur_cents=800, posting_deposit_eur_cents=ceiling)
        assert created.status_code == 201, created.data
        request_id = created.data["id"]

        saved = pricing(self.sender, request_id)
        # Draft quote -> saved request: the same terms, the same ceiling.
        assert money(saved["chosen_terms"]) == money(quote["chosen_terms"])
        assert saved["chosen_terms"]["terms_status"] == "provisional"
        assert saved["deposit"]["maximum_eur_cents"] == ceiling
        deposit = client_for(self.sender).get(
            reverse("finance-posting-deposit", args=[request_id])
        )
        assert deposit.status_code == 200, deposit.data
        assert deposit.data["quote"]["maximum_eur_cents"] == ceiling


class RequestOfferDealConsistencyTests(TestCase):
    def test_request_quote_offer_and_deal_state_one_set_of_numbers(self):
        enable_mock_rail()
        set_boost_commission(2_500)
        scenario = build_scenario(prefix="j63c")
        set_boost_intent(
            delivery_request_id=scenario.delivery_request.pk,
            actor_id=scenario.sender.pk,
            amount_eur_cents=500,
        )

        quoted = pricing(scenario.sender, scenario.delivery_request.pk)
        request_terms = quoted["chosen_terms"]
        assert request_terms["terms_status"] == "provisional"
        assert request_terms["traveler_total_minor"] == 2_500
        assert request_terms["sender_total_with_boost_minor"] == 3_125
        assert quoted["deposit"]["maximum_eur_cents"] == 3_125

        # Request quote -> proposed Offer.
        offer = propose(scenario, reward=quoted["chosen_reward_eur_cents"])
        for field in TERMS_FIELDS:
            assert offer[field] == request_terms[field], field
        assert offer["sender_total_minor"] == request_terms["sender_total_minor"]
        assert offer["platform_fee_minor"] == request_terms["platform_fee_minor"]

        # Offer -> Deal.
        shown = latest_offer(scenario.traveler, offer["match"])
        response = accept(scenario.traveler, shown["id"], **confirmed(shown))
        assert response.status_code == 201, response.data
        deal = Deal.objects.get(pk=response.data["id"])
        for field in TERMS_FIELDS:
            assert getattr(deal.terms, field) == request_terms[field], field
        balance = deal_balance_order(deal)
        assert (
            int(balance.amount_eur_cents)
            == request_terms["sender_total_with_boost_minor"]
        )

        # Committed: the request pricing reports the frozen Deal, and a later
        # Admin rate change does not reach it.
        set_boost_commission(1_000)
        frozen = pricing(scenario.sender, scenario.delivery_request.pk)
        assert frozen["chosen_terms"]["terms_status"] == "frozen"
        assert money(frozen["chosen_terms"]) == money(request_terms)

        # Funding clears the request's Boost column; the frozen total stands.
        pay_order_with_mock(self.client, balance)
        scenario.delivery_request.refresh_from_db()
        assert scenario.delivery_request.boost_eur_cents == 0
        funded = pricing(scenario.sender, scenario.delivery_request.pk)
        assert funded["chosen_terms"]["terms_status"] == "frozen"
        assert money(funded["chosen_terms"]) == money(request_terms)

    def test_a_rate_change_before_commitment_moves_quote_offer_and_deal_together(
        self,
    ):
        enable_mock_rail()
        scenario = build_scenario(prefix="j63r")
        set_boost_intent(
            delivery_request_id=scenario.delivery_request.pk,
            actor_id=scenario.sender.pk,
            amount_eur_cents=800,
        )
        match_id = propose(scenario)["match"]
        set_boost_commission(1_000)

        request_terms = pricing(scenario.sender, scenario.delivery_request.pk)[
            "chosen_terms"
        ]
        shown = latest_offer(scenario.traveler, match_id)
        assert request_terms["boost_platform_fee_minor"] == 80
        for field in TERMS_FIELDS:
            assert shown[field] == request_terms[field], field

        response = accept(scenario.traveler, shown["id"], **confirmed(shown))
        assert response.status_code == 201, response.data
        terms = Deal.objects.get().terms
        assert (
            terms.sender_total_with_boost_minor
            == request_terms["sender_total_with_boost_minor"]
        )

    def test_pricing_is_the_senders_alone(self):
        scenario = build_scenario(prefix="j63a")
        for user in (scenario.traveler, scenario.outsider):
            response = client_for(user).get(
                reverse("parcels-pricing", args=[scenario.delivery_request.pk])
            )
            assert response.status_code == 403
