# F1b: Finance retires a Stripe payout account, and the readiness job checks its environment (2026-11-28)

Brief F1b (`docs/handoff/builders/F1b.md`). Server and console only. No migration, no switch, no new
payout state, no app change. Nothing deployed. Needed before Stripe Connect opens beyond the
France-only test; not needed for payouts on (O4).

## 1. Retire an account

A connected account never changes country, and a traveler has one active account per platform and
mode. A traveler whose account was opened for FR and who now declares DE was stuck on
`stripe_account_country_mismatch`, and nothing ever set an account inactive.

`payout_accounts.retire_account(actor, account_id, reason)`:

- `retry_payouts` and `view_payouts` (Finance and Super Admin), through `require_capabilities`. A
  reason is required (`reason_required`).
- One transaction, locks in the order of `apps/core/financial_locks.py`: every Payout that names the
  account (its snapshot `stripe_account` or its active instruction's), ascending id; the traveler's
  EUR method; the account.
- Refused with `already_retired` when the account is inactive: nothing is written.
- Refused with `payout_in_progress` while one of those payouts is `processing`, `sent` or `failed`
  (`PAYOUT_IN_PROGRESS`): Stripe work on the account has begun and is not finished. The existing
  payout states say it; no new state.
- Sets `active=False`; status and reason come from `evaluate_readiness`, which already answers
  `unavailable` / `account_replaced` for an inactive account. The method's status follows
  (`_sync_method_status`). One `AdminAuditLog` row `payout_account.retired`: actor, target, before
  (active, status, reason, country), after, and the reason.
- Funded payout rows and method versions are not touched.

What follows from it, with no other change:

- `standing_accounts` filters `active=True`, so it no longer returns the account.
- `_creation_operation` passes over the creation whose account is retired (an `Exists` annotation on
  the same query, so reads keep their statement count). The next onboarding opens attempt `v2` with
  a new idempotency key, for the country the method now declares.
- `payout_mobile._eur_rail` treats a bound account that is retired like no account, so the payout
  page offers `configure_eur` again (F1's states, none added). This matters when Finance retires
  before the traveler changes country.
- Execution already refuses an inactive destination (`_assert_dispatchable`, `account_missing`).
  `_lock_payout_aggregate` now reads the account's `active` again after taking the Payout lock: the
  locking query's join can predate a retirement that committed while it waited. Without it a
  dispatch that queued behind the retirement sent the transfer to the retired account (red test).

Console: **Retire Stripe account** on the traveler's Payouts tab (only with `retry_payouts`), to
`finance/payout-accounts/<id>/retire/`, guarded by the same capability; the form collects the reason
and shows the domain's refusal text. `docs/ADMIN_OPERATIONS.md` says when and how.

## 2. The readiness job guard

`jobs.handle_payout_account_refresh` returns `account_other_environment` before any provider call
when `in_this_environment(account)` is false (another platform, or another mode), the check
`destination_account` makes for the member's calls. The job ends as done with that result recorded.

## 3. Not done

- The account at Stripe is not closed or changed; only Wassla stops using it.
- A payout already funded to the retired account stays blocked at execution; Finance settles it as any
  other blocked payout (no new action, per the brief).

## Evidence

Red: each fix removed in turn against the new tests (local runs, 2026-11-28).

| Rule | Test | Red without | Green |
| --- | --- | --- | --- |
| FR account, traveler wants DE, retire, next onboarding creates and binds DE; audit row | `test_f1b_retire_account::test_retiring_the_account_lets_the_next_onboarding_open_one_for_the_declared_country` | creation pass-over | yes |
| Retired while still bound: setup offered again, new account bound | `test_f1b_retire_account::test_a_retired_account_still_bound_to_the_method_is_offered_setup_again` | `payout_mobile` change | yes |
| Refused without the permission (ops, support, trust) | `test_retiring_needs_the_finance_permission`, `TestConsoleForm::test_staff_without_the_permission_get_no_form` | new | yes |
| Refused without a reason | `test_retiring_needs_a_reason`, `TestConsoleForm::test_the_form_refuses_an_empty_reason` | new | yes |
| Refused while a payout is processing, sent or failed | `test_retiring_is_refused_while_a_payout_to_the_account_is_in_progress` | new | yes |
| Funded instruction rows identical; execution refuses the account | `test_funded_payout_instructions_are_unchanged_and_no_longer_dispatch` | new | yes |
| Retiring twice writes nothing | `test_retiring_twice_reports_it_is_already_retired_and_writes_nothing` | new | yes |
| A dispatch queued behind the retirement sees it | `RetireRacesDispatchTests` (threads, PostgreSQL) | `_lock_payout_aggregate` re-read | yes |
| Console form from the payout page | `TestConsoleForm::test_finance_retires_with_a_reason_from_the_travelers_payout_page` | new | yes |
| Job: current platform refreshed; other platform or mode, no provider call | `test_f1b_refresh_job_environment` | job guard | yes |

Screenshots of the console form and the payout tab: in the pull request.
