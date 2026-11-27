# Builder brief G1-B: the job obligation

**Builder:** Claude Opus, extra-high effort. One builder at a time on the branch.
**Start only when** the lead says the plan is approved and gives you Ismail's answers to D1 to D9.
**Plan:** `docs/handoff/LOOP_END_PLAN.md` at commit `e66bb5b`, on branch
`claude/project-thread-mb20d4`. Read it with `git fetch origin claude/project-thread-mb20d4` and
`git show e66bb5b:docs/handoff/LOOP_END_PLAN.md`. If the lead names a later commit, use that one.
Where this brief and the plan differ, the plan wins, and you tell the lead.

## 1. Your job

Close family G-E on the G1 branch: the obligation to follow a checkout cannot be lost. Part of
your change is in the shared job runner, so it applies to every job kind, not only to checkouts.

## 2. Branch and order

- Branch `claude/g1-guest-checkout-csrf`, pull request #67. You start from G1-A's pushed, green
  head. Pull first. Do not start while G1-A is still working on the branch.
- G1-C follows you. The pull request is reviewed once, after G1-C.

## 3. Read first

1. `CLAUDE.md`.
2. The plan: sections 3 and 4 (rules R2, R3 and R4 are yours), sections 6.2 and 6.3 (G-E1 to
   G-E3), 6.5, and item 2 of Appendix B.
3. On your branch: `docs/handoff/status/G1.md` as G1-A left it.

## 4. What you build

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
- `_already_satisfied_reason` reads the same predicate.

**G-E2. Claim fencing, for every job kind** (`jobs.py`; `ScheduledJob` in `models.py`).
`claim_due_jobs` stamps a fresh `claim_id`, a new nullable UUID column. One helper writes all five
completions of `run_job`: missing handler, deferred, permanent failure, failure, success. Each
filters on `pk`, `status = running` and that `claim_id`. Zero rows means the run lost its claim:
it logs and writes nothing. Every write that makes a job pending again clears `claim_id`. Find
them all; today they include `_arm_checkout_settle`, `requeue_stuck_jobs`, and in `operations.py`
`_reactivate_completed_job` and `retry_failed_job`. A handler's effects stay safe on their own,
whether or not its completion is accepted.

**G-E3. Intent and wake in one transaction** (`services.py` `_record_close_intent`). It also arms
the settle job due now, inside the caller's transaction, taking the job row lock last as today. No
caller arms separately. If the job is running, the wake is recorded on the row as today (`run_at`
later than `locked_at`), and no completion of that run pushes it later: `_next_run_at` stays. The
immediate wake comes from the new intent only, so a provider outage still backs off.

## 5. What you remove

The five unconditional completion updates in `run_job`. Every separate call that arms the settle
job after a close intent. The sweep's restriction to `LIVE_CHECKOUT`.

## 6. What is not yours

- Money rules, dispositions and `reconcile_attempt` (G1-A, done before you).
- The gate function and the screens (G1-C).
- What each job handler does, beyond the settle handler's "done" rule. You change how completions
  are written, not what handlers compute.

## 7. Tests

Red first: round-7 blocker 2 (a stale worker's completion overwrites a re-armed job) and
should-fix 2 (the close intent and the job wake commit separately).

Then, extending G1-A's state table:

- 101 obligations with the sweep's limit of 100: all are armed within two cycles;
- tries exhausted while a close is outstanding: re-armed after the capped delay;
- a wake during the same claim: the run's completion does not push it later;
- a stale success, deferral, retry, permanent failure and missing handler, each finishing after a
  newer claim: zero rows written, for a checkout job and for one other job kind;
- a crash on either side of the close-intent transaction;
- real threads, both orders: job against job; job against a tap; job against a staff disposition.

Mechanical checks: a scan test that no `ScheduledJob` completion is written outside the helper,
and that every write to `status = pending` clears `claim_id`.

The whole finance suite passes: the fencing touches payouts, refunds and notifications jobs too.

## 8. Done when

1. The two findings above are tests, red before and green after.
2. The rows above pass, and the scan tests hold.
3. The migration is generated, `task check-drift` is clean and the contract is committed.
4. CI is green on your head, and the status file tells G1-C what changed.

## Rules, the same for every builder

1. Build what this brief names and nothing else. Add no lock, counter, generation, flag, column,
   job kind or retry loop that the plan does not name. If one seems needed, stop and ask.
2. Red first. Reproduce each finding listed under "Tests" as a failing test before you fix it. A
   failing test must tell the bad outcome apart from a correct serial execution.
3. Group tests by family, in files named after the invariant. Never skip, delete or weaken a test.
   A test of a mechanism you delete is rewritten to the new rule, and the pull request lists it
   with the reason.
4. Remove what you replace in the same pull request. The tests of the closed families stay green.
5. The server enforces every rule. The app never fakes a result. Every user-facing string exists
   in English, French and Arabic.
6. After a migration, run `task check-drift` in `backend/` and commit the regenerated contract.
7. Push only to your branch, with ordinary pushes: no force push, no rebase of pushed commits. The
   whole suites and the Android build run in GitHub CI on the branch. While you fix, re-run locally
   only the tests that failed. The work is ready only when every CI check is green, "Schema drift"
   included.
8. Never deploy, never restart or change a server, never build the app for a device. The
   repository is public: no server address, account email, key, token or password in a file, a
   commit, the pull request or a comment.
9. Do not edit `HANDOFF.md`, the plan, or files that belong to another brief. Do not merge. Write
   nothing on GitHub except the pull request description.
10. No model name in a commit, a pull request or a document. Do not use the word "partner".

## Stop and ask the lead when

- a fix needs a mechanism the plan does not name;
- the code cannot do what the plan says, or the plan and the code disagree about a fact;
- a change would alter a money, code or matching result in a way the plan does not state;
- something marked **[Guess]** turns out to be wrong;
- the only way forward would weaken a test.

Say what you found, with file and line, and what you would do. Then wait. The lead takes it to the
planner. Do not patch around it.

## What you hand back

- The branch pushed, CI green on its head, and that head's commit id.
- The evidence table: one row per finding under "Tests", with the finding, the report it came
  from, the red test and the commit where it fails, the green test, and device evidence where this
  brief asks for it.
- The inventory of writers and callers of each mechanism you built: who writes the field, who
  calls the function.
- The tests you removed or rewrote, each with its reason.
- What you saw outside this brief, as a note for a follow-up. Do not fix it.
- `docs/handoff/status/G1.md` on the branch, rewritten to say where the work stands,
  and what G1-C needs to know.
