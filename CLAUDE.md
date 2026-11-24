# Wassla: instructions for every agent

Wassla (repository `shiptripis`; earlier names ShipTrip and Waçla) is a marketplace where a sender's
parcel travels with a traveler who is already making the trip. Since 2026-11-13 it targets **fast
delivery**: urgent parcels, mostly on flights and drives made the same day. "Same day" is the target,
not a rule the app enforces.

These rules hold for any agent working here (Claude Code, Codex or another). `AGENTS.md` points to
this file. There is no longer a split between a frontend owner and a backend owner: since 2026-11-11
the owner assigns all work, backend included, to whichever agent runs the task.

**Ismail is the owner.** Whoever runs a session acts for him. Product decisions, money rules, scope,
and deploying stay his.

## Read first

1. `HANDOFF.md`: where the work stands, what is next, the owner's decisions and the open items.
2. `docs/WASSLA_L_SERIES_PROGRESS.md`: the live board and every finished package's handoff notes.
3. For the topic you touch:
   - `docs/SHIPTRIP_V1_SPEC.md`, the V1 specification;
   - `docs/WASSLA_DISCOVERY_PRO_SPEC.md`, the owner-approved addendum, which overrides the V1
     specification for the topics it covers;
   - `docs/WASSLA_DISCOVERY_PRO_PLAN.md`, the work packages, their order, model and effort, the rules
     every package follows (section 1) and the decisions (section 5).

Authority, highest first: the owner's latest instruction, the addendum, the V1 specification, then
code, comments and older documents. `docs/IMPLEMENTATION_STATUS.md` and the `docs/PHASE_*.md` files
record what was built. They never replace a specification.

## Hard rules

- **Never deploy** without Ismail's explicit approval.
- Work goes to `main` (the working branch since 2026-11-16; the old `main` is kept as `main-old`):
  one package or task per branch, one pull request into `main`. Only docs-only board and plan commits go to it
  directly.
- **Merge only when every CI check is green, "Schema drift" included,** and the gate review is
  recorded on the pull request (plan 1.6).
- Never skip, delete or weaken a test to get green. A test that encoded a rule the specification has
  since changed is rewritten to the new rule, and the pull request says which and why.
- **Use the model and effort the plan gives for each package, exactly** (plan 1.2 and section 3). For
  new work the same rule decides: the strongest model for anything that touches matching, money,
  codes or staff authority; the lighter model for the rest; never low effort.
- **Parked scope is not built.** Professional transporters, the manifest dashboard, custody history
  and courier handoff are parked for a later subdomain. Do not start them and do not leave hooks for
  them. Their complete plan is `docs/parked/WASSLA_PROFESSIONAL_AND_COURIER_PLAN.md`.
- **There are no real users and the app has never been in production.** Spend nothing on legacy data,
  backward compatibility with old clients, tombstone routes or data-migration notes. One caution
  stays: a table or column is dropped only in a cleanup task Ismail has approved, never inside a
  feature.
- Do not fake payment, verification, delivery or payout success in the client. The server decides.
- When a rule cannot be built as written, or a change would alter a money, code or matching result,
  stop and ask instead of guessing (plan 1.7).
- Wording with Ismail: the requirements document of 11 November 2026 is "the cahier des charges".
  Do not use the word "partner".

## Models: who plans, who builds, who reviews

Ismail's rule since 2026-11-24, for every code change, however small:

- **Plan first.** A Claude Opus 5.5 agent at extra-high effort investigates and writes the
  implementation plan. The plan splits the work into packages and gives each package a builder model
  (Claude Sonnet or Claude Opus) and an effort (medium, high or extra high, never low), chosen by
  difficulty and by the "strongest model" rule above. It aims for the best result in the most
  efficient way.
- **The lead session coordinates and does not code.** It hands each package to its builder agent,
  reviews the result, runs the gate and merges. Product, money, code-rule and matching questions the
  plan raises go to Ismail before building (plan 1.7).
- **Astra 6.2 (OpenAI) thinks, it does not write product code.** It is the strongest reasoner after
  Claude Fable, but its code is poor. Use it to save usage on read-only thinking work: the second
  independent gate pass (races, authorization, idempotency, money, privacy), root-cause
  investigations and plan critiques. Ismail runs it himself: the lead writes a self-contained prompt
  for him to paste. Astra's report is a claim, not proof. The lead verifies every finding against the
  code, and a real finding goes back to the package's builder to fix.

