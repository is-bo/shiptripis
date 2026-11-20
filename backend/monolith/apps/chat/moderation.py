"""Reported chat messages and staff's decisions about them (App Store 1.2).

A member reports a message they received, once, with a reason and an optional
note, and may block the sender at the same time (`apps.accounts.blocks`).
Staff then decide, with a reason that is audited and stays internal:

- **dismiss** the open reports: the message stays as it is;
- **remove** the message: both members see "Removed by Wassla" instead of it;
- **restore** a removed message.

Every decision closes all the message's open reports (`actioned` when staff
removed it, `dismissed` otherwise). A member who keeps sending abuse is
suspended from their person page in the console, the existing staff action.

Decisions on one message are serialised on the message row, so two staff
members deciding at once queue and the second reads the first one's outcome.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.parcels import tracking

from .models import ChatMessage, ChatMessageReport

MODERATE_PERMISSION = "moderate_chat"

ACTION_DISMISS = "dismiss"
ACTION_REMOVE = "remove"
ACTION_RESTORE = "restore"
ACTIONS = (ACTION_DISMISS, ACTION_REMOVE, ACTION_RESTORE)

#: The audit action each decision writes.
AUDIT_ACTIONS = {
    ACTION_DISMISS: "chat.reports_dismissed",
    ACTION_REMOVE: "chat.message_removed",
    ACTION_RESTORE: "chat.message_restored",
}

MAX_NOTE_LENGTH = 500
MAX_REASON_LENGTH = 500


class ChatModerationError(ValueError):
    """A refused report or decision, with a stable machine code and an HTTP status."""

    def __init__(self, code: str, detail: str, *, status: int = 409):
        super().__init__(detail)
        self.code = code
        self.status = status


# --- reports ------------------------------------------------------------------


def file_report(
    *, message: ChatMessage, reporter, reason: str, note: str
) -> tuple[ChatMessageReport, bool]:
    """Record the reporter's one report on this message. Returns `(report, created)`.

    The caller (`apps.chat.views`) has proved the reporter is the other party
    of the conversation and may read it. Only a message someone else sent can
    be reported; a second report answers the first one, unchanged.
    """

    if reason not in ChatMessageReport.Reason.values:
        raise ChatModerationError("report_reason_invalid", "Choose a reason.", status=400)
    if message.sender_id == reporter.id:
        raise ChatModerationError(
            "report_own_message", "You cannot report your own message.", status=400
        )
    existing = ChatMessageReport.objects.filter(message=message, reporter=reporter).first()
    if existing is not None:
        return existing, False
    try:
        with transaction.atomic():
            report = ChatMessageReport.objects.create(
                message=message,
                reporter=reporter,
                reason=reason,
                note=(note or "").strip()[:MAX_NOTE_LENGTH],
            )
    except IntegrityError:
        return ChatMessageReport.objects.get(message=message, reporter=reporter), False
    return report, True


# --- staff decisions ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Decision:
    action: str
    reports_closed: int
    removed: bool


def available_decisions(message: ChatMessage, open_reports: int) -> dict[str, bool]:
    """Which decisions the message page offers now."""

    return {
        ACTION_DISMISS: bool(open_reports) and message.removed_at is None,
        ACTION_REMOVE: message.removed_at is None,
        ACTION_RESTORE: message.removed_at is not None,
    }


def _require_moderator(actor) -> None:
    from apps.admin_panel.permissions import has_all_admin_permissions

    if not has_all_admin_permissions(actor, MODERATE_PERMISSION):
        raise ChatModerationError(
            "permission_denied", "You cannot moderate chat messages.", status=403
        )


def _staff_reason(reason: str) -> str:
    reason = (reason or "").strip()
    if not reason:
        raise ChatModerationError("reason_required", "A reason is required.", status=400)
    return reason[:MAX_REASON_LENGTH]


def _forget_text_in_inbox(message_id: int) -> None:
    """Drop a removed message's text from the inbox rows that carried it.

    The recipient's bell row keeps the event as it was published, and a late
    redelivery republishes that row: without this the text stays readable
    there after Wassla removed it. Restoring does not put it back; the
    conversation shows it again.
    """

    from apps.core import channels
    from apps.notifications.models import Notification

    rows = Notification.objects.select_for_update().filter(
        channel=channels.CHAT_MESSAGE_NEW, payload__message_id=message_id
    )
    for row in rows:
        if "body" in row.payload:
            row.payload = {key: value for key, value in row.payload.items() if key != "body"}
            row.save(update_fields=["payload"])


def decide(*, message_id: int, actor, action: str, reason: str) -> Decision:
    """Apply one staff decision to one message. Audited; refuses a no-op."""

    from apps.admin_panel.services import record_admin_action

    if action not in ACTIONS:
        raise ChatModerationError("moderation_action_invalid", "Unknown decision.", status=400)
    _require_moderator(actor)
    reason = _staff_reason(reason)
    with transaction.atomic():
        message = (
            # Only the message row is locked; the request is read for its number.
            ChatMessage.objects.select_for_update(no_key=True, of=("self",))
            .select_related("match__parcel")
            .filter(pk=message_id)
            .first()
        )
        if message is None:
            raise ChatModerationError("message_not_found", "No such message.", status=404)
        # Read once under the lock: a report filed while the decision runs stays
        # open for the next decision instead of being closed unseen.
        open_ids = list(
            ChatMessageReport.objects.filter(
                message=message, status=ChatMessageReport.Status.OPEN
            ).values_list("pk", flat=True)
        )
        if not available_decisions(message, len(open_ids))[action]:
            raise ChatModerationError(
                "moderation_unchanged", "This decision changes nothing on this message."
            )
        before_removed = message.removed_at is not None
        at = timezone.now()
        if action == ACTION_REMOVE:
            message.removed_at, message.removed_by = at, actor
            closed_as = ChatMessageReport.Status.ACTIONED
        elif action == ACTION_RESTORE:
            message.removed_at, message.removed_by = None, None
            closed_as = ChatMessageReport.Status.DISMISSED
        else:
            closed_as = ChatMessageReport.Status.DISMISSED
        if action != ACTION_DISMISS:
            message.save(update_fields=["removed_at", "removed_by"])
        if action == ACTION_REMOVE:
            _forget_text_in_inbox(message.pk)

        closed = ChatMessageReport.objects.filter(
            pk__in=open_ids, status=ChatMessageReport.Status.OPEN
        ).update(status=closed_as, decided_by=actor, decided_at=at, decision_reason=reason)
        record_admin_action(
            actor=actor,
            action=AUDIT_ACTIONS[action],
            target=message,
            before={"removed": before_removed, "open_reports": len(open_ids)},
            after={
                "removed": message.removed_at is not None,
                "open_reports": len(open_ids) - closed,
            },
            reason=reason,
            reference=tracking.for_request(message.match.parcel),
            metadata={
                "match_id": message.match_id,
                "reports_closed": closed,
                "reports_closed_as": closed_as,
            },
        )
    return Decision(action=action, reports_closed=closed, removed=message.removed_at is not None)
