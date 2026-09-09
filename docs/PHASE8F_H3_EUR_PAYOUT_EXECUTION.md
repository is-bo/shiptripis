# Phase 8F-H3 — automatic EUR payout execution, recovery and reconciliation

H3 builds the rail that actually pays a Traveler. It sits on the dormant domain
[H1](PHASE8F_H1_PAYOUT_FOUNDATIONS.md) created, the onboarding and readiness
layer [H2](PHASE8F_H2_STRIPE_CONNECT_ONBOARDING.md) built and
[H2.5](PHASE8F_H25_TEST_ACTIVATION_VERIFICATION.md) verified in TEST, and the
architecture [H0](PHASE8F_H0_PAYOUT_FINANCE_ARCHITECTURE.md) fixed. Starting
local `main` and `origin/main` were `b3a71307da9644f3d0a6205b7a6e8682b3385175`,
release `v1.0.0-rc.16+b3a7130`.

**There is no admin “Pay” button on this rail, and adding one would be a
regression.** A Traveler is paid because a delivery was confirmed, a protection
window closed, every hold was clear and a worker did the arithmetic — or they
are not paid, and the reason is a machine code an operator can read.

## The shape of the problem

Paying a Traveler through Stripe is not one operation. It is two, days apart:

1. a **platform Transfer** moves ShipTrip's EUR out of its own Stripe balance
   and into the Traveler's connected account;
2. a **connected-account bank Payout** moves that balance to their IBAN.

Between them the money is gone from ShipTrip and has not arrived anywhere the
Traveler can reach. Almost every rule in this phase follows from taking that
window seriously: a Transfer is never a payment, a failed bank payout is never a
reason to Transfer again, and a settlement can no longer treat committed money
as platform cash.

The second problem is worse and quieter. After a timeout, a crashed worker
cannot tell whether Stripe received the request. H3's answer is to make that
distinction structural rather than inferential — see *The three transactions*.

## Provider contract re-verified

Verified on 9 September 2026 against Stripe's currently served documentation,
before any execution code was written. H0's selections stand; nothing needed a
redesign, and two details were confirmed precisely enough to be worth recording.

| H0 decision | Current contract | Result |
|---|---|---|
| `POST /v1/transfers` with `amount`, `currency`, `destination`, `source_transaction`, `transfer_group`, `metadata` | All present; `source_transaction` is documented as **the charge ID** | Confirmed |
| Never a PaymentIntent as `source_transaction` | “tie it to an existing charge by specifying the charge ID as the `source_transaction` parameter”; the docs give `latest_charge` and the charge list as the two ways to resolve one | Confirmed |
| Transfer against an unsettled charge does not fail on balance | “the transfer request returns success regardless of your available balance if the related charge hasn't settled yet. However, the funds don't become available in the destination account until the funds from the associated charge are available” | Confirmed — and this is exactly why the bank stage defers rather than fails |
| Connected-account balance read with `Stripe-Account` | `GET /v1/balance` authenticated as the connected account; platform and connected balances are separate accounts | Confirmed |
| `POST /v1/payouts` in connected scope, `method=standard`, explicit `destination` | All present; `destination` optional and defaults to the default external account for the currency | Confirmed |
| Payout statuses | `pending`, `in_transit`, `paid`, `failed`, `canceled`. “Some payouts that fail might initially show as `paid`, then change to `failed`” | Confirmed — the late-return path is a documented provider behaviour, not a hypothetical |
| `POST /v1/payouts/{po}/cancel` | “You can cancel a previously created payout if its status is `pending`… You can't cancel automatic Stripe payouts” | Confirmed; the adapter passes the refusal through rather than softening it |
| `POST /v1/transfers/{tr}/reversals` | Only possible if the connected account's available balance covers the reversal | Confirmed |
| Event names | `payout.created`, `payout.updated`, `payout.paid`, `payout.failed`, **`payout.canceled`** (one `l`), `transfer.created`, `transfer.reversed`, `balance.available`, `refund.created/updated/failed`, `charge.dispute.created/updated/closed/funds_withdrawn/funds_reinstated` all exist verbatim | Confirmed. There is no `transfer.paid` or `transfer.failed`; `transfer.updated` is metadata only and is not subscribed |
| Idempotency retention | “You can remove keys from the system automatically after they're at least 24 hours old… The idempotency layer compares incoming parameters to those of the original request and errors if they're not the same” | Confirmed. H3 replays only inside a 23-hour window |
| FR/EUR minimum payout | “Minimum payout amounts are typically one base unit of the local currency”; the country table gives EU countries 1 EUR | Confirmed — 100 cents, and configurable |

