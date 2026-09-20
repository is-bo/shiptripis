# Phase J9.4 — Final Post-J9 Release Candidate Verification & TEST APK Build

**Execution Date:** 2026-09-20  
**Branch:** `main`  
**Git HEAD SHA:** `5bf55f1e665e69551ec428570bcb05975ae987f4`  
**Runtime / Deployment Merge SHA:** `61d4419eedb11b864f0efadb14c89978fab38067`  
**Railway TEST Release:** `v1.0.0-rc.44+61d4419`  
**Target API Origin:** `https://shiptrip-production-f7f7.up.railway.app`  
**Status:** **ACCEPTED & SIGNED OFF (TEST ONLY)**  

---

## 1. Executive Summary

Phase J9.4 represents the final consolidation, cross-system regression verification, and packaging phase following the adversarial J9 audit and all subsequent remediation work (J9.1, J9.2, J9.3).

This phase validates the full integration of the codebase on `main`:
1. **Source Integrity:** Verified that product/runtime source code on `main` (`5bf55f1e`) is identical to the reviewed and deployed runtime SHA (`61d4419e`); the difference is documentation-only (`docs/IMPLEMENTATION_STATUS.md` and `docs/PHASE_J93_FINAL_DEFECTS.md`). No source modifications were made during J9.4.
2. **Defect Status:** All 18 findings from the J9 audit across backend, admin panel, and mobile client remain fully resolved:
   - **CRITICAL: 0**
   - **MAJOR: 0**
   - **MINOR: 0**
