# Wassla handoff

Written on 2026-11-15 by the planning session of the L-series, at Ismail's request, so that a
session on another account can continue exactly where the work stands. Everything such a session
needs is in this repository. Nothing here depends on an earlier conversation.

**Read `CLAUDE.md` first** (the rules), then this file, then the board
(`docs/WASSLA_L_SERIES_PROGRESS.md`).

## 1. Start here

```
git fetch origin
git checkout feature/discovery-professional-delivery
```

All current work is on that branch. `main` is far behind it and must not be touched (section 4).

A first message that works for a fresh session:

> Read CLAUDE.md, HANDOFF.md and the board in docs/WASSLA_L_SERIES_PROGRESS.md on the branch
> feature/discovery-professional-delivery. Tell me where the work stands and what you would do
> next, then wait for my go.

## 2. What Wassla is

A marketplace where a sender's parcel travels with a traveler who is already making the trip.
A sender posts a request and proposes to a compatible traveler; the deal is funded; the traveler
collects the parcel with a pickup code, reports progress, and delivers by entering the recipient's
code; the payout is released 48 hours later unless a dispute freezes it.

Since 2026-11-13 the product is **fast delivery**: urgent parcels, mostly on flights and drives made
the same day. Ismail's words: "we just wanna try and target same day urgent delivery". It is a
target and a positioning, not a rule the app enforces.

Stack: Flutter app in `mobile/` (English, French, Arabic); Django monolith in `backend/monolith/`
(REST API, staff console, staff API under `/api/admin/`); Go services in `backend/services/` (chat,
notifications, ID upload); PostgreSQL 16, Redis 7, S3-compatible storage; the production host stack in
`infra/vps/`; the public site in `web/`. `ARCHITECTURE.md` describes the system.

## 3. Where the work stands (2026-11-15)

The **L-series** (Home discovery, routes for everyone, traveler pricing, progress reports, the staff
verification inbox, problems and schedule changes, tracking numbers, proposal deadlines and trip-fit
alerts, reviews, staff two-step sign-in, finance exports, the admin AI helper and its skill) is
built, merged into the integration branch and accepted by its final package:

- Every package from L1A to L18B, and L10 (final acceptance), is **merged**. Pull requests #22 to
  #49. The board has one row and one handoff block per package.
- L10 changed no product code. Its verdict and every number are in
  `docs/WASSLA_L_SERIES_RELEASE_REPORT.md`. Tests on the final build: Django 3,270 passed, Flutter
  1,533 passed, Go race tests clean on 14 packages.
- **Nothing is merged into `main` and nothing is deployed.** The release report has not yet been
  formally handed to Ismail for his end review; that follows L19 (section 5).
- One L-series package is left: **L19**, paused by Ismail.

The last commit of the integration branch when this was written: `4478ad9` (board after L10).

## 4. Branches

| Branch | What it is |
| --- | --- |
| `feature/discovery-professional-delivery` | **The integration branch. All work lands here** through pull requests. |
| `feature/wassla-v3-baseline` (`dd7f820`) | The baseline the integration branch started from: the app before the L-series. No pull request exists for it. |
| `main` | Last real change in September 2026 (the K-series release record). Far behind. **Never merge into it without Ismail's explicit approval.** |
| `codex/rebrand-waçla`, `codex/v1-vps-readiness`, `codex/v2-email-readiness` | Older stacked branches. Each is contained in the next, and all are contained in the baseline. |
| `claude/project-thread-*` | One per finished package, all squash-merged. Safe to delete once Ismail agrees (section 6). |

Pull requests are squash-merged. After a squash merge, a warning that the old branch has "unpushed
commits" is harmless; nothing needs a force-push.

Brand history: ShipTrip, then Waçla, then **Wassla**. Some `shiptrip` and `wacla` names remain on
purpose: the Go module path, the database role, `docs/SHIPTRIP_V1_SPEC.md`, systemd unit names, a
fixture name, and provider checkout descriptions that are part of idempotency fingerprints. Do not
rename them as "cleanup" without checking what depends on each.

## 5. What is next, in Ismail's order

