"""Versioned financial-data AEAD and independently keyed account identity.

No SECRET_KEY fallback. Keep retired keys for retained records. Callers supply
the immutable public UUID before insertion, never a database sequence ID.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import unicodedata

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.views.decorators.debug import sensitive_variables


@sensitive_variables()
def key_configuration():
    try:
        raw = settings.PAYOUT_DATA_KEYRING
        raw = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(raw, dict) or not raw:
            raise ValueError
        keys = {}
        for name, encoded in raw.items():
            if not isinstance(name, str) or not re.fullmatch(
                r"[A-Za-z0-9_-]{1,64}", name
            ):
                raise ValueError
            key = base64.b64decode(encoded, validate=True)
            if len(key) != 32:
                raise ValueError
            keys[name] = key
        active = settings.PAYOUT_DATA_ACTIVE_KEY_ID
        fingerprint = base64.b64decode(
            settings.PAYOUT_ACCOUNT_FINGERPRINT_KEY, validate=True
        )
        if active not in keys or len(fingerprint) != 32 or fingerprint in keys.values():
            raise ValueError
        return keys, active, fingerprint
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ImproperlyConfigured(
            "Payout encryption requires a valid independent 256-bit keyring and fingerprint key."
        ) from None


def _aad(model, record, field):
    return json.dumps(
        ["shiptrip-payout", model, str(record), field, 1], separators=(",", ":")
    ).encode()


@sensitive_variables()
def encrypt(value: str, *, model: str, record, field: str) -> str:
    keys, active, _ = key_configuration()
    nonce = os.urandom(12)
    ciphertext = AESGCM(keys[active]).encrypt(
        nonce, value.encode("utf-8"), _aad(model, record, field)
    )
    return json.dumps(
        {
            "v": 1,
            "kid": active,
            "nonce": base64.b64encode(nonce).decode(),
            "ct": base64.b64encode(ciphertext).decode(),
        },
        separators=(",", ":"),
    )


@sensitive_variables()
def decrypt(envelope: str, *, model: str, record, field: str) -> str:
    keys, _, _ = key_configuration()
    try:
        obj = json.loads(envelope)
        if (
            set(obj) != {"v", "kid", "nonce", "ct"}
            or type(obj["v"]) is not int
            or obj["v"] != 1
        ):
            raise ValueError
        nonce = base64.b64decode(obj["nonce"], validate=True)
        if len(nonce) != 12:
            raise ValueError
        return (
            AESGCM(keys[obj["kid"]])
            .decrypt(
                nonce,
                base64.b64decode(obj["ct"], validate=True),
                _aad(model, record, field),
            )
            .decode("utf-8")
        )
    except (ValueError, KeyError, TypeError, InvalidTag, UnicodeError):
        raise ValidationError(
            "Sensitive payout data could not be authenticated."
        ) from None


@sensitive_variables()
def normalize_digits(value: str, *, minimum: int, maximum: int) -> str:
    try:
        if not isinstance(value, str) or len(value) > 100:
            raise ValueError
        normalized = "".join(
            str(unicodedata.decimal(c)) for c in value if not c.isspace()
        )
        if not minimum <= len(normalized) <= maximum:
            raise ValueError
        return normalized
    except (ValueError, TypeError):
        raise ValidationError("Invalid postal account format.") from None


@sensitive_variables()
def account_fingerprint(ccp_number: str, ccp_key: str, nip: str) -> str:
    _, _, key = key_configuration()
    parts = [
        "dz-ccp-v1",
        normalize_digits(ccp_number, minimum=1, maximum=20),
        normalize_digits(ccp_key, minimum=2, maximum=2),
        normalize_digits(nip, minimum=20, maximum=20),
    ]
    return hmac.new(
        key, json.dumps(parts, separators=(",", ":")).encode(), hashlib.sha256
    ).hexdigest()
