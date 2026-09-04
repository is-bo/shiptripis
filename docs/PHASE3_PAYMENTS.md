# Phase 3 — Payments, posting deposit, Stripe, Chargily, payouts

This is the engineering handoff for the V1 financial architecture. It documents
what exists, why it is shaped that way, and what an operator still has to do
before real money moves.

`docs/SHIPTRIP_V1_SPEC.md` remains authoritative. Where this document adds
detail the specification left open, the choice and its reasoning are stated.

---

## 1. The split that everything else follows

The legacy `apps.payments` schema binds one `PaymentIntent` to one accepted
`Offer` and carries DZD as if it were marketplace truth. It stays in the
database as history, keeps serving legacy rows, and is firewalled off V1 Deals.
Nothing in Phase 3 writes to it or reinterprets it.

The V1 model separates two things that schema conflated:

| | What it is | What it knows |
|---|---|---|
| `PaymentOrder` | The **business obligation**, always canonical EUR cents | What is owed, credited, captured, refunded |
| `PaymentAttempt` | One **provider attempt** against it | Which rail, what was charged, in what currency, at what rate |

An order may have many attempts over its life. Provider semantics never become
the canonical business truth, which is what lets Stripe (EUR), Chargily (DZD at
a snapshotted rate) and the test mock share one reconciliation path.

Everything else hangs off that split: `PaymentProviderEvent` (webhook
idempotency), `PaymentRefund`, `GuestPaymentLink`, `LedgerTransaction` /
`LedgerEntry`, `Payout`, `TravelerPayoutMethod` and `ScheduledJob`.

---

## 2. Money representation

Canonical money is **integer EUR cents**, everywhere, with no floating point in
any path. `apps/finance/money.py` is the only arithmetic:

* `percentage_of(amount, bps=…)` — basis points, rounded **half up**. A posting
  deposit is a prepayment of the sender's own balance, not a fee, so there is no
  reason to round against them; the clamp is what bounds it.
* `convert_eur_cents(amount, to_currency=…, rate_micros=…)` — rounded **up**.
  Rounding down would collect less than the EUR obligation requires.
* FX rates are stored as `rate_micros` = target major units per EUR × 1 000 000,
  so 150.25 DZD/EUR is `150_250_000` and is exact to six decimal places.

**DZD has exponent 0.** Chargily expresses DZD in whole dinars, which is also
how the currency circulates. Converting therefore loses precision; the residual
is a rounding difference absorbed deliberately, not a discrepancy to reconcile.

> One real bug was found here during implementation and is worth recording:
> `Decimal.__floordiv__` truncates toward zero, so the usual `-(-a // b)`
> ceiling trick silently rounds **down** on Decimals. The conversion uses plain
> Python integers, where floor division is exact.

---

## 3. State machines

### PaymentOrder

```
pending ──► partially_paid ──► paid
   │              │              │
   │              │              ├──► refund_pending ──► partially_refunded ──► refunded
   │              │              │
   └──────────────┴──────────────┴──► cancelled
```

Status is **derived, never assigned ad hoc**. `_recompute_order_money` sums the
order's own attempts and refunds and re-derives both the money columns and the
status. A replayed webhook therefore converges on the same numbers instead of
adding a second time, and a crash between two writes heals on the next event.

`outstanding_eur_cents = max(0, amount − credited − paid)` is a property, never
a column, so it cannot drift.

Database constraints, not application code, hold the invariants:

| Constraint | What it makes impossible |
|---|---|
| `fin_order_amount_positive` | A zero or negative obligation |
| `fin_order_no_overcollection` | `credited + paid > amount` |
| `fin_order_refund_within_capture` | `refunded > paid` |
| `fin_order_one_live_deposit_per_request` | Two live posting deposits on a request |
| `fin_order_one_live_balance_per_deal` | Two live balance obligations on a Deal |
| `fin_order_currency_eur` | A canonical amount in any other currency |

### PaymentAttempt

```
created ──► checkout_pending ──► processing ──► succeeded
                 │                    │
                 ├────────────────────┴──► failed | expired | cancelled
```

`processing` is a real state, not a placeholder: Stripe's delayed methods (SEPA
debit, bank transfer) complete the session before the money settles and follow
with `async_payment_succeeded` or `async_payment_failed`.

