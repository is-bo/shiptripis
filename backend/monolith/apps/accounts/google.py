"""Google ID-token verification.

The mobile client signs in with Google and sends the resulting ID token to
`/api/auth/oauth/google`. We verify the JWT signature against Google's
public keys and check the `aud` claim is one of our configured client IDs.

Returns the verified payload (with `sub`, `email`, `name`, ...) on success;
raises `GoogleAuthError` on any verification failure.
"""
from __future__ import annotations

from django.conf import settings
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token


class GoogleAuthError(Exception):
    pass


def verify_id_token(token: str) -> dict:
    if not settings.GOOGLE_OAUTH_CLIENT_IDS:
        raise GoogleAuthError("Google OAuth not configured on server")

    try:
        payload = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            audience=None,
        )
    except ValueError as exc:
        raise GoogleAuthError(f"invalid token: {exc}") from exc

    aud = payload.get("aud")
    if aud not in settings.GOOGLE_OAUTH_CLIENT_IDS:
        raise GoogleAuthError("token audience not accepted")

    iss = payload.get("iss")
    if iss not in {"https://accounts.google.com", "accounts.google.com"}:
        raise GoogleAuthError("token issuer not accepted")

    return payload
