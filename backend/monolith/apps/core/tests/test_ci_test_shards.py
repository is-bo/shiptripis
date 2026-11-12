"""L4C: the CI shards share out the whole suite, and the check proves it.

`config.test_shards` decides which test files each CI job runs and checks the
jobs' reports afterwards. A bug there would silently drop tests from every
pull request, so the rules are pinned here without a database.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from config import test_shards

FILES = [f"apps/x/tests/test_{name}.py" for name in "abcdefghij"]
WEIGHTS = {FILES[0]: 600.0, FILES[1]: 300.0, FILES[2]: 300.0, FILES[3]: 30.0}


def test_every_file_lands_in_exactly_one_shard():
    for shards in (1, 2, 3, 4, 7, 12):
        bins = test_shards.assign(FILES, WEIGHTS, shards)
        assert len(bins) == shards
        flat = [name for names in bins for name in names]
        assert sorted(flat) == sorted(FILES), shards


def test_the_assignment_depends_only_on_the_files_and_weights():
    assert test_shards.assign(FILES, WEIGHTS, 4) == test_shards.assign(
        list(reversed(FILES)), dict(reversed(WEIGHTS.items())), 4
    )


def test_the_heaviest_file_goes_first_to_the_least_loaded_shard():
    a, b, c, d = FILES[:4]

    assert test_shards.assign([a, b, c, d], WEIGHTS, 2) == [[a, d], [b, c]]
    # Unmeasured files weigh the same, so they alternate in name order.
    assert test_shards.assign(FILES[4:], {}, 2) == [FILES[4:][0::2], FILES[4:][1::2]]


@pytest.mark.parametrize("value", ["", "0/4", "5/4", "2", "a/b", "2/4/1"])
def test_a_malformed_shard_is_refused(value):
    with pytest.raises(ValueError):
        test_shards.parse_shard(value)


def _reports(shards: int) -> list[dict]:
    bins = test_shards.assign(FILES, WEIGHTS, shards)
    return [
        test_shards.report(
            shard=(index + 1, shards),
            collected=FILES,
            collected_tests=len(FILES) * 2,
            files=names,
            tests=len(names) * 2,
            durations=[(f"{name}::test_one", 1.0) for name in names],
        )
        for index, names in enumerate(bins)
    ]


def test_complete_reports_verify():
    assert test_shards.verify(_reports(4)) == []


def test_a_missing_shard_or_file_fails_the_check():
    reports = _reports(4)
    assert test_shards.verify(reports[:3])
    assert test_shards.verify([]) == ["no shard reports"]

    dropped = _reports(4)
    dropped[1]["files"] = dropped[1]["files"][1:]
    dropped[1]["tests"] -= 2
    assert any("ran in no shard" in problem for problem in test_shards.verify(dropped))


def test_a_file_run_twice_or_a_short_count_fails_the_check():
    doubled = _reports(4)
    doubled[0]["files"] = doubled[0]["files"] + doubled[1]["files"][:1]
    assert any("more than one shard" in problem for problem in test_shards.verify(doubled))

    short = _reports(4)
    short[2]["tests"] -= 1
    assert any("tests but" in problem for problem in test_shards.verify(short))


def test_shards_that_collected_different_suites_fail_the_check():
    reports = _reports(2)
    reports[1]["collected"] = FILES[:-1]
    assert test_shards.verify(reports)


def test_the_measurements_cover_the_suite_as_committed():
    weights = json.loads(test_shards.DURATIONS_FILE.read_text(encoding="utf-8"))
    root = test_shards.DURATIONS_FILE.parents[1]
    assert weights, "config/test_durations.json is empty"
    assert all(value >= 0 for value in weights.values())
    # Every measured file still exists, so a rename cannot leave a stale
    # weight that skews the split.
    assert [name for name in weights if not (root / Path(name)).is_file()] == []
