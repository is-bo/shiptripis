"""J7C: the "someone else can pay" link as the Sender and the payer see it.

Four claims, each checkable on a screen:

**Opening the sheet again does not break the link already shared.** The owner
reads their link without issuing one, and sharing hands back the live link
rather than a replacement. The token is re-derivable for the owner only with
the application key; the database alone still cannot produce a working link.

**The Sender always knows which state the link is in.** None, active, expired,
revoked, paid or closed -- plus whether someone is paying with it right now, in
which case it cannot be replaced *or* revoked.

**The payer's email is asked for only when it is used.** It exists for
ShipTrip's own receipt, failure and refund messages. With transactional email
off, none is ever sent, so the page does not ask.

**The public page is the app, in the payer's language, and says nothing else.**
"""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.business_settings import get_active_business_settings
from apps.core.models import BusinessSettingsVersion
from apps.finance.guest_web import _amount, _duration
from apps.finance.models import GuestPaymentLink, PaymentAttempt, PaymentOrder
from apps.finance.providers import ProviderError
from apps.finance.services import (
    GuestCheckoutInProgress,
    cancel_order,
    create_guest_link,
    derive_guest_token,
    ensure_posting_deposit_order,
    hash_guest_token,
    resolve_guest_link,
    revoke_guest_link,
)

from .factories import (
    assert_page_withholds,
    build_scenario,
    open_mock_checkout,
    pay_order_with_mock,
    visible_page_text,
)


def _enable_mock() -> None:
    settings_version = get_active_business_settings()
    policy = deepcopy(settings_version.policy)
    policy["payments"]["providers"]["mock_enabled"] = True
    BusinessSettingsVersion.objects.filter(pk=settings_version.pk).update(
        policy=policy
    )


class _BalanceCase(TestCase):
    """A funded-ready Deal balance of EUR 25.00 owned by the sender."""

    prefix = "j7c"

    def setUp(self):
        _enable_mock()
        self.scenario = build_scenario(prefix=self.prefix)
        self.scenario.accept(reward_eur_cents=2_000)
        self.order = self.scenario.balance_order()
        self.sender = APIClient()
        self.sender.force_authenticate(self.scenario.sender)
        self.url = reverse(
            "finance-order-guest-link", args=[str(self.order.public_reference)]
        )
        self.revoke_url = reverse(
            "finance-order-guest-link-revoke",
            args=[str(self.order.public_reference)],
        )

    def live_links(self):
        return GuestPaymentLink.objects.filter(
            order=self.order, revoked_at__isnull=True, consumed_at__isnull=True
        )


# --- the owner's link -----------------------------------------------------------


