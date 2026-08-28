from types import SimpleNamespace

from django.db import IntegrityError, transaction
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.locations.models import Location
from apps.locations.permissions import IsLocationCreatorOrReadOnly


PRIVATE_FIELDS = {
    "normalized_label",
    "private_label",
    "latitude",
    "longitude",
    "provider",
    "source",
    "provider_place_id",
    "provider_metadata",
    "created_by_id",
    "owner_id",
    "updated_at",
}


def _make_user(email: str) -> User:
    return User.objects.create_user(
        username=email,
        email=email,
        password="Sup3rStrongPass!",
        full_name="Location User",
    )


def _client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _payload(**overrides) -> dict:
    payload = {
        "kind": Location.Kind.EXACT_ADDRESS,
        "normalized_label": "12 rue Exemple, 75010 Paris, France",
        "private_label": "12 rue Exemple, 75010 Paris, France",
        "city": "Paris",
        "region": "Île-de-France",
        "country_code": "fr",
        "latitude": "48.876100",
        "longitude": "2.359900",
        "provider": "example_maps",
        "source": "geocoder",
        "provider_place_id": "place-paris-12",
        "provider_metadata": {"formatted_address": "12 rue Exemple"},
        "precision": Location.Precision.ROOFTOP,
    }
    payload.update(overrides)
    return payload


class LocationApiPrivacyTests(APITestCase):
    def setUp(self):
        self.owner = _make_user("owner@example.com")
        self.other = _make_user("other@example.com")
        response = _client(self.owner).post(
            reverse("locations-list-create"),
            _payload(),
            format="json",
        )
        assert response.status_code == 201, response.data
        self.location = Location.objects.get(pk=response.data["id"])

    def test_owner_detail_contains_private_fields(self):
        response = _client(self.owner).get(
            reverse("locations-detail", kwargs={"pk": self.location.pk})
        )

        assert response.status_code == 200
        assert PRIVATE_FIELDS.issubset(response.data)
        assert response.data["private_label"].startswith("12 rue")
        assert response.data["provider_metadata"]["formatted_address"].startswith(
            "12 rue"
        )

    def test_non_owner_detail_contains_only_coarse_fields(self):
        response = _client(self.other).get(
            reverse("locations-detail", kwargs={"pk": self.location.pk})
        )

        assert response.status_code == 200
        assert PRIVATE_FIELDS.isdisjoint(response.data)
        assert response.data["public_label"] == "Paris, FR"
        assert response.data["coarse_latitude"] == "48.900000"
        assert response.data["coarse_longitude"] == "2.400000"

    def test_list_selects_visibility_for_each_object(self):
        other_location = Location.objects.create(
            owner=self.other,
            created_by=self.other,
            public_label="Algiers, DZ",
            coarse_latitude="36.800000",
            coarse_longitude="3.000000",
            **{
                field: value
                for field, value in _payload(
                    provider_place_id="other-place",
                    city="Algiers",
                ).items()
                if field != "country_code"
            },
            country_code="DZ",
        )

        response = _client(self.owner).get(reverse("locations-list-create"))

        assert response.status_code == 200
        by_id = {row["id"]: row for row in response.data}
        assert PRIVATE_FIELDS.issubset(by_id[self.location.id])
        assert other_location.id not in by_id

    def test_unauthenticated_callers_are_rejected(self):
        anonymous = APIClient()
        list_response = anonymous.get(reverse("locations-list-create"))
        detail_response = anonymous.get(
            reverse("locations-detail", kwargs={"pk": self.location.pk})
        )

        assert list_response.status_code == 401
        assert detail_response.status_code == 401