Ismail decides when each starts. Do not start any of them on your own.

### 5.1 L19, findings of final acceptance (paused)

Plan section "L19" and decision 5.1g. **Strongest model, high effort, backend only, no migration.**
Start only when Ismail says so.

1. The admin helper's notes still describe a staff path to open a dispute that L18A removed
   (`backend/monolith/apps/admin_helper/skill/knowledge/architecture-and-diagrams.md`, and the same
   line in the generated `INSTRUCTIONS.txt`). Drop the sentence, search the skill for other mentions,
   regenerate with `python manage.py build_helper_instructions`, rerun the one proof conversation.
2. With `PAYOUT_PROFILES_ENABLED` off (the shipped example configuration), `ensure_payout_for_deal`
   in `apps/finance/services.py` creates the payout with no mode, so it defaults to `legacy_unknown`
   while its funding is in test mode, and the finance dashboard splits one deal's traveler balance
   across two modes. The payout takes the mode of its funding attempt (the `funding_attempt(order)`
   lookup that `create_snapshot` uses). Production cannot reach this branch.

Done when L10's 22 acceptance tests and the whole suites are green on its pull request and the
release report's section 14 marks both findings closed. **After L19, hand Ismail the release report**
(plan L10 item 9): the report, the switches still off, and the open decisions of section 8 below.

### 5.2 A scan for unnecessary complexity and repeated logic

Ismail wants the code scanned for unnecessary complexity and repeated logic. Suggested way to run it,
so that nothing changes behaviour by accident:

1. **Read-only first.** Produce a findings document (for example `docs/WASSLA_CLEANUP_AUDIT.md`):
   each finding with its place, why it is unnecessary or repeated, what would replace it, the risk,
   and whether it touches matching, money, codes or staff authority.
2. Ismail approves the list. Only then is anything changed.
3. Group the approved findings into small packages, one pull request each, with the model and
   effort decided by the rule of plan 1.2. Each is behaviour-preserving: the whole suites and L10's
   acceptance tests (`backend/monolith/apps/core/tests/test_l10_*.py`) pass unchanged.
4. No money result, code rule or matching result may change. If a simplification would change one,
   it stops and becomes a question for Ismail.

Rules that already have one home. A second copy of any of these is a finding; the home itself is
not:

| Rule | Its one home |
| --- | --- |
| Ticket proof for flight and sea legs | `apps/trips/proofs.py` |
| Switches and settings | `apps/core/marketplace_policy.py` |
| Listed price arithmetic | `apps/matching/listed_price.py` |
| Writes to `Deal.status` | `apps/deals` only |
| Tracking number | `apps/parcels/tracking.py` |
| Public rating averages and counts | `apps/ratings/public.py` (`countable`) |
| Staff work list and its severity | `apps/admin_panel/worklist.py` |
| "Waiting" in the verification inbox and its three decisions | `apps/admin_panel/verification_inbox.py` |
| Console actions the AI helper also runs | `apps/admin_panel/staff_actions.py`, registry in `apps/admin_helper/actions.py` |
| Problem reports | `apps/problems` |
| Schedule changes | `apps/trips/schedule_changes.py` |
| Ending every session of an account | `apps/accounts/sessions.py` (`end_all_sessions`) |
| "Confirmed email needed to write" | `apps/accounts/permissions.py` (`EmailVerifiedToWrite`) |
| Staff second-step gate | `apps/admin_panel/two_step.py` |

Known candidates, found during the L-series and deliberately left (verify each before acting):

- **Legacy tables and branches** (`docs/WASSLA_L1_CLEANUP_INVENTORY.md`, section 2): the models,
  migrations and tables of `apps.payments`, `apps.wallet`, `apps.verification`, `apps.trips.Trip`
  and `ProductRequest`; the `schema_version` 1 and 2 branches in matching, trips, parcels and
  finance; `apps/matching/services.py::_legacy_chat_eligibility`. No real row needs them. They stayed
  because the L-series forbade any migration that drops or narrows (plan 1.5 rule 5). **Removing
  them needs Ismail to lift that rule for a dedicated cleanup package**, on the strongest model,
  because the branches sit inside matching, finance and pricing reads.
