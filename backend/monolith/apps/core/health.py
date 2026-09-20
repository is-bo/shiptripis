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

    Redis is measured here but is not a hard HTTP readiness dependency. It
    carries cache/throttle state and non-financial delivery transports; an
    outage is operationally significant, but restarting Django cannot repair
    it and would also remove otherwise-safe database-backed API operations.
    Object storage and payment providers remain on the permissioned deep-health
    surface rather than this orchestrator probe.
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
            checks["rate_limit_cache"] = "degraded"
    except Exception:
        checks["rate_limit_cache"] = "degraded"

    # Database access and the applied schema are hard dependencies for every
    # authoritative request. Redis is different: it accelerates delivery,
    # caches routes and holds shared throttle counters, but never owns money,
    # capacity or a delayed financial obligation. Redis-backed security gates
    # fail closed at their own request boundaries (notably DRF throttles and
    # KYC upload limiting). Restarting a healthy web process cannot repair an
    # external Redis outage and would turn a degraded subsystem into total
    # unavailability, so readiness remains true while reporting degradation.
    ready = checks["database"] == "ok" and checks["migrations"] == "ok"
    degraded = ready and any(value != "ok" for value in checks.values())
    return _response(
        {
            "status": "degraded" if degraded else ("ready" if ready else "not_ready"),
            "release": settings.RELEASE_ID,
            "checks": checks,
        },
        status=200 if ready else 503,
    )
