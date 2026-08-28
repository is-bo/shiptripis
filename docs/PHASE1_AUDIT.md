# ShipTrip V1 Phase 1A audit

Date: 2026-08-24  
Authority: `docs/SHIPTRIP_V1_SPEC.md`

## Scope and evidence

The audit traced the Django domain and APIs, migrations, payment/verification
state transitions, Redis publication, Go services and contracts, Flutter
repositories/screens, CI schema-drift workflow, Railway configuration, and the
deployed Railway service topology. A generated code graph is available in
`graphify-out/` for future relationship queries.

The pre-change Django baseline was 226 passing tests and two failures caused by
tests calling a disabled mock webhook without enabling it. Go, Flutter,
PostgreSQL client, and sqlc tools were initially absent from the workstation.

## Highest-risk findings

| Severity | Finding | V1 consequence |
|---|---|---|
| Critical | Pickup and delivery codes are published to both parties and may be persisted in notification payloads. Delivery code is not delayed. | New Deals must not enter the legacy handover path. Phase 2 must make the sender authoritative for the pickup code, keep the delivery code unavailable to the traveler, and implement durable 30-minute release. |
| Critical | The legacy payment provider is mock-backed and successful delivery can make payout immediately available. | New Deal payments remain `payment_required`; no production mock fallback, payout, or handover integration is introduced in Phase 1. Phase 2 must bind real provider attempts to Deals and enforce the 48-hour protection window. |
| Critical | Legacy pricing and Offers are DZD-centric, while some payment paths can label those integer amounts EUR without conversion. | Legacy rows are explicitly `legacy_dzd`. New Offers and Deal terms use integer EUR cents only, reference versioned settings, and never reinterpret old amounts. |
| High | Legacy Trips can be active without current KYC or approved flight proof. | Only V1 Journey publication creates a matchable Journey; it requires current KYC and approved proof for every FLIGHT leg. DRIVE needs no transport proof. |
| High | Capacity was a Trip-level number without transactional reservation. | Acceptance locks every covered JourneyLeg and creates per-leg allocations atomically after recomputing active reservations. |
| High | Partial refunds reverse the entire legacy wallet hold. | The legacy payment/wallet path is not reused for Deals. Refund/ledger correction is deferred to the Phase 2 Deal payment design. |
| High | ProductRequest is publicly creatable/searchable and has inconsistent payout semantics. | ProductRequest creation and business-flow mutation return 410; history is preserved for read-only admin/audit access only. |
| High | Redis is used as ephemeral event transport; production startup can use a process-local Redis and the current outbox is detection-only. | Redis is never capacity or money authority. Durable critical jobs/outbox recovery remains a release blocker for the later payment/handover phases. |
| Medium | sqlc declares four packages but all query directories are empty; Go services use raw pgx for their small database boundary. | `schema.sql` remains canonical and is regenerated. sqlc generation is intentionally a loud no-op until a Go service receives a real owned query; Phase 1 does not duplicate Django marketplace logic in Go. |
| High | Flutter models and flows assume airport Trips, DZD, traveler-first application, ProductRequest, Offer-bound payment, and immediate handover/payout. | The client is not migrated piecemeal. `docs/PHASE1_API_CHANGES.md` is the breaking-contract handoff for the later full redesign. |

## Existing systems preserved

- Account authentication, JWT claims, KYC submissions, object-storage helpers,
  Redis channel conventions, admin site, Go authentication/config/health
  packages, and Railway service definitions remain useful foundations.
- Airport, Trip, ProductRequest, legacy Match/Offer, PaymentIntent, wallet,
  verification, and notification rows remain intact for audit/history.
- Django remains migration and marketplace state authority. Go remains the
  boundary for existing relay/integration services; no business state machine
  is copied into Go.

## Migration and production constraints

- Phase 1 uses additive tables/nullable columns, explicit legacy markers, and
  public write switches. It contains no money conversion or destructive
  contract migration.
- Airport rows have no trusted latitude/longitude. Because V1 Location exact
  coordinates are required, a legacy Trip/Journey backfill would have to invent
  data. It is intentionally blocked until a versioned, reviewed airport
  coordinate source is imported. `Journey.legacy_trip` preserves the bridge.
- Production Railway topology was inspected read-only and deployments were
  healthy. Direct production row-count reconciliation was not possible because
  this workstation has no registered Railway SSH key. No key was registered and
  no production data or infrastructure was mutated.
- The Phase 1 migrations were exercised forward, one revision backward, and
  forward again on an isolated PostgreSQL 16 database. Production rehearsal
  still requires row counts and a maintenance-window decision: the regular
  index creation and validated checks in `parcels.0003` can take locks on a
  large live parcel table.
- Before any future contract/drop migration, reconcile legacy row counts,
  active fulfillments, suspicious EUR-labelled legacy payment rows, Product
  history, and plaintext verification/notification payloads.

## Phase 1 verification outcome

- Independent security/API, database/concurrency, and contract/regression
  reviews were completed. Their valid findings were fixed: V1 Deals cannot
  enter legacy mock payment, handover, wallet, or chat flows; Product rows and
  media are admin-read-only; exact location/proof metadata is protected;
  acceptance/counter locks have one deterministic order; and list/query hot
  paths avoid the identified N+1 queries.
- Django fast suite: Ruff, system check, migration-state check, and 252 tests
  pass; 37 PostgreSQL/convention-dependent tests skip as designed on SQLite.
- PostgreSQL 16: 131 focused tests pass, including migration preservation and
  rollback plus three real row-lock races (overcapacity, competing Matches,
  and accept-versus-counter). The latest migrations also passed a manual
  forward/rollback/reapply cycle.
- `backend/contracts/sql/schema.sql` was regenerated from PostgreSQL. A second
  export is identical after normalizing only `pg_dump`'s random
  `\\restrict`/`\\unrestrict` token. sqlc is a loud no-op because every query
  directory is empty and the Go services still use raw `pgxpool`.
- Go: `gofmt`, build, vet, and all service/shared-package unit tests pass. The
  configured `-race` command was attempted but cannot run on this Windows host
  without CGO/GCC; Linux CI remains the authoritative race gate.
- Flutter 3.47.1: format enforcement, `analyze --fatal-infos`, and all 16 tests
  pass. The legacy UI remains intentionally scheduled for redesign.

## Performance and index review

- Deal and Match list serializers use `select_related`/`Prefetch`; regression
  tests cap representative list serialization at four queries.
- Capacity reads use the `(journey_leg, status)` allocation index and lock
  covered legs in deterministic order. Public search filters have status,
  route/location, time, and capacity indexes appropriate for the Phase 1
  foundation.
- Collection endpoints are capped or paginated to avoid unbounded reads.
- Full geospatial compatibility, detour scoring, PostGIS, and ranking are
  intentionally absent until Phase 2+ matching work.
