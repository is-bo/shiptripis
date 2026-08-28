from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models


latitude_validators = (
    MinValueValidator(Decimal("-90")),
    MaxValueValidator(Decimal("90")),
)
longitude_validators = (
    MinValueValidator(Decimal("-180")),
    MaxValueValidator(Decimal("180")),
)
country_code_validator = RegexValidator(
    regex=r"^[A-Z]{2}$",
    message="Use an uppercase ISO 3166-1 alpha-2 country code.",
)


class Location(models.Model):
    """An immutable place record with separate private and public precision.

    Exact fields are available to backend matching, but API callers other than
    the owner receive only the public label and optional coarse coordinates.
    """

    class Kind(models.TextChoices):
        CITY = "city", "City"
        EXACT_ADDRESS = "exact_address", "Exact address"
        MAP_POINT = "map_point", "Map point"
        AIRPORT = "airport", "Airport"
        PUBLIC_MEETING_POINT = "public_meeting_point", "Public meeting point"

    class Precision(models.TextChoices):
        EXACT = "exact", "Exact"
        ROOFTOP = "rooftop", "Rooftop"
        BUILDING = "building", "Building"
        STREET = "street", "Street"
        NEIGHBORHOOD = "neighborhood", "Neighborhood"
        CITY = "city", "City"
        REGION = "region", "Region"
        COUNTRY = "country", "Country"
        APPROXIMATE = "approximate", "Approximate"
        UNKNOWN = "unknown", "Unknown"

    kind = models.CharField(max_length=24, choices=Kind.choices)

    # normalized_label and private_label may contain an exact address. They
    # must never be rendered by the public serializer.
    normalized_label = models.CharField(max_length=500)
    public_label = models.CharField(max_length=255)
    private_label = models.CharField(max_length=500)
    city = models.CharField(max_length=120)
    region = models.CharField(max_length=120, blank=True, default="")
    country_code = models.CharField(
        max_length=2,
        validators=[country_code_validator],
    )

    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        validators=latitude_validators,
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        validators=longitude_validators,
    )
    coarse_latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        validators=latitude_validators,
        null=True,
        blank=True,
    )
    coarse_longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        validators=longitude_validators,
        null=True,
        blank=True,
    )

    # Provider fields are deliberately generic so the domain is not tied to a
    # map vendor. provider_metadata is private because raw geocoder responses
    # may contain a formatted address or other exact-location information.
    provider = models.CharField(max_length=64, blank=True, default="")
    source = models.CharField(max_length=64, blank=True, default="")
    provider_place_id = models.CharField(max_length=255, blank=True, default="")
    provider_metadata = models.JSONField(blank=True, default=dict)
    precision = models.CharField(
        max_length=24,
        choices=Precision.choices,
        default=Precision.UNKNOWN,
    )
    # Server-controlled provenance gate for airport coordinates. A user may
    # create valid selected/geocoded map points, but only a reviewed import or
    # provider integration may mark an airport coordinate as trusted.
    coordinates_trusted = models.BooleanField(default=False, db_index=True)
    coordinate_dataset_version = models.CharField(
        max_length=64,
        blank=True,
        default="",
    )

    airport = models.ForeignKey(
        "trips.Airport",
        on_delete=models.PROTECT,
        related_name="locations",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="locations_created",
        null=True,
        blank=True,
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="locations_owned",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "locations_location"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(
                fields=("country_code", "city"),
                name="locations_country_city_idx",
            ),
            models.Index(
                fields=("kind", "country_code"),
                name="locations_kind_country_idx",
            ),
            models.Index(
                fields=("owner", "-created_at"),
                name="locations_owner_created_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(latitude__gte=-90, latitude__lte=90),
                name="locations_latitude_range",
            ),
            models.CheckConstraint(
                condition=models.Q(longitude__gte=-180, longitude__lte=180),
                name="locations_longitude_range",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        coarse_latitude__isnull=True,
                        coarse_longitude__isnull=True,
                    )
                    | models.Q(
                        coarse_latitude__isnull=False,
                        coarse_longitude__isnull=False,
                    )
                ),
                name="locations_coarse_coords_pair",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(coarse_latitude__isnull=True)
                    | models.Q(
                        coarse_latitude__gte=-90,
                        coarse_latitude__lte=90,
                    )
                ),
                name="locations_coarse_lat_range",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(coarse_longitude__isnull=True)
                    | models.Q(
                        coarse_longitude__gte=-180,
                        coarse_longitude__lte=180,
                    )
                ),
                name="locations_coarse_lon_range",
            ),
            models.UniqueConstraint(
                fields=("owner", "provider", "provider_place_id"),
                condition=(
                    models.Q(owner__isnull=False)
                    & ~models.Q(provider="")
                    & ~models.Q(provider_place_id="")
                ),
                name="locations_owner_provider_place_uniq",
            ),
            models.UniqueConstraint(
                fields=("provider", "provider_place_id"),
                condition=(
                    models.Q(owner__isnull=True)
                    & ~models.Q(provider="")
                    & ~models.Q(provider_place_id="")
                ),
                name="locations_shared_provider_place_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        coordinates_trusted=False,
                        coordinate_dataset_version="",
                    )
                    | (
                        models.Q(coordinates_trusted=True)
                        & ~models.Q(coordinate_dataset_version="")
                    )
                ),
                name="locations_coordinate_trust_pair",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        coarse_pair = (self.coarse_latitude is None, self.coarse_longitude is None)
        if coarse_pair[0] != coarse_pair[1]:
            errors["coarse_latitude"] = (
                "Coarse latitude and longitude must be supplied together."
            )
        if self.provider_place_id and not self.provider:
            errors["provider"] = "Provider is required when provider_place_id is set."
        if self.airport_id and self.kind != self.Kind.AIRPORT:
            errors["airport"] = "An Airport link is valid only for airport locations."
        if self.coordinates_trusted and not self.coordinate_dataset_version:
            errors["coordinate_dataset_version"] = (
                "Trusted coordinates require a reviewed dataset/provider version."
            )
        if self.coordinate_dataset_version and not self.coordinates_trusted:
            errors["coordinates_trusted"] = (
                "A dataset version is valid only for server-trusted coordinates."
            )
        if not isinstance(self.provider_metadata, dict):
            errors["provider_metadata"] = "Provider metadata must be a JSON object."
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return self.public_label
