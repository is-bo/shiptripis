from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User

from ..permissions import AdminRole, assign_admin_roles


class AdminDeepHealthTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="ops-health@example.com",
            email="ops-health@example.com",
            password="Test-password-123!",
            full_name="Ops Health",
        )
        assign_admin_roles(self.user, (AdminRole.OPS,))
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    @patch("apps.admin_panel.health.redis.Redis.from_url")
    def test_deep_health_is_permissioned_and_contains_safe_aggregates(self, from_url):
        from_url.return_value.ping.return_value = True

        response = self.client.get("/api/admin/health/deep")

        assert response.status_code == 200
        assert response["Cache-Control"] == "no-store"
        assert response.data["checks"]["redis"] == "ok"
        assert "scheduled_jobs" in response.data["checks"]
        serialized = str(response.data).lower()
        for forbidden in ("password", "secret_key", "bearer_token", "webhook_secret"):
            assert forbidden not in serialized

    def test_ordinary_authenticated_user_is_forbidden(self):
        ordinary = User.objects.create_user(
            username="ordinary-health@example.com",
            email="ordinary-health@example.com",
            password="Test-password-123!",
            full_name="Ordinary",
        )
        self.client.force_authenticate(ordinary)

        response = self.client.get("/api/admin/health/deep")

        assert response.status_code == 403
