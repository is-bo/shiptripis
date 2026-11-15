"""L18A: a sender verifies their email before posting a parcel.

V1 specification, "Sender launch verification is email-only". The flag and the
code screen existed and nothing enforced them. Creating a delivery request is
now refused with `email_verification_required` while the flag is false; a
Google account arrives verified. Nothing else is gated.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.finance.models import PaymentOrder
from apps.locations.models import Country, Place
from apps.parcels.models import ParcelMedia, ParcelRequest
from apps.parcels.views import EMAIL_VERIFICATION_REQUIRED

CREATE_URL = reverse("parcels-delivery-v1-create")
QUOTE_URL = reverse("parcels-pricing-quote")


@patch("apps.core.redis_bus.publish_after_commit")
class SenderEmailGateTests(TestCase):
    def setUp(self):
        france = Country.objects.create(
            code="FR", name="France", source="l18a", source_id="l18a-fr", source_version="l18a"
        )
        algeria = Country.objects.create(
            code="DZ", name="Algeria", source="l18a", source_id="l18a-dz", source_version="l18a"
        )
        self.pickup_place = Place.objects.create(
            country=france,
            place_type=Place.PlaceType.LOCALITY,
            source="l18a",
            source_id="l18a-paris",
            source_version="l18a",
            name="Paris",
            latitude=Decimal("48.856614"),
            longitude=Decimal("2.352222"),
        )
        self.delivery_place = Place.objects.create(
            country=algeria,
            place_type=Place.PlaceType.LOCALITY,
            source="l18a",
            source_id="l18a-algiers",
            source_version="l18a",
            name="Algiers",
            latitude=Decimal("36.737232"),
            longitude=Decimal("3.086472"),
        )

    def _sender(self, email: str, *, verified: bool) -> User:
        return User.objects.create_user(
            username=email,
            email=email,
            password="Sup3rStrongPass!",
            full_name="Gate Sender",
            is_email_verified=verified,
        )

    def _client(self, user: User) -> APIClient:
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def _payload(self, sender: User) -> dict:
        now = timezone.now()
        photo = ParcelMedia.objects.create(
            parcel=None,
            uploaded_by=sender,
            purpose=ParcelMedia.Purpose.ITEM_PHOTO,
            bucket="shiptrip-parcel-test",
            object_key=f"parcels/staged/{sender.pk}/{uuid4().hex}.jpg",
            content_type="image/jpeg",
            bytes=2048,
        )
        return {
            "pickup_place_id": self.pickup_place.pk,
            "delivery_place_id": self.delivery_place.pk,
            "ready_window_start": (now + timedelta(days=1)).isoformat(),
            "ready_window_end": (now + timedelta(days=1, hours=2)).isoformat(),
            "deadline_at": (now + timedelta(days=3)).isoformat(),
            "actual_weight_kg": "2.50",
            "declared_value_eur_cents": 12_500,
            "sender_proposed_reward_eur_cents": 3_000,
            "title": "Documents for Algiers",
            "description": "A sealed folder of personal documents.",
            "category": "documents",
            "handling_notes": "",
            "fragile": False,
            "description_is_accurate": True,
            "item_is_legal": True,
            "no_prohibited_goods": True,
            "declared_value_is_accurate": True,
            "customs_responsibilities_understood": True,
            "item_photo_media_id": photo.pk,
        }

    def _tables(self) -> tuple[int, int, int]:
        return (
            ParcelRequest.objects.count(),
            PaymentOrder.objects.count(),
            ParcelMedia.objects.filter(parcel__isnull=False).count(),
        )

    def test_an_unverified_sender_is_refused_and_nothing_is_written(self, _publish):
        sender = self._sender("l18a-unverified@example.com", verified=False)
        payload = self._payload(sender)
        before = self._tables()

        response = self._client(sender).post(CREATE_URL, payload, format="json")

        assert response.status_code == 403, response.data
        assert response.data["code"] == EMAIL_VERIFICATION_REQUIRED == "email_verification_required"
        assert response.data["detail"]
        assert self._tables() == before
        photo = ParcelMedia.objects.get(pk=payload["item_photo_media_id"])
        assert photo.parcel_id is None

    def test_the_refusal_comes_before_validation(self, _publish):
        sender = self._sender("l18a-empty@example.com", verified=False)
        response = self._client(sender).post(CREATE_URL, {}, format="json")
        assert response.status_code == 403
        assert response.data["code"] == EMAIL_VERIFICATION_REQUIRED

    def test_a_verified_sender_posts(self, _publish):
        sender = self._sender("l18a-verified@example.com", verified=True)
        response = self._client(sender).post(CREATE_URL, self._payload(sender), format="json")
        assert response.status_code == 201, response.data
        assert ParcelRequest.objects.filter(sender=sender).count() == 1

    def test_verifying_opens_the_door(self, _publish):
        sender = self._sender("l18a-later@example.com", verified=False)
        client = self._client(sender)
        assert client.post(CREATE_URL, self._payload(sender), format="json").status_code == 403

        User.objects.filter(pk=sender.pk).update(is_email_verified=True)
        sender.refresh_from_db()
        client.force_authenticate(user=sender)
        response = client.post(CREATE_URL, self._payload(sender), format="json")
        assert response.status_code == 201, response.data

    @patch("apps.accounts.views.verify_id_token")
    def test_a_google_account_posts(self, mock_verify, _publish):
        mock_verify.return_value = {
            "sub": "l18a-google-sub",
            "email": "l18a-google@example.com",
            "email_verified": True,
            "name": "Google Sender",
        }
        signed_in = APIClient().post(
            reverse("auth-oauth-google"), {"id_token": "fake"}, format="json"
        )
        assert signed_in.status_code == 200, signed_in.data
        sender = User.objects.get(email="l18a-google@example.com")
        assert sender.is_email_verified is True

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {signed_in.data['access']}")
        response = client.post(CREATE_URL, self._payload(sender), format="json")
        assert response.status_code == 201, response.data

    @patch("apps.accounts.views.verify_id_token")
    def test_google_sign_in_verifies_an_unconfirmed_password_account(self, mock_verify, _publish):
        sender = self._sender("l18a-linked@example.com", verified=False)
        mock_verify.return_value = {
            "sub": "l18a-linked-sub",
            "email": "L18A-Linked@example.com",
            "email_verified": True,
            "name": "Linked Sender",
        }
        signed_in = APIClient().post(
            reverse("auth-oauth-google"), {"id_token": "fake"}, format="json"
        )
        assert signed_in.status_code == 200, signed_in.data
        sender.refresh_from_db()
        assert sender.is_email_verified is True

    @patch("apps.accounts.views.verify_id_token")
    def test_google_takes_an_unconfirmed_account_away_from_its_password(
        self, mock_verify, _publish
    ):
        """Whoever chose the password never proved they own the address.

        Anyone can sign up with someone else's email. When the real owner then
        signs in with Google, the stranger's password and sessions must stop
        working, or they would sit inside a verified account.
        """

        squatter = APIClient()
        signed_up = squatter.post(
            reverse("auth-sign-up"),
            {
                "email": "l18a-owner@example.com",
                "password": "Sup3rStrongPass!",
                "full_name": "Not The Owner",
                "phone": "+213555111444",
                "wilaya": "16",
            },
            format="json",
        )
        assert signed_up.status_code == 201, signed_up.data
        mock_verify.return_value = {
            "sub": "l18a-owner-sub",
            "email": "l18a-owner@example.com",
            "email_verified": True,
            "name": "Real Owner",
        }
        assert APIClient().post(
            reverse("auth-oauth-google"), {"id_token": "fake"}, format="json"
        ).status_code == 200

        account = User.objects.get(email="l18a-owner@example.com")
        assert account.is_email_verified is True
        assert account.has_usable_password() is False
        refreshed = APIClient().post(
            reverse("auth-refresh"), {"refresh": signed_up.data["refresh"]}, format="json"
        )
        assert refreshed.status_code == 401
        signed_in = APIClient().post(
            reverse("auth-sign-in"),
            {"email": "l18a-owner@example.com", "password": "Sup3rStrongPass!"},
            format="json",
        )
        assert signed_in.status_code != 200

    @patch("apps.accounts.views.verify_id_token")
    def test_google_links_a_verified_account_and_keeps_its_password(
        self, mock_verify, _publish
    ):
        sender = self._sender("l18a-kept@example.com", verified=True)
        mock_verify.return_value = {
            "sub": "l18a-kept-sub",
            "email": "l18a-kept@example.com",
            "email_verified": True,
            "name": "Kept",
        }
        assert APIClient().post(
            reverse("auth-oauth-google"), {"id_token": "fake"}, format="json"
        ).status_code == 200
        sender.refresh_from_db()
        assert sender.has_usable_password() is True

    def test_nothing_else_is_gated(self, _publish):
        """The price quote, the photo staging and the account stay open."""

        sender = self._sender("l18a-other@example.com", verified=False)
        client = self._client(sender)
        now = timezone.now()
        quote = client.post(
            QUOTE_URL,
            {
                "pickup_place_id": self.pickup_place.pk,
                "delivery_place_id": self.delivery_place.pk,
                "actual_weight_kg": "2.50",
                "ready_window_end": (now + timedelta(days=1, hours=2)).isoformat(),
                "deadline_at": (now + timedelta(days=3)).isoformat(),
            },
            format="json",
        )
        assert quote.status_code == 200, quote.data
        assert client.get(reverse("me")).status_code == 200
        assert client.get(reverse("parcels-list")).status_code == 200
