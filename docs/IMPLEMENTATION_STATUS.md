# ShipTrip V1 Implementation Status

Current phase: Phase 5 **PAUSED / IN PROGRESS**; Phase 6A engineering foundations **IMPLEMENTED / EXTERNAL ACTIVATION PENDING**
Overall status: Phase 1–4 backend lifecycle work remains complete and the V1 delivery lifecycle runs end to end. Money is
server-authoritative and double-entry ledgered, every cross-domain transition
follows one global lock order, the traveler can never read a delivery code, the
delivery code stays sealed for 30 minutes after pickup, payout waits 48 hours
and is frozen by any active dispute, and every delayed obligation is a
PostgreSQL row rather than a timer. The unfinished Phase 5 Flutter rebuild is
preserved at commit `58e79f9` and remains paused; it is not complete and Phase
6A does not modify it.

## Completed

- V1 product specification installed
- Codex rules installed
- Claude rules installed
- Phase 1A multi-perspective audit completed (`docs/PHASE1_AUDIT.md`)
- Core-domain/migration ADR accepted (`docs/decisions/0002-v1-core-domain-and-migration.md`)
- Immutable Location model/API with public/coarse privacy boundary
- Journey, ordered FLIGHT/DRIVE legs, private flight proof, KYC/proof publication gates, and active Journey search
- DeliveryRequest V1 Location/timing/decimal parcel/EUR/safety contract
- ProductRequest and legacy Trip/DZD/traveler-first public writes retired with history preserved read-only
- Versioned business settings and server-authoritative EUR-cent Offer economics
- Sender-first Offer/counter/accept services with immutable economic snapshots
- Deal, DealTermsSnapshot, DealEvent, and transactional per-segment capacity allocations
- Breaking API/Flutter contract handoff (`docs/PHASE1_API_CHANGES.md`)
- PostgreSQL schema regenerated with normalized drift clean
- Independent security/API, database/concurrency, and contract/regression reviews completed and valid findings fixed
- Current Phase 2 verification: SQLite 303 passed/39 skipped and PostgreSQL 308
  passed/34 skipped; Django checks, migration drift, Ruff, and schema repeat-dump
  stability pass
- Go build, vet, and unit tests pass; the race gate remains assigned to Linux CI
- Provider-neutral routing/geocoding contract with validated/cache-namespaced
  results, bounded external calls, deterministic fakes, status API, and explicit
  unavailable/spatial-fallback behavior
- Trusted airport-coordinate provenance and transactional reviewed-CSV import;
  no fabricated legacy coordinate backfill
- Ordered multi-leg FLIGHT/DRIVE sub-route matching, alternate-anchor search,
  covered-leg proof/trust gates, DRIVE detour distance/time, carried-subroute
  distance, and internal rejection explanations
- Versioned Phase 2 pricing: chargeable/volumetric weight, distance bands,
  global floor, minimum/recommended reward, urgency/detour adjustments, EUR-cent
  commission, and immutable Offer/Deal/Match snapshots
- Deterministic post-compatibility ranking with a sender-request boost hook only;
  no paid boost product
- Capacity-safe acceptance revalidated under PostgreSQL row locks, including
  per-segment allocation, concurrent last-capacity rejection, and no partial
  Deal/Offer/allocation state
- Route-provider calls complete before negotiation row locks; locked
  revalidation uses frozen preflight outcomes and fails closed on changed route
  inputs
- Acceptance serializes KYC, Journey-wide approved flight-proof, and account
  eligibility witnesses through Deal commit; PostgreSQL revocation-race tests
  cover both KYC and proof rows
- Database-backed pending-payment reservation expiry, idempotent release,
  pre-funding Deal cancellation, safe Journey cancellation, and audit events
- Phase 2 discovery/quote/explanation/API handoff and operational notes
  (`docs/PHASE2_MATCHING_PRICING.md`)
- Phase 2 migrations applied and reverse/forward rehearsed on PostgreSQL 16;
  SQL schema contract regenerated with normalized repeat-dump stability
- Discovery query-count/performance regressions pass at 24 candidates (three
  queries per direction, zero exact-node route calls, bounded cached misses),
  with PostgreSQL p50/p95 and index plans recorded in the Phase 2 handoff

### Phase 2B review fixes

- Public/internal split for every matching representation
  (`apps/matching/public_contract.py`). The internal compatibility, pricing,
  ranking and policy snapshots stay persisted for audit and admin, and are no
  longer serialized to a party
- Pre-funding exact-location reconstruction closed: route positions, exact
  detour metres, partial routed components, interpolated pickup/delivery
  instants, per-leg capacity and ranking factors are removed from every
  counterparty payload and replaced with detour/distance bands, a covered-leg
  summary and leg-schedule windows
- Adversarial privacy regression that runs the actual inference attack from an
  off-corridor pickup, with the internal admin payload as a control that must
  still be solvable
- `POST /matches/quote` is a narrow sender contract; the internal explanation
  stays behind `IsAdminUser` on `GET /matches/explain`
- Structured domain failure contract: distinct machine codes for
  journey/request/offer/match state, `rejection_codes`,
  `minimum_reward_eur_cents`, `journey_leg_ids`; an unmapped exception is
  `internal_error`/500 instead of a mislabelled business-settings outage
- Server-declared `awaiting_party` / `awaiting_user_id` / `allowed_actions` per
  caller on every Offer representation, with mutations still authoritative
- Discovery candidates carry `start_leg_id`, `end_leg_id` and a safe covered-leg
  summary at zero additional queries per candidate
