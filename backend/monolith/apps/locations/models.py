from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models

from .geography import normalize_search_name


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
    # Optional authoritative catalogue context.  Legacy address-book rows may
    # remain unscoped; every new V1 preferred point is scoped to the selected
    # canonical Place and can therefore never create a competing city identity.
    canonical_place = models.ForeignKey(
        "Place",
        on_delete=models.PROTECT,
        related_name="preferred_locations",
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


class Country(models.Model):
    """An authoritative ISO country used by the geography catalogue.

    ``Location`` remains the user-owned exact address/pin model.  Country and
    Place are stable catalogue identities consumed by the future locality UX.
    """

    code = models.CharField(
        max_length=2,
        primary_key=True,
        validators=[country_code_validator],
    )
    name = models.CharField(max_length=120)
    normalized_name = models.CharField(max_length=120, editable=False)
    source = models.CharField(max_length=96)
    source_id = models.CharField(max_length=128)
    source_version = models.CharField(max_length=96)
    active = models.BooleanField(default=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "locations_country"
        ordering = ("name", "code")
        indexes = [
            models.Index(fields=("active", "name"), name="geo_country_active_name_idx"),
            models.Index(
                fields=("source", "source_id"),
                name="geo_country_source_id_idx",
            ),
            models.Index(
                fields=("normalized_name",),
                name="geo_country_norm_name_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("source", "source_id"),
                name="geo_country_source_identity_uniq",
            ),
        ]

    def save(self, *args, **kwargs):
        self.code = self.code.upper()
        self.normalized_name = normalize_search_name(self.name)
        super().save(*args, **kwargs)

    def clean(self) -> None:
        super().clean()
        self.code = self.code.upper()
        if not isinstance(self.metadata, dict):
            raise ValidationError({"metadata": "Metadata must be a JSON object."})

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class Place(models.Model):
    """A stable selectable geography record, including airports.

    The natural key is ``(source, source_id)``.  Names and coordinates can be
    refreshed without changing the internal primary key, while old records are
    retained and marked inactive when a source retires them.
    """

    class PlaceType(models.TextChoices):
        ADMIN_REGION = "admin_region", "Administrative region"
        LOCALITY = "locality", "Locality / commune"
        AIRPORT = "airport", "Airport"

    country = models.ForeignKey(
        Country,
        on_delete=models.PROTECT,
        related_name="places",
    )
    place_type = models.CharField(max_length=24, choices=PlaceType.choices)
    source = models.CharField(max_length=96)
    source_id = models.CharField(max_length=160)
    source_version = models.CharField(max_length=96)
    name = models.CharField(max_length=255)
    normalized_name = models.CharField(max_length=255, editable=False)
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="children",
        null=True,
        blank=True,
    )
    admin_level = models.CharField(max_length=48, blank=True, default="")
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        validators=latitude_validators,
        null=True,
        blank=True,
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        validators=longitude_validators,
        null=True,
        blank=True,
    )
    iata_code = models.CharField(max_length=3, blank=True, default="")
    icao_code = models.CharField(max_length=4, blank=True, default="")
    airport_type = models.CharField(max_length=40, blank=True, default="")
    passenger_use = models.BooleanField(default=False)
    legacy_airport = models.OneToOneField(
        "trips.Airport",
        on_delete=models.PROTECT,
        related_name="catalogue_place",
        null=True,
        blank=True,
    )
    active = models.BooleanField(default=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "locations_place"
        ordering = ("name", "id")
        indexes = [
            models.Index(
                fields=("country", "active", "place_type"),
                name="geo_place_ctry_act_type_idx",
            ),
            models.Index(
                fields=("source", "source_id"), name="geo_place_source_id_idx"
            ),
            models.Index(
                fields=("place_type", "active"),
                name="geo_place_type_active_idx",
            ),
            models.Index(
                fields=("parent", "active"), name="geo_place_parent_active_idx"
            ),
            models.Index(
                fields=("active", "normalized_name"),
                name="geo_place_active_norm_name_idx",
            ),
            models.Index(
                fields=("country", "normalized_name"),
                name="geo_place_ctry_norm_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("source", "source_id"),
                name="geo_place_source_identity_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(latitude__isnull=True, longitude__isnull=True)
                    | models.Q(latitude__isnull=False, longitude__isnull=False)
                ),
                name="geo_place_coords_pair",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(latitude__isnull=True)
                    | models.Q(latitude__gte=-90, latitude__lte=90)
                ),
                name="geo_place_latitude_range",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(longitude__isnull=True)
                    | models.Q(longitude__gte=-180, longitude__lte=180)
                ),
                name="geo_place_longitude_range",
            ),
            models.CheckConstraint(
                condition=models.Q(iata_code="") | models.Q(place_type="airport"),
                name="geo_place_iata_airport_only",
            ),
            models.CheckConstraint(
                condition=models.Q(icao_code="") | models.Q(place_type="airport"),
                name="geo_place_icao_airport_only",
            ),
            models.CheckConstraint(
                condition=models.Q(passenger_use=False)
                | models.Q(place_type="airport"),
                name="geo_place_passenger_airport_only",
            ),
            models.CheckConstraint(
                condition=~models.Q(place_type="airport")
                | models.Q(latitude__isnull=False, longitude__isnull=False),
                name="geo_place_airport_coords_required",
            ),
            models.UniqueConstraint(
                fields=("iata_code",),
                condition=models.Q(iata_code__gt=""),
                name="geo_place_iata_uniq",
            ),
        ]

    def save(self, *args, **kwargs):
        self.normalized_name = normalize_search_name(self.name)
        if self.iata_code:
            self.iata_code = self.iata_code.upper()
        if self.icao_code:
            self.icao_code = self.icao_code.upper()
        super().save(*args, **kwargs)

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        if self.parent_id == self.pk:
            errors["parent"] = "A place cannot be its own parent."
        if self.parent is not None and self.parent.country_id != self.country_id:
            errors["parent"] = "Parent must belong to the same country."
        if self.place_type != self.PlaceType.AIRPORT and (
            self.iata_code
            or self.icao_code
            or self.airport_type
            or self.legacy_airport_id
            or self.passenger_use
        ):
            errors["place_type"] = "Airport fields are valid only for airport places."
        if not isinstance(self.metadata, dict):
            errors["metadata"] = "Metadata must be a JSON object."
        if errors:
            raise ValidationError(errors)

    @property
    def display_label(self) -> str:
        if self.parent_id and self.parent is not None:
            return f"{self.name} · {self.parent.name}"
        return self.name

    def resolve_matching_locality(self):
        """Return the canonical locality identity used by V1 compatibility.

        Airports must have exactly one active primary ``served`` mapping;
        returning ``None`` is a deliberate fail-closed result for an unmapped
        airport rather than an inferred city from a display label.
        """

        if self.place_type == self.PlaceType.LOCALITY:
            # A reviewed catalogue refresh can retire a locality after a
            # request/journey was created.  Do not keep matching against a
            # retired identity; V1 compatibility must fail closed.
            return self if self.active else None
        if self.place_type != self.PlaceType.AIRPORT:
            return None
        cached_locality = getattr(self, "_matching_locality_cache", None)
        if cached_locality is not None:
            return cached_locality or None
        prefetched = getattr(self, "_active_matching_mappings", None)
        if prefetched is None:
            prefetched = getattr(self, "_prefetched_objects_cache", {}).get(
                "airport_mappings"
            )
        if prefetched is not None:
            mapping = next(
                (
                    item
                    for item in prefetched
                    if item.active
                    and item.is_primary
                    and item.relationship_type
                    == AirportLocalityMapping.RelationshipType.SERVED
                    and item.locality.active
                ),
                None,
            )
            locality = mapping.locality if mapping else None
            self._matching_locality_cache = locality or False
            return locality
        mapping = (
            self.airport_mappings.filter(
                active=True,
                is_primary=True,
                relationship_type=AirportLocalityMapping.RelationshipType.SERVED,
                locality__active=True,
            )
            .select_related("locality")
            .first()
        )
        locality = mapping.locality if mapping else None
        self._matching_locality_cache = locality or False
        return locality

    def __str__(self) -> str:
        return self.display_label


