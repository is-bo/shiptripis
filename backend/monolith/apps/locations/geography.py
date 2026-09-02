"""Small, deterministic helpers shared by catalogue import and search."""

from __future__ import annotations

import re
import unicodedata


_PUNCTUATION = re.compile(
    r"[\u0027\u0060\u00b4\u2018\u2019\u201b\u201c\u201d\u2013\u2014\u2212_-]+"
)
_WHITESPACE = re.compile(r"\s+")


def normalize_search_name(value: str) -> str:
    """Return an accent/case/punctuation-insensitive search representation.

    Unicode letters (including Arabic, Spanish and German characters) are
    retained. Latin combining marks are removed, apostrophes and hyphens are
    treated as word separators, and whitespace is collapsed. This is intended
    for indexed prefix queries, not as an identity key.
    """

    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    text = _PUNCTUATION.sub(" ", text)
    text = "".join(
        " " if unicodedata.category(char).startswith("P") else char for char in text
    )
    return _WHITESPACE.sub(" ", text).strip()
