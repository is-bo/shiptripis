"""Small, dependency-free request correlation and access logging middleware."""

from __future__ import annotations

import logging
import time
import uuid

from django.http import HttpRequest, HttpResponse

logger = logging.getLogger("shiptrip.request")


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
        response = self.get_response(request)
        elapsed_ms = round((time.monotonic() - started) * 1000, 2)
        response["X-Request-ID"] = request_id
        if response.status_code >= 400:
            route = getattr(getattr(request, "resolver_match", None), "route", None)
            safe_path = f"/{route}" if route else "<unmatched>"
            logger.warning(
                "request completed with error",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    # Log only the source-defined route template. Concrete
                    # path values can contain guest capability tokens or
                    # other identifiers and must not enter the log stream.
                    "path": safe_path,
                    "status": response.status_code,
                    "duration_ms": elapsed_ms,
                },
            )
        return response