class OwnerLinkLifecycleTests(_BalanceCase):
    prefix = "j7c-life"

    def test_reading_issues_nothing_and_says_there_is_no_link_yet(self):
        for _ in range(3):
            res = self.sender.get(self.url)
            assert res.status_code == 200, res.data
        assert GuestPaymentLink.objects.filter(order=self.order).count() == 0
        assert res.data["state"] == "none"
        assert res.data["token"] is None
        assert res.data["payment_link"] is None
        assert res.data["can_create"] is True
        assert res.data["can_revoke"] is False
        # The authoritative amount and a machine purpose -- never a label the
        # client would have to trust, and never a figure it computed.
        assert res.data["amount_eur_cents"] == self.order.outstanding_eur_cents
        assert res.data["amount_eur_cents"] == 2_500
        assert res.data["purpose"] == "deal_balance"

    def test_sharing_creates_the_first_link_then_hands_back_the_same_one(self):
        first = self.sender.post(self.url, {}, format="json")
        assert first.status_code == 201, first.data
        assert first.data["state"] == "active"
        assert first.data["reused"] is False
        assert first.data["reissued"] is False
        assert first.data["payment_link"].endswith(
            f"/pay/guest/{first.data['token']}"
        )
        assert first.data["amount_eur_cents"] == 2_500

        second = self.sender.post(self.url, {}, format="json")
        assert second.status_code == 200, second.data
        assert second.data["reused"] is True
        assert second.data["reissued"] is False
        assert second.data["payment_link"] == first.data["payment_link"]
        assert second.data["expires_at"] == first.data["expires_at"]

        read = self.sender.get(self.url)
        assert read.data["state"] == "active"
        assert read.data["payment_link"] == first.data["payment_link"]
        assert read.data["can_revoke"] is True
        assert read.data["checkout_in_progress"] is False

        # One capability, and the one a relative already holds still works.
        assert self.live_links().count() == 1
        assert resolve_guest_link(first.data["token"]).order_id == self.order.pk

    def test_the_link_lasts_seventy_two_hours(self):
        before = timezone.now()
        self.sender.post(self.url, {}, format="json")
        after = timezone.now()
        issued_at = self.live_links().get().expires_at - timedelta(hours=72)
        assert before <= issued_at <= after

    def test_a_revoked_link_says_so_and_a_new_one_is_a_deliberate_act(self):
        shared = self.sender.post(self.url, {}, format="json").data

        revoked = self.sender.post(self.revoke_url)
        assert revoked.status_code == 200, revoked.data
        assert revoked.data["revoked"] == 1
        assert revoked.data["state"] == "revoked"
        assert revoked.data["payment_link"] is None
        assert revoked.data["token"] is None
        assert revoked.data["can_create"] is True

        read = self.sender.get(self.url)
        assert read.data["state"] == "revoked"
        assert GuestPaymentLink.objects.filter(order=self.order).count() == 1

        fresh = self.sender.post(self.url, {}, format="json")
        assert fresh.status_code == 201
        assert fresh.data["token"] != shared["token"]
        assert fresh.data["state"] == "active"

    def test_an_expired_link_is_reported_and_not_silently_replaced(self):
        shared = self.sender.post(self.url, {}, format="json").data
        self.live_links().update(expires_at=timezone.now() - timedelta(seconds=1))

        read = self.sender.get(self.url)
        assert read.data["state"] == "expired"
        assert read.data["payment_link"] is None
        assert read.data["can_create"] is True
        assert read.data["expires_at"] is not None
        # Reading did not issue anything.
        assert GuestPaymentLink.objects.filter(order=self.order).count() == 1

        renewed = self.sender.post(self.url, {}, format="json")
        assert renewed.status_code == 201
        assert renewed.data["token"] != shared["token"]
        assert self.live_links().count() == 1

    def test_a_paid_obligation_offers_nothing_more_to_share(self):
        shared = self.sender.post(self.url, {}, format="json").data
        link = GuestPaymentLink.objects.get(order=self.order)
        pay_order_with_mock(
            self.client,
            self.order,
            actor_id=None,
            guest_link=link,
            guest_email="",
        )

        read = self.sender.get(self.url)
        assert read.data["state"] == "paid"
        assert read.data["payment_link"] is None
        assert read.data["can_create"] is False
        assert read.data["can_revoke"] is False
        assert read.data["amount_eur_cents"] == 0

        refused = self.sender.post(self.url, {}, format="json")
        assert refused.status_code == 409
        assert refused.data["code"] in ("order_not_collectable", "nothing_outstanding")
        assert (
            APIClient()
            .get(reverse("finance-guest-payment", args=[shared["token"]]))
            .status_code
            == 404
        )

    def test_a_closed_obligation_is_closed_not_paid(self):
        cancel_order(order_id=self.order.pk, reason="j7c test")
        read = self.sender.get(self.url)
        assert read.data["state"] == "closed"
        assert read.data["can_create"] is False

    def test_only_the_owner_reads_the_link(self):
        self.sender.post(self.url, {}, format="json")
        for user in (self.scenario.traveler, self.scenario.outsider):
            other = APIClient()
            other.force_authenticate(user)
            res = other.get(self.url)
            assert res.status_code == 403, user
            assert "payment_link" not in res.data
            assert "token" not in res.data
        assert APIClient().get(self.url).status_code in (401, 403)


