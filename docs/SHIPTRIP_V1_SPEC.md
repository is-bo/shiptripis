# ShipTrip V1 — Product and Technical Specification

SHIPTRIP_V1_SPEC.md is the authoritative ShipTrip V1 product and technical specification. If legacy code, README files, ARCHITECTURE.md, comments, tests, or previous product assumptions conflict with this specification, this specification wins unless the user explicitly overrides it.

**Locked:** 24 August 2026  
**Market:** EU ↔ Algeria  
**Platform entity:** France  
**Canonical marketplace currency:** EUR  
---

## 1. Product definition

ShipTrip is a peer-to-peer parcel-delivery marketplace connecting senders with travelers who already have spare carrying capacity.

V1 is **delivery only**. The existing Kaba/ProductRequest flow is removed from active product behavior.

A traveler does not have a single airport-to-airport “trip.” A traveler has a **Journey** made from ordered **Journey Legs**.

Launch transport modes:

- FLIGHT
- DRIVE

Example:

- Paris → Algiers by flight
- Algiers → Jijel by drive

That traveler may potentially carry parcels:

- Paris → Algiers
- Paris → Jijel
- Algiers → Jijel

Matching operates against feasible **sub-routes**, not just full journeys.

---

## 2. Accounts and verification

One account can be:

- Sender
- Traveler
- Both

A user with both roles switches context without maintaining separate identities.

### Traveler

Traveler KYC is required before publishing any journey.

Only **flight legs require transport proof**. Drive legs do not require car/license/vehicle proof beyond traveler KYC.

If a journey contains a flight leg, required flight proof must be approved before the journey becomes matchable.

### Sender

Sender launch verification is **email-only** unless future risk logic triggers additional checks.

Do not globally require sender phone verification.

---

## 3. Kaba/ProductRequest retirement

The current ProductRequest feature must not remain in the live V1 product.

Migration rules:

1. Audit existing data and dependencies first.
2. Disable creation.
3. Remove from mobile UX.
4. Remove from public API/business flows.
5. Remove from matching/pricing/payment behavior.
6. Keep legacy records safely accessible to admins if they exist.
7. Do not blindly drop tables or data.
8. Remove legacy schema only after a later explicit migration proves no dependency remains.

---

## 4. Currency and money

### Canonical currency

All marketplace economics are EUR:

- delivery reward
- recommended price
- minimum price
- offers
- counteroffers
- commission
- sender total
- posting deposit
- boosts
- refunds
- traveler earnings
- ledger/accounting

Store authoritative EUR values as integer euro cents.

### Chargily

DZD is a **provider settlement representation**, not marketplace truth.

When Chargily is selected:

`EUR canonical amount × admin EUR→DZD rate = Chargily DZD amount`

Checkout shows:

- canonical EUR amount
- DZD amount charged
- exchange rate used

The server calculates the DZD amount.

The client must never supply an authoritative exchange rate or converted amount.

Each Chargily attempt snapshots:

- EUR amount
- DZD amount
- EUR→DZD rate
- provider IDs
- timestamp

Changing the admin rate later must not change old payments.

### Stripe

Stripe customer payments remain EUR-native whenever possible.

### Traveler payouts

Traveler liability/earnings remain recorded in EUR.

If an admin manually pays a traveler in DZD or another currency, record:

- EUR obligation
- actual payout currency
- actual amount
- FX rate used if applicable
- method/provider
- reference/receipt
- admin actor
- timestamp

---

## 5. Locations

Airport-only origin/destination is no longer the core model.

The active V1 geography flow is:

1. country
2. canonical catalogue place
3. optional preferred exact meeting point

Users do not create matching cities. A canonical `Place` is a stable ShipTrip
catalogue locality/municipality/commune or airport. Its immutable identity, not
its mutable display label, is authoritative.

Every selected place has one backend-owned **matching locality**:

- a locality/municipality/commune resolves to itself;
- an airport resolves through one explicit active primary served-locality
  mapping;
- an airport without a reliable mapping is unavailable for matching.

Matching locality is derived from the selected canonical place. It is not
inferred from free text, map labels, coordinates or preferred-point distance.

