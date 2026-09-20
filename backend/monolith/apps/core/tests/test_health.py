from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings


class HealthEndpointTests(TestCase):
    @override_settings(RELEASE_ID="test-release")
    def test_liveness_is_cheap_and_exposes_only_release_metadata(self):
        response = self.client.get("/healthz")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "release": "test-release"}
        assert response.headers["Cache-Control"] == "no-store"
        assert len(response.headers["X-Request-ID"]) == 32

    @override_settings(RELEASE_ID="test-release")
    def test_readiness_checks_database_and_migrations(self):
        response = self.client.get("/readyz")

        assert response.status_code == 200
        assert response.json()["checks"] == {
            "database": "ok",
            "migrations": "ok",
            "rate_limit_cache": "ok",
        }

    @override_settings(
        CACHES={"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}
    )
    def test_readiness_reports_optional_cache_degradation_without_restart_signal(self):
        response = self.client.get("/readyz")

        assert response.status_code == 200
        assert response.json()["status"] == "degraded"
        assert response.json()["checks"]["rate_limit_cache"] == "degraded"

    @patch("apps.core.health.connection.cursor", side_effect=OSError("database down"))
    def test_database_unavailable_is_not_ready(self, _cursor):
        response = self.client.get("/readyz")

        assert response.status_code == 503
        assert response.json()["status"] == "not_ready"
        assert response.json()["checks"]["database"] == "failed"

    @patch("apps.core.health.MigrationExecutor")
    def test_pending_migration_is_not_ready(self, executor_class):
        executor = MagicMock()
        executor.loader.graph.leaf_nodes.return_value = [("core", "9999_pending")]
        executor.migration_plan.return_value = [object()]
        executor_class.return_value = executor

        response = self.client.get("/readyz")

        assert response.status_code == 503
        assert response.json()["status"] == "not_ready"
        assert response.json()["checks"]["migrations"] == "pending"

    @override_settings(
        CACHES={"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}
    )
    @patch("apps.core.health.connection.cursor", side_effect=OSError("database down"))
    def test_hard_failure_stays_closed_when_cache_is_also_degraded(self, _cursor):
        response = self.client.get("/readyz")

        assert response.status_code == 503
        assert response.json()["checks"] == {
            "database": "failed",
            "migrations": "ok",
            "rate_limit_cache": "degraded",
        }

    def test_error_logging_uses_route_templates_not_capability_values(self):
        capability = "do-not-log-this-guest-capability"

        with self.assertLogs("shiptrip.request", level="WARNING") as captured:
            response = self.client.get(f"/api/payments/guest/{capability}")

        assert response.status_code == 404
        record = captured.records[0]
        assert capability not in record.path
        assert record.path == "/api/payments/guest/<str:token>"
