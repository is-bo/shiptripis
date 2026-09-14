"""Bidirectional Deal ratings: submission, the blind window and the reveal.

Three rules make the blind window mean something, and each is enforced in a
different place on purpose.

**Who may rate is derived from the Deal, never from the request.** The sender
rates the traveler and the traveler rates the sender; the role, the rater and
the ratee are all read off the locked Deal row. A guest who paid the order, the
parcel's recipient and every unrelated user are refused before any state is
inspected, so there is no body a caller can post that makes them a party.

**A rating is one statement, made once.** `ratings_one_per_side_per_deal` holds
one row per side per Deal and the model refuses every field change except the
reveal flip. Checking for an existing row first is a courtesy that produces a
readable error; the constraint is what makes a second rating impossible rather
than unlikely.

**Visibility is computed, not stored.** `is_revealed` is the predicate -- both
sides submitted, or the frozen review window has passed -- and everything that
displays a rating asks it. `revealed_at` exists so the state is queryable and
auditable, and the durable `rating_reveal` job stamps it, but a worker that has
not run yet cannot keep a rating hidden past its window, and one that runs early
cannot expose a rating whose window is still open.

The window a row is judged against is copied onto the row at submission
(`review_window_ends_at`) rather than read from live settings: a revision that
lengthens the review window tomorrow must not move a reveal date both parties
were already promised today.
"""

from __future__ import annotations

import logging
from datetime import datetime

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.core.financial_locks import lock_deal_lifecycle
from apps.core.phase4_policy import RatingPolicy, phase4_policy
from apps.deals import lifecycle
from apps.deals.models import Deal, DealEvent

from .models import Rating

logger = logging.getLogger(__name__)


class RatingError(RuntimeError):
    """A rating operation was refused. Carries a stable machine code."""

    code = "rating_error"

    def __init__(self, message: str, *, code: str | None = None, **details):
        super().__init__(message)
        if code:
            self.code = code
        self._details = details

    def details(self) -> dict:
        return dict(self._details)


class NotAuthorized(RatingError):
    code = "not_authorized"


#: Deal statuses in which a delivery has been confirmed and the parties may
#: still speak about it. `disputed` and `partially_refunded` are deliberately
#: included: a delivery that went wrong is exactly the one whose rating is worth
#: reading, and excluding them would bias the record upwards.
RATABLE_STATUSES = (
    Deal.Status.DELIVERY_CONFIRMED,
    Deal.Status.PROTECTION_WINDOW,
    Deal.Status.COMPLETED,
    Deal.Status.DISPUTED,
    Deal.Status.PARTIALLY_REFUNDED,
)

_OTHER_ROLE = {
    Rating.RaterRole.SENDER: Rating.RaterRole.TRAVELER,
    Rating.RaterRole.TRAVELER: Rating.RaterRole.SENDER,
}


# --- input hygiene ------------------------------------------------------------


def _clean_score(score: object) -> int:
    """1..5, an integer, and nothing that merely looks like one.

    `True` is an `int` in Python and would otherwise be stored as a score of 1.
    """

    if isinstance(score, bool) or not isinstance(score, int):
        raise RatingError(
            "A rating score must be a whole number from 1 to 5.",
            code="rating_score_invalid",
        )
    if not 1 <= score <= 5:
        raise RatingError(
            "A rating score must be between 1 and 5.",
            code="rating_score_invalid",
            score=score,
        )
    return score


def _clean_tags(tags: object, *, policy: RatingPolicy) -> list[str]:
    """Only tags the active revision offers, de-duplicated, order preserved.

    Tags are meant to be aggregated across a user's whole history, so a
    free-text tag would become a permanent one-off category that nothing can
    ever roll up. An unknown tag is refused rather than silently dropped: the
    client and the server have to agree about what was recorded.
    """

    if tags is None:
        return []
    if not isinstance(tags, (list, tuple)):
        raise RatingError("Rating tags must be a list.", code="rating_tag_invalid")
    allowed = set(policy.allowed_tags)
    cleaned: list[str] = []
    for raw in tags:
        tag = raw.strip() if isinstance(raw, str) else ""
        if tag not in allowed:
            raise RatingError(
                "That rating tag is not offered.",
                code="rating_tag_invalid",
                tag=str(raw)[:64],
                allowed_tags=list(policy.allowed_tags),
            )
        if tag not in cleaned:
            cleaned.append(tag)
    return cleaned


