You are an independent second-pass reviewer. This review is read-only: do not write, commit or push code, and do not comment on GitHub. You may read files and run read-only git commands. Run `git fetch origin` first.

This is the **third review** of pull request #69, "F1: make payout setup availability and actions explicit on the server", in this repository (is-bo/shiptripis). Review the head of `origin/claude/f1-payout-availability`; its code head is `ee1e477c4847105d8fabfcfb960b1e162bdc3b1d` (the only later commit, if any, adds this prompt).

- You rejected the previous head, `f3f37a35193332bf52605db5e6216c2f27384485`, with 1 blocker, 4 should-fixes, 1 nit and 2 pre-existing faults. That report is `docs/handoff/astra/results/f1-astra-round2-result.md` on `main`.
- The builder's answer to each finding is in the "Round 3" section of `docs/PHASE_F1_PAYOUT_AVAILABILITY.md` at the new head.
- The branch was rebased on the current `main`, so compare `origin/main...origin/claude/f1-payout-availability` (three dots) for the whole package. Round 3 is the last code commit; `git diff f3f37a3 ee1e477c4847105d8fabfcfb960b1e162bdc3b1d` will not apply cleanly across the rebase, so read the round-3 commit on its own (`git show ee1e477c4847105d8fabfcfb960b1e162bdc3b1d`).
- Backend code is under `backend/monolith/apps/finance/` (mainly `payout_accounts.py`, `payout_mobile.py`, `payout_profile_api.py`) and `backend/monolith/apps/core/financial_locks.py`. The rules are in `CLAUDE.md`; money is a "strongest model" area there. The package is section 4 "F1" of `docs/WASSLA_PHONE_TEST_2_PLAN.md`.

## Background (treat as true)
- Live settings: `PAYOUT_PROFILES_ENABLED=false`; `STRIPE_CONNECT_ENABLED=false` with an empty country allowlist; the private payout (cheque) store is not configured; payout execution is off. The owner wants payouts switched on soon after F1 merges, so the profiles-on and Connect-on paths matter as much as the live ones.
- A Stripe connected account never changes country. The database allows one active account per traveler, platform and mode. Method versions are immutable; binding an account appends a version.
- Stripe replays an idempotent POST for about 24 hours (the code uses 23); after that the code searches by metadata.

## Your round-2 findings, in short
1. **Blocker.** A stale onboarding could append a bound DE version over a newer FR declaration; a bound DE account with an explicit `country="FR"` returned the DE link. The builder now records the version onboarding started on, re-checks it (and `enabled`) under every method lock, keeps an account Stripe returns after a change as the active account without binding it, answers 409 `payout_preference_changed`, and runs the country decision before reusing a bound account (once before any Stripe call, once under the method lock).
2. **Should-fix.** Read and write gave two codes for one state. Now one function, `account_country_refusal`, decides for both: with a standing account its country must be open and the declaration must name it; without one the declared country must be open.
3. **Should-fix.** An ambiguous FR creation then a DE declaration failed the fingerprint with a generic 400, and an operation under another platform or mode blocked setup. The applicable creation is now looked up by a key carrying method, platform and mode (`_creation_operation`), its original country is recovered from the stored request fingerprint (`_requested_country`), and the replay or the search uses that country and the original key. The read uses the same lookup (`creation_unresolved`).
4. **Should-fix.** After a link failure the read offered only `refresh`. It now offers `resume_eur_setup` while Stripe still needs the traveler (`onboarding_incomplete`), and the test goes 502, GET, advertised action.
5. **Should-fix.** The race test's wait accepted any waiter. It now records both backend PIDs and waits for the trailing PID's ungranted advisory lock on this traveler's key, blocked by the leading PID.
6. **Nit.** The replacement test and the queue test now look for the submitted values and both masks.
7. **Pre-existing.** A 403 on the recovery search marked the creation `failed`, so the next call used a new key. Now only `ProviderCheckoutRejected` on the creation POST itself marks it `failed`; any other failure of the replay or the search leaves it `unknown` with its key.
8. **Pre-existing.** Onboarding locked method then account; refresh locked account then method. Refresh (`_apply_snapshot`) now locks the traveler's EUR method first, and projects status onto the method only when the account is its current destination.

## What to do
1. Mark each finding **fixed**, **partly fixed** (say what is missing) or **not fixed**.
2. Hunt for **new**, real, reachable problems introduced in this round. In particular:
   - **Money and idempotency.** Can any interleaving of onboarding, a preference PATCH, a refresh or webhook, and a second onboarding still bind an account to a version the traveler did not choose last, bind an account to the wrong traveler, create a second Stripe account, or re-POST a creation with a different key or body? Does a kept, unbound account ever become a funding destination without a fresh onboarding call that passes the country decision?
   - **Lock order and deadlocks.** The canonical order is in `apps/core/financial_locks.py`. Check every path that now takes the method lock inside `_apply_snapshot` (refresh, webhooks, jobs, onboarding's own binding) for a lock held earlier in the same transaction that would invert the order, and for nested atomics that hold the account lock first.
   - **Read and write consistency.** For each state of (standing account or not, its country open or not, declaration country, ambiguous creation inside or past the window, other platform or mode), does the read's `unavailable_reason` and `available_actions` match what onboarding answers? The builder accepts one deliberate gap: an ambiguous creation that only Stripe can settle keeps `configure_eur`, because that call is the one that settles it. Say if you disagree.
   - **Fingerprint recovery.** `_requested_country` recomputes the request fingerprint over the allowed country ceiling. Can it pick the wrong country, or return none for a request the code itself sent?
   - **Weakened tests.** Check that no rewritten assertion lost its meaning and that each new test fails without its fix.
3. Report only real, reachable problems. No style opinions.

## Output format
- One opening sentence.
- A table of the 8 round-2 items above: # | Status | Note.
- A table of new findings: Severity (Blocker / Should-fix / Nit) | File and line | Concrete failure (inputs or state → wrong result) | Suggested fix.
- What you checked and found sound, and what you could not check.
- A final line: "Overall verdict: approve" or "Overall verdict: reject".