- **The payout path without payout profiles** (`PAYOUT_PROFILES_ENABLED` off). Live mode requires
  profiles, so this branch serves development and tests only. Whether to keep two payout paths is a
  question for Ismail after L19.
- **Statuses nothing sets**: deal `offer_accepted` and `payment_failed`, journey
  `pending_verification`. Left on purpose (plan 5.1f): the V1 specification names them and they sit
  in status lists, a database constraint and the app.
- **About 80 code comments cite sections of an earlier `CLAUDE.md`** (`CLAUDE.md §4`, `§9`, `G1`
  and so on). The guardrails G1 to G6b are restated in today's `CLAUDE.md`; the numbered sections no
  longer exist. The earlier file is in git history (`git log --follow CLAUDE.md`, before 2026-08-30).
- L9A known limit: after an accepted later pickup time, the no-show window still uses the original
  time (`agreed_pickup_at` keeps its funded value).
- The console refund form, asked twice for the same payment and reason, answers with the refund that
  exists whatever the amount (`finance.services.request_refund`); the AI helper refuses that case.
- `tools/geography` tests are not run in CI.

### 5.3 Repository cleanup

Candidates, for Ismail to approve before anything is deleted:

- Root files from earlier phases: `TASKS.md` (a two-person task list from mid-2026, stale but with
  notes on why some behaviours are deliberate), `ShipTrip_Progress_Report.pdf`, the empty
  `package.json` and `package-lock.json`, `backend/services/HANDOVER.md`.
- Tool folders: `.cursor/`, `.codegraph/`.
- `docs/`: about 120 files. The dated phase reports (`PHASE_*`, `K_SERIES_*`, `V1_*`, `V2_*`,
  `k6-notes/`, `k7-notes/`, `superpowers/`) are history; `docs/IMPLEMENTATION_STATUS.md` is close to
  9,000 lines. An archive folder or a trimmed status file would make the live documents easier to
  find. The live ones are listed in section 9.
- Remote branches: the merged `claude/project-thread-*` branches and the three `codex/*` branches.
- `ARCHITECTURE.md` was corrected in L1A but predates most of the L-series.
- Removed in the handoff commit because they contradicted today's rules: the old `HANDOFF.md`
  (April 2026) and `.claude/MEMORY.md` with `.claude/memory/` (a two-agent split, DZD commission
  rules and a storage design that no longer exist). Git history has them.

### 5.4 Other changes

Ismail said there are other changes he wants. He has not described them yet. Ask him.

## 6. How the work is run

`CLAUDE.md` has the rules. The full procedure is plan section 1 (`docs/WASSLA_DISCOVERY_PRO_PLAN.md`):
1.0 the runbook, 1.2 models and effort, 1.4 the checks, 1.5 the rules of every package, 1.6 the gate
review, 1.7 when to stop and ask, 1.8 the board, 1.9 the brief for a package.

The L-series was run by three roles: an orchestrator that kept the board, started one worker per
package with the plan's model and effort, ran the gate review and merged; one worker per package;
and an advisor that settled questions about the specification and plan and recorded each answer in
the plan. One session can play all three, or the person can start one session per package. What must
not change:

- One package at a time, in the board's order, each in its own pull request into the integration
  branch.
- The model and effort the plan names for the package. Before starting a package, say which model
  and effort it needs so the person can switch to it. Ismail corrected this once and asked to be
  reminded at every step.
- The gate review is recorded on the pull request before the merge, and the merge waits for every
  check: `Go — build, vet, unit tests`, `Go — integration tests (real Redis)`, the four
  `Django — tests (shard N)` jobs, `Django — migrations + tests + lint`,
  `Production config + static web`, `Flutter — format, analyze, tests` and `Schema drift`.
- After a merge, the board is updated in a small docs-only commit on the integration branch. Pull
  before editing it.
- Ismail did not want to be asked small questions during the build. A question about what the
  specification or plan means, or a choice between two ways to build the same rule, is settled by
  reading them and recording the choice as a judgment call in the package's handoff block. Only
  what would change a product decision, a money rule or the approved scope waits for him.
