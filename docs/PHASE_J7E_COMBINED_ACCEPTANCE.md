# Phase J7E — Combined J7 Acceptance, Regression Sweep & Final TEST APK

Status: ACCEPTED, TEST only. Stripe TEST, Chargily TEST,
`PAYOUT_DZD_EXECUTION_ENABLED=false`, zero real money.
Final TEST Profile ARM64 APK built for owner testing against:
`https://shiptrip-production-f7f7.up.railway.app`

Starting point: `f27c111` (J7D merged). Branch: `gemini/j7e-combined-acceptance`.
Scope: Mobile acceptance, cross-phase integration verification across J7A–J7D,
universal Arabic currency isolation, localized route accessibility semantics,
RTL visual travel order verification, multi-viewport stress testing, full
regression pass, and final TEST APK production.

---

## 1. Executive Summary & Verification Matrix

Phase J7E consolidates and verifies all J7 user-facing changes into a single,
battle-tested, production-ready build:

* **J7A — Request Creation & Pricing Alignment:**
  * Boost removed from initial request creation; available only after publication.
  * Reward step control aligned to €0.50 increments.
  * Authoritative pricing calculation preserved without client-side divergence.
* **J7B — Route Presentation & Matching:**
  * Published request and delivery routes display consistent departure → arrival ordering.
  * Journey arrival time is strictly required for matching compatibility.
  * Legacy journeys lacking arrival times remain cleanly incompatible.
* **J7C — Guest Payer Experience:**
  * Sender guest-payment sheet redesigned with live link generation and token seeds.
  * Reopening the sheet reuses the active link rather than invalidating it.
  * Revocation is cleanly locked out while guest checkout is actively in progress.
  * Public payer page is responsive, localized, and displays receipt email fields only when receipts are active.
* **J7D — Unified Payment Success & Return UX:**
  * All payment results flow through `features/common/payment_result.dart`.
  * Wax-seal visual identity, Fraunces hero figures, and purpose-specific ledger states (*Paid in full* stamp, deposit credit, remaining balance).
  * Web provider-return shell mirrors mobile status.
* **J7E Core Presentation Enhancements:**
  * **Universal Arabic Currency Formatting:** `Money.format` strips directional marks (`\u200f`) and wraps Arabic currency figures in Left-to-Right Isolates (`\u2066` … `\u2069`), guaranteeing numbers precede symbols (`35,00 €` / `40.500 DA`) across buttons, sentences, headers, and breakdowns.
  * **Localized Route Accessibility Semantics:** Screen readers announce localized travel connectors (EN: *"Algiers to Paris"*, FR: *"Alger vers Paris"*, AR: *"الجزائر إلى باريس"*), while visual layout retains strict origin-to-destination travel order across both LTR and RTL viewports.
  * **Multi-Viewport & Typography Verification:** Tested across 320×640 (compact Android), 390×844 (standard iOS/Android), 411×869 (tall Android), landscape (844×390), and 1.6× accessibility text scaling with zero overflows or clip defects.

---

## 2. Arabic Currency Presentation Fix

### Root Cause Analysis
In Arabic locales (`ar`), standard ICU/`NumberFormat` formatting inserts Right-to-Left Marks (`\u200f`) or places currency symbols in positions that can cause BiDi engines to swap number and symbol order when embedded in Arabic sentences or mixed BiDi contexts (e.g., rendering `€ 35,00` or corrupting decimal separators).

### Solution (`mobile/lib/core/money/money.dart`)
1. In `Money.format(String? locale)`:
   * When `locale` starts with `'ar'`, directional control marks (`\u200f`, `\u200e`) are stripped.
   * The formatted string is wrapped in a Left-to-Right Isolate: `\u2066` + formatted string + `\u2069`.
2. In `mobile/lib/features/common/payment_result.dart`:
   * Redundant local wrapping was removed, allowing `amount.format(locale)` to serve as the single source of truth for all payment figure displays.
3. Verified with comprehensive unit and widget tests:
   * Standalone figures: `\u206635,00\u00a0€\u2069`
   * Algerian Dinar figures: `\u206640.500\u00a0DA\u2069`
   * Embedded inside full Arabic sentences and payment CTAs.