- Offer/Deal terms serialize the agreed economics only; ranking weights, boost
  parameters, detour limits and scan caps stay internal
- V1 EUR offers no longer serialize legacy DZD economics; legacy offers and the
  database are unchanged
- Journey legs publish a distance band to non-owners instead of the exact routed
  distance and duration (found while auditing, same defect class)
- `/api/parcels/open` rejects retired IATA filters with 400 instead of returning
  a silently impossible empty V1 result
- `DeliveryRequest.traveler_reward_eur_cents` is documented and exposed as
  `sender_proposed_reward_eur_cents`: sender intent, never an agreed price
- Decline and withdraw both terminate a Match as `CANCELLED`; `EXPIRED` is
  reserved for system-driven endings
- Phase 2B verification: SQLite 339 passed/39 skipped and PostgreSQL 344
  passed/34 skipped; Django checks, migration drift, Ruff, schema contract
  stability, Go build/vet/test, and Flutter format/analyze/test all pass

### Phase 2C — remaining Phase 2B minors closed

- Decline and withdraw speak the same structured V1 domain-error contract as
  propose/counter/accept: `not_authorized`, `offer_not_pending`,
  `match_not_pending`, `product_request_retired`, each with the offending
  status as a structured field. No V1 negotiation failure returns prose only
- Location privacy can no longer be reduced by a commercial settings change.
  `PUBLIC_DISTANCE_BAND_MAXIMA` is the privacy ladder, the published band labels
  are derived from it, and a settings revision whose pricing distance bands
  subdivide one of those buckets is refused at activation and again on every
  read (`pricing_bands_reduce_location_privacy`). The published
  `distance_band_base_cents` therefore cannot resolve a carried distance more
  finely than `matched_distance_band` admits
- `covered_legs` is a key-level allowlist in both directions: the internal
  builder and the public projection are both driven by
  `PUBLIC_LEG_SUMMARY_FIELDS` / `PUBLIC_LOCATION_SUMMARY_FIELDS`, so a field
  added to the internal leg summary is invisible to a counterparty by default,
  including inside a snapshot persisted by an older build

## Phase 3 — payments, posting deposit, providers, payouts

Full engineering detail in `docs/PHASE3_PAYMENTS.md`.

- `PaymentOrder` (canonical EUR obligation) / `PaymentAttempt` (one provider
  attempt) replace the legacy one-PaymentIntent-per-Offer model. Legacy
  `apps.payments` rows stay untouched, keep serving legacy flows, and remain
  firewalled from V1 Deals; no legacy DZD payment is reinterpreted as EUR
- Money is integer EUR cents with no floating point anywhere. FX is stored at
  micro precision and snapshotted onto the attempt that used it
- Order money and status are **recomputed** from the order's own attempts and
  refunds rather than incremented, so a replayed event converges instead of
  double-counting. Over-collection, over-refund, double deposit credit, and a
  released payout without eligibility are all refused by database constraints,
  not only by application code
- Posting-deposit mode: `clamp(10% of the recommended sender total, EUR 3,
  EUR 7)`, server-calculated, snapshotted. A request is created
  `awaiting_deposit` and becomes discoverable only when a reconciled payment
  says so; the expiry refund is armed in the same transaction as publication
- The deposit is credited into the accepted Deal's balance, never charged twice,
  and is returned on unmatched expiry, on sender cancellation before an accepted
  offer, and — after a defect found in review — when an accepted Deal expires
  unfunded
- Stripe: EUR checkout against the documented REST contract, manual
  `Stripe-Signature` verification, `Idempotency-Key` on every mutation,
  third-party guest payer, and a payout-capability lookup that never infers a
  capability from a country
- Chargily: DZD settlement of a canonical EUR obligation at an immutable
  snapshotted rate, with separate switches for "disabled" and "no new
  checkouts". It has no refund API, so its refunds are operator-settled through
  an audited admin route rather than faked
- Guest payer: `secrets.token_urlsafe(32)`, hash-only storage, single use,
  expiring, revocable, uniform 404 on every rejection, and a payload containing
  amount, currency, a generic description and an expiry — no party, parcel, deal
  or identifier of any kind
- Append-only double-entry ledger with five accounts and six recorded facts.
  Every transaction sums to zero; corrections are new linked transactions and
  history is never rewritten
- `ScheduledJob` is the durable obligation store for delayed financial work,
  claimed with `FOR UPDATE SKIP LOCKED`, retried with backoff, and requeued
  after a worker death. Redis is never the record
- Payout architecture exists and cannot release: Phase 3 has no code path out of
  `not_eligible`, and `fin_payout_release_requires_eligibility` makes that
  structural. Manual settlement records actor, reference, currency, amount and
  rate, and is refused until Phase 4 releases the payout
- MOCK cannot function as a production rail: the registry refuses to construct
  it without an explicit deployment opt-in, production refuses to boot with that
  opt-in set, and nothing anywhere falls back to it from a misconfigured real
  provider
- Independent security and finance-state reviews run; both valid findings fixed
  with regression tests (trapped deposit credit, unreachable manual refund
  settlement), plus four defects found by our own verification: a Decimal
  ceiling-division bug in FX conversion, a PostgreSQL `FOR UPDATE` outer-join
  failure, a lock-order deadlock between refund and reconciliation, and
  `payment.captured` being published for failed attempts
- Phase 3 verification: SQLite 596 passed/53 skipped; PostgreSQL 615 passed/34
  skipped including 14 financial concurrency tests; migrations rehearsed forward
  and reverse on PostgreSQL 16; schema contract regenerated with repeat-dump
  stability; Ruff, Django checks and migration drift clean; Go build/vet/test
  clean; Flutter format/analyze/test clean

