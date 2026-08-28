"""Parcels schema.

Per ARCHITECTURE.md §11:
- `ParcelRequest` — base row via Django multi-table inheritance.
- `DeliveryRequest(ParcelRequest)` — sender ships an item they already own.
- `ProductRequest(ParcelRequest)` — sender asks the traveler to BUY then carry.
- `ParcelMedia` — photos referencing object storage (bucket + object_key).

Status machine:
    open → matched → in_transit → delivered → completed
                  ↘ cancelled
                  ↘ expired

Pricing intent (from sender) is captured here as `base_amount_dzd` (delivery)
or `product_price_dzd` (product). The authoritative *frozen* amounts live on
the Offer row when a traveler accepts/counters (CLAUDE.md §6).
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.trips.models import Airport


class ParcelRequest(models.Model):
    """Base row for a sender's request.

    Two concrete subclasses use multi-table inheritance:
    - DeliveryRequest (kind=delivery)
    - ProductRequest  (kind=product)
    """

    class Kind(models.TextChoices):
        DELIVERY = "delivery", "Delivery"
        PRODUCT = "product", "Product"

    class Status(models.TextChoices):
        #: V1 posting-deposit mode only. The sender has created the request but
        #: the deposit has not been captured, so the request is not published,
        #: not discoverable and not proposable. Publication is the effect of a
        #: reconciled payment, never a client assertion.
        AWAITING_DEPOSIT = "awaiting_deposit", "Awaiting posting deposit"
        OPEN = "open", "Open"
        MATCHED = "matched", "Matched"
        IN_TRANSIT = "in_transit", "In transit"
        DELIVERED = "delivered", "Delivered"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    class ItemType(models.TextChoices):
        DOCUMENTS = "documents", "Documents"
        SMALL_BOX = "small_box", "Small box"
        ELECTRONICS = "electronics", "Electronics"
        CLOTHING = "clothing", "Clothing"
        OTHER = "other", "Other"

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="parcel_requests",
    )
    kind = models.CharField(max_length=12, choices=Kind.choices, db_index=True)

    origin = models.ForeignKey(
        Airport,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="parcels_from",
    )
    destination = models.ForeignKey(
        Airport,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="parcels_to",
    )
    pickup_city = models.CharField(max_length=80, blank=True, default="")
    delivery_city = models.CharField(max_length=80, blank=True, default="")

    weight_kg = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text="Legacy integer weight. V1 uses DeliveryRequest.actual_weight_kg.",
    )
    item_type = models.CharField(
        max_length=16, choices=ItemType.choices, default=ItemType.OTHER
    )
    description = models.TextField(blank=True, default="", max_length=2000)

    deadline_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Latest acceptable delivery time. Used by matching.",
    )

    # When set, the sender posted this request targeting one specific traveler
    # (e.g. from a trip tile). Counter-offers are only legal in that direction —
    # broadcast requests (target_traveler=NULL) are accept/decline because the
    # sender already priced the deal. See apps/matching/views.py CounterOfferView.
    target_traveler = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="targeted_parcels",
    )

    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.OPEN, db_index=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "parcels_request"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["origin", "destination", "status"],
                name="parcels_corridor_idx",
            ),
            models.Index(fields=["sender", "-created_at"], name="parcels_sender_idx"),
            models.Index(fields=["kind", "status"], name="parcels_kind_status_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(origin=models.F("destination")),
                name="parcels_origin_neq_destination",
            ),
        ]

    def __str__(self) -> str:
        return f"#{self.id} {self.kind} {self.origin_id or '?'}→{self.destination_id or '?'}"


class DeliveryRequest(ParcelRequest):
    """Sender already owns the item; offers a base amount, traveler keeps 75%.

    `base_amount_dzd` is the **sender-proposed** payout to the traveler before
    the 25% commission is added on top (CLAUDE.md §6). Final numbers are
    frozen on the Offer row when accepted.
    """

    schema_version = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(2)],
        help_text="1 is the legacy airport/DZD contract; 2 is the V1 location/EUR contract.",
    )
    pickup_location = models.ForeignKey(
        "locations.Location",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="delivery_requests_from",
    )
    delivery_location = models.ForeignKey(
        "locations.Location",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="delivery_requests_to",
    )
    ready_window_start = models.DateTimeField(null=True, blank=True)
    ready_window_end = models.DateTimeField(null=True, blank=True)
    actual_weight_kg = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("0.01")),
            MaxValueValidator(Decimal("100.00")),
        ],
    )
    length_cm = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("0.01")),
            MaxValueValidator(Decimal("500.00")),
        ],
    )
    width_cm = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("0.01")),
            MaxValueValidator(Decimal("500.00")),
        ],
    )
    height_cm = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(Decimal("0.01")),
            MaxValueValidator(Decimal("500.00")),
        ],
    )
    declared_value_eur_cents = models.PositiveBigIntegerField(null=True, blank=True)
    #: The sender's posted *intent* only. It is not an agreed price and never
    #: feeds pricing, ranking or settlement: the authoritative reward is the
    #: Offer's `traveler_reward_minor`, which the server validates against the
    #: matched minimum. The column name is retained for audit continuity; the
    #: API exposes it as `sender_proposed_reward_eur_cents`.
    traveler_reward_eur_cents = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text=(
            "Sender-posted intended reward in canonical EUR cents. Non-binding "
            "and non-authoritative; Offer.traveler_reward_minor is the agreed "
            "reward."
        ),
    )
    title = models.CharField(max_length=160, blank=True, default="")
    category = models.CharField(
        max_length=32,
        choices=ParcelRequest.ItemType.choices,
        blank=True,
        default="",
    )
    handling_notes = models.TextField(blank=True, default="", max_length=2000)
    fragile = models.BooleanField(default=False)
    # Ranking hook only, and the only two columns a boost may ever write on a
    # request. `apps.boosts` derives them from its active purchases; nothing
    # about compatibility, capacity, KYC, timing or safety is reachable from
    # here, which is what makes "boost never creates compatibility" structural.
    ranking_boost_weight = models.PositiveSmallIntegerField(default=0)
    ranking_boost_expires_at = models.DateTimeField(null=True, blank=True)
    description_is_accurate = models.BooleanField(default=False)
    item_is_legal = models.BooleanField(default=False)
    no_prohibited_goods = models.BooleanField(default=False)
    declared_value_is_accurate = models.BooleanField(default=False)
    customs_responsibilities_understood = models.BooleanField(default=False)

    base_amount_dzd = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(100)],
        help_text="Legacy proposed payout in DZD. Null for V1 EUR requests.",
    )

    class Meta:
        db_table = "parcels_delivery"
        indexes = [
            models.Index(
                fields=["schema_version", "pickup_location", "delivery_location"],
                name="parcels_v1_route_idx",
            ),
            models.Index(
                fields=["schema_version", "ready_window_start", "ready_window_end"],
                name="parcels_v1_ready_window_idx",
            ),
            models.Index(
                fields=["ranking_boost_expires_at"],
                name="parcels_boost_expiry_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(schema_version__in=(1, 2)),
                name="parcels_delivery_schema_ver",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(schema_version=1)
                    | (
                        models.Q(pickup_location__isnull=False)
                        & models.Q(delivery_location__isnull=False)
                        & models.Q(ready_window_start__isnull=False)
                        & models.Q(ready_window_end__isnull=False)
                        & models.Q(actual_weight_kg__isnull=False)
                        & models.Q(declared_value_eur_cents__isnull=False)
                        & models.Q(traveler_reward_eur_cents__isnull=False)
                    )
                ),
                name="parcels_delivery_v1_required",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(pickup_location__isnull=True)
                    | models.Q(delivery_location__isnull=True)
                    | ~models.Q(pickup_location=models.F("delivery_location"))
                ),
                name="parcels_delivery_locations_differ",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(ready_window_start__isnull=True)
                    & models.Q(ready_window_end__isnull=True)
                )
                | (
                    models.Q(ready_window_start__isnull=False)
                    & models.Q(ready_window_end__isnull=False)
                    & models.Q(ready_window_start__lt=models.F("ready_window_end"))
                ),
                name="parcels_delivery_ready_window",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(actual_weight_kg__isnull=True)
                    | (
                        models.Q(actual_weight_kg__gt=0)
                        & models.Q(actual_weight_kg__lte=100)
                    )
                ),
                name="parcels_delivery_weight_range",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(length_cm__isnull=True)
                    & models.Q(width_cm__isnull=True)
                    & models.Q(height_cm__isnull=True)
                )
                | (
                    models.Q(length_cm__gt=0, length_cm__lte=500)
                    & models.Q(width_cm__gt=0, width_cm__lte=500)
                    & models.Q(height_cm__gt=0, height_cm__lte=500)
                ),
                name="parcels_delivery_dimensions",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(schema_version=1)
                    | (
                        models.Q(description_is_accurate=True)
                        & models.Q(item_is_legal=True)
                        & models.Q(no_prohibited_goods=True)
                        & models.Q(declared_value_is_accurate=True)
                        & models.Q(customs_responsibilities_understood=True)
                    )
                ),
                name="parcels_delivery_v1_safety",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(schema_version=1)
                    | models.Q(base_amount_dzd__isnull=True)
                ),
                name="parcels_delivery_v1_no_dzd",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        ranking_boost_weight=0,
                        ranking_boost_expires_at__isnull=True,
                    )
                    | models.Q(
                        ranking_boost_weight__gt=0,
                        ranking_boost_expires_at__isnull=False,
                    )
                ),
                name="parcels_ranking_boost_pair",
            ),
        ]

    def clean(self):
        super().clean()
        if self.schema_version != 2:
            return
        errors = {}
        for field in ("origin", "destination", "weight_kg"):
            if getattr(self, f"{field}_id" if field != "weight_kg" else field) is not None:
                errors[field] = "Legacy route/weight fields must be empty for V1."
        for field in ("pickup_city", "delivery_city"):
            if getattr(self, field):
                errors[field] = "Legacy city fields must be empty for V1."
        for field in ("deadline_at", "title", "description", "category"):
            if not getattr(self, field):
                errors[field] = "This field is required for V1 delivery requests."
        for field in ("length_cm", "width_cm", "height_cm"):
            if getattr(self, field) is None:
                errors[field] = "This field is required for V1 delivery requests."
        if (
            self.ready_window_end is not None
            and self.deadline_at is not None
            and self.ready_window_end > self.deadline_at
        ):
            errors["deadline_at"] = "Deadline must not precede the ready-window end."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def is_ranking_boost_active(self, *, at=None) -> bool:
        at = at or timezone.now()
        return bool(
            self.ranking_boost_weight > 0
            and self.ranking_boost_expires_at is not None
            and self.ranking_boost_expires_at > at
        )


class ProductRequest(ParcelRequest):
    """Sender asks the traveler to BUY a product, then carry it.

    `product_price_dzd` is what the traveler will pay at the store. Sender
    pays price + base_fee + tiered commission (frozen on Offer).
    """

    product_url = models.URLField(blank=True, default="", max_length=500)
    store_name = models.CharField(max_length=120, blank=True, default="")
    product_price_dzd = models.PositiveIntegerField(
        validators=[MinValueValidator(100)],
        help_text="Item price in DZD; pricing engine derives commission.",
    )

    class Meta:
        db_table = "parcels_product"


class ParcelMedia(models.Model):
    """Photo (or future doc) attached to a parcel request.

    `object_key` references an object in MinIO/S3 — Django never stores
    binary bytes (ARCHITECTURE.md §9, §11).
    """

    parcel = models.ForeignKey(
        ParcelRequest, on_delete=models.CASCADE, related_name="media"
    )
    bucket = models.CharField(max_length=64)
    object_key = models.CharField(max_length=255)
    content_type = models.CharField(max_length=64, default="image/jpeg")
    bytes = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "parcels_media"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["parcel", "created_at"], name="parcels_media_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["bucket", "object_key"],
                name="parcels_media_unique_object",
            ),
        ]

    def __str__(self) -> str:
        return f"parcel#{self.parcel_id} {self.object_key}"
