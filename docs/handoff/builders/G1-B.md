# Brief G1-B: jobs that follow a checkout

**Builder:** Claude Opus, extra-high effort.
**Branch:** `claude/g1-guest-checkout-csrf`, pull request #67. You start from G1-A's pushed,
green head. Pull first. Do not start while G1-A is still working on the branch. G1-C follows you.
**Read first:** `CLAUDE.md`; `docs/handoff/builders/README.md`; the plan sections 3, 4 (rules R2,
R3 and R4) and 5.2 and the G1 rows of Appendix A; `docs/handoff/status/G1.md` as G1-A left it.

## 1. Your job

Close rule G-E: the obligation to follow a checkout cannot be lost. Part of the change is in the
shared job runner, so it applies to every job kind.

## 2. What you build

Paths are under `backend/monolith/apps/finance/`.

**G-E1. The sweep defines the obligation** (`jobs.py` `_sweep_live_checkouts`; `services.py`
`arm_live_checkouts`). On every job cycle, each `OUTSTANDING` attempt (G1-A's predicate) has a
settle job that is pending or running. Where it has none, or one that is succeeded, failed or
cancelled, the sweep makes it pending.

- A job the sweep re-arms after its tries ran out is due after the capped delay, not at once.
- The sweep never pulls a pending job forward.
- It takes unarmed obligations in id order up to its limit. An armed one leaves the unarmed set,
  so every obligation is armed within a known number of cycles.
- The settle handler reports "done" only when the attempt is no longer `OUTSTANDING`.
  `_already_satisfied_reason` reads the same predicate.

**G-E2. A run writes its completion only while the claim is its own** (`jobs.py`, `run_job`).
`claim_due_jobs` already stamps `locked_at` at every claim. One helper writes all five
completions of `run_job` (missing handler, deferred, permanent failure, failure, success). Each
filters on `pk`, `status = running` and the `locked_at` this run was given. Zero rows means the
run lost its claim: it logs and writes nothing. No new column.

- Every write that makes a job pending again sets `locked_at` to null, as today. Check them all:
  `_arm_checkout_settle`, `requeue_stuck_jobs`, and in `operations.py`
  `_reactivate_completed_job` and `retry_failed_job`.
- **[Guess]** Two claims of one job never carry the same `locked_at`, because a second claim
  needs the job to be pending again first, later in time. If you find a path where they can be
  equal, the fallback is one nullable UUID column `claim_id`, stamped at the claim and used in
  the same filter. Say which you used.
- A handler's effects stay safe on their own, whether or not its completion is accepted.

**G-E3. Intent and wake in one transaction** (`services.py` `_record_close_intent`). It also arms
the settle job due now, inside the caller's transaction, taking the job row lock last as today.
No caller arms separately. If the job is running, the wake is recorded on the row as today
(`run_at` later than `locked_at`), and no completion of that run pushes it later. The immediate
wake comes from the new intent only, so a provider outage still backs off.

## 3. What you remove

The five unconditional completion updates in `run_job`. Every separate call that arms the settle
job after a close intent. The sweep's restriction to `LIVE_CHECKOUT`.

## 4. What is not yours

Money rules, dispositions and `reconcile_attempt` (G1-A). The gate function and the screens
(G1-C). What each job handler computes: you change how completions are written.

## 5. Tests

Red first: round-7 blocker 2 (a stale worker's completion overwrites a re-armed job) and the
should-fix "the close intent and the job wake commit separately".

- 101 obligations against the sweep's limit: all are armed within two cycles.
- Tries exhausted while a close is outstanding: the sweep re-arms after the capped delay.
- A wake during the same claim is kept by every one of the five completions.
- A stale run, for each of the five completions: it writes nothing, and the newer claim's
  outcome stands.
- A crash on either side of the close-intent transaction: the intent and its job exist together
  or not at all.
- One job kind that is not a checkout runs through the helper unchanged.

Mechanical check: a scan test that no `ScheduledJob` completion is written outside the helper.

## 6. Done when

1. The two findings are tests, red before and green after, and every case of section 5 passes.
2. If a column was added: the migration, `task check-drift` clean, the contract committed.
3. `docs/handoff/status/G1.md` tells G1-C where things stand. CI is green on your last commit.