The existing user-owned `Location` model is retained only for an optional
preferred exact point inside the selected canonical context. It may store:

- normalized label/address
- latitude/longitude
- geocoding provider/source
- provider place ID where available
- precision level
- public/coarse label
- private/exact label

The backend validates a new preferred point against the selected country and
locality using the existing provider abstraction. Insufficient provider context
fails transparently; it never assigns a different canonical city. The map is
therefore used only after place selection to answer where within that place a
participant prefers to meet, and it is optional during request/journey creation.
Active preferred-point, request and Journey write APIs require canonical Place
references; pre-8C location-only records may remain readable but cannot be
newly created.

### Privacy

Before funding, the counterparty sees only coarse information such as city/neighborhood.

Do not reveal exact:

- street
- building
- private map pin
- recipient address

The backend may use exact coordinates internally for authorized operational
purposes before funding, but they never decide basic V1 locality compatibility.

Exact pickup/dropoff unlocks to the relevant parties only after the deal is funded.

### Maps

Abstract:

- geocoding
- reverse geocoding
- directions
- route distance
- route polyline

Do not lock the domain to one vendor.

---

## 6. Journey model

### Journey

Recommended fields:

- traveler
- overall start
- overall destination
- status
- publication/verification state
- notes
- timestamps

Suggested status:

- draft
- pending_verification
- active
- in_progress
- completed
- cancelled
- expired

### JourneyLeg

Ordered by position:

- journey
- position
- mode: FLIGHT | DRIVE
- canonical origin place
- canonical destination place
- optional preferred origin/destination points scoped to those places
- depart_at
- arrive_at
- capacity_kg
- route/distance metadata

### Flight leg

Additional:

- flight number
- departure airport metadata
- arrival airport metadata
- proof media
- proof status
- reviewer
- reviewed_at
- rejection reason

### Drive leg

No transport proof at launch.

Store route/polyline when possible and allowed detour parameters.

### Transport-mode availability (locked, Phase 8F-A)

A leg's mode is constrained by geography, not chosen freely. Countries belong
to **road networks**; two places may be joined by DRIVE only when they sit on
the same one.

- Algeria is its own road network.
- France, Spain and Germany share the continental European road network.
- A country with no declared network is its own island, which fails closed.

Therefore, for V1:

- **Any leg between Algeria and any non-Algerian country must be FLIGHT.**
  Algiers → Paris, Jijel → Marseille and Madrid → Algiers are flight-only.
  DRIVE is refused for these pairs.
- Within Algeria, DRIVE is allowed.
- Between supported European countries, DRIVE remains allowed
  (France → Germany, France → Spain).
- V1 has no ferry or sea transport. Adding one is a product decision with
  proof, capacity and timing consequences, not a table entry.

This is enforced **server-side** as the authority. A stale or hand-written
client that submits an Algeria ↔ Europe DRIVE leg is refused with the
structured code `journey_leg_mode_unavailable`, carrying `leg_position`,
`required_mode`, `origin_country` and `destination_country`. Publication
re-checks the rule, so a leg that became impossible after it was written
cannot reach senders. The Flutter route editor prevents the choice
proactively and never offers a mode the pair cannot have.

### Route UX: stops, not legs (locked, Phase 8F-A)

Travellers build a route by naming **stops**; ShipTrip derives the legs
between them. Segment *k* runs from stop *k* to stop *k+1*, which makes leg
positions contiguous, the first leg's origin the journey's start, and every
leg's origin the previous leg's destination — structurally, not by
validation.

Required behaviour:

- set origin, set destination, **insert an intermediate stop between any two
  existing stops**, add further stops, remove an intermediate stop, change any
  stop, and reorder intermediate stops where safe.
- Inserting a stop must never require deleting the destination first.
- Positions are never exposed as list indexes in the interface.

Two consecutive stops must resolve to **different canonical matching
localities**. Because an airport resolves to the locality it serves, an
airport and its city are the same stop, not two — "CDG then Paris" is not a
leg.

### Airports as a facet of a stop (locked, Phase 8F-A)

