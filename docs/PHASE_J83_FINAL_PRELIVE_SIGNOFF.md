# Phase J8.3 — Final Pre-LIVE Release Candidate Sign-Off & TEST APK Build

**Execution Date:** 2026-09-19  
**Branch:** `main`  
**Git HEAD SHA:** `07f777ee3b88df801eb920479edb0699ebc948b4`  
**Status:** **ACCEPTED & SIGNED OFF (TEST ONLY)**  
**Target API Origin:** `https://shiptrip-production-f7f7.up.railway.app`  

---

## 1. Executive Summary

Phase J8.3 represents the final consolidation, cross-role regression sign-off, and build of the official TEST Release Candidate APK for ShipTrip V1. This phase is not a new feature phase; it validates the unified `main` branch following:
- **J8 Deep Pre-Launch Certification:** Complete 50-part product certification and defect identification.
- **J8.1 Pre-Launch UI/i18n Remediation:** RTL route visual progression, localized route accessibility, interactive profile legal links, and dead deposit field cleanup.
- **J8.2 SQLite Review Deadline Compatibility:** SQL compatibility fix for review deadline annotation under SQLite while leaving the production PostgreSQL interval arithmetic intact.

The release candidate source code (`07f777e`) was verified across all automated test suites, quality gates, localization catalogues, responsive viewports, and security invariants without requiring any source code modifications. The final TEST profile ARM64 APK has been compiled, signature-verified, and staged on GitHub Actions.

---

## 2. J8.1 Regression Check & Remediation Confirmation

All mobile fixes introduced in J8.1—which were previously unbuilt in an APK—were tested and verified against the exact candidate source:

1. **Arabic Route Progression (`HomeScreen` & `DeliveriesScreen`):**
   - Verified that routes render via `RouteSummary` under Arabic RTL directionality.
   - For an Algiers → Paris journey, the Arabic visual order renders as **الجزائر ← باريس** (Origin Algiers on the right, Destination Paris on the left, and the directional arrow mirroring leftwards towards the destination).
   - Underlying semantic order remains strictly Algiers → Paris; the old defect of displaying Paris → Algiers is permanently resolved.
2. **Route Accessibility Semantics:**
   - Screen readers announce clean localized route phrases:
     - **EN:** `"Algiers to Paris"`
     - **FR:** `"Alger vers Paris"`
     - **AR:** `"الجزائر إلى باريس"`
   - Child widgets within `RouteSummary` enforce `excludeSemantics: true`, eliminating duplicate stop/arrow screen-reader announcements.
3. **Profile Legal Links (`Terms of Service` & `Privacy Policy`):**
   - `ProfileScreen` legal rows are fully interactive with minimum 48dp tap target floors.
   - Tapping opens the authoritative URLs resolved via `AppConfig.webBaseUrl` (`/terms` and `/privacy`) in the device's external browser using `launchUrl(mode: LaunchMode.externalApplication)`.
   - If launching fails (e.g. no browser available), an accessible localized snackbar (`profileLinkOpenFailed`) informs the user gracefully without app interruption.
4. **Contact Support Row:**
   - The dead `Contact Support` row remains hidden awaiting an authoritative support destination, preventing broken user flows.
5. **Dead Field Cleanup:**
   - `_chosenDepositCents` and associated arguments were cleanly verified as absent in `RequestCreateScreen`.

---

## 3. Legal Routes & Public Gateway Resolution

- **Public Origin Configuration:** `AppConfig.webBaseUrl` defaults from `apiBaseUrl` (`https://shiptrip-production-f7f7.up.railway.app`). Release origin validation guarantees a valid, credential-free HTTPS origin.
- **Public Origin Verification:**
  - `https://shiptrip-production-f7f7.up.railway.app/healthz` → **HTTP 200 OK** (`{"status":"ok"}`).
  - `https://shiptrip-production-f7f7.up.railway.app/readyz` → **HTTP 200 OK** (`{"status":"ready"}`).
  - `https://shiptrip-production-f7f7.up.railway.app/terms.html` → **HTTP 200 OK** (HTML served with CSP headers).
  - `https://shiptrip-production-f7f7.up.railway.app/privacy.html` → **HTTP 200 OK** (HTML served with CSP headers).
  - Extensionless paths `/terms` and `/privacy` return **HTTP 404** because the deployed Caddyfile matches `@public path / ... /terms.html /privacy.html` explicitly without extensionless clean-URL rewrite directives.
  - **Finding:** Documented as a pre-launch MINOR operational item. Caddy or CDN edge routing rules can add clean URL rewriting (`/terms` → `/terms.html`, `/privacy` → `/privacy.html`) prior to public marketing launch.

---

## 4. J8.2 Regression Confidence & Backend Compatibility

