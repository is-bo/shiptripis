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

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.business_settings import get_active_business_settings
from apps.core.models import BusinessSettingsVersion
from apps.deals.models import Deal
from apps.finance.models import (
    GuestPaymentLink,
    PaymentAttempt,
    PaymentOrder,
)
from apps.finance.services import (
    GuestLinkInvalid,
    NotAuthorized,
    create_guest_link,
    hash_guest_token,
    resolve_guest_link,
)

from .factories import build_scenario, deliver_mock_webhook, succeed_attempt


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
