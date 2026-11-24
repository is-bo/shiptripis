"""The city a public route line names (fix plan P2, owner decision Q1).

`Place.display_label` is the catalogue's full naming, `"<name> · <parent>"`,
and the parent is an administrative area, not a city: `Alger Centre · Alger`,
`Paris · Paris`, `Berlin, Stadt · Berlin, Stadt`. That stays right where
precision is the point (the staff console, the place picker, the owner's own
screens and the funded deal's route). A route line read by anyone else names
cities only, and this module is the one home of that rule:

- **Algeria:** the wilaya, which is the commune's parent (`Alger Centre`,
  `Bab Ezzouar` and `Hydra` all read `Alger`). It is how Algerians name a
  place, and the most discreet level.
- **Germany:** Destatis appends a status or epithet after the first comma
  (`Berlin, Stadt`, `München, Landeshauptstadt`,
  `Erkrath, Fundort des Neanderthalers, Stadt`); everything after it goes.
- **Spain:** INE postposes the article (`Coruña, A`,
  `Palmas de Gran Canaria, Las`, `Alfàs del Pi, l'`); it moves to the front,
  part by part around the slash of an official bilingual name, which is kept
  (`Alicante/Alacant`). A comma that is not followed by an article is part of
  the name (`Saus, Camallera i Llampaies`) and stays.
- **France and anywhere else:** the commune's own name.
- **An airport** reads as the city it serves. An airport with no active
  primary served mapping names nothing: it fails closed, exactly as
  `Place.resolve_matching_locality` does.

A display rule, not a secret: the commune's catalogue id still travels beside
the name, because filters, pre-fill and matching identity need it. The caller
passes places whose parent (and, for an airport, served mapping with the
locality's parent) is already loaded, so this reads no row.
"""

from __future__ import annotations

from .models import Place

#: Every article INE postposes, in the case INE writes it. A suffix outside
#: this set is part of the name, so an unknown form keeps the official name.
_SPANISH_ARTICLES = frozenset(
    {
        "El",
        "La",
        "Los",
        "Las",
        "el",
        "la",
        "les",
        "els",
        "Les",
        "Els",
        "L'",
        "l'",
        "A",
        "O",
        "As",
        "Os",
        "Es",
        "Sa",
        "Ses",
    }
)


def city_name(place: Place | None) -> str:
    """The public city name of ``place``, or ``""`` when it names no city."""

    if place is None:
        return ""
    if place.place_type == Place.PlaceType.AIRPORT:
        place = place.resolve_matching_locality()
        if place is None:
            return ""
    country = place.country_id
    if country == "DZ":
        return place.parent.name if place.parent_id else place.name
    if country == "DE":
        return place.name.split(",", 1)[0].strip()
    if country == "ES":
        return "/".join(_spanish_part(part) for part in place.name.split("/"))
    return place.name


def _spanish_part(part: str) -> str:
    stem, separator, article = part.rpartition(", ")
    if not separator or article not in _SPANISH_ARTICLES:
        return part
    joiner = "" if article.endswith("'") else " "
    return f"{article}{joiner}{stem}"