A FLIGHT leg still starts and ends at airports. A city is **never silently
converted** into an airport. Instead a stop carries the airport it is reached
by, chosen explicitly, and the route reads:

    Jijel  —DRIVE→  Algiers · ALG  —FLIGHT→  Paris · CDG

The journey's own start and destination stay the places the traveller named;
the legs carry the airports. The two agree because the endpoint check
compares matching localities, not place ids.

### Creation and editing UX

Support both:

- manual multi-stop creation
- assisted journey creation

Example assisted flow:

User says overall route Paris → Jijel, enters Paris → Algiers flight, and the app offers to add Algiers → Jijel as a drive leg.

### Editing an existing Journey (locked, Phase 8F-A)

A Journey the traveller owns is editable while it is **draft** or
**pending_verification** *and* nothing depends on its route. Every other
status — active, in_progress, completed, cancelled, expired — is refused,
as is any journey carrying a Deal or a pending/accepted Match.

- The edit replaces the whole ordered chain in one authoritative write, under
  the aggregate lock, and is re-validated exactly as publication would be.
- A leg the client is keeping carries its `id`. That identity is what lets an
  unchanged flight leg keep its reviewed proof across an edit.
- A refusal is **explained**, never merely hidden: the API serves `editable`
  and `edit_blocked_code` to the owner, and the interface states the reason.

### Proof consequences of an edit (locked, Phase 8F-A)

Changing a flight leg's **origin airport, destination airport, flight number,
departure time or arrival time** means its proof no longer evidences that
flight. Such proof is **not left attached**: an approved or pending proof is
returned to `pending` for re-review, with the previous decision, reviewer and
changed fields preserved in the row's `metadata` audit trail. A rejected
proof is left rejected. Proof belonging to a leg the edit removes is
discarded with it. The API reports both counts so the traveller is told.

---

## 7. Delivery request

A sender request should contain:

### State
- sender
- status
- published_at
- deadline/expiry
- optional targeted traveler/journey

### Locations
- canonical pickup place
- canonical delivery place
- optional private preferred pickup point scoped to the pickup place
- optional private preferred delivery point scoped to the delivery place
- safe canonical place/airport summaries before funding

### Timing
- ready time/window
- delivery deadline
- flexibility

### Parcel
- title
- description
- category
- actual weight — **required**
- length/width/height — **optional**, all three together or none. An empty set
  is accepted and prices on actual weight alone (volumetric weight is zero); a
  partial set is refused with a single `dimensions` error. Empty dimensions
  must never prevent posting, and must never make a posted request
  undiscoverable or unmatchable.
- declared value
- photos — **at least one photograph of the actual item is required**. It is
  marketplace evidence of the shipment, not identity evidence: it lives in the
  private media bucket Django's own credential owns, never in the KYC bucket,
  and is served only through a short-lived signed URL to the sender, to staff,
  to the addressee of a targeted request, or to any authenticated user once the
  request has been published. The photo is uploaded *before* the request is
  created and consumed by the create call in the same transaction, so no failed
  upload can leave a live request with no image.
- handling notes — optional
- fragile flag if supported

### Safety/customs
Sender affirms:

- description is accurate
- item is legal
- no prohibited goods
- value is accurate
- applicable customs/import responsibilities are understood

Maintain an admin-configurable prohibited-goods policy.

---

## 8. Pricing engine

ShipTrip should borrow the structure of carrier pricing—distance/zone plus chargeable weight—without copying expensive courier retail tariffs.

### Chargeable weight

Use:

`volumetric_weight_kg = (L_cm × W_cm × H_cm) / 5000`

Then:

`chargeable_weight_kg = max(actual_weight_kg, volumetric_weight_kg)`

Default pricing weight rounding: upward to 0.5 kg.

### Matched distance

Price the matched request sub-route, not necessarily the traveler's full journey.

Use:

- routed road distance for drive legs
- consistent flight/great-circle distance for flight legs
- sum relevant covered legs

### Minimum traveler reward

`minimum_reward = max(global_floor, distance_base + chargeable_weight × weight_rate)`

Seed defaults:

