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
    def test_readiness_fails_when_the_distributed_rate_limit_cache_is_unusable(self):
        response = self.client.get("/readyz")

        assert response.status_code == 503
        assert response.json()["status"] == "not_ready"
        assert response.json()["checks"]["rate_limit_cache"] == "failed"

    def test_error_logging_uses_route_templates_not_capability_values(self):
        capability = "do-not-log-this-guest-capability"

        with self.assertLogs("shiptrip.request", level="WARNING") as captured:
            response = self.client.get(f"/api/payments/guest/{capability}")

        assert response.status_code == 404
        record = captured.records[0]
        assert capability not in record.path
        assert record.path == "/api/payments/guest/<str:token>"
