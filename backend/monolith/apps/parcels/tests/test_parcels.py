from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.contrib.admin.sites import AdminSite
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.locations.models import Country, Location, Place
from apps.parcels.models import (
    DeliveryRequest,
    ParcelMedia,
    ParcelRequest,
    ProductRequest,
)
from apps.parcels.admin import ParcelMediaInline, ParcelRequestAdmin


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


class ProductAdminRetirementTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get("/admin/parcels/")
        self.product = ParcelRequest(kind=ParcelRequest.Kind.PRODUCT)
        site = AdminSite()
        self.parent_admin = ParcelRequestAdmin(ParcelRequest, site)
        self.media_inline = ParcelMediaInline(ParcelRequest, site)

    def test_parent_admin_cannot_create_bare_product_rows(self):
        assert self.parent_admin.has_add_permission(self.request) is False

    def test_historical_product_media_is_read_only(self):
        assert self.media_inline.has_add_permission(self.request, self.product) is False
        assert (
            self.media_inline.has_change_permission(self.request, self.product) is False
        )
        assert (
            self.media_inline.has_delete_permission(self.request, self.product) is False
        )
        assert set(
            self.media_inline.get_readonly_fields(self.request, self.product)
        ) == {field.name for field in ParcelMedia._meta.fields}


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


def _make_location(
    owner: User,
    *,
    city: str,
    suffix: str,
    country_code: str = "FR",
) -> Location:
    return Location.objects.create(
        owner=owner,
        created_by=owner,
        kind=Location.Kind.EXACT_ADDRESS,
        normalized_label=f"12 {suffix} Street, {city}",
        public_label=city,
        private_label=f"Apartment 4, 12 {suffix} Street, {city}",
        city=city,
        region="",
        country_code=country_code,
        latitude="48.856600",
        longitude="2.352200",
        coarse_latitude="48.850000",
        coarse_longitude="2.350000",
        source="manual",
        precision=Location.Precision.ROOFTOP,
    )


def _delivery_v1_payload(pickup: Location, delivery: Location, **overrides) -> dict:
    now = timezone.now()
    base = {
        "pickup_location_id": pickup.id,
        "delivery_location_id": delivery.id,
        "ready_window_start": (now + timedelta(days=1)).isoformat(),
        "ready_window_end": (now + timedelta(days=1, hours=2)).isoformat(),
        "deadline_at": (now + timedelta(days=3)).isoformat(),
        "actual_weight_kg": "2.50",
        "length_cm": "20.00",
        "width_cm": "10.00",
        "height_cm": "5.00",
        "declared_value_eur_cents": 12_500,
        "sender_proposed_reward_eur_cents": 3_000,
        "title": "Documents for Algiers",
        "description": "A sealed folder of personal documents.",
        "category": "documents",
        "handling_notes": "Keep dry.",
        "fragile": False,
        "description_is_accurate": True,
        "item_is_legal": True,
        "no_prohibited_goods": True,
        "declared_value_is_accurate": True,
        "customs_responsibilities_understood": True,
    }
    base.update(overrides)
    return base


def _staged_item_photo(user: User) -> ParcelMedia:
    """One uploaded-but-unclaimed item photo, ready for a create call.

    Every V1 request needs one (Phase 8F-B), and a staged row is single-use,
    so this mints a fresh one per payload rather than sharing a fixture.
    """

    return ParcelMedia.objects.create(
        parcel=None,
        uploaded_by=user,
        purpose=ParcelMedia.Purpose.ITEM_PHOTO,
        bucket="shiptrip-parcel-test",
        object_key=f"parcels/staged/{user.pk}/{uuid4().hex}.jpg",
        content_type="image/jpeg",
        bytes=1024,
    )


def _create_v1_delivery(
    sender: User,
    pickup: Location,
    delivery: Location,
    **overrides,
) -> DeliveryRequest:
    now = timezone.now()
    values = {
        "sender": sender,
        "kind": ParcelRequest.Kind.DELIVERY,
        "schema_version": 2,
        "pickup_location": pickup,
        "delivery_location": delivery,
        "item_type": ParcelRequest.ItemType.DOCUMENTS,
        "description": "A sealed folder.",
        "deadline_at": now + timedelta(days=3),
        "ready_window_start": now + timedelta(days=1),
        "ready_window_end": now + timedelta(days=1, hours=2),
        "actual_weight_kg": "2.50",
        "length_cm": "30.00",
        "width_cm": "20.00",
        "height_cm": "5.00",
        "declared_value_eur_cents": 12_500,
        "traveler_reward_eur_cents": 3_000,
        "title": "Documents",
        "category": ParcelRequest.ItemType.DOCUMENTS,
        "description_is_accurate": True,
        "item_is_legal": True,
        "no_prohibited_goods": True,
        "declared_value_is_accurate": True,
        "customs_responsibilities_understood": True,
    }
    values.update(overrides)
    return DeliveryRequest.objects.create(**values)


