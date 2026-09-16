"""J6.1 — an Offer publishes its Boost economics, and acceptance commits them.

What is being defended, in the order a Traveler meets it:

**The figure shown is the figure frozen.** A pending offer publishes what
accepting it right now would commit -- base reward, Boost, the Traveler's total
and the sender's total -- built through the same functions acceptance uses. An
accepted offer publishes its Deal's frozen terms and nothing else.

**A race ends in a refusal, never a silent substitution.** The sender may change
their Boost while an offer is open. The acceptor echoes the totals they read;
if those no longer match what would commit, nothing commits and the acceptor is
told. Traveler sees €35 then the Deal freezes €30 is not a reachable state, and
neither is the reverse.

**The old fields keep their meaning.** `traveler_reward_minor` is still the base
reward and `sender_total_minor` is still base reward plus base commission.

**Nothing is invented.** An offer that was countered, declined, withdrawn or
expired never had a Boost recorded on it, so it publishes none.

J2 economics are unchanged: acceptance still freezes the same `DealTermsSnapshot`
and still creates the same balance order. `apps/boosts/tests/test_j2_boost.py`
and the H5 regression are the gate for that.
"""

from __future__ import annotations

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from apps.boosts.services import set_boost_intent
from apps.boosts.tests.test_boosts import legacy_purchase
from apps.boosts.tests.test_j2_boost import set_boost_commission
from apps.deals.models import Deal
from apps.deals.tests.phase4_factories import enable_mock_rail
from apps.finance.tests.factories import build_scenario, pay_order_with_mock
from apps.matching.models import Match, Offer
from apps.matching.offer_economics import OfferEconomicsReader, PROJECTION_FIELDS
from apps.parcels.models import DeliveryRequest, ParcelRequest

TERMS_FIELDS = (
    "boost_amount_minor",
    "boost_traveler_bonus_minor",
    "boost_platform_fee_minor",
    "traveler_total_minor",
    "sender_total_with_boost_minor",
)


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def set_boost(scenario, amount: int) -> None:
    set_boost_intent(
        delivery_request_id=scenario.delivery_request.pk,
        actor_id=scenario.sender.pk,
        amount_eur_cents=amount,
    )