- Judgment calls are listed, not hidden: each package's handoff block and the release report
  (section 12) collect them for Ismail's end review.

Gate screenshots were saved outside the repository (section 9). From now on, attach them to the
pull request, which the plan allows (1.6), unless Ismail names another place.

## 7. Decisions Ismail has made

Locked. Do not reopen them; the plan's section 5 has the dates and the detail.

**Scope**
- Fast delivery, mostly same-day flights and drives. No enforced same-day rule.
- Parked, with their full text kept in `docs/parked/WASSLA_PROFESSIONAL_AND_COURIER_PLAN.md` for a
  later subdomain: professional transporters (profile, business document, ticket exemption), the
  manifest dashboard, custody history, courier handoff. Packages L6B, L7A, L7B, L8A, L8B and the
  professional half of L6A. Never start them, leave no hooks.
- Sea legs stay built and switched off. Turning them on is Ismail's call: the legal and customs
  position was not researched and the crossings were not checked on the operators' sites.
- Launch countries: Algeria, France, Spain, Germany.
- Not built, because he declined them: a legal package (terms page with recorded acceptance, final
  prohibited-items list). He also declined shipping the AI helper switched off: it ships on.

**Product**
- Every traveler may build a multi-stop route. Travelers pass the ID check, and upload a ticket for
  each flight and sea leg. Nobody is exempt.
- No capacity cap set by staff.
- Pricing: a price per kg and a minimum per parcel, per route; the offer is pre-filled and still
  negotiable; Wassla's minimum applies; the fee is on top.
- Discovery profiles are opt-in. "I can carry this" stays. Depart and arrive reminders per leg.
- A declined schedule change followed by a cancellation counts as caused by the traveler.
- A proposal waits 6 hours, or until the pickup time if that is sooner, with a reminder 1 hour
  before.
- Senders verify by email only. Travelers by ID.
- Push: Firebase only, for the closed app.
- From the cahier des charges, he chose to build: the tracking number, alerts to travelers whose
  trip fits a new request, the reminder before a proposal expires, "the other person did not come",
  public reviews with report and hide, finance exports and staff two-step sign-in.

**Staff side**
- One verification inbox (ID and Tickets), switches, suspend and pause, everything audited.
- AI helper: per-admin keys; the read key ends 8 hours after creation, the change key after 30
  minutes; no ID documents, bank details, delivery codes or chat contents ever reach it; money, ban,
  role and settings actions are prepared by the helper and confirmed by the admin in the console.
  The skill is for the Super Admin only for now and must answer any question about the app,
  including how it is built, with diagrams.

**Process**
- Never merge into `main` or deploy without his approval. Model and effort exactly as planned.
- The app has no real users: no legacy or backward-compatibility work.
- Quality bar: impeccable UX; clean code, dead and messy code removed; location, finance and
  admin-control logic airtight.

Four ways the app differs from the cahier des charges that Ismail has **not** decided, and that no
plan covers. Do not build any of them unless he asks: payment in full before matching (the app takes
a small refundable posting deposit, full payment after a traveler agrees); a fixed price grid (the
app has a minimum, a suggestion and negotiation); travelers alerted and the first to accept assigned
(the app lets the sender choose and propose); weekly payouts (the app pays per delivery after 48
hours).

## 8. Open items for Ismail

**Before real users** (release report section 10)
1. A real, monitored support address in `EMAIL_SUPPORT_ADDR`. The app's "Contact support" appears
   only when the server has one. `EMAIL_FROM_ADDR` and `EMAIL_REPLY_TO` need verified-domain
   addresses.
2. `web/support.html` still lists placeholder mailboxes at `shiptrip.example`.
3. A terms page with recorded acceptance and the final prohibited-items list.
4. If a CDN or another proxy is ever put in front of the web server, set the trusted proxies and the
   per-address limits for it first.
5. The payout keyring must be provisioned before the first production start.

