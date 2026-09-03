# ShipTrip V1 Implementation Status

Current phase: Phase 5 **IMPLEMENTED / DEVICE REVIEW PENDING**; Phase 5C visual restoration **IMPLEMENTED / HARDWARE QA PENDING**; Phase 6B **IMPLEMENTED / NATIVE-LANGUAGE, EMAIL-CLIENT AND LEGAL REVIEW PENDING**; Phase 6C **IMPLEMENTED / EXTERNAL SENDING INACTIVE**; Phase 6D mobile communication-language integration **IMPLEMENTED**; Phase 7A production hardening **IMPLEMENTED / EXTERNAL ACTIVATION PENDING**; Phase 8A mobile reliability **IMPLEMENTED / RELEASE-MODE HARDWARE QA PENDING**; Phase 8B authoritative geography catalogue **IMPLEMENTED**; Phase 8C canonical location UX and locality matching **IMPLEMENTED / DEVICE REVIEW PENDING**; Phase 8C UX review pass **IMPLEMENTED / HARDWARE QA PENDING**; Phase 8D admin rebuild, 8D-R matching lock repair, 8D-F finance deadlock repair and 8D-V visual pass **IMPLEMENTED**; Phase 8E integration and private release candidate **IMPLEMENTED / OWNER DEVICE QA AND PROVIDER-MODE READ PENDING**
Overall status: Phase 1–4 backend lifecycle work remains complete and the V1 delivery lifecycle runs end to end. Money is
server-authoritative and double-entry ledgered, every cross-domain transition
follows one global lock order, the traveler can never read a delivery code, the
delivery code stays sealed for 30 minutes after pickup, payout waits 48 hours
and is frozen by any active dispute, and every delayed obligation is a
PostgreSQL row rather than a timer. The Phase 5 Flutter V1 rebuild is now
implemented against the real V1 contracts: the client uses no retired endpoint,
computes no authoritative money, and cannot put a delivery code in front of a
traveler. `flutter analyze --fatal-infos` is clean and the mobile suite passes.
What remains before Phase 5 can be called finished is rendering on real
devices — every layout claim is currently backed by widget tests at real device
metrics rather than by hardware.

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

- **Phase 5: IMPLEMENTED / DEVICE REVIEW PENDING.** The Flutter V1 client is
  rebuilt end to end against the real V1 contracts, extracted from the URL
  configuration and serializers rather than from documentation. Engineering
  detail is in `docs/PHASE5_FLUTTER_V1.md`. Summary:
  - Final navigation is Home / Deliveries / Chat / Profile, with notifications
    on the header bell. The bottom-overlap bug is fixed *structurally* — a
    docked bar plus one shared inset — and no screen carries a hand-tuned
    bottom padding
  - One account, one identity: role context reorders Home and re-points the
    primary action, and hides nothing
  - Complete sender and traveler lifecycles: request creation with the five
    separate safety declarations, posting deposit, discovery, sender-first
    proposal and counter, funding, recipient, pickup, the 30-minute delivery
    buffer, delivery confirmation, the 48-hour protection window, disputes with
    evidence, cancellation quotes, bidirectional blind ratings, boosts, chat,
    notifications, KYC, multi-leg FLIGHT/DRIVE journeys with flight proof
  - Money is server-authoritative by construction: `Money` defines no
    arithmetic operators, so a client-side total is a compile error
  - The traveler can never obtain the delivery code. `revealDeliveryCode` has
    exactly one call site, guarded by the sender branch and the server's own
    `can_reveal_delivery_code`; codes are never persisted, never logged, and
    redact themselves in `toString()`
  - English, French and Arabic catalogues at 928 keys each, machine-verified
    for key parity, placeholder survival, Arabic's six ICU plural categories
    and the absence of embedded bidi control characters
  - `flutter analyze --fatal-infos` clean; 107 mobile tests green across six
    device profiles including small Android, gesture navigation, iPhone home
    indicator, landscape and 1.6x text
  - A temporary web build against a live local backend was used to actually
    look at the app, there being no Android/iOS toolchain on this machine. It
    found four defects no test had caught, including a **BLOCKER**:
    `restore()` was never called, so the app sat on its splash screen forever.
    All four are fixed and the harness removed
  - **Not yet done:** rendering on real Android/iOS hardware, and a
    native-speaker review of the French and Arabic catalogues
  - One backend BLOCKER found and fixed (V1 chat eligibility); further MAJOR and
    MINOR findings are listed in `docs/PHASE5_FLUTTER_V1.md` for Codex
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

- Phase 5 close-out: render the client on representative devices and fix any
  visual regressions; have the French and Arabic catalogues reviewed by native
  speakers; wire pagination for `/api/deals`, `/api/notifications` and chat
  history before users accumulate long histories
- Phase 5 backend follow-ups for Codex: the MAJOR findings in
  `docs/PHASE5_FLUTTER_V1.md` — handover/dispute/rating events publish no
  notifications, the guest payer has no post-payment status endpoint, and
  `kyc_status` cannot distinguish "never submitted" from "expired"
- Superseded: Phase 5 resume using `docs/PHASE1_API_CHANGES.md`,
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

## Phase 7A — production hardening and release engineering (2026-08-29)

Implemented locally without touching `mobile/`, activating providers, or
deploying production:

**Phase 5C is IMPLEMENTED / HARDWARE QA PENDING.** The original ShipTrip
visual identity has been restored on top of the Phase 5 V1 engineering, using
commit `76ce129` as the reference rather than recollection: parchment ground
with paper grain, the original ink and terracotta, the sun accent, ink pill
buttons, passport stamps, boarding-pass cards, wax seals, perforated postage
marks, the animated flight path, and the staggered entrance choreography. The
welcome screen and the three-chapter benefits carousel are restored; the auth
screens use the original masthead instead of an app bar. Two MAJOR findings
were fixed — the app defaulted to dark mode (the original had no dark theme,
so every dark-mode device saw a product that looked nothing like ShipTrip),
and the ink/terracotta ramps had drifted from the original values. Details,
including the deliberate accessibility deviation on the tertiary grey and the
confirmation that the original had no gradients or image assets, are in
`docs/PHASE5C_VISUAL_RESTORATION.md`. `dart format` clean,
`flutter analyze --fatal-infos` clean, 107 tests green, no behavioural
assertion weakened. Phase 7A introduced no breaking response-shape change for
mobile; the client now reads `Retry-After` and `X-Request-ID`. Rendering on
real Android/iOS hardware remains the outstanding gate.

- production boot now requires an explicit production environment label,
  database/Redis/HTTPS object-storage configuration, safe hosts/origins, strong
  independent secrets, and all payment escape hatches closed; Stripe/Chargily
  credentials remain optional while disabled
- public liveness and database/migration readiness probes plus a granular,
  permissioned deep-health endpoint for Redis, durable jobs, provider-event
  recovery, email backlog, provider configuration and storage configuration
- shared Redis-backed production throttles for authentication/OTP, discovery,
  payment, handover, upload/evidence, chat, and admin-invitation surfaces;
  global request-body bounds at Django and Caddy
- server-generated request IDs, allow-listed JSON production logging, release
  metadata, Sentry PII-off environment/release metadata, secure cookies/origins,
  gateway/static security headers and CSP
- defensive fixes for Google unverified-email account linking, concurrent OTP
  attempt-budget bypass, legacy finance/dispute granular authorization/audit,
  parcel bucket/key response leakage, and unbounded legacy list responses
- validated PostgreSQL/Redis Go connection URLs, an authoritative expanded
  `.env.example`, and a loopback-only read-only load probe
- release artifacts: `docs/PHASE7A_PRODUCTION_READINESS.md`,
  `docs/DEPLOYMENT_RUNBOOK.md`, `docs/ROLLBACK_RUNBOOK.md`, and
  `docs/PROVIDER_ACTIVATION_RUNBOOK.md`

Local Phase 7A verification is green: the complete SQLite application suite
passed **943 tests / 65 expected infrastructure-specific skips**, and the
full PostgreSQL 16 suite passed **974 tests / 34 expected skips** against the
local server (using the repository's ignored `config/settings/test_pg.py`
helper only for the earlier collection setup, not as a test module). A clean
fresh-migration PostgreSQL schema dump matched `contracts/sql/schema.sql` after
the CI-documented generator-noise normalization; the temporary schema database
was verified empty of active connections and dropped. Ruff, Django checks,
migration checks, explicit production `check --deploy`, Python compilation, Go
format/build/vet/unit tests, static route/link/CSP checks, Railway JSON parsing,
and diff integrity passed. A bounded authenticated local read probe completed
500/500 requests successfully at concurrency 10 (140.87 req/s, 13.95 ms
median, 466.39 ms p95) on Django's development server and file-backed SQLite;
this is stability evidence, not a production capacity claim. No schema/model
migration was added.

Phase 7A remains **NO-GO for public launch**. External Railway backup/restore
and production-sized migration rehearsal, real-Redis and Caddy container
validation, legal/support content, provider activation, monitoring/on-call
ownership, and Phase 5C mobile/device compatibility approval remain required.
Stripe, Chargily, and Sender.net are still not configured or live-verified.

### Phase 7A release-hardening continuation — 2026-08-30

- The authenticated Go KYC upload now has a Redis-backed, atomic fixed-window
  account budget before multipart parsing/storage (default 6/hour). Multiple
  service instances consume one shared counter; concurrent calls cannot exceed
  the budget; denial is structured HTTP 429 with `Retry-After`; missing or
  failed Redis is a safe HTTP 503 with no object/recorder work. The optional
  hashed-IP budget is off by default and requires an explicit trusted client-IP
  source when enabled.
- The combined Railway launcher now requires a validated non-loopback
  `KYC_RATE_LIMIT_REDIS_URL` and maps it into only the KYC child. The existing
  loopback Redis remains isolated to the combined container's ordinary
  pub/sub/cache work and cannot accidentally become a per-replica KYC limiter.
- KYC image verification now completes a full decode after signature, decoder
  format and 48-megapixel checks, closing header-valid truncated-image uploads.
  Private object keys were also removed from orphan-cleanup logs.
- A real PostgreSQL gate exposed a payment/cancellation interleaving that could
  mark captured money cancelled with no refund obligation. `cancel_order` now
  becomes a no-op when captured applied cents are not fully covered by durable
  refund rows; the focused PostgreSQL race and deterministic regression pass.
- Focused gates are green: Go KYC/config/Redis packages, 26 production
  boot/launcher refusal tests, 61 finance/deployment tests, the isolated
  PostgreSQL account suite (25 tests), and the focused PostgreSQL financial
  race/regression. Full PostgreSQL (974/34), full SQLite (943/65), and fresh
  migration schema drift are now complete; ordinary Go build/vet/tests and
  final lint/check evidence are recorded above and in
  `docs/PHASE7A_PRODUCTION_READINESS.md`.

Phase 7A remains **NO-GO for public launch**. Distributed limiter code is no
longer the blocker; provisioning the shared managed Redis and exercising the
tagged real-Redis outage/recovery suite are. Caddy container validation, the Go
CGO race gate, production-sized migration/restore rehearsal, external legal and
operational approval, provider activation, and mobile/device compatibility also
remain open. No provider was activated, no production system was deployed, and
`mobile/` was not modified by this continuation.

## Phase 6B stabilization continuation handoff — 2026-08-29

Phase 6B is **not visually complete**. Claude's established public, admin, and
email visual direction is preserved for a later Impeccable pass. The engineering
stabilization found and fixed the admin journey proof-count contract and made
the Go email consumer reject messages that still lack a durable event ID after
stream backfill; it did not redesign any surface. On the supported Python 3.12
runtime, the complete SQLite suite passes 871 tests with 65 expected
infrastructure-specific skips.

### ENGINEERING ISSUE

- Authenticated Django-admin template integration is green on the project's
  supported Python 3.12 runtime. A login capture exists, but representative
  authenticated admin screenshots with populated data remain a visual-review
  task; the available browser harness does not automate the login flow.
- This stabilization pass could not independently recapture exact 320 px,
  375 px, and 430 px viewports because the available headless Edge build clamps
  the layout viewport to roughly 500 px. Claude's Phase 6B notes record a
  passing 375 px emulated-browser review; desktop and 500 px narrow captures
  also show no horizontal overflow. Exact-width evidence should be repeated
  during the continuation pass.

### DESIGN REVIEW NEEDED

- Resume Claude's final Impeccable review of the complete EN/FR/AR landing
  composition, including exact phone, tablet, desktop, and wide-desktop sizes.
- Review authenticated admin dashboard, users, KYC, proofs, marketplace,
  disputes, finance, settings, and health states with representative data,
  especially dense/empty/error rows and financially important statuses.
- Review the shared transactional email shell and representative messages in
  Gmail, Outlook, and Apple Mail at desktop and narrow widths; RTL/localized
  email presentation has not been implemented.
- Revisit Terms, Privacy, Prohibited Items, and Support only after qualified
  legal review and native FR/AR copy are supplied. They remain English-only
  product/legal drafts and must not be treated as approved legal text.

## Phase 6B final visual/product review — 2026-08-29 (Claude)

The continuation pass the stabilization handoff asked for is **done**. Every
surface was reviewed as rendered, at the sizes and in the states it will be met
in, and the visual BLOCKER/MAJOR findings are fixed. Full detail, with severities
and before/after reasoning, is in `docs/PHASE6B_VISUAL_PRODUCT_QUALITY.md` §15.

### What was reviewed, and how

- **Public site**: `/en/`, `/fr/`, `/ar/` at 320, 375, 430, 768, 1024, 1440 and
  1600 CSS px, plus the four document pages at 375 and 1440. Phone widths were
  measured in an emulated viewport at 2× — this closes the exact-width evidence
  gap the stabilization handoff recorded, which was a limitation of headless
  Edge (no layout below ~492 px), not of the site. At every width and locale
  `scrollWidth == clientWidth`.
- **Admin**: rendered against a seeded database carrying four deals driven
  through the real services, an open dispute with evidence and timeline, a
  resolved dispute, a failed attempt, an unapplied payment, a refund needing
  manual action, an unverified provider event, three job states, pending and
  rejected KYC, three flight proofs and a failed outbound email. Pages were
  produced with `force_login` server-side rather than by typing credentials into
  the login form, which is also the answer to the handoff's "harness does not
  automate the login flow" note. `tools/preview/` holds the seed, dump and
  render scripts, with a README.
- **Email**: all 24 documents rendered to files and reviewed at desktop and
  375 px, plus a mechanical audit of every document for client-hostile
  constructs.

### Visual fixes landed

Public site — hero italic collision; Arabic FAQ arrow pointing up while closed;
six trust items leaving a two-cell hole; the FAQ leaving half a band empty; a
three-row 149 px sticky header at 320 px; the eyebrow rule sliding between lines
of a wrapped eyebrow; the mobile table of contents reading as damage; the
policy pages not marking the current language; the two boarding-pass seams
sitting at different heights in French.

Admin — a **Needs attention** queue panel on the dashboard (nine queues, each a
count linked to the changelist filtered to exactly those rows); a read-only
`OutboundMessage` admin, which is the first operator visibility of transactional
email at all; worded status chips replacing boolean icons on the user queue,
where a red cross under IS BANNED meant the account was fine; a confirmation
step on the bulk ban action; the scheduled-job change form frozen so `requeue`
is the only mutation, as its own docstring already claimed; a **Key values**
reading of the settings policy in operator units; a **Where the money is** panel
on the dispute page.

Email — the plain-text part now carries the anti-phishing and transactional
footer the HTML part always had; two sentences that interpolated a context value
mid-sentence now stand alone when the value is absent, which a durable outbox
makes a real case.

### Decisions recorded

- **Email localization is not presentation work** and was not implemented:
  there is no `LANGUAGES`, no catalogue, no `gettext` call, no language on
  `User` and none on `OutboundMessage`. `docs/PHASE6B_VISUAL_PRODUCT_QUALITY.md`
  §15.4 specifies the required launch behaviour (FR + AR + EN for every
  user-facing kind, `ADMIN_INVITATION` excepted), the priority order, and
  exactly what a focused Codex task has to cover — including RTL email
  rendering and the guest/recipient language resolution, which has no user row
  to read from.
