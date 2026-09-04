"""redis_bus enforces the G6 / G6b guardrails:

- publish_after_commit fires ONLY after the transaction commits
- it writes a PublishedEvent audit row
- on rollback, nothing is published and no audit row is written
- mark_delivered is idempotent
"""

from datetime import timedelta
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.db import transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.core import redis_bus
from apps.core.models import PublishedEvent


class PublishAfterCommitTests(TransactionTestCase):
    """on_commit callbacks need a real commit; TestCase wraps tests in
    rollback-only transactions which would discard the callbacks."""

    def test_returns_event_id(self):
        with patch.object(redis_bus, "get_client") as gc:
            gc.return_value.publish.return_value = 1
            with transaction.atomic():
                eid = redis_bus.publish_after_commit("trip.created", {"id": 1})
        assert isinstance(eid, str)
        assert len(eid) == 32  # uuid4 hex

    def test_publishes_after_commit_with_audit_row(self):
        with patch.object(redis_bus, "get_client") as gc:
            gc.return_value.publish.return_value = 1
            with transaction.atomic():
                eid = redis_bus.publish_after_commit("trip.created", {"id": 7})
                # Inside the block: not yet published, no audit row.
                assert PublishedEvent.objects.count() == 0
                gc.return_value.publish.assert_not_called()
            # After commit: audit row + publish call.
            assert PublishedEvent.objects.filter(event_id=eid).exists()
            gc.return_value.publish.assert_called_once()
            args, _ = gc.return_value.publish.call_args
            assert args[0] == "trip.created"
            # payload includes event_id + ts + caller fields
            assert f'"event_id":"{eid}"' in args[1]
            assert '"id":7' in args[1]

    def test_rollback_emits_nothing(self):
        class _Boom(Exception):
            pass

        with patch.object(redis_bus, "get_client") as gc:
            try:
                with transaction.atomic():
                    redis_bus.publish_after_commit("trip.created", {"id": 1})
                    raise _Boom()
            except _Boom:
                pass
            gc.return_value.publish.assert_not_called()
        assert PublishedEvent.objects.count() == 0

    def test_publish_failure_keeps_audit_row_for_sweep(self):
        import redis as redis_pkg

        with patch.object(redis_bus, "get_client") as gc:
            gc.return_value.publish.side_effect = redis_pkg.RedisError("nope")
            with transaction.atomic():
                eid = redis_bus.publish_after_commit("trip.created", {"id": 1})
        # Audit row stays (so the daily sweep can flag it as undelivered).
        assert PublishedEvent.objects.filter(event_id=eid).exists()


class PublishAfterCommitValidationTests(TestCase):
    """Pure validation — no on_commit, so a regular TestCase is fine."""

    def test_rejects_empty_channel(self):
        import pytest

        with pytest.raises(ValueError):
            redis_bus.publish_after_commit("", {"x": 1})

    def test_rejects_non_dict_payload(self):
        import pytest

        with pytest.raises(TypeError):
            redis_bus.publish_after_commit("ch", [1, 2, 3])  # type: ignore[arg-type]


