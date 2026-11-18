"""Dates for text the server writes itself, such as an email fact row.

Wassla's Arabic is Algerian Arabic: Western digits (0-9) and the Maghrebi
month names (جانفي, فيفري ... أوت ...), never the Mashriq ones (يناير, أغسطس)
or Arabic-Indic digits (٠-٩). The mobile app follows the same rule through
`ar_DZ` in `mobile/lib/core/format/locale_formats.dart`.

The month names live here rather than in the `.po` files on purpose: a month
is data, and translating `"August"` once for every context would let a stray
`msgstr` reintroduce أغسطس.
"""

from __future__ import annotations

from datetime import datetime, timezone

from django.utils.dateparse import parse_datetime

from .languages import normalize_communication_language

MONTHS: dict[str, tuple[str, ...]] = {
    "en": (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ),
    "fr": (
        "janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre",
    ),
    "ar": (
        "جانفي", "فيفري", "مارس", "أفريل", "ماي", "جوان",
        "جويلية", "أوت", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر",
    ),
}

_DATE_TIME_SEPARATOR = {"en": ", ", "fr": " à ", "ar": "، "}


def format_utc_datetime(value: datetime | str | None, language: object) -> str:
    """`1 September 2026, 10:00 UTC`, `1 septembre 2026 à 10:00 UTC`,
    `1 سبتمبر 2026، 10:00 UTC`.

    Accepts an aware datetime or the ISO string an event payload carries.
    Returns an empty string for a missing or unreadable value, so the caller's
    fact row is simply left out instead of printing a raw timestamp.
    """

    moment = parse_datetime(value) if isinstance(value, str) else value
    if not isinstance(moment, datetime) or moment.tzinfo is None:
        return ""
    language = normalize_communication_language(language)
    utc = moment.astimezone(timezone.utc)
    month = MONTHS[language][utc.month - 1]
    return (
        f"{utc.day} {month} {utc.year}"
        f"{_DATE_TIME_SEPARATOR[language]}{utc:%H:%M} UTC"
    )
