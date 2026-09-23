import time
from datetime import timedelta
from unittest.mock import MagicMock, patch

import redis
from django.test import TestCase
from django.utils import timezone

from apps.core import ops_snapshot
from apps.finance.models import ScheduledJob


def _stream_client(*, decode: bool, oldest_ms: int, pending: int = 2):
    def text(value: str):
        return value if decode else value.encode()

    client = MagicMock()
    client.xlen.return_value = 7
    client.xpending.return_value = {
        "pending": pending,
        "min": text(f"{oldest_ms}-0") if pending else None,
        "max": None,
        "consumers": [],
    }
    # redis-py always gives str keys here, but values stay bytes unless the
    # client decodes responses -- the case the old deep-health code missed.
    client.xinfo_groups.return_value = [
        {"name": text("other-group"), "pending": 0, "lag": 99},
        {"name": text("workers"), "pending": pending, "lag": 3},
    ]
    return client


class StreamBacklogTests(TestCase):
    def test_reports_backlog_for_decoded_and_raw_clients(self):
        oldest_ms = int((time.time() - 125) * 1000)
        for decode in (True, False):
            with self.subTest(decode=decode):
                report = ops_snapshot.stream_backlog(
                    _stream_client(decode=decode, oldest_ms=oldest_ms),
                    "stream",
                    "workers",
                )
                assert report["length"] == 7
                assert report["pending"] == 2
                assert report["lag"] == 3
                assert 120 <= report["oldest_pending_age_seconds"] <= 135

    def test_nothing_pending_has_no_oldest_age(self):
        report = ops_snapshot.stream_backlog(
            _stream_client(decode=True, oldest_ms=0, pending=0), "stream", "workers"
        )
        assert report["pending"] == 0
        assert report["oldest_pending_age_seconds"] is None

    def test_missing_group_or_outage_is_unknown_not_zero(self):
        client = MagicMock()
        client.xlen.return_value = 0
        client.xpending.side_effect = redis.ResponseError("NOGROUP")
        report = ops_snapshot.stream_backlog(client, "stream", "workers")
        assert report["pending"] is None
        assert report["oldest_pending_age_seconds"] is None


class OpsSnapshotTests(TestCase):
    def test_snapshot_counts_overdue_work_and_logs_numbers_only(self):
        now = timezone.now()
        ScheduledJob.objects.create(
            kind=ScheduledJob.Kind.RATING_REVEAL,
            key="ops-snapshot-overdue",
            run_at=now - timedelta(minutes=10),
            payload={"deal_id": 1},
        )
        ScheduledJob.objects.create(
            kind=ScheduledJob.Kind.RATING_REVEAL,
            key="ops-snapshot-future",
            run_at=now + timedelta(hours=1),
            payload={"deal_id": 2},
        )
        client = _stream_client(decode=True, oldest_ms=int(time.time() * 1000))

        with patch.object(ops_snapshot.redis.Redis, "from_url", return_value=client):
            with self.assertLogs("shiptrip.ops", level="INFO") as captured:
                snapshot = ops_snapshot.log_ops_snapshot()

        assert snapshot["jobs_overdue"] == 1
        assert 590 <= snapshot["jobs_oldest_overdue_seconds"] <= 700
        assert snapshot["outbound_overdue"] == 0
        assert snapshot["fcm_stream_pending"] == 2
        assert snapshot["email_stream_length"] == 7
        record = captured.records[0]
        assert record.event == "ops_snapshot"
        assert record.ops == snapshot
        for value in snapshot.values():
            assert value is None or isinstance(value, (int, str))
        client.close.assert_called_once()

    def test_redis_outage_still_reports_database_backlog(self):
        with patch.object(
            ops_snapshot.redis.Redis,
            "from_url",
            side_effect=redis.ConnectionError("down"),
        ):
            snapshot = ops_snapshot.build_ops_snapshot()

        assert snapshot["redis"] == "unavailable"
        assert snapshot["jobs_overdue"] == 0
