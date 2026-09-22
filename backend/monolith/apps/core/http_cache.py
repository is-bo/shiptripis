"""Conditional public responses for small, stable reference catalogues."""

from __future__ import annotations

import json
from hashlib import sha256

from rest_framework.response import Response


def public_catalog_response(request, data, *, max_age: int = 3_600) -> Response:
    encoded = json.dumps(
        data, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    etag = f'"{sha256(encoded).hexdigest()}"'
    headers = {
        "Cache-Control": f"public, max-age={max_age}",
        "ETag": etag,
    }
    if request.headers.get("If-None-Match") == etag:
        return Response(status=304, headers=headers)
    return Response(data, headers=headers)
