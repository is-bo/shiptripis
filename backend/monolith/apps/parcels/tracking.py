"""The parcel tracking number (spec 16, plan 2.10).

This module is the only place that creates, formats or parses a tracking
number. A number is ``WSL-`` followed by eight characters of ``ALPHABET``,
for example ``WSL-7K3M9QXD``. It is stored whole, in
``ParcelRequest.tracking_number``, and every surface reads it through
``for_request`` or ``for_deal``.

A number identifies a parcel; it never authorises anything. It is random
rather than a counter so that it does not reveal how many parcels exist.
"""

from __future__ import annotations

import re
import secrets
from typing import TYPE_CHECKING, Callable

from django.db import IntegrityError, transaction

if TYPE_CHECKING:
    from apps.deals.models import Deal
    from apps.parcels.models import ParcelRequest

#: No 0, 1, I, L, O or U, so a number can be read aloud and typed without
#: mistakes. 30 characters, 8 of them: about 6.6 x 10^11 numbers.
ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
PREFIX = "WSL-"
LENGTH = 8
#: The stored form, prefix included.
MAX_LENGTH = len(PREFIX) + LENGTH

#: Creating a request tries this many numbers before it gives up.
MAX_ATTEMPTS = 5

_BODY = re.compile(f"[{ALPHABET}]{{{LENGTH}}}")
#: What a person may type around a number: case, the ``WSL`` prefix and the
#: hyphen are optional (spec 16).
_TYPED = re.compile(r"(?:WSL-?)?(?P<body>[0-9A-Z]{8})")
#: Bidirectional isolation and marks an email client adds around a number in
#: right-to-left text, which come along when it is copied.
_BIDI_MARKS = "‎‏⁦⁧⁨⁩"


class TrackingNumberUnavailable(RuntimeError):
    """Every attempt to give a new request a free number collided."""


def generate() -> str:
    """A new random number. Uniqueness is the database's to enforce."""

    return PREFIX + "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))


def normalize(text: str | None) -> str | None:
    """The stored form of a number someone typed, or ``None`` if it is not one.

    Accepts ``wsl-7k3m9qxd``, ``WSL7K3M9QXD``, ``7K3M9QXD`` and surrounding
    spaces. Refuses a wrong length or a character outside ``ALPHABET``.
    """

    if not isinstance(text, str):
        return None
    candidate = text.strip().strip(_BIDI_MARKS).strip().upper()
    match = _TYPED.fullmatch(candidate)
    if match is None or not _BODY.fullmatch(match["body"]):
        return None
    return PREFIX + match["body"]


def is_valid(value: str | None) -> bool:
    """Whether ``value`` is a number in its stored form."""

    return (
        isinstance(value, str)
        and value.startswith(PREFIX)
        and _BODY.fullmatch(value[len(PREFIX) :]) is not None
    )


def for_request(request: "ParcelRequest") -> str:
    """The number of one request, for any payload, email or page."""

    return request.tracking_number


def for_deal(deal: "Deal") -> str:
    """The number of the parcel a deal carries.

    A request that reopens after a cancelled deal keeps its number, so every
    deal on the same request shows the same one.
    """

    return for_request(deal.delivery_request)


def insert_with_new_number(instance: "ParcelRequest", insert: Callable[[], None]) -> None:
    """Run the first save of a request, drawing a new number on a collision.

    ``insert`` performs the actual save. Each attempt runs in its own savepoint
    so a collision leaves the surrounding transaction usable. Any other
    integrity error is re-raised unchanged.
    """

    model = type(instance)._meta.get_field("tracking_number").model
    for attempt in range(MAX_ATTEMPTS):
        if attempt:
            instance.tracking_number = generate()
        try:
            with transaction.atomic():
                insert()
            return
        except IntegrityError:
            if not model._default_manager.filter(
                tracking_number=instance.tracking_number
            ).exists():
                raise
    raise TrackingNumberUnavailable(
        f"No free tracking number after {MAX_ATTEMPTS} attempts."
    )