3. **Comprehensive Quality Gates:** 
   - **Flutter Suite:** All **974 tests passed**; `flutter analyze --fatal-infos` reported **0 issues**; `dart format` reported **188 files unchanged**; localization catalogues EN, FR, AR are 100% complete (`mobile/l10n_untranslated.json` is `{}`).
   - **Django Backend Suite:** **2,245 passed, 34 skipped, 0 failed** under PostgreSQL 16 Alpine in CI run [35509519341](https://github.com/is-bo/shiptripis/actions/runs/35509519341); J9 targeted tests (15/15 passed); deployment safety (40/40 passed); `ruff check backend` clean; schema drift clean (0 drift); `check --deploy` clean under production settings.
   - **Go Microservices:** All 12 packages passed unit, race, and real-Redis integration testing; `go vet` clean.
   - **Edge / Static / Web:** `tools/check_static_web.py` passed (8 HTML, 1 stylesheet, 2 Caddy configs); deployed `/healthz`, `/readyz`, `/terms`, and `/privacy` return HTTP 200 OK.
4. **Final TEST APK:** Built, signed with Android debug certificate, verified, and staged via GitHub Actions workflow run `35511147551`. Supersedes the legacy J8.3 artifact (`shiptrip-v1.0.0-j83-test-07f777e-profile-arm64.apk`).

---

## 2. Source Integrity & Commit Lineage

- **Active Branch:** `main`
- **Working Tree:** Clean (zero uncommitted or untracked changes)
- **Local `main` vs `origin/main`:** In sync (`HEAD == origin/main`)
- **Starting HEAD SHA:** `5bf55f1e665e69551ec428570bcb05975ae987f4`
- **Ending HEAD SHA:** `5bf55f1e665e69551ec428570bcb05975ae987f4`
- **Reviewed Runtime Merge SHA:** `61d4419eedb11b864f0efadb14c89978fab38067`
- **Difference Analysis (`61d4419` .. `5bf55f1`):**
  ```
  docs/IMPLEMENTATION_STATUS.md   | 21 +++++++++++++++++++--
  docs/PHASE_J93_FINAL_DEFECTS.md |  9 +++++----
  2 files changed, 24 insertions(+), 6 deletions(-)
  ```
  The diff is strictly documentation-only. Zero runtime, backend, frontend, configuration, or database files differ.
- **Source Modifications During J9.4:** **NO** (all release gates passed without modifications).

---

## 3. J9 Remediation Regression Matrix

### J9.1 Critical Isolation & Races
| Defect | Severity | Component | Verification Result |
| --- | --- | --- | --- |
| **DEF-ADM-01** | CRITICAL | Admin Authorization | Banned Super, Finance, and Trust staff cannot access Admin HTML console, direct URL deep links, Admin REST API, or Django admin. Banned status immediately revokes active JWT sessions. |
| **DEF-MOB-07** | CRITICAL | Mobile Auth Isolation | Account A logout purges all private ratings and cache state; Account B login never observes Account A data. Stale in-flight responses from User A cannot overwrite User B provider state. |
| **DEF-MOB-08** | CRITICAL | Discovery Pagination Race | In Find Travelers, an in-flight `loadMore` request cannot overwrite a newly completed sort or pull-to-refresh query. Authoritative query state always prevails. |

### J9.2 Economics, Money & Re-Entrancy
| Defect | Severity | Component | Verification Result |
| --- | --- | --- | --- |
| **DEF-MOB-01** | MAJOR | Pricing Quote Invalidation | Changing route, weight, dimensions, dates, deadline, or reward after obtaining a quote immediately invalidates the prior quote. Out-of-order quote responses are discarded. |
| **DEF-MOB-02** | MAJOR | Exact Money Parsing | Strict currency parser accepts `12`, `12.3`, `12.30`, and comma-equivalent (`12,30`); rejects `12.345` and `0.001` without silent rounding. Zero floating-point drift. |
| **DEF-MOB-03** | MAJOR | Offer Accept Mutation Guard | Rapidly tapping Offer Accept triggers exactly one mutation request and one confirmation prompt. |
| **DEF-MOB-05** | MAJOR | Guest Pay Double-Tap Guard | Rapid tapping on Guest Checkout Pay button dispatches exactly one checkout session request. |
| **DEF-MOB-06** | MAJOR | Boost Control Disabling | During boost save operations, all value-changing controls are disabled to prevent stale edits. |
| **DEF-MOB-09** | MAJOR | Form Re-Entrancy Protection | Request create, Journey create, Dispute submit, Rating submit, and Deposit pay forms are guarded against double-submission. |
| **DEF-MOB-14** | MAJOR | Mobile Journey Time Gate | Client rejects past and current departure timestamps prior to dispatching backend requests. |

### J9.3 Timing, Error Copy, Constraints & Access
| Defect | Severity | Component | Verification Result |
| --- | --- | --- | --- |
| **J9-BE-01** | MAJOR | Backend Departure Timing | Direct backend Journey route writes and publication reject elapsed departure times (past and exact boundary rejected; strictly future departures accepted). Multi-leg chronology preserved under lock. |
| **DEF-ADM-02** | MAJOR | Payout Profile Feature Flag | When `FEATURE_PAYOUT_PROFILES_ENABLED=False`, authorized operators (Finance, Super) receive an explicit HTTP 503 Configuration Unavailable response; unauthorized operators receive HTTP 403 Forbidden. |
| **DEF-ADM-03** | MAJOR | Finance Snapshot Guard | `FinanceSnapshotUnavailable` exception renders as a controlled 503 page in HTML console and returns HTTP 503 JSON in control plane. Standalone PostgreSQL snapshot requirements (read-only, repeatable-read, 10s statement timeout) preserved. |
| **DEF-MOB-13** | MAJOR | Unauthorized Deal Recovery | Unrelated accounts, 403, 404, or expired Deal links render a dedicated localized unavailable state with screen-reader live-region announcements and safe Home/Back recovery. Deal data remains hidden. |
| **DEF-MOB-04** | MINOR | Error Localization | Pricing quote failures map structured error codes to localized copy (EN, FR, AR). Raw backend error prose is never rendered. |
| **DEF-MOB-10** | MINOR | Leg Capacity Bounds | Client and backend both strictly enforce 0.01 kg – 200.00 kg with at most two decimal places. |
| **DEF-MOB-11** | MINOR | DZD Digit Validation | Distinguishes empty from malformed inputs; validates CCP (1–20 digits), key (exactly 2 digits), and RIP (exactly 20 digits) with localized feedback. |
| **DEF-MOB-12** | MINOR | Verification Code Validation | Shared 6-digit validator distinguishes empty (required) from malformed (must be 6 digits) across email verification and password reset screens. |

---

## 4. End-to-End System Smoke Verification

### 4.1 Admin Console Smoke
Verified administrative capabilities across Super, Finance, Trust, Support, and Ops roles:
- **Overview & Navigation:** Operational dashboards render without unhandled exceptions.
- **People & KYC:** Person profile view, document inspection, and identity verification controls function securely.
- **Payout Reviews:** Enabled queue operates within bounded query budgets (13 queries on PostgreSQL); disabled feature displays explicit 503 page for authorized staff while denying unauthorized staff with 403.
- **Finance Control Plane:** Standalone PostgreSQL read-only snapshot functions without 500 errors; non-PostgreSQL / atomic contexts return controlled 503.

### 4.2 Complete Mobile Flow & Cross-Role Lifecycle
1. **Sender Journey:**
   - Registration/Login → Home dashboard.
   - Request creation: Multi-step route, parcel specifications (weight bounded 0.01–200.00 kg), reward proposal, deposit estimation.
   - Deposit checkout (Stripe TEST / Chargily TEST) → Payment result screen with seal badge and breakdown.
   - Published request: Add/Edit Boost (€5.00) → Find Travelers search with race-protected sorting/pagination.
   - Proposal dispatch to matching traveler → Deal negotiation.
2. **Traveler Journey:**
   - Login → KYC verification check.
   - Journey creation: Multi-leg route with future departure enforcement; flight legs require valid proof; capacity enforced.
   - Offer reception: Base reward (€30.00) + Boost (€5.00) = €35.00 correctly displayed.
   - Rapid-tap protected acceptance → Deal establishment.
3. **Fulfillment & Protection:**
   - Funding: Sender completes deal funding; exact pickup and drop-off addresses revealed.
   - Pickup: Traveler verifies parcel handover.
   - Delivery Code Security: Traveler never receives delivery code in Deal payload, handover endpoint, push notifications, serialization, accessibility tree, or logs. Code is revealed to sender/recipient only after 30-minute post-pickup window.
   - Confirmation & Dispute Protection: Delivery confirmation initiates a mandatory 48-hour payout protection window. Dispute submission freezes payout distribution.
   - Blind Ratings: One review per participant; submissions remain hidden until both parties submit or the window expires.
   - Payout Setup: EUR Connect onboarding or DZD manual review queue.

### 4.3 Money & Financial Invariants
- **Canonical Currency:** EUR is platform currency. All calculations (fees, deposits, rewards, boosts) occur server-side.
- **Canonical Calculation:** Base Traveler Reward (€30.00) + Boost (€5.00) = **€35.00** Traveler Earnings. Verified consistent across Request, Offer, Deal, and Payout models.

---

## 5. Deployed TEST Backend & Legal Endpoints

- **Gateway URL:** `https://shiptrip-production-f7f7.up.railway.app`
- **Health Check (`/healthz`):** **HTTP 200 OK**
  ```json
  {"status": "ok", "release": "v1.0.0-rc.44+61d4419"}
  ```
- **Readiness Check (`/readyz`):** **HTTP 200 OK**
  ```json
  {"status": "ready", "release": "v1.0.0-rc.44+61d4419", "checks": {"database": "ok", "migrations": "ok", "rate_limit_cache": "ok"}}
  ```
- **Legal Endpoints:**
  - `https://shiptrip-production-f7f7.up.railway.app/terms` → **HTTP 200 OK** (HTML draft served with CSP headers).
  - `https://shiptrip-production-f7f7.up.railway.app/privacy` → **HTTP 200 OK** (HTML draft served with CSP headers).
- **Financial Safety Configuration:**
  - `PAYMENTS_ENVIRONMENT=test`
  - Stripe `sk_test_...` and `STRIPE_CONNECT_EXPECTED_MODE=test`
  - Chargily TEST API credentials
  - `PAYMENTS_ALLOW_MOCK_PROVIDER=false` (mock rail prohibited in production settings)
  - `PAYOUT_DZD_EXECUTION_ENABLED=false` (manual bank execution disabled)
  - Zero live financial transactions executed.

---

## 6. Localization, Viewports & Accessibility

1. **Localization Parity:**
   - Catalogues EN, FR, and AR are 100% complete (`mobile/l10n_untranslated.json` is `{}`).
   - Arabic RTL progression: Routes render origin on right, destination on left, with left-pointing directional arrows.
   - Currency BiDi isolation: Numbers wrapped in LTR isolates (`\u2066` … `\u2069`) to prevent currency symbol transposition.
2. **Responsive Viewports:**
   - Tested at `320×640` (small Android), `390×844` (standard mobile), `411×869` (Android gesture nav), `844×390` (landscape), and `1.6×` text scale.
   - Zero layout overflows, clipped text, or overlapping tap targets on Home, Request Create, Find Travelers, Offer, Deal, Payment Result, Profile, DZD Setup, or OTP screens.
3. **Accessibility:**
   - Clean route announcements without duplicate arrows (`Algiers to Paris` / `Alger vers Paris` / `الجزائر إلى باريس`).
   - Minimum 48dp touch targets on all interactive elements.
   - Screen-reader live regions announce async state changes, error banners, and unauthorized Deal status.

---

## 7. Official J9.4 TEST Release Candidate APK

The release candidate APK was compiled and staged via GitHub Actions workflow `android-release.yml`:

- **Artifact Name:** `shiptrip-v1.0.0-j94-test-5bf55f1-profile-arm64`
- **APK Filename:** `shiptrip-v1.0.0-j94-test-5bf55f1-profile-arm64.apk`
- **APK File Size:** **36,785,781 bytes** (~36.8 MB / 35.08 MiB)
- **APK SHA-256:**
  ```
  af844feb64f2c93bc315a9d49aa21f1434d08ee2d008b27d7d76a778c04aadbe
  ```
- **Source Git SHA:** `5bf55f1e665e69551ec428570bcb05975ae987f4` (short `5bf55f1`)
- **GitHub Actions Workflow:** `Build Android`
- **GitHub Actions Run ID:** [35511147551](https://github.com/is-bo/shiptripis/actions/runs/35511147551)
- **Artifact ID:** `10605397360`
- **Configured API Origin:** `https://shiptrip-production-f7f7.up.railway.app`
- **Build Type / Target:** Private Profile ARM64 (AOT compiled, carries debug keystore for installability, debug payloads stripped).

---

## 8. Mandatory Testing & Operational Instructions

> [!IMPORTANT]
> **APK Installation Rule:**
> You must **UNINSTALL every previous ShipTrip APK** from test devices before installing the J9.4 APK. This includes the J8.3 build (`shiptrip-v1.0.0-j83-test-07f777e-profile-arm64.apk`) and all prior test builds.

> [!IMPORTANT]
> **Matching Test Rule:**
> Owner testing of the matching engine must use a **NEW Journey with explicit valid arrival times**. Do not reuse pre-J7B Journeys created without arrival timestamps.

> [!NOTE]
> **Railway Backend Deployment:**
> No redeployment was performed or required. The deployed Railway release `v1.0.0-rc.44+61d4419` represents the exact product runtime code.

---

## 9. Sign-Off Statement

All J9 defects remain verified and closed. All automated quality gates are green. The J9.4 TEST APK has been successfully built and verified against the deployed test backend.

- **J9.4 FINAL RELEASE CANDIDATE:** **PASS**
- **All known J9 defects remain resolved:** **YES**
- **New J9.4 TEST APK ready for installation:** **YES**
- **Product / code release candidate accepted:** **YES**
- **Safe to proceed to controlled LIVE operational checklist:** **YES**
