from __future__ import annotations

import gzip
import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from apps.trips.models import Airport

from ...models import (
    AirportLocalityMapping,
    Country,
    GeographyCatalogueImport,
    Place,
    PlaceAlternateName,
)

#: The reviewed catalogue that ships inside the release image. Kept gzipped —
#: 28 MB of JSON is 1 MB packed, and a release that carries its own data is one
#: artefact to deploy and one digest to verify instead of two.
BUNDLED_MANIFEST = (
    Path(__file__).resolve().parents[2] / "data" / "geography_manifest_2026.json.gz"
)


#: The two bytes every gzip stream starts with.
GZIP_MAGIC = bytes((0x1F, 0x8B))


def read_manifest_bytes(path: Path) -> bytes:
    """Return a manifest's raw JSON bytes, transparently un-gzipping.

    The digest downstream is always taken over these *uncompressed* bytes, so
    the identity of a manifest is its reviewed content and not how it happened
    to be packed.
    """

    raw = path.read_bytes()
    if path.suffix == ".gz" or raw[:2] == GZIP_MAGIC:
        return gzip.decompress(raw)
    return raw


def _required(row: dict[str, Any], key: str, version: str) -> str:
    value = row.get(key)
    if value is None or str(value).strip() == "":
        raise CommandError(f"Manifest row is missing {key!r}: {row!r}")
    return str(value).strip()


def _bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    normalized = str(value).strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise CommandError(f"Invalid boolean value: {value!r}")


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("metadata") or {}
    if not isinstance(value, dict):
        raise CommandError("source metadata must be a JSON object")
    return value


def _coordinates(row: dict[str, Any]) -> tuple[Decimal | None, Decimal | None]:
    latitude_value = row.get("latitude")
    longitude_value = row.get("longitude")
    latitude_blank = latitude_value is None or str(latitude_value).strip() == ""
    longitude_blank = longitude_value is None or str(longitude_value).strip() == ""
    if latitude_blank and longitude_blank:
        return None, None
    if latitude_blank != longitude_blank:
        raise CommandError("latitude and longitude must be supplied together")
    try:
        latitude = Decimal(str(latitude_value))
        longitude = Decimal(str(longitude_value))
    except InvalidOperation as exc:
        raise CommandError("latitude and longitude must be decimal numbers") from exc
    if not latitude.is_finite() or not longitude.is_finite():
        raise CommandError("latitude and longitude must be finite decimal numbers")
    if not Decimal("-90") <= latitude <= Decimal("90"):
        raise CommandError(f"latitude is out of range: {latitude}")
    if not Decimal("-180") <= longitude <= Decimal("180"):
        raise CommandError(f"longitude is out of range: {longitude}")
    return latitude, longitude


def _unique_rows(rows: list[dict[str, Any]], label: str) -> None:
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (_required(row, "source", ""), _required(row, "source_id", ""))
        if key in seen:
            raise CommandError(f"Duplicate {label} source identity: {key[0]}:{key[1]}")
        seen.add(key)


