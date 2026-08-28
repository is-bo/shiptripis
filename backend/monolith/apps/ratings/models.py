"""Bidirectional Deal ratings with a blind review window.

One rating per side per Deal, immutable once submitted, and invisible to the
counterparty until either both sides have submitted or the review window closes.
Immutability is what makes the blind window mean anything: if a rating could be
edited after the other side's became visible, "blind" would only describe the
first draft.

Visibility is computed, not merely stored. `revealed_at` is set by a durable
`rating_reveal` job so the state is queryable and auditable, and the serializers
independently recompute the same predicate, so a worker that has not run yet
cannot keep a rating hidden past its window or expose one early.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q


class Rating(models.Model):
    class RaterRole(models.TextChoices):
        SENDER = "sender", "Sender rating the traveler"
        TRAVELER = "traveler", "Traveler rating the sender"

    deal = models.ForeignKey(
        "deals.Deal",
        on_delete=models.PROTECT,
        related_name="ratings",
    )
    rater = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ratings_given",
    )
    ratee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ratings_received",
    )
    rater_role = models.CharField(max_length=10, choices=RaterRole.choices)
    score = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    tags = models.JSONField(default=list, blank=True)
    comment = models.TextField(blank=True, default="", max_length=4_000)

    #: The window this rating was submitted against, frozen from the Deal so a
    #: settings change cannot move a reveal date that a party was promised.
    review_window_ends_at = models.DateTimeField()
    revealed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ratings_rating"
        ordering = ["deal_id", "rater_role"]
        constraints = [
            models.UniqueConstraint(
                fields=["deal", "rater_role"],
                name="ratings_one_per_side_per_deal",
            ),
            models.CheckConstraint(
                condition=Q(score__gte=1) & Q(score__lte=5),
                name="ratings_score_range",
            ),
            models.CheckConstraint(
                condition=~Q(rater=F("ratee")),
                name="ratings_rater_neq_ratee",
            ),
        ]
        indexes = [
            models.Index(fields=["ratee", "-created_at"], name="ratings_ratee_idx"),
            models.Index(
                fields=["revealed_at", "review_window_ends_at"],
                name="ratings_reveal_idx",
            ),
        ]

    def save(self, *args, **kwargs):
        """Immutable except for the reveal flip.

        A rating is a statement made at a point in time under a blind window.
        Allowing it to be rewritten afterwards would let a party wait, read the
        other side once it appeared, and then restate their own.
        """

        if self.pk:
            allowed = {"revealed_at", "updated_at"}
            update_fields = kwargs.get("update_fields")
            if update_fields is None or set(update_fields) - allowed:
                raise ValidationError(
                    "Ratings are immutable; only the reveal flag may change."
                )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Ratings cannot be deleted.")

    def __str__(self) -> str:
        return f"Rating#{self.pk} deal={self.deal_id} {self.rater_role} {self.score}"
