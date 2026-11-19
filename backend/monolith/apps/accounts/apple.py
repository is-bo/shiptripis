"""Sign in with Apple: identity-token verification (plan EGS, decisions 11 and 14).

The iOS app signs in with Apple and sends the identity token it receives to
`/api/auth/oauth/apple`. The token is a JWT signed RS256 with one of the keys
Apple publishes at `APPLE_KEYS_URL`. Before asking Apple, the app made a random
nonce and gave Apple its SHA-256; it sends the raw nonce here. The nonce binds
the token to this app's sign-in request, so a token Apple issued for another
sign-in is refused; the token's short expiry bounds how long it can be
replayed. The nonce is deliberately not single-use: Apple gives the person's
name only on the first authorization, so a retry with the same token after a
failed first attempt must still work.

`verify_identity_token` accepts a token only when all of these hold: the
header names RS256 and the id of a key Apple publishes; the signature verifies
with that key; `iss` is exactly Apple; `aud` is a single value listed in
`APPLE_SIGN_IN_CLIENT_IDS` (the iOS bundle id); `exp` and `iat` are present
and current within 30 seconds (CLAUDE.md G2); `sub` is present; `nonce` is the
SHA-256 of the raw nonce; an `email`, when the token carries one, is one Apple
says is verified. A token without an email is accepted with `email` None and
`email_verified` False: it can sign in to an identity already linked, never
link or open an account (`apps.accounts.social`). The person's name is never
in the token.

Raises `AppleAuthError` when the token is refused (401) and
`AppleAuthUnavailable` when Sign in with Apple cannot be checked right now:
not configured on this server, or Apple's keys could not be fetched (503).
No message carries a token, a claim value or a nonce.
"""

from __future__ import annotations

import hashlib
import hmac

import jwt
from django.conf import settings
from jwt import PyJWKClient
from jwt.exceptions import (
    ExpiredSignatureError,
    InvalidAudienceError,
    InvalidIssuerError,
    PyJWKClientConnectionError,
    PyJWKClientError,
    PyJWKSetError,
    PyJWTError,
)

APPLE_ISSUER = "https://appleid.apple.com"
APPLE_KEYS_URL = "https://appleid.apple.com/auth/keys"
ALGORITHM = "RS256"

#: Seconds allowed for fetching Apple's keys on a request thread: the read
#: budget of `google.py`'s certificate fetch. urllib applies the one value to
#: the connection and to each read, so a stall cannot hold a request slot for
#: the library's 30-second default.
KEYS_TIMEOUT_SECONDS = 5.0

#: How long a fetched key set is reused. A token signed with a key Apple added
#: since is not refused for that: `PyJWKClient` refetches on an unknown key id,
#: at most once per cooldown.
KEYS_CACHE_SECONDS = 3600

#: Clock leeway for `exp` and `iat`, as for our own tokens (CLAUDE.md G2).
LEEWAY_SECONDS = 30

_REQUIRED_CLAIMS = ["iss", "aud", "exp", "iat", "sub"]

_INVALID = "The Apple identity token is not valid."
_UNREACHABLE = "Sign in with Apple is temporarily unavailable."


class AppleAuthError(Exception):
    """The identity token is refused."""


class AppleAuthUnavailable(Exception):
    """Sign in with Apple is not configured here, or Apple could not be reached."""


def _new_keys_client() -> PyJWKClient:
    return PyJWKClient(
        APPLE_KEYS_URL,
        cache_jwk_set=True,
        lifespan=KEYS_CACHE_SECONDS,
        timeout=KEYS_TIMEOUT_SECONDS,
    )


#: One client per process, so every request thread shares its cached key set.
#: The warm-up fetch runs outside the client's lock, so on a cold cache each
#: concurrent request thread may fetch Apple's keys once: bounded by the
#: thread count, and harmless.
_keys = _new_keys_client()


def nonce_digest(raw_nonce: str) -> str:
    """What the app gives Apple for ``raw_nonce``: its SHA-256, lowercase hex."""

    return hashlib.sha256(raw_nonce.encode("utf-8")).hexdigest()


def verify_identity_token(token: str, *, raw_nonce: str) -> dict:
    """The verified claims of an Apple identity token.

    With an email, ``email_verified`` comes back as the boolean ``True``
    (Apple sends ``true`` or the string ``"true"``); anything else is refused.
    Without one, ``email`` is None and ``email_verified`` False.
    """

    audiences = list(settings.APPLE_SIGN_IN_CLIENT_IDS)
    if not audiences:
        raise AppleAuthUnavailable("Sign in with Apple is not available right now.")

    # The header is read before any key is fetched, so a token that is not
    # RS256 is refused without a network call; the signature check below
    # accepts RS256 only as well.
    try:
        header = jwt.get_unverified_header(token)
    except PyJWTError as exc:
        raise AppleAuthError(_INVALID) from exc
    key_id = header.get("kid")
    if header.get("alg") != ALGORITHM or not isinstance(key_id, str) or not key_id:
        raise AppleAuthError(_INVALID)

    # Reading the key set (cached, or fetched now) can fail only on Apple's
    # side: unreachable, or an answer that is not a key set. The token was
    # never judged, so that is unavailable, never a refusal.
    try:
        _keys.get_signing_keys()
    except (PyJWKClientError, PyJWKSetError, OSError, ValueError) as exc:
        raise AppleAuthUnavailable(_UNREACHABLE) from exc
    try:
        signing_key = _keys.get_signing_key(key_id)
    except (PyJWKClientConnectionError, PyJWKSetError, OSError, ValueError) as exc:
        # The refetch for a key id Apple may have added since failed.
        raise AppleAuthUnavailable(_UNREACHABLE) from exc
    except PyJWKClientError as exc:
        # Apple publishes no key with this id.
        raise AppleAuthError(_INVALID) from exc

    try:
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=[ALGORITHM],
            audience=audiences,
            issuer=APPLE_ISSUER,
            leeway=LEEWAY_SECONDS,
            options={"require": _REQUIRED_CLAIMS, "enforce_minimum_key_length": True},
        )
    except ExpiredSignatureError as exc:
        raise AppleAuthError("The Apple identity token has expired.") from exc
    except InvalidAudienceError as exc:
        raise AppleAuthError("The Apple identity token is not for this app.") from exc
    except InvalidIssuerError as exc:
        raise AppleAuthError("The Apple identity token was not issued by Apple.") from exc
    except PyJWTError as exc:
        raise AppleAuthError(_INVALID) from exc

    # Apple names one audience; a list would pass PyJWT's membership test.
    if not isinstance(claims["aud"], str):
        raise AppleAuthError("The Apple identity token is not for this app.")
    if not isinstance(claims["sub"], str) or not claims["sub"]:
        raise AppleAuthError(_INVALID)
    # Constant time. A digest is ASCII hex, so a claim that is not ASCII
    # cannot match (and `compare_digest` accepts ASCII strings only).
    nonce = claims.get("nonce")
    if not (
        isinstance(nonce, str)
        and nonce.isascii()
        and hmac.compare_digest(nonce, nonce_digest(raw_nonce))
    ):
        raise AppleAuthError("The Apple identity token does not belong to this sign-in.")
    if claims.get("email") is None:
        return {**claims, "email": None, "email_verified": False}
    verified = claims.get("email_verified")
    if verified is not True and verified != "true":
        raise AppleAuthError("Apple account email is not verified.")
    return {**claims, "email_verified": True}
