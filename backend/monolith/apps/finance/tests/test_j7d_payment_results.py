"""J7D: what a payer is told after a payment, on every surface ShipTrip owns.

**The provider return page reads the order, never the query string.** A
`result=success` on an unpaid order renders "We're confirming your payment",
re-checks itself a bounded number of times, then says it is taking longer --
it never says "Payment complete". Only an order the webhook has settled does.

**Every outcome has its own words.** Complete, already completed, confirming,
still confirming, not completed, cancelled, no longer active -- each in EN, FR
and AR, on the same shell as the guest page.

**The guest is never sent to an app they do not have**, and is told about a
receipt only when ShipTrip really is sending one.

**The settlement block names the payment that just happened**, so the app can
say "you paid €X" -- or "someone else paid €X" -- without doing arithmetic.
"""

from __future__ import annotations

import re
from copy import deepcopy
from html import unescape

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.business_settings import get_active_business_settings
from apps.core.models import BusinessSettingsVersion
from apps.finance.models import PaymentAttempt, PaymentOrder
from apps.finance.payment_return_web import RECHECK_DELAYS
from apps.finance.serializers import payment_settlement_payload
from apps.finance.services import (
    cancel_order,
    create_guest_link,
    ensure_posting_deposit_order,
    revoke_guest_link,
)
from apps.notifications.models import OutboundMessage

from .factories import (
    assert_page_withholds,
    build_scenario,
    open_mock_checkout,
    pay_order_with_mock,
    visible_page_text,
)


def _visible(html: str) -> str:
    """Visible text with entities decoded: Django escapes every apostrophe."""

    return unescape(visible_page_text(html))


def _enable_mock() -> None:
    settings_version = get_active_business_settings()
    policy = deepcopy(settings_version.policy)
    policy["payments"]["providers"]["mock_enabled"] = True
    BusinessSettingsVersion.objects.filter(pk=settings_version.pk).update(
        policy=policy
    )


class _BalanceCase(TestCase):
    """A Deal balance of EUR 25.00 owned by the sender, nothing paid yet."""

    prefix = "j7d"

    def setUp(self):
        cache.clear()
        _enable_mock()
        self.scenario = build_scenario(prefix=self.prefix)
        self.scenario.accept(reward_eur_cents=2_000)
        self.order = self.scenario.balance_order()
        self.url = f"/pay/{self.order.public_reference}/return"

    def page(self, **query):
        response = APIClient().get(self.url, query)
        return response, _visible(response.content.decode())

    def guest_link(self):
        issued = create_guest_link(
            order_id=self.order.pk, actor_id=self.scenario.sender.pk
        )
        return issued


# --- the settlement block ----------------------------------------------------------


class SettlementNamesTheLastPaymentTests(_BalanceCase):
    prefix = "j7d-settle"

    def test_nothing_paid_names_no_payment(self):
        block = payment_settlement_payload(self.order)
        assert block["last_payment_eur_cents"] is None
        assert block["last_paid_by"] is None

    def test_the_sender_paying_is_self_with_the_amount_just_paid(self):
        pay_order_with_mock(self.client, self.order)
        self.order.refresh_from_db()
        block = payment_settlement_payload(self.order)
        assert block["is_settled"] is True
        assert block["last_payment_eur_cents"] == 2_500
        assert block["last_paid_by"] == "self"
        assert block["remaining_eur_cents"] == 0

    def test_someone_else_paying_is_guest_and_names_nobody(self):
        issued = self.guest_link()
        pay_order_with_mock(
            self.client,
            self.order,
            actor_id=None,
            guest_link=issued.link,
            guest_email="payer@example.com",
        )
        self.order.refresh_from_db()
        block = payment_settlement_payload(self.order)
        assert block["last_paid_by"] == "guest"
        assert block["last_payment_eur_cents"] == 2_500
        assert "payer@example.com" not in str(block)

    def test_the_deal_payment_endpoint_serves_it(self):
        pay_order_with_mock(self.client, self.order)
        sender = APIClient()
        sender.force_authenticate(self.scenario.sender)
        res = sender.get(f"/api/deals/{self.scenario.deal.pk}/payment")
        assert res.status_code == 200
        settlement = res.data["order"]["settlement"]
        assert settlement["last_payment_eur_cents"] == 2_500
        assert settlement["last_paid_by"] == "self"


