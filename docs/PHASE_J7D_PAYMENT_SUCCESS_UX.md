# Phase J7D — Payment success, return and completion UX

Status: implemented, TEST only. Stripe TEST, Chargily TEST,
`PAYOUT_DZD_EXECUTION_ENABLED` false, no LIVE provider activation and no
real-money operation. **APK: NOT BUILT** — deferred to the final combined J7
acceptance build (J7A + J7B + J7C + J7D).

Starting point: `667ddcb` (J7C recorded). Branch `claude/j7d-payment-success-ux`.
Backend, public web **and** mobile change. No migration, no schema change. No
payment accounting, ledger, verification, idempotency, deposit, Boost, refund or
provider-routing code changed.

Owner feedback: the payment-success pages looked generic and disconnected from
ShipTrip; J7C left the provider-return page on the old design and the in-app
payer on "The payment is confirmed" wording.

---

## 1. Surface inventory (before J7D)

| Surface | Where | Component before | After |
|---|---|---|---|
| Request deposit success | `DepositScreen` settled | `PaymentSuccessView` (generic receipt, CTA *Find travelers*) | shared `PaymentResultView`, *View request* |
| Full payment at posting | same screen, deposit ≥ obligation | same generic receipt, no distinction | *Paid in full* stamp + "only the difference" note |
| Deal balance success | `DealPaymentScreen` settled | `PaymentSuccessView` titled "Paid", CTA *Done* (pop) | shared view, ledger, *View delivery* |
| Final / paid in full | same | "Remaining balance due" row hidden, nothing positive shown | *Paid in full* stamp, *Payment protected* |
| Partial Deal payment | checkout poll | kept "confirming" until the 2-minute budget ran out | *Payment received* + Remaining + *Pay remaining €Y* |
| Boost payment | — | **not reachable**: no V1 code creates a `boost` order (Boost is part of the Deal balance, J2) | purpose mapped ("Boost payment") for completeness only |
| Guest-paid Sender | Deal / deposit result, J7C sheet | "Paid by: Someone else" row / "€X was paid successfully" | "Someone else paid €X for this payment." |
| In-app provider return | `CheckoutSection` | small `InfoNotice` blocks under a still-visible "Remaining to pay" hero | full-page checking / still checking / failed / cancelled / partial results |
| Stripe / Chargily return | `/pay/<ref>/return` | static trilingual `TemplateView`, same words for every outcome | server-state view on the J7C shell |
| Public guest payer return | same page | same | *Payment complete* + purpose + "You can close this page." |
| Guest link reopened after paying | `/pay/guest/<token>` | uniform "no longer works" | *This payment has already been completed* |
| In-app anonymous payer after hand-off | `GuestPayScreen` | "Confirming…" + "The payment is confirmed." | *Finish on the payment page* (no claim) |
| Failed / cancelled / pending | checkout + return page | one "didn't go through" block; cancel indistinguishable | separate failed, cancelled, not-completed, checking, still-checking |

Shared before: only `CheckoutSection` (deposit + Deal) and `PaymentSuccessView`
(deposit + Deal). Separate: the J7C sheet's paid state, the public pages,
`GuestPayScreen`. **After: every surface above draws from one component
(`features/common/payment_result.dart`) or one web shell
(`templates/payments/_shell.html`).** `PaymentSuccessView` is deleted.

## 2. One visual system

Mobile `PaymentResultView` and the web result card share one layout:

```
            (wax seal + check icon)        ← mark: seal / checking ring / failed / cancelled
   REMAINING DELIVERY PAYMENT              ← purpose, terracotta eyebrow
        Payment received                   ← one heading, Fraunces
            €30.00                         ← the payment just made, Fraunces hero
         Jijel → Paris                     ← only from the request's own route
  ┌───────────────────────────────┐
  │ ✓ Payment protected            │      ← the outcome, in words
  │ Delivery total        €42.00   │      ← read like a receipt
  │ Deposit already paid  −€12.00  │
  │ Paid now              €30.00   │
  │ [PAID IN FULL]                 │      ← a stamp, never "Remaining €0.00"
  └───────────────────────────────┘
  WHAT HAPPENS NEXT
  Funds are held pending delivery. Follow the delivery steps to continue.
  [ → View delivery ]                     ← ink pill, where the server's state points
```

