You are an independent second-pass reviewer. This review is read-only: do not write, commit or push code, and do not comment on GitHub. You may read files and run read-only git commands. Run `git fetch origin` first.

This is the **fifth review** of pull request #69, "F1: make payout setup availability and actions explicit on the server", in this repository (is-bo/shiptripis). Review the code at `bd74c3a8048ad0e0e0abb2be94e72883ce8ac6c5`, the round-5 code head of `origin/claude/f1-payout-availability`.

- **Head.** Three docs-only commits follow it on the branch: `ef04fd3` (the first version of this prompt), `7b5a5aa` (the builder's status file, `docs/handoff/status/F1.md`) and the commit that adds this revised prompt, which is the branch head. Check it: `git diff --stat bd74c3a8048ad0e0e0abb2be94e72883ce8ac6c5 origin/claude/f1-payout-availability` must list only files under `docs/`. If it lists anything else, say so first and review that too.
- **CI is green.** All 11 checks passed on `7b5a5aa` (workflow run 45989713862, finished 2026-11-27 11:42 UTC), whose code is identical to `bd74c3a`: Django migrations, tests and lint; the four Django test shards (PostgreSQL 16, so the real-thread race tests ran and were not skipped); Go build and unit tests; Go integration tests; Flutter; Schema drift; Production config; isolated-infrastructure. You do not need to check CI.
- You rejected the previous code head, `c559318831160de31f9c7b5ac24df66b83ab8677`, with 1 blocker, 6 should-fixes and 1 nit (and 4 of the round-3 items partly fixed). That report is `docs/handoff/astra/results/f1-astra-round4-result.md`, committed on this branch in the round-5 commit.
- The builder's answer is the "Round 5" section of `docs/PHASE_F1_PAYOUT_AVAILABILITY.md` at the new head. It names one root cause and fixes it with one lock rather than case by case.
- The branch was not rebased this round. Compare `origin/main...origin/claude/f1-payout-availability` (three dots) for the whole package, and read the round-5 commit on its own (`git show bd74c3a8048ad0e0e0abb2be94e72883ce8ac6c5`).
- Backend code is under `backend/monolith/apps/finance/` (mainly `payout_accounts.py`, `payout_profiles.py`, `payout_profile_api.py`, `payout_account_api.py`, `payout_mobile.py`) and `backend/monolith/apps/core/financial_locks.py`. The rules are in `CLAUDE.md`; money is a "strongest model" area there. The package is section 4 "F1" of `docs/WASSLA_PHONE_TEST_2_PLAN.md`.

## Anti-loop triage rules (the owner's rules for every review since 2026-11-27; apply them to your findings)
This package has been through four rejected rounds. These three rules keep the review on the package's scope:
1. **Legacy and upgrade findings are not applicable.** The app has never been live and has no users or historical rows. A finding that needs a row written by an older version of this code, an old app version, a URL or link issued before the change, or a migration of old data is **not applicable**: do not report it as a finding. You may list it in one line under "Not applicable".
2. **Out-of-scope findings go to a follow-up note.** Payout setup is the scope: onboarding, the payout preference, the payout read model, and the refresh and dashboard calls and their locks. Anything outside it is listed in one line under "Follow-up, outside F1", not in the findings table.
3. **Fixes go to the root cause.** A real, reachable problem in scope is reported with its severity. When it is a new variant of a family an earlier round already fixed (for example another interleaving of onboarding and a preference change), say which family, and name the design gap that still allows the family, so the next round changes the design and not the single case.

## Background (treat as true)
- Live settings: `PAYOUT_PROFILES_ENABLED=false`; `STRIPE_CONNECT_ENABLED=false` with an empty country allowlist; the private payout (cheque) store is not configured; payout execution is off. The owner wants payouts switched on soon after F1 merges, so the profiles-on and Connect-on paths matter as much as the live ones.
- PostgreSQL 16, no connection pooler (no PgBouncer), Django persistent connections (`CONN_MAX_AGE` 60), Gunicorn `gthread` workers (one database connection per thread, `--timeout 120`), `ATOMIC_REQUESTS` off, no `statement_timeout` or `lock_timeout` on web requests, `idle_in_transaction_session_timeout` 5 min. Provider calls use a 3.05 s connect and 15 s read timeout by default (production allows at most 10 s and 30 s).
- A Stripe connected account never changes country. The database allows one active account per traveler, platform and mode. Method versions are immutable; binding an account appends a version and bumps the method revision. The preference PATCH checks the revision.
- Stripe replays an idempotent POST for about 24 hours (the code uses 23); past that the code lists recent accounts and matches metadata. Stripe returns the same answer, refusal included, for the same key and body.
- No production code deactivates a `StripePayoutAccount`, and the only writers of an EUR method's version or enabled flag are `set_preference` and onboarding's own binding.

## Known and left to the owner (do not report these again)
These are listed in the pull request under "Left as it was" and wait for a decision by the lead and the owner. Report one only if you find it now produces a wrong binding, a second Stripe account or a wrong money result.
1. EUR can be chosen while Stripe onboarding is off if the country list is not empty; the read mirrors it.
2. Keeping EUR needs an open country: once the list drops the saved one, EUR is accepted only with a new open country.
3. A direct onboarding call without an EUR preference answers `payout_setup_invalid`.
4. The CCP and RIP check keys are not verified (no verified formula was available).
5. An ambiguous creation that only Stripe can settle keeps `configure_eur` on the read; that call settles it.
6. A preference change sent while an onboarding call runs waits for that call to answer. This one is in scope for the "Waiting" question below: report it if the wait is unbounded, holds something another path needs, or can tie up the server.

## The builder's root cause and design, in short
Round 4 checked the declaration only while each of onboarding's short transactions held the method lock; between them the call talks to Stripe with no lock, and a preference change could commit there. Now:
1. `hold_payout_account_setup(traveler_id)` (session-level PostgreSQL advisory lock, two keys, `PAYOUT_ACCOUNT_SETUP_LOCK`) is held by `start_onboarding` and `ensure_account` from reading the declaration to handing out the link: the intent still commits before its POST, and a dying process drops the lock with its connection. It nests.
2. `lock_payout_account_setup(traveler_id)` (the same key, transaction level) is taken by every EUR preference write before User: in the PATCH view and in `payout_profiles._method` for EUR. Nothing else takes the lock (not funding, refresh, webhooks or jobs).
3. So a change waits for an onboarding call in flight (and, if that call bound an account, then meets a stale revision), an onboarding call waits for a change and serves it, and a second onboarding call waits for the first and finds its account.
4. The checks under the method lock stay as the binding's own guard; the link check now also compares the exact version the account was resolved on.
5. Onboarding refuses a closed rail (no country open) before the Traveler's own state, as the read does. A creation's answer is dated by the operation's first request. `destination_account` refuses an account outside the configured platform and mode before refresh or dashboard calls Stripe. An accepted creation clears the "not found" search marker.

## What to do
1. Mark each round-4 item (1 blocker, 6 should-fixes, 1 nit) and each round-3 item you marked partly fixed (3, 6, 7, 8) **fixed**, **partly fixed** (say what is missing) or **not fixed**.
2. Judge the root cause first: does the setup lock close the whole family the round-4 blocker belongs to (any EUR preference change committing while an onboarding call for the same traveler is between its steps), or does a gap remain? Then hunt for **new**, real, reachable problems in this round. In particular:
   - **The lock itself.** Can any path change an EUR declaration (version or enabled) without taking the setup lock first? Can a path take it after User or after any other lock, and deadlock with onboarding, which holds it and then takes User, the method and the account? Is the session-level lock always released (exceptions, provider errors, a broken connection, a thread reusing its persistent connection for the next request)? Does nesting (start_onboarding then ensure_account, a nested call in the same session) release exactly once per acquisition?
   - **Money and idempotency.** With the lock, can any interleaving of onboarding calls, a preference PATCH or POST, a refresh or webhook, and a hosted-link mint still bind an account to a declaration the traveler did not choose last, bind another traveler's account, create a second Stripe account, send a request for a superseded or closed-country declaration, or replay a key with a different body?
   - **Waiting.** Who now waits on Stripe, for how long, and does any of them hold a row lock or a transaction a funding, refresh or webhook path needs while it waits?
   - **Read and write consistency.** For each state (standing account or not, its country open or not, declaration country open or not, no country open at all, a creation outstanding inside or past the window, current or superseded, searched in vain or not, another platform or mode), do the read's `unavailable_reason` and `available_actions` match what onboarding, refresh and dashboard answer?
   - **Tests.** Check the new real-thread file `test_f1_payout_account_setup_race.py` (does each wait really prove the lock, and would each test fail without it?), the rewritten readiness test, the new same-country test, and the five tests now labelled as checking the guard on onboarding's own connection: did any lose its meaning?
3. Report only real, reachable problems, after applying the three anti-loop triage rules above. No style opinions.

## Output format
- One opening sentence.
- A table of the round-4 items and the four partly fixed round-3 items: # | Status | Note.
- A table of new findings: Severity (Blocker / Should-fix / Nit) | File and line | Concrete failure (inputs or state → wrong result) | Family (rule 3: "new", or the earlier family it is a variant of) | Suggested fix at the root.
- "Not applicable" and "Follow-up, outside F1": one line each per item, or "none".
- What you checked and found sound, and what you could not check.
- A final line: "Overall verdict: approve" or "Overall verdict: reject".
