"""Report the durable Redis streams: length, groups, consumers, pending work.

Two stream families carry obligations through Redis. `notif:fcm` holds push
transport that PostgreSQL no longer tracks once its dispatch job succeeded, and
`email:send` carries rendered mail whose `OutboundMessage` row retries it. A
Redis cutover, restart or rollback is only safe when this report says nothing
is waiting, and after one it is the proof that entries, groups and pending
lists survived. It is also the on-demand view of stream lag.

Every command it sends is read-only (INFO, CONFIG GET, TTL, XINFO, XPENDING).
The target URL is never printed: it carries the Redis password.

Usage::

    python manage.py inspect_redis_streams
    python manage.py inspect_redis_streams --json
    python manage.py inspect_redis_streams --require-drained
    python manage.py inspect_redis_streams --url "$OTHER_REDIS_URL"
"""

from __future__ import annotations

import json
import time
from urllib.parse import urlparse

import redis
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core import redis_bus

#: Written by the Go FCM consumer on every read loop with a 45-second TTL.
FCM_HEARTBEAT_KEY = "fcm:worker:active"


def _default_streams() -> list[str]:
    return [
        settings.FCM_STREAM,
        settings.FCM_RESULTS_STREAM,
        redis_bus._EMAIL_STREAM,
    ]


def _id_tuple(entry_id: str | None) -> tuple[int, int] | None:
    if not entry_id:
        return None
    ms, _, seq = str(entry_id).partition("-")
    try:
        return int(ms), int(seq or 0)
    except ValueError:
        return None


def _age_seconds(entry_id: str | None, now_ms: int) -> float | None:
    parsed = _id_tuple(entry_id)
    if parsed is None:
        return None
    return round(max(0, now_ms - parsed[0]) / 1000, 1)


def _config(client: redis.Redis, name: str) -> str | None:
    try:
        return str(client.config_get(name).get(name, ""))
    except redis.ResponseError:
        # Managed providers may disable CONFIG; report it, never guess.
        return None


def eviction_verdict(policy: str | None) -> str:
    """Stream keys have no TTL, so only `allkeys-*` policies can evict them."""

    if policy is None:
        return "unverifiable"
    return "unsafe" if policy.startswith("allkeys-") else "safe"


def _server(client: redis.Redis) -> dict:
    info: dict = {}
    for section in ("server", "persistence", "memory"):
        try:
            info.update(client.info(section))
        except redis.ResponseError:
            pass
    policy = _config(client, "maxmemory-policy")
    heartbeat_ttl = client.ttl(FCM_HEARTBEAT_KEY)
    return {
        "redis_version": info.get("redis_version"),
        "used_memory_human": info.get("used_memory_human"),
        "maxmemory": _config(client, "maxmemory"),
        "maxmemory_policy": policy,
        "eviction": eviction_verdict(policy),
        "appendonly": _config(client, "appendonly"),
        "appendfsync": _config(client, "appendfsync"),
        "save": _config(client, "save"),
        "aof_last_write_status": info.get("aof_last_write_status"),
        "rdb_last_bgsave_status": info.get("rdb_last_bgsave_status"),
        "rdb_changes_since_last_save": info.get("rdb_changes_since_last_save"),
        "loading": info.get("loading"),
        "fcm_worker_heartbeat_ttl": heartbeat_ttl if heartbeat_ttl >= 0 else None,
    }


def _group(
    client: redis.Redis, stream: str, row: dict, last_id: str, now_ms: int
) -> dict:
    name = row["name"]
    pending = int(row.get("pending") or 0)
    lag = row.get("lag")
    last_delivered = row.get("last-delivered-id")
    oldest = None
    if pending:
        first = client.xpending_range(stream, name, min="-", max="+", count=1)
        if first:
            entry = first[0]
            oldest = {
                "id": entry["message_id"],
                "consumer": entry["consumer"],
                "age_seconds": _age_seconds(entry["message_id"], now_ms),
                "idle_seconds": round(int(entry["time_since_delivered"]) / 1000, 1),
                "deliveries": int(entry["times_delivered"]),
            }
    consumers = [
        {
            "name": consumer["name"],
            "pending": int(consumer.get("pending") or 0),
            "idle_seconds": round(int(consumer.get("idle") or 0) / 1000, 1),
        }
        for consumer in client.xinfo_consumers(stream, name)
    ]
    # Redis reports lag as null when it cannot count (e.g. a group created at
    # an explicit ID). A group whose cursor has reached the stream's last ID
    # has nothing undelivered either way.
    caught_up = lag == 0 or (
        lag is None
        and _id_tuple(last_delivered) is not None
        and _id_tuple(last_id) is not None
        and _id_tuple(last_delivered) >= _id_tuple(last_id)
    )
    return {
        "name": name,
        "pending": pending,
        "lag": lag,
        "last_delivered_id": last_delivered,
        "entries_read": row.get("entries-read"),
        "drained": pending == 0 and caught_up,
        "oldest_pending": oldest,
        "consumers": consumers,
    }


