"""Small, dependency-free request correlation and access logging middleware."""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import ExitStack

from django.conf import settings
from django.db import connections
from django.http import HttpRequest, HttpResponse

logger = logging.getLogger("shiptrip.request")
performance_logger = logging.getLogger("shiptrip.performance")


class _QueryMetrics:
    """Count and time queries without retaining SQL or parameter values."""

    def __init__(self) -> None:
        self.count = 0
        self.duration_ms = 0.0

    def __call__(self, execute, sql, params, many, context):  # noqa: ANN001
        started = time.monotonic()
        try:
            return execute(sql, params, many, context)
        finally:
            self.count += 1
            self.duration_ms += (time.monotonic() - started) * 1000


def _safe_route(request: HttpRequest) -> str:
    route = getattr(getattr(request, "resolver_match", None), "route", None)
    return f"/{route}" if route else "<unmatched>"


def _actor_class(request: HttpRequest) -> str:
    match = getattr(request, "resolver_match", None)
    namespaces = set(getattr(match, "namespaces", ()) or ())
    route = str(getattr(match, "route", "") or "")
    if "admin" in namespaces or "admin_console" in namespaces or route.startswith("admin"):
        return "admin"
    user = getattr(request, "user", None)
    return "authenticated" if getattr(user, "is_authenticated", False) else "anonymous"


class RequestIDMiddleware:
    """Attach a server-generated correlation id to every response.

    We intentionally do not trust a caller-supplied id: accepting arbitrary
    header values makes log correlation spoofable and can inject control
    characters into line-oriented log sinks.  The id is safe to return to a
    client so support can ask for it without exposing request data.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_id = uuid.uuid4().hex
        request.request_id = request_id
        started = time.monotonic()
        query_metrics = _QueryMetrics()
        if settings.PERFORMANCE_DB_METRICS_ENABLED:
            with ExitStack() as stack:
                initialized_databases = list(connections.all(initialized_only=True))
                for database in initialized_databases:
                    stack.enter_context(database.execute_wrapper(query_metrics))
                # The default connection may not be initialized until the
                # first view query. Accessing it installs the wrapper without
                # opening a network connection by itself.
                if not any(db.alias == "default" for db in initialized_databases):
                    stack.enter_context(
                        connections["default"].execute_wrapper(query_metrics)
                    )
                response = self.get_response(request)
        else:
            response = self.get_response(request)
        elapsed_ms = round((time.monotonic() - started) * 1000, 2)
        response["X-Request-ID"] = request_id
        if response.status_code >= 400:
            logger.warning(
                "request completed with error",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    # Log only the source-defined route template. Concrete
                    # path values can contain guest capability tokens or
                    # other identifiers and must not enter the log stream.
                    "path": _safe_route(request),
                    "status": response.status_code,
                    "duration_ms": elapsed_ms,
                },
            )
        if elapsed_ms >= settings.PERFORMANCE_SLOW_REQUEST_MS:
            fields = {
                "event": "slow_http_request",
                "request_id": request_id,
                "method": request.method,
                "path": _safe_route(request),
                "status": response.status_code,
                "duration_ms": elapsed_ms,
                "actor_class": _actor_class(request),
            }
            if settings.PERFORMANCE_DB_METRICS_ENABLED:
                fields.update(
                    db_queries=query_metrics.count,
                    db_time_ms=round(query_metrics.duration_ms, 2),
                )
            performance_logger.info("slow HTTP request", extra=fields)
        return response