A success arriving after we locally expired or cancelled an attempt is still
applied — the money is real. Whether it can be *absorbed* is a separate
question; see §7.

At most one attempt per order may be open at a time
(`fin_attempt_one_open_per_order`). Switching rail cancels the previous attempt
through the service, so two live checkouts can never race to fund one
obligation.

### Payout

```
not_eligible ──► eligible ──► scheduled ──► processing ──► paid
                                                        └► failed
```

**Phase 3 contains no code path that leaves `not_eligible`.** That is the point.
`fin_payout_release_requires_eligibility` refuses any status past `eligible`
without an `eligible_at`, and only the Phase 4 release service sets it.
`fin_payout_paid_requires_evidence` refuses a `paid` row without either a
provider payout id or a named admin actor plus a reference.

---

## 4. Posting deposit

**Mode** is versioned policy: `payments.timing_mode` is `posting_deposit`
(the V1 default) or `after_acceptance`.

**Amount**: `clamp(percent_bps of the recommended sender total, min, max)`,
seeded as 10%, €3, €7.

At posting time no journey is chosen, so there is no matched sub-route to price
against. The estimate uses the request's own straight-line pickup→delivery
distance with no detour and no urgency premium. That is the conservative
reading: a real matched route is at least this long, so the deposit never
exceeds a tenth of what the sender will actually owe. The inputs are snapshotted
onto the order, so a later settings change cannot alter what was charged.

**Publication is the effect of a reconciled payment, never a client assertion.**
In deposit mode a new request is created `awaiting_deposit`. Every matchability
gate in the codebase already tests `status == OPEN`, so an unpaid request is
invisible to discovery, to `/api/parcels/open`, and to `create_sender_offer`.
When the deposit order reaches `paid`, `_publish_request_after_deposit` flips it
to `open` **and arms the expiry refund in the same transaction** — a request can
never become discoverable without its refund obligation also existing.

**Credit, not a second charge.** At acceptance the balance order is created with
`amount = sender_total` and any eligible deposit is credited into it:

```
sender total       €40.00
posting deposit    −€4.00   (already paid)
outstanding        €36.00   ← what the checkout charges
```

Eligibility is narrow: same owner, same delivery request, a *paid* deposit,
nothing refunded, and not already credited anywhere. `credit_source` is a
one-to-one link, so a second attempt to spend the same deposit fails on the
unique index rather than discounting twice.

**Every way it can end without a delivery returns the money**:

| Ending | What happens |
|---|---|
| Request expires unmatched | `deposit_expiry_refund` job refunds in full |
| Sender cancels before an accepted offer | Refunded in full, in the same transaction as the cancellation |
| Deposit unpaid when the request expires | Order cancelled, nothing to refund |
| Accepted deal never funded | Credit **released** back to the deposit, which then refunds on expiry or credits a later acceptance |

> That last row was a real defect found by the finance-state review and fixed:
> the credit link marked the deposit "already credited", so the expiry refund
> declined to return it and a later acceptance declined to re-use it. The money
> sat in `deal_funds` against an expired deal with no path out. `cancel_order`
> now posts a compensating ledger transaction and detaches the credit.
> Regression: `TrappedDepositRegressionTests`.

---

## 5. Providers

Availability is **server-authoritative**. A provider is offered only when the
versioned policy enables it, the deployment holds its credentials, those
credentials describe an environment the server can identify, and the rail is
accepting new checkouts. A button in the client is not a capability.

### The rail decides the settlement currency

**Stripe settles EUR. Chargily settles DZD. Neither is a payer's choice and
neither is a client's input.** `settlement_amounts()` takes its currency from
`gateway.payment_currency` and from nothing else; `CheckoutCreateSerializer`
refuses a request that so much as names `currency`, `payment_currency`,
`amount_eur_cents` or `fx_rate` with `client_supplied_amount_rejected`. Each
adapter also refuses the wrong currency at its own door
(`unsupported_currency`), so a Stripe-in-dinars charge has no path to exist at
any layer.

The client is therefore given the answer rather than the ingredients. Every
surface that can start a checkout serves a `providers` list in which each row
carries:

