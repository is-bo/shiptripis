"""L1A: what a retired backend surface answers now.

Two shapes, and only two. The six paths in ``apps.core.retired_routes`` keep a
``410 Gone`` with their stable refusal code, because a stale client may still
call them and deserves an explicit answer. Every other route L1A removed is
simply not routed any more and answers ``404``. The inventory
(``docs/WASSLA_L1_CLEANUP_INVENTORY.md``) lists the evidence for each removal.

Literal paths, never ``reverse()``: the names of removed routes no longer
exist, and a stale client calls the path, not the name.
"""

from __future__ import annotations

from datetime import timedelta

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.matching.models import Match, Offer
from apps.parcels.models import ParcelRequest, ProductRequest
from apps.payments.models import PaymentIntent
from apps.trips.models import Trip
from apps.verification.models import HandoverCode


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


#: (method, path, refusal code) for every tombstone in apps.core.retired_routes.
TOMBSTONES = (
    ("post", "/api/matches/apply", "legacy_matching_flow_retired"),
    ("post", "/api/matches/apply-to-trip", "legacy_matching_flow_retired"),
    ("post", "/api/matches/1/offers/counter", "legacy_matching_flow_retired"),
    ("post", "/api/parcels/delivery", "legacy_delivery_flow_retired"),
    ("get", "/api/parcels/quote/delivery", "legacy_dzd_quote_retired"),
    ("post", "/api/parcels/product", "product_request_retired"),
)

#: (method, path) for every route L1A removed outright.
REMOVED = (
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


class TombstoneTests(APITestCase):
    def setUp(self):
        self.user = _user("tombstone@example.com", "201")

    def test_each_tombstone_answers_410_with_its_refusal_code(self):
        client = _client(self.user)
        for method, path, code in TOMBSTONES:
            with self.subTest(path=path):
                response = getattr(client, method)(path, {}, format="json")
                assert response.status_code == 410, (path, response.status_code)
                assert response.data["code"] == code
                assert response.data["detail"]

    def test_a_tombstone_answers_only_the_method_it_retired(self):
        client = _client(self.user)
        for method, path, _code in TOMBSTONES:
            other = "get" if method == "post" else "post"
            with self.subTest(path=path):
                response = getattr(client, other)(path, {}, format="json")
                assert response.status_code == 405, (path, response.status_code)

    def test_a_tombstone_still_requires_authentication(self):
        client = _client()
        for method, path, _code in TOMBSTONES:
            with self.subTest(path=path):
                response = getattr(client, method)(path, {}, format="json")
                assert response.status_code == 401, (path, response.status_code)


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
            {"kind": HandoverCode.Kind.PICKUP},
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
        }
        assert counter.status_code == 410
        assert accept.status_code == 410
        assert PaymentIntent.objects.count() == 0
        assert HandoverCode.objects.count() == 0


#: The admin templates resolve static files; the manifest only exists after
#: collectstatic, so rendering tests use plain storage.
LOCAL_STATIC = override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)


@LOCAL_STATIC
class HistoricalAdminTests(APITestCase):
    """The legacy money and handover tables are readable and nothing else."""

    LEGACY_MODELS = (
        ("payments", "paymentintent"),
        ("payments", "paymentevent"),
        ("payments", "refund"),
        ("wallet", "wallet"),
        ("wallet", "walletentry"),
        ("wallet", "hold"),
        ("wallet", "withdrawal"),
        ("verification", "handovercode"),
    )

    def setUp(self):
        self.staff = User.objects.create_superuser(
            username="history-admin@example.com",
            email="history-admin@example.com",
            password="Sup3rStrongPass!",
        )

    def test_every_legacy_table_is_view_only_in_the_django_admin(self):
        from django.apps import apps
        from django.contrib import admin as django_admin
        from django.test import RequestFactory

        request = RequestFactory().get("/")
        request.user = self.staff
        for app_label, model_name in self.LEGACY_MODELS:
            with self.subTest(model=f"{app_label}.{model_name}"):
                model = apps.get_model(app_label, model_name)
                model_admin = django_admin.site._registry[model]
                assert model_admin.has_view_permission(request)
                assert not model_admin.has_add_permission(request)
                assert not model_admin.has_change_permission(request)
                assert not model_admin.has_delete_permission(request)
                assert not model_admin.get_actions(request)

    def test_the_changelist_still_renders_for_staff(self):
        self.client.force_login(self.staff)
        for app_label, model_name in self.LEGACY_MODELS:
            with self.subTest(model=f"{app_label}.{model_name}"):
                response = self.client.get(
                    reverse(f"admin:{app_label}_{model_name}_changelist")
                )
                assert response.status_code == 200
                add = self.client.get(reverse(f"admin:{app_label}_{model_name}_add"))
                assert add.status_code == 403