class CheckoutInProgressTests(_BalanceCase):
    prefix = "j7c-busy"

    def test_a_payer_mid_checkout_freezes_replacement_and_revocation(self):
        shared = self.sender.post(self.url, {}, format="json").data
        link = self.live_links().get()
        open_mock_checkout(self.order, actor_id=None, guest_link=link, guest_email="")

        read = self.sender.get(self.url)
        assert read.data["state"] == "active"
        assert read.data["checkout_in_progress"] is True
        assert read.data["can_revoke"] is False
        assert read.data["can_create"] is False
        # The same link is still the link; sharing it again is harmless.
        again = self.sender.post(self.url, {}, format="json")
        assert again.status_code == 200
        assert again.data["token"] == shared["token"]

        refused = self.sender.post(self.revoke_url)
        assert refused.status_code == 409
        assert refused.data["code"] == "guest_checkout_in_progress"
        link.refresh_from_db()
        assert link.revoked_at is None
        with self.assertRaises(GuestCheckoutInProgress):
            revoke_guest_link(order_id=self.order.pk, actor_id=self.scenario.sender.pk)

    def test_the_sender_can_still_pay_it_themselves(self):
        link = create_guest_link(
            order_id=self.order.pk, actor_id=self.scenario.sender.pk
        ).link
        guest_attempt = open_mock_checkout(
            self.order, actor_id=None, guest_link=link, guest_email=""
        )
        own = open_mock_checkout(self.order, actor_id=self.scenario.sender.pk)
        guest_attempt.refresh_from_db()
        assert guest_attempt.status == PaymentAttempt.Status.CANCELLED
        assert own.payer_id == self.scenario.sender.pk
        # With the payer's session superseded, the link can be managed again.
        assert self.sender.get(self.url).data["can_revoke"] is True


class TokenRecoveryTests(_BalanceCase):
    prefix = "j7c-token"

    def test_the_database_alone_cannot_produce_a_working_link(self):
        issued = create_guest_link(
            order_id=self.order.pk, actor_id=self.scenario.sender.pk
        )
        link = issued.link
        assert link.token_seed
        assert link.token_seed != issued.token
        assert hash_guest_token(link.token_seed) != link.token_hash
        assert derive_guest_token(link.token_seed) == issued.token
        assert len(issued.token) >= 43

    def test_a_link_from_before_j7c_is_reported_but_never_invented(self):
        GuestPaymentLink.objects.create(
            order=self.order,
            token_hash=hash_guest_token("legacy-token-without-a-seed"),
            created_by=self.scenario.sender,
            expires_at=timezone.now() + timedelta(days=1),
        )
        read = self.sender.get(self.url)
        assert read.data["state"] == "active"
        assert read.data["payment_link"] is None
        assert read.data["can_create"] is True

        # Sharing replaces it, exactly as before J7C, and says so.
        replaced = self.sender.post(self.url, {}, format="json")
        assert replaced.status_code == 201
        assert replaced.data["reissued"] is True
        assert self.live_links().count() == 1

    def test_a_rotated_key_hides_the_link_instead_of_showing_a_dead_one(self):
        shared = self.sender.post(self.url, {}, format="json").data
        with override_settings(SECRET_KEY="j7c-rotated-" + "x" * 50):
            read = self.sender.get(self.url)
        assert read.data["state"] == "active"
        assert read.data["payment_link"] is None
        # The link the relative holds still resolves; only re-display is lost.
        assert resolve_guest_link(shared["token"]).order_id == self.order.pk


# --- the payer's email ------------------------------------------------------------


