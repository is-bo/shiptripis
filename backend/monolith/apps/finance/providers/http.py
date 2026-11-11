"""Bounded, thread-local HTTP transport for payment providers.

`requests.Session` reuses TCP/TLS connections but is not documented as
thread-safe. Gunicorn uses threads in the combined application container, so each
long-lived worker thread owns one session per provider. Sessions never carry
authentication or request bodies as mutable defaults; every call supplies its
own headers and data.
"""

from __future__ import annotations

import atexit
import logging
import threading
import time
from http.cookiejar import DefaultCookiePolicy

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter

POOL_CONNECTIONS = 2
POOL_MAXSIZE = 4

_local = threading.local()
_registry_lock = threading.Lock()
_sessions: list[requests.Session] = []
_timing_logger = logging.getLogger("shiptrip.provider")


class _RejectProviderCookies(DefaultCookiePolicy):
    """Provider APIs authenticate with headers; never persist response cookies."""

    def set_ok(self, cookie, request):  # noqa: ANN001
        del cookie, request
        return False

    def return_ok(self, cookie, request):  # noqa: ANN001
        del cookie, request
        return False


def _new_session() -> requests.Session:
    session = requests.Session()
    session.cookies.set_policy(_RejectProviderCookies())
    # `max_retries=0` is load-bearing for money mutations. Provider retries are
    # classified by the domain layer and reuse the recorded idempotency key;
    # urllib3 must never replay a mutation behind that layer's back.
    adapter = HTTPAdapter(
        pool_connections=POOL_CONNECTIONS,
        pool_maxsize=POOL_MAXSIZE,
        max_retries=0,
        pool_block=True,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    with _registry_lock:
        _sessions.append(session)
    return session


def provider_session(provider: str) -> requests.Session:
    """Return one reusable session per provider and worker thread."""

    sessions = getattr(_local, "sessions", None)
    if sessions is None:
        sessions = {}
        _local.sessions = sessions
    session = sessions.get(provider)
    if session is None:
        session = _new_session()
        sessions[provider] = session
    return session


def provider_timeout(override: float | None = None) -> float | tuple[float, float]:
    """Return explicit connect/read timeouts, preserving test overrides."""

    if override is not None:
        return override
    return (
        float(getattr(settings, "PAYMENTS_PROVIDER_CONNECT_TIMEOUT_SECONDS", 3.05)),
        float(getattr(settings, "PAYMENTS_PROVIDER_READ_TIMEOUT_SECONDS", 15.0)),
    )


def log_provider_timing(
    *, provider: str, operation: str, started: float, outcome: str
) -> None:
    """Emit allow-listed latency fields only; never URL, payload, IDs or auth."""

    _timing_logger.info(
        "payment provider call",
        extra={
            "event": "provider_http_call",
            "provider": provider,
            "operation": operation,
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
            "outcome": outcome,
        },
    )


def close_provider_sessions() -> None:
    """Close every process-local pool during orderly worker shutdown."""

    with _registry_lock:
        sessions = list(_sessions)
        _sessions.clear()
    for session in sessions:
        session.close()


atexit.register(close_provider_sessions)
