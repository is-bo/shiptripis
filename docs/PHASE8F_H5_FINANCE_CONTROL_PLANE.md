# Phase 8F-H5 — Finance control plane core

Contract version: `h5.v1`. H5.1 consumes this backend contract; presentation
must not implement alternative accounting formulas. Starting main:
`21c5c861c8936150e5473737684b3896bbf54932`.

## Authority and compatibility

`apps/finance/control_plane/definitions.py` is the metric dictionary, including
name, formula, source, inclusion/exclusion, units, timestamp and reconciliation.
`queries.py` supplies the exact contributing-row query for each metric;
`snapshot.py` aggregates it and `drilldown.py` pages the same query.
`reconciliation.py` compares the reporting projection with ledger, payout-state
and settlement/refund records. H0–H4 financial writers and provider adapters are
unchanged. There are no new tables, indexes, migrations, financial mutations,
snapshot caches, exports, or provider balance requests.

H0 proposed dedicated earned-revenue accounts and recognition events, but H1–H4
did not create them. The existing `platform_commission` label is **not** evidence
that funding is earned revenue. H5 uses a read-only earning-evidence projection
of those existing signed entries. It does not pretend the proposed accounts
exist, rewrite historical entries, or change settlement's account vocabulary.
Dedicated recognition accounts, category allocation and tax accounting remain
separate future accounting work, not an H5.1 frontend formula.

All money is integer EUR cents. DZD amounts are frozen integer whole dinars on
individual manual instructions. `sum(payout_amount_minor)` is labeled DZD
scheduled/manual settlement amount, never canonical marketplace value. Missing
FX/settlement amounts stay null, with `dzd_missing_count`; they are not priced
using current settings. At rate 260, 6,000 EUR cents corresponds to 15,600 DZD.
No total combines EUR cents with DZD dinars.

## Scope and time

The endpoint requires `mode=test|live|legacy_unknown`. Queries constrain mode
in the database, including capture/refund, ledger, payout, bank allocation and
funding allocation sources. Unknown historical mode is a separate review cohort;
it is never silently treated as TEST or LIVE. No names, email patterns or
synthetic/probe labels exclude historical financial rows.

One existing metadata gap is handled explicitly: refunding a wholly unapplied
capture can leave its ledger transaction mode `legacy_unknown`, because the
historical writer searched only applied captures. If the linked refund and its
capture both explicitly agree on TEST or LIVE, H5 attributes those ledger rows
to that mode in SQL and reports `source_attributed_legacy_entry_count` with an
integrity warning. They are excluded from the unknown cohort. Contradictory
known modes are never overridden, and no stored history is rewritten.

H0 reporting timezone is **Europe/Paris**, including DST. `period=today|7d|30d`
means local today plus the preceding 0/6/29 calendar days. Default is `30d`.
`period=custom&start=YYYY-MM-DD&end=YYYY-MM-DD` includes both named dates by
converting to `[start midnight, midnight after end)`. Custom ranges are ordered,
at most 366 calendar days and cannot end in the future. Boundaries are aware
datetimes; storage remains UTC.

Period selection changes **flows only**. Liabilities, holdings, exposure,
open refunds, disputes and operational queues are current, evaluated under one
PostgreSQL `REPEATABLE READ, READ ONLY` transaction. The response states `as_of`
and `balance_basis=current`. There is no historical balance-as-of reconstruction.
The service requires a standalone PostgreSQL transaction, sets a 10-second
per-statement timeout and makes no writes or provider requests.

Filters:

| Parameter | Accepted values / semantics |
|---|---|
| `provider` | `stripe`, `chargily`. Cash/refunds/reservations use the actual source provider. Payout/revenue scope is an any-source Deal cohort, including credited deposits and bound Boost. |
| `rail` | `stripe_eur`, `manual_dzd`; outgoing frozen method/currency. |
| `currency` | `EUR`, `DZD`; outgoing settlement currency, never changes canonical units. |
| `state` | Existing Payout status enum. |
| `operation` | Allowlisted operational stage from `OPERATION_STAGES`, e.g. `claimed`, `bank_processing`, `settled`; exact rail-operation drilldown. |
| `held` | `true`, `false`, `disputed`; scoped active holds and/or user/provider disputes. |
| `search` | Exact payout/order UUID, `ST-<Deal id>` or `TR-<Traveler id>`; no substring/SQL-like search, names or bank identifiers. |

