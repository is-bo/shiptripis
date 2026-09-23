"""Measure a Go realtime service's memory per idle WebSocket connection.

Start the service (e.g. the chat relay built from ``backend/services/cmd/chat``)
against the load database and Redis, then::

    python backend/loadtest/ws_memory.py --service-pid 1234 \
        --wsprobe path/to/wsprobe.exe --url ws://127.0.0.1:8081/ws/chat

It drives ``tools/cmd/wsprobe`` in steps, reads the service's resident memory
once connections settle at each step, and prints the least-squares slope in
KiB per connection. Idle connections are the realistic steady state: a mobile
client holds one socket per realtime service while the app is open.
"""

from __future__ import annotations

import argparse
import statistics
import subprocess
import time
from pathlib import Path

import psutil

DATA_DIR = Path(__file__).resolve().parent / ".data"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--service-pid", type=int, required=True)
    parser.add_argument("--wsprobe", required=True)
    parser.add_argument("--url", default="ws://127.0.0.1:8081/ws/chat")
    parser.add_argument("--tokens", default=str(DATA_DIR / "world.json"))
    parser.add_argument("--step", type=int, default=250)
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--settle", type=float, default=4.0)
    args = parser.parse_args()

    service = psutil.Process(args.service_pid)
    baseline = service.memory_info().rss / 2**20
    print(f"idle service RSS: {baseline:.1f} MiB")
    probe = subprocess.Popen(
        [
            args.wsprobe,
            "-url", args.url,
            "-tokens", args.tokens,
            "-step", str(args.step),
            "-steps", str(args.steps),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    points: list[tuple[int, float]] = [(0, baseline)]
    assert probe.stdout is not None and probe.stdin is not None
    for line in probe.stdout:
        if not line.startswith("step "):
            continue
        fields = dict(part.split("=") for part in line.split()[1:])
        time.sleep(args.settle)
        rss = service.memory_info().rss / 2**20
        connected = int(fields["connected"])
        points.append((connected, rss))
        print(
            f"connections {connected:>6}  failed {fields['failed']:>4}  "
            f"service RSS {rss:8.1f} MiB  threads {service.num_threads()}"
        )
        probe.stdin.write("\n")
        probe.stdin.flush()
    probe.stdin.close()
    probe.wait(timeout=60)

    if len(points) > 2:
        xs = [float(x) for x, _ in points]
        ys = [y for _, y in points]
        slope = statistics.linear_regression(xs, ys).slope
        print(f"slope: {slope * 1024:.1f} KiB per idle connection")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