class PlaceAlternateName(models.Model):
    """A source-backed alternate/localized name; no invented translations."""

    place = models.ForeignKey(
        Place,
        on_delete=models.CASCADE,
        related_name="alternate_name_records",
    )
    name = models.CharField(max_length=255)
    normalized_name = models.CharField(max_length=255, editable=False)
    language = models.CharField(max_length=16, blank=True, default="und")
    source = models.CharField(max_length=96)
    source_id = models.CharField(max_length=160)
    source_version = models.CharField(max_length=96)
    active = models.BooleanField(default=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "locations_place_alternate_name"
        indexes = [
            models.Index(
                fields=("normalized_name", "active"),
                name="geo_alt_name_norm_active_idx",
            ),
            models.Index(
                fields=("source", "source_id"), name="geo_alt_name_source_id_idx"
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("source", "source_id"),
                name="geo_alt_name_source_identity_uniq",
            ),
            models.UniqueConstraint(
                fields=("place", "language", "normalized_name"),
                name="geo_alt_name_place_lang_norm_uniq",
            ),
        ]

    def save(self, *args, **kwargs):
        self.normalized_name = normalize_search_name(self.name)
        self.language = (self.language or "und").casefold()
        super().save(*args, **kwargs)

    def clean(self) -> None:
        super().clean()
        if not isinstance(self.metadata, dict):
            raise ValidationError({"metadata": "Metadata must be a JSON object."})

    def __str__(self) -> str:
        return f"{self.name} ({self.language})"


class AirportLocalityMapping(models.Model):
    """Explicit airport-to-useful-locality context mapping.

    ``Place.parent`` identifies the physical administrative context.  This
    model records the separate locality an airport commercially serves.
    """

    class RelationshipType(models.TextChoices):
        SERVED = "served", "Commercially served locality"
        PHYSICAL = "physical", "Physical locality"

    airport = models.ForeignKey(
        Place,
        on_delete=models.CASCADE,
        related_name="airport_mappings",
    )
    locality = models.ForeignKey(
        Place,
        on_delete=models.PROTECT,
        related_name="airport_contexts",
    )
    relationship_type = models.CharField(
        max_length=16,
        choices=RelationshipType.choices,
        default=RelationshipType.SERVED,
    )
    is_primary = models.BooleanField(default=False)
    source = models.CharField(max_length=96)
    source_id = models.CharField(max_length=160)
    source_version = models.CharField(max_length=96)
    active = models.BooleanField(default=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "locations_airport_locality_mapping"
        indexes = [
            models.Index(
                fields=("airport", "active"), name="geo_map_airport_active_idx"
            ),
            models.Index(
                fields=("locality", "active"), name="geo_map_locality_active_idx"
            ),
            models.Index(
                fields=("source", "source_id"),
                name="geo_map_source_id_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("source", "source_id"),
                name="geo_map_source_identity_uniq",
            ),
            models.UniqueConstraint(
                fields=("airport", "relationship_type", "locality"),
                name="geo_map_airport_type_locality_uniq",
            ),
            models.UniqueConstraint(
                fields=("airport", "relationship_type"),
                condition=models.Q(active=True, is_primary=True),
                name="geo_map_one_primary_uniq",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        if (
            self.airport is not None
            and self.airport.place_type != Place.PlaceType.AIRPORT
        ):
            errors["airport"] = "Mapping source must be an airport place."
        if (
            self.locality is not None
            and self.locality.place_type != Place.PlaceType.LOCALITY
        ):
            errors["locality"] = "Mapping target must be a locality place."
        if (
            self.airport is not None
            and self.locality is not None
            and self.airport.country_id != self.locality.country_id
        ):
            errors["locality"] = "Airport and locality must share a country."
        if not isinstance(self.metadata, dict):
            errors["metadata"] = "Metadata must be a JSON object."
        if self.active and (
            (self.airport is not None and not self.airport.active)
            or (self.locality is not None and not self.locality.active)
        ):
            errors["active"] = "An active mapping must reference active places."
        if not self.active and self.is_primary:
            errors["is_primary"] = "An inactive mapping cannot be primary."
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.airport.name} → {self.locality.name}"


class GeographyCatalogueImport(models.Model):
    """A record that one exact catalogue manifest has been applied here.

    The catalogue is 56k rows of reviewed source data, too large to live in a
    migration and too important to leave to somebody remembering to run a
    command. The release ships one manifest artefact and the deployment applies
    it once; this table is how "once" is decided.

    The key is ``content_sha256`` — the digest of the manifest's *uncompressed*
    bytes, so it identifies the reviewed data itself rather than how it was
    packed. A boot whose shipped manifest already matches the stored digest
    skips the import in one indexed read; that is what keeps the import from
    being destructive, or even expensive, on every boot.
    """

    content_sha256 = models.CharField(max_length=64, unique=True)
    #: What the manifest actually put in the database, for the operator who has
    #: to answer "did the catalogue land?" without counting rows by hand.
    counts = models.JSONField(default=dict, blank=True)
    #: The release that applied it. Free text on purpose: it is provenance for
    #: a human, never something the importer branches on.
    applied_by_release = models.CharField(max_length=128, blank=True, default="")
    applied_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "locations_geography_catalogue_import"
        ordering = ("-applied_at",)
        verbose_name = "geography catalogue import"
        verbose_name_plural = "geography catalogue imports"

    def __str__(self) -> str:
        return f"{self.content_sha256[:12]} @ {self.applied_at:%Y-%m-%d %H:%M}"