One contract fact worth stating plainly because it shaped the code: Stripe
retains an idempotency key's result for **at least** 24 hours, not forever. So
“retry with the same key” is a recovery strategy with an expiry date, and past
it the only safe move is to look for the object or to stop.

## The three transactions

Execution is deliberately not one transaction, and the seam between the second
and the third is the whole design.

**1 — Reserve** (`_reserve_dispatch`). Under the Deal lifecycle aggregate: plan
which Stripe charges support this obligation, write immutable
`PayoutFundingAllocation` rows, a `PayoutAttempt` and one
`PayoutProviderOperation` per slice — all `prepared` — and move the Payout to
`scheduled`. Nothing external exists. A crash here is free.

**2 — Commit** (`_commit_dispatch`). A short guarded transition to
`dispatch_committed`, immediately before the first byte leaves. **This is the
linearization point.** After it commits, the amount is treated as externally
exposed even though no HTTP request has been made, because a crash between this
commit and the response is indistinguishable from a lost answer.

**3 — Send and reconcile.** Provider I/O with no database lock held. A confirmed
answer is recorded once. A timeout becomes `unknown`, never “failed, safe to
resend with a new key”.

An operation lease (`retry_after`) stops two workers being inside the same POST
at once. After a crash the lease has to expire before recovery begins, which is
a deliberate trade: from outside, a crashed worker and a slow one look
identical, and waiting two minutes is cheaper than a second Transfer.

## What actually happens, stage by stage

| Stage | Local state | Ledger |
|---|---|---|
| Released by the protection gate | `eligible`, `payout_execute` job armed | — |
| Reserved | `scheduled`, allocations bind the source charges | — |
| Dispatch committed | `processing`, attempt `dispatch_committed` | — |
| Transfer accepted | attempt `accepted` | debit `connect_funds`, credit `provider_clearing` — **payable untouched** |
| Connected balance still pending | deferred, no retry budget spent | — |
| Bank payout submitted | disbursement `pending` | debit `payout_in_transit`, credit `connect_funds` — **payable untouched** |
| Provider reports `in_transit` | `sent` | — |
| Provider reports `paid` | `paid` | debit traveler payable, credit `payout_in_transit` |
| Bank payout fails before paid | `failed` **and blocked**, allocation released, attempt stays `accepted` | debit `connect_funds`, credit `payout_in_transit` |
| Genuine late return after paid | `failed`, disbursement `returned`, paid history kept | debit `connect_funds`, credit traveler payable |

Every posting is idempotent on the operation or disbursement's own public
reference, and every leg carries the payout and the Deal, so each Deal's
sub-ledger still sums to zero on its own.

## Money rules that are enforced, not documented

**The Traveler receives the agreed amount.** The Transfer amount, the bank
payout amount and the canonical obligation are the same number. No Stripe fee,
Connect cost or bank charge is deducted anywhere, and a test asserts the three
figures against the award.

**One euro funds one thing.** `PayoutFundingAllocation` rows are immutable and a
reservation is undone only by an append-only `PayoutFundingRelease` — written
only when Stripe *definitively rejected the request before executing it*.
`request_refund` subtracts live reservations from a capture's spendable amount
under the same lock the dispatch path takes, so a refund and a payout racing for
the same cents produce one winner and one explicit refusal.