| Field | Meaning |
|---|---|
| `available` | The single gate a "pay with this" control may be enabled from |
| `payment_currency` / `settlement_currency` | What this rail settles in |
| `settlement_amount_minor` + `_exponent` | What this rail will actually charge |
| `canonical_amount_eur_cents` | The one EUR obligation it stands for |
| `eur_dzd_rate` + `rate_is_indicative` | Dinar rails only; today's rate, not a binding one |
| `unavailable_reason` | Machine code — never a sentence |

`rate_is_indicative` matters: the rate that binds is snapshotted onto the
`PaymentAttempt` when the checkout is created, and a later admin change does not
move an attempt that already exists.

A rail that cannot take *this particular* amount — a dinar total under
Chargily's floor — comes back `available: false` with
`amount_below_provider_minimum`, rather than being offered and failing at the
tap.

`credential_mode` stays out of the payer-facing contract and appears only in
`as_operator_dict()`, which the admin console and deep health read.

### Configuration that exists but must not be used

`ProviderNotConfigured` means the deployment has no credentials.
`ProviderConfigurationInvalid` (`provider_configuration_invalid`) means it has
credentials that describe an environment nobody can identify — and the two
deserve different answers, because the second is a rail somebody has already
switched on.

`configuration_problem()` reports it, `availability()` turns it into
`available: false`, and `resolve_gateway_for_checkout()` raises before any
provider call. `get_gateway()` deliberately does **not** enforce it: webhooks,
reconciliation and refunds for money that already exists have to keep working
while an operator repairs the setting, or refusing one bad checkout would strand
real payments.

### Stripe

Written against Stripe's documented HTTP contract, not an SDK — there is no
`stripe` package in this project's dependency set, and the REST API *is* the
contract. Form-encoded requests to `/v1`, an `Idempotency-Key` header on every
mutation, and manual `Stripe-Signature` verification exactly as Stripe documents
for integrations without an official library:

1. split the header on `,` then `=` to recover `t` and every `v1`
2. build `signed_payload = f"{t}.{raw_body}"`
3. HMAC-SHA256 with the endpoint's `whsec_` secret
4. constant-time compare, then reject a timestamp outside tolerance (default
   300s)

Only `v1` is honoured — `v0` is a test scheme and accepting it would be a
downgrade. Several `v1` values may be present while a secret is rolling, so any
one match suffices. Values that are not hex are discarded before comparison,
because `hmac.compare_digest` raises `TypeError` on a non-ASCII string and an
unauthenticated caller could otherwise turn one line of header into a 500 — and
a 5xx tells a real provider to retry forever.

### Chargily

Chargily is a **settlement rail, not marketplace truth**. The canonical
obligation stays EUR; the adapter is handed an already-converted DZD amount and
charges exactly that. It never converts and never reads the rate.

* base: `https://pay.chargily.net/api/v2` (live), `.../test/api/v2` (test) — the
  URL *and* the key decide the mode
* auth: `Authorization: Bearer <api secret key>`
* checkout: `POST /checkouts` with `amount` (whole dinars) + `currency: "dzd"`,
  `success_url` (required), `failure_url`, `webhook_endpoint`, `description`,
  `metadata`
* webhook: header `signature` = HMAC-SHA256 hex of the **raw body**, keyed with
  the API secret key; events `checkout.paid`, `checkout.failed`,
  `checkout.canceled`, `checkout.expired`

A `checkout.paid` whose object does not itself say `paid` is not trusted: the
object wins, not the label.

**Chargily Pay v2 exposes no refund endpoint.** The adapter raises
`RefundNotSupported` rather than fabricating a success, the refund stays
`pending`, and an operator settles it through
`POST /api/admin/payments/refunds/<id>/settle` with a mandatory reference. A
database constraint refuses a settled refund that carries no reference: money
leaving the platform with no actor and no reference is untraceable.

**Two Chargily switches exist and mean different things.**
`providers.chargily_enabled` removes it from the client's list.
`chargily.new_checkouts_enabled` stops *new* checkouts while webhooks,
reconciliation, refunds and history keep working — that is the switch an
operator reaches for during an incident.

**Chargily states its environment twice, and the two must agree.**

