"""Tests for apps.payments — mock provider flow + state machine + idempotency."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.matching.models import Match, Offer
from apps.parcels.models import DeliveryRequest, ParcelRequest, ProductRequest
from apps.payments.models import PaymentIntent, Refund
from apps.trips.models import Trip


def _user(email: str, suffix: str) -> User:
    return User.objects.create_user(
        username=email,
        email=email,
        password="Sup3rStrongPass!",
        full_name=f"User {suffix}",
        phone=f"+213555000{suffix}",
        wilaya="16",
    )


def _client(user: User) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _setup_accepted_offer(total_dzd: int = 5000) -> tuple[User, User, Offer]:
    sender = _user("p_sender@example.com", "100")
    traveler = _user("p_traveler@example.com", "101")
    parcel = DeliveryRequest.objects.create(
        sender=sender,
        kind=ParcelRequest.Kind.DELIVERY,
        origin_id="ALG",
        destination_id="CDG",
        weight_kg=2,
        item_type=ParcelRequest.ItemType.DOCUMENTS,
        base_amount_dzd=total_dzd - 1000,
    )
    trip = Trip.objects.create(
        traveler=traveler,
        origin_id="ALG",
        destination_id="CDG",
        departure_at=timezone.now() + timedelta(days=2),
        capacity_kg=20,
        status=Trip.Status.ACTIVE,
    )
    match = Match.objects.create(
        parcel=parcel,
        trip=trip,
        sender=sender,
        traveler=traveler,
        status=Match.Status.ACCEPTED,
    )
    offer = Offer.objects.create(
        match=match,
        proposed_by=Offer.ProposedBy.TRAVELER,
        proposer=traveler,
        base_amount_dzd=total_dzd - 1000,
        commission_dzd=1000,
        total_dzd=total_dzd,
        economics_version=Offer.EconomicsVersion.LEGACY_DZD,
        currency=Offer.Currency.DZD,
        status=Offer.Status.ACCEPTED,
        responded_at=timezone.now(),
    )
    return sender, traveler, offer


@override_settings(PAYMENTS_LEGACY_MUTATIONS_ENABLED=True)
class CreateIntentTests(APITestCase):
    def setUp(self):
        self.sender, self.traveler, self.offer = _setup_accepted_offer()

    @patch("apps.payments.views.redis_bus.publish_after_commit")
    def test_sender_creates_intent_mock_succeeds_instantly(self, pub):
        c = _client(self.sender)
        r = c.post(
            reverse("payments-create"),
            {"offer_id": self.offer.id, "currency": "DZD"},
            format="json",
        )
        assert r.status_code == 201, r.data
        assert r.data["status"] == "succeeded"
        assert r.data["amount_minor"] == self.offer.total_dzd
        assert r.data["currency"] == "DZD"
        assert r.data["provider"] == "mock"
        assert r.data["provider_intent_id"].startswith("pi_mock_")
        # publishes payment.captured
        ch = [c.args[0] for c in pub.call_args_list]
        assert "payment.captured" in ch

    def test_traveler_cannot_pay(self):
        c = _client(self.traveler)
        r = c.post(
            reverse("payments-create"),
            {"offer_id": self.offer.id, "currency": "DZD"},
            format="json",
        )
        assert r.status_code == 403

    def test_cannot_pay_non_accepted_offer(self):
        self.offer.status = Offer.Status.PENDING
        self.offer.save()
        c = _client(self.sender)
        r = c.post(
            reverse("payments-create"),
            {"offer_id": self.offer.id, "currency": "DZD"},
            format="json",
        )
        assert r.status_code == 409

    def test_idempotency_key_returns_same_intent(self):
        c = _client(self.sender)
        body = {
            "offer_id": self.offer.id,
            "currency": "DZD",
            "idempotency_key": "abc-123",
        }
        r1 = c.post(reverse("payments-create"), body, format="json")
        assert r1.status_code == 201
        r2 = c.post(reverse("payments-create"), body, format="json")
        assert r2.status_code == 200
        assert r2.data["id"] == r1.data["id"]
        assert PaymentIntent.objects.filter(offer=self.offer).count() == 1

    def test_double_pay_succeeded_offer_returns_existing(self):
        c = _client(self.sender)
        r1 = c.post(
            reverse("payments-create"),
            {"offer_id": self.offer.id, "currency": "DZD"},
            format="json",
        )
        r2 = c.post(
            reverse("payments-create"),
            {"offer_id": self.offer.id, "currency": "DZD"},
            format="json",
        )
        assert r1.status_code == 201
        assert r2.status_code == 200
        assert r2.data["id"] == r1.data["id"]

    def test_capture_auto_issues_pickup_code(self):
        # Mock provider succeeds inline, so creating the intent triggers
        # _synthesize_succeeded → auto-issues a PICKUP code to the sender.
        from apps.verification.models import HandoverCode

        c = _client(self.sender)
        r = c.post(
            reverse("payments-create"),
            {"offer_id": self.offer.id, "currency": "DZD"},
            format="json",
        )
        assert r.status_code == 201, r.data
        active = HandoverCode.objects.filter(
            match=self.offer.match,
            kind=HandoverCode.Kind.PICKUP,
            status=HandoverCode.Status.ACTIVE,
        )
        assert active.count() == 1
        assert active.get().issued_to_id == self.sender.id


@override_settings(PAYMENTS_LEGACY_MUTATIONS_ENABLED=True)
class RetiredProductBoundaryTests(APITestCase):
    def setUp(self):
        self.sender = _user("product_sender@example.com", "110")
        self.traveler = _user("product_traveler@example.com", "111")
        product = ProductRequest.objects.create(
            sender=self.sender,
            kind=ParcelRequest.Kind.PRODUCT,
            origin_id="ALG",
            destination_id="CDG",
            weight_kg=1,
            product_price_dzd=20_000,
        )
        trip = Trip.objects.create(
            traveler=self.traveler,
            origin_id="ALG",
            destination_id="CDG",
            departure_at=timezone.now() + timedelta(days=2),
            capacity_kg=10,
        )
        self.match = Match.objects.create(
            parcel=product,
            trip=trip,
            sender=self.sender,
            traveler=self.traveler,
            status=Match.Status.ACCEPTED,
        )
        self.offer = Offer.objects.create(
            match=self.match,
            proposed_by=Offer.ProposedBy.TRAVELER,
            proposer=self.traveler,
            base_amount_dzd=20_000,
            base_fee_dzd=2_500,
            commission_dzd=5_000,
            total_dzd=27_500,
            economics_version=Offer.EconomicsVersion.LEGACY_DZD,
            currency=Offer.Currency.DZD,
            status=Offer.Status.ACCEPTED,
        )

    def test_product_cannot_reenter_payment_handover_or_chat(self):
        from apps.verification.models import HandoverCode

        payment = _client(self.sender).post(
            reverse("payments-create"),
            {"offer_id": self.offer.pk, "currency": "DZD"},
            format="json",
        )
        handover = _client(self.sender).post(
            reverse("handover-issue", args=[self.match.pk]),
            {"kind": HandoverCode.Kind.PICKUP},
            format="json",
        )
        chat = _client(self.sender).get(
            reverse("matches-chat-eligibility", args=[self.match.pk])
        )
        counter = _client(self.sender).post(
            reverse("offers-counter-v1", args=[self.offer.pk]),
            {"traveler_reward_eur_cents": 500},
            format="json",
        )
        accept = _client(self.sender).post(
            reverse("offers-accept", args=[self.offer.pk]), format="json"
        )

        assert payment.status_code == 410
        assert handover.status_code == 410
        assert chat.status_code == 200
        assert counter.status_code == 410
        assert accept.status_code == 410
        assert chat.data == {
            "eligible": False,
            "reason": "product_request_retired",
            "match_id": self.match.pk,
        }
        assert PaymentIntent.objects.count() == 0
        assert HandoverCode.objects.count() == 0


@override_settings(PAYMENTS_LEGACY_MUTATIONS_ENABLED=True)
class DetailAndCancelTests(APITestCase):
    def setUp(self):
        self.sender, self.traveler, self.offer = _setup_accepted_offer()
        c = _client(self.sender)
        r = c.post(
            reverse("payments-create"),
            {"offer_id": self.offer.id, "currency": "DZD"},
            format="json",
        )
        self.intent_id = r.data["id"]

    def test_payer_sees_detail(self):
        c = _client(self.sender)
        r = c.get(reverse("payments-detail", args=[self.intent_id]))
        assert r.status_code == 200
        assert r.data["id"] == self.intent_id

    def test_non_payer_forbidden(self):
        c = _client(self.traveler)
        r = c.get(reverse("payments-detail", args=[self.intent_id]))
        assert r.status_code == 403

    def test_cannot_cancel_succeeded(self):
        c = _client(self.sender)
        r = c.post(reverse("payments-cancel", args=[self.intent_id]), format="json")
        assert r.status_code == 409


@override_settings(PAYMENTS_LEGACY_MUTATIONS_ENABLED=True)
class RefundTests(APITestCase):
    def setUp(self):
        self.sender, self.traveler, self.offer = _setup_accepted_offer(total_dzd=10000)
        c = _client(self.sender)
        r = c.post(
            reverse("payments-create"),
            {"offer_id": self.offer.id, "currency": "DZD"},
            format="json",
        )
        self.intent_id = r.data["id"]

    @patch("apps.payments.views.redis_bus.publish_after_commit")
    def test_full_refund_marks_intent_refunded(self, pub):
        c = _client(self.sender)
        r = c.post(reverse("payments-refund", args=[self.intent_id]), format="json")
        assert r.status_code == 201, r.data
        intent = PaymentIntent.objects.get(pk=self.intent_id)
        assert intent.status == "refunded"
        assert intent.refunded_at is not None
        assert Refund.objects.filter(intent=intent).count() == 1
        ch = [c.args[0] for c in pub.call_args_list]
        assert "payment.refunded" in ch

    def test_partial_refund_moves_to_refund_pending(self):
        c = _client(self.sender)
        r = c.post(
            reverse("payments-refund", args=[self.intent_id]),
            {"amount_minor": 4000},
            format="json",
        )
        assert r.status_code == 201, r.data
        intent = PaymentIntent.objects.get(pk=self.intent_id)
        assert intent.status == "refund_pending"

    def test_refund_exceeding_captured_rejected(self):
        c = _client(self.sender)
        r = c.post(
            reverse("payments-refund", args=[self.intent_id]),
            {"amount_minor": 999999},
            format="json",
        )
        assert r.status_code == 409


@override_settings(
    PAYMENTS_MOCK_WEBHOOK_ENABLED=True,
    PAYMENTS_LEGACY_MUTATIONS_ENABLED=True,
)
class MockWebhookTests(APITestCase):
    """The dev/QA webhook endpoint can flip an intent to succeeded/failed."""

    def setUp(self):
        # Create with the API to get a real intent, then force it to processing.
        self.sender, self.traveler, self.offer = _setup_accepted_offer()
        c = _client(self.sender)
        r = c.post(
            reverse("payments-create"),
            {"offer_id": self.offer.id, "currency": "DZD"},
            format="json",
        )
        self.intent = PaymentIntent.objects.get(pk=r.data["id"])
        # Reset it to processing so the webhook has something to do.
        self.intent.status = PaymentIntent.Status.PROCESSING
        self.intent.succeeded_at = None
        self.intent.save()

    def test_mock_webhook_succeeded_transitions_intent(self):
        c = APIClient()
        r = c.post(
            reverse("payments-webhook-mock"),
            {"provider_intent_id": self.intent.provider_intent_id, "event": "succeeded"},
            format="json",
        )
        assert r.status_code == 200, r.data
        self.intent.refresh_from_db()
        assert self.intent.status == "succeeded"

    def test_mock_webhook_failed_transitions_intent(self):
        c = APIClient()
        r = c.post(
            reverse("payments-webhook-mock"),
            {"provider_intent_id": self.intent.provider_intent_id, "event": "failed"},
            format="json",
        )
        assert r.status_code == 200, r.data
        self.intent.refresh_from_db()
        assert self.intent.status == "failed"
        assert self.intent.failure_code == "mock_failed"

    def test_mock_webhook_unknown_intent_404(self):
        c = APIClient()
        r = c.post(
            reverse("payments-webhook-mock"),
            {"provider_intent_id": "pi_unknown", "event": "succeeded"},
            format="json",
        )
        assert r.status_code == 404
        self.intent.refresh_from_db()
        assert self.intent.status == PaymentIntent.Status.PROCESSING

    @override_settings(PAYMENTS_MOCK_WEBHOOK_ENABLED=False)
    def test_mock_webhook_is_hidden_when_disabled(self):
        r = APIClient().post(
            reverse("payments-webhook-mock"),
            {"provider_intent_id": self.intent.provider_intent_id, "event": "failed"},
            format="json",
        )
        assert r.status_code == 404


class RetiredLegacyMutationFirewallTests(APITestCase):
    def setUp(self):
        self.sender, _traveler, self.offer = _setup_accepted_offer()

    @override_settings(PAYMENTS_LEGACY_MUTATIONS_ENABLED=False)
    def test_historical_offer_cannot_reach_instant_mock_payment(self):
        before = PaymentIntent.objects.count()

        response = _client(self.sender).post(
            reverse("payments-create"),
            {"offer_id": self.offer.pk, "currency": "DZD"},
            format="json",
        )

        assert response.status_code == 410
        assert response.data["code"] == "legacy_payment_retired"
        assert PaymentIntent.objects.count() == before