**Committed money is not platform cash.** `settlement.read_deal_money` now
counts externally committed exposure, not only `paid`. A Transfer Stripe has
accepted has left the platform balance even though nobody has been paid, and
treating it as settleable is how the same euro reaches two people.

**A failed bank payout does not retry itself.** A bank payout fails for a
reason the platform cannot fix by trying again — a closed account, a wrong
holder name, an unusable IBAN — and the destination is Stripe's to hold and the
Traveler's to correct. So the failure sets a block reason, which is what stops
both the worker and the sweeper from picking the payout back up, and only an
operator's audited *Retry bank payout* clears it. An automatic retry here would
hammer the provider against the same broken account until somebody noticed.

**A sub-minimum award is kept owed.** Below Stripe's 1 EUR FR/EUR minimum the
payout is `blocked/payout_below_minimum` — checked *before* the Transfer, so the
money is not stranded one step further away in a connected account it cannot be
paid out of. Never rounded up, never forfeited, never marked paid. Same-account
accumulation is modelled (`StripeDisbursement` takes N allocations, and the
constraint that they sum to the payout is a database trigger) but H3 creates one
allocation per disbursement; batching is deliberately deferred rather than
faked.

## Recovering from an unknown result

Three routes, in order, and no fourth:

1. **Inside 23 hours** — replay the byte-identical request under the same
   idempotency key. Stripe returns the original object.
2. **Past that window** — a single bounded search: transfers by the payout's own
   opaque `transfer_group` plus the operation reference in metadata; bank
   payouts by the operation reference within the connected account, anchored on
   the operation's first request time.
3. **Neither resolves it** — `PayoutUnresolved`, which the job records as a
   permanent failure. The reservation stands, the key stands, and a person looks
   at it. A fresh POST is never issued because a retry window expired.

## Webhooks

Two endpoints, two scopes, two secrets — unchanged from H2. What H3 adds:

| Scope | Added events | What happens |
|---|---|---|
| Connected | `payout.created/updated/paid/failed/canceled` | Re-read the authoritative Payout in the connected scope, then converge through `apply_bank_payout_observation`. A payout id this platform did not create quarantines the account with a compliance hold |
| Connected | `balance.available` | Wake bank payouts deferred for availability |
| Platform | `transfer.created`, `transfer.reversed` | Re-read the Transfer; a reversal posts a compensating entry for the confirmed amount only |
| Platform | `balance.available` | Wake liquidity-blocked work |
| Platform | `refund.created/updated/failed` | A refund ShipTrip raised is left to the refund reconciler. One it did not raise opens a hold on the affected Deal and creates no second refund |
| Platform | `charge.dispute.*` | Record a `ProviderDispute`, hold the affected Deal, and — on a **won** close only — clear that dispute's own hold and nothing else |

No event is trusted on arrival. Every handler re-reads the authoritative object
in the correct account scope, and the write is guarded on an observation
timestamp so a slow old `GET` cannot regress a newer one.

## Races, proven against real PostgreSQL

`apps/finance/tests/test_phase8fh3_concurrency.py` runs real threads on real
connections and asserts **external** effects from the provider's own call log,
not local row counts.

* Two workers on one payout: exactly one `POST /v1/transfers`, exactly one
  `POST /v1/payouts`, one ledger posting each.
* Refund versus dispatch: whichever lands first, `refunded + reserved` never
  exceeds the capture, and the loser gets an explicit reason.
* Dispute versus dispatch, both directions. Dispute first → nothing is sent.
  Dispatch first → the freeze still stops the *next* stage, and the committed
  exposure is recorded on the payout rather than denied. The operator copy says
  recovery review is required; it does not promise a successful freeze.
