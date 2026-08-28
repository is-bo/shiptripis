# ADR 0002 — V1 core domain and staged legacy migration

- Status: Accepted for Phase 1
- Date: 2026-08-24
- Authority: `docs/SHIPTRIP_V1_SPEC.md`

## Context

The current schema is a functioning legacy delivery/product marketplace: routes are airport-to-airport `Trip` rows, parcel and offer economics are DZD, `ProductRequest` is public, a traveler may create the first offer, `Match` also acts as fulfillment state, and `PaymentIntent` is one-to-one with an accepted Offer. Existing IATA foreign keys, DZD amounts, payment/ledger rows, and ProductRequest history cannot be reinterpreted or deleted.

Phase 1 therefore uses an expand/backfill/switch strategy. Legacy tables and columns remain explicit compatibility records; all new V1 records use the structures below. Contract/removal migrations are deferred until production data has been reconciled and every dependent client has moved.

## Decisions

### Location

`locations.Location` is an immutable place record with a typed kind, normalized/public/private labels, city, region, ISO country code, exact and optional coarse coordinates, provider metadata, precision, and an optional protected Airport link. Coordinates use fixed-precision decimal fields with paired/range constraints.

Public serializers expose only the coarse label and coarse coordinates. Exact labels, provider IDs, metadata, and exact coordinates are returned only to the location owner or to the sender/traveler of a funded Deal. Django owns this authorization decision; notification and Go relay payloads must never contain private location fields.

### Journey, JourneyLeg, and flight proof

`trips.Journey` is the new traveler aggregate. It owns ordered `JourneyLeg` rows and may point one-to-one to a legacy `Trip` for audit/compatibility. A leg has a unique `(journey, position)`, mode `FLIGHT` or `DRIVE`, origin/destination Locations, departure/arrival times, decimal kg capacity, and route metadata.

`JourneyLegProof` is separate from KYC. It reuses private object-storage references and review conventions, but a proof belongs to one flight leg and records review status, reviewer, reviewed time, and rejection reason. A journey may be published only when traveler KYC is currently approved and every flight leg has approved proof. Drive legs require no transport proof.

Legacy Airports remain IATA-primary-keyed. They do not contain trusted coordinates, while V1 Locations require exact coordinates. The compatibility backfill is therefore gated on importing a versioned, reviewed airport-coordinate dataset; coordinates must never be fabricated or defaulted to `0,0`. Once that prerequisite exists, a reversible data migration may create deterministic airport Locations and convert each legacy Trip into a compatibility Journey. Ordered stopovers become ordered flight legs. Missing arrival times stay null and proof approval is never invented; formerly active legacy Trips import as `pending_verification` and are not matchable until the V1 gates pass. Until then, `Journey.legacy_trip` is the protected bridge and legacy Trip rows remain history-only.

### DeliveryRequest migration and ProductRequest retirement

`DeliveryRequest` is extended additively with `schema_version=2`, pickup/delivery Locations, ready window, deadline, decimal actual weight, dimensions, declared value in EUR cents, title/category, handling notes, and explicit safety/customs declarations. Existing Airport FKs, integer weight, and DZD price remain nullable legacy fields. Legacy delivery rows are linked to airport Locations and retain their DZD economics; missing addresses, dimensions, declared values, and FX are not fabricated.

`ProductRequest` and its parent/media/history rows remain intact. Public creation, detail, mutation, matching, payment, handover, and chat paths return `410 Gone`; active public feeds exclude product rows; and parent/media admin access is read-only. No table or historical row is dropped in Phase 1.

### EUR money and versioned business settings

New V1 marketplace amounts are integer EUR cents and percentage rates are integer basis points. Legacy DZD columns are not renamed, converted, or reused as EUR.

`core.BusinessSettingsVersion` is an append-only revision with a unique version, lifecycle state, canonical currency, commission basis points, pricing version, and JSON policy values. Services may activate a revision but never mutate an active revision. Offers reference the revision and copy the relevant economic inputs; Deals copy them again into immutable terms.