class ReceiptEmailTests(_BalanceCase):
    prefix = "j7c-mail"

    def setUp(self):
        super().setUp()
        self.token = create_guest_link(
            order_id=self.order.pk, actor_id=self.scenario.sender.pk
        ).token
        self.page = f"/pay/guest/{self.token}"

    @override_settings(TRANSACTIONAL_EMAIL_ENABLED=False)
    def test_with_email_off_nobody_is_asked_and_nothing_is_kept(self):
        api = APIClient().get(reverse("finance-guest-payment", args=[self.token]))
        assert api.data["receipt_email_required"] is False

        page = APIClient().get(self.page).content.decode()
        assert '<input type="email"' not in page
        assert "receipt" not in visible_page_text(page).lower()

        # Even a hand-crafted POST carrying an address does not get it stored.
        posted = APIClient().post(
            self.page, {"provider": "mock", "email": "someone@example.com"}
        )
        assert posted.status_code == 302
        attempt = PaymentAttempt.objects.get(order=self.order)
        assert attempt.guest_email == ""

    @override_settings(TRANSACTIONAL_EMAIL_ENABLED=True)
    def test_with_email_on_it_is_labelled_explained_and_validated(self):
        api = APIClient().get(reverse("finance-guest-payment", args=[self.token]))
        assert api.data["receipt_email_required"] is True

        page = APIClient().get(self.page).content.decode()
        text = visible_page_text(page)
        assert '<input type="email"' in page and " required " in page
        assert "Email for your receipt" in text
        assert "doesn't create an account" in text.replace("&#x27;", "'")

        missing = APIClient().post(self.page, {"provider": "mock", "email": ""})
        assert missing.status_code == 400
        assert "Enter a valid email address" in missing.content.decode()
        assert 'aria-invalid="true"' in missing.content.decode()
        assert not PaymentAttempt.objects.filter(order=self.order).exists()

        typo = APIClient().post(self.page, {"provider": "mock", "email": "aunt@"})
        assert typo.status_code == 400
        # What they typed is kept so they can fix it rather than retype it.
        assert 'value="aunt@"' in typo.content.decode()

        ok = APIClient().post(
            self.page, {"provider": "mock", "email": " aunt@example.com "}
        )
        assert ok.status_code == 302
        assert PaymentAttempt.objects.get(order=self.order).guest_email == (
            "aunt@example.com"
        )

    @override_settings(TRANSACTIONAL_EMAIL_ENABLED=True)
    def test_the_app_checkout_applies_the_same_rule(self):
        res = APIClient().post(
            reverse("finance-guest-checkout", args=[self.token]),
            {"provider": "mock"},
            format="json",
        )
        assert res.status_code == 400
        assert "email" in res.data


# --- the public page --------------------------------------------------------------


