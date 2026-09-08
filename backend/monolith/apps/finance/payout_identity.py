"""Deterministic review assistance, never an automated ownership decision."""

import re
import unicodedata


def normalize_name(value: str, *, accent_insensitive=False) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.replace("ـ", "")
    value = "".join(
        c
        for c in value
        if not ("ARABIC" in unicodedata.name(c, "") and unicodedata.category(c) == "Mn")
    )
    value = re.sub(r"\s*[-‐‑–’'ʼ]\s*", " ", value)
    if accent_insensitive:
        # Strip combining accents only following Latin letters.
        latin = False
        out = []
        for c in unicodedata.normalize("NFD", value):
            if unicodedata.category(c) != "Mn":
                latin = "LATIN" in unicodedata.name(c, "")
            if not (latin and unicodedata.category(c) == "Mn"):
                out.append(c)
        value = unicodedata.normalize("NFC", "".join(out))
    return " ".join(value.split())


def compare_names(
    given, family, *, attested_given=None, attested_family=None, aliases=()
):
    if not attested_given or not attested_family:
        return {
            "classification": "insufficient_attestation",
            "human_review_required": True,
        }
    actual = (normalize_name(given), normalize_name(family))
    expected = (normalize_name(attested_given), normalize_name(attested_family))
    if actual == expected:
        classification = "consistent"
    elif tuple(
        normalize_name(x, accent_insensitive=True) for x in (given, family)
    ) == tuple(
        normalize_name(x, accent_insensitive=True)
        for x in (attested_given, attested_family)
    ):
        classification = "consistent"
    elif actual in [
        (normalize_name(a[0]), normalize_name(a[1])) for a in aliases
    ] or sorted(" ".join(actual).split()) == sorted(" ".join(expected).split()):
        classification = "review_alias_spelling"
    elif any("ARABIC" in unicodedata.name(c, "") for c in given + family) != any(
        "ARABIC" in unicodedata.name(c, "") for c in attested_given + attested_family
    ):
        classification = "review_alias_spelling"
    else:
        classification = "mismatch"
    return {"classification": classification, "human_review_required": True}