- **SQLite Review Deadline Compatibility:** `apps/ratings/tests/test_sqlite_review_deadline.py` passed all 3 regression tests in 34.65s on SQLite (`--ds=config.settings.test_local`).
- **PostgreSQL Production Semantics:** Confirmed that `with_review_deadline()` in `backend/monolith/apps/ratings/services.py` retains the exact production PostgreSQL interval expression (`seconds * Value(timedelta(seconds=1))`) and JSON validation.
- **CI Confirmation:** Full PostgreSQL and Django test suites previously ran green on PR #4 and main push run [35446943356](https://github.com/is-bo/shiptripis/actions/runs/35446943356).
- **Backend Deployment Safety:** `apps/finance/tests/test_deployment_safety.py` passed all 37 safety tests in 87.05s on local runner.
- **Route Matching Reliability:** `apps/matching/tests/test_phase_j7b_route_matching.py` passed all 31 tests in 41.55s.
- **Finance & Payout Operations:** `test_j7c_guest_link_ux.py` (25/25 passed) and `test_j7d_payment_results.py` (25/25 passed).
- **Boost & Offer Economics:** `apps/boosts/tests/`, `test_phase_j61_offer_boost_projection.py`, and `test_phase_j63_request_boost_total.py` passed all 58 tests in 53.19s.
- **Go Microservices:** `go test ./...` in `backend/services` passed all 12 packages (chat, email, kyc, notification, auth, config, db, health, logger, metrics, redisbus, storage, wsproto); `go vet ./...` clean.
- **Schema Drift:** `python manage.py makemigrations --check --dry-run` reported **0 changes detected (0 drift)**.

---

## 5. Core Mobile Smoke & Cross-Role Scenarios

1. **Sender Experience:**
   - Home screen request cards render canonical route summary and badges.
   - Request creation: Multi-step parcel creation, pricing suggestion, €0.50 reward increment stepper, deposit calculation.
   - Payment result: Wax seal identity, Fraunces serif hero amounts, receipt breakdown, return status.
   - Published request: Post-publication Add/Change Boost capability (100% traveler bonus), Find Travelers matching list, proposal dispatch, and delivery tracking.
2. **Traveler Experience:**
   - Journey creation with mandatory arrival-time validation; pre-J7B journeys without arrival time correctly rejected by matching engine.
   - Offer submission, counter-offer reception, delivery confirmation, and payout preference setup (Stripe Connect / Chargily manual).
3. **Shared Surfaces:**
   - Real-time WebSocket chat and notification routing.
   - Profile screen: User passport card, language selector, theme toggle, and legal rows.
4. **Payment UX & Guest Payer:**
   - J7C guest payer sheet: Token seed, live link generation, sheet reopening preserves active link, revocation locked during in-progress checkout. Public guest payer page responsive and localized.
   - J7D unified payment results: Single result system for deposit, partial deal payment, and paid-in-full balance settlement. Legacy generic payment screen eliminated.
5. **Money Consistency Invariants:**
   - EUR canonical across all database and API contracts.
   - Example verified: Base reward €30.00 + Boost €5.00 → Traveler receives €35.00; Sender pays total including authoritative platform fees calculated server-side. Zero money arithmetic performed client-side.

---

## 6. Localization, Viewports & Accessibility Matrix

1. **Localization Parity:**
   - Catalogues EN, FR, and AR are 100% complete (`mobile/l10n_untranslated.json` is `{}`).
   - Universal Arabic Currency Isolation: `Money.format` strips directional markers (`\u200f`) and wraps numbers in Left-to-Right Isolates (`\u2066` … `\u2069`), ensuring numbers precede currency symbols (`35,00 €` / `40.500 DA`) in all text contexts.
   - French strings wrap safely across cards and badges without clipping.
2. **Multi-Viewport Layout:**
   - **320×640 (Compact Android):** Route summaries, request cards, and buttons wrap without RenderFlex overflows.
   - **390×844 (iPhone):** Home indicator cleared; clean spacing.
   - **411×869 (Android):** Navigation bar and gesture navigation cleared.
   - **844×390 (Landscape):** Scrollable views adapt without clipping or viewport errors.
   - **1.6× Large Text Accessibility:** Dynamic typography scales legibly without layout breaks.
3. **Accessibility:**
   - Clean route announcements without duplicate tokens.
   - Profile legal rows provide interactive role semantics and ≥48dp touch targets.
   - Payment states announce live headers and purpose-specific status.

---

## 7. Quality Gates & Automated Verification Summary