# --- deal-derived facts -------------------------------------------------------


def _party_role(deal: Deal, actor_id: int) -> tuple[str, int, int]:
    """`(role, rater_id, ratee_id)` for a party, or `NotAuthorized`.

    Everything a rating records about identity comes from here. Nothing in a
    request body can name a rater, a ratee or a role.
    """

    if actor_id == deal.sender_id:
        return Rating.RaterRole.SENDER, deal.sender_id, deal.traveler_id
    if actor_id == deal.traveler_id:
        return Rating.RaterRole.TRAVELER, deal.traveler_id, deal.sender_id
    raise NotAuthorized(
        "Only the sender and the traveler of this delivery may rate it."
    )


def _window_end(deal: Deal) -> datetime | None:
    """The instant this Deal's review window closes.

    Normally the column `apply_delivery_confirmed` stored. A Deal confirmed
    before that column was populated falls back to its own frozen lifecycle
    policy, so an old row still has a computable window rather than an
    open-ended one.
    """

    if deal.rating_window_ends_at is not None:
        return deal.rating_window_ends_at
    if deal.delivery_confirmed_at is None:
        return None
    return deal.delivery_confirmed_at + lifecycle.rating_window(deal)


def with_review_deadline(queryset):
    """SQL equivalent of the frozen deadline, including pre-column Deals."""
    from datetime import timedelta
    from django.db.models import BigIntegerField, Case, CharField, DateTimeField, ExpressionWrapper, F, JSONField, Value, When
    from django.db.models.fields.json import KeyTextTransform
    from django.db.models.functions import Cast, Coalesce

    key = "rating_review_window_seconds"
    parsed = Case(
        When(**{f"lifecycle_policy__{key}__regex": r"^[0-9]{1,10}$"},
             then=Cast(KeyTextTransform(key, "lifecycle_policy"), BigIntegerField())),
        default=Value(None), output_field=BigIntegerField(),
    )
    # JSON numbers only: a numeric string or bool is not a policy integer.
    seconds = Case(
        When(**{f"lifecycle_policy__{key}": Cast(Cast(parsed, CharField()), JSONField())}, then=parsed),
        default=Value(1_209_600), output_field=BigIntegerField(),
    )
    legacy = ExpressionWrapper(F("delivery_confirmed_at") + seconds * Value(timedelta(seconds=1)),
                               output_field=DateTimeField())
    return queryset.alias(review_deadline=Coalesce("rating_window_ends_at", legacy))


def _assert_window_open(deal: Deal, *, at: datetime) -> datetime:
    """The state gate, returning the window the new row is frozen against."""

    if deal.delivery_confirmed_at is None or deal.status not in RATABLE_STATUSES:
        raise RatingError(
            "This delivery cannot be rated yet.",
            code="rating_not_available",
            deal_status=deal.status,
        )
    window_end = _window_end(deal)
    if window_end is None or at >= window_end:
        raise RatingError(
            "The review window for this delivery has closed.",
            code="rating_window_closed",
            review_window_ends_at=window_end.isoformat() if window_end else None,
        )
    return window_end


# --- the blind predicate ------------------------------------------------------


def _both_sides_submitted(deal: Deal) -> bool:
    """Are both roles on file for this Deal?

    Reads through the related manager rather than issuing its own query, so a
    caller that prefetched `ratings` pays nothing extra and a caller that did
    not still gets the right answer.
    """

    return len({row.rater_role for row in deal.ratings.all()}) >= 2


def is_revealed(rating: Rating, *, deal: Deal, at: datetime | None = None) -> bool:
    """Is this rating visible to the counterparty?

    The whole blind rule in one place: both sides have spoken, or the window
    frozen onto this row when it was written has passed. `revealed_at` is not
    consulted, which is the point -- the stamp records that the job ran, it does
    not decide what a party may see.
    """

    at = at or timezone.now()
    window_end = rating.review_window_ends_at
    if window_end is not None and at >= window_end:
        return True
    return _both_sides_submitted(deal)