## Phase 3B — financial correctness, lock order and durable recovery

Closes every BLOCKER and MAJOR from the Phase 3 Claude review gate below. Full
engineering detail in `docs/PHASE3_PAYMENTS.md` sections 6a, 11 and 12.

- **One global lock order, declared in `apps/core/financial_locks.py`.**
  Request -> Match -> Offer -> Journey -> JourneyLeg -> eligibility witnesses ->
  Deal -> DealLegAllocation -> PaymentOrder -> PaymentAttempt ->
  PaymentProviderEvent -> PaymentRefund -> Payout -> ledger -> ScheduledJob.
  Three helpers implement it (`lock_request_graph`, `lock_deal_aggregate`,
  `lock_payment_order_aggregate`) and payment reconciliation, Deal funding,
  grace expiry, Deal cancellation and request cancellation all enter through
  them. Two rows of the same type are always taken in ascending id
- **The `PaymentOrder` <-> `Deal` cycle is removed**, not retried around.
  `reconcile_attempt` takes the complete domain aggregate before any finance
  row, so payment and grace expiry approach the graph from the same direction.
  The original stranded-payment reproduction (12 rounds of payment racing grace
  expiry, 2 of which used to deadlock and lose the money) is now a repeated
  stress test that asserts a single coherent terminal state every round
- **The `PaymentOrder` <-> `ParcelRequest` cycle is removed.** Request
  cancellation is a transactional domain service
  (`apps/parcels/services.py::cancel_delivery_request`) that locks the request
  graph before its orders and decides the refund from locked financial state
  instead of an unlocked read of `paid_eur_cents`
- **Provider events have a durable processing lifecycle**: `received`,
  `processing`, `applied`, `ignored`, `retryable`, `failed`, with
  `processing_attempts`, `next_retry_at`, `last_error_code/message`,
  `processed_at`, a `payload_fingerprint` that catches a provider reusing an
  event id, and a `normalized_event` sufficient to replay reconciliation after
  a crash. Uniqueness still prevents a duplicate economic effect; it no longer
  suppresses an effect that never happened
- **A committed event always has a live obligation to finish.** The
  `provider_event_process` job is created in the same transaction as the event,
  re-armed on every retry, and re-armed by a redelivery *before* the inline
  attempt — so a process killed mid-apply still leaves the work scheduled
- **External money reconciliation outlives business cancellation.**
  `cancel_order` closes the collection window and cancels only `attempt_expiry`
  jobs; `provider_reconcile`, `provider_event_process` and `refund_reconcile`
  survive. A provider that settles after the Deal expired or the request was
  cancelled is recorded truthfully, flagged `is_unapplied`, ledgered, and given
  a refund obligation — and does not revive the Deal or restore capacity
- **Every non-terminal refund is re-driven.** `refund_reconcile` is a real job
  kind with backoff and a stable provider idempotency key. A remote refund that
  succeeded before a local crash is rediscovered rather than re-issued (one
  external refund from two calls, asserted). A rail that has failed
  `REFUND_MANUAL_ESCALATION_ATTEMPTS` times sets `requires_manual_action` and
  joins the operator queue while the automatic retries continue
- **No provider HTTP call runs under a financial lock.** Checkout, checkout
  recovery, refund settlement and provider polling all use record-intent ->
  commit -> call -> reconcile. `request_refund` defers the provider call to
  `transaction.on_commit`, so a refund raised inside payment reconciliation or
  cancellation cannot hold domain locks across the network
- **Deployment cannot select development settings by accident.** `manage.py`,
  `config/wsgi.py`, `config/asgi.py`, both Dockerfiles, both Railway service
  files and the combined Railway launcher all name `config.settings.prod`
  explicitly. New tests boot the real production entrypoint in a clean
  interpreter and assert it *refuses to start* with
  `PAYMENTS_ALLOW_MOCK_PROVIDER`, `PAYMENTS_MOCK_WEBHOOK_ENABLED` or
  `PAYMENTS_LEGACY_MUTATIONS_ENABLED` set, or with no public base URL
- **The legacy mock rail is firewalled, not merely unused.**
  `PAYMENTS_LEGACY_MUTATIONS_ENABLED` (default false, refused in production)
  gates `choose_provider`/`get_provider` and every legacy mutation view; the
  unauthenticated legacy mock webhook answers 404. A V1 Deal or Offer gets its
  own `v1_deal_payment_not_available` refusal before the blanket retirement
  gate, so the client can tell "wrong rail" from "API gone". Historical rows
  are untouched and still readable
- **`Offer.economics_version` has no creation default.** A new V1 Offer states
  `v1_eur` explicitly; an Offer created without a version is an `IntegrityError`
  against `offer_economics_consistent`, not a silent legacy DZD price
- **Financial conservation is asserted against the provider, not the
  database.** `MockGateway` keeps its captures in module-level dictionaries
  Django never writes to; the race and recovery tests capture the provider
  session id before the race and assert local accounting against the rail's own
  record, so a payment lost to a rollback fails the test instead of agreeing
  with itself
- **Concurrency test quality.** Every future is joined, every worker exception
  propagates, and the two remaining either-branch assertions were replaced with
  enumerated terminal outcomes (`test_accept_and_counter_share_one_lock_order`
  now asserts the full state the winner implies; the grace-expiry race asserts
  the attempt succeeded unconditionally, because the provider charged before
  either thread started)