class DeliveryCreateTests(APITestCase):
    def setUp(self):
        self.user = _make_user()
        self.client = _auth_client(self.user)

    def test_unauth_rejected(self):
        c = APIClient()
        r = c.post(
            reverse("parcels-delivery-create"), _delivery_payload(), format="json"
        )
        assert r.status_code == 401

    @patch("apps.parcels.views.redis_bus.publish_after_commit")
    def test_legacy_delivery_creation_is_gone(self, pub):
        r = self.client.post(
            reverse("parcels-delivery-create"), _delivery_payload(), format="json"
        )
        assert r.status_code == 410, r.data
        assert r.data["code"] == "legacy_delivery_flow_retired"
        assert DeliveryRequest.objects.count() == 0
        pub.assert_not_called()


class ProductCreateTests(APITestCase):
    def setUp(self):
        self.user = _make_user()
        self.client = _auth_client(self.user)

    @patch("apps.parcels.views.redis_bus.publish_after_commit")
    def test_product_creation_is_gone_and_does_not_publish(self, pub):
        r = self.client.post(
            reverse("parcels-product-create"), _product_payload(), format="json"
        )
        assert r.status_code == 410, r.data
        assert ProductRequest.objects.count() == 0
        pub.assert_not_called()


class DeliveryV1CreateTests(APITestCase):
    def setUp(self):
        self.sender = _make_user("v1-sender@example.com")
        self.client = _auth_client(self.sender)
        self.pickup = _make_location(self.sender, city="Paris", suffix="Pickup")
        self.delivery = _make_location(
            self.sender,
            city="Algiers",
            suffix="Delivery",
            country_code="DZ",
        )
        france = Country.objects.create(
            code="FR",
            name="France",
            source="phase8c-test",
            source_id="country-fr",
            source_version="phase8c",
        )
        algeria = Country.objects.create(
            code="DZ",
            name="Algeria",
            source="phase8c-test",
            source_id="country-dz",
            source_version="phase8c",
        )
        self.pickup_place = Place.objects.create(
            country=france,
            place_type=Place.PlaceType.LOCALITY,
            source="phase8c-test",
            source_id="locality-paris",
            source_version="phase8c",
            name="Paris",
        )
        self.delivery_place = Place.objects.create(
            country=algeria,
            place_type=Place.PlaceType.LOCALITY,
            source="phase8c-test",
            source_id="locality-algiers",
            source_version="phase8c",
            name="Algiers",
        )
        self.pickup.canonical_place = self.pickup_place
        self.pickup.save(update_fields=["canonical_place", "updated_at"])
        self.delivery.canonical_place = self.delivery_place
        self.delivery.save(update_fields=["canonical_place", "updated_at"])

    def _canonical_payload(self, *, include_locations=False, **overrides):
        payload = _delivery_v1_payload(self.pickup, self.delivery)
        if not include_locations:
            payload.pop("pickup_location_id")
            payload.pop("delivery_location_id")
        payload.update(
            pickup_place_id=self.pickup_place.pk,
            delivery_place_id=self.delivery_place.pk,
            item_photo_media_id=_staged_item_photo(self.sender).pk,
        )
        payload.update(overrides)
        return payload

    def test_requires_authentication(self):
        response = APIClient().post(
            reverse("parcels-delivery-v1-create"),
            _delivery_v1_payload(self.pickup, self.delivery),
            format="json",
        )
        assert response.status_code == 401

    def test_location_only_creation_is_rejected(self):
        response = self.client.post(
            reverse("parcels-delivery-v1-create"),
            _delivery_v1_payload(self.pickup, self.delivery),
            format="json",
        )

        assert response.status_code == 400
        assert "pickup_place_id" in response.data
        assert "delivery_place_id" in response.data
        assert DeliveryRequest.objects.count() == 0

    @patch("apps.parcels.views.redis_bus.publish_after_commit")
    def test_new_creation_persists_canonical_places_without_forcing_exact_points(
        self, publish
    ):
        response = self.client.post(
            reverse("parcels-delivery-v1-create"),
            self._canonical_payload(),
            format="json",
        )

        assert response.status_code == 201, response.data
        parcel = DeliveryRequest.objects.get()
        assert parcel.schema_version == 3
        assert parcel.pickup_place == self.pickup_place
        assert parcel.delivery_place == self.delivery_place
        assert parcel.pickup_location is None
        assert parcel.delivery_location is None
        assert response.data["pickup_place"]["id"] == self.pickup_place.pk
        assert response.data["pickup_location"] is None
        publish.assert_called_once()

    @patch("apps.parcels.views.redis_bus.publish_after_commit")
    def test_canonical_creation_accepts_scoped_preferred_points(self, publish):
        response = self.client.post(
            reverse("parcels-delivery-v1-create"),
            self._canonical_payload(include_locations=True),
            format="json",
        )

        assert response.status_code == 201, response.data
        parcel = DeliveryRequest.objects.get()
        assert parcel.schema_version == 3
        assert parcel.pickup_location == self.pickup
        assert parcel.delivery_location == self.delivery
        assert response.data["pickup_location"]["private_label"].startswith(
            "Apartment 4"
        )
        publish.assert_called_once()

    def test_canonical_creation_requires_both_places(self):
        response = self.client.post(
            reverse("parcels-delivery-v1-create"),
            self._canonical_payload(delivery_place_id=None),
            format="json",
        )

        assert response.status_code == 400
        assert "delivery_place_id" in response.data
        assert DeliveryRequest.objects.count() == 0

    def test_rejects_unconfirmed_safety_declaration(self):
        response = self.client.post(
            reverse("parcels-delivery-v1-create"),
            self._canonical_payload(no_prohibited_goods=False),
            format="json",
        )
        assert response.status_code == 400
        assert "no_prohibited_goods" in response.data
        assert DeliveryRequest.objects.count() == 0

    def test_rejects_legacy_dzd_input(self):
        response = self.client.post(
            reverse("parcels-delivery-v1-create"),
            self._canonical_payload(base_amount_dzd=99_999),
            format="json",
        )
        assert response.status_code == 400
        assert "base_amount_dzd" in response.data
        assert DeliveryRequest.objects.count() == 0

    def test_rejects_location_owned_by_another_user(self):
        other = _make_user("location-owner@example.com")
        private_location = _make_location(
            other,
            city="Lyon",
            suffix="Secret",
        )
        response = self.client.post(
            reverse("parcels-delivery-v1-create"),
            self._canonical_payload(pickup_location_id=private_location.pk),
            format="json",
        )
        assert response.status_code == 400
        assert "pickup_location_id" in response.data
        assert DeliveryRequest.objects.count() == 0

    def test_rejects_incomplete_dimensions_and_invalid_window(self):
        """A partial set is refused; the message names the group, not a side.

        Three identical "this field is required" errors on `length_cm`,
        `width_cm` and `height_cm` are what the device QA saw as an
        unexplained bounce back to the parcel step, because the form had no
        input bound to those keys. One `dimensions` error is the whole story
        and lands where the user is looking.
        """

        response = self.client.post(
            reverse("parcels-delivery-v1-create"),
            self._canonical_payload(width_cm=None),
            format="json",
        )
        assert response.status_code == 400
        assert "dimensions" in response.data
        assert DeliveryRequest.objects.count() == 0

        now = timezone.now()
        response = self.client.post(
            reverse("parcels-delivery-v1-create"),
            self._canonical_payload(
                ready_window_start=(now + timedelta(days=2)).isoformat(),
                ready_window_end=(now + timedelta(days=1)).isoformat(),
            ),
            format="json",
        )
        assert response.status_code == 400
        assert "ready_window_end" in response.data

    def test_model_and_database_reject_mixed_v1_legacy_fields(self):
        with self.assertRaises(ValidationError):
            _create_v1_delivery(
                self.sender,
                self.pickup,
                self.delivery,
                pickup_city="Exact legacy city leak",
            )

        valid = _create_v1_delivery(self.sender, self.pickup, self.delivery)
        with self.assertRaises(IntegrityError), transaction.atomic():
            DeliveryRequest.objects.filter(pk=valid.pk).update(base_amount_dzd=1)