class LocationCreateValidationTests(APITestCase):
    def setUp(self):
        self.user = _make_user("creator@example.com")
        self.client = _client(self.user)

    def test_create_assigns_identity_server_side_and_normalizes_country(self):
        response = self.client.post(
            reverse("locations-list-create"),
            _payload(),
            format="json",
        )

        assert response.status_code == 201, response.data
        location = Location.objects.get(pk=response.data["id"])
        assert location.created_by == self.user
        assert location.owner == self.user
        assert location.country_code == "FR"

    def test_rejects_client_supplied_owner_or_creator(self):
        response = self.client.post(
            reverse("locations-list-create"),
            _payload(owner_id=999, created_by_id=999),
            format="json",
        )

        assert response.status_code == 400
        assert {"owner_id", "created_by_id"}.issubset(response.data)
        assert Location.objects.count() == 0

    def test_rejects_out_of_range_exact_coordinates(self):
        response = self.client.post(
            reverse("locations-list-create"),
            _payload(latitude="90.000001"),
            format="json",
        )

        assert response.status_code == 400
        assert "latitude" in response.data

    def test_rejects_client_supplied_public_or_coarse_values(self):
        response = self.client.post(
            reverse("locations-list-create"),
            _payload(
                public_label="12 rue Exemple",
                coarse_latitude="48.876100",
                coarse_longitude="2.359900",
            ),
            format="json",
        )

        assert response.status_code == 400
        assert {"public_label", "coarse_latitude", "coarse_longitude"}.issubset(
            response.data
        )

    def test_rejects_non_object_provider_metadata(self):
        response = self.client.post(
            reverse("locations-list-create"),
            _payload(provider_metadata=["not", "an", "object"]),
            format="json",
        )

        assert response.status_code == 400
        assert "provider_metadata" in response.data

    def test_rejects_duplicate_nonblank_provider_place(self):
        first = self.client.post(
            reverse("locations-list-create"),
            _payload(),
            format="json",
        )
        second = self.client.post(
            reverse("locations-list-create"),
            _payload(private_label="Different private label"),
            format="json",
        )

        assert first.status_code == 201, first.data
        assert second.status_code == 400
        assert "provider_place_id" in second.data
        assert Location.objects.count() == 1

    def test_different_owners_may_save_the_same_provider_place(self):
        first = self.client.post(
            reverse("locations-list-create"),
            _payload(),
            format="json",
        )
        other = _make_user("same-place-owner@example.com")
        second = _client(other).post(
            reverse("locations-list-create"),
            _payload(),
            format="json",
        )

        assert first.status_code == 201, first.data
        assert second.status_code == 201, second.data
        assert Location.objects.filter(provider_place_id="place-paris-12").count() == 2

    def test_database_rejects_unpaired_coarse_coordinates(self):
        data = _payload(provider_place_id="db-pair-check")
        data["country_code"] = "FR"
        data["public_label"] = "Paris, FR"
        data["coarse_latitude"] = "48.900000"

        with self.assertRaises(IntegrityError), transaction.atomic():
            Location.objects.create(
                owner=self.user,
                created_by=self.user,
                **data,
            )


class LocationAuthorizationTests(APITestCase):
    def setUp(self):
        self.creator = _make_user("creator-auth@example.com")
        self.owner = _make_user("owner-auth@example.com")
        self.location = Location.objects.create(
            created_by=self.creator,
            owner=self.owner,
            public_label="Paris, FR",
            coarse_latitude="48.900000",
            coarse_longitude="2.400000",
            **{
                **_payload(provider_place_id="auth-place"),
                "country_code": "FR",
            },
        )

    def test_api_has_no_update_or_delete_endpoint(self):
        detail_url = reverse("locations-detail", kwargs={"pk": self.location.pk})
        patch_response = _client(self.creator).patch(
            detail_url,
            {"public_label": "Mutated"},
            format="json",
        )
        delete_response = _client(self.creator).delete(detail_url)

        assert patch_response.status_code == 405
        assert delete_response.status_code == 405
        self.location.refresh_from_db()
        assert self.location.public_label == "Paris, FR"

    def test_mutation_permission_is_creator_only(self):
        permission = IsLocationCreatorOrReadOnly()
        creator_request = SimpleNamespace(method="PATCH", user=self.creator)
        owner_request = SimpleNamespace(method="PATCH", user=self.owner)
        reader_request = SimpleNamespace(method="GET", user=self.owner)

        assert permission.has_object_permission(creator_request, None, self.location)
        assert not permission.has_object_permission(owner_request, None, self.location)
        assert permission.has_object_permission(reader_request, None, self.location)
