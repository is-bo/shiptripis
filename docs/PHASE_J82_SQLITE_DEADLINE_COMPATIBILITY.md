# J8.2 — SQLite review deadline compatibility

## Scope and finding

`DEF-ADM-01` affected `with_review_deadline()` in
`backend/monolith/apps/ratings/services.py`. The existing query multiplied a
per-Deal integer number of review seconds by `Value(timedelta(seconds=1))`.
Django's SQLite compiler rejects that mixed SQL multiplication with
`DatabaseError: Invalid arguments for operator *`. The new regression test
reproduced this failure before the implementation changed.

The seconds value is **not a constant**. For pre-column Deals it comes from the
Deal's frozen `lifecycle_policy.rating_review_window_seconds`; the fallback is
1,209,600 seconds (14 days). Normal delivery confirmation stores the deadline
in `rating_window_ends_at`, which remains the first choice in `Coalesce`.
The Python lifecycle fallback also reads the frozen policy. A constant
14-day duration in the SQL query would therefore alter historical Deal behavior.

After replacing the multiplication, the SQLite test also exposed a second
incompatibility in the old JSON comparison: its nested `Cast(..., JSONField())`
compiled a malformed JSON path. PostgreSQL supports the original interval
arithmetic and keeps the original JSON value check.

## Fix and equivalence

The SQLite branch checks `json_type(...) = 'integer'` and the existing
nonnegative, at-most-10-digit regex before casting the frozen policy value.
It multiplies the resulting seconds by 1,000,000 integer microseconds and
wraps that value as a Django `DurationField` expression. Django then adds it
to `delivery_confirmed_at` in SQL. Numeric strings, booleans, negative values,
and overlength values continue to use the 14-day fallback.

The PostgreSQL branch retains the original seconds expression and
`seconds * Value(timedelta(seconds=1))`. No raw SQL, migration, schema change,
Python row transform, or product change was introduced. `with_review_deadline`
still returns a QuerySet alias usable for annotation, filtering, ordering,
and the correlated `resolved_notifications()` query. Django `DateTimeField`
conversion continues to return timezone-aware datetimes.

For a Deal confirmed at `2026-09-01 12:00 UTC` with the default 14-day
window, the computed deadline is `2026-09-15 12:00 UTC`. The notification is
unresolved one microsecond before that instant and resolved at and after it.
The rating window and blind reveal use the same exclusive open-window
boundary. A frozen seven-day policy computes `2026-09-08 12:00 UTC`; an
already-rated sender's prompt resolves while the unrated traveler's prompt
remains open until the deadline. The counterparty rating stays blind before
the deadline and becomes visible at it.

## Codex verification

Settings: `DJANGO_SETTINGS_MODULE=config.settings.test_local` (in-memory
SQLite). The focused regression initially failed against the old expression
with the reported `Invalid arguments for operator *` error.

- New SQLite regression, existing J1 rating notification test, existing rating
  window tests, and existing blind/reveal tests: **10 passed**.
- Changed Python files: `ruff format` and `ruff check` passed.
- Schema drift (`manage.py makemigrations --check --dry-run`): **No changes detected**.
- `git diff --check`: **passed**.
- Full Django, broad backend, full PostgreSQL, and repository-wide checks:
  intentionally reserved for Gemini.

## Gemini verification handoff

The owner will receive this copy-paste prompt in the Codex handoff with
`<IMPLEMENTATION_SHA>` replaced by the exact committed SHA:

> Gemini, independently verify ShipTrip J8.2 at the immutable commit
> `<IMPLEMENTATION_SHA>` on branch `codex/j82-sqlite-review-deadline`. Check out
> that exact SHA, report `git rev-parse HEAD` and worktree status, and do not
> modify product behavior, configuration, schema, or the commit under test.
> Use the environment and service setup from `.github/workflows/ci.yml` for
> PostgreSQL and Redis. Keep Stripe and Chargily in TEST and
> `PAYOUT_DZD_EXECUTION_ENABLED=false`; do not use LIVE or real money.
>
> From `backend/monolith`, run on SQLite with
> `--ds=config.settings.test_local`: the new
> `apps/ratings/tests/test_sqlite_review_deadline.py`, all
> `apps/ratings/tests/test_ratings.py`, and the focused notification-resolution
> cases in `apps/deals/tests/test_phase_j1.py` (at least
> `test_rating_submission_resolves_prompt_and_preserves_blindness`). Identify
> and run any other directly relevant notification-resolution tests.
>
> Repeat the new deadline regression, ratings suite, and notification-resolution
> cases against real PostgreSQL with `--ds=config.settings.dev`. If practical,
> run the full Django test suite against PostgreSQL as CI does. Run
> `ruff check .`, `python manage.py makemigrations --check --dry-run`, the
> deployment safety tests, the production-profile
> `python manage.py check --deploy --fail-level WARNING` with CI-equivalent
> safe dummy variables, and root `python tools/check_static_web.py`.
>
> Inspect and explicitly report before, exactly at, and after the review
> deadline; 14-day default and frozen per-Deal duration; already-rated state;
> one-sided blind/reveal behavior; and resolution of `rating.prompt` and
> `rating.required`. State whether SQLite and PostgreSQL semantics match.
> Report every exact command, test counts, failures verbatim, unavailable
> checks and why, and a final PASS/FAIL. Return the report to the owner for
> Codex review. Do not merge, push, deploy, or build an APK.

Gemini returned results: **pending owner report**.

## Release record

- Implementation branch: `codex/j82-sqlite-review-deadline`.
- Implementation SHA: supplied in the Codex handoff (the commit cannot name
  its own SHA inside this file).
- CI: pending Gemini green evidence and finalization.
- Railway TEST deployment: decision pending merge. The production PostgreSQL
  expression remains unchanged, and the new calculation is SQLite-only. If
  Gemini verifies PostgreSQL equivalence, no runtime TEST deployment is
  expected to be necessary under the task's deployment rule.
- Provider configuration: unchanged. Stripe TEST, Chargily TEST, and
  `PAYOUT_DZD_EXECUTION_ENABLED=false` remain the safety requirements; no LIVE
  or real-money execution was performed.
- APK: **NOT BUILT**.