- **Crash/recovery points covered by local fault injection**: after event
  persistence before financial application, after attempt success before order
  recompute, after remote refund success before local commit, after a
  ScheduledJob claim before completion, and a killed worker mid-apply

### Phase 3B takeover repairs

Codex stopped mid-task. Three defects in its working tree were repaired before
anything else could be verified:

- `apps/core/tests/test_phase1_migrations.py` created a historical `Offer` with
  `economics_version`/`currency`, which matching.0002 does not have. `setUp`
  raised, so `tearDown` never restored the schema, and the shared test database
  stayed migrated backwards — 14 later `TransactionTestCase` classes failed with
  "no such table". The kwargs are gone (Phase 1 backfills those defaults, which
  is what the test asserts) and the restore is now an `addCleanup` registered
  before the backwards migration, so a failing `setUp` can no longer poison the
  rest of the suite
- `apps/matching/tests/test_v1_matching.py` had a new test header inserted into
  the middle of `test_sender_proposes_first_with_frozen_eur_terms`, orphaning
  its second half against an undefined `offer`. The original test is restored
  and the economics-version test is now standalone
- The legacy retirement gate ran before the V1-specific refusal, so a V1 Deal
  got 410 `legacy_payment_retired` where the contract (and the existing test)
  expects 409 `v1_deal_payment_not_available`

### Phase 3B verification

- SQLite: 650 tests, 591 passed / 59 skipped, 0 failures. PostgreSQL: 650
  tests, 616 passed / 34 skipped, 0 failures
- PostgreSQL finance + deals: 273 tests clean, including 20 financial
  concurrency tests and 14 crash/recovery tests — among them the 12-round deal
  payment/cancellation stress and the 8-round parcel payment/cancellation
  stress
- Repeated stress: three consecutive PostgreSQL rounds of
  `test_concurrency` + `test_recovery` + `apps.deals` (40 tests each) clean
- Ruff, `manage.py check`, `makemigrations --check` clean; no new migrations, so
  the committed SQL schema contract is unchanged
- Go build, vet and tests clean
- **Not run on this host**: the `-race` Go gate (no CGO toolchain), the
  docker-based `task check-drift` (no Docker), and the Flutter
  format/analyze/test gate (no Flutter SDK installed). No Flutter file was
  changed in Phase 3B
- Stripe and Chargily remain **CODE-CONTRACT VERIFIED**. No credentials exist
  and no live or sandbox provider call was made
- Phase 4 was not implemented and no Phase 4 behaviour was added

### Phase 3B residual findings (MINOR, legacy-only)

- `apps/payments/views.py::PaymentIntentRefundView` still performs its provider
  call inside a row-locked transaction. It is historical shape and unreachable
  in production: the legacy retirement gate refuses before it, and production
  refuses to boot with that switch set. Left as-is rather than restructuring a
  retired engine
- `apps/verification/services.py` locks `HandoverCode` before `Match` while
  legacy payment paths lock `Match` first. Legacy-only — V1 handover is refused
  with 409 `v1_deal_handover_not_available` — and handover is Phase 4's to
  rewrite
- `activate_business_settings` locks the candidate revision and then the active
  one. Reviewed and **not** a cycle: `core_settings_one_active` is a partial
  unique index, so there is at most one active row and all concurrent
  activators wait on the same second row
- The test suite logs Redis connection timeouts wherever `redis_bus` is not
  patched. Publishing is already fail-open and audited, so this is test noise
  and runtime slowness, not a correctness issue
- A provider that reuses an event id with a *different* signed payload marks
  the event `failed`, but the original delivery's `provider_event_process` job
  may still be pending and will then apply the **original** normalized event and
  move the row to `applied`. Reviewed and deliberately left: the original event
  was signature- and amount-verified, applying it exactly once is the correct
  financial outcome, and the alternative would strand it. The status transition
  is the only confusing part

## Phase 4 - handover, protection, disputes, cancellation, ratings, boosts

Full engineering detail in `docs/PHASE4_HANDOVER_DISPUTES.md`.

### Legacy handover audit - nothing was reused

`apps/verification` was audited before anything was written and found unusable
for V1 Deals on six independent counts, any one of which would have been
disqualifying: it hangs off a `Match` rather than a Deal; it locks
`HandoverCode` *before* `Match`, inverting the global order; it publishes the
plaintext code on the Redis bus to **both** parties, which for a delivery code
means straight to the traveler and into their database inbox row; it issues the
delivery code immediately on pickup with no safety buffer; its codes carry about
20 bits of entropy; and it settles the legacy DZD wallet with no protection
window and no dispute freeze. It keeps serving its historical rows, stays
refused for V1 (409 `v1_deal_handover_not_available`), and no migration moves a
legacy row into the new tables.

### Deal lifecycle

- `apps/deals/lifecycle.py` is the state machine and the only writer of a Deal
  lifecycle field. Every `apply_*` takes an already-locked aggregate, is
  idempotent, and reads its deadlines from the Deal's own frozen policy
- `Deal.lifecycle_policy` and `Deal.agreed_pickup_at` are snapshotted once, at
  funding. A settings revision published tomorrow cannot shorten today's safety
  buffer, move today's protection deadline or change a cancellation penalty a
  party has already been quoted
- Five database check constraints state the handover order independently of the
  application: no delivery-code window before a confirmed pickup, no release
  before a window, no confirmed delivery before a release, no protection window
  before a confirmed delivery, no no-show without an actor and a timestamp
