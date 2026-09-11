# Phase 8F-H6B — Traveler Mobile Payout UX

## Overview

Phase 8F-H6B delivers the traveler mobile payout experience for ShipTrip in Flutter, directly consuming the frozen Phase 8F-H6A backend contract (`docs/PHASE8F_H6A_MOBILE_PAYOUT_CONTRACT.md`, backend commit `c73a4fc`, release `v1.0.0-rc.25+c73a4fc`).

In accordance with ShipTrip's core invariants and financial rules:
- **No client-side state invention**: Flutter never derives payout eligibility, rails, release status, 48-hour rules, or frozen DZD conversions. The backend's `display_state`, `blocking_reason`, and `available_actions` are strictly authoritative.
- **Canonical EUR & Frozen DZD**: Amounts always display canonical EUR alongside frozen DZD (using the snapshotted conversion and explicit rate formula) whenever DZD settlement is active.
- **Strictly 6 Inputs on DZD Setup**: First Name, Last Name, CCP Number, CCP Key, RIP, and Crossed Cheque Photo. National Identification Number (NIP) is explicitly excluded from the product and codebase.
- **Mandated Cheque Copy**: Exact multi-lingual copy for Crossed Cheque Photo upload across English, French, and Arabic.
- **Future-Scope Notice**: Transparent notice that preference changes and profile replacements apply to future payouts only and do not alter in-flight transactions.

---

## Architecture & Implementation Summary

### 1. Domain Models (`mobile/lib/domain/payout.dart`)
- **Enums & Value Objects**:
  - `PayoutPreference`: `eur_only`, `dzd_only`, `both` (with null for unconfigured).
  - `EurPayoutState`: `not_configured`, `setup_required`, `pending_verification`, `ready`, `needs_attention`.
  - `DzdPayoutState`: `not_configured`, `pending_review`, `ready`, `needs_attention`, `rejected`.
  - `PayoutDisplayState`: `pending_delivery`, `protection_active`, `ready`, `in_flight`, `paid`, `needs_attention`, `failed`. Unknown states fail safely to `needsAttention`.
  - `PayoutRail`: `stripe_eur`, `manual_dzd`.
- **Contract Models**:
  - `EurPayoutMethod` and `DzdPayoutMethod`: parse wire states, readiness flags, revisions, and string arrays for `available_actions`.
  - `DzdProfileSummary`: masks CCP (`•••• 1234`) and RIP (`•••• 5678`), captures review state and submission timestamps.
  - `PayoutMethodsSummary`: holds preferences, revision tokens for optimistic concurrency, and sub-methods.
  - `PayoutMobile`: comprehensive mobile projection including canonical EUR cents, frozen DZD amount, fixed FX rate in micros, display state, blocking reason, and contextual action list.
  - `PayoutListItem` & `PayoutHistoryPage`: paginated history models supporting Django DRF pagination (`results`, `next`, `previous`, `count`).

### 2. Repositories & API Client (`mobile/lib/data/repositories.dart`)
- `payoutMethods()`: `GET /api/payouts/methods`
- `updatePayoutPreference()`: `PATCH /api/payouts/methods` with atomic optimistic locking (`eur_revision`, `dzd_revision`).
- `startStripeOnboarding()`: `POST /api/payouts/stripe/onboarding` returning onboarding URL and expiry.
- `openStripeDashboard()`: `POST /api/payouts/stripe/dashboard` returning dashboard URL.
- `refreshStripeReadiness()`: `POST /api/payouts/stripe/refresh` forcing backend synchronization.
- `uploadPayoutProof()`: `POST /api/payouts/proof` uploading multipart cheque photo.
- `submitDzdProfile()`: `POST /api/payouts/dzd` submitting the 6-field profile with proof reference.
- `payoutHistoryPaginated()`: `GET /api/payouts?page=N` returning `PayoutHistoryPage`.
- `payoutDetail()`: `GET /api/payouts/{reference}` returning `PayoutMobile`.

### 3. State Management (`mobile/lib/app/app_state.dart`)
- `payoutMethodsProvider`: fetches and caches `PayoutMethodsSummary`.
- `payoutHistoryProvider(int page)`: retrieves paginated payout history.
- `payoutDetailProvider(String reference)`: fetches live payout detail.
- `refreshVolatileState()`: invalidates all payout providers upon app refresh or push notification.

