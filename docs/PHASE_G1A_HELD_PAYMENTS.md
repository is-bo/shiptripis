# G1-A: held payments and finality (rule G-D)

Brief `docs/handoff/builders/G1-A.md`, plan `docs/handoff/LOOP_END_PLAN.md` (rule G-D, decision
D2). Pull request #67, branch `claude/g1-guest-checkout-csrf`; G1-B and G1-C follow on the same
branch. Nothing deployed.

**The rule.** Every payment a provider reports is accounted for before the order collects again.
Three facts are kept apart: can this checkout still collect (finality), did the provider report a
payment (evidence), and what became of the money (disposition).

## Final design

**Finality.** `checkout_final_at` means the provider confirmed the checkout can take no further
payment. It is written by one function, `reconcile_attempt`, in the same UPDATE as a terminal
status, and the check constraint `fin_attempt_final_is_terminal` (migration `finance 0037`)
refuses a final attempt that is not `succeeded`, `failed`, `expired` or `cancelled`.
`close_checkout` answers how the provider says the checkout ended: `closed` (by this call),
`failed`, `expired`, `cancelled`, or `collected` (a payment is under way). Stripe and Chargily read
the checkout after a refused expiry and report the provider's own word. `settle_checkout` records
that word; `_record_checkout_final` and the gate's "final but open" branch are gone.

**Evidence.** A reported payment is verified only when the provider states an amount that is a
whole number of minor units equal to the attempt's, and the attempt's currency. One function,
`_unverified_reason`, says why not: `amount_unverifiable` (missing or fractional),
`amount_mismatch`, `currency_mismatch`. The test gateway no longer invents a currency the provider
did not state.

**Three predicates, once, in `finance/models.py`.** `LIVE_CHECKOUT` (can still collect),
`HELD_PAYMENT` (a failed attempt whose code is one of `HELD_PAYMENT_CODES`, with no disposition),
and `OUTSTANDING` (either). The gate, `settle_checkout`'s early return and
`_already_satisfied_reason` read `OUTSTANDING`; the finance queue reads `HELD_PAYMENT` or unapplied
money not yet refunded.

**The gate.** An order with a held payment opens and hands out no checkout: `PaymentUnderReview`,
stable code `payment_under_review` (409), for the owner and for a guest link alike. A hold sends no
payment-failed email and withdraws one queued earlier; the payment return page shows "Still
confirming… You don't need to pay again". The app has the code and its strings in English, French
and Arabic (`paymentUnderReviewTitle`, `paymentUnderReviewBody`); G1-C draws the state.

**How a hold ends, and no other way.**

| How | Who | Where |
|---|---|---|
| Applied | A verified report, on a hold staff never closed | `reconcile_attempt` |
| Unapplied and refunded | A verified report the order cannot absorb | `reconcile_attempt` |
| Released | The settle read: checkout final, no payment; never for `paid_after_disposition` | `_release_hold` |
| `no_debit` | Finance, with a reason | `resolve_payment_attention` |
| `returned` | Finance, with a reason and the provider's payment reference | `resolve_payment_attention` |

`settle_checkout`'s read has six answers: paid and verified, paid and not verified (both through
`reconcile_attempt`), final with no payment, open, processing, unreadable (`ProviderError`). For a
hold, open, processing and unreadable change nothing.

**Staff.** The console's payment page offers **Close held payment** for a hold: a form with the two
dispositions only (`PaymentDispositionForm`; "resolved", "dismissed" and "superseded" stay for
other items). It carries the failure code staff reviewed. One transaction locks the attempt,
refuses a payment that changed (`payment_changed`), checks the reference (`returned` needs one,
equal to the stored payment id when one is stored and belonging to no other attempt), writes the
disposition and the audit row `payment.hold_closed` (before: status, failure, unapplied,
disposition, payment id; after: disposition, payment id). No provider call. The reference is kept
in `provider_payment_id`; no column was added. The console is English-only, like the rest of it;
the lead decided this meets "Done when 3".

**Automatic paths obey staff (R5).** Under the attempt's row lock, which staff take too,
`reconcile_attempt` meets a closed item: the payment a `returned` disposition names changes nothing
(`payment_already_returned`); any other success holds it again as `paid_after_disposition`, clears
the disposition (the audit row keeps it), stores that payment's id and arms the settle job, once;
such a hold is never applied or released, and only `returned` ends it.

**No provider call inside a transaction (R1).** The test gateway raises when called inside any
transaction other than a test's own, so every test checks it.

## Rewritten tests

| Test | Why |
|---|---|
| `test_guest_payment`: `…amount_cannot_be_accepted_is_read_until_it_is_accounted_for`, `…any_path_finds_unaccounted_is_read_until_it_is` | The settle note for a hold is now `payment_held` (was `payment_unverified`). |
| `test_guest_payment`: `…staff_resolved_is_no_longer_read` | A hold now ends only as `no_debit` or `returned` with the failure code staff saw; it uses `returned` with a reference. |
| `test_chargily`: `…refused_expiry_is_answered_by_reading_the_checkout` | A checkout that ended before the call now answers the provider's word (`expired`, `failed`, `cancelled`), not `closed`. |
| `test_stripe`: `…refused_expiry_is_answered_by_reading_the_session` | Same, for an expired session. |

## Evidence

Red at `7ab8fa4` (CI run 433, shard 2: exactly these three failed); green from `47943cc`.

| Finding or rule | Test (`apps/finance/tests/test_held_payments.py`) |
|---|---|
| Round 7 blocker 1: a held payment did not stop a new checkout, and the payer was told nothing was charged | `RoundSevenFindingTests.test_a_held_payment_stops_every_new_checkout` (red: no refusal) |
| Round 7 blocker 3: staff closed a hold while the settle read was out; the read's success was applied | `…test_staff_closing_a_hold_while_its_settle_job_reads_is_obeyed` (red: `succeeded`) |
| Chargily should-fix: a close that found the payment failed left the attempt final and `processing` | `…test_a_close_that_finds_the_payment_failed_ends_the_attempt` (red: `processing`) |
| States × events (12 states; taps, six webhooks, six reads, three closes, expiry, two dispositions, order stops, paid by another attempt) | `AttemptTableTests`, 244 tests generated from `TABLE`: answer, next state, ledger, refund, finance queue, no failed email while held |
| Both orders: webhook and disposition, read and disposition (also mid-read), tap and webhook | `EitherOrderTests`, 11 tests |
| Late evidence: the same report twice, a `returned` reference that does not match | `LateEvidenceTests`, 5 tests; mid-read success after each disposition in `EitherOrderTests` |
| Final means terminal; one writer; predicates once; no provider call in a transaction | `MechanicalChecks`, 4 tests |
| Staff form: two dispositions, audit row, changed payment refused, reference required, held again ends only as returned | `HeldPaymentConsoleTests`, 5 tests |

Blocker 3's test calls the new disposition (`no_debit` with the failure code staff saw) where the
red version used `resolved`; the bad outcome it checks is the same.

## Left to the next briefs

- G1-B: the sweep (`arm_live_checkouts`) still reads `LIVE_CHECKOUT`, so a held attempt whose
  settle job ran out is armed again only by a new report until G1-B reads `OUTSTANDING` there.
- G1-C: `next_checkout` and `_hands_back` still restate parts of `LIVE_CHECKOUT` in Python; the
  owner's and guest's screens do not yet draw `payment_under_review`; screenshots of the "being
  checked" states and of the staff form.
