# Wassla Discovery and Professional Delivery Implementation Plan

Written 2026-11-10, updated 2026-11-11 and 2026-11-12 (packages L4C and L11A to L17 added, order in
section 3) and 2026-11-13 (scope narrowed to fast delivery: professional transporters and courier
handoff parked, see 5.1e), for the orchestrator (the project coordinator). Product rules:
`docs/WASSLA_DISCOVERY_PRO_SPEC.md` ("the spec"). Live status: `docs/WASSLA_L_SERIES_PROGRESS.md`
("the progress file").
Baseline: `feature/wassla-v3-baseline` at `dd7f820`. Integration branch:
`feature/discovery-professional-delivery`.

The spec says **what**. This plan says **how, in what order, by whom, and what proves it is done**.
If the plan and the spec disagree, the spec wins and the disagreement is a plan bug to report.

**Scope since 2026-11-13.** Wassla is for fast delivery: urgent parcels, mostly on flights and drives
made the same day. Packages L6B, L7A, L7B, L8A and L8B and the professional half of L6A are
**parked**: their full text is in `docs/parked/WASSLA_PROFESSIONAL_AND_COURIER_PLAN.md`. They are not
started, and no package leaves a hook for them. What remains, in order: L6A (smaller), L9A, L9B,
L12A, L12B, L13A, L13B, L14, L15, L16, L17, L10.

---

## 1. How to run this plan

### 1.0 When Ismail says "start"

The coordinator does exactly this, with no further questions:

1. Read `CLAUDE.md`, the spec, sections 1 to 3 of this plan, and the progress file.
2. In the progress file, find the package to work on:
   - a package that is `in_progress`, `in_review` or `changes_requested` is resumed first;
   - then a `blocked` package whose question has been answered;
   - otherwise take the first `not_started` package in the order of section 3 whose "Depends on"
     packages are all `merged`.
   A package that is still `blocked` is passed over, never forgotten: see "When a package is blocked"
   below.
3. Mark it `in_progress` in the progress file on the integration branch (1.8).
4. Start **one thread** for that package, with the **model and effort from section 3**, and give it the
   brief in 1.9 unchanged except for the package id.
5. When the agent opens its pull request, mark the package `in_review` and run the gate review (1.6).
6. If the gate fails, mark it `changes_requested` and send the findings back to the same thread.
7. If the gate passes and CI is green, merge the pull request into
   `feature/discovery-professional-delivery`, mark the package `merged` with the merge commit, and
   tell Ismail in one line what was merged.
8. Repeat from step 2 until L10 is `merged`, then stop and hand Ismail the release report.

One package at a time. **Never merge into `main` and never deploy**; both need Ismail's explicit
approval, given after L10.

**When a package is blocked** (decided by Ismail on 2026-11-12: one question must not stop the whole
build, and he is not watching it).
- A question about what the spec or this plan means, or a judgment call between two ways of building
  the same rule, goes to **the advisor** (the plan thread, 1.1). Its answer is recorded in the
  progress file and the package continues. This is the normal path and it does not block.
- Only what the advisor says it cannot settle, because it would change a product decision, a money
  rule or the scope Ismail approved, waits for Ismail. The coordinator then marks the package
  `blocked`, writes the question in "Questions for Ismail" with what each answer would lead to, and
  **goes on with the next `not_started` package in section 3 order whose dependencies are all
  `merged`**.
- A package that depends on a blocked one waits with it. Nothing is built on a guess to keep moving.
- When Ismail answers, the blocked package is resumed before any new package starts.
- If nothing can run because everything left depends on a blocked package, stop and tell Ismail in
  one message what is waiting on him.

### 1.1 Roles

- **Orchestrator:** the project coordinator. Hands one work package at a time to an agent, reviews the result against the
  package's "Done when" list, and merges it into the integration branch. Never merges into `main`.
  Never deploys. Both need Ismail's explicit approval.
- **Advisor:** the plan thread that wrote the spec and this plan. The coordinator and, through it, the
  agents bring it problems, spec or plan questions and judgment calls. It answers, and corrects the
  plan or spec in a docs-only commit when they are wrong or silent. It starts no package and merges
  nothing. Ismail's rule: ask the advisor rather than him.