class DepositEndpointServesSettlementTests(TestCase):
    def setUp(self):
        cache.clear()
        _enable_mock()
        self.scenario = build_scenario(prefix="j7d-dep", open_request=False)
        self.deposit = ensure_posting_deposit_order(
            delivery_request=self.scenario.delivery_request
        )
        self.sender = APIClient()
        self.sender.force_authenticate(self.scenario.sender)
        self.url = f"/api/parcels/{self.scenario.delivery_request.pk}/posting-deposit"

    def test_a_paid_deposit_says_what_was_paid_and_publishes(self):
        before = self.sender.get(self.url).data["order"]["settlement"]
        assert before["is_settled"] is False
        assert before["next_step"] == "pay_posting_deposit"

        pay_order_with_mock(self.client, self.deposit)
        res = self.sender.get(self.url)
        assert res.status_code == 200
        order = res.data["order"]
        assert order["status"] == "paid"
        assert order["settlement"]["is_settled"] is True
        assert order["settlement"]["next_step"] == "await_offers"
        assert order["settlement"]["last_paid_by"] == "self"
        assert order["settlement"]["last_payment_eur_cents"] == int(
            self.deposit.amount_eur_cents
        )
        # The live obligation still rides beside it, so the app can say whether
        # this deposit covers the whole current total.
        assert res.data["quote"]["maximum_eur_cents"] >= int(
            self.deposit.amount_eur_cents
        )
        self.scenario.delivery_request.refresh_from_db()
        assert self.scenario.delivery_request.status == "open"


# --- the provider return page ------------------------------------------------------


class ReturnPageNeverTrustsTheRedirectTests(_BalanceCase):
    prefix = "j7d-trust"

    def test_a_forged_success_on_an_unpaid_order_is_never_complete(self):
        open_mock_checkout(self.order)
        for result in ("success", "anything", ""):
            response, text = self.page(result=result)
            assert response.status_code == 200
            assert "Payment complete" not in text
            assert "We're confirming your payment" in text

    def test_it_re_checks_on_a_backing_off_schedule_then_stops(self):
        open_mock_checkout(self.order)
        for check, delay in enumerate(RECHECK_DELAYS):
            response, text = self.page(result="success", check=check)
            html = response.content.decode()
            assert f'content="{delay};url=?result=success&amp;lang=en&amp;check={check + 1}"' in html
            assert "We're confirming your payment" in text
        response, text = self.page(result="success", check=len(RECHECK_DELAYS))
        html = response.content.decode()
        assert 'http-equiv="refresh"' not in html
        assert "Still confirming your payment" in text
        assert "You don't need to pay again" in text
        assert "Check again" in text
        # A manual check reads once more; it does not restart the schedule.
        assert f"check={len(RECHECK_DELAYS)}" in html
        assert sum(RECHECK_DELAYS) < 60

    def test_the_webhook_moves_it_to_complete(self):
        attempt = open_mock_checkout(self.order)
        _, text = self.page(result="success", check=2)
        assert "We're confirming your payment" in text
        from .factories import deliver_mock_webhook, succeed_attempt

        assert deliver_mock_webhook(self.client, succeed_attempt(attempt)).status_code == 200
        response, text = self.page(result="success", check=3)
        assert "Payment complete" in text
        assert "€25.00" in text
        assert 'http-equiv="refresh"' not in response.content.decode()