Parchment, ink `#0E1F2C`, terracotta eyebrow and seal, Fraunces heading and
amount, DM Sans body, Noto Sans Arabic in Arabic, the sunken inset panel, a
dashed `StampChip`. No gradient, no green success circle, no confetti, no bank
blue. The checking state has **no seal and no tick** — a quiet sunken disc with a
thin terracotta ring (static under reduced motion). Failed is a soft danger disc;
cancelled a neutral one. The J7C sheet's paid state now uses the same mark.

## 3. Purpose-specific content (`settledPaymentResult`)

All figures are server fields: `last_payment_eur_cents` (new), `amount`,
`deposit_credit`, `remaining`, `status`. No subtraction anywhere.

| Case | Heading | Hero | Outcome / ledger | Next | Primary / secondary |
|---|---|---|---|---|---|
| Deposit, request open | Payment received | deposit paid | *Your request is now published*; "This deposit counts toward your delivery total when a traveler accepts." | Find a traveler going your way and send them an offer. | View request / Back to Home |
| Deposit ≥ current obligation | same | same | + *Paid in full*; "This covers your delivery total as it stands. If you later add a Boost or raise the reward, only the difference would be due." | same | same |
| Deal paid, deposit credited | Payment received | paid now | *Payment protected*; total, −deposit, paid now; *Paid in full* | Funds are held pending delivery. Follow the delivery steps to continue. | View delivery |
| Deal paid in one payment | same | amount | *Payment protected*; *Paid in full* (no lines) | same | View delivery |
| Partial | Payment received | paid now | total, paid now, **Remaining**; "Pay the remaining €Y to confirm the delivery. The traveler can't collect the parcel until it's paid." | — | Pay remaining €Y / View delivery |
| Someone else paid | Payment received | that payment | lead: "Someone else paid €X for this payment." | as purpose | as purpose |
| Opened after it settled | This payment is already complete | as above | as above | as above | as above |

"Published" is the request's own status (`open`), not inferred from the payment.
"Paid in full" is the order's `paid` status (the server's statement that nothing
remains). "Escrow" appears nowhere; the product words are *Payment protected* and
*Funds held pending delivery*.

**Purpose names** reuse J7C's strings: *Deposit for your request*, *Delivery
payment*, *Remaining delivery payment* (credited deposit or more than one
payment), *Boost payment*. No enum reaches the screen.

**Route** is the request's two canonical places via J7B's `request_labels`
(`requestHasRoute`), drawn with the shared `InlineRoute`; absent when the request
has no recorded route. Never assembled from other data.

## 4. Navigation

* *View request* / *View delivery* use `leavePaymentForRequest` /
  `leavePaymentForDeal` (router): if the screen underneath **is** that request or
  delivery, pop back to it; otherwise replace the payment screen. Back never
  returns to a settled or payable payment screen, nothing is stacked twice, and
  the app is never reset to Home (only the explicit *Back to Home* does `go`).
* The Deal CTA uses the order's own `deal_id`; a deposit never offers a delivery.
* Re-opening a settled payment shows *already complete*, never a Pay button.

## 5. In-app return from the provider

There are no app deep links (the manifest has none); every hosted checkout ends
in the browser on `/pay/<ref>/return`, and the app learns the outcome on resume
or from the live event.

`CheckoutSection` now reports its phase (`choosing`, `confirming`, `settled`,
`partial`, `failed`, `cancelled`) and the screen hands the whole page to the
result — the stale "Remaining to pay" hero steps aside.

* **Checking your payment** — "If you finished paying, it will show here in a
  moment. You don't need to pay again." + *Back to payment* (which offers the
  same open session, "Continue your payment", never a second one).
* **We're still confirming your payment** after the backup schedule, + *Check
  again*.
* **Payment didn't go through** (attempt `failed`) — "Nothing was charged…" +
  *Try again* (only while the order is collectable) / exit action.
* **Payment cancelled** (attempt `cancelled`/`expired`) — "No completed payment
  was recorded." + *Try again*.
* **Partial** — see §3.

