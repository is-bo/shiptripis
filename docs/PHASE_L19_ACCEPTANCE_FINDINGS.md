# Phase L19: Findings of final acceptance

Package L19 of `docs/WASSLA_DISCOVERY_PRO_PLAN.md` (plan L19 and 5.1g). L10 found two low faults
(`docs/WASSLA_L_SERIES_RELEASE_REPORT.md`, section 14) and, by its own rule, fixed neither. This
package fixes both, after L10 merged, so that L10's acceptance tests run on the code that ships.

Backend only. **No migration**, no Go, mobile or landing change, no new switch.

## 1. The helper's notes say what the server does

- `apps/admin_helper/skill/knowledge/architecture-and-diagrams.md`: the sentence "The server code has a
  staff-side way to open a dispute, but no console page or staff API uses it." is gone. L18A removed
  that code (`open_dispute(as_admin=True)`). "Staff cannot open a dispute today." stays.
- The whole skill was searched for `as_admin`, `close_dispute` and any staff way to open a dispute.
  Nothing else described removed code. Two lines narrowed the claim to the console, which suggested
  another way might exist; both now say it plainly:
  - `stakeholder-questions.md`: "Staff cannot open a dispute from the console today." became
    "Staff cannot open a dispute today."
  - `overview-and-glossary.md`: "(no console page lets staff open one)" became "(staff cannot open one)".
- `INSTRUCTIONS.txt` regenerated with `python manage.py build_helper_instructions`; `--check` passes.
- New guard, `apps/admin_helper/tests/test_l19_notes.py`: no line of the skill or of
  `INSTRUCTIONS.txt` describes, in plain words, a staff way to open a dispute, and both notes still
  say staff cannot. L18A's own search (`apps/disputes/tests/test_l18a_removed_paths.py`) already
  proves that no code and no note names the removed functions, so this test does not repeat it (and
  names neither function, which that search forbids).

### Proof conversation, rerun

As in L10 (`docs/PHASE_L10_FINAL_ACCEPTANCE.md`, section 3): one Haiku agent told to follow the skill
folder only, with no server and no key.

| Admin typed | Notes read | Result |
| --- | --- | --- |
| "Can staff open a dispute for a member, from the console or any other way? If a sender phones us and says the parcel arrived broken, what do we do?" | `SKILL.md`, `problems-and-disputes.md`, `admin-console.md` | "No. Staff cannot open a dispute, from any console page, the staff API, or the AI helper." Then the steps for the caller: the sender opens it in the app with "Arrived damaged" and photos, inside the window (pickup to 48 hours after delivery), which freezes the payout; who can move and resolve it; and that whether staff should be able to is an open decision for the owner. **Correct.** |
| Conversation 11 of L17: "How does Wassla make money, who gets paid what and when, and how many users do we have?" | `money.md`, `pricing.md`, `stakeholder-questions.md` | 25% on top, rounded up; the traveler gets the whole reward and boost 48 hours after delivery; a dispute freezes the payout; no user count in the notes, and where to look. **As L17.** |

Every sentence it found about staff and disputes says staff cannot open one. None describes a staff
path.

## 2. A payout carries the mode of the money that funded it

**Before.** With `PAYOUT_PROFILES_ENABLED` off, `ensure_payout_for_deal` (`apps/finance/services.py`)
created the payout without a mode, so it took the column default `legacy_unknown` while its funding
attempt was in `test`. The ledger's mode rule (one mode for a transaction, `legacy_unknown` when its
legs disagree) then put the payout transaction in `legacy_unknown`, and the finance dashboard showed
one deal's traveler outstanding as 0 in test and −11.00 in `legacy_unknown`.

**After.** That branch reads the deal's funding the way the profile path does and gives the payout
its funding attempt's mode. It keeps `legacy_unknown` only when no capture funded the deal.

- `apps/finance/payout_snapshots.py`: new `deal_funding_order(deal_id)`, the deal's latest
  non-cancelled balance order. It is the query `create_snapshot` already ran inline; `create_snapshot`
  now calls it (same query, same result: the profile path's behaviour is unchanged).
- `ensure_payout_for_deal`, profiles off: `source = funding_attempt(deal_funding_order(deal_id))`, and
  the new row gets `provider_mode=source.provider_mode` (else `legacy_unknown`). Nothing else on the
  row changes: method, notes, status and the release job are as before.
- Fixed at the payout row: the ledger's mode rule, the dashboard and the exports are not touched, and
  no label was added. No backfill (no real data).
- Live mode cannot reach this branch (`config/settings/payments.py` requires payout profiles in live
  mode). The profile path (`create_snapshot`) is not changed in behaviour.

## 3. Tests

New, `apps/finance/tests/test_l19_payout_mode.py` (profiles off):

- `FundedPayoutModeTests` (a `TransactionTestCase` over L10's `AcceptanceWorld`, because the
  dashboard reads its own snapshot): a drive, a deal funded in test mode through the mock rail,
  carried, delivered with the recipient's code, protected 48 hours and settled by hand. The payout,
  the funding attempts and every ledger transaction of the deal are in `test`; the test-mode dashboard
  shows the reward settled and the traveler outstanding at 0; every `legacy_unknown` metric is 0 and
  the three `legacy_unknown` exports are empty; the test-mode exports reconcile with the dashboard
  (payouts settled, fee kept, gross funded).
- `UnfundedPayoutTests`: an accepted deal with no capture behind it still gets `legacy_unknown`.

Both new test files fail on the code before this package (checked by reverting each fix) and pass
after it.

Existing tests:

- No test asserted `legacy_unknown` for a funded payout without profiles, so no expectation changed.
  `test_phase8fh1_migrations.py` still asserts `legacy_unknown` for a payout written before the mode
  column existed, which this package does not touch.
- Profiles on: every existing test unchanged.
- L10's 22 acceptance tests: no assertion changed. `test_the_three_exports_add_up_to_the_finance_dashboard`
  already read the payout's mode from the row, so it now downloads the payouts in `test`. Its comment,
  which said the manual path "leaves its money mode unknown", was the only line changed in L10's files.
- `test_j2_h5_regression.py`: its module docstring said a payout without profiles "is stamped
  `legacy_unknown`"; now it only says why the world runs with profiles on. No code changed.

Counts: Django 3,270 before, 3,274 after (+4). See section 5 for the runs.

## 4. Judgment calls

1. The two "console only" lines in the notes (section 1) were tightened as well as the one the plan
   named. They were true, but read as if a non-console staff path existed.
2. The order lookup moved into `deal_funding_order` so that both payout paths share one query instead
   of a second copy (quality bar: one home per rule). `create_snapshot`'s behaviour is identical.
3. The comment in L10's export test was corrected (no code or assertion changed), so the acceptance
   test does not describe the fault this package fixed.
4. `_funding_provider(order)` in `apps/finance/services.py` stays: it feeds the method choice and
   differs from `funding_attempt` for an order funded only by a credited deposit. Merging the two would
   change a payout method result, which is outside this package. Listed for the cleanup scan.

## 5. Checks

- `python -m ruff check .`: clean. `python manage.py makemigrations --check --dry-run`: no changes.
- `python manage.py build_helper_instructions --check`: up to date.
- Whole Django suite on PostgreSQL 16 and Redis 7, the four CI shards run locally: see the pull request
  for the counts; CI's checks are recorded on it.
- No Go, Flutter or schema change, so Go, Flutter and Schema drift are covered by CI alone.