class EnqueueEmailAfterCommitTests(TransactionTestCase):
    """The email stream publisher (first XADD in Django) mirrors the
    publish_after_commit discipline: fire only after commit, write a
    PublishedEvent audit row, swallow Redis errors so the sweep catches misses.
    """

    def test_returns_event_id(self):
        with patch.object(redis_bus, "get_client") as gc:
            gc.return_value.xadd.return_value = b"1-0"
            with transaction.atomic():
                eid = redis_bus.enqueue_email_after_commit(
                    "u@example.com", "Subj", "Body", kind="verify"
                )
        assert isinstance(eid, str)
        assert len(eid) == 32  # uuid4 hex

    def test_xadds_after_commit_with_audit_row(self):
        with patch.object(redis_bus, "get_client") as gc:
            gc.return_value.xadd.return_value = b"1-0"
            with transaction.atomic():
                eid = redis_bus.enqueue_email_after_commit(
                    "u@example.com", "Subj", "Body", kind="verify"
                )
                # Inside the block: nothing enqueued, no audit row yet.
                assert PublishedEvent.objects.count() == 0
                gc.return_value.xadd.assert_not_called()
            # After commit: audit row on the email:send channel + one XADD.
            row = PublishedEvent.objects.get(event_id=eid)
            assert row.channel == "email:send"
            gc.return_value.xadd.assert_called_once()
            args, kwargs = gc.return_value.xadd.call_args
            assert args[0] == "email:send"
            fields = args[1]
            assert fields["event_id"] == eid
            # payload is a JSON string carrying the render + routing metadata.
            import json

            payload = json.loads(fields["payload"])
            assert payload == {
                "event_id": eid,
                "to": "u@example.com",
                "subject": "Subj",
                "body": "Body",
                "kind": "verify",
            }
            # MAXLEN ~ 10000 (approximate trimming) per G1.
            assert kwargs.get("maxlen") == 10000
            assert kwargs.get("approximate") is True

    def test_rollback_enqueues_nothing(self):
        class _Boom(Exception):
            pass

        with patch.object(redis_bus, "get_client") as gc:
            try:
                with transaction.atomic():
                    redis_bus.enqueue_email_after_commit(
                        "u@example.com", "S", "B", kind="reset"
                    )
                    raise _Boom()
            except _Boom:
                pass
            gc.return_value.xadd.assert_not_called()
        assert PublishedEvent.objects.count() == 0

    def test_xadd_failure_keeps_audit_row_for_sweep(self):
        import redis as redis_pkg

        with patch.object(redis_bus, "get_client") as gc:
            gc.return_value.xadd.side_effect = redis_pkg.RedisError("nope")
            with transaction.atomic():
                eid = redis_bus.enqueue_email_after_commit(
                    "u@example.com", "S", "B", kind="reset"
                )
        # Audit row stays so the daily sweep flags it as undelivered.
        assert PublishedEvent.objects.filter(event_id=eid).exists()

    def test_rejects_bad_kind(self):
        import pytest

        with pytest.raises(ValueError):
            redis_bus.enqueue_email_after_commit("u@x.com", "S", "B", kind="spam")

    def test_rejects_empty_recipient(self):
        import pytest

        with pytest.raises(ValueError):
            redis_bus.enqueue_email_after_commit("", "S", "B", kind="verify")


class MarkDeliveredTests(TestCase):
    def test_marks_delivered_once(self):
        ev = PublishedEvent.objects.create(
            channel="trip.created",
            event_id="abc123",
            payload_hash="x" * 64,
        )
        assert ev.delivered_at is None
        assert redis_bus.mark_delivered("abc123") is True
        ev.refresh_from_db()
        assert ev.delivered_at is not None

    def test_idempotent(self):
        PublishedEvent.objects.create(
            channel="trip.created",
            event_id="abc123",
            payload_hash="x" * 64,
        )
        assert redis_bus.mark_delivered("abc123") is True
        # Second call: row already delivered, returns False.
        assert redis_bus.mark_delivered("abc123") is False

    def test_unknown_event_id_returns_false(self):
        assert redis_bus.mark_delivered("not-a-real-id") is False


class SweepDeliveredTests(TestCase):
    @patch.object(redis_bus, "get_client")
    def test_sweep_recovers_a_per_user_delivery_receipt(self, get_client):
        event = PublishedEvent.objects.create(
            channel="offer.created",
            event_id="event-per-user-receipt",
            payload_hash="x" * 64,
        )
        PublishedEvent.objects.filter(pk=event.pk).update(
            published_at=timezone.now() - timedelta(minutes=10)
        )
        client = MagicMock()
        client.exists.return_value = 0
        client.scan_iter.return_value = iter(
            ["delivered:event-per-user-receipt:42"]
        )
        get_client.return_value = client

        output = StringIO()
        call_command("sweep_published_events", stdout=output)

        event.refresh_from_db()
        assert event.delivered_at is not None
        assert "recovered=1" in output.getvalue()
