"""Seed the reviewed initial sea crossings (spec 5.3.1, plan L3A).

Idempotent and conservative:

* A port name must resolve to exactly one active catalogue *city* in its
  country, by name or by a source-backed alternate name. Anything else is
  reported and every crossing that uses it is skipped; nothing is guessed.
* A crossing that already exists is left exactly as it is. Re-running the
  command therefore never re-activates a crossing staff deactivated, and never
  rewrites a distance staff corrected.
* New rows take their ``active`` flag from the file and their great-circle
  distance from catalogue coordinates when both cities have them, otherwise
  from the file's reviewed port coordinates, through the same haversine
  function either way.

The default file ships inside the application image beside the geography
manifest, which is what lets the VPS ``catalogue`` step run it.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.locations.models import Place, SeaCrossing
from apps.locations.sea_crossings import great_circle_meters, resolve_port
from apps.routing.geometry import GeoPoint, haversine_meters

DEFAULT_FILE = Path(__file__).resolve().parents[2] / "data" / "sea_crossings.json"


class Command(BaseCommand):
    help = "Create the reviewed initial sea crossings; never changes existing rows."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--file",
            default=str(DEFAULT_FILE),
            help="Path to the sea crossings JSON file (defaults to the shipped one).",
        )

    def handle(self, *args, **options) -> None:
        path = Path(options["file"])
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            ports = document["ports"]
            crossings = document["crossings"]
            version = str(document["version"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise CommandError(f"Cannot read sea crossings from {path}: {exc}") from exc

        resolved: dict[str, Place] = {}
        fallback_points: dict[str, GeoPoint] = {}
        for slug, port in ports.items():
            place, problem = resolve_port(str(port["country"]), str(port["name"]))
            if place is None:
                self.stdout.write(
                    self.style.WARNING(
                        f"skipped port {slug} ({port['name']}, {port['country']}): {problem}"
                    )
                )
                continue
            resolved[slug] = place
            fallback_points[slug] = GeoPoint(
                float(port["latitude"]), float(port["longitude"])
            )

        created = existing = skipped = 0
        with transaction.atomic():
            for row in crossings:
                origin_slug, destination_slug = row["from"], row["to"]
                origin = resolved.get(origin_slug)
                destination = resolved.get(destination_slug)
                if origin is None or destination is None:
                    skipped += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"skipped crossing {origin_slug} -> {destination_slug}: "
                            "a port did not resolve"
                        )
                    )
                    continue
                if SeaCrossing.objects.filter(
                    origin_locality=origin, destination_locality=destination
                ).exists():
                    existing += 1
                    continue
                distance = great_circle_meters(origin, destination)
                if distance is None:
                    distance = haversine_meters(
                        fallback_points[origin_slug], fallback_points[destination_slug]
                    )
                crossing = SeaCrossing.objects.create(
                    origin_locality=origin,
                    destination_locality=destination,
                    distance_meters=distance,
                    is_active=bool(row["active"]),
                )
                self._audit(crossing, version=version, path=path)
                created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"sea crossings: {created} created, {existing} already present, "
                f"{skipped} skipped"
            )
        )

    @staticmethod
    def _audit(crossing: SeaCrossing, *, version: str, path: Path) -> None:
        from apps.admin_panel.services import record_admin_action

        record_admin_action(
            actor=None,
            action="sea_crossing.seeded",
            target=crossing,
            before={},
            after={
                "origin_locality_id": crossing.origin_locality_id,
                "destination_locality_id": crossing.destination_locality_id,
                "distance_meters": crossing.distance_meters,
                "is_active": crossing.is_active,
            },
            reason=f"Initial sea crossings {version} ({path.name})",
        )