### 4. User Interfaces & Screens
- **`PayoutMethodsScreen` (`mobile/lib/features/profile/payout_methods_screen.dart`)**:
  - Preference selector (`EUR only`, `DZD only`, `Both`) with future-scope notice.
  - EUR Stripe card with status pill, onboarding / dashboard actions via `url_launcher`, and app lifecycle observer for automatic readiness refresh on return.
  - DZD CCP / BaridiMob card with status pill, masked account numbers, and dynamic actions (`Setup`, `Update payout information`).
  - Shortcut link to payout history.
- **`DzdSetupScreen` (`mobile/lib/features/profile/dzd_setup_screen.dart`)**:
  - Strictly 6 inputs:
    1. First name (`first_name`)
    2. Last name (`last_name`)
    3. CCP number (`ccp_number`)
    4. CCP key (`ccp_key`)
    5. RIP (`rip`)
    6. Crossed cheque photo (`proof_reference`)
  - No NIP field anywhere in UI or serialization.
  - Mandated cheque photo copy in FR/AR/EN.
  - `SingleChildScrollView` layout to prevent form state loss and ensure full validation across all fields.
- **`PayoutDetailScreen` (`mobile/lib/features/profile/payout_detail_screen.dart`)**:
  - Displays canonical EUR amount.
  - When DZD settlement: displays snapshotted DZD amount and frozen rate formula (`1 EUR = X DZD`).
  - Displays server authoritative `display_state` via `StatusPill`.
  - Displays payout rail, deal reference, and timestamps.
  - Safe blocking reason banner and contextual actions (`configure_payout_method`, `view_deal`).
- **`PayoutsScreen` (`mobile/lib/features/profile/payouts_screen.dart`)**:
  - Paginated history list rendering dual currencies (EUR + DZD).
  - Tapping an item navigates directly to `PayoutDetailScreen`.
- **`DeliveryScreen` (`mobile/lib/features/deals/delivery_screen.dart`)**:
  - Traveler protection section consumes `deal.payoutSummary`.
  - Renders display state, dual currencies, frozen rate formula, and direct action to view payout details or configure methods.
- **Navigation & Deep Linking (`mobile/lib/app/router.dart`, `notifications_screen.dart`)**:
  - Routes: `/profile/payout-methods`, `/profile/payout-methods/dzd`, `/payouts/:reference`.
  - Push notification routing: `OpenPayoutDetail` opens detail; `OpenPayoutMethods` opens methods.

---

## Localization Verification

All user-facing strings are localized across English (`app_en.arb`), French (`app_fr.arb`), and Arabic (`app_ar.arb`), with RTL layouts fully tested:

### Mandated Cheque Copy
- **French (FR)**:
  - Label: `Photo du chèque barré complet`
  - Explainer: `Téléversez une photo claire du chèque barré complet.`
- **Arabic (AR)**:
  - Label: `صورة كاملة لشيك مُسطَّر`
  - Explainer: `حمّل صورة واضحة وكاملة للشيك المُسطَّر.`
- **English (EN)**:
  - Label: `Photo of the full crossed cheque`
  - Explainer: `Upload a clear photo of the full crossed cheque.`

---

## Verification & Automated Test Coverage

### Automated Test Suite: `mobile/test/phase8fh6b_payout_screens_test.dart`
1. `PayoutMethodsScreen renders preferences, EUR card, and DZD card`: Verified.
2. `PayoutMethodsScreen selecting preference sends PATCH with exact wire fields`: Verified (`eur_revision`, `dzd_revision`).
3. `DzdSetupScreen has strictly six inputs and NO NIP field`: Verified (5 text fields + 1 cheque upload, zero NIP references).
4. `DzdSetupScreen displays mandated cheque copy in English, French, and Arabic`: Verified.
5. `DzdSetupScreen validates required fields before submission`: Verified.
6. `PayoutDetailScreen renders canonical EUR, snapshotted DZD, and rate formula`: Verified.
7. `PayoutDetailScreen renders blocking reason when present`: Verified.
8. `PayoutsScreen (History) renders paginated payout history items`: Verified.
9. `DeliveryScreen payout integration renders payoutSummary in traveler delivery screen`: Verified.

### Full Quality Gates
- **Static Analysis**: `flutter analyze` passes with **0 issues**.
- **Regression Suite**: `money_test.dart`, `phase8fc_payment_rails_test.dart`, `phase8fd_push_test.dart` all pass cleanly.
