# Wassla L-Series Progress

The shared record for every agent working on `feature/discovery-professional-delivery`.
Rules for this file: `docs/WASSLA_DISCOVERY_PRO_PLAN.md` section 1.8. In short:

- **Read this file first**, the board and every handoff block above your package.
- **The board is edited only by the orchestrator**, on the integration branch.
- **Each agent fills in only its own handoff block**, inside its own pull request.
- Statuses: `not_started`, `in_progress`, `in_review`, `changes_requested`, `merged`, `blocked`, and
  `parked` (not part of this build; never picked up).

When Ismail says "start", the orchestrator follows plan section 1.0: resume anything unfinished,
otherwise take the first `not_started` package whose dependencies are all `merged`.

## Board

| Package | What | Model | Effort | Status | Branch | Pull request | Merge commit | Phase doc |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| L0 | Spec and plan | | | merged | | | see git log for `docs/WASSLA_DISCOVERY_PRO_PLAN.md` | |
| L1A | Backend cleanup, including Railway removal | Opus | high | merged | `claude/project-thread-po89ml` | #22 | `345849b` | `docs/PHASE_L1A_BACKEND_CLEANUP.md` |
| L1B | Mobile and docs cleanup | Sonnet | medium | merged | `claude/project-thread-y61pdg` | #23 | `ae412a3` | |
| L2A | Discovery backend and marketplace policy | Opus | high | merged | `claude/project-thread-jms2kh` | #24 | `46682bc` | `docs/PHASE_L2A_DISCOVERY_CONTRACT.md` |
| L2B | Discovery on Home (mobile) | Sonnet | high | merged | `claude/project-thread-qu26fd` | #25 | `c2e279f` | `docs/PHASE_L2B_DISCOVERY_HOME.md` |
| L3A | Routes for everyone, backend | Opus | xhigh | merged | `claude/project-thread-bl54yl` | #26 | `b10cda8` | `docs/PHASE_L3A_ROUTES_BACKEND.md` |
| L3B | Routes for everyone, mobile and admin screens | Sonnet | high | merged | `claude/project-thread-52tsvf` | #28 | `edb94d7` | `docs/PHASE_L3B_ROUTES_MOBILE_ADMIN.md` |
| L4A | Traveler pricing, backend | Opus | high | merged | `claude/project-thread-q374r4` | #29 | `5014497` | `docs/PHASE_L4A_TRAVELER_PRICING_BACKEND.md` |
| L4C | Housekeeping: test time limit and ferry distance cleanup | Opus | high | merged | `claude/project-thread-a448wo` | #30 | `c360dcf` | `docs/PHASE_L4C_HOUSEKEEPING.md` |
| L4B | Traveler pricing, mobile | Sonnet | medium | merged | `claude/project-thread-fyrhxt` | #31 | `c685db0` | `docs/PHASE_L4B_TRAVELER_PRICING_MOBILE.md` |
| L11A | Tracking number, backend | Opus | high | merged | `claude/project-thread-5otrp2` | #32 | `1021c89` | `docs/PHASE_L11A_TRACKING_NUMBER.md` |
| L11B | Tracking number, mobile | Sonnet | medium | merged | `claude/project-thread-14swqv` | #33 | `75640c0` | `docs/PHASE_L11B_TRACKING_NUMBER_MOBILE.md` |
| L5A | Progress updates and reminders, backend | Sonnet | medium | merged | `claude/project-thread-lsol7m` | #34 | `73d5169` | `docs/PHASE_L5A_PROGRESS_UPDATES_BACKEND.md` |
| L5B | Progress updates and reminders, mobile | Sonnet | medium | merged | `claude/project-thread-s4d2gr` | #35 | `c078060` | `docs/PHASE_L5B_PROGRESS_UPDATES_MOBILE.md` |
| L6A | Verification inbox (ID and Tickets) and removal of the parked switches | Opus | high | merged | `claude/project-thread-eqdiqe` | #36 | `a4f72db` | `docs/PHASE_L6A_VERIFICATION_INBOX.md` |
| L9A | Problems and route changes, backend | Opus | high | merged | `claude/project-thread-qpwihm` | #37 | `9ceb40e` | `docs/PHASE_L9A_PROBLEMS_ROUTE_CHANGES.md` |
| L9B | Problems and route changes, mobile | Sonnet | medium | merged | `claude/project-thread-18lfzs` | #38 | `b00260b` | `docs/PHASE_L9B_PROBLEMS_ROUTE_CHANGES_MOBILE.md` |
| L12A | Proposal deadline and trip-fit alerts, backend | Opus | high | merged | `claude/project-thread-ef7f2z` | #39 | `05ab258` | `docs/PHASE_L12A_PROPOSAL_DEADLINE_TRIP_FIT.md` |
| L12B | Proposal deadline and trip-fit alerts, mobile | Sonnet | medium | merged | `claude/project-thread-y6l5b8` | #40 | `8f81454` | `docs/PHASE_L12B_PROPOSAL_DEADLINE_MOBILE.md` |
| L13A | Reviews, reports and moderation, backend | Opus | high | not_started | | | | |
| L13B | Reviews, mobile | Sonnet | medium | not_started | | | | |
| L14 | Staff two-step sign-in and finance exports | Opus | high | not_started | | | | |
| L15 | AI helper: keys and read access | Opus | xhigh | not_started | | | | |
| L16 | AI helper: changes | Opus | xhigh | not_started | | | | |
| L17 | AI helper skill | Sonnet | medium | not_started | | | | |
| L10 | Final acceptance (runs last, after L17) | Opus | high | not_started | | | | |