| Mode | Key prefix | `CHARGILY_API_BASE` |
|---|---|---|
| Test | `test_sk_` | `https://pay.chargily.net/test/api/v2` |
| Live | `live_sk_` | `https://pay.chargily.net/api/v2` |

Any other pairing — including an unrecognised prefix — is `unknown`, and
`unknown` is a stop condition, not a cautious "probably test". Phase 8F-C found
exactly this on the deployed environment: a `test_sk_` key presented to the live
base. Chargily answered `401`, and because the adapter raised the catch-all
`ProviderError`, the payer saw a generic "try again in a moment" for a
configuration fault no retry could fix.

Both halves of that are now closed. `configuration_problem()` refuses the
checkout before the request is made, and a `401`/`403` from either provider
raises `ProviderNotConfigured` rather than a transient error — with the HTTP
status, the derived mode and the API-base environment logged, and the key
logged nowhere.

### Mock

Test and local development only. It does **not** self-succeed: `create_checkout`
returns a pending session like a real rail, and a test must post a signed mock
webhook to move it. A provider that succeeds on creation is precisely the
footgun this phase removed.

Three independent guards keep it out of production:

1. `PAYMENTS_ALLOW_MOCK_PROVIDER` defaults to false, and the registry refuses to
   even construct the gateway without it — including when business policy asks
   for it.
2. `config.settings.prod` raises at boot if the flag is set, so a deployment
   that enables it never starts and cannot take a single payment.
3. There is no fallback path anywhere. A misconfigured Stripe raises
   `ProviderNotConfigured` and the checkout fails, which is the safe outcome.

---

## 6. Webhooks

The only unauthenticated write surfaces in the system, so:

* **The raw body is what gets verified.** `request.body` is read before DRF
  parses anything; re-serialising a parsed dict would change whitespace and key
  order and break every signature.
* **A bad signature is a 400 and nothing else.** No row is written, and the
  response says nothing about whether the referenced payment exists.
* **Idempotent by insert, recoverable by state.** `apply_provider_event`
  inserts `PaymentProviderEvent` first; a duplicate conflicts on
  `(provider, provider_event_id)`. Uniqueness stops a *second economic effect*
  — it no longer suppresses an effect that never happened. See 6a.
* **Order is never assumed.** An event is matched to its attempt by provider
  handle. A terminal attempt refuses to move backwards, and a late failure
  cannot unfund a paid order.
* **Availability does not gate events.** A provider disabled for new checkouts
  still has customers mid-flight; the webhook path resolves its gateway through
  `get_gateway`, which takes no policy at all.

A success must state what was charged. An amount or currency that does not match
what the server asked for fails the attempt (`amount_mismatch` /
`currency_mismatch`) and moves no money; a success reporting **no** amount is
refused as `amount_unverifiable` rather than applied on the strength of its
label.

### 6a. Provider-event processing lifecycle

Receipt and successful application are different facts, and they are stored as
different facts. `PaymentProviderEvent.processing_result` is a state machine:

| State | Meaning | What drives it forward |
|---|---|---|
| `received` | Committed, not yet applied | the inline apply, or the `provider_event_process` job created in the same transaction |
| `processing` | An apply is in flight | `requeue_stuck_jobs` after a worker death; re-entry is allowed and idempotent |
| `retryable` | An apply failed | `next_retry_at` plus the re-armed `provider_event_process` job, or a provider redelivery |
| `applied` | The economic effect committed | terminal |
| `ignored` | A no-op event with nothing to apply | terminal |
| `failed` | The provider reused an event id with a different payload | terminal; operator review |

The row carries what recovery needs: `processing_attempts`,
`processing_started_at`, `next_retry_at`, `last_error_code`,
`last_error_message`, `processed_at`, and `normalized_event` — the safe subset
of provider fields sufficient to replay reconciliation after a process crash.
`payload_fingerprint` detects a provider reusing an event id for different
content; that is refused rather than applied.

Two properties this shape buys:

* **A committed event can never permanently suppress its own unfinished
  financial effect.** The old model committed the idempotency gate ahead of the
  money, so a rollback in reconciliation turned every provider retry into a
  `duplicate_event` no-op, forever. Now only `applied` and `ignored`
  short-circuit.
