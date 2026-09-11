# Phase 8F-H7 — Full TEST payout rehearsal and release validation

H7 adds no features. It is a controlled, end-to-end TEST rehearsal that asks one
question of the payout system H0–H6 built: **does it hold together on the
deployed service, from a real provider charge to a Traveler who is actually
paid, without paying anyone twice and without a single number disagreeing with
the ledger?**

Two funded Deals were driven through their complete lifecycles on
`https://shiptrip-production-f7f7.up.railway.app`, release
`v1.0.0-rc.25+c73a4fc`, on 11 September 2026. Both reached `paid`. Stripe was
TEST, Chargily was TEST, email stayed disabled, no LIVE operation of any kind
was performed, and no real dinar was transferred.

**No source change was required.** This document, and the implementation-status
entry beside it, are the only files H7 writes.

## What "rehearsal" was allowed to mean

Three rules shaped every decision below.

**Provider state advanced through the real provider.** Both Deals were funded by
opening the application's own hosted checkout and paying it: a Stripe Checkout
Session settled with a TEST card, and a Chargily TEST checkout settled on
`pay.chargily.dz`. Both captures arrived as signature-verified webhooks at the
deployed endpoints. The Stripe EUR payout was executed by the deployed finance
worker, which created a real platform Transfer and a real connected-account bank
Payout. None of that is fixture data.

**Database state advanced through application services.** Negotiation, funding,
recipient capture, pickup, delivery, release, execution and manual settlement all
ran through the production code paths — several of them over the deployed HTTP
API as the Finance operator. No payout status, amount, currency, FX rate or
ledger row was ever written by hand.

**Two deliberate exceptions, both disclosed, neither financial.** The 48-hour
protection window cannot be waited out inside a rehearsal, and the DZD execution
flag is off by default. Both are described precisely in *Deliberate test
controls* below.

## Test identities

All accounts are synthetic and are referenced by safe identifiers only. No real
personal, banking or identity data was used or uploaded.

| Role | Reference | Note |
|---|---|---|
| Path A Traveler | `TR-14`, `qa14@example.com` | Existing synthetic QA Traveler from H2.5, with a ready Stripe connected account |
| Path A Sender | user 50, `h7a-20260911-sender@shiptrip-qa.invalid` | Created for H7 |
| Path A Deal / Payout | `ST-6` / `PAYOUT-6`, `4a42a9fc-…ec05` | — |
| Path B Traveler | `TR-52`, `h7b-20260911-traveler@shiptrip-qa.invalid` | Created for H7, approved KYC, approved DZD profile |
| Path B Sender | user 51, `h7b-20260911-sender@shiptrip-qa.invalid` | Created for H7 |
| Path B Deal / Payout | `ST-7` / `PAYOUT-7`, `14c7a976-…c50d` | — |
| Finance operator | user 53, `h7b-20260911-finance@shiptrip-qa.invalid` | `finance` role |
| Second Finance operator | user 55, `h7b-20260911-finance2@shiptrip-qa.invalid` | Used only to prove exclusive ownership |
| Trust reviewer | user 54, `h7b-20260911-trust@shiptrip-qa.invalid` | `trust_verification` role |

The Path A Traveler's connected account is `acct_1UDSCo…`, under platform
`acct_1TLWM9…`, with EUR bank destination `ba_1UDSht…`. CCP and RIP values are
synthetic zero-fill placeholders and appear nowhere in this document; the console
and the mobile contract expose only their last four digits.

## Path A — Stripe funded, automatic EUR payout

### Funding

The Sender's €58.75 balance order was paid through the application's own Stripe
Checkout Session `cs_test_a1x2iM…`, settled with TEST card `4000 0000 0000 0077`
(the card Stripe documents as adding funds directly to the available balance, so
the connected-account bank stage would not sit behind a seven-day settlement
delay). Stripe delivered `checkout.session.completed`
(`evt_1UEbSf3aixfgmaTz…`) to the platform endpoint: signature verified,
`provider_mode = test`, applied once, bound to attempt 17 and order 12. A
`balance.available` event followed a minute later.

