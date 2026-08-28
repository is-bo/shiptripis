from __future__ import annotations

import csv
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.locations.services import create_trusted_airport_location
from apps.trips.models import Airport


class Command(BaseCommand):
    help = "Import reviewed IATA airport coordinates from an explicit CSV dataset."

    def add_arguments(self, parser) -> None:
        parser.add_argument("csv_path")
        parser.add_argument("--dataset-version", required=True)

    def handle(self, *args, **options):
        del args
        path = Path(options["csv_path"]).resolve()
        if not path.is_file():
            raise CommandError(f"Airport coordinate CSV does not exist: {path}")

        try:
            with path.open("r", encoding="utf-8-sig", newline="") as source:
                rows = list(csv.DictReader(source))
        except (OSError, UnicodeError, csv.Error) as exc:
            raise CommandError(f"Could not read airport coordinate CSV: {exc}") from exc
        if not rows:
            raise CommandError("Airport coordinate CSV contains no data rows.")
        if len(rows) > 10_000:
            raise CommandError("Airport coordinate CSV exceeds the 10,000-row limit.")
        required = {"iata", "latitude", "longitude"}
        if not required.issubset(rows[0]):
            raise CommandError(
                "CSV headers must include iata, latitude, and longitude."
            )

        created = 0
        try:
            with transaction.atomic():
                for number, row in enumerate(rows, start=2):
                    iata = (row.get("iata") or "").strip().upper()
                    try:
                        airport = Airport.objects.get(pk=iata)
                    except Airport.DoesNotExist as exc:
                        raise CommandError(
                            f"Row {number}: unknown IATA airport '{iata}'."
                        ) from exc
                    _location, was_created = create_trusted_airport_location(
                        airport=airport,
                        latitude=row.get("latitude"),
                        longitude=row.get("longitude"),
                        dataset_version=options["dataset_version"],
                    )
                    created += int(was_created)
        except ValidationError as exc:
            raise CommandError(f"Airport coordinate import failed: {exc}") from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Reviewed {len(rows)} airport rows; created {created} trusted locations."
            )
        )