* **A redelivery re-arms the durable job before it tries inline.** If the
  recovery job had already exhausted its retries and the process is *killed*
  mid-apply — so no `except` clause runs — the re-armed row is still there.
  Regression: `test_a_redelivered_event_re_arms_an_exhausted_recovery_job`,
  which raises a `BaseException` precisely because a SIGKILL cannot be caught.

---

## 7. Deal funding and late money

```
provider event → PaymentAttempt reconciliation → PaymentOrder reconciliation
               → apps.deals.services.fund_deal → Deal FUNDED
```

`fund_deal` is the only path into `Deal.Status.FUNDED`. Provider code never
reaches in and sets Deal fields. It is idempotent by row lock: a Deal already
past `payment_required` returns `changed=False`, so two duplicate success events
cannot fund twice. Leg allocations move `pending_payment → funded` in the same
transaction.

Funding refuses if the reservation is already gone — funding a Deal whose
capacity has been released would silently oversell a leg.

**Late-success handling is explicit.** Money that the obligation cannot absorb
(the order is already covered, or cancelled) is:

1. recorded as `succeeded` with `is_unapplied = True` — the money is real
2. written to the ledger as a customer payment — the books show it
3. automatically refunded — `PaymentRefund.Reason.UNAPPLIED_PAYMENT`
4. excluded from the order's `paid`/`refunded` totals, so `refunded <= paid`
   stays true and the constraint is never fighting the data

A payment landing after the payment grace lapsed therefore does **not** revive
the Deal. `release_pending_deal_reservation` cancels the balance order in the
same transaction that releases the capacity, which is what makes the later
success unabsorbable.

---

## 8. Ledger

Append-only double-entry. Every financial fact is one `LedgerTransaction` with a
balanced set of `LedgerEntry` rows; `post()` refuses an unbalanced set, and both
models reject `save()` on an existing row and reject `delete()` outright.
Corrections are new, linked, compensating transactions.

Sign convention: positive increases an asset, negative increases a liability or
recognises revenue. Every transaction sums to exactly zero, which makes "money
appeared from nowhere" a detectable condition rather than a hope.

| Account | Meaning |
|---|---|
| `provider_clearing` | Money held at the PSP (asset) |
| `sender_deposit` | Posting deposit held for a sender (liability) |
| `deal_funds` | Deal funds held pending delivery (liability) |
| `traveler_payable` | Owed to a traveler (liability) |
| `platform_commission` | Recognised commission (revenue) |

The six facts recorded: customer payment, posting-deposit credit, deal funding
(splitting held funds into traveler payable + commission), refund, payout,
correction.

`key` is the idempotency handle — a replayed webhook, a re-run job or a
double-submitted admin action resolves to the same key and is refused by the
unique index. `post()` reports that as "already recorded", not as an error.

The legacy `apps.wallet` ledger is untouched and still serves legacy
`PaymentIntent` rows. It is not reused for V1: its hold/release semantics move
money between two user wallets, which does not describe a platform holding funds
against an obligation.

---

## 9. Guest payer

A `GuestPaymentLink` is a single-purpose, expiring capability to pay one order.
Holding it lets someone pay. It grants **no** Deal ownership, no chat, no dispute
authority, and no sight of the recipient, the addresses or the counterparty.

* token: `secrets.token_urlsafe(32)`; only the SHA-256 digest is stored, and the
  plaintext is returned exactly once, to the order owner
* one live link per order — issuing a new one revokes the previous
* single use: consumed when the payment succeeds
* every rejection — unknown, expired, revoked, consumed, or attached to a closed
  order — is the same uniform 404, so a prober learns nothing
* the guest payload is amount, currency, a generic description, an expiry and
  the available rails. Nothing else, and no identifiers at all
* the surface is throttled against token guessing

---

## 10. Payouts

Provider-agnostic. The traveler's obligation is canonical EUR; how it is settled
is a separate question.

**No country implies a capability.** An automatic Stripe transfer requires all
of: the policy allowing it, a Stripe-connected payout method on file, and Stripe
itself reporting `payouts_enabled` and an active `transfers` capability.
Anything else falls back to the manual queue — including a Chargily-funded Deal,
because a Chargily customer payment does not imply a Chargily payout rail.

An unreachable Stripe yields `available=False`, so the manual queue is the safe
default rather than the error case.

