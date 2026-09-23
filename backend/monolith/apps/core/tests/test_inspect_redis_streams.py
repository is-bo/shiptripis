import json
from io import StringIO
from unittest import mock

import redis
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase

from apps.core.management.commands.inspect_redis_streams import eviction_verdict

URL = "redis://default:do-not-print@redis.internal.invalid:6379/0"

#: Everything the command may send. Any other call is a write it must not make.
READ_ONLY = {
    "info",
    "config_get",
    "ttl",
    "xinfo_stream",
    "xinfo_groups",
    "xinfo_consumers",
    "xpending_range",
    "close",
}


def fake_redis(*, pending=0, lag=0, last_delivered="1700000000000-0"):
    client = mock.MagicMock()
    client.info.return_value = {
        "redis_version": "8.2.1",
        "used_memory_human": "1.2M",
        "aof_last_write_status": "ok",
        "rdb_last_bgsave_status": "ok",
    }
    config = {
        "maxmemory-policy": "noeviction",
        "maxmemory": "0",
        "appendonly": "yes",
        "appendfsync": "everysec",
        "save": "60 1",
    }
    client.config_get.side_effect = lambda name: {name: config[name]}
    client.ttl.return_value = 40

    def xinfo_stream(name):
        if name != "notif:fcm":
            raise redis.ResponseError("no such key")
        return {
            "length": 3,
            "first-entry": ("1690000000000-0", {"event_id": "a"}),
            "last-generated-id": "1700000000000-0",
        }

    client.xinfo_stream.side_effect = xinfo_stream
    client.xinfo_groups.return_value = [
        {
            "name": "notif-fcm-workers",
            "consumers": 2,
            "pending": pending,
            "last-delivered-id": last_delivered,
            "entries-read": 3,
            "lag": lag,
        }
    ]
    client.xinfo_consumers.return_value = [
        {"name": "old-hostname", "pending": pending, "idle": 90_000},
        {"name": "new-hostname", "pending": 0, "idle": 1_000},
    ]
    client.xpending_range.return_value = [
        {
            "message_id": "1699999990000-0",
            "consumer": "old-hostname",
            "time_since_delivered": 90_000,
            "times_delivered": 1,
        }
    ]
    return client


class InspectRedisStreamsTests(SimpleTestCase):
    def run_command(self, client, *args):
        out = StringIO()
        with mock.patch("redis.Redis.from_url", return_value=client):
            call_command("inspect_redis_streams", "--url", URL, *args, stdout=out)
        return out.getvalue()

    def assert_read_only(self, client):
        sent = {call[0].split(".")[0] for call in client.method_calls}
        assert sent <= READ_ONLY, sent - READ_ONLY

    def test_reports_pending_work_and_refuses_a_drain_check(self):
        client = fake_redis(pending=1)
        report = json.loads(self.run_command(client, "--json"))

        stream = next(s for s in report["streams"] if s["name"] == "notif:fcm")
        group = stream["groups"][0]
        assert group["pending"] == 1
        assert group["drained"] is False
        assert group["oldest_pending"]["id"] == "1699999990000-0"
        assert group["oldest_pending"]["consumer"] == "old-hostname"
        assert group["oldest_pending"]["idle_seconds"] == 90.0
        assert report["server"]["eviction"] == "safe"
        assert report["target"] == "redis.internal.invalid:6379/0"

        with self.assertRaisesRegex(CommandError, "notif:fcm"):
            self.run_command(fake_redis(pending=1), "--require-drained")
        self.assert_read_only(client)

    def test_a_caught_up_group_is_drained_even_when_redis_cannot_count_lag(self):
        client = fake_redis(pending=0, lag=None, last_delivered="1700000000000-0")
        text = self.run_command(client, "--require-drained")

        assert "notif-fcm-workers: pending=0" in text
        assert "stream email:send: absent" in text
        assert "do-not-print" not in text
        self.assert_read_only(client)

    def test_undelivered_entries_are_not_drained(self):
        with self.assertRaises(CommandError):
            self.run_command(fake_redis(pending=0, lag=2), "--require-drained")

    def test_entries_on_a_stream_nobody_reads_are_not_drained(self):
        client = fake_redis()
        client.xinfo_groups.return_value = []
        with self.assertRaisesRegex(CommandError, "notif:fcm"):
            self.run_command(client, "--require-drained")

    def test_unreachable_redis_names_the_host_not_the_password(self):
        client = fake_redis()
        client.info.side_effect = redis.ConnectionError("refused")
        with self.assertRaisesRegex(CommandError, "redis.internal.invalid") as raised:
            self.run_command(client)
        assert "do-not-print" not in str(raised.exception)

    def test_eviction_verdict_only_flags_policies_that_reach_ttl_less_keys(self):
        assert eviction_verdict("noeviction") == "safe"
        assert eviction_verdict("volatile-lru") == "safe"
        assert eviction_verdict("allkeys-lru") == "unsafe"
        assert eviction_verdict("allkeys-lfu") == "unsafe"
        assert eviction_verdict(None) == "unverifiable"
