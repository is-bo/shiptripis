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

from .models import Rating
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
