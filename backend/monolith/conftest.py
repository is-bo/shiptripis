"""Test-session setup.

Two things live here: the CI shard options (``--shard``, ``--shard-report``;
the rules are in `config.test_shards`), and a forward-compatibility shim for
the interpreter a developer happens to have, not for the one the product ships
on. CI and the container image both pin Python 3.12 (`.github/workflows/ci.yml`,
`backend/monolith/Dockerfile`); the shim does nothing there.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from config import test_shards


def _patch_template_context_copy() -> None:
    """Django 5.1 cannot copy a template context on Python 3.14.

    `BaseContext.__copy__` is written as `duplicate = copy(super())`. Copying a
    `super` proxy returned a real instance up to Python 3.13; from 3.14 it
    returns the proxy, and the next line — `duplicate.dicts = ...` — raises
    `AttributeError`. It fires inside `InclusionAdminNode`, so on 3.14 every
    admin changelist and change form 500s and every test that renders one
    fails, with nothing wrong in this codebase.

    Django fixes this upstream. Until the pinned version moves, this restores
    the pre-3.14 behaviour so an admin test means what it says on whichever
    interpreter it is run with.
    """

    if sys.version_info < (3, 14):
        return
    from django.template.context import BaseContext

    def __copy__(self):  # noqa: N807 - matching the name being replaced
        duplicate = BaseContext.__new__(type(self))
        duplicate.__dict__.update(self.__dict__)
        duplicate.dicts = self.dicts[:]
        return duplicate

    BaseContext.__copy__ = __copy__


_patch_template_context_copy()


# -- CI shards ------------------------------------------------------------------


def pytest_addoption(parser) -> None:
    group = parser.getgroup("shards", "CI test shards")
    group.addoption(
        "--shard",
        default=None,
        help="Run only shard K of N, by whole test file (K/N, 1-based).",
    )
    group.addoption(
        "--shard-report",
        default=None,
        help="Write the files this run collected and ran, with seconds per file.",
    )


def pytest_configure(config) -> None:
    value = config.getoption("--shard")
    try:
        shard = test_shards.parse_shard(value) if value else None
    except ValueError as exc:
        raise pytest.UsageError(str(exc)) from None
    if shard is not None or config.getoption("--shard-report"):
        config.pluginmanager.register(
            _ShardPlugin(shard, config.getoption("--shard-report")), "wassla-shards"
        )


class _ShardPlugin:
    def __init__(self, shard: tuple[int, int] | None, report_path: str | None) -> None:
        self.shard = shard
        self.report_path = report_path
        self.collected: list[str] = []
        self.collected_tests = 0
        self.files: list[str] = []
        self.tests = 0
        self.durations: list[tuple[str, float]] = []

    @pytest.hookimpl(trylast=True)  # after pytest-django has ordered the items
    def pytest_collection_modifyitems(self, config, items) -> None:
        file_of = test_shards.file_of
        self.collected = sorted({file_of(item.nodeid) for item in items})
        self.collected_tests = len(items)
        if self.shard is not None:
            index, total = self.shard
            weights = json.loads(test_shards.DURATIONS_FILE.read_text(encoding="utf-8"))
            mine = set(test_shards.assign(self.collected, weights, total)[index - 1])
            dropped = [item for item in items if file_of(item.nodeid) not in mine]
            if dropped:
                config.hook.pytest_deselected(items=dropped)
            items[:] = [item for item in items if file_of(item.nodeid) in mine]
        self.files = sorted({file_of(item.nodeid) for item in items})
        self.tests = len(items)

    def pytest_report_collectionfinish(self, config, items):
        if self.shard is None:
            return None
        return (
            f"shard {self.shard[0]}/{self.shard[1]}: {len(self.files)} of "
            f"{len(self.collected)} test files, {self.tests} of "
            f"{self.collected_tests} tests"
        )

    def pytest_runtest_logreport(self, report) -> None:
        # Setup carries class and module fixtures, so a file's first test
        # reports what building that file's world costs.
        self.durations.append((report.nodeid, report.duration))

    def pytest_sessionfinish(self, session, exitstatus) -> None:
        if not self.report_path:
            return
        Path(self.report_path).write_text(
            json.dumps(
                test_shards.report(
                    shard=self.shard or (1, 1),
                    collected=self.collected,
                    collected_tests=self.collected_tests,
                    files=self.files,
                    tests=self.tests,
                    durations=self.durations,
                ),
                indent=1,
            ),
            encoding="utf-8",
        )
