# G1-B: the jobs that follow a checkout (rule G-E)

Brief `docs/handoff/builders/G1-B.md`, plan `docs/handoff/LOOP_END_PLAN.md` (rules R2, R3, R4,
G-E). Pull request #67, branch `claude/g1-guest-checkout-csrf`, after G1-A and before G1-C.
Nothing deployed.

**The rule.** The obligation to follow a checkout cannot be lost. Part of the change is in the
shared job runner, so it applies to every job kind.

## Final design

**G-E1. The sweep defines the obligation (R3).** `arm_outstanding_attempts` (`services.py`, was
`arm_live_checkouts`), run on every job cycle by `jobs._sweep_outstanding_attempts`, reads
`OUTSTANDING` (a checkout that can still collect, or a held payment) instead of `LIVE_CHECKOUT`.
Each outstanding attempt whose settle job (`provider_reconcile:<attempt>`) is missing, succeeded,
failed or cancelled is armed through `_arm_checkout_settle`: due now, or, when its job failed
(its tries ran out), after the capped retry delay (`_retry_delay(CHECKOUT_JOB_ATTEMPTS)`, 6 hours),
so a provider that keeps failing is not read hot. A pending or running job is never touched, so
the sweep never pulls one forward. It takes unarmed attempts in id order up to its limit (100);
an armed one leaves the unarmed set, so N attempts are armed within ceil(N / 100) cycles.

The settle handler (`handle_provider_reconcile`) reports done only when the attempt is no longer
`OUTSTANDING`; any other answer is retried with backoff (`outstanding_<note>`).
`_already_satisfied_reason` already read the same predicate. The partial index the sweep reads
follows it: `fin_attempt_live_checkout_idx` becomes `fin_attempt_outstanding_idx` on
`OUTSTANDING` (migration `finance 0038`). `HELD_PAYMENT_CODES` became a sorted tuple so the
index's SQL is the same on every run (a frozenset's order changes with the hash seed).

**G-E2. A run writes its completion only while the claim is its own (R4).** One helper,
`jobs._complete_run`, writes all five ends of `run_job` (missing handler, deferred, permanent
failure, failure, success). Its single UPDATE filters on `pk`, `status = running` and the
`locked_at` this run's claim stamped. Zero rows means the run lost its claim: it logs
`finance.job_claim_lost` and writes nothing, so the newer claim's outcome stands. No new column.

- The guess held: two claims of one job never carry the same `locked_at`. A second claim needs
  the job pending again, which only its own end, `requeue_stuck_jobs` (15 minutes stale) or a
  re-arm of a finished job can do, each later in time, and the claim stamps `timezone.now()`.
  `claim_id` was not needed.
- Every write that makes a job pending again sets `locked_at` to null, as before:
  `_arm_checkout_settle`, `requeue_stuck_jobs`, `schedule_job(reactivate_failed=True)`,
  `payout_sweeper`'s revival, `operations._reactivate_completed_job` and `retry_failed_job`.
- A wake recorded during a run (`run_at` later than `locked_at`, written by
  `_arm_checkout_settle` on a running job) is kept by every end: the job is pending again, due by
  the sooner of the wake and the run's own next time, `completed_at` empty. Before, only the
  deferral and the retry kept it; `_next_run_at` is folded into the helper.
- Two domain paths ended a job they did not run: `_finish_event` (an event applied) and the
  `mark_refund_succeeded` marked a pending or running job succeeded. They now touch only a pending
  job; a running one writes its own end. The end state is the same as before, when the run's
  unconditional write came last.
- Handler effects were already idempotent on their own; nothing in a handler changed.

**G-E3. Intent and wake in one transaction (R2).** `_record_close_intent` writes
`close_requested_at` and, only when the intent is new, arms the settle job due now, inside the
caller's transaction, taking the job row lock last. `_stop_collecting_attempts` now records its
close through it. Removed: the two arms in `_settle_before_checkout` (after a provider error and
after a live note) and the arm in `handle_attempt_expiry` (settling or collecting). A close asked
for again keeps the job's backoff, so a provider outage is not read hot; the sweep covers any
outstanding attempt left without a pending job.

## What was removed

The five unconditional completion updates in `run_job` and `_next_run_at`. Every separate arm of
the settle job after a close intent (`_settle_before_checkout` twice, `handle_attempt_expiry`,
`_stop_collecting_attempts`). The sweep's restriction to `LIVE_CHECKOUT`, and its index.