| Distance | Base |
|---|---:|
| 0–100 km | €4 |
| >100–300 km | €6 |
| >300–750 km | €9 |
| >750–1,500 km | €12 |
| >1,500–3,000 km | €16 |
| >3,000–5,000 km | €20 |
| >5,000 km | €24 |

Seed:

- global floor: €7
- weight rate: €2.50/kg

All parameters are admin-configurable.

### Recommended traveler reward

Default:

`recommended = round_up(minimum × 1.20 + detour_adjustment + urgency_adjustment)`

Round to €0.50.

No opaque dynamic surge pricing at launch.

Show the user:

- minimum
- ShipTrip recommendation
- chosen traveler reward

### Offer economics

The **sender proposes first**.

The negotiated amount is the **traveler reward**.

Example:

- traveler reward: €30
- commission: 25%
- ShipTrip fee: €7.50
- sender total: €37.50

Commission is globally admin-configurable and snapshotted when the offer/deal is created.

Do not silently subtract commission from what the traveler believes they accepted.

---

## 9. Matching

Matching has:

1. hard compatibility
2. ranking

### Hard compatibility

Require:

- traveler KYC valid
- journey active
- required flight proof approved
- request active
- pickup before delivery on journey
- feasible route
- feasible time/deadline
- sufficient capacity on every covered leg
- operational road feasibility within configured threshold (never a substitute
  for canonical-locality identity)
- item allowed
- safety rules pass
- request and ordered journey subroute endpoints resolve to the same canonical
  matching-locality IDs

Boost can never override these.

### Canonical locality matching

For V1, basic origin/destination compatibility is exact equality of canonical
matching-locality identity. A journey's ordered leg nodes preserve subroute
matching, so a request may join at one matching locality and leave at a later
matching locality without collapsing the leg order.

Preferred pins do not alter this result. Two different localities do not become
compatible because their coordinates are close. Radius matching, neighboring
municipalities, automatic nearby-city compatibility and geographic detour
scoring are not active V1 features.

Airport/locality interoperability occurs only when the catalogue explicitly
defines the airport as serving that locality. It does not make every airport
equivalent to every locality in its administrative region.

### Ranking

Use explainable factors:

- route fit
- time fit
- traveler rating
- reliability/completion
- cancellation/no-show history
- verification
- activity/response
- request freshness
- sender boost

Boost affects ranking only and must be labeled.

### Geospatial DB

Prefer PostGIS if the production Railway PostgreSQL setup can support it safely.

Do not blindly migrate databases. Audit and rehearse the extension/migration first.

---

## 10. Segment-aware capacity

Capacity is per journey leg.

Example, 20 kg capacity:

- 10 kg Paris→Algiers
- 5 kg Paris→Jijel
- 8 kg Algiers→Jijel

Load:

- first segment = 15 kg
- second segment = 13 kg

Valid.

Create per-leg reservations/allocations.

Suggested reservation states:

- pending_payment
- funded
- in_transit
- released
- completed
- cancelled

When an offer is accepted:

1. DB transaction
2. lock relevant leg rows
3. recompute reserved/active capacity
4. verify all segments
5. reserve capacity atomically
6. create Deal
7. fail cleanly if concurrent acceptance consumed remaining capacity

Never rely only on client checks or Redis locks.

---

## 11. Offers and Deal

### Offers

- sender creates initial offer
- traveler accept/decline/counter
- sender may counter
- only non-proposer acts on current pending offer
- proposer may withdraw
- one pending offer in the chain
- one accepted offer leading to an active Deal

No arbitrary 24h offer expiry.

System may invalidate an offer if:

- request expired
- deadline passed
- journey cancelled/departed
- capacity disappeared
- account suspended
- safety state changed

Each offer snapshots:

- traveler reward
- commission rate
- fee
- sender total
- pricing version
- relevant terms

### Deal

Accepted offer creates first-class Deal.

Lifecycle:

1. offer_accepted
2. payment_required
3. funded
4. pickup_ready
5. picked_up
6. in_transit
7. delivery_ready
8. delivery_confirmed
9. protection_window
10. completed

