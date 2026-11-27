# Brief DC: remove unused code on the server and in the Go services

**Builder:** Claude Opus, high effort. Some candidates are in money files.
**Branch:** new, from the tip of `main`, after L1 to L4 and the feature packages of `HANDOFF.md`
0.4 have merged, so that the sweep runs once on the code as it will be tested.
**Read first:** `CLAUDE.md`; `docs/handoff/builders/README.md`; the plan
(`docs/handoff/LOOP_END_PLAN.md`) sections 3.5 and 7.2.

## 1. Your job

Remove code that nothing calls. Deleting it changes no behaviour. If a deletion would change an
answer, the code was not dead: put it back and list it.

## 2. Candidates (the planner's scan of `main` at `b4b838f`, before L1 to L4)

Each was found by a static scan and a repository-wide count of its name. Each may have a use the
scan cannot see (a template, a string, `getattr`, Django's own lookups). You confirm every one.

Paths are under `backend/monolith/`.

- **Classes:** `CanViewDisputeEvidence` (`apps/core/permissions.py`), `PayoutReleaseRefused`
  (`apps/finance/payout_release.py`), `SearchForm` (`apps/admin_panel/console_forms.py`).
- **Functions:** `_link_factory` (`apps/admin_panel/finance_dashboard.py`), `freeze_reason_for`
  (`apps/finance/payout_reconciliation.py`), `scheduled_job_kinds`
  (`apps/finance/payout_provider_events.py`), `validate_from_settings`
  (`config/settings/connect.py`).
- **Properties and methods:** `is_no_show` (`apps/problems/models.py`), `is_paused`
  (`apps/trips/models.py`), `net_paid_eur_cents` (`apps/finance/models.py`), `return_ok` and
  `set_ok` (`apps/finance/providers/http.py`), `bulk_update` (`apps/finance/payout_models.py`).
- **Called only by tests:** `prepare_attempt` and `prepare_provider_operation`
  (`apps/finance/payout_operations.py`), `resume_account` (`apps/finance/payout_accounts.py`),
  `revoke_identity` (`apps/finance/payout_profiles.py`), `account_balance`
  (`apps/finance/ledger.py`), `cancel_bank_payout` and `reverse_transfer`
  (`apps/finance/providers/stripe_connect.py`), `parse_corridor_points`
  (`apps/routing/geometry.py`), `reset_storage_clients` (`apps/core/storage.py`).
- One unused import and two blocks of commented-out code that the linter's extra rules report.

## 3. How

1. **Run the scan again** on the tip of `main`, because L1 to L4 and the features changed the
   list. Use a dead-code scanner for Python and one for Go, run locally. Add no tool to CI and
   no dependency to the project.
2. **Confirm each candidate:** search the whole tree for its name, including tests, fixtures,
   templates, settings, URL configuration, strings and dynamic lookups.
3. **"Called only by tests" needs a decision per item.** A function that only a test calls is
   dead, and goes with that test, unless it is a test helper by purpose (`reset_storage_clients`
   may be one): then it stays and you say so. A method that overrides a guard on purpose
   (`bulk_update` may block a bulk write) is not dead: it stays.
4. A provider method that the product will need at launch and that is not parked scope
   (`cancel_bank_payout`, `reverse_transfer`) is a question, not a deletion. Ask the lead.
5. One commit per app.

## 4. What is not yours

Code with a live caller, however badly it reads. Large functions and large files. The app (MC).
Parked scope has no code to keep: if you find a hook for professional transporters, the manifest
dashboard, custody history or courier handoff, list it for the lead.

## 5. Proof

- The whole suites are green, Go included. Each removed test is listed with what it called.
- No migration is created: `task check-drift` is clean without a change.
- The linters of both languages are green.

## 6. Done when

1. The pull request has one row per candidate: removed, or kept with the reason.
2. You report the lines removed, per app.
3. The status entry is written. A phase document is not needed.
4. Every CI check is green.