Manual settlement records the EUR obligation, the actual currency and amount,
the FX rate used, the method, the reference, the receipt, the admin actor and
the timestamp. It is refused unless Phase 4 has released the payout — which
Phase 3 cannot do.

---

## 11. Durable scheduled work

`ScheduledJob` is the obligation store. Redis may make delivery prompt; nothing
in `apps/finance/jobs.py` reads Redis, and a job that exists in this table runs
even if every cache and queue is wiped.

| Kind | What it does |
|---|---|
| `deposit_expiry_refund` | Refunds a deposit when the request expired unmatched |
| `payment_grace_release` | Per-deal companion to the reservation sweep |
| `attempt_expiry` | Closes a hosted checkout the customer never completed |
| `provider_reconcile` | Polls the provider for a webhook that never arrived |
| `provider_event_process` | Re-drives a received provider event until its economic effect commits |
| `refund_reconcile` | Drives or polls a non-terminal refund using its stable provider idempotency key |
| `payout_release_check` | Phase 3 stub for the Phase 4 release gate — reports the payout as still gated and advances nothing |

**Every non-terminal state has a named consumer.** `PaymentAttempt.processing`
is an open status, so `attempt_expiry` and `provider_reconcile` both drive it.
`PaymentProviderEvent.received/processing/retryable` are driven by
`provider_event_process`. `PaymentRefund.pending/processing` are driven by
`refund_reconcile`. Nothing here is informational-only.

**Exhaustion escalates rather than disappearing.** A job that burns its retry
budget logs `finance.job_exhausted` at error level and stays visible in the
admin with a `requeue` action. A refund that has failed
`REFUND_MANUAL_ESCALATION_ATTEMPTS` times additionally sets
`requires_manual_action`, which puts it in the operator refund queue — the
automatic retries continue, but the obligation stops depending on them.

Claiming uses `SELECT ... FOR UPDATE SKIP LOCKED` where the database supports
it, so several workers share the queue without running the same job twice; on
SQLite it degrades to a plain locked read, which is correct with one writer.
Failures retry with exponential backoff capped at six hours and never kill the
loop. A worker that dies mid-run has its job returned by `requeue_stuck_jobs`.

Run it with `manage.py run_finance_worker` (long-running, alongside the existing
reservation releaser) or `manage.py run_finance_jobs` (one-shot, cron-safe).
Overlapping runs are harmless — every handler is idempotent in its own right.

---

## 12. Global lock order

There is **one** acquisition order for the whole system, not a finance-local
one. It is declared in `apps/core/financial_locks.py`, and every cross-domain
financial transition goes through the helpers there:

```
DeliveryRequest / ParcelRequest
  -> Match                (ascending id)
  -> Offer                (ascending id)
  -> Journey
  -> JourneyLeg           (position, id)
  -> KYC / proof / User eligibility witnesses   (acceptance only)
  -> Deal
  -> DealLegAllocation    (journey leg, id)
  -> PaymentOrder         (ascending id)
  -> PaymentAttempt       (ascending id)
  -> PaymentProviderEvent
  -> PaymentRefund        (ascending id)
  -> Payout
  -> append-only ledger rows
  -> ScheduledJob
```

Only the rows a transition actually needs are locked, but any it does need are
taken in this order. Two rows of the same type are always taken in ascending
`id`. Provider-event and ScheduledJob claims are deliberately short
transactions that commit *before* acquiring any business or finance row, so
they are never a reverse edge into this graph.

Three entry points implement it:

| Helper | Locks |
|---|---|
| `lock_request_graph(request_id, include_negotiation=)` | request, then its matches and offers |
| `lock_deal_aggregate(deal_id)` | the request graph, then journey, legs, deal, allocations |
| `lock_payment_order_aggregate(order_id)` | the deal aggregate (or request graph), then the order |

**The two cycles the Phase 3 review reproduced are gone.**

* `PaymentOrder <-> Deal`: `reconcile_attempt` used to lock the order and then
  the deal, while `release_pending_deal_reservation` locked the deal and then
  the order. On PostgreSQL that deadlocked, the webhook rolled back, and a
  charged customer was left with no succeeded attempt, no ledger entry and no
  refund. `reconcile_attempt` now takes the *complete* domain aggregate first
  through `lock_payment_order_aggregate`, so both directions start at the
  request.
