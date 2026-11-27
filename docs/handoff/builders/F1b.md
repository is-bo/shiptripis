# Brief F1b: retire a Stripe payout account, and the readiness job guard

**Builder:** Claude Opus, extra-high effort.
**Branch:** new, from the tip of `main`, after F1 has merged.
**Needed before:** Stripe Connect opens beyond the France-only test. Not needed for payouts on
(operation O4).
**Read first:** `CLAUDE.md`; `docs/handoff/builders/README.md`; the plan sections 3, 5.1 and 6;
`docs/PHASE_F1_PAYOUT_AVAILABILITY.md`; `docs/ADMIN_OPERATIONS.md`.

## 1. Your job

Two small things in the payout account code.

1. A traveler whose Stripe account was opened for the wrong country has no way out: the account's
   country cannot change, and nothing ever sets a Stripe payout account inactive. Add the one
   staff action that retires an account.
2. The scheduled job that refreshes readiness loads its account by id (`apps/finance/jobs.py`,
   near line 650). After a switch to another Stripe platform in the same mode it would send the
   old platform's account id to the new credential. Give it the guard the member's calls have.

## 2. What you build

Paths are under `backend/monolith/`.

**Retire an account** (a console action on the traveler's payout page, in `apps/admin_panel/`,
with the service function in `apps/finance/payout_accounts.py`).

- Finance permission, a required reason, an `AdminAuditLog` row with actor, target, before and
  after. Staff already sign in with a second step.
- One transaction, taking locks in the order `apps/core/financial_locks.py` gives: it sets the
  account inactive with the reason.
- It is refused, with a clear message, while a payout to that account is in progress.
  **[Guess]** The existing payout states say this without a new one. If they cannot, stop and ask.
- Afterwards `standing_accounts` no longer returns the account, and `current_creation` passes
  over the creation that produced it, so the traveler's next onboarding creates a new account for
  the country now declared.
- Funded payout instructions are not changed.
- The traveler's payout page then offers setup again. Use the states F1 already has; add none.

**The job guard** (`apps/finance/jobs.py`). Before the provider call, the job checks
`in_this_environment(account)`, as `destination_account` does for the member's calls. An account
of another platform or mode is not sent: the job ends as done, with the reason recorded.

## 3. What is not yours

Everything else in F1. The phone screens (F2). No second staff action: a creation that stays
unclear is resolved by F1 itself.

## 4. Tests

- Retire, from the stuck state to a working setup: an account for FR, the traveler wants DE,
  staff retire it, the next onboarding creates a DE account and binds it. The audit row is
  checked.
- Refused: without the permission; without a reason; while a payout to the account is in
  progress.
- The funded instruction rows are identical before and after.
- Retiring twice: the second attempt reports that it is already retired and writes nothing.
- The job: an account of the current platform is refreshed; an account of another platform or
  mode makes no provider call.

## 5. Done when

1. Every case of section 4 passes.
2. `docs/ADMIN_OPERATIONS.md` says when and how Finance retires an account.
3. A screenshot of the console form is in the pull request.
4. The phase document and the status entry are written.
5. Every CI check is green.
