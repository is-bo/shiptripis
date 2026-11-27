You are an independent second-pass reviewer. This review is read-only: do not write, commit or push code, and do not comment on GitHub. You may read files and run read-only git commands.

This is the **seventh review** of pull request #67, "G1: guest checkout without a browser-session dependency", in this repository (is-bo/shiptripis). Run `git fetch origin` first if a commit is missing.
- You rejected head `4337d9caff2d8e9961e3410f2e20343deb8ec5d4`, `f1fe5659fef2851c07473458fefc53ffa3a298d2`, `d99c8384882a3eaddae94d164e4bb3588acb4662`, `1643afc1857ea3c0c0ba807f440e18db03c7bf94`, `a0b48be0fba822c29216bed133b3fff8f99f2980` and `4e4c0ea98f677919fc02041d61398a4bc77698a2` (three blockers, nine should-fix, one nit). Your sixth report is `docs/handoff/astra/results/g1-astra-round6-result.md` on `main`.
- The new head is `NEWHEAD`. The fixes are one commit, `NEWSHORT`, directly on `4e4c0ea`. `main` had only docs since, so it is not merged in.
- Compare `4e4c0ea..NEWSHORT` for this round's fixes, and `origin/main...NEWHEAD` (three dots) for the whole package.
- Backend code is under `backend/monolith/` (mostly `apps/finance/services.py`, `jobs.py`, `models.py`, `operations.py`, `views.py`, `guest_web.py`, `providers/chargily.py`); the app under `mobile/lib/` (`domain/payment.dart`, `features/requests/checkout_section.dart`). The package is section 4 "G1" of `docs/WASSLA_PHONE_TEST_2_PLAN.md`. The write-up, with a "Seventh-pass review" section, is `docs/PHASE_G1_GUEST_CHECKOUT_CSRF.md`.
- Rules are in `CLAUDE.md`. Money is a "strongest model" area there.

## The no-old-data rule (treat as correct)
The app has never been live. There are no users, no stored provider data, and no rows, URLs, events or jobs written by code from before G1 that a deploy would inherit. CLAUDE.md, the owner's rules: "There are no real users and the app has never been in production. Spend nothing on legacy data, backward compatibility with old clients, tombstone routes or data-migration notes." Under that rule the lead ruled findings that exist only for such rows **not applicable**, and nothing is built for them. So:
- Do not report a problem whose only trigger is a row, association, URL, payload, deadline or job that only code from before this PR could have written. Mark your earlier findings of that kind **not applicable**.
- Do report anything reachable from the code at the new head, starting from an empty database, through any sequence of requests, webhooks, provider answers, job runs, worker crashes, provider outages and staff actions. A state this code can reach after a failure (for example an attempt ended before its provider confirmed the close) is in scope, whatever a test helper calls it.

## Lead instructions the fixes had to follow (treat as correct)
- **B:** never leave a superseded attempt payable. Ask the provider to close the old checkout and supersede only after the provider confirms. Otherwise answer a neutral, translated "a payment is already being made, try again later" conflict. Never hold the database lock across a slow provider call. The same rule applies when the same payer switches rail or amount.
- **A:** prefer removing the raw URI and Referer from proxy logs over regexes.
- **C:** recover with the original idempotency key and the exact original parameters.

## What changed this round
The round-6 structure is kept: binding only by stored ids (`_match_attempt`), liveness only by the provider's word (`checkout_final_at`, `LIVE_CHECKOUT`), one settle routine (`settle_checkout`), one settle job (`provider_reconcile:<attempt>`), the sweep (`arm_live_checkouts`) and the gate (`_checkout_step`, `_hands_back`).