Side/terminal states:

- cancelled
- expired
- payment_failed
- disputed
- refunded
- partially_refunded

Use explicit domain/service transition functions.

Append immutable timeline events for critical transitions.

---

## 12. Posting deposit

Global mode:

- AFTER_ACCEPTANCE
- POSTING_DEPOSIT

Intended V1 setting is POSTING_DEPOSIT.

Recommended seed:

`deposit = clamp(10% of recommended sender total, €3, €7)`

Admin-configurable.

Deposit:

- required before publication in deposit mode
- credited to final Deal payment
- not an extra hidden fee
- auto-refunded if request expires unmatched
- fully refunded if sender cancels before accepted offer
- remains represented in payment/refund ledger

---

## 13. Payment architecture

The current one-PaymentIntent-per-accepted-Offer model is not sufficient.

Create:

### PaymentOrder

Canonical EUR obligation.

Purposes:

- posting_deposit
- deal_balance
- boost

Track:

- owner
- canonical EUR amount
- credits
- outstanding amount
- status
- related request/deal/boost
- terms snapshot

### PaymentAttempt

Provider-specific attempt.

Track:

- order
- provider
- payer user nullable
- guest payer nullable
- canonical EUR amount
- payment currency
- provider amount
- FX snapshot
- provider IDs
- idempotency
- state/failure

Providers:

- STRIPE
- CHARGILY
- MOCK only for tests/local—not production

### Core payment security

- backend calculates money
- backend creates checkout
- signed provider webhooks
- unique provider event IDs
- idempotent handling
- safe duplicate/out-of-order events
- redirect is not authoritative success
- production mock payment forbidden

---

## 14. Stripe

Use EUR customer checkout.

Support third-party payment:

1. sender taps “Have someone else pay”
2. backend creates transaction-specific guest Stripe link
3. guest needs no ShipTrip account
4. webhook funds sender-owned Deal
5. guest gets no chat/deal/dispute authority

Guest link:

- unguessable
- expiring
- revocable
- minimal information

### Payout

Do not hard-code “all Algerian travelers are payable by Stripe.”

Use payout capability abstraction and verify actual ShipTrip account/country capability.

If unavailable, use manual payout fallback.

---

## 15. Chargily

Checkout displays:

- EUR canonical amount
- DZD amount
- `€1 = X DZD`

Admin controls `chargily_eur_dzd_rate`.

Every change is audited.

Admin can disable **new** Chargily checkouts without breaking:

- existing payments
- webhooks
- reconciliation
- refunds

Chargily-funded traveler payouts enter manual payout flow unless another eligible payout method exists.

---

## 16. Ledger and payout

Preserve append-only accounting concepts.

Track:

- customer payment
- traveler liability
- commission
- posting-deposit credit
- refund
- payout
- correction/reversal

Use compensating entries rather than silently rewriting history.

Avoid legal “escrow” claims unless legal/payment structure truly qualifies.

Prefer product wording:

- Payment protected
- Funds held pending delivery
- Payout pending confirmation

---

## 17. Pickup and delivery codes

Use cryptographically random codes.

Store hashes only.

Rate-limit and cap attempts.

Never log plaintext.

### Pickup code

After funding:

- sender can see pickup code
- traveler cannot see it
- sender gives it when parcel is physically handed over
- traveler enters it
- success confirms pickup and starts delivery-code timer

### Delivery code

Locked rule: **30-minute buffer after pickup confirmation**.

During first 30 minutes:

- sender cannot reveal it
- recipient email is not sent
- traveler cannot access it

After 30 minutes:

- email code to recipient
- reveal it in sender app
- traveler still cannot fetch it

Recipient gives code to traveler at handoff.

Traveler enters it.

Success confirms delivery and begins the protection window.

---

## 18. Recipient

Collected after funding.

Required:

- name
- email

Optional:

- phone
- delivery note

Protect recipient PII and do not expose it in public matching.

---

## 19. Disputes

Protection/dispute window: **48 hours after delivery confirmation**.

Opening a dispute always freezes payout.

Suggested statuses:

- open
- awaiting_evidence
- under_review
- resolved
- closed

