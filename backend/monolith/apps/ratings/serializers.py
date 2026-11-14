"""Read and write contracts for Deal ratings.

Two rules shape everything here.

**Nothing in a request body decides who is rating whom.** The submit serializer
accepts a score, tags and a comment -- and that is the entire vocabulary. Rater,
ratee, role, deal and review window are derived from the locked Deal inside
`apps.ratings.services`, so there is no field a caller could add to rate on
somebody else's behalf or against a different Deal.

**Visibility is asked, never assumed.** `RatingSerializer.is_revealed` calls the
service predicate rather than reporting `revealed_at`. A rating whose window has
closed reads as revealed even if the durable job has not run yet, and a rating
whose window is open reads as blind even if a stamp somehow arrived early.
"""

from __future__ import annotations

from rest_framework import serializers

from .models import Rating, RatingReport
from .public import report_state
from .services import is_revealed


class RatingSubmitSerializer(serializers.Serializer):
    """One party's rating of the other.

    The bounds here are the cheap outer edge only. The authoritative rules --
    which tags exist and how long a comment may be -- live in the active
    Phase 4 revision and are applied by the service, because they are
    commercially tunable and a serializer compiled into the image is not.
    """

    score = serializers.IntegerField(min_value=1, max_value=5)
    tags = serializers.ListField(
        child=serializers.CharField(max_length=64, trim_whitespace=True),
        required=False,
        allow_empty=True,
        max_length=64,
    )
    comment = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=4_000,
        trim_whitespace=True,
    )


class RatingSerializer(serializers.ModelSerializer):
    """One rating row, as its rater or a revealed counterparty may read it.

    Callers should `select_related("deal")` (and, for a list, prefetch
    `deal__ratings`): the reveal predicate asks the Deal whether both sides are
    on file, and without those the flag costs a query per row.
    """

    is_revealed = serializers.SerializerMethodField()
    deal_id = serializers.IntegerField(read_only=True)
    rater_id = serializers.IntegerField(read_only=True)
    ratee_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Rating
        fields = (
            "id",
            "deal_id",
            "rater_id",
            "ratee_id",
            "rater_role",
            "score",
            "tags",
            "comment",
            "review_window_ends_at",
            "revealed_at",
            "is_revealed",
            "created_at",
        )
        read_only_fields = fields

    def get_is_revealed(self, obj: Rating) -> bool:
        return is_revealed(obj, deal=obj.deal, at=self.context.get("at"))


class MyRatingSerializer(RatingSerializer):
    """A rating the caller received, as "My ratings" lists it (L13A).

    `moderation` is staff's standing decision: `null`, `comment_hidden` (the
    public no longer reads the comment; the score still counts) or `removed`
    (not counted anywhere, shown here as "Removed by Wassla, not counted").
    The rated person keeps reading their own rating as written. `my_report` is
    their own report on it: `null`, `received` or `reviewed`.

    Reads the `moderation_state` and `my_report_status` annotations
    `apps.ratings.views.MyRatingsView` puts on the queryset.
    """

    moderation = serializers.CharField(source="moderation_state", allow_null=True)
    my_report = serializers.SerializerMethodField()

    class Meta(RatingSerializer.Meta):
        fields = (*RatingSerializer.Meta.fields, "moderation", "my_report")
        read_only_fields = fields

    def get_my_report(self, obj: Rating) -> str | None:
        return report_state(obj.my_report_status)


class ReportCreateSerializer(serializers.Serializer):
    """A member's report on one review (spec 18).

    `journey` and `request` are the Find Travelers context, sent only from a
    candidate's reviews: with them, a sender may report a traveler's review
    they reached through their own open request while public listings are off.
    """

    reason = serializers.ChoiceField(choices=RatingReport.Reason.choices)
    note = serializers.CharField(
        required=False, allow_blank=True, max_length=500, trim_whitespace=True
    )
    journey = serializers.IntegerField(min_value=1, required=False)
    request = serializers.IntegerField(min_value=1, required=False)

    def validate(self, attrs):
        if ("journey" in attrs) != ("request" in attrs):
            raise serializers.ValidationError(
                "Send both journey and request, or neither."
            )
        return attrs
