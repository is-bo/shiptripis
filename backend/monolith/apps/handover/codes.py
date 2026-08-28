"""Handover-code cryptography: generation, verification hashing, and sealing.

Three separate operations, three separate keys, and one deliberate design
decision that is worth stating plainly because it is the only place Phase 4
keeps a recoverable copy of a secret.

**Generation.** Codes are drawn from `secrets.choice` over a 32-character
Crockford base32 alphabet with the ambiguous letters (I, L, O, U) removed. At
the seeded length of eight characters that is ``32**8 == 2**40`` possibilities.
A code is spoken aloud between two strangers standing next to each other, so
readability is a security property here: a code people mistype is a code people
work around.

**Verification.** Only ``code_hash`` is consulted when a traveler submits a
code. It is ``HMAC-SHA256(pepper, deal_id : kind : code)``, compared with
`hmac.compare_digest`. The pepper lives in the environment, not the database,
so a stolen database dump does not let an attacker test candidate codes offline.
A slow KDF would add nothing on top of 40 bits of entropy plus a five-attempt
cap, and it would put an Argon2 hash inside a row-locked transaction.

**Sealing.** The sender must be able to *re-open* their pickup code, and to
open the delivery code every time they look at it after the 30-minute buffer.
A hash cannot answer that, and rotating on every view would invalidate a code
the traveler was already given -- or, worse, a delivery code the recipient
already has by email. So the plaintext is also stored sealed: encrypt-then-MAC
with a key that is separate from the verification pepper and separate from
``SECRET_KEY``.

    plaintext is never stored; ciphertext is.

The seal is bound to ``(deal_id, kind)`` as authenticated associated data, so a
sealed blob copied from one Deal into another fails to open rather than
revealing anything. Unsealing has exactly two callers -- the sender's pickup
reveal and the sender/recipient delivery reveal -- and both are authorization
and state gated, and both write an access audit row. The traveler has no
unsealing path at all.

Everything is built from `hmac`, `hashlib` and `secrets`. Nothing here adds a
dependency, and no plaintext code is ever logged, published, or written to a
timeline event.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from django.conf import settings

#: Crockford base32 without I, L, O and U. 32 symbols, so each character is
#: exactly five bits and the arithmetic below stays honest.
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

#: What a human may type instead of the canonical symbol.
_CONFUSABLES = {"I": "1", "L": "1", "O": "0"}

_SEAL_VERSION = b"\x01"
_NONCE_BYTES = 16
_TAG_BYTES = 32


class SealError(RuntimeError):
    """A sealed code failed authentication or is malformed."""

    code = "handover_seal_invalid"


def _base_secret() -> bytes:
    """The root secret every handover key is derived from.

    ``HANDOVER_CODE_SECRET`` is its own environment variable so that rotating
    or compromising the Django ``SECRET_KEY`` (sessions, signing) is not the
    same event as compromising parcel handover. Production refuses to boot
    without it; development and tests derive a deterministic value from
    ``SECRET_KEY`` so a fresh checkout runs with no extra configuration.
    """

    configured = getattr(settings, "HANDOVER_CODE_SECRET", "")
    if configured:
        return configured.encode("utf-8")
    return hashlib.sha256(
        b"shiptrip.handover.fallback.v1|" + settings.SECRET_KEY.encode("utf-8")
    ).digest()


def _derive(label: bytes) -> bytes:
    return hmac.new(_base_secret(), label, hashlib.sha256).digest()


def _pepper_key() -> bytes:
    return _derive(b"shiptrip.handover.pepper.v1")


def _seal_key() -> bytes:
    return _derive(b"shiptrip.handover.seal.v1")


def _seal_mac_key() -> bytes:
    return hmac.new(_seal_key(), b"mac", hashlib.sha256).digest()


# --- generation and normalisation --------------------------------------------


def generate_code(length: int) -> str:
    """A fresh code. ``secrets`` only -- never ``random``."""

    if not 6 <= length <= 16:
        raise ValueError("Handover code length must be between 6 and 16 characters.")
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def normalize_code(raw: str) -> str:
    """Fold what a human typed onto the canonical alphabet.

    Case, spaces and dashes are removed, and the three ambiguous shapes are
    mapped to the symbol they are usually mistaken for. A character that is
    still outside the alphabet is left in place so the comparison simply fails;
    it is never silently dropped, because dropping characters would shorten the
    effective search space.
    """

    folded = []
    for character in (raw or "").upper():
        if character in {" ", "-", "_", "\t"}:
            continue
        folded.append(_CONFUSABLES.get(character, character))
    return "".join(folded)


def format_code(code: str) -> str:
    """Group a code for display: ``ABCD-EFGH``. Never used for comparison."""

    if len(code) <= 4:
        return code
    midpoint = (len(code) + 1) // 2
    return f"{code[:midpoint]}-{code[midpoint:]}"


# --- verification hashing -----------------------------------------------------


def hash_code(*, deal_id: int, kind: str, code: str) -> str:
    """The value stored in ``DealHandoverCode.code_hash``.

    Binding the Deal id and the kind into the message means a hash lifted from
    one row cannot be replayed against another, and a pickup hash can never
    satisfy a delivery submission.
    """

    message = f"{deal_id}:{kind}:{normalize_code(code)}".encode("utf-8")
    return hmac.new(_pepper_key(), message, hashlib.sha256).hexdigest()


def code_matches(*, deal_id: int, kind: str, code: str, code_hash: str) -> bool:
    """Constant-time comparison. Returns a bare boolean and nothing more.

    Callers must not report *how* a submission failed. A response that
    distinguishes "wrong length" from "wrong characters" from "close" is a
    search oracle, so the API answers with one uniform rejection.
    """

    candidate = hash_code(deal_id=deal_id, kind=kind, code=code)
    return hmac.compare_digest(candidate, code_hash or "")


# --- sealing ------------------------------------------------------------------


def _keystream(nonce: bytes, length: int) -> bytes:
    key = _seal_key()
    stream = bytearray()
    counter = 0
    while len(stream) < length:
        stream.extend(
            hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        )
        counter += 1
    return bytes(stream[:length])


def _aad(deal_id: int, kind: str) -> bytes:
    return f"{deal_id}:{kind}".encode("utf-8")


def seal_code(*, deal_id: int, kind: str, code: str) -> str:
    """Encrypt-then-MAC a code so its owner can be shown it again.

    Layout, before base64: version byte, 16-byte random nonce, ciphertext, and
    a 32-byte tag over all of it plus the ``(deal_id, kind)`` associated data.
    """

    plaintext = code.encode("utf-8")
    nonce = secrets.token_bytes(_NONCE_BYTES)
    ciphertext = bytes(
        a ^ b for a, b in zip(plaintext, _keystream(nonce, len(plaintext)))
    )
    header = _SEAL_VERSION + nonce + ciphertext
    tag = hmac.new(
        _seal_mac_key(), header + _aad(deal_id, kind), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(header + tag).decode("ascii")


def unseal_code(*, deal_id: int, kind: str, sealed: str) -> str:
    """Open a sealed code. Raises `SealError` rather than returning garbage."""

    try:
        blob = base64.urlsafe_b64decode((sealed or "").encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise SealError("The sealed handover code is malformed.") from exc
    if len(blob) < 1 + _NONCE_BYTES + _TAG_BYTES + 1:
        raise SealError("The sealed handover code is malformed.")
    header, tag = blob[:-_TAG_BYTES], blob[-_TAG_BYTES:]
    if header[:1] != _SEAL_VERSION:
        raise SealError("Unsupported sealed handover code version.")
    expected = hmac.new(
        _seal_mac_key(), header + _aad(deal_id, kind), hashlib.sha256
    ).digest()
    if not hmac.compare_digest(expected, tag):
        # Either the key changed, the row was tampered with, or the blob came
        # from a different Deal. None of those may produce a plaintext.
        raise SealError("The sealed handover code failed authentication.")
    nonce = header[1 : 1 + _NONCE_BYTES]
    ciphertext = header[1 + _NONCE_BYTES :]
    plaintext = bytes(
        a ^ b for a, b in zip(ciphertext, _keystream(nonce, len(ciphertext)))
    )
    return plaintext.decode("utf-8")