**Open decisions** (release report section 11, plan 5.1f and 5.1g)
1. Should staff be able to open a dispute? Today only the sender or the traveler can.
2. Payout setup needs a confirmed email (added in L18A as a safety measure). Keep it?
3. The AI helper's urgency thresholds: tickets after 2 hours; ID checks and payouts after 24;
   payout methods and payout identity after 48; reported reviews after 72.
4. Turning sea legs on.
5. The planner's choices he has not individually confirmed (plan 5.1c): random tracking number;
   trip-fit caps of 30 travelers per request and 5 alerts per traveler per day; reviews show the
   role, not the name; authenticator app only for two-step; no email, phone, address or bank detail
   in exports. Also the schedule-change threshold `route_change.material_shift_minutes`, 360.
6. When to start L19, the scan, the cleanup, and what the other changes are (section 5).
7. For the cleanup: whether to lift the "no migration drops or narrows" rule so the legacy tables
   and branches can go (section 5.2).

**For his end review**: the judgment calls of every package, release report section 12.

## 9. Where everything lives

| What | Where |
| --- | --- |
| Rules for agents | `CLAUDE.md` (and `AGENTS.md`, which points to it) |
| V1 specification | `docs/SHIPTRIP_V1_SPEC.md` |
| Addendum that overrides it for the L-series topics | `docs/WASSLA_DISCOVERY_PRO_SPEC.md` |
| Plan: runbook, rules, packages, decisions | `docs/WASSLA_DISCOVERY_PRO_PLAN.md` |
| Board, handoff notes, questions, change log | `docs/WASSLA_L_SERIES_PROGRESS.md` |
| Release report of the L-series | `docs/WASSLA_L_SERIES_RELEASE_REPORT.md` |
| What each package built | `docs/PHASE_L*.md`, one per package |
| Parked plan | `docs/parked/WASSLA_PROFESSIONAL_AND_COURIER_PLAN.md` |
| What the first cleanup removed and kept | `docs/WASSLA_L1_CLEANUP_INVENTORY.md` |
| Progress log | `docs/IMPLEMENTATION_STATUS.md` (newest entry at the top) |
| AI helper skill and its notes | `backend/monolith/apps/admin_helper/skill/` |
| Staff operations, deployment, rollback, providers, push | `docs/ADMIN_OPERATIONS.md`, `docs/DEPLOYMENT_RUNBOOK.md`, `docs/ROLLBACK_RUNBOOK.md`, `docs/PROVIDER_ACTIVATION_RUNBOOK.md`, `docs/PUSH_NOTIFICATIONS_RUNBOOK.md` |
| Production host and its settings | `infra/vps/`, `infra/vps/ENVIRONMENT.md`, `infra/vps/stack.env.example` |
| CI | `.github/workflows/ci.yml` |
| Design and product notes | `DESIGN.md`, `PRODUCT.md`, `ARCHITECTURE.md` |

**Not in the repository.** These were kept in the previous account's project folder, which another
account cannot reach. Ismail has them and can pass them on:

- The gate screenshots of every package and the gallery L10 built from them (324 images, about
  57 MB, `l-series-screens/gallery.html`). The file names are listed in each package's phase doc.
- The comparison of the app with the cahier des charges (a PDF in English and one in French).

## 10. Working notes that save time

**Checks** (plan 1.4 has the full list)
- Backend: `ruff check .`, `python manage.py makemigrations --check --dry-run`, the whole pytest
  suite on PostgreSQL. Use `python -m ruff` with the pinned version (0.8.4 in `requirements.txt`); a
  newer global ruff reports about a thousand false errors.
- The Django suite needs PostgreSQL 16 and Redis 7 and the environment of `ci.yml`, including every
  `DRF_*_THROTTLE_RATE=10000/min` variable; without them about 30 tests fail with 429. Serially it
  takes about 30 minutes; CI splits it into four shards by file
  (`backend/monolith/config/test_shards.py`, durations in `config/test_durations.json`). A second run
  in parallel needs its own `POSTGRES_DB`.
- After a migration: `task check-drift` in `backend/`, and commit the regenerated `schema.sql` and
  sqlc output. If drift appears with no schema change, check the `pg_dump` client version first: CI
  runs `pg_dump` inside the PostgreSQL 16 service container for that reason.