Legacy Offers are marked `legacy_dzd`. New Offers are `v1_eur` and must use EUR, with traveler reward, commission basis points, platform fee, sender total, pricing version, and a terms JSON snapshot. Database checks require internally consistent sums and prevent new nonlegacy DZD economics.

### Sender-first offers

The sender creates every new V1 initial Offer. The traveler may accept, decline, or counter; the sender may counter back. Only the non-proposer may act on a pending offer, and only its proposer may withdraw it. There is one pending offer in a chain and one accepted offer per Match.

The traveler-first endpoint is retired for V1 and returns `410 Gone`. Existing offer rows retain their original proposer and DZD values. Countering no longer depends on the legacy `target_traveler` broadcast distinction.

### Deal, immutable terms, and timeline

`deals.Deal` is a first-class aggregate created once from an accepted V1 Offer and linked to the delivery request, Journey, sender, and traveler. Phase 1 defines the lifecycle statuses needed by later phases but implements only offer acceptance/payment-required foundations. Legacy `Match`, `PaymentIntent`, wallet, and handover records remain untouched.

`DealTermsSnapshot` is one-to-one with Deal and copies the accepted reward, fee, sender total, currency, commission basis points, settings version, pricing version, and policy JSON. A database constraint allows DZD only for explicitly legacy snapshots. `DealEvent` is append-only and records critical structural transitions.

### Segment capacity

`DealLegAllocation` is the capacity reservation record. It stores positive decimal kg on one JourneyLeg, is unique per `(deal, journey_leg)`, and has reservation states suitable for later payment/fulfillment transitions. Active allocation queries are indexed by `(journey_leg, status)`.

Offer acceptance is one Django transaction. It locks the delivery request,
every Match for that request in primary-key order, the target Offer, and every
covered JourneyLeg in deterministic position/ID order; recomputes active
allocation totals; verifies capacity on every leg; creates Deal, terms, event,
and allocations; then accepts the Offer and expires competing state. Redis is
never capacity authority. The service is idempotent for a previously accepted
Offer/Deal, after object-level authorization is rechecked.

## API and compatibility consequences

- New `/api/locations` and `/api/journeys` contracts replace airport-only creation for V1.
- `/api/trips*` and Airport endpoints remain temporary legacy reads; new Trip creation is retired.
- Delivery creation accepts V1 Location/timing/parcel/safety fields and EUR-cent reward inputs; DZD fields are legacy-output-only.
- `/api/parcels/product` and `/api/matches/apply` return `410 Gone`.
- Match/Offer responses gain explicit economics version, currency, EUR amounts, Journey, Deal, and covered-leg identifiers.
- Accepted V1 offers return the created Deal and allocations. Payment remains a later-phase Deal-bound contract; the old Offer-bound PaymentIntent path is legacy-only.
- Flutter must treat these as versioned breaking changes; it must not infer funding from offer acceptance or parse Journey responses as flat Trips.

## Migration, rollout, and recovery

1. Expand with nullable/additive tables and columns.
2. Import a reviewed airport-coordinate dataset, then backfill airport Locations and legacy Journey/leg compatibility records without changing source rows. This step is blocked while coordinates are unavailable.
3. Backfill legacy delivery Location links and mark DZD economics explicitly legacy.
4. Deploy readers that understand both schemas.
5. Switch new writes to V1 EUR/Location/Journey/Deal services and disable retired public writes.
6. Regenerate `schema.sql`; run sqlc/gRPC generators and schema-drift checks.
7. Reconcile production row counts, active legacy fulfillment, suspicious EUR-labelled legacy payments, and plaintext code notifications before any future contract migration.

Rollback before the write switch removes only generated compatibility rows and additive schema. After V1 writes exist, rollback is application rollback to dual-read compatibility; V1 tables are retained until data is exported/reconciled. No Phase 1 rollback converts money, deletes ProductRequest, or removes Airport/Trip tables.

## Deferred work

Phase 1 does not implement geospatial ranking, detour routing, pricing recommendations, real providers, PaymentOrder/PaymentAttempt, posting deposits, payouts, disputes, 30-minute delivery-code release, 48-hour protection, ratings, boost, final admin/mobile UI, or the landing site. The new foundations must not call the unsafe legacy mock-payment or immediate-handover path.
