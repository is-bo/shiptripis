"""Third-party payer: it buys the payment and nothing else.

The threat model behind these tests is that holding a guest link is the *only*
credential involved, so every question is "what else does it let me do?". The
answers must all be "nothing": no Deal, no chat, no dispute, no recipient, no
addresses, no other order, and no way to tell an expired link from one that
never existed.
"""

from __future__ import annotations

import json
import secrets
from copy import deepcopy
from datetime import timedelta
from unittest import mock

from django.db.models import F
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.business_settings import get_active_business_settings
from apps.core.models import BusinessSettingsVersion
from apps.deals.models import Deal
from apps.finance import jobs
from apps.finance import services
from apps.finance.models import (
    GuestPaymentLink,
    PaymentAttempt,
    PaymentOrder,
    PaymentProviderEvent,
    PaymentRefund,
    ScheduledJob,
)
from apps.finance import views as finance_views
from apps.finance.operations import (
    FinanceOperationsError,
    queue_payment_reconciliation,
)
from apps.finance.providers import (
    ProviderCheckoutRejected,
    ProviderError,
    ProviderNotConfigured,
    ProviderUnavailable,
)
from apps.finance.providers.mock import MockGateway
from apps.finance.services import (
    CHECKOUT_CLOSE_ATTEMPTS,
    CHECKOUT_OPENING_WINDOW,
    CHECKOUT_RECOVERY_LIMIT,
    CheckoutInProgress,
    FinanceError,
    GuestLinkInvalid,
    NotAuthorized,
    cancel_order,
    close_order_to_collection,
    create_guest_link,
    hash_guest_token,
    reconcile_attempt,
    recover_checkout_attempt,
    resolve_guest_link,
    revoke_guest_link,
    start_checkout,
)
from apps.notifications.models import OutboundMessage

from .factories import (
    build_scenario,
    deliver_mock_webhook,
    mock_event_body,
    open_mock_checkout,
    succeed_attempt,
)


def _enable_mock():
    settings_version = get_active_business_settings()
    policy = deepcopy(settings_version.policy)
    policy["payments"]["providers"]["mock_enabled"] = True
    BusinessSettingsVersion.objects.filter(pk=settings_version.pk).update(
        policy=policy
    )


class GuestPaymentTestCase(TestCase):
    def setUp(self):
        _enable_mock()
        self.scenario = build_scenario(prefix="guest")
        self.scenario.accept(reward_eur_cents=3_200)
        self.order = self.scenario.balance_order()
        self.issued = create_guest_link(
            order_id=self.order.pk, actor_id=self.scenario.sender.pk, label="Dad"
        )
        self.token = self.issued.token
        self.guest = APIClient()  # deliberately unauthenticated

    def client_for(self, user) -> APIClient:
        client = APIClient()
        client.force_authenticate(user=user)
        return client


class GuestTokenStorageTests(GuestPaymentTestCase):
    def test_only_a_hash_of_the_token_is_stored(self):
        link = GuestPaymentLink.objects.get(pk=self.issued.link.pk)

        assert link.token_hash == hash_guest_token(self.token)
        assert self.token not in link.token_hash
        # No column anywhere holds the plaintext.
        stored = json.dumps(
            {
                field.name: str(getattr(link, field.name))
                for field in GuestPaymentLink._meta.fields
            }
        )
        assert self.token not in stored

    def test_the_token_is_long_and_unguessable(self):
        # 32 random bytes, urlsafe-base64 encoded.
        assert len(self.token) >= 40
        second = create_guest_link(
            order_id=self.order.pk, actor_id=self.scenario.sender.pk
        ).token
        assert second != self.token

    def test_issuing_a_new_link_revokes_the_previous_one(self):
        create_guest_link(order_id=self.order.pk, actor_id=self.scenario.sender.pk)

        with self.assertRaises(GuestLinkInvalid):
            resolve_guest_link(self.token)
        assert (
            GuestPaymentLink.objects.filter(
                order=self.order, revoked_at__isnull=True, consumed_at__isnull=True
            ).count()
            == 1
        )

    def test_only_the_owner_can_issue_or_revoke_a_link(self):
        with self.assertRaises(NotAuthorized):
            create_guest_link(
                order_id=self.order.pk, actor_id=self.scenario.outsider.pk
            )

        response = self.client_for(self.scenario.traveler).post(
            reverse(
                "finance-order-guest-link",
                args=[str(self.order.public_reference)],
            )
        )
        assert response.status_code == 403