**Realtime and polling.** The screens already re-read on the `payment.*` event
(`LiveResource.payment` / `deposit`); that is the primary path. The checkout's
backup re-reads changed from every 3 s for 2 min (40 reads) to a counted
back-off `3, 3, 5, 5, 10, 10, 20, 20, 20` s (9 reads), then stop; returning to
the app re-reads once immediately. Nothing polls after the schedule. J7C's sheet
fallback is unchanged.

**Bugs found and fixed while testing this flow:**

1. Hiding the summary shifted the checkout's index in the list, so Flutter
   rebuilt it and it forgot the payment in flight (back to a Pay form while the
   payer was on Stripe). The slot is now stable and the section keyed.
2. *Back to payment* re-adopted the parent's stale order and forgot the open
   session it had just read back, offering a fresh checkout — a double-payment
   path. The section now adopts the parent's order only when the parent really
   re-read it.
3. Two taps inside one frame opened two checkouts (the button disables only on
   the next rebuild). `_checkout` / `_resume` now refuse re-entry.

## 6. Public pages (`/pay/<ref>/return`, `/pay/guest/<token>`)

`templates/payments/_shell.html` is the J7C page shell (tokens, faces, wax-seal
header, EN · FR · العربية switch, `no-referrer`, `noindex`, no script) shared by
the guest page and the new return page.

`apps/finance/payment_return_web.py` resolves the order by its reference and
says what the **server** says — `?result=` never decides the outcome:

| Server state | Page |
|---|---|
| order `paid`, newest attempt succeeded, success door | **Payment complete** · amount · purpose · guest: "You can close this page." / app payer: "…go back to the ShipTrip app. It updates by itself." |
| order `paid` otherwise | **This payment has already been completed** (+ "being refunded in full" when the returning payment was unapplied and refunded) |
| attempt in flight, success door (or none) | **We're confirming your payment**, bounded meta-refresh `3, 3, 5, 5, 10, 20` s, then **Still confirming** + *Check again* (one read, no restart) |
| attempt `failed` | **Payment wasn't completed** · "nothing was charged" |
| attempt `cancelled`/`expired`; Stripe failure door in flight | **Payment cancelled** · "No completed payment was recorded." |
| other rail's failure door in flight | **Payment wasn't completed** · "No completed payment was recorded." (no claim either way) |
| order closed, or unknown reference | **This link is no longer active** (404) |

Non-success amounts carry a visible label (*Amount still due*, *Amount being
confirmed*). A guest is never told to open an app; a retry tells them to use the
link they were sent. **Receipt line** only when `TRANSACTIONAL_EMAIL_ENABLED`,
the payer gave an address and the outbox holds a live receipt for this payment
(*on its way* when pending, *has been sent* when dispatched). TEST has email
off, so TEST never shows it.

Language: `?lang=` → browser → the guest link's language (guest) or the owner's
(app payer) → English. The switch keeps `result` and drops the re-check counter.

**Guest link reopened after paying** now reads *This payment has already been
completed / Nothing more is needed.* (200). Only a token that hashes to a stored
link reaches it, so it discloses nothing to a prober; unknown, expired, revoked
and closed links keep one uniform *This link is no longer active* page.

**Privacy.** The return page shows an amount, a generic purpose and an outcome —
the facts the guest page already shows its token holder. No party, email,
address, route, parcel, deal, request or order id. The reference is a random
UUID held by the payer's own browser; the page is throttled like the guest page.
This deliberately replaces the J3 "disclose nothing, say nothing" page, which
could not tell a payer whether they had paid.

## 7. Backend contract (additive, read-only)

* `settlement.last_payment_eur_cents`, `settlement.last_paid_by`
  (`self`/`guest`/null) — the newest applied payment on its own. Same privacy
  rule as `paid_by`.
* `GET /api/parcels/<id>/posting-deposit` now includes `order.settlement`, the
  block the Deal endpoint already served.
* `/pay/<uuid>/return` is a view (was a `TemplateView`); `/pay/guest/<token>`
  gains the already-completed branch.

## 8. Copy