def _reveal(rows, *, deal: Deal, at: datetime, reason: str) -> int:
    """Stamp `revealed_at` on the rows not stamped yet. Idempotent.

    The model forbids changing any field after creation except this one, so the
    save names exactly those fields; a wider `update_fields` would be refused.
    """

    pending = [row for row in rows if row.revealed_at is None]
    for row in pending:
        row.revealed_at = at
        row.save(update_fields=["revealed_at", "updated_at"])
    if pending:
        lifecycle.record_event(
            deal,
            DealEvent.Kind.RATING_REVEALED,
            {"reason": reason, "rating_ids": [row.pk for row in pending]},
        )
    return len(pending)


# --- submission ---------------------------------------------------------------


def submit_rating(
    *,
    deal_id: int,
    actor_id: int,
    score: int,
    tags: list[str] | None = None,
    comment: str = "",
) -> Rating:
    """Record one party's rating of the other, once, under the Deal lock.

    Enters through `lock_deal_lifecycle` like every other Phase 4 writer, so a
    rating arriving at the same instant as a dispute, a protection expiry or a
    cancellation queues behind it and then reads committed state.

    When this is the second side, both rows are revealed inside the same
    transaction. There is no interleaving in which one party can read the
    other's rating while their own is still unwritten.
    """

    policy = phase4_policy().ratings
    # Validated before any row is locked: a malformed payload is a client bug,
    # and it should not make two parties queue behind a lifecycle lock.
    score = _clean_score(score)
    cleaned_tags = _clean_tags(tags, policy=policy)
    cleaned_comment = (comment or "").strip()[: policy.max_comment_length]

    with transaction.atomic():
        aggregate = lock_deal_lifecycle(deal_id)
        deal = aggregate.deal
        role, rater_id, ratee_id = _party_role(deal, actor_id)
        at = timezone.now()
        window_end = _assert_window_open(deal, at=at)

        existing = {row.rater_role: row for row in aggregate.ratings}
        if role in existing:
            raise RatingError(
                "You have already rated this delivery.",
                code="rating_already_submitted",
                rating_id=existing[role].pk,
            )

        try:
            with transaction.atomic():
                rating = Rating.objects.create(
                    deal=deal,
                    rater_id=rater_id,
                    ratee_id=ratee_id,
                    rater_role=role,
                    score=score,
                    tags=cleaned_tags,
                    comment=cleaned_comment,
                    review_window_ends_at=window_end,
                )
        except IntegrityError as exc:
            # `ratings_one_per_side_per_deal` fired. Only reachable from a
            # writer that did not take the lifecycle lock, which is exactly the
            # case the constraint exists for.
            raise RatingError(
                "You have already rated this delivery.",
                code="rating_already_submitted",
            ) from exc

        lifecycle.record_event(
            deal,
            DealEvent.Kind.RATING_SUBMITTED,
            # The score is deliberately absent. Both parties read this timeline,
            # and a payload carrying the score would publish through the
            # timeline exactly what the blind window withholds.
            {"rater_role": role, "rating_id": rating.pk},
            actor_id=actor_id,
        )

        counterpart = existing.get(_OTHER_ROLE[role])
        if counterpart is not None:
            _reveal(
                [counterpart, rating],
                deal=deal,
                at=at,
                reason="both_sides_submitted",
            )
    return rating


def reveal_ratings_for_deal(*, deal_id: int, at: datetime | None = None) -> str:
    """Stamp every rating on one Deal that the predicate already makes visible.

    Called by the durable `rating_reveal` job when the window closes, and safe
    to call at any other moment: it stamps nothing the predicate would not
    already show, so an early run is a no-op rather than a disclosure.
    """

    at = at or timezone.now()
    with transaction.atomic():
        aggregate = lock_deal_lifecycle(deal_id)
        deal = aggregate.deal
        rows = list(aggregate.ratings)
        if not rows:
            return "no_ratings"
        due = [row for row in rows if is_revealed(row, deal=deal, at=at)]
        if not due:
            return "not_due"
        count = _reveal(due, deal=deal, at=at, reason="review_window_closed")
    return f"revealed={count}" if count else "already_revealed"