class Command(BaseCommand):
    help = "Idempotently import an authoritative geography catalogue manifest."

    def add_arguments(self, parser):
        parser.add_argument(
            "--manifest",
            help=(
                "Path to a normalized JSON manifest (plain or .gz). "
                "Defaults to the reviewed manifest bundled with the release."
            ),
        )
        parser.add_argument(
            "--deactivate-missing",
            action="store_true",
            help="Mark records absent from this manifest inactive for each included source.",
        )
        parser.add_argument(
            "--skip-if-current",
            action="store_true",
            help=(
                "Exit successfully without touching the database when this "
                "exact manifest has already been applied. Intended for a "
                "deployment that applies the bundled catalogue on first boot "
                "and must be a cheap no-op on every boot after it."
            ),
        )

    def handle(self, *args, **options):
        path = Path(options["manifest"]) if options.get("manifest") else BUNDLED_MANIFEST
        try:
            raw = read_manifest_bytes(path)
        except (OSError, gzip.BadGzipFile) as exc:
            raise CommandError(f"Unable to read manifest {path}: {exc}") from exc
        content_sha256 = hashlib.sha256(raw).hexdigest()

        if options.get("skip_if_current") and GeographyCatalogueImport.objects.filter(
            content_sha256=content_sha256
        ).exists():
            # One indexed read. This is the steady-state path on every boot
            # after the catalogue has landed, and it must never be more
            # expensive — or more destructive — than that.
            self.stdout.write(
                json.dumps({"skipped": True, "content_sha256": content_sha256})
            )
            return

        try:
            manifest = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CommandError(f"Unable to read manifest {path}: {exc}") from exc
        if not isinstance(manifest, dict):
            raise CommandError("Manifest root must be a JSON object.")
        if manifest.get("format_version") != 1:
            raise CommandError(
                "Unsupported geography manifest format_version; expected 1."
            )

        countries = manifest.get("countries", [])
        places = manifest.get("places", [])
        alternate_names = manifest.get("alternate_names", [])
        mappings = manifest.get("airport_mappings", [])
        for label, rows in (
            ("countries", countries),
            ("places", places),
            ("alternate_names", alternate_names),
            ("airport_mappings", mappings),
        ):
            if not isinstance(rows, list) or any(
                not isinstance(row, dict) for row in rows
            ):
                raise CommandError(f"{label} must be a list of JSON objects.")
            _unique_rows(rows, label)

        default_version = str(manifest.get("source_version", "")).strip()
        counts = {"countries": 0, "places": 0, "alternate_names": 0, "mappings": 0}
        seen_places: dict[str, set[str]] = {}
        seen_alternate_names: dict[str, set[str]] = {}
        seen_mappings: dict[str, set[str]] = {}
        for row in alternate_names:
            source = _required(row, "source", default_version)
            source_id = _required(row, "source_id", default_version)
            seen_alternate_names.setdefault(source, set()).add(source_id)
        for row in mappings:
            source = _required(row, "source", default_version)
            source_id = _required(row, "source_id", default_version)
            seen_mappings.setdefault(source, set()).add(source_id)

        with transaction.atomic():
            country_by_code: dict[str, Country] = {}
            for row in countries:
                code = _required(row, "code", default_version).upper()
                if len(code) != 2 or not code.isascii() or not code.isalpha():
                    raise CommandError(f"Invalid ISO alpha-2 country code: {code!r}")
                source = _required(row, "source", default_version)
                source_id = _required(row, "source_id", default_version)
                version = str(row.get("source_version") or default_version).strip()
                if not version:
                    raise CommandError(f"Country {code} has no source_version.")
                if (
                    Country.objects.filter(source=source, source_id=source_id)
                    .exclude(code=code)
                    .exists()
                ):
                    raise CommandError(
                        f"Country source identity is assigned to another ISO code: {source}:{source_id}"
                    )
                country, _ = Country.objects.get_or_create(
                    code=code,
                    defaults={
                        "name": _required(row, "name", version),
                        "source": source,
                        "source_id": source_id,
                        "source_version": version,
                    },
                )
                country.name = _required(row, "name", version)
                country.source = source
                country.source_id = source_id
                country.source_version = version
                country.active = _bool(row.get("active"), True)
                country.metadata = _metadata(row)
                country.save()
                country_by_code[code] = country
                counts["countries"] += 1

            # Create/update records without parents first. This makes the
            # manifest order irrelevant and allows safe parent renames.
            place_by_key: dict[tuple[str, str], Place] = {}
            parent_refs: dict[tuple[str, str], tuple[str, str] | None] = {}
            for row in places:
                source = _required(row, "source", default_version)
                source_id = _required(row, "source_id", default_version)
                version = str(row.get("source_version") or default_version).strip()
                if not version:
                    raise CommandError(
                        f"Place {source}:{source_id} has no source_version."
                    )
                code = _required(row, "country_code", version).upper()
                country = (
                    country_by_code.get(code)
                    or Country.objects.filter(code=code).first()
                )
                if country is None:
                    raise CommandError(
                        f"Place {source}:{source_id} references unknown country {code}."
                    )
                place_type = _required(row, "place_type", version)
                if place_type not in Place.PlaceType.values:
                    raise CommandError(
                        f"Unknown place_type {place_type!r} for {source}:{source_id}."
                    )
                key = (source, source_id)
                place = Place.objects.filter(source=source, source_id=source_id).first()
                if place is not None and place.country_id != country.code:
                    raise CommandError(
                        f"Place source identity changed country: {source}:{source_id}"
                    )
                if place is None:
                    place = Place(source=source, source_id=source_id)
                place.country = country
                place.place_type = place_type
                place.source_version = version
                place.name = _required(row, "name", version)
                place.admin_level = str(row.get("admin_level") or "")[:48]
                place.latitude, place.longitude = _coordinates(row)
                place.iata_code = str(row.get("iata_code") or "").upper()
                place.icao_code = str(row.get("icao_code") or "").upper()
                if place.iata_code and (
                    len(place.iata_code) != 3
                    or not place.iata_code.isascii()
                    or not place.iata_code.isalpha()
                ):
                    raise CommandError(f"Invalid IATA code for {source}:{source_id}.")
                if place.icao_code and (
                    len(place.icao_code) != 4
                    or not place.icao_code.isascii()
                    or not place.icao_code.isalpha()
                ):
                    raise CommandError(f"Invalid ICAO code for {source}:{source_id}.")
                passenger_use = _bool(row.get("passenger_use"), False)
                if place_type != Place.PlaceType.AIRPORT and (
                    place.iata_code
                    or place.icao_code
                    or row.get("airport_type")
                    or passenger_use
                ):
                    raise CommandError(
                        f"Non-airport place {source}:{source_id} has airport fields."
                    )
                place.airport_type = str(row.get("airport_type") or "")[:40]
                place.passenger_use = passenger_use
                place.active = _bool(row.get("active"), True)
                if place_type == Place.PlaceType.AIRPORT and (
                    place.latitude is None or place.longitude is None
                ):
                    raise CommandError(
                        f"Airport {source}:{source_id} must have coordinates."
                    )
                place.metadata = _metadata(row)
                place.parent = None
                place.save()
                place_by_key[key] = place
                seen_places.setdefault(source, set()).add(source_id)
                parent_source = str(row.get("parent_source") or source).strip()
                parent_id = row.get("parent_source_id")
                parent_refs[key] = (
                    (parent_source, str(parent_id).strip())
                    if parent_id not in (None, "")
                    else None
                )

                if place_type == Place.PlaceType.AIRPORT and place.iata_code:
                    airport, _ = Airport.objects.get_or_create(
                        iata=place.iata_code,
                        defaults={
                            "name": place.name[:120],
                            "city": str(row.get("legacy_city") or "")[:80],
                            "country": code,
                        },
                    )
                    if airport.country != code and airport.country:
                        raise CommandError(
                            f"IATA {place.iata_code} already belongs to country {airport.country}."
                        )
                    airport.name = place.name[:120]
                    airport.city = str(
                        row.get("legacy_city") or airport.city or place.name
                    )[:80]
                    airport.country = code
                    airport.save(update_fields=("name", "city", "country"))
                    place.legacy_airport = airport
                    place.save(update_fields=("legacy_airport", "updated_at"))
                elif place_type != Place.PlaceType.AIRPORT and place.legacy_airport_id:
                    place.legacy_airport = None
                    place.save(update_fields=("legacy_airport", "updated_at"))
                counts["places"] += 1

            for key, parent_ref in parent_refs.items():
                if parent_ref is None:
                    continue
                parent = place_by_key.get(parent_ref)
                if parent is None:
                    parent = Place.objects.filter(
                        source=parent_ref[0], source_id=parent_ref[1]
                    ).first()
                if parent is None:
                    raise CommandError(
                        f"Place {key[0]}:{key[1]} references missing parent {parent_ref}."
                    )
                place = place_by_key[key]
                if parent.country_id != place.country_id:
                    raise CommandError(
                        f"Place {key[0]}:{key[1]} has a cross-country parent."
                    )
                if parent.pk == place.pk:
                    raise CommandError(f"Place {key[0]}:{key[1]} cannot parent itself.")
                place.parent = parent
                place.save(update_fields=("parent", "updated_at"))

            parent_by_id = dict(Place.objects.values_list("id", "parent_id"))
            for place in place_by_key.values():
                seen_ancestors = {place.pk}
                parent_id = parent_by_id.get(place.pk)
                while parent_id is not None:
                    if parent_id in seen_ancestors:
                        raise CommandError(
                            f"Place {place.source}:{place.source_id} has a parent cycle."
                        )
                    seen_ancestors.add(parent_id)
                    parent_id = parent_by_id.get(parent_id)

            for row in alternate_names:
                source = _required(row, "source", default_version)
                source_id = _required(row, "source_id", default_version)
                version = str(row.get("source_version") or default_version).strip()
                if not version:
                    raise CommandError(
                        f"Alternate name {source}:{source_id} has no source_version."
                    )
                place_key = (
                    str(row.get("place_source") or source).strip(),
                    _required(row, "place_source_id", version),
                )
                place = (
                    place_by_key.get(place_key)
                    or Place.objects.filter(
                        source=place_key[0], source_id=place_key[1]
                    ).first()
                )
                if place is None:
                    raise CommandError(
                        f"Alternate name references missing place {place_key}."
                    )
                alternate, _ = PlaceAlternateName.objects.get_or_create(
                    source=source,
                    source_id=source_id,
                    defaults={
                        "place": place,
                        "name": _required(row, "name", version),
                        "language": str(row.get("language") or "und"),
                        "source_version": version,
                    },
                )
                alternate.place = place
                alternate.name = _required(row, "name", version)
                alternate.language = str(row.get("language") or "und")
                alternate.source_version = version
                alternate.active = _bool(row.get("active"), True)
                alternate.metadata = _metadata(row)
                alternate.save()
                counts["alternate_names"] += 1

            if options["deactivate_missing"]:
                mapping_sources = set(seen_mappings)
                mapping_sources.update(
                    str(source).strip()
                    for source in manifest.get("deactivate_sources", [])
                    if str(source).strip()
                )
                for source in mapping_sources:
                    AirportLocalityMapping.objects.filter(source=source).exclude(
                        source_id__in=seen_mappings.get(source, set())
                    ).update(active=False, is_primary=False)

            for row in mappings:
                source = _required(row, "source", default_version)
                source_id = _required(row, "source_id", default_version)
                version = str(row.get("source_version") or default_version).strip()
                if not version:
                    raise CommandError(
                        f"Mapping {source}:{source_id} has no source_version."
                    )
                airport_key = (
                    str(row.get("airport_source") or source).strip(),
                    _required(row, "airport_source_id", version),
                )
                locality_key = (
                    str(row.get("locality_source") or source).strip(),
                    _required(row, "locality_source_id", version),
                )
                airport = (
                    place_by_key.get(airport_key)
                    or Place.objects.filter(
                        source=airport_key[0], source_id=airport_key[1]
                    ).first()
                )
                locality = (
                    place_by_key.get(locality_key)
                    or Place.objects.filter(
                        source=locality_key[0], source_id=locality_key[1]
                    ).first()
                )
                if airport is None or locality is None:
                    raise CommandError(
                        f"Mapping {source}:{source_id} references missing places."
                    )
                if airport.place_type != Place.PlaceType.AIRPORT:
                    raise CommandError(
                        f"Mapping {source}:{source_id} source is not an airport."
                    )
                if locality.place_type != Place.PlaceType.LOCALITY:
                    raise CommandError(
                        f"Mapping {source}:{source_id} target is not a locality."
                    )
                if airport.country_id != locality.country_id:
                    raise CommandError(
                        f"Mapping {source}:{source_id} crosses countries."
                    )
                relationship_type = str(
                    row.get("relationship_type")
                    or AirportLocalityMapping.RelationshipType.SERVED
                )
                if (
                    relationship_type
                    not in AirportLocalityMapping.RelationshipType.values
                ):
                    raise CommandError(
                        f"Mapping {source}:{source_id} has an unknown relationship type."
                    )
                mapping_active = _bool(row.get("active"), True)
                if mapping_active and (not airport.active or not locality.active):
                    raise CommandError(
                        f"Mapping {source}:{source_id} references an inactive place."
                    )
                mapping, _ = AirportLocalityMapping.objects.get_or_create(
                    source=source,
                    source_id=source_id,
                    defaults={
                        "airport": airport,
                        "locality": locality,
                        "relationship_type": relationship_type,
                        "source_version": version,
                    },
                )
                mapping.airport = airport
                mapping.locality = locality
                mapping.relationship_type = relationship_type
                mapping.is_primary = (
                    _bool(row.get("is_primary"), False) if mapping_active else False
                )
                mapping.source_version = version
                mapping.active = mapping_active
                mapping.metadata = _metadata(row)
                mapping.save()
                counts["mappings"] += 1

            if options["deactivate_missing"]:
                deactivate_sources = set(seen_places)
                deactivate_sources.update(seen_alternate_names)
                deactivate_sources.update(seen_mappings)
                deactivate_sources.update(
                    str(source).strip()
                    for source in manifest.get("deactivate_sources", [])
                    if str(source).strip()
                )
                for source in deactivate_sources:
                    seen = seen_places.get(source, set())
                    Place.objects.filter(source=source).exclude(
                        source_id__in=seen
                    ).update(active=False)
                    PlaceAlternateName.objects.filter(source=source).exclude(
                        source_id__in=seen_alternate_names.get(source, set())
                    ).update(active=False)

                AirportLocalityMapping.objects.filter(
                    Q(airport__active=False) | Q(locality__active=False)
                ).update(active=False, is_primary=False)

            # Inside the same transaction as the rows it describes: a marker
            # that outlived a rolled-back import would make the next boot skip
            # a catalogue that is not actually there.
            GeographyCatalogueImport.objects.update_or_create(
                content_sha256=content_sha256,
                defaults={
                    "counts": counts,
                    "applied_by_release": str(
                        getattr(settings, "RELEASE_ID", "") or ""
                    )[:128],
                },
            )

        self.stdout.write(
            self.style.SUCCESS(
                json.dumps({**counts, "content_sha256": content_sha256}, sort_keys=True)
            )
        )
