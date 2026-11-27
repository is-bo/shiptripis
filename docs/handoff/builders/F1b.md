# Builder brief F1b: payout account repair by Finance

**Builder:** Claude Opus, extra-high effort. One builder at a time on the branch.
**Start only when** the lead says the plan is approved and gives you Ismail's answers to D1 to D9.
**Plan:** `docs/handoff/LOOP_END_PLAN.md` at commit `e66bb5b`, on branch
`claude/project-thread-mb20d4`. Read it with `git fetch origin claude/project-thread-mb20d4` and
`git show e66bb5b:docs/handoff/LOOP_END_PLAN.md`. If the lead names a later commit, use that one.
Where this brief and the plan differ, the plan wins, and you tell the lead.

## 1. Your job

Add the two staff actions that give Finance a way out of two stuck payout-account states. Neither
action exists today, on `main` either. Payouts stay switched off until this merges (decision D9),
and with Connect off both states are unreachable.

## 2. Branch and order

- A new branch from the tip of `main`, after F1 has merged. The lead names it. One pull request.
- C1 does not wait for you. Switching payouts on does.

## 3. Read first

1. `CLAUDE.md`, above all the staff rules: the second step, and an `AdminAuditLog` row with actor,
   target, before, after and a required reason.
2. The plan: sections 3 and 4, section 7.3 (F-C3 and F-C5) and section 7.7.
3. On `main` after F1: `docs/PHASE_F1_PAYOUT_AVAILABILITY.md` and `docs/ADMIN_OPERATIONS.md`.

## 4. What you build

Paths are under `backend/monolith/`. Both actions live in the staff console (`apps/admin_panel/`),
with their rules in `apps/finance/payout_accounts.py`.

**Settle a creation.** Allowed only for a creation past the replay window whose search found
nothing (`CREATION_NOT_FOUND`). Finance looks at Stripe and records one of two findings, with a
reason:

- No account exists. The operation becomes a definite failure. The freeze ends, and the next
  onboarding call starts a new attempt.
- This account exists, with its id. The id is recorded on the operation. The next onboarding call
  retrieves it and binds it through the normal path. The action itself binds nothing.

**Retire an account.** Sets a `StripePayoutAccount` inactive, with a reason. Refused while a payout
to that account is in progress. Afterwards the creation that produced the account is passed over,
so the next onboarding call creates a new account for the country now declared. Funded payout
instructions and their snapshots do not change.
**[Guess]** "A payout to that account is in progress" maps onto the payout states that exist. If
it needs a new state, stop and ask.

For both:

- The state change and the audit row are one transaction, under the user row lock and then the
  method row lock, in the order F1 uses.
- The action writes nothing at Stripe. If it reads Stripe to show Finance the facts, that read is
  outside the transaction.
- It needs the finance capability that guards the existing reconcile actions, and the staff second
  step.
- In any other state it is refused, with a reason the staff member can read.
- `docs/ADMIN_OPERATIONS.md` says when and how to use each.

## 5. What you remove

Nothing is expected. If F1's "waiting for support" state has no link from the console to the new
action, add the link.

## 6. What is not yours

Closing an account at Stripe: Finance does that in Stripe's dashboard. How payouts are executed.
The phone screens. Any change to F1's freeze or read model.

## 7. Tests

- Each action from the stuck state to a working setup, through the public entry points:
  stuck creation, settled as "none", onboarding creates and binds; stuck creation, settled as
  "exists", onboarding retrieves and binds; an account for the wrong country, retired, onboarding
  creates one for the new country.
- Refusals: settle inside the window; settle an operation that is not "not found"; retire during a
  payout; no reason; no capability; no second step.
- Real threads, both orders: settle against an onboarding call; retire against the funding of a
  payout to that account; two staff members on the same item.
- The funded-instruction rows are identical before and after each action.
- The audit row of each action is checked, field by field.

## 8. Done when

1. Each stuck state reaches a working setup in a test, with the audit row checked.
2. The refusals and races above pass.
3. Strings in English, French and Arabic where the app or the console shows something new, and a
   360 px screenshot of each new console form in English and Arabic.
4. A phase document with the evidence table, and every CI check green.

## Rules, the same for every builder

1. Build what this brief names and nothing else. Add no lock, counter, generation, flag, column,
   job kind or retry loop that the plan does not name. If one seems needed, stop and ask.
2. Red first. Reproduce each finding listed under "Tests" as a failing test before you fix it. A
   failing test must tell the bad outcome apart from a correct serial execution.
3. Group tests by family, in files named after the invariant. Never skip, delete or weaken a test.
   A test of a mechanism you delete is rewritten to the new rule, and the pull request lists it
   with the reason.
4. Remove what you replace in the same pull request. The tests of the closed families stay green.
5. The server enforces every rule. The app never fakes a result. Every user-facing string exists
   in English, French and Arabic.
6. After a migration, run `task check-drift` in `backend/` and commit the regenerated contract.
7. Push only to your branch, with ordinary pushes: no force push, no rebase of pushed commits. The
   whole suites and the Android build run in GitHub CI on the branch. While you fix, re-run locally
   only the tests that failed. The work is ready only when every CI check is green, "Schema drift"
   included.
8. Never deploy, never restart or change a server, never build the app for a device. The
   repository is public: no server address, account email, key, token or password in a file, a
   commit, the pull request or a comment.
9. Do not edit `HANDOFF.md`, the plan, or files that belong to another brief. Do not merge. Write
   nothing on GitHub except the pull request description.
10. No model name in a commit, a pull request or a document. Do not use the word "partner".

## Stop and ask the lead when

- a fix needs a mechanism the plan does not name;
- the code cannot do what the plan says, or the plan and the code disagree about a fact;
- a change would alter a money, code or matching result in a way the plan does not state;
- something marked **[Guess]** turns out to be wrong;
- the only way forward would weaken a test.

Say what you found, with file and line, and what you would do. Then wait. The lead takes it to the
planner. Do not patch around it.

## What you hand back

- The branch pushed, CI green on its head, and that head's commit id.
- The evidence table: one row per finding under "Tests", with the finding, the report it came
  from, the red test and the commit where it fails, the green test, and device evidence where this
  brief asks for it.
- The inventory of writers and callers of each mechanism you built: who writes the field, who
  calls the function.
- The tests you removed or rewrote, each with its reason.
- What you saw outside this brief, as a note for a follow-up. Do not fix it.
- `docs/handoff/status/F1B.md` on the branch, rewritten to say where the work stands.