Rail/state/hold/reference filters select the contributing Deal cohort for flows.
An unmatched deposit/Boost remains reachable by its own order UUID. Without a
cohort filter, applied unmatched funding is included. A mixed-funded Deal is
explicitly `funding_mix=mixed`; its **whole award** may belong to both provider
cohorts. Those cohort totals are non-additive. Exact source reservations are
separately reported from immutable allocations; no last-provider fiction splits
a mixed obligation. Provider exposure never asserts a Stripe Dashboard or
Chargily wallet balance.

## KPI dictionary

The executable dictionary returned in `definitions` is authoritative at the
field level. This table explains the economic relationships and source grain.
All current amounts include signed corrections; no negative discrepancy is
clamped away.

| Key | Formula / source grain | Time basis |
|---|---|---|
| `gross_funded` | Positive customer-payment/provider-clearing ledger leg linked to a succeeded, applied capture, once. Posting deposits, balances and paid Boost are included. | Capture `succeeded_at` |
| `net_funded` | Period gross funded minus period finalized **applied** refunds. This is a cash-flow measure and can be negative. | Capture and refund successful dates independently |
| `deposits_collected` | Posting-deposit subset of gross funded. | Capture `succeeded_at` |
| `deposits_credited` | Positive sender-deposit leg on deposit-credit postings. No cash is collected here. | Credit posting timestamp |
| `deposits_held` | Negative net sender-deposit balance attributable to applied deposit source orders. Credits/refunds discharge this holding. | Current |
| `deposits_refunded` | Finalized applied posting-deposit refunds; a subset of applied refunds. | Refund `succeeded_at` |
| `boost_funded` | Boost subset of applied funding. Binding/allocation entries add no captured cash. | Capture `succeeded_at` |
| `recognized_revenue` | Negative signed platform-commission entries with evidenced earning outcome, including later corrections. | Later of entry posting and first earning evidence |
| `pending_earnings` | Negative net platform-commission entries without earning evidence. Unbound/refundable Boost held funds are not allocated platform earnings. | Current |
| `traveler_outstanding` | Negative net traveler payable per Deal, summed once per Payout; orphan ledger balances produce reconciliation mismatch. | Current |
| `liability_*` | Exclusive classification of that same payable. See precedence below. | Current |
| `payouts_settled` | Positive payable discharge ledger legs of kind payout, paired with bank-paid allocation or manual paid evidence. Transfers and submissions contribute zero. | Matching bank disbursement `paid_at`, or manual Payout `paid_at` |
| `payout_returns` | Negative payable legs of append-only bank-return corrections. A prior paid flow remains historical. | Return posting timestamp |
| `connected_funds` | Signed net `connect_funds` asset. | Current |
| `bank_in_transit` | Signed net `payout_in_transit` asset; pending and in-transit bank submissions still owe the Traveler. | Current |
| `externally_committed` | Distinct outstanding awards with committed/unknown/accepted/sent attempt or nonzero connected/transit asset. Orthogonal to holds. | Current |
| `source_reserved` | Unreleased immutable funding allocations in the selected mode. A settled source remains consumed/reserved, not free cash. | Current |
| `refunds_requested` | Pending refund rows. | Current |
| `refunds_processing` | Processing refund rows. | Current |
| `refunds_outstanding` | Pending + processing reservation rows, including manual-action cases. | Current |
| `refunds_failed` | Failed execution rows, separately surfaced for entitlement review. | Current |
| `refunds_finalized` | Succeeded refunds, including refunds of unapplied captures. | Refund `succeeded_at` |
| `refunds_applied` | Succeeded refunds of applied captures only; subtracted from funded volume once. | Refund `succeeded_at` |
| `provider_disputes` | Provider disputes in open/review/warning or lost/recovery state. Known canonical amounts only; partial/unknown stays explicit. | Current |
| `provider_disputed_payouts` | Distinct outstanding awards affected by attributable provider disputes. | Current |
| `user_disputed_payouts` | Distinct outstanding awards with active ShipTrip user disputes. Separate from provider disputes. | Current |
| `held_payouts` | Distinct outstanding awards affected by active payout, Deal, account or source-attempt Finance holds. | Current |
| `payout_operations` | Current non-cancelled Payout awards including settled rows; one row per operation-queue obligation, not additional liability. | Current |