Evidence bundle automatically includes:

- Deal timeline
- offer history
- pricing/terms snapshots
- payment events
- payout events
- code attempt/events
- chat
- journey/flight proof references
- request snapshot
- relevant location/timing events
- admin actions

Users may add:

- text
- photos
- video

Admin resolutions:

- full sender refund
- full traveler payout
- partial split

Partial split must create explicit financial entries.

---

## 20. Cancellation/no-show

Make policy parameters admin-configurable and snapshot them into the Deal.

Recommended seed policy:

### Before accepted offer
- cancel allowed
- full deposit refund

### After accepted offer before funding
- cancel
- release capacity
- no payout

### After funding before pickup
Traveler cancels:
- full sender refund

Sender cancels:
- >24h before pickup: full refund
- <24h: traveler compensation default 10% of traveler reward, cap €15; remaining amount refunded

### No-show
Launch:
- admin-reviewed
- verified traveler no-show → full sender refund
- reliability/risk impact

### After pickup
No normal cancellation; use dispute/admin resolution.

---

## 21. Payout protection

Delivery confirmation starts a **48-hour protection window**.

No payout during it.

At expiry:

- no dispute → schedule/release payout
- dispute → remain frozen

Critical payout jobs must be durable/idempotent and survive Redis/process restarts.

---

## 22. Ratings

Bidirectional.

One rating per side per completed Deal.

Recommended:

- 1–5 overall
- optional tags
- optional text
- 14-day review window
- blind reveal until both submit or window closes

---

## 23. Boost

Only sender delivery requests can be boosted.

Boost:

- ranking only
- clearly labeled
- admin-configurable packages
- separate payment order
- cannot bypass route/capacity/KYC/safety/time eligibility

---

## 24. Chat

Chat allowed only for legitimate funded Deals between the actual sender and traveler.

Keep history after completion/cancellation according to policy, but restrict new messages once closed unless a support flow explicitly permits it.

---

## 25. Notifications and Sender.net

Events include:

- match
- offer/counter
- accepted
- payment required/succeeded/failed
- recipient required
- pickup ready/confirmed
- delivery code available to sender
- delivered
- dispute
- payout
- KYC/proof
- cancellation

Use Sender.net for transactional email.

The existing SMTP worker can be configured to Sender SMTP for V1.

Require:

- verified domain
- SPF
- DKIM
- DMARC
- TLS
- env secrets
- durable/idempotent retryable email jobs

Critical emails:

- verify email
- password reset
- admin invite
- recipient delivery code
- payment status
- dispute status
- payout status
- cancellation/security

---

## 26. Admin

Recommended roles:

- Operations Admin
- Support Agent
- Finance Admin
- Trust & Verification Admin
- Super Admin

Use granular permissions underneath.

### Super Admin

Bootstrap idempotently from environment variables.

Do not create through normal public invite path.

### Admin invites

- email invite
- one-time cryptographically random token
- hash at rest
- default 24h expiry
- bound to email
- assigned role/permissions
- auditable create/revoke/use

### Admin dashboard sections

- overview KPIs
- users
- requests
- journeys/legs
- matches
- offers
- Deals
- payments/refunds
- payouts
- disputes
- KYC
- flight proof
- safety/risk
- ratings
- boosts
- provider health
- settings
- admin users
- roles/permissions
- invites
- immutable audit log

### Business settings

At minimum:

- payment timing
- posting deposit
- commission
- pricing bands/rates
- detour radius
- Chargily enabled
- EUR→DZD rate
- Stripe enabled
- payment grace
- cancellation cutoff/compensation
- 30m code buffer
- 48h protection
- boost packages

---

## 27. Mobile navigation

Bottom navigation:

1. Home
2. Deliveries
3. Chat
4. Profile

Notifications use header/bell.

### Deliveries

Sender:
- Published/Matching
- Offers
- Payment Required
- Pickup
- In Transit
- Protection/Dispute
- History

Traveler:
- Journeys
- Offers
- Awaiting Payment
- Pickup
- Carrying
- Payout Pending
- Completed
- Disputes