class PublicPageTests(_BalanceCase):
    prefix = "j7c-page"

    def setUp(self):
        super().setUp()
        self.issued = create_guest_link(
            order_id=self.order.pk,
            actor_id=self.scenario.sender.pk,
            communication_language="fr",
        )
        self.page = f"/pay/guest/{self.issued.token}"

    def test_the_page_leads_with_the_amount_and_what_it_is_for(self):
        res = APIClient().get(self.page, HTTP_ACCEPT_LANGUAGE="en-GB,en;q=0.8")
        assert res.status_code == 200
        html = res.content.decode()
        text = visible_page_text(html)
        assert 'lang="en"' in html and 'dir="ltr"' in html
        assert "€25.00" in text
        assert "Payment for a delivery" in text
        assert "Pay €25.00" in text
        assert "You don't need an account" in text.replace("&#x27;", "'")
        assert "3 more days" in text
        assert "ShipTrip never sees your card details" in text
        # The enum never reaches a person.
        assert "deal_balance" not in text

    def test_the_page_withholds_every_party_place_and_identifier(self):
        request = self.scenario.delivery_request
        html = APIClient().get(self.page).content.decode()
        assert_page_withholds(
            html,
            self.scenario.sender.email,
            self.scenario.sender.full_name,
            self.scenario.traveler.email,
            self.scenario.traveler.full_name,
            request.title,
            request.pickup_location.private_label,
            request.delivery_location.private_label,
            str(self.order.public_reference),
            str(self.order.pk),
            str(request.pk),
            str(self.order.deal_id),
            self.issued.link.token_seed,
            self.issued.link.token_hash,
        )
        # The token is the path and nowhere else: never in a query string.
        assert f"?token={self.issued.token}" not in html
        assert f"lang={self.issued.token}" not in html
        assert '<meta name="referrer" content="no-referrer">' in html

    def test_it_speaks_the_readers_language_then_the_links(self):
        ar = APIClient().get(self.page, HTTP_ACCEPT_LANGUAGE="ar-DZ,ar;q=0.9")
        html = ar.content.decode()
        assert 'lang="ar"' in html and 'dir="rtl"' in html
        assert "دفع مقابل توصيل" in html
        assert "25,00 €" in html

        # No usable browser language: the language the link was issued in.
        fallback = APIClient().get(self.page, HTTP_ACCEPT_LANGUAGE="de-DE")
        assert 'lang="fr"' in fallback.content.decode()
        assert "Paiement d’une livraison" in fallback.content.decode()

        # An explicit choice wins over both.
        chosen = APIClient().get(
            f"{self.page}?lang=en", HTTP_ACCEPT_LANGUAGE="ar"
        ).content.decode()
        assert 'lang="en"' in chosen
        for code in ("en", "fr", "ar"):
            assert f'href="?lang={code}"' in chosen

    def test_a_deposit_is_named_as_a_deposit(self):
        scenario = build_scenario(prefix="j7c-dep", open_request=False)
        deposit = ensure_posting_deposit_order(
            delivery_request=scenario.delivery_request,
            chosen_amount_eur_cents=500,
        )
        token = create_guest_link(order_id=deposit.pk, actor_id=scenario.sender.pk).token
        text = visible_page_text(
            APIClient().get(f"/pay/guest/{token}?lang=en").content.decode()
        )
        assert "Deposit for a delivery request" in text
        assert "€5.00" in text

    def test_every_dead_link_reads_the_same_in_the_readers_language(self):
        revoke_guest_link(order_id=self.order.pk, actor_id=self.scenario.sender.pk)
        for path in (self.page, "/pay/guest/never-issued"):
            res = APIClient().get(f"{path}?lang=fr")
            assert res.status_code == 404
            html = res.content.decode()
            assert "Ce lien de paiement n’est plus valable" in html
            assert "€" not in visible_page_text(html)

    def test_a_rail_outage_at_the_tap_is_not_reported_as_a_dead_link(self):
        with mock.patch(
            "apps.finance.guest_web.start_checkout",
            side_effect=ProviderError("provider down"),
        ):
            res = APIClient().post(self.page, {"provider": "mock", "lang": "en"})
        assert res.status_code == 503
        assert "Payments are paused for a moment" in res.content.decode()
        assert "no longer works" not in res.content.decode()

    def test_the_page_hands_off_to_the_provider_without_touching_the_amount(self):
        res = APIClient().post(
            self.page, {"provider": "mock", "amount_eur_cents": "1"}
        )
        assert res.status_code == 302
        attempt = PaymentAttempt.objects.get(order=self.order)
        assert res["Location"] == attempt.checkout_url
        assert attempt.amount_eur_cents == 2_500
        assert attempt.guest_link_id == self.issued.link.pk
        self.order.refresh_from_db()
        assert self.order.status == PaymentOrder.Status.PENDING


class PageFormattingTests(TestCase):
    def test_amounts_follow_the_apps_locale_formatting(self):
        assert _amount(2_500, "en") == "€25.00"
        assert _amount(123_456, "en") == "€1,234.56"
        assert _amount(2_500, "fr") == "25,00 €"
        assert _amount(123_456, "fr") == "1 234,56 €"
        assert _amount(2_500, "ar") == "25,00 €"

    def test_the_remaining_time_is_said_in_words_with_arabic_duals(self):
        now = timezone.now()

        def say(delta, lang):
            return _duration(now + delta, lang, now=now)

        assert say(timedelta(hours=72), "en") == "3 more days"
        assert say(timedelta(hours=72), "fr") == "3 jours"
        assert say(timedelta(hours=72), "ar") == "3 أيام"
        assert say(timedelta(hours=47, minutes=10), "ar") == "يومين"
        assert say(timedelta(hours=30), "en") == "1 more day"
        assert say(timedelta(hours=5), "en") == "5 more hours"
        assert say(timedelta(hours=2), "ar") == "ساعتين"
        assert say(timedelta(hours=11), "ar") == "11 ساعة"
        assert say(timedelta(minutes=20), "fr") == "1 heure"
        assert say(timedelta(seconds=-1), "en") == "less than an hour"
