from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from apps.core.middleware import RequestIDMiddleware


class PerformanceLoggingTests(TestCase):
    @override_settings(
        PERFORMANCE_SLOW_REQUEST_MS=60_000,
        PERFORMANCE_DB_METRICS_ENABLED=False,
    )
    def test_fast_request_does_not_emit_performance_noise(self):
        with self.assertNoLogs("shiptrip.performance"):
            response = self.client.get("/healthz")

        assert response.status_code == 200

    @override_settings(
        PERFORMANCE_SLOW_REQUEST_MS=0,
        PERFORMANCE_DB_METRICS_ENABLED=True,
    )
    def test_slow_event_has_safe_route_actor_and_database_measurements(self):
        request = RequestFactory().get("/admin/users/?token=do-not-log")
        request.resolver_match = SimpleNamespace(
            route="admin/users/", namespaces=("admin_console",)
        )
        request.user = SimpleNamespace(is_authenticated=True)

        def response(_request):
            get_user_model().objects.count()
            return HttpResponse(status=200)

        middleware = RequestIDMiddleware(response)
        with self.assertLogs("shiptrip.performance", level="INFO") as captured:
            result = middleware(request)

        assert result.status_code == 200
        record = captured.records[0]
        assert record.event == "slow_http_request"
        assert record.path == "/admin/users/"
        assert record.actor_class == "admin"
        assert record.db_queries == 1
        assert record.db_time_ms >= 0
        assert "do-not-log" not in str(record.__dict__)

    @override_settings(
        PERFORMANCE_SLOW_REQUEST_MS=0,
        PERFORMANCE_DB_METRICS_ENABLED=False,
    )
    def test_concrete_capability_and_query_are_absent(self):
        capability = "private-guest-capability"

        with self.assertLogs("shiptrip.performance", level="INFO") as captured:
            response = self.client.get(
                f"/api/payments/guest/{capability}?token=private-query-token"
            )

        assert response.status_code == 404
        record = captured.records[0]
        assert record.path == "/api/payments/guest/<str:token>"
        assert capability not in str(record.__dict__)
        assert "private-query-token" not in str(record.__dict__)