- **Six unwired templates are LAUNCH REQUIRED**: `KYC_STATUS`,
  `FLIGHT_PROOF_STATUS`, `SECURITY_EVENT`, `PAYMENT_FAILED`, `REFUND_STATUS`,
  and `GUEST_PAYMENT` if the guest rail ships. `PROTECTION_ENDING` is strongly
  recommended. `PAYMENT_PROCESSING` is NOT NEEDED. §15.5 has the reasoning per
  template. **No backend event was wired in this pass.**
- `SECURITY_EVENT` is the sharpest of them: `PasswordResetConfirmView` sets a
  new password and notifies nobody, so an attacker with mailbox access takes an
  account over silently. The template is already written.

### Still open after this pass

- Native French and Arabic review of both the site and the email copy. Mechanical
  RTL is verified; linguistic quality is not claimed.
- No real email client was used. Gmail, Outlook desktop and Outlook.com, Apple
  Mail and a narrow Android client remain unverified; the construct audit is
  what the design is built to survive, not evidence that it did.
- Model `verbose_name_plural` is unset on several models, so the admin reads
  "O auth identitys", "Matchs", "Ledger entrys", "Wallet entrys", "Handover code
  accesss", "Kyc submissions". Fixing it touches model `Meta` and generates
  migrations, so it was left out of a visual pass.
- Policy pages remain unapproved English-only drafts, and support mailboxes
  remain placeholders. Neither was changed.
- No provider was activated, no webhook registered, no DNS or deploy touched,
  and no Flutter file was read or written.

## Phase 6C — transactional email wiring and localization (2026-08-29)