EN / FR / AR reviewed side by side. Headings: *Payment received / Paiement reçu /
تمّ استلام الدفع*, *Payment complete / Paiement effectué / تمّ الدفع*, *Checking your
payment / Vérification de votre paiement / نتحقّق من دفعك*, *Payment cancelled /
Paiement annulé / أُلغي الدفع*, *Paid in full / Payé intégralement / مدفوع بالكامل*.
One heading per screen; no "successfully", "confirmed", "webhook",
"settlement", "escrow" or "séquestre" (asserted). The J3 key
`guestPayThanksBody` ("The payment is confirmed") and 21 other dead
payment-result keys were removed; `l10n_untranslated.json` is empty.

**Arabic figures.** A rendered screen showed the hero as "€ 30,00": the Arabic
currency pattern opens with an RLM and the trailing euro sign takes the page's
direction. The hero now renders left-to-right, and figures inside Arabic
sentences are wrapped in an LTR isolate (RLM dropped). A test measures the glyph
boxes — € right of the digits with the isolate, left without it — because the
image of a mixed line is easy to misread (it was, once, during this phase).

## 9. Tests

**Backend** — `apps/finance/tests/test_j7d_payment_results.py` (25): settlement
names the last payment (self/guest, no email); both endpoints serve it; forged
`success` never completes; backing-off re-check then stop; webhook moves pending
to complete; app vs guest copy; receipt only when really queued/dispatched (not
on failure, not with email off); failure door after payment = already complete;
declined vs cancelled vs not-completed; guest retry wording; closed/unknown =
no longer active; privacy; FR/AR/`Accept-Language`/link language; shared shell;
guest link paid / Sender-paid / revoked / unknown / closed. Updated: 8FC return
tests (new contract), J2/J7C dead-link wording.

**Mobile** — `test/phase_j7d_payment_result_test.dart` (49): content for every
purpose; deposit screen settle-while-watching, already-complete, paid-in-full,
no-route; Deal screen paid-in-full with credit, guest-paid, already-complete;
the real checkout hand-off (url_launcher channel stubbed): checking with no
seal and no stale form, live event → result, backup schedule = 9 reads then none
for 10 min, resume reads once, cancelled ≠ failed, failed, back-to-payment
resumes the same session, partial; double tap = one checkout; navigation pop vs
replace, Home, Deal → delivery; every result at 320×640, 390×844, 411×869,
844×390 and 1.6× in EN/FR/AR without overflow and with ≥ 48 dp targets; banned
words in three languages; Arabic RTL route and LTR figures (measured);
live-region heading, amount read with purpose, decorative mark excluded,
reduced-motion ring. Updated: J3, J6 and 8F-F4 tests for the new component.

## 10. Visual QA

Real screens (not isolated widgets) rendered with a throwaway golden rig (app
fonts + icon font, not committed) at 390×844 EN: deposit received, deposit paid
in full, partial Deal, Deal paid in full, guest-paid Sender, checking, still
checking, failed, cancelled; FR at 1.6× (deposit, Deal, partial); AR (deposit,
Deal, guest-paid, checking, failed); 320×640 (EN Deal, FR deposit); 844×390;
411×869. Public pages rendered through the real views and inspected in a browser
at 390 and 320, light and dark, EN/FR/AR (success guest/app, pending, still
confirming, failed, cancelled, already completed, guest link completed, no
longer active): no horizontal scroll. Defects found only by looking: the Arabic
hero figure order, the ledger reading as a sum rather than a receipt, the
deposit note's unanchored "It's", a heavy outline button on the checking state,
a still-spinning ring after checks stopped, and unlabelled amounts on non-success
web pages — all fixed.

## 11. Remaining findings

* **MINOR** — app-wide, pre-existing: Arabic sentences and buttons elsewhere that
  embed a formatted amount (e.g. *Pay 35,00 € with Stripe*) put the euro sign in
  front of the number for the same RLM reason. J7D fixed it on result surfaces
  only; `paymentResultFigure` is the reusable fix.
* **MINOR** — `GuestPayScreen` (in-app anonymous payer) still cannot learn the
  outcome (no anonymous status endpoint); it now claims nothing. No deep link
  reaches it today.
* **MINOR** — `InlineRoute`'s semantics label joins stops with a hard-coded
  English " to " (pre-existing, J1).
* **Note** — Boost has no separate payment obligation in V1; a Boost result is
  therefore not reachable and was not designed beyond purpose naming.