Exactly one attempt on that order succeeded. The funding transaction pair is the
normal two-step capture:

| Account | Cents | Transaction |
|---|---|---|
| `provider_clearing` | +5,875 | 25 — provider capture |
| `deal_funds` | −5,875 | 25 |
| `deal_funds` | +5,875 | 26 — deal funded |
| `traveler_payable` | −4,700 | 26 |
| `platform_commission` | −1,175 | 26 |

### Routing snapshot

Funding froze `PAYOUT-6` before anything else could move: rail
`stripe_transfer`, currency EUR, `funding_provider_snapshot = stripe`,
`routing_policy_version = payout_routing_v1`, method version 2 (the Traveler's
current Stripe version, bound to connected account 1), snapshot version 1,
award 4,700 cents, status `not_eligible`.

### Delivery and protection

Recipient recorded → `pickup_ready`. The Sender revealed the pickup code and the
Traveler submitted it → `in_transit`, and the delivery code went into its
30-minute buffer with `traveler_can_view_delivery_code = false`. After the buffer
elapsed the code released on its own schedule, the Sender revealed it, the
Traveler submitted it → `protection_window`.

`protection_ends_at − delivery_confirmed_at = 172,800 seconds`, exactly 48 hours.
A release evaluated inside the window returned `protection_open` and the payout
stayed `not_eligible` with no execution attempted.

### Execution

After the clock control described below made the window closed, the deployed
finance worker did the rest unattended:

| Job / event | Result |
|---|---|
| `payout_release_check:6` | `payout_eligible` at 21:27:33, basis `delivery_protection` |
| `payout_execute:6` | reserved → committed → Transfer → bank payout |
| Platform Transfer | `tr_3UEbSe…`, 4,700 cents, scope `acct_1TLWM9…`, idempotency `tr:test:4a42a9fc-…:a1:s17`, balance txn `txn_3UEbSe…` |
| Connected bank Payout | `po_1UEbzs…`, 4,700 cents, `method=standard`, destination `ba_1UDSht…`, scope `acct_1UDSCo…` |
| Disbursement 3 | submitted 21:28:37.601, **paid** 21:28:37.853 |
| `PAYOUT-6` | **paid** 21:28:37.853, `settlement_basis = stripe_bank_payout`, state version 7 |

Exactly one `transfer_create` operation and one `bank_payout_create` operation
exist. One funding allocation (`ch_3UEbSe…`, 4,700 cents), zero releases.
**Award = Transfer amount = bank payout amount = 4,700 cents**; no fee was
deducted anywhere.

Provider events arrived on the correct endpoints and scopes, all signature
verified, all `provider_mode = test`: `transfer.created` on the **platform**
endpoint; `payout.created`, `payout.updated` ×2, `payout.paid` and
`balance.available` on the **connect** endpoint.

### Ledger

Three balanced transactions, exactly the H3 contract — the payable is untouched
until money actually lands:

| Transaction | Entries |
|---|---|
| 29 — transfer accepted | `connect_funds` +4,700 / `provider_clearing` −4,700 |
| 30 — bank payout submitted | `payout_in_transit` +4,700 / `connect_funds` −4,700 |
| 31 — bank payout settled | `traveler_payable` +4,700 / `payout_in_transit` −4,700 |

Deal 6's sub-ledger sums to zero; its Traveler payable nets to zero; the
platform retains its €11.75 commission.

## Path B — Chargily funded, manual DZD payout

### Funding

The €68.75 balance order was paid through a real Chargily TEST checkout,
`01m294abkm…`, on `pay.chargily.dz` in Test mode: **19,250.00 DZD**, EDAHABIA
card, accepted. Chargily delivered `checkout.paid`
(`01m294d34nnx…`): signature verified through the documented HMAC-SHA256 of the
raw body (the deployment leaves `CHARGILY_WEBHOOK_SECRET` empty and the adapter
correctly falls back to the API secret key, which is what Chargily signs with),
`provider_mode = test`, applied once, bound to attempt 20.

