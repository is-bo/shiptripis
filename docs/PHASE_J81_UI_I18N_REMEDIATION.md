# ShipTrip Phase J8.1 — Pre-Launch UI/i18n Remediation Report

**Execution Date:** 2026-09-19  
**Branch:** `gemini/j81-ui-i18n-remediation` -> `main`  
**Phase Purpose:** Remediation of front-end UI, localization (i18n), accessibility semantics, and dead-field defects identified during the J8 Deep Pre-Launch Product Certification.  
**Constraints Enforced:**
- Mobile and static documentation changes only.
- Strict exclusion of DEF-SND-04 (+€15 Boost preset) per explicit instructions.
- Zero sensitive backend logic modifications.
- Railway deployment: **NO**.
- APK build: **NOT BUILT**.

---

## 1. Remediation Scope & Defect Closures

### DEF-SND-01 — MAJOR: Arabic RTL Route Progression Inversion
- **Issue:** On `HomeScreen` and `DeliveriesScreen`, request cards previously rendered routes using inverted string concatenation: `context.isRtl ? '$to ← $from' : '$from → $to'`. This caused Arabic readers to read *Destination ← Origin*, completely reversing the physical and logical order of journeys.
- **Remediation:**
  - Replaced manual route string logic in `HomeScreen` (`_RequestRow`) and `DeliveriesScreen` with canonical `RouteSummary(from: from, to: to)`.
  - `RouteSummary` renders `Wrap` / `Row` of stops with `Icons.arrow_forward_rounded` (`matchTextDirection: true`).
  - Under Arabic RTL `Directionality`, the origin is laid out on the right, the destination on the left, and the directional arrow automatically mirrors to point leftwards (towards destination).
  - Updated legacy test assertions in `mobile/test/phase_j7b_route_matching_test.dart` to assert correct RTL layout geometry and `RouteSummary` semantics.
- **Status:** **RESOLVED & VERIFIED**.

### DEF-SND-02 — MINOR: RouteSummary Hardcoded English Semantics
- **Issue:** `RouteSummary` in `mobile/lib/design/components/route.dart` hardcoded English connector semantics: `'$from to $to'`. French and Arabic screen reader users heard English connector text.
- **Remediation:**
  - Refactored `RouteSummary` to consume `routeSemanticLabel` with the active context `Locale`.
  - Localized connector text:
    - English: `"to"` (`Algiers to Paris`)
    - French: `"vers"` (`Alger vers Paris`)
    - Arabic: `"إلى"` (`الجزائر إلى باريس`)
  - Enforced `excludeSemantics: true` on the inner visual row/wrap so assistive technologies announce only the single clean semantic phrase without duplicating child fragments.
- **Status:** **RESOLVED & VERIFIED**.

### DEF-SND-03 — MINOR: Profile Legal Rows Non-Interactive & Contact Support Action
- **Issue:** In `ProfileScreen`, Terms of Service and Privacy Policy rows had empty callbacks (`() {}`), while Contact Support was an interactive row leading nowhere with no configured support email, URL, or ticketing backend.
- **Remediation:**
  - Added `webBaseUrl` configuration to `mobile/lib/core/env/app_config.dart` (defaulting to `apiBaseUrl` with release origin validation).
  - Resolved canonical public legal routes using `Uri.parse(AppConfig.webBaseUrl).resolve('/terms')` and `/privacy`.
  - Implemented `_openLegalUrl` in `ProfileScreen` with external browser launcher `launchUrl(uri, mode: LaunchMode.externalApplication)`.
  - Added graceful failure notification using `AppSnack.info(context, l.profileLinkOpenFailed)` if browser launching fails.
  - Added localized string `profileLinkOpenFailed` across all 3 ARB catalogues (`app_en.arb`, `app_fr.arb`, `app_ar.arb`); regenerated localizations; `mobile/l10n_untranslated.json` remains `{}`.
  - Removed Contact Support row completely until an authoritative destination is configured (preventing broken user experience).
  - Verified 48dp minimum tap target floor on interactive legal rows.
- **Status:** **RESOLVED & VERIFIED**.

### DEF-SND-05 — IDEA / MINOR: Dead Field Cleanup in RequestCreateScreen
- **Issue:** `RequestCreateScreen` retained dead state field `int? _chosenDepositCents;` and passed dead argument `postingDepositEurCents: _chosenDepositCents,`.
- **Remediation:**
  - Removed `int? _chosenDepositCents;` and argument from `RequestCreateScreen`.
  - Verified clean compilation, zero warnings, and clean screen mounting.
- **Status:** **RESOLVED & VERIFIED**.

### Explicit Non-Inclusion: DEF-SND-04 (+€15 Boost Preset)
- Per explicit prompt instructions, DEF-SND-04 was **NOT** implemented in this phase.

---

## 2. Verification Suite & Quality Gates

| Gate / Test Suite | Scope | Target | Result | Status |
| :--- | :--- | :--- | :--- | :--- |
| `phase_j81_ui_remediation_test.dart` | J8.1 UI & i18n Suite | 28 tests | 28 passed, 0 failed | **PASS** |
| `phase_j7b_route_matching_test.dart` | Route Matching & Semantics | 26 tests | 26 passed, 0 failed | **PASS** |
| Full Mobile Test Suite | All Mobile Tests | 934 tests | 934 passed, 0 failed | **PASS** |
| Flutter Static Analysis | `flutter analyze --fatal-infos` | 0 issues | 0 issues found | **PASS** |
| Dart Code Formatter | `dart format --output=none --set-exit-if-changed .` | 183 files | 0 unformatted | **PASS** |
| Localization Parity | `mobile/l10n_untranslated.json` | 0 untranslated | `{}` (100% translated) | **PASS** |
| Public Static Web Check | `tools/check_static_web.py` | 8 HTML, 1 CSS | Passed (8 HTML, 1 CSS) | **PASS** |

### Responsive Visual QA Matrix
Tested across the complete responsive device matrix:
1. `DeviceProfile.smallAndroid` (320 × 640 dp): `RouteSummary` wraps cleanly without overflow; request cards fit with zero pixel overflows.
2. `DeviceProfile.iphone` (390 × 844 dp): Zero overflow; home indicator cleared.
3. `DeviceProfile.android` (411 × 869 dp): Clean layout across LTR and RTL.
4. `DeviceProfile.largeText` (390 × 844 @ 1.6× text scale): `RouteSummary` wraps multi-line cleanly without clipping or RenderFlex overflows; accessibility semantics preserved.

---

## 3. Invariants & Non-Regression Summary
- **Currency authority:** EUR remains canonical; zero changes to financial contracts or snapshots.
- **KYC gate:** Traveler KYC required before publishing journeys; unchanged.
- **Leg & route stability:** Journey legs, airport codes, flight-only transatlantic routes preserved.
- **Backend stability:** Zero backend code modified. Zero schema migrations introduced.
