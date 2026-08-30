#!/usr/bin/env python3
"""Bounded read-only smoke/load probe for a local ShipTrip environment.

The runner refuses non-loopback hosts, caps request/concurrency values, sends
only GET requests, and never calls checkout/webhook/mutation routes.  It uses
only the Python standard library so it can run in CI or a clean workstation.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


SAFE_HOSTS = {"127.0.0.1", "localhost", "::1"}
DEFAULT_PATHS = ("/healthz", "/readyz")


@dataclass(frozen=True)
class Sample:
    path: str
    status: int
    elapsed_ms: float


def _bounded_int(name: str, value: int, *, minimum: int, maximum: int) -> int:
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _request(base_url: str, path: str, bearer: str) -> Sample:
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    headers = {"User-Agent": "shiptrip-local-load-test/1"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers=headers, method="GET"), timeout=10
        ) as response:
            response.read(1024)
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except (OSError, TimeoutError):
        status = 0
    return Sample(path, status, (time.perf_counter() - started) * 1000)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--requests", type=int, default=40)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--path", action="append", dest="paths")
    parser.add_argument(
        "--bearer-env",
        default="",
        help="Name of an environment variable containing a test JWT (never printed).",
    )
    args = parser.parse_args()

    parsed = urllib.parse.urlparse(args.base_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in SAFE_HOSTS:
        parser.error("--base-url must target localhost/loopback")
    try:
        count = _bounded_int("requests", args.requests, minimum=1, maximum=5000)
        concurrency = _bounded_int(
            "concurrency", args.concurrency, minimum=1, maximum=50
        )
    except ValueError as exc:
        parser.error(str(exc))

    paths = tuple(args.paths or DEFAULT_PATHS)
    forbidden = ("checkout", "webhook", "refund", "handover", "admin/")
    if any(not path.startswith("/") or any(term in path for term in forbidden) for path in paths):
        parser.error("paths must be absolute read-only non-financial/non-admin routes")
    bearer = os.environ.get(args.bearer_env, "") if args.bearer_env else ""

    work = [paths[index % len(paths)] for index in range(count)]
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        samples = list(pool.map(lambda path: _request(args.base_url, path, bearer), work))
    wall_seconds = time.perf_counter() - started

    latencies = sorted(sample.elapsed_ms for sample in samples)
    errors = sum(not 200 <= sample.status < 400 for sample in samples)
    p95_index = min(len(latencies) - 1, int(len(latencies) * 0.95))
    report = {
        "target": args.base_url,
        "requests": len(samples),
        "concurrency": concurrency,
        "duration_seconds": round(wall_seconds, 3),
        "requests_per_second": round(len(samples) / wall_seconds, 2),
        "latency_ms": {
            "median": round(statistics.median(latencies), 2),
            "p95": round(latencies[p95_index], 2),
            "max": round(max(latencies), 2),
        },
        "errors": errors,
        "status_counts": {
            str(status): sum(sample.status == status for sample in samples)
            for status in sorted({sample.status for sample in samples})
        },
    }
    print(json.dumps(report, indent=2))
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