class ReturnPageOutcomesTests(_BalanceCase):
    prefix = "j7d-out"

    def test_the_app_payer_is_told_the_app_updates_by_itself(self):
        pay_order_with_mock(self.client, self.order)
        response, text = self.page(result="success")
        assert response.status_code == 200
        assert "Payment complete" in text
        assert "€25.00" in text
        assert "Payment for a delivery" in text
        assert "go back to the ShipTrip app" in text
        # One heading, no stacked synonyms.
        for duplicate in ("Payment successful", "Payment succeeded", "Success"):
            assert duplicate not in text
        assert "receipt" not in text

    def test_the_guest_is_never_sent_to_an_app(self):
        issued = self.guest_link()
        pay_order_with_mock(
            self.client, self.order, actor_id=None, guest_link=issued.link, guest_email=""
        )
        _, text = self.page(result="success")
        assert "Payment complete" in text
        assert "You can close this page." in text
        assert "ShipTrip app" not in text
        # Receipts are off in TEST: no promise of one.
        assert "receipt" not in text

    @override_settings(TRANSACTIONAL_EMAIL_ENABLED=True)
    def test_a_receipt_is_mentioned_only_when_one_is_really_on_its_way(self):
        issued = self.guest_link()
        attempt = pay_order_with_mock(
            self.client,
            self.order,
            actor_id=None,
            guest_link=issued.link,
            guest_email="payer@example.com",
        )
        receipt = OutboundMessage.objects.get(
            key=f"guest_payment:attempt:{attempt.pk}:succeeded"
        )
        _, text = self.page(result="success")
        assert "A receipt is on its way to your email." in text
        assert "payer@example.com" not in text

        receipt.status = OutboundMessage.Status.DISPATCHED
        receipt.dispatched_at = timezone.now()
        receipt.save(update_fields=["status", "dispatched_at"])
        _, text = self.page(result="success")
        assert "A receipt has been sent to your email." in text

        receipt.status = OutboundMessage.Status.FAILED
        receipt.dispatched_at = None
        receipt.save(update_fields=["status", "dispatched_at"])
        _, text = self.page(result="success")
        assert "receipt" not in text

    def test_coming_back_through_the_failure_door_after_payment_is_already_complete(self):
        pay_order_with_mock(self.client, self.order)
        _, text = self.page(result="failure")
        assert "This payment has already been completed" in text
        assert "Payment complete" not in text

    def test_a_declined_payment_says_nothing_was_charged(self):
        attempt = open_mock_checkout(self.order)
        PaymentAttempt.objects.filter(pk=attempt.pk).update(
            status=PaymentAttempt.Status.FAILED, failure_code="card_declined"
        )
        _, text = self.page(result="failure")
        assert "Payment wasn't completed" in text
        assert "nothing was charged" in text
        assert "card_declined" not in text
        assert "€25.00" in text  # still due
        assert "To try again, go back to the ShipTrip app." in text

    def test_a_cancelled_checkout_is_cancelled_not_failed(self):
        attempt = open_mock_checkout(self.order)
        PaymentAttempt.objects.filter(pk=attempt.pk).update(
            status=PaymentAttempt.Status.CANCELLED
        )
        _, text = self.page(result="failure")
        assert "Payment cancelled" in text
        assert "No completed payment was recorded." in text
        assert "nothing was charged" not in text

    def test_leaving_stripe_is_a_cancellation_before_any_webhook(self):
        attempt = open_mock_checkout(self.order)
        PaymentAttempt.objects.filter(pk=attempt.pk).update(provider="stripe")
        _, text = self.page(result="failure")
        assert "Payment cancelled" in text

    def test_other_rails_failure_door_is_not_completed_not_failed(self):
        open_mock_checkout(self.order)
        _, text = self.page(result="failure")
        assert "Payment wasn't completed" in text
        assert "No completed payment was recorded." in text
        # Nothing a provider has not said.
        assert "nothing was charged" not in text

    def test_a_guest_whose_payment_failed_is_sent_back_to_their_link(self):
        issued = self.guest_link()
        attempt = open_mock_checkout(
            self.order, actor_id=None, guest_link=issued.link, guest_email=""
        )
        PaymentAttempt.objects.filter(pk=attempt.pk).update(
            status=PaymentAttempt.Status.FAILED
        )
        _, text = self.page(result="failure")
        assert "open the payment link you were sent" in text
        assert "ShipTrip app" not in text

    def test_a_closed_order_and_an_unknown_reference_are_no_longer_active(self):
        cancel_order(order_id=self.order.pk, reason="j7d")
        response, text = self.page(result="success")
        assert response.status_code == 404
        assert "This link is no longer active" in text
        assert "€" not in text

        import uuid

        unknown = APIClient().get(f"/pay/{uuid.uuid4()}/return", {"result": "success"})
        assert unknown.status_code == 404
        assert "This link is no longer active" in _visible(
            unknown.content.decode()
        )