- `DealEvent` gained 26 Phase 4 kinds. `apps/deals/timeline.py` projects it per
  viewer through a payload-key **allowlist**, so a key added by a future
  transition is invisible to a party until somebody deliberately allows it

### Handover codes

- New `apps/handover`. Codes are 8 Crockford base32 characters (2^40) from
  `secrets`, verified against `HMAC-SHA256(pepper, "deal:kind:code")` with
  `compare_digest`, and additionally stored **sealed** - encrypt-then-MAC under
  a separate derived key with `(deal_id, kind)` as associated data
- The seal exists because the specification requires the sender to re-open both
  codes and a hash cannot answer that, while rotating on every view would
  invalidate a code the traveler or the recipient already holds. Plaintext is
  never stored; ciphertext is. Verification never decrypts and revealing never
  compares; unsealing has two callers, both authorization- and state-gated, and
  both write a `HandoverCodeAccess` audit row that never holds the value
- Production refuses to boot unless `HANDOVER_CODE_SECRET` is at least 32
  characters and differs from `DJANGO_SECRET_KEY`, so compromising session
  signing is not the same event as compromising parcel handover
- **The traveler has no delivery-code read path at any layer**: none in the
  service, none in the URL conf, none in a serializer, none in an event payload,
  none in a notification, none in the Django admin (`code_hash` and
  `sealed_code` are excluded from every admin surface). `handover_state` states
  `"traveler_can_view_delivery_code": false` as an assertable contract
- Attempts: five failures per code trigger a timed lockout, three lockouts
  retire the code permanently, and an append-only `HandoverAttempt` table backs
  a per-Deal sliding window - a table rather than a counter, because a counter
  cannot answer "how many attempts in the last hour" after a restart. Both
  submit endpoints carry a `handover_submit` scoped throttle. Every
  value-dependent rejection collapses to one uniform message, and the serializer
  deliberately does not validate the code's shape

### The 30-minute buffer

- `delivery_code_available_at` is a stored column; the delivery code is created
  `buffered` with that instant copied onto it and a constraint refusing a
  buffered row without one
- `release_delivery_code` is the only way out, compares against the stored
  instant under the Deal row lock, and promotes the code **and** arms the
  recipient's email in one transaction - so "the code was revealed early" and
  "the recipient was emailed early" are the same impossible event
- A sender who looks after the window but before the worker runs triggers the
  identical release inline, so a stopped worker delays only the email

### Recipient and the durable notification

- `DealRecipient` is required before pickup - the delivery-code email has
  nowhere to go without it, and discovering that after the parcel has changed
  hands is unrecoverable. The traveler is shown a name and a delivery note only
  once carrying, and never the email address
- New `OutboundMessage` is a durable PostgreSQL obligation; the Redis stream is
  only how it is carried. The code is **not in the row**: `secret_ref` names the
  sealed code and the outbox opens it at render time, so the plaintext is never
  at rest in the notification table, the in-app inbox or the published-event
  audit. Dispatch is claim then carry then mark, so a crash re-carries an
  identical body: exactly-once logically, at-least-once physically

### Protection, payout eligibility and the race

- `apps/finance/payout_release.py` is the only normal path out of
  `not_eligible`, and requires all four of: verified delivery confirmation, the
  stored `protection_ends_at` passed, no active dispute, and clean financial
  state (order paid, nothing refunded, no refund in flight)
- **The dispute/timer race has no losing interleaving.** Both writers enter
  through `lock_deal_lifecycle`, which takes the Deal row before disputes and
  before the payout, so the second transaction blocks and then reads committed
  state. `Payout.Status.FROZEN` was added outside the constraint's released set
  so a freeze can never leave a payout the database considers releasable
- A clean expiry completes the Deal; the payout continues on its own lifecycle
  and each later state change is recorded on the Deal timeline. Holding a
  finished delivery open until an operator's bank transfer clears would
  misreport it for days, and V1 payouts are manual by default

### Disputes

- `Dispute`, `DisputeEvent`, `DisputeEvidence`. One active dispute per Deal
  enforced by a partial unique index; a retrying client resolves to the existing
  row rather than creating a rival with its own resolution
