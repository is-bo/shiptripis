# F1b status

Branch `claude/project-thread-13gwfo`. Server and console only, no migration.

- Done: `retire_account` (Finance, reason, audit row, refused while a payout is processing, sent or
  failed, idempotent refusal when already retired); the console form on the traveler's Payouts tab;
  the readiness job's environment guard.
- Outside the brief's list, needed for its rules: `payout_mobile` ignores a retired bound account (so
  setup is offered), and `_lock_payout_aggregate` re-reads the account after the Payout lock (closes a
  race where a queued dispatch sent to a just-retired account). Both have red tests.
- Phase doc: `docs/PHASE_F1B_RETIRE_PAYOUT_ACCOUNT.md`.