Two earlier attempts on the same order are part of the evidence rather than
noise: attempt 18 ended `failed` via a real `checkout.failed` event, attempt 19
ended `cancelled`/`expired` via real `checkout.canceled` and `checkout.expired`
events. Both were applied once, and **only** attempt 20 funded the Deal —
funding captured exactly once despite three provider sessions.

### Routing, profile and FX snapshot

| Frozen fact | Value |
|---|---|
| Rail | `manual`, currency DZD |
| Funding provider snapshot | `chargily` |
| Method version | 10 (sequence 2) |
| DZD profile revision | 2 |
| Canonical EUR | 5,500 cents |
| Frozen FX | 280,000,000 micros, source `business_settings_v9.payments.chargily.eur_dzd_rate_micros` |
| Frozen DZD settlement | **15,400** |
| Rounding policy | `ceil_whole_dzd_v1` |

`ceil(5500 × 280,000,000 / 100,000,000) = 15,400`. The rate is the authoritative
frozen rate for this object; the historical 260 / 15,600 case from H4 is
untouched and both appear side by side in the Finance drilldown.

### Delivery, protection and the Finance workflow

Delivery followed the same real handover path as Path A;
`protection_ends_at − delivery_confirmed_at` was again exactly 172,800 seconds,
and a release inside the window returned `protection_open`.

The manual workflow then ran **over the deployed HTTP API** as the Finance
operator:

| Step | Result |
|---|---|
| Detail | `eligible`, state version 5, EUR 5,500 / DZD 15,400 / rate 280,000,000, CCP and RIP masked to last four |
| Prepare | `scheduled`, instruction revision 1, operator 53, state version 6 |
| Second operator prepare | **400** `payout_profile_invalid` |
| Second operator begin | **403** "Only the claiming operator may execute this instruction" |
| Begin | `processing`, committed 21:34:58.690, state version 7 |
| Receipt upload | 201, evidence `81468f6b-…6261` |
| Confirm (settled) | **paid** 21:34:59.920, `sent_at` 21:34:59.911 preserved separately, state version 9 |
| Confirm repeated | identical projection, **state version still 9** |

The receipt is a synthetic PNG generated for this rehearsal and captioned
"SYNTHETIC QA TRANSFER RECEIPT — NOT A REAL BANK TRANSFER. No money was sent."
It is stored encrypted in the payout evidence bucket, not as a URL. **No dinar
was transferred to any account.** The payout reference is
`manual:6:81468f6b-…`, generated internally; `receipt_url` is empty and
`provider_payout_id` is empty, both correct for this rail.

Event timeline: `funding_snapshot` → `hold_opened` → `hold_cleared` →
`protection_release` (blocked) → `protection_release` (eligible) →
`manual_instruction_created` → `manual_instruction_committed` →
`manual_transfer_sent` → `manual_transfer_settled`. Both the sent and the
settled events, and both timestamps, are preserved.

### Ledger

One balanced settlement transaction: `traveler_payable` +5,500 /
`provider_clearing` −5,500. Deal 7's sub-ledger sums to zero, its payable nets to
zero, and the repeated confirm produced **no second settlement row**.

## Routing immutability after funding

Both checks were run on the already-funded payouts.

**Preference change.** Traveler A (EUR-only) had DZD enabled; Traveler B
(DZD-only) had EUR enabled. Both summaries now read `both`. `PAYOUT-6` remained
`stripe_transfer`/EUR/method version 2; `PAYOUT-7` remained
`manual`/DZD/15,400/method version 10/profile revision 2. Neither rerouted.

**Profile replacement.** A new DZD profile was submitted, reviewed and approved
for Traveler B, becoming method version 13 / profile revision 3 and the current
active destination. `PAYOUT-7` stayed byte-for-byte on method version 10 and
profile revision 2, with its amount, currency and FX unchanged. The historical
destination did not move; future payouts would use the new version.