## Rewritten tests

Under R4 a run that holds no claim writes nothing, so a test that called `run_job` on a job nobody
claimed now claims it first (`finance/tests/factories.claim`, which stamps the claim as the worker
does). No assertion changed in these:

- `finance/tests/test_guest_payment.py`: `test_a_payment_being_made_holds_off_expiry_and_is_followed_to_its_end`,
  `test_cancelling_the_order_closes_the_checkout_a_payer_holds`,
  `test_a_cancelled_orders_checkout_that_took_a_payment_refunds_it`,
  `test_closing_the_order_to_collection_closes_its_checkout_too`,
  `test_an_order_closed_while_a_checkout_opens_has_nothing_to_close`,
  `test_a_payment_settling_outlives_its_orders_cancellation`,
  `test_a_close_asked_for_while_the_settle_job_runs_is_not_deferred_past`,
  `test_a_success_whose_amount_cannot_be_accepted_is_read_until_it_is_accounted_for`,
  `test_a_payment_any_path_finds_unaccounted_is_read_until_it_is`,
  `test_a_payment_staff_resolved_is_no_longer_read`,
  `test_staff_reconciliation_reads_the_provider_for_a_payment_it_could_not_accept`.
- `finance/tests/test_phase8fh3_execution.py`: `TestWorker.test_a_deferred_wait_does_not_consume_the_retry_budget`,
  `TestWorker.test_an_unresolved_operation_is_terminal_not_retried`.
- `deals/tests/test_phase_i1a_journey_timing.py`: `PayoutReleaseGateTests.test_the_release_job_is_rescheduled_to_the_floor_not_retried_blindly`.
- `trips/tests/test_l5a_progress.py`: `ReminderHandlerTests.test_the_job_runner_executes_a_stored_reminder`.

Rewritten to the new rule:

| Test | Why |
|---|---|
| `test_guest_payment.test_a_settle_job_that_ran_out_is_armed_again_until_the_checkout_is_final` | The sweep now arms a job whose tries ran out after the capped retry delay, not at once (G-E1). The test asserts the job is pending and due more than 5 hours out, then runs the loop at that time. |
| `test_guest_payment.test_the_job_loop_arms_every_live_checkout_left_without_a_settle_job` and the test above | `arm_live_checkouts` is now `arm_outstanding_attempts`; same assertions. |

## Evidence

Red at `1333f54`; green from GREEN_SHA.

| Finding or rule | Test |
|---|---|
| Round 7 blocker 2: a stale worker's completion overwrites a re-armed job | `test_job_claims.AStaleRunWritesNothing`: each of the five ends (failure before and after its tries ran out), while the newer claim runs and after it re-armed the job (red: the stale end is written) |
| Round 7 should-fix: the close intent and the job wake commit separately | `test_checkout_obligation.TheCloseIntentCommitsWithItsWake.test_a_crash_after_the_close_intent_leaves_its_settle_job_due` (red: the job stays due after the checkout's expiry); `…crash_before_it_commits_leaves_neither` |
| 101 obligations against the sweep's limit: all armed within two cycles, in id order | `TheSweepArmsEveryOutstandingAttempt.test_more_than_its_limit_within_two_cycles` |
| Tries exhausted while a close is outstanding: re-armed after the capped delay | `…test_a_job_whose_tries_ran_out_is_armed_after_the_capped_delay`; a held payment: `…test_a_held_payment_whose_job_ran_out` |
| The sweep never pulls a pending job forward | `…test_never_pulls_a_pending_job_forward` |
| The settle job reports done only when the attempt is no longer outstanding | `…test_a_settle_job_reports_done_only_once_the_attempt_is_accounted_for` |
| A provider outage still backs off | `TheCloseIntentCommitsWithItsWake.test_a_close_asked_for_again_keeps_the_jobs_backoff` |
| A wake during the same claim is kept by every one of the five ends | `test_job_claims.AWakeDuringTheClaimIsKept` |
| A job kind that is not a checkout runs through the helper unchanged | `test_job_claims.AJobThatIsNotACheckout` (success, deferral, retry then failure, permanent failure) |
| Mechanical: no completion is written outside the helper | `test_job_claims.OnlyTheRunWritesItsEnd`: only `_complete_run` writes `last_attempt_at`; only it and `requeue_stuck_jobs` update a job filtered as running |
| Migration and contract | `finance 0038`; `backend/contracts/sql/schema.sql` changes only by the index |
