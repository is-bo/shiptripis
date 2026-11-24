"""The city a card names (fix plan P2, owner decisions of 2026-11-24).

The owner's rule: **cards show cities; detail pages show the catalogue place;
the exact location only after funding.** `Place.display_label` is the
catalogue's full naming, `"<name> · <parent>"` (`Houari Boumediene Airport ·
Alger`, `Lyon · Rhône`), and it stays on every detail page, the place picker,
the owner's own screens, the staff console and the funded deal's route. A
list card or list row names cities only, and this module is the one home of
that rule:

- **Algeria:** the wilaya (`Alger Centre`, `Bab Ezzouar` and `Hydra` all read
  `Alger`). Only a parent the catalogue records as a wilaya counts; a commune
  without one names nothing rather than a daïra or its own name.
- **Germany:** the name before the first comma. Destatis appends a status or
  epithet after it (`Berlin, Stadt`, `München, Landeshauptstadt`,
  `Erkrath, Fundort des Neanderthalers, Stadt`), always as `", "` except in one
  row written without the space (`Ebstorf,Klosterflecken`), so the split is on
  the comma itself.
- **Spain:** INE postposes the article (`Coruña, A`,
  `Palmas de Gran Canaria, Las`, `Alfàs del Pi, l'`); it moves to the front,
  part by part around the slash of an official bilingual name, which is kept
  (`Alacant/Alicante`). A comma that is not followed by an article is part of
  the name (`Saus, Camallera i Llampaies`) and stays.
- **France and anywhere else:** the commune's own name.
- **An airport** reads as the city it serves. An airport with no active
  primary served mapping names nothing: it fails closed, exactly as
  `Place.resolve_matching_locality` does.

A display rule, not a secret: the catalogue ids still travel beside the name,
because filters, pre-fill and matching identity need them. The caller passes
places whose parent (and, for an airport, served mapping with the locality's
parent) is already loaded, so this reads no row.
"""

from __future__ import annotations

from .models import Place

#: The tier the Algerian catalogue gives a wilaya (`algeria-wilaya` rows).
WILAYA = "wilaya"

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
    """The city a card names for ``place``, or ``""`` when it names none."""

    if place is None:
        return ""
    if place.place_type == Place.PlaceType.AIRPORT:
        place = place.resolve_matching_locality()
        if place is None:
            return ""
    country = place.country_id
    if country == "DZ":
        parent = place.parent if place.parent_id else None
        return parent.name if parent is not None and parent.admin_level == WILAYA else ""
    if country == "DE":
        return place.name.split(",", 1)[0].strip()
    if country == "ES":
        return "/".join(_spanish_part(part) for part in place.name.split("/"))
    return place.name


def card_place(place: Place | None) -> dict | None:
    """A catalogue place as a list card or list row carries it.

    The one card-level projection: the ids and kind a client needs to act on
    the place, and every name-like field set to the city. The served locality
    is resolved once and reused for both the id and the name.
    """

    if place is None:
        return None
    locality = place.resolve_matching_locality()
    city = city_name(place)
    return {
        "id": place.pk,
        "name": city,
        "display_label": city,
        "place_type": place.place_type,
        "country_code": place.country_id,
        "iata_code": place.iata_code or None,
        "matching_locality_id": locality.pk if locality is not None else None,
    }


def _spanish_part(part: str) -> str:
    stem, separator, article = part.rpartition(", ")
    if not separator or article not in _SPANISH_ARTICLES:
        return part
    joiner = "" if article.endswith("'") else " "
    return f"{article}{joiner}{stem}"