---

## 3. Localized Route Accessibility & RTL Order

### Accessibility Semantics (`mobile/lib/design/components/route.dart`)
Screen reader users navigating route components require natural language connectors.
* Added `routeSemanticLabel(BuildContext context, String origin, String destination)`:
  * Arabic (`ar`): `"$origin إلى $destination"`
  * French (`fr`): `"$origin vers $destination"`
  * English / fallback: `"$origin to $destination"`
* `InlineRoute` wraps visual arrow icons in `ExcludeSemantics` and sets `Semantics(label: ..., child: ...)` on the route container.
* Visual presentation maintains `origin -> destination` directional flow according to physical travel progression.

---

## 4. Cross-Phase Integration Verification (J7A–J7D)

| Phase | Invariant | Verified By | Result |
|---|---|---|---|
| **J7A** | Boost excluded from initial request creation | `phase_j7e_combined_acceptance_test.dart` | PASS |
| **J7A** | Reward adjustments use €0.50 increments | `phase_j7e_combined_acceptance_test.dart` | PASS |
| **J7B** | Origin → Destination ordering preserved on Request & Delivery cards | `phase_j7e_combined_acceptance_test.dart` | PASS |
| **J7B** | Matching requires explicit Journey arrival time | `phase_j7e_combined_acceptance_test.dart` | PASS |
| **J7C** | Reopening guest payer sheet preserves live link | `phase_j7e_combined_acceptance_test.dart` | PASS |
| **J7C** | Revoking guest link is locked out when checkout is active | `phase_j7e_combined_acceptance_test.dart` | PASS |
| **J7D** | PaymentResultView displays wax seal, Fraunces hero, and proper receipt ledger | `phase_j7e_combined_acceptance_test.dart`, `phase_j7d_payment_result_test.dart` | PASS |
| **J7D** | Paid-in-full status suppresses remaining balance line | `phase_j7e_combined_acceptance_test.dart` | PASS |

---

## 5. Dead Surface Confirmation: `GuestPayScreen`

As verified during J7C and J7D audits:
* `GuestPayScreen` (`mobile/lib/features/payments/guest_pay_screen.dart`, route `/guest/pay/:token`) exists as a legacy in-app guest checkout screen.
* Analysis confirmed that public guest payment links (`https://shiptrip-production-f7f7.up.railway.app/pay/guest/<token>`) are opened in the device web browser via `launchUrl`, not routed internally to `GuestPayScreen`.
* In accordance with phase rules, no synthetic navigation was introduced; the surface remains dormant and unreferenced in production navigation flows.

---

## 6. Multi-Viewport & Accessibility Stress Suite

`mobile/test/phase_j7e_combined_acceptance_test.dart` verified all critical flows across:
1. **320×640 (Small Android):** No bottom overlap, cards and buttons fit comfortably.
2. **390×844 (Standard Phone):** Canonical spacing, perfect typography alignment.
3. **411×869 (Tall Android):** Correct scroll bounds, no floating artifacts.
4. **844×390 (Landscape Mode):** Scrollable views adapt without clipping or keyboard overflow.
5. **1.6× Large Text Accessibility:** Dynamic text scales legibly; buttons and badges wrap safely without text truncations.

---

## 7. Owner Testing Instructions

To test the final APK against the live TEST backend:

1. **Uninstall Existing APK:**
   * You **must uninstall** any previous ShipTrip APK from your test device before installing this build. This prevents keystore signature mismatch errors or stale SQLite/SharedPreferences cache states.
2. **Backend Target:**
   * The APK connects to `https://shiptrip-production-f7f7.up.railway.app`.
   * Stripe and Chargily operate in **TEST mode**.
   * Payout execution is disabled (`PAYOUT_DZD_EXECUTION_ENABLED=false`).
   * Zero real money is involved.
3. **Important Note on Journey Matching:**
   * To test matching against newly created requests, **create a NEW Journey with explicit arrival times**.
   * Legacy journeys created prior to J7B without arrival times will intentionally be classified as incompatible.
