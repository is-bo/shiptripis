"""Host-only aggregate checks; no public listener, raw logs or credentials."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def capture(*args):
    return subprocess.check_output(args, text=True, timeout=15)


def main():
    problems = []
    compose = ["docker", "compose", "-p", "wacla", "--env-file", os.environ["STACK_ENV_FILE"],
               "-f", str(Path(__file__).with_name("compose.yml"))]
    rows = capture(*compose, "ps", "--all", "--format", "json")
    rows = json.loads(rows) if rows.strip().startswith("[") else [json.loads(r) for r in rows.splitlines()]
    by_service = {r["Service"]: r for r in rows}
    for service in ("app", "caddy", "postgres", "redis"):
        row = by_service.get(service, {})
        if row.get("State") != "running" or row.get("Health") != "healthy":
            problems.append(f"{service}_unhealthy")
    disk = shutil.disk_usage("/var/lib/docker")
    if disk.used / disk.total > .80:
        problems.append("disk_over_80_percent")
    stats = capture("docker", "stats", "--no-stream", "--format", '{{json .}}')
    memory = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        if key in {"MemTotal", "MemAvailable"}:
            memory[key] = int(value.split()[0]) * 1024
    if memory["MemAvailable"] / memory["MemTotal"] < .15:
        problems.append("host_memory_over_85_percent")
    load = os.getloadavg()
    if load[1] > (os.cpu_count() or 1) * 1.5:
        problems.append("host_load_high")
    container_stats = []
    for line in stats.splitlines():
        row = json.loads(line)
        if row.get("Name", "").startswith("wacla-"):
            container_stats.append({"name": row["Name"], "cpu_percent": row["CPUPerc"], "memory_percent": row["MemPerc"]})
            if float(row["MemPerc"].rstrip("%")) > 85:
                problems.append("container_memory_over_85_percent")
    persistence = capture(*compose, "exec", "-T", "redis", "sh", "-c",
                          'REDISCLI_AUTH="$(cat /run/secrets/redis_password)" redis-cli INFO persistence')
    info = dict(r.strip().split(":", 1) for r in persistence.splitlines() if ":" in r and not r.startswith("#"))
    if info.get("aof_enabled") != "1" or info.get("aof_last_write_status") != "ok" or info.get("rdb_last_bgsave_status") != "ok":
        problems.append("redis_persistence_unhealthy")
    logs = capture(*compose, "logs", "--no-log-prefix", "--since", "5m", "app")
    statuses = []
    snapshots = 0
    for line in logs.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if item.get("event") == "http_request" and isinstance(item.get("status"), int):
            statuses.append(item["status"])
        ops = item.get("ops")
        if isinstance(ops, dict):
            snapshots += 1
            if (ops.get("jobs_oldest_overdue_seconds") or 0) > 600 or ops.get("jobs_failed_unresolved", 0):
                problems.append("financial_job_backlog")
            if (ops.get("outbound_oldest_overdue_seconds") or 0) > 600:
                problems.append("email_backlog")
            for key, value in ops.items():
                if key.endswith("stream_lag") and isinstance(value, (int, float)) and value > 100:
                    problems.append("queue_lag")
            if ops.get("max_connections") and (ops.get("connections") or 0) / ops["max_connections"] > .70:
                problems.append("database_connection_pressure")
    if statuses and sum(s >= 500 for s in statuses) / len(statuses) > .01:
        problems.append("http_5xx_over_1_percent")
    marker = Path(os.environ.get("WACLA_STATE", "/var/lib/wacla")) / "backup-last-success"
    worker_marker = marker.with_name("last-finance-snapshot")
    if snapshots or not worker_marker.exists():
        worker_marker.write_text(str(time.time()))
    if time.time() - float(worker_marker.read_text()) > 900:
        problems.append("finance_worker_snapshot_missing")
    if not marker.exists() or time.time() - float(marker.read_text()) > 26 * 3600:
        problems.append("backup_missing_or_stale")
    print(json.dumps({"problems": sorted(set(problems)), "http_requests_5m": len(statuses),
                      "ops_snapshots_5m": snapshots, "disk_used_bytes": disk.used,
                      "load_average": load, "host_memory_bytes": memory,
                      "containers": container_stats}))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