class DeliveryV1PrivacyAndAuthorizationTests(APITestCase):
    def setUp(self):
        self.sender = _make_user("privacy-sender@example.com")
        self.traveler = _make_user("privacy-traveler@example.com")
        self.outsider = _make_user("privacy-outsider@example.com")
        self.pickup = _make_location(self.sender, city="Paris", suffix="Private")
        self.delivery = _make_location(
            self.sender,
            city="Algiers",
            suffix="Recipient",
            country_code="DZ",
        )
        self.open_request = _create_v1_delivery(
            self.sender,
            self.pickup,
            self.delivery,
        )
        self.targeted_request = _create_v1_delivery(
            self.sender,
            self.pickup,
            self.delivery,
            target_traveler=self.traveler,
        )

    def test_owner_receives_private_location_fields(self):
        response = _auth_client(self.sender).get(
            reverse("parcels-detail", args=[self.open_request.pk])
        )
        assert response.status_code == 200
        assert response.data["pickup_location"]["private_label"].startswith(
            "Apartment 4"
        )
        assert "latitude" in response.data["pickup_location"]
        assert "provider_metadata" in response.data["pickup_location"]

    def test_other_user_receives_only_coarse_location_fields(self):
        response = _auth_client(self.outsider).get(
            reverse("parcels-detail", args=[self.open_request.pk])
        )
        assert response.status_code == 200
        pickup = response.data["pickup_location"]
        assert pickup["public_label"] == "Paris"
        assert pickup["coarse_latitude"] == "48.850000"
        for exact_field in (
            "normalized_label",
            "private_label",
            "latitude",
            "longitude",
            "provider_place_id",
            "provider_metadata",
        ):
            assert exact_field not in pickup

    def test_only_owner_or_target_can_read_targeted_request(self):
        target_response = _auth_client(self.traveler).get(
            reverse("parcels-detail", args=[self.targeted_request.pk])
        )
        assert target_response.status_code == 200
        assert "private_label" not in target_response.data["pickup_location"]

        outsider_response = _auth_client(self.outsider).get(
            reverse("parcels-detail", args=[self.targeted_request.pk])
        )
        assert outsider_response.status_code == 403

    def test_open_feed_excludes_targeted_requests_and_keeps_locations_coarse(self):
        response = _auth_client(self.outsider).get(reverse("parcels-open-search"))
        assert response.status_code == 200
        assert [row["id"] for row in response.data] == [self.open_request.id]
        assert "private_label" not in response.data[0]["pickup_location"]


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

    def test_product_kind_is_excluded_from_live_list(self):
        DeliveryRequest.objects.create(
            sender=self.user,
            kind="delivery",
            origin_id="ALG",
            destination_id="CDG",
            weight_kg=2,
            base_amount_dzd=2000,
        )
        ProductRequest.objects.create(
            sender=self.user,
            kind="product",
            origin_id="ALG",
            destination_id="CDG",
            weight_kg=2,
            product_price_dzd=10000,
        )
        r = self.client.get(reverse("parcels-list"), {"kind": "product"})
        assert r.status_code == 200
        assert r.data == []