- Window: a party may dispute while the parcel is in carriage (the "no
  cancellation after pickup" path) or after delivery while inside the protection
  window. Only an admin may open one outside it, and a dispute opened after a
  payout was paid records `payout_already_settled` rather than pretending the
  money is still here
- The evidence bundle is captured at open time as immutable **references** -
  timeline, offers, terms, payments, refunds, payout, handover and attempt
  events, chat, journey and proof references, request snapshot, no-show - and
  contains no code in any form, no recipient contact details and no exact
  private location labels
- User evidence is size-, count- and content-type-capped, with the declared type
  verified against the actual bytes, stored in a private bucket, and reachable
  only through a short-lived signed URL issued after an authorization check

### Money: one settlement engine

- `apps/finance/settlement.py` serves dispute resolution, post-funding
  cancellation and no-show alike, so they cannot disagree about what
  "reconciles" means: every collected cent is refunded, paid out, or kept
- Checked three times over - `plan_settlement` refuses a split that does not sum
  to the collected total, `ledger.post` refuses an unbalanced transaction, and
  `disputes_resolution_reconciles` refuses to store a disagreeing resolution
- Fixed order of operations: re-recognise the liabilities first, release **only**
  the deposit credit about to be refunded, refund balance-order-first, then set
  the payout. Partial splits are integer-exact (`proportional` gives the
  traveler the floor and the platform the rounding remainder)
- Everything is keyed on one `settlement_key`, so two administrators serialize
  on the Dispute row and the loser returns the resolved row unchanged

### Cancellation, no-show, ratings, boosts

- Post-funding cancellation implements the seeded policy - traveler cancels:
  full refund; sender >24 h: full refund; sender <24 h: 10% of the reward capped
  at EUR 15 to the traveler, remainder refunded - all snapshotted onto the Deal.
  `GET /api/deals/<id>/cancellation` prices it without performing it. After
  pickup there is no normal cancellation; the API points at a dispute
- No-show is admin-reviewed with a named permission; a verified traveler no-show
  refunds the sender in full through the same settlement engine
- Ratings are bidirectional, one per side, immutable, and blind until both sides
  submit or the 14-day window closes. Visibility is recomputed as well as
  stored, so a worker that has not run cannot hide a rating past its window and
  an early one cannot expose it
- Paid boosts reuse the Phase 3 payment rails unchanged. Activation happens only
  on the authoritative provider event; a payment landing after the request is no
  longer boostable is **refunded**, not stranded. The only columns a boost ever
  writes on a request are the two ranking fields

### Durable obligations and the Phase 4 lock order

- Six job kinds added: `delivery_code_release`, `protection_expiry`,
  `rating_reveal`, `boost_expiry`, `outbound_message`, and
  `payout_release_check` turned from a Phase 3 stub into a real gate. Each
  handler is idempotent, refuses to act early against its stored instant, and is
  armed in the same transaction as the fact that made it true
- The global order is extended, not replaced:
  Request -> Match -> Offer -> **BoostPurchase** -> Journey -> JourneyLeg ->
  witnesses -> Deal -> DealLegAllocation -> **DealRecipient** ->
  **DealHandoverCode** -> **Dispute** -> **Rating** -> PaymentOrder ->
  PaymentAttempt -> PaymentProviderEvent -> PaymentRefund -> Payout -> ledger ->
  ScheduledJob
- Everything Phase 4 adds sits between `Deal` and `PaymentOrder`, except
  `BoostPurchase`, which sits with its request graph and never touches a Deal.
  `lock_deal_lifecycle` takes the whole set in one function, so the ordering is
  a property of that function rather than of every caller's discipline. The
  legacy `HandoverCode`-before-`Match` ordering is not reintroduced

### Admin primitives

- `apps/core/permissions.py` checks named Django permissions with `is_superuser`
  as the only blanket override and staff membership required on top. Migration
  `core.0007` seeds four groups matching the specification's roles. Reading a
  party's evidence and moving their money are separate capabilities, and neither
  is the same as viewing a payout queue. Final role/admin UX remains Phase 6

### Defects found and fixed during Phase 4

- **A funded Deal accepted a pickup with no recipient recorded.** `_deal_accepts`
  allowed status `funded`, so the parcel could change hands before anyone knew
  where the delivery code was to be sent - discovered 30 minutes later, with the
  parcel already gone. Pickup now requires `pickup_ready`
- **Funding crashed under a pre-Phase-4 settings revision.** `ensure_pickup_code`
  let `InvalidPhase4Policy` propagate out of `fund_deal`, so rolling settings
  back would have stopped every payment - the exact opposite of the documented
  degradation contract. Handover policy now falls back to the documented seeds,
  and `snapshot_on_funding` also catches a missing active revision
- **An unauthorized code submission was audited and then rolled back** by the
  exception it raised, losing the one attempt record most worth keeping. Every
  refusal now defers its exception until after the attempt row commits
- **`handle_boost_expiry` recorded an early fire as success**, discharging an
  obligation it had not performed and leaving the purchase `active` forever. It
  now raises and retries, like its siblings
- **The handover API mapped every exception to a handover-shaped 500**, hiding
  serializer and database failures from DRF's own handling. The catch is now
  narrowed to the mapped domain failures

### Phase 4 independent review

Two adversarial reviews ran before sign-off, both instructed to break invariants
rather than to describe the code.

**Security review** (handover secrecy, delivery-code isolation, the 30-minute
buffer, recipient privacy, the guest surface) found **no reachable defect**. It
enumerated every `unseal_code` call path, every serializer that could carry code
material, every logger and event payload, and the legacy refusal, and named the
specific gate that stopped each of its nine attack paths.

**Correctness review** (lock ordering, settlement arithmetic, idempotency,
state-machine gates, durability) reproduced its findings with throwaway probes
rather than reasoning about them. It confirmed **no deadlock cycle** — every
`select_for_update` across the six apps takes a prefix of the declared global
order, and no provider HTTP call happens under a financial lock — and verified
`plan_settlement` against 336 amount combinations, every Phase 4 transition for
replay safety, and every state-skip attempt. It also found this, which the
existing suite structurally could not:

- **BLOCKER, fixed — a second dispute could pay the same euro twice.** A Deal
  resolved as `full_traveler_payout` and then actually settled could have a
  second dispute opened inside the same protection window and resolved as
  `full_sender_refund`. `read_deal_money` reported what the Deal had *collected*
  and knew nothing about what had already been *paid out*, so the refund was
  computed against money that had already left. Reproduced end to end through
  shipped endpoints: 4 500 out against 2 500 in, with the ledger left claiming
  the traveler owed the platform the reward back. Fixed in two independent
  places — `plan_settlement` now bounds every refund by `settleable`
  (collected minus paid out) and floors the traveler's share at what they were
  already sent, and a party can no longer open a second dispute once one has
  been resolved. `apps/finance/tests/test_phase4_settlement_bounds.py` replays
  the original sequence
- **MAJOR, fixed — the ledger could be double-posted by a second settlement.**
  `_post_reallocation` derived its deltas from the price frozen at acceptance,
  which is correct only for a Deal's first settlement. It now derives them from
  the ledger's current position, so a second settlement posts nothing
- **MAJOR, fixed — two safety nets that did not exist.**
  `payout_release_check` is armed at funding and first fires 48 hours later,
  usually mid-transit; it returned a string, so the job was marked succeeded and
  the net was consumed before it could catch anything. `dispatch_due_messages`,
  the outbox backstop for a message whose job was lost, had no caller anywhere.
  The first now raises so it retries; the second runs in the finance worker loop
- **MINOR, fixed — a live delivery code could be issued on a refunded Deal.**
  Cancellation retired live codes; dispute resolution did not, and
  `rotate_code`'s delivery branch never checked Deal status. A sender whose Deal
  had just been refunded could mint a fresh code and have the platform email it
  to a third party
- **MINOR, fixed** — three disagreeing "closed Deal" status lists, which made
  the delivery-release job retry a correct refusal 24 times and raise an ERROR
  alert; `handle_rating_reveal` retiring itself on an early fire; the dispatch
  flag and its timeline entry written outside one transaction; a dead lock
  helper documenting an order no caller took and the settlement contradicts; and
  `complete_manual_payout` — the endpoint that actually sends the money — gated
  on bare `is_staff` while the decision authorising it required a named
  permission
- **Accepted, documented** — a payout that is already `paid` can coexist with a
  dispute an administrator opens afterwards. No code can recall a bank transfer;
  the dispute records `payout_already_settled` and the settlement bounds mean it
  can allocate only what is left. The guaranteed invariant is stated precisely
  in `docs/PHASE4_HANDOVER_DISPUTES.md` rather than overclaimed

## In progress

- **Phase 5: PAUSED / IN PROGRESS.** Flutter V1 rebuild, frontend integration,
  UX/RTL/accessibility audit, final mobile testing, and cross-stack findings
  remain assigned to Claude after its usage reset. The work is checkpointed and
  must not be reformatted, rewritten, or marked complete by Phase 6A
- **Phase 6A: engineering foundation implemented; release gates remain.** Fixed admin roles, secure
  invitations, audit/operations APIs, dashboard and health visibility,
  versioned settings administration, Sender.net through the durable generic
  SMTP boundary, localized public web, and policy/support drafts. Engineering
  detail is in `docs/PHASE6A_ADMIN_EMAIL_LANDING.md`. Focused verification on
  2026-08-28 passed 56 Django admin/notification/account tests, Django system
  and migration-drift checks, Ruff, the Go email/config suites, localized-route
  and Arabic RTL assertions, the frontend anti-pattern detector, and a stable
  two-pass PostgreSQL 16 schema export. sqlc generation remains an explicit
  no-op because the configured query directories contain no `.sql` files
- **Phase 6A stabilization checkpoint (2026-08-28).** Full SQLite: 819 passed / 65
  skipped / 2 failed; full PostgreSQL 16: 850 passed / 34 skipped / 2 failed.
  Both failures pre-date Phase 6A: the uncommitted
  `apps/chat/tests/test_zzz_probe.py` diagnostic deliberately failed and was
  removed at this final cleanup checkpoint, while the Phase 1–4 V1 chat test
  expected legacy `v1_payment_unavailable`; it now correctly asserts the
  current funded-Deal gate's `payment_pending` response. Phase 3
  finance/concurrency/recovery: 62 passed; Phase 4
  lifecycle/concurrency: 172 passed; admin/notifications/accounts: 56 passed.
  Three stale Phase 4 test fixtures were updated to the fixed Phase 6A role
  names, and a reproduced payment/cancellation deadlock was fixed by making
  cancellation enter the canonical aggregate lock order. Django check,
  migration drift/apply, Ruff, Go build/vet/test, and clean-database schema
  drift/repeat-export gates pass; sqlc remains an explicit zero-query no-op.
- Production data reconciliation is awaiting an authorized Railway SSH key
- Production migration lock-duration rehearsal awaits production row counts and an approved window
- Trusted airport-coordinate dataset selection before any legacy Trip/Journey backfill
- Production route-provider adapter/credentials and cache configuration
- PostGIS-capable Railway database rehearsal before replacing bounded spatial fallback

## Next

- Phase 5 resume: complete the paused Flutter V1 redesign using `docs/PHASE1_API_CHANGES.md`,
  `docs/PHASE2_MATCHING_PRICING.md` and `docs/PHASE4_HANDOVER_DISPUTES.md`.
  The Phase 4 API exposes every authoritative timestamp the client needs, so no
  deadline or amount is ever computed on the device
- Phase 6A release review: apply final visual judgment after Phase 5 resumes,
  complete counsel review/localized legal text, and activate the deployment
  configuration described in `docs/PHASE6A_ADMIN_EMAIL_LANDING.md`
- Provider activation: real Stripe and Chargily credentials, production webhook
  registration, Sender.net configuration, and the final environment variables
  including `HANDOVER_CODE_SECRET`

## Important known legacy assumptions

- Airport Trip, DZD Offer, ProductRequest, Offer-bound PaymentIntent, wallet,
  verification, and notification rows remain historical compatibility data.
- New V1 marketplace writes do not use those legacy contracts.
- The existing Flutter UI still uses the legacy contracts and must not be
  released against the V1 write switch before its planned redesign.
- Legacy verification currently exposes codes and lacks the V1 timing rules;
  it is prohibited for new Deals.
- The Go race suite is configured in Linux CI; it cannot execute on the current
  Windows host because no CGO-compatible GCC toolchain is installed.
- The prior Flutter client was entirely legacy. Phase 5 contains an unfinished,
  checkpointed V1 replacement; because integration and testing are incomplete,
  it still must not be released against the V1 write switch.
- The bottom-navigation redesign (Home/Deliveries/Chat/Profile, notifications in
  the header bell, one shared bottom inset) remains recorded for Phase 5.

## Phase 3 Claude review gate — 2026-08-25 (all findings closed in Phase 3B)

Verdict: **NEEDS CODEX FIXES**. Codex's own gates are green (596 passed /
54 skipped on SQLite; 251 passed on PostgreSQL for `apps/finance` +
`apps/deals`; Ruff clean; `manage.py check` clean; no migration drift), and the
financial architecture is sound in design. The blockers below were found by
adversarial probing, not by the existing suite, which structurally cannot fail
on them.

