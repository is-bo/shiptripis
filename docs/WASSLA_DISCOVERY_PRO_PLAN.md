# Wassla Discovery and Professional Delivery Implementation Plan

Written 2026-11-10 for the orchestrator. Product rules: `docs/WASSLA_DISCOVERY_PRO_SPEC.md` ("the spec").
Baseline: `feature/wassla-v3-baseline` at `dd7f820`. Integration branch:
`feature/discovery-professional-delivery`.

The spec says **what**. This plan says **how, in what order, by whom, and what proves it is done**.
If the plan and the spec disagree, the spec wins and the disagreement is a plan bug to report.

---

## 1. How to run this plan

### 1.1 Roles

- **Orchestrator:** hands one work package at a time to an agent, reviews the result against the
  package's "Done when" list, and merges it into the integration branch. Never merges into `main`.
  Never deploys. Both need Ismail's explicit approval.
- **Agent:** implements exactly one work package. Reads, in this order: `CLAUDE.md`, the spec, section
  1 and 2 of this plan, its own package, and the code the package names. Nothing else is in scope.
- **Ownership note.** `CLAUDE.md` and `AGENTS.md` name Codex as the backend owner. For this L-series
  Ismail assigned the work to Claude agents through the orchestrator, backend included. That
  instruction is the owner override both files allow.

### 1.2 Models

