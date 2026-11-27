# Builder brief G1-A: payment state and money

**Builder:** Claude Opus, extra-high effort. One builder at a time on the branch.
**Start only when** the lead says the plan is approved and gives you Ismail's answers to D1 to D9.
**Plan:** `docs/handoff/LOOP_END_PLAN.md` at commit `e66bb5b`, on branch
`claude/project-thread-mb20d4`. Read it with `git fetch origin claude/project-thread-mb20d4` and
`git show e66bb5b:docs/handoff/LOOP_END_PLAN.md`. If the lead names a later commit, use that one.
Where this brief and the plan differ, the plan wins, and you tell the lead.

## 1. Your job

Rebuild family G-D on the G1 branch: every reported payment is accounted for before the order
collects again. You own the server's state and money rules. Two briefs follow you on the same
branch: G1-B (jobs) and G1-C (the gate function and the screens).

## 2. Branch and order

- Branch `claude/g1-guest-checkout-csrf`, pull request #67. Last reviewed head: `57684cb`
  (rejected, round 7).
- First merge `origin/main` into the branch with a merge commit.
- You can run beside F1, N1, P3B-A and S1-A. G1-B starts when your work is pushed and green.
- The pull request is reviewed once, after G1-C.

## 3. Read first

1. `CLAUDE.md`.
2. The plan: sections 3 and 4 (rules R5 and R8 are yours), sections 6.1 to 6.3 (G-D1 to G-D6) and
   6.5, the G1 rows of Appendix A, and item 2 of Appendix B.
3. On your branch: `docs/handoff/status/G1.md`, `docs/PHASE_G1_GUEST_CHECKOUT_CSRF.md` and
   `docs/ADMIN_OPERATIONS.md`. Astra's round-7 report is restated in Appendix A; ask the lead for
   the original.

## 4. What you build

Paths are under `backend/monolith/`. Keep three facts apart everywhere: can this checkout still
collect, did the provider report a payment, and what became of the money.

**G-D1. Final means terminal** (`apps/finance/services.py`, `apps/finance/providers/`).
`checkout_final_at` is written by `reconcile_attempt` only, in the same UPDATE statement as the
terminal status. `close_checkout` returns how the provider says the checkout ended (closed unpaid,
failed, expired, cancelled, or a payment under way), and `settle_checkout` passes that outcome on.
Add the check constraint
`checkout_final_at IS NULL OR status IN ('succeeded','failed','expired','cancelled')`.

**G-D2. "Verified" has one meaning.** A reported payment is verified only when the provider's
answer states an amount that is a whole number of minor units and equals the expected one, and a
currency that equals the expected one. A missing amount, a missing currency, a fractional amount
or a mismatch is not verified. One function decides it; `reconcile_attempt` and the staff action
both call it.
**[Guess]** Both providers state a currency in a success answer, or in the read that follows.
Check `providers/stripe.py` and `providers/chargily.py`. If one never does, stop and ask.

**G-D3. Three predicates, stated once** (`apps/finance/models.py`).

- `LIVE_CHECKOUT`: can still collect (as today).
- `HELD_PAYMENT`: a reported debit with no disposition. It is today's `UNVERIFIED_PAYMENT` with one
  more failure code, `paid_after_disposition`.
- `OUTSTANDING`: either of the two.

The finance queue (`payment_attention_queryset` in `apps/finance/operations.py`) keeps its rule:
held, or unapplied with a refund not complete. The unapplied-payment and refund path does not
change.

**G-D4. The gate refuses while a payment is held.** In `_checkout_step`, an order with a
`HELD_PAYMENT` attempt opens and hands out no checkout. The answer is the stable code
`payment_under_review` (409), translated. A hold sends no payment-failed email. The state the
screens read says "under review"; G1-C draws it and later folds your check into the gate function.

**G-D5. A hold ends only by a disposition** (`operations.py` `resolve_payment_attention`;
`apps/admin_panel/console_views.py` `payment_resolve`; `console_forms.py`
`PaymentAttentionResolutionForm`). The four dispositions and their conditions are the table in
plan section 6.3. For the two staff ones:

- The provider read returns a typed answer: no payment and final; paid and verified; paid and not
  verified; open; processing; unreadable. Open, processing and unreadable allow no disposition.
- `no_debit` needs "no payment and final". `returned` needs a final checkout with a reported
  payment, the provider's payment reference (equal to the one read, when the provider gave one)
  and the evidence that the money went back.
- The action reads the provider first, outside any transaction. Then one transaction locks the
  attempt, checks that it is still held with the same code and reference, writes the disposition
  (actor, reason, reference, evidence) and writes the audit row. The console view's transaction
  wraps only that second step.
- The form offers `no_debit` and `returned` for a held payment. "Resolved", "dismissed" and
  "superseded" stay for the other kinds of item.
- Schema: two new `operational_resolution` choices, and one new column for the provider payment
  that a `returned` disposition accounted for.

**G-D6. Automatic paths obey the disposition** (`reconcile_attempt`, under the attempt row lock).
For an attempt staff closed: a report of the payment that a `returned` disposition accounted for
changes nothing. Any other reported success puts the attempt back on hold with
`paid_after_disposition`, clears the disposition (the audit log keeps it) and records the event,
once, whichever path saw it. That hold is never applied automatically. Only `returned` closes it.

## 5. What you remove

`_record_checkout_final`. The gate's "final but open" branch. The "resolved, dismissed,
superseded" choices for a held payment. The acceptance of an empty currency in
`reconcile_attempt`.

## 6. What is not yours

- `apps/finance/jobs.py` and how jobs are armed (G1-B). Use the arming that exists.
- The gate function and every screen (G1-C). You add one check to `_checkout_step` and one code.
- Guest link expiry, the Chargily create idempotency, the payout preflight (follow-ups and C1).
- Closed families G-A, G-B and G-C: their tests stay green and their code stays as it is.

## 7. Tests

Red first: round-7 blocker 1 (an unverified payment does not stop a new checkout), blocker 3
(staff resolve while a read is in progress, and the late success is applied) and should-fix 1
(a close that learns "failed" leaves the attempt final and `processing`).

Start the state table of plan section 6.5 as data, and generate tests from it. Your part:

- states S5 to S11, with every money event: each webhook variant (verified; no amount; no
  currency; fractional amount; mismatch; failed), each staff disposition on each typed provider
  answer, staff reconcile, the order paid by another attempt;
- for each: the next state, the answer, the ledger effect and the finance queue;
- both orders of webhook against staff disposition, and of a provider read against staff
  disposition, with real threads;
- late evidence: a success seen only by a provider read after each disposition; the same report
  twice; the unapplied-refund queue unchanged.

Mechanical checks: the check constraint; `checkout_final_at` assigned in one function; the three
predicates stated once; a test gateway that fails if it is called inside a transaction.

## 8. Done when

1. The three findings above are tests, red before and green after.
2. Your rows of the state table pass. G1-B and G1-C extend the same table.
3. The migration is generated, `task check-drift` is clean and the contract is committed.
4. `docs/ADMIN_OPERATIONS.md` says how Finance uses the two dispositions. The disposition form has
   360 px screenshots in English and Arabic. New strings exist in three languages.
5. CI is green on your head, and the status file tells G1-B where the predicates and the settle
   handler stand.

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
- `docs/handoff/status/G1.md` on the branch, rewritten to say where the work stands,
  and what G1-B needs to know.