The current FX rate was deliberately **not** changed. `activate_business_settings`
retires the previous revision permanently and refuses to reactivate it, so
proving snapshot immutability that way would have left an unreturnable settings
revision on the deployed environment for evidence that the immutable
`fx_rate_micros`, `fx_settings_version`, `fx_snapshot_at` and
`original_settlement_amount_minor` columns — plus the profile-replacement result
above — already provide. This is recorded as a deliberate omission, not a pass.

## Idempotency and race safety

| Check | Result |
|---|---|
| Stripe `checkout.session.completed` redelivered | HTTP 200 `{"received":true,"duplicate":true}`; one stored row, original `received_at` preserved, no new ledger entry, no new notification |
| Chargily `checkout.paid` redelivered | Same: 200 duplicate, one row, no new ledger, no new notification |
| `execute_payout(6)` called twice after paid | `PayoutBlocked: Terminal payout` both times |
| `admin_refresh_payout(6)` | `transfer_observed,bank_payout_paid` — re-read Stripe, **one** transfer operation, **one** bank payout operation, **one** disbursement, no new ledger rows, state version unchanged |
| DZD confirm repeated | Identical projection, state version unchanged, one settlement transaction |
| Second Finance operator | Refused at both prepare (400) and begin (403) |
| Finance hold opened before release | Release returned `finance_hold_active`; prepare refused; clearing the hold restored progression |

Both replays were performed by posting the provider's own stored, signed payload
back through the public webhook endpoint with a valid signature. That is
application-level duplicate delivery, not a provider-initiated redelivery from
the Stripe Dashboard, and is labelled as such.

## Notifications

Seventeen payout notifications exist for the two Travelers across the whole
history, with **seventeen distinct `event_id` values** — no duplicate survived
the replays or the repeated finalisation.

* Path A: `payout.ready` → `payout.processing` → `payout.paid`.
* Path B: `payout.profile_ready` ×2 → `payout.needs_attention` (the hold-and-block
  episode) → `payout.ready` → `payout.processing` → `payout.paid`.

The DZD rail deliberately coalesces to `paid` rather than emitting `sent` and
`paid` a few milliseconds apart, which is the H0 rule.

A regex scan of every payout notification payload for Stripe object identifiers,
`stripe.com` URLs, CCP/RIP-shaped digit runs and account field names returned
**zero matches**. Payloads carry only `deal_id`, `match_id`, `parcel_id`,
`journey_id`, `payout_reference` (an internal UUID), `message_key`, `event_id`
and a timestamp. Email stayed disabled throughout.

## Finance projection

The H5.1 dashboard and the H5 read model tracked both objects through every
stage. At the funded stage the payout groups read exactly
`manual_dzd / pre_delivery / chargily · €55.00 · 15,400 DZD` and
`stripe_eur / pre_delivery / stripe · €47.00`, with `liability_pre_delivery`
at €102.00 across two payouts.

After settlement both leave the liability buckets entirely and appear in their
rail drilldowns:

```
PAYOUT-6 | ST-6 | TR-14 | €47.00 | 47.00 EUR  | Paid | Stripe EUR transfer | Stripe-funded
PAYOUT-7 | ST-7 | TR-52 | €55.00 | 15,400 DZD | Paid | Manual DZD transfer | Chargily-funded | 1 EUR = 280 DZD
```

Euros and dinars are never added; each payout shows its own frozen rate, so the
H4 object at 260 and the H7 object at 280 sit in the same table without
interfering. The deployed Finance console's payout detail pages for both objects
contain no Stripe object identifier, no Stripe URL and no full account number.

## Reconciliation after H7

One H5 snapshot (`mode=test`, 30 days), taken after both paths completed and
again after the configuration was restored:

| Comparison | Reported | Authority | Difference | Row mismatches |
|---|---|---|---|---|
| Applied funding | €512.88 | €512.88 | €0.00 | 0 |
| Finalized refunds | €0.00 | €0.00 | €0.00 | 0 |
| Paid settlements | €282.00 | €282.00 | €0.00 | 0 |
| Traveler state to ledger | €60.00 | €60.00 | €0.00 | 0 |
| Traveler dashboard to ledger | €60.00 | €60.00 | €0.00 | 0 |
| Platform recognition partition | €85.50 | €85.50 | €0.00 | 0 |

`integrity = ok`, zero unbalanced transactions, no warnings, no data issues.

The absolute totals moved because H7 created real TEST transactions, and that is
expected: funding rose by €127.50 (€58.75 + €68.75) from the pre-H7 €385.38, and
paid settlements rose by €102.00 (€47.00 + €55.00) from €180.00. The global
ledger sums to **0** across 71 entries in 32 transactions, with zero unbalanced
transactions; every mode bucket balances independently.

## Returned and failed payout coverage

No returned or failed payout was produced on the provider. Stripe TEST offers no
deterministic, non-destructive way to fail a bank payout on a connected account
without altering that account's external destination, which would have put the
settled H7 Stripe payout at risk for evidence the existing suite already covers.

Coverage is therefore **simulated test coverage, not real-provider evidence**:
`TestBankPayoutFailure` in the H3 execution suite (failed bank payout never
recreates the Transfer; a genuine late return after paid preserves the paid
history and restores the debt; insufficient connected balance defers without
failing) plus the two H6A mobile tests that assert a returned bank payout renders
as returned rather than as paid or as a generic failure. Six tests, all passing
on PostgreSQL. `payout_returns` in the H5 snapshot is €0.00 with zero rows — no
returned state was fabricated anywhere.

## Mobile contract and UI smoke

The deployed API was read as each Traveler at three points. Every projection was
correct for its rail and stage:

| Stage | Path A | Path B |
|---|---|---|
| Funded | `stripe_eur`, EUR 4,700, `dzd_amount: null`, `awaiting_delivery` | `manual_dzd`, EUR 5,500, DZD 15,400, rate 280,000,000, `awaiting_delivery` |
| Protection | `protection_active`, `blocking_reason: protection_active`, real `protection_ends_at` | same shape |
| Paid | `paid`, `paid_at` set | `paid`, `sent_at` **and** `paid_at` set separately |

`destination_scope` reads `funded_snapshot` throughout, `available_actions` are
bounded to `view_payout` / `refresh`, and the same object appears identically in
the summary, the detail endpoint, the history page and the Deal's
`payout_summary`. Path A's `sent_at` is null because the Stripe bank payout moved
from `processing` to `paid` without an observed `in_transit` stage, which is the
documented H3 mapping rather than a gap.

UI smoke used the existing H6B widget suite rather than a new build: **16 of 16
tests pass**, covering payout methods, DZD setup validation, the detail screen's
canonical EUR plus snapshotted DZD and rate formula, blocking reasons, paginated
history, the delivery-screen payout section, notification deep-linking for all
payout states, and Arabic RTL layout of the methods and detail screens. No new
APK was built and no device QA was performed; no H6B integration defect was found
that would have justified one.

## Deliberate test controls

**Clock control.** A 48-hour window cannot elapse inside a rehearsal. For each
Deal, and only after its protection state had been observed as correct, all six
of its lifecycle timestamps — `funded_at`, `pickup_confirmed_at`,
`delivery_code_available_at`, `delivery_code_released_at`,
`delivery_confirmed_at`, `protection_ends_at` — were shifted back by a uniform
72 hours, together with that payout's `payout_release_check` job. Every interval
was preserved, so `protection_ends_at − delivery_confirmed_at` remained exactly
172,800 seconds and the 48-hour product rule was neither changed nor bypassed —
only made to have already elapsed. No status, amount, currency, rate, payout,
ledger or provider record was touched. One disclosed artefact: each Deal's
`funded_at` now precedes its own immutable provider capture timestamp, because
the payment attempt's `succeeded_at` is provider evidence and was deliberately
left alone.

