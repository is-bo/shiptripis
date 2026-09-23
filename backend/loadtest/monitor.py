"""Sample server-side resource use while a load run is in progress.

Every ``--interval`` seconds it records, for each process ``serve.py`` started
(plus any ``--pid name=PID`` you add, e.g. a Go realtime service):

* resident memory (RSS / Windows working set) and CPU % of one core;
* whole-machine CPU %, so the load generator's own share is visible;
* PostgreSQL backends on the load database by state (``pg_stat_activity``),
  and the sum of the cluster's ``postgres`` process memory.

    python backend/loadtest/monitor.py --out .data/run-100-monitor.csv

Stop it with Ctrl+C (or ``--duration``); it prints min/avg/max per column.
Run it with the monolith venv's interpreter (it needs psutil and psycopg).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import time
from pathlib import Path

import psutil
import psycopg

LOADTEST_DIR = Path(__file__).resolve().parent
DATA_DIR = LOADTEST_DIR / ".data"


def _dsn() -> str:
    pgdata = os.environ.get("LOADTEST_PGDATA", "").strip()
    if pgdata:
        import pgserver

        return pgserver.get_server(pgdata, cleanup_mode=None).get_uri()
    return (
        f"host={os.environ['POSTGRES_HOST']} port={os.environ.get('POSTGRES_PORT', '5432')} "
        f"user={os.environ['POSTGRES_USER']} password={os.environ.get('POSTGRES_PASSWORD', '')} "
        "dbname=postgres"
    )


def _postgres_rss_mb(pgdata: str) -> float:
    if not pgdata:
        return 0.0
    needle = Path(pgdata).as_posix().lower()
    postmasters = []
    for proc in psutil.process_iter(["name", "cmdline"]):
        name = (proc.info["name"] or "").lower()
        cmdline = " ".join(proc.info["cmdline"] or []).replace("\\", "/").lower()
        if name.startswith("postgres") and needle in cmdline:
            postmasters.append(proc)
    total = 0
    seen: set[int] = set()
    for master in postmasters:
        try:
            family = [master, *master.children(recursive=True)]
        except psutil.Error:
            continue
        for proc in family:
            if proc.pid in seen:
                continue
            seen.add(proc.pid)
            try:
                total += proc.memory_info().rss
            except psutil.Error:
                pass
    return round(total / 2**20, 1)


def _resolve(proc: psutil.Process) -> psutil.Process:
    """Follow launcher processes to the interpreter that does the work.

    A Windows venv ``python.exe`` is a 4 MB launcher that starts the real
    interpreter as its only child; measuring the launcher would report nothing.
    """

    while True:
        try:
            children = proc.children()
        except psutil.Error:
            return proc
        if len(children) != 1:
            return proc
        proc = children[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out", default=str(DATA_DIR / "monitor.csv"))
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--duration", type=float, default=0, help="seconds; 0 = until Ctrl+C")
    parser.add_argument("--pid", action="append", default=[], help="extra process as name=PID")
    parser.add_argument("--db", default=os.environ.get("LOADTEST_DB_NAME", "shiptrip_load"))
    args = parser.parse_args()

    serve_state = json.loads((DATA_DIR / "serve.json").read_text(encoding="utf-8"))
    processes = {
        name: _resolve(psutil.Process(pid)) for name, pid in serve_state["processes"].items()
    }
    for item in args.pid:
        name, pid = item.split("=", 1)
        processes[name] = _resolve(psutil.Process(int(pid)))
    for proc in processes.values():
        proc.cpu_percent(None)
    psutil.cpu_percent(None)

    pgdata = os.environ.get("LOADTEST_PGDATA", "").strip()
    conn = psycopg.connect(_dsn(), autocommit=True)
    columns = ["t"]
    for name in processes:
        columns += [f"{name}_rss_mb", f"{name}_cpu_pct"]
    columns += [
        "web_rss_mb_total",
        "machine_cpu_pct",
        "db_conns_total",
        "db_conns_active",
        "db_conns_idle",
        "db_conns_cluster",
        "postgres_rss_mb",
    ]
    rows: list[dict] = []
    started = time.monotonic()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        try:
            while not args.duration or time.monotonic() - started < args.duration:
                time.sleep(args.interval)
                row: dict = {"t": round(time.monotonic() - started, 1)}
                web_total = 0.0
                for name, proc in processes.items():
                    try:
                        rss = proc.memory_info().rss / 2**20
                        cpu = proc.cpu_percent(None)
                    except psutil.Error:
                        rss, cpu = 0.0, 0.0
                    row[f"{name}_rss_mb"] = round(rss, 1)
                    row[f"{name}_cpu_pct"] = round(cpu, 1)
                    if name.startswith("web-"):
                        web_total += rss
                row["web_rss_mb_total"] = round(web_total, 1)
                row["machine_cpu_pct"] = psutil.cpu_percent(None)
                states = dict(
                    conn.execute(
                        "SELECT state, count(*) FROM pg_stat_activity "
                        "WHERE datname = %s AND pid <> pg_backend_pid() GROUP BY state",
                        (args.db,),
                    ).fetchall()
                )
                row["db_conns_total"] = sum(states.values())
                row["db_conns_active"] = states.get("active", 0)
                row["db_conns_idle"] = states.get("idle", 0) + states.get(
                    "idle in transaction", 0
                )
                row["db_conns_cluster"] = conn.execute(
                    "SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend'"
                ).fetchone()[0]
                row["postgres_rss_mb"] = _postgres_rss_mb(pgdata)
                writer.writerow(row)
                handle.flush()
                rows.append(row)
        except KeyboardInterrupt:
            pass

    if rows:
        print(f"{len(rows)} samples -> {out}")
        for column in columns[1:]:
            values = [float(row[column]) for row in rows]
            print(
                f"{column:>28}: min {min(values):8.1f}  avg "
                f"{statistics.fmean(values):8.1f}  max {max(values):8.1f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