For €5 applied deposit + €55 applied balance funding a €60 obligation, gross
funded is €60. Crediting the deposit contributes zero additional funding.
Unapplied duplicate cash, failed/expired attempts and binding/reclassification
entries do not enter gross funded. An orphan succeeded duplicate attempt without
its capture posting cannot inflate the KPI and produces a reconciliation gap.
Refunding an unapplied duplicate does not reduce applied net funded volume.

Boost follows the frozen F1 economics. Gross funded and revenue are different
concepts and are never added together: Boost cash enters funded volume once;
its Traveler share remains payable, while the platform share stays pending
until earning evidence. This backend does not invent extra fee categories.

Earning evidence is the earliest of clean `Deal.completed_at`, an immutable
final-dispute/cancellation/compensation event, or an authoritative settlement
ledger posting. The event path covers final settlements whose allocation delta
was zero. Entries posted later are recognized at their own later posting time,
so a correction cannot retroactively change an earlier period. Allocation
without that evidence is pending, even if payment or Transfer succeeded.
Separate delivery/Boost earned-category figures are unavailable because existing
settlement corrections do not retain those category splits. Total recognized
platform consideration is not claimed to be VAT-exclusive statutory revenue,
profit, or available cash.

## Liability and rail classification

Nonzero payable appears exactly once. Invalid negative payable or nonzero
paid/cancelled balances go to `inconsistent` and remain visible. Otherwise:

1. `disputed`: active user/provider dispute, dispute hold or frozen state.
2. `held`: another active FinanceHold, across every H1 scope.
3. `blocked`: blocked/failed or substantive block reason. Connected-balance
   deferral alone is not treated as a setup block.
4. `sent`, then `processing`: local sent state; committed/unknown/connected/
   bank-pending/manual-processing exposure.
5. `protection`: delivered and stored protection deadline has not elapsed.
6. `pre_delivery`: funded without confirmed delivery or a final settlement award.
7. `scheduled`, then `eligible`: authoritative release exists and there is no
   higher-priority block or external commitment.
8. `awaiting_release`: remaining nonzero payable without authoritative release;
   wall-clock expiry by itself does not fabricate eligibility.

H0 explicitly recognizes pre-delivery Traveler liability at funding, so it
cannot be omitted from the total. Clean contractual completion and actual
Traveler payment are distinct. A failed bank payout restores connected funds
without discharging payable. A late return restores payable and keeps the
historical paid movement. Holding money does not hide its connected/bank location.

`payouts` groups current payable by rail, exclusive bucket and funding mix.
`rail_operations` groups current Payout records by operational state, including
manual waiting/claimed/processing/sent/settled and Stripe commitment/connected/
bank-processing/in-transit/settled/failed-returned. Settled operational rows are
current-state counts, **not** the historical paid-flow metric. Cancelled rows
are excluded from this operational queue. A current settled DZD row shows its
stored canonical EUR and frozen DZD amount; its lifecycle never recalculates FX.

## Reconciliation and completeness

The response's `integrity` contains `ok`, `warning` or `mismatch`, signed
differences and mismatched-row counts. Mismatches take precedence over warnings.
Financial discrepancies do not change healthz/readiness status.

