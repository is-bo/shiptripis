from datetime import timedelta
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.parcels.models import (
    DeliveryRequest,
    ParcelRequest,
    ProductRequest,
)


def _make_user(email: str = "sender@example.com") -> User:
    user = User.objects.create_user(
        username=email,
        email=email,
        password="Sup3rStrongPass!",
        full_name="Sen Der",
        phone="+213555000222",
        wilaya="16",
    )
    return user


def _auth_client(user: User) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _delivery_payload(**overrides) -> dict:
    base = {
        "origin": "ALG",
        "destination": "CDG",
        "weight_kg": 3,
        "item_type": "documents",
        "description": "Birth certificate",
        "base_amount_dzd": 3000,
        "pickup_city": "Algiers",
        "delivery_city": "Paris",
    }
    base.update(overrides)
    return base


def _product_payload(**overrides) -> dict:
    base = {
        "origin": "CDG",
        "destination": "ALG",
        "weight_kg": 2,
        "item_type": "electronics",
        "store_name": "Fnac",
        "product_url": "https://fnac.fr/x",
        "product_price_dzd": 45000,
    }
    base.update(overrides)
    return base


class DeliveryCreateTests(APITestCase):
    def setUp(self):
        self.user = _make_user()
        self.client = _auth_client(self.user)

    def test_unauth_rejected(self):
        c = APIClient()
        r = c.post(reverse("parcels-delivery-create"), _delivery_payload(), format="json")
        assert r.status_code == 401

    @patch("apps.parcels.views.redis_bus.publish_after_commit")
    def test_creates_delivery_and_publishes(self, pub):
        r = self.client.post(
            reverse("parcels-delivery-create"), _delivery_payload(), format="json"
        )
        assert r.status_code == 201, r.data
        assert r.data["kind"] == "delivery"
        assert r.data["base_amount_dzd"] == 3000
        assert r.data["product_price_dzd"] is None
        assert r.data["origin"]["iata"] == "ALG"
        assert DeliveryRequest.objects.count() == 1
        pub.assert_called_once()
        ch, payload = pub.call_args.args
        assert ch == "parcel.created"
        assert payload["kind"] == "delivery"

    def test_rejects_same_origin_destination(self):
        r = self.client.post(
            reverse("parcels-delivery-create"),
            _delivery_payload(origin="ALG", destination="ALG"),
            format="json",
        )
        assert r.status_code == 400
        assert "destination" in r.data

    def test_rejects_unknown_iata(self):
        r = self.client.post(
            reverse("parcels-delivery-create"),
            _delivery_payload(origin="ZZZ"),
            format="json",
        )
        assert r.status_code == 400
        assert "airports" in r.data

    def test_rejects_past_deadline(self):
        past = (timezone.now() - timedelta(days=1)).isoformat()
        r = self.client.post(
            reverse("parcels-delivery-create"),
            _delivery_payload(deadline_at=past),
            format="json",
        )
        assert r.status_code == 400
        assert "deadline_at" in r.data


class ProductCreateTests(APITestCase):
    def setUp(self):
        self.user = _make_user()
        self.client = _auth_client(self.user)

    @patch("apps.parcels.views.redis_bus.publish_after_commit")
    def test_creates_product(self, pub):
        r = self.client.post(
            reverse("parcels-product-create"), _product_payload(), format="json"
        )
        assert r.status_code == 201, r.data
        assert r.data["kind"] == "product"
        assert r.data["product_price_dzd"] == 45000
        assert r.data["base_amount_dzd"] is None
        assert r.data["store_name"] == "Fnac"
        assert ProductRequest.objects.count() == 1
        pub.assert_called_once()


class ParcelListTests(APITestCase):
    def setUp(self):
        self.user = _make_user()
        self.other = _make_user(email="other@example.com")
        self.client = _auth_client(self.user)

    def test_lists_only_mine(self):
        DeliveryRequest.objects.create(
            sender=self.user,
            kind=ParcelRequest.Kind.DELIVERY,
            origin_id="ALG",
            destination_id="CDG",
            weight_kg=2,
            base_amount_dzd=2000,
        )
        DeliveryRequest.objects.create(
            sender=self.other,
            kind=ParcelRequest.Kind.DELIVERY,
            origin_id="ALG",
            destination_id="CDG",
            weight_kg=2,
            base_amount_dzd=2000,
        )
        r = self.client.get(reverse("parcels-list"))
        assert r.status_code == 200
        assert len(r.data) == 1
        assert r.data[0]["sender_id"] == self.user.id

    def test_filter_by_kind(self):
        DeliveryRequest.objects.create(
            sender=self.user, kind="delivery",
            origin_id="ALG", destination_id="CDG", weight_kg=2, base_amount_dzd=2000,
        )
        ProductRequest.objects.create(
            sender=self.user, kind="product",
            origin_id="ALG", destination_id="CDG", weight_kg=2, product_price_dzd=10000,
        )
        r = self.client.get(reverse("parcels-list"), {"kind": "product"})
        assert r.status_code == 200
        assert len(r.data) == 1
        assert r.data[0]["kind"] == "product"


class ParcelCancelTests(APITestCase):
    def setUp(self):
        self.user = _make_user()
        self.other = _make_user(email="other@example.com")
        self.client = _auth_client(self.user)
        self.parcel = DeliveryRequest.objects.create(
            sender=self.user, kind="delivery",
            origin_id="ALG", destination_id="CDG", weight_kg=2, base_amount_dzd=2000,
        )

    @patch("apps.parcels.views.redis_bus.publish_after_commit")
    def test_owner_can_cancel_open(self, pub):
        r = self.client.post(reverse("parcels-cancel", args=[self.parcel.pk]))
        assert r.status_code == 200
        assert r.data["status"] == "cancelled"
        pub.assert_called_once()
        assert pub.call_args.args[0] == "parcel.cancelled"

    def test_non_owner_forbidden(self):
        c = _auth_client(self.other)
        r = c.post(reverse("parcels-cancel", args=[self.parcel.pk]))
        assert r.status_code == 403

    def test_cannot_cancel_delivered(self):
        self.parcel.status = ParcelRequest.Status.DELIVERED
        self.parcel.save(update_fields=["status"])
        r = self.client.post(reverse("parcels-cancel", args=[self.parcel.pk]))
        assert r.status_code == 409


class ParcelDetailTests(APITestCase):
    def setUp(self):
        self.user = _make_user()
        self.client = _auth_client(self.user)
        self.delivery = DeliveryRequest.objects.create(
            sender=self.user, kind="delivery",
            origin_id="ALG", destination_id="CDG", weight_kg=2, base_amount_dzd=2000,
        )
        self.product = ProductRequest.objects.create(
            sender=self.user, kind="product",
            origin_id="CDG", destination_id="ALG", weight_kg=1, product_price_dzd=20000,
            store_name="Apple", product_url="https://apple.com/x",
        )

    def test_delivery_detail_includes_base_amount(self):
        r = self.client.get(reverse("parcels-detail", args=[self.delivery.pk]))
        assert r.status_code == 200
        assert r.data["base_amount_dzd"] == 2000
        assert r.data["product_price_dzd"] is None

    def test_product_detail_includes_product_fields(self):
        r = self.client.get(reverse("parcels-detail", args=[self.product.pk]))
        assert r.status_code == 200
        assert r.data["product_price_dzd"] == 20000
        assert r.data["store_name"] == "Apple"
        assert r.data["base_amount_dzd"] is None

    def test_404_for_unknown(self):
        r = self.client.get(reverse("parcels-detail", args=[9999]))
        assert r.status_code == 404