Phase 6C is implemented with external sending inactive. `User.preferred_language`
and Deal-scoped `DealRecipient.communication_language` accept only `en`, `fr`,
or `ar`; historical blanks resolve to English without rewriting intent. Guest
payment links snapshot an explicit language (or the owner's resolved language).
`OutboundMessage.language` snapshots the locale at enqueue time, so profile
changes cannot mutate queued obligations.

French and Arabic Django gettext catalogues provide localized subjects,
preheaders, bodies, CTAs, footers, plain text and conservative HTML. Arabic
documents are RTL with explicit LTR isolation for codes, URLs and money. The
delivery-code path remains `secret_ref` to trusted final renderer to SMTP; the
plaintext code is absent from all persisted context, events, logs and jobs.

Authoritative, deterministic, idempotent wiring now covers KYC approval/action
required, flight-proof approval/action required, password-reset security
notification, actual payment failure, refund pending/completed, guest payment
failure/receipt, and one protection-ending reminder 24 hours before expiry.
Opening a dispute cancels pending protection-ending reminders. Transient
payment processing, payment-required/succeeded, and evidence-request mail stay
deliberately unwired; admin invitation remains English-only for launch.

The four additive migrations and PostgreSQL schema contract were regenerated
and repeat-dump checked. Phase 6C tests cover language snapshots/fallbacks,
three-locale delivery-code secrecy, event idempotency, security notification
confidentiality, late payment success cancellation, refund/guest privacy,
protection cancellation, migration reversibility and Redis-independent outbox
durability. Required Flutter selectors and guest receipt-email collection are
documented follow-up; `mobile/` was untouched.

Verification completed locally: full SQLite application suite **937 passed / 65
skipped**; fresh PostgreSQL Phase 6C, recovery and localization suite **34
passed**, plus PostgreSQL migration forward/reverse rehearsal **1 passed**;
Ruff, Django checks, migration drift, Python compilation, static email rendering,
Go build/vet/tests and normalized PostgreSQL schema repeat-dump all pass.

### Local toolchain note

This machine runs Python 3.14.3 while CI and the image pin 3.12. Django 5.1.4
copies a template context with `copy(super())`, which returns the proxy from
3.14, so every admin render raises inside `InclusionAdminNode` — two admin tests
were failing here for that reason alone. `backend/monolith/conftest.py` restores
the pre-3.14 behaviour behind a version guard; on 3.12 it does nothing.

## Phase 6D — mobile communication-language integration (2026-08-30)

Phase 6D is a bounded Flutter compatibility patch closing the client-side gap
Phase 6C left open. No backend file, no email template, no landing or admin
surface, no payment logic and no handover cryptography was touched, and no
provider, webhook, DNS record or deployment was configured. The Phase 5C visual
identity is unchanged; no screen was redesigned.

### App language and communication language are now two named settings

`Profile -> Language` holds both, one under the other, because they are one
question to a user and two different answers in the system:

- **App language** is the interface. It is a device setting, it never leaves
  the phone, and it is the only thing that decides text direction.
- **Email language** is what ShipTrip writes to the account in — payment and
  refund receipts, KYC and flight-proof decisions, dispute, cancellation and
  payout notices, account-security mail. It is stored on the account and
  follows the user to every device.

Each carries a one-line explanation naming that difference, and every option is
written in its own language so a user who landed in the wrong interface can
still recognise theirs. Splitting them into two Profile rows was rejected: two
rows offering the same three languages is the confusing duplicate the
distinction exists to prevent.

The two settings are independent after account creation. Changing the interface
language sends nothing to the server and cannot overwrite a stored preference.
The one legitimate synchronisation is at sign-up, where the account does not
exist yet: `POST /api/auth/sign-up` now carries `preferred_language` resolved
from the language the form was filled in. Google sign-in accepts the same
optional field, which the server applies only when it creates a fresh account.

Selecting Arabic email does not mirror the app. Only the app-language setting
does, and the Arabic option label is direction-scoped to itself.

### API mapping used

Verified against the Phase 6C serializers rather than assumed:

| Surface | Call | Field |
|---|---|---|
| Profile read | `GET /api/me` | `preferred_language` (resolved by the server) |
| Profile write | `PATCH /api/me` | `preferred_language` — the only writable field |
| Recipient write | `PUT /api/deals/{id}/recipient` | optional `communication_language` |
| Recipient read | deal aggregate, sender projection | `communication_language` |
| Guest link | `POST /api/payments/orders/{ref}/guest-link` | optional `communication_language`, echoed back |

Values are exactly `en`, `fr`, `ar`. The client never sends a region tag, a
`Locale`, or a null.

### Legacy behaviour

`CommunicationLanguage.parse` mirrors
`apps.core.languages.normalize_communication_language`: a blank, missing,
unknown or wrongly-cased value resolves to English. Accounts created before the
preference existed therefore show English selected rather than an empty
selector, and a deployment that omits the key entirely still parses. No
migration-time intent is invented on the client.

### Recipient language

The recipient form gained an EN/FR/AR row directly under the email address it
governs, using the existing `AppSegmentedChoice` — the app's own selector, not
a Material dropdown. `AppSegmentedChoice` gained `helper`, `errorText` and
`enabled` so it keeps the form's footnote rhythm and stays visible-but-inert on
a form the server has locked after pickup.

- A **new** recipient defaults to the sender's stored communication language,
  which is what the server snapshots when the field is omitted.
- An **existing** recipient loads the stored server value and keeps it unless
  the sender changes it. Correcting a phone number cannot rewrite the language
  of an email somebody is waiting for.
- A **legacy blank** recipient row, and a deployment that omits the field, both
  edit as English — the server's own fallback — not as the sender's preference.
- The language is never inferred from a name, an email address, its domain, a
  nationality, or a city. The sender chooses; that is the only input.

### Guest payment

`PaymentRepository.createGuestLink` now accepts and forwards
`communication_language`, and `GuestPaymentLink` parses the snapshot the server
returns. There is still no guest-link issuing screen in the mobile build, so
today the server's own snapshot of the owner's resolved preference is what
applies; the client no longer prevents an explicit choice when that screen
lands. No guest-payer UI was added and no guest authority was granted.

### Delivery-code isolation is unchanged

`secret_ref -> trusted localized renderer -> SMTP` is untouched. Flutter renders
no transactional email and receives no delivery-code secret as traveler. The
traveller's recipient projection still carries no email, no phone and no
language, `RecipientView.toString()` still redacts, and the sender reveal
endpoint still has exactly one call site. Regression coverage for all four is in
`mobile/test/handover_isolation_test.dart`.

### Verification

`mobile/test/support/fake_api.dart` installs a fake Dio adapter under the real
`ApiClient`, repositories, session controller and screens, so the tests assert
on the JSON that would actually reach Django rather than on a stubbed
repository.

- `dart format --set-exit-if-changed lib test` — clean, 109 files, 0 changed.
- `flutter analyze --fatal-infos` — no issues.
- `flutter test` — **192 passed**, up from the 107 that passed before this
  phase; every pre-existing Phase 5C test remains green.
- ARB key parity: 975 keys in each of EN, FR and AR; `l10n_untranslated.json`
  is empty.

New coverage: profile blank/EN/FR/AR/change/persisted-PATCH/server-error;
recipient default-from-sender, explicit EN/FR/AR, edit-preserves, legacy blank,
missing field, change-existing, payload shape; the AR-app/EN-mail,
AR-app/FR-mail, EN-app/AR-mail and FR-app/AR-mail combinations; guest-link
propagation and omission; sign-up language; and a render matrix over six device
profiles times three locales for both screens.

### Findings

- **Historical MINOR — resolved in the final bounded closeout.**
  `SkeletonDetail` overflowed a short landscape viewport. The shared component
  now scrolls only when its parent supplies a finite height; list-hosted uses
  keep their natural column layout. The old landscape exception is gone.
- **Historical MAJOR, not MINOR — resolved in the final bounded closeout.**
  Guest checkout sent no payer `email`. With transactional email enabled the
  server rejected every anonymous checkout before creating an attempt, so the
  launch-enabled guest rail could not work in its intended configuration.
- **Historical BLOCKER, not MINOR — resolved in the final bounded closeout.**
  Normal email sign-up required an Algerian `wilaya`, which blocked legitimate
  France/EU-side senders and travelers from the active mobile account path.
  The backend Google endpoint did not require it, but the Flutter application
  exposes no social-sign-in trigger, so that was not a launch workaround. The
  V1 specification contains no residence-wilaya requirement.

## Final bounded application closeout (2026-08-30)

This is a closeout pass over the three findings above, not a new product phase.
No provider, webhook, DNS record, production environment or deployment was
configured or activated.

### Sign-up domain correction

The wilaya control was stale Algeria-only onboarding. The account model already
allowed a blank value, but the normal sign-up serializer and Flutter form made
it mandatory. That field is not a KYC input and no matching, Journey, payment
or marketplace policy reads it. Actual V1 pickup and delivery locations carry
their country and region on delivery requests and Journeys.

Normal email sign-up now omits wilaya. Django accepts an omitted or blank value
and keeps validating a supplied two-character Algerian code for older clients.
Google registration was already optional; it now applies the same allowlist
validation when a legacy value is supplied. No speculative residence-country
or profile-region field was added. New accounts remain `BOTH`, so the same
France/EU-side or Algeria-side account can act as Sender, Traveler or switch
between those contexts. No migration was required because the model column was
already blank-capable.

### Guest payer receipt email

ShipTrip owns the receipt-email input before redirect; the hosted provider owns
payment credentials. The anonymous screen now requires and validates a
localized payer email, then sends only `provider` plus the trimmed `email` to
the existing guest checkout endpoint. The guest-link language snapshot still
selects receipt/failure/refund language; the payer does not gain a language or
identity mutation surface.

The server stores the address only on the payment attempt and never echoes it
from the guest response. The anonymous contract still exposes no Deal id,
counterparty, recipient, exact location, chat, dispute, refund, payout or
handover authority. Focused tests cover the enabled-email requirement, invalid
input, accepted input, minimal response, localized payment facts and all guest
authority denials.

### Shared responsive loading state

`SkeletonDetail` was a fixed natural-height `Column` placed directly into a
short finite viewport. The shared component now detects that finite constraint
and supplies its own vertical scroll root, while preserving the Phase 5C
spacing, shape and unbounded list-hosted behavior. A selected guest provider
also exposed the shared `AppCard` accent rail stretching inside an unbounded
`ListView`; the rail now takes the card's intrinsic height instead of requesting
infinite height.

Coverage includes 320-pixel narrow portrait, Android and iPhone safe areas,
large text, 844x390 landscape, and a deliberately short 844x240 landscape with
both a top bar and pinned footer. The recipient landscape test no longer
suppresses the old overflow.

### Closeout verification

- `dart format --set-exit-if-changed lib test` — clean, 112 files, 0 changed.
- `flutter analyze --fatal-infos` — no issues.
- `flutter test` — **205 passed**.
- Django account/auth regression suite — **29 passed**.
- Django guest checkout/email/privacy/authority suites — **20 passed**.
- Ruff — clean.
- Django system check — no issues.
- `makemigrations --check --dry-run` — no changes detected.

Final application finding state for this bounded pass: wilaya requirement
**BLOCKER resolved**; guest payer email **MAJOR resolved**; shared skeleton
overflow **MINOR resolved**. No application BLOCKER, MAJOR or MINOR finding from
the three-item closeout remains open. Provider credentials and the other
external release-activation prerequisites below remain intentionally untouched.

## Pre-launch release checkpoint (2026-08-30)

The release candidate now has an operator-triggered **Build Android** GitHub
Actions workflow. It derives artifact names from the authoritative Flutter
version (or an explicit RC label), accepts only a credential-free HTTPS API
origin, and produces a signed release APK plus AAB when the four documented
GitHub signing secrets are present. The keystore exists only in the runner's
temporary directory. A separately selected, clearly named debug APK remains
available for controlled installation before signing is configured; release
builds never fall back to the debug key.

Normal CI now includes production-profile fail-closed tests, Django deployment
checks, static route/link/CSP validation, and both Railway Caddyfile validation
in addition to the existing Flutter, Django/PostgreSQL, Ruff, migration/schema,
and Go gates. Root Railway health routing now targets `/readyz` rather than
liveness alone.

The seeded immutable Business Settings version 5 is the pre-launch provider
baseline: Stripe, Chargily, mock payments, new Chargily checkouts, and automatic
Stripe payouts are disabled. Transactional email dispatch also honors
`EMAIL_ENABLED=false` before touching either transport and retains the durable
outbox obligation for later replay. No provider credential or signing material
is stored in the repository.

Local release evidence after the final safety edits:

- Flutter format/analyze/tests: clean, **205 passed**.
- Django application suite: **987 passed**, 65 intentional skips.
- Ruff, Django system check, and migration drift: clean.
- Deployment fail-closed suite and production `check --deploy`: clean.
- Go format/build/vet/tests: clean.
- Static web validation: clean (8 HTML files, 1 stylesheet).
- Railway configuration JSON: valid.
- Local Android packaging is unavailable on this workstation because no
  Android SDK is installed; the GitHub runner is the authoritative packaging
  environment.

This checkpoint does not authorize public launch. Provider credentials,
provider webhooks, outbound email, Google Play submission, and public
announcement remain disabled or pending explicit operator action.

## Phase 8A — mobile reliability, performance and missing states (2026-08-31)

Phase 8A is implemented. This was a bounded mobile reliability pass; it did not
start the Phase 8B geography/location work, redesign the admin, activate a
provider, or replace the Phase 5C visual identity.

### Insets and compact layouts

The shared `AppScaffold` applied horizontal `SafeArea` only and assumed an app
bar, footer or shell navigation would always own both vertical insets. Welcome,
authentication and onboarding routes have no app bar, and ordinary surfaces
without a footer had no shared bottom owner, so their content could enter the
Android status/cutout or navigation/gesture regions.

`AppScaffold` now consumes the top system inset for app-bar-less or deliberately
behind-app-bar bodies and the bottom inset whenever no footer owns it. Footer
safe area, the docked shell navigation, `resizeToAvoidBottomInset`, and
`AppScrollPadding` continue to own their existing parts without double-padding.
The contract applies to welcome/onboarding, login/sign-up/password flows, Home,
Deliveries, Chat, Profile and the task/form routes built on the shared scaffold.
Sheets retain their existing modal safe-area handling. Coverage exercises
Android buttons, Android gestures, an iPhone-style home inset, narrow portrait,
844x390 landscape, 1.6x text, and a 280-pixel keyboard inset.

The same device matrix exposed a separate shared empty-state defect: a
full-surface `AppEmptyState` inside a sliver received an unbounded height and
asked a nested scroll view to fill infinity. It now lets the parent own
scrolling when height is unbounded, eliminating blank/exceptional list empties.

### Performance and Android artifact evidence

The reported slow artifact is a debug build, which carries JIT, assertions,
service-protocol and widget-inspection overhead and is not a production
performance measurement. The bounded code audit found no tab-switch refetch
loop (the indexed shell keeps tabs mounted), no repeated Chat request loop, and
the important lists already use lazy builders or have bounded result sets. No
useful motion or identity element was removed.

Two real paint costs were fixed. The full-screen `PaperGrain` painter is now
isolated by a repaint boundary, and the looping route trace no longer redraws
its static dashed path and city marks on every plane frame; the backdrop and
moving plane are separate paint layers. Reduced-motion behavior remains intact.

Android packaging evidence is deliberately split between observed and measured:

- The device-tested debug footprint is the tester's approximately **160 MB**
  observation. No ShipTrip debug APK file is present in this workspace, and a
  fresh local ARM64 debug build stops with `No Android SDK found`, so that number
  could not be independently re-measured here.
- The available signed universal release APK is **58,651,019 bytes**
  (**58.65 MB / 55.93 MiB**), SHA-256
  `149370e8ac386efe7352d3557f18cc5435510b1087fa72b08c4aca9741641451`.
  This AOT artifact is the realistic production-size evidence; a separate
  profile APK was not built on the SDK-less workstation.
- Its compressed native payload is the dominant contributor: x86_64
  **19.74 MiB**, ARM64 **18.32 MiB**, and ARMv7 **16.01 MiB**. The complete
  `country_flags` vector set is next at **1.15 MiB**; all other Flutter assets,
  fonts and Android resources are small. No required font, animation, package
  or asset was removed for a cosmetic size win.
- An ARM64-only APK was not built locally. Removing the other two ABI payloads
  from the measured universal artifact projects approximately **21.17 MB /
  20.19 MiB**, before build-specific ZIP differences. The operator-triggered
  Android workflow now defaults private phone-test APKs to ARM64, retains a
  universal choice, and still builds the full signed release AAB.

### Chat, empty/error states and Profile passport

Chat now calls the server's authoritative eligibility pre-flight before message
history. Loading, intentional inbox/thread empty, `payment_pending`, ready,
offline and retryable failure states are distinct. An unfunded Deal is explained
as a payment gate (with a payment action when the Deal id is known), not rendered
as a raw 402/403-like failure, and history is not requested before funding.
Closed funded conversations remain readable while their composer stays blocked.

Chat, Notifications, Payouts and Ratings now render their intentional shared
empty language without the unbounded-list failure. Deliveries and Home
discovery/matching already had explicit loading, empty, error and ready states,
so they were verified rather than redesigned. The user-facing failure audit
found no screen rendering `DioException`, `serverDetail`, HTTP status or backend
codes. Structured codes remain internal for control flow and map through the
shared localized feedback/retry component; regression coverage proves both a
network-offline state and a `capacity_exceeded` conflict hide raw details.

The passport account concept was recovered from git revision `1640a45`, not
recreated from memory. Its dark passport/stamp composition is restored with
current authoritative name/email, KYC and email trust markers, Sender/Traveler
capabilities, an exact server-filtered completed-Deal count, a clearly labeled
recent received-rating average, join date and communication language. The old
hard-coded member number, demo statistics and 12,400 DZD wallet were not
restored; no internal id is exposed. Missing or failed optional facts render
honest empty/unavailable values rather than invented data.

### Verification and remaining findings

- `dart format lib test` — clean, 115 files.
- `flutter analyze --fatal-infos` — no issues.
- `flutter test` — **224 passed** (205 baseline plus 19 Phase 8A tests).
- Focused coverage includes all requested safe-area, Chat, Notifications,
  Payouts, Ratings, passport populated/partial, structured-error and network
  cases, plus the authoritative paginated completed-count contract.
- Impeccable UI detector — no findings on the changed UI targets.
- Workflow YAML parses; `git diff --check` is clean.

No Phase 8A application **BLOCKER**, **MAJOR** or **MINOR** defect remains known.
Release/profile frame timing and the exact ARM64 APK size remain hardware/build
evidence gaps, not claimed measurements; the GitHub ARM64 option is the path to
close them on the next explicitly authorized device build. Existing external
release blockers below are unchanged.

## Phase 8B — authoritative geography catalogue (2026-08-31)

Phase 8B is implemented as a backend data foundation only. It does not start
the Phase 8C Flutter country/place picker, alter Journey/DeliveryRequest
matching, change exact-coordinate Location records, redesign the admin, or
activate a provider.

The new `locations.Country` and `locations.Place` catalogue uses stable
`(source, source_id)` identities with an internal immutable primary key,
canonical and normalized names, parent administration, optional coordinates,
active state and source/version metadata. `Place` represents administrative
regions, localities/communes and airports. `PlaceAlternateName` stores only
source-backed localized names. `AirportLocalityMapping` is an explicit,
inspectable relationship for an airport's commercially served locality;
physical context remains on the airport's parent/metadata and is never guessed
from a display name. Existing user-owned `Location`, legacy `trips.Airport`,
Journey, JourneyLeg and DeliveryRequest relationships remain intact.

`manage.py import_geography --manifest ...` is transactional, rerunnable and
source-identity based. It preserves primary keys across renames, updates
metadata, supports additions and can inactivate missing records only for
explicitly refreshed sources. `tools/geography/normalize_sources.py` downloads
fixed allow-listed sources on operator request and produces the normalized
manifest; bulk geography is intentionally not embedded in migrations.

The verified 2026 manifest contains 56,134 places and 3,833 source-backed
alternate names. Coverage is 69 Algerian wilayas and 1,541 communes (including
wilayas 59–69), 34,875 INSEE communes plus 119 parents, 8,132 INE
municipalities plus 52 provinces/19 autonomous communities, and 10,749
Destatis AGS municipalities plus 16 states/401 district parents. Germany
excludes 194 uninhabited
municipality-free `Textkennzeichen=66` rows and retains the two inhabited type
65 rows. The conservative OurAirports policy yields 161 scheduled-service
airports (DZ 31, FR 49, ES 42, DE 39) and excludes closed/unsupported types and
all unscheduled military, private and general-aviation records.

Algeria now parses the official ONS CGN 2021 PDF for all 1,541 stable commune
W/C identities and the official JORADP Law 26-06 PDF for every amended mother
and new-wilaya commune list. Each ONS identity must reconcile exactly once and
each Law 26-06 list must match exactly. The third-party JSON contributes only
coordinates, Arabic names, daïra hints and reviewed spelling reconciliation;
its five-digit `post_code` is not represented as an official ONS identifier.
France uses INSEE COG 2026, Spain the INE register at 1 January 2026, and
Germany the Destatis GV-ISys 30 June 2026 extract.

The public API is bounded and read-only: `GET /api/geography/countries` and
paginated `GET /api/geography/places` support country, query, place type,
parent and active filters. Responses include stable IDs, parent context,
airport labels/codes and served-locality context when an explicit mapping is
present. Search normalization is Unicode-aware (case/accents/combining marks,
hyphens/apostrophes and Arabic retained) and searches canonical plus
source-backed alternate names. Catalogue/admin indexes cover source identity,
country/type/parent/active and normalized names. PostgreSQL partial
`varchar_pattern_ops` indexes support the default active prefix search without
requiring another extension; one-character queries use exact matching and
punctuation-only queries are rejected. Querysets use select/prefetch to avoid
N+1 responses.

Every airport has a canonical administrative parent through a reviewed
country-specific ISO-region crosswalk. The versioned mapping file retains the
seven reviewed commercial contexts (ALG, CDG, ORY, BCN, MAD, FRA and MUC) plus
separate physical links for ALG, CDG, ORY and BCN. Phase 8C expands this into
161 active primary served mappings through deterministic source-identity and
municipality resolution. No display-name inference occurs in the Django
importer.

Focused import/API/data-quality tests cover idempotence, rename preservation,
source-scoped retirement, invalid boundary values, hierarchy cycles, Unicode,
same-name context, inactive filtering and mapping safety. Phase 8C adds an
exact coverage gate: every selectable airport has one active primary served
locality, and an unresolved airport is unavailable for matching. OurAirports
municipality hints are never promoted without deterministic catalogue
resolution.

Final Phase 8B verification:

- the Phase 8B baseline normalizer completed with 4 countries, 56,134 places,
  3,833 alternate names and 11 reviewed mappings; nine input artefacts have recorded SHA-256
  checksums, and the focused PDF/airport normalizer suite passed 3/3;
- the complete manifest imported transactionally into PostgreSQL 16 and a
  populated rerun completed in about 143 seconds with counts unchanged;
  Aflou retained internal ID 56106 / ONS source ID `0319` while remaining
  parented to wilaya 59;
- focused final geography import/API tests passed 14/14 on SQLite and 14/14 on
  PostgreSQL; the wider 251-test Locations/Trips/Parcels/Matching suite was
  green on both databases (SQLite: 39 expected skips; PostgreSQL: 34 expected
  skips);
- PostgreSQL `EXPLAIN (ANALYZE, BUFFERS)` used the partial normalized-name
  pattern indexes for canonical and alternate-prefix branches (0.256 ms in the
  local 56k-row rehearsal); API serialization is held to three queries by a
  regression assertion;
- Ruff, Django check, `makemigrations --check --dry-run`, and `git diff
  --check` are clean. Two UTF-8 PostgreSQL schema exports were byte-identical
  at SHA-256 `B16C470B0D25FB851AABE98D01AD6B1778CB90B31A742A670C9C1092AF1FCAA3`.
  The sqlc query directories remain empty, so no generated Go repository was
  changed.

## Phase 8C — canonical location UX and locality-based matching (2026-09-01)

Phase 8C is implemented end to end. Active V1 creation now follows
**Country → canonical Place → optional preferred exact point** for both Sender
requests and Traveler journeys. Flutter receives only bounded server-side
catalogue search results; it never downloads the 56k-row catalogue, creates
matching cities, or infers a locality from a pin. The same canonical Place
references are used by `DeliveryRequest`, `Journey`, and ordered `JourneyLeg`.

Matching locality is derived authoritatively from the selected `Place` (rather
than snapshotted or copied): a locality/municipality/commune resolves to itself,
and an airport resolves through its one active primary `SERVED`
`AirportLocalityMapping`. This keeps the identity stable and avoids drift if a
reviewed mapping changes. Compatibility compares only these canonical locality
IDs. Preferred coordinates, free-text labels, nearby cities, radius, and
geographic detour do not change basic V1 compatibility. Ordered multi-leg
subroutes, mode semantics, capacity, proof requirements and start/end leg
selection remain intact.

Every one of the 161 selectable scheduled-service airports has a deterministic
primary served-locality mapping: DZ 31, FR 49, ES 42, DE 39. The normalized
manifest contains 165 mappings total (161 served + four physical context
rows). `tools/geography/airport_locality_mappings_2026.json` seeds seven
high-impact served-city policies and four physical contexts. Of the remaining
154 airports, 81 use the maintained stable-ID source-context override table
for commercial semantics or ambiguous municipality nomenclature, and 73 use a
unique authoritative/source municipality-context resolution. Display-name
guessing is rejected. CDG and ORY both resolve to canonical Paris; ALG resolves
to the canonical Alger Centre commune under the reviewed commercial Algiers
policy. An airport that cannot be resolved is not selectable for matching.

Preferred exact points retain the legacy `Location` model but must reference
the selected canonical Place. The backend uses the existing route-provider
reverse-geocoding abstraction to validate country/locality context, ignores
client-supplied provider metadata, fails safely when provider context is
insufficient, and never promotes a point into a new city. Exact address,
coordinates, provider metadata and private notes remain hidden before the
funded Deal state under the existing backend authorization rules.

Legacy schema-2 requests and schema-1 journeys remain readable for private
fixtures and bounded compatibility tests. They are not guessed or backfilled
from arbitrary historical pins. The active DeliveryRequest and Journey write
contracts reject location-only payloads, and the active Location write API
requires `canonical_place`: all new V1 records use canonical Place references,
while optional Location IDs must be scoped to those Places. No unrelated
accounts or lifecycle/finance records were deleted.

Mobile localization covers English, French and Arabic, including RTL. Picker
states include loading, empty, error/retry, selected, debounce and stale
request cancellation; changing country clears incompatible results. Optional
preferred points can be skipped or marked flexible. Flight legs require airport
endpoints; DRIVE legs accept catalogue localities or airports.

Phase 8C migrations are additive and Django-owned:
`locations.0005_location_canonical_place`,
`parcels.0008_remove_deliveryrequest_parcels_delivery_schema_ver_and_more`, and
`trips.0007_remove_journey_journey_distinct_endpoints_and_more`. The
PostgreSQL `contracts/sql/schema.sql` was regenerated after applying them;
sqlc query directories remain empty, so no generated Go repository changed.

Verification:

- Django canonical/location/trips/parcels/matching plus posting-deposit
  integration suite: **97 passed** on SQLite and **97 passed** on PostgreSQL.
  The broader matching plus posting-deposit suite passes **181 tests with 29
  expected skips**.
- Flutter targeted Phase 8C picker/contract tests: **15 passed**; full mobile
  suite: **239 passed**; `flutter analyze --fatal-infos`: clean; Dart format:
  clean.
- Geography normalizer: **4 countries, 56,134 places, 3,833 alternate names,
  165 airport mappings**; normalizer unit tests **3/3**; exact airport coverage
  **161/161**.
- `manage.py check`, `makemigrations --check --dry-run`, Ruff on changed
  backend/tools paths, schema export and `git diff --check`: clean. Two local
  PostgreSQL schema dumps differed only in pg_dump's per-run nonce/version
  headers and were byte-identical after the repository's documented narrow
  normalization; sqlc generation is an explicit no-op because all query
  directories are empty.

Stripe, Chargily, email, map/geocoding and other external providers were not
activated.

### Phase 8D-V — admin visual and taste pass (2026-09-02, Claude)

A presentation-only pass over the Phase 8D operations console. No business
logic, no financial locking, no matching, no permission check and no migration
was touched; no provider was activated; no Flutter file was opened; Phase 8E
was not started. The work was reviewed against representative seeded states
rather than blank pages, using a new local dump of all 34 console screens.

**What was wrong.** The Phase 8D information architecture was right, but it
read as Django admin wearing a new palette. Two `.st-` layers fought Django's
own variables at the wrong specificity; the navigation was a wrapping band of
twenty flat links with no current-section anchor; routes printed as
`Paris · CDG · France → Algiers · ALG · Algeria` run-on strings; money sat in
prose; the "attention" panel disappeared when it was empty; a KYC operator met
tiny thumbnails and a generic dropdown instead of an evidence viewer and two
obvious decisions; and commission, deposit and FX were raw numeric fields with
no read-back.

**Design system.** `apps/core/static/shiptrip/admin.css` was rewritten as a
single token layer (canvas / surface / surface-2 / surface-3, three ink tones,
two line weights, six status families each with text/ground/line, accent, seal,
plus scales for radius, spacing, shadow and type). Both themes are defined for
every token. The shell keeps a dark ground in both themes, so it now carries
its own `--st-shell-fg` / `--st-shell-muted` that do not invert with the
content palette.

**Navigation.** One row of ten sections with icons and a seal-coloured current
underline, plus a second band listing the destinations inside the current
section only. Because a section tab alone would hide its siblings, the overview
carries a role-filtered map of every destination the signed-in role can open,
so nothing is more than one click from the landing page.

**Screens.** Overview separates raised queues from cleared ones without hiding
either. KYC and flight proof lead with large evidence, a waiting-time alert and
a distinct Approve / Reject pair in a bordered decision card. Journeys, Deals
and proofs render routes as a node ribbon with airport codes and per-leg mode.
Deal and Dispute lead with money. Settings explains commission as a worked
euro example from the real pricing engine, the deposit as a floor/rate/ceiling
band, and the Chargily rate as `1 EUR = 150.00 DZD` with the euro obligation
still named as canonical. System reports Healthy / Degraded / Needs attention
with a dot plus words, and still refuses to imply a worker heartbeat.

**Defects found and fixed during the pass** (all presentation-layer):

- Django's `#container` is a viewport-height column flex box, so the header
  shrank back to one line on any page tall enough to overflow, clipping the
  navigation under the breadcrumbs. Fixed with `flex: 0 0 auto`.
- Django's `responsive.css` turns the header into a column below 1024px, which
  gave the full-width navigation a 100% *height* basis and broke the shell at
  laptop and tablet widths. Beaten with a `body`-scoped rule.
- `#header a:link` outranks a two-class selector, so navigation links took
  Django's header link colour; in dark mode that resolved to dark ink on the
  dark shell and the whole navigation went invisible. Fixed by stating the
  navigation's own `:link`/`:visited` colours.
- A Django `{# … #}` comment cannot span lines (`tag_re` has no `DOTALL`).
  Three multi-line comments would have rendered as literal text on the page;
  one already did. All converted to `{% comment %}`.
- `--st-ink-3` failed WCAG AA at 11px on the sunken surface (3.58:1), which
  covered every table header, field label and secondary line in the console.
  Darkened to `#55636e`; the whole console now passes AA in both themes.
- The Approve button used `--st-ok`, a *text* token that inverts to a light
  mint in dark mode, putting white on mint at 2.24:1. Given its own
  `--approve-button-bg`, dark enough for white text in both themes.
- The overview's queue counts never reached the template, so the page said
  "Every queue is empty" beside "7 queues with work waiting".
- Evidence was listed twice on the KYC screen — once as a preview, once as a
  link row. The link row is now shown only for files that cannot be previewed.

**Accessibility.** Every rendered console page was audited with a computed
contrast sweep in both themes; the sweep reports zero failures. Status is never
colour alone (chip = dot + word); table headers are scoped; the search and
filter controls are labelled; `:focus-visible` is a 3px ring; destructive
actions are visually distinct from confirmations; `prefers-reduced-motion` is
honoured.

Files: `apps/core/static/shiptrip/admin.css` (rewritten),
`apps/core/admin_display.py`, `apps/core/templatetags/shiptrip_admin.py`,
`apps/admin_panel/console_views.py`, `apps/admin_panel/console_presenters.py`,
`apps/admin_panel/console_forms.py`,
`apps/admin_panel/tests/test_phase8d_console.py`, all fifteen
`templates/admin/console/*.html` (including a new `_route.html` partial),
`templates/admin/base_site.html`, `templates/admin/index.html`,
`tools/preview/dump_console_pages.py` (new),
`tools/preview/enrich_admin_preview.py` (new), `tools/preview/README.md`,
`docs/ADMIN_OPERATIONS.md`, `.claude/launch.json`.

Verification: full SQLite suite **1074 passed** (80 skipped);
PostgreSQL `admin_panel` + `core` + `disputes` + `kyc` + `accounts`
**206 passed**; `apps.admin_panel` **43 passed**; Ruff clean;
`manage.py check` clean; `git diff --check` clean. Four console tests were
updated where they asserted on copy this pass deliberately changed, and one
where it depended on an unescaped `&` the templates no longer emit.

Known remaining items, none blocking:

- **MINOR** — `apps/core/admin_display.py` and roughly thirty pre-existing
  files are not `ruff format` clean. The project gate is `ruff check`, which
  passes; this pass did not reformat files it only edited.
- **MINOR** — the brand seal's single letter sits at 3.9:1 on the terracotta
  disc. It is `aria-hidden` decoration rather than content, so it is exempt,
  but a darker disc would clear AA if the mark is ever made meaningful.
- **MINOR** — the payments table's provider column is sized for the seeded
  "Mock (tests/local only)" label and will read tighter than it will in
  production, where the values are "Stripe" and "Chargily".

### Phase 8D-F — finance refund/reconciliation deadlock repair (2026-09-02)

A focused concurrency repair for the MAJOR Phase 8D-R handed off. No payment,
pricing or refund product semantic changed, no migration was added, no provider
was activated, no Flutter file was touched, the admin visual redesign was not
started and Phase 8E was not started.

**The deadlock, reproduced.** `RefundRaceTests.
test_a_refund_racing_a_reconciliation_never_exceeds_the_capture` was run
repeatedly against a local PostgreSQL 16.2 cluster with `log_statement = all`,
`log_lock_waits = on` and `deadlock_timeout = 200ms`. It deadlocked in 2 of the
first 5 runs, and PostgreSQL reported:

```
ERROR:  deadlock detected
DETAIL: Process 4396 waits for ShareLock on transaction 2818; blocked by 14900.
        Process 14900 waits for ShareLock on transaction 2819; blocked by 4396.
        Process 4396: COMMIT
        Process 14900: SELECT ... FROM "finance_payment_attempt" ...
CONTEXT: while locking tuple (0,2) in relation "finance_payment_order"
         SQL statement "SELECT 1 FROM ONLY "public"."finance_payment_order" x
                        WHERE "id" = $1 FOR KEY SHARE OF x"
```

**The two transactions.** The statement log named them exactly.

* **A — `finance.services.request_refund` (pid 14900).** `_order_for_update` ->
  `PaymentOrder` id 1 `FOR UPDATE`; then `PaymentAttempt` id 1 `FOR UPDATE`.
  Order then attempt: the canonical direction.
* **B — `finance.services._persist_provider_event` (pid 4396),** the short
  transaction the webhook opens before any business row.
  `INSERT INTO finance_provider_event (..., attempt_id, order_id, ...)`, then a
  `ScheduledJob` insert, then `COMMIT`. It asks for no row lock at all.

**The cycle.** Django emits every foreign key as `DEFERRABLE INITIALLY
DEFERRED`, so B's foreign keys are not checked when the `INSERT` runs; they are
checked at `COMMIT`, as one `SELECT 1 FROM <parent> WHERE id = $1 FOR KEY SHARE`
per constraint, fired in constraint-creation order. For
`finance_provider_event` that order is `finance_payment_attempt` first and
`finance_payment_order` second — model field order, chosen by no application
code.

```
A holds  PaymentOrder   FOR UPDATE     ->  waits for PaymentAttempt FOR UPDATE
B holds  PaymentAttempt FOR KEY SHARE  ->  waits for PaymentOrder   FOR KEY SHARE
```

`FOR KEY SHARE` conflicts with `FOR UPDATE`, so each transaction blocks the
other and PostgreSQL kills B. The failure is intermittent because it needs B to
reach `COMMIT` inside the window where A holds the order row and has not yet
taken the attempt row.

**Root cause.** *Not* the ordering Phase 8D-R suspected. `reconcile_attempt`
does take `lock_payment_order_aggregate` before `PaymentOrder`, and
`request_refund` takes only `PaymentOrder -> PaymentAttempt`, but a suffix of the
canonical order is not an inversion, and the two never met in this deadlock —
`_persist_provider_event` commits before `reconcile_attempt` ever runs. The real
inverted order was the database's referential-integrity trigger order, and no
amount of reordering application statements can fix it, because one of the two
orders does not belong to the application.

**Canonical order, restated with a strength rule.** The order in
`apps/core/financial_locks.py` is unchanged:

```
DeliveryRequest/ParcelRequest -> Match -> Offer -> BoostPurchase -> Journey
  -> JourneyLeg -> KYC/proof/User witnesses -> Deal -> DealLegAllocation
  -> DealRecipient -> DealHandoverCode -> Dispute -> Rating -> PaymentOrder
  -> PaymentAttempt -> PaymentProviderEvent -> PaymentRefund -> Payout
  -> ledger -> ScheduledJob
```

What is new is the mode. **Every row in that graph is now acquired
`FOR NO KEY UPDATE`** — `select_for_update(no_key=True)` — never a bare
`select_for_update()`. PostgreSQL's row-lock conflict matrix is the whole
argument: `FOR KEY SHARE` conflicts with `FOR UPDATE` and with nothing else,
while `FOR NO KEY UPDATE` still conflicts with `FOR SHARE`, `FOR NO KEY UPDATE`
and `FOR UPDATE`. Two writers therefore still exclude each other exactly as
before, and a deferred foreign-key check no longer waits on either of them. The
stronger mode buys only the right to delete a locked row or change its primary
key; no writer in this graph does either — every row here is append-only or
updated in place — so nothing was given up. This removes the whole class of
implicit reverse edges in one move, including two more the audit found:
inserting a `finance_ledger_entry` or a `notification_outbound_message` while
holding a `PaymentOrder` lock takes `FOR KEY SHARE` on `deals_deal` at commit,
which inverts against every writer that enters through `lock_deal_aggregate`.

**Sibling paths audited.** Refund request, provider-event persistence, webhook
processing, `reconcile_attempt`, payment success and failure, manual refund
settlement, `refund_order_in_full`, deposit-expiry refund, order cancellation
and close-to-collection, guest links, payout release and freeze, dispute
settlement and manual payout were all read for application-level inversion.
None was found: every one of them either enters through `lock_deal_aggregate` /
`lock_payment_order_aggregate` or takes a suffix of the canonical order.
`_fund_deal_if_covered` and `apply_posting_deposit_credit` re-enter
`lock_deal_aggregate` from inside a finance transaction, and both callers
already hold that aggregate, so the re-lock is a no-op rather than a reverse
edge. `BusinessSettingsVersion` was added to the rule because
`PaymentOrder.business_settings_version` and
`PaymentAttempt.fx_settings_version` reference it, so an FX/pricing activation
held a lock a concurrent checkout's commit needed.

**One idempotency strengthening.** `request_refund` promised idempotency on the
key but only looked the key up *before* opening its transaction. Three
simultaneous operator clicks therefore all missed it, one created the refund and
the other two were refused with `RefundExceedsCapture` — safe for the money,
wrong as an answer. The key is now re-read inside the transaction, after the
order row is held, so simultaneous duplicates receive the same refund the
sequential retry already received. No amount, status, provider behaviour, or
error surface for a genuine over-refund changed.

**Financial safety.** Nothing was unlocked and no lock was removed. Every writer
still serializes on the same rows in the same order; only the conflict class
against foreign-key references changed. The layered over-refund guard is
untouched: `request_refund` refuses to exceed the attempt's capture,
`_recompute_order_money` clamps `refunded_eur_cents` to `paid_eur_cents`, and
the `fin_order_refund_within_capture` check constraint holds at the database.
EUR-cent canonical truth, Stripe EUR settlement, the Chargily DZD conversion
model and its frozen per-attempt FX rate, traveler reward, ShipTrip fee, posting
deposit, guest payment, payment protection and refund policy are all unchanged.

**Concurrency evidence.** New module
`apps/finance/tests/test_phase8df_lock_order.py`, 14 tests:

- **Structural contract (2).** An AST guard over the ten modules that lock
  canonical-graph rows asserts every `select_for_update` passes `no_key=True`,
  and a second test asserts the contract is still written beside the helper.
- **Emitted SQL (2).** `lock_payment_order_aggregate` and `lock_deal_lifecycle`
  are run under `CaptureQueriesContext`; every locking statement must say
  `FOR NO KEY UPDATE` and none may say a bare `FOR UPDATE`.
- **A — refund vs reconciliation (3).** The reproduction, asserting the webhook
  answers 200 rather than the 500 a `DeadlockDetected` becomes; a **30-round**
  repeated stress on one order and attempt; and a full refund followed by a
  racing one-cent refund that must be refused.
- **B — webhook vs refund (1).** A first-time capture on a second attempt
  landing while the first attempt is refunded. Every succeeded attempt ends
  either applied or carried unapplied and fully obligated for refund.
- **C — duplicate refunds (2).** Two partial refunds that both fit, and three
  simultaneous identical operator requests returning one obligation.
- **D — reconciliation concurrency (3).** Three distinct provider events for one
  attempt captured once; reconciliation after webhook; webhook after
  reconciliation.
- **E — failure/rollback (1).** A refund transaction killed mid-flight leaves no
  refund row, no ledger fact and no money-column drift, and the attempt is still
  refundable afterwards.

Every race asserts the ledger transactions the order touched still net to zero.

Verification:

- **Negative control.** Reverting only the `PaymentOrder` and `PaymentAttempt`
  lock modes in `_order_for_update`/`request_refund` reproduces the deadlock in
  **6 of 6** runs, and the new test fails deterministically with
  `Round 0 lost the provider event: the webhook answered 500`. The original test
  passed silently on those same runs, because the webhook view converts every
  exception into a 500 and the assertion it made still held. Restoring the
  repair returns it to **0 of 6**.
- **Stress.** `RefundRaceTests` — both tests, so 80 executions of the racing
  pair — ran **40 consecutive times: 40 passed, 0 failed, and 0 deadlocks
  recorded in the PostgreSQL server log.** A separate earlier loop ran the
  single original test **12 times, 12 clean**. Before the repair the same test
  deadlocked in 2 of the first 5 runs and then in the very next run.
- `apps.finance` on PostgreSQL 16: **356 tests, OK.**
- New module on PostgreSQL: **14 passed**; on SQLite **2 passed, 12 skipped**
  (`no_key` is a silent no-op where `has_select_for_update` is false, and the
  concurrency classes are correctly gated).
- **Full Django suite on PostgreSQL 16: 1074 tests, OK, 34 skipped — zero
  failures and zero errors.** Phase 8D-R ended this gate at 1060 tests with
  1 error and 34 skips; that error was this deadlock, and no previously
  hidden failure appeared behind it. The test count rose by exactly the 14
  added here and the skip count is unchanged.
- Full Django suite on SQLite: **1074 tests, OK, 80 skipped** (the 1060/68
  Phase 8D-R baseline plus this phase's 14, of which 12 correctly skip).
- Phase 8D integration re-verification on PostgreSQL — `admin_panel`, `kyc`,
  the admin dashboard, `disputes`, `finance`, `payments` and `deals`
  together: **514 passed** (8D-R's 500 plus this phase's 14). Admin console,
  finance, payments, refunds, payouts, disputes and verification/settings
  are unchanged in behaviour and no admin visual was touched.
- **One stale sibling guard was updated, not weakened.** Phase 8D-R's
  `CanonicalOfferLockShapeTests._assert_locks_are_well_formed` selected locking
  statements by the literal substring `FOR UPDATE`, which `FOR NO KEY UPDATE`
  does not contain, so the first full run reported `0 not greater than 0: this
  backend locks rows, so the negotiation must emit locks`. The helper now
  recognises both modes and still asserts the rule it exists for — a locking
  query over a `LEFT OUTER JOIN` must name its tables — against whichever mode
  the statement used. `apps.matching.tests.test_phase8dr_offer_locks`:
  **17 passed** on PostgreSQL afterwards, and the guard is still non-vacuous.
- `ruff check .`, `manage.py check`, `makemigrations --check --dry-run` and
  `git diff --check`: clean. **No migration was added**; a lock-mode repair
  changes no schema, so `contracts/sql/schema.sql` and sqlc regeneration do not
  apply.

Local harness note: the workstation's embedded PostgreSQL data directory lived
under the user temp folder and had lost `global/pg_control` between phases. It
was re-initialised under LocalAppData and reached through the existing
`SHIPTRIP_TEST_PGDATA` override that `config/settings/test_pg.py` already
honours. No repository file changed for it.

Remaining findings:

- **MINOR — legacy rails still lock `FOR UPDATE`.** The unrouted legacy views in
  `apps/matching/views.py`, `apps/verification/services.py` (refused for V1
  Deals), `apps/wallet` and `apps/payments` were deliberately left out of the
  strength rule and out of the structural guard's module list. They cannot
  execute against a V1 Deal, and Phase 8D-R already recorded the first two as
  removal candidates. They belong to the Phase 8E cleanup, not to this repair.
- **MINOR — `AdminInvitation` and `OutboundMessage`** are still locked
  `FOR UPDATE` and are outside the canonical graph. Neither is a foreign-key
  parent of a finance row, so neither can produce this cycle.
- The Phase 8D-R MINORs (`_covered_legs` dead code, unrouted legacy matching
  views), the Phase 8D telemetry MINOR and the three Phase 8C MINORs are
  unchanged and were deliberately not touched.

Phase 8D-F files: `apps/core/financial_locks.py`,
`apps/core/business_settings.py`, `apps/finance/services.py`,
`apps/finance/jobs.py`, `apps/finance/payout_release.py`,
`apps/finance/settlement.py`, `apps/parcels/services.py`,
`apps/disputes/services.py`, `apps/trips/services.py`,
`apps/matching/v1_services.py`, `apps/admin_panel/services.py`,
`apps/admin_panel/views.py`, `apps/admin_panel/console_views.py`,
`apps/admin_panel/management/commands/bootstrap_super_admin.py`,
`apps/accounts/views.py`, `apps/finance/tests/test_phase8df_lock_order.py`
(new), `apps/matching/tests/test_phase8dr_offer_locks.py` (the stale guard above)
and this status document. Nothing else in the working tree was modified.

### Phase 8D-R — PostgreSQL matching lock repair (2026-09-02)

A focused transaction/query repair for the blocker Phase 8D handed off. No
matching rule, price, money semantic, API contract, migration or admin visual
was changed, no provider was activated, no Flutter file was touched, and
Phase 8E was not started.

**Blocker.** On PostgreSQL the V1 sender-offer transaction could not create a
single offer:

```
django.db.utils.NotSupportedError:
FOR UPDATE cannot be applied to the nullable side of an outer join
```

(`psycopg.errors.FeatureNotSupported`), raised while locking the covered
`JourneyLeg` rows in `apps/matching/v1_services.py`. Reproduced with
`apps.matching.tests.test_v1_matching.V1NegotiationConcurrencyTests` against a
local PostgreSQL 16 cluster: both tests errored inside `setUp`, at the very
first `create_sender_offer` call.

**Root cause.** `JourneyLeg.origin` and `JourneyLeg.destination` became
nullable with Phase 8C canonical geography, so
`select_related("origin", "destination")` compiles to two
`LEFT OUTER JOIN "locations_location"` clauses. The leg lock in
`_create_sender_offer_locked` and `_counter_offer_locked` was a bare
`select_for_update()`, which emits a trailing `FOR UPDATE` covering every table
in the query — including the nullable side of those joins. PostgreSQL rejects
that form outright. `_accept_offer_locked` already used
`select_for_update(of=("self",))` and was unaffected, which is why acceptance
paths looked healthy while every offer creation failed. The neighbouring
`DeliveryRequest` locks were likewise already scoped with
`of=("self", "parcelrequest_ptr")` and compile correctly despite their own
nullable `pickup_location`/`delivery_location` joins.

**Why SQLite never exposed it.** The SQLite backend reports
`has_select_for_update = False`, so Django drops the locking clause before the
query is compiled — `select_for_update()` is a silent no-op there and no
`FOR UPDATE` is ever emitted. The dedicated concurrency classes are
additionally gated on `@skipUnlessDBFeature("has_select_for_update")`, so no
SQLite run could reach the statement even in principle. The repository's CI
Django job does run on PostgreSQL 16, but the Phase 8B–8D canonical-geography
work is still uncommitted, so CI has never seen this tree.

**Repair.** One documented helper, `_lock_journey_legs(journey)`, now performs
the leg lock for creation, counter and acceptance with
`select_for_update(of=("self",))`, emitting
`... FOR UPDATE OF "trips_journey_leg"`. The locked set is unchanged in intent:
the per-segment capacity rows the transaction actually writes. The read-only
`Location` rows — which this statement could never have locked, and which no
caller meant to lock — are simply read through the same join. The identical
latent defect was found by audit and repaired in the unrouted legacy
`OfferAcceptView` (`Match.select_related("trip")`, also nullable). No other
`select_for_update` call site in the monolith joins to a nullable relation.

**Transaction safety.** Nothing was unlocked to make the query compile. Before
the repair PostgreSQL took no leg lock at all, because the statement never
executed; after it, the leg rows are locked on that backend for the first time.
The lock order is unchanged and consistent across every writer:

```
DeliveryRequest (+ ParcelRequest base) → Match → Offer → Journey → JourneyLeg
  → KycSubmission → JourneyLegProof → User
```

Creation takes request → journey → legs and then inserts its Match/Offer, so it
never holds a negotiation row lock ahead of the journey; `counter_offer`,
`accept_offer` and `core.financial_locks.lock_deal_aggregate` approach the same
rows in the same direction. The request-row lock still serializes competing
writers for one request, the `match_unique_pending_journey` partial unique index
still makes a duplicate pending Match impossible, and the post-lock re-reads of
request status and journey status are still what decide — not the pre-lock
preflight.

**Regression coverage.** `apps/matching/tests/test_phase8dr_offer_locks.py`
(new, 17 tests) exercises the repaired path over the production shape: a
canonical Paris → Jijel request against a CDG → ALG → Jijel FLIGHT + DRIVE
journey whose legs carry `origin_place`/`destination_place` only and no
`Location` rows at all. It covers a valid offer with the correct start/end
legs, Match and Offer contents and the OFFER_CREATED event; wrong sender;
closed request; inactive journey; self-match; the target-traveler restriction;
canonical locality identity (a metres-away twin Paris is refused while the real
one is accepted, so proximity can never stand in for identity); an invalid leg
range; counter; and acceptance allocating both legs. Two tests flip request and
journey state *between* preflight and lock to prove the locked re-read decides.
A structural guard asserts that every `FOR UPDATE` the negotiation emits names
its tables whenever the query outer-joins. Three PostgreSQL-only concurrency
tests prove the lock is real: an in-flight proposal blocks a competing
`JourneyLeg` capacity write until commit (and the same write succeeds
afterwards), two racing proposals on one request/journey leave exactly one
pending Match, and two requests sharing one journey both settle without
deadlock.

Verification:

- The new module fails **8 of 17** against the pre-repair code and passes
  **17/17** on PostgreSQL; on SQLite it is **14 passed, 3 skipped** (the
  concurrency class is correctly gated).
- `apps.matching` + `apps.parcels` + `apps.trips` on PostgreSQL: **251 passed,
  34 skipped** (234 existing plus the 17 new; every skip is a retired legacy
  Trip/DZD path). `apps.matching.tests.test_v1_matching` alone: **18 passed**.
- Full Django suite on PostgreSQL 16, **before** the repair: 1043 tests,
  **413 errors**. The exact `FOR UPDATE cannot be applied to the nullable side
  of an outer join` message appears **826** times, across `finance` (209),
  `disputes` (47), `matching` (42), `handover` (40), `notifications` (33),
  `deals` (22), `ratings` (15), `admin_panel` (4) and `core` (1). Phase 8D's
  66 errors were a 102-test slice of this same cascade.
- Full Django suite on PostgreSQL 16, **after** the repair: 1060 tests,
  **1 error, 34 skipped** — the cascade is gone, and the one remaining error is
  the independent finance deadlock recorded below.
- Phase 8D integration re-verification on PostgreSQL — `admin_panel`, `kyc`,
  the admin dashboard, `disputes`, `finance`, `payments` and `deals` together:
  **500 passed**. Matching no longer poisons the integration run.
- Full Django suite on SQLite after the repair: **1060 tests, all passed,
  68 skipped**. Nothing regressed on the fast backend.
- `ruff check .`, `manage.py check`, `makemigrations --check --dry-run` and
  `git diff --check`: clean. **No migration was added** — this was a query and
  locking repair, and `contracts/sql/schema.sql` is untouched by it, so no
  schema or sqlc regeneration applies.

Local test-harness note: `config/settings/test_pg.py` is the gitignored local
PostgreSQL runner. It lacked the throttle-rate override that
`config/settings/test_local.py` and the CI Django job both carry, so a long run
tripped the 60/min anon budget and reported 429s as `apps.accounts` failures.
The same documented override was added to that local file; no repository file
and no product throttle changed.

Remaining findings:

- **MAJOR — independent finance deadlock, newly visible. RESOLVED in
  Phase 8D-F, above.** The suspected `lock_payment_order_aggregate`
  ordering below turned out not to be the cycle; the reproduction showed
  the inverted order was PostgreSQL's own deferred foreign-key check
  order on `finance_provider_event`, and the deadlock is on
  `finance_payment_order`, not `finance_payment_attempt`. The original
  observation is kept verbatim below because it is what led there.
  `apps.finance.tests.test_concurrency.RefundRaceTests.test_a_refund_racing_a_reconciliation_never_exceeds_the_capture`
  intermittently raises `psycopg.errors.DeadlockDetected` on
  `finance_payment_attempt` (roughly one run in three in isolation) when
  `finance.services.request_refund` races a webhook-driven
  `finance.services.reconcile_attempt`. `reconcile_attempt` takes the full
  cross-domain aggregate through `lock_payment_order_aggregate` before the
  `PaymentOrder` row; `request_refund` opens with `_order_for_update` and takes
  no aggregate first. This is not a matching defect and is not caused by this
  repair — before it, the same test errored on the nullable-join lock during
  fixture setup, so the deadlock could never be reached. It belongs to the
  finance/concurrency owner.
- **MINOR** — `apps/matching/v1_services.py:_covered_legs` is now unreachable;
  its `for_update` branch is dead code kept only by its own definition.
- **MINOR** — the legacy, unrouted `OfferAcceptView` and `CounterOfferView` in
  `apps/matching/views.py` are dead alongside the retired legacy routes. The
  nullable-join lock in the former was repaired rather than left broken, but
  the classes themselves remain candidates for removal.
- The three Phase 8C MINORs (parent `admin_level`, remaining Flutter semantic
  activation controls, retired manual-address strings) and the Phase 8D
  telemetry MINOR are unchanged.

Phase 8D-R files: `apps/matching/v1_services.py`, `apps/matching/views.py`,
`apps/matching/tests/test_phase8dr_offer_locks.py` (new) and this status
document. Nothing else in the working tree was modified.

### Phase 8D — Admin functional UX rebuild (2026-09-02)

The Django admin entry point is now a role-aware ShipTrip operations console
for the nontechnical owner and staff roles. `/admin/` opens an actionable
overview instead of the raw model directory. The primary navigation is filtered
by the existing Phase 6A capability matrix (Ops, Support, Finance, Trust /
Verification and Super Admin); the primary navigation exposes raw Django model
screens only through the explicit Super Admin “Technical records” escape hatch.
Existing model-level authorization on bookmarked technical URLs is unchanged.

Delivered surfaces:

- Action queues for KYC, flight proofs, disputes, payment failures, refunds,
  payouts, failed jobs, email and provider readiness. Counts are authoritative
  database counts and link to the matching filtered queue; zero queues stay
  visible as checked, quiet states.
- Users with name/email search, account and KYC state, activity totals and a
  safe detail page. Requests, Journeys, Deals and disputes link back to the
  user without exposing exact private locations to roles that cannot see them.
- KYC and flight-proof review with applicant/Traveler context, canonical route
  and flight details, previous attempts, authorized image previews and
  short-lived private evidence links,
  explicit Approve/Reject actions and required rejection reasons. Evidence
  access is capability-gated and audited; object-store bucket/key values never
  appear in HTML.
- Delivery requests, ordered FLIGHT/DRIVE Journeys, segment capacity and proof
  readiness, plus coherent Deal pages showing Sender/Traveler, canonical route,
  agreed EUR terms, payment attempts, lifecycle, protection and dispute state.
- Dispute queue/detail with age, participants, evidence, money at stake, payout
  freeze state, status notes and a two-step server-side resolution preview /
  confirmation. Final resolution re-locks and re-plans through the existing
  settlement service, so the preview is never authoritative and double
  settlement remains impossible.
- Finance pages for payments, refunds, payouts and append-only ledger. Amounts
  are rendered in human EUR units while provider currency/reference and failure
  context remain visible. Refund requests and manual refund/payout evidence
  use existing idempotent audited services; no mock payment path was added.
- Staff invitations, fixed role matrix, role replacement, access enable/disable,
  revoke and replace actions. Invitation plaintext tokens remain email-only and
  are never rendered in the browser; self-disable and Super Admin guardrails
  remain enforced by the service layer.
- Grouped business settings for commission, deposit, EUR floors, FX and
  provider availability, with human units, immutable revision creation,
  explicit confirmation/reason fields and readable policy guardrails including
  the 30-minute delivery-code buffer and 48-hour payout protection window.
  Existing Deal snapshots are not rewritten. No provider was enabled by this
  phase.
- System & operations health for database, Redis, routing, KYC limiter mode,
  durable jobs, email and finance worker signals; filtered failed-job and email
  queues; geography catalogue summary;
  and readable audited admin activity. Technical records are owner-only.

Implementation is additive and backend-only for Phase 8D: new console views,
forms, presenters, templates, navigation and CSS sit on top of the existing
audit services. No schema migration or contract regeneration was required.
No Flutter/mobile files, provider credentials, external
provider activation or Phase 8E work was included.

Verification:

- `manage.py check`: clean; all new Python modules compile; Ruff on changed
  backend/admin files: clean.
- Direct render smoke test against a freshly migrated SQLite schema: all 18
  overview, queue, finance, staff, settings, system, geography, audit and
  technical routes returned HTTP 200; KYC detail rendered evidence and review
  controls.
- The expanded SQLite regression slice passed **189 tests**, including the
  Phase 8D HTTP/session/CSRF task tests, Phase 6A staff and permission tests,
  review-email events, raw Django dashboard, KYC, Journeys, finance/policy/jobs,
  disputes and dispute presentation. The 24 new console tests exercise real
  HTTP handling, not direct view dispatch: confirmed KYC and proof decisions,
  private signed retrieval and denied roles, audit records, invite/revoke/role/
  access flows, commission and FX revision creation, dispute preview versus
  settlement, refund creation, currency exponents and sanitized storage errors.
- **33 PostgreSQL admin/verification/staff/settings tests passed** against a
  uniquely named disposable local database. The broader 102-test PostgreSQL
  finance/dispute/concurrency attempt had **66 errors**, predominantly during
  fixture offer creation, due to the pre-existing nullable-join lock failure
  below. It is not a green PostgreSQL integration result.
- Local Python 3.14 / Django 5.1.4 raises `Context.__copy__` errors even in
  unmodified admin tests. Verification was therefore rerun with Python 3.12
  and the repository's pinned requirements, matching the production Dockerfile;
  full HTTP and raw Django admin tests pass on that runtime. No production
  dependency was changed.
- Desktop and 700px-wide visual checks cover navigation, evidence, staff,
  settings and disputes. Review-only evidence is explicitly synthetic; no
  real private identity document or external provider was accessed. The
  Impeccable check returned no findings. Migration dry-run reports no changes.

Final review corrections within Phase 8D include visible staff confirmations,
atomic invitation replacement, private dispute text remaining evidence-gated,
currency-aware manual payout amounts (whole DZD versus EUR cents), proof
readiness across every flight leg, current KYC approval rather than a stale
denormalized flag, distinct form label IDs, and filtered queue destinations.

Remaining findings / handoff:

- **MAJOR — existing PostgreSQL matching integration regression. RESOLVED in
  Phase 8D-R, above.** `apps/matching/v1_services.py:603` applied
  `select_for_update()` to JourneyLeg with
  `select_related("origin", "destination")`. Those relations are nullable after
  canonical geography, so PostgreSQL rejected the outer-join lock before an
  offer could be created. Reproduced independently through the real scenario
  factory; this file had no Phase 8D edits. The broader finance/dispute/race
  regression could not be signed off until it was handled in a separately
  authorized integration fix, which Phase 8D-R is. Matching business behavior
  was not changed by Phase 8D or by the repair.
- **MINOR — telemetry limitation.** The existing system has durable queue
  state but no reliable per-worker heartbeat for email/finance/reservations.
  The console explicitly distinguishes queue state from worker liveness rather
  than inventing an “online” indicator.
- The three existing Phase 8C MINORs remain tracked below: parent `admin_level`,
  roughly twelve remaining Flutter semantic activation controls, and retired
  manual-address localization strings. They were not changed by Phase 8D.
- Functional UI is ready for Claude's focused visual review. PostgreSQL
  integration is not fully cleared; Phase 8E has not been started.

Phase 8D files: `apps/admin_panel/console_{forms,presenters,urls,views}.py`,
`apps/admin_panel/services.py`, `apps/admin_panel/tests/test_phase8d_console.py`,
`apps/disputes/services.py`, `apps/core/admin_display.py`,
`apps/core/templatetags/shiptrip_admin.py`, `apps/core/tests/test_admin_dashboard.py`,
`apps/core/static/shiptrip/admin.css`, `config/urls.py`,
`templates/admin/base_site.html`, `templates/admin/console/*`,
`tools/preview/dump_console.py`, `docs/ADMIN_OPERATIONS.md`, this status document
and the preview-tool README. Other existing working-tree changes were preserved.

### Phase 8C UX review pass (2026-09-02)

A bounded Flutter UX/quality review of the shipped Phase 8C flow. No backend
geography model, canonical Place identity, matching-locality derivation,
airport mapping, API semantics, privacy rule or Journey semantic was changed;
the pass is frontend-only and Phase 8D was not started.

What the review found and fixed:

- **Country selection.** The step was headed with `locationCountryField`
  ("Country code"), a leftover from the retired manual-address form, above raw
  Material `ChoiceChip`s, and the catalogue's English country names were shown
  verbatim in French and Arabic. It is now a titled question with flag-bearing
  ShipTrip pills, localized names for the four launch countries (server name
  retained as fallback), and a selected state carried by fill *and* a check
  rather than colour alone.
- **Search layout.** The search field lived inside the results `ListView`, so
  it scrolled away with its own results, and the list used a hard-coded
  48 dp bottom pad instead of `AppScrollPadding`. The country question now owns
  the page until it is answered, then collapses to one pinned row — chosen
  country plus a Change affordance — above a pinned search box, with the
  results scrolling beneath. A first attempt at a horizontally scrolled country
  strip was rejected because it pushed Germany off a 411 dp viewport.
- **Result rows.** Rows were `Card`+`ListTile` with an LTR-hard-coded chevron
  and a `Locality`/`Airport` type word. They are now a shared `PlaceResultRow`:
  a mode-tinted glyph tile, the name, an AIRPORT mark and a monospaced
  LTR-locked IATA badge for airports, a direction-aware chevron, and a merged
  semantic label.
- **Algeria and same-name context.** A commune whose wilaya shares its name
  rendered as two stacked copies of one word ("Jijel" over "Locality · Jijel").
  Context now falls through to the country when the parent adds nothing, and
  keeps the parent whenever it disambiguates. Exposing the parent's tier
  ("Jijel Wilaya", "Nord department") would need the API to serve the parent's
  `admin_level`; it is recorded below as a MINOR enhancement, not assumed.
- **Airports.** An airport with no catalogue parent fell back to the raw
  country code ("Airport · FR"). It now falls back to the country's localized
  name. The server's matching locality is still never surfaced.
- **Preferred point.** The field could set and replace a point but never
  remove one, and its copy did not distinguish the required matching place
  from the optional operational preference. `PreferredPointField` now shows
  "Flexible within {place}" as a real answer in primary ink, carries an
  Optional mark, states outright that matching runs on the place, and offers
  removal. The map step gained a Decide later action.
- **Map transition.** The map opened titled "Choose a place" with no indication
  of which place constrained it, and silently fell back to the Algiers frame
  for a catalogue row without coordinates. It now shows a persistent context
  strip naming the selected place, names that place in the confirm helper, and
  says so when the catalogue has no centre to open on.
- **Dependent resets.** Changing a canonical place silently discarded its
  preferred point. The user is now told. Changing country is a visible return
  to the country question rather than an invisible clear.
- **Review step.** Two rows both labelled "Preferred meeting point" were
  indistinguishable; they now name their end and state the flexible case
  instead of omitting it.
- **Accessibility.** `Semantics(button: true, …)` wrapped around
  `ExcludeSemantics` produces a control a screen reader announces correctly and
  cannot activate — the tap action is discarded on the way up. Fixed on the
  Phase 8C path (`AppSelectField`, `AppIconButton`, `PlaceResultRow`,
  `CountryChoiceTile`, the country row) and covered by a regression test. The
  same pattern remains elsewhere in the app and is recorded below.

Files changed: `mobile/lib/design/components/place.dart` (new),
`mobile/lib/features/location/preferred_point_field.dart` (new),
`mobile/lib/features/location/canonical_place_picker_screen.dart`,
`mobile/lib/features/location/location_picker_screen.dart`,
`mobile/lib/features/requests/request_create_screen.dart`,
`mobile/lib/features/journeys/journey_create_screen.dart`,
`mobile/lib/app/router.dart`, `mobile/lib/design/components/forms.dart`,
`mobile/lib/design/components/primitives.dart`, the three ARB files and their
generated localizations, plus `mobile/test/canonical_place_picker_test.dart`,
`mobile/test/preferred_point_test.dart` (new) and
`mobile/test/design/place_semantics_test.dart` (new).

Verification: `dart format` clean; `flutter analyze --fatal-infos` clean;
`flutter test` **269 passed** (239 baseline plus 30 review tests, including a
6-device x 3-locale render matrix over the picker). No Django, tools or
contract file was touched.

Known remaining items, none blocking:

- **MINOR** — naming a parent's administrative tier in a result ("Jijel
  Wilaya", "Nord department", "Madrid province") would need
  `GET /api/geography/places` to serve the parent's `admin_level` alongside
  `parent_name`. Left for Codex to decide; the client does not guess it.
- **MINOR** — the `Semantics` + `ExcludeSemantics` activation defect above
  still affects roughly a dozen controls outside the Phase 8C path
  (`chat_list_screen`, `home_screen`, `notifications_screen`,
  `language_screen`, `appearance_screen`, `rate_screen`, `guest_pay_screen`,
  `navigation.dart`, `sheets.dart`, `forms.dart` check/segmented/step
  controls). The fix is one `onTap:` on the outer `Semantics`; it belongs to an
  app-wide accessibility pass, not to a location review.
- **MINOR** — the retired manual-address strings (`locationCountryField`,
  `locationCountryHint`, `locationCountryInvalid`, `locationCityField`,
  `locationRecent`, `locationCityOnly`, `locationExactAddress`,
  `locationAirports`, `locationExactRequired*`) are now unreferenced in all
  three ARB files. They were left in place rather than removed inside a UX pass.
- Hardware QA on a physical device is still pending, as for Phase 8A/8C.

### Phase 8E — final integration, tracked cleanup and release candidate (2026-09-02)

Phase 8E closes the bounded items Phases 8C and 8D-V recorded, repairs two
defects found while assembling the release, ships the reviewed geography
catalogue inside the artefact, and takes the accumulated Phase 8A–8D worktree to
a committed, deployed private release candidate. No V1 decision was revisited:
Kaba/ProductRequest stays retired, economics stay canonical EUR, the sender
still proposes first, exact locations stay hidden until funding, the traveler
still cannot retrieve a delivery code, and matching still compares canonical
locality identities only.

**Geography parent tier (Phase 8C MINOR, closed).** `GET /api/geography/places`
now serves `parent_admin_level` beside `parent_name`, and inside
`matching_locality` / `served_locality`, taken verbatim from the reviewed
source — `wilaya`, `region`, `department`, `autonomous_community`, `province`,
`state`, `district`. It was already on every row; nothing was fabricated, and a
source that records no tier serves an empty string. Flutter uses it to say
"Jijel Wilaya" where it previously had to fall through to "Algeria", because a
commune stacked under an identically named parent read as two copies of one
word. A tier the app has no phrasing for falls back to the bare parent name
rather than being inferred from the country. Seven localized tier phrasings were
added in EN/FR/AR; the French and Arabic forms use apposition and idafa
respectively, so no elision or agreement is guessed. The place search stays at
three queries.

**Flutter activation defect (Phase 8C MINOR, closed).** `Semantics(button:
true, …)` wrapped around `ExcludeSemantics` announces a control correctly and
discards its tap action, so the control is a button a screen reader cannot
press — worse than an unlabelled one, because it looks finished. Phase 8C fixed
the five controls on the location path. The audit found 22 such pairs; 17 were
unfixed and 16 of those were genuinely interactive. All are now fixed: the
segmented choice, the check tile, the step indicator, the bottom navigation bar,
the option sheet, chat rows, notification rows, appearance and language options,
profile rows, boost packages, guest and checkout payment tiles, the rating tag
chips, and the star rating. Six of those nodes were also announcing *nothing* —
`ExcludeSemantics` had eaten the only text they had — and were given labels.
Two cases were not a missing `onTap:`:

- The star rating declares `slider: true`, which is operated with increase and
  decrease rather than a tap; it now carries `onIncrease` / `onDecrease`.
- The step indicator's outer node is a progress readout, not a button. Wrapping
  the whole row in `ExcludeSemantics` threw away back-navigation to completed
  steps. Each completed step is now its own semantic button; steps still ahead
  of the user stay out of the tree, as before.

`PlaceContextStrip` and the decorative glyphs stay excluded — they are not
controls. Beyond per-control tests, a source-level guard
(`test/design/semantics_activation_guard_test.dart`) fails the suite if any
`Semantics` node claiming an interactive role sits above an `ExcludeSemantics`
without the matching action. It was verified to actually catch a reintroduction
rather than pass vacuously.

**Retired localization strings (Phase 8C MINOR, closed).** The ten
manual-address keys (`locationCountryField`, `locationCountryHint`,
`locationCountryInvalid`, `locationCityField`, `locationRecent`,
`locationCityOnly`, `locationExactAddress`, `locationAirports`,
`locationExactRequiredNotice`, `locationExactRequiredRow`) were confirmed
unreferenced by a word-boundary search over `lib/` and `test/` and removed from
all three ARB files. No active key was touched, and `flutter gen-l10n` reports
no untranslated messages.

**Matching dead code (Phase 8D-R MINOR, partly closed).**
`apps/matching/v1_services.py:_covered_legs` had no caller anywhere in the
repository and was removed; `InvalidLegRange`, which it raised, is still used by
the live leg-range validation and stays. The unrouted legacy
`TravelerApplyView`, `SenderApplyView`, `CounterOfferView` and `OfferAcceptView`
are **retained and documented** rather than deleted. Nothing routes, imports or
calls them, but they are the pre-V1 traveler-first behaviour that comments in
`apps.parcels` still point at, and they are the reason
`apps/finance/tests/test_phase8df_lock_order.py` excludes `apps.matching.views`
from the canonical finance lock graph. Removing them is a legacy-retirement
change, not a release-candidate cleanup. The module docstring was corrected: it
had been advertising retired endpoints as if they were live, and now names the
routed set, points every V1 negotiation write at `v1_views`, and says outright
that the legacy classes must not be given a route.

**Legacy lock rails (unchanged, as instructed).** `apps.verification`,
`apps.wallet` and `apps.payments` were not refactored. Active V1 does not reach
them and they do not participate in the finance lock graph.

**Admin MINORs (Phase 8D-V, two closed, one declined).** The brand seal moved
from `#d0602c` (3.9:1 against its white letter) to `#b94e22` (5.03:1); it is
`aria-hidden` decoration and formally exempt, but the letter is still read by
eye. The console's leading table column got a 150 px floor and a non-wrapping
identity line, so a page of short real provider values ("Stripe", "Chargily")
no longer collapses a column that the long seeded label made comfortable. The
`ruff format` MINOR was **declined**: the project gate is `ruff check`, which
passes, and reformatting roughly thirty pre-existing files would bury this
release in an unrelated diff.

**Defect found: the SQL schema contract carried a foreign database.** The
worktree's regenerated `backend/contracts/sql/schema.sql` contained pre-Django
Prisma-era enum types (`MatchStatus`, `ParcelStatus`, `ParcelType`, `Role`,
`TransactionType`) and their tables — 1,384 added lines against HEAD's 7,296.
No migration creates those objects; the file had been dumped from a developer
database that still carried them. CI's schema-drift gate regenerates from a
fresh `migrate`, so this would have failed the gate, and as a contract it
described a database that does not exist. It was regenerated from a clean
PostgreSQL 16 database built by `migrate` alone: 7,955 lines, 671 added and 12
removed against HEAD — the five geography tables plus the constraints the Phase
8C migrations dropped, and nothing else. Two consecutive dumps were identical
after the documented nonce normalisation (SHA-256
`82B24DB8D0465BA1B86557197E732F123B30A0B1D7B337097763F7B56858C45C`).

**Defect found: the release had no geography data.** The Phase 8C write
contract refuses a `DeliveryRequest` or a `Journey` that does not reference a
canonical `Place`, and the catalogue lived only as a 28 MB manifest outside the
repository. A deployment of this code with an empty catalogue is a deployment on
which nobody can create anything — and the previously deployed release answers
404 for `/api/geography/countries`, so this is the first release that needs it.
The reviewed manifest now ships in the image as
`backend/monolith/apps/locations/data/geography_manifest_2026.json.gz`
(deterministically gzipped, 1.05 MB; uncompressed SHA-256
`b4aad209f4ae7ecb264fc9ae4b5d9b4b61b7ff9d918ca470729db93d1abb7692`), so one
release identifier carries the code and the exact reviewed data.

`import_geography` reads `.gz`, defaults to the bundled artefact, and gained
`--skip-if-current`, which compares the manifest's uncompressed-content digest
against a new `locations_geography_catalogue_import` row and returns after one
indexed read when they match. The marker is written inside the same transaction
as the rows it describes, so a rolled-back import cannot leave a marker that
makes the next boot skip a catalogue that is not there. `backend/railway/start.py`
runs it **after** the gateway is listening: a first import takes minutes, and
ahead of readiness it would fail the platform health check and roll the
deployment back. A failure is loud and non-fatal — the service keeps serving and
the console reports a catalogue that is not at the shipped digest.
`--deactivate-missing` is deliberately absent from the boot path, and a test
asserts all of this positionally, including that no `.dockerignore` pattern
drops the artefact.

Rehearsed against PostgreSQL 16: migrations applied clean, the first import took
145.7 s at a 280 MB peak and produced 4 countries / 56,134 places / 3,833
alternate names / 165 mappings, and the second run was a 2.9 s no-op. This
reverses the earlier "keep the data out of the release" position, and
`tools/geography/README.md` records why.

**Provider mode is now readable without reading a secret.** Configuration,
enablement and test-versus-live are three different facts, and only the first
two were reported anywhere. Each gateway now derives a `credential_mode` —
`test`, `live`, `unknown` or `not_configured` — from its credential's documented
shape: Stripe's key prefix, and for Chargily the key prefix cross-checked
against the API base, where a live key against the test base (or the reverse)
reports `unknown` rather than picking a half. It never returns, logs or compares
a key value. It surfaces in `/api/admin/health/deep`, in
`/api/admin/provider-health` through a new operator-only `as_operator_dict()`,
and on the console's System and Settings pages. The payer-facing `as_dict()`
contract is unchanged, and a test pins that the operational fields cannot leak
into a checkout response.

Deployed provider state was established **without reading any key**: an unsigned
webhook returns 400 `invalid_webhook_signature` when the signing secret is
configured and 503 `provider_not_configured` when it is not. Both Stripe and
Chargily answered 400 and the mock rail answered 503, confirming that both real
rails have signing secrets configured and that the mock rail is correctly
refused in production. Test-versus-live and business-settings enablement were
**not** determined in this phase: both need either an authenticated admin
session or the raw keys, and the operator reads them from the console once this
release is deployed. No provider was enabled, disabled or otherwise changed, and
no charge of any kind was created.

**Object storage.** KYC evidence is stored in the private `S3_BUCKET_KYC` and
reachable only through a short-lived presigned redirect behind `view_kyc` plus
`view_evidence`, audited, with `Cache-Control: no-store` and
`Referrer-Policy: no-referrer`. Dispute evidence **does** have a safe private
path — `S3_BUCKET_DISPUTE` (falling back to the KYC bucket), the same presigned
TTL, and an authorization check that admits only the two deal parties or staff.
The earlier concern that it lacked one is closed. The deployed gateway exposes
no bucket: unauthenticated `POST /api/kyc/submit` answers 401 through the Go KYC
service rather than 404, and the alias `/kyc/submit` behaves identically.

**Email.** Outbound transactional email remains intentionally inactive. It was
not enabled, and no transactional mail was sent in this phase.

**Local harness note.** A full SQLite run on a workstation that also has the
gitignored `config/settings/test_pg.py` reports one discovery error unless
`SHIPTRIP_TEST_PGDATA` points at a healthy embedded cluster: Django's test
discovery imports every module under `config/settings/`, and that module boots
an embedded PostgreSQL on import. It is a local-only artefact — the file is
gitignored and never reaches CI — but it will confuse the next person who runs
the suite without the variable set.

#### Phase 8E release record

- **Release commit** `0a61cba063e899092391613e05fde64ea959e00a`, pushed to
  `is-bo/shiptripis` `main` (`cef2a9c..0a61cba`). The `upstream`
  `islamouahab/ShipTrip` remote is push-disabled and was not written to.
- **Local gates on that exact tree:** PostgreSQL 16 **1102 passed / 34 expected
  skips**, SQLite **1102 passed / 80 expected skips**, Flutter `dart format`
  clean, `flutter analyze --fatal-infos` clean, `flutter test` **281 passed**
  (269 baseline plus 12 Phase 8E tests). Ruff, `manage.py check`,
  `makemigrations --check --dry-run`, `git diff --check`,
  `tools/check_static_web.py`, Go build/vet/unit tests all clean. Caddy
  validation needs Docker, which the workstation lacks; it runs in CI.
- **CI** run `33681208736` on `0a61cba`: **success**, all six jobs — Go unit,
  Go integration (real Redis), Django, Production config + static web, Flutter,
  and Schema drift. The drift job passing is the independent confirmation that
  the regenerated `schema.sql` matches a clean `migrate`.
- **Railway** deployment `32e74fb3-6085-455b-a7b2-f732357574ea`: **SUCCESS**,
  production environment, one replica (unchanged — the local KYC limiter
  requires exactly one). `RELEASE_ID` moved from `v1.0.0-rc.1+cef2a9c` to
  `v1.0.0-rc.2+0a61cba`; no other variable was read or written.
- **Migrations applied:** `locations.0004_country_place_airportlocalitymapping_and_more`,
  `locations.0005_location_canonical_place`,
  `locations.0006_geographycatalogueimport`,
  `parcels.0008_remove_deliveryrequest_parcels_delivery_schema_ver_and_more`,
  `trips.0007_remove_journey_journey_distinct_endpoints_and_more`.
- **Geography import on Railway:** started 21:00:11 UTC, committed 21:03:04 UTC
  (173 s), reporting content digest
  `b4aad209f4ae7ecb264fc9ae4b5d9b4b61b7ff9d918ca470729db93d1abb7692` and
  4 countries / 56,134 places / 3,833 alternate names / 165 mappings. Readiness
  was green throughout; the catalogue was briefly empty between readiness and
  the import's commit, exactly as designed.
- **Deployed catalogue verified through the public API:** DZ 69 wilayas and
  1,541 communes, FR 34,875 communes and 119 parents, ES 8,132 municipalities
  and 71 parents, DE 10,749 municipalities and 417 parents, 161 selectable
  airports (DZ 31, FR 49, ES 42, DE 39). Because an airport is only selectable
  with an active primary served mapping, that count is the 161/161 coverage
  gate. Wilaya identities 59–69 are all present (Aflou through El Abiodh Sidi
  Cheikh). CDG and ORY resolve to Paris, MAD to Madrid, FRA to Frankfurt am
  Main and ALG to Alger Centre. `parent_admin_level` is served on the
  deployment: Jijel/`wilaya`, Paris/`department`, Madrid/`province`,
  Frankfurt/`district`.
- **Deployed smoke:** `/`, `/en/`, `/fr/`, `/ar/` and the four legal/support
  pages 200; `/healthz` and `/readyz` 200 with database, migrations and
  `rate_limit_cache` all `ok`; `POST /api/auth/sign-in` 400 (validation),
  `/api/me` and `/api/parcels/open` 401; geography search 200; `/admin/` 302 to
  a 200 ShipTrip-branded login. Unauthenticated `POST /api/kyc/submit` answers
  **401**, not 404, through the gateway, and `/kyc/submit` behaves identically.
- **Payment webhooks on the deployment:** `/api/payments/webhooks/stripe` and
  `/api/payments/webhooks/chargily` both reject an unsigned probe with 400
  `invalid_webhook_signature`, which is only reachable when the signing secret
  is configured; `/api/payments/webhooks/mock` answers 503
  `provider_not_configured`, so the test rail cannot move money in production.
  No signed event was sent and no charge was created.
- **Android artifact:** workflow run `33682489873` on the same `0a61cba`,
  artifact `shiptrip-v1.0.0-rc.2-0a61cba-debug-arm64`. **Debug**, not signed
  release: the repository has no Actions secrets at all, so
  `ANDROID_KEYSTORE_BASE64` and its passwords are absent and the workflow
  correctly refuses to substitute a debug key into a release build. The APK is
  `shiptrip-v1.0.0-rc.2-0a61cba-debug-arm64.apk`, **96,481,615 bytes
  (92.01 MiB)**, SHA-256
  `0bbbc3287c385924ff3017351f21a67aa37cfdba52f61b1bdd902e84b7f828c2`,
  embedding `https://shiptrip-production.up.railway.app` and no provider
  secret of any kind.

  On size: the earlier figures are not comparable to this one. ~160 MB was a
  universal debug build, 58.65 MB a universal *release*, and the 21.17 MB
  projection an ARM64 *release*. This is an ARM64 *debug* build, and the ABI
  targeting did work — `lib/arm64-v8a/` holds 51.7 MiB of native code while
  `armeabi-v7a` and `x86_64` carry only a 0.1 MiB JNI shim each. The bulk is
  debug-only: a JIT `libflutter.so` at 38.8 MB, a
  `libVkLayer_khronos_validation.so` at 15.2 MB that ships only in debug, and
  the Dart kernel blob that a release build replaces with stripped AOT code.
  Nothing here indicates unexpected growth; a signed release ARM64 build
  remains the ~21 MB artifact, and it is blocked only on the signing secrets.

#### Phase 8E-A private profile artifact

A bridge step, not a phase: produce an artifact fit for judging real-phone
performance, and change nothing else.

- **Why the debug APK was the wrong instrument.** A debug build runs Dart under
  the JIT engine, ships the Vulkan validation layer, and carries the whole Dart
  kernel; it is slower than the product by a margin wide enough that any lag
  judged from it is unattributable. Profile is the mode Flutter provides for
  this question: release AOT code and the optimised engine, with only the
  tracing hooks a profiler needs left in.
- **Follow-up commit** `6a46c16914abe580a8361bcbba50ad678d13b6b9` — the Build
  Android workflow and `docs/ANDROID_BUILD_RUNBOOK.md`, nothing else.
  `git diff 0a61cba..6a46c16 -- mobile/` is empty: every line of Flutter
  application code and the entire Android Gradle configuration are identical to
  the deployed release. Backend runtime code is untouched, so the deployment was
  **not** redeployed and still serves `v1.0.0-rc.2+0a61cba`.
- **Three build types, kept separate.** `release` (signed, distributable),
  `profile` (private device QA), `debug` (install-only fallback). Profile uses
  the Flutter Gradle plugin's own `profile` build type, created with
  `initWith(debug)`, so it carries the runner's auto-generated Android debug
  signing config. Nothing in the release path moved: the Gradle guard still
  throws on any `*Release` task unless all four signing values are present, so a
  debug key cannot reach a release artifact. Production signing policy was not
  weakened, relaxed or bypassed.
- **CI** run `33689383484` on `6a46c16`: **success**, all six jobs.
- **Android** run `33689392364` on `6a46c16`, artifact
  `shiptrip-v1.0.0-rc.2-6a46c16-profile-arm64`.
- **The artifact.** `shiptrip-v1.0.0-rc.2-6a46c16-profile-arm64.apk`,
  **33,792,256 bytes (32.23 MiB)**, SHA-256
  `909ceac55c4494e0ddfedbff25a58afa3e026e91cd0ada58167f0ad992ccddcd`
  (recomputed locally, matching the runner's `SHA256SUMS.txt`).
- **Proved to be profile, not debug or release.** AOT `lib/arm64-v8a/libapp.so`
  present; `libvmservice_snapshot.so` present, which only a profile build ships;
  `kernel_blob.bin`, `isolate_snapshot_data`, `vm_snapshot_data` and
  `libVkLayer_khronos_validation.so` all absent. The workflow asserts three of
  these on the runner before upload, so a mislabelled artifact fails the build
  rather than reaching a phone.
- **ARM64 targeting held.** `lib/arm64-v8a/` carries 25.52 MiB of real code
  (`libflutter.so` 11.99 MiB, `libapp.so` 11.88 MiB,
  `libvmservice_snapshot.so` 1.56 MiB); `armeabi-v7a` and `x86_64` carry only a
  0.05 / 0.10 MiB `libdartjni.so` JNI shim each, the same pattern as the debug
  artifact.
- **Configuration.** `https://shiptrip-production.up.railway.app` appears twice
  inside the Dart AOT snapshot; the `10.0.2.2` development default does not
  appear. A ten-pattern secret scan over the whole APK (Stripe secret,
  restricted, publishable and webhook keys, Chargily keys, AWS keys, PEM private
  key blocks, bearer tokens, Postgres DSNs, SMTP password markers) found nothing.
- **Installable.** `apksigner verify` passed on the runner. The APK carries an
  APK Signature Scheme v2 block whose certificate is the standard
  `CN=Android Debug, O=Android` key AGP generated on that runner, fingerprint
  `591bdcb7b5189416b63534492cd524220853c14169967b7858fa3f9e81c6da45`. Manifest:
  `com.shiptrip.shiptrip`, versionName 1.0.0, versionCode 1, minSdk 24,
  targetSdk 36, `extractNativeLibs=false`, `debuggable=true` (inherited from the
  debug build type, which is how a profiler attaches; it does not change Dart's
  execution mode).
- **The Phase 8E debug APK must be uninstalled first.** Its certificate is
  `bb9314f908cf8a0ece3dfc017377946553c631bbe79fe8f5c5d0cfd154f88e83` — a
  different runner, a different auto-generated debug key, the same
  `applicationId`. Android refuses to update an installed app with a different
  signer, so an in-place install fails with `INSTALL_FAILED_UPDATE_INCOMPATIBLE`.
- **Measured size comparison** (all figures from the artifacts themselves):

  | Build | APK | `lib/` | `assets/` | `classes*.dex` |
  | --- | --- | --- | --- | --- |
  | Debug ARM64 (`0a61cba`) | 92.01 MiB | 51.81 MiB | 104.00 MiB | 10.74 MiB |
  | **Profile ARM64 (`6a46c16`)** | **32.23 MiB** | 25.67 MiB | 4.24 MiB | 10.74 MiB |
  | Release universal (`32731448680`) | 55.93 MiB | 54.07 MiB | 2.66 MiB | 0.85 MiB |

  Profile is 65% smaller than the debug artifact. Almost all of that is the Dart
  kernel: debug ships `kernel_blob.bin` at 86.86 MiB uncompressed plus an 11.11
  MiB `isolate_snapshot_data`, which AOT compilation replaces outright, and it
  ships a 37.03 MiB JIT `libflutter.so` against profile's 11.99 MiB optimised
  one plus the 14.53 MiB Vulkan validation layer that only debug carries.
- **Profile is still not release size, and the gap is explainable.** A release
  ARM64 build would be roughly 21 MiB. Profile's extra ~11 MiB is three known
  things: `classes*.dex` is 10.74 MiB because R8 minification runs only on
  release (0.85 MiB there), the AOT `libapp.so` is 11.88 MiB against release's
  7.00 MiB because profile keeps symbol names and timeline instrumentation, and
  `libvmservice_snapshot.so` adds 1.56 MiB that release omits. Nothing here is
  unexpected growth.
- **How to read the numbers it produces.** Profile's tracing instrumentation is
  real work, so frame timings from it are marginally pessimistic. Treat them as
  an upper bound on release frame cost, not as the release figure. The
  `debuggable=true` manifest flag also makes ART run the Kotlin/Java side with
  debug-friendly settings, which matters far less than the Dart side but is not
  nothing.
- **No payment call of any kind was made** during this step, and no provider
  secret was read, printed or logged. Provider mode remains an owner reading
  from the admin console.

Known remaining items:

- **MINOR** — `ruff format` cleanliness across roughly thirty pre-existing
  files, deliberately not taken in a release phase (see above).
- Hardware QA on a physical device is still pending and is written up as
  `docs/PHASE8E_DEVICE_QA.md`. Judge it on the **profile** artifact
  (`shiptrip-v1.0.0-rc.2-6a46c16-profile-arm64`), not the debug one; the
  debug build's timings are not attributable to the product.
- **Owner-read, not determined here:** whether each payment rail's credentials
  are test or live, and whether business settings have each rail enabled. Both
  need an authenticated admin session; the console now states all three facts
  on one line. Provider end-to-end testing stays gated on that reading.
- **No signed Android release** until `ANDROID_KEYSTORE_BASE64`,
  `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS` and `ANDROID_KEY_PASSWORD`
  exist as repository Actions secrets. The debug artifact is for controlled
  private installation only, not distribution.

## Phase 8F-A — journey UX, editing, route validity and flight-proof repair (2026-09-03)

Five findings from the owner's second real-device QA on the Phase 8E-A profile
APK. Scope was held to exactly those: parcel creation, KYC admin evidence,
payment rails and push notifications were deliberately not touched, and Phase
8F-B was not started.

### 1. The route builder asked for the wrong noun

**The finding.** Start Jijel, destination Paris. The app immediately made one
leg, Jijel → Paris. The traveller then wanted Jijel → Algiers → Paris and had
no way in: "Add a leg" *appended*, producing Jijel → Paris → Algiers. The only
route to the answer was to delete Paris, add Algiers, and add Paris again.

**Root cause.** The screen was leg-centric. `_addLeg()` could only push onto
the end of the chain; there was no insert at a position, and changing leg 0's
destination moved the journey's destination instead of splitting the span.

**The change.** The model is now **stops**, and the legs between them are
derived. `mobile/lib/features/journeys/journey_route_draft.dart` holds an
ordered list of stops plus one segment per gap; segment *k* runs from stop *k*
to stop *k+1*. That makes three server rules structurally impossible to break
rather than merely validated — contiguous positions from zero, first leg
begins where the journey does, each leg starts where the last ended.

The affordance the old screen lacked sits between every pair of stops:
**"Add a stop here"**. Inserting Algiers between Jijel and Paris splits that
segment into two and leaves the destination alone. Also supported: change any
stop including an endpoint, remove an intermediate stop (the two segments it
separated rejoin), and move an intermediate stop earlier or later. No list
index is ever shown.

`JourneyLeg` and its ordered-position architecture are unchanged. This is a
different way of *editing* the same chain, not a different chain.

### 2. A stop is a place, and sometimes an airport at that place

The catalogue resolves CDG to Paris and ALG to Algiers, so an airport and the
city it serves are **the same stop**: "CDG then Paris" is not a leg, it is one
place twice. A stop therefore carries an optional airport it is *reached by*,
and the leg endpoints use that airport while the journey's own start and
destination stay the places the traveller named. The route reads

    Jijel  —drive→  Algiers · ALG  —flight→  Paris · CDG

A city is never silently converted into an airport. When a segment must fly
and an end is a city, the editor says so and asks which airport, seeding the
picker with that city's country.

### 3. DRIVE between Algeria and France was accepted

**Locked rule.** Countries belong to declared **road networks**; DRIVE is
available only within one. Algeria is its own network; France, Spain and
Germany share the continental European one; an undeclared country is its own
island, which fails closed.

So **any leg between Algeria and any non-Algerian country must be FLIGHT** —
Algiers → Paris, Jijel → Marseille, Madrid → Algiers. Algerian domestic DRIVE
is allowed. France → Germany and France → Spain DRIVE remain allowed. No
ferry or sea transport was invented.

**Enforced server-side**, not only in Flutter. `apps/trips/transport_rules.py`
owns the table; `JourneyRouteWriteSerializer._validate_leg_modes` refuses a
create *or* an edit with the structured code `journey_leg_mode_unavailable`,
carrying `leg_position`, `required_mode`, `origin_country` and
`destination_country`. `_validate_leg_sequence` re-checks at publication, so a
leg that became impossible after it was written — a legacy row, or a catalogue
refresh that moved a place — cannot reach senders. Flutter mirrors the table
in `mobile/lib/domain/transport_rules.dart` and simply does not offer DRIVE on
such a segment, with a sentence saying why.

Defaults help without ever proposing an impossible mode: airport→airport
across countries defaults to FLIGHT, locality→locality inside one road network
to DRIVE, and any pair that can only fly to FLIGHT.

### 4. A configured journey could not be edited

`PATCH /api/journeys/<id>` now rewrites an editable journey's endpoints, whole
leg chain and notes in one authoritative write under the aggregate lock,
re-validated exactly as publication would be.

**What may be edited.** DRAFT and PENDING_VERIFICATION, owned by the caller,
*and* carrying no dependent state. ACTIVE, IN_PROGRESS, COMPLETED, CANCELLED
and EXPIRED are refused, as is any journey with a Deal or a pending/accepted
Match — a draft can be uneditable because a sender is already proposing
against it.

**The refusal explains itself.** The detail endpoint serves `editable` and
`edit_blocked_code` to the owner only; the detail screen keeps the Edit button
visible but inert with the reason beneath it, and the edit screen states it
rather than showing a form that cannot be saved. Hiding the button explains
nothing to someone looking for it.

The edit screen reuses the create screen's route editor rather than growing a
second form.

### 5. Editing a flight leg no longer leaves stale proof attached

Changing a flight leg's origin airport, destination airport, flight number,
departure time or arrival time means its proof no longer evidences that
flight. A leg the client is keeping carries its `id`, so an **unchanged**
flight leg keeps its approved proof across an edit; a materially changed one
has its approved or pending proof returned to `pending` for re-review, with
the previous status, reviewer, review time and the changed field names
preserved in the row's `metadata` audit trail. A rejected proof is left
rejected. Proof on a leg the edit removes is discarded with it.

Both counts come back in the response, the app warns *before* sending an edit
that would cost a reviewed proof, and reports what actually happened after.
A capacity edit does not invalidate anything — a boarding pass does not stop
proving a flight because the traveller decided to carry less.

### 6. Flight-proof upload: the real root cause

**Reproduced on the deployment first.** Railway HTTP logs show four
`POST /api/journeys/1/legs/2/proof` → **500** at 12:09–12:10 UTC on 3 Sep,
455/411/279/1213 ms — long enough to have reached object storage and failed
there. The Django log line carried no provider detail.

**Root cause, proved directly.** Django writes flight proof with *Django's*
S3 credential, but the view wrote it to `settings.S3_BUCKET_KYC` — the bucket
whose credential belongs to the **Go KYC service**. Probing the deployed
endpoint with each credential:

| Credential | `shiptrip-kyc-…` | `shiptrip-media-…` |
| --- | --- | --- |
| Django `S3_*` | **403 AccessDenied** | put/get OK |
| Go `KYC_S3_*` | put/get OK | 403 AccessDenied |

`boto3` raised `ClientError`, nothing caught it, Django returned 500, and
Flutter's status mapping turned that into *"This isn't your fault. Try again
in a moment."* — which was both untrue and unactionable. This is why KYC
upload succeeded on the same phone in the same session: it goes through the Go
service with the other credential.

**The repair.**

- New `S3_BUCKET_PROOF` setting, defaulting to `S3_BUCKET_PARCEL`. Flight
  proof is journey evidence, not identity evidence, and belongs in the private
  media bucket Django owns — alongside dispute evidence, which already has the
  same shape. Storage stays private; the admin console still serves it only
  through an authorised, presigned, no-store redirect.
- Storage failures are caught and answered `503 proof_storage_unavailable`.
  The provider's own message names buckets and keys, so it goes to the log
  with the request id and never to the phone.
- Every proof refusal now carries a machine code: `proof_file_missing`,
  `proof_file_too_large`, `proof_media_type_unsupported`, `proof_kind_unknown`,
  `proof_only_for_flight`, `journey_not_owned`, `journey_proof_upload_closed`,
  `proof_storage_unavailable`.
- `manage.py check_object_storage` does a real put/get/delete round trip per
  configured bucket with the credential the application actually uses. A
  bucket name in an environment variable is not access, and nothing in
  `readyz`, settings validation or the console could previously tell the
  difference.
- `/api/ops/health` reports `proof_bucket_configured`.

**Client half.** `ApiException._kindFor` mapped 413 and 415 to `server`, so a
file that was too large or the wrong type told the user it was not their
fault; both are now `validation`. A failed upload keeps the chosen file and
offers Retry rather than sending someone back to the gallery, and the retry
carries the **same idempotency key** — new column plus a partial unique index
on `(leg, idempotency_key)` — so an attempt that reached the server before the
connection died attaches to that proof instead of leaving a reviewer a second
copy. The multipart part now states its content type instead of leaving the
transport to infer one from a gallery path that may have no extension.

### 7. € and kg sat above the digits

**Root cause, not a nudge.** Unit labels were passed to Material's
`suffixIcon` slot. That slot is laid out as an *icon*: centred inside a box
with a 48-point minimum height, with a bare `Padding` child pinned to that
box's **top edge**. The result was roughly thirteen logical pixels of drift
above the number. Material's other trailing slot, `suffix`, is baseline
aligned but fades to zero opacity until the field has focus or content, so a
unit put there vanishes from an empty field.

Fixed once, centrally: `AppTextField` gained a `unit` parameter that renders
the label in `suffixIcon` with `suffixIconConstraints` minimum dropped to
zero, which shrink-wraps the box to the text and lets the decorator centre it
on the input. The style matches the input's own `bodyLarge`, so centring the
boxes lines up the baselines rather than merely the middles. `AppAmountField`
(€), the request weight (kg) and dimension (cm) fields and the journey
capacity field all route through it; the one-off `_UnitSuffix` widget is gone.
No `Padding(top: …)` was added anywhere.

### 8. Route summary

The journey detail screen read `leg.origin?.coarseLabel` — a legacy
`Location` field that is **null on every journey created since Phase 8C** — so
the header and the leg list rendered blank endpoint labels. Endpoint naming
now goes through `journey_labels.dart`: canonical place first, coarse Location
only as a legacy fallback, an em dash rather than an empty string. Each stop
on the route line also carries its own context ("Jijel Wilaya", "Paris
department") and a Departs/Arrives prefix on its time.

### Matching semantics: unchanged

Compatibility is still equality of derived canonical matching-locality IDs.
Nothing in this phase touches `apps/matching`. No radius, pin, display-name or
nearby-city matching was reintroduced. Route editing changes which
`JourneyLeg` rows exist; it does not change how compatibility is calculated.
The 8C matching tests pass unchanged.

### Files changed

Backend: `apps/trips/transport_rules.py` (new), `apps/trips/services.py`,
`apps/trips/serializers.py`, `apps/trips/views.py`, `apps/trips/models.py`,
`apps/trips/migrations/0008_journeylegproof_idempotency_key_and_more.py`
(new), `apps/core/management/commands/check_object_storage.py` (new),
`apps/admin_panel/health.py`, `config/settings/base.py`,
`apps/trips/tests/test_phase8fa_journey_editing.py` (new).

Flutter: `domain/transport_rules.dart` (new),
`features/journeys/journey_route_draft.dart` (new),
`features/journeys/journey_route_editor.dart` (new),
`features/journeys/journey_edit_screen.dart` (new),
`features/journeys/journey_labels.dart` (new),
`features/journeys/journey_create_screen.dart`,
`features/journeys/journey_detail_screen.dart`,
`features/journeys/leg_proof_screen.dart`,
`features/requests/request_create_screen.dart`,
`design/components/forms.dart`, `domain/journey.dart`,
`data/repositories.dart`, `core/api/api_exception.dart`,
`core/api/error_codes.dart`, `app/router.dart`, the three ARB catalogues and
their generated localisations, `test/support/fake_api.dart`, and three new
Phase 8F-A test files.

### Migration

One, additive: `trips.0008` adds a defaulted `idempotency_key` column and a
partial unique index that excludes the empty string, so a client that sends no
key keeps today's behaviour. No backfill, no table rewrite, no lock beyond the
metadata change.

#### Phase 8F-A release, deployment and artifact

**Release** `v1.0.0-rc.3+fb49e60`, four commits:

| SHA | What |
| --- | --- |
| `9dc9afa` | The phase: stop-based routing, journey editing, the mode rule, the proof repair, the unit fix |
| `b8b952e` | Re-exported `contracts/sql/schema.sql` for the new column and index |
| `8c4fde6` | Made the route editor's stop rows operable, not merely announced |
| `fb49e60` | Dropped two unreachable bits of the editor — **the release SHA** |

Two of those exist because a gate caught something real, which is the point of
having them:

- **Schema drift failed on `9dc9afa`**, correctly: the migration added
  `trips_journey_leg_proof.idempotency_key` and its partial unique index, and
  the committed SQL contract still described the database without them. The
  regenerated contract's whole diff is those two objects.
- **A new Arabic/TalkBack test failed on the first editor**, and it was not the
  test's fault. The stop row wrapped an `InkWell` in
  `Semantics(button: true, excludeSemantics: true, …)`, which discards the
  child's tap action on the way up — a control a screen reader announces and
  cannot press, the exact defect Phase 8E went through the app to remove. Fixed
  the way the location picker's rows already do it: label *and* action on the
  Semantics node, `ExcludeSemantics` underneath.
- **Flutter CI failed on `8c4fde6`** where the local run passed: CI runs a
  newer Flutter in which `SemanticsData.hasFlag` is deprecated, and it analyses
  with `--fatal-infos`. The tap-action assertion is the one that matters and is
  what the existing activation tests check, so the flag assertion went.

**Local gates before the push.** Django 1159 passed / 34 skipped on PostgreSQL
16 (`--ds=config.settings.dev`), `ruff check .` clean, `makemigrations --check`
clean. Flutter 343 passed, `dart format` clean, `flutter analyze
--fatal-infos` clean.

**CI** run `33796400375` on `fb49e60`: **success**, all six jobs — Flutter,
Django, Go build/vet/unit, Go integration (real Redis), Schema drift,
Production config + static web.

**Railway deployment** `5a967012-0ff2-4bf7-84c0-43d1b2a3a2bf`, project
`shiptripis`, service `shiptrip`, production environment. `/readyz` 200 with
`release: v1.0.0-rc.3+fb49e60` and `database`, `migrations`,
`rate_limit_cache` all `ok`. Two variables changed and nothing else:
`RELEASE_ID` and a new explicit `S3_BUCKET_PROOF=shiptrip-media-h6a-np-6v`.
No payment rail was enabled, disabled or exercised, and no provider secret was
read, printed or logged.

##### The deployed proof upload, before and after

Railway's own HTTP log is the whole story. Before, on `v1.0.0-rc.2+0a61cba`:

```
12:09:43 POST /api/journeys/1/legs/2/proof 500  455ms
12:10:02 POST /api/journeys/1/legs/2/proof 500  411ms
12:10:08 POST /api/journeys/1/legs/2/proof 500  279ms
12:10:20 POST /api/journeys/1/legs/2/proof 500 1213ms
```

After, on `v1.0.0-rc.3+fb49e60`, with a synthetic traveller
(`phase8fa-…@shiptrip-test.invalid`) and no payment of any kind:

```
19:44:45 POST /api/journeys                   400  20ms   ← DZ→FR drive refused
19:44:45 POST /api/journeys                   201  48ms
19:44:47 POST /api/journeys/4/legs/5/proof    201 1266ms  ← the finding, fixed
19:44:47 POST /api/journeys/4/legs/5/proof    200   12ms  ← retry, same key
19:44:48 POST /api/journeys/4/legs/5/proof    415   10ms  ← PDF refused
```

Verified against the deployment, end to end:

- The Algeria → France **DRIVE** leg is refused with
  `journey_leg_mode_unavailable` and `required_mode: FLIGHT`.
- The proof lands at
  `shiptrip-media-h6a-np-6v/journeys/4/legs/5/proofs/l1fEu3tare9YW5Vf3VF_bg.png`
  — the bucket Django's own credential owns.
- **Read back with Django's deployed credential**: 513 bytes, `image/png`,
  byte-identical to what was uploaded. That is precisely the operation the
  admin console's evidence redirect performs, so the proof is servable for
  review. (The console *page* was not opened: that needs an authenticated
  admin session, which is an owner action.)
- A retry with the same idempotency key returns **200 and the same proof id**;
  the database holds one row, not two.
- `PATCH /api/journeys/4` with only the capacity changed: `proofs_reset_for_
  review: 0`. The same PATCH changing the flight number and dates:
  `proofs_reset_for_review: 1`, and the proof's own metadata records
  `flight_leg_materially_changed`, `['flight_number', 'depart_at',
  'arrive_at']`, `previous_status: pending`.
- `GET /api/journeys/4` serves the owner `editable: true`,
  `edit_blocked_code: null`.

`manage.py check_object_storage` run against the deployed credentials reports
`proof`/`parcel`/`dispute` (all `shiptrip-media-h6a-np-6v`) **writable and
readable**, and `kyc` (`shiptrip-kyc-i7wgelkvyjp9`) **403** — see the blockers
below.

##### Android profile artifact

- **Workflow** run `33798036038` on `fb49e60`, `build_type=profile`,
  `apk_architecture=arm64`,
  `api_base_url=https://shiptrip-production.up.railway.app`.
- **Artifact** `shiptrip-v1.0.0-rc.3-fb49e60-profile-arm64`, APK
  `shiptrip-v1.0.0-rc.3-fb49e60-profile-arm64.apk`, **33,792,232 bytes
  (32.23 MiB)**, SHA-256
  `e5afba162869c6781992b19b74a6d31f1ccf578265ce6fe24fbb3b7373b4c462`
  — recomputed locally, matching the runner's `SHA256SUMS.txt`.
- **Proved to be profile, not debug or release**, from the artifact itself:
  AOT `lib/arm64-v8a/libapp.so` present; `libvmservice_snapshot.so` present,
  which only a profile build ships; `kernel_blob.bin`, `isolate_snapshot_data`
  and `libVkLayer_khronos_validation.so` all absent.
- **ARM64 targeting held**: `lib/arm64-v8a/` carries 25.52 MiB of real code,
  while `armeabi-v7a` and `x86_64` carry only a 0.05 / 0.10 MiB JNI shim each
  — the same pattern as 8E-A, and the same 32.23 MiB total.
- **Configuration**: `https://shiptrip-production.up.railway.app` is inside the
  Dart AOT snapshot; the `10.0.2.2` development default does not appear. An
  eleven-pattern secret scan over every entry in the APK (Stripe secret /
  restricted / publishable / webhook keys, Chargily keys, Tigris storage ids
  and secrets, AWS key ids, PEM private-key blocks, Postgres DSNs, SMTP
  password markers) found nothing.
- **Same signer caveat as 8E-A.** This is an auto-generated debug key on a new
  runner, so it will not update an installed 8E-A APK in place. Uninstall the
  previous build first; Android refuses a same-`applicationId` update from a
  different signer with `INSTALL_FAILED_UPDATE_INCOMPATIBLE`.

##### Findings that remain open

- **MAJOR, and out of this phase's scope — KYC admin evidence cannot be
  viewed.** The same credential mismatch that broke flight proof still applies
  to KYC: `admin_panel.console_views.kyc_evidence` presigns against
  `settings.S3_BUCKET_KYC`, and Django's key is denied on that bucket. Proved
  directly — `check_object_storage` reports `kyc … head_bucket failed: 403`,
  and a direct probe returns `AccessDenied` for Django's key and success for
  the Go service's. The reviewer therefore gets a broken evidence link, not the
  image. Phase 8F-A was explicitly scoped away from KYC admin evidence, so this
  was **not** fixed here; it is a one-line bucket/credential decision for
  8F-B, and the new management command is the tool for confirming it.
- **MINOR** — the two synthetic verification travellers, their draft journeys
  (ids 3 and 4) and two proof objects remain in the private environment as
  evidence. They are drafts, so no sender can see them.
- **MINOR** — `ruff format` cleanliness across roughly thirty pre-existing
  files, still deliberately untaken in a release phase. `ruff check` is clean.
- Unchanged from 8E-A: no signed Android release until the four
  `ANDROID_KEYSTORE_*` Actions secrets exist; provider mode remains an owner
  reading from the admin console.

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