1. **Your blocker 2 (an unverifiable or mismatched success never accounted for).** Whether a checkout can collect and whether its payment is accounted for are now two facts. `UNVERIFIED_PAYMENT` (`models.py`): a failed attempt with `failure_code` in `amount_unverifiable`, `amount_mismatch`, `currency_mismatch` and no `operational_resolution`; the finance attention queue uses it too. While it holds, `settle_checkout` reads the provider even though the checkout is final; a final outcome goes through `reconcile_attempt` with the amount and currency checks unchanged, else it answers `payment_unverified`. `process_provider_event` arms the settle job when the event recorded such a failure; the job raises `RetryableJobError` on `payment_unverified` (normal backoff, 32 tries). `jobs._already_satisfied_reason` keeps it unsatisfied, so a failed one is not archived. The sweep does not re-arm it (not live): after its tries the attempt stays in the attention queue for a person. Staff reconciliation queues the same job. A staff resolution ends the reads.
2. **Should-fix: a close requested during a running job.** `_arm_checkout_settle` now reads and writes the job under its row lock (taken after any other lock). On a RUNNING job it sets `run_at` to no earlier than now (so later than the claim); `run_job`'s deferral and retry keep the sooner time (`jobs._next_run_at`: `run_at` later than `locked_at` means it was asked again during the run). `settle_checkout` re-reads status, `close_requested_at` and `expires_at` after the provider fetch, before deciding to leave the checkout open.
3. **Should-fix: Chargily processing and the collecting state.** Chargily `processing` maps to `processing`. When a close is refused because a payment is being made, the attempt is recorded as `processing` through `reconcile_attempt` (no new column), so the gate, expiry and screens wait for that payment's outcome. On the screens, a live checkout on an attempt whose status is no longer open also counts as under way.
4. **Should-fix: the guest-link guard.** `_guest_checkout_open` counts an open attempt or any `LIVE_CHECKOUT` opened through the link.
5. **Should-fix: resumable Continue.** `checkout_state(...)` is replaced by `next_checkout(...)`, which returns the state and, when resumable, the rail; the owner's order payloads (including the posting-deposit summary) carry `resume_provider`. The app's Continue opens that rail, and a provider refusal re-reads the order.
6. **Should-fix: the guest POST that finds the payment made.** When the tap is refused with a `FinanceError`, the page looks up the completed link (`_completed_link`) first and shows the paid page.
7. **Should-fix: Chargily livemode strictness.** Only the exact strings `"true"` and `"false"` are converted; anything else stays as it is and the mode check refuses it.
8. **Nit: the decline test.** `test_a_declined_card_ends_nothing` asserts `failure_code == "card_declined"` again.
9. **Replay.** `process_provider_event` re-binds by the stored ids on every run and no longer reads `record.attempt`.

How the rest of your sixth report maps: round-4 #1, round-5 blocker 1 and your blocker 1 by item 9 (replay no longer reads a stored association; a row written by the removed fallback is in any case not applicable); round-4 #2 by item 2; round-5 should-fix 6 by item 5; round-5 should-fix 7 by item 3; round-5 should-fix 4 by item 7 for strictness. Declared not applicable under the no-old-data rule (the write-up lists them): round-3 #2 and your admin-display should-fix (payloads stored before the scrubbers); round-4 #9, round-5 should-fix 2 and your inherited-Chargily should-fix (the old one-hour deadline); B's remainder, round-5 blocker 3's remainder and your blocker 3 (URLs or conflicts issued by old code); the replay part of round-5 should-fix 4 and your stored-`livemode` should-fix (events stored before the upgrade).

Tests rewritten to the new rule are listed in the write-up. The write-up says each new test fails with its fix removed (16 server mutations, 2 app).

## What to do
1. Mark each row of your sixth report's first table, and each of your sixth report's new findings, **fixed**, **partly fixed** (say what is missing), **not fixed**, or **not applicable** (only under the no-old-data rule; say why).
2. Verify the structural rules hold from an empty database, rather than only the reported paths:
   - **Money.** Does every payment taken through a checkout land exactly once (applied, or unapplied and refunded), or, when its amount or currency cannot be accepted, stay in front of staff until a verified report applies it or staff resolve it? Any double application under the concurrent settle job, expiry job, webhook, tap and staff reconciliation? Can `payment_unverified` loop hot?
   - **Liveness.** Is `checkout_final_at` set anywhere without a provider's word? Can any checkout whose URL left the server be not live while it can still collect? Can any live checkout be left without a pending settle job beyond the sweep's next cycles? Can a close request be lost or deferred past while a settle job runs?
   - **One checkout that can collect.** Can two checkouts that can collect exist for one order at any moment, on any path?
   - **Binding.** Can an event or snapshot reach an attempt other than the one that stored the id it names?
   - **Locks.** Is any lock held across a provider call?
   - **Screens.** Can the owner or guest screen offer a tap the server would refuse? Does anything on the guest surfaces say who is paying? Copy in all three languages?
   - **Tests.** Check each rewritten test: the change must be the new rule, not a loosened assertion.
3. Report only real, reachable problems. No style opinions.

## Output format
- One opening sentence.
- A table of the earlier findings listed in step 1: # | Status | Note.
- A table of new findings: Severity (Blocker / Should-fix / Nit) | File and line | Concrete failure | Suggested fix.
- What you could not check.
- A final line: "Overall verdict: approve" or "Overall verdict: reject".