* `PaymentOrder <-> ParcelRequest`: the same inversion between
  `_publish_request_after_deposit` and request cancellation / deposit-expiry
  refund. Cancellation is now a transactional domain service,
  `apps/parcels/services.py::cancel_delivery_request`, which locks the request
  graph before its orders and decides the refund from locked state rather than
  an unlocked read of `paid_eur_cents`. `handle_deposit_expiry_refund` does the
  same.

A nested caller re-locking a row the outer transaction already holds is
harmless. Acquiring an *earlier* row after a later one is what is forbidden.

> The finance-local ordering (`PaymentOrder -> PaymentAttempt ->
> PaymentRefund`) still holds and still stops a refund deadlocking a
> reconciliation on the same attempt. It is now the tail of the global order
> rather than the whole of it. It was found by an actual PostgreSQL deadlock in
> `RefundRaceTests::test_two_simultaneous_full_refunds_return_the_money_once`,
> not by inspection.

### Provider I/O never runs under a financial lock

Every remote call uses the same durable-intent shape:

1. a short transaction validates and records the intent, then **commits**
2. the provider call runs with `connection.in_atomic_block == False`, carrying
   a stable idempotency key derived from the committed row
3. a second short transaction reconciles the result

`start_checkout`, `recover_checkout_attempt`, `_settle_refund_with_provider`
and `handle_provider_reconcile` all follow it. `request_refund` schedules the
provider call through `transaction.on_commit`, so a refund raised *inside*
payment reconciliation or request cancellation cannot make an HTTP call while
those domain locks are held — with the `refund_reconcile` job as the crash-safe
fallback if the process exits before the callback runs. Regressions:
`test_provider_refund_call_runs_after_financial_locks_commit`,
`test_checkout_provider_call_runs_without_database_transaction`.

If the remote call succeeds and the process dies before step 3, recovery
re-issues the *same* idempotency key, so the provider returns the original
refund or checkout instead of making a second one.
`test_remote_refund_success_then_local_failure_reuses_provider_refund` asserts
one external refund from two calls.

### External money outlives business cancellation

Business-object lifecycle and external-money reconciliation are deliberately
separate. `cancel_order` closes the collection window and cancels only
`attempt_expiry` jobs — it does **not** cancel `provider_reconcile`,
`provider_event_process` or `refund_reconcile`, because those are the only
mechanisms that could recover money the webhook lost. A provider that settles
after the Deal expired, the request was cancelled or the payment grace lapsed
therefore still lands: the payment is recorded truthfully, flagged
`is_unapplied`, written to the ledger, given a refund obligation, and
explicitly does **not** revive the Deal or restore released capacity.

Chargily has no refund API, so an unapplied Chargily capture becomes a durable
**manual** obligation: `requires_manual_action`, a live `refund_reconcile` job,
visible in the admin refund queue, and dischargeable only through
`settle_refund_manually`, which requires an admin actor and a settlement
reference and is idempotent against double settlement.

### Cancellation racing payment

Both orderings are tested, and money is conserved either way:

* **payment wins** — the deposit is applied, then cancellation raises a refund
  for it (`test_payment_then_request_cancellation_refunds_applied_money`)
* **cancellation wins** — the late success is recorded `is_unapplied` and
  refunded, and the request stays cancelled
  (`test_request_cancellation_then_payment_refunds_unapplied_money`)

plus threaded stress over both orderings on PostgreSQL: 8 parcel rounds and 12
deal rounds, each asserting a single coherent terminal state.

### Financial conservation is asserted against the provider, not the database

`apps/finance/tests/assertions.py` checks, after every race:

```
provider-known successful funds == locally accounted successful funds
accounted                       == applied + unapplied
order.paid_eur_cents            == applied
every invalid capture has a refund obligation for its full amount
every succeeded attempt has a customer-payment ledger fact
every ledger transaction nets to zero
```

The external figure comes from `MockGateway`'s own module-level dictionaries,
captured *before* the race and keyed by provider session id. Those dictionaries
are not Django state, so a rolled-back application transaction cannot shrink
them — which is the whole point: a payment that vanished locally shows up as a
mismatch instead of quietly agreeing with itself.