class ParcelCancelTests(APITestCase):
    def setUp(self):
        self.user = _make_user()
        self.other = _make_user(email="other@example.com")
        self.client = _auth_client(self.user)
        self.parcel = DeliveryRequest.objects.create(
            sender=self.user,
            kind="delivery",
            origin_id="ALG",
            destination_id="CDG",
            weight_kg=2,
            base_amount_dzd=2000,
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
        self.other = _make_user("history-outsider@example.com")
        self.client = _auth_client(self.user)
        self.delivery = DeliveryRequest.objects.create(
            sender=self.user,
            kind="delivery",
            origin_id="ALG",
            destination_id="CDG",
            weight_kg=2,
            base_amount_dzd=2000,
        )
        self.product = ProductRequest.objects.create(
            sender=self.user,
            kind="product",
            origin_id="CDG",
            destination_id="ALG",
            weight_kg=1,
            product_price_dzd=20000,
            store_name="Apple",
            product_url="https://apple.com/x",
        )

    def test_delivery_detail_includes_base_amount(self):
        r = self.client.get(reverse("parcels-detail", args=[self.delivery.pk]))
        assert r.status_code == 200
        assert r.data["base_amount_dzd"] == 2000
        assert r.data["product_price_dzd"] is None

    def test_product_detail_is_retired_even_for_owner(self):
        r = self.client.get(reverse("parcels-detail", args=[self.product.pk]))
        assert r.status_code == 410

    def test_product_history_is_not_visible_to_other_users(self):
        r = _auth_client(self.other).get(
            reverse("parcels-detail", args=[self.product.pk])
        )
        assert r.status_code == 410

    def test_404_for_unknown(self):
        r = self.client.get(reverse("parcels-detail", args=[9999]))
        assert r.status_code == 404


class DeliveryQuoteTests(APITestCase):
    """The legacy DZD quote cannot participate in the V1 EUR flow."""

    def setUp(self):
        self.user = _make_user("quote@example.com")
        self.client = _auth_client(self.user)

    def test_unauth_rejected(self):
        c = APIClient()
        r = c.get(reverse("parcels-quote-delivery"), {"weight_kg": 2})
        assert r.status_code == 401

    def test_legacy_dzd_quote_is_gone(self):
        r = self.client.get(
            reverse("parcels-quote-delivery"),
            {"weight_kg": 3, "origin": "ALG", "destination": "CDG"},
        )
        assert r.status_code == 410
        assert r.data["code"] == "legacy_dzd_quote_retired"
        assert "suggested_base_dzd" not in r.data


class ParcelMediaPrivacyTests(APITestCase):
    """Regression — media serializer must NOT leak storage bucket/object_key."""

    def setUp(self):
        self.user = _make_user("media-priv@example.com")
        self.client = _auth_client(self.user)
        self.delivery = DeliveryRequest.objects.create(
            sender=self.user,
            kind=ParcelRequest.Kind.DELIVERY,
            origin_id="ALG",
            destination_id="CDG",
            weight_kg=1,
            item_type=ParcelRequest.ItemType.DOCUMENTS,
            description="x",
            base_amount_dzd=2000,
        )
        ParcelMedia.objects.create(
            parcel=self.delivery,
            bucket="parcels-private",
            object_key="users/42/some-uuid.jpg",
            content_type="image/jpeg",
            bytes=12345,
        )

    def test_detail_does_not_leak_storage_keys(self):
        r = self.client.get(reverse("parcels-detail", args=[self.delivery.pk]))
        assert r.status_code == 200
        assert r.data["media"], "expected media in response"
        m = r.data["media"][0]
        assert "bucket" not in m
        assert "object_key" not in m
        # but useful fields are still there
        assert m["content_type"] == "image/jpeg"
        assert m["bytes"] == 12345


class OpenParcelSearchTests(APITestCase):
    def setUp(self):
        self.sender = _make_user("send1@example.com")
        self.other_sender = _make_user("send2@example.com")
        self.traveler = _make_user("trav@example.com")

        self.p_open = DeliveryRequest.objects.create(
            sender=self.other_sender,
            kind=ParcelRequest.Kind.DELIVERY,
            origin_id="ALG",
            destination_id="CDG",
            weight_kg=2,
            item_type="documents",
            base_amount_dzd=3000,
        )
        self.p_own = DeliveryRequest.objects.create(
            sender=self.sender,
            kind=ParcelRequest.Kind.DELIVERY,
            origin_id="ALG",
            destination_id="CDG",
            weight_kg=2,
            item_type="documents",
            base_amount_dzd=3000,
        )
        self.p_matched = DeliveryRequest.objects.create(
            sender=self.other_sender,
            kind=ParcelRequest.Kind.DELIVERY,
            origin_id="ALG",
            destination_id="CDG",
            weight_kg=2,
            item_type="documents",
            base_amount_dzd=3000,
            status=ParcelRequest.Status.MATCHED,
        )
        self.p_targeted = DeliveryRequest.objects.create(
            sender=self.other_sender,
            target_traveler=self.traveler,
            kind=ParcelRequest.Kind.DELIVERY,
            origin_id="ALG",
            destination_id="CDG",
            weight_kg=2,
            item_type="documents",
            base_amount_dzd=3000,
        )
        self.p_product = ProductRequest.objects.create(
            sender=self.other_sender,
            kind=ParcelRequest.Kind.PRODUCT,
            origin_id="ALG",
            destination_id="CDG",
            weight_kg=2,
            item_type="electronics",
            product_price_dzd=20_000,
        )

    def test_legacy_open_requests_are_not_in_v1_feed(self):
        c = _auth_client(self.sender)
        r = c.get(reverse("parcels-open-search"))
        assert r.status_code == 200
        ids = {row["id"] for row in r.data}
        assert ids == set()

    def test_retired_airport_filters_are_rejected_instead_of_returning_nothing(self):
        c = _auth_client(self.sender)

        both = c.get(reverse("parcels-open-search") + "?origin=ALG&destination=CDG")
        origin_only = c.get(reverse("parcels-open-search") + "?origin=ALG")

        assert both.status_code == 400
        assert both.data["code"] == "airport_filter_retired"
        assert both.data["retired_parameters"] == ["destination", "origin"]
        assert origin_only.status_code == 400
        assert origin_only.data["retired_parameters"] == ["origin"]

    def test_filters_by_max_weight(self):
        c = _auth_client(self.traveler)
        r = c.get(reverse("parcels-open-search") + "?max_weight_kg=1")
        assert r.status_code == 200
        assert r.data == []

    def test_requires_auth(self):
        c = APIClient()
        r = c.get(reverse("parcels-open-search"))
        assert r.status_code in (401, 403)