| Relationship | Independent check |
|---|---|
| Traveler state | Current unpaid authorized Payout awards vs negative net ledger payable; compare each Deal so opposing gaps cannot cancel. |
| Dashboard liability | Sum contributing Payout ledger balances vs complete scoped ledger payable; catches orphan payable. |
| Applied funding | Applied succeeded capture amounts vs captured ledger amounts, including per-capture comparisons. |
| Finalized refunds | Successful refund records vs refund/provider-clearing legs, including per-refund comparisons. |
| Paid settlements | Paid bank allocations plus manual paid records vs payable discharge legs; returned allocations retain historical paid evidence. |
| Platform share | All-time evidence-recognized credits + pending allocated credits = total signed platform-share ledger. This is a recognition partition check, not proof that proposed earned-revenue accounts exist. |
| Conservation | Every selected ledger transaction balances across all its legs, including when a rail/provider view selected only part of that transaction. |

Failed refunds are not silently treated as discharged entitlement. Current
reservation logic excludes failed rows, while provider refusals normally retain
pending/manual-action obligations. H5 therefore reports failed rows separately
and warns that their unresolved entitlement requires review. It does not invent
a refund-payable account or add a possibly superseded failed request twice.

Provider balances and provider costs are **unavailable/null**, not zero.
No new external API integration or guessed percentage estimates are introduced.
Provider disputes with unknown canonical amounts return `status=partial`, null
total, known subtotal and count. Legacy/unclassified funding is flagged; it is
not relabeled as an operational source provider.

## Server surface and privacy

`GET /admin/finance/control-plane/?mode=test` returns the snapshot (use the
repository's mounted console prefix if changed). Add `metric=<key>` for its
contributing-row drilldown. `net_funded` drills through its named gross/refund
components. Rail-operation groups drill with `metric=payout_operations`, `rail`
and `operation` matching that group. `page` is 1–100; `page_size` is 1–100, default 50. Results have stable
primary-key ordering, `has_next`, exact totals and a response `as_of`. Narrow
filters rather than requesting unbounded deep offsets. Separate requests can
observe later financial changes; there is no durable snapshot token.

All monetary results are raw integer values: `{count, amount_eur_cents, status}`.
Net cash-flow count is null because subtracting unlike row counts is not useful.
Ledger metrics count contributing entries, payout metrics distinct obligations,
refund metrics refund records; those counts are not interchangeable. DZD rail
groups additionally carry frozen `amount_dzd` and missing-value count.

Access uses the existing fresh `view_finance_summary` capability and active,
non-banned staff boundary: Finance and Super allowed; Support, Ops and Trust
denied. `FINANCE_DASHBOARD_ENABLED=false` hides the endpoint with 404 after
authorization. GET only; unknown/repeated filters are rejected. Responses use
private/no-store cache controls. Database timeout errors are sanitized to 503.

Drilldowns include safe payout/order UUIDs and established ST/TR display
references. Legacy ledger/refund/allocation/dispute tables lack UUIDs and use
staff-only typed row references. No arbitrary notes, provider payloads, bank
account data, CCP/RIP/key, names/emails, cheque/evidence URLs, secrets or handover
codes are serialized. H4 sensitive reveals remain separate audited operations.

## Verification and release record

H5 tests live in `apps/finance/tests/test_phase8fh5_control_plane.py`. They use
real PostgreSQL constraints and standalone snapshot transactions, existing
H3/H4 fixtures, provider-adapter fakes only for lifecycle setup, and a network
guard. No provider API is invoked. No new race tests are needed: the reporting
transaction is read-only. The suite covers economic totals, entry/record
reconciliation, duplicates, refunds, holds, protected/eligible/external/paid/
returned states, frozen DZD, filters, bounded queries and access control.

The consolidated PostgreSQL H5 run passed **20 tests** in 100.62 seconds. The
single warning was the existing Django 6 URLField default-scheme deprecation in
`admin_panel/console_forms.py`. The H5 query plan used `fin_ledger_deal_idx`;
there was no evidence justifying a schema/index change. The final response gate
also checks explicit integer JSON values after PostgreSQL SUM normalization.
No shared accounting writer changed, so the isolated H5/reconciliation tests
are the justified release collection; the 800+ unrelated finance tests were
not rerun. Ruff is checked on all changed Python. Schema/sqlc regeneration and
drift checks are not applicable because no schema/model/migration changed.

Exact SHAs, CI availability and deployment observations are recorded in the
H5 completion report. H5.1 visual polish and H6 mobile work are outside this change.
