from django.conf import settings
from django.db import models


class Notification(models.Model):
    """Persisted, per-recipient notification.

    Written by `apps.core.redis_bus.publish_after_commit` for every user id in
    the `targets` list, in the same `on_commit` step that publishes to Redis.
    The Go WS dispatcher fans the same payload live; this row is the
    persistent inbox the mobile client reads on cold start and after
    backgrounding.

    `event_id` matches `core_published_event.event_id` so we can correlate
    inbox rows with delivery receipts and the G6b audit table.
    """

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    channel = models.CharField(max_length=64, db_index=True)
    event_id = models.CharField(max_length=64, db_index=True)
    payload = models.JSONField(default=dict)
    read_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "notification"
        indexes = [
            models.Index(
                fields=("recipient", "-created_at"),
                name="notif_recipient_recent_idx",
            ),
            models.Index(
                fields=("recipient", "read_at"),
                name="notif_recipient_unread_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("recipient", "event_id"),
                name="notif_recipient_event_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"Notification(channel={self.channel}, recipient={self.recipient_id})"
