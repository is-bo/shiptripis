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

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

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
        Airport, on_delete=models.PROTECT, related_name="parcels_from"
    )
    destination = models.ForeignKey(
        Airport, on_delete=models.PROTECT, related_name="parcels_to"
    )
    pickup_city = models.CharField(max_length=80, blank=True, default="")
    delivery_city = models.CharField(max_length=80, blank=True, default="")

    weight_kg = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
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
        return f"#{self.id} {self.kind} {self.origin_id}→{self.destination_id}"


class DeliveryRequest(ParcelRequest):
    """Sender already owns the item; offers a base amount, traveler keeps 75%.

    `base_amount_dzd` is the **sender-proposed** payout to the traveler before
    the 25% commission is added on top (CLAUDE.md §6). Final numbers are
    frozen on the Offer row when accepted.
    """

    base_amount_dzd = models.PositiveIntegerField(
        validators=[MinValueValidator(100)],
        help_text="Proposed payout to traveler in DZD (commission added on Offer).",
    )

    class Meta:
        db_table = "parcels_delivery"


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