**Flag control.** `PAYOUT_DZD_EXECUTION_ENABLED` was set to `true` on Railway so
the manual DZD workflow could run through the real deployed HTTP API rather than
an in-process settings override, then set back to `false` after settlement. Both
changes redeployed the same release `v1.0.0-rc.25+c73a4fc`; `/healthz` and
`/readyz` returned 200 with database, migrations and rate-limit cache `ok` after
each, and all workers — gunicorn, Caddy, loopback Redis, the reservation
releaser, the finance worker, the KYC gRPC listener and the four Go workers —
came back running. The flag is back at its pre-H7 value and every other payout,
provider, email and dashboard flag is unchanged.

## Findings

**MINOR — a superseded identity attestation retroactively blocks an
already-funded manual payout, with a reason code that misdescribes the problem.**

`approved_profile` requires `not identity.successors.exists()` on the attestation
that approved a DZD profile revision. `attest_identity` makes every new
attestation supersede the traveler's previous one unconditionally, even when the
attested legal name is identical. So when a Traveler's identity is re-attested —
which happens on a renewed KYC, and happened here during the profile-replacement
check — the approval of the *frozen* profile revision that an already-funded
payout is bound to is invalidated after the fact. `PAYOUT-7` moved to
`blocked / payout_setup_required` and emitted a `payout.needs_attention`
notification, pointing the Traveler at a payout profile that is complete and was
approved. The Traveler cannot clear it: any further profile submission creates
another successor.

Why it is MINOR rather than MAJOR: no money is at risk or misdirected, the frozen
destination never changes, and a Finance operator can recover with one audited
command. Re-reviewing the frozen profile revision (`review_profile` on
revision 2) rebound it to the current attestation, `approved_profile` returned
true, and release proceeded normally — that is exactly what was done here, and
the payout settled correctly afterwards.

It is **not fixed in H7**. The successor rule is deliberate H1/H4 identity
anti-abuse design, and choosing between "a superseded attestation should not
invalidate a historical approval it already granted" and "it should, and the
operator queue must surface it with an accurate reason" is a product decision
about identity semantics, not the smallest correct fix to an evident bug. It
belongs to whoever owns the payout identity model.

**Observation, not a defect.** The manual rail sets `paid_at` but leaves
`settled_at` and `settlement_basis` empty; only the Stripe reconciler writes
those. Nothing reads them for accounting — H5's `paid_settlements` counted
`PAYOUT-7` correctly at €282.00 — so this is a cosmetic asymmetry between the two
rails rather than a reconciliation problem.

No BLOCKER and no MAJOR finding was produced by H7.

## Limitations

* Returned and failed payout behaviour is covered by existing tests, not by a
  real provider failure. See *Returned and failed payout coverage*.
* The current FX rate was not changed after funding; see *Routing immutability*.
* Webhook replays were application-level, not Stripe-Dashboard redeliveries.
* Mobile verification was the deployed API contract plus the existing green H6B
  widget suite. No new APK, no device QA.
* Path A reused the H2.5 synthetic Traveler's already-onboarded connected
  account rather than running a fresh Stripe hosted onboarding.
* Path A's connected-account bank payout was made available immediately by using
  the TEST card documented to add funds directly to the available balance. A
  production charge settles on the account's normal schedule, and H3's
  `connected_balance_pending` deferral — still visible on the pre-existing
  `PAYOUT-4` — is the path that handles that.
* The QA accounts created for H7 were left active and auditable rather than
  disabled, so the evidence above can be re-read.

## Verdict

**H7 PASS.** Both rails proved end to end on the deployed TEST service: funding
captured exactly once, routing frozen and immutable, protection exactly 48 hours
and enforced, eligibility correct, exactly one Transfer and exactly one bank
payout, operator-attested DZD settlement with synthetic evidence, correct and
duplicate-free notifications, correct mobile and Finance projections, a global
ledger that balances to zero, and an H5 snapshot with `integrity = ok` and every
comparison at zero difference. No LIVE Stripe operation, no LIVE Chargily
operation and no real dinar transfer occurred.

I1 and H8 were not started.