**Parked on 2026-11-13 (Ismail's decision, plan 5.1e).** Wassla now targets fast delivery: urgent
parcels, mostly on flights and drives made the same day. These packages are not part of this build and
are never picked up. Their full text is in `docs/parked/WASSLA_PROFESSIONAL_AND_COURIER_PLAN.md`.

| Package | What | Model | Effort | Status |
| --- | --- | --- | --- | --- |
| L6A, professional half | Professional profile, business document check, ticket exemption, Professional tab | Opus | high | parked |
| L6B | Professional Mode, mobile | Sonnet | medium | parked |
| L7A | Manifest, backend projections | Sonnet | medium | parked |
| L7B | Manifest dashboard, mobile | Sonnet | high | parked |
| L8A | Custody, courier handoff, recipient confirmation | Opus | xhigh | parked |
| L8B | Custody and handoff, mobile | Sonnet | high | parked |

**Order of the remaining work (plan section 3):** L6A, L9A, L9B, L12A, L12B, L13A, L13B, L14, L15,
L16, L17, and L10 last. These rows were changed by the plan thread on Ismail's instruction of
2026-11-13; the board is otherwise still edited only by the orchestrator.

**Added 2026-11-12 (approved by Ismail):** L11A to L17 above, and the no-show reports inside L9A and
L9B (spec 12, 16 to 20; plan 5.1b), then L4C and the new order (plan 5.1d). **The order of the
board table is the order of work, as in plan section 3.**

**Next package:** L13A (Opus, high effort; reviews, reports and moderation, backend). Section 3 order.

**L12B judgment calls (accepted at the gate, for Ismail's end review):** (1) no endpoint returns one request card, so Browse reads the public list on (up to 8 pages) to find the parcel a trip-fit alert names; `GET /api/discovery/requests/<id>` would be exact and is a backend change left to Codex if wanted; (2) the "no longer listed" notice also covers a trip named by a route alert, which used to miss silently; (3) the expired proposal screen hides the deadline line, because its notice says it. The gate's first CI run failed every job in about a second with no logs (a runner or account fault, not the code); after re-runs on 2026-11-14 all ten checks passed.

**Closed carry-overs (2026-11-13):** L6B was to add the Pro badge and business name to L4B's trip
cards; L6B is parked, so nothing is owed. L5A's note that route changes must call
`schedule_leg_reminders` is now written into L9A's text.

**L12A judgment calls (accepted at the gate, for Ismail's end review):** (1) withdraw and match cancel also refuse after the deadline, so expiry is the single ending; (2) one trip-fit alert per traveler per request (the better ranked trip), since the cap counts travelers; (3) trip-fit alerts also need the listings switch, because the alert opens the public preview; (4) the offer payload reads `expired` from the deadline on, before the job stores it; (5) the reminder and the trip-fit alert are push class `marketplace`; (6) the trip-fit push copy names no cities. The gate also updated L4A's console pricing test, which posted the marketplace form without the new fields.

**L9A judgment calls (accepted at the gate, for Ismail's end review):** (1) "earlier than the agreed pickup" counts only when the pickup moved earlier; (2) accepted but unfunded deals are classified and asked too; (3) problems reuse `view_disputes`/`manage_disputes`; (4) a repeat report returns the live one; (5) general reports from funding to `delivery_ready`; (6) a console no-show page for the existing action, and no second audit row on an API replay; (7) informed senders are told when the change applies. The advisor's answers (commit `2220b61`) are built as written. Known limit: the no-show window keeps the funded `agreed_pickup_at`.

**L11A judgment calls (accepted at the gate, for Ismail's end review):** (1) no guest payer email or page carries the tracking number, including the deposit receipt the plan mentions, because spec 16's list of who sees it leaves the guest out (spec wins over plan); (2) `GET /api/parcels/<id>` shows the number to the sender only, a traveler learns it from the proposal; (3) the console Payments and Payouts lists lead with the number, the payer or traveler moves to the second column; (4) background-job and technical-record pages keep record ids. The gate also fixed two console layout bugs that predate L11A: every list's search box was about 174 px wide instead of 340 px, and the deal heading lost its mono face.

**L6A judgment calls (accepted at the gate, for Ismail's end review):** (1) a different decision on an already-decided row is refused even when it stores the same status (reject against ask for a new upload), so a second reviewer is never told their choice was saved; (2) the waiting total shows on the Verification section tab and on its entry; (3) the admin API takes the same three decisions as the console; (4) the app's notification list keeps the generic "Account" row for both kinds of decision (it renders by channel), and the push and the email carry the difference, so no mobile change was needed.

**L5A judgment calls (accepted at the gate, for Ismail's end review):** (1) paused journeys still take progress reports and get reminders, because funded deals continue; (2) a report that a later report depends on cannot be retracted (`progress_has_followup`); (3) a late `departed` report re-arms the arrival question under its own job key; (4) no reminder for `at_port`; (5) a retraction sends a neutral `deal.updated` refresh, no push. L9A's route changes must call `schedule_leg_reminders` after re-timing legs.

**L11B judgment call (accepted at the gate, for Ismail's end review):** the posting-deposit screen does not show the tracking number, because the plan's list of screens leaves it out; `PaymentOrder.trackingNumber` is already read, so adding it is one line. Later mobile packages put `TrackingNumberView` (`mobile/lib/design/components/tracking.dart`) on their own parcel screens (rule 12).

**Closed carry-over (L4C, PR #30, `c360dcf`):** L3A's backup ferry distances are removed (seed port coordinates, staff-typed kilometres, `distance_km` on `create_crossing`); a test pinned every shipped crossing's distance, match and price before the removal and passes unchanged after it. A city without catalogue coordinates is refused as a port (`sea_crossing_coordinates_missing`).

**Closed carry-over (L4C):** the Django CI job is now four parallel shards (`Django — tests (shard K)`, 25-minute limit each); the check `Django — migrations + tests + lint` keeps its name and fails unless every shard passed and every collected test ran exactly once. Slowest shard about 13 minutes on three consecutive runs. When the slowest shard passes 15 minutes, refresh `backend/monolith/config/test_durations.json` from a green run's `django-shard-report-*` artifacts, then add a shard if needed (phase doc section 1).

**L4A judgment calls (accepted at the gate, not reviewed by Ismail):** (1) `listed_reward` takes `enabled=`, read from the quote's settings revision, so a scan adds no query; (2) the price stays editable while the journey is `in_progress`, because it still takes offers on later legs, and a test proves existing offers, deals, orders, ledger and payouts stay identical; (3) counter offers record `listed_price` too; (4) the price history is its own table `trips.JourneyPriceChange`, not `AdminAuditLog`, because the actor is the traveler; (5) clearing or re-sending the stored price is allowed with the switch off; (6) ties name the traveler's terms first; (7) a non-owner sees no `price` while the switch is off; (8) the console journey page shows the price and Django admin makes it read-only.

**Closed carry-over:** FR/ES city coordinates. Every French (34,875) and Spanish (8,132) catalogue city now has official coordinates, joined by INSEE and INE code (France: `geo.api.gouv.fr` town hall points; Spain: Eurostat GISCO LAU 2024 boundary centroids), with source digests in the manifest and the digest pin updated. `test_every_launch_country_city_has_coordinates` fails if any DZ, FR, ES or DE city lacks them, so the distance floor is a crash guard only. Merged in PR #27 (`0119c96`). The `PushRepository.unregisterDevice` carry-over is closed: L2B removed it.

## Handoff notes

One block per package, written by that package's agent in its pull request. Keep each block short and
factual. Use exactly these headings.

### L1A. Backend cleanup, including Railway removal

- Contract as built (names that differ from the plan): no tombstones. Every removed route answers
  404, including the six paths the plan listed for 410. The Railway launcher is now `infra/vps/launcher.py` (`run()`, no `main()`), the internal
  gateway config `infra/vps/gateway.Caddyfile`, the Go entrypoint `backend/services/entrypoint.sh`.
  Legacy history admins use `apps/core/historical_admin.py` (view-only). Full list:
  `docs/WASSLA_L1_CLEANUP_INVENTORY.md`.
- Left for a later package: L1B removes the mobile `compatibleJourneys()` and `airports()`
  repository methods (no callers, routes now 404) and can drop the app's mapping of the six removed
  channel names (`trip.created`, `trip.updated`, `trip.cancelled`, `match.created`,
  `handover.confirmed`, `handover.code_issued`): Ismail confirmed there are no real users, so no
  stored inbox row carries them. It may also delete the client's handling of the retired refusal
  codes `legacy_matching_flow_retired`, `legacy_delivery_flow_retired`, `legacy_dzd_quote_retired`,
  `legacy_trip_flow_retired`, `legacy_trip_search_retired` and `legacy_payment_retired`: no server
  code sends them any more. Keep `product_request_retired`, `legacy_contract_not_supported` and
  `airport_filter_retired`: live server code still sends them.
  `journeys/search` and open-requests stay until L2B. Ismail answered the three open questions (no
  real users, no legacy data): `infra/vps/MIGRATION.md` is deleted. Legacy tables and the
  `schema_version` 1/2 branches stay because removing them needs a narrowing migration (rule 1.5.5);
  inventory section 3 lists them as a follow-up candidate.
- Switches added and their defaults: none. Removed: `SHIPTRIP_EMBEDDED_REDIS`,
  `PAYMENTS_MOCK_WEBHOOK_ENABLED`, `PAYMENTS_LEGACY_MUTATIONS_ENABLED` (no reader left).
- Deviations from the plan (what, why, approved by): branch is `claude/project-thread-po89ml`, not
  an `l/l1a-...` name, because the session's harness fixes the branch (not approved by Ismail; the
  PR target is still `feature/discovery-professional-delivery`). `apps/matching/views.py` cancel,
  decline and withdraw now lock with `select_for_update(no_key=True)` and the module joined the
  lock-order gate; the gate's stated reason for leaving it out was the legacy classes L1A deleted.
  Lock strength only, no result change; accepted by the orchestrator. The plan's 410 tombstone
  module was built and then removed: Ismail confirmed the app was never released and has no real
  users, and the orchestrator asked for 404 on all six paths. Legacy admins made
  view-only and the withdrawal "mark sent" action removed (plan: admin registrations for removed
  surfaces are in scope; the tables stay readable).
- Tests (before and after counts): Django 2,529 passed / 34 skipped (2,563) before;
  2,438 passed / 0 skipped after (138 IDs removed, of which 34 were skipped and 5 are renames; 13 added).
  Go 199 top-level tests before and after. VPS unit 29 before and after. Removed tests are listed in
  inventory section 1.10.
- Known limits: Flutter could not run in this environment (CI runs it; only two Dart test fixture
  strings changed). The VPS image build and all nine container integration groups passed locally.

### L1B. Mobile and docs cleanup

- Contract as built (names that differ from the plan): no contract change. Removed from the client:
  `compatibleJourneys()`, `airports()`, `Airport`, `uploadPhoto`, `cancelMatch`, `unreadActiveCount`,
  `retiredHistory`, the six removed channel names (including the `NotificationChannel` values
  `matchCreated`, `tripCreated`, `tripUpdated`, `tripCancelled`, `handoverConfirmed`), the six retired
  refusal codes, `wilayas.dart`, ~45 unused getters/helpers and 202 unused ARB keys (EN, AR, FR).
  The full list is `docs/WASSLA_L1_CLEANUP_INVENTORY.md` section 4.
- Left for a later package: `JourneyRepository.searchPage` and `RequestRepository`/`MatchingRepository`
  `openFeedPage` stay until L2B replaces them (plan). `PushRepository.unregisterDevice` has no caller;
  sign-out ought to unregister the push installation, so whichever package touches sign-out/push
  should wire it (not deleted on purpose). Later packages re-add ARB keys they need.
- Switches added and their defaults: none.
- Deviations from the plan (what, why, approved by): branch is the harness name
  `claude/project-thread-y61pdg`; PR targets `feature/discovery-professional-delivery`. Four test
  fixtures moved off removed channel/code names. Chat controller's write-only `_backgroundError` field
  was removed with its unused getter (the failure path still swallows the error, as before).
- Tests (before and after counts): Flutter 1,079 passed before, 1,083 after (4 added in
  `legacy_removal_test.dart`). `flutter analyze --fatal-infos` clean before and after. No golden
  file changed.
- Known limits: no screenshots taken (no visual change, and no widget touched). The unused-member
  sweep is name-based, so a member used only through dynamic access would be missed; analyze and the
  suite found none.

### L2A. Discovery backend and marketplace policy

- Contract as built (names that differ from the plan): `docs/PHASE_L2A_DISCOVERY_CONTRACT.md`.
  Usual routes are a child table `PublicProfileRoute` (max 3, position kept) rather than a field, so
  each end is a foreign key to a catalogue locality. The profile's public id is a uuid
  (`PublicProfile.public_id`). `role` on People is the viewer's role (a sender sees travelers). Place
  filters accept any place id, including an airport, and resolve it to its matching locality. The trip
  card's `capacity_band` (`under_5kg`, `5_to_10kg`, `10_to_20kg`, `20kg_plus`) is the smallest free
  weight across the legs still ahead; the spec's "existing public band" did not exist, and a journey
  with a full leg ahead is not listed. The fan-out uses a `ScheduledJob` kind
  `discovery_route_alerts` (choices-only migration `finance/0027`). `trust_signals(user_ids, side=)`
  replaces `traveler_trust_signals` in `apps/matching/find_travelers.py` (same J4 result for travelers).
- Left for a later package: L2B removes the mobile `searchPage`/`openFeedPage` callers of the two
  removed endpoints and the client's handling of `airport_filter_retired` (no server code sends it
  now), and maps `discovery.route_alert` and `discovery.traveler_interested`. L3A moves the
  "flight leg needs an approved ticket" check in `apps/discovery/listings.py:listable_journeys` into
  `proofs.py` (it then covers sea legs) and adds "not paused" to the listing and to
  `matches.traveler_matches`; if pause must re-notify alerts on resume, the job key needs a suffix.
  L4A adds the listed price to the trip card; L6A adds the pro badge and business name.
- Switches added and their defaults: the whole `marketplace` section of spec 2.1 (defaults in the
  contract, section 1); L2A reads `discovery.listings_enabled` (on), `discovery.profiles_enabled` (on)
  and `discovery.interest_daily_cap` (10).
- Deviations from the plan (what, why, approved by): branch is the harness name
  `claude/project-thread-jms2kh`; PR targets `feature/discovery-professional-delivery`. The interest
  cap is a rolling 24 hours and answers 429 (no calendar day is fair across Paris and Algiers). An
  opted-out or hidden member is absent from People, the person page and person alerts, while their
  published trips and requests stay in Listings (spec 4.3: the profile is opt-in, listings are not); a
  banned member is absent everywhere. Discovery reuses the `matching_discovery` throttle scope, so no
  new setting. Reported to the orchestrator with the PR; not reviewed by Ismail.
- Tests (before and after counts): Django 2,438 passed / 0 skipped before; 2,539 passed / 0 skipped
  after (13 removed with the two endpoints; 114 added: 113 in `apps/discovery/tests`, 1 in
  `apps/parcels`; the posting-deposit and J6.4 person-page tests gained assertions for the fan-out
  job and the Discovery tab). Go unchanged and green (`go test -race ./...`).
- Known limits: Matches costs 11 queries per group and has at most 3 groups (bounded, not flat in
  groups). No mobile change in this package, so nothing on Home uses these endpoints until L2B.

### L2B. Discovery on Home (mobile)

- Contract as built (names that differ from the plan): `docs/PHASE_L2B_DISCOVERY_HOME.md`. Routes
  `/discover/trips`, `/discover/requests`, `/discover/people[/:id]`, `/profile/public`,
  `/profile/alerts`; a Browse link takes `from`/`to` (a launch corridor), `alert` and `focus`. The
  traveler-interested push and inbox row open `/requests/<id>/discovery?journey=<jid>`. Domain models
  in `lib/domain/public_discovery.dart`, calls in `lib/data/discovery_repository.dart`, state in
  `lib/app/discovery_state.dart`. Removed: `searchPage`, `openFeedPage`, `JourneySearchPage`,
  `OpenRequestPage`, `discoveryPageSize`, the `airport_filter_retired` handling, and
  `PushRepository.unregisterDevice`.
- Left for a later package: L3B adds sea legs to the trip card (mode icons already come from the
  card's `legs`); L4B adds the listed price to the trip card and preview; L6B the pro badge and business
  name.
- Switches added and their defaults: none. Tier switches are read from the server's `state`.
- Deviations from the plan (what, why, approved by): carry-over `unregisterDevice` was removed rather
  than wired: sign-out already unregisters server-side, so a client call would be a second, failing
  path after the token is gone. Home pull-to-refresh now uses always-scrollable physics so it works on a
  quiet Home. Role-switcher label ellipsises (a 5.9px overflow at 360px). Profile rows with a value
  (language, appearance) share the row 3:2 and wrap instead of overflowing at 320dp and 1.6x text
  (existing code, fixed at the coordinator's request). Reported to the orchestrator
  with the PR; not reviewed by Ismail.
- Judgment calls: corridor chips are the six launch pairs between France, Spain, Germany and Algeria;
  the People row is unfiltered and titled by the viewer's role; previews are bottom sheets; an alert
  deep link resolves through the alerts list plus Browse focus (there is no single-item endpoint);
  focus on Find Travelers pages client-side and quotes for the server's reason; "I can carry this" is
  on a matched traveler card and its preview; a per-usual-route alert switch on the person page; the
  opt-in card hides silently if its read fails; sections follow the member's own content; "See all"
  reused instead of a new label; dates in Arabic use the app's existing formatter (Arabic-Indic digits
  in dates, Latin digits in counts and money), unchanged.
- Tests (before and after counts): Flutter 1,087 passed before, 1,303 after (`k6_discovery_paging_test`
  replaced; eight new `l2b_*` suites). Analyzer clean with `--fatal-infos`.
- Known limits: Home reads Matches at cold start (one request, in the 8-request budget); the trips,
  people and opt-in reads wait until scrolled near. Gate screenshots are rendered from the widget tree
  with the real fonts (EN and AR, 360px), not a device.

### L3A. Routes for everyone, backend

- Contract as built (names that differ from the plan): `docs/PHASE_L3A_ROUTES_BACKEND.md`.
  `SeaCrossing` also stores `distance_meters` (French and Spanish catalogue cities have no
  coordinates, so a great circle cannot be computed at match time); staff give it in km only when a
  city has no coordinates. A sea refusal carries `reason` and no `required_mode` (a road refusal is
  byte-identical to before). Stop refusals are `journey_stop_invalid` with a `reason`. Pause codes:
  `journey_paused_by_staff`, `journey_paused_by_owner`, `journey_not_pausable`,
  `journey_pause_reason_required`; a new offer on a paused journey is refused with `journey_paused`.
  The funded route serves the handover window and note as `route.handover_stops`. Outbox kind
  `leg_proof_status`, channel `leg_proof.status_changed`. The two L2A carry-overs are done: the ticket
  check in `listable_journeys` goes through `proofs.proof_gap_exists()`, and "not paused" is in
  `lifecycle.discoverable()`, which covers listings, both Matches roles, scans and journey detail.
- Left for a later package: L3B builds the console screens over `create_crossing`,
  `activate_crossing`, `deactivate_crossing`, `pause_journey` and `resume_journey`; moves the mobile
  `maxJourneyLegCapacityKg` to 20000; maps the new codes (`sea_*` reasons, `journey_stop_invalid`,
  pause codes, `journey_paused`, `sea_proof_not_approved`); and may rename the app's
  `flightProofStatusChanged` and `proofOnlyForFlight` identifiers (their wire values already moved).
  Audit action names `flight_proof.*` and the `review_flight_proofs` permission keep their names
  (stored in audit and role rows). L6A adds the professional exemption inside `proofs.py` only.
  **Closed after L3A (FR/ES coordinates follow-up):** the bundled catalogue now gives every French
  and Spanish city official coordinates keyed by INSEE and INE code (`geo.api.gouv.fr`, Eurostat
  GISCO LAU 2024), the digest pin is updated, and a release-data test fails if any launch-country
  city lacks coordinates. The floor stays only as a crash guard.
- Switches added and their defaults: none new. L3A reads `sea_legs_enabled` (off), defined in L2A.
- Deviations from the plan (what, why, approved by): branch is the harness name
  `claude/project-thread-bl54yl`; PR targets `feature/discovery-professional-delivery`. The seed file
  is `backend/monolith/apps/locations/data/sea_crossings.json`, not `tools/geography/`, because the
  VPS image ships only `backend/monolith` (the `catalogue` step now runs the seed). `available_modes`,
  `default_mode` and `flight_is_required` were removed rather than made place-aware: no production
  code called them, and `check_leg_mode` is the one rule. `sea_legs_available` covers every sea leg
  of the journey, not only the covered range: spec 5.3 says a deactivated crossing blocks new offers
  "on every journey that uses it", and the spec wins. Volume and parcel-slot failures answer the
  existing `capacity_exceeded`. No alias is kept for the renamed kind and channel (never in
  production). The staff pause reason is internal; the owner sees only `paused_by_staff`. A stop left
  at its defaults stores no row; refusing every category is refused. A pending offer stays pending
  while paused and cannot be accepted until resume; resuming does not re-send route alerts.
  Crossings are read, not locked, at acceptance (deactivation touches nothing else, so the read is
  serially equivalent). Permissions: crossings use `manage_settings`, staff pause `manage_journeys`.
  Pre-existing bug fixed: a road leg between catalogue cities without coordinates and without a stored
  distance crashed the scan; it now prices at the distance floor. Existing tests edited (listed in
  the PR): the version string, the renamed kind, channel and code, the 20,000 kg ceiling, and the two
  `available_modes`/`default_mode` tests rewritten onto `check_leg_mode`. Reported to the orchestrator
  with the PR; not reviewed by Ismail.
- Tests (before and after counts): Django 2,539 passed before; 2,615 passed after (77 added: 46 in
  `test_l3a_routes.py`, 25 in `test_l3a_matching.py`, 6 in `test_l3a_ticket_copy.py`; two
  `phase8fa` tests of the removed helpers became one). Go unchanged and green. `makemigrations --check` clean; `schema.sql` regenerated (additions only).
- Known limits: (closed since: French and Spanish road legs priced at the distance floor until the
  coordinates follow-up above.) Road distance everywhere is straight-line: no production route provider is configured.
  The console has no crossing or pause screen until L3B; staff use the service functions.

### L3B. Routes for everyone, mobile and admin screens

Detail: `docs/PHASE_L3B_ROUTES_MOBILE_ADMIN.md`.

- Contract as built (names that differ from the plan): no new endpoint; the app reads
  `GET /api/geography/sea-crossings`, `proof_required` and `proof_state`, `stops`,
  `refused_categories`, `accepts_fragile`, `pause`, per-leg `capacity_volume_l` and
  `capacity_parcels`, and a funded deal's `route.handover_stops`, and writes `stops`,
  `refused_categories`, `accepts_fragile` and the two capacity fields on create and edit (an edit
  always sends them, with explicit nulls for a limit that was removed), plus
  `POST /api/journeys/<id>/pause` and `/resume`. Console routes: `sea-crossing-new`,
  `sea-crossing-toggle`, `journey-pause`. `resolve_port(country, name)` moved into
  `apps.locations.sea_crossings` so the add form and the seed use one resolver. Mobile renames:
  `legProofStatusChanged`, `proofNotRequired`, `staleTicketInvalid`, `proofExplainerFlight`;
  `TransportMode.requiresProof` is deleted.
- Left for a later package: nothing from L3A is open on the app or console side. Booking reference for
  a ferry ticket is not stored anywhere (the queue shows the document kind where a flight shows its
  number); adding one is a backend change for L6A or later if wanted. There is no in-app link to
  support, so the staff-paused banner is text only. L6A adds the professional ticket exemption inside
  `proofs.py` and the proof screen already follows `proof_required`, so it needs no app change.
- Switches added and their defaults: none new. The console now exposes `sea_legs_enabled` (off) in
  Settings → Marketplace features, with a warning line.
- Deviations from the plan (what, why, approved by): all judgment calls, none reviewed by Ismail.
  (1) Ferry queue "reference" column shows the document kind: no booking-reference field exists.
  (2) Sea is never pre-selected; flight stays the derived default, so nobody boards a ferry by
  accident. (3) The traveler word is "Ferry", the console word is "Sea". (4) Ticket-proof URL paths,
  permission names and audit action names keep `flight_proof`: they live in stored rows and links.
  (5) The Sea legs switch lives in the existing Marketplace features form, not a new card.
  (6) The first stop shows only the pickup switch and the last only the drop-off switch, and the
  request never contradicts the server's normalisation. (7) The ferry mode colour is a plum that no
  status tone uses. (8) The ferry list has its own provider with retry off, so a failure shows the
  notice at once instead of loading for a minute. (9) `ApiException.intExtra` now unwraps a
  one-element list, and `stringExtra` is new: a refusal raised from a serializer wraps every value.
  (10) The "What you carry" section appears once two stops exist. (11) Ticket kinds on the proof
  screen stay ticket, boarding pass and booking for both modes; the server owns validation.
- Tests (before and after counts): Flutter 1,303 passed before; 1,353 after (50 added: 30 in
  `l3b_sea_route_model_test.dart`, 20 in `l3b_sea_screens_test.dart`; two existing tests updated for
  the new fixture fields and the 20,000 kg ceiling, one replaced for the deleted `requiresProof`).
  `flutter analyze --fatal-infos` clean. Django: 2,615 passed before (L3A); L3B adds 36 (34 in
  `apps/admin_panel/tests/test_l3b_console.py`, 2 in `apps/discovery/tests/test_marketplace_policy.py`);
  the full Django job in CI is green. `makemigrations --check` clean (no
  model change). Ruff check clean.
- Known limits: the console journey page shows stops and capacity but staff cannot edit them (by
  design: the traveler owns them). A route with a ferry leg cannot be priced differently from a flight
  until L4A. The French and Spanish coordinates carry-over above is untouched by this package.

### L4A. Traveler pricing, backend

Detail: `docs/PHASE_L4A_TRAVELER_PRICING_BACKEND.md`.

- Contract as built (names that differ from the plan): `Journey.price_per_kg_eur_cents` and
  `min_price_eur_cents` (CHECK `journey_price_complete`), new append-only `trips.JourneyPriceChange`
  as the journey's price audit trail. Rules in `apps/trips/pricing.py` (`check_price`,
  `apply_journey_price`, `traveler_pricing_policy`). `PATCH /api/journeys/<id>/pricing` takes both keys
  (nulls clear) and answers the journey; new `GET /api/journeys/pricing-policy` gives the editor the
  switch and ceilings. Journey payload and trip card: `price` = `{price_per_kg_eur_cents,
  min_price_eur_cents}` or null. Find Travelers: `economics.listed` = `{reward_eur_cents, economics,
  price_per_kg_eur_cents, min_price_eur_cents, basis}` or null; sort `listed_price`. Codes:
  `journey_price_invalid` (reasons `price_incomplete`, `price_per_kg_above_maximum` with
  `max_price_per_kg_eur_cents`, `min_price_above_maximum` with `max_min_price_eur_cents`),
  `traveler_pricing_disabled`, `journey_price_not_editable` (with `status`). Offer
  `terms_snapshot.listed_price` (block or null), not in the public terms snapshot.
- Left for a later package: L4B builds the app side (route editor and journey detail "Your price"
  reading `pricing-policy`, Find Travelers card and sort, pre-filled propose sheet from
  `economics.listed`, trip card line). A route edit (`PATCH /api/journeys/<id>`) must always send the
  two price fields, because leaving them out clears the price (whole-route rule, like stops). Route
  write refusals are list-wrapped by DRF like every route refusal; the pricing endpoint's are flat.
  `POST /api/matches/quote` and traveler-side compatible-requests rows carry no listed price.
- Switches added and their defaults: none new. L4A reads `marketplace.traveler_pricing`
  (`enabled` on, `max_price_per_kg_eur_cents` 10,000, `max_min_price_eur_cents` 50,000), defined in
  L2A, and adds them to the console's Marketplace features form. An unreadable revision reads as off.
- Deviations from the plan (what, why, approved by): all judgment calls, not reviewed by Ismail.
  (1) `listed_reward(journey, pricing_quote, *, enabled)`: the switch is passed in, read from the
  same settings revision as the quote, so a scan costs no query and never mixes revisions.
  (2) The price is also editable while the journey is `in_progress` (plan lists draft, pending
  verification and active): an in-progress journey still takes offers on later legs, so its price
  stays editable for exactly as long as it can be offered on. (3) The listed price is recorded on
  every V1 offer's snapshot, counters included, since both go through `_v1_offer_values`; amounts are
  untouched. (4) The audit trail is a dedicated table, not `AdminAuditLog`, because the actor is the
  traveler, not staff, and has no reason to give. (5) Clearing a price or re-sending the stored one
  is allowed with the switch off, so a route edit never fails on a price the traveler did not change.
  (6) On a tie the basis names the traveler's terms first. (7) A non-owner sees no `price` on journey
  detail while the switch is off; the owner always sees what they stored. (8) Console journey page
  gained a price card and Django admin makes the price read-only.
- Tests (before and after counts): Django 2,654 passed before (integration branch at `de7d538`); 2,703 passed after, 0 skipped. 49 added (26 in
  `apps/matching/tests/test_l4a_listed_price.py`, 23 in `apps/trips/tests/test_l4a_journey_price.py`).
  Two existing tests rewritten to the new contract: `test_phase_j4_find_travelers` economics key set
  (gains `listed`) and `test_marketplace_policy` form save (expects the `traveler_pricing` section).
  The finance suite passes with no edits. `makemigrations --check` clean; `schema.sql` regenerated
  (additions only).
- Known limits: a stored price above a ceiling that staff later lowered stays until the traveler
  changes it (ceilings are typo guards applied at write time). The listed price shown by Find
  Travelers is an unlocked read; the offer's snapshot is recomputed under the journey lock, so a
  price change between the two is recorded faithfully and never changes the amount the sender typed.

### L4C. Housekeeping: test time limit and ferry distance cleanup

Detail: `docs/PHASE_L4C_HOUSEKEEPING.md`.

- Contract as built (names that differ from the plan): CI's Django tests are four parallel jobs
  `django-shard` (`Django — tests (shard K)`, 25-minute limit each). The check name
  `Django — migrations + tests + lint` is kept; that job now only passes when every shard passed and
  `config/test_shards.py verify` proves every collected test file ran in exactly one shard. Split by
  whole file over `backend/monolith/config/test_durations.json`; pytest options `--shard=K/N` and
  `--shard-report=PATH` in the root `conftest.py`. Durations: see the phase doc. Ferry: a port in
  `sea_crossings.json` is `{country, name}` only; `create_crossing(actor, origin_locality_id,
  destination_locality_id, reason, active=False)` (no `distance_km`); a city without catalogue
  coordinates is refused with `sea_crossing_coordinates_missing` (codes
  `sea_crossing_distance_required` / `_invalid` and `MAX_CROSSING_DISTANCE_KM` are gone); the console
  form has no kilometres field.
- Left for a later package: nothing. **Every later package:** a new test file runs in a shard
  automatically (weighed as an average file). When the slowest shard passes 15 minutes, refresh
  `config/test_durations.json` from a green run's `django-shard-report-*` artifacts
  (`python config/test_shards.py merge DIR`), and add a matrix entry if that is not enough.
- Switches added and their defaults: none.
- Deviations from the plan (what, why, approved by): none. Sharding was possible without weakening
  anything, so the limit was not raised to 90 minutes. No column was left unused: `distance_meters`
  is still written (from catalogue coordinates only) and read; only the backup's inputs went.
- Tests (before and after counts): Django 2,703 passed before (integration branch at `e4c2530`);
  2,722 passed after, 0 skipped. Added 19 (4 pinned shipped-crossing tests, 14 shard tests,
  1 console test); 5 ferry tests rewritten to the new rule (listed in the phase doc).
- Known limits: the split is only as even as `test_durations.json` is current; `verify` keeps it
  complete whatever the balance. Lint and the migration check run in shard 1 only.

### L4B. Traveler pricing, mobile

Detail: `docs/PHASE_L4B_TRAVELER_PRICING_MOBILE.md`. Screenshots: `/mnt/project-files/l-series-screens/L4B/`.

- Contract as built (names that differ from the plan): none; the app reads L4A's contract as shipped
  (`Journey.price`, `TripCard.price`, `economics.listed`, `sort=listed_price`, `GET
  /api/journeys/pricing-policy`, `PATCH /api/journeys/<id>/pricing`). `JourneyRepository.update` always
  sends the two price fields (null included) because a left-out price is cleared.
- Left for a later package: nothing for L4B.
- Switches added and their defaults: none; reads `marketplace.traveler_pricing` through the policy
  endpoint. Off: price fields and the "Lowest price" sort are hidden, a stored price is re-sent
  unchanged by a route edit.
- Deviations from the plan (what, why, approved by): judgment calls, not reviewed by Ismail. (1) The
  different-amount field starts on the listed price and "Use suggested" is hidden when a listed price
  exists. (2) The sort pill shows only while pricing is on. (3) The trip preview sheet also shows the
  price. (4) The journey page edits the price on any journey that is not finished (server decides).
- Tests (before and after counts): Flutter 1,353 to 1,374 (+21, `l4b_traveler_pricing_test.dart`); two
  L3B tests answer the new policy route (no assertion changed). Django untouched.
- Known limits: the listed price is shown on the card and the propose sheet, not on the Find Travelers
  trip detail sheet.

### L5A. Progress updates and reminders, backend

Detail: `docs/PHASE_L5A_PROGRESS_UPDATES_BACKEND.md`.

- Contract as built (names that differ from the plan): model `trips.JourneyLegProgress` (migration
  `trips/0011`); `DealEvent` kinds `traveler_progress` and `traveler_progress_retracted`; `ScheduledJob`
  kind `leg_reminder`; channels `deal.progress_reported` and `journey.leg_reminder`. Routes:
  `GET /api/journeys/<id>/progress`, `POST /api/journeys/<id>/legs/<leg_id>/progress {kind}`,
  `POST /api/journeys/<id>/progress/<progress_id>/retract`, `GET /api/journeys/progress/pending`
  (`{results: [{journey_id, leg_id, kind, place_name, planned_at}]}`). Flat `{code, detail}` refusals:
  `progress_out_of_order`, `progress_too_early` (+`available_at`), `progress_kind_not_allowed`,
  `progress_retract_window_closed`, `progress_has_followup`, `journey_not_owned`, `journey_not_reportable`.
  A repeat report is a 200 with the existing row. Timeline payload keys: `source`
  (`traveler_reported`), `progress_id`, `progress_kind`, `leg_id`.
- Left for a later package: L5B (stepper, Home question, sheet from the notification, sender timeline
  lines). L9A's route changes must call `apps.trips.progress.schedule_leg_reminders(journey)` after
  re-timing legs (the old jobs no-op on a moved time, the new times need their own). A staff report
  (`source=staff`) is stored but has no endpoint yet.
- Switches added and their defaults: none; reads the existing `marketplace.reminders` section
  (on, 30 and 60 minutes, repeat after 180 minutes, 2 repeats).
- Deviations from the plan (what, why, approved by): judgment calls, not reviewed by Ismail. (1) Paused
  journeys still take reports and get reminders, because funded deals continue (spec 5.7). (2) Retracting
  a report that a later report depends on (`departed` under `arrived`, `arrived` under the next leg's
  `departed`) is refused (`progress_has_followup`). (3) A late `departed` report re-arms the arrival
  question under its own job key, because the first arrival job had already found "not yet departed" and
  stopped. (4) Reminders are keyed to departed and arrived only; `at_port` has no reminder.
  (5) A retraction sends a neutral `deal.updated` refresh to the sender, no push.
- Tests (before and after counts): Django 2,751 passed before; 2,795 after (+44, `test_l5a_progress.py`),
  0 skipped. The first full local run had 30 failures that were all HTTP 429 from my shell lacking CI's
  `DRF_*_THROTTLE_RATE` variables; those five files pass (102) with them set.
- Known limits: the pending-questions read runs one query per leg to check for a funded parcel (small
  per traveler); a "Not yet" answer is the repeat chain itself, there is no snooze state.

### L5B. Progress updates and reminders, mobile

Detail: `docs/PHASE_L5B_PROGRESS_UPDATES_MOBILE.md`. Screenshots: `l-series-screens/L5B/` (EN and AR).

- Contract as built (names that differ from the plan): no backend change. Reminder deep link is
  `/journeys/<id>?leg=<leg_id>&ask=<kind>`; new `LiveResource.progress` for Home's question; the sender's
  timeline lines come from the deal's existing `timeline` array (`traveler_progress`, minus any
  `traveler_progress_retracted` with the same `progress_id`).
- Left for a later package: nothing from this package. L9A's route changes still owe the
  `schedule_leg_reminders` call (see L5A).
- Switches added and their defaults: none.
- Deviations from the plan (what, why, approved by): judgment calls, not reviewed by Ismail. (1) "Not yet"
  hides the question for the app session only; there is no server snooze (L5A has none). (2) Timeline
  lines show on the sender's view only; the traveler has the stepper. (3) A reminder opens its sheet only
  if the server still offers that step, otherwise just the stepper. (4) Home reads the pending questions
  only when the traveler has a live journey (no extra request for senders).
- Tests (before and after counts): Flutter 1,399 passed before, 1,428 after (+29,
  `test/l5b_progress_test.dart`). Two older journey-detail tests gained a `/progress` route. Analyze
  `--fatal-infos` and format clean; all 10 CI checks green including Schema drift.
- Known limits: no connectivity detection; the offline message appears after a failed attempt, and the
  "Needs a connection" line is always shown under the button.

### L6A. Verification inbox and removal of the parked switches

Detail: `docs/PHASE_L6A_VERIFICATION_INBOX.md`. Screenshots: `l-series-screens/L6A/` (console EN; emails EN, FR, AR).

- Contract as built (names that differ from the plan): `apps/admin_panel/verification_inbox.py` owns
  "waiting" (`waiting_counts(request)`, once per request), the tabs, the landing URL and the decision
  values. New console route `verification` (`/admin/verification/`, landing redirect). Decision values
  `approved`, `resubmission_requested`, `rejected`, accepted by the console form, both review services
  and `POST /api/admin/kyc|flight-proofs/<id>/review`. Audit actions keep their names
  (`kyc.rejected`, `flight_proof.rejected`); the outcome is `metadata.outcome` on every decision. Both
  status channels and both email contexts carry `outcome`. Tab links are the queues filtered to
  `?status=pending`.
- Left for a later package: nothing owed. When L15's helper reports document reviews as a count
  (plan 2.11), it should read `verification_inbox.waiting(tab)` so its number matches the inbox.
- Switches added and their defaults: none. Removed: `marketplace.courier_handoff`,
  `marketplace.professional` (a revision naming either is refused on save).
- Deviations from the plan (what, why, approved by): judgment calls, not reviewed by Ismail. (1) A
  different decision on an already-decided row is refused even when it stores the same status, so a
  second reviewer is never told their choice was saved; the same decision replayed stays a silent
  success. (2) The navigation shows the total on the Verification section tab and on the entry.
  (3) "New upload requested" is shown on decided rows (queue, previous attempt, history, header), read
  from the audit entry, one query per page. (4) The admin API takes the three decisions too, so there
  is one rule. (5) The plan's "a search of `backend/` for `professional` and `courier_handoff` finds
  nothing" holds for code; the one remaining hit is the test the plan asks for, which saves a revision
  naming those two keys and expects the refusal. (6) Console labels renamed to the spec's words: overview
  items "ID checks to review" and "Tickets to review", breadcrumbs "Verification › ID|Tickets"; the
  technical Django-admin queue panel uses the same two labels.
- Tests (before and after counts): Django 2,795 collected before, 2,824 after (+28 in
  `test_l6a_verification_inbox.py`, +1 policy test; the two policy tests that read the removed sections
  lost those lines). Six existing assertions rewritten to the new labels or the email context's
  `outcome` (listed in the phase doc). `makemigrations --check` clean; ruff clean; no migration.
- Known limits: the app's notification list keeps one generic "Account" row for both decisions (it
  renders by channel); the push and email carry the difference. The console is English only.

### L6B, L7A, L7B, L8A, L8B. Parked

Parked on 2026-11-13, not part of this build. No handoff notes. Full text: `docs/parked/WASSLA_PROFESSIONAL_AND_COURIER_PLAN.md`.

### L9A. Problems and route changes, backend

Detail: `docs/PHASE_L9A_PROBLEMS_ROUTE_CHANGES.md`. Screenshots: `/mnt/project-files/l-series-screens/L9A/`.

- Contract as built (names that differ from the plan): `problems.ShipmentProblem` adds
  `reporter_role`, `escalated_at`, `acknowledged_by/at/reason`, `closed_at`, `closed_by_audit`;
  statuses `open|escalated|acknowledged|closed`. `GET|POST /api/deals/<id>/problems` (the read adds
  `no_show_kind`, `no_show_reason`, `no_show_available_at`, `reportable_kinds`). Console
  `disputes/problems/` and `marketplace/deals/<id>/no-show/`; `admin_panel.services.record_deal_no_show`
  is the one staff path (API and console). `trips.JourneyScheduleChange` adds `proposed_by`,
  `affected`, `applied_at`, `withdrawn_at`, `withdrawn_by`; the consent adds `reasons`
  (`deadline|shift|pickup`), `arrival_before/after`, `pickup_before/after`, `decided_at`; affected
  rows carry `informed` for collected parcels; the preview carries `notices` (`ticket_recheck`); the
  sender's view carries `informed`, `can_answer`, `actions`. Routes:
  `journeys/<id>/schedule-changes` (GET list, POST propose), `.../preview`, `.../<change>/withdraw`,
  `deals/<id>/schedule-change` (sender GET) and `.../accept|decline`. Channels
  `deal.problem_reported`, `journey.schedule_change_proposed|answered|applied|withdrawn`. Job kind
  `schedule_change_settle`. `CancellationQuote.caused_by`; `cancellation_reason`
  `declined_schedule_change`. `apps.trips.services.validate_leg_times` extracted from the sequence check.
- Left for a later package: L9B builds every app screen on this contract (problem report sheet and
  list with the no-show button driven by `can_report_no_show`/`no_show_reason`; the traveler's
  change-times flow using `preview` then propose, the waiting state and withdraw; the sender's
  accept/decline card from `GET /api/deals/<id>/schedule-change`; the cancellation confirmation reads
  `caused_by`). Push taps currently open Deliveries.
- Switches added and their defaults: none (uses the existing `marketplace.route_change.material_shift_minutes`, 360).
- Deviations from the plan (what, why, approved by): the advisor's answers of 2026-11-13 (commit
  `2220b61`) are built as written: baseline is what the sender last agreed to, the pickup side counts
  for parcels not collected, collected parcels are informed and never block, a re-timed ticket leg is
  re-checked on apply, the unreachable reminder branch is removed. Own calls, for Ismail's end
  review: (1) "earlier than the agreed pickup" counts only when the pickup moved earlier; (2) accepted
  but unfunded deals are classified and asked too; (3) problem capabilities reuse
  `view_disputes`/`manage_disputes`; (4) a repeat report returns the live one (200); (5) general
  reports are accepted from funding to `delivery_ready`; (6) a console no-show page was added (the
  existing action was API only) and the API path no longer writes a second audit row on a replay;
  (7) informed senders are told when the change applies; (8) a waiting change is withdrawn as
  `no_longer_valid` when the journey stops being live or progresses past the new times.
- Tests (before and after counts): Django 2,824 collected before, 2,895 after, all passing locally in 4 shards (+26 in
  `apps/problems/tests/test_l9a_problems.py`, +45 in `apps/trips/tests/test_l9a_schedule_changes.py`).
  No existing assertion changed. `makemigrations --check` clean, ruff clean, `schema.sql` re-exported
  (additions only), Go notification lockstep test passes.
- Known limits: `agreed_pickup_at` keeps its funded value after a change, so the no-show window
  still opens at the old pickup time; the console is English only.

### L9B. Problems and route changes, mobile

Detail: `docs/PHASE_L9B_PROBLEMS_ROUTE_CHANGES_MOBILE.md`. Screenshots: `/mnt/project-files/l-series-screens/L9B/`.

- Contract as built (names that differ from the plan): no backend change. New live-event channels are mapped
  (`deal.problem_reported`, `journey.schedule_change_*`); a `journey.schedule_change_proposed` push with a
  `deal_id` opens `/deals/<id>/schedule-change`. `CancellationQuote.causedBy` reads `caused_by`. Routes
  `/deals/:id/schedule-change` and `/journeys/:id/change-times`.
- Left for a later package: nothing from this package.
- Switches added and their defaults: none.
- Deviations from the plan (what, why, approved by): none. The optional reads (problems, schedule change)
  do not retry on failure and render nothing, so a failed side read never fails the delivery page.
- Tests (before and after counts): Flutter 1,428 before, 1,461 after (33 new). No Django or Go change.
- Known limits: the leg editor cannot tell departed or arrived legs; the server refuses and the screen says why.

### L11A. Tracking number, backend

Detail: `docs/PHASE_L11A_TRACKING_NUMBER.md`. Screenshots: `/mnt/project-files/l-series-screens/L11A/`.

- Contract as built (names that differ from the plan): `ParcelRequest.tracking_number` (`varchar(12)`,
  unique, `WSL-` plus 8 of `23456789ABCDEFGHJKMNPQRSTVWXYZ`), migrations `parcels/0011` to `0013`.
  `apps/parcels/tracking.py`: `generate`, `normalize`, `is_valid`, `for_request`, `for_deal`,
  `insert_with_new_number` (5 attempts, then `TrackingNumberUnavailable`). API key `tracking_number`
  on parcels (sender only), matches, offers, deals, the deal payment view, payment orders
  (`PaymentOrder.tracking_number`: a deposit or Boost names its request, a balance its deal),
  payouts (and the mobile `payout_status` block), disputes and the JSON admin lists. Email contexts
  carry `tracking_number`, shown as "Tracking number" / "Numéro de suivi" / "رقم التتبع". Finance
  `Scope.search_kind`; console search helper `apps/admin_panel/tracking_search.py`.
- Left for a later package: L11B shows the number in the app (read `tracking_number` from the
  payloads above; the request detail carries it for the sender only). Every later package that names
  a parcel uses `tracking.for_request` or `tracking.for_deal`, never a record id.
- Switches added and their defaults: none.
- Deviations from the plan (what, why, approved by): judgment calls, not reviewed by Ismail. (1) No
  guest payer email carries the number, including the deposit receipt the plan mentions: spec 16
  lists who sees it and keeps it off the guest's page, and an existing test already forbade the guest
  receipt from echoing deal context. (2) Console Payments and Payouts move the payer and traveler to
  the second column so the number leads. (3) Background-job and technical-record pages keep record
  ids. (4) Two console layout fixes found at the gate (the search box width on every list, the mono
  heading) are included.
- Tests (before and after counts): Django 2,722 passed before (integration branch at `6c00013`);
  2,751 passed after, 0 skipped. Added 29 (`test_l11a_tracking_number.py` 28,
  `test_l11a_tracking_migration.py` 1) plus new privacy assertions in four existing files; three
  finance tests, four notification tests and one person-page test rewritten to the new rule (listed
  in the phase doc). No list gained a query (table in the phase doc).
- Known limits: immutability is enforced in `ParcelRequest.save`, so a queryset `update()` could
  still change a number; nothing in the code does. Background-job pages name records by id.

### L11B. Tracking number, mobile

Detail: `docs/PHASE_L11B_TRACKING_NUMBER_MOBILE.md`. Screenshots: `/mnt/project-files/l-series-screens/L11B/`.

- Contract as built (names that differ from the plan): widget `TrackingNumberView(number, dense)` in `mobile/lib/design/components/tracking.dart`; `readTrackingNumber` in `domain/json.dart`; `trackingNumber` on `DeliveryRequest`, `Match`, `Offer`, `Deal`, `PaymentOrder`, `DealPaymentState`, `PayoutMobile`, `PayoutListItem`, `Dispute`. Strings `trackingNumberLabel`, `trackingNumberCopy`, `trackingNumberCopied`.
- Left for a later package: later mobile packages put the widget on their own parcel screens (rule 12). The posting-deposit screen does not show it yet (`PaymentOrder.trackingNumber` is read).
- Switches added and their defaults: none.
- Deviations from the plan (what, why, approved by): none. No screen printed a delivery id as a reference, so there was nothing to remove.
- Tests (before and after counts): Flutter 1,374 to 1,399.
- Known limits: the app trusts the server's decision on who sees the number; it never validates the format.

### L12A. Proposal deadline and trip-fit alerts, backend

Detail: `docs/PHASE_L12A_PROPOSAL_DEADLINE_TRIP_FIT.md`. Screenshots: `/mnt/project-files/l-series-screens/L12A/` (console EN).

- Contract as built (names that differ from the plan): `apps/matching/offer_deadlines.py`
  (`response_deadline`, `schedule_deadline_jobs`, `deadline_passed`, `effective_status`, the two
  handlers). Job kinds `offer_response_reminder`, `offer_expiry` (migration `finance/0030`), keys
  `<kind>:<offer id>:<expires_at>`, payload `{offer_id, expires_at}`. Refusal code `offer_expired`
  (409, with `expires_at`) on accept, counter, decline, withdraw and match cancel. Channels
  `offer.response_reminder` (`match_id`, `parcel_id`, `journey_id`, `offer_id`, `tracking_number`)
  and `discovery.request_fits_trip` (`request_id`, `journey_id`); expiry is `offer.updated` with
  `status: "expired"` to both. The plan's `awaiting` is the existing `awaiting_party`
  (`sender|traveler`, with `awaiting_user_id`); no second field. From the deadline on an offer
  payload reads `status: "expired"`, `allowed_actions: []`, `awaiting_party: null`. Trip-fit:
  `apps/discovery/trip_fit.py`, model `discovery.TripFitAlert` (migration `discovery/0002`), called
  by `handle_route_alert_fanout` for a request.
- Left for a later package: L12B maps the two new channels and the `offer.updated` expired status
  in the app (`domain/notification.dart`, `live_updates.dart`, `push_coordinator.dart`), renders
  "Answer by" / "Waiting for an answer until" from `expires_at` and `awaiting_party`, the expired
  state and the `offer_expired` refusal; the trip-fit push opens `/requests/<id>/discovery?journey=<jid>`.
- Switches added and their defaults: `marketplace.offers.response_deadline_enabled` (on),
  `response_hours` (6), `reminder_before_hours` (1, must be smaller than the delay, 0 for none);
  `marketplace.discovery.trip_fit_alerts_enabled` (on), `trip_fit_max_travelers` (30),
  `trip_fit_daily_cap` (5). All on the console's "Marketplace features" form.
- Deviations from the plan (what, why, approved by): judgment calls, not reviewed by Ismail.
  (1) Withdraw and match cancel also refuse after the deadline, so expiry is the single ending.
  (2) One trip-fit alert per traveler per request (the better ranked trip), since the cap counts
  travelers. (3) Trip-fit alerts also need the listings switch, because the alert opens the public
  preview. (4) The offer payload reads `expired` from the deadline on, before the job stores it.
  (5) The reminder and the trip-fit alert are push class `marketplace`, like the proposal itself.
  (6) The trip-fit push copy names no cities (ids only on a lock screen).
- Tests (before and after counts): Django 2,895 collected before, 2,941 after (+34
  `test_l12a_offer_deadlines.py`, +12 `test_l12a_trip_fit.py`), all passing locally in 4 shards.
  Rewritten to the new rule: `test_alerts.py::test_a_request_opening_notifies_request_watchers`
  (its watcher was the fitting traveler, who now gets the trip-fit alert instead), the two
  `test_marketplace_policy.py` form tests and `test_l4a_journey_price.py`'s console test (they post
  the new fields).
  `makemigrations --check` clean, ruff clean, `schema.sql` re-exported (additions only), Go
  `go test -race ./...` passes.
- Known limits: between the deadline and the expiry job (normally under a minute) the match still
  reads `pending` while its offer reads `expired`. Choosing whom to alert is a flat number of
  queries; each traveler told costs one inbox write (8 queries).

### L12B. Proposal deadline and trip-fit alerts, mobile

Detail: `docs/PHASE_L12B_PROPOSAL_DEADLINE_MOBILE.md`. Screenshots: `/mnt/project-files/l-series-screens/L12B/`.

- Contract as built (names that differ from the plan): widget `OfferDeadline` in
  `mobile/lib/features/offers/offer_deadline.dart`; `clockProvider` in `core/time/clock.dart` (the one clock
  for countdowns); `ApiErrorCode.offerExpired` (a stale-state code); channels `offerResponseReminder` and
  `discoveryRequestFitsTrip`; destination `OpenRequestFit(requestId, journeyId)`; Browse requests takes
  `carryJourneyId` (query `journey`) next to `focus`; `showRequestPreview(..., carryJourneyId:)`. Push for the
  trip-fit alert is `/discover/requests?focus=<request>&journey=<journey>`.
- Left for a later package: nothing owed. The reminder's bell row uses the generic proposal wording; an
  `offer.updated` with `status: expired` keeps the generic "Offer" bell row.
- Switches added and their defaults: none (both channels follow the existing marketplace push class).
- Deviations from the plan (what, why, approved by): judgment calls, not reviewed by Ismail. (1) No endpoint
  returns one request card, so Browse reads the public list on (up to 8 pages) to find the named parcel and
  says "no longer open" if it is not there; `GET /api/discovery/requests/<id>` would be exact and is a backend
  change left to Codex if wanted. (2) The same "no longer listed" notice now also covers a trip named by a
  route alert, which used to miss silently. (3) The expired proposal screen hides the deadline line, because
  the notice says it.
- Tests (before and after counts): Flutter 1,461 before, 1,493 after (32 new in
  `test/l12b_proposal_deadline_test.dart`). Test support gained an optional `now` on `containerFor`,
  `discoveryContainer` and `pumpDiscovery`. No Django or Go change.
- Known limits: the countdown is minutes, rounded up, and re-checks every 15 seconds in the last hour; at
  zero the screen re-reads, so for a moment the line says "The time to answer has passed" before the server's
  "expired" arrives. The match still reads pending until the expiry job runs (L12A's known limit).

### L13A. Reviews, reports and moderation, backend

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L13B. Reviews, mobile

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L14. Staff two-step sign-in and finance exports

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L15. AI helper: keys and read access

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L16. AI helper: changes

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L17. AI helper skill

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L10. Final acceptance

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

## Questions for Ismail

| Asked | Question | Answer |
| --- | --- | --- |
| 2026-11-11 | Which sea crossings? | Research the popular routes and add them. Done: spec 5.3.1. |
| 2026-11-11 | Remove Railway files? | Yes. They do not stay on this branch. In L1A. |
| 2026-11-11 | Is a declined schedule change a traveler-caused cancellation? | Yes. |
| 2026-11-11 | Keep "I can carry this"? | Yes. |
| 2026-11-12 | Which gaps against the cahier des charges should be built? | Tracking number; alert to travelers whose trip fits plus a reminder before a proposal expires; "the other person did not come"; reviews on profiles with report and hide; admin export and two-step sign-in. |
| 2026-11-12 | Before the unattended run: fix the test time limit first? Tracking number right after L4B? AI helper shipped off? One question must not stop everything? A legal package (terms, prohibited items)? Keep the screenshots? | Yes, yes, **no** (the helper ships on), yes, **no**, yes. Plan 5.1d. |
| 2026-11-12 | AI helper: may it read everything and act directly? | No documents, bank details, delivery codes or chat contents. Money, ban, role and settings actions are prepared and confirmed in the console. Read key expires 8 hours after creation even in use; change key 30 minutes. The skill is written last. |
| 2026-11-13 | Ismail stopped the build after L5B: Wassla is for fast delivery, mostly flights and drives made the same day. What changes? | Professional travelers are parked for a later subdomain, their plan kept in the repository. Courier handoff is parked too. Sea legs stay built and switched off. "Same day" is the target, not a rule in the app. A proposal waits 6 hours (or until the pickup time) with a reminder 1 hour before, instead of 48 and 12. Everything else stays. Plan 5.1e. |

## Change log for the plan and spec

| Date | Change |
| --- | --- |
| 2026-11-10 | Spec and plan first written. |
| 2026-11-11 | Added effort per package, the start runbook (plan 1.0), this progress file (plan 1.8), the agent brief (plan 1.9), the researched sea crossings (spec 5.3.1), Railway removal in L1A, and Ismail's answers. |
| 2026-11-12 | Plan L3B: the staff-paused banner shows no reason, because L3A keeps the staff pause reason internal (the owner's payload carries only `paused_by_staff`). |
| 2026-11-12 | Added packages L11A to L17 and the no-show reports in L9A and L9B (spec 12 and 16 to 20; plan 2.10 to 2.12, section 3, 5.1b, 5.1c). L10 stays the last package and gains their acceptance checks. Correction recorded in plan 5.1b: proposals had no expiry at the baseline; L12A adds it. |
| 2026-11-12 | Skill drafted early at Ismail's request: `docs/admin-helper-skill/` (`/wassla` plus the pasted line; briefing by default; how-to answers). Spec 20.5 and 20.7 updated; L15 gained `GET tasks` and the one-line copy block; L17 now verifies and proves the draft instead of writing it. |
| 2026-11-12 | Before the unattended run (plan 5.1d): added L4C (CI time limit, ferry distance cleanup) to run first; moved L11A and L11B to right after L4B and added rule 1.5.12; added the advisor role (1.1) and "When a package is blocked" (1.0); gate screenshots are kept in `/mnt/project-files/l-series-screens/` and L10 builds a gallery (1.6). |
| 2026-11-13 | Scope narrowed to fast delivery (plan 5.1e, spec "Scope change of 2026-11-13"). Parked, with their complete text moved to `docs/parked/WASSLA_PROFESSIONAL_AND_COURIER_PLAN.md`: the professional half of L6A, L6B, L7A, L7B, L8A, L8B; spec 7, 9, 10 and the professional column of spec 6. L6A is now the verification inbox with two tabs and removes the two unused policy sections. L9A's problems live in `apps.problems` and lose the courier kinds; it no longer depends on L8A. L12A's proposal deadline is 6 hours or the pickup time, reminder 1 hour. The helper's action table, the final acceptance scenarios, `CLAUDE.md`, `AGENTS.md` and the skill draft were aligned. The documents as they stood before: commit `50547be`. |
| 2026-11-13 | Advisor answers for L9A's schedule changes, written into spec 12 and plan L9A, L9B and 5.1e: the baseline for "moved" is what the sender last agreed to; the pickup side counts for parcels not yet collected; collected parcels are informed and never block; a re-timed ticket leg goes back to review on apply through the existing path; the unreachable `ACTIVE` reminder branch in `replace_journey_route` is removed. |
| 2026-11-13 | L9B merged (PR #38, `b00260b`): problem reports, no-show action and route changes on the app. No backend change. Next: L12A. |
| 2026-11-14 | L12A merged (PR #39, `05ab258`): proposal deadline (6 hours or the pickup time, reminder 1 hour before), expiry, `offer_expired` refusals and trip-fit alerts, with their console switches. Next: L12B. |
| 2026-11-14 | L12B merged (PR #40, `8f81454`): proposal deadline line and last-hour countdown, expired state with next step, reminder and trip-fit alert in the bell, push and live updates, parcel preview for the named trip. Next: L13A. |
| 2026-11-14 | Advisor answer for L13A, written into plan L13A and L13B: on the trip reviews endpoint the listings switch closes only the public path; the owner, a viewer with a shared match, and a Find Travelers viewer (who passes `?request=<id>`, checked with `explain_candidate`) still read the reviews, so no rating becomes a dead tap. |