Combine “My Trips” + “Carrying” into one coherent traveler activity experience.

### Critical bug

Fix bottom-navigation overlap everywhere:

- lists
- forms
- chat composer
- maps
- sheets
- keyboard
- small phones
- gesture navigation
- iPhone home indicator
- landscape
- nested navigation
- long pages

No content/CTA may sit underneath the bottom bar.

The frontend must undergo an Impeccable audit covering visual hierarchy, typography, spacing, states, accessibility, RTL, localization, maps, money clarity and lifecycle clarity.

---

## 28. Landing site

Languages:

- French
- Arabic RTL
- English

Include:

- value proposition
- sender flow
- traveler flow
- flight + drive explanation
- safety/KYC
- payment protection
- fees
- FAQ
- app download
- support
- Terms
- Privacy
- prohibited-items/safety

Avoid unqualified “escrow” claims.

---

## 29. GDPR/privacy engineering

Implement privacy by design/default.

Capabilities:

- versioned Terms/Privacy acceptance
- export request
- correction
- deletion request
- portability where applicable
- consent/preferences where required
- retention classes
- legal-retention exceptions
- sensitive admin access logging
- least privilege
- exact-location privacy
- recipient minimization
- KYC access restrictions

Final French/EU marketplace, consumer, DSA, customs and payment-services position requires qualified legal review.

---

## 30. Security

Audit:

- JWT/session lifecycle
- object-level authorization
- webhook signatures
- replay/idempotency
- code security
- file MIME/signature/size
- private object storage
- admin permissions
- invite security
- CORS/CSRF
- rate limits
- secret management
- dependency risk
- security headers
- structured PII-safe logs

Hard invariants:

- traveler never reads delivery code
- exact address never leaks before funding
- client never controls FX or authoritative price
- guest payer gets no Deal authority
- payout cannot happen during dispute or before protection ends

---

## 31. Performance/reliability

- PostGIS/GiST where safe
- B-tree indexes
- EXPLAIN matching queries
- no N+1
- pagination
- route/geocode cache
- cache never authoritative
- transactional capacity
- mobile retry/jitter
- image compression/thumbnails
- avoid unnecessary Flutter rebuilds
- durable critical jobs
- observability for DB, matching, payment, payout, email and queue failures

Redis may accelerate work but must not be the only place an authoritative financial/delayed obligation exists.

---

## 32. Testing

Unit:

- pricing
- volumetric weight
- FX
- commission
- deposit
- matching
- route order
- capacity
- cancellation
- code timer
- protection timer

Invariant/property tests:

- no payout before 48h
- no payout while disputed
- traveler cannot see delivery code
- no exact address before funding
- boost cannot create compatibility
- capacity never negative
- refunds never exceed paid amount
- no two funded Deals for same request
- FX snapshots immutable

Concurrency:

- last-capacity race
- duplicate webhook
- dispute vs protection timer
- duplicate payout
- counteroffer race
- code retries

E2E:

Sender:
create → deposit → publish → offer/counter → accept → pay → recipient → pickup → delivery → protection → complete → review

Traveler:
KYC → journey → proof → offer → funded → pickup → carry → delivery → payout → review

Also test:
- cancellation
- no-show
- full refund
- full payout
- partial split
- guest payer
- Chargily FX
- boost
- mixed flight+drive

---

## 33. Current-repo migration facts

Respect the existing architecture:

- Django owns migrations.
- Go depends on generated SQL/schema contracts.
- Flutter is the mobile client.
- current payments are still mock-oriented
- existing request/trip schema is airport-centric
- pricing is DZD-centric
- current Offer model assumes traveler-first initial offer
- PaymentIntent is tied one-to-one to accepted Offer
- ProductRequest exists
- constrained Railway Redis may be ephemeral

Migration principles:

1. inspect before editing
2. add new schema
3. migrate/backfill safely
4. temporary compatibility only where needed
5. switch application behavior
6. remove legacy paths after verification
7. regenerate SQL/sqlc after Django migrations
8. keep schema-drift gate
9. preserve historical IDs/economics where practical
10. do not invent historical EUR exchange rates
11. data-migration tests
12. rollback notes

