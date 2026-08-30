"""Cheap liveness/readiness probes shared by Django and the edge gateway."""

from __future__ import annotations

from django.core.cache import caches
from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.http import JsonResponse


def _response(payload: dict, *, status: int = 200) -> JsonResponse:
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "no-store"
    return response


def healthz(_request):
    """Liveness: proves only that the Python process can answer HTTP."""

    return _response({"status": "ok", "release": settings.RELEASE_ID})


def readyz(_request):
    """Readiness: database and migration graph must be usable.

    Redis, object storage and payment providers are intentionally not part of
    this public probe. Redis is a delivery optimisation and provider outages
    must not make the API disappear; those dependencies are surfaced by the
    permissioned deep-health endpoint instead.
    """

    checks = {"database": "ok", "migrations": "ok", "rate_limit_cache": "ok"}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        checks["database"] = "failed"

    if checks["database"] == "ok":
        try:
            executor = MigrationExecutor(connection)
            if executor.migration_plan(executor.loader.graph.leaf_nodes()):
                checks["migrations"] = "pending"
        except Exception:
            checks["migrations"] = "failed"

    try:
        cache = caches["default"]
        marker = settings.RELEASE_ID or "unknown"
        cache_key = f"readyz:{marker}"
        cache.set(cache_key, marker, timeout=5)
        if cache.get(cache_key) != marker:
            checks["rate_limit_cache"] = "failed"
    except Exception:
        checks["rate_limit_cache"] = "failed"

    ready = all(value == "ok" for value in checks.values())
    return _response(
        {
            "status": "ready" if ready else "not_ready",
            "release": settings.RELEASE_ID,
            "checks": checks,
        },
        status=200 if ready else 503,
    )