- Go: `gofmt -l .`, `go build ./...`, `go vet ./...`, `go test -race -count=1 ./...` in
  `backend/services`.
- Mobile: `flutter gen-l10n`, `dart format --output=none --set-exit-if-changed lib test`,
  `flutter analyze --fatal-infos`, `flutter test` (about 3 minutes). CI uses Flutter 3.47.1,
  Go 1.26, Python 3.12.

**CI**
- If every check fails within seconds and shows no logs, the fault is the runner or the GitHub
  account, not the code. It happened on 2026-11-14 and twice on 2026-11-15, and Ismail fixed it each
  time. Tell him once, then re-run the failed jobs when he says. Never push an empty commit to
  retry.
- One test has failed once in a full local run and passed alone and in CI:
  `test_phase8fh5_control_plane::test_user_dispute_is_separate_and_postgres_plan_uses_existing_indexes`.

**Tests that fail when something new is not registered**
- A new `/api/admin` route must be added to the frozen inventory `STAFF_API_ROUTES` in
  `apps/admin_panel/tests/test_l14_two_step.py`.
- A new console POST route must be in the AI helper's action table or its "never" list
  (`apps/admin_helper/actions.py`), or `test_l16_coverage.py` fails.
- A new person-page tab in the console must be added to the expectations in
  `apps/admin_panel/tests/test_phase_j64_person_profile.py`.
- A new Redis channel is added in three places together (plan 1.5 rule 8); a Go test compares the
  lists.
- A change to the helper's notes needs `python manage.py build_helper_instructions`; a test fails
  when `INSTRUCTIONS.txt` is stale. A package that changes behaviour the notes describe updates the
  matching file in `skill/knowledge/`.

**Test helpers**
- Staff: sign in with `apps/admin_panel/tests/two_step_helpers.staff_login(client, user)`. Never
  `force_authenticate` on a staff route and never turn the gate off. The staff API is session-only;
  bearer tokens open no staff route.
- Any test that posts a parcel or writes payout setup over HTTP creates the user with
  `is_email_verified=True`.
- The acceptance world: `backend/monolith/apps/core/tests/l10_world.py`.

**PostgreSQL and Django traps met during the build**
- `select_for_update()` with `select_related(...)` locks the joined rows too. Use
  `select_for_update(of=("self",))` when only the main row should be locked.
- A `CHECK (x >= 1)` passes when `x` is NULL; a both-or-neither constraint needs an explicit
  not-null test.
- DRF wraps error values in lists, so `None` in a `ValidationError` payload renders as the string
  "None". Leave the key out instead.
- Lock order in the AI helper: the admin user row, then the active settings revision, then key rows,
  then prepared-action rows.
- "Ask for a new upload" in the verification inbox is stored as status `rejected` with
  `outcome: resubmission_requested`, because the Go service owns the ID status values. Never add an
  ID status in Django.
- A whole-route update of a journey that omits the price fields clears the price; the app always
  resends them.

**Flutter test traps**
- The test font is Ahem, every glyph one em wide, so overflow with long strings can be an artefact;
  wrap with `Flexible` anyway.
- To reach the end of a lazy list in a test, scroll in steps of 80% of the viewport; jumping to the
  maximum extent never converges. Call `ensureVisible` before tapping a row that
  `scrollUntilVisible` found.
- Screenshots come from a throwaway widget test that loads the real fonts and writes PNG files. Do
  not commit it. Console screenshots come from a live-server test driven by Playwright.

**Geography**
- Every French commune and Spanish municipality has coordinates (PR #27). Refresh only coordinates
  with `tools/geography/normalize_sources.py --download --supplement-coordinates ...`; a full rebuild
  pulls newer upstream data and is not needed.

## 11. What the other account needs

- Write access to the GitHub repository `is-bo/shiptripis`, given by Ismail.
- CI runs on the repository's own GitHub Actions; nothing to set up.
- The provider keys, the production host and the Firebase project are Ismail's. No task in section
  5 needs them: everything runs in test mode with the mock payment rail.
