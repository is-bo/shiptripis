"""redis_bus enforces the G6 / G6b guardrails:

- publish_after_commit fires ONLY after the transaction commits
- it writes a PublishedEvent audit row
- on rollback, nothing is published and no audit row is written
- mark_delivered is idempotent
"""

from unittest.mock import patch

from django.db import transaction
from django.test import TestCase, TransactionTestCase

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