Ismail's rule: quality first, save usage where possible. **Opus** for any package that touches
matching, money or codes. **Sonnet** for the rest. Each package states its model. If a Sonnet package
turns out to need a change in `apps/matching`, `apps/finance`, `apps/handover`, `apps/deals/lifecycle.py`
or `apps/deals/cancellation.py`, the agent stops and the orchestrator re-issues that part to Opus.
Two things are not such a change and are allowed in a Sonnet package where the package says so:
adding a new `ScheduledJob` kind and registering its handler (the handler itself lives in the
package's own app), and reading existing finance or deal rows without writing them.

### 1.3 Branches and CI

- One branch per package, from the current tip of the integration branch:
  `l/<package id>-<short name>`, for example `l/l3a-routes-backend`.
- One pull request per package **into `feature/discovery-professional-delivery`**. CI runs on every
  pull request, whatever the base branch.
- A package merges only when CI is green and the gate review is done (1.6).
- Packages run in the order of section 3. A "B" package (mobile) starts only after its "A" package
  (backend) is merged, because the contract must exist first.

### 1.4 The checks every package runs before asking for review

```
# Backend (when Python changed)
cd backend/monolith
ruff check .
python manage.py makemigrations --check --dry-run
python -m pytest -q --ds=config.settings.dev          # PostgreSQL, the whole suite

# Contracts (when a migration was added)
cd backend && task check-drift                          # regenerates schema.sql and sqlc, must be clean

# Go (when Go changed, or a Redis channel was added or renamed)
cd backend/services
gofmt -l . ; go build ./... ; go vet ./... ; go test -race -count=1 ./...

# Mobile (when Dart or ARB changed)
cd mobile
flutter gen-l10n
dart format --output=none --set-exit-if-changed lib test
flutter analyze --fatal-infos
flutter test
```

The whole suite, not the new tests only. A package that makes an existing test fail has not finished.
Never skip, delete or weaken a test to get green. A test that encoded a rule the spec has now changed
is rewritten to the new rule, and the pull request says which and why.

### 1.5 Rules that hold in every package

1. **Server authority.** Every rule in the spec is enforced in Django. The app mirrors rules only to
   avoid offering something the server would refuse.
2. **Money.** No package changes how a fee, total, refund, protection window, arrival floor or payout
   is calculated. EUR integer cents only. A package that needs a new amount derives it from the
   existing functions and snapshots it.
3. **Beside the machine.** Custody, handoff, progress, problems and route changes never write
   `Deal.status` and never call a lifecycle transition, with the single exception of the three
   confirmed-delivery paths in L8A, which call the existing `apply_delivery_confirmed`.
4. **Privacy.** Every public payload is built by an explicit allowlist and has a test that walks the
   JSON and fails on a forbidden key or substring (the pattern is the J4 privacy test for
   `find-travelers`).
5. **Migrations.** Additive only. No column or table is dropped, renamed or narrowed in this series.
   New columns are nullable or have a default that keeps old rows valid. After every migration run
   `task check-drift` and commit the regenerated contract.
6. **Switches.** A new capability reads its switch from the marketplace policy (2.1) on the server, at
   the moment of the action. A switched-off capability answers with a stable machine code and the app
   renders the "not available" state. Nothing is hidden by the client alone.
7. **Audit.** Every staff action added here writes `AdminAuditLog` with actor, action, target, before,
   after and a required reason.
8. **Events.** A new Redis channel is added in three places together: `apps/core/channels.py`,
   the push matrix in `apps/notifications/push.py` (with EN, FR and AR copy), and `subscribeChannels`
   in `backend/services/internal/notification/dispatcher.go`. A Go test compares the lists.
9. **Copy.** Every user-facing string is in the three ARB files (app), or translated in the template
   (web pages and email). `l10n_untranslated.json` stays empty.
10. **No dead code.** A package removes what it replaces in the same pull request. No commented-out
    code, no unused parameter "for later", no second implementation of an existing rule.
11. **Status file.** Each package adds a short dated entry at the top of `docs/IMPLEMENTATION_STATUS.md`
    and writes `docs/PHASE_<id>_<NAME>.md` with what was built, the contract, and the test counts.

### 1.6 Gate review

Before merging a package the orchestrator checks, and records in the pull request:

- every line of the package's "Done when" list, with the evidence;
- the diff contains nothing outside the package's scope;
- for Opus packages: a second, independent review pass focused on races, authorization, idempotency
  and money invariants;
- for mobile packages: screenshots of every new screen in EN and AR, at 360 px wide, with the keyboard
  open where there is a form, in each state the package lists.

### 1.7 When to stop and ask

Stop and report, without guessing, when: a spec rule cannot be implemented as written; a change would
alter a money, code or matching result for an existing deal; a migration would need to drop or rewrite
data; an existing test encodes behaviour the spec does not mention.

---

## 2. Shared design decisions

These are settled. Packages build on them and do not redesign them.

### 2.1 Marketplace policy (switches and settings)

A new section in `BusinessSettingsVersion.policy`, parsed by a typed reader in a new module
`backend/monolith/apps/core/marketplace_policy.py`, in the style of `apps/core/phase4_policy.py`.

```
"marketplace": {
  "discovery":       {"listings_enabled": true, "profiles_enabled": true,
                      "interest_daily_cap": 10},
  "sea_legs_enabled": false,
  "courier_handoff": {"enabled": false, "unconfirmed_review_days": 5, "link_valid_days": 30},
  "professional":    {"applications_enabled": true},
  "traveler_pricing":{"enabled": true, "max_price_per_kg_eur_cents": 10000,
                      "max_min_price_eur_cents": 50000},
  "reminders":       {"enabled": true, "depart_after_minutes": 30, "arrive_after_minutes": 60,
                      "repeat_after_minutes": 180, "max_repeats": 2},
  "route_change":    {"material_shift_minutes": 360}
}
```

- A settings row with no `marketplace` section is valid and means the defaults above, so no existing
  row needs rewriting. Unknown keys are refused when a revision is saved.
- The defaults are the spec's: sea legs and courier handoff ship **off**; everything else ships on.
- `marketplace_policy()` returns a frozen dataclass. Every switch check goes through it.
- The admin Settings page gets one form, "Marketplace features", saved through the existing
  `_save_settings_revision(..., path_updates=..., reason=...)` with permission `manage_settings`.
- The app learns switch states from the endpoints that need them, never from a global flags endpoint.

### 2.2 One function for ticket proof

New module `backend/monolith/apps/trips/proofs.py`:

- `PROOF_REQUIRED_MODES = frozenset({FLIGHT, SEA})`
- `leg_requires_proof(leg) -> bool`
- `leg_proof_satisfied(leg, *, traveler_is_verified_professional) -> bool`
- `journey_proof_gaps(journey, *, at) -> list[leg]`

Every site that today tests `mode == FLIGHT` **to decide about proof** calls these instead. Sites that
test it for a flight-specific reason (flight number, airport endpoints) stay as they are. The known
proof sites at the baseline are listed in section 6.1.

### 2.3 Sea is a mode plus an allowlist

- `JourneyLeg.Mode` gains `SEA`. No new place type.
- New model `locations.SeaCrossing(origin_locality, destination_locality, is_active, created_at,
  updated_at)`, both foreign keys to `Place` rows of type LOCALITY, unique on the ordered pair.
- `apps/trips/transport_rules.py` becomes place-aware. `available_modes` and `check_leg_mode` accept
  the two `Place` rows, resolve each to its matching locality with the existing
  `resolve_matching_locality()`, and add `SEA` when the switch is on and an active crossing joins them.
- `AirportLocalityMapping` and the matching-locality resolution are **not** renamed or generalised.

### 2.4 Verified professional

`apps.professionals.services.is_verified_professional(user, *, at=None) -> bool` is the only answer.
True when the user's `ProfessionalProfile.status` is `verified` and the user is not banned.

### 2.5 Listed price

`apps/matching/listed_price.py::listed_reward(journey, pricing_quote) -> ListedPrice | None`. Returns
`None` when the journey has no price or the switch is off. Otherwise
`max(ceil(price_per_kg_eur_cents * chargeable_weight_kg), min_price_eur_cents, minimum_reward_eur_cents)`.
Fee and sender total come from `calculate_offer_economics`. Nothing else computes a listed price.

### 2.6 Custody is its own app

New Django app `apps.custody` owns custody events, courier handoffs, the recipient link and problems.
It may read deals and call `deals.lifecycle.record_event` for the timeline. It may not write a deal.

### 2.7 Durable timers

Reminders and the 5-day review use the existing `finance.ScheduledJob` through
`finance.services.schedule_job`, with new kinds and handlers registered in `apps/finance/jobs.py`
`HANDLERS`. Each handler re-reads state and does nothing if the work is no longer needed.

### 2.8 Pages for people without an account

The courier page and the recipient page follow `apps/finance/guest_web.py`: a server-rendered Django
page, the token in the path, only its hash stored, every failure rendering the same neutral page,
language from the browser with a one-tap switch, no private data.

### 2.9 Names

- Phase ids are the L series. "V1", "V2", "V3" already mean other things in this repository.
- The Redis channel `flight_proof.status_changed` becomes `leg_proof.status_changed` in L3A. The app
  keeps rendering old inbox rows that carry the old name.
- Admin permission codes `view_flight_proofs` and `review_flight_proofs` keep their codes (they are
  stored in role rows) and are relabelled "Ticket proofs".

---

## 3. Work packages

| # | Package | Model | Depends on |
| --- | --- | --- | --- |
| L0 | Spec and plan (this commit) | done | |
| L1A | Backend cleanup | Opus | L0 |
| L1B | Mobile and docs cleanup | Sonnet | L1A |
| L2A | Discovery backend and marketplace policy | Opus | L1A |
| L2B | Discovery on Home (mobile) | Sonnet | L2A, L1B |
| L3A | Routes for everyone, backend: sea, ticket proof, stops, capacity, pause | Opus | L2A |
| L3B | Routes for everyone, mobile and admin screens | Sonnet | L3A |
| L4A | Traveler pricing, backend | Opus | L3A |
| L4B | Traveler pricing, mobile | Sonnet | L4A, L3B |
| L5A | Progress updates and reminders, backend | Sonnet | L3A |
| L5B | Progress updates and reminders, mobile | Sonnet | L5A, L3B |
| L6A | Professional profile, verification, admin inbox, proof skip | Opus | L3A |
| L6B | Professional Mode, mobile | Sonnet | L6A |
| L7A | Manifest, backend projections | Sonnet | L6A |
| L7B | Manifest dashboard, mobile | Sonnet | L7A, L6B |
| L8A | Custody, courier handoff, recipient confirmation, backend and web pages | Opus | L5A |
| L8B | Custody and handoff, mobile | Sonnet | L8A, L7B |
| L9A | Problems and route changes, backend | Opus | L8A |
| L9B | Problems and route changes, mobile | Sonnet | L9A, L8B |
| L10 | Final acceptance | Opus | all |

This follows Ismail's order: cleanup, then discovery, then sea legs for everyone, then professional
features.

---

## 4. Packages in detail

### L1A. Backend cleanup (Opus)

**Goal.** Remove dead and retired backend code without changing any behaviour a current client uses,
and without touching data.

**Rules for this package.**
- Removal needs evidence, written in the inventory: no route, no importer, no caller in the mobile app,
  no admin console screen, no job handler. "Looks old" is not evidence.
- **No table, column or migration is removed.** A model whose table holds history stays as a model,
  with its migrations, in its app. Only the surfaces around it go.
- No change to matching, pricing, lifecycle, payment or payout results. If a removal would alter one,
  it is listed as "kept, needs decision" instead.
- Deliverable: `docs/WASSLA_L1_CLEANUP_INVENTORY.md` with three lists: removed (with evidence), kept
  (with the reason), needs Ismail's decision.

**Starting inventory found at the baseline** (verify each; this list is a lead, not a verdict):

| Item | Where | Evidence so far |
| --- | --- | --- |
| Unrouted legacy views `TravelerApplyView`, `SenderApplyView`, `CounterOfferView`, `OfferAcceptView` | `apps/matching/views.py` | Not imported by `apps/matching/urls.py` |
| Legacy match services | `apps/matching/services.py` | Check each function for a live caller; it imports the legacy `PaymentIntent` |
| Legacy payments API (`/api/payments/intents` and siblings) | `apps/payments` views, serializers, providers, urls | Mounted after V1 finance; the app is tested not to call it |
| Legacy wallet API (`/api/wallets`, `/api/withdrawals`) and signals | `apps/wallet` | The app is tested not to call it |
| Legacy match-scoped handover routes | `apps/verification` | The mobile test calls these "the ones that leaked plaintext to both parties"; treat removal as a security fix |
| Legacy trips API (`/api/trips*`, `/api/airports`), `TripMediaUploadView` | `apps/trips/views.py`, serializers | Superseded by journeys; `Journey.legacy_trip` still points at the `Trip` model, so the model stays |
| Retired 410 routes (`matches/apply`, `matches/apply-to-trip`, `matches/<pk>/offers/counter`, `parcels/product`, legacy delivery create and quote) | several `urls.py` | Keep one small tombstone module that answers 410 for these paths; delete the legacy implementations behind them |
| `GET /api/matches/compatible-journeys` | `apps/matching/v1_views.py` | Superseded by `find-travelers`; the app has an unused repository method for it |
| Redis channels nobody publishes (`trip.*`, `match.created`, `handover.code_issued` and others) | `apps/core/channels.py`, Go dispatcher list | Remove a channel only when nothing publishes it and no stored inbox row needs it rendered |
| `schema_version` 1 and 2 branches | `apps/matching`, `apps/trips`, `apps/parcels` (about 48 references) | Remove a branch only when it is provably unreachable for live rows; otherwise keep and record |
| Railway launch files | `backend/services/railway*.json`, entrypoint | Needs Ismail's decision: is Railway retired now that hosting is the VPS? Do not remove without it |

**Also in scope.** Django admin registrations, tests, fixtures and settings that exist only for removed
surfaces. `ARCHITECTURE.md`: correct what is false at the baseline.

**Done when.**
- The inventory file exists and every removed item has its evidence.
- `git grep` shows no reference to a removed symbol.
- `makemigrations --check` is clean and no migration file was added or deleted.
- The whole Django, Go and Flutter suites pass. Test counts before and after are in the phase doc, and
  every removed test is listed with the surface it covered.
- A request to each removed route returns 404, or 410 for the tombstones.

### L1B. Mobile and docs cleanup (Sonnet)

**Goal.** The app and the docs contain nothing unused or misleading before new screens are added.

**Scope.**
- Unused repository methods, domain models, widgets, routes and files in `mobile/lib`. Known lead:
  `compatibleJourneys` in `mobile/lib/data/repositories.dart` has no caller. The journey search and
  open-requests methods also have no screen today; **keep them until L2B replaces them**.
- Unused ARB keys in all three languages. Dead assets.
- Extend `mobile/test/legacy_removal_test.dart` so each removed surface stays removed.
- Docs: `CLAUDE.md` and `AGENTS.md` titles say Wassla. Historical phase docs are left as written.

**Rules.** No behaviour change. No visual change. No refactor of working screens "while here".

**Done when.** `flutter analyze --fatal-infos` is clean, the whole Flutter suite passes, the inventory
file gains a mobile section, and golden or screenshot tests are unchanged.

### L2A. Discovery backend and marketplace policy (Opus)

**Goal.** The marketplace policy exists, and the server can answer the three discovery tiers with
strictly public data.

**Build.**

1. **Marketplace policy** exactly as 2.1, with the admin form and tests for: missing section means
   defaults; unknown key refused; each field's bounds.
2. **Public profile.** New app `apps.discovery`. Model `PublicProfile`: `user` (one to one),
   `is_discoverable` (default false), `usual_routes` (up to three pairs of locality place ids,
   validated against the catalogue), `consent_version`, `consented_at`, `prompt_dismissed_at`,
   `hidden_at`, `hidden_by`, `hidden_reason`.
   - `GET /api/discovery/profile/me` returns the settings **and the exact card others would see**.
   - `PUT /api/discovery/profile/me` sets `is_discoverable`, `usual_routes`, `prompt_dismissed`.
3. **Matches tier.** `GET /api/discovery/matches?role=sender|traveler`.
   - Sender: the caller's open delivery requests, newest first, at most 3; for each, the first 3
     candidates from the existing find-travelers page builder, in its existing payload shape, plus
     `more_available`.
   - Traveler: the caller's active journeys, soonest departure first, at most 3; for each, the first 3
     rows from the existing compatible-requests builder.
   - Envelope `state`: `results`, `none` (items exist, nothing compatible), `no_active_items`.
   - It must call the existing builders. It must not evaluate compatibility itself.
4. **Listings tier.** Replace the two unused public endpoints with allowlisted ones and remove the old
   ones (`GET /api/journeys/search`, `GET /api/parcels/open`) and their tests in this same package.
   - `GET /api/discovery/trips?origin_country=&destination_country=&origin_place_id=&destination_place_id=&departing_after=&limit=&offset=`
     returns discoverable journeys (existing `trips.lifecycle.discoverable`, traveler ID-verified,
     proof satisfied, not paused, not the caller's own), soonest departure first, with the spec 4.2
     trip card and a server `next_offset`.
   - `GET /api/discovery/requests?...same filters...` returns open, untargeted, unexpired delivery
     requests that are not the caller's, newest first, with the spec 4.2 request card.
   - Place filters match on matching locality, the same identity matching uses.
5. **People tier.** `GET /api/discovery/people?role=traveler|sender&origin_place_id=&destination_place_id=`
   returns opted-in, not hidden, not banned users on the other side, with the spec 4.2 profile card.
   A "traveler" is a user with a published journey in the last 12 months or a usual route; a "sender"
   likewise with requests. `GET /api/discovery/people/<opaque id>` returns one card plus that user's
   currently discoverable trips or open requests.
6. **Route alerts.** Model `RouteAlert(user, watches: trips|requests, origin_locality, destination_locality,
   subject_user nullable, is_active)`, at most 10 active per user. `GET/POST /api/discovery/alerts`,
   `DELETE /api/discovery/alerts/<id>`. When a journey becomes discoverable or a request opens,
   matching alerts get one notification on the new channel `discovery.route_alert` (push class
   non-essential, honours `marketplace_enabled`). At most one notification per alert per 6 hours.
7. **"I can carry this".** `POST /api/discovery/requests/<id>/interest` with `journey_id`. The server
   runs the existing `evaluate_candidate`; if incompatible it answers the rejection codes. If
   compatible it stores `TravelerInterest(request, journey, traveler)` (unique per request and journey),
   enforces the daily cap, and notifies the sender on the new channel `discovery.traveler_interested`
   with the request id and journey id only. It creates no match, no offer and no reservation.
8. **Admin.** On the person page: hide and unhide a public profile, with a reason, permission
   `manage_users`, audited. A discovery section listing the person's alerts and interests, read only.

**Privacy tests (required).** For each of the five public payloads, a test that builds a user with a
distinctive last name, email, phone, street address and coordinates, a recipient, and a KYC row, then
asserts none of those strings and none of the forbidden keys appear anywhere in the JSON.

**Performance.** Each endpoint has a fixed query count that does not grow with the number of rows,
asserted with `assertNumQueries` at 1 row and at 20 rows, like the J4 contract.

**Done when.** The contract is written in `docs/PHASE_L2A_DISCOVERY_CONTRACT.md`; the privacy and query
count tests pass; an opted-out, hidden or banned user appears in no tier; the two old endpoints and
the code only they used are gone; switching `listings_enabled` or `profiles_enabled` off makes the
tier answer `state: "disabled"`.

### L2B. Discovery on Home (Sonnet)

**Goal.** Home shows, in order: what needs me, what is in progress, matches for me, listings, people,
my own items. It stays fast and calm.

**Screens.**
- **Home** (`mobile/lib/features/home/home_screen.dart`). Keep the role switcher, the verify notice,
  "needs attention" and "in progress" exactly where they are, above discovery. Then:
  - *Matches for you*: one group per request or journey with up to three cards and "See all", which
    opens the existing Find Travelers screen or the journey's compatible requests.
  - *Trips leaving soon* (sender) or *Parcels looking for a traveler* (traveler): corridor chips built
    from the four launch countries, five cards, "Browse all".
  - *People on your routes*: a horizontal row of profile cards, "See all".
  - The one-time opt-in card of spec 4.3, placed above *People*.
- **Browse trips** and **Browse requests**: full lists with filters for from, to and date, using the
  existing canonical place picker, lazy paging with the server's `next_offset`.
- **Trip preview** and **Request preview**: the public card in full, with the spec 4.4 action.
- **Person**: the public profile, their current trips or requests, the route alert toggle.
- **Public profile settings** (Profile, new row "Public profile"): the switch, the usual routes, and a
  live preview that renders the server's own card.
- **Alerts** (Profile, "Route alerts"): list, add, delete.

**States every section and screen needs.** Loading as skeletons shaped like the content. Empty with a
useful next step ("Post a request to see who can carry it"). Error with retry that keeps the rest of
Home usable. Offline showing the last loaded content marked as such. Tier disabled: the section is
absent, not an error. Each Home section loads independently; one failing never blanks the page.

**Rules.** No new bottom tab. No matching logic in Dart. Cards render only fields the server sent.
Pull to refresh refreshes every section. Deep links from the two new notification channels open the
right screen. Reuse the design system in `mobile/lib/design`; no one-off styles.

**Remove.** The old journey-search and open-feed repository methods and `k6_discovery_paging_test`'s
use of them, replaced by tests of the new methods.

**Tests.** Widget tests per section for every state; RTL and bottom-overlap tests extended to the new
screens (`navigation_and_rtl_test`, `no_bottom_overlap_test`); a request-budget test that Home makes a
bounded number of calls on open; localisation test passes with zero untranslated keys.

**Done when.** The gate screenshots exist (1.6) and Home's time to first content is not worse than the
baseline in the existing cold-start test.

### L3A. Routes for everyone, backend (Opus)

**Goal.** Sea legs on admin-managed crossings, ticket proof for flight and sea through one function,
stop options, optional volume and parcel-count capacity, what the traveler accepts, and pause. All
enforced by the server. All existing flight and road behaviour unchanged.

**Schema (additive).**
- `JourneyLeg.Mode` gains `SEA`.
- `locations.SeaCrossing` (2.3).
- `JourneyLeg.capacity_volume_l` (positive integer, null) and `capacity_parcels` (positive small
  integer, null). `DealLegAllocation.allocated_volume_l` (null), snapshotted from the request's
  dimensions when they exist.
- `trips.JourneyStopDetail(journey, position, accepts_pickup=True, accepts_dropoff=True,
  handover_note (max 280), window_start, window_end)`, unique on journey and position. A journey with
  no rows behaves as today.
- `Journey.refused_categories` (list of `DeliveryRequest` category codes, default empty) and
  `Journey.accepts_fragile` (default true).
- `Journey.paused_at`, `paused_by_staff` (bool), `pause_reason`.
- `apps/trips/constraints.py::MAX_JOURNEY_LEG_CAPACITY_KG` becomes `20000.00`. The mobile constant
  `maxJourneyLegCapacityKg` follows in L3B.

**Sea crossings.**
- `python manage.py seed_sea_crossings --file tools/geography/sea_crossings.json`. Idempotent. Creates
  each pair **inactive**. A pair is created only when both names resolve to exactly one catalogue
  locality; anything else is reported and skipped. The file holds the candidate port cities from spec
  5.3, both directions.
- Service functions `activate_crossing`, `deactivate_crossing`, `create_crossing`, each requiring a
  reason and writing the audit log. (The console screen is L3B.)
- `GET /api/geography/sea-crossings` returns `{"enabled": bool, "crossings": [{origin, destination}]}`
  with public place cards, cacheable, active rows only.

**Mode rules** (`apps/trips/transport_rules.py`, place-aware as 2.3).
- A `SEA` leg needs: the switch on; both endpoints LOCALITY places; an active crossing from the
  origin's matching locality to the destination's; no flight number.
- Refusal keeps the existing code `journey_leg_mode_unavailable` and adds a machine `reason`:
  `sea_legs_disabled`, `sea_crossing_unavailable` or `sea_endpoint_not_port_city`.
- `DRIVE` and `FLIGHT` answers are byte-for-byte what they are today for every existing input.
- A sea leg's distance uses the same great-circle function as a flight leg.

**Ticket proof** (2.2).
- Create `apps/trips/proofs.py`. Replace every proof decision listed in 6.1.
- `JourneyLegProofCreateView` accepts flight and sea legs. A road leg is refused with
  `proof_not_required` (replaces `proof_only_for_flight`).
- Publishing: every flight and sea leg needs an approved proof. Error codes stay
  `flight_proof_not_approved` and gain `sea_proof_not_approved`.
- Compatibility: keep the check `flight_proofs_approved`; add `sea_proofs_approved`.
- Journey payloads gain, per leg, server-authored `proof_required` and `proof_state`
  (`not_required`, `missing`, `pending`, `approved`, `rejected`). The app stops deciding this.
- The Redis channel becomes `leg_proof.status_changed` (Django, push matrix, Go list). Push and email
  copy say "ticket" and name the mode. To keep the integration branch working, this package also
  makes the two matching one-line changes in the app (the channel name and the error code).

**Matching** (`apps/matching/compatibility.py`, `discovery.py`, `find_travelers.py`, `v1_services.py`).
New checks, each with its own rejection code and a test:
- `journey_not_paused`
- `sea_legs_available` (switch on and crossing active for every sea leg in the covered range)
- `sea_proofs_approved`
- `stop_services_allow_handover` (pickup stop accepts pickup; drop-off stop accepts drop-off)
- `item_accepted_by_traveler` (category and fragile)
- `volume_available_on_every_leg` (only when the leg declares a volume and the request has dimensions;
  otherwise passes and adds the limitation `volume_unverified`)
- `parcel_slots_available_on_every_leg`

`MATCHING_VERSION` becomes `v1-matching-2`. The acceptance path (`_lock_acceptance_eligibility`,
`_lock_journey_legs`) locks and re-checks the same things under the same locks: proof witnesses for
every proof-required leg, volume and parcel slots together with weight. Query counts for
`find-travelers` and `compatible-requests` stay flat.

**Stops, acceptance and pause API.**
- The journey write serializer accepts an optional `stops` list and `refused_categories`,
  `accepts_fragile`, per-leg `capacity_volume_l`, `capacity_parcels`. Validation: positions exist;
  first stop not drop-off-only, last stop not pickup-only; a window fits between arriving at and
  leaving the stop; note length.
- `handover_note` is returned only in a deal payload, only to that deal's sender and traveler, only
  once the deal is funded, and only for the stops that deal uses.
- `POST /api/journeys/<id>/pause` and `/resume` for the owner. A staff pause cannot be lifted by the
  owner (`journey_paused_by_staff`). Staff service functions `pause_journey`, `resume_journey` with a
  reason and audit.

**Tests.** A mode matrix (every country pair, with and without a crossing, switch on and off). Publish
and compatibility for sea with missing, pending, rejected and approved proof. The complete existing
matching, trips and deals suites pass with no edits beyond the version string and the renamed code. A
concurrency test where two acceptances compete for the last parcel slot and for the last litres, and
exactly one wins. Stop services. Category refusal. Pause. A privacy test that `handover_note` appears
in no pre-funding payload.

**Done when.** With the switch off, no request can create or match a sea leg, proven by test. With it
on and a crossing active, the Lille, Paris, Lyon, Marseille, Algiers, Sétif, Constantine route from
Ismail's brief can be created, published with an approved sea ticket, and matched leg by leg, with a
Lille to Paris parcel using no capacity on the sea leg, proven by test.

### L3B. Routes for everyone, mobile and admin screens (Sonnet)

**Mobile.**
- `TransportMode` and `LegMode` gain sea, with icon and colour in `design/components/status.dart`.
  `transport_rules.dart` offers Sea only for pairs the server's crossings list contains while enabled.
  `requiresProof` is deleted; screens read `proof_required` and `proof_state` from the server.
- Route editor (`journey_route_editor.dart`, `journey_route_draft.dart`): the segment mode chooser
  shows the modes the pair allows, with a one-line reason when Sea is absent because the switch is
  off. Per-leg optional "Volume (litres)" and "Number of parcels" under an "More capacity options"
  disclosure, so the default form is no longer than today. A stop sheet with "Accept pickups here",
  "Accept drop-offs here", an optional time window and an optional note with a line saying who will
  see it. A "What I carry" section for refused categories and fragile.
- Ticket proof screen (`leg_proof_screen.dart`): copy and illustrations for flight and for ferry.
- Journey detail: pause and resume, the paused banner, the staff-paused banner with the reason.
- Sender side: Find Travelers, trip preview, offer and deal screens render sea legs, the
  `volume_unverified` caveat, and, after funding, the stop note and window.

**Admin console.**
- Geography: a "Sea crossings" table with add, activate and deactivate, each asking for a reason.
- Ticket proofs queue and detail: title "Ticket proofs", a Mode column and filter, the ferry booking
  reference where the flight number is today.
- Journey detail: pause and resume with a reason; stops with their options; capacity by leg.
- Settings: "Sea legs" in the Marketplace features form, with a warning line naming what it enables.

**States.** As spec 14. In particular: the crossings list failing to load must not block editing road
and flight legs; a leg whose mode became unavailable shows the server's reason on that leg.

**Tests.** Route draft model tests for sea; editor widget tests for each mode combination; proof
screen states; RTL and bottom-overlap; admin view tests for permissions and audit rows.

**Done when.** A traveler can build the Lille to Constantine route on a 360 px phone in Arabic without
horizontal scrolling or overlap, and the gate screenshots show it.

### L4A. Traveler pricing, backend (Opus)

**Schema.** `Journey.price_per_kg_eur_cents` and `Journey.min_price_eur_cents`, both null or both set,
each within the bounds in the marketplace policy.

**Rules.**
- Set through the journey write serializer, and through `PATCH /api/journeys/<id>/pricing` while the
  journey is draft, pending verification or active. A change is recorded in the audit trail of the
  journey and affects only offers created afterwards.
- `listed_reward` (2.5) is the only calculation.
- `find-travelers` candidate `economics` gains `listed`: `null`, or
  `{reward_eur_cents, economics, price_per_kg_eur_cents, min_price_eur_cents, basis}` where
  `economics` is the output of `calculate_offer_economics` and `basis` is `per_kg`,
  `traveler_minimum` or `wassla_minimum`. A new sort `listed_price` puts unpriced journeys last.
- The discovery trip card shows `price_per_kg_eur_cents` and `min_price_eur_cents` only.
- `create_sender_offer` is unchanged in what it accepts: any reward at or above Wassla's minimum. The
  listed price is a default, not a floor. The offer's `terms_snapshot` gains `listed_price` (the block
  above, or null) for audit.
- Counter, accept, boost, fee, deposit and checkout are untouched.
- Switch `traveler_pricing.enabled` off: prices cannot be set, and `listed` is null everywhere.

**Tests.** The formula at each boundary, including rounding up. Wassla's minimum wins when the
traveler's price is lower. An offer below Wassla's minimum is refused exactly as before. An offer
below the listed price but above the minimum is accepted for negotiation. Changing the price leaves
existing offers' snapshots identical. The `find-travelers` query count is unchanged. The complete
finance suite passes with no edits.

**Done when.** A diff of every amount on an end-to-end deal created at the listed price equals the
same deal created today by typing that amount by hand.

### L4B. Traveler pricing, mobile (Sonnet)

- Route editor and journey detail: "Your price" with "Price per kg" and "Minimum per parcel", optional,
  with the line "Senders see your price plus Wassla's fee. Wassla's minimum for each parcel still
  applies." No client-side price examples: the app does no price arithmetic.
- Find Travelers card: the listed price for this parcel. Sort by listed price.
- Propose sheet: pre-filled with the listed price; primary action "Offer €X"; secondary "Offer a
  different amount"; the fee and the sender's total, from the server, visible before sending; the
  server's minimum shown when the sender goes lower.
- Trip cards in discovery: "from €X per kg, minimum €Y".
- States, RTL, EUR formatting through the existing money components only.

**Done when.** Money tests (`money_test`, the perspective tests) pass unchanged, and a sender can go
from a trip card to a sent offer at the listed price in three taps.

### L5A. Progress updates and reminders, backend (Sonnet)

**Schema.** `trips.JourneyLegProgress(leg, kind: at_port|departed|arrived, source: traveler|staff,
reported_by, reported_at, retracted_at)`, one live row per leg and kind.

**API.**
- `GET /api/journeys/<id>/progress`: per leg, the reports and the server-authored next actions.
- `POST /api/journeys/<id>/legs/<leg_id>/progress` with `kind`. Owner only; journey active or in
  progress; `at_port` only on a sea leg and before `departed`; `departed` needs the previous leg
  `arrived` (or the first leg); `arrived` needs `departed`; not more than 24 hours before the planned
  time (`progress_too_early`).
- `POST .../progress/<id>/retract` within 10 minutes of the report.
- `GET /api/journeys/progress/pending`: the questions currently due for the caller, used by Home.

**Effects.** For each funded deal with a live allocation on that leg: one `DealEvent` of a new kind
`TRAVELER_PROGRESS` (through the existing `record_event`), projected in `apps/deals/timeline.py` with
`source: "traveler_reported"`, and one notification to the sender on the new channel
`deal.progress_reported`. No deal field changes. A retraction adds a retraction event; history is
never deleted.

**Reminders** (2.7). New `ScheduledJob` kind `leg_reminder`, scheduled for each leg when a journey is
published, keyed by leg, kind, planned time and attempt. The handler does nothing unless: reminders
are enabled; the journey is live; the leg's planned time still equals the payload's; the leg carries
at least one funded parcel; no report exists. Otherwise it notifies the traveler on the new channel
`journey.leg_reminder` and schedules the next attempt up to `max_repeats`.

**Not in scope.** No change to `Deal`, to `apps/deals/arrival.py` (early arrival stays a separate
fact), or to any payout gate. If one seems needed, stop (1.2).

**Tests.** Ordering rules. Fan-out to exactly the deals on that leg. A deal's row is byte-identical
before and after a report. The reminder handler in each no-op case and the notify case, including
running twice. The Go channel list test.

### L5B. Progress updates and reminders, mobile (Sonnet)

- Journey detail: a "Trip progress" stepper, one step per leg, with one large button for the next
  action and an undo for 10 minutes.
- Home, in "needs attention": "Did you depart from {city}?" with "Yes, departed" and "Not yet".
- The reminder notification opens the same question as a sheet. The bell inbox lists it.
- Sender's deal screen: progress lines in the timeline, each marked "reported by the traveler".
- States, RTL, and an offline rule: a report needs the network; the button says so instead of queuing.

### L6A. Professional profile, verification, admin inbox, proof skip (Opus)

**Schema.** New app `apps.professionals`.
- `ProfessionalProfile(user one to one, business_name, registration_number, registration_country,
  business_city place, document_kind, status: pending|needs_info|verified|rejected|suspended,
  staff_message, reviewed_by, reviewed_at, verified_at, suspended_at, suspension_reason)`.
- `ProfessionalDocument(profile, bucket, object_key, content_type, bytes, sha256, idempotency_key)`,
  stored and served exactly like `JourneyLegProof` (private bucket, same size and type limits,
  evidence viewed only through the audited staff redirect).
- `ProfessionalProfileEvent` (append-only status history with actor and reason).

**API.**
- `GET /api/professional/profile`, `PUT` (only while not verified and not suspended),
  `POST /api/professional/profile/document`, `POST /api/professional/profile/submit`.
- Submit needs an approved ID check and the applications switch on
  (`professional_applications_closed`).
- `/api/me` gains `professional: {status, business_name}`.
- Verified fields are locked for the user. Staff can correct them with a reason.
- Channel `professional.status_changed` and an email through the outbox, in the user's language.

**Proof skip.** `is_verified_professional` (2.4) feeds `apps/trips/proofs.py`. Matching querysets get
the fact as one annotation so query counts stay flat. The acceptance lock takes the professional
profile row as a witness whenever the skip is what satisfies a leg, exactly as it does for KYC.
Public payloads gain `traveler.professional: {business_name} | null` through one helper, and the match
reason `professional_verified`. The reason `flight_proof_approved` is emitted only when a real
approved proof exists. The offer `terms_snapshot` records whether the skip applied.

**Suspension.** `suspend_professional` and `reinstate_professional` (staff, reason, audit). On
suspension the user's journeys are re-evaluated lazily by the gates; nothing is rewritten, and funded
deals are untouched (spec 6).

**Admin: one verification inbox.**
- One "Verification" entry with the total waiting count. Three tabs with counters: ID, Professional,
  Tickets. The ID and Tickets tabs are the existing queues under a shared header.
- One review screen (`verification_detail.html`) for all three, with three decisions: approve, ask for
  more, reject. A reason is required for the last two.
- Professional: "ask for more" sets `needs_info` and shows the staff message to the user.
- ID and Tickets: "ask for more" records the existing rejected status with the reason and marks the
  audit entry and the notification `outcome: "resubmission_requested"`, so the user reads "we need a
  new upload" and can resubmit. The KYC status enum, owned by the Go service, is not changed.
- New permission codes `view_professional_profiles`, `review_professional_profiles`, added to the
  role matrix by a data migration that grants them wherever the KYC equivalents are held.
- Person page: a Professional section with status, history, suspend and reinstate.

**Tests.** The status machine. A verified professional publishes and is matched on flight and sea legs
with no proof; the same journey is refused the moment they are suspended; funded deals are unchanged.
Acceptance racing a suspension resolves to one consistent outcome. Privacy: registration number and
document never appear in any non-staff payload. Permissions and audit for every staff action.

### L6B. Professional Mode, mobile (Sonnet)

- Profile gains "Professional Mode". Screens: what it is and what it needs; the form (business name,
  registration number, country, city with the place picker, document type, photo); pending;
  more-information-needed with the staff message and a re-upload; verified, with what it unlocks;
  suspended, with the reason and how to reach support; applications closed.
- A Pro badge component in the design system, used on trip cards, Find Travelers, the public profile,
  offers, deals and tracking.
- Public professional profile screen (spec 7.3).
- For a verified professional the ticket step is absent from publishing, with one line explaining why.
- States, RTL, upload progress and failure, photo retake.

### L7A. Manifest, backend projections (Sonnet)

Read-only. Verified professionals only (`professional_required`), except the deal filters.

- `GET /api/pro/today`: offers awaiting an answer; collections due; parcels ready to deliver; counts
  by state. Later packages add their own sections here.
- `GET /api/journeys/<id>/manifest`: stops in order; at each, parcels to collect and to drop, each
  with reference, title, weight, status and the next action; per leg, used and free weight, volume
  and parcel slots.
- `GET /api/deals` gains filters `journey_id`, `pickup_place_id`, `delivery_place_id`, `status`,
  `expected_before`, and `q` (reference).
- `GET /api/pro/earnings?journey_id=`: totals read from existing deal terms snapshots and payout rows,
  grouped by payout state. Sums only. No new fee, FX or refund arithmetic.
- Fixed query counts, asserted.

### L7B. Manifest dashboard, mobile (Sonnet)

- Home: a "Today" section for verified professionals, above discovery, listing actions in the order a
  working day needs them.
- Deliveries: a "Routes" view; the route manifest; the stop view, where each parcel row opens the
  existing pickup or delivery screen and returns to the list. There is no "confirm all".
- Shipments: filters and reference search on the existing deliveries list.
- Profile: "Earnings by route" inside the existing payouts area.
- At widths of 840 dp and more, the manifest uses two panes. The last opened manifest is readable
  offline and marked as such; code entry needs the network and says so.

### L8A. Custody, courier handoff, recipient confirmation (Opus)

**Schema.** App `apps.custody` (2.6).
- `CustodyEvent(deal, kind, source, actor, occurred_at, data)`, append-only. Kinds: `collected`,
  `condition_recorded`, `handed_to_courier`, `courier_accepted`, `handoff_cancelled`,
  `courier_out_for_delivery`, `courier_reported_delivered`, `courier_delivery_failed`, `delivered`.
  Sources as spec 10.1.
- `CollectionRecord(deal one to one, condition, note)` with private photos.
- `CourierHandoff(deal, status: reported|courier_confirmed|cancelled, courier_company, branch,
  representative, tracking_reference, handed_at, receipt, link_token_hash, link_expires_at,
  courier_name, courier_confirmed_at, confirm_ip, confirm_user_agent)`, at most one not-cancelled per
  deal.
- `RecipientLink(deal, token_hash, expires_at, revoked_at)`.
- `CustodyReview(deal, reason, status: open|resolved, resolution, resolved_by, resolved_reason)`.
- `HandoverAttempt.actor` becomes nullable and gains `channel` (`traveler_app` by default,
  `recipient_page`).
- New `DealEvent` kinds for the timeline. `Deal` gets no new field and no new status.

**Handoff.**
- `POST /api/deals/<id>/courier-handoff` by the deal's traveler. Needs: the switch on; pickup
  confirmed; delivery not confirmed; no active dispute. Returns the record and the one-time link.
- `POST /api/deals/<id>/courier-handoff/cancel` while not courier-confirmed.
- `GET /api/deals/<id>/custody`: current holder, events with sources, the handoff, and server-authored
  actions for the viewer.
- `POST /api/deals/<id>/collection-record` by the traveler, once, after pickup.
- Courier page `GET/POST /c/<token>` (2.8): confirm receipt with a name; afterwards report out for
  delivery, delivered, or delivery failed. Throttled per token and per address.

**Final delivery after a handoff.** Three functions in `apps/handover/services.py`, each taking the
deal lifecycle lock and then calling the existing `apply_delivery_confirmed`:
- `confirm_delivery_as_recipient(token, submitted_code)`: verifies the delivery code with the existing
  hashing, attempt recording and lockout, on channel `recipient_page`.
- `confirm_delivery_as_sender(deal_id, actor_id)`: the deal's sender, only while a handoff is active.
- `confirm_delivery_as_staff(deal_id, actor_id, reason, evidence_note)`: permission `manage_lifecycle`,
  only from an open `CustodyReview`, audited.
All three need the deal to accept a delivery exactly as today (`DELIVERY_READY` with a released code).
The delivery event records the method. The traveler-code path is unchanged.
- Recipient page `GET/POST /r/<token>` (2.8): progress without private data; "I received my parcel"
  with the code; "I have a problem", which notifies the sender and opens a `CustodyReview`.
- When a handoff is recorded: an email to the recipient with the page link, in their language, through
  the outbox; a notification to the sender.

**The 5-day rule.** `ScheduledJob` kind `courier_delivery_review` at handoff time plus the policy
days. The handler opens a `CustodyReview` when delivery is still unconfirmed, the handoff is not
cancelled and no dispute is active, and notifies the sender. Staff see a "Courier deliveries to
review" queue.

**Channels.** `deal.courier_handoff`, `deal.courier_update`, `deal.delivery_review`.

**Tests (all required).**
- A handoff, a courier confirmation and every courier report leave the `Deal` row, the ledger, the
  payout rows and the money-related scheduled jobs identical.
- Each of the three new confirmations produces the same deal fields, protection end and scheduled jobs
  as the traveler-code path at the same instant.
- Wrong codes on the recipient page lock out exactly as in the app. Expired, revoked and unknown
  tokens render the same page.
- The sender cannot confirm without a handoff. Staff cannot confirm without an open review,
  the permission and a reason.
- Recipient and sender confirming at the same moment yield one transition.
- An active dispute blocks handoff creation and all three confirmations.
- The review job is idempotent and does nothing once delivery is confirmed.
- Privacy tests for both pages and for the custody payload as seen by each party.
- The handoff link, pickup code and delivery code are different secrets and none accepts another.

**Done when.** The grep in L10 for writes to `Deal.status` finds none in `apps/custody`.

### L8B. Custody and handoff, mobile (Sonnet)

- Deal screen: a custody timeline where every line carries its source label.
- After pickup: an optional "Record condition" sheet with photos; skipping is one tap.
- Traveler: "Hand over to a local courier": a short form, then a full-screen QR code with the link,
  the waiting state, the confirmed state, and "I took it back".
- Sender: the banner "Handed to a local courier, awaiting final delivery", the courier's name and
  tracking reference, and "The recipient has it", which opens a confirmation dialog stating that it
  confirms delivery and starts the 48-hour protection period.
- Manifest: handoffs awaiting courier confirmation appear in Today.
- States including "courier handoff is not available" when the switch is off.

### L9A. Problems and route changes, backend (Opus)

**Problems.** `custody.ShipmentProblem(deal, reported_by, kind, note, status: open|acknowledged|
escalated|closed, closed_by, closed_reason)`. `POST` and `GET /api/deals/<id>/problems`. Kinds as spec
12. `parcel_damaged`, `parcel_mismatch`, `courier_lost` and `courier_refused` escalate to staff at
once. The other party is notified on `deal.problem_reported`. A problem changes nothing on the deal;
the existing dispute and cancellation actions remain the only paths with money consequences. Staff
queue with acknowledge and close, each with a reason.

**Schedule changes.** Times only. Adding or removing stops on an active journey is not part of this
build.
- `trips.JourneyScheduleChange(journey, status: pending_senders|applied|withdrawn, original, proposed,
  reason)` and `JourneyScheduleChangeConsent(change, deal, state: pending|accepted|declined)`.
- `POST /api/journeys/<id>/schedule-changes` by the owner with new leg times. The server validates the
  sequence with the existing leg-sequence rules, finds the affected funded deals, and classifies each:
  **material** when the new arrival at its drop-off stop is after the request's deadline or moved by
  more than `route_change.material_shift_minutes`.
- No material deal: the change applies at once and affected senders are notified.
- Otherwise it waits. Each affected sender accepts or declines. It applies when every material deal is
  accepted or no longer active. The traveler may withdraw it.
- A sender who declines may cancel through the existing cancellation flow. **The cancellation is
  recorded as caused by the traveler and uses the existing traveler-cancellation outcome; no new
  refund rule is written.** This line needs Ismail's confirmation before the package starts (5.3).
- `Deal.arrival_snapshot` and `funded_scheduled_arrival_floor_at` are never rewritten. The payout
  floor stays the one agreed at funding.
- Applying a change reschedules leg reminders and is recorded with the original schedule.

**Tests.** Classification at each boundary. Apply, wait, accept, decline, withdraw. The arrival
snapshot is untouched. Cancellation after a decline produces exactly the amounts the existing
traveler-cancellation path produces. Pending offers are re-validated at acceptance against the new
times.

### L9B. Problems and route changes, mobile (Sonnet)

- "Report a problem" from the deal screen and from a manifest row; the problem list on the deal.
- Traveler: "Change times" on an active journey, a review step listing the affected parcels and which
  senders must agree, and the pending state.
- Sender: a screen comparing the old and new times with "Accept" and "Decline", and, on decline, the
  cancellation consequence text from the existing cancellation quote endpoint.

### L10. Final acceptance (Opus)

1. Whole suites on PostgreSQL, Go with race detection, and Flutter. Counts recorded against the
   baseline (Django 2,529 passed, Flutter 1,083 passed at `dd7f820`).
2. Scripted end-to-end scenarios in test mode: the Karim route from Ismail's brief as a verified
   professional; an individual traveler with a sea leg and a ticket; discovery to an offer at the
   listed price, payment, pickup, courier handoff, recipient confirmation, protection, payout; the
   same with nobody confirming, through the 5-day review.
3. Invariant proofs, as greps recorded in the report: no proof decision outside `apps/trips/proofs.py`;
   no write to `Deal.status` outside `apps/deals`; no listed-price arithmetic outside
   `apps/matching/listed_price.py`; every public discovery serializer has a privacy test; every new
   staff action writes an audit row.
4. Switch matrix: with each switch off, the capability refuses on the server and the app shows the
   unavailable state.
5. Migrations: every one additive, `sqlmigrate` output reviewed, `task check-drift` clean.
6. Performance: the K-series budgets and all asserted query counts hold.
7. Design review of every new screen in EN, FR and AR on a small phone and a tablet.
8. `docs/WASSLA_L_SERIES_RELEASE_REPORT.md` and `docs/IMPLEMENTATION_STATUS.md`.
9. Hand Ismail the report, the list of switches that are still off, and the open decisions. **No merge
   into `main` and no deployment without his explicit approval.**

---

## 5. Decisions still open with Ismail

None of these blocks L1 or L2.

1. **Sea crossings.** The candidate port list must be checked against real ferry schedules, and the
   legal position for carrying parcels by sea confirmed, before the "Sea legs" switch is turned on.
   The code ships with it off.
2. **Railway files.** Remove them in L1A, or keep them? (Hosting is moving to the VPS.)
3. **Declined schedule change.** L9A treats the resulting cancellation as caused by the traveler. Confirm
   before L9A starts.
4. **"I can carry this".** A small addition in L2A so a traveler looking at an open request is not at a
   dead end. It is not an offer. It can be dropped from L2A and L2B without affecting anything else.
5. **Later, not in this build:** business logos and photos, courier API integrations, recurring
   routes, fleet management, analytics.

---

## 6. Code map at the baseline (`dd7f820`)

### 6.1 Sites that decide about flight proof today

Each must go through `apps/trips/proofs.py` in L3A. Line numbers are at the baseline and will drift;
search for the mode comparison.

| File | Around line |
| --- | --- |
| `apps/matching/compatibility.py` | 244, 286, 449, 893 to 900 |
| `apps/matching/v1_services.py` | 149, 559 |
| `apps/matching/find_travelers.py` | 480, 534, 590 |
| `apps/matching/discovery.py` | `_matching_leg_queryset` (`has_approved_proof_value`) |
| `apps/trips/services.py` | 77, 90, 664 |
| `apps/trips/serializers.py` | 238, 502 |
| `apps/trips/lifecycle.py` | 24 |
| `apps/trips/views.py` | 380, 643 |
| `apps/notifications/push.py` | 236, 375, 380 |
| `apps/notifications/models.py` | 160 |
| `apps/admin_panel/services.py` | 401 (`review_flight_proof`) |
| `apps/admin_panel/console_views.py` | 611, 998, 1191 to 1333, 1422 |
| `apps/admin_panel/console_urls.py` | 63 to 71 |
| `apps/admin_panel/permissions.py` | 74, 183, 393 |
| `apps/admin_panel/views.py` | 148, 318, 523 |
| `apps/core/templatetags/shiptrip_admin.py` | 113 |
| `apps/core/channels.py` | 49 |
| `backend/services/internal/notification/dispatcher.go` | 94 |
| `mobile/lib/domain/transport_mode.dart` | `requiresProof` |

All backend paths are under `backend/monolith/`.

### 6.2 Where things live

| Concern | Files |
| --- | --- |
| Journey, legs, proof, publish gates | `apps/trips/models.py`, `services.py`, `serializers.py`, `views.py`, `transport_rules.py`, `lifecycle.py` |
| Compatibility, ranking, candidate payloads | `apps/matching/compatibility.py`, `discovery.py`, `ranking.py`, `find_travelers.py`, `public_contract.py` |
| Offers and acceptance under lock | `apps/matching/v1_services.py` |
| Wassla minimum and recommendation | `apps/matching/pricing.py`, `policy.py`, `posting_pricing.py` |
| Fee and settings | `apps/core/business_settings.py`, `apps/core/models.py` |
| Deal state machine and timeline | `apps/deals/lifecycle.py`, `models.py`, `timeline.py`, `arrival.py`, `cancellation.py` |
| Pickup and delivery codes | `apps/handover/services.py`, `models.py`, `codes.py` |
| Durable jobs | `apps/finance/models.py` (`ScheduledJob`), `apps/finance/jobs.py`, `apps/finance/services.py::schedule_job` |
| Events, inbox, push, email | `apps/core/redis_bus.py`, `apps/core/channels.py`, `apps/notifications/push.py`, `outbox.py` |
| No-account web page pattern | `apps/finance/guest_web.py` |
| Admin console | `apps/admin_panel/console_urls.py`, `console_views.py`, `permissions.py`, `templates/admin/console/` |
| Place catalogue | `apps/locations/models.py`, `tools/geography/`, `docs/GEOGRAPHY_CATALOGUE.md` |
| Mobile Home, routes, discovery | `mobile/lib/features/home/`, `features/journeys/`, `features/requests/discovery_screen.dart` |
| Mobile API layer and models | `mobile/lib/data/repositories.dart`, `mobile/lib/domain/` |
| Mobile design system | `mobile/lib/design/` |