def _stream(client: redis.Redis, stream: str, now_ms: int) -> dict:
    try:
        info = client.xinfo_stream(stream)
    except redis.ResponseError:
        # XINFO STREAM answers "no such key" for a stream never written.
        return {"name": stream, "exists": False, "drained": True, "groups": []}
    last_id = info.get("last-generated-id")
    first_entry = info.get("first-entry")
    first_id = first_entry[0] if first_entry else None
    length = int(info.get("length") or 0)
    groups = [
        _group(client, stream, row, last_id, now_ms)
        for row in client.xinfo_groups(stream)
    ]
    return {
        "name": stream,
        "exists": True,
        "length": length,
        "first_id": first_id,
        "first_entry_age_seconds": _age_seconds(first_id, now_ms),
        "last_generated_id": last_id,
        # Entries on a stream no group reads are undelivered by definition.
        "drained": all(group["drained"] for group in groups)
        and (bool(groups) or length == 0),
        "groups": groups,
    }


def inspect(client: redis.Redis, streams: list[str]) -> dict:
    now_ms = int(time.time() * 1000)
    return {
        "server": _server(client),
        "streams": [_stream(client, stream, now_ms) for stream in streams],
    }


class Command(BaseCommand):
    help = (
        "Read-only report of Redis stream length, consumer groups, consumers "
        "and pending entries, plus the eviction and persistence settings."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--stream",
            action="append",
            help="Inspect only this stream. Repeatable. Default: every durable stream.",
        )
        parser.add_argument(
            "--url",
            help="Inspect this Redis instead of REDIS_URL (never printed).",
        )
        parser.add_argument(
            "--json", action="store_true", help="Print the report as JSON."
        )
        parser.add_argument(
            "--require-drained",
            action="store_true",
            help="Exit non-zero unless every group has nothing pending or undelivered.",
        )

    def handle(self, *args, **options):
        url = options.get("url") or settings.REDIS_URL
        parsed = urlparse(url)
        target = f"{parsed.hostname}:{parsed.port or 6379}{parsed.path or ''}"
        client = redis.Redis.from_url(
            url, decode_responses=True, socket_connect_timeout=2, socket_timeout=5
        )
        try:
            report = inspect(client, options.get("stream") or _default_streams())
        except redis.RedisError as exc:
            raise CommandError(
                f"Redis at {target} could not be inspected: {type(exc).__name__}"
            ) from exc
        finally:
            client.close()
        report["target"] = target

        if options["json"]:
            self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
        else:
            self._write_text(report)

        if options["require_drained"]:
            undrained = [
                stream["name"] for stream in report["streams"] if not stream["drained"]
            ]
            if undrained:
                raise CommandError(
                    "Pending or undelivered stream work: " + ", ".join(undrained)
                )

    def _write_text(self, report: dict) -> None:
        server = report["server"]
        self.stdout.write(
            f"redis {report['target']} version={server['redis_version']} "
            f"used={server['used_memory_human']} maxmemory={server['maxmemory']}"
        )
        self.stdout.write(
            f"  maxmemory-policy={server['maxmemory_policy']} "
            f"eviction={server['eviction']} appendonly={server['appendonly']} "
            f"appendfsync={server['appendfsync']} save={server['save']!r} "
            f"aof_last_write={server['aof_last_write_status']} "
            f"rdb_last_bgsave={server['rdb_last_bgsave_status']}"
        )
        self.stdout.write(
            f"  fcm worker heartbeat ttl={server['fcm_worker_heartbeat_ttl']}"
        )
        for stream in report["streams"]:
            if not stream["exists"]:
                self.stdout.write(f"stream {stream['name']}: absent")
                continue
            self.stdout.write(
                f"stream {stream['name']}: length={stream['length']} "
                f"first={stream['first_id']} "
                f"(age {stream['first_entry_age_seconds']}s) "
                f"last={stream['last_generated_id']} groups={len(stream['groups'])} "
                f"drained={'yes' if stream['drained'] else 'NO'}"
            )
            for group in stream["groups"]:
                self.stdout.write(
                    f"  group {group['name']}: pending={group['pending']} "
                    f"lag={group['lag']} last-delivered={group['last_delivered_id']} "
                    f"drained={'yes' if group['drained'] else 'NO'}"
                )
                if oldest := group["oldest_pending"]:
                    self.stdout.write(
                        f"    oldest pending {oldest['id']} on {oldest['consumer']}: "
                        f"age {oldest['age_seconds']}s, idle {oldest['idle_seconds']}s, "
                        f"deliveries {oldest['deliveries']}"
                    )
                for consumer in group["consumers"]:
                    self.stdout.write(
                        f"    consumer {consumer['name']}: pending={consumer['pending']} "
                        f"idle={consumer['idle_seconds']}s"
                    )
