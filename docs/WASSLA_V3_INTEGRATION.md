# Wassla V3 integration baseline

Prepared on 26 October 2026 on `feature/wassla-v3-baseline`.

## History and scope

The integration starts from V2 `bdec34f3236eb4ddc2c102a80b9a5627808ac634`,
which includes V1 `b215c5936146e2f0045d74c801e70b1b34e7f36b`, and merges
the completed V3 `77245abfbe04de4ce3891a6edf68e1e4bcdd7c8d`. The original V3
was a sibling of V1/V2, so simply pushing `work` would not have supplied their
history. This merge keeps both parents and all three phase commits.

Brand-name conflicts use Wassla while retaining V2 code. The outbox, settings
and URL configuration have identical Python ASTs to V2 after normalizing the
brand name. V2 SMTP safeguards, database rate/send gates, backlog review,
current-capability checks, localized secure invitation landing, transactions,
migrations and fluid email tables are preserved. The V2 schema contract is
unchanged. The Flutter runtime and native assets are byte-identical to V3;
V1 localization tests and its sign-in synchronization fix are retained.

Django and Go default sender display names and examples now say Wassla.
Configured overrides and addresses are preserved. Historical provider account
and checkout descriptions retain V2's Waçla wording because it participates in
fingerprints/idempotent replay. Guest-payment presentation alone converts both
historical brand names to Wassla. The new V2 invitation page inherits the
supplied V3 light/dark logos from the shared shell.

VPS runtime, Compose, Dockerfiles, launchers, security configuration, migrations
and contracts remain V2's implementation. The only VPS differences are the
example sender display name and the landing-page branding assertion.

## Verification

- Full Flutter: 1,082 passed initially; one CPU-budget benchmark failed while
  concurrent Go/container compilation saturated the runner. That unchanged
  benchmark passed in isolation (largest payload 2,963 microseconds, limit
  8,000). Thus all 1,083 tests passed across the full run and focused rerun.
- Flutter analysis with fatal infos and Dart formatting: clean.
- Full Django PostgreSQL suite: **2,529 passed, 34 retired-contract skips,
  zero failures**, in 44m42s.
- Go build, vet and unit/race tests: all 14 test packages passed.
- Full Go integration/race tests: all 14 test packages passed; 353 test/subtest
  passes, no skips, using real local Redis and disposable PostgreSQL. The first
  fixture used an unsupported database name; the final run used the required
  loopback `wacla` fixture without changing its safety guard.
- VPS unit tests: 29 passed.
- Fresh local VPS/backup images: built successfully; all nine integration
  groups passed, including durable PostgreSQL/Redis recreation, concurrent
  migration refusal, both proxy layers, TLS/WebSockets, client-IP throttles,
  non-root/read-only processes, supervisor recovery, localized invitations,
  encrypted backup, isolated restore and corruption/failure refusal.
- All 432 email layout checks passed across every template, EN/FR/AR,
  320/390/800px and normal/inline-only styles with remote resources blocked.
- Static web/edge routing: eight HTML pages, two stylesheets and two Caddy
  configurations passed. Eight globe tests passed.
- Ruff clean. No missing migrations. Migrated PostgreSQL schema matches the
  committed V2 contract after normalizing dump versions/nonces.
- Both V2 translation catalogs retain every entry with only brand substitution.

Detailed local logs and source-preservation evidence are under
`build/integration/` (ignored review artifacts). Historical V3 screenshots
remain under `build/rebrand/`; current email checks also saved screenshots.

Main is untouched. No deployment, production migration, provider activation,
external sending, DNS change or release APK is part of this integration. The
isolated local infrastructure checks do not establish target VPS or external
provider readiness; the existing operator activation gates remain in force.