---

## 13. API surface

| Method | Path | Who |
|---|---|---|
| GET | `/api/payments/providers` | authenticated |
| GET | `/api/payments/orders` | owner |
| GET | `/api/payments/orders/<uuid>` | owner or staff |
| POST | `/api/payments/orders/<uuid>/checkout` | owner |
| POST | `/api/payments/orders/<uuid>/guest-link` | owner |
| POST | `/api/payments/orders/<uuid>/guest-link/revoke` | owner |
| GET | `/api/parcels/<id>/posting-deposit` | sender or staff |
| POST | `/api/parcels/<id>/posting-deposit` | sender |
| GET | `/api/deals/<id>/payment` | deal parties (traveler sees status only) |
| GET | `/api/payouts` | traveler |
| POST | `/api/admin/payouts/<id>/complete` | staff |
| POST | `/api/admin/payments/orders/<uuid>/refund` | staff |
| POST | `/api/admin/payments/refunds/<id>/settle` | staff |
| GET | `/api/payments/guest/<token>` | capability only |
| POST | `/api/payments/guest/<token>/checkout` | capability only |
| POST | `/api/payments/webhooks/{stripe,chargily,mock}` | signature only |

Orders are addressed by `public_reference` (a random UUID), never by primary
key, so they cannot be enumerated.

**Flutter calculates nothing.** Deposit, outstanding balance, FX, commission,
sender total, refund amount and payout eligibility all arrive pre-computed. The
checkout serializer *rejects* a client-supplied amount, currency or rate with a
400 rather than ignoring it, so a tampering client gets a clear answer instead of
believing it set the price.

---

## 14. Migration behaviour

* `core.0005_seed_phase3_payment_settings` adds business settings **version 3** —
  version 2 plus a `payments` object — and activates it. Version 2 is untouched
  and retired; every Offer or Deal already pointing at it keeps the economics it
  agreed to. Rollback re-activates version 2 rather than deleting version 3,
  because orders reference revisions through `PROTECT`.
* `parcels.0007` adds the `awaiting_deposit` status choice. No data is rewritten.
* `finance.0001` / `finance.0002` create the new tables. Nothing migrates out of
  `apps.payments`: no legacy DZD payment is reinterpreted as EUR, and no
  historical value is invented.
* Forward and reverse were rehearsed on PostgreSQL 16 (`finance → zero`,
  `core → 0004`, `parcels → 0006`, then forward again), all clean.

**Payment policy comes from the active revision, not the offer's.** The offer
freezes the agreed economics — reward, commission rate, fee, sender total — and
those are what the order charges. Which rails exist, how the deposit is priced
and what the FX rate is are properties of the moment the payment happens. Reading
payment policy off the offer's own revision would break every offer negotiated
before Phase 3 shipped; there is a regression test for exactly that
(`LegacyRevisionCompatibilityTests`).

---

## 15. Still required before real money moves

| Item | Status |
|---|---|
| Stripe account, secret key, webhook endpoint + signing secret | **not configured** |
| Stripe payout/transfer capability approval | **not verified** |
| Chargily merchant account and API secret key | **not configured** |
| A real `chargily.eur_dzd_rate_micros` | seeded value is a **placeholder** |
| `PAYMENTS_PUBLIC_BASE_URL` on the deployment | **not set** |
| `run_finance_worker` added to the process topology | **not deployed** |
| Legal review of payment wording before launch | outstanding |

Until Stripe and Chargily are configured, `/api/payments/providers` reports both
as unavailable with `provider_not_configured` and every checkout on them is
refused. That is the intended failure mode: no rail silently substitutes for
another, and the mock cannot stand in.

---

## 16. Not implemented (Phase 4)

Deliberately absent: pickup code, delivery code, the 30-minute reveal, recipient
code email, delivery confirmation, the 48-hour protection behaviour, disputes and
evidence, partial dispute splits, cancellation compensation beyond deposit
consistency, no-show resolution, ratings, paid boost purchasing, the Flutter
redesign, the admin frontend, the landing site.

The payout *architecture* exists. Payout *release* does not, and the database
constraint makes that structural rather than a convention.
