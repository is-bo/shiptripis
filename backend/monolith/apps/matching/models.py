"""Matching schema — Match + Offer chain.

Per ARCHITECTURE.md §11 + CLAUDE.md §6:

- A Match links one ParcelRequest to one Trip. Multiple Matches per parcel
  are fine (the sender shops around) until one Match's Offer is accepted.
- An Offer is a price proposal on a Match. Offers form a counter chain via
  `parent_offer` (each side counters the previous one). The first Offer
  is created by the **traveler** when they apply to carry the parcel.
- Pricing is FROZEN on the Offer row at creation. `commission_dzd`,
  `base_fee_dzd`, `total_dzd` come from `apps.core.pricing` and are never
  recomputed. If platform rates change, in-flight offers settle at their
  frozen rates.

Status machines:

  Match:   pending → accepted → ... → completed | cancelled | expired

  Offer:   pending  → countered (a child Offer takes over)
                   → accepted   (terminal — also moves Match to accepted)
                   → declined   (terminal)
                   → withdrawn  (proposer cancels before counterparty acts)
                   → expired    (TTL lapsed)

Only the side that DID NOT propose the current Offer can act on it
(accept / decline / counter). The proposer can withdraw it.

A Match has at most ONE accepted Offer. Enforced at the DB level via a
partial unique index.
"""

from __future__ import annotations

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.parcels.models import ParcelRequest
from apps.trips.models import Trip


class Match(models.Model):
    """Sender's parcel paired with a traveler's trip."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        IN_TRANSIT = "in_transit", "In transit"
        DELIVERED = "delivered", "Delivered"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    parcel = models.ForeignKey(
        ParcelRequest, on_delete=models.PROTECT, related_name="matches"
    )
    trip = models.ForeignKey(
        Trip, on_delete=models.PROTECT, related_name="matches"
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="matches_as_sender",
    )
    traveler = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="matches_as_traveler",
    )

    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "matching_match"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["parcel", "status"], name="match_parcel_status_idx"),
            models.Index(fields=["trip", "status"], name="match_trip_status_idx"),
            models.Index(fields=["sender", "-created_at"], name="match_sender_idx"),
            models.Index(fields=["traveler", "-created_at"], name="match_traveler_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["parcel", "trip"],
                condition=models.Q(status="pending"),
                name="match_unique_pending_pair",
            ),
        ]

    def __str__(self) -> str:
        return f"Match#{self.id} parcel={self.parcel_id} trip={self.trip_id} ({self.status})"


class Offer(models.Model):
    """A price proposal on a Match — frozen pricing at creation."""

    class ProposedBy(models.TextChoices):
        TRAVELER = "traveler", "Traveler"
        SENDER = "sender", "Sender"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COUNTERED = "countered", "Countered"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"
        WITHDRAWN = "withdrawn", "Withdrawn"
        EXPIRED = "expired", "Expired"

    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="offers")
    parent_offer = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="counter_child",
        help_text="Previous offer this one counters; null for the first offer.",
    )

    proposed_by = models.CharField(max_length=10, choices=ProposedBy.choices)
    proposer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="offers_proposed",
        help_text="The user who created this offer (matches `proposed_by` side).",
    )

    # Frozen pricing — written once at creation, never updated.
    base_amount_dzd = models.PositiveIntegerField(
        validators=[MinValueValidator(0)],
        default=0,
        help_text=(
            "Delivery: traveler's payout. "
            "Product: product price the traveler will pay at the store."
        ),
    )
    base_fee_dzd = models.PositiveIntegerField(
        validators=[MinValueValidator(0)],
        default=0,
        help_text="Platform base fee (product=2,500; delivery=0).",
    )
    commission_dzd = models.PositiveIntegerField(
        validators=[MinValueValidator(0)], default=0
    )
    total_dzd = models.PositiveIntegerField(
        validators=[MinValueValidator(0)],
        default=0,
        help_text="What the sender pays. Frozen at creation.",
    )

    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True
    )

    note = models.TextField(blank=True, default="", max_length=1000)
    expires_at = models.DateTimeField(null=True, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "matching_offer"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["match", "-created_at"], name="offer_match_idx"),
            models.Index(fields=["status"], name="offer_status_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["match"],
                condition=models.Q(status="accepted"),
                name="offer_one_accepted_per_match",
            ),
            models.UniqueConstraint(
                fields=["match"],
                condition=models.Q(status="pending"),
                name="offer_one_pending_per_match",
            ),
        ]

    def __str__(self) -> str:
        return f"Offer#{self.id} match={self.match_id} by={self.proposed_by} ({self.status})"


class MatchEvent(models.Model):
    """Append-only audit log for a Match's lifecycle."""

    class Kind(models.TextChoices):
        MATCH_CREATED = "match_created", "Match created"
        OFFER_CREATED = "offer_created", "Offer created"
        OFFER_COUNTERED = "offer_countered", "Offer countered"
        OFFER_ACCEPTED = "offer_accepted", "Offer accepted"
        OFFER_DECLINED = "offer_declined", "Offer declined"
        OFFER_WITHDRAWN = "offer_withdrawn", "Offer withdrawn"
        OFFER_EXPIRED = "offer_expired", "Offer expired"
        MATCH_CANCELLED = "match_cancelled", "Match cancelled"
        MATCH_IN_TRANSIT = "match_in_transit", "Match in transit"
        MATCH_COMPLETED = "match_completed", "Match completed"

    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="events")
    offer = models.ForeignKey(
        Offer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    kind = models.CharField(max_length=24, choices=Kind.choices)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "matching_event"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["match", "-created_at"], name="match_event_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.kind} match={self.match_id}"
