You are an independent second-pass reviewer. This review is read-only: do not write, commit or push code, and do not comment on GitHub. You may read files and run read-only git commands. Run `git fetch origin` first.

This is the **fourth review** of pull request #69, "F1: make payout setup availability and actions explicit on the server", in this repository (is-bo/shiptripis). Review the head of `origin/claude/f1-payout-availability`; its code head is `c559318831160de31f9c7b5ac24df66b83ab8677` (the only later commit, if any, adds this prompt).

- You rejected the previous code head, `ee1e477c4847105d8fabfcfb960b1e162bdc3b1d`, with 3 blockers, 6 should-fixes and 1 nit. That report is `docs/handoff/astra/results/f1-astra-round3-result.md` on `main`.
- The builder's answer is the "Round 4" section of `docs/PHASE_F1_PAYOUT_AVAILABILITY.md` at the new head. It names one root cause and fixes the findings there rather than one by one.
- The branch was rebased on the current `main`, so compare `origin/main...origin/claude/f1-payout-availability` (three dots) for the whole package, and read the round-4 commit on its own (`git show c559318831160de31f9c7b5ac24df66b83ab8677`).
- Backend code is under `backend/monolith/apps/finance/` (mainly `payout_accounts.py`, `payout_mobile.py`, `payout_profile_api.py`, `payout_account_api.py`). The rules are in `CLAUDE.md`; money is a "strongest model" area there. The package is section 4 "F1" of `docs/WASSLA_PHONE_TEST_2_PLAN.md`.

## Background (treat as true)
- Live settings: `PAYOUT_PROFILES_ENABLED=false`; `STRIPE_CONNECT_ENABLED=false` with an empty country allowlist; the private payout (cheque) store is not configured; payout execution is off. The owner wants payouts switched on soon after F1 merges, so the profiles-on and Connect-on paths matter as much as the live ones.
- A Stripe connected account never changes country. The database allows one active account per traveler, platform and mode. Method versions are immutable; binding an account appends a version. An enabled EUR method always has a version with an open country (the preference write refuses otherwise).
- Stripe replays an idempotent POST for about 24 hours (the code uses 23); past that the code lists recent accounts and matches metadata. Stripe returns the same answer, refusal included, for the same key and body.
- No production code deactivates a `StripePayoutAccount`.

## The builder's root cause and design, in short
Onboarding took its inputs from different moments and places (the country from the body or the version, the version from when it started, the creation from a method-wide search, the account's readiness from an unlocked copy). Now every call serves **one declaration** (the method's current version and its country), and:
1. A `country` in the request is only an assertion against it (`_declaration_of`), refused with 409 `payout_preference_changed` before any Stripe call.
2. `_plan_onboarding` decides under User → method → account locks, with the same `onboarding_refusal` the read uses (order: standing account's country decision; a creation a search found nothing for; the declared country). A standing account is bound there, in the same transaction that locks it.
3. A creation's fingerprint includes the declaration version (`_creation_identity`). A request is sent or replayed only if the operation's stored fingerprint equals the current declaration's and Stripe still replays the key. Any other outstanding operation is only searched for, by `shiptrip_operation`.
4. `_ask_stripe` writes a failure only onto an operation still outstanding with no provider object (`OUTSTANDING`, empty `provider_object_id`). Only a refused creation POST marks `failed`.
5. `_record_account` locks the method then the account, marks the operation accepted only if it names no other account, and then: already the destination → success; same declaration, enabled, observed country equal → bind; otherwise keep it unbound and refuse.
6. `start_onboarding` checks again, under the method lock and after the link is minted, that the account is still the enabled method's destination, and returns that locked method for the response.
7. The read (`eur_method`) decides from the bound account only when it belongs to the configured platform and mode (`in_this_environment`); otherwise from the standing account and creation, so it offers `configure_eur` after a platform or mode switch.
8. `CountryUnsupported` carries `country` and `of_account`; the API sets `account_country` only when `of_account` is true.
9. `resume_account` and the old recovery helpers are removed; onboarding is the one path.

One rule is deliberately stricter than before: an ambiguous creation made for an earlier declaration is never replayed, even if the same country is declared again; a search that finds nothing then waits for Finance.

## What to do
1. Mark each round-3 item (3 blockers, 6 should-fixes, 1 nit) **fixed**, **partly fixed** (say what is missing) or **not fixed**.
2. Hunt for **new**, real, reachable problems in this round. In particular:
   - **Money and idempotency.** Can any interleaving of two onboarding calls, a preference PATCH, a refresh or webhook, and a hosted-link mint still bind an account to a declaration the traveler did not choose last, bind another traveler's account, create a second Stripe account, send a request for a superseded or closed-country declaration, or replay a key with a different body? Is the fingerprint-includes-declaration rule sound as the test of "this operation was made for this declaration"?
   - **Conditional writes.** Can any late or concurrent answer still overwrite a settled operation (`failed`, `accepted`, `not_found`), or can a legitimate answer be lost because a condition is too strict?
   - **Lock order and deadlocks.** The canonical order is in `apps/core/financial_locks.py`. Check `_plan_onboarding`, `_record_account`, `_apply_snapshot`, the final check in `start_onboarding`, and the refresh, webhook and job paths.
   - **Read and write consistency.** For each state (standing account or not, its country open or not, declaration country open or not, a creation outstanding inside or past the window, current or superseded, searched in vain or not, another platform or mode), do the read's `unavailable_reason` and `available_actions` match what onboarding answers?
   - **The removed path.** Does anything still need `resume_account` or the removed helpers (admin console, jobs, webhooks, helper tasks)?
   - **Weakened tests.** Check the rewritten tests named in the phase doc, and that each new test fails without its fix.
3. Report only real, reachable problems. No style opinions.

## Output format
- One opening sentence.
- A table of the 10 round-3 items: # | Status | Note.
- A table of new findings: Severity (Blocker / Should-fix / Nit) | File and line | Concrete failure (inputs or state → wrong result) | Suggested fix.
- What you checked and found sound, and what you could not check.
- A final line: "Overall verdict: approve" or "Overall verdict: reject".
