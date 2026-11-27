"""L1A: what a retired backend surface answers now.

Every route L1A removed is simply not routed any more and answers ``404``,
including the six paths that used to answer ``410``: the app was never
released, so no stale client needs an explicit refusal. The inventory
(``docs/WASSLA_L1_CLEANUP_INVENTORY.md``) lists the evidence for each removal.

Literal paths, never ``reverse()``: the names of removed routes no longer exist.
"""

from __future__ import annotations

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.matching.models import Match, Offer
from apps.parcels.models import ParcelRequest, ProductRequest
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


def _client(user: User | None = None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


#: (method, path) for every route L1A removed outright.
REMOVED = (
    # Pre-V1 matching writes, delivery create, DZD quote and ProductRequest
    # create (these answered 410 until L1A).
    ("post", "/api/matches/apply"),
    ("post", "/api/matches/apply-to-trip"),
    ("post", "/api/matches/1/offers/counter"),
    ("post", "/api/parcels/delivery"),
    ("get", "/api/parcels/quote/delivery"),
    ("post", "/api/parcels/product"),
    # Legacy DZD payment intents and the unauthenticated mock webhook.
    ("get", "/api/payments/intents"),
    ("post", "/api/payments/intents/create"),
    ("get", "/api/payments/intents/1"),
    ("post", "/api/payments/intents/1/cancel"),
    ("post", "/api/payments/intents/1/refund"),
    ("post", "/api/payments/webhook/mock"),
    # Legacy DZD wallets and withdrawals.
    ("get", "/api/wallets"),
    ("get", "/api/wallets/DZD"),
    ("get", "/api/wallets/DZD/entries"),
    ("get", "/api/wallets/DZD/holds"),
    ("get", "/api/withdrawals"),
    ("post", "/api/withdrawals/create"),
    # Legacy match handover codes (V1 handover lives under /api/deals/).
    ("get", "/api/matches/1/handover"),
    ("post", "/api/matches/1/handover/issue"),
    ("post", "/api/matches/1/handover/verify"),
    ("get", "/api/matches/1/handover/code"),
    # Legacy airport-based trips (V1 uses /api/journeys).
    ("get", "/api/trips"),
    ("post", "/api/trips"),
    ("get", "/api/trips/search"),
    ("get", "/api/trips/1"),
    ("post", "/api/trips/1/cancel"),
    ("post", "/api/trips/1/media"),
    ("get", "/api/airports"),
    # Superseded by find-travelers and the quote endpoint.
    ("get", "/api/matches/compatible-journeys"),
)


class RemovedRouteTests(APITestCase):
    def test_every_removed_route_answers_404(self):
        client = _client(_user("removed@example.com", "202"))
        for method, path in REMOVED:
            with self.subTest(method=method, path=path):
                response = getattr(client, method)(path, {}, format="json")
                assert response.status_code == 404, (path, response.status_code)

    def test_a_removed_route_answers_404_to_an_anonymous_caller_too(self):
        client = _client()
        for method, path in REMOVED:
            with self.subTest(method=method, path=path):
                response = getattr(client, method)(path, {}, format="json")
                assert response.status_code == 404, (path, response.status_code)


class RetiredProductBoundaryTests(APITestCase):
    """A historical ProductRequest match cannot re-enter any live flow.

    Ported from the deleted ``apps/payments/tests/test_payments.py``: the
    legacy payment and handover routes it called are gone (404 now, asserted
    above), and the live chat, counter and accept surfaces must still refuse.
    """

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

    def test_product_cannot_reenter_payment_handover_chat_counter_or_accept(self):
        client = _client(self.sender)

        payment = client.post(
            "/api/payments/intents/create",
            {"offer_id": self.offer.pk, "currency": "DZD"},
            format="json",
        )
        handover = client.post(
            f"/api/matches/{self.match.pk}/handover/issue",
            {"kind": "pickup"},
            format="json",
        )
        chat = client.get(reverse("matches-chat-eligibility", args=[self.match.pk]))
        counter = client.post(
            reverse("offers-counter-v1", args=[self.offer.pk]),
            {"traveler_reward_eur_cents": 500},
            format="json",
        )
        accept = client.post(reverse("offers-accept", args=[self.offer.pk]), format="json")

        assert payment.status_code == 404
        assert handover.status_code == 404
        assert chat.status_code == 200
        assert chat.data == {
            "eligible": False,
            "reason": "product_request_retired",
            "match_id": self.match.pk,
            "blocked_by_me": False,
        }
        assert counter.status_code == 410
        assert accept.status_code == 410
