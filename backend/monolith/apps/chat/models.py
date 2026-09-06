from django.conf import settings
from django.db import models


class ChatMessage(models.Model):
    """A single 1:1 chat message tied to a Match.

    Django owns persistence + the write path. On create the send view
    publishes `chat.message.new` via `redis_bus.publish_after_commit` with
    `targets=[other_member_uid]`; the Go chat-service fans the same payload
    to the recipient's live WebSocket (it never writes this table itself).

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
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "chat_message"
        indexes = [
            models.Index(
                fields=("match", "created_at"),
                name="chat_match_created_idx",
            ),
            models.Index(fields=("match", "id"), name="chat_match_id_idx"),
        ]

    def __str__(self) -> str:
        return f"ChatMessage(match={self.match_id}, sender={self.sender_id})"