- **Agent:** implements exactly one work package. Reads, in this order: `CLAUDE.md`, the progress file
  (the board and every earlier package's handoff notes), the spec, sections 1 and 2 of this plan, its
  own package, and the code the package names. Nothing else is in scope.
- **Ownership note.** `CLAUDE.md` and `AGENTS.md` name Codex as the backend owner. For this L-series
  Ismail assigned the work to Claude agents through the orchestrator, backend included. That
  instruction is the owner override both files allow.

### 1.2 Models and effort

Ismail's rule: quality first, save usage where possible. **Opus** for any package that touches
matching, money or codes. **Sonnet** for the rest. Every package also has a reasoning **effort**:

- **xhigh:** the package where a mistake corrupts matching (L3A), and the two that open a new door
  into staff authority (L15, L16).
- **high:** every other Opus package, and the Sonnet packages that carry the most user-facing design
  (L2B, L3B).
- **medium:** the remaining Sonnet packages, which follow an existing pattern closely.

Nothing in this series runs at low effort, and nothing needs max. The gate review (1.6) runs on Opus
at high effort for every package; the second review pass on Opus packages also runs at high.
Section 3 lists the model and effort for each package, and each package heading repeats them. They
are not to be lowered to save usage. If a Sonnet package
turns out to need a change in `apps/matching`, `apps/finance`, `apps/handover`, `apps/deals/lifecycle.py`
or `apps/deals/cancellation.py`, the agent stops and the orchestrator re-issues that part to Opus.
Two things are not such a change and are allowed in a Sonnet package where the package says so:
adding a new `ScheduledJob` kind and registering its handler (the handler itself lives in the
package's own app), and reading existing finance or deal rows without writing them.

### 1.3 Branches and CI

- One branch per package, from the current tip of the integration branch:
  `l/<package id>-<short name>`, for example `l/l3a-routes-backend`. Agent sessions get a branch
  name fixed by their harness (`claude/project-thread-...`) and cannot follow this naming; that is
  fine, because what matters is the pull request's base branch.
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
3. **Beside the machine.** Progress, problems and route changes never write `Deal.status` and never
   call a lifecycle transition. There is no exception in this build.
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
11. **Status files.** Each package adds a short dated entry at the top of `docs/IMPLEMENTATION_STATUS.md`,
    writes `docs/PHASE_<id>_<NAME>.md` with what was built, the contract, and the test counts, and
    fills in its own handoff block in the progress file (1.8).
12. **Tracking number.** From L11A on, every new payload, email, web page and screen that refers to a
    parcel shows its tracking number, read through `apps/parcels/tracking.py` (2.10) on the server and
    shown with L11B's shared widget in the app. No package prints a delivery id as a reference, and
    no public discovery payload carries the number.

### 1.6 Gate review

Before merging a package the orchestrator checks, and records in the pull request:

- every line of the package's "Done when" list, with the evidence;
- the diff contains nothing outside the package's scope;
- for Opus packages: a second, independent review pass focused on races, authorization, idempotency
  and money invariants;
- for mobile packages: screenshots of every new screen in EN and AR, at 360 px wide, with the keyboard
  open where there is a form, in each state the package lists.
- **The screenshots are kept** (Ismail, 2026-11-12, so he can review the look at the end without
  opening pull requests). Every package that adds or changes a screen, mobile or console, saves its
  gate screenshots as PNG files in the shared project folder
  `/mnt/project-files/l-series-screens/<package id>/`, named `<screen>-<state>-<language>.png`, and
  lists the file names in its phase doc. The gate does not pass without them. If a session cannot
  reach that folder, the agent attaches them to the pull request and says so in its handoff notes,
  and the coordinator copies them across. L10 assembles them into one gallery.

### 1.7 When to stop and ask

Stop and report, without guessing, when: a spec rule cannot be implemented as written; a change would
alter a money, code or matching result for an existing deal; a migration would need to drop or rewrite
data; an existing test encodes behaviour the spec does not mention.

The agent reports to the coordinator, the coordinator takes it to the advisor, and only what the
advisor cannot settle waits for Ismail (1.0, "When a package is blocked").

### 1.8 The progress file: how agents coordinate

`docs/WASSLA_L_SERIES_PROGRESS.md` on the integration branch is the single shared record. Every agent
reads it before anything else, so no agent depends on another agent's conversation.

- **The board** (one row per package: status, model, effort, branch, pull request, merge commit, phase
  doc) is edited **only by the orchestrator**, directly on the integration branch, in small docs-only
  commits. Statuses: `not_started`, `in_progress`, `in_review`, `changes_requested`, `merged`,
  `blocked`, and `parked` (not part of this build; never picked up by 1.0).
- **Handoff notes** (one block per package) are written **by that package's agent, inside its own pull
  request**, and merge with it. They hold what the next agent cannot learn from the plan: the final
  names of endpoints, fields, error codes and channels where they differ from this plan; anything
  deliberately left for a later package; new switches and their defaults; test counts before and
  after; known limits.
- An agent edits only its own handoff block. It never edits the board or another package's block, so
  two pull requests never conflict in this file.
- **Deviations.** If an agent had to deviate from this plan, the handoff notes say what, why, and who
  approved it. A deviation from the **spec** is never made by an agent; it is a stop-and-ask (1.7).
- **Questions for Ismail** are listed at the bottom of the file by the orchestrator, with the date
  asked and, later, the answer.
- The plan and the spec are not rewritten as work proceeds. If a later package's instructions are
  made wrong by an earlier package's outcome, the orchestrator corrects the plan in a docs-only
  commit and records it in the file's change log.

### 1.9 The brief the orchestrator gives each agent

```
You are implementing package <ID> of the Wassla L-series in the repository is-bo/shiptripis.

1. Check out feature/discovery-professional-delivery and create the branch l/<id>-<short-name> from it.
2. Read, in this order: CLAUDE.md; docs/WASSLA_L_SERIES_PROGRESS.md (the board and all earlier
   handoff notes); docs/WASSLA_DISCOVERY_PRO_SPEC.md; sections 1 and 2 of
   docs/WASSLA_DISCOVERY_PRO_PLAN.md; then the section for package <ID>.
3. Implement package <ID> and nothing else. The spec is authoritative. Follow every rule in plan
   section 1.5. Stop and report instead of guessing in the cases of plan section 1.7.
4. Run every check in plan section 1.4 that applies. The whole suites must pass.
5. Write docs/PHASE_<ID>_<NAME>.md, add the entry to docs/IMPLEMENTATION_STATUS.md, and fill in your
   own handoff block in docs/WASSLA_L_SERIES_PROGRESS.md. Do not edit the board.
6. Open one pull request into feature/discovery-professional-delivery. In its description list each
   line of the package's "Done when" with the evidence. Never push to main. Never deploy.
```

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
  "traveler_pricing":{"enabled": true, "max_price_per_kg_eur_cents": 10000,
                      "max_min_price_eur_cents": 50000},
  "reminders":       {"enabled": true, "depart_after_minutes": 30, "arrive_after_minutes": 60,
                      "repeat_after_minutes": 180, "max_repeats": 2},
  "route_change":    {"material_shift_minutes": 360}
}
```

As merged in L2A the reader also carries two sections, `courier_handoff` and `professional`, that
nothing reads. Their features were parked on 2026-11-13, so **L6A removes both** (1.5 rule 10).

Added on 2026-11-12, by the package named: L12A adds `"offers": {"response_deadline_enabled": true,
"response_hours": 6, "reminder_before_hours": 1}` (6 and 1 since 2026-11-13) and, inside `discovery`,
`"trip_fit_alerts_enabled": true, "trip_fit_max_travelers": 30, "trip_fit_daily_cap": 5`. The AI
helper has its own top-level policy section, `admin_helper`, defined in L15.

- A settings row with no `marketplace` section is valid and means the defaults above, so no existing
  row needs rewriting. Unknown keys are refused when a revision is saved.
- The defaults are the spec's: sea legs ship **off**; everything else ships on.
- `marketplace_policy()` returns a frozen dataclass. Every switch check goes through it.
- The admin Settings page gets one form, "Marketplace features", saved through the existing
  `_save_settings_revision(..., path_updates=..., reason=...)` with permission `manage_settings`.
- The app learns switch states from the endpoints that need them, never from a global flags endpoint.

### 2.2 One function for ticket proof

New module `backend/monolith/apps/trips/proofs.py`:

- `PROOF_REQUIRED_MODES = frozenset({FLIGHT, SEA})`
- `leg_requires_proof(leg) -> bool`
- `leg_proof_satisfied(leg) -> bool`
- `journey_proof_gaps(legs) -> list[leg]`

(As built in L3A. Nobody is exempt: spec 6.)

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

Parked on 2026-11-13 (see `docs/parked/WASSLA_PROFESSIONAL_AND_COURIER_PLAN.md`). No such notion
exists in this build.

### 2.5 Listed price

`apps/matching/listed_price.py::listed_reward(journey, pricing_quote) -> ListedPrice | None`. Returns
`None` when the journey has no price or the switch is off. Otherwise
`max(ceil(price_per_kg_eur_cents * chargeable_weight_kg), min_price_eur_cents, minimum_reward_eur_cents)`.
Fee and sender total come from `calculate_offer_economics`. Nothing else computes a listed price.

### 2.6 Problems are their own app

New Django app `apps.problems` owns problem reports (L9A). It may read deals and call
`deals.lifecycle.record_event` for the timeline. It may not write a deal. (This section used to
describe `apps.custody`, which was parked on 2026-11-13 with courier handoff.)

### 2.7 Durable timers

Reminders and proposal deadlines use the existing `finance.ScheduledJob` through
`finance.services.schedule_job`, with new kinds and handlers registered in `apps/finance/jobs.py`
`HANDLERS`. Each handler re-reads state and does nothing if the work is no longer needed.

### 2.8 Pages for people without an account

Parked on 2026-11-13 with courier handoff (the courier page and the recipient page). This build adds
no page for people without an account.

### 2.9 Names

- Phase ids are the L series. "V1", "V2", "V3" already mean other things in this repository.
- The Redis channel `flight_proof.status_changed` becomes `leg_proof.status_changed` in L3A. The app
  keeps rendering old inbox rows that carry the old name.
- Admin permission codes `view_flight_proofs` and `review_flight_proofs` keep their codes (they are
  stored in role rows) and are relabelled "Ticket proofs".
- In this plan "agent" means the Claude agent that implements a package. The assistant an admin
  connects in L15 to L17 is always called "the helper" or "the assistant", in code and in copy
  (`apps.admin_helper`), so the two are never confused.

### 2.10 Tracking number

`apps/parcels/tracking.py` is the only place that creates, formats or parses a tracking number (spec
16). The column is `ParcelRequest.tracking_number`. Every surface reads a parcel's number through
`for_request` or `for_deal`. From L11A on, a package that shows or logs a reference for a parcel uses
it; `ST-<id>` and the context key `deal_reference` are gone.

### 2.11 What the AI helper may carry

One rule for every payload of `apps.admin_helper` (spec 20.3), enforced by allowlist serializers and
by the privacy walk in L15:

- **A person**, wherever one is named inside another payload, is
  `{"id", "display": "<first name> <last initial>.", "console_url"}` and nothing else. The `person`
  record itself (`records/person/<id>`) adds only: the account state (active, banned, deactivated),
  "member since" as month and year, and activity counts. Its field list is frozen by a test (advisor,
  2026-11-14, on L15's question).
- **Never present, under any key:** a file, a file name, a storage key or a signed address; a document
  number; a date of birth; an email; a phone; a street address or coordinates; payout, bank or card
  data; a pickup or delivery code; a key, token, secret or password; a chat message; a guest payer's
  email.
- **User-written text** appears only on `records/<type>/<id>`, under the key `untrusted_user_text`
  (an object of field name to text, each cut to 500 characters). No other key may hold it.
- **Document reviews** (identity, ticket, payout method, payout identity) are a count and a console
  link. They have no record type.
- **Authority** is the admin's own, read fresh on every call, through the permission code of the
  console page the payload mirrors. A helper key opens only `/api/admin/helper/`.

### 2.12 Staff second step

`apps.admin_panel.two_step.two_step_satisfied(request)` is the only answer to "has this staff session
passed the second step", and `fresh_two_step(request, minutes=10)` the only answer to "recently". From
L14 on, every staff surface (console, technical admin, `/api/admin/`) is behind the first, and the
steps named in spec 19.1 are behind the second.

---

## 3. Work packages

| # | Package | Model | Effort | Depends on |
| --- | --- | --- | --- | --- |
| L0 | Spec and plan (this commit) | done |  |  |
| L1A | Backend cleanup | Opus | high | L0 |
| L1B | Mobile and docs cleanup | Sonnet | medium | L1A |
| L2A | Discovery backend and marketplace policy | Opus | high | L1A |
| L2B | Discovery on Home (mobile) | Sonnet | high | L2A, L1B |
| L3A | Routes for everyone, backend: sea, ticket proof, stops, capacity, pause | Opus | xhigh | L2A |
| L3B | Routes for everyone, mobile and admin screens | Sonnet | high | L3A |
| L4A | Traveler pricing, backend | Opus | high | L3A |
| L4C | Housekeeping: test time limit and ferry distance cleanup | Opus | high | L4A |
| L4B | Traveler pricing, mobile | Sonnet | medium | L4A, L3B, L4C |
| L11A | Tracking number, backend | Opus | high | L4C |
| L11B | Tracking number, mobile | Sonnet | medium | L11A, L4B |
| L5A | Progress updates and reminders, backend | Sonnet | medium | L3A |
| L5B | Progress updates and reminders, mobile | Sonnet | medium | L5A, L3B |
| L6A | Verification inbox (ID and Tickets) and removal of the parked switches (backend and console) | Opus | high | L3A |
| L9A | Problems and route changes, backend | Opus | high | L5A, L6A |
| L9B | Problems and route changes, mobile | Sonnet | medium | L9A, L5B |
| L12A | Proposal deadline and trip-fit alerts, backend | Opus | high | L9A, L11A |
| L12B | Proposal deadline and trip-fit alerts, mobile | Sonnet | medium | L12A, L9B, L11B |
| L13A | Reviews, reports and moderation, backend | Opus | high | L12A |
| L13B | Reviews, mobile | Sonnet | medium | L13A, L12B |
| L14 | Staff two-step sign-in and finance exports (backend and console) | Opus | high | L13A |
| L15 | AI helper: keys and read access (backend and console) | Opus | xhigh | L14 |
| L16 | AI helper: changes (backend and console) | Opus | xhigh | L15 |
| L17 | AI helper skill | Sonnet | medium | L16, L13B |
| L10 | Final acceptance | Opus | high | all, L17 included |

L11A to L17 were added on 2026-11-12 (spec 16 to 20). **The order of this table is the order of
work, not the numbers.** Everything down to L5B is merged. What remains, in order: **L6A, L9A, L9B,
L12A, L12B, L13A, L13B, L14, L15, L16, L17, and L10 last.** The no-show reports of spec 12 are inside
L9A and L9B.

**Parked on 2026-11-13** (Ismail, 5.1e), not in this table and not to be started: L6B, L7A, L7B, L8A,
L8B and the professional half of L6A. Their rows, models, effort and full text are in
`docs/parked/WASSLA_PROFESSIONAL_AND_COURIER_PLAN.md`. The numbers L6B, L7 and L8 are not reused.

Why some packages are Opus although they look small (rule 1.2): L6A changes the ticket and ID
decisions that open or close matching for a journey, and the policy reader matching depends on;
L11A edits reference strings inside `apps/finance`, `apps/handover` and `apps/deals/cancellation.py`; L12A changes offers and calls
the matching engine; L13A changes `trust_signals`, which feeds ranking; L14, L15 and L16 are staff
authority.

---

## 4. Packages in detail

### L1A. Backend cleanup (Opus, high effort)

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
| Railway deployment | root `railway.json`, `backend/railway/`, `backend/gateway/railway.json`, `backend/monolith/railway.web.json`, `backend/monolith/railway.grpc.json`, `backend/services/railway.json`, `backend/services/railway-entrypoint.sh`, and Railway-only branches in settings, config, Dockerfiles, CI and tests | **Ismail decided on 2026-11-11: Railway does not stay on this branch.** See "Railway removal" below |

**Railway removal.** Hosting is the VPS (`infra/vps/`). Remove the Railway deployment files listed
above and every code path that exists only for Railway: settings and config branches keyed on Railway
environment variables, Railway-only Docker stages and entrypoints, Railway references in CI, and tests
that assert Railway behaviour. Rules: the VPS path must be the one that remains and must keep working,
proven by the VPS unit tests, the `vps-readiness` workflow and the production-safety CI job; an
environment variable the VPS also uses keeps its name even if it was introduced for Railway; a setting
whose only reader was Railway is deleted, not left unused; `docs/` runbooks that describe Railway as
the current host are corrected, while dated historical phase reports are left as written. Anything
where it is unclear whether the VPS still depends on it goes to "kept, needs decision" with the
evidence. This overrides the V1 specification's note that Railway resources remain.

**Also in scope.** Django admin registrations, tests, fixtures and settings that exist only for removed
surfaces. `ARCHITECTURE.md`: correct what is false at the baseline.

**Done when.**
- The inventory file exists and every removed item has its evidence.
- `git grep` shows no reference to a removed symbol.
- `makemigrations --check` is clean and no migration file was added or deleted.
- The whole Django, Go and Flutter suites pass. Test counts before and after are in the phase doc, and
  every removed test is listed with the surface it covered.
- A request to each removed route returns 404, or 410 for the tombstones.
- No Railway file or Railway-only code path remains (`git grep -i railway` shows only dated historical
  reports and the cleanup inventory), and the VPS unit tests, `vps-readiness` and the
  production-safety job pass.

### L1B. Mobile and docs cleanup (Sonnet, medium effort)

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

### L2A. Discovery backend and marketplace policy (Opus, high effort)

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

### L2B. Discovery on Home (Sonnet, high effort)

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

### L3A. Routes for everyone, backend (Opus, xhigh effort)

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
- `python manage.py seed_sea_crossings --file tools/geography/sea_crossings.json`. Idempotent. The
  file holds exactly the crossings of spec 5.3.1, both directions, each with its `active` flag: the
  twelve listed crossings active, the seven others inactive. A pair is created only when both names
  resolve to exactly one catalogue locality; anything else is reported and skipped, never guessed.
  Re-running the command never re-activates a crossing staff deactivated.
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

### L3B. Routes for everyone, mobile and admin screens (Sonnet, high effort)

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
- Journey detail: pause and resume, the paused banner, and the staff-paused banner, which tells the
  traveler to contact support (L3A keeps the staff reason internal; the payload has `paused_by_staff`).
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

### L4A. Traveler pricing, backend (Opus, high effort)

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

### L4C. Housekeeping: test time limit and ferry distance cleanup (Opus, high effort)

Added on 2026-11-12 from two carry-overs on the board. It runs **first**, before L4B, because the
first item blocks merges. Opus because the second item sits next to pricing (1.2).

**1. The Django CI job must not run out of time.** It takes 33 to 44 minutes against
`timeout-minutes: 45` in `.github/workflows/ci.yml`, and grows with every package.
- Preferred: split the Django test job into parallel shards (a matrix over `pytest` groups or
  `pytest-split`, each shard with its own PostgreSQL service), keeping every other step and every
  required check name that branch protection or the gate relies on. All shards must pass; none is
  optional. The whole suite still runs on every pull request.
- If sharding cannot be done without weakening anything, raise the limit to 90 minutes instead and say
  why in the handoff notes.
- No test is skipped, deleted, marked slow or moved out of the pull-request run to gain time.
- Record the before and after durations. Target: the slowest shard, or the single job, finishes with
  at least 40% of its limit unused.

**2. Remove L3A's backup ferry distances.** The seed port coordinates in
`apps/locations/data/sea_crossings.json`, the staff-entered kilometres on "Add a crossing"
(`console_sea.py` and its form and template), and the `distance_km` parameter of `create_crossing` in
`apps/locations/sea_crossings.py`, with whatever only they used. Every launch-country city has
catalogue coordinates since pull request #27, so the fallback is dead.
- Before removing, prove it is dead: a test over every seeded crossing shows both ends resolve to
  catalogue coordinates.
- A sea leg's distance, price quote and match result must be identical before and after for every
  seeded crossing; a test pins them. If any differs, stop (1.7) and report instead of adjusting.
- Additive-only still holds (1.5 rule 5): a stored column is left in place and no longer written or
  read; say so in the handoff notes.

**Done when.** Two consecutive CI runs on the pull request are green with the headroom above; the
ferry tests pass; `docs/PHASE_L4C_HOUSEKEEPING.md` records the durations and what was removed.

### L4B. Traveler pricing, mobile (Sonnet, medium effort)

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

### L11A. Tracking number, backend (Opus, high effort)

Opus because the reference strings live in `apps/finance`, `apps/handover`, `apps/deals/cancellation.py`
and `apps/disputes` (1.2). No amount, code or state changes in this package; if one seems needed, stop.

It runs right after L4B (moved forward on 2026-11-12), so that every later package uses the tracking
number from its first line instead of being reworked afterwards (1.5 rule 12).

**Goal.** Spec 16. One number per parcel, created with the request, shown by every server surface
that today shows `ST-<id>`, and searchable by staff.

**Schema.** `parcels.ParcelRequest.tracking_number`: `CharField(max_length=12)`, unique. Added in the
three steps Django documents for a unique column with a generated value: add it nullable, fill every
existing row in a data migration, then make it non-null and unique. This is the one place in the
series where a new column is tightened after it is filled; it is still additive (1.5 rule 5).
`ParcelRequest.save` refuses a change to a saved row's number.

**One module.** `apps/parcels/tracking.py` (2.10): `ALPHABET`, `generate()`, `normalize(text) ->
str | None`, `for_request(request)`, `for_deal(deal)`. Creation retries on a unique collision, at most
five times, then raises. Nothing else builds, parses or formats a tracking number.

**Where it appears.**
- API payloads, as `tracking_number`: the owner's request payloads; proposal and match payloads between
  the two people of a proposal; deal payloads for both parties; the owner's payment order payloads;
  the traveler's payout payloads; dispute payloads. Packages after this one add it to their own new
  payloads (1.5 rule 12).
- Not in: the five public discovery payloads of L2A, Find Travelers candidates, the compatible-requests
  list before a proposal exists, and the guest payment view and page. The existing privacy tests gain
  `tracking_number` and the pattern `WSL-` as forbidden.
- Emails and notifications: every context that carries `deal_reference` carries `tracking_number`
  instead, read through `for_deal`. Request-stage emails (posting deposit, guest payment receipt for a
  deposit) carry it through `for_request`. The outbox templates and facts are updated in EN, FR and
  AR. The key `deal_reference` and the string `ST-` no longer exist anywhere.
- The delivery-code email to the recipient carries it. (The recipient and courier pages that were
  also to show it are parked.)
- Finance control plane: the search that accepts `ST-<deal>` accepts a tracking number instead
  (`TR-<traveler>` is unchanged); the drill-down shows it.
- Console: the requests, deals, disputes, payments, refunds and payouts lists search by tracking
  number through `normalize` (exact match on the normalised value) and show it in the first column;
  detail pages show it in the heading. The JSON admin lists accept the same search.

**Tests.** Format and alphabet. A forced collision retries and succeeds; five collisions raise. A saved
number cannot change. `normalize` accepts `wsl-7k3m9qxd`, `WSL7K3M9QXD`, `7K3M9QXD` and surrounding
spaces, and refuses a wrong length or a forbidden character. A request that reopens after a cancelled
deal keeps its number and the second deal shows the same one. Each email kind renders the number. The
privacy tests. Console and control-plane search. Query counts of the touched list endpoints unchanged.

**Done when.** `grep -R "ST-" backend/monolith/apps backend/monolith/templates` and
`grep -R "deal_reference"` return nothing outside migrations and this plan's history; the data
migration is proven on a database that already holds requests; the contract is in
`docs/PHASE_L11A_TRACKING_NUMBER.md`.

### L11B. Tracking number, mobile (Sonnet, medium effort)

- Show the number on: the request detail, each proposal, the delivery screen heading (sender and
  traveler), the payment screen, the dispute screen and the traveler's payout line. Later mobile
  packages use the same widget on their own screens (1.5 rule 12). One shared widget in
  `mobile/lib/design`:
  the number in a monospaced style, a copy button with a confirmation, and a semantic label that reads
  it character by character.
- Always left to right, isolated, inside Arabic text (the pattern used for the guest link preview).
- The number is display only: no screen, deep link or search opens a parcel from a typed number.
- It never appears on a discovery card, a browse list, Find Travelers or a public preview.
- Remove every place that printed a delivery id as a reference.
- Tests: the widget in EN, FR and AR at 360 px; copy; the screens above with and without a number in a
  cached older payload (render nothing, not a placeholder); zero untranslated keys.

### L5A. Progress updates and reminders, backend (Sonnet, medium effort)

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

### L5B. Progress updates and reminders, mobile (Sonnet, medium effort)

- Journey detail: a "Trip progress" stepper, one step per leg, with one large button for the next
  action and an undo for 10 minutes.
- Home, in "needs attention": "Did you depart from {city}?" with "Yes, departed" and "Not yet".
- The reminder notification opens the same question as a sheet. The bell inbox lists it.
- Sender's deal screen: progress lines in the timeline, each marked "reported by the traveler".
- States, RTL, and an offline rule: a report needs the network; the button says so instead of queuing.

### L6A. Verification inbox and removal of the parked switches (Opus, high effort)

Backend and console only. There is no mobile half. Until 2026-11-13 this package also built
professional profiles and the ticket exemption; that half is parked
(`docs/parked/WASSLA_PROFESSIONAL_AND_COURIER_PLAN.md`) and nothing here prepares for it.

**Goal.** Spec 13: one verification inbox for staff with two tabs, ID and Tickets, and one review
screen with three decisions. And remove the two policy sections that the parked features left behind.

**Inbox.**
- One "Verification" entry in the console navigation, with the total number waiting across both
  tabs. It replaces the two entries "KYC review" and "Ticket proofs". "Payout identity checks" stays a
  separate entry: it is a step of dinar payout approval, not part of spec 13's inbox.
- Two tabs with counters under one shared header: **ID** (the existing KYC queue) and **Tickets** (the
  existing ticket-proof queue, flight and sea). The existing route names (`kyc-queue`, `kyc-detail`,
  `proof-queue`, `proof-detail` and the evidence routes) are kept, so links from person pages, the
  work list and old notifications still land. A staff member who holds only one of `view_kyc` and
  `view_flight_proofs` sees only that tab.
- Opening "Verification" lands on the first tab that has something waiting, otherwise on ID.
- The counters and the navigation total come from the same query functions the queues use; no second
  count exists (1.5 rule 10). The overview's work list keeps one item per tab.

**One review screen.** Both detail pages already render `verification_detail.html`. Make it one
screen in fact: the same header, evidence area, history and decision area for both kinds, with three
decisions: **approve**, **ask for more**, **reject**. A reason is required for the last two.
- "Ask for more" records the existing rejected status with the reason, and marks the audit entry and
  the user's notification `outcome: "resubmission_requested"`, so the user reads "we need a new
  upload" (EN, FR, AR in the push matrix and the email) and can submit again exactly as after a
  rejection today. The KYC status enum, owned by the Go service, is not changed, and no status is
  added to `JourneyLegProof`.
- "Reject" keeps today's behaviour and copy.
- Evidence is still viewed only through the audited staff redirect.

**Removing the parked switches.**
- In `apps/core/marketplace_policy.py`: delete `CourierHandoffPolicy`, `ProfessionalPolicy`, their
  two fields on the policy dataclass, their parsing, `_COURIER_KEYS`, `_PROFESSIONAL_KEYS` and their
  lines in the module docstring ("Sea legs ship off. Everything else ships on."). Update
  `apps/discovery/tests/test_marketplace_policy.py` to match.
- From then on a revision that carries `courier_handoff` or `professional` is refused as an unknown
  key, like any other. Nothing ever wrote them: the "Marketplace features" form has no field for
  either, and there is no production data. Add a test that says so: saving a revision with either key
  is refused.
- `apps/trips/proofs.py`: the module docstring's sentence about L6A adding an exemption is removed.
  The functions are not touched.
- No migration.

**Tests.** The navigation total and each tab's counter equal the queue's own count, for each staff
role. Tab visibility by permission. Landing tab. Each of the three decisions for both kinds: the
status written, the audit row (with `outcome` on "ask for more"), the notification and its copy in
three languages, the reason required. A user can resubmit after "ask for more". An approved ticket
still makes its leg matchable and a rejected one still does not (the existing proof tests, unchanged
and green). The policy tests above. Fixed query count for the inbox header.

**Done when.** `docs/PHASE_L6A_VERIFICATION_INBOX.md` holds the contract; a search of
`backend/` and `mobile/` (code, not docs) for `professional` and for `courier_handoff` finds nothing;
the console screenshots of both tabs and the review screen, EN, are saved (1.6);
`docs/ADMIN_OPERATIONS.md` describes the inbox for staff.

### L6B, L7A, L7B, L8A, L8B. Parked

Professional Mode in the app, the manifest (backend and app), and custody with courier handoff
(backend and app). **Parked by Ismail on 2026-11-13. Not in this build.** Full text, with models and
effort: `docs/parked/WASSLA_PROFESSIONAL_AND_COURIER_PLAN.md`.

### L9A. Problems and route changes, backend (Opus, high effort)

**Problems.** New app `apps.problems` (2.6). `problems.ShipmentProblem(deal, reported_by, kind,
note, status: open|acknowledged|escalated|closed, closed_by, closed_reason)`. `POST` and
`GET /api/deals/<id>/problems`. Kinds, as spec 12: `sender_unavailable`, `traveler_no_show`,
`recipient_unavailable`, `parcel_mismatch`, `parcel_damaged`, `trip_disrupted` (the trip was
cancelled or delayed: a flight, a drive or a crossing), `customs_delay`, `other`. There is no courier
kind in this build. `parcel_damaged` and `parcel_mismatch` escalate to staff at once, as do the two
no-show kinds below. The other party is notified on `deal.problem_reported`. Every payload and
notification names the parcel by its tracking number (1.5 rule 12). A problem changes nothing on the
deal; the existing dispute and cancellation actions remain the only paths with money consequences.
Staff queue with acknowledge and close, each with a reason.

**No-show reports** (spec 12, added 2026-11-12). Two of the kinds are no-show reports:
`sender_unavailable` reported by the traveler and the new kind `traveler_no_show` reported by the
sender.
- Accepted only when the deal is funded, `agreed_pickup_at` is set and has passed, and
  `pickup_confirmed_at` is empty; otherwise `no_show_report_not_allowed` with the reason. The reporter
  must be the party the kind names (`problem_kind_not_allowed_for_role`). One open no-show report per
  reporter per deal.
- Both kinds escalate to staff at once and notify the other party on `deal.problem_reported`.
- The staff problem queue shows, on a no-show report, a "Record a no-show" link that opens the
  **existing** admin no-show action for that deal with the party pre-selected (permission
  `record_no_show`). The report itself never calls `record_no_show`, writes no `Deal.no_show_*` field,
  and refunds nothing. Recording the no-show closes the report with a reference to the audit row.
- `GET /api/deals/<id>/problems` returns, for the caller, `can_report_no_show` and the reason when it
  is false, so the app never guesses the window.
- Tests: the window at each boundary; role and kind; the duplicate; a deal row byte-identical before
  and after a report; the staff link carries the deal and the party and nothing else; closing on
  record.

**Schedule changes.** Times only. Adding or removing stops on an active journey is not part of this
build.
- `trips.JourneyScheduleChange(journey, status: pending_senders|applied|withdrawn, original, proposed,
  reason)` and `JourneyScheduleChangeConsent(change, deal, state: pending|accepted|declined)`.
- `POST /api/journeys/<id>/schedule-changes` by the owner with new leg times. The server validates the
  sequence with the existing leg-sequence rules, finds the affected funded deals, and classifies each:
  **material** when the new arrival at its drop-off stop is after the request's deadline or moved by
  more than `route_change.material_shift_minutes`. The details below were settled by the advisor on
  2026-11-13 (5.1e):
  - **Baseline.** "Moved" compares the new time with the one that sender last agreed to: the latest
    applied change they accepted for that deal, else the arrival frozen at funding
    (`arrival_snapshot`), else the one in force. A change that applied at once does not reset it. The
    threshold counts in both directions. The deadline test counts only when the new arrival is later
    than the baseline.
  - **Pickup side**, for a deal whose pickup is not confirmed: also material when the time at its
    pickup stop moves by more than the same threshold in either direction (baseline: the accepted
    change, else the `pickup_at` of the match's compatibility snapshot), or when the leg would now
    leave that stop before the deal's `agreed_pickup_at`.
  - **Already collected** (pickup confirmed, delivery not): no consent row. The deal is listed on the
    change as `informed`, its sender is notified with the old and new times and the server-authored
    actions that exist today (report a problem, open a dispute), and it never holds the change back.
    A pending or declined consent whose deal is then picked up stops blocking in the same way.
  - **Ticket proof.** When a change **applies** (not when it is proposed), each flight or sea leg
    whose proven fields changed goes through the existing `_invalidate_leg_proofs` path of
    `apps/trips/services.py`, the one a route edit uses. No second rule. The preview the traveler
    confirms says so ("your ticket will be checked again; until then this trip takes no new
    proposals"), as server text.
  - The default of `material_shift_minutes` stays 360. It is a setting.
  - The reminder re-schedule inside `replace_journey_route` (the `ACTIVE` branch L5A added) is
    unreachable, because only draft and pending journeys are editable. L9A removes it, with a test
    that an active journey's route edit is refused, since the schedule change now owns re-timing.
- No material deal: the change applies at once and affected senders are notified.
- Otherwise it waits. Each affected sender who is asked accepts or declines. It applies when every
  material deal is accepted, no longer active, or already collected. The traveler may withdraw it.
- A sender who declines may cancel through the existing cancellation flow. **The cancellation is
  recorded as caused by the traveler and uses the existing traveler-cancellation outcome; no new
  refund rule is written.** Ismail confirmed this on 2026-11-11.
- `Deal.arrival_snapshot` and `funded_scheduled_arrival_floor_at` are never rewritten. The payout
  floor stays the one agreed at funding.
- Applying a change is recorded with the original schedule and reschedules leg reminders by calling
  `apps.trips.progress.schedule_leg_reminders(journey)` (L5A's carry-over).

**Tests.** Classification at each boundary, including three small changes that together pass the
threshold, the pickup side, and a collected parcel that is informed and never blocks. Apply, wait,
accept, decline, withdraw, and a pickup confirmed while a consent is pending. The ticket of a re-timed
flight leg returns to pending on apply and the trip stops taking proposals. The arrival
snapshot is untouched. Cancellation after a decline produces exactly the amounts the existing
traveler-cancellation path produces. Pending offers are re-validated at acceptance against the new
times. Leg reminders follow the new times.

**Done when.** The contract is in `docs/PHASE_L9A_PROBLEMS_ROUTE_CHANGES.md`; a search for writes to
`Deal.status` and for calls to a lifecycle transition finds none in `apps/problems` or in the
schedule-change code.

### L9B. Problems and route changes, mobile (Sonnet, medium effort)

- "Report a problem" from the deal screen; the problem list on the deal.
- **No-show** (spec 12): when the server says `can_report_no_show`, the deal screen shows one clear
  action above the pickup code area, "The sender did not come" for the traveler and "The traveler did
  not come" for the sender. One tap opens a sheet with an optional note and a line saying what happens
  next ("Wassla staff will look at it. Nothing is cancelled or refunded yet."). After sending, the
  screen shows the report's state and offers chat. The other person sees a banner with "Reply in
  chat" and their own report action. Large targets (spec 14); EN, FR, AR; 360 px.
- Traveler: "Change times" on an active journey, a review step listing the affected parcels and which
  senders must agree, and the pending state.
- Sender: a screen comparing the old and new times with "Accept" and "Decline", and, on decline, the
  cancellation consequence text from the existing cancellation quote endpoint. For a parcel already
  collected the same screen informs only: no "Accept" or "Decline", and the two existing actions the
  server names (report a problem, open a dispute).
- Traveler's review step also shows the server's line about the ticket being checked again.

### L12A. Proposal deadline and trip-fit alerts, backend (Opus, high effort)

**Goal.** Spec 17. A proposal has a deadline with one reminder and a clean expiry, and travelers whose
trip really fits a new request are told once.

**Policy.** The marketplace policy (2.1) gains
`"offers": {"response_deadline_enabled": true, "response_hours": 6, "reminder_before_hours": 1}`
(hours 1 to 168; the reminder strictly smaller than the delay or 0 for none; the defaults were 48 and
12 until 2026-11-13, when Ismail shortened them for urgent delivery) and, inside `discovery`,
`"trip_fit_alerts_enabled": true, "trip_fit_max_travelers": 30, "trip_fit_daily_cap": 5`. The
"Marketplace features" form gains both groups.

**Response deadline.**
- `Offer.expires_at` already exists and is never set. Set it in the two places an offer row is created
  (`create_sender_offer`, `counter_offer` in `apps/matching/v1_services.py`) when the switch is on, to
  **the earlier of** now plus `response_hours` **and the pickup time of this match**: the `pickup_at`
  of the compatibility evaluation those two functions already run before writing the offer (spec
  17.1: a proposal never outlives the pickup it is about). The engine already refuses a pair whose
  pickup time is not in the future, so the deadline is always after now; L12A adds no time rule of its
  own and does not compute a pickup time itself. The deadline is fixed when the offer is written; a
  later schedule change (L9A) does not move it, and acceptance re-validates as it does today. An offer
  without a deadline never expires.
- Two new `ScheduledJob` kinds (2.7), keyed by offer id and the deadline: `offer_response_reminder` at
  the deadline minus `reminder_before_hours` (not scheduled when that moment is not in the future) and
  `offer_expiry` at the deadline. Both are scheduled in the transaction that creates the offer.
- The reminder handler does nothing unless the offer is still pending and its deadline equals the
  payload's. Otherwise it notifies the person who did not write the offer on the new channel
  `offer.response_reminder`.
- The expiry handler takes the same locks, in the same order, as the decline path. If the offer is
  still pending and its deadline has passed it sets `status = expired` and `responded_at`, records the
  existing `MatchEvent.Kind.OFFER_EXPIRED`, leaves the match and the request exactly as a decline
  leaves them, and publishes the existing `offer.updated` with the new status. The push matrix gains
  EN, FR and AR copy for "expired", to both people.
- Accept, counter and decline refuse an offer whose deadline has passed with the stable code
  `offer_expired`, inside the lock, whether or not the job has run.
- Expiry writes no reliability signal and touches no reservation, deal, order or ledger row.
- Offer payloads already carry `expires_at`; they also carry `awaiting: "sender" | "traveler"`.

**Trip-fit alerts.** New module `apps/discovery/trip_fit.py`, called by the existing
`handle_route_alert_fanout` for a request before the route alerts are sent. One job, two audiences.
- It calls `compatible_journeys_for_request` with the existing policy and keeps the eligible
  evaluations in the engine's own ranking order. It does not evaluate, filter or rank by itself.
- It notifies each journey's owner on the new channel `discovery.request_fits_trip`, with the request
  id and journey id only, up to `trip_fit_max_travelers`, skipping a traveler who has reached
  `trip_fit_daily_cap` in the last 24 hours. Push class non-essential, honouring `marketplace_enabled`.
- The event id is derived from the request and the journey, so a replay notifies nobody twice.
- The user ids it notified are passed to the route-alert step, which skips them for this request.
- It re-reads every gate: the switch, the request still listable, the journey still discoverable and
  not paused.
- Both new channels follow 1.5 rule 8.

**Tests.** Deadline set from policy on a proposal and on a counter; the pickup time used instead
when it comes first, on both; no reminder job when the deadline is less than the reminder delay away;
none when the switch is off. The
reminder in each no-op case and the notify case, run twice. Expiry: the row, the event, the match and
request state compared with a decline; byte-identical deal, order and ledger tables. Accept racing
expiry at the same instant: exactly one outcome, proven with two transactions. `offer_expired` on
accept, counter and decline after the deadline with the job not yet run. Fan-out: only compatible
journeys, the cap per request in ranking order, the daily cap, the replay, the skip of route-alert
recipients, the privacy walk on the notification payload, a fixed query count at 1 and at 20 journeys.
The Go channel list test.

**Done when.** The contract is in `docs/PHASE_L12A_PROPOSAL_DEADLINE_TRIP_FIT.md`; with each switch
off the server neither sets a deadline nor sends an alert; no compatibility decision exists outside
`apps/matching`.

### L12B. Proposal deadline and trip-fit alerts, mobile (Sonnet, medium effort)

- Proposal cards and the proposal screen: "Answer by {day, time}" for the person who must answer,
  "Waiting for an answer until {day, time}" for the other. Within the last hour, a calm countdown.
  Times in the device's time zone.
- The expired state: a designed row and screen state with the next step ("Propose to another
  traveler" for the sender, "Browse parcels" for the traveler). The server's `offer_expired` refusal
  shows this state, not an error.
- The reminder notification opens the proposal. The bell inbox lists it.
- The trip-fit notification opens the Request preview (L2B) with the named journey in focus and the
  "I can carry this" action; if the server now says the pair is incompatible or the request is closed,
  the preview states the server's reason.
- No new notification setting: both follow the existing "marketplace activity" and essential classes
  the server assigns.
- Tests: each proposal state in EN and AR at 360 px, RTL, the deep links, the offline state, zero
  untranslated keys.

### L13A. Reviews, reports and moderation, backend (Opus, high effort)

Opus because removing a rating changes `trust_signals` in `apps/matching/find_travelers.py`, which
feeds ranking (1.2).

**Goal.** Spec 18.

**Schema**, in `apps.ratings`. `Rating` itself is not altered and stays immutable.
- `RatingReport(rating, reporter, reason: offensive|personal_information|unrelated|untrue|other,
  note (500), status: open|dismissed|actioned, decided_by, decided_at, decision_reason)`, unique on
  rating and reporter.
- `RatingModeration(rating one to one, state: comment_hidden|removed, decided_by, decided_at,
  reason)`. Lifting a decision deletes this row; the history is the audit log.

**One rule for visibility.** `apps/ratings/public.py`:
- `countable(queryset, at)`: revealed (the existing predicate) and not `removed`.
- `public_reviews(subject_user_id, *, side, at, limit, offset)`: countable ratings, newest first, each
  as `{id, score, tags, comment | null, comment_removed, written_by: "sender" | "traveler",
  month: "YYYY-MM", reported_by_me}`. A hidden comment is `null` with `comment_removed: true`.
- `reviews_visible_to(viewer, subject)`: true when the subject has a visible public profile (L2A), or
  owns a journey that is listable now, or shares a match with the viewer.
- `trust_signals` uses `countable`, so a removed rating leaves the average and count on every card.
  Its query count does not change.

**API.**
- `GET /api/discovery/people/<opaque id>/reviews?limit=&offset=`: both sides, like the profile card.
- `GET /api/discovery/trips/<journey id>/reviews`: the owner's ratings as a traveler, like the trip
  card and Find Travelers.
- `POST /api/ratings/<id>/reports` with `reason` and `note`. The caller must be able to see the
  review, or be its ratee. A second report by the same person answers the first one's state.
- `GET /api/users/me/ratings` marks each row `moderation: null | "comment_hidden" | "removed"`.
- Switched-off profiles answer `state: "disabled"` on the people endpoint, as the other discovery
  endpoints do.
- The trips endpoint (settled by the advisor on 2026-11-14, because Find Travelers shows a rating and
  is not governed by the listings switch): the listings switch closes only the **public** path. The
  owner, and a viewer who shares a match with the owner, always get the reviews. A viewer coming from
  Find Travelers passes `?request=<id>`, their own open request; the server checks the pair with the
  existing `explain_candidate` (the single-pair verdict "I can carry this" uses) and, when the journey
  is a compatible candidate, answers the reviews whatever the switch says. Only a viewer whose sole
  path is the public listing gets `state: "disabled"` when listings are off. Every failure of the
  `request` path (not the viewer's request, not open, not compatible, unknown journey) answers exactly
  what an unknown journey answers, so it reveals nothing about the pair. No compatibility decision is
  made outside `apps/matching`; the query count is fixed with and without the parameter.

**Staff.** New permission `moderate_ratings` for Trust / Verification and Super Admin. Console page
"Reported reviews" (`trust/reviews/`): open reports first, with the review, the delivery link, the
number of reports and their reasons. Actions, each with a required reason and an audit row: dismiss,
hide the comment, remove the rating, lift a decision. Acting on a review closes all its open reports.
The console overview gains the "Reported reviews" item. The reporter's identity is shown to staff only.

**Privacy tests.** The two public payloads walk clean of the author's name, ids, the deal id and every
key forbidden in L2A. A blind rating never appears. A removed rating appears in no public payload and
no average.

**Tests.** Each decision and its reversal; `trust_signals` before and after a removal; the report
uniqueness; who may report; fixed query counts at 1 and 20 reviews; the audit rows.

**Done when.** The contract is in `docs/PHASE_L13A_REVIEWS.md`; no public average or count is computed
outside `countable`.

### L13B. Reviews, mobile (Sonnet, medium effort)

- A "Reviews" screen opened by tapping the rating on the Person page, the Trip preview and a Find
  Travelers candidate (from Find Travelers the app sends the request's id as `request`, see L13A): the average and count from the card, then the list with lazy paging. A removed
  comment shows "Comment removed by Wassla".
- "Report" in each review's menu: a sheet with the five reasons and an optional note, then "Thanks,
  we will review it". A review already reported by the viewer says so and offers nothing more.
- "My ratings": the same report action, and the "Removed by Wassla, not counted" state.
- No review text appears on any card, only on the Reviews screen.
- States (loading skeletons, empty "No reviews yet", error with retry, offline, disabled), RTL, 360 px,
  zero untranslated keys.

### L14. Staff two-step sign-in and finance exports (Opus, high effort)

Backend and console only. There is no mobile half.

**Goal.** Spec 19.

**Two-step sign-in.**
- New module `apps/admin_panel/two_step.py`: time-based one-time codes per RFC 6238 (SHA-1, 6 digits,
  30 seconds, one step of tolerance either side), written with the standard library and tested against
  the RFC's published vectors. The only new dependency allowed is a pure-Python QR generator for the
  enrolment page.
- `admin_panel.AdminTwoStep(user one to one, secret, confirmed_at, last_accepted_step,
  failed_attempts, locked_until)` and `AdminRecoveryCode(user, code_hash, used_at)`. The secret is
  stored with the existing envelope encryption in `apps/finance/sensitive_data.py`; recovery codes are
  stored hashed. A code at or below `last_accepted_step` is refused.
- One gate, `two_step_satisfied(request) -> bool`, true when the session carries a verification for the
  signed-in user. It is used by: a middleware covering every path under `/admin/` except sign-in,
  sign-out, the two-step pages and the invitation acceptance page; and `HasAdminPermission`, so the
  JSON staff API under `/api/admin/` answers only inside a two-step-verified console session. A bearer
  token alone is refused with `admin_two_step_required`. Before changing this, list every caller of
  `/api/admin/` in the repository in the handoff notes; if one is outside the console, stop (1.7).
  Settled by the advisor on 2026-11-14, after the agent found two callers (a developer load probe and
  an operator's health check in the deployment runbook):
  - The staff API is session-authenticated only, with CSRF on writes, and both callers go through a
    two-step-verified console session. The probe may mark its own session verified only with the
    in-process helper the tests use, because it already runs with database access. No setting, header,
    query parameter or route may mark a session verified from outside the process.
  - The gate lives in `HasAdminPermission`, **not** in a rule on the `/api/admin/` path prefix. The
    route inventory test lists the staff API routes and a short, named list of routes that answer
    without the second step. That list holds `invitations/accept` (it creates the account, before any
    enrolment, and returns nothing that opens another route). **L15 adds the AI helper routes to it:**
    they live under `/api/admin/helper/`, accept only a helper key, and that key can be created only
    behind a fresh second step.
  - Texts in the technical admin and in docstrings that tell staff to call a staff API route with a
    token are changed to name the console page that does the same thing.
  - The verification in the session is bound to the user's id. A reset (console or server command)
    deletes the target's rows and ends their sessions. Every password sign-in clears it.
- Pages under `/admin/two-step/`: enrol (QR, text key, confirm), verify, recovery code, and the
  one-time display of 10 recovery codes. Signing out or a new session asks again.
- `fresh_two_step(request, minutes=10)` for the steps of spec 19.1. Staff role changes and the reset
  below call it; L15 calls it for key creation.
- Reset by a Super Admin on the staff page (`manage_admins`, required reason, audit row, the target's
  rows deleted, their sessions ended). `python manage.py reset_admin_two_step <email>` for the last
  Super Admin, which also writes an audit row.
- Server setting `ADMIN_TWO_STEP_REQUIRED`, default true. `config/settings/prod.py` refuses to start
  with it false. Tests that are not about two-step use a helper that marks the session verified; no
  test turns the gate off.
- Audit rows for: enrolment, reset, a lockout, a recovery code used.

**Finance exports.**
- New permission `export_finance` for Finance and Super Admin.
- Console page `finance/exports/`: kind, from, to. It answers a streamed CSV download.
- `apps/admin_panel/exports.py`, one builder per kind, each an explicit column list:
  - `transactions`: one line per captured payment attempt and one per refund: date, tracking number,
    payment reference, provider, provider reference, purpose (deposit, delivery, boost), paid by (owner
    or guest), amount, currency, dinar amount when present, status, sender id and name.
  - `commissions`: one line per funded deal: tracking number, funded date, traveler reward, Wassla fee,
    sender total, refunded to sender, fee kept, deal status, sender and traveler ids and names.
  - `payouts`: one line per payout: tracking number, payout reference, method, status, amount,
    currency, dinar amount when present, eligible date, paid date, failure reason, traveler id and name.
- Every amount is read from the terms snapshot, the payment, refund and payout rows or the ledger. No
  amount is recomputed (1.5 rule 2). The page reads and never writes a finance row.
- Range required, at most 366 days, on the row's own date in UTC. The first row is the column names.
  UTF-8 with a byte-order mark, RFC 4180 quoting. A cell that starts with
  `=`, `+`, `-`, `@`, a tab or a carriage return is prefixed with an apostrophe.
- Each export writes one audit row: kind, range, line count.

**Tests.** The RFC vectors; the tolerance window; replay refused; lockout and its release; recovery code
single use; the middleware on every console route name and on the technical admin; the JSON staff API
with a bearer token alone, with an unverified session and with a verified one; reset and forced
re-enrolment; `fresh_two_step`; production settings refusing the relaxed flag. Exports: column lists
frozen by a test; a forbidden-substring walk (email, phone, address, account numbers); totals equal to
the finance dashboard's for the same range; the formula guard; the range limit; permission by role; a
fixed query count per 1,000 lines.

**Done when.** No console page, technical admin page or `/api/admin/` route answers without the second
step, except the named list above; `docs/PHASE_L14_ADMIN_SECURITY_EXPORTS.md` holds the route inventory, the export columns and the
recovery procedure; `docs/ADMIN_OPERATIONS.md` explains enrolment, reset and exports for staff.

### L15. AI helper: keys and read access (Opus, xhigh effort)

**Goal.** Spec 20.1 to 20.3, 20.5, 20.6 and 20.8. An admin's assistant can read that admin's briefing
and follow it down to single records, with that admin's rights and the data limits of 2.11. This
package contains no way to change anything.

**App.** New Django app `apps.admin_helper`. It owns the keys, the call log, the policy reader, the
helper API and the console pages. It reads other apps through their existing query functions and
writes none of their tables.

**Policy.** New top-level section in `BusinessSettingsVersion.policy`, read by
`apps/admin_helper/policy.py` in the style of 2.1:
`"admin_helper": {"enabled": true, "read_key_hours": 8, "change_key_minutes": 30,
"prepared_action_valid_hours": 24, "requests_per_minute": 60}`. Bounds: read 1 to 8 hours, change 5
to 60 minutes, validity 1 to 72 hours, rate 10 to 300. A missing section means these defaults. A form
"AI helper" on the Settings page, permission `manage_settings`.

**Keys.**
- `AdminHelperKey(id uuid, admin, kind: read|change, key_hash, hint, created_at, expires_at,
  revoked_at, last_used_at, use_count)`. The key is `wslr_` or `wslw_` plus 43 URL-safe random
  characters. Only its SHA-256 is stored; `hint` is its last four characters. A partial unique
  constraint allows one unrevoked key per admin and kind.
- `issue_key(admin, kind, request)` requires `fresh_two_step` (L14), revokes the admin's live key of
  that kind, sets `expires_at` from policy at creation, and returns the plain key once.
  `expires_at` never moves.
- `resolve_key(plain)` returns the key only when: the switch is on; it is unrevoked and unexpired; and
  `has_admin_access` is true for a freshly loaded admin. Every other case is the same
  `401 admin_helper_key_invalid`.
- Audit rows for issue and stop. `AdminHelperCall(key, method, path, status, at)` for every call,
  written after the response, pruned after 30 days by a new `ScheduledJob` kind.

**Authentication and authority.**
- A DRF authentication class reads `Authorization: Bearer <key>` and nothing else: not a query
  parameter, not a cookie. It is installed only on the helper's views, and the helper's views accept
  nothing else. A helper key opens no other route in the system. The helper routes do not use
  `HasAdminPermission` and are added to L14's named list of routes that answer without a session's
  second step; nothing else is added to that list.
- Each endpoint and each resource names the admin permission code of the console page it mirrors and
  checks it with `has_all_admin_permissions` (the fresh check) on every call.
- Throttle per key from policy; `429 admin_helper_rate_limited`.
- Every response: `Cache-Control: no-store`.

**One work list.** Move `_attention_items` out of `console_views.py` into
`apps/admin_panel/worklist.py` as `work_items(admin) -> list[WorkItem]`, where a `WorkItem` has
`code`, `permission`, `title`, `hint`, `count`, `oldest_waiting_since`, `severity: urgent|today|info`,
`route`, `query`. The console overview and the helper briefing both render this list; neither builds
its own (1.5 rule 10). It must cover every queue the overview shows when this package starts,
including those added by L6A, L9A and L13A. `oldest_waiting_since` and `severity` are new;
severity is a fixed rule per item written next to it, not a model's guess.

**API**, all under `/api/admin/helper/v1/`, JSON, read only:
- `GET guide`: the admin's display name and roles; the key's kind and expiry; the resources and
  queues this admin may read; the actions this key may take (empty in this package); the console base
  address; and `rules`, a short fixed text stating 2.11 for the assistant.
- `GET briefing`: `generated_at`, then `items` (raised work, most urgent first: `code`, `title`,
  `why`, `count`, `oldest_waiting_minutes`, `severity`, `next_step`, `console_url`, `queue`), `clear`
  (the queues with nothing waiting), and `system` (provider and job health when the admin may see it).
  No user-written text.
- `GET queues/<code>?limit=&cursor=`: at most 25 rows, oldest first: `type`, `id`, `tracking_number`
  when the row has one, `status`, `waiting_minutes`, amounts in EUR cents with currency, `people` (2.11
  form), `next_step`, `console_url`.
- `GET records/<type>/<id>`: one record through its allowlist serializer, its timeline as server
  labels, and `console_url`. User-written fields appear only here, under `untrusted_user_text`, each
  cut to 500 characters.
- `GET search?q=`: a tracking number (through `tracking.normalize`), a payment or payout reference, or
  an internal user id. It answers typed links, never a list of people by name.
- `GET tasks`: the how-to list for this admin (spec 20.5): `[{code, title, asks: [example questions],
  steps: [plain sentences], console_url, needs_document: bool, action: <L16 action code or null>}]`,
  only the tasks whose permission the admin holds. The texts live in `apps/admin_helper/tasks.py`, one
  entry per thing an admin can do in the console, keyed to the same permission code and route as the
  console page. A test lists every console route name and requires each to have a task or to be on an
  explicit "no task" list, so the how-to cannot fall behind the console.
- Types: `person`, `request`, `journey`, `deal`, `dispute`, `payment`, `refund`, `payout`, `job`,
  `problem`, `review_report`, and the review queues of 2.11 as counts and links only.

**Resource registry.** `apps/admin_helper/resources.py`: one entry per type with its permission code,
its queryset function, its allowlist serializer, its console address builder and its `next_step`
texts. A type without an entry does not exist for the helper. Serializers are written key by key;
none reuses a console presenter or a model serializer.

**Console.**
- The overview page gets an "AI helper" card: what it is in two lines; each key's state ("Active until
  17:40", "None"); "Create read key (8 hours)" and "Stop key"; and, right after creation, the one-time
  copy block and a line saying it will not be shown again. "Copy" copies exactly one line,
  `/wassla <address> <key>`, where the address is this server's `/api/admin/helper/v1`, so the admin
  pastes one thing into their assistant (spec 20.7). The change key and its button arrive in L16 and
  are not stubbed here.
- An "AI helper" page: the admin's keys and their recent calls. Super Admin also sees every admin's
  keys (never a key itself) and can stop any of them, audited.
- With the switch off the card says so and offers nothing.

**Privacy tests (required).** For every helper payload, build a person with a distinctive last name,
email, phone, street address, coordinates, date of birth, document number, a KYC file, a payout
profile with account details, pickup and delivery codes, a chat message and a guest payer email; then
walk the JSON and fail on any of those strings and on the forbidden keys of 2.11. A second test puts
an instruction sentence in every user-written field and proves it appears only under
`untrusted_user_text` on `records`, and nowhere in `guide`, `briefing`, `queues` or `search`.

**Authority tests (required).** For each role and each endpoint and type: the helper answers exactly
when the console route it mirrors would. A role downgrade, a ban and a deactivation take effect on the
next call with the same key. A read key at 7 h 59 min answers and at 8 h does not, including when it
was used one second earlier. A new key stops the old one. The switch off refuses every key. A helper
key is refused on a sample of every other API family and on the console. A session cookie or a user
token is refused on the helper API. Only the hash is stored, proven by searching the database dump for
the plain key.

**Other tests.** Rate limit. Call log written and pruned. The briefing equals the console overview for
the same admin, item by item. Fixed query counts for `briefing`, and for `queues` at 1 and 25 rows.

**Done when.** The contract and the full list of fields per type are in
`docs/PHASE_L15_ADMIN_HELPER_READ.md`; a second, independent review pass on authority and data limits
is recorded in the pull request (1.6); `curl` examples for each endpoint are in the phase doc with a
redacted key.

### L16. AI helper: changes (Opus, xhigh effort)

**Goal.** Spec 20.4. A change key lets the assistant do two harmless things directly and prepare the
rest for the admin to confirm in the console.

**Notes.** `admin_panel.AdminNote(target_type: deal|dispute|person, target_id, author, body (2000),
via_helper, created_at)`, append only. Shown on the deal, dispute and person console pages with a form
for staff (permission: the page's own view permission). Notes are internal: never in a user payload.

**Prepared actions.** `admin_helper.PreparedAction(id uuid, admin, key, action, target_type,
target_id, params, helper_reason (500), summary, status: waiting|confirmed|rejected|expired|failed,
created_at, expires_at, decided_at, outcome)`.

**Action registry.** `apps/admin_helper/actions.py`: one entry per action with its permission code,
its mode (`direct` or `prepared`), its parameter schema, `validate(admin, params)`, `summary(params)`
and `run(admin, params, reason)`. `validate` and `run` call the **same service function and the same
form validation the console view calls**; no action has a second implementation, and an entry may not
call a model's `save`. The registry is the complete list:

| Action | Mode | Permission | Existing action it calls |
| --- | --- | --- | --- |
| `note.add` | direct | the target page's view permission | `AdminNote` creation above |
| `problem.acknowledge` | direct | as L9A's staff queue | L9A acknowledge |
| `refund.request` | prepared | `issue_refunds` | the console refund request |
| `dispute.set_status`, `dispute.resolve` | prepared | `manage_disputes`, `resolve_disputes` | the console dispute actions |
| `deal.record_no_show` | prepared | `record_no_show` | `record_no_show` |
| `user.ban`, `user.unban` | prepared | `manage_users` | the console access action |
| `profile.hide`, `profile.show` | prepared | `manage_users` | L2A profile visibility |
| `journey.pause`, `journey.resume` | prepared | `manage_journeys` | L3A journey pause |
| `sea_crossing.activate`, `sea_crossing.deactivate` | prepared | as L3A | L3A crossing toggle |
| `job.retry`, `job.resolve` | prepared | `reconcile_finance` or `manage_lifecycle`, as the console decides per job | the console job actions |
| `payout.retry` | prepared | `retry_payouts` | the console payout recovery |
| `review.hide_comment`, `review.remove`, `review.dismiss_report`, `review.lift` | prepared | `moderate_ratings` | L13A moderation |

Anything not in this table cannot be done or prepared through the helper. In particular, and proven
by a test that lists every console POST route and requires each to be either in this table or in an
explicit "never through the helper" list: staff, roles and invitations; settings; helper keys;
two-step; revealing payout details; identity, ticket, payout-method and payout-identity reviews;
manual dinar payout steps; payment reconcile and resolve; refund settlement.

**API**, under `/api/admin/helper/v1/`, change key only (`403 admin_helper_change_key_required`
for a read key):
- `POST actions` with `action`, `target`, `params`, `reason`. The server checks the permission (fresh),
  validates, then for a direct action runs it and answers the result, and for a prepared action stores
  it and answers `status: "waiting"`, the `summary` and the `confirm_url` in the console.
- `GET actions?status=`: the admin's own prepared actions and their outcomes.
- `guide` now lists, for this key, the actions this admin may take and each one's mode and parameters.

**Console.**
- The AI helper card gains "Create change key (30 minutes)". It needs a fresh two-step code. The copy
  block states the expiry time.
- "Waiting for your confirmation" on the AI helper page and as an item of the work list: for each
  prepared action the server's summary, the target as a link, the parameters in words, and the
  assistant's reason shown in a box labelled "Written by the AI helper, check it".
- Confirm asks for the admin's own reason (pre-filled, editable, required), re-validates against the
  current state, checks the permission again and runs the registry's `run` as the signed-in admin. If
  the state changed it says "This no longer applies" and marks the action failed. Reject needs no
  reason. A prepared action can be confirmed only by the admin whose key prepared it, only from a
  two-step-verified console session, and only once.
- Expiry after `prepared_action_valid_hours` by a new `ScheduledJob` kind.

**Audit.** Direct and confirmed actions write the audit row the console action writes, with metadata
`{"via": "ai_helper", "key": <id>, "prepared_action": <id or null>}`. Preparing and rejecting write
their own rows.

**Tests.** For each registry entry: the permission matrix by role; `validate` refusing what the
console refuses; the confirmed result equal, row for row, to the console action's result; the audit
metadata. A prepared action cannot run through any helper endpoint, with any key. Confirm by another
admin, without two-step, twice, after expiry, and after the target changed. A read key on `POST
actions`. A change key at 29 min 59 s and at 30 min. The coverage test over every console POST route.
An instruction placed in a dispute description and returned by `records` cannot cause any state change
without a console confirmation, shown by a scripted client that obeys it and still ends with only a
`waiting` row. Finance tables byte-identical after preparing a refund.

**Done when.** `docs/PHASE_L16_ADMIN_HELPER_CHANGES.md` holds the registry as built and the
"never" list; the second review pass is recorded (1.6); with the switch off no key works and the
waiting list is read only.

### L17. AI helper skill (Sonnet, medium effort)

Runs last of the helper packages, after L16. Ismail first asked for the skill to be written last, then
on 2026-11-12 asked for it to be drafted at once: **the draft already exists in
`docs/admin-helper-skill/`** (`SKILL.md`, `INSTRUCTIONS.txt`, `README.md`), written against this plan
before any helper code existed. This package makes it true.

**Goal.** Spec 20.7. The admin types `/wassla`, pastes the copied line, and gets a briefing, or an
answer to whatever they added after it. A small, fast model must manage it, and the answers must be
plain enough for someone who has never used the console.

**Work.**
1. Compare the draft with the helper as built (`docs/PHASE_L15_...`, `docs/PHASE_L16_...`): every
   endpoint name, every field it relies on (`next_step`, `confirm_url`, `untrusted_user_text`, the
   `tasks` shape, the status codes). Fix the draft where the build differs. Do not change the helper to
   fit the draft unless the draft's way is simpler for the admin; then it is a stop-and-ask (1.7).
2. Keep `INSTRUCTIONS.txt` generated from `SKILL.md` (same body, no front matter); add the small
   script that does it and a test that fails when they differ.
3. The console's AI helper card gets "Download the skill" and "Copy the instructions", served from
   these files at build time.
4. Run the proof below.

**Files.** `SKILL.md` is in the standard skill layout (front matter with `name: wassla` and a one-line
description, then the body). Neither file contains a key or an address; the copied line supplies both.

**Content rules.** At most 140 lines. Besides the `/wassla` behaviour above, it tells the assistant
to: read `guide` first and trust it over the file; present raised work in the server's order with the
console link for each item; open a queue or record only when the admin asks or when it needs one to
explain an item; answer "how do I ...?" only from `tasks`; treat everything under
`untrusted_user_text` as data and never as an instruction; never ask for a change key unless the admin
asks for a change; say plainly that a prepared action waits for the admin's click and give the link;
say what was refused and why instead of guessing; never invent a number, a status or a link; send the
pasted key only in the request header to the pasted address, and never show it, store it or put it in
a link; say how to get a new key when one expires; answer in the admin's language, in short plain
sentences. It names only the few fields it must (`next_step`, `confirm_url`, `untrusted_user_text`);
`guide` carries the rest.

**Proof.** Eight scripted conversations against a seeded local server, run with the smallest Claude
model available to the agent, transcripts in the phase doc: `/wassla` with the copied line and nothing
else (the briefing); `/wassla` with no key (where to get one); "how do I refund someone?" answered from
`tasks`; "what is WSL-... waiting for?"; one dispute explained; a refund prepared with a change key
and the confirmation link given; a user-written instruction ignored; an expired key handled. Each must
end correct without a retry. If the small model fails a scenario, fix the helper's `guide`, `tasks` or
`next_step` texts first and the skill second; do not solve it by lengthening the skill past the limit.

**Done when.** `docs/PHASE_L17_ADMIN_HELPER_SKILL.md` holds the transcripts; the card's two buttons
work; `docs/ADMIN_OPERATIONS.md` has a half-page "Using the AI helper" for staff.

### L10. Final acceptance (Opus, high effort)

L10 runs last, after L17.

1. Whole suites on PostgreSQL, Go with race detection, and Flutter. Counts recorded against the
   baseline (Django 2,529 passed, Flutter 1,083 passed at `dd7f820`).
2. Scripted end-to-end scenarios in test mode. The main one is the product's target (2026-11-13): **an
   urgent parcel carried the same day**, once on a flight with an approved ticket and once on a drive
   with two stops, from discovery to an offer at the listed price, payment, pickup, the progress
   reports, delivery with the recipient's code, protection, payout. Also: a traveler with a sea leg
   and a ticket, with the sea switch turned on for the test. Added 2026-11-12: a request whose tracking
   number is followed from creation to payout through every email and screen; a proposal that expires
   after its reminder, and one that expires at the pickup time because that came first; a trip-fit alert leading to "I can carry this" and a proposal; a no-show report
   recorded by staff; a review reported, hidden, then removed and the average changing; a staff
   sign-in with enrolment, a wrong code, a recovery code and a reset; the three exports reconciled
   with the finance dashboard; the eight AI helper conversations of L17 run again on the final build.
3. Invariant proofs, as greps recorded in the report: no proof decision outside `apps/trips/proofs.py`;
   no write to `Deal.status` outside `apps/deals`; no listed-price arithmetic outside
   `apps/matching/listed_price.py`; every public discovery serializer has a privacy test; every new
   staff action writes an audit row; no `ST-` reference and no tracking-number code outside
   `apps/parcels/tracking.py`; no public rating average outside `apps/ratings/public.py`; no work-list
   query outside `apps/admin_panel/worklist.py`; every helper payload has the privacy walk; every
   console POST route is in the helper's action table or its "never" list; no staff route answers
   without the second step, except L14's named list (invitation acceptance, and the helper API, whose
   keys are created behind a fresh second step); nothing in `backend/` or `mobile/` code names a professional, a courier
   handoff or custody (the parked features left no hook).
4. Switch matrix: with each switch off, the capability refuses on the server and the app shows the
   unavailable state. This includes the response deadline, trip-fit alerts and the AI helper (off:
   every key refused at once).
5. Migrations: every one additive, `sqlmigrate` output reviewed, `task check-drift` clean.
6. Performance: the K-series budgets and all asserted query counts hold.
7. Design review of every new screen in EN, FR and AR on a small phone and a tablet. Assemble the
   kept gate screenshots (1.6) into one gallery for Ismail,
   `/mnt/project-files/l-series-screens/gallery.html`: one section per package, each image captioned
   with its screen, state and language. Take the missing ones for packages merged before 2026-11-12
   (L2B, L3B) and for L4B if it has none.
8. `docs/WASSLA_L_SERIES_RELEASE_REPORT.md` and `docs/IMPLEMENTATION_STATUS.md`.
9. Hand Ismail the report, the list of switches that are still off, and the open decisions. **No merge
   into `main` and no deployment without his explicit approval.**

---

## 5. Decisions

### 5.1 Answered by Ismail on 2026-11-11

1. **Sea crossings.** Researched and added: spec 5.3.1. Twelve crossings are seeded active and seven
   inactive. The "Sea legs" switch itself still ships off.
2. **Railway.** It does not stay on this branch. L1A removes it.
3. **Declined schedule change.** The cancellation that follows is treated as caused by the traveler.
4. **"I can carry this".** Kept.

### 5.1b Added by Ismail on 2026-11-12

After a review of the app against the "cahier des charges" of 11 November 2026, Ismail chose five
gaps to close and added one idea of his own. All are in spec 16 to 20 and spec 12.

1. **Tracking number** (L11A, L11B).
2. **Alert travelers whose trip fits, and remind before a proposal expires** (L12A, L12B). The review
   had said proposals already expire; they did not. The column existed and nothing set it. L12A adds
   the deadline itself.
3. **"The other person did not come"** (in L9A, L9B).
4. **Reviews readable on profiles, with report and hide** (L13A, L13B). The score and count were
   already on every card since L2A; the comments and moderation are what is new.
5. **Admin export and two-step sign-in** (L14).
6. **Admin AI helper** (L15, L16, L17). Decided by Ismail in discussion: each admin's own keys with
   that admin's rights; the read key expires 8 hours after creation even while in use; the change key
   lasts 30 minutes, adjustable; documents, bank details, delivery codes and chat contents never reach
   the helper; money, ban, role and settings actions are prepared by the helper and confirmed by the
   admin in the console. The skill: he first said to write it last, then asked for a draft the same
   day, started by typing `/wassla` with the pasted key, giving the briefing when nothing else is
   typed and answering "how do I ...?" questions, in words simple enough for anyone. The draft is in
   `docs/admin-helper-skill/`; L15 gained the `tasks` how-to list for it; L17 verifies it.

Not chosen, so not planned: profile photo and extra profile fields, the prohibited-items list, the
summary on the page a relative pays from, volume and a payout-account check on trips, SMS, a terms
page with recorded acceptance, a computer version of the user app, and the four design choices (full
payment before matching, a fixed grid, automatic assignment, weekly payouts).

### 5.1d Before the unattended run (Ismail, 2026-11-12, evening)

Ismail said he will not check on the build until it is done, asked what should change first, and
accepted four of six suggestions:

1. **Yes:** fix the test time limit first. It is package L4C, with the ferry distance carry-over.
2. **Yes:** build the tracking number right after L4B (L11A, L11B moved forward; 1.5 rule 12).
3. **No:** the AI helper does **not** ship switched off. It ships on, as spec 20.8 says.
4. **Yes:** one question must not stop everything (1.0, "When a package is blocked").
5. **No:** no package for a terms page with recorded acceptance or for the final prohibited-items
   list. They are still needed before real users and remain outside this build.
6. **Yes:** keep the gate screenshots in one place (1.6) and build a gallery in L10.

He also asked that the coordinator be reminded to bring problems to the advisor and to use the model
and effort of section 3 for every package, exactly.

### 5.1e Scope narrowed to fast delivery (Ismail, 2026-11-13)

Ismail stopped the build after L5B and said: Wassla will be only for fast delivery, mostly flights and
drives made the same day; professional travelers are not needed for now and are planned later on a
subdomain, so their plan must be kept in the repository, not thrown away; everything else stays. In
the discussion that followed he decided:

1. **Professional transporters are parked**: the professional half of L6A, and L6B, L7A, L7B.
2. **Courier handoff is parked too**, with the custody history around it: L8A, L8B.
3. **Sea legs stay as built and switched off.** No work on them.
4. **"Same day" is the target, not a rule.** The app enforces nothing about a trip's length.
5. **A proposal waits 6 hours for an answer, or until the pickup time if that comes first, with one
   reminder 1 hour before** (was 48 and 12). Both stay admin settings.
6. The staff verification inbox stays, with two tabs (ID, Tickets) instead of three.

The parked text is in `docs/parked/WASSLA_PROFESSIONAL_AND_COURIER_PLAN.md`, word for word, with what
to check before resuming.

Choices the planner made while writing this change (not individually confirmed; any can be changed
before its package starts):

- The two unused switches the parked features left in the settings reader are **removed** by L6A,
  not kept for later (1.5 rule 10). They return with the features.
- Problem reports get their own small app, `apps.problems`, because the custody app they were going
  to live in is parked.
- The problem kind "crossing cancelled" became "trip cancelled or delayed", so that it also fits a
  flight and a drive. The three courier kinds are gone.
- The optional photo of the parcel's condition at pickup was part of L8A and is parked with it.
- The filters and reference search on the deliveries list were part of the manifest and are parked
  with it.
- "The pickup time" in decision 5 is the time the matching engine already computes for that parcel on
  that trip. For a flight it is the departure.
- L6A keeps Opus at high effort although it is smaller, because ticket and ID decisions open and
  close matching.
- Schedule changes (L9A, asked by its agent): whether a change is "large" is measured against what
  the sender last agreed to; a large move of the pickup time also needs the sender's agreement; a
  sender whose parcel is already collected is told, not asked, because they can no longer cancel; a
  re-timed flight or sea ticket is checked again. The threshold stays 6 hours by default. With a
  same-day target Ismail may want it lower; it is an admin setting.

### 5.1c Choices the planner made inside those additions (not individually confirmed)

Told to Ismail on 2026-11-12. Any of them can be changed before its package starts.

- The tracking number is random (`WSL-` plus 8 characters), not a counter, so it does not reveal how
  many parcels exist. It is not shown on public cards or on the page a relative pays from.
- A proposal's deadline was 48 hours with one reminder 12 hours before (now 6 hours and 1 hour,
  decided by Ismail, 5.1e); expiry leaves no mark on anyone.
- Trip-fit alerts go to at most 30 travelers per request and 5 per traveler per day.
- A review shows whether a sender or a traveler wrote it, not the author's name. Staff can hide only
  the comment or remove the whole rating from the score.
- Two-step sign-in uses an authenticator app only, is required for every staff account and cannot be
  turned off from the console.
- Exports carry names and internal ids but no email, phone, address or bank detail.
- The helper sees a person as first name and last initial only, never an email or phone. User-written
  text reaches it only on a single record, labelled as untrusted.
- The helper can add internal notes and acknowledge a problem directly; internal notes are a new,
  small console feature added for that.
- Reviews that need a document (identity, tickets, payout methods) cannot be decided or
  even prepared through the helper.
- A prepared action lasts 24 hours and only the admin whose key prepared it can confirm it.
- L15 and L16 run at xhigh effort, like L3A, because they touch staff authority.

### 5.2 Still open

1. **Turning sea legs on.** The legal and customs position for carrying parcels by sea was not
   researched, and the crossings were not checked on the operators' own sites. This is Ismail's call
   when he turns the switch on. It blocks nothing in the build.

### 5.3 Later, not in this build

Parked with a complete plan (`docs/parked/WASSLA_PROFESSIONAL_AND_COURIER_PLAN.md`): professional
transporters, the manifest dashboard, custody history and courier handoff.

Not planned at all: business logos and photos, courier API integrations, recurring routes, fleet
management, analytics.

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
| Offers: creation, counter, decline, the unused `expires_at` | `apps/matching/v1_services.py`, `apps/matching/models.py` (`Offer`) |
| Route alerts and their durable fan-out | `apps/discovery/alerts.py` |
| Ratings, the blind rule, the public average | `apps/ratings/services.py`, `apps/matching/find_travelers.py` (`trust_signals`) |
| Staff no-show record | `apps/deals/cancellation.py::record_no_show` |
| Staff roles, permission codes, the fresh permission check | `apps/admin_panel/permissions.py` |
| Console work list ("What needs attention") | `apps/admin_panel/console_views.py::_attention_items`, `templates/admin/console/overview.html` |
| Audit log | `apps/admin_panel/models.py` (`AdminAuditLog`), `apps/admin_panel/services.py::record_admin_action` |
| Envelope encryption for secrets at rest | `apps/finance/sensitive_data.py` |
| Parcel references today (`ST-<id>`) | search `deal_reference` in `apps/` |