* Hold arriving between the Transfer and the bank payout: the bank stage
  re-reads holds immediately before committing, so a Transfer having been
  accepted is not authority to pay a bank.
* A worker killed after the dispatch commitment: the operation stays
  `committed`, a second worker defers on the lease, and once it expires the same
  identity is recovered. Still one Transfer.
* Two simultaneous bank-payout retries after one operator authorisation: one
  new disbursement, one new bank payout, and the original Transfer untouched.

Database guards, also tested: a second committed attempt is refused by a partial
unique index; allocations cannot exceed their bank payout; a funding release
cannot be edited or raw-deleted; an operation's link to its source slice or
disbursement cannot be repointed; a disbursement's provider identity cannot be
swapped once Stripe assigned one.

## Two design corrections found before merge

### The lock order the webhook path took

`apply_bank_payout_observation` locked the disbursement before its payouts,
while `apply_bank_payout_accepted` — reached from the HTTP response — locked the
payout first. Two paths that routinely run at the same moment, taking the same
two rows in opposite orders, is a deadlock waiting for traffic. The observation
path now reads its payout ids unlocked, takes the Deal lifecycle and Payout
locks in the canonical order, and only then locks the disbursement, revalidating
membership afterwards. The H3 execution modules were also added to the
`test_phase8df_lock_order` AST gate, so a bare `select_for_update()` in them
fails that gate first.

## One design correction found by PostgreSQL

The first PostgreSQL run failed with `FOR NO KEY UPDATE cannot be applied to the
nullable side of an outer join`. The payout lock was `select_related`-ing its
nullable destination version, so PostgreSQL was asked to lock a row that might
not exist. Fixed by naming the lock target explicitly (`of=("self",)`), which is
also more honest: only the Payout row needs locking, and the destination version
is immutable by construction. SQLite had accepted it silently, which is exactly
why the concurrency tier is PostgreSQL-only.

## Admin surface

The existing `Finance → Payouts` detail page gains a Stripe panel: canonical
obligation, masked account reference, readiness and last check, committed
exposure, source allocations with their charge references, external operations
with provider references and states, bank payouts with submitted/paid/arrival
times, active holds, and the full payout timeline.

Three recovery actions, each on its own capability, each state-safe:

* **Re-read Stripe state** (`reconcile_finance`) — asks the provider and lets
  the same reconciler a webhook uses record the answer.
* **Retry bank payout** (`retry_payouts`) — only from `failed`, only with no
  active hold, no unresolved operation, no live disbursement, and only against
  the current state version. Clearing the block reason *is* the authorisation:
  it is the recorded human judgement that the destination has been corrected.
  It creates another *bank payout*; there is no path that creates the Transfer
  again.
* **Hold for Finance review** (`manage_payout_holds`) — stops the next stage and
  leaves the reservation exactly as it was.

There is deliberately no Mark paid, no reset to eligible, no force, no amount or
destination edit. `complete_manual_payout` still refuses versioned payouts.

## Configuration

| Variable | Value for TEST | Note |
|---|---|---|
| `STRIPE_CONNECT_PAYOUTS_ENABLED` | `true` | No longer refused at boot. Still refused **without** `STRIPE_CONNECT_ENABLED`, and still refused when `STRIPE_CONNECT_EXPECTED_MODE` is `live` — live payout execution is H8's gate, not this release's |
| `payments.payout.auto_stripe_enabled` | `true` | The versioned business authorisation. H0 requires **both**; either one off and nothing dispatches |
| `STRIPE_CONNECT_MINIMUM_PAYOUT_EUR_CENTS` | `100` | Stripe's published FR/EUR minimum |
| `STRIPE_CONNECT_NON_STRIPE_FUNDING_ENABLED` | `false` | Unchanged, still refused true. Chargily-funded EUR remains `blocked/funding_route_unavailable` |
| `PAYOUT_DZD_EXECUTION_ENABLED` | `false` | H4 |
| `FINANCE_DASHBOARD_ENABLED` | `false` | H5 |
| `EMAIL_ENABLED` | `false` | Payout events are enqueued durably and dispatch nothing |

