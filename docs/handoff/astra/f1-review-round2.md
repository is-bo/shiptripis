You are an independent second-pass reviewer. This review is read-only: do not write, commit or push code, and do not comment on GitHub. You may read files and run read-only git commands. Run `git fetch origin` first.

This is the **second review** of pull request #69, "F1: make payout setup availability and actions explicit on the server", in this repository (is-bo/shiptripis). Review the head of `origin/claude/f1-payout-availability`; its code head is `f3f37a35193332bf52605db5e6216c2f27384485` (the only later commit, if any, adds this prompt).

- You rejected the previous head, `317b55e7ba1a06b63b2205f8901fbf041b246e3d`, with 1 blocker and 9 should-fixes. That report is `docs/handoff/astra/results/f1-astra-result.md` on `main`.
- The builder's answer to each finding is in the "Round 2" section of `docs/PHASE_F1_PAYOUT_AVAILABILITY.md` at the new head.
- The branch was rebased on the current `main`, so compare `origin/main...origin/claude/f1-payout-availability` (three dots) for the whole package. Round 2 is the last commit or commits on top of the three round-1 commits.
- Backend code is under `backend/monolith/apps/finance/` and `backend/monolith/apps/core/financial_locks.py`. The rules are in `CLAUDE.md`; money is a "strongest model" area there. The package is section 4 "F1" of `docs/WASSLA_PHONE_TEST_2_PLAN.md`, the owner answers are in its section 6 (Q2: CCP only, no bank RIB rail).

## Background (treat as true)
- Live settings: `PAYOUT_PROFILES_ENABLED=false`; `STRIPE_CONNECT_ENABLED=false` with an empty country allowlist; the private payout (cheque) store is not configured; payout execution is off.
- The owner wants traveler payouts (profiles on, DZD first) switched on soon after F1 merges, so the profiles-on paths matter as much as the live ones.
- An Algérie Poste CCP RIP is `007 99999`, then the CCP number padded with zeros to ten digits, then a two-digit key. No verified formula for either key was available, so neither key is computed.

## Your round-1 findings, in short
1. **Blocker.** A DZD-only to EUR-only PATCH racing funding could fund with no rail (`payout_preference_required`). The builder added a per-traveler method-set advisory lock (`lock_payout_method_set`) taken by funding after the Deal aggregate and by every writer that adds a method or changes which are enabled, plus a two-connection PostgreSQL test in both orders (`apps/finance/tests/test_f1_payout_method_set_race.py`).
2. **Should-fix.** EUR selectability with a saved country that left the allowlist; lowercase country stored as typed.
3. **Should-fix.** A bound account of another country made `configure_eur` loop.
4. **Should-fix.** An unresolved account creation still offered `configure_eur`.
5. **Should-fix.** The email refusal outranked profiles off and the role on writes.
6. **Should-fix.** A one-to-four-digit CCP number was its own mask.
7. **Should-fix.** `GET /api/payouts/profiles/dzd` lacked `setup` and `contract_version`.
8. **Should-fix.** A proof uploaded before the store was deconfigured could still be submitted.
9. **Should-fix.** A link failure after binding answered "Nothing changed".
10. **Should-fix.** The write-up promised a 200 read to a banned (inactive) account.

The lead also found that the work in progress copied the EUR account country onto the DZD version through the PATCH; `set_preference` now stores no country on DZD for every caller.

## What to do
1. Mark each finding **fixed**, **partly fixed** (say what is missing) or **not fixed**.
2. Hunt for **new**, real, reachable problems introduced in this round. In particular:
   - **Lock order and deadlocks.** The advisory lock sits after `Payout` and before `TravelerPayoutMethod`; profile writers take `User`, then the set. Look for any path that holds the set (or a method row) and then waits for a Deal, Payout or User row, any funding path that reads methods without the set lock, and any writer that inserts a method or flips `enabled` without it. Check that the race test really proves the interleaving it claims.
   - **Money and idempotency.** The schedule is now provisioned on every route to an existing account, and a failure after binding raises `AccountKeptProviderError`. Can any retry create a second account, re-POST a creation, bind an account to the wrong traveler or country, or change a funded instruction?
   - **The CCP rule.** Can a valid CCP account be refused (leading zeros, Arabic-Indic digits, separators)? Can the masks still reveal the whole number, alone or together? Does the duplicate-account fingerprint still match the same account typed two ways?
   - **Read and write consistency** for the new codes `stripe_account_country_mismatch` and `stripe_account_unresolved` (now 409) and the new `eur.country_supported` and `eur.account_country` fields.
   - **Weakened tests.** Many fixtures changed because the CCP rule changed. Check that no secret, mask or refusal assertion lost its meaning.
3. Report only real, reachable problems. No style opinions.

## Output format
- One opening sentence.
- A table of the 10 round-1 findings: # | Status | Note.
- A table of new findings: Severity (Blocker / Should-fix / Nit) | File and line | Concrete failure (inputs or state → wrong result) | Suggested fix.
- What you checked and found sound, and what you could not check.
- A final line: "Overall verdict: approve" or "Overall verdict: reject".