class ReturnPagePrivacyAndLanguageTests(_BalanceCase):
    prefix = "j7d-lang"

    def test_it_discloses_no_party_place_parcel_or_id(self):
        pay_order_with_mock(self.client, self.order)
        response, _ = self.page(result="success")
        html = response.content.decode()
        assert_page_withholds(
            html,
            self.scenario.sender.email,
            self.scenario.traveler.email,
            str(self.scenario.deal.pk),
            str(self.scenario.delivery_request.pk),
            str(self.order.pk),
        )
        assert 'name="referrer" content="no-referrer"' in html
        assert "noindex" in html

    def test_three_languages_on_the_shared_shell(self):
        pay_order_with_mock(self.client, self.order)
        fr = APIClient().get(self.url, {"result": "success", "lang": "fr"})
        fr_text = _visible(fr.content.decode())
        assert "Paiement effectué" in fr_text
        assert "25,00" in fr_text

        ar = APIClient().get(self.url, {"result": "success", "lang": "ar"})
        ar_html = ar.content.decode()
        assert 'dir="rtl"' in ar_html
        assert "تمّ الدفع" in _visible(ar_html)
        # The figure is isolated left to right inside the Arabic page.
        assert re.search(r'<bdi dir="ltr">25,00\s€</bdi>', ar_html)

        browser = APIClient().get(
            self.url, {"result": "success"}, HTTP_ACCEPT_LANGUAGE="fr-FR,fr;q=0.9"
        )
        assert "Paiement effectué" in _visible(browser.content.decode())

        # The switch keeps the outcome and drops the re-check counter.
        assert 'href="?result=success&amp;lang=fr"' in ar_html
        for shared in ('class="brand"', 'class="langs"', "/assets/fonts/fraunces.woff2"):
            assert shared in ar_html

    def test_the_guest_reads_the_links_language_when_the_browser_has_none(self):
        issued = create_guest_link(
            order_id=self.order.pk,
            actor_id=self.scenario.sender.pk,
            communication_language="ar",
        )
        pay_order_with_mock(
            self.client, self.order, actor_id=None, guest_link=issued.link, guest_email=""
        )
        response = APIClient().get(self.url, {"result": "success"})
        assert 'lang="ar"' in response.content.decode()


# --- the guest page ------------------------------------------------------------


class GuestPageDeadStatesTests(_BalanceCase):
    prefix = "j7d-guest"

    def test_a_paid_link_says_the_payment_is_complete(self):
        issued = self.guest_link()
        pay_order_with_mock(
            self.client, self.order, actor_id=None, guest_link=issued.link, guest_email=""
        )
        response = APIClient().get(f"/pay/guest/{issued.token}?lang=en")
        text = _visible(response.content.decode())
        assert response.status_code == 200
        assert "This payment has already been completed" in text
        assert "Nothing more is needed" in text
        assert "ask them for a new link" not in text
        assert "€" not in text

    def test_the_sender_paying_themselves_completes_the_link_too(self):
        issued = self.guest_link()
        revoke_guest_link(order_id=self.order.pk, actor_id=self.scenario.sender.pk)
        pay_order_with_mock(self.client, self.order)
        text = _visible(
            APIClient().get(f"/pay/guest/{issued.token}?lang=fr").content.decode()
        )
        assert "Ce paiement a déjà été effectué" in text

    def test_revoked_and_unknown_links_are_no_longer_active(self):
        issued = self.guest_link()
        revoke_guest_link(order_id=self.order.pk, actor_id=self.scenario.sender.pk)
        for path in (f"/pay/guest/{issued.token}", "/pay/guest/never-issued"):
            response = APIClient().get(f"{path}?lang=en")
            assert response.status_code == 404
            text = _visible(response.content.decode())
            assert "This link is no longer active" in text
            assert "already been completed" not in text

    def test_paid_is_not_claimed_for_a_closed_order(self):
        issued = self.guest_link()
        cancel_order(order_id=self.order.pk, reason="j7d")
        assert PaymentOrder.objects.get(pk=self.order.pk).status == "cancelled"
        response = APIClient().get(f"/pay/guest/{issued.token}?lang=en")
        assert response.status_code == 404
        assert "already been completed" not in response.content.decode()
