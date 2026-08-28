from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User


class LegacyTripRetirementTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="legacy-trip@example.com",
            email="legacy-trip@example.com",
            password="Sup3rStrongPass!",
            full_name="Legacy Trip User",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_legacy_trip_creation_is_gone(self):
        response = self.client.post(
            reverse("trips-list-create"), {}, format="json"
        )

        assert response.status_code == 410
        assert response.data["code"] == "legacy_trip_flow_retired"

    def test_legacy_trip_search_is_gone(self):
        response = self.client.get(reverse("trips-search"))

        assert response.status_code == 410
        assert response.data["code"] == "legacy_trip_search_retired"