# --- read model ---------------------------------------------------------------


def _projection(rating: Rating, *, revealed: bool, viewer_id: int) -> dict:
    return {
        "id": rating.pk,
        "rater_role": rating.rater_role,
        "rater_id": rating.rater_id,
        "ratee_id": rating.ratee_id,
        "score": rating.score,
        "tags": list(rating.tags or []),
        "comment": rating.comment,
        "review_window_ends_at": rating.review_window_ends_at,
        "revealed_at": rating.revealed_at,
        "is_revealed": revealed,
        "is_mine": rating.rater_id == viewer_id,
        "created_at": rating.created_at,
    }


def rating_state(
    *,
    deal: Deal,
    viewer_id: int,
    is_staff: bool = False,
    at: datetime | None = None,
) -> dict:
    """What one viewer may know about this Deal's ratings.

    A rating appears in `ratings` only when the predicate reveals it, when the
    viewer wrote it, or when the viewer is staff. Nothing else is projected --
    no redacted score, no truncated comment -- because a hidden rating that
    ships half its content is not blind.

    `counterparty_submitted` is content-free and stays useful: it is what the
    client's "waiting for their review" state is built from, and it says nothing
    about what the other side wrote.
    """

    at = at or timezone.now()
    policy = phase4_policy().ratings
    rows = list(deal.ratings.all())
    by_role = {row.rater_role: row for row in rows}

    viewer_role = None
    if viewer_id == deal.sender_id:
        viewer_role = Rating.RaterRole.SENDER
    elif viewer_id == deal.traveler_id:
        viewer_role = Rating.RaterRole.TRAVELER

    window_end = _window_end(deal)
    window_open = bool(
        deal.delivery_confirmed_at is not None
        and deal.status in RATABLE_STATUSES
        and window_end is not None
        and at < window_end
    )
    mine = by_role.get(viewer_role) if viewer_role else None
    counterpart = by_role.get(_OTHER_ROLE[viewer_role]) if viewer_role else None

    visible = []
    for row in rows:
        revealed = is_revealed(row, deal=deal, at=at)
        if not (revealed or is_staff or row.rater_id == viewer_id):
            continue
        visible.append(_projection(row, revealed=revealed, viewer_id=viewer_id))

    return {
        "deal_id": deal.pk,
        "deal_status": deal.status,
        "viewer_role": viewer_role,
        "review_window_ends_at": window_end,
        "window_open": window_open,
        "can_rate": bool(viewer_role is not None and window_open and mine is None),
        "submitted": mine is not None,
        "state": (
            "revealed" if mine is not None and is_revealed(mine, deal=deal, at=at)
            else "submitted_waiting" if mine is not None
            else "available" if viewer_role and window_open
            else "expired" if window_end and at >= window_end
            else "unavailable"
        ),
        "counterparty_submitted": (
            counterpart is not None if viewer_role else len(by_role) >= 2
        ),
        "both_sides_submitted": len(by_role) >= 2,
        "allowed_tags": list(policy.allowed_tags),
        "max_comment_length": policy.max_comment_length,
        "ratings": visible,
    }


def received_ratings(*, user_id: int, at: datetime | None = None, limit: int = 100):
    """Ratings this user has received, narrowed to the ones already visible.

    The `WHERE` clause is the predicate expressed in SQL so the database does
    the narrowing before the page limit applies -- otherwise a user whose most
    recent page is all still-blind ratings would see nothing older. Callers
    apply `is_revealed` to the rows they get back; that, not this queryset, is
    the authority on visibility.
    """

    at = at or timezone.now()
    return (
        Rating.objects.filter(ratee_id=user_id)
        .select_related("deal")
        .prefetch_related("deal__ratings")
        .annotate(sides_on_file=Count("deal__ratings"))
        .filter(Q(review_window_ends_at__lte=at) | Q(sides_on_file__gte=2))
        .order_by("-created_at")[:limit]
    )
