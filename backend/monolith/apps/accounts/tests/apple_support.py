"""Sign in with Apple in tests: a local RSA key served as Apple's key set.

Nothing here reaches Apple. `serve_keys` gives `apps.accounts.apple` a fresh key
client (an empty cache) and answers its HTTP fetch itself, so the production
client code runs as it does in production: the URL, the timeout, the parsing
and the cache.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import time
from contextlib import contextmanager, nullcontext
from unittest.mock import MagicMock, patch

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from apps.accounts import apple

BUNDLE_ID = "com.shiptrip.shiptrip"
KEY_ID = "apple-test-key-1"
#: The raw nonce the app sends; Apple's token carries its SHA-256 hex.
RAW_NONCE = "Qm9vdHN0cmFwLW5vbmNlLWZvci10ZXN0cw"
SUBJECT = "001234.5f0c8d1e2b3a4c5d6e7f8091a2b3c4d5.1201"
EMAIL = "apple.person@example.com"

#: Apple's signing key in these tests, and a key Apple never published.
SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
FOREIGN_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)

#: Marks a claim to leave out of the token.
DROP = object()


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def public_jwk(private_key=SIGNING_KEY, *, kid: str = KEY_ID) -> dict:
    jwk = RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    return {**jwk, "kid": kid, "alg": "RS256", "use": "sig"}


def key_set(*jwks: dict) -> dict:
    return {"keys": list(jwks) if jwks else [public_jwk()]}


def claims(**overrides) -> dict:
    now = int(time.time())
    values = {
        "iss": "https://appleid.apple.com",
        "aud": BUNDLE_ID,
        "exp": now + 600,
        "iat": now,
        "sub": SUBJECT,
        "email": EMAIL,
        "email_verified": True,
        "is_private_email": False,
        "auth_time": now,
        "nonce_supported": True,
        "nonce": sha256_hex(RAW_NONCE),
    }
    values.update(overrides)
    return {name: value for name, value in values.items() if value is not DROP}


def identity_token(*, key=SIGNING_KEY, kid: str | None = KEY_ID, **overrides) -> str:
    headers = {} if kid is None else {"kid": kid}
    return jwt.encode(claims(**overrides), key, algorithm="RS256", headers=headers)


def _segment(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def forged_token(header: dict, *, sign=None, **overrides) -> str:
    """A token assembled by hand, for algorithms PyJWT refuses to produce.

    ``sign`` turns the signing input into the signature bytes; without it the
    signature is empty, as for `alg: none`.
    """

    signing_input = (
        f"{_segment(json.dumps(header).encode())}."
        f"{_segment(json.dumps(claims(**overrides)).encode())}"
    )
    signature = sign(signing_input.encode("ascii")) if sign else b""
    return f"{signing_input}.{_segment(signature)}"


def hs256_with_public_key(**overrides) -> str:
    """The key-confusion attack: HS256 keyed with Apple's public key."""

    public_pem = SIGNING_KEY.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return forged_token(
        {"alg": "HS256", "kid": KEY_ID, "typ": "JWT"},
        sign=lambda data: hmac.new(public_pem, data, hashlib.sha256).digest(),
        **overrides,
    )


@contextmanager
def serve_keys(keys: dict | bytes | None = None, *, error: Exception | None = None):
    """Answer the key fetch with ``keys`` (or raise ``error``); yields the opener.

    ``opener.open`` records each fetch: its request (with the URL) and timeout.
    """

    opener = MagicMock()
    if error is not None:
        opener.open.side_effect = error
    else:
        body = keys if isinstance(keys, bytes) else json.dumps(keys or key_set()).encode()
        opener.open.side_effect = lambda request, timeout: nullcontext(io.BytesIO(body))
    with (
        patch.object(apple, "_keys", apple._new_keys_client()),
        patch("jwt.jwks_client.urllib.request.build_opener", return_value=opener),
    ):
        yield opener