## Migrations

`finance/0020_phase8fh3_execution` is additive: `PayoutFundingRelease`,
`StripeDisbursement`, `StripeDisbursementAllocation`, ten new columns on
`PayoutProviderOperation`, two new ledger accounts and four new job kinds. No
data is rewritten and no provider call is made.
`finance/0021_phase8fh3_guards` installs the write-boundary triggers described
above. Both reverse cleanly on a disposable database; neither should be reversed
once real provider operations exist.

## Deferred, and named as deferred

* **Same-account accumulation of sub-minimum awards.** Modelled in the schema,
  not scheduled. A sub-minimum award is a persistent `blocked` state today.
* **Automatic transfer reversal.** The adapter has the call and the ledger has
  the posting; no automatic path invokes it, because “policy authorises it” is
  not a decision H3 was given.
* **Bank-payout cancellation as a product action.** The adapter call exists and
  passes Stripe's `pending`-only refusal through. Nothing calls it
  automatically.
* **Non-Stripe-funded EUR.** Still gated, still false, still blocked.

## Verified on the deployed release

`v1.0.0-rc.17+1d86cb3`, deployment `2eb9b372-d756-477a-bc6b-5099a18d5044`,
SUCCESS. `/healthz` and `/readyz` 200, migrations `ok`, zero pending. Merged as
a fast-forward of the CI-green SHA; six required jobs passed, including the
schema-drift gate.

Webhook events were added **after** the deploy, never before: the connected
destination `we_1UDSGx3aixfgmaTzPxCXmtOB` now carries 11 events and the platform
destination `we_1UAYk83aixfgmaTzEQr2WKS0` 16, both on `2026-03-25.dahlia`, all
five original payment events retained, no wildcard.

Both authorisations were turned on — `STRIPE_CONNECT_PAYOUTS_ENABLED=true` and
business settings **v9** with `payments.payout.auto_stripe_enabled=true`.

### The controlled TEST payouts

Three new Deals were built for synthetic Traveler `14` through the real
services — offer, acceptance, recipient, pickup and delivery all through
production code paths — and paid with real Stripe TEST Checkout sessions. The
historical EUR 60 QA payout `1` was not reused and is untouched.

**The gate was proven before it was passed.** With the flag on, the business
setting on, the account authoritatively `ready` and the money captured, the
first payout still refused: `payout_not_eligible`, zero attempts, zero external
operations. Only then was the stored protection deadline moved into the past —
a database fixture, with no endpoint added and the production check unchanged.

| | Payout 2 | Payout 3 |
|---|---|---|
| Source charge | `ch_3UDl9N3aixfgmaTz0xwd8rr2` | `ch_3UDlGS3aixfgmaTz1kSe4R12` |
| Transfer | `tr_3UDl9N3aixfgmaTz0MVUi3Zp` | `tr_3UDlGS3aixfgmaTz1OOyOZSO` |
| Bank payout | `po_1UDlHlKWXRqQfWCdfzxKss8X` | `po_1UDlOGKWXRqQfWCdqaaSLs2W` |
| Stripe status | **paid** | **paid** |
| ShipTrip status | **paid** | **paid** |

Stripe's own `GET /v1/payouts/po_1UDlHl…` reports `status: paid`, `amount: 6000`,
`currency: eur`, `method: standard`, `automatic: false`, `livemode: false`,
destination `ba_1UDShtKWXRqQfWCdLiAFt2n0`, and metadata containing only
ShipTrip's opaque operation and payout references.

Nobody clicked anything. `evaluate_payout_release` armed `payout_execute`, and
the deployed worker did the rest.

### What the evidence actually shows

