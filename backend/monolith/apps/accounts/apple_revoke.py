"""Revoking Sign in with Apple when an account is deleted (App Store 5.1.1(v)).

Apple asks an app that offers Sign in with Apple to revoke the person's Apple
authorization when they delete their account. Revoking needs a token Apple
issued to this app, and the server keeps none: the app asks Apple for a fresh
authorization code at the moment of deletion and sends it here. The server
exchanges that code for a refresh token at `/auth/token` and revokes it at
`/auth/revoke`, both authenticated by a client secret: a short-lived ES256
JWT signed with the Sign in with Apple key (`APPLE_SIGN_IN_PRIVATE_KEY`, the
`.p8` file Apple lets the developer download once) and naming its key id and
the developer team.

`revoke_with_authorization_code` raises `AppleRevokeUnavailable` when the key
is not configured here or Apple cannot be reached (503), and
`AppleRevokeRefused` when Apple refuses the code (it expired, was used, or was
issued to another app). No message carries a code, a token or the key.
"""

from __future__ import annotations

import time

import jwt
import requests
from django.conf import settings

APPLE_AUDIENCE = "https://appleid.apple.com"
TOKEN_URL = "https://appleid.apple.com/auth/token"
REVOKE_URL = "https://appleid.apple.com/auth/revoke"

#: Seconds for each call to Apple, the same budget as fetching Apple's keys.
TIMEOUT_SECONDS = 5.0

#: The client secret is made per deletion and needs to live only for the two
#: calls; Apple accepts up to six months.
CLIENT_SECRET_TTL_SECONDS = 300


class AppleRevokeUnavailable(Exception):
    """Revoking cannot be done right now: not configured, or Apple unreachable."""


class AppleRevokeRefused(Exception):
    """Apple refused the authorization code."""


def is_configured() -> bool:
    """Whether this server holds everything revoking needs."""

    return bool(
        settings.APPLE_SIGN_IN_CLIENT_IDS
        and settings.APPLE_TEAM_ID
        and settings.APPLE_SIGN_IN_KEY_ID
        and settings.APPLE_SIGN_IN_PRIVATE_KEY
    )


def _client_id() -> str:
    """The app's bundle id: the first of `APPLE_SIGN_IN_CLIENT_IDS`."""

    return settings.APPLE_SIGN_IN_CLIENT_IDS[0]


def client_secret(*, now: int | None = None) -> str:
    """The ES256 client secret Apple's token and revoke endpoints ask for."""

    issued = int(time.time() if now is None else now)
    return jwt.encode(
        {
            "iss": settings.APPLE_TEAM_ID,
            "iat": issued,
            "exp": issued + CLIENT_SECRET_TTL_SECONDS,
            "aud": APPLE_AUDIENCE,
            "sub": _client_id(),
        },
        settings.APPLE_SIGN_IN_PRIVATE_KEY,
        algorithm="ES256",
        headers={"kid": settings.APPLE_SIGN_IN_KEY_ID},
    )


def _post(url: str, data: dict) -> requests.Response:
    try:
        return requests.post(url, data=data, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise AppleRevokeUnavailable("Apple could not be reached.") from exc


def revoke_with_authorization_code(code: str) -> None:
    """Exchange ``code`` for a refresh token and revoke it."""

    if not is_configured():
        raise AppleRevokeUnavailable("Revoking Sign in with Apple is not configured.")
    try:
        secret = client_secret()
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise AppleRevokeUnavailable("The Sign in with Apple key is not usable.") from exc
    base = {"client_id": _client_id(), "client_secret": secret}

    exchanged = _post(
        TOKEN_URL, {**base, "code": code, "grant_type": "authorization_code"}
    )
    if exchanged.status_code == 400:
        raise AppleRevokeRefused("Apple refused the authorization code.")
    if exchanged.status_code != 200:
        raise AppleRevokeUnavailable("Apple did not answer the token exchange.")
    try:
        body = exchanged.json()
    except ValueError as exc:
        raise AppleRevokeUnavailable("Apple's answer could not be read.") from exc
    token, hint = body.get("refresh_token"), "refresh_token"
    if not token:
        token, hint = body.get("access_token"), "access_token"
    if not isinstance(token, str) or not token:
        raise AppleRevokeUnavailable("Apple's answer carried no token.")

    revoked = _post(REVOKE_URL, {**base, "token": token, "token_type_hint": hint})
    if revoked.status_code != 200:
        raise AppleRevokeUnavailable("Apple did not confirm the revocation.")
