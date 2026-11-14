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


class RatingReport(models.Model):
    """One member's report that a review should not be shown (spec 18).

    A member reports a review once: `ratings_report_once` holds one row per
    review and reporter, and a second attempt answers the first one's state.
    The reporter is shown to staff only; the author is never told who
    reported, and the reporter only ever sees "received" then "reviewed".
    """

    class Reason(models.TextChoices):
        OFFENSIVE = "offensive", "Offensive"
        PERSONAL_INFORMATION = "personal_information", "Contains personal information"
        UNRELATED = "unrelated", "Not about this delivery"
        UNTRUE = "untrue", "Untrue"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        #: Staff looked and left the review as it was, or lifted a decision.
        DISMISSED = "dismissed", "Dismissed"
        #: Staff hid the comment or removed the rating.
        ACTIONED = "actioned", "Actioned"

    rating = models.ForeignKey(Rating, on_delete=models.PROTECT, related_name="reports")
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    reason = models.CharField(max_length=24, choices=Reason.choices)
    #: The reporter's own words. Staff read them; nobody else does.
    note = models.CharField(max_length=500, blank=True, default="")
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    #: Staff-internal, like every staff reason: never sent to a member.
    decision_reason = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ratings_report"
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["rating", "reporter"], name="ratings_report_once"
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="open", decided_at__isnull=True)
                    | (~Q(status="open") & Q(decided_at__isnull=False))
                ),
                name="ratings_report_decided_when_closed",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "created_at"], name="ratings_report_queue_idx"),
        ]

    def __str__(self) -> str:
        return f"RatingReport#{self.pk} rating={self.rating_id} {self.status}"


class RatingModeration(models.Model):
    """Staff's standing decision about one review (spec 18).

    At most one per rating. `comment_hidden` keeps the score and tags counted
    and replaces the text with "Comment removed by Wassla"; `removed` takes the
    rating out of every public average, count and list. Lifting a decision
    deletes this row: the rating itself is never edited, and the history of
    decisions is the audit log.
    """

    class State(models.TextChoices):
        COMMENT_HIDDEN = "comment_hidden", "Comment hidden"
        REMOVED = "removed", "Rating removed"

    rating = models.OneToOneField(
        Rating, on_delete=models.PROTECT, related_name="moderation"
    )
    state = models.CharField(max_length=16, choices=State.choices)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    decided_at = models.DateTimeField()
    #: Staff-internal: recorded here and in the audit log, never shown to a member.
    reason = models.CharField(max_length=500)

    class Meta:
        db_table = "ratings_moderation"

    def __str__(self) -> str:
        return f"RatingModeration rating={self.rating_id} {self.state}"