**The PaymentIntent gap is real and was closed.** The checkout rail had stored
only `pi_3UDl9N…`; `provider_charge_id` was empty. H3 resolved it to `ch_…`,
verified the charge and persisted it, and Stripe accepted the Transfer with that
charge as `source_transaction`.

**A Transfer is not a payment.** After the transfer accepted, the ledger read
`connect_funds 6000`, `traveler_payable −6000` — money out of the platform, and
the Traveler still owed every cent. The payable only reached zero when Stripe
said `paid`.

**Deferral is real, not decorative.** Payout 2's transfer was made against an
unsettled charge, so Stripe placed the funds in the connected account's
*pending* balance. The bank stage deferred with `connected_balance_pending`,
retry budget untouched at attempts `0`, rather than paying a bank from money
that had not settled.

**Convergence is idempotent under real provider behaviour.** Eight `payout.*`
events arrived across the two payouts — `created`, `updated` twice, `paid` —
and every one resolved to `bank_payout_paid` with **one** ledger effect each and
zero failed events. `transfer.created` (platform) and `balance.available` (both
scopes) were also ingested and applied.

**Exactly one Transfer per payout**, counted on the provider's own objects:
`{payout 2: 1, payout 3: 1, payout 4: 1}`.

**Ledger, per Deal, after settlement:** `traveler_payable 0`, `connect_funds 0`,
`payout_in_transit 0`, `provider_clearing 1500`, `platform_commission −1500`,
net **0**. The Traveler received the full EUR 60.00; no Stripe cost was
deducted from it.

**Notifications leaked nothing.** Nine durable `payout_status` messages, all
`pending`, none dispatched, keyed on the payout reference and state version, and
containing no `acct_`, `tr_`, `po_`, `ch_` or `ba_` value.

**Admin surface, rendered live on the paid payout.** Finance gets `200` with the
Stripe panel, the transfer and bank-payout references, the source charge, a
masked account reference (the full connected id is absent), the timeline through
`bank_payout_paid`, and the recovery actions. There is no “Mark payout paid” on
the page, no secret and no IBAN. Support gets `403`.

### The failure test, and why it is not live evidence

H0 and this phase prefer a Stripe-supported TEST bank-payout failure. Stripe
publishes FR test IBANs for exactly that — `FR89370400440532013002` fails with
`account_closed`. Adding one to Traveler 14's connected account was refused:

```
403 invalid_request_error / oauth_not_supported
This application does not have the required permissions for this endpoint
on account 'acct_1UDSCoKWXRqQfWCd'.
```

That was the **platform's own credential**, not a restricted CLI key. A platform
may not manage the external account of a `requirement_collection=stripe`
controller account — which is the architecture working exactly as H0 and H2
specified: the Traveler owns their bank details in the Express Dashboard and
ShipTrip never holds or changes them. Forcing a live failure requires the
Traveler to add the failing IBAN themselves, the same class of human step as
H2.5's hCaptcha.

So the failure and recovery paths — definitive bank rejection, bank failure
before paid, late return after paid, ambiguous-result recovery, transfer
rejection and release — are proven by **provider-adapter fault injection against
real PostgreSQL**, not by Stripe. That distinction is deliberate and this
document does not blur it.

### Open at the end of the run

Payout 4 is `processing` with its Transfer accepted (`tr_3UDlMD3aixfgmaTz0VBDqz5s`)
and its bank payout waiting for connected-account availability. That is the
deferral behaving correctly, not a stall; the sweeper carries it. The historical
EUR 60 QA payout `1` remains `blocked / legacy_instruction_required`, unpaid,
with no provider reference.

One minor finding worth recording: `PayoutDeferred` does not advance the
payout's `next_action_at`, so the sweeper re-arms a deferred payout on its own
cadence rather than the deferral's. Each re-arm simply re-reads the balance and
defers again, so it is not a correctness problem — but the deferral's own delay
is advisory rather than binding, and a later phase should make the two agree.
