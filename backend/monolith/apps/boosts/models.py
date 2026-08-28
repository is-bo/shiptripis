"""Paid sender boosts.

Phase 2 built the ranking hook (`DeliveryRequest.ranking_boost_weight` and a
capped points bonus applied *after* hard compatibility). Phase 3 reserved
`PaymentOrder.Purpose.BOOST`. This is the product that joins them, and the one
rule that outranks everything else about it:

    a boost changes where a compatible request appears in a list.
    It never makes an incompatible request compatible.

That is structural rather than a convention. `apps.matching.ranking` raises if
asked to rank a candidate that failed compatibility, and nothing here touches
KYC, capacity, route eligibility, timing, safety or verification -- the only
columns a purchase ever writes on the request are the two ranking fields.

Activation is driven by the authoritative payment, never by the client's return
from a checkout page: `apps.finance.services.reconcile_attempt` calls the
activation service when a BOOST order becomes `paid`.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class BoostPurchase(models.Model):
    """One purchase of one admin-configured package for one delivery request."""

    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", "Pending payment"
        ACTIVE = "active", "Active"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled before payment"
        #: Paid, but the request was no longer boostable when the money landed.
        UNUSABLE = "unusable", "Paid but unusable"
        REFUNDED = "refunded", "Refunded"

    #: Statuses that still occupy a slot against `max_active_per_request`.
    OCCUPYING_STATUSES = ("pending_payment", "active")

    public_reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    delivery_request = models.ForeignKey(
        "parcels.DeliveryRequest",
        on_delete=models.PROTECT,
        related_name="boost_purchases",
    )
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="boost_purchases",
        help_text="Always the delivery request's own sender.",
    )
    payment_order = models.OneToOneField(
        "finance.PaymentOrder",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="boost_purchase",
    )

    package_code = models.CharField(max_length=32, db_index=True)
    #: The package exactly as it was priced at purchase. A later settings
    #: revision may reprice or withdraw the package; this row keeps what the
    #: buyer was actually quoted.
    package_snapshot = models.JSONField(default=dict, blank=True)
    duration_seconds = models.PositiveIntegerField()
    price_eur_cents = models.PositiveBigIntegerField()
    ranking_weight = models.PositiveSmallIntegerField()
    business_settings_version = models.ForeignKey(
        "core.BusinessSettingsVersion",
        on_delete=models.PROTECT,
        related_name="boost_purchases",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING_PAYMENT,
        db_index=True,
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    disposition_reason = models.CharField(max_length=64, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "boosts_purchase"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(price_eur_cents__gt=0),
                name="boosts_price_positive",
            ),
            models.CheckConstraint(
                condition=Q(duration_seconds__gt=0),
                name="boosts_duration_positive",
            ),
            models.CheckConstraint(
                condition=Q(ranking_weight__gt=0),
                name="boosts_weight_positive",
            ),
            # An active boost states when it started and when it ends. Without
            # this a bug could leave a boost with no expiry, which the ranking
            # hook would treat as permanently boosted.
            models.CheckConstraint(
                condition=(
                    ~Q(status="active")
                    | (Q(activated_at__isnull=False) & Q(expires_at__isnull=False))
                ),
                name="boosts_active_requires_window",
            ),
        ]
        indexes = [
            models.Index(
                fields=["delivery_request", "-created_at"], name="boosts_request_idx"
            ),
            models.Index(fields=["status", "expires_at"], name="boosts_expiry_idx"),
            models.Index(fields=["buyer", "-created_at"], name="boosts_buyer_idx"),
        ]

    def is_active(self, *, at=None) -> bool:
        at = at or timezone.now()
        return bool(
            self.status == self.Status.ACTIVE
            and self.expires_at is not None
            and self.expires_at > at
        )

    def __str__(self) -> str:
        return (
            f"BoostPurchase#{self.pk} request={self.delivery_request_id} "
            f"{self.package_code} ({self.status})"
        )
