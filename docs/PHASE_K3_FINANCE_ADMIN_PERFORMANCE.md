# K3 — Finance & Admin Performance Remediation

Status: **released to Railway TEST**.

K3 started from exact `main` SHA
`e462dc5469955e255378208616b6109987112b4b` on branch
`codex/k3-finance-admin-performance`. The exact implementation independently
verified by Gemini and deployed to TEST is
`fe1e5bffcf09b52a2bf6bfba7bf949114bc8a1bb`. PR #14 merged to `main` at
`80100463edfbf1d03a0f3add32bce433069954bc`.

## Measurement method

Measurements used an isolated local PostgreSQL 16.13 cluster, Django's
in-process test client, K1 query capture, and a deterministic synthetic data
set with 605 users, 125 payouts, 125 DZD payout-profile revisions, 100 complete
manual-DZD lifecycles, 25 pending reviews, disputes, and high-cardinality user
history. Each duration is the median of three warmed requests. DB time is the
sum of Django-reported query durations. The harness recorded the five slowest
SQL statements and normalized duplicate-query groups for every surface.

The data and measurement scripts are local ignored artifacts under
`.codex-temp`; no production or Railway data was read or changed.

Baseline SQL diagnostics were captured before implementation edits:

| Surface | Slowest SQL ms | Slowest SQL shape | Duplicate groups |
| --- | ---: | --- | ---: |
| Finance Overview | 63 | payable `COUNT/SUM` over the universally annotated payout/ledger projection | 10 |
| Payouts Hub | 104 | full payout queue projection including FX, funding, holds, disputes, exposure, and stage annotations | 10 |
| Manual DZD list | 106 | the same full payout queue projection | 10 |
| Manual DZD detail | 1 | payout-event history with actor/evidence joins | 5 |
| Payout Reviews list | 6 | payout-method/revision review queue projection | 2 |
| Payout Review detail | 2 | profile/revision base select; the dominant waste was hundreds of individually small repeated permission queries | 5 |
| Payments | 4 | payment-attempt list projection | 0 |
| Finance reconciliation | 56 | payable `COUNT/SUM` over the comprehensive projection | 10 |
| People list | 5 | User plus four joined `COUNT(DISTINCT ...)` relations | 0 |
| Person detail | 2 | request-state projection | 1 |
| Admin Overview | 3 | pending payout-method count | 1 |
| Disputes list | 34 | dispute base list; unused collections followed as separate prefetches | 0 |

Duplicate groups are normalized SQL shapes, not merely identical literal SQL.
The Finance pages repeated the payable aggregate up to 11 times; payout-review
detail repeated staff, direct-permission, and group-permission lookups once per
candidate reviewer. The post-change JSON retained the same five-slowest and
duplicate-group capture for comparison.

## Before and after

| Surface | Before ms | After ms | Improvement | Before queries | After queries | Before DB ms | After DB ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Finance Overview | 3,861.0 | 604.7 | 84.3% | 88 | 27 | 972 | 123 |
| Payouts Hub | 5,910.4 | 647.9 | 89.0% | 101 | 22 | 1,206 | 115 |
| Manual DZD list | 5,742.0 | 639.5 | 88.9% | 101 | 22 | 1,083 | 112 |
| Manual DZD detail | 41.6 | 38.3 | 8.1% | 34 | 19 | 7 | 12 |
| Payout Reviews list | 44.6 | 41.7 | 6.4% | 14 | 14 | 16 | 15 |
| Payout Review detail | 842.4 | 43.2 | 94.9% | 780 | 24 | 304 | 13 |
| Payments | 43.8 | 44.1 | noise | 6 | 6 | 5 | 5 |
| Finance reconciliation | 3,821.0 | 4,431.7 | run-to-run noise | 86 | 86 | 958 | 1,019 |
| People list | 38.2 | 34.3 | 10.1% | 7 | 6 | 9 | 6 |
| Person detail | 45.0 | 42.5 | 5.5% | 22 | 22 | 9 | 8 |
| Admin Overview | 28.9 | 27.8 | 3.9% | 17 | 16 | 7 | 7 |
| Disputes list | 83.5 | 73.4 | 12.1% | 9 | 7 | 38 | 40 |

Reconciliation's query path is intentionally unchanged. Its final wall-clock
sample varied upward while query count and SQL structure stayed identical; an
earlier post-change median was 3,797.3 ms. K3 makes no performance claim for
that explicit comprehensive operation.

