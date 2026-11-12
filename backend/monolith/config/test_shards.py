"""Split the Django test suite into parallel CI shards, by whole test file.

CI runs the suite as N jobs (`.github/workflows/ci.yml`, job `django-shard`),
each started with ``--shard=K/N``; the pytest options live in the root
``conftest.py``. Every job collects the whole suite and keeps only its own
files, so a file's module and class fixtures are built once, in one
job, exactly as in a single run.

Files are shared out by the longest-processing-time rule over the measured
seconds per file in ``test_durations.json``: heaviest file first, each to the
shard with the least work so far. A file missing from the measurements (a new
test file) counts as an average file. The assignment depends only on the
collected file list and the measurements, so every job computes the same one.

Nothing is optional: with ``--shard-report=PATH`` each job writes what it
collected and what it ran, and ``python config/test_shards.py verify DIR``
(the ``Django — migrations + tests + lint`` job) fails unless the reports
together ran every collected file exactly once.

Refreshing the measurements, when the shards drift apart: download a green
run's ``django-shard-report-*`` artifacts into one directory and run
``python config/test_shards.py merge DIR > config/test_durations.json``.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

DURATIONS_FILE = Path(__file__).with_name("test_durations.json")


def parse_shard(value: str) -> tuple[int, int]:
    """``"K/N"`` as ``(K, N)``, with 1 <= K <= N."""

    try:
        index, total = (int(part) for part in value.split("/"))
    except ValueError:
        raise ValueError(f"--shard takes K/N, for example 2/4, not {value!r}") from None
    if not 1 <= index <= total:
        raise ValueError(f"--shard {value}: K must be between 1 and N")
    return index, total


def assign(files: list[str], weights: dict[str, float], shards: int) -> list[list[str]]:
    """Share ``files`` out over ``shards`` bins, heaviest first, least-loaded bin."""

    known = [weights[name] for name in files if name in weights]
    default = sum(known) / len(known) if known else 1.0
    loads = [0.0] * shards
    bins: list[list[str]] = [[] for _ in range(shards)]
    for name in sorted(files, key=lambda name: (-weights.get(name, default), name)):
        target = min(range(shards), key=lambda index: (loads[index], index))
        bins[target].append(name)
        loads[target] += weights.get(name, default)
    return [sorted(names) for names in bins]


def file_of(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


def report(*, shard, collected, collected_tests, files, tests, durations) -> dict:
    """One job's shard report: what it collected, what it ran, seconds per file."""

    seconds: dict[str, float] = defaultdict(float)
    for nodeid, duration in durations:
        seconds[file_of(nodeid)] += duration
    index, total = shard
    return {
        "shard": index,
        "of": total,
        "collected": collected,
        "collected_tests": collected_tests,
        "files": files,
        "tests": tests,
        "seconds": {name: round(seconds[name], 2) for name in sorted(seconds)},
    }


# -- command line: verify and merge reports -----------------------------------


def _load_reports(directory: str) -> list[dict]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(Path(directory).rglob("*.json"))
    ]


def verify(reports: list[dict]) -> list[str]:
    """Why the reports do not add up to one whole run, or nothing.

    The number of shards is the one the jobs ran with, so a job that never
    reported is caught by the others.
    """

    if not reports:
        return ["no shard reports"]
    totals = {report["of"] for report in reports}
    if len(totals) != 1:
        return [f"the shards ran with different totals: {sorted(totals)}"]
    shards = totals.pop()
    problems = []
    if sorted(report["shard"] for report in reports) != list(range(1, shards + 1)):
        problems.append(
            f"expected one report from each of shards 1..{shards}, got "
            f"{sorted(report['shard'] for report in reports)}"
        )
    collected = {tuple(report["collected"]) for report in reports}
    if len(collected) != 1:
        problems.append("the shards collected different test files")
    counts = {report["collected_tests"] for report in reports}
    if len(counts) != 1:
        problems.append("the shards collected different numbers of tests")
    if problems:
        return problems
    everything = set(reports[0]["collected"])
    ran: dict[str, int] = defaultdict(int)
    for report in reports:
        for name in report["files"]:
            ran[name] += 1
    missing = sorted(everything - set(ran))
    twice = sorted(name for name, count in ran.items() if count > 1)
    if missing:
        problems.append(f"{len(missing)} test files ran in no shard: {missing[:10]}")
    if twice:
        problems.append(f"{len(twice)} test files ran in more than one shard: {twice[:10]}")
    total = sum(report["tests"] for report in reports)
    if total != reports[0]["collected_tests"]:
        problems.append(
            f"the shards ran {total} tests but {reports[0]['collected_tests']} were collected"
        )
    return problems


def merge(reports: list[dict]) -> dict[str, float]:
    seconds: dict[str, float] = {}
    for report in reports:
        seconds.update(report["seconds"])
    return {name: seconds[name] for name in sorted(seconds)}


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "verify":
        reports = _load_reports(argv[1])
        problems = verify(reports)
        for problem in problems:
            print(f"::error::{problem}")
        if not problems:
            for report in sorted(reports, key=lambda report: report["shard"]):
                print(
                    f"shard {report['shard']}/{report['of']}: {len(report['files'])} files, "
                    f"{report['tests']} tests, {sum(report['seconds'].values()) / 60:.1f} min"
                )
            print(
                f"all {len(reports[0]['collected'])} test files and "
                f"{reports[0]['collected_tests']} tests ran exactly once"
            )
        return 1 if problems else 0
    if len(argv) == 2 and argv[0] == "merge":
        print(json.dumps(merge(_load_reports(argv[1])), indent=1))
        return 0
    print(__doc__)
    print("usage: test_shards.py verify DIR | merge DIR", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
