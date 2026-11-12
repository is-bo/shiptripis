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
| L4A | Traveler pricing, backend | Opus | high | not_started | | | | |
| L4B | Traveler pricing, mobile | Sonnet | medium | not_started | | | | |
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
| L10 | Final acceptance | Opus | high | not_started | | | | |

**Next package:** L4A (Opus, high effort). It depends only on L3A, which is merged. L5A and L6A are also unblocked; section 3 order puts L4A first, then L4B, which needs L4A and L3B.

**Open carry-over:** remove L3A's backup ferry distances: the seed port coordinates in `apps/locations/data/sea_crossings.json` and the staff-entered kilometres on "Add a crossing", with the `distance_km` parameter of `create_crossing` in `apps.locations.sea_crossings`. They are no longer needed now that every launch-country city has catalogue coordinates (PR #27). Until removed, they only apply to a city without coordinates.

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

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

### L4B. Traveler pricing, mobile

- Contract as built (names that differ from the plan):
- Left for a later package:
- Switches added and their defaults:
- Deviations from the plan (what, why, approved by):
- Tests (before and after counts):
- Known limits:

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

## Change log for the plan and spec

| Date | Change |
| --- | --- |
| 2026-11-10 | Spec and plan first written. |
| 2026-11-11 | Added effort per package, the start runbook (plan 1.0), this progress file (plan 1.8), the agent brief (plan 1.9), the researched sea crossings (spec 5.3.1), Railway removal in L1A, and Ismail's answers. |
| 2026-11-12 | Plan L3B: the staff-paused banner shows no reason, because L3A keeps the staff pause reason internal (the owner's payload carries only `paused_by_staff`). |
