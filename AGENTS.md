# Wassla Codex Instructions

Codex is the primary engineering owner. Before substantial work, read:

- `docs/SHIPTRIP_V1_SPEC.md`
- `docs/IMPLEMENTATION_STATUS.md`

The specification is authoritative when legacy code, documentation, comments, tests, or previous assumptions conflict with it, unless the user explicitly overrides it.

## Primary ownership

Codex primarily owns Django/backend, Go services, database schema and migrations, APIs, matching and geospatial logic, payments, payouts, disputes, concurrency, security, performance, infrastructure, integrations, tests, and release engineering.

## Permanent engineering rules

- Inspect existing code before editing and preserve useful existing architecture.
- Prefer safe, staged migrations over destructive rewrites. Django remains migration authority.
- After schema changes, regenerate schema and sqlc contracts and run schema-drift checks.
- The server is authoritative for money. Financially important operations must be idempotent and auditable.
- Capacity reservations and financial state transitions must be transactional.
- Critical delayed jobs must survive Redis and process restarts.
- Never use mock payments in production.
- Write and run tests with implementation.
- Before completion, review security, authorization, races, performance, migrations, and regressions. Use review or subagents where useful, fix valid findings, and rerun relevant gates.
- Update `docs/IMPLEMENTATION_STATUS.md` after meaningful work; it tracks progress but never replaces the specification.

## Core invariants

- EUR is canonical. DZD exists only as a Chargily or manual-settlement representation; FX is server-controlled and snapshotted.
- A Journey consists of ordered legs. V1 transport modes are FLIGHT and DRIVE, and only flight legs require transport proof.
- Traveler KYC is required before publishing a journey.
- Capacity is allocated per segment.
- The sender proposes first. Boost cannot override compatibility.
- Exact locations stay hidden until the deal is funded.
- A traveler can never retrieve the delivery code, which remains hidden for 30 minutes after pickup.
- A dispute freezes payout, and payout waits 48 hours after delivery confirmation.
- ProductRequest/Kaba is not active in V1.

## Discovery and professional delivery (L-series)

Before any work on Home discovery, sea legs, traveler pricing, professional transporters, custody,
courier handoff or progress reminders, also read:

- `docs/WASSLA_DISCOVERY_PRO_SPEC.md` (owner-approved addendum; overrides the V1 specification for the topics it covers)
- `docs/WASSLA_DISCOVERY_PRO_PLAN.md` (work packages, order, model and effort per package, and the checks that close each one)
- `docs/WASSLA_L_SERIES_PROGRESS.md` (the live board and each finished package's handoff notes; read it first, and fill in only your own package's block)

Work happens on `feature/discovery-professional-delivery`, one package per pull request into that
branch. Never merge into `main` or deploy without the owner's explicit approval. For this series the
owner assigned backend packages to Claude agents through the orchestrator. Until package L3A is
merged the code still enforces FLIGHT and DRIVE only, with proof on flight legs only.
