"""Encrypt short-lived transactional-email secrets without storing plaintext."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid

from django.conf import settings

_VERSION = b"\x01"
_NONCE_BYTES = 16
_TAG_BYTES = 32


class OutboundSecretError(RuntimeError):
    pass


def _root_key() -> bytes:
    configured = getattr(settings, "TRANSACTIONAL_EMAIL_SECRET", "")
    if configured:
        return configured.encode("utf-8")
    return hashlib.sha256(
        b"shiptrip.transactional-email.fallback.v1|"
        + settings.SECRET_KEY.encode("utf-8")
    ).digest()


def _derive(label: bytes) -> bytes:
    return hmac.new(_root_key(), label, hashlib.sha256).digest()


def _keystream(nonce: bytes, length: int) -> bytes:
    key = _derive(b"seal")
    stream = bytearray()
    counter = 0
    while len(stream) < length:
        stream.extend(
            hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        )
        counter += 1
    return bytes(stream[:length])


def _aad(secret_id: uuid.UUID, purpose: str) -> bytes:
    return f"{secret_id}:{purpose}".encode("utf-8")


def seal(*, secret_id: uuid.UUID, purpose: str, plaintext: str) -> str:
    if not plaintext:
        raise ValueError("Outbound email secret cannot be empty.")
    value = plaintext.encode("utf-8")
    nonce = secrets.token_bytes(_NONCE_BYTES)
    ciphertext = bytes(a ^ b for a, b in zip(value, _keystream(nonce, len(value))))
    header = _VERSION + nonce + ciphertext
    tag = hmac.new(
        _derive(b"mac"),
        header + _aad(secret_id, purpose),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(header + tag).decode("ascii")


def unseal(*, secret_id: uuid.UUID, purpose: str, sealed_value: str) -> str:
    try:
        blob = base64.urlsafe_b64decode((sealed_value or "").encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise OutboundSecretError("Outbound email secret is malformed.") from exc
    if len(blob) < 1 + _NONCE_BYTES + _TAG_BYTES + 1 or blob[:1] != _VERSION:
        raise OutboundSecretError("Outbound email secret is malformed.")
    header, tag = blob[:-_TAG_BYTES], blob[-_TAG_BYTES:]
    expected = hmac.new(
        _derive(b"mac"),
        header + _aad(secret_id, purpose),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(tag, expected):
        raise OutboundSecretError("Outbound email secret failed authentication.")
    nonce = header[1 : 1 + _NONCE_BYTES]
    ciphertext = header[1 + _NONCE_BYTES :]
    plaintext = bytes(
        a ^ b for a, b in zip(ciphertext, _keystream(nonce, len(ciphertext)))
    )
    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OutboundSecretError("Outbound email secret is invalid.") from exc