- **BLOCKER — `PaymentOrder` <-> `Deal` lock-order cycle strands captured
  money.** `reconcile_attempt` locks `PaymentOrder` then `Deal` (via
  `_fund_deal_if_covered` -> `fund_deal`); `release_pending_deal_reservation`
  locks `Deal` then `PaymentOrder` (via `cancel_deal_balance_orders`).
  Reproduced on PostgreSQL: 2 of 12 runs of a payment racing grace expiry
  deadlocked, the webhook rolled back, and the customer was charged with no
  succeeded attempt, no ledger entry and no refund.
- **BLOCKER — `PaymentOrder` <-> `ParcelRequest` is the same cycle again.**
  `_publish_request_after_deposit` locks `ParcelRequest` while holding the
  order; `ParcelCancelView` and `handle_deposit_expiry_refund` take them the
  other way round.
- **BLOCKER — the idempotency gate commits ahead of the money.**
  `apply_provider_event` commits `PaymentProviderEvent` in its own transaction
  before calling `reconcile_attempt`. Any rollback in reconciliation turns
  every provider retry into a `duplicate_event` no-op, permanently.
- **BLOCKER — `cancel_order` cancels the `provider_reconcile` job**, which is
  the only path that could recover money the webhook lost.
- **MAJOR — nothing reads `PaymentProviderEvent.processing_result='pending'`**,
  so the stranded state is undetectable.
