# ShipTrip H8A — final release report

This report distinguishes the reviewed/deployed runtime commit from the later
documentation-only completion commit. The latter does not change application code.
H8A releases readiness controls into the existing TEST-configured environment;
H8B external LIVE activation is not performed.

| # | Required result | Evidence / outcome |
| --- | --- | --- |
| 1 | Starting SHA | `7c67093e88ac9b89386674384158fddeb7147605` |
| 2 | Branch | `codex/phase-h8a-production-readiness` |
| 3 | Files changed | 42 files in the reviewed release; completion adds this report. Full changed-path list follows. |
| 4 | Schema/migration | **NO** schema, migration, backfill or historical financial rewrite. 74 migrations verified; schema SQL matches. |
| 5 | H5.2 blocker consumption | Overview and H5 attention drilldown consume the shared PRE-H8 safe payout classifier under read-only snapshots. |
| 6 | Needs Attention grouping | Traveler, Finance, provider and nullable/unknown owner; null displays “Payout review required” without inventing an owner. |
| 7 | Duplicate behavior | One payout contributes at most one primary blocker; overlapping holds/disputes/setup do not multiply the headline. Refund failures remain separate issues. |
| 8 | Mode model | Hosting/security environment is separate from `PAYMENTS_ENVIRONMENT=test|live`; explicit money intent defaults TEST. |
| 9 | Explicit LIVE guard | LIVE requires explicit intent, coherent configured keys/origins/Connect scope, payout profiles and enabled/verified email configuration. Key replacement alone fails closed. |
| 10 | Mixed modes | Provider transports, webhook/poll evidence, checkout history/credits/Boost, refunds, accounts and payout actions reject conflicting mode authority. |
| 11 | Stripe readiness | Hosted server-priced Checkout and official API origin; LIVE platform activation/credentials remain H8B prerequisites. |
| 12 | Stripe webhook mode | Verify raw signature first, require matching boolean event mode, persist/ignore foreign events; duplicates remain idempotent. |
| 13 | Connect readiness | Separate platform/Connect signing secrets, explicit expected mode, platform identity and bound account readiness. H8B must onboard LIVE accounts. |
| 14 | Chargily readiness | Coherent key/API mode, fixed DZD representation and snapshotted server FX. LIVE merchant activation remains external. |
| 15 | Chargily mode protection | Exact TEST/LIVE API base must agree with key and intent; signing override is empty or equals API secret; foreign evidence cannot authorize money. |
| 16 | Stripe payout readiness | Existing policy/feature gates, source authority, protections/arrival floor, holds, idempotency and audit remain required; LIVE money POSTs first verify platform readiness. |
| 17 | Manual DZD readiness | Explicit mode replaces old TEST literal; execution still requires flag, authority, claim/version gates, FX/evidence and actual-settlement attestation. Flag stays false. |
| 18 | Email dependency verdict | **Launch-critical** for sender verification and recipient delivery-code obligations. Still disabled. H8B must verify sender/SMTP and review 77 pending obligations observed in the initial audit before enabling. |
| 19 | Push readiness | Existing FCM configuration retained/enabled; real device/project alignment remains H8B/mobile validation. Push is not payment authority. Invalid enabled FCM credentials can fail the combined worker startup; disable the optional integration if needed. |
| 20 | Mobile API readiness | Release requires explicit HTTPS API/KYC origins; debug retains emulator convenience. WebSocket scheme follows the API. Origin test and full 528-test Flutter suite pass; no release APK built. |
| 21 | Public-origin matrix | Canonical origin `https://shiptrip-production-f7f7.up.railway.app`; full API/WS/webhook/return/refresh/email/admin/hosts matrix in readiness §6. |
| 22 | Railway audit | Existing project/service retained. Both provider credential classes TEST; Finance true, DZD false, email false. Deployment changes only release ID and explicit `PAYMENTS_ENVIRONMENT=test`. |
| 23 | Critical flags | Profiles/Finance/Connect/Connect payouts enabled; DZD and non-Stripe EUR/legacy/mock execution disabled; email disabled/unverified; FCM enabled. Versioned Stripe/Chargily/new-checkout/auto-Stripe policy audited enabled. Full source/ordering matrix in readiness §7. |
| 24 | Startup/readiness | Contradictory configuration fails startup without provider I/O. `/healthz` is liveness; `/readyz` checks DB/migrations/shared cache. Optional external provider connectivity is not silently made a readiness dependency. Object/action guards fail closed before money I/O. |
| 25 | Historical separation | Retain TEST and legacy provenance; no relabel/reset. Wrong-mode history cannot fund/refund/settle in LIVE. Existing TEST work must be reconciled before H8B switches the single-mode service. |
| 26 | Finance default after LIVE | Defaults to explicit LIVE intent; deliberate TEST/legacy audit scopes remain. Recent activity is restricted by persisted payout/refund mode. |
| 27 | Admin mode safety | Persisted mode displayed on financial details; cross-mode money actions refused while existing permissions/version/claim checks remain. Safety holds may still be opened on history. |
| 28 | H8B dashboard prerequisites | LIVE Stripe platform/Connect activation, eligible accounts/countries, separate endpoints/secrets/API versions; LIVE Chargily merchant key/signing/callback; verified email sender/SMTP; approved DZD operating process. No dashboard changed in H8A. |
| 29 | H8B exact sequence | Freeze release → backup/restore evidence → freeze new TEST work and reconcile obligations → resolve email backlog → Stripe LIVE setup → Chargily LIVE setup → stop combined service and stage coherent variables → one reviewed restart with execution off → no-money validation → deliberate collection/execution enablement → close TEST endpoint overlap, preserving records. Full executable contract/event subscriptions: readiness §9. |
| 30 | Rollback | Before LIVE money: stop service and restore entire prior TEST artifact/config bundle. After LIVE money: retain LIVE keys/history/reconciliation, disable new collection/execution and fix forward on an H8A-capable build. Never restore an old DB over LIVE activity or downgrade to unguarded code. |
| 31 | H8C recommendation | Prefer zero-money H8B checks then monitor the first genuine customer transaction. An optional controlled real transaction requires separate owner consent, consenting parties, minimum server-valid amount and normal delivery/protection/settlement timing; no mock DZD or accelerated clocks. |
| 32 | Codex fast tests | 55 guards/config passes; focused PostgreSQL blocker/history/manual checks passed; corrective targeted tests passed. Ruff/whitespace, Flutter origin test and three-file analysis passed. Commands/timings in readiness §12; broad suites delegated. |
| 33 | Gemini prompts | Three exact-SHA prompts issued: initial full verification; affected three-module rerun; final currency-only fixture rerun. Retained in `.tmp/H8A_GEMINI_VERIFIER_PROMPT*.md`. |
| 34 | Gemini results | Round 1: 1,932 Django passes, 3 failures, 34 intentional legacy skips; 528 Flutter passes. Round 2: all 56 H5/H5.1 tests passed; 16 currency fixture failures identified. Round 3: all 34 currency tests passed. Every original failure resolved; no repeat full-suite claim. |
| 35 | CI | **PASS**, all six jobs. Full Django: **1,936 passed / 34 intentional legacy skips**, 1,756.60s — [GitHub run 34755880830](https://github.com/is-bo/shiptripis/actions/runs/34755880830). Single explicitly dispatched release gate; no duplicate automatic run on main promotion. |
| 36 | Implementation SHA | Initial feature: `34bff5bc8859c7336111f312a88564b4c62af019`; final Gemini-verified implementation: `c3a4e23ae28d0ba7dce8c4c2c49dfa14e11ba5cb`; reviewed/deployed release including verification docs: `4ec23a17a41a150ba5afe58d410ed5c3d6722631`. |
| 37 | Final main | Completion documentation commit atop `4ec23a1`; exact SHA is returned in the final task response. Local main and origin/main verified equal. No runtime change after the reviewed deployment. |
| 38 | Branch cleanup | Deleted locally and remotely after fast-forward promotion of the reviewed commit |
| 39 | TEST deployment | `a400f0d4-e4cd-4b85-9817-35ab03f79e35`; release `v1.0.0-rc.30+4ec23a1`; **SUCCESS**. Uploaded exact clean Git archive; deployed runtime hashes match reviewed commit. |
| 40 | `/healthz` | **200**, correct `v1.0.0-rc.30+4ec23a1` release |
| 41 | `/readyz` | **200**, database/migrations/rate-limit cache all `ok`, correct release |
| 42 | Migrations/workers | Zero pending migrations; Gunicorn, Caddy, Redis, finance/reservation workers, KYC gRPC and all four Go services present under the process supervisor |
| 43 | H5 integrity | **ok**; one read-only TEST/30-day snapshot at `2026-09-13T12:38:18.505573+00:00`. |
| 44 | Funding difference | **0** EUR cents. |
| 45 | Liability difference | **0** EUR cents, both traveler-state and dashboard comparisons. |
| 46 | Revenue difference | **0** EUR cents in the platform-recognition partition. |
| 47 | Refund difference | **0** EUR cents. |
| 48 | Ledger | Net **0 EUR cents**, **0 unbalanced transactions**; all H5 comparison row mismatches zero. Provider physical cash remains explicitly unobserved. |
| 49 | Stripe still TEST | **YES**, runtime key class and Connect expected mode TEST |
| 50 | Chargily still TEST | **YES**, runtime key and API base both TEST |
| 51 | DZD execution false | **YES**, runtime flag false; email also remains false |
| 52 | No LIVE operation | Confirmed: no LIVE API request, checkout, transfer, bank payout, refund, real DZD settlement or money mutation performed by H8A. No email sent or provider dashboard changed. |
| 53 | Remaining prerequisites | H8B BLOCKER: coherent LIVE provider activation/secrets/endpoints, verified email and reviewed backlog, reconciled TEST commitments, backup/recovery evidence. MAJOR: DZD staffing/settlement/refund/evidence approval, actual mobile release/device/FCM and map contract. MINOR: >5,000 attention scopes require narrowing; owner groups share full drilldown; indirect-target activity remains in full audit log. These are activation prerequisites, not unresolved H8A release failures. |

The full readiness rationale, variable matrix, endpoint event lists and staged
cutover/rollback contract are in [PHASE_H8A_PRODUCTION_READINESS.md](PHASE_H8A_PRODUCTION_READINESS.md).

**H8A PASS**

**Ready for Claude H8B production cutover? YES**

“Ready for H8B” permits starting the separately authorized external cutover phase.
It does not assert that LIVE activation prerequisites have already been fulfilled.

Deployed source verification: all ten selected runtime hashes match the exact `git archive`
bytes for the release SHA. The first comparison against raw Git blobs differed because
Windows Git exports configured CRLF line endings; archive comparison resolved this
without a second H5 snapshot or deployment. The final verdict uses the one persisted
snapshot, not a rerun.

## Changed paths

- `backend/.env.example`
- `backend/monolith/apps/admin_panel/console_manual_payout.py`
- `backend/monolith/apps/admin_panel/console_views.py`
- `backend/monolith/apps/admin_panel/finance_dashboard.py`
- `backend/monolith/apps/admin_panel/finance_operations.py`
- `backend/monolith/apps/finance/connect_webhooks.py`
- `backend/monolith/apps/finance/control_plane/attention.py`
- `backend/monolith/apps/finance/control_plane/definitions.py`
- `backend/monolith/apps/finance/control_plane/drilldown.py`
- `backend/monolith/apps/finance/control_plane/snapshot.py`
- `backend/monolith/apps/finance/jobs.py`
- `backend/monolith/apps/finance/mode_safety.py`
- `backend/monolith/apps/finance/payout_accounts.py`
- `backend/monolith/apps/finance/payout_domain.py`
- `backend/monolith/apps/finance/payout_execution.py`
- `backend/monolith/apps/finance/payout_manual.py`
- `backend/monolith/apps/finance/payout_reconciliation.py`
- `backend/monolith/apps/finance/payout_snapshots.py`
- `backend/monolith/apps/finance/providers/chargily.py`
- `backend/monolith/apps/finance/providers/stripe.py`
- `backend/monolith/apps/finance/providers/stripe_connect.py`
- `backend/monolith/apps/finance/services.py`
- `backend/monolith/apps/finance/tests/test_h8a_finance.py`
- `backend/monolith/apps/finance/tests/test_h8a_guards.py`
- `backend/monolith/apps/finance/tests/test_phase8fc_provider_currency.py`
- `backend/monolith/apps/finance/tests/test_phase8fh2_deployment.py`
- `backend/monolith/apps/finance/tests/test_phase8fh4_manual.py`
- `backend/monolith/apps/finance/tests/test_phase8fh51_finance_dashboard.py`
- `backend/monolith/apps/finance/tests/test_phase8fh52_finance_operator_ux.py`
- `backend/monolith/apps/finance/tests/test_phase8fh5_control_plane.py`
- `backend/monolith/config/settings/base.py`
- `backend/monolith/config/settings/connect.py`
- `backend/monolith/config/settings/payments.py`
- `backend/monolith/config/settings/prod.py`
- `backend/monolith/templates/admin/console/finance_detail.html`
- `backend/monolith/templates/admin/console/finance_overview.html`
- `backend/monolith/templates/admin/console/manual_payout.html`
- `docs/IMPLEMENTATION_STATUS.md`
- `docs/PHASE_H8A_PRODUCTION_READINESS.md`
- `mobile/lib/core/env/app_config.dart`
- `mobile/lib/main.dart`
- `mobile/test/core/env/app_config_test.dart`
- `docs/PHASE_H8A_RELEASE_REPORT.md` (completion evidence)
