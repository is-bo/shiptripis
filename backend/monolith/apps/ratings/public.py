"""The one rule for what the public may read of a member's ratings (spec 18).

Three questions, each answered in exactly one place:

**Does this rating count?** `countable` is the blind rule
(`apps.ratings.services.is_revealed`, written in SQL: the window frozen on the
row has passed, or both sides have rated) and "staff have not removed it".
Every public average, count and list is computed over `countable` and nothing
else: `rating_summaries` (the rating on every card, Find Travelers, ranking,
and the member's own Profile since L18A) and the reviews lists below. A rating
whose comment staff hid still counts; only its text goes.

**What does a review show?** `public_reviews` builds each review key by key:
the score, the tags, the comment (or `null` with `comment_removed: true`),
which side wrote it, the month, and whether the viewer reported it (always
`null` for a guest). Never the author's name, any member id, the deal or its
tracking number.

**May this viewer read this person's reviews?** `reviews_visible_to`: the
person has a visible public profile, owns a journey that is listed now, or
shares a match with the viewer. A trip's reviews have one more door,
`trip_reviews_access`: a sender coming from Find Travelers names their own open
request, and the matching engine's single-pair verdict decides (settled by the
advisor on 2026-11-14, plan L13A). A guest, a viewer without an account (plan
EGS, decision 10), takes the public paths only.
"""

from __future__ import annotations

from datetime import datetime

from django.db.models import (
    Avg,
    CharField,
    Count,
    Exists,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Value,
)

from .models import Rating, RatingModeration, RatingReport

#: `written_by` values: the side of the delivery the author was on.
WRITTEN_BY_SENDER = Rating.RaterRole.SENDER
WRITTEN_BY_TRAVELER = Rating.RaterRole.TRAVELER

#: Which ratings a person received in one role. "As a traveler" means the
#: ratings their senders wrote, which is what a trip card and Find Travelers
#: show; `None` is the whole person, as on a profile card.
SIDE_TRAVELER = "traveler"

#: Frozen rating states of a summary: `new` until one rating counts.
RATING_NEW = "new"
RATING_RATED = "rated"

#: What the reporter is told about their report (spec 18): "received" while
#: staff have not looked at it, then "reviewed", and nothing more.
REPORT_RECEIVED = "received"
REPORT_REVIEWED = "reviewed"


def countable(queryset: QuerySet, *, at: datetime) -> QuerySet:
    """The ratings that count: revealed, and not removed by staff.

    Both conditions are correlated `EXISTS` on the same query, so applying this
    to an aggregate costs no extra query.
    """

    counterpart = Rating.objects.filter(deal_id=OuterRef("deal_id")).exclude(
        rater_role=OuterRef("rater_role")
    )
    removed = RatingModeration.objects.filter(
        rating_id=OuterRef("pk"), state=RatingModeration.State.REMOVED
    )
    return (
        queryset.alias(
            counterpart_submitted=Exists(counterpart), staff_removed=Exists(removed)
        )
        .filter(Q(review_window_ends_at__lte=at) | Q(counterpart_submitted=True))
        .filter(staff_removed=False)
    )


def ratings_received(subject_user_id: int, *, side: str | None) -> QuerySet:
    """Every rating one person received, in one role or both (not yet narrowed)."""

    if side not in (SIDE_TRAVELER, None):
        raise ValueError(f"Unknown review side {side!r}.")
    queryset = Rating.objects.filter(ratee_id=subject_user_id)
    if side == SIDE_TRAVELER:
        queryset = queryset.filter(rater_role=Rating.RaterRole.SENDER)
    return queryset


def _summary(average, count: int) -> dict:
    if not count or average is None:
        return {"state": RATING_NEW, "average": None, "count": 0}
    # One decimal. A person with three ratings does not have a reputation
    # measured to four.
    return {"state": RATING_RATED, "average": round(float(average), 1), "count": count}