def propose(scenario, reward: int = 2_000) -> dict:
    response = client_for(scenario.sender).post(
        reverse("matches-propose-v1"),
        {
            "parcel_id": scenario.delivery_request.pk,
            "journey_id": scenario.journey.pk,
            "start_leg_id": scenario.leg.pk,
            "end_leg_id": scenario.leg.pk,
            "traveler_reward_eur_cents": reward,
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    return response.data


def latest_offer(user, match_id: int) -> dict:
    response = client_for(user).get(reverse("matches-detail", args=[match_id]))
    assert response.status_code == 200, response.data
    return response.data["latest_offer"]


def accept(user, offer_id: int, **shown):
    return client_for(user).post(
        reverse("offers-accept", args=[offer_id]), shown, format="json"
    )


def projection(offer: dict) -> dict:
    return {field: offer[field] for field in PROJECTION_FIELDS}


def confirmed(offer: dict) -> dict:
    return {
        "traveler_total_minor": offer["traveler_total_minor"],
        "sender_total_with_boost_minor": offer["sender_total_with_boost_minor"],
    }


class OfferProjectionContractTests(TestCase):
    def test_zero_boost_total_is_the_base_and_old_fields_keep_their_meaning(self):
        scenario = build_scenario(prefix="j61z")
        offer = propose(scenario)

        assert offer["traveler_reward_minor"] == 2_000
        assert offer["platform_fee_minor"] == 500
        assert offer["sender_total_minor"] == 2_500
        assert projection(offer) == {
            "boost_terms_status": "provisional",
            "boost_economics_version": "additive_commission_v2",
            "boost_amount_minor": 0,
            "boost_traveler_bonus_minor": 0,
            "boost_platform_fee_minor": 0,
            "traveler_total_minor": 2_000,
            "sender_total_with_boost_minor": 2_500,
        }

    def test_a_boost_is_published_identically_to_both_parties_and_no_one_else(self):
        scenario = build_scenario(prefix="j61p")
        set_boost(scenario, 800)
        # What the propose sheet shows before anything is sent: the Find
        # Travelers envelope's total for the request's own chosen reward.
        envelope = client_for(scenario.sender).get(
            reverse("matches-find-travelers-v1"),
            {"parcel_id": scenario.delivery_request.pk},
        )
        assert envelope.status_code == 200, envelope.data
        sheet = envelope.data["request"]
        assert sheet["chosen_reward_eur_cents"] == 2_000
        assert sheet["boost_eur_cents"] == 800

        proposed = propose(scenario, reward=sheet["chosen_reward_eur_cents"])
        match_id = proposed["match"]
        # Proposal screen -> submitted offer: one number.
        assert proposed["traveler_total_minor"] == sheet["total_offered_reward_eur_cents"]

        expected = {
            "boost_terms_status": "provisional",
            "boost_economics_version": "additive_commission_v2",
            "boost_amount_minor": 800,
            "boost_traveler_bonus_minor": 800,
            "boost_platform_fee_minor": 200,
            # base 2000 + the whole Boost
            "traveler_total_minor": 2_800,
            # base 2000 + base fee 500 + Boost 800 + Boost fee 200
            "sender_total_with_boost_minor": 3_500,
        }
        assert projection(proposed) == expected
        # The base fields are untouched by the Boost.
        assert proposed["traveler_reward_minor"] == 2_000
        assert proposed["sender_total_minor"] == 2_500

        for party in (scenario.sender, scenario.traveler):
            assert projection(latest_offer(party, match_id)) == expected
            listed = client_for(party).get(reverse("matches-offers", args=[match_id]))
            assert listed.status_code == 200
            assert projection(listed.data[0]) == expected
            matches = client_for(party).get(reverse("matches-list"))
            assert projection(matches.data[0]["latest_offer"]) == expected

        outsider = client_for(scenario.outsider)
        assert (
            outsider.get(reverse("matches-detail", args=[match_id])).status_code
            == 403
        )
        assert (
            outsider.get(reverse("matches-offers", args=[match_id])).status_code
            == 403
        )
        assert outsider.get(reverse("matches-list")).data == []
        assert accept(scenario.outsider, proposed["id"]).status_code == 403
        assert not Deal.objects.exists()


class OfferProjectionLifecycleTests(TestCase):
    def test_the_total_follows_a_boost_edit_until_acceptance_freezes_it(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="j61l")
        set_boost(scenario, 800)
        match_id = propose(scenario)["match"]
        assert latest_offer(scenario.traveler, match_id)["traveler_total_minor"] == 2_800

        # Provisional means exactly this: the sender's Boost is still theirs.
        set_boost(scenario, 500)
        shown = latest_offer(scenario.traveler, match_id)
        assert shown["boost_terms_status"] == "provisional"
        assert shown["traveler_total_minor"] == 2_500
        assert shown["sender_total_with_boost_minor"] == 3_125

        response = accept(scenario.traveler, shown["id"], **confirmed(shown))
        assert response.status_code == 201, response.data
        deal = Deal.objects.get(pk=response.data["id"])
        terms = deal.terms
        assert terms.boost_amount_minor == 500
        assert terms.traveler_total_minor == 2_500
        assert terms.sender_total_with_boost_minor == 3_125
        assert scenario_balance(deal) == 3_125

        frozen = latest_offer(scenario.traveler, match_id)
        assert frozen["boost_terms_status"] == "frozen"
        # The accepted offer and the Deal it became state one set of numbers.
        for field in TERMS_FIELDS:
            assert frozen[field] == response.data["terms"][field], field
        assert projection(frozen) == projection(
            latest_offer(scenario.sender, match_id)
        )

        # Funding clears the request's Boost column. The accepted offer still
        # reads its Deal, never the request.
        pay_order_with_mock(self.client, deal_balance_order(deal))
        scenario.delivery_request.refresh_from_db()
        assert scenario.delivery_request.boost_eur_cents == 0
        after_funding = latest_offer(scenario.traveler, match_id)
        assert after_funding["boost_amount_minor"] == 500
        assert after_funding["traveler_total_minor"] == 2_500

    def test_a_boost_cut_after_the_read_refuses_and_commits_nothing(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="j61r")
        set_boost(scenario, 800)
        match_id = propose(scenario)["match"]
        shown = latest_offer(scenario.traveler, match_id)
        assert shown["traveler_total_minor"] == 2_800

        set_boost(scenario, 0)
        refused = accept(scenario.traveler, shown["id"], **confirmed(shown))
        assert refused.status_code == 409, refused.data
        assert refused.data["code"] == "offer_economics_changed"
        assert refused.data["current_economics"]["traveler_total_minor"] == 2_000

        # Nothing committed: no Deal, request still open, Boost still editable.
        assert not Deal.objects.exists()
        scenario.delivery_request.refresh_from_db()
        assert scenario.delivery_request.status == ParcelRequest.Status.OPEN
        assert Offer.objects.get(pk=shown["id"]).status == Offer.Status.PENDING
        set_boost(scenario, 0)

        reread = latest_offer(scenario.traveler, match_id)
        assert reread["traveler_total_minor"] == 2_000
        response = accept(scenario.traveler, reread["id"], **confirmed(reread))
        assert response.status_code == 201, response.data
        assert Deal.objects.get().terms.traveler_total_minor == 2_000

    def test_a_boost_added_after_the_read_refuses_the_other_way_too(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="j61a")
        match_id = propose(scenario)["match"]
        shown = latest_offer(scenario.traveler, match_id)
        assert shown["traveler_total_minor"] == 2_000

        set_boost(scenario, 500)
        refused = accept(scenario.traveler, shown["id"], **confirmed(shown))
        assert refused.status_code == 409, refused.data
        assert refused.data["code"] == "offer_economics_changed"
        assert not Deal.objects.exists()

    def test_a_commission_change_is_caught_on_the_sender_total(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="j61c")
        set_boost(scenario, 800)
        match_id = propose(scenario)["match"]
        shown = latest_offer(scenario.traveler, match_id)
        assert shown["sender_total_with_boost_minor"] == 3_500

        set_boost_commission(1_000)
        refused = accept(scenario.traveler, shown["id"], **confirmed(shown))
        assert refused.status_code == 409
        assert refused.data["code"] == "offer_economics_changed"
        assert refused.data["current_economics"]["sender_total_with_boost_minor"] == (
            3_380
        )

        reread = latest_offer(scenario.traveler, match_id)
        response = accept(scenario.traveler, reread["id"], **confirmed(reread))
        assert response.status_code == 201, response.data
        assert response.data["terms"]["sender_total_with_boost_minor"] == 3_380

    def test_an_unconfirmed_accept_works_without_a_boost_but_not_with_one(self):
        enable_mock_rail()
        plain = build_scenario(prefix="j61n")
        plain_match = propose(plain)["match"]
        plain_offer = latest_offer(plain.traveler, plain_match)
        # A client that predates J6.1 rendered the base reward, which is the
        # whole reward when there is no Boost. It keeps working.
        first = accept(plain.traveler, plain_offer["id"])
        assert first.status_code == 201, first.data
        # An idempotent replay returns the same Deal, whatever it echoes.
        replay = accept(plain.traveler, plain_offer["id"], traveler_total_minor=1)
        assert replay.status_code == 200
        assert replay.data["id"] == first.data["id"]

        boosted = build_scenario(prefix="j61b")
        set_boost(boosted, 800)
        boosted_match = propose(boosted)["match"]
        boosted_offer = latest_offer(boosted.traveler, boosted_match)
        # The same client would have shown €20.00 for an offer that pays €28.00.
        refused = accept(boosted.traveler, boosted_offer["id"])
        assert refused.status_code == 409, refused.data
        assert refused.data["code"] == "offer_economics_confirmation_required"
        assert refused.data["current_economics"]["traveler_total_minor"] == 2_800
        assert not Deal.objects.filter(delivery_request=boosted.delivery_request)

        invalid = accept(boosted.traveler, boosted_offer["id"], traveler_total_minor=-1)
        assert invalid.status_code == 400

    def test_a_sender_accepting_a_counter_confirms_the_same_totals(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="j61k")
        set_boost(scenario, 800)
        proposed = propose(scenario)
        counter = client_for(scenario.traveler).post(
            reverse("offers-counter-v1", args=[proposed["id"]]),
            {"traveler_reward_eur_cents": 2_400},
            format="json",
        )
        assert counter.status_code == 201, counter.data
        assert counter.data["traveler_reward_minor"] == 2_400
        assert counter.data["traveler_total_minor"] == 3_200
        # base 2400 + fee 600 + Boost 800 + Boost fee 200
        assert counter.data["sender_total_with_boost_minor"] == 4_000

        shown = latest_offer(scenario.sender, proposed["match"])
        assert projection(shown) == projection(counter.data)
        response = accept(scenario.sender, shown["id"], **confirmed(shown))
        assert response.status_code == 201, response.data
        for field in TERMS_FIELDS:
            assert response.data["terms"][field] == shown[field], field


class HistoricalOfferProjectionTests(TestCase):
    def test_closed_offers_publish_no_invented_boost(self):
        scenario = build_scenario(prefix="j61h")
        set_boost(scenario, 800)
        proposed = propose(scenario)
        client_for(scenario.traveler).post(
            reverse("offers-counter-v1", args=[proposed["id"]]),
            {"traveler_reward_eur_cents": 2_400},
            format="json",
        )
        offers = client_for(scenario.sender).get(
            reverse("matches-offers", args=[proposed["match"]])
        ).data
        countered = next(row for row in offers if row["id"] == proposed["id"])
        assert countered["status"] == "countered"
        assert countered["boost_terms_status"] == "unavailable"
        assert all(
            countered[field] is None
            for field in PROJECTION_FIELDS
            if field != "boost_terms_status"
        )
        # The base economics that were frozen on the row are still there.
        assert countered["traveler_reward_minor"] == 2_000
        assert countered["sender_total_minor"] == 2_500

        latest = next(row for row in offers if row["status"] == "pending")
        declined = client_for(scenario.sender).post(
            reverse("offers-decline", args=[latest["id"]]), format="json"
        )
        assert declined.status_code == 200, declined.data
        assert declined.data["boost_terms_status"] == "unavailable"
        assert declined.data["traveler_total_minor"] is None

    def test_a_legacy_dzd_offer_publishes_no_boost(self):
        scenario = build_scenario(prefix="j61d")
        offer = Offer(
            economics_version=Offer.EconomicsVersion.LEGACY_DZD,
            currency=Offer.Currency.DZD,
            status=Offer.Status.PENDING,
            base_amount_dzd=150_000,
        )
        match = Match(
            parcel=scenario.delivery_request.parcelrequest_ptr,
            status=Match.Status.PENDING,
        )
        result = OfferEconomicsReader().project(offer, match)
        assert result["boost_terms_status"] == "unavailable"
        assert result["traveler_total_minor"] is None

    def test_a_paid_legacy_package_is_projected_exactly_as_acceptance_binds_it(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="j61v")
        purchase = legacy_purchase(
            delivery_request=scenario.delivery_request,
            buyer=scenario.sender,
            amount_eur_cents=777,
        )
        pay_order_with_mock(self.client, purchase.payment_order)
        match_id = propose(scenario)["match"]

        shown = latest_offer(scenario.traveler, match_id)
        assert projection(shown) == {
            "boost_terms_status": "provisional",
            "boost_economics_version": "traveler_split_v1",
            "boost_amount_minor": 777,
            "boost_traveler_bonus_minor": 582,
            "boost_platform_fee_minor": 195,
            "traveler_total_minor": 2_582,
            # The package was paid on its own order, so the sender owed the
            # Boost and nothing on top of it.
            "sender_total_with_boost_minor": 3_277,
        }
        response = accept(scenario.traveler, shown["id"], **confirmed(shown))
        assert response.status_code == 201, response.data
        frozen = latest_offer(scenario.traveler, match_id)
        assert frozen["boost_terms_status"] == "frozen"
        for field in TERMS_FIELDS:
            assert frozen[field] == shown[field] == response.data["terms"][field]
        # J2 unchanged: the balance is the base sender total only.
        assert scenario_balance(Deal.objects.get(pk=response.data["id"])) == 2_500


class OfferProjectionQueryCostTests(TestCase):
    def test_the_match_list_projects_many_negotiations_at_constant_cost(self):
        scenario = build_scenario(prefix="j61q")
        set_boost(scenario, 800)
        propose(scenario)
        client = client_for(scenario.sender)
        client.get(reverse("matches-list"))
        with CaptureQueriesContext(connection) as one:
            assert len(client.get(reverse("matches-list")).data) == 1

        for index in range(3):
            request = copy_request(scenario.delivery_request)
            set_boost_intent(
                delivery_request_id=request.pk,
                actor_id=scenario.sender.pk,
                amount_eur_cents=500 + index,
            )
            scenario.delivery_request = request
            propose(scenario)
        with CaptureQueriesContext(connection) as four:
            listed = client.get(reverse("matches-list")).data
        assert len(listed) == 4
        assert {row["latest_offer"]["boost_amount_minor"] for row in listed} == {
            800,
            500,
            501,
            502,
        }
        assert len(four) == len(one), [q["sql"] for q in four.captured_queries]


def deal_balance_order(deal):
    from apps.finance.models import PaymentOrder

    return PaymentOrder.objects.get(
        deal=deal, purpose=PaymentOrder.Purpose.DEAL_BALANCE
    )


def scenario_balance(deal) -> int:
    return int(deal_balance_order(deal).amount_eur_cents)


def copy_request(source: DeliveryRequest) -> DeliveryRequest:
    """A second open request on the same corridor, for list-cost measurements."""

    values = {}
    for field in DeliveryRequest._meta.concrete_fields:
        if (
            field.primary_key
            or field.name == "parcelrequest_ptr"
            or getattr(field, "auto_now", False)
            or getattr(field, "auto_now_add", False)
        ):
            continue
        values[field.attname] = getattr(source, field.attname)
    values["boost_eur_cents"] = 0
    values["ranking_boost_weight"] = 0
    values["ranking_boost_expires_at"] = None
    return DeliveryRequest.objects.create(**values)
