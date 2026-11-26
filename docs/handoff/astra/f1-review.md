You are an independent second-pass reviewer. This review is read-only: do not write, commit or push code, and do not comment on GitHub. You may read files and run read-only git commands.

Review pull request #69, "F1: make payout setup availability and actions explicit on the server", in this repository (is-bo/shiptripis), at head commit `317b55e7ba1a06b63b2205f8901fbf041b246e3d`. Use a three-dot diff against `origin/main`, and run `git fetch origin` first if the commit is missing.
- Backend code is under `backend/monolith/apps/finance/`.
- The rules are in `CLAUDE.md`. Money is a "strongest model" area there.
- The package is section 4 "F1" of `docs/WASSLA_PHONE_TEST_2_PLAN.md`. The finding is section 1.3, and the owner answers are in section 6. Q1 is yes: test DZD setup first, then FR-only Stripe. Q2: CCP only, no bank RIB rail.
- The write-up is `docs/PHASE_F1_PAYOUT_AVAILABILITY.md`.

## Background (treat as true)
- Live settings:
  - `PAYOUT_PROFILES_ENABLED=false`
  - `STRIPE_CONNECT_ENABLED=false`, with an empty country allowlist
  - the private payout (cheque) store is not configured
  - payout execution is off
- In the phone test, the payout and payout-method pages returned bare 404s or offered actions the server then refused.

## What F1 claims
- **One gate.** `setup_gate(user)` in `payout_mobile.py` is built from the same checks that refuse each write. Every offered action, preference option and reason comes from it. It calls no provider and writes nothing.
- **Reads while profiles are off.** `GET /api/payouts/methods` and `GET /api/payouts/profiles/dzd` answer 200 with the saved setup and a `setup` block (`available`, `unavailable_reason`, `preference_options`). Each rail has `selectable` and `unavailable_reason`. `contract_version` is `f1.v1`.
- **Funding preference.** `preference_required` is false while profiles are off.
- **History.** The list and detail add only the funded rail's setup actions that are usable now.
- **Removed fields.** `stripe_setup` loses `available`, `can_start_onboarding` and `can_manage`.
- **New stable codes:**
  - `payout_profiles_disabled` (read 200; write 409)
  - `payout_traveler_required` (write 403; sender-only, deactivated or banned)
  - `stripe_connect_no_countries` (409 with a DZD alternative)
  - `payout_evidence_unavailable` (503)
  - existing: `email_verification_required`, `stripe_connect_unavailable`, `payout_country_unsupported`, `stripe_connect_provider_error`
- **Enforcement tightening.** The three Stripe routes now refuse sender-only and banned accounts.
- **Staff routes.** Staff routes on `ProfileView` answer 409 instead of 404 when profiles are off.
- **Mirrored existing rules (unchanged):**
  - EUR is selectable while Connect is off if the allowlist is non-empty.
  - Keeping EUR in a preference change requires its country to still be open.
  - Onboarding without an EUR preference answers `payout_setup_invalid`.
- **No money change claimed.**
- **Rewritten tests:**
  - the 404 assertion in `test_phase8fh1_foundations.py`
  - two `stripe_setup` flag tests in `test_phase8fh2_accounts.py`

## What to hunt for (concrete failures only)
1. **Read and write consistency.** Find any action or `selectable` that the server would still refuse, or a write that succeeds although the gate says it is unavailable. Check every combination of the switches above, plus email, role, banned or deactivated, and allowlist contents.
2. **Authorization and ownership.**
   - another user's UUIDs and revisions;
   - staff versus member paths;
   - whether the new 200 reads leak private fields (CCP/RIP numbers, cheque images, Stripe account IDs, documents) to anyone, including the owner beyond masked values.
   - Every public payload must come from an explicit allowlist with a privacy test.
3. **Money.**
   - Does `preference_required=false` while profiles are off change which rail a funded deal snapshots, or the amounts and FX?
   - Can a preference update race a funding snapshot?
   - Are funded instructions and payout snapshots unchanged?
   - Is idempotency preserved?
4. **Stale and concurrent writes.**
   - revision checks on preference and profile updates;
   - double submits;
   - a switch flipped between the read and the write.
5. **Contract and consumers.**
   - Does any existing mobile code read the removed `stripe_setup` flags or depend on the old 404?
   - Is the `f1.v1` contract coherent for package F2 (`docs/PHASE_F1_PAYOUT_AVAILABILITY.md` handoff)?
   - Is the staff 409 change safe for console pages?
6. **Tests.** Were the rewritten tests justified and not weakened? Do the new tests assert real outcomes for each code?

## Output format
- One opening sentence with your overall view.
- A table: Severity (Blocker / Should-fix / Nit) | File and line | Concrete failure (inputs or state → wrong result) | Suggested fix.
- A short list of what you checked and found sound, and what you could not check.
- Final line: "Overall verdict: approve" or "Overall verdict: reject".

Report only real, reachable problems. No style opinions.