The Finance Overview repeatable-read section was timed separately around the
actual builders: median 3,408.7 ms before and 467.6 ms after, an 86.3%
reduction. It therefore retains an old PostgreSQL snapshot for materially less
time. No autovacuum setting was changed; shortening application transactions
addresses the observed risk directly.

## Confirmed root causes and changes

### Finance operational reads

`build_snapshot(scope)` evaluated every metric, provider split, payout
grouping, attention projection, and reconciliation comparison for pages that
render only a small operational subset. The Overview repeated its largest
payable aggregate 11 times. Payouts Hub and Manual DZD then opened additional
repeatable-read drilldowns after paying for the comprehensive snapshot.

`apps.finance.control_plane.operations.build_operational_snapshot` now builds
only named metrics plus optional rail groups and attention. Finance Overview
asks for its three headline metrics and failed refunds; Payouts Hub and Manual
DZD ask only for rail-operation groups. The full `build_snapshot` and
`reconcile` implementations remain intact and exclusive to the explicit
Reconciliation surface.

Each operational page retains one short `REPEATABLE READ, READ ONLY`
transaction. Counts and the initial queue rows share its `Queries` instance,
timestamp, and database snapshot. Stage and DZD rail refinements are applied to
the already-annotated projection. Queue drilldowns omit an unused totals query
and unused bucket/funding/FX/exposure columns. A non-shared public drilldown
continues to open its own strong snapshot and return its full contract.

The Overview no longer claims a reconciliation verdict it did not compute. It
links explicitly to Full accounting detail; only Reconciliation publishes the
integrity verdict and evidence. Headline amounts, rail/cohort counts, blocker
classification, EUR/DZD values, and provider-mode distinctions are parity
tested against the comprehensive snapshot.

### Payout attention

The previous bounded implementation reloaded the full related payout graph and
recomputed shared dispute/hold facts once per 200 payouts. K3 keeps the
authoritative `payout_attention` classifier but loads its bounded graph once
and builds one request-scoped `page_context` through the existing 5,000-row
safety limit. Query count is now constant across the former batch boundary.

A second SQL implementation of the blocker hierarchy was rejected. The
classifier depends on approved profile/attestation history, account readiness,
supersession, bank state, disputes, holds, and immutable instruction snapshots;
duplicating those predicates would create financial-safety drift. The selected
batched read removes repetition without caching or changing the central rule.

### Manual DZD detail

The detail route now loads one request-scoped presentation graph for payout,
traveler, Deal, active instruction/profile/evidence, reviews and identity
attestations, attempts, events, amendments, active disputes, and balance
orders. Presentation helpers consume prefetched collections. Holds and receipts
retain their authoritative scoped queries, and evidence bytes remain behind
the existing permission-checked read service. No decrypted destination is
prefetched or cached. Mutating services still reload and lock their own rows;
redirects follow successful writes and any same-response error/reveal render
rebuilds the read graph.

### Payout reviews and object storage

`reviewer_choices()` previously called a fresh permission lookup for every
staff user: 780 queries with the measured staff population. It now selects
active, unbanned staff who are superusers or hold the direct/group capability
in one request-scoped SQL query. It does not populate or reuse Django's
permission cache, so ban, deactivation, downgrade, and direct-permission
changes remain effective on the next request. A scaling test proves detail
query count is unchanged after adding 24 eligible reviewers.

The list/detail path was inspected for repeated S3 reachability calls. It reads
stored evidence metadata and uses the existing secured evidence endpoint; it
does not perform duplicate synchronous `HEAD` calls. Request-scope S3
deduplication was therefore not applicable and no Redis/object-store cache was
introduced.

### People, Person detail, Admin Overview, and disputes

People previously joined requests, journeys, sender Deals, and traveler Deals
into one relation and repaired multiplicity with four
`COUNT(DISTINCT ...)` aggregates. K3 replaces these joins with independent
correlated count subqueries and reads only the latest KYC status through a
scalar subquery. Counts remain correct for one account with both
high-cardinality request and journey histories, query count stays flat, and
the main user query contains no activity-table joins.

Person detail was already paginated and query-bounded (22 queries before and
after); no new aggregate system was justified. Admin Overview now computes
provider-health rows once and reuses them for warnings and rendering, removing
one duplicate query. Disputes list no longer prefetches events and Deal payment
orders that it does not render; detail explicitly retains those relationships.