def rating_summaries(user_ids: list[int], *, at: datetime, side: str | None) -> dict[int, dict]:
    """The rating block of a card, `{state, average, count}`, for each person.

    The one average in the product: computed over `countable`, in one grouped
    query whatever the number of people. `side=SIDE_TRAVELER` counts only
    what senders wrote (a trip card, Find Travelers); `None` is the whole
    person (a profile card, the member's own Profile).
    """

    if not user_ids:
        return {}
    scope = Rating.objects.filter(ratee_id__in=user_ids)
    if side == SIDE_TRAVELER:
        scope = scope.filter(rater_role=Rating.RaterRole.SENDER)
    elif side is not None:
        raise ValueError(f"Unknown review side {side!r}.")
    rows = (
        countable(scope, at=at)
        .values("ratee_id")
        .annotate(average=Avg("score"), rated_count=Count("id"))
    )
    found = {row["ratee_id"]: (row["average"], row["rated_count"]) for row in rows}
    return {user_id: _summary(*found.get(user_id, (None, 0))) for user_id in user_ids}


def report_state(status: str | None) -> str | None:
    """The reporter's view of their report: `received`, `reviewed`, or `None`."""

    if not status:
        return None
    return REPORT_RECEIVED if status == RatingReport.Status.OPEN else REPORT_REVIEWED


def _review(rating: Rating) -> dict:
    hidden = rating.moderation_state == RatingModeration.State.COMMENT_HIDDEN
    comment = (rating.comment or "").strip()
    return {
        "id": rating.pk,
        "score": rating.score,
        "tags": list(rating.tags or []),
        "comment": None if hidden or not comment else comment,
        "comment_removed": hidden,
        "written_by": rating.rater_role,
        "month": rating.created_at.strftime("%Y-%m"),
        "my_report": report_state(rating.my_report_status),
    }


def public_reviews(
    subject_user_id: int,
    *,
    side: str | None,
    viewer_id: int | None,
    at: datetime,
    limit: int,
    offset: int,
) -> tuple[list[dict], int | None]:
    """One page of a person's countable reviews, newest first, and the next offset.

    One query whatever the page size: the moderation state and the viewer's own
    report are correlated subqueries on the page's own rows. A guest
    (`viewer_id` `None`) has reported nothing, so no report is looked up.
    """

    moderation = RatingModeration.objects.filter(rating_id=OuterRef("pk"))
    if viewer_id is None:
        my_report_status = Value(None, output_field=CharField())
    else:
        my_report_status = Subquery(
            RatingReport.objects.filter(
                rating_id=OuterRef("pk"), reporter_id=viewer_id
            ).values("status")[:1]
        )
    queryset = (
        countable(ratings_received(subject_user_id, side=side), at=at)
        .annotate(
            moderation_state=Subquery(moderation.values("state")[:1]),
            my_report_status=my_report_status,
        )
        .only("pk", "score", "tags", "comment", "rater_role", "created_at")
        .order_by("-created_at", "-pk")
    )
    rows = list(queryset[offset : offset + limit + 1])
    next_offset = offset + limit if len(rows) > limit else None
    return [_review(row) for row in rows[:limit]], next_offset


def shares_match(viewer_id: int, subject_user_id: int) -> bool:
    """Have these two members ever been the two sides of one match?"""

    from apps.matching.models import Match

    return Match.objects.filter(
        Q(sender_id=viewer_id, traveler_id=subject_user_id)
        | Q(sender_id=subject_user_id, traveler_id=viewer_id)
    ).exists()