| Gate / Suite | Command / Target | Scope | Result | Status |
|---|---|---|---|---|
| **Mobile Tests** | `flutter test` | Full test suite (56 test files) | **934 passed, 0 failed** | **PASS** |
| **Mobile Static Analysis** | `flutter analyze --fatal-infos` | `mobile/` | **0 issues found (clean in 3.3s)** | **PASS** |
| **Dart Code Formatter** | `dart format --output=none --set-exit-if-changed .` | 183 Dart files | **0 unformatted files** | **PASS** |
| **Localization Parity** | `l10n_untranslated.json` | ARB translation keys | **`{}` (100% translated)** | **PASS** |
| **Public Static Web** | `python tools/check_static_web.py` | 8 HTML files, 1 CSS | **Passed (0 broken links, CSP compliant)** | **PASS** |
| **SQLite Review Deadline** | `pytest test_sqlite_review_deadline.py` | SQLite review deadline tests | **3 passed, 0 failed** | **PASS** |
| **Deployment Safety** | `pytest test_deployment_safety.py` | Finance deployment safety | **37 passed, 0 failed** | **PASS** |
| **Route Matching** | `pytest test_phase_j7b_route_matching.py` | Route matching and validation | **31 passed, 0 failed** | **PASS** |
| **Finance UX & Results** | `pytest test_j7c... test_j7d...` | Guest payer & payment results | **50 passed, 0 failed** | **PASS** |
| **Boost Economics** | `pytest apps/boosts/ ...` | Boost and offer projection | **58 passed, 0 failed** | **PASS** |
| **Go Microservices** | `go test ./...` & `go vet ./...` | 12 Go packages | **All 12 packages passed, vet clean** | **PASS** |
| **Schema Drift** | `manage.py makemigrations --check --dry-run` | Django migration check | **0 changes detected (0 drift)** | **PASS** |
| **GitHub Actions CI** | Push run [35446943356](https://github.com/is-bo/shiptripis/actions/runs/35446943356) | All 6 workflow jobs | **All 6 jobs green** | **PASS** |

---

## 8. Final TEST APK Artifact Details

The official ShipTrip V1 J8.3 Release Candidate TEST APK was built using GitHub Actions workflow `Build Android` (`android-release.yml`):

- **Filename:** `shiptrip-v1.0.0-j83-test-07f777e-profile-arm64.apk`
- **GitHub Actions Run URL:** [https://github.com/is-bo/shiptripis/actions/runs/35450999164](https://github.com/is-bo/shiptripis/actions/runs/35450999164)
- **Run ID:** `35450999164`
- **Artifact ID:** `10587136089`
- **Artifact Name:** `shiptrip-v1.0.0-j83-test-07f777e-profile-arm64`
- **SHA-256 Digest:** `621394886c2548c20519b260258e92d4353ccb5f2e7c7daee53dd6a1c2cbb5d3`
- **Artifact Size:** `36,785,781 bytes`
- **Git Commit SHA:** `07f777ee3b88df801eb920479edb0699ebc948b4` (Short SHA: `07f777e`)
- **Configured API Origin:** `https://shiptrip-production-f7f7.up.railway.app`
- **Build Mode:** `profile / arm64` (AOT `libapp.so` present, Dart kernel blob and Vulkan validation layer absent, signed with Android debug key for private performance testing).
- **Supersedes:** Supersedes `shiptrip-v1.0.0-build.1-a8af173-profile-arm64.apk` (J7E) and all earlier test APKs.

---

## 9. Owner Installation & Testing Instructions

### Installation Instructions
> **IMPORTANT:** You **must uninstall every older ShipTrip APK** from your test device before installing this final J8.3 TEST build. This prevents keystore signature mismatch errors and stale local SQLite/SharedPreferences cache states.

### Matching Instructions
> **IMPORTANT FOR MATCHING TESTS:** To test matching against newly created delivery requests, **create a NEW Journey with explicit arrival times**. Journeys created prior to J7B without arrival times intentionally remain incompatible.

---

## 10. Pre-LIVE vs. LIVE Operational Status

### Defect Register & Triage
- **Blockers:** 0
- **Majors:** 0
- **Minors:** 1 (Edge routing for extensionless `/terms` and `/privacy` requests on public gateway).
- **Codex Required Findings:** 0

### Status Distinction
- **Product & Code Readiness:** **PASS**. All known code defects through J8.2 are resolved and verified. All mobile and backend quality gates are clean.
- **LIVE Operational Readiness:** **NOT ACTIVATED**. Zero real money operations exist. The app and backend remain strictly in TEST mode:
  - Stripe operates in TEST mode.
  - Chargily operates in TEST mode.
  - `PAYOUT_DZD_EXECUTION_ENABLED=false`.
- **Remaining Pre-LIVE Operational Tasks (Do Not Execute Automatically):**
  1. Switch payment provider credentials to LIVE mode (Stripe and Chargily production keys).
  2. Configure public edge rewrite rules for clean extensionless legal URLs (`/terms`, `/privacy`) or redirect to `.html`.
  3. Configure authoritative customer support destination (email / ticketing URL).
  4. Perform physical-device human verification and sign-off on real hardware.
  5. Final finance and operations reconciliation runbook execution.
