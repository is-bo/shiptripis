# Post-funding DZD payout setup reconciliation

## Incident and cause

TEST Payout #8 was funded while the Traveler's enabled DZD method had no
profile. Its immutable funding snapshot points to instruction version #14 with
no DZD profile revision. Later the Traveler submitted a profile and crossed
cheque, creating version #48 and profile revision #4, which Admin approved.
The prior Admin approval sweeper only selected payouts whose *funding snapshot*
already pointed to that profile, so the payout remained blocked with
`payout_setup_required`. The database trigger correctly prohibited changing its
active instruction without an amendment row.

## Reconciliation contract

`complete_initial_dzd_setup` is the sole transition for the empty funded slot.
It serializes on the Deal, Payout, and method, then requires a versioned,
unpaid manual DZD payout whose immutable funding and active instruction are
still the same no-profile version. The funding attempt and FX snapshot must be
present. The Traveler's currently enabled and ready method must carry a newer
version and approved profile, with both the submission and consent recorded
after funding. That version must have been created by the same Traveler under
the profile policy. No instruction change or payout attempt may already exist.
The current approved profile must pass evidence, identity, and KYC checks.

The Traveler's explicit profile submission and version consent authorize
completion of this *initial setup*. It does not authorize changing a real
funded destination. An existing destination still uses the separate Traveler
confirmation and Admin amendment workflow. A qualifying completion creates
`PayoutInstructionAmendment` with reason `initial_payout_setup_completed`, an
event, and an Admin action recording the old/new version, profile revision,
actor, and source. The PostgreSQL trigger sees the amendment and permits the
active-instruction change. The original method version, profile snapshot
(still null), EUR/DZD amounts, FX, funding rail, ledger, and Deal economics do
not change. Replays create no additional amendment or event; repeated
approval against the same identity/name check reuses its existing review.

Approval commits its method review before scanning payouts. This preserves
the Deal-first lock order for reconciliation and avoids a method-to-Deal lock
cycle with funding or release. The same service runs for console and API
approvals. Once bound, normal-delivery payouts run the existing release
evaluator. Settlement awards use a separate recheck of the recorded amount
revision, protection state, and disputes. Finance holds remain an independent
manual-transfer gate. Neither path forces `eligible` through an open protection
period or dispute. A committed
amendment whose release recheck was interrupted is discoverable for retry.

## Cancellation compensation and Admin presentation

`delivery_protection` and `schedule_floor` keep the normal confirmed-delivery
and live-balance checks. `cancellation_compensation` and
`dispute_settlement` are recorded settlement awards and do not require a
successful delivery or an *open* balance order. The manual preparation gate
requires the award revision, valid DZD amount and profile, no active
dispute/hold, any applicable protection period, and enough unrefunded,
unreserved captured funding. The Admin presenter follows the same distinction
and no longer shows `delivery_unconfirmed` or `balance_order_missing` for a
compensation award. It still shows real setup, hold, dispute, FX and execution
blocks. A placeholder page can mention a newer submitted or approved profile
without displaying its bank mask or cheque as this payout's destination.
After reconciliation, the payout's active version supplies the masked
destination and cheque through the existing audited reveal/evidence rules.

## Existing TEST data repair

`manage.py reconcile_initial_dzd_setup` is read-only by default. It reports
the candidate count, distinct Travelers, approved current methods, safe/skipped
reason totals, and interrupted readiness rechecks without bank details. Use
the dry run on TEST first and review the total and refusal reasons. Execution
requires `--execute --actor-id <authorized-admin-id>`; `--payout-id <id>`
restricts either mode to one payout. Execution rechecks the predicate under
locks and records the normal audit. It never marks a payout paid or starts a
transfer. Payout #1 (`snapshot_version=0`, `legacy_instruction_required`) is
excluded and must remain quarantined. No SQL data repair is needed.

No TEST inventory or account mutation has been run in this implementation
phase. After independent GREEN verification, merge, and exact TEST deployment,
run the system-wide dry run, inspect skips, then execute the reviewed repair.
Confirm Payout #8 points to the approved instruction, cheque and mask appear
only through the authorized Admin view, and its status follows the release
gate. Do not reveal full CCP/RIP values in reports. Leave
`PAYOUT_DZD_EXECUTION_ENABLED=false`; do not perform a bank payout.

## Verification status

The scoped tests cover placeholder funding, approval, rejection/correction,
profile before funding, real later destination change, replay, a PostgreSQL
race test for the amendment, the dry-run/execute command, and compensation
presenter/preparation. Local SQLite can exercise behavior but not PostgreSQL
triggers or row-lock contention. Changed-file Ruff and targeted tests are the
Codex gates. Gemini must run the PostgreSQL race/trigger path, full Finance,
Admin and Django regressions, schema drift, CI and deployment checks before
approval. CI, merge, TEST deployment, affected-record scan, and final account
repair are pending that handoff.

Gemini's first PostgreSQL verification of `05251e5750625320d4581af885144b8121e7778a`
returned RED: the method row lock also selected nullable `current_version` and
profile joins, which PostgreSQL rejects for `FOR NO KEY UPDATE`. The follow-up
restricts the lock to the method row with `of=("self",)` while retaining the
related reads and Deal-first lock order. The existing lifecycle and concurrency
tests cover the affected call; PostgreSQL re-verification of the follow-up SHA
was required before merge, deployment, or TEST repair. Local recheck: 9 scoped
tests passed, with the PostgreSQL-only race test skipped on SQLite; changed-file
Ruff, Python compilation, and diff checks passed.

Gemini re-verified `3bc2a98e69d18f9a321e566ca21203765fdf82c7` on
PostgreSQL 16 and returned GREEN. The scoped reconciliation suite passed 10/10,
including the concurrent single-amendment race and command dry-run/execute.
Admin manual-console tests passed 37/37; cancellation/dispute suites passed
69/69. The full Django suite passed 2,164 tests, 34 skipped, 0 failed. Ruff,
missing-migration, schema-drift, production deployment, deployment safety (40
passed), Go unit, and static web checks passed. CI, merge, TEST deployment, and
TEST record reconciliation remain pending.