## How work is done

1. Read the board. Take the next package or the task Ismail gave. One at a time.
2. Branch from the tip of `main`. Build that package and nothing else.
3. Run every check of plan 1.4 that applies. The whole suites, not only the new tests.
4. Write `docs/PHASE_<id>_<NAME>.md`, add a dated entry at the top of
   `docs/IMPLEMENTATION_STATUS.md`, and fill in the package's handoff block on the board.
5. Open the pull request into `main`, listing each "Done when" line with its
   evidence.
6. Gate review (plan 1.6), recorded on the pull request: every "Done when" line, nothing outside the
   package's scope, a second independent pass on races, authorization, idempotency and money for
   packages on the strongest model (by Astra 6.2 when available, see "Models" above), and screenshots in English and Arabic at 360 px for every new
   screen.
7. Merge when all checks are green. Then update the board in a docs-only commit.

## Quality bar

Ismail's words: impeccable user experience; clean code, which includes removing dead and messy code;
location, finance and admin-control logic airtight. A package removes what it replaces in the same
pull request. No commented-out code, no parameter "for later", no second implementation of a rule
that already has a home.

## Product invariants

- EUR integer cents are canonical. DZD exists only as a Chargily or manual-settlement
  representation, converted on the server and snapshotted.
- A journey is an ordered list of legs: flight, drive, or sea (sea is built and switched off).
  Flight and sea legs need an approved ticket; the one rule lives in `apps/trips/proofs.py`.
- A traveler passes the ID check before publishing a journey. A sender confirms their email before
  posting a request; payout setup needs a confirmed email too.
- The sender proposes first. Boost cannot bypass compatibility. "I can carry this" is a signal of
  interest, not a proposal.
- A traveler may list a price per kg and a minimum per parcel; the offer is pre-filled and still
  negotiable, Wassla's minimum applies, and the fee is on top.
- Exact locations stay hidden until the deal is funded.
- The traveler can never retrieve the delivery code, and it stays locked for 30 minutes after pickup.
  Final delivery is the traveler entering the recipient's code.
- Payout waits 48 hours after delivery, and a dispute freezes it.
- Progress reports, problem reports and schedule changes sit beside the deal: they never write
  `Deal.status`.
- Staff sign in with a second step. A new staff action writes `AdminAuditLog` with actor, target,
  before, after and a required reason.
- A parcel is named by its tracking number (`apps/parcels/tracking.py`), never by a record id, and the
  number never appears on a public or guest surface.
- Kaba/ProductRequest is not active.
- Launch countries: Algeria, France, Spain and Germany.

## Engineering rules

- The server enforces every rule; the app mirrors a rule only to avoid offering what the server
  would refuse.
- Financially important operations are idempotent, transactional and auditable.
- Django owns migrations. After a migration run `task check-drift` in `backend/` and commit the
  regenerated contract in the same pull request.
- A new switch is read from the marketplace policy on the server at the moment of the action
  (`apps/core/marketplace_policy.py`); switched off, the capability answers a stable code.
- Every public payload is built from an explicit allowlist and has a privacy test.
- Every user-facing string exists in English, French and Arabic (Modern Standard Arabic).
- Critical delayed jobs survive Redis and process restarts.
- Guardrails the code cites as `CLAUDE.md G1` to `G6b` (from an earlier version of this file):
  **G1** WebSocket fan-out by pub/sub with delivery receipts and presence keys before the push
  fallback; **G2** 30 seconds of JWT clock leeway on both the Django and Go sides; **G3** the schema
  drift gate re-exports `schema.sql` and regenerates sqlc before diffing; **G4** object storage only
  through the S3-compatible abstraction; **G5** mutual TLS for gRPC in production, 16 MB message
  limit on both sides; **G6** Redis publish only after commit, with a `PublishedEvent` row (**G6b**)
  so a missed delivery is detected.

## Mobile rules

- Main navigation is Home, Deliveries, Chat and Profile. Notifications live in the header bell.
- A traveler's trips and the parcels they carry are in the same Deliveries experience.
- Nothing may hide behind the bottom navigation: check forms, lists, maps, chat, the keyboard,
  sheets, small phones, Android gesture navigation, the iPhone home indicator, landscape and Arabic
  right-to-left.
- Loading, empty, error, offline and validation states are designed, translated and accessible.
