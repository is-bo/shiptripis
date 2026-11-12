# Wassla L-Series Progress

The shared record for every agent working on `feature/discovery-professional-delivery`.
Rules for this file: `docs/WASSLA_DISCOVERY_PRO_PLAN.md` section 1.8. In short:

- **Read this file first**, the board and every handoff block above your package.
- **The board is edited only by the orchestrator**, on the integration branch.
- **Each agent fills in only its own handoff block**, inside its own pull request.
- Statuses: `not_started`, `in_progress`, `in_review`, `changes_requested`, `merged`, `blocked`.

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
| L4B | Traveler pricing, mobile | Sonnet | medium | not_started | | | | |
| L11A | Tracking number, backend | Opus | high | not_started | | | | |
| L11B | Tracking number, mobile | Sonnet | medium | not_started | | | | |
| L5A | Progress updates and reminders, backend | Sonnet | medium | not_started | | | | |
| L5B | Progress updates and reminders, mobile | Sonnet | medium | not_started | | | | |
| L6A | Professional profile, verification, admin inbox, proof skip | Opus | high | not_started | | | | |
| L6B | Professional Mode, mobile | Sonnet | medium | not_started | | | | |
| L7A | Manifest, backend projections | Sonnet | medium | not_started | | | | |
| L7B | Manifest dashboard, mobile | Sonnet | high | not_started | | | | |
| L8A | Custody, courier handoff, recipient confirmation | Opus | xhigh | not_started | | | | |
| L8B | Custody and handoff, mobile | Sonnet | high | not_started | | | | |
| L9A | Problems and route changes, backend | Opus | high | not_started | | | | |
| L9B | Problems and route changes, mobile | Sonnet | medium | not_started | | | | |
| L12A | Proposal deadline and trip-fit alerts, backend | Opus | high | not_started | | | | |
| L12B | Proposal deadline and trip-fit alerts, mobile | Sonnet | medium | not_started | | | | |
| L13A | Reviews, reports and moderation, backend | Opus | high | not_started | | | | |
| L13B | Reviews, mobile | Sonnet | medium | not_started | | | | |
| L14 | Staff two-step sign-in and finance exports | Opus | high | not_started | | | | |
| L15 | AI helper: keys and read access | Opus | xhigh | not_started | | | | |
| L16 | AI helper: changes | Opus | xhigh | not_started | | | | |
| L17 | AI helper skill | Sonnet | medium | not_started | | | | |
| L10 | Final acceptance (runs last, after L17) | Opus | high | not_started | | | | |

**Added 2026-11-12 (approved by Ismail):** L11A to L17 above, and the no-show reports inside L9A and
L9B (spec 12, 16 to 20; plan 5.1b), then L4C and the new order (plan 5.1d). **The order of this
table is the order of work, as in plan section 3:** L4C, L4B, L11A, L11B, then L5A to L9B, then L12A
to L17, and L10 last. These rows were added and ordered by the plan thread on Ismail's instruction;
the board is otherwise still edited only by the orchestrator.

**Next package:** L4B (Sonnet, medium effort), then L11A (Opus, high), then L11B (Sonnet, medium). Section 3 order.

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

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L5B. Progress updates and reminders, mobile

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L6A. Professional profile, verification, admin inbox, proof skip

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L6B. Professional Mode, mobile

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L7A. Manifest, backend projections

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L7B. Manifest dashboard, mobile

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L8A. Custody, courier handoff, recipient confirmation

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L8B. Custody and handoff, mobile

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L9A. Problems and route changes, backend

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L9B. Problems and route changes, mobile

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L11A. Tracking number, backend

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L11B. Tracking number, mobile

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L12A. Proposal deadline and trip-fit alerts, backend

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L12B. Proposal deadline and trip-fit alerts, mobile

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

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

## Change log for the plan and spec

| Date | Change |
| --- | --- |
| 2026-11-10 | Spec and plan first written. |
| 2026-11-11 | Added effort per package, the start runbook (plan 1.0), this progress file (plan 1.8), the agent brief (plan 1.9), the researched sea crossings (spec 5.3.1), Railway removal in L1A, and Ismail's answers. |
| 2026-11-12 | Plan L3B: the staff-paused banner shows no reason, because L3A keeps the staff pause reason internal (the owner's payload carries only `paused_by_staff`). |
| 2026-11-12 | Added packages L11A to L17 and the no-show reports in L9A and L9B (spec 12 and 16 to 20; plan 2.10 to 2.12, section 3, 5.1b, 5.1c). L10 stays the last package and gains their acceptance checks. Correction recorded in plan 5.1b: proposals had no expiry at the baseline; L12A adds it. |
| 2026-11-12 | Skill drafted early at Ismail's request: `docs/admin-helper-skill/` (`/wassla` plus the pasted line; briefing by default; how-to answers). Spec 20.5 and 20.7 updated; L15 gained `GET tasks` and the one-line copy block; L17 now verifies and proves the draft instead of writing it. |
| 2026-11-12 | Before the unattended run (plan 5.1d): added L4C (CI time limit, ferry distance cleanup) to run first; moved L11A and L11B to right after L4B and added rule 1.5.12; added the advisor role (1.1) and "When a package is blocked" (1.0); gate screenshots are kept in `/mnt/project-files/l-series-screens/` and L10 builds a gallery (1.6). |