- **MAJOR — a provider refund HTTP call runs inside `reconcile_attempt`'s
  transaction**, holding order and attempt row locks for up to the 15s timeout
  and widening both deadlock windows.
- **MAJOR — a `pending` refund is never re-driven.** `request_refund` returns
  an existing row before reaching the provider, and there is no
  refund-settlement `ScheduledJob` kind.
- **MAJOR — `ParcelCancelView` decides whether to refund from an unlocked
  read** of `paid_eur_cents`, so a deposit paid in that window is cancelled
  without a refund obligation.
- **MAJOR — deployment settings selection.** `manage.py` defaults to
  `config.settings.dev`, which defaults `PAYMENTS_ALLOW_MOCK_PROVIDER` and
  `PAYMENTS_MOCK_WEBHOOK_ENABLED` to true; nothing committed selects
  `config.settings.prod`. The Phase 3 mock guards are correct but only run
  under `prod`.
- **MAJOR (latent) — legacy `apps.payments`** still mounts an ungated
  instant-success mock provider (`choose_provider` always returns mock) and an
  unauthenticated mock webhook. Confined today only because legacy offer
  creation is retired; `Offer.economics_version` still defaults to
  `LEGACY_DZD`.

Verified sound and not regressed: `PaymentOrder` derivation and constraints,
`PaymentAttempt` transitions including `processing`, posting-deposit pricing and
clamps, deposit credit/release, FX immutability (attempts serialize their own
frozen rate), guest-payer isolation, ledger double-entry and append-only
behaviour, `fund_deal` as the sole writer of `Deal.FUNDED`, the payout
`not_eligible` gate, Stripe/Chargily signature verification, the absence of a
fabricated Chargily refund, object-level authorization across all Phase 3
endpoints, and the three Phase 2 minors.

Provider status: Stripe and Chargily are **CODE-CONTRACT VERIFIED** only. No
credentials exist, no live or sandbox provider call has been made, and neither
may be described as LIVE-PROVIDER VERIFIED.

At the time of this historical Phase 3 review, Phase 4 had not yet been
implemented. The Phase 4 sections above record its later completion.

## External dependencies/blockers

- Stripe credentials (secret key + webhook signing secret) and payout/transfer
  capability approval; until configured, Stripe is reported unavailable and
  every Stripe checkout is refused
- Chargily merchant account and API secret key, plus a real
  `chargily.eur_dzd_rate_micros` — the seeded rate is an explicit placeholder
- `PAYMENTS_PUBLIC_BASE_URL` on the deployment (production refuses to boot
  without it) and `run_finance_worker` added to the process topology
- Sender.net account credentials, verified sending domain, SPF/DKIM/DMARC DNS,
  support/from addresses, and final public/deep-link origin; the generic SMTP
  adapter and durable message contracts exist, but these external settings are
  not configured
- map provider
- Apple/Google developer accounts
- legal review before public launch
- authorized Railway SSH access for production data reconciliation
- reviewed airport-coordinate source for a later compatibility backfill
- production route/directions provider credentials and adapter selection
- Railway PostGIS template/environment and migration rehearsal for scaled spatial search

Agents should update this file as work progresses, but it must not become a replacement for the actual specification.
