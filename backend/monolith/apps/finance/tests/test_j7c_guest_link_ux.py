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
Wassla's own receipt, failure and refund messages. With transactional email
off, none is ever sent, so the page does not ask.

**The public page is the app, in the payer's language, and says nothing else.**

G1 adds a fifth: **the page works in the browser that opens it.** The shared
shell suppresses the referrer, so Chromium submits the form with `Origin: null`
and no Referer, which Django's cookie-based CSRF check refuses. The page's
authority is the link token in its path, so the page is exempt from that check
and every submission here is made the way that browser makes it.
"""

from __future__ import annotations

import dataclasses
import logging
from copy import deepcopy
from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string
from rest_framework.test import APIClient

from apps.core.business_settings import get_active_business_settings
from apps.core.models import BusinessSettingsVersion
from apps.finance import guest_web
from apps.finance.guest_web import _amount, _duration
from apps.finance.models import (
    GuestPaymentLink,
    LedgerTransaction,
    PaymentAttempt,
    PaymentOrder,
    PaymentRefund,
)
from apps.finance.providers import ProviderError
from apps.finance.providers.mock import MockGateway
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
    deliver_mock_webhook,
    open_mock_checkout,
    pay_order_with_mock,
    succeed_attempt,
    visible_page_text,
)

#: How Chromium submits the page's form over HTTPS under the shell's
#: `<meta name="referrer" content="no-referrer">`: `Origin: null` and no
#: Referer (phone test 2, finding 1.1). Django's CSRF check refuses both.
SHELL_SUBMIT = {"secure": True, "HTTP_ORIGIN": "null"}


def browser() -> Client:
    """A browser as Django sees one: the CSRF check on, no cookie yet."""

    return Client(enforce_csrf_checks=True)


def assert_private(response) -> None:
    """The guest response is cached by nobody and names itself to nobody."""

    assert response["Referrer-Policy"] == "no-referrer", response.status_code
    directives = {part.strip() for part in response["Cache-Control"].split(",")}
    assert {"private", "no-store"} <= directives, response["Cache-Control"]


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
        posted = browser().post(
            self.page,
            {"provider": "mock", "email": "someone@example.com"},
            **SHELL_SUBMIT,
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

        payer = browser()
        missing = payer.post(
            self.page, {"provider": "mock", "email": ""}, **SHELL_SUBMIT
        )
        assert missing.status_code == 400
        assert "Enter a valid email address" in missing.content.decode()
        assert 'aria-invalid="true"' in missing.content.decode()
        assert_private(missing)
        assert not PaymentAttempt.objects.filter(order=self.order).exists()

        typo = payer.post(
            self.page, {"provider": "mock", "email": "aunt@"}, **SHELL_SUBMIT
        )
        assert typo.status_code == 400
        # What they typed is kept so they can fix it rather than retype it.
        assert 'value="aunt@"' in typo.content.decode()
        assert not PaymentAttempt.objects.filter(order=self.order).exists()

        ok = payer.post(
            self.page,
            {"provider": "mock", "email": " aunt@example.com "},
            **SHELL_SUBMIT,
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
        assert "Wassla never sees your card details" in text
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
            # L11A: the parcel's tracking number is never on the guest page.
            request.tracking_number,
            "WSL-",
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
            assert "Ce lien n’est plus actif" in html
            assert "€" not in visible_page_text(html)

    def test_a_rail_outage_at_the_tap_is_not_reported_as_a_dead_link(self):
        with mock.patch(
            "apps.finance.guest_web.start_checkout",
            side_effect=ProviderError("provider down"),
        ):
            res = browser().post(
                self.page, {"provider": "mock", "lang": "en"}, **SHELL_SUBMIT
            )
        assert res.status_code == 503
        assert "Payments are paused for a moment" in res.content.decode()
        assert "no longer active" not in res.content.decode()

    def test_the_page_hands_off_to_the_provider_without_touching_the_amount(self):
        res = browser().post(
            self.page, {"provider": "mock", "amount_eur_cents": "1"}, **SHELL_SUBMIT
        )
        assert res.status_code == 302
        attempt = PaymentAttempt.objects.get(order=self.order)
        assert res["Location"] == attempt.checkout_url
        assert attempt.amount_eur_cents == 2_500
        assert attempt.guest_link_id == self.issued.link.pk
        self.order.refresh_from_db()
        assert self.order.status == PaymentOrder.Status.PENDING


# --- G1: the page in the browser that opens it ------------------------------------

#: The console's templates resolve static files, and tests build no manifest.
UNHASHED_STATIC = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}


class BrowserCheckoutTests(_BalanceCase):
    """The link token is the authority. Cookies, sessions and headers are not."""

    prefix = "g1-browser"

    def setUp(self):
        super().setUp()
        self.issued = create_guest_link(
            order_id=self.order.pk,
            actor_id=self.scenario.sender.pk,
            communication_language="en",
        )
        self.link = self.issued.link
        self.page = f"/pay/guest/{self.issued.token}"
        MockGateway.reset()

    def tap(self, client=None, *, path=None, data=None, **headers):
        """Press the page's button, as the browser submits it unless told otherwise."""

        return (client or browser()).post(
            path or self.page,
            {"provider": "mock", "lang": "en", **(data or {})},
            **(headers or SHELL_SUBMIT),
        )

    def attempts(self):
        return PaymentAttempt.objects.filter(order=self.order)

    def assert_dead(self, response, *, status=404):
        html = response.content.decode()
        assert response.status_code == status, response.status_code
        assert "This link is no longer active" in html
        assert "€" not in visible_page_text(html)
        assert_private(response)

    def test_a_fresh_payer_without_cookies_reaches_hosted_checkout(self):
        payer = browser()
        page = payer.get(self.page, secure=True)
        assert page.status_code == 200
        html = page.content.decode()
        assert "csrfmiddlewaretoken" not in html
        assert '<meta name="referrer" content="no-referrer">' in html
        assert not page.cookies

        handed_off = self.tap(payer)

        assert handed_off.status_code == 302, handed_off.content
        attempt = self.attempts().get()
        assert handed_off["Location"] == attempt.checkout_url
        assert attempt.checkout_url.startswith("https://mock.invalid/checkout/")
        assert not handed_off.cookies
        # Nothing set a cookie, so the browser never had one to send.
        assert not payer.cookies
        assert attempt.status == PaymentAttempt.Status.CHECKOUT_PENDING
        assert attempt.payer_id is None
        assert attempt.guest_link_id == self.link.pk
        assert attempt.amount_eur_cents == 2_500
        self.order.refresh_from_db()
        assert self.order.status == PaymentOrder.Status.PENDING

    def test_a_submission_with_neither_origin_nor_referer_is_accepted(self):
        handed_off = self.tap(secure=True)
        assert handed_off.status_code == 302, handed_off.content
        assert handed_off["Location"] == self.attempts().get().checkout_url

    def test_a_signed_in_member_pays_as_a_guest_and_gains_nothing(self):
        outsider = browser()
        outsider.force_login(self.scenario.outsider)
        assert self.tap(outsider).status_code == 302
        attempt = self.attempts().get()
        assert attempt.payer_id is None
        assert attempt.guest_link_id == self.link.pk

        # The owner's own session does not make the guest attempt theirs.
        owner = browser()
        owner.force_login(self.scenario.sender)
        assert self.tap(owner)["Location"] == attempt.checkout_url
        assert self.attempts().get().payer_id is None

        # Paying is not membership: the order and its link stay shut.
        api = APIClient()
        api.force_authenticate(self.scenario.outsider)
        assert api.get(self.url).status_code == 403
        detail = reverse(
            "finance-order-detail", args=[str(self.order.public_reference)]
        )
        assert api.get(detail).status_code == 403

        # A session never rescues a link that does not work.
        self.assert_dead(self.tap(outsider, path="/pay/guest/never-issued"))
        assert self.attempts().count() == 1

    def test_a_dead_link_starts_nothing_however_the_browser_submits(self):
        sender = self.scenario.sender.pk
        GuestPaymentLink.objects.filter(pk=self.link.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assert_dead(self.tap())

        revoked = create_guest_link(order_id=self.order.pk, actor_id=sender)
        revoke_guest_link(order_id=self.order.pk, actor_id=sender)
        self.assert_dead(self.tap(path=f"/pay/guest/{revoked.token}"))

        consumed = create_guest_link(order_id=self.order.pk, actor_id=sender)
        GuestPaymentLink.objects.filter(pk=consumed.link.pk).update(
            consumed_at=timezone.now()
        )
        self.assert_dead(self.tap(path=f"/pay/guest/{consumed.token}"))

        self.assert_dead(self.tap(path="/pay/guest/never-issued"))
        assert not self.attempts().exists()

    def test_a_link_stopped_while_the_payer_taps_starts_no_payment(self):
        """The page reads the link unlocked; checkout reads it again under the
        order lock that revoking and replacing take, so the later read wins."""

        sender = self.scenario.sender.pk
        stops = {
            "revoked": lambda link: revoke_guest_link(
                order_id=link.order_id, actor_id=sender
            ),
            "replaced": lambda link: create_guest_link(
                order_id=link.order_id, actor_id=sender
            ),
            "expired": lambda link: GuestPaymentLink.objects.filter(
                pk=link.pk
            ).update(expires_at=timezone.now() - timedelta(seconds=1)),
        }
        real_resolve = guest_web.resolve_guest_link
        for reason, stop in stops.items():
            with self.subTest(reason):
                token = create_guest_link(
                    order_id=self.order.pk, actor_id=sender
                ).token

                def resolve_then_stop(value, stop=stop):
                    link = real_resolve(value)
                    stop(link)
                    return link

                with mock.patch.object(
                    guest_web, "resolve_guest_link", side_effect=resolve_then_stop
                ):
                    response = self.tap(path=f"/pay/guest/{token}")
                self.assert_dead(response, status=409)
                assert not self.attempts().exists()

    def test_a_payer_already_at_the_provider_freezes_revocation(self):
        assert self.tap().status_code == 302
        with self.assertRaises(GuestCheckoutInProgress):
            revoke_guest_link(order_id=self.order.pk, actor_id=self.scenario.sender.pk)
        self.link.refresh_from_db()
        assert self.link.revoked_at is None

    def test_a_second_tap_reuses_the_first_checkout_and_funds_once(self):
        payer = browser()
        first = self.tap(payer)
        second = self.tap(payer)
        assert first.status_code == second.status_code == 302
        assert first["Location"] == second["Location"]
        attempt = self.attempts().get()

        event = succeed_attempt(attempt)
        for _ in range(2):
            assert deliver_mock_webhook(self.client, event).status_code == 200
        self.order.refresh_from_db()
        assert self.order.status == PaymentOrder.Status.PAID
        assert self.order.paid_eur_cents == 2_500
        assert LedgerTransaction.objects.filter(kind="deal_funding").count() == 1

        # A tap after the payment lands says so and starts nothing.
        after = self.tap(payer)
        assert after.status_code == 200
        assert "This payment has already been completed" in after.content.decode()
        assert self.attempts().count() == 1

    @override_settings(TRANSACTIONAL_EMAIL_ENABLED=True)
    def test_a_second_holder_with_another_address_is_not_shown_the_checkout(self):
        aunt = self.tap(data={"email": "aunt@example.com"})
        assert aunt.status_code == 302
        url = aunt["Location"]

        stranger = self.tap(data={"email": "stranger@example.com"})

        html = stranger.content.decode()
        assert stranger.status_code == 409
        assert "already open under another email address" in html
        assert 'aria-invalid="true"' in html
        assert 'value="stranger@example.com"' in html
        assert url not in html and "Location" not in stranger
        assert_private(stranger)
        attempt = self.attempts().get()
        assert attempt.guest_email == "aunt@example.com"
        assert attempt.checkout_url == url

        # The first holder still reaches their checkout.
        assert self.tap(data={"email": "aunt@example.com"})["Location"] == url

    def test_a_tap_while_the_first_is_still_opening_is_asked_to_wait(self):
        real_create = MockGateway.create_checkout
        during = []

        def second_tap_meanwhile(gateway, request):
            if not during:
                during.append("entered")
                during.append(self.tap())
                during.append(
                    list(self.attempts().values_list("status", "checkout_url"))
                )
            return real_create(gateway, request)

        with mock.patch.object(
            MockGateway, "create_checkout", new=second_tap_meanwhile
        ):
            first = self.tap()

        waiting = during[1]
        html = waiting.content.decode()
        assert waiting.status_code == 409
        assert "Your payment page is being opened" in html
        assert "no longer active" not in html
        assert "Payments are paused" not in html
        assert_private(waiting)
        assert during[2] == [("created", "")]
        attempt = self.attempts().get()
        assert first.status_code == 302
        assert first["Location"] == attempt.checkout_url
        assert MockGateway.checkout_session_ids() == [attempt.provider_session_id]

        # "Try again" resends the same choice and reaches that one checkout.
        assert '<input type="hidden" name="provider" value="mock">' in html
        assert self.tap()["Location"] == attempt.checkout_url
        assert self.attempts().count() == 1

    def test_a_tap_replaced_while_opening_is_asked_to_wait(self):
        """The owner pays in the app while the guest's checkout is opening:
        the guest is told to try again, not sent to an empty or closed one."""

        real_create = MockGateway.create_checkout
        owner = []

        def owner_pays_meanwhile(gateway, request):
            if not owner:
                owner.append("entered")
                owner.append(
                    open_mock_checkout(self.order, actor_id=self.scenario.sender.pk)
                )
            return real_create(gateway, request)

        with mock.patch.object(
            MockGateway, "create_checkout", new=owner_pays_meanwhile
        ):
            response = self.tap()

        assert response.status_code == 409
        assert "Your payment page is being opened" in response.content.decode()
        guest_attempt = self.attempts().get(guest_link=self.link)
        assert guest_attempt.status == PaymentAttempt.Status.CANCELLED
        assert guest_attempt.checkout_url == ""
        live = self.attempts().get(status__in=PaymentAttempt.OPEN_STATUSES)
        assert live.pk == owner[1].pk

    def test_a_provider_failure_funds_nothing_and_the_link_still_works(self):
        with mock.patch.object(
            MockGateway, "create_checkout", side_effect=ProviderError("rail down")
        ):
            failed = self.tap()
        assert failed.status_code == 503
        assert "Payments are paused for a moment" in failed.content.decode()
        assert_private(failed)
        attempt = self.attempts().get()
        assert attempt.status == PaymentAttempt.Status.FAILED
        assert attempt.checkout_url == ""
        self.order.refresh_from_db()
        assert self.order.status == PaymentOrder.Status.PENDING
        assert self.order.paid_eur_cents == 0

        # The link was never the problem: it still shows the amount and pays.
        assert browser().get(self.page).status_code == 200
        retried = self.tap()
        assert retried.status_code == 302
        live = self.attempts().get(status__in=PaymentAttempt.OPEN_STATUSES)
        assert live.pk != attempt.pk
        assert retried["Location"] == live.checkout_url
        assert deliver_mock_webhook(self.client, succeed_attempt(live)).status_code == 200
        self.order.refresh_from_db()
        assert self.order.paid_eur_cents == 2_500
        attempt.refresh_from_db()
        assert attempt.status == PaymentAttempt.Status.FAILED

    @override_settings(TRANSACTIONAL_EMAIL_ENABLED=False)
    def test_fields_the_payer_adds_cannot_steer_the_payment(self):
        other = build_scenario(prefix="g1-other")
        other.accept(reward_eur_cents=2_000)
        other_order = other.balance_order()
        other_token = create_guest_link(
            order_id=other_order.pk, actor_id=other.sender.pk
        ).token
        outsider = str(self.scenario.outsider.pk)
        forged = {
            "amount_eur_cents": "1",
            "amount": "1",
            "currency": "DZD",
            "payment_currency": "DZD",
            "provider_amount_minor": "1",
            "order": str(other_order.pk),
            "order_id": str(other_order.pk),
            "reference": str(other_order.public_reference),
            "token": other_token,
            "payer": outsider,
            "payer_id": outsider,
            "actor_id": outsider,
            "user_id": outsider,
            "guest_link_id": "1",
            "guest_email": "forged@example.com",
            "email": "forged@example.com",
            "idempotency_key": "forged",
            "checkout_url": "https://evil.example/pay",
            "success_url": "https://evil.example/ok",
            "status": "succeeded",
        }

        response = self.tap(data=forged)

        assert response.status_code == 302, response.content
        attempt = self.attempts().get()
        assert response["Location"] == attempt.checkout_url
        assert "evil.example" not in response["Location"]
        assert attempt.amount_eur_cents == 2_500
        assert attempt.payment_currency == "EUR"
        assert attempt.payer_id is None
        assert attempt.guest_link_id == self.link.pk
        assert attempt.guest_email == ""
        assert attempt.idempotency_key != "forged"
        assert attempt.status == PaymentAttempt.Status.CHECKOUT_PENDING
        assert not PaymentAttempt.objects.filter(order=other_order).exists()
        self.order.refresh_from_db()
        assert self.order.status == PaymentOrder.Status.PENDING

    def test_every_guest_response_is_private_and_sends_no_referrer(self):
        responses = {
            "page": browser().get(self.page),
            "arabic": browser().get(f"{self.page}?lang=ar"),
            "unknown link": browser().get("/pay/guest/never-issued"),
            "wrong method": browser().put(self.page),
        }
        with mock.patch(
            "apps.finance.views.GuestPaymentThrottle.allow_request",
            return_value=False,
        ):
            responses["throttled"] = browser().get(self.page)
        responses["handoff"] = self.tap()
        deliver_mock_webhook(self.client, succeed_attempt(self.attempts().get()))
        responses["already paid"] = browser().get(self.page)

        assert {name: res.status_code for name, res in responses.items()} == {
            "page": 200,
            "arabic": 200,
            "unknown link": 404,
            "wrong method": 405,
            "throttled": 429,
            "handoff": 302,
            "already paid": 200,
        }
        for name, response in responses.items():
            with self.subTest(name):
                assert_private(response)

    def test_a_server_error_on_the_page_is_private_too(self):
        """Django builds the 500 for an exception in the view or in a later
        middleware only after the view's wrappers have unwound. The headers
        come from the first middleware, which sees that response too."""

        failing = Client(raise_request_exception=False)
        with self.assertLogs("django.request", level="ERROR"):
            with mock.patch.object(
                guest_web, "_throttled", side_effect=RuntimeError("cache down")
            ):
                from_view = failing.get(self.page)
            with mock.patch(
                "django.contrib.sessions.middleware.SessionMiddleware.process_request",
                side_effect=RuntimeError("session store down"),
            ):
                from_middleware = failing.post(
                    self.page, {"provider": "mock"}, **SHELL_SUBMIT
                )

        for name, response in {"view": from_view, "middleware": from_middleware}.items():
            with self.subTest(name):
                assert response.status_code == 500
                assert_private(response)
        assert not self.attempts().exists()

    def test_a_session_does_not_lift_the_guest_bound(self):
        """One bucket per client address, signed in or not, and the page shares
        it with the app's guest endpoints."""

        from apps.finance.views import GuestPaymentThrottle

        member = browser()
        member.force_login(self.scenario.outsider)
        api = reverse("finance-guest-payment", args=[self.issued.token])
        with mock.patch.dict(
            GuestPaymentThrottle.THROTTLE_RATES, {"guest_payment": "2/min"}
        ):
            # Strangers use up an address's budget; a member's session from
            # the same address does not reopen it.
            spent = "203.0.113.10"
            for _ in range(2):
                assert browser().get(self.page, REMOTE_ADDR=spent).status_code == 200
            assert member.get(self.page, REMOTE_ADDR=spent).status_code == 429
            assert APIClient().get(api, REMOTE_ADDR=spent).status_code == 429

            # A member's own requests count against the address like anyone's.
            shared = "203.0.113.11"
            for _ in range(2):
                assert member.get(self.page, REMOTE_ADDR=shared).status_code == 200
            assert browser().get(self.page, REMOTE_ADDR=shared).status_code == 429
            tapped = self.tap(member, REMOTE_ADDR=shared, **SHELL_SUBMIT)
            assert tapped.status_code == 429
        assert not self.attempts().exists()

    def test_the_token_stays_out_of_the_provider_logs_and_navigation(self):
        secrets = (self.issued.token, self.link.token_hash, self.link.token_seed)
        sent = []
        real_create = MockGateway.create_checkout

        def capture(gateway, request):
            sent.append(request)
            return real_create(gateway, request)

        records = []

        class Collect(logging.Handler):
            def emit(self, record):
                records.append(record)

        root = logging.getLogger()
        handler = Collect(level=logging.DEBUG)
        level = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        try:
            with override_settings(PERFORMANCE_ACCESS_LOG_ENABLED=True):
                browser().get(self.page)
                with mock.patch.object(
                    MockGateway, "create_checkout", side_effect=ProviderError("down")
                ):
                    assert self.tap().status_code == 503
                with mock.patch.object(MockGateway, "create_checkout", capture):
                    handed_off = self.tap()
        finally:
            root.removeHandler(handler)
            root.setLevel(level)

        assert handed_off.status_code == 302
        assert len(sent) == 1
        outbound = repr(dataclasses.asdict(sent[0]))
        navigation = handed_off["Location"]
        # `django.request` repeats the concrete path, and the production
        # formatter replaces that message with the route template
        # (`test_deployment_safety`). Every other line is checked as written.
        logged = " ".join(
            f"{record.name} {record.getMessage()} {vars(record)}"
            for record in records
            if record.name != "django.request"
        )
        assert "finance.guest_page_checkout_unavailable" in logged
        for secret in secrets:
            assert secret not in outbound
            assert secret not in navigation
            assert secret not in logged

    @override_settings(STORAGES=UNHASHED_STATIC)
    def test_csrf_still_guards_a_session_authorized_form(self):
        """The exemption is this one page, not `Origin: null` everywhere."""

        from apps.admin_panel.permissions import AdminRole, assign_admin_roles
        from apps.admin_panel.tests.two_step_helpers import staff_login

        staff = get_user_model().objects.create_user(
            email="g1-staff@example.com",
            username="g1-staff@example.com",
            password="Strong-pass-123!",
            is_staff=True,
            is_superuser=True,
        )
        assign_admin_roles(staff, (AdminRole.SUPER_ADMIN,), elevate_super_admin=True)
        console = browser()
        staff_login(console, staff)
        secret = get_random_string(32)
        console.cookies[settings.CSRF_COOKIE_NAME] = secret
        attempt = open_mock_checkout(self.order)
        form = f"/admin/finance/refunds/new/{attempt.pk}/"
        same_origin = {"secure": True, "HTTP_ORIGIN": "https://testserver"}

        for name, data, headers in (
            ("shell submission with the token", {"csrfmiddlewaretoken": secret}, SHELL_SUBMIT),
            ("no origin or referer", {"csrfmiddlewaretoken": secret}, {"secure": True}),
            ("same origin without the token", {}, same_origin),
        ):
            with self.subTest(name):
                refused = console.post(form, data, **headers)
                assert refused.status_code == 403
                assert "CSRF verification failed" in refused.content.decode()

        # The same browser, token in hand, from the site's own origin: let through.
        allowed = console.post(form, {"csrfmiddlewaretoken": secret}, **same_origin)
        assert allowed.status_code == 200
        assert "CSRF verification failed" not in allowed.content.decode()
        assert not PaymentRefund.objects.exists()

        # And the guest page takes that browser's shell submission as a guest's.
        assert self.tap(console).status_code == 302
        assert self.attempts().get(
            status__in=PaymentAttempt.OPEN_STATUSES
        ).payer_id is None

    def test_only_the_signed_webhook_funds_the_order(self):
        assert self.tap().status_code == 302
        attempt = self.attempts().get()

        # Coming back from the provider proves nothing.
        back = browser().get(
            f"/pay/{self.order.public_reference}/return?result=success", secure=True
        )
        assert back.status_code == 200
        self.order.refresh_from_db()
        assert self.order.status == PaymentOrder.Status.PENDING

        # A forged event is refused and moves no money.
        forged = deliver_mock_webhook(
            self.client, succeed_attempt(attempt), signature="forged"
        )
        assert forged.status_code == 400
        self.order.refresh_from_db()
        assert self.order.status == PaymentOrder.Status.PENDING
        assert self.order.paid_eur_cents == 0

        # The provider's signed event does.
        assert deliver_mock_webhook(self.client, succeed_attempt(attempt)).status_code == 200
        self.order.refresh_from_db()
        assert self.order.status == PaymentOrder.Status.PAID
        self.link.refresh_from_db()
        assert self.link.consumed_at is not None
        assert (
            "This payment has already been completed"
            in browser().get(self.page).content.decode()
        )


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
