# L4C: Housekeeping (test time limit, backup ferry distances)

Package L4C of `docs/WASSLA_DISCOVERY_PRO_PLAN.md` (Opus, high effort), added on 2026-11-12 from two
carry-overs on the board. No product behaviour changes for members; no migration.

## 1. The Django CI job no longer runs out of time

**Before.** One job, `Django — migrations + tests + lint`, ran the whole suite in 33 to 44 minutes
against `timeout-minutes: 45`; L4A's first attempt was cancelled at 87%. Measured on L4A's last green
run (`caa57eb`, run 43220665143): pytest step 41 min 55 s, job 43 min 13 s, 4% of the limit unused.
Locally (PostgreSQL 16, 4 cores) the same suite ran 2,703 tests in 31 min 51 s. On CI runners the
tests add up to 39.8 minutes; the heaviest file, `apps/finance/tests/test_phase8fh5_control_plane.py`,
takes 5.2 minutes, so four shards stay well above the floor that one file sets.

**After.** Four parallel jobs, `django-shard` (shards 1 to 4, `timeout-minutes: 25` each,
`fail-fast: false`), each with its own PostgreSQL and Redis service.

Both runs reported "all 153 test files and 2722 tests ran exactly once".

| Run | Commit | Slowest shard job | Limit unused |
| --- | --- | --- | --- |
| 1 (run 43272745554), split from local measurements | `d278922` | shard 1: 13 min 10 s (pytest 11 min 53 s); others 10 min 12 s to 11 min 17 s | 47% |
| 2 (run 43275407631), split from CI measurements | `2bd7e62` | shard 3: 13 min 8 s (tests 11.7 min); others 9 min 47 s to 12 min 36 s | 47% |

How it works:

- `backend/monolith/config/test_shards.py` decides the split: **whole test files**, so a file's
  module and class fixtures are still built once, shared out by longest-processing-time (heaviest
  file first, to the shard with the least work so far) over the measured seconds per file in
  `config/test_durations.json`. A file without a measurement counts as an average file. The
  assignment depends only on the collected files and the measurements, so every job computes the
  same one.
- The options `--shard=K/N` and `--shard-report=PATH` are registered in the root `conftest.py`. The
  shard total is the matrix size (`strategy.job-total`), so adding a shard is one matrix entry.
- **The required check keeps its name.** `Django — migrations + tests + lint` is now a small job
  that `needs` the shards and runs `if: always()`. It fails unless every shard passed, then runs
  `python config/test_shards.py verify`, which fails unless the shards' reports show the same
  collected suite, one report per shard, every collected test file run in exactly one shard, and the
  test counts adding up to the collected total. A shard that is cancelled, skipped or silently drops
  files therefore turns the check red.
- `ruff check .` and `makemigrations --check` run in shard 1 only (they read the whole tree); every
  shard runs `migrate` on its own database.
- `config/test_durations.json` holds the seconds per file measured on CI runners in run 1 (merged from
  its four shard reports). Run 1 itself was split from a local measurement, which is why its shards
  were less even.
- No test is skipped, deleted, marked or moved out of the pull-request run.
- **Refreshing the measurements** when shards drift apart: download a green run's
  `django-shard-report-*` artifacts into one directory and run
  `python config/test_shards.py merge DIR > config/test_durations.json`. The test
  `test_the_measurements_cover_the_suite_as_committed` fails if a measured file no longer exists.
  Add a shard to the matrix when the slowest one passes 60% of its limit.

## 2. L3A's backup ferry distances are removed

Every launch-country city has catalogue coordinates since pull request #27, so a crossing's distance
always came from them; the backup was dead. Proof, in this order:

1. Commit `2a1e29d` added `apps/locations/tests/test_l4c_shipped_crossings.py` on the old code, where
   it passed. It imports the slice of the bundled catalogue that `resolve_port` can see for the
   shipped port names (every active city whose name or alternate name normalizes to a port name, with
   its parents, so a shared name stays ambiguous), seeds the shipped list, and pins:
   - every port resolves to one catalogue city with coordinates;
   - the seed creates all 38 crossings, 0 skipped, with the file's active flags;
   - each crossing's distance in metres, equal to the catalogue great-circle distance;
   - for a 2 kg parcel sailing port to port on each of the 24 live directions, created through
     `POST /api/journeys`: the leg's distance, a compatible match by `great_circle_sea_crossing`, the
     matched distance, and the minimum and recommended reward.
2. Commit `241a028` removed the backup. The same test passes unchanged, so no seeded crossing's
   distance, price or match changed.

Removed:

- the `latitude` and `longitude` of every port in `apps/locations/data/sea_crossings.json` (a port is
  now its country and catalogue city name), and the seed command's fallback to them;
- the `distance_km` parameter of `create_crossing`, its range check, error codes
  `sea_crossing_distance_required` and `sea_crossing_distance_invalid`, and
  `MAX_CROSSING_DISTANCE_KM`;
- the "Distance in kilometres" field of the console's "Add a crossing" form.

Now a city without catalogue coordinates cannot become a port: `create_crossing` refuses with
`sea_crossing_coordinates_missing` (shown as a form error in the console) and the seed skips that
crossing with a report. No column changed: `SeaCrossing.distance_meters` is still written, from the
catalogue coordinates only, and read by the sea-leg snapshot exactly as before. The test world in
`apps/trips/tests/sea_world.py` keeps French and Spanish cities without coordinates on purpose, so
the road distance-floor crash guard and the new refusal stay proved.

## 3. Tests

Django: 2,703 passed before (integration branch at `e4c2530`); 2,722 passed after, 0 skipped.

- Added: `apps/locations/tests/test_l4c_shipped_crossings.py` (4),
  `apps/core/tests/test_ci_test_shards.py` (14: the split covers every file once, is deterministic,
  balances by weight, refuses a malformed `--shard`; `verify` catches a missing shard, a dropped
  file, a file run twice, a short test count and shards that collected different suites; the
  measurements name only files that exist), and one console test (the form asks for no distance).
- Rewritten to the new rule: in `test_l3a_routes.py`, "a city without coordinates needs a stated
  distance" became "cannot be a port", the duplicate-crossing check uses two cities with
  coordinates, and the seed test gives Marseille its catalogue coordinates and checks a
  coordinate-less port is skipped; in `test_l3b_console.py` the add-a-crossing tests use Oran to
  Algiers (both with coordinates) and "needs a distance" became "is refused".
- `ruff check .` and `makemigrations --check` clean. No migration, so no schema change.

## 4. Screenshots

None: no app screen changes. The console's "Add a crossing" form loses one optional field.
