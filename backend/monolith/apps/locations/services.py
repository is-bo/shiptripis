from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.trips.models import Airport

from .models import Location


def _coordinate(value: object, *, minimum: Decimal, maximum: Decimal) -> Decimal:
    try:
        coordinate = Decimal(str(value)).quantize(Decimal("0.000001"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError("Coordinate must be a finite decimal value.") from exc
    if not coordinate.is_finite() or not minimum <= coordinate <= maximum:
        raise ValidationError(f"Coordinate must be between {minimum} and {maximum}.")
    return coordinate


@transaction.atomic
def create_trusted_airport_location(
    *,
    airport: Airport,
    latitude: object,
    longitude: object,
    dataset_version: str,
) -> tuple[Location, bool]:
    """Create one immutable shared airport point from a reviewed dataset."""

    dataset_version = dataset_version.strip()
    if not dataset_version or len(dataset_version) > 64:
        raise ValidationError("Dataset version must contain 1 to 64 characters.")
    latitude_value = _coordinate(
        latitude,
        minimum=Decimal("-90"),
        maximum=Decimal("90"),
    )
    longitude_value = _coordinate(
        longitude,
        minimum=Decimal("-180"),
        maximum=Decimal("180"),
    )
    provider = "reviewed_airport_dataset"
    provider_place_id = f"{dataset_version}:{airport.iata}"
    existing = Location.objects.filter(
        owner__isnull=True,
        provider=provider,
        provider_place_id=provider_place_id,
    ).first()
    if existing is not None:
        if (
            existing.latitude != latitude_value
            or existing.longitude != longitude_value
            or existing.airport_id != airport.pk
        ):
            raise ValidationError(
                "This immutable dataset version already contains different airport data."
            )
        return existing, False

    quantum = Decimal("0.1")
    location = Location(
        kind=Location.Kind.AIRPORT,
        normalized_label=f"{airport.iata} — {airport.name}",
        public_label=f"{airport.iata} — {airport.city}, {airport.country}",
        private_label=f"{airport.iata} — {airport.name}",
        city=airport.city,
        country_code=airport.country,
        latitude=latitude_value,
        longitude=longitude_value,
        coarse_latitude=latitude_value.quantize(quantum, rounding=ROUND_HALF_UP),
        coarse_longitude=longitude_value.quantize(quantum, rounding=ROUND_HALF_UP),
        provider=provider,
        source="reviewed_import",
        provider_place_id=provider_place_id,
        provider_metadata={"dataset_version": dataset_version, "iata": airport.iata},
        precision=Location.Precision.EXACT,
        coordinates_trusted=True,
        coordinate_dataset_version=dataset_version,
        airport=airport,
        owner=None,
        created_by=None,
    )
    location.full_clean()
    location.save(force_insert=True)
    return location, True