## PostgreSQL plans and index decision

Safe `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` was run against the local
dataset.

| Path | Before planning / execution | After planning / execution | Evidence |
| --- | ---: | ---: | --- |
| People first 20 | 33.219 / 4.381 ms | 4.986 / 1.834 ms | Removed four outer joins and the multi-relation aggregate; page-bounded scalar subqueries use existing FK indexes where selective. |
| Manual payout queue projection | 161.652 / 8.746 ms | 53.556 / 7.118 ms | Removed unused projected annotations; the measured narrow stage returned no rows but still demonstrates lower planner and executor work over the same 125-payout population. |

No index migration was added. Measurements did not justify the write/storage
cost of a new index:

- Ledger payable queries already use `fin_ledger_deal_idx (deal_id, account)`,
  the exact hot correlation. Candidate `(attempt_id, account)`, `(refund_id,
  account)`, and `(payout_id, account)` indexes were not used by the measured
  operational bottleneck.
- Ledger transaction `(provider_mode, kind)` belongs to unchanged deep
  reconciliation; the 250-row measured table was not a post-fix hotspot.
- Holds had no measured rows and already have FK indexes plus
  `(payout_id, cleared_at)`. There was no plan evidence for the three additional
  active-scope compound indexes.
- Provider disputes had no measured rows; its existing identity index served
  the observed plan. `(provider_mode, status)` had no demonstrated benefit.
- Profile reviews had 100 rows and an existing `profile_id` index. The 756-query
  reduction came from permission N+1 removal, not review lookup ordering.
- Payout operational grouping reads most of the 125-row mode cohort and derives
  state from authoritative annotations. A partial active index was not
  selective enough in the measured plan and would not remove that reasoning.
- People search was 38.2 ms end to end at 605 users. `pg_trgm` remains deferred.

The remaining payout plan is complex because it centralizes financial and
safety predicates. K3 reduces how often and how broadly it is evaluated rather
than copying predicates or hiding it behind a cache. Gemini should repeat plans
with 1,000 payouts and flag any scale-specific index that becomes demonstrably
selective.

## Query budgets and parity

The K3 PostgreSQL tests use ceilings rather than brittle exact values:

| Surface | Query ceiling |
| --- | ---: |
| Finance Overview | 35 |
| Payouts Hub | 30 |
| Manual DZD list | 30 |
| Manual DZD detail | 28 |
| Payout Reviews list | 16 |
| Payout Review detail | 32 |
| Payments | 10 |
| Reconciliation | 95 |
| People | 8 |
| Person detail | 30 |
| Admin Overview | 22 |
| Disputes | 10 |

Parity tests compare operational headline metric dictionaries, rail-operation
groups, payout-attention output, and definition version with one comprehensive
snapshot over the same PostgreSQL state. They also assert that the deep
integrity comparisons, definitions, and provider decomposition remain present
on the comprehensive path. Existing manual-DZD workflow and reconciliation
tests retain lifecycle, evidence, redirect, integrity, and mismatch behavior.

## Codex verification boundary

The final short gate passed 12 tests: six K3 parity/query/scaling/permission
tests, four K2 manual-DZD continuity tests, and two Finance
rendering/integrity tests, plus the parameterized cases collected by those
targets. Ruff, Python compilation, Django system check, and the no-migration
check passed. An earlier affected-file regression run reported 92 passes and
one now-updated stale Overview-health expectation; it was not a full suite and
is not presented as the release gate.

There are no model changes, migrations, schema/sqlc changes, Go changes,
Flutter changes, caching changes, or provider calls. Financial calculations,
ledger semantics, EUR canonical amounts, FX snapshots, payout eligibility,
instructions/state machine, dispute economics, KYC rules, transaction locks,
auditing, Admin capabilities, and Stripe/Chargily modes are unchanged.

The full Django PostgreSQL suite, broad Finance/Admin/payment/dispute groups,
large 100/500-user and 100/1,000-payout scale verification, schema drift,
production/static checks, CI, and deployment were intentionally handed off to
Gemini/CI under the K3 test budget. Their results are recorded below.

## Independent verification, CI, and merge