Recommended new concepts:

- Location
- Journey
- JourneyLeg
- JourneyLegProof
- CapacityReservation/DealLegAllocation
- Deal
- DealTermsSnapshot
- PaymentOrder
- PaymentAttempt
- Payout
- Dispute
- DisputeEvidence
- Rating
- BoostPurchase
- versioned BusinessSetting
- AdminInvite
- AdminAuditEvent
- durable Outbox/ScheduledJob

Reuse good foundations:

- accounts/JWT
- KYC pipeline
- object storage
- chat gating concept
- notification service
- append-only wallet ideas
- hashed handover-code ideas
- migration/schema-drift tooling
- gateway separation



---

# 34. Release acceptance checklist

## Product
- [ ] Delivery-only live product
- [ ] both-role account
- [ ] EU↔Algeria real-world locations
- [ ] flight + drive multi-leg
- [ ] flight proof
- [ ] drive requires no transport proof
- [ ] sender-first offers
- [ ] both-way counteroffers
- [ ] multiple parcels/journey
- [ ] segment capacity safe
- [ ] EUR min/recommended pricing
- [ ] commission snapshots
- [ ] ranking-only boost

## Payment
- [ ] posting deposit
- [ ] deposit credit
- [ ] Stripe
- [ ] guest payer
- [ ] Chargily EUR+DZD+rate
- [ ] admin FX control
- [ ] immutable FX snapshots
- [ ] refunds reconcile
- [ ] payout abstraction
- [ ] manual payout queue
- [ ] mock blocked in prod

## Handover
- [ ] secure pickup code
- [ ] secure delivery code
- [ ] 30m reveal delay
- [ ] 30m recipient email delay
- [ ] traveler cannot fetch delivery code
- [ ] 48h protection

## Disputes
- [ ] dispute freezes payout
- [ ] evidence bundle
- [ ] full refund
- [ ] full payout
- [ ] partial split
- [ ] ledger reconciliation

## Admin
- [ ] env super admin
- [ ] secure invites
- [ ] granular permissions
- [ ] KYC/proof queues
- [ ] disputes
- [ ] finance
- [ ] FX/settings
- [ ] provider switches
- [ ] audit log

## UX
- [ ] Home/Deliveries/Chat/Profile
- [ ] notifications in header
- [ ] no bottom-nav overlap
- [ ] coherent My Trips/Carrying
- [ ] Arabic RTL
- [ ] French
- [ ] English
- [ ] accessibility
- [ ] loading/error/offline
- [ ] polished admin
- [ ] polished landing

## Engineering
- [ ] migration rehearsal
- [ ] schema drift
- [ ] concurrency tests
- [ ] payment idempotency
- [ ] durable critical jobs
- [ ] geospatial/index plan
- [ ] performance audit
- [ ] security audit
- [ ] privacy audit
- [ ] backup/restore
- [ ] observability
- [ ] release artifacts

---

# 35. External blockers code cannot solve

1. Stripe account/capability approval.
2. Chargily merchant credentials/approval.
3. Sender.net account + DNS authentication.
4. Production map-provider credentials.
5. Apple/Google developer accounts.
6. Final French/EU legal review.



---

# 36. Non-negotiable invariants

1. EUR is truth; DZD is a provider/manual settlement representation.
2. Exchange rates are server-controlled and snapshotted.
3. Journey = ordered legs, not one airport pair.
4. Capacity = per segment.
5. Sender proposes first.
6. Price floor uses distance + chargeable weight.
7. Boost never bypasses compatibility.
8. Exact locations remain private until funded.
9. Traveler never receives delivery code.
10. Delivery code remains hidden for 30m after pickup.
11. Dispute freezes payout.
12. Payout waits 48h after delivery confirmation.
13. Kaba/ProductRequest is out of active V1.
14. Financial operations are idempotent and auditable.
15. Critical delayed work survives restart.
16. Super admin comes from env; other admins use secure invites.
17. Existing repository is a foundation, not the final product specification.
18. “Done” means integrated, tested, reviewed and release-gated.
