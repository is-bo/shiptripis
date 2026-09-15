"""J2 pricing, the flexible deposit, and the universal guest payer.

Three claims, each of which the owner can check on a screen:

**A sender sees three distinct numbers before they choose.** The minimum the
platform enforces, the recommendation ShipTrip makes, and whatever they pick.
The recommendation is advice in both directions; the minimum is a floor the
server owns, because a client that computed it would be a client that could be
edited.

**A deposit is a choice inside a band, not a fixed fee.** EUR 3 or more, up to
the obligation it is paid against, with no artificial EUR 7 ceiling. It is
credited once against the final balance and never charged twice.

**Any sender payment can be paid by someone else.** The posting deposit and the
deal balance both, through the same payment order, the same provider
verification, the same ledger and the same refund path. The only difference is
who is standing at the checkout -- and they get no Deal authority for it.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.boosts.services import set_boost_intent
from apps.core.business_settings import activate_business_settings
from apps.core.models import BusinessSettingsVersion
from apps.deals.tests.phase4_factories import enable_mock_rail
from apps.finance.models import (
    GuestPaymentLink,
    PaymentAttempt,
    PaymentOrder,
    PaymentRefund,
)
from apps.finance.services import (
    DepositAmountInvalid,
    DepositCheckoutInProgress,
    GuestCheckoutInProgress,
    NotAuthorized,
    create_guest_link,
    ensure_posting_deposit_order,
    maximum_chosen_deposit,
    quote_posting_deposit,
    resolve_guest_link,
    revoke_guest_link,
)
from apps.finance.policy import phase3_policy
from apps.finance.settlement import assert_deal_reconciles
from apps.finance.tests.factories import (
    build_scenario,
    deliver_mock_webhook,
    open_mock_checkout,
    pay_order_with_mock,
    succeed_attempt,
)
from apps.matching.posting_pricing import (
    PriceBelowPostingMinimum,
    assert_chosen_price_allowed,
    quote_posting_price,
)
from apps.parcels.models import DeliveryRequest


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def set_deposit_policy(**overrides) -> BusinessSettingsVersion:
    """Activate a revision with a different posting-deposit configuration."""

    active = BusinessSettingsVersion.objects.get(status="active")
    policy = deepcopy(active.policy)
    policy["payments"]["posting_deposit"].update(overrides)
    revision = BusinessSettingsVersion.objects.create(
        version=active.version + 1,
        status=BusinessSettingsVersion.Status.DRAFT,
        commission_rate_bps=active.commission_rate_bps,
        pricing_version=active.pricing_version,
        policy=policy,
    )
    return activate_business_settings(revision)


# --- pricing ------------------------------------------------------------------


class PostingPriceTests(TestCase):
    def test_three_distinct_values_are_priced_without_a_journey(self):
        scenario = build_scenario(prefix="j2p1")
        quote = quote_posting_price(
            delivery_request=scenario.delivery_request,
            chosen_reward_eur_cents=2_000,
        )
        payload = quote.as_dict()

        assert payload["minimum_reward_eur_cents"] > 0
        assert (
            payload["recommended_reward_eur_cents"]
            >= payload["minimum_reward_eur_cents"]
        )
        assert payload["chosen_reward_eur_cents"] == 2_000
        # Each value arrives with its own economics, so no client adds anything.
        for key in ("minimum_economics", "recommended_economics", "chosen_economics"):
            assert payload[key]["sender_total_minor"] == (
                payload[key]["traveler_reward_minor"]
                + payload[key]["platform_fee_minor"]
            )
        # The estimate says how it was derived without publishing a distance
        # measured from the sender's own private endpoints.
        assert payload["estimate_method"].startswith("posting_estimate:")
        assert "estimate_distance_meters" not in payload

    def test_a_chosen_price_may_sit_anywhere_at_or_above_the_minimum(self):
        scenario = build_scenario(prefix="j2p2")
        quote = quote_posting_price(delivery_request=scenario.delivery_request)
        minimum = quote.minimum_reward_eur_cents
        recommended = quote.recommended_reward_eur_cents
        assert recommended > minimum

        # At the minimum, below the recommendation, and far above it: all fine.
        for chosen in (minimum, recommended - 1, recommended, recommended * 10):
            assert_chosen_price_allowed(quote=quote, chosen_reward_eur_cents=chosen)

        with self.assertRaises(PriceBelowPostingMinimum) as caught:
            assert_chosen_price_allowed(
                quote=quote, chosen_reward_eur_cents=minimum - 1
            )
        assert caught.exception.code == "price_below_minimum"
        assert caught.exception.details()["minimum_reward_eur_cents"] == minimum

    def test_the_request_pricing_endpoint_is_owner_only(self):
        scenario = build_scenario(prefix="j2p3")
        url = reverse("parcels-pricing", args=[scenario.delivery_request.pk])

        assert APIClient().get(url).status_code == 401
        assert client_for(scenario.outsider).get(url).status_code == 403
        assert client_for(scenario.traveler).get(url).status_code == 403

        res = client_for(scenario.sender).get(url)
        assert res.status_code == 200, res.data
        assert res.data["chosen_reward_eur_cents"] == 2_000
        assert res.data["chosen_is_below_minimum"] is False
        assert res.data["deposit"]["is_flexible"] is True


# --- deposit ------------------------------------------------------------------


class FlexibleDepositTests(TestCase):
    def test_the_recommendation_is_a_tenth_of_the_recommended_total_in_band(self):
        scenario = build_scenario(prefix="j2d1")
        quote = quote_posting_deposit(delivery_request=scenario.delivery_request)
        policy = phase3_policy()

        basis = quote.estimated_sender_total_eur_cents
        raw = basis * policy.posting_deposit.percent_bps // 10_000
        expected = min(
            max(raw, policy.posting_deposit.min_eur_cents),
            policy.posting_deposit.max_eur_cents,
        )
        assert quote.amount_eur_cents == expected
        assert 300 <= quote.amount_eur_cents <= 700
        # The floor a sender is held to is stated apart from the band the
        # recommendation was clamped into.
        assert quote.min_eur_cents == policy.posting_deposit.chosen_min_eur_cents == 300

        # A EUR 50 recommended total gives a EUR 5 recommended deposit.
        quote_50 = quote_posting_price(delivery_request=scenario.delivery_request)
        if quote_50.recommended_economics["sender_total_minor"] == 5_000:
            assert quote.amount_eur_cents == 500

    def test_the_sender_may_choose_three_euros_or_far_more_than_seven(self):
        scenario = build_scenario(prefix="j2d2", open_request=False)
        request = scenario.delivery_request
        ceiling = maximum_chosen_deposit(
            delivery_request=request, policy=phase3_policy()
        )
        assert ceiling == 2_500  # EUR 20 reward + 25% commission

        for chosen in (300, 500, 700, 1_000, 2_000, ceiling):
            order = ensure_posting_deposit_order(
                delivery_request=request, chosen_amount_eur_cents=chosen
            )
            assert order.amount_eur_cents == chosen, chosen
            snapshot = order.terms_snapshot["posting_deposit_inputs"]
            assert snapshot["chosen_deposit_eur_cents"] == chosen
            assert snapshot["chosen_by_sender"] is True
            assert snapshot["remaining_after_deposit_eur_cents"] == ceiling - chosen
            # One live obligation throughout: repricing, never a second deposit.
            assert (
                PaymentOrder.objects.filter(
                    delivery_request_id=request.pk,
                    purpose=PaymentOrder.Purpose.POSTING_DEPOSIT,
                )
                .exclude(status=PaymentOrder.Status.CANCELLED)
                .count()
                == 1
            )

    def test_a_deposit_below_the_floor_or_above_the_obligation_is_refused(self):
        scenario = build_scenario(prefix="j2d3", open_request=False)
        request = scenario.delivery_request
        ceiling = maximum_chosen_deposit(
            delivery_request=request, policy=phase3_policy()
        )

        with self.assertRaises(DepositAmountInvalid) as low:
            ensure_posting_deposit_order(
                delivery_request=request, chosen_amount_eur_cents=299
            )
        assert low.exception.code == "deposit_below_minimum"
        assert low.exception.details()["minimum_eur_cents"] == 300

        with self.assertRaises(DepositAmountInvalid) as high:
            ensure_posting_deposit_order(
                delivery_request=request, chosen_amount_eur_cents=ceiling + 1
            )
        assert high.exception.code == "deposit_above_obligation"
        assert high.exception.details()["maximum_eur_cents"] == ceiling

    def test_the_obligation_ceiling_grows_with_the_boost(self):
        scenario = build_scenario(prefix="j2d4", open_request=False)
        request = scenario.delivery_request
        policy = phase3_policy()
        assert maximum_chosen_deposit(delivery_request=request, policy=policy) == 2_500

        set_boost_intent(
            delivery_request_id=request.pk,
            actor_id=scenario.sender.pk,
            amount_eur_cents=800,
        )
        request.refresh_from_db()
        # Boost 800 plus its own 25% commission.
        assert (
            maximum_chosen_deposit(delivery_request=request, policy=policy) == 3_500
        )

    def test_the_recommendation_does_not_move_when_a_boost_is_added(self):
        """Boost is optional extra reward; it must not jiggle the default."""

        scenario = build_scenario(prefix="j2d5", open_request=False)
        request = scenario.delivery_request
        before = quote_posting_deposit(delivery_request=request).amount_eur_cents

        set_boost_intent(
            delivery_request_id=request.pk,
            actor_id=scenario.sender.pk,
            amount_eur_cents=5_000,
        )
        request.refresh_from_db()
        after = quote_posting_deposit(delivery_request=request).amount_eur_cents
        assert before == after

    def test_a_deposit_cannot_be_repriced_once_money_or_a_checkout_is_involved(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="j2d6", open_request=False)
        request = scenario.delivery_request
        order = ensure_posting_deposit_order(
            delivery_request=request, chosen_amount_eur_cents=500
        )
        open_mock_checkout(order)

        # The provider was asked for a specific amount; changing the obligation
        # underneath that session would collect the wrong number.
        with self.assertRaises(DepositCheckoutInProgress):
            ensure_posting_deposit_order(
                delivery_request=request, chosen_amount_eur_cents=900
            )

    def test_the_deposit_is_credited_exactly_once_into_the_final_balance(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="j2d7", open_request=False)
        request = scenario.delivery_request
        deposit = ensure_posting_deposit_order(
            delivery_request=request, chosen_amount_eur_cents=1_000
        )
        pay_order_with_mock(self.client, deposit)
        request.refresh_from_db()
        assert request.status == "open"

        deal = scenario.accept(reward_eur_cents=2_000)
        balance = scenario.balance_order()
        assert balance.amount_eur_cents == 2_500
        assert balance.credited_eur_cents == 1_000
        assert balance.outstanding_eur_cents == 1_500

        pay_order_with_mock(self.client, balance)
        balance.refresh_from_db()
        assert balance.status == PaymentOrder.Status.PAID
        assert balance.paid_eur_cents == 1_500
        # Never twice: the credit link is one-to-one and re-applying is a no-op.
        from apps.finance.services import apply_posting_deposit_credit

        assert apply_posting_deposit_credit(order=balance, deal=deal) == 1_000
        balance.refresh_from_db()
        assert balance.credited_eur_cents == 1_000
        assert assert_deal_reconciles(deal.pk)["net"] == 0

    def test_a_deposit_at_the_full_obligation_leaves_nothing_to_collect(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="j2d8", open_request=False)
        request = scenario.delivery_request
        deposit = ensure_posting_deposit_order(
            delivery_request=request, chosen_amount_eur_cents=2_500
        )
        pay_order_with_mock(self.client, deposit)
        request.refresh_from_db()

        deal = scenario.accept(reward_eur_cents=2_000)
        balance = scenario.balance_order()
        assert balance.credited_eur_cents == 2_500
        assert balance.outstanding_eur_cents == 0
        # A fully credited balance funds the Deal without a second charge.
        deal.refresh_from_db()
        assert deal.status == "funded"
        assert assert_deal_reconciles(deal.pk)["net"] == 0

    def test_the_deposit_endpoint_carries_the_band_and_the_sender_choice(self):
        scenario = build_scenario(prefix="j2d9", open_request=False)
        sender = client_for(scenario.sender)
        url = reverse(
            "finance-posting-deposit", args=[scenario.delivery_request.pk]
        )

        res = sender.get(url)
        assert res.status_code == 200, res.data
        quote = res.data["quote"]
        assert quote["minimum_eur_cents"] == 300
        assert quote["maximum_eur_cents"] == 2_500
        assert quote["recommended_eur_cents"] == quote["amount_eur_cents"]
        assert quote["is_flexible"] is True

        created = sender.post(url, {"amount_eur_cents": 1_200}, format="json")
        assert created.status_code == 201, created.data
        assert created.data["amount_eur_cents"] == 1_200
        assert created.data["quote"]["chosen_eur_cents"] == 1_200

        refused = sender.post(url, {"amount_eur_cents": 100}, format="json")
        assert refused.status_code == 409, refused.data
        assert refused.data["code"] == "deposit_below_minimum"


# --- guest payer --------------------------------------------------------------


class GuestPayerTests(TestCase):
    def _link(self, order, actor):
        return create_guest_link(order_id=order.pk, actor_id=actor.pk)

    def test_a_guest_can_pay_a_posting_deposit_through_the_same_rails(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="j2g1", open_request=False)
        deposit = ensure_posting_deposit_order(
            delivery_request=scenario.delivery_request,
            chosen_amount_eur_cents=500,
        )
        issued = self._link(deposit, scenario.sender)
        assert issued.url.endswith(f"/pay/guest/{issued.token}")
        assert issued.reissued is False

        attempt = pay_order_with_mock(
            self.client,
            deposit,
            actor_id=None,
            guest_link=issued.link,
            guest_email="dad@example.com",
        )
        deposit.refresh_from_db()
        scenario.delivery_request.refresh_from_db()

        assert attempt.guest_link_id == issued.link.pk
        assert attempt.payer_id is None
        assert deposit.status == PaymentOrder.Status.PAID
        # Publication is the effect of the reconciled payment, whoever paid.
        assert scenario.delivery_request.status == "open"
        issued.link.refresh_from_db()
        assert issued.link.consumed_at is not None

    def test_a_guest_can_pay_a_deal_balance_and_gains_no_deal_authority(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="j2g2")
        deal = scenario.accept(reward_eur_cents=2_000)
        balance = scenario.balance_order()
        issued = self._link(balance, scenario.sender)

        payload = APIClient().get(
            reverse("finance-guest-payment", args=[issued.token])
        )
        assert payload.status_code == 200, payload.data
        # The entire payload a guest is entitled to.
        assert payload.data["amount_eur_cents"] == 2_500
        assert payload.data["purpose"] == "deal_balance"
        assert set(payload.data) == {
            "amount_eur_cents",
            "currency",
            "purpose",
            "description",
            "expires_at",
            "providers",
        }

        pay_order_with_mock(
            self.client,
            balance,
            actor_id=None,
            guest_link=issued.link,
            guest_email="aunt@example.com",
        )
        deal.refresh_from_db()
        assert deal.status == "funded"
        assert assert_deal_reconciles(deal.pk)["net"] == 0

        # The guest is not a party. Holding the token opens nothing else.
        anon = APIClient()
        assert anon.get(reverse("finance-deal-payment", args=[deal.pk])).status_code in (
            401,
            403,
        )
        assert anon.get(reverse("deals-detail", args=[deal.pk])).status_code in (
            401,
            403,
            404,
        )

    def test_an_expired_revoked_or_paid_link_all_fail_the_same_way(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="j2g3")
        scenario.accept(reward_eur_cents=2_000)
        balance = scenario.balance_order()

        expired = self._link(balance, scenario.sender)
        GuestPaymentLink.objects.filter(pk=expired.link.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        revoked = self._link(balance, scenario.sender)
        revoke_guest_link(order_id=balance.pk, actor_id=scenario.sender.pk)
        unknown = "not-a-real-token"

        anon = APIClient()
        for token in (expired.token, revoked.token, unknown):
            res = anon.get(reverse("finance-guest-payment", args=[token]))
            assert res.status_code == 404, token
            assert res.data["code"] == "guest_link_invalid"
            assert res.data["detail"] == "This payment link is not valid."

        # Once paid, the live link stops resolving too.
        live = self._link(balance, scenario.sender)
        pay_order_with_mock(
            self.client,
            balance,
            actor_id=None,
            guest_link=live.link,
            guest_email="uncle@example.com",
        )
        assert (
            anon.get(reverse("finance-guest-payment", args=[live.token])).status_code
            == 404
        )

    def test_only_the_owner_may_issue_or_revoke_a_link(self):
        scenario = build_scenario(prefix="j2g4")
        scenario.accept(reward_eur_cents=2_000)
        balance = scenario.balance_order()

        for stranger in (scenario.traveler, scenario.outsider):
            with self.assertRaises(NotAuthorized):
                create_guest_link(order_id=balance.pk, actor_id=stranger.pk)
            with self.assertRaises(NotAuthorized):
                revoke_guest_link(order_id=balance.pk, actor_id=stranger.pk)

    def test_reissuing_retires_the_previous_link_and_says_so(self):
        scenario = build_scenario(prefix="j2g5")
        scenario.accept(reward_eur_cents=2_000)
        balance = scenario.balance_order()

        first = self._link(balance, scenario.sender)
        second = self._link(balance, scenario.sender)
        assert second.reissued is True

        first.link.refresh_from_db()
        assert first.link.revoked_at is not None
        with self.assertRaises(Exception):
            resolve_guest_link(first.token)
        assert resolve_guest_link(second.token).pk == second.link.pk
        # Exactly one live capability per obligation, always.
        assert (
            GuestPaymentLink.objects.filter(
                order=balance, revoked_at__isnull=True, consumed_at__isnull=True
            ).count()
            == 1
        )

    def test_a_link_cannot_be_replaced_out_from_under_a_payer_mid_checkout(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="j2g6")
        scenario.accept(reward_eur_cents=2_000)
        balance = scenario.balance_order()
        issued = self._link(balance, scenario.sender)
        open_mock_checkout(
            balance,
            actor_id=None,
            guest_link=issued.link,
            guest_email="cousin@example.com",
        )

        with self.assertRaises(GuestCheckoutInProgress):
            create_guest_link(order_id=balance.pk, actor_id=scenario.sender.pk)

        # Revoking is still the owner's escape hatch.
        assert revoke_guest_link(order_id=balance.pk, actor_id=scenario.sender.pk) == 1

    def test_two_payers_on_one_obligation_cannot_fund_it_twice(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="j2g7")
        deal = scenario.accept(reward_eur_cents=2_000)
        balance = scenario.balance_order()
        issued = self._link(balance, scenario.sender)

        # A guest opens a checkout, then the sender opens their own. Only one
        # attempt may be open per obligation, so the first is superseded.
        guest_attempt = open_mock_checkout(
            balance,
            actor_id=None,
            guest_link=issued.link,
            guest_email="friend@example.com",
        )
        sender_attempt = open_mock_checkout(balance, actor_id=scenario.sender.pk)
        guest_attempt.refresh_from_db()
        assert guest_attempt.status == PaymentAttempt.Status.CANCELLED
        assert guest_attempt.failure_code == "superseded"

        # Both providers report success anyway. The obligation absorbs one; the
        # other is recorded honestly as unapplied and refunded in full.
        assert (
            deliver_mock_webhook(
                self.client, succeed_attempt(sender_attempt)
            ).status_code
            == 200
        )
        assert (
            deliver_mock_webhook(
                self.client, succeed_attempt(guest_attempt)
            ).status_code
            == 200
        )

        balance.refresh_from_db()
        assert balance.paid_eur_cents == 2_500
        unapplied = PaymentAttempt.objects.filter(order=balance, is_unapplied=True)
        assert unapplied.count() == 1
        assert PaymentRefund.objects.filter(
            order=balance, reason=PaymentRefund.Reason.UNAPPLIED_PAYMENT
        ).exists()
        deal.refresh_from_db()
        assert deal.status == "funded"
        assert assert_deal_reconciles(deal.pk)["net"] == 0

    def test_the_shared_page_pays_without_a_login_and_hides_everything_else(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="j2g8", open_request=False)
        deposit = ensure_posting_deposit_order(
            delivery_request=scenario.delivery_request,
            chosen_amount_eur_cents=500,
        )
        issued = create_guest_link(order_id=deposit.pk, actor_id=scenario.sender.pk)

        anon = APIClient()
        page = anon.get(f"/pay/guest/{issued.token}")
        assert page.status_code == 200
        body = page.content.decode()
        assert "5" in body
        for secret in (
            scenario.sender.email,
            scenario.traveler.email,
            str(deposit.public_reference),
            str(scenario.delivery_request.pk),
        ):
            assert secret not in body, secret

        gone = anon.get("/pay/guest/definitely-not-a-token")
        assert gone.status_code == 404
        assert "no longer works" in gone.content.decode()

    def test_the_shared_page_hands_the_payer_to_the_provider(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="j2g9", open_request=False)
        deposit = ensure_posting_deposit_order(
            delivery_request=scenario.delivery_request,
            chosen_amount_eur_cents=500,
        )
        issued = create_guest_link(order_id=deposit.pk, actor_id=scenario.sender.pk)

        posted = APIClient().post(
            f"/pay/guest/{issued.token}",
            {"provider": "mock", "email": "neighbour@example.com"},
        )

        assert posted.status_code == 302, posted
        attempt = PaymentAttempt.objects.get(order=deposit)
        assert posted["Location"] == attempt.checkout_url
        # The page starts exactly the same kind of attempt the app does, on the
        # same obligation, with no amount the payer could have influenced.
        assert attempt.guest_link_id == issued.link.pk
        assert attempt.payer_id is None
        assert attempt.amount_eur_cents == 500

        # A rail the page did not offer is refused rather than passed through.
        refused = APIClient().post(
            f"/pay/guest/{issued.token}",
            {"provider": "stripe", "email": "neighbour@example.com"},
        )
        assert refused.status_code == 404


# --- the J3 success contract --------------------------------------------------


class PaymentSettlementContractTests(TestCase):
    def test_the_order_states_what_happened_without_naming_the_guest(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="j2s1", open_request=False)
        deposit = ensure_posting_deposit_order(
            delivery_request=scenario.delivery_request,
            chosen_amount_eur_cents=1_000,
        )
        issued = create_guest_link(order_id=deposit.pk, actor_id=scenario.sender.pk)
        pay_order_with_mock(
            self.client,
            deposit,
            actor_id=None,
            guest_link=issued.link,
            guest_email="dad@example.com",
        )
        scenario.delivery_request.refresh_from_db()
        deal = scenario.accept(reward_eur_cents=2_000)
        balance = scenario.balance_order()

        sender = client_for(scenario.sender)
        res = sender.get(
            reverse("finance-order-detail", args=[balance.public_reference])
        )
        assert res.status_code == 200, res.data
        settlement = res.data["settlement"]
        assert settlement["is_settled"] is False
        assert settlement["amount_eur_cents"] == 2_500
        assert settlement["deposit_credited_eur_cents"] == 1_000
        assert settlement["remaining_eur_cents"] == 1_500
        assert settlement["deal_id"] == deal.pk
        assert settlement["next_step"] == "pay_deal_balance"

        pay_order_with_mock(self.client, balance)
        res = sender.get(
            reverse("finance-order-detail", args=[balance.public_reference])
        )
        settlement = res.data["settlement"]
        assert settlement["is_settled"] is True
        assert settlement["remaining_eur_cents"] == 0
        assert settlement["paid_by"] == "self"
        assert settlement["next_step"] == "await_pickup"

        # The deposit says a guest paid it, and does not say which guest.
        res = sender.get(
            reverse("finance-order-detail", args=[deposit.public_reference])
        )
        assert res.data["settlement"]["paid_by"] == "guest"
        assert "dad@example.com" not in str(res.data["settlement"])


# --- posting a request end to end --------------------------------------------


class PostingContractTests(TestCase):
    def test_posting_below_the_minimum_is_refused_and_writes_nothing(self):
        """The floor is the server's, whatever the posting screen showed."""

        scenario = build_scenario(prefix="j2c1")
        quote = quote_posting_price(delivery_request=scenario.delivery_request)
        before = DeliveryRequest.objects.count()

        # The service-level refusal is the one the create view raises; assert it
        # directly, because the V1 create route needs a staged photo and a
        # canonical place graph that this scenario deliberately does not build.
        with self.assertRaises(PriceBelowPostingMinimum):
            assert_chosen_price_allowed(
                quote=quote,
                chosen_reward_eur_cents=quote.minimum_reward_eur_cents - 1,
            )
        assert DeliveryRequest.objects.count() == before
