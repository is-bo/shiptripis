"""Sender boosts: the J2 reward intent, and the retired paid package.

One rule outranks everything else here and survives both models:

    a boost changes where a compatible request appears in a list.
    It never makes an incompatible request compatible.

That is structural rather than a convention. `apps.matching.ranking` raises if
asked to rank a candidate that failed compatibility, and nothing in this app
touches KYC, capacity, route eligibility, timing, safety or verification -- the
only columns a boost ever writes on a request are `boost_eur_cents` and the two
ranking fields.

**J2 Boost** is not a product the sender buys. It is extra reward they attach
to their own request: a plain EUR-cent amount on `DeliveryRequest`, editable
while the request is unmatched, carrying no timer and no expiry of its own. It
is frozen into the Deal's terms at the commitment boundary and collected inside
the Deal balance, so it refunds, settles and reconciles as part of the reward it
belongs to. `BoostIntentEvent` is its append-only audit trail.

**`BoostPurchase` is the retired J1-era paid visibility package.** No new row is
ever written: `purchase_boost` is gone and the endpoint answers 410. Existing
rows stay exactly as they were sold -- amount, split, package, duration, weight
and settings version -- because a settled payment's terms are not something a
later product decision gets to reinterpret. Any still-active row keeps its
ranking effect until it expires, and a payment already in flight when J2 shipped
still reconciles through `activate_paid_boost`.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


class BoostPurchase(models.Model):
    """One retired J1-era paid visibility and delivery-earnings commitment.

    Historical only. See the module docstring: nothing writes a new row.
    """

    class EconomicsVersion(models.TextChoices):
        LEGACY_VISIBILITY_ONLY = "visibility_only", "Legacy visibility only"
        TRAVELER_SPLIT_V1 = "traveler_split_v1", "Traveler split V1"

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
    deal = models.ForeignKey(
        "deals.Deal",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="boost_purchases",
        help_text="The Deal whose Traveler earns this boost allocation.",
    )

    package_code = models.CharField(max_length=32, db_index=True)
    #: The visibility package exactly as committed. A later settings revision
    #: may change or withdraw it; this row keeps what the buyer was promised.
    package_snapshot = models.JSONField(default=dict, blank=True)
    duration_seconds = models.PositiveIntegerField()
    amount_eur_cents = models.PositiveBigIntegerField()
    ranking_weight = models.PositiveSmallIntegerField()
    economics_version = models.CharField(
        max_length=24,
        choices=EconomicsVersion.choices,
        default=EconomicsVersion.TRAVELER_SPLIT_V1,
    )
    traveler_share_bps = models.PositiveSmallIntegerField(default=0)
    traveler_boost_eur_cents = models.PositiveBigIntegerField(default=0)
    platform_boost_eur_cents = models.PositiveBigIntegerField(default=0)
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
                condition=Q(amount_eur_cents__gt=0),
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
            models.CheckConstraint(
                condition=(
                    Q(economics_version="visibility_only")
                    | (
                        Q(traveler_share_bps__gte=5_001)
                        & Q(traveler_share_bps__lte=9_999)
                        & Q(
                            amount_eur_cents=models.F("traveler_boost_eur_cents")
                            + models.F("platform_boost_eur_cents")
                        )
                    )
                ),
                name="boosts_economic_split_consistent",
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


class BoostIntentEvent(models.Model):
    """Append-only record of every change to a request's Boost amount.

    Boost is money the sender commits to, and it moves without a payment of its
    own, so "what was it, when, and who changed it" cannot live only in the
    column's current value. Every write goes through
    `apps.boosts.services.set_boost_intent`, which appends one row here inside
    the same transaction as the column update.

    Rows are never updated and never deleted. A correction is a new row.
    """

    class Reason(models.TextChoices):
        SENDER_SET = "sender_set", "Sender set the boost"
        SENDER_INCREASED = "sender_increased", "Sender increased the boost"
        SENDER_DECREASED = "sender_decreased", "Sender decreased the boost"
        SENDER_REMOVED = "sender_removed", "Sender removed the boost"
        FROZEN_INTO_DEAL = "frozen_into_deal", "Frozen into a committed Deal"
        CONSUMED_BY_FUNDING = "consumed_by_funding", "Consumed by Deal funding"
        RELEASED_WITH_RESERVATION = (
            "released_with_reservation",
            "Revived with an unfunded reservation release",
        )
        REQUEST_CLOSED = "request_closed", "Request cancelled or expired"

    delivery_request = models.ForeignKey(
        "parcels.DeliveryRequest",
        on_delete=models.PROTECT,
        related_name="boost_intent_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="boost_intent_events",
        help_text="Null when the platform moved the amount, not a person.",
    )
    deal = models.ForeignKey(
        "deals.Deal",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="boost_intent_events",
    )
    reason = models.CharField(max_length=32, choices=Reason.choices)
    previous_eur_cents = models.PositiveBigIntegerField()
    amount_eur_cents = models.PositiveBigIntegerField()
    commission_rate_bps = models.PositiveSmallIntegerField(default=0)
    ranking_weight = models.PositiveSmallIntegerField(default=0)
    business_settings_version = models.ForeignKey(
        "core.BusinessSettingsVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="boost_intent_events",
    )
    request_status = models.CharField(max_length=16, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "boosts_intent_event"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(commission_rate_bps__lte=10_000),
                name="boosts_intent_commission_bps",
            ),
        ]
        indexes = [
            models.Index(
                fields=["delivery_request", "-created_at"],
                name="boosts_intent_request_idx",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Boost intent events are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Boost intent events are append-only.")

    def __str__(self) -> str:
        return (
            f"BoostIntent#{self.pk} request={self.delivery_request_id} "
            f"{self.previous_eur_cents}c -> {self.amount_eur_cents}c ({self.reason})"
        )
