"""Operations view over Deal ratings.

Registered with no add, no change and no delete, and that is not merely a
convention here: the model refuses every field change except the reveal flip and
refuses deletion outright, so an editable admin would offer operators actions
the database would then reject.

The list makes the blind gate legible rather than leaving it to be inferred.
`Revealed?` is the computed predicate -- both sides submitted, or the frozen
window has passed -- next to the stored `revealed_at` stamp, so an operator
looking at a support ticket can see at a glance whether a party can actually
read a rating and whether the durable job has caught up yet.
"""

from __future__ import annotations

from django.contrib import admin

from .models import Rating
from .services import is_revealed


@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "deal",
        "rater_role",
        "rater",
        "ratee",
        "score",
        "review_window_ends_at",
        "revealed_at",
        "revealed_display",
        "created_at",
    )
    list_filter = ("rater_role", "score", "created_at")
    search_fields = ("deal__id", "rater__email", "ratee__email", "comment")
    date_hierarchy = "created_at"
    list_select_related = ("deal", "rater", "ratee")
    fields = (
        "deal",
        "rater",
        "ratee",
        "rater_role",
        "score",
        "tags",
        "comment",
        "review_window_ends_at",
        "revealed_at",
        "revealed_display",
        "created_at",
        "updated_at",
    )
    readonly_fields = fields

    def has_add_permission(self, request):  # noqa: ARG002
        return False

    def has_change_permission(self, request, obj=None):  # noqa: ARG002
        return False

    def has_delete_permission(self, request, obj=None):  # noqa: ARG002
        return False

    @admin.display(boolean=True, description="Revealed?")
    def revealed_display(self, obj: Rating) -> bool:
        """The predicate the parties are actually served, not the stamp."""

        return is_revealed(obj, deal=obj.deal)