class GuestTokenValidationTests(GuestPaymentTestCase):
    def _get(self, token: str):
        return self.guest.get(reverse("finance-guest-payment", args=[token]))

    def test_a_valid_token_returns_only_payment_information(self):
        response = self._get(self.token)

        assert response.status_code == 200, response.data
        assert set(response.data) == {
            "amount_eur_cents",
            "currency",
            "purpose",
            "description",
            "expires_at",
            "providers",
            "receipt_email_required",
        }
        assert response.data["currency"] == "EUR"
        assert response.data["amount_eur_cents"] == self.order.outstanding_eur_cents
        # `purpose` is the machine-readable form of what `description` already
        # says in words -- which kind of payment this is. It carries no new
        # disclosure, and it is one of a closed set of platform-defined values.
        assert response.data["purpose"] in {
            "posting_deposit",
            "deal_balance",
            "boost",
        }

    def test_the_payload_names_no_person_place_or_parcel(self):
        response = self._get(self.token)
        body = json.dumps(response.data, default=str)

        for secret in (
            self.scenario.sender.email,
            self.scenario.sender.full_name,
            self.scenario.traveler.email,
            self.scenario.delivery_request.title,
            self.scenario.delivery_request.pickup_location.public_label,
            self.scenario.delivery_request.pickup_location.private_label,
            self.scenario.delivery_request.delivery_location.private_label,
            str(self.order.public_reference),
            # L11A: the parcel's tracking number is never on the guest surface.
            self.scenario.delivery_request.tracking_number,
            "WSL-",
            "tracking_number",
        ):
            assert str(secret) not in body, secret

        # Identifiers are absent structurally, not by substring luck: the
        # payload has exactly six keys and none of them is an id.
        assert set(response.data) == {
            "amount_eur_cents",
            "currency",
            "purpose",
            "description",
            "expires_at",
            "providers",
            "receipt_email_required",
        }
        assert not any(
            key.endswith("_id") or key == "id" for key in response.data
        )

    def test_a_guessed_token_is_indistinguishable_from_an_expired_one(self):
        guessed = self._get(secrets.token_urlsafe(32))

        GuestPaymentLink.objects.filter(pk=self.issued.link.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        expired = self._get(self.token)

        assert guessed.status_code == expired.status_code == 404
        assert guessed.data == expired.data
        assert expired.data["code"] == "guest_link_invalid"

    def test_a_revoked_token_stops_working_immediately(self):
        self.client_for(self.scenario.sender).post(
            reverse(
                "finance-order-guest-link-revoke",
                args=[str(self.order.public_reference)],
            )
        )

        assert self._get(self.token).status_code == 404

    def test_a_link_for_a_closed_order_stops_working(self):
        from apps.finance.services import cancel_order

        cancel_order(order_id=self.order.pk, reason="test")

        assert self._get(self.token).status_code == 404

    def test_a_wildly_long_token_is_rejected_without_a_lookup(self):
        with self.assertRaises(GuestLinkInvalid):
            resolve_guest_link("x" * 5_000)


class GuestCheckoutTests(GuestPaymentTestCase):
    def test_a_guest_can_open_a_checkout_and_see_only_the_amount(self):
        response = self.guest.post(
            reverse("finance-guest-checkout", args=[self.token]),
            {"provider": "mock"},
            format="json",
        )

        assert response.status_code == 201, response.data
        assert set(response.data) == {
            "checkout_url",
            "amount_eur_cents",
            "payment_currency",
            "provider",
            "expires_at",
        }
        attempt = PaymentAttempt.objects.get(order=self.order)
        assert attempt.payer_id is None
        assert attempt.guest_link_id == self.issued.link.pk

    def test_a_guest_payment_funds_the_senders_deal(self):
        self.guest.post(
            reverse("finance-guest-checkout", args=[self.token]),
            {"provider": "mock"},
            format="json",
        )
        attempt = PaymentAttempt.objects.get(order=self.order)

        deliver_mock_webhook(self.client, succeed_attempt(attempt))

        self.order.refresh_from_db()
        deal = Deal.objects.get(pk=self.scenario.deal.pk)
        assert self.order.status == PaymentOrder.Status.PAID
        assert deal.status == Deal.Status.FUNDED
        # The Deal still belongs to the sender and the traveler only.
        assert deal.sender_id == self.scenario.sender.pk
        assert deal.traveler_id == self.scenario.traveler.pk

    def test_a_guest_link_is_single_use(self):
        self.guest.post(
            reverse("finance-guest-checkout", args=[self.token]),
            {"provider": "mock"},
            format="json",
        )
        attempt = PaymentAttempt.objects.get(order=self.order)
        deliver_mock_webhook(self.client, succeed_attempt(attempt))

        assert self.guest.get(
            reverse("finance-guest-payment", args=[self.token])
        ).status_code == 404
        link = GuestPaymentLink.objects.get(pk=self.issued.link.pk)
        assert link.consumed_at is not None

    def test_a_guest_cannot_choose_the_amount(self):
        response = self.guest.post(
            reverse("finance-guest-checkout", args=[self.token]),
            {"provider": "mock", "amount_eur_cents": 1},
            format="json",
        )

        assert response.status_code == 400
        assert PaymentAttempt.objects.filter(order=self.order).count() == 0

    def test_a_guest_cannot_pay_a_different_order(self):
        other = build_scenario(prefix="guest-other")
        other.accept()
        other_order = other.balance_order()

        self.guest.post(
            reverse("finance-guest-checkout", args=[self.token]),
            {"provider": "mock"},
            format="json",
        )

        assert PaymentAttempt.objects.filter(order=other_order).count() == 0
        assert PaymentAttempt.objects.get().order_id == self.order.pk


class GuestAuthorityDenialTests(GuestPaymentTestCase):
    """Paying is not membership. Every authenticated surface stays shut."""

    def test_the_guest_surface_grants_no_session(self):
        response = self.guest.get(reverse("finance-guest-payment", args=[self.token]))

        assert response.status_code == 200
        assert "sessionid" not in response.cookies
        assert "Authorization" not in response

    def test_a_guest_cannot_read_the_deal(self):
        response = self.guest.get(
            reverse("deals-detail", args=[self.scenario.deal.pk])
        )

        assert response.status_code in (401, 403)

    def test_a_guest_cannot_read_the_payment_order(self):
        response = self.guest.get(
            reverse(
                "finance-order-detail", args=[str(self.order.public_reference)]
            )
        )

        assert response.status_code in (401, 403)

    def test_a_guest_cannot_cancel_the_deal(self):
        response = self.guest.post(
            reverse("deals-cancel", args=[self.scenario.deal.pk])
        )

        assert response.status_code in (401, 403)
        assert Deal.objects.get(pk=self.scenario.deal.pk).status != (
            Deal.Status.CANCELLED
        )

    def test_a_guest_cannot_open_chat_on_the_match(self):
        response = self.guest.get(
            reverse("matches-chat-eligibility", args=[self.scenario.deal.match_id])
        )

        assert response.status_code in (401, 403)

    def test_a_guest_cannot_list_payouts_or_orders(self):
        assert self.guest.get(reverse("finance-payouts")).status_code in (401, 403)
        assert self.guest.get(reverse("finance-orders")).status_code in (401, 403)

    def test_a_guest_cannot_request_a_refund(self):
        response = self.guest.post(
            reverse(
                "finance-admin-refund", args=[str(self.order.public_reference)]
            ),
            {"attempt_id": 1, "amount_eur_cents": 1, "reason": "admin"},
            format="json",
        )

        assert response.status_code in (401, 403)

    def test_paying_does_not_add_the_guest_to_the_deal(self):
        self.guest.post(
            reverse("finance-guest-checkout", args=[self.token]),
            {"provider": "mock"},
            format="json",
        )
        attempt = PaymentAttempt.objects.get(order=self.order)
        deliver_mock_webhook(self.client, succeed_attempt(attempt))

        deal = Deal.objects.get(pk=self.scenario.deal.pk)
        assert deal.sender_id == self.scenario.sender.pk
        assert deal.traveler_id == self.scenario.traveler.pk
        # There is no user row for the guest at all.
        assert attempt.payer_id is None


class CheckoutRecheckTests(GuestPaymentTestCase):
    """G1: checkout reads the link again, under the order lock.

    The link a caller passes in is a snapshot from an unlocked read. Whatever
    has happened to it since -- revoked, replaced, expired, used, its order
    closed -- and whichever order the caller pairs it with, the locked re-read
    decides, and every refusal is the same `guest_link_invalid`.
    """

    def start(self, link, order=None):
        return start_checkout(
            order_id=(order or self.order).pk,
            provider="mock",
            actor_id=None,
            guest_link=link,
            guest_email="",
        )

    def assert_refused(self, link, order=None):
        with self.assertRaises(GuestLinkInvalid):
            self.start(link, order)
        assert not PaymentAttempt.objects.filter(order=self.order).exists()

    def test_a_live_link_opens_the_checkout(self):
        attempt = self.start(resolve_guest_link(self.token)).attempt
        assert attempt.guest_link_id == self.issued.link.pk
        assert attempt.payer_id is None

    def test_a_link_revoked_since_it_was_read_is_refused(self):
        snapshot = resolve_guest_link(self.token)
        revoke_guest_link(order_id=self.order.pk, actor_id=self.scenario.sender.pk)
        self.assert_refused(snapshot)

    def test_a_link_replaced_since_it_was_read_is_refused(self):
        snapshot = resolve_guest_link(self.token)
        create_guest_link(order_id=self.order.pk, actor_id=self.scenario.sender.pk)
        self.assert_refused(snapshot)

    def test_a_link_expired_since_it_was_read_is_refused(self):
        snapshot = resolve_guest_link(self.token)
        GuestPaymentLink.objects.filter(pk=snapshot.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assert_refused(snapshot)

    def test_a_link_used_since_it_was_read_is_refused(self):
        snapshot = resolve_guest_link(self.token)
        GuestPaymentLink.objects.filter(pk=snapshot.pk).update(
            consumed_at=timezone.now()
        )
        self.assert_refused(snapshot)

    def test_a_link_whose_order_closed_is_refused_in_the_same_words(self):
        snapshot = resolve_guest_link(self.token)
        cancel_order(order_id=self.order.pk, reason="g1 test")
        self.assert_refused(snapshot)

    def test_a_link_pays_only_its_own_order(self):
        other = build_scenario(prefix="guest-recheck")
        other.accept()
        other_order = other.balance_order()

        self.assert_refused(resolve_guest_link(self.token), order=other_order)
        assert not PaymentAttempt.objects.filter(order=other_order).exists()

    def test_the_owners_own_checkout_needs_no_link(self):
        revoke_guest_link(order_id=self.order.pk, actor_id=self.scenario.sender.pk)
        attempt = open_mock_checkout(self.order, actor_id=self.scenario.sender.pk)
        assert attempt.guest_link_id is None
        assert attempt.payer_id == self.scenario.sender.pk

    def test_the_apps_guest_checkout_gets_the_same_recheck(self):
        real_resolve = finance_views.resolve_guest_link

        def resolve_then_revoke(token):
            link = real_resolve(token)
            revoke_guest_link(
                order_id=self.order.pk, actor_id=self.scenario.sender.pk
            )
            return link

        with mock.patch.object(
            finance_views, "resolve_guest_link", side_effect=resolve_then_revoke
        ):
            response = self.guest.post(
                reverse("finance-guest-checkout", args=[self.token]),
                {"provider": "mock"},
                format="json",
            )

        assert response.status_code == 404
        assert response.data["code"] == "guest_link_invalid"
        assert not PaymentAttempt.objects.filter(order=self.order).exists()


class WorkerLost(BaseException):
    """A process dying mid-request: nothing in the request catches it."""


class OpenCheckoutTests(GuestPaymentTestCase):
    """G1, third pass: an order never has two checkouts that can collect.

    A link can be held by more than one person, and nothing a holder sends
    tells the one who opened a checkout from another, so no guest is handed an
    open checkout: each tap replaces it, and every holder is answered alike.
    An open checkout is replaced only once its provider confirms it can no
    longer collect; otherwise the caller is told a payment is under way. A
    checkout whose request died is recovered under its own key first. Only the
    member who opened a checkout is handed it again.
    """

    def setUp(self):
        super().setUp()
        MockGateway.reset()
        self.endpoint = reverse("finance-guest-checkout", args=[self.token])

    def start(self, email=""):
        return start_checkout(
            order_id=self.order.pk,
            provider="mock",
            actor_id=None,
            guest_link=resolve_guest_link(self.token),
            guest_email=email,
        )

    def owner_starts(self):
        return start_checkout(
            order_id=self.order.pk, provider="mock", actor_id=self.scenario.sender.pk
        )

    def attempts(self):
        return PaymentAttempt.objects.filter(order=self.order)

    def assert_only_payable(self, live):
        """`live` is the order's one open attempt and the one checkout anyone can pay."""

        assert list(
            self.attempts().filter(status__in=PaymentAttempt.OPEN_STATUSES)
        ) == [live]
        payable = [
            session
            for session in MockGateway.checkout_session_ids()
            if MockGateway.is_payable(session)
        ]
        assert payable == [live.provider_session_id]

    def age_past_the_opening_window(self, attempt):
        """As if the request that owns `attempt` died: its claim has lapsed."""

        PaymentAttempt.objects.filter(pk=attempt.pk).update(
            opening_until=timezone.now() - timedelta(seconds=1)
        )

    def expire(self, attempt):
        """Run `attempt`'s own expiry job, as the worker does once it is due."""

        PaymentAttempt.objects.filter(pk=attempt.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        return jobs.handle_attempt_expiry({"attempt_id": attempt.pk})

    def lose_a_checkout(self, who):
        """`who` taps and its request dies at the provider, storing nothing."""

        with (
            mock.patch.object(MockGateway, "create_checkout", side_effect=WorkerLost),
            self.assertRaises(WorkerLost),
        ):
            who()
        return self.attempts().get(status=PaymentAttempt.Status.CREATED)

    @override_settings(TRANSACTIONAL_EMAIL_ENABLED=True)
    def test_another_holder_replaces_the_checkout_once_it_is_closed(self):
        first = self.start("aunt@example.com").attempt

        second = self.start("stranger@example.com")

        replaced = PaymentAttempt.objects.get(pk=first.pk)
        assert replaced.status == PaymentAttempt.Status.CANCELLED
        assert replaced.failure_code == "superseded"
        assert not MockGateway.is_payable(first.provider_session_id)
        assert second.created is True
        assert second.attempt.checkout_url != first.checkout_url
        assert second.attempt.guest_email == "stranger@example.com"
        self.assert_only_payable(second.attempt)

    @override_settings(TRANSACTIONAL_EMAIL_ENABLED=True)
    def test_the_address_a_holder_sends_changes_nothing_they_are_told(self):
        """Knowing the first holder's address earns nothing: every holder,
        whatever they send, gets a checkout of their own, never the first."""

        first = self.guest.post(
            self.endpoint,
            {"provider": "mock", "email": "aunt@example.com"},
            format="json",
        )
        assert first.status_code == 201
        seen = {first.data["checkout_url"]}

        for email in ("aunt@example.com", "Aunt@Example.com", "stranger@example.com"):
            with self.subTest(email):
                again = APIClient().post(
                    self.endpoint, {"provider": "mock", "email": email}, format="json"
                )
                assert again.status_code == 201
                assert set(again.data) == set(first.data)
                assert again.data["checkout_url"] not in seen
                seen.add(again.data["checkout_url"])

        self.assert_only_payable(
            self.attempts().get(status__in=PaymentAttempt.OPEN_STATUSES)
        )

    def test_a_checkout_its_provider_cannot_close_is_not_replaced(self):
        first = self.start().attempt

        for error in (ProviderUnavailable("timed out"), ProviderError("refused")):
            MockGateway.fail_close(first.provider_session_id, error)
            for who in (self.start, self.owner_starts):
                with self.subTest(error=type(error).__name__, who=who.__name__):
                    with self.assertRaises(CheckoutInProgress):
                        who()
        response = APIClient().post(self.endpoint, {"provider": "mock"}, format="json")

        assert response.status_code == 409
        assert response.data["code"] == "checkout_in_progress"
        assert "checkout_url" not in response.data
        kept = self.attempts().get()
        assert kept.pk == first.pk
        assert kept.status == PaymentAttempt.Status.CHECKOUT_PENDING
        self.assert_only_payable(kept)

    def test_a_checkout_that_took_a_payment_is_not_replaced(self):
        first = self.start().attempt
        # Paid at the provider; its webhook has not arrived yet.
        MockGateway.mark(first.provider_session_id, "succeeded")

        with self.assertRaises(CheckoutInProgress):
            self.start()

        kept = self.attempts().get()
        assert kept.pk == first.pk
        assert kept.status in PaymentAttempt.OPEN_STATUSES
        assert deliver_mock_webhook(self.client, succeed_attempt(kept)).status_code == 200
        self.order.refresh_from_db()
        assert self.order.status == PaymentOrder.Status.PAID

    def test_a_payment_settling_is_never_replaced(self):
        first = self.owner_starts().attempt
        # A delayed method was authorised; its success or failure follows.
        reconcile_attempt(attempt_id=first.pk, outcome="processing")

        for who in (self.start, self.owner_starts):
            with self.subTest(who.__name__), self.assertRaises(CheckoutInProgress):
                who()

        # Its expiry leaves it to that outcome as well.
        assert self.expire(first) == "attempt_settling"
        kept = self.attempts().get()
        assert kept.status == PaymentAttempt.Status.PROCESSING
        assert MockGateway.is_payable(kept.provider_session_id)
        assert MockGateway.checkout_session_ids() == [kept.provider_session_id]
        MockGateway.mark(kept.provider_session_id, "succeeded")
        assert deliver_mock_webhook(self.client, succeed_attempt(kept)).status_code == 200
        self.order.refresh_from_db()
        assert self.order.status == PaymentOrder.Status.PAID

    def test_a_checkout_closed_in_this_request_is_never_handed_out(self):
        """Closed because the amount due no longer matched it, then matching
        again by the time the request looks once more: still replaced, never
        handed back with a URL its provider has closed."""

        first = self.owner_starts().attempt
        PaymentAttempt.objects.filter(pk=first.pk).update(
            amount_eur_cents=F("amount_eur_cents") + 1
        )
        real_close = MockGateway.close_checkout

        def closes_then_amount_matches_again(gateway, *, provider_session_id):
            outcome = real_close(gateway, provider_session_id=provider_session_id)
            PaymentAttempt.objects.filter(pk=first.pk).update(
                amount_eur_cents=F("amount_eur_cents") - 1
            )
            return outcome

        with mock.patch.object(
            MockGateway, "close_checkout", new=closes_then_amount_matches_again
        ):
            second = self.owner_starts()

        assert second.created is True
        assert second.attempt.checkout_url != first.checkout_url
        first.refresh_from_db()
        assert first.status == PaymentAttempt.Status.CANCELLED
        self.assert_only_payable(second.attempt)

    def test_the_owner_is_handed_their_own_checkout_again(self):
        first = self.owner_starts().attempt

        again = self.owner_starts()

        assert again.created is False
        assert again.attempt.pk == first.pk
        assert again.attempt.checkout_url == first.checkout_url
        assert MockGateway.checkout_session_ids() == [first.provider_session_id]

    def test_the_owner_on_another_amount_or_a_lapsed_checkout_closes_it_first(self):
        lapsed = {"expires_at": timezone.now() - timedelta(seconds=1)}
        # What the next tap sees after the amount due changed.
        repriced = {"amount_eur_cents": F("amount_eur_cents") + 1}
        for change in (lapsed, repriced):
            with self.subTest(sorted(change)):
                first = self.owner_starts().attempt
                PaymentAttempt.objects.filter(pk=first.pk).update(**change)

                second = self.owner_starts()

                assert second.created is True
                assert not MockGateway.is_payable(first.provider_session_id)
                self.assert_only_payable(second.attempt)

    def test_a_checkout_still_opening_keeps_its_key_and_answers_try_again(self):
        real_create = MockGateway.create_checkout
        during = []

        def others_tap_meanwhile(gateway, request):
            if not during:
                during.append("entered")
                for who in (self.start, self.owner_starts):
                    with self.assertRaises(CheckoutInProgress):
                        who()
                during.append(
                    list(
                        self.attempts().values_list(
                            "status", "checkout_url", "idempotency_key"
                        )
                    )
                )
            return real_create(gateway, request)

        with mock.patch.object(
            MockGateway, "create_checkout", new=others_tap_meanwhile
        ):
            first = self.start().attempt

        assert during[1] == [("created", "", first.idempotency_key)]
        assert first.checkout_url
        assert self.attempts().count() == 1
        assert MockGateway.checkout_session_ids() == [first.provider_session_id]
        retry = self.start()
        assert retry.created is True
        assert not MockGateway.is_payable(first.provider_session_id)
        self.assert_only_payable(retry.attempt)

    def test_a_checkout_whose_worker_died_is_recovered_not_opened_twice(self):
        real_create = MockGateway.create_checkout
        sent = []

        def opens_then_dies(gateway, request):
            sent.append(request)
            result = real_create(gateway, request)
            if len(sent) == 1:
                # The provider opened it; the process died before storing it.
                raise WorkerLost
            return result

        with mock.patch.object(MockGateway, "create_checkout", new=opens_then_dies):
            with self.assertRaises(WorkerLost):
                self.owner_starts()
            lost = self.attempts().get()
            assert lost.status == PaymentAttempt.Status.CREATED
            assert lost.checkout_url == ""
            with self.assertRaises(CheckoutInProgress):
                self.owner_starts()
            self.age_past_the_opening_window(lost)

            session = self.owner_starts()

        assert session.created is False
        assert session.attempt.pk == lost.pk
        assert session.attempt.status == PaymentAttempt.Status.CHECKOUT_PENDING
        assert MockGateway.checkout_session_ids() == [
            session.attempt.provider_session_id
        ]
        # Recovered under the same key with exactly the same parameters.
        assert len(sent) == 2 and sent[1] == sent[0]

    def test_a_guest_checkout_whose_worker_died_is_recovered_then_closed(self):
        real_create = MockGateway.create_checkout
        sent = []

        def opens_then_dies(gateway, request):
            sent.append(request)
            result = real_create(gateway, request)
            if len(sent) == 1:
                raise WorkerLost
            return result

        with mock.patch.object(MockGateway, "create_checkout", new=opens_then_dies):
            with self.assertRaises(WorkerLost):
                self.start()
            lost = self.attempts().get()
            self.age_past_the_opening_window(lost)

            session = self.start()

        lost.refresh_from_db()
        assert sent[1] == sent[0]
        assert lost.status == PaymentAttempt.Status.CANCELLED
        assert lost.provider_session_id == MockGateway.checkout_session_ids()[0]
        assert not MockGateway.is_payable(lost.provider_session_id)
        assert len(MockGateway.checkout_session_ids()) == 2
        self.assert_only_payable(session.attempt)

    def test_one_request_at_a_time_recovers_a_lost_checkout(self):
        """A second request while the first repeats the lost checkout's
        create is asked to wait and calls no provider: the provider never sees
        the key twice at once (Stripe refuses that) and keeps one checkout."""

        real_create = MockGateway.create_checkout
        sent = []
        during = []

        def opens_then_dies(gateway, request):
            sent.append(request.idempotency_key)
            if len(sent) == 1:
                real_create(gateway, request)
                raise WorkerLost
            if len(sent) == 2:
                for who in (self.start, self.owner_starts):
                    with self.assertRaises(CheckoutInProgress):
                        who()
                    during.append(who.__name__)
            else:
                raise ProviderCheckoutRejected("key already in use")
            return real_create(gateway, request)

        with mock.patch.object(MockGateway, "create_checkout", new=opens_then_dies):
            with self.assertRaises(WorkerLost):
                self.owner_starts()
            lost = self.attempts().get()
            self.age_past_the_opening_window(lost)

            session = self.owner_starts()

        assert during == ["start", "owner_starts"]
        assert sent == [lost.idempotency_key, lost.idempotency_key]
        assert session.created is False and session.attempt.pk == lost.pk
        assert self.attempts().count() == 1
        self.assert_only_payable(session.attempt)

    def test_a_lost_checkout_that_cannot_be_recovered(self):
        """Unreachable, the caller waits. Refused for good, or on a rail with
        nothing to recover it by, it is abandoned: its URL, if a checkout was
        opened at all, never left the server, so no one can pay it."""

        with (
            mock.patch.object(MockGateway, "create_checkout", side_effect=WorkerLost),
            self.assertRaises(WorkerLost),
        ):
            self.owner_starts()
        lost = self.attempts().get()
        self.age_past_the_opening_window(lost)

        with (
            mock.patch.object(
                MockGateway,
                "create_checkout",
                side_effect=ProviderUnavailable("timed out"),
            ),
            self.assertRaises(CheckoutInProgress),
        ):
            self.owner_starts()
        assert self.attempts().get().status == PaymentAttempt.Status.CREATED
        # An unreachable provider releases the claim: the next tap tries the
        # same key again at once instead of waiting out the window.
        with (
            mock.patch.object(
                MockGateway,
                "create_checkout",
                side_effect=ProviderUnavailable("timed out"),
            ) as create,
            self.assertRaises(CheckoutInProgress),
        ):
            self.owner_starts()
        assert [call.args[0].idempotency_key for call in create.call_args_list] == [
            lost.idempotency_key
        ]
        assert self.attempts().get().status == PaymentAttempt.Status.CREATED

        real_create = MockGateway.create_checkout

        def refuses_the_lost_key(gateway, request):
            if request.idempotency_key == lost.idempotency_key:
                raise ProviderCheckoutRejected("refused")
            return real_create(gateway, request)

        with mock.patch.object(
            MockGateway, "create_checkout", new=refuses_the_lost_key
        ):
            session = self.owner_starts()
        lost.refresh_from_db()
        assert lost.status == PaymentAttempt.Status.CANCELLED
        assert lost.failure_code == "superseded"
        assert session.created is True
        self.assert_only_payable(session.attempt)

        with (
            mock.patch.object(MockGateway, "create_checkout", side_effect=WorkerLost),
            self.assertRaises(WorkerLost),
        ):
            self.start()
        unknown = self.attempts().get(status=PaymentAttempt.Status.CREATED)
        self.age_past_the_opening_window(unknown)
        recorded = []

        def recording(gateway, request):
            recorded.append(request.idempotency_key)
            return real_create(gateway, request)

        with (
            mock.patch(
                "apps.finance.services.RECOVERABLE_CHECKOUT_PROVIDERS", frozenset()
            ),
            mock.patch.object(MockGateway, "create_checkout", new=recording),
        ):
            last = self.start()
        unknown.refresh_from_db()
        assert unknown.status == PaymentAttempt.Status.CANCELLED
        assert recorded == [last.attempt.idempotency_key]

    def test_a_checkout_replaced_while_opening_is_never_handed_out(self):
        """The guest's provider call outlives the opening window, and the owner
        pays meanwhile: the owner recovers the guest's checkout, closes it and
        replaces it. The guest is answered a retryable 409, never a URL, and
        the guest's retry closes the owner's checkout before opening its own."""

        real_create = MockGateway.create_checkout
        owners = []

        def owner_pays_meanwhile(gateway, request):
            if not owners:
                owners.append("entered")
                self.age_past_the_opening_window(
                    self.attempts().get(guest_link=self.issued.link)
                )
                owners.append(self.owner_starts().attempt)
            return real_create(gateway, request)

        with mock.patch.object(
            MockGateway, "create_checkout", new=owner_pays_meanwhile
        ):
            response = self.guest.post(
                self.endpoint, {"provider": "mock"}, format="json"
            )

        assert response.status_code == 409
        assert response.data["code"] == "checkout_in_progress"
        assert "checkout_url" not in response.data
        guest_attempt = self.attempts().get(guest_link=self.issued.link)
        assert guest_attempt.status == PaymentAttempt.Status.CANCELLED
        assert not MockGateway.is_payable(guest_attempt.provider_session_id)
        owner_attempt = owners[1]
        assert owner_attempt.payer_id == self.scenario.sender.pk
        self.assert_only_payable(owner_attempt)

        retry = self.guest.post(self.endpoint, {"provider": "mock"}, format="json")

        assert retry.status_code == 201
        assert not MockGateway.is_payable(owner_attempt.provider_session_id)
        live = self.attempts().get(status__in=PaymentAttempt.OPEN_STATUSES)
        assert live.guest_link_id == self.issued.link.pk
        assert retry.data["checkout_url"] == live.checkout_url
        self.assert_only_payable(live)

    # --- fourth pass: expiry, history, recovery claims -----------------------

    def test_expiry_closes_the_checkout_before_the_order_takes_another(self):
        """Our expiry is not the provider's: a checkout handed out stays
        payable at its provider until it is closed there. The expiry job
        closes it first, so the next payer never opens one beside it."""

        first = self.owner_starts().attempt

        assert self.expire(first) == "attempt_expired"

        first.refresh_from_db()
        assert first.status == PaymentAttempt.Status.EXPIRED
        assert not MockGateway.is_payable(first.provider_session_id)
        second = self.start()
        assert second.created is True
        self.assert_only_payable(second.attempt)

    def test_expiry_keeps_a_checkout_its_provider_has_not_closed(self):
        first = self.owner_starts().attempt
        MockGateway.fail_close(first.provider_session_id, ProviderUnavailable("down"))

        with self.assertRaises(jobs.RetryableJobError):
            self.expire(first)

        kept = self.attempts().get()
        assert kept.pk == first.pk
        assert kept.status == PaymentAttempt.Status.CHECKOUT_PENDING
        assert kept.close_requested_at is not None
        # Being closed, it is handed to no one, its own payer included, and
        # nothing replaces it.
        for who in (self.start, self.owner_starts):
            with self.subTest(who.__name__), self.assertRaises(CheckoutInProgress):
                who()
        self.assert_only_payable(kept)

        # The job's next run, once the provider answers, finishes the close.
        MockGateway.fail_close(first.provider_session_id, None)
        assert self.expire(kept) == "attempt_expired"
        second = self.start()
        assert second.created is True
        self.assert_only_payable(second.attempt)

    def test_a_payment_taken_before_its_webhook_holds_off_expiry_and_replacement(self):
        """Authorised and settling at the provider, its webhook not here yet:
        the provider refuses to close it, so nothing ends or replaces it."""

        first = self.start().attempt
        MockGateway.mark(first.provider_session_id, "processing")

        for who in (self.start, self.owner_starts):
            with self.subTest(who.__name__), self.assertRaises(CheckoutInProgress):
                who()
        assert self.expire(first) == "attempt_collecting"

        kept = self.attempts().get()
        assert kept.pk == first.pk
        assert kept.status == PaymentAttempt.Status.CHECKOUT_PENDING
        self.assert_only_payable(kept)
        MockGateway.mark(kept.provider_session_id, "succeeded")
        assert deliver_mock_webhook(self.client, succeed_attempt(kept)).status_code == 200
        self.order.refresh_from_db()
        assert self.order.status == PaymentOrder.Status.PAID

    def test_expiry_waits_for_the_request_still_opening_a_checkout(self):
        lost = self.lose_a_checkout(self.owner_starts)

        with self.assertRaises(jobs.JobDeferred):
            self.expire(lost)
        assert self.attempts().get().status == PaymentAttempt.Status.CREATED

        self.age_past_the_opening_window(lost)
        assert self.expire(lost) == "attempt_expired"

    def test_no_order_history_carries_a_checkout_url(self):
        """Only the checkout endpoint hands a checkout out, because only it
        decides who may have it. The owner's history shows neither their own
        open checkout's URL nor a guest's, with its receipt address."""

        owner = self.client_for(self.scenario.sender)
        reference = str(self.order.public_reference)
        own = owner.post(
            reverse("finance-order-checkout", args=[reference]),
            {"provider": "mock"},
            format="json",
        )
        assert own.status_code == 201 and own.data["checkout_url"]
        theirs = self.guest.post(self.endpoint, {"provider": "mock"}, format="json")
        assert theirs.status_code == 201

        detail = owner.get(reverse("finance-order-detail", args=[reference]))

        assert detail.status_code == 200
        assert len(detail.data["attempts"]) == 2
        assert all("checkout_url" not in row for row in detail.data["attempts"])
        body = json.dumps(detail.data, default=str)
        assert own.data["checkout_url"] not in body
        assert theirs.data["checkout_url"] not in body

    def test_the_reconciliation_job_never_reopens_a_lost_checkout(self):
        """A checkout no one stored was never handed out, so no one paid it:
        the job asks the provider nothing and brings back no URL."""

        lost = self.lose_a_checkout(self.owner_starts)

        with mock.patch.object(MockGateway, "create_checkout") as create:
            with self.assertRaises(jobs.JobDeferred):
                jobs.handle_provider_reconcile({"attempt_id": lost.pk})
            self.age_past_the_opening_window(lost)
            assert self.expire(lost) == "attempt_expired"
            assert (
                jobs.handle_provider_reconcile({"attempt_id": lost.pk})
                == "checkout_never_handed_out"
            )

        create.assert_not_called()
        lost.refresh_from_db()
        assert (lost.provider_session_id, lost.checkout_url) == ("", "")
        # Nor can staff queue one for it: there is nothing to learn.
        with self.assertRaises(FinanceOperationsError) as refused:
            queue_payment_reconciliation(attempt_id=lost.pk)
        assert refused.exception.code == "checkout_never_handed_out"

    def test_a_recovery_that_finds_its_attempt_ended_stores_and_shows_nothing(self):
        lost = self.lose_a_checkout(self.owner_starts)
        real_create = MockGateway.create_checkout

        def order_cancelled_meanwhile(gateway, request):
            result = real_create(gateway, request)
            cancel_order(order_id=self.order.pk, reason="deal_cancelled")
            return result

        with mock.patch.object(
            MockGateway, "create_checkout", new=order_cancelled_meanwhile
        ):
            assert recover_checkout_attempt(attempt_id=lost.pk) == "checkout_abandoned"

        lost.refresh_from_db()
        assert lost.status == PaymentAttempt.Status.CANCELLED
        assert (lost.provider_session_id, lost.checkout_url) == ("", "")
        sessions = MockGateway.checkout_session_ids()
        assert len(sessions) == 1
        assert not MockGateway.is_payable(sessions[0])

    def test_a_checkout_stored_after_its_recovery_was_refused_is_closed_first(self):
        """The owner's slow request stores its checkout just after a guest's
        recovery of it was refused. The guest closes it at the provider before
        opening its own: it never drops a checkout that can still be paid."""

        real_create = MockGateway.create_checkout
        keys = []
        guest = []

        def slow_owner(gateway, request):
            keys.append(request.idempotency_key)
            if len(keys) == 1:
                # The owner's create is out past its window; a guest taps.
                self.age_past_the_opening_window(self.attempts().get())
                guest.append(self.start())
            elif len(keys) == 2:
                # The guest's recovery under the owner's key. The owner's
                # answer arrives and is stored before this refusal does.
                result = real_create(gateway, request)
                PaymentAttempt.objects.filter(
                    idempotency_key=request.idempotency_key
                ).update(
                    provider_session_id=result.provider_session_id,
                    checkout_url=result.checkout_url,
                    status=PaymentAttempt.Status.CHECKOUT_PENDING,
                )
                raise ProviderCheckoutRejected("refused")
            return real_create(gateway, request)

        with (
            mock.patch.object(MockGateway, "create_checkout", new=slow_owner),
            self.assertRaises(CheckoutInProgress),
        ):
            self.owner_starts()

        assert keys[1] == keys[0]
        owners = PaymentAttempt.objects.get(idempotency_key=keys[0])
        assert owners.status == PaymentAttempt.Status.CANCELLED
        assert not MockGateway.is_payable(owners.provider_session_id)
        assert guest[0].created is True
        assert guest[0].attempt.guest_link_id == self.issued.link.pk
        self.assert_only_payable(guest[0].attempt)

    def test_a_create_whose_answer_was_lost_is_recovered_not_opened_twice(self):
        """The provider opened the checkout and its answer timed out: the
        attempt keeps its key, and the next tap gets that checkout back."""

        real_create = MockGateway.create_checkout

        def opens_then_times_out(gateway, request):
            real_create(gateway, request)
            raise ProviderUnavailable("read timed out")

        with (
            mock.patch.object(
                MockGateway, "create_checkout", new=opens_then_times_out
            ),
            self.assertRaises(ProviderUnavailable),
        ):
            self.owner_starts()
        kept = self.attempts().get()
        assert kept.status == PaymentAttempt.Status.CREATED
        assert kept.checkout_url == ""

        session = self.owner_starts()

        assert session.created is False
        assert session.attempt.pk == kept.pk
        assert MockGateway.checkout_session_ids() == [
            session.attempt.provider_session_id
        ]
        self.assert_only_payable(session.attempt)

    def test_a_lost_checkout_is_recovered_after_the_public_address_changed(self):
        """The request is frozen on the attempt, so a recovery after a restart
        with other settings still sends the provider exactly the first one."""

        real_create = MockGateway.create_checkout
        sent = []

        def opens_then_dies(gateway, request):
            sent.append(request)
            result = real_create(gateway, request)
            if len(sent) == 1:
                raise WorkerLost
            return result

        with mock.patch.object(MockGateway, "create_checkout", new=opens_then_dies):
            with self.assertRaises(WorkerLost):
                self.owner_starts()
            lost = self.attempts().get()
            self.age_past_the_opening_window(lost)
            with override_settings(PAYMENTS_PUBLIC_BASE_URL="https://moved.invalid"):
                session = self.owner_starts()

        assert "moved.invalid" not in sent[0].success_url
        assert sent[1] == sent[0]
        assert session.created is False and session.attempt.pk == lost.pk
        assert MockGateway.checkout_session_ids() == [
            session.attempt.provider_session_id
        ]

    def test_a_close_whose_request_died_is_finished_never_handed_out(self):
        """The guest's request dies just after the provider closed the owner's
        checkout. The owner's next tap is not handed that closed checkout: it
        finishes the close and opens a new one."""

        first = self.owner_starts().attempt
        real_close = MockGateway.close_checkout

        def closes_then_dies(gateway, *, provider_session_id):
            real_close(gateway, provider_session_id=provider_session_id)
            raise WorkerLost

        with (
            mock.patch.object(MockGateway, "close_checkout", new=closes_then_dies),
            self.assertRaises(WorkerLost),
        ):
            self.start()
        assert not MockGateway.is_payable(first.provider_session_id)
        assert self.attempts().get().close_requested_at is not None

        again = self.owner_starts()

        assert again.created is True
        assert again.attempt.checkout_url != first.checkout_url
        self.assert_only_payable(again.attempt)

    @override_settings(TRANSACTIONAL_EMAIL_ENABLED=False)
    def test_with_receipts_off_no_surface_keeps_or_sends_an_address(self):
        real_create = MockGateway.create_checkout
        sent = []

        def recording(gateway, request):
            sent.append(request.customer_email)
            return real_create(gateway, request)

        with mock.patch.object(MockGateway, "create_checkout", new=recording):
            api = self.guest.post(
                self.endpoint,
                {"provider": "mock", "email": "someone@example.com"},
                format="json",
            )
            self.start("someone@example.com")

        assert api.status_code == 201
        assert sent == ["", ""]
        assert set(self.attempts().values_list("guest_email", flat=True)) == {""}

        # Nor does the provider's completion, which carries the address the
        # payer typed on its page: no address is kept and no receipt is owed.
        live = self.attempts().get(status__in=PaymentAttempt.OPEN_STATUSES)
        completion = mock_event_body(
            event_id=f"evt_{live.pk}_paid",
            outcome="succeeded",
            session_id=live.provider_session_id,
            payment_id=f"{live.provider_session_id}_pi",
            reference=str(self.order.public_reference),
            amount=int(live.provider_amount_minor),
            currency=live.payment_currency,
            event_type="checkout.paid",
            guest_email="someone@example.com",
        )
        assert deliver_mock_webhook(self.client, completion).status_code == 200
        live.refresh_from_db()
        assert live.status == PaymentAttempt.Status.SUCCEEDED
        assert live.guest_email == ""
        assert not OutboundMessage.objects.filter(
            kind=OutboundMessage.Kind.GUEST_PAYMENT
        ).exists()
        # Nor is it kept on the stored event, raw or normalised.
        stored = PaymentProviderEvent.objects.get(provider_event_id=f"evt_{live.pk}_paid")
        assert stored.normalized_event["guest_email"] == ""
        assert "someone@example.com" not in json.dumps(
            [stored.normalized_event, stored.payload]
        )

    # -- fifth pass ----------------------------------------------------------

    def test_a_late_event_from_an_abandoned_checkout_never_ends_the_one_opening(self):
        real_create = MockGateway.create_checkout

        def opens_then_dies(gateway, request):
            real_create(gateway, request)
            raise WorkerLost

        with (
            mock.patch.object(MockGateway, "create_checkout", new=opens_then_dies),
            self.assertRaises(WorkerLost),
        ):
            self.owner_starts()
        old = self.attempts().get()
        [old_session] = MockGateway.checkout_session_ids()
        # Its request died long ago: past recovery, the next tap abandons it.
        PaymentAttempt.objects.filter(pk=old.pk).update(
            opening_until=timezone.now() - timedelta(seconds=1),
            created_at=timezone.now() - CHECKOUT_RECOVERY_LIMIT - timedelta(seconds=1),
        )
        late_expiry = mock_event_body(
            event_id="evt_abandoned_expired",
            outcome="expired",
            session_id=old_session,
            reference=str(self.order.public_reference),
            attempt_id=old.pk,
            event_type="checkout.expired",
        )

        def opens_while_the_late_event_lands(gateway, request):
            result = real_create(gateway, request)
            # The abandoned checkout's expiry arrives while this one opens.
            assert deliver_mock_webhook(self.client, late_expiry).status_code == 200
            return result

        with mock.patch.object(
            MockGateway, "create_checkout", new=opens_while_the_late_event_lands
        ):
            session = self.owner_starts()

        live = session.attempt
        assert session.created is True
        live.refresh_from_db()
        assert live.status == PaymentAttempt.Status.CHECKOUT_PENDING
        assert MockGateway.is_payable(live.provider_session_id)
        assert list(self.attempts().filter(status__in=PaymentAttempt.OPEN_STATUSES)) == [
            live
        ]
        # The event is bound to the attempt whose checkout it is about.
        event = PaymentProviderEvent.objects.get(provider_event_id="evt_abandoned_expired")
        assert event.attempt_id == old.pk

    def test_an_event_bound_before_its_checkout_was_stored_is_read_again_under_lock(self):
        """Bound to an attempt while it had no checkout, an event about
        another checkout is applied only after this one was stored: it ends
        nothing, and money it reports is kept for a human."""

        real_create = MockGateway.create_checkout

        def opens_while_events_land(gateway, request):
            for outcome in ("expired", "succeeded"):
                body = mock_event_body(
                    event_id=f"evt_other_{outcome}",
                    outcome=outcome,
                    session_id="mock_cs_another",
                    reference=str(self.order.public_reference),
                    attempt_id=request.metadata["attempt_id"],
                    amount=request.amount_minor,
                    currency=request.currency,
                    event_type=f"checkout.{outcome}",
                )
                with mock.patch.object(
                    services,
                    "process_provider_event",
                    side_effect=RuntimeError("the worker is busy"),
                ):
                    assert deliver_mock_webhook(self.client, body).status_code == 200
            return real_create(gateway, request)

        with mock.patch.object(
            MockGateway, "create_checkout", new=opens_while_events_land
        ):
            live = self.owner_starts().attempt

        expired = PaymentProviderEvent.objects.get(provider_event_id="evt_other_expired")
        paid = PaymentProviderEvent.objects.get(provider_event_id="evt_other_succeeded")
        assert expired.attempt_id == paid.attempt_id == live.pk
        assert services.process_provider_event(event_id=expired.pk) == "another_checkout"
        with self.assertRaises(FinanceError):
            services.process_provider_event(event_id=paid.pk)
        expired.refresh_from_db()
        assert expired.processing_result == PaymentProviderEvent.ProcessingResult.IGNORED
        live.refresh_from_db()
        assert live.status == PaymentAttempt.Status.CHECKOUT_PENDING
        self.assert_only_payable(live)

    def test_cancelling_the_order_closes_the_checkout_a_payer_holds(self):
        live = self.owner_starts().attempt
        assert (
            ScheduledJob.objects.get(key=f"attempt_expiry:{live.pk}").max_attempts
            == CHECKOUT_CLOSE_ATTEMPTS
        )

        cancel_order(order_id=self.order.pk, reason="deal_cancelled")

        live.refresh_from_db()
        assert live.status == PaymentAttempt.Status.CANCELLED
        assert live.failure_code == "deal_cancelled"
        assert live.close_requested_at is not None
        job = ScheduledJob.objects.get(key=f"checkout_close:{live.pk}")
        assert job.kind == ScheduledJob.Kind.CHECKOUT_CLOSE
        assert job.max_attempts == CHECKOUT_CLOSE_ATTEMPTS
        # The provider is asked by that job, outside the order's transaction,
        # and asked again until it confirms.
        assert MockGateway.is_payable(live.provider_session_id)
        MockGateway.fail_close(live.provider_session_id, ProviderUnavailable("down"))
        assert jobs.run_job(job) == "failed"
        job.refresh_from_db()
        assert job.status == ScheduledJob.Status.PENDING
        assert MockGateway.is_payable(live.provider_session_id)
        MockGateway.fail_close(live.provider_session_id, None)
        jobs.run_job(job)
        job.refresh_from_db()
        assert job.status == ScheduledJob.Status.SUCCEEDED
        assert job.last_result == "checkout_closed"
        assert not MockGateway.is_payable(live.provider_session_id)

    def test_closing_the_order_to_collection_closes_its_checkout_too(self):
        live = self.owner_starts().attempt

        close_order_to_collection(order_id=self.order.pk, reason="settled")

        live.refresh_from_db()
        assert live.status == PaymentAttempt.Status.CANCELLED
        assert live.close_requested_at is not None
        jobs.run_job(ScheduledJob.objects.get(key=f"checkout_close:{live.pk}"))
        assert not MockGateway.is_payable(live.provider_session_id)

    def test_an_order_closed_while_a_checkout_opens_has_nothing_to_close(self):
        with (
            mock.patch.object(MockGateway, "create_checkout", side_effect=WorkerLost),
            self.assertRaises(WorkerLost),
        ):
            self.owner_starts()
        lost = self.attempts().get()

        cancel_order(order_id=self.order.pk, reason="deal_cancelled")

        lost.refresh_from_db()
        assert lost.status == PaymentAttempt.Status.CANCELLED
        assert not ScheduledJob.objects.filter(key=f"checkout_close:{lost.pk}").exists()

    def test_a_payment_settling_outlives_its_orders_cancellation(self):
        live = self.owner_starts().attempt
        reconcile_attempt(attempt_id=live.pk, outcome="processing")
        MockGateway.mark(live.provider_session_id, "processing")

        cancel_order(order_id=self.order.pk, reason="deal_cancelled")

        live.refresh_from_db()
        assert live.status == PaymentAttempt.Status.PROCESSING
        assert not ScheduledJob.objects.filter(key=f"checkout_close:{live.pk}").exists()
        # Its success is real money for an order that no longer exists:
        # recorded as unapplied and refunded.
        MockGateway.mark(live.provider_session_id, "succeeded")
        assert deliver_mock_webhook(self.client, succeed_attempt(live)).status_code == 200
        live.refresh_from_db()
        assert live.status == PaymentAttempt.Status.SUCCEEDED
        assert live.is_unapplied is True
        assert PaymentRefund.objects.filter(
            attempt=live, reason=PaymentRefund.Reason.UNAPPLIED_PAYMENT
        ).exists()

    def test_a_recovery_refused_for_its_credentials_keeps_the_key(self):
        real_create = MockGateway.create_checkout
        sent = []

        def opens_then_dies(gateway, request):
            sent.append(request.idempotency_key)
            result = real_create(gateway, request)
            if len(sent) == 1:
                raise WorkerLost
            return result

        with (
            mock.patch.object(MockGateway, "create_checkout", new=opens_then_dies),
            self.assertRaises(WorkerLost),
        ):
            self.owner_starts()
        lost = self.attempts().get()
        self.age_past_the_opening_window(lost)

        with (
            mock.patch.object(
                MockGateway,
                "create_checkout",
                side_effect=ProviderNotConfigured("credentials rejected"),
            ),
            self.assertRaises(CheckoutInProgress),
        ):
            self.owner_starts()
        lost.refresh_from_db()
        assert lost.status == PaymentAttempt.Status.CREATED

        # Credentials repaired: the same key brings back the checkout it opened.
        with mock.patch.object(MockGateway, "create_checkout", new=opens_then_dies):
            session = self.owner_starts()
        assert session.attempt.pk == lost.pk
        assert MockGateway.checkout_session_ids() == [
            session.attempt.provider_session_id
        ]
        assert sent == [lost.idempotency_key, lost.idempotency_key]

    def test_a_claim_runs_its_full_window_from_when_it_is_granted(self):
        real_lock = services._order_for_update
        start = timezone.now()
        clock = [start]

        def waits_for_the_lock(order_id):
            order = real_lock(order_id)
            # The order lock took five minutes to come.
            clock[0] = start + timedelta(minutes=5)
            return order

        with (
            mock.patch("django.utils.timezone.now", side_effect=lambda: clock[0]),
            mock.patch.object(
                services, "_order_for_update", side_effect=waits_for_the_lock
            ),
            mock.patch.object(MockGateway, "create_checkout", side_effect=WorkerLost),
            self.assertRaises(WorkerLost),
        ):
            self.owner_starts()

        opening = self.attempts().get()
        assert opening.opening_until == clock[0] + CHECKOUT_OPENING_WINDOW

    def test_an_owner_is_never_handed_a_checkout_its_provider_expired(self):
        MockGateway.set_checkout_lifetime(timedelta(minutes=30))
        first = self.owner_starts().attempt

        # The attempt ends when its provider stops the checkout collecting,
        # sooner than its own lifetime, and its jobs run by that deadline.
        assert first.expires_at <= timezone.now() + timedelta(minutes=30)
        assert (
            ScheduledJob.objects.get(key=f"attempt_expiry:{first.pk}").run_at
            == first.expires_at
        )
        assert ScheduledJob.objects.get(
            key=f"provider_reconcile:{first.pk}"
        ).run_at == first.expires_at + timedelta(minutes=5)

        # Past it, with the provider's expiry webhook missed, the owner is not
        # handed the dead checkout again.
        later = first.expires_at + timedelta(seconds=1)
        with mock.patch("django.utils.timezone.now", return_value=later):
            second = self.owner_starts()
        assert second.created is True
        assert second.attempt.pk != first.pk


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)
class TechnicalRecordsTests(GuestPaymentTestCase):
    """G1: a hosted checkout URL leaves the server only in a checkout call's
    answer, so not even the technical admin shows it, nor the frozen request
    that repeats the receipt address."""

    def test_the_technical_attempt_page_shows_no_checkout_url_or_request(self):
        from django.test import Client

        from apps.accounts.models import User
        from apps.admin_panel.permissions import AdminRole, assign_admin_roles
        from apps.admin_panel.tests.two_step_helpers import verify_session

        MockGateway.reset()
        attempt = start_checkout(
            order_id=self.order.pk, provider="mock", actor_id=self.scenario.sender.pk
        ).attempt
        assert attempt.checkout_url and attempt.checkout_request
        owner = User.objects.create_user(
            email="owner@example.test",
            username="owner@example.test",
            password="Strong-pass-123!",
            full_name="Owner",
            is_staff=True,
            is_superuser=True,
        )
        assign_admin_roles(owner, (AdminRole.SUPER_ADMIN,), elevate_super_admin=True)
        client = Client()
        client.force_login(owner)
        verify_session(client, owner)

        page = client.get(
            reverse("admin:finance_paymentattempt_change", args=[attempt.pk])
        )

        assert page.status_code == 200
        body = page.content.decode()
        # The page is this attempt's, with its diagnostics.
        assert attempt.provider_session_id in body
        assert attempt.idempotency_key in body
        assert "mock.invalid/checkout" not in body
        assert "/return?result=" not in body

