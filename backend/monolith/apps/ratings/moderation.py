"""Reports on reviews and staff's decisions about them (spec 18, plan L13A).

A member reports a review once, with a reason. Staff then decide, with a
reason that is audited and stays internal:

- **dismiss** the open reports: the review stays as it is;
- **hide the comment**: the score and tags still count, the text goes;
- **remove the rating**: it leaves every public average, count and list;
- **lift** a standing decision: the review is shown as written again.

Every decision closes all the review's open reports (`actioned` when staff
hid or removed something, `dismissed` otherwise), so the reporter's "received"
becomes "reviewed". The rating row is never edited: a decision is a
`RatingModeration` row beside it, and lifting deletes that row. The history of
decisions is the audit log.

Decisions on one review are serialised on the rating row, taken
`FOR NO KEY UPDATE` like every other lock on a row of the deal aggregate
(`apps.core.financial_locks`), so two staff members deciding at once queue
and the second reads the first one's outcome.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.parcels import tracking

from .models import Rating, RatingModeration, RatingReport

MODERATE_PERMISSION = "moderate_ratings"

ACTION_DISMISS = "dismiss"
ACTION_HIDE_COMMENT = "hide_comment"
ACTION_REMOVE = "remove"
ACTION_LIFT = "lift"
ACTIONS = (ACTION_DISMISS, ACTION_HIDE_COMMENT, ACTION_REMOVE, ACTION_LIFT)

#: The audit action each decision writes.
AUDIT_ACTIONS = {
    ACTION_DISMISS: "rating.reports_dismissed",
    ACTION_HIDE_COMMENT: "rating.comment_hidden",
    ACTION_REMOVE: "rating.removed",
    ACTION_LIFT: "rating.moderation_lifted",
}

MAX_NOTE_LENGTH = 500
MAX_REASON_LENGTH = 500


class ModerationError(ValueError):
    """A refused report or decision, with a stable machine code and an HTTP status."""

    def __init__(self, code: str, detail: str, *, status: int = 409):
        super().__init__(detail)
        self.code = code
        self.status = status


# --- reports ------------------------------------------------------------------


def file_report(*, rating: Rating, reporter, reason: str, note: str) -> tuple[RatingReport, bool]:
    """Record the reporter's one report on this review. Returns `(report, created)`.

    Who may report is decided by the caller (`apps.ratings.views`), which has
    already proved the reporter can read this review or is its ratee. A second
    report by the same person answers the first one, unchanged, and a race
    between two taps resolves on `ratings_report_once`.
    """

    if reason not in RatingReport.Reason.values:
        raise ModerationError("report_reason_invalid", "Choose a reason.", status=400)
    existing = RatingReport.objects.filter(rating=rating, reporter=reporter).first()
    if existing is not None:
        return existing, False
    try:
        with transaction.atomic():
            report = RatingReport.objects.create(
                rating=rating,
                reporter=reporter,
                reason=reason,
                note=(note or "").strip()[:MAX_NOTE_LENGTH],
            )
    except IntegrityError:
        return RatingReport.objects.get(rating=rating, reporter=reporter), False
    return report, True


# --- staff decisions ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Decision:
    action: str
    reports_closed: int
    state: str | None


def _require_moderator(actor) -> None:
    from apps.admin_panel.permissions import has_all_admin_permissions

    if not has_all_admin_permissions(actor, MODERATE_PERMISSION):
        raise ModerationError(
            "permission_denied", "You cannot moderate reviews.", status=403
        )


def _staff_reason(reason: str) -> str:
    reason = (reason or "").strip()
    if not reason:
        raise ModerationError("reason_required", "A reason is required.", status=400)
    return reason[:MAX_REASON_LENGTH]


def _close_open_reports(rating: Rating, *, status: str, actor, at, reason: str) -> int:
    return RatingReport.objects.filter(
        rating=rating, status=RatingReport.Status.OPEN
    ).update(status=status, decided_by=actor, decided_at=at, decision_reason=reason)


def decide(*, rating_id: int, actor, action: str, reason: str) -> Decision:
    """Apply one staff decision to one review. Audited; refuses a no-op.

    A decision that would change nothing (dismissing with no open report,
    hiding an already hidden comment, lifting where nothing stands) is refused
    with `moderation_unchanged` rather than recorded twice.
    """

    from apps.admin_panel.services import record_admin_action

    if action not in ACTIONS:
        raise ModerationError("moderation_action_invalid", "Unknown decision.", status=400)
    _require_moderator(actor)
    reason = _staff_reason(reason)
    with transaction.atomic():
        rating = (
            # Only the rating row is locked; the deal and request are read.
            Rating.objects.select_for_update(no_key=True, of=("self",))
            .select_related("deal__delivery_request")
            .filter(pk=rating_id)
            .first()
        )
        if rating is None:
            raise ModerationError("rating_not_found", "No such review.", status=404)
        current = RatingModeration.objects.filter(rating=rating).first()
        before_state = current.state if current else None
        open_reports = RatingReport.objects.filter(
            rating=rating, status=RatingReport.Status.OPEN
        ).count()
        at = timezone.now()

        if action == ACTION_DISMISS:
            if not open_reports:
                raise ModerationError(
                    "moderation_unchanged", "This review has no open report to dismiss."
                )
            after_state = before_state
            closed_as = RatingReport.Status.DISMISSED
        elif action == ACTION_LIFT:
            if current is None:
                raise ModerationError(
                    "moderation_unchanged", "No decision stands on this review."
                )
            current.delete()
            after_state = None
            closed_as = RatingReport.Status.DISMISSED
        else:
            after_state = (
                RatingModeration.State.COMMENT_HIDDEN
                if action == ACTION_HIDE_COMMENT
                else RatingModeration.State.REMOVED
            )
            if before_state == after_state:
                raise ModerationError(
                    "moderation_unchanged",
                    "The comment is already hidden."
                    if action == ACTION_HIDE_COMMENT
                    else "The rating is already removed.",
                )
            if action == ACTION_HIDE_COMMENT and not (rating.comment or "").strip():
                raise ModerationError(
                    "rating_has_no_comment", "This review has no comment to hide."
                )
            RatingModeration.objects.update_or_create(
                rating=rating,
                defaults={
                    "state": after_state,
                    "decided_by": actor,
                    "decided_at": at,
                    "reason": reason,
                },
            )
            closed_as = RatingReport.Status.ACTIONED

        closed = _close_open_reports(
            rating, status=closed_as, actor=actor, at=at, reason=reason
        )
        record_admin_action(
            actor=actor,
            action=AUDIT_ACTIONS[action],
            target=rating,
            before={"moderation": before_state, "open_reports": open_reports},
            after={"moderation": after_state, "open_reports": open_reports - closed},
            reason=reason,
            reference=tracking.for_deal(rating.deal),
            metadata={"reports_closed": closed, "reports_closed_as": closed_as},
        )
    return Decision(action=action, reports_closed=closed, state=after_state)
