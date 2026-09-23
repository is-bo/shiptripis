"""Google ID-token verification.

The mobile client signs in with Google and sends the resulting ID token to
`/api/auth/oauth/google`. We verify the JWT signature against Google's
public keys and check the `aud` claim is one of our configured client IDs.

Returns the verified payload (with `sub`, `email`, `name`, ...) on success;
raises `GoogleAuthError` on any verification failure, and
`GoogleAuthUnavailable` when Google's signing keys cannot be fetched.
"""
from __future__ import annotations

import threading

from django.conf import settings
from google.auth import exceptions as google_exceptions
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

#: (connect, read) budget for fetching Google's signing certificates. The
#: library default is 120 seconds on a request thread; with four Gunicorn
#: request slots, four sign-ins during a Google network stall would otherwise
#: hold every slot for two minutes.
CERTS_TIMEOUT_SECONDS = (3.05, 5.0)


class GoogleAuthError(Exception):
    pass


class GoogleAuthUnavailable(Exception):
    """Google's certificate endpoint could not be reached in time."""


class _BoundedRequest(google_requests.Request):
    """google-auth transport with an explicit timeout on every call."""

    def __call__(self, url, method="GET", body=None, headers=None, timeout=None, **kwargs):
        return super().__call__(
            url,
            method=method,
            body=body,
            headers=headers,
            timeout=CERTS_TIMEOUT_SECONDS,
            **kwargs,
        )


_local = threading.local()


def _transport() -> _BoundedRequest:
    # One transport per request thread, so its session keeps the TLS
    # connection to Google warm between sign-ins. `requests.Session` is not
    # documented as thread-safe, hence not one per process.
    request = getattr(_local, "request", None)
    if request is None:
        request = _BoundedRequest()
        _local.request = request
    return request


def verify_id_token(token: str) -> dict:
    if not settings.GOOGLE_OAUTH_CLIENT_IDS:
        raise GoogleAuthError("Google OAuth not configured on server")

    try:
        payload = id_token.verify_oauth2_token(
            token,
            _transport(),
            audience=None,
        )
    except google_exceptions.TransportError as exc:
        raise GoogleAuthUnavailable("Google sign-in is temporarily unavailable.") from exc
    except ValueError as exc:
        raise GoogleAuthError(f"invalid token: {exc}") from exc

    aud = payload.get("aud")
    if aud not in settings.GOOGLE_OAUTH_CLIENT_IDS:
        raise GoogleAuthError("token audience not accepted")

    iss = payload.get("iss")
    if iss not in {"https://accounts.google.com", "accounts.google.com"}:
        raise GoogleAuthError("token issuer not accepted")
    if payload.get("email_verified") is not True:
        raise GoogleAuthError("Google account email is not verified")

    return payload