def reviews_visible_to(
    viewer_id: int,
    subject_user_id: int,
    *,
    side: str | None,
    at: datetime,
    profiles_enabled: bool,
    listings_enabled: bool,
    sea_legs_enabled: bool,
) -> bool:
    """May this viewer read this person's reviews in this role?

    The person's whole record (`side=None`) is public through a visible
    profile. Their record as a traveler is also public while they own a
    journey that is listed now, and to anyone who shares a match with them.
    The switches are the caller's reading of the marketplace policy at the
    moment of the request; a switched-off path opens nothing.
    """

    from apps.discovery.listings import listable_journeys
    from apps.discovery.profiles import visible_profiles

    if viewer_id == subject_user_id:
        return True
    if profiles_enabled and visible_profiles().filter(user_id=subject_user_id).exists():
        return True
    if side != SIDE_TRAVELER:
        return False
    if (
        listings_enabled
        and listable_journeys(at=at, sea_legs_enabled=sea_legs_enabled)
        .filter(traveler_id=subject_user_id)
        .exists()
    ):
        return True
    return shares_match(viewer_id, subject_user_id)


#: `trip_reviews_access` answers.
ACCESS_OK = "ok"
ACCESS_DISABLED = "disabled"
ACCESS_NOT_FOUND = "not_found"


def _compatible_candidate(*, viewer_id: int, request_id: int, journey_id: int, at) -> bool:
    """Is this journey a Find Travelers candidate for the viewer's own open request?

    The verdict is the matching engine's (`explain_candidate`, the same
    single-pair evaluation "I can carry this" and Find Travelers use); nothing
    here decides compatibility.
    """

    from apps.matching.discovery import explain_candidate
    from apps.parcels.models import DeliveryRequest, ParcelRequest
    from apps.trips.models import Journey

    if not DeliveryRequest.objects.filter(
        pk=request_id,
        sender_id=viewer_id,
        kind=ParcelRequest.Kind.DELIVERY,
        status=ParcelRequest.Status.OPEN,
    ).exists():
        return False
    try:
        evaluation = explain_candidate(
            delivery_request_id=request_id, journey_id=journey_id, at=at
        )
    except (DeliveryRequest.DoesNotExist, Journey.DoesNotExist):
        return False
    return bool(evaluation.compatibility.compatible)


def trip_reviews_access(
    *,
    viewer_id: int | None,
    journey_id: int,
    request_id: int | None,
    at: datetime,
    listings_enabled: bool,
    sea_legs_enabled: bool,
) -> tuple[str, int | None]:
    """May this viewer read the reviews of this journey's traveler? `(answer, owner id)`.

    In order: the owner, and a viewer who shares a match with the owner,
    always may. A viewer naming their own open request (`request_id`, sent
    from Find Travelers) may when the matching engine finds the journey a
    compatible candidate, whatever the listings switch says; every failure of
    that path answers exactly as an unknown journey does, so it tells nothing
    about the pair or about the journey existing. Otherwise the public path:
    `disabled` while listings are off, and only a journey listed now passes.

    A guest (`viewer_id` `None`) owns nothing, shares no match and has no
    request, so only the public path is theirs; a guest naming a request is
    answered as an unknown journey.
    """

    from apps.discovery.listings import listable_journeys
    from apps.trips.models import Journey

    if viewer_id is None and request_id is not None:
        return ACCESS_NOT_FOUND, None
    owner_id = (
        Journey.objects.filter(pk=journey_id).values_list("traveler_id", flat=True).first()
    )
    if viewer_id is not None:
        if owner_id is not None and (
            owner_id == viewer_id or shares_match(viewer_id, owner_id)
        ):
            return ACCESS_OK, owner_id
        if request_id is not None:
            if owner_id is not None and _compatible_candidate(
                viewer_id=viewer_id, request_id=request_id, journey_id=journey_id, at=at
            ):
                return ACCESS_OK, owner_id
            return ACCESS_NOT_FOUND, None
    if not listings_enabled:
        return ACCESS_DISABLED, None
    if (
        owner_id is not None
        and listable_journeys(at=at, sea_legs_enabled=sea_legs_enabled)
        .filter(pk=journey_id)
        .exists()
    ):
        return ACCESS_OK, owner_id
    return ACCESS_NOT_FOUND, None
