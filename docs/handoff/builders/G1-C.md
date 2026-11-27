# Builder brief G1-C: the checkout gate and the screens

**Builder:** Claude Opus, extra-high effort. One builder at a time on the branch.
**Start only when** the lead says the plan is approved and gives you Ismail's answers to D1 to D9.
**Plan:** `docs/handoff/LOOP_END_PLAN.md` at commit `e66bb5b`, on branch
`claude/project-thread-mb20d4`. Read it with `git fetch origin claude/project-thread-mb20d4` and
`git show e66bb5b:docs/handoff/LOOP_END_PLAN.md`. If the lead names a later commit, use that one.
Where this brief and the plan differ, the plan wins, and you tell the lead.

## 1. Your job

Close family G-F on the G1 branch: screens offer exactly what the gate allows. You replace two
statements of the same rule with one pure function, and you make the two phone screens keep a
refusal over an older read. You are the last brief on the branch, so you also finish the pull
request.

## 2. Branch and order

- Branch `claude/g1-guest-checkout-csrf`, pull request #67. You start from G1-B's pushed, green
  head. Pull first.
- After you, the lead writes the Astra prompt for the whole pull request.

## 3. Read first

1. `CLAUDE.md`, including the mobile rules.
2. The plan: sections 3 and 4 (rules R6 and R9, and the `ReadOrder` helper), section 6.3 (G-D4,
   G-F1, G-F2), 6.5, 6.6, and item 2 of Appendix B.
3. On your branch: `docs/handoff/status/G1.md` as G1-B left it, and
   `docs/PHASE_G1_GUEST_CHECKOUT_CSRF.md`.

## 4. What you build

**G-F1. One gate function over stated facts** (`backend/monolith/apps/finance/services.py`:
`_checkout_step`, `_hands_back`, `next_checkout`; `views.py`; `guest_web.py`).
`checkout_gate(facts)` is a pure function. The facts are: the order (collectable, amount
outstanding), its attempts, the caller (the owner, or a guest link and what it may do), the rail
asked for and the rails available, the amount, and the time.

- `_checkout_step` builds the facts under the order lock and acts on the answer.
- The read path builds the same kind of facts without the lock and maps the answer to a screen
  state. No condition is stated twice. G1-A's `HELD_PAYMENT` check moves into the function.
- Owner states: ready, resumable (with its rail), settling, guest paying, in progress, under
  review.
- Guest states: ready, in progress, paid, inactive. "In progress" is one neutral message for
  every case where the guest must wait or must not pay again. It never says who is paying.
- For the same facts and the same time, the gate and the read path agree. A screen cannot predict
  a later webhook, and a refusal after an older read is not a disagreement.
- The payout preflight is not part of the function. Leave it where it is (C1).

**G-F2. A refusal beats an older read** (`mobile/lib/features/requests/checkout_section.dart`,
`mobile/lib/features/guest/guest_pay_screen.dart`, `guest_payment_sheet.dart`). Both screens use
`ReadOrder`, one instance per order. If `mobile/lib/core/read_order.dart` is not on `main` yet,
create it with its tests exactly as plan section 4 describes; if it is, use it unchanged.

**The "under review" state on screen.** The owner's section and the guest page show G-D4's state:
a payment for this order is being checked, do not pay again. No surface says "nothing was
charged" for a held payment: not the app, not the guest web page.

## 5. What you remove

The conditions restated in `next_checkout`. Any screen logic that decides by itself what the
server would accept.

## 6. What is not yours

- Money rules and dispositions (G1-A) and jobs (G1-B). If the gate needs a fact they do not
  expose, add the read, not a second rule.
- The provider list against the payout preflight, guest link expiry, Chargily create idempotency
  (follow-ups and C1).
- The guest page's capability rules (closed family G-A).

## 7. Tests

Red first: round-7 should-fix 3 (an older successful read re-enables a refused action), on both
phone screens.

Then, completing the state table:

- for every state S0 to S11: what the owner screen and the guest screen offer;
- the property: for the same facts and time, what the screens offer equals what the gate accepts;
- owner detail, deposit summary, guest web page and guest app screen;
- a refused tap followed by an older read; a failed refresh; a paid order; a cancelled order;
- `ReadOrder`: two reads answered in reverse order; a change answered after a newer read.

## 8. Done when

1. The finding above is a test, red before and green after, and the property test passes.
2. Screenshots in English and Arabic at 360 px of the "being checked" state on the owner screen,
   the guest app screen and the guest web page. Nothing hides behind the bottom navigation.
3. New strings exist in English, French and Arabic.
4. `docs/PHASE_G1_GUEST_CHECKOUT_CSRF.md` describes the final design of all six families in about
   200 lines, with one evidence table for G1-A, G1-B and G1-C. The entry in
   `docs/IMPLEMENTATION_STATUS.md` is updated.
5. The pull request description lists each "Done when" line of plan section 6.6 with its
   evidence, the tests removed or rewritten on the whole branch, and the inventory of writers.
6. Every CI check is green.

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
- `docs/handoff/status/G1.md` on the branch, rewritten to say where the work stands.
