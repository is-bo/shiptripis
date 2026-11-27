# Brief G1-A: held payments and finality

**Builder:** Claude Opus, extra-high effort.
**Branch:** `claude/g1-guest-checkout-csrf`, pull request #67. Last reviewed head: `57684cb`
(rejected, round 7). First merge `origin/main` into the branch. G1-B and G1-C follow you on the
same branch, one builder at a time.
**Starts:** when the lead gives you Ismail's answers to the plan's decisions (D2 is yours).
**Read first:** `CLAUDE.md`; `docs/handoff/builders/README.md`; the plan
(`docs/handoff/LOOP_END_PLAN.md`) sections 3, 4 and 5.2 and the G1 rows of Appendix A; on your
branch `docs/handoff/status/G1.md` and the G1 phase document; `docs/ADMIN_OPERATIONS.md`.

## 1. Your job

Close rule G-D: every reported payment is accounted for before the order collects again. Three
facts are kept apart: can this checkout still collect (finality), did the provider report a
payment (evidence), and what became of the money (disposition).

## 2. What the code does today (checked at `57684cb`)

Paths are under `backend/monolith/apps/finance/`.

- The gate `_checkout_step` (`services.py`) checks `LIVE_CHECKOUT` and never
  `UNVERIFIED_PAYMENT`.
- `_record_checkout_final` sets `checkout_final_at` without a terminal status.
- `reconcile_attempt` accepts a success with an empty currency, applies a late success to a
  failed attempt without reading `operational_resolution`, and saves `checkout_final_at` in an
  earlier statement than the status.
- The console's `payment_resolve` view (`admin_panel/console_views.py`) calls
  `resolve_payment_attention` (`operations.py`) and writes the audit row. The form
  (`PaymentAttentionResolutionForm`) offers "resolved", "dismissed" and "superseded".

## 3. What you build

**G-D1. Final means terminal.** `checkout_final_at` is written by one function,
`reconcile_attempt`, in the same UPDATE as the terminal status. `_record_checkout_final` goes.
`close_checkout` returns how the provider says the checkout ended (closed unpaid, failed, expired,
cancelled, or a payment under way), and `settle_checkout` passes that on. A check constraint:
`checkout_final_at IS NULL OR status IN ('succeeded','failed','expired','cancelled')`.

**G-D2. "Verified" has one meaning.** One function. A reported payment is verified only when the
provider's answer states an amount that is a whole number of minor units and equals the expected
one, and a currency that equals the expected one. Anything missing, fractional or different is
not verified. **[Guess]** Both providers state a currency in a success answer, or in the read
that follows it; then the hold heals by itself.

**G-D3. Three predicates, stated once, in `models.py`.**

- `LIVE_CHECKOUT`: can still collect.
- `HELD_PAYMENT`: a reported payment that is not verified, or that arrived after staff closed
  the item, and that has no disposition. This is today's `UNVERIFIED_PAYMENT` with one more
  failure code, `paid_after_disposition`.
- `OUTSTANDING`: `LIVE_CHECKOUT` or `HELD_PAYMENT`. The gate, `settle_checkout`'s early return,
  the sweep and `_already_satisfied_reason` read this one.

The finance queue keeps its rule: held, or unapplied with a refund not complete.

**G-D4. The gate refuses while a payment is held.** An order with a held attempt opens and hands
out no checkout. The answer is the stable code `payment_under_review` (409), translated: a
payment for this order is being checked, do not pay again. No surface says "nothing was charged"
for a held attempt: not the app, not the guest page, not the payment-failed email (a hold sends
none).

**G-D5. A hold ends in one of five ways, and in no other.**

| How | Who | Condition |
|---|---|---|
| Applied | Automatic | A verified report, on a hold staff never closed. Credited once, by the existing path. |
| Unapplied and refunded | Automatic | A verified report that the order cannot absorb. The existing path. |
| Released | Automatic | The settle job's read of the provider says: the checkout is final and holds no successful payment. Only for a hold staff never closed. The attempt becomes an ordinary failed attempt. |
| `no_debit` | Staff | Finance saw at the provider that no money was taken. A required reason. |
| `returned` | Staff | Finance saw that the money went back. A required reason and the provider's payment reference, which must equal the one stored on the attempt when one is stored. |

- The provider read in `settle_checkout` gives a typed answer: final with no payment; paid and
  verified; paid and not verified; open; processing; unreadable. Open, processing and unreadable
  change nothing.
- The staff action makes no provider call. It is one transaction: lock the attempt, check it is
  still held with the same failure code, write the disposition with actor, reason and reference,
  write the audit row.
- The form offers `no_debit` and `returned` for a held payment. "Resolved", "dismissed" and
  "superseded" stay for the other kinds of item.
- The reference of a `returned` disposition is kept on the attempt. Use a column the attempt
  already has for the provider's payment id. Add one column only if none can hold it.

**G-D6. Automatic paths obey the disposition.** In `reconcile_attempt`, under the attempt's row
lock, for an attempt staff closed:

- a report of the payment that a `returned` disposition names changes nothing;
- any other reported success puts the attempt back on hold with `paid_after_disposition`, clears
  the disposition (the audit log keeps it) and records the event, once, whichever path saw it;
- a hold with that code is never applied or released automatically. Only `returned` closes it.

The staff action and `reconcile_attempt` take the same row lock, so the second sees the first.

## 4. What you remove

`_record_checkout_final`; the gate's "final but open" branch; the "resolved", "dismissed" and
"superseded" choices for a held payment; every second statement of the three predicates.

## 5. What is not yours

Jobs and the sweep (G1-B). The gate function and the screens (G1-C): you add the
`payment_under_review` answer and its strings, G1-C draws the state. The payout preflight (C1).

## 6. Tests

Red first: round-7 blocker 1, blocker 3 and the Chargily should-fix (plan Appendix A).

Write the cases as a table of data and generate the tests from it.

- **Attempt states:** opening; never opened; open and payable; closing; settling; ended locally
  with the provider not confirmed; paid; ended and confirmed; held; closed by staff as
  `no_debit`; closed as `returned`; held again after a disposition.
- **Events:** a tap by the member who opened it; a tap by another member or a guest; a webhook
  (paid and verified, paid with no amount, with no currency, with a fractional amount, with a
  mismatch, failed); the settle read, for each typed answer; a close confirmed unpaid, refused
  because a payment is under way, or reporting a failure; expiry; each staff disposition; the
  order stops collecting; the order is paid by another attempt.
- For every state and every event that can reach it: the next state, the answer, the ledger
  effect and the finance queue.
- **Both orders of:** webhook and staff disposition; settle read and staff disposition; tap and
  webhook.
- **Late evidence:** a success seen only by a provider read, after each disposition; the same
  report twice; a `returned` reference that does not match.

Mechanical checks: the check constraint; `checkout_final_at` assigned in one function; the three
predicates stated once; the test gateway fails when it is called inside a transaction.

## 7. Done when

1. The three findings are tests, red before and green after, and the table passes.
2. The migration is generated, `task check-drift` is clean, the contract is committed.
3. `payment_under_review` and the staff form's strings exist in three languages.
4. `docs/ADMIN_OPERATIONS.md` says how Finance uses the two dispositions.
5. `docs/handoff/status/G1.md` tells G1-B where things stand. CI is green on your last commit.
