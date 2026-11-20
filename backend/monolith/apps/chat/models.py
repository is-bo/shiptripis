from django.conf import settings
from django.db import models
from django.db.models import Q


class ChatMessage(models.Model):
    """A single 1:1 chat message tied to a Match.

    Django owns persistence + the write path. On create the send view
    publishes `chat.message.new` via `redis_bus.publish_after_commit` with
    both participant IDs; the Go chat-service fans the persisted receipt
    to their live WebSockets (it never writes this table itself). Only the
    counterparty receives a notification inbox row or push.

    The thread is implicit: `(match, ordered by id)`. There is no
    separate `chat_thread` table in V1 — a Match already scopes exactly the
    two parties allowed to talk, and chat is gated on a succeeded payment for
    the match's accepted offer (see the send view). If group/multi-thread
    chat ever appears (V2) a thread table can be introduced then.

    Table name `chat_message` is a Go-read contract: the chat-service's sqlc
    repo (`contracts/sql/queries/chat/`) will read history from it. Changing
    columns here requires re-running `task contract:sync-db` + flagging Claude
    B so sqlc is regenerated (CLAUDE.md §4).
    """

    match = models.ForeignKey(
        "matching.Match",
        on_delete=models.CASCADE,
        related_name="chat_messages",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_messages",
    )
    body = models.TextField(max_length=2000)
    client_message_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True, db_index=True)
    #: Staff removed the message after a report (`apps.chat.moderation`). The
    #: body stays for staff and the audit trail; members see that it was
    #: removed, never what it said.
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )

    class Meta:
        db_table = "chat_message"
        constraints = [
            models.UniqueConstraint(
                fields=("match", "sender", "client_message_id"),
                name="chat_sender_client_message_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=("match", "created_at"),
                name="chat_match_created_idx",
            ),
            models.Index(fields=("match", "id"), name="chat_match_id_idx"),
        ]

    def __str__(self) -> str:
        return f"ChatMessage(match={self.match_id}, sender={self.sender_id})"


class ChatMessageReport(models.Model):
    """A member reported a message they received (App Store 1.2, plan STORE).

    One report per message and reporter. Staff decide every open report of a
    message together (`apps.chat.moderation`): dismiss, remove the message, or
    restore it. The reporter's note and the staff reason stay internal.
    """

    class Reason(models.TextChoices):
        SPAM = "spam", "Spam or advertising"
        HARASSMENT = "harassment", "Harassment or threats"
        SCAM = "scam", "Scam or fraud"
        INAPPROPRIATE = "inappropriate", "Offensive or sexual content"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        #: Staff looked and left the message as it was.
        DISMISSED = "dismissed", "Dismissed"
        #: Staff removed the message.
        ACTIONED = "actioned", "Actioned"

    message = models.ForeignKey(
        ChatMessage, on_delete=models.PROTECT, related_name="reports"
    )
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    reason = models.CharField(max_length=16, choices=Reason.choices)
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
    decision_reason = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "chat_message_report"
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["message", "reporter"], name="chat_report_once"
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="open", decided_at__isnull=True)
                    | (~Q(status="open") & Q(decided_at__isnull=False))
                ),
                name="chat_report_decided_when_closed",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "created_at"], name="chat_report_queue_idx"),
        ]

    def __str__(self) -> str:
        return f"ChatMessageReport#{self.pk} message={self.message_id} {self.status}"