Gemini's initial pass on exact `a56e455` returned RED solely because three
H5.2 tests still asserted the pre-K3 implicit-Overview-reconciliation behavior.
It independently confirmed financial parity, authorization, transaction
consistency, all 12 query budgets, the measured performance gains, plan/index
conclusions, and the application architecture. The test-only follow-up aligned
those assertions with the approved design. Gemini re-verification returned
**GREEN** on exact SHA `fe1e5bffcf09b52a2bf6bfba7bf949114bc8a1bb`:
the H5.2 suite passed 11 tests, the K3 suite passed 6, Ruff passed, all three
previous failures were resolved, and application behavior remained unchanged.

[PR #14 CI](https://github.com/is-bo/shiptripis/actions/runs/35627721395)
passed all six required jobs on final branch head `a460dd5`:

- Django PostgreSQL: 2,293 passed, 34 skipped; Ruff clean; no missing
  migrations.
- Production configuration: 46 tests passed; static/edge and native Caddy
  checks passed.
- Flutter: 974 tests passed; analyzer clean; 188 files correctly formatted.
- Go build, vet, unit/race, and real-Redis integration passed; the integration
  tier reported 287 executed tests and zero skips.
- Schema drift passed with no drift.

[PR #14](https://github.com/is-bo/shiptripis/pull/14) merged at
`80100463edfbf1d03a0f3add32bce433069954bc`. The commit after the exact Gemini
SHA contains only the two release documents; the deployed application tree is
the exact reviewed tree.

## Railway TEST release and telemetry

A clean 1,166-file `git archive` of exact SHA
`fe1e5bffcf09b52a2bf6bfba7bf949114bc8a1bb` was uploaded to the existing
ShipTrip TEST service as `v1.0.0-rc.48+fe1e5bf`. Deployment
`bfa3336f-e0ce-42d2-90b9-a8f2fb42fbc1` reached **SUCCESS** with image digest
`sha256:7981da428d5632b08f755729b7106b3db64bee32c3a1e3b2b2891439050a0684`.
SHA-256 hashes for the five central K3 runtime files matched between the exact
archive and the running container. Startup reported no migrations to apply,
all required child services ready, and the bundled geography catalogue already
current.

Public checks returned:

- `/healthz`: HTTP 200, release `v1.0.0-rc.48+fe1e5bf`.
- `/readyz`: HTTP 200; database, migrations, and rate-limit cache all `ok`.
- Railway HTTP metrics over the deployment window: 10 requests, zero errors,
  p50/p95 56 ms. There were no HTTP 5xx responses. One early `/healthz`
  request took 565 ms and still returned 200.
- Railway resource snapshot: 543.5 MB average / 592.0 MB maximum memory from a
  1,024 MB limit; maximum CPU 0.382 vCPU from a 2-vCPU limit.

The read-only authenticated smoke used the running container and deployed
PostgreSQL state. Each result is a median of three warmed Django requests with
query capture; these deployed-data timings are acceptance evidence rather than
a replacement for the controlled local before/after data above.

| TEST surface | Median ms | Queries | Result |
| --- | ---: | ---: | --- |
| Admin Overview | 22.2 | 13 | 200 |
| Finance Overview | 420.0 | 23 | 200 |
| Payouts Hub | 784.7 | 29 | 200 |
| Manual DZD | 577.4 | 17 | 200 |
| Payout Reviews | 22.1 | 4 | 200 |
| Payout Review detail | 49.2 | 21 | 200 |
| Payments | 25.7 | 3 | 200 |
| People | 23.9 | 3 | 200 |
| Person detail | 36.4 | 13 | 200 |
| Disputes | 9.4 | 2 | 200 |

All deployed query counts remain beneath the K3 ceilings. An unauthenticated
Finance request redirected to Admin login, and an active restricted staff
account received HTTP 403 on Payout Reviews. No financial POST or provider
operation was performed. Stripe and Chargily remain TEST, mock payments and
DZD payout execution remain off, and EUR/ledger/FX/payout/dispute behavior is
unchanged. The FCM stream has one consumer with zero pending and zero lag;
both transport streams contain zero entries. Embedded Redis remains the
documented K1 TEST exception.

The merged application branch was deleted locally and remotely after TEST
verification. No migration or index was added. The remaining performance work
is limited to monitoring the deliberately comprehensive reconciliation path
and re-evaluating plan-driven indexes only if larger real data makes one
selective. K3 requires no Redis snapshot cache, materialized view, CQRS, read
replica, or sharding.
