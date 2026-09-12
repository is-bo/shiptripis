# Phase I1B — Early Arrival, Route Visibility & Delivery Lifecycle Mobile UX

Authoritative documentation for the Flutter/mobile presentation of Phase I1.
Baseline backend contract: `docs/PHASE_I1A_JOURNEY_TIMING_CONTRACT.md` (deployed as `v1.0.0-rc.26+4d8d715`).

---

## 1. Executive Summary

Phase I1B implements the complete mobile presentation layer for Journey Timing, Early Arrival, Route Visibility, and Delivery Lifecycle separation.
All changes strictly respect backend authority: Flutter never invents wire enum values, never reinterprets unknown states, never recomputes financial or timing floors client-side, and preserves all invariant boundaries established in Phase I1A.

---

## 2. Implemented Features & Architectural Details

### 2.1 Traveler "I arrived early" Flow
- **Affordance**: Visible only when server-supplied `deal.arrival.report_available == true` (and `canReportEarlyArrival` action is present in `available_actions`).
- **Confirmation**: Tapping the action opens a confirmation dialog stating:
  - Title: localized `earlyArrivalConfirmSheetTitle` ("Report early arrival")
  - Body: localized `earlyArrivalConfirmSheetBody` ("This notifies the sender that you arrived before the scheduled arrival. It does not confirm delivery of the parcel...")
  - Explicit Consequence Notice: localized `earlyArrivalPayoutFloorExplanation` ("Arriving early does not make the payout available earlier than the protected payout date for this delivery.")
- **Dispatch**: Submits `POST /api/deals/<id>/arrival/report`.
- **Idempotency**: Handled gracefully (`changed: false` returns deal without error).
- **Pending State**: Upon submission, invalidates `dealDetailProvider` and transitions to "Waiting for Sender confirmation" notice (`earlyArrivalWaitingSenderTitle`).

### 2.2 Sender Review & Decision Flow
- **Notice Banner**: When early arrival is pending (`state == 'pending_confirmation'`), an action card appears at the top of the Deal screen.
  - Title: localized `earlyArrivalSenderNoticeTitle` ("Traveler says they arrived early")
  - Body: localized `earlyArrivalSenderNoticeBody` ("The traveler reported early arrival for this delivery. Confirming arrival acknowledges their presence; parcel delivery and payout protection remain separate.")
- **Actions**:
  - Primary: "Confirm arrival" (`earlyArrivalConfirmAction`) -> `POST /api/deals/<id>/arrival/confirm`
  - Secondary: "Decline" (`earlyArrivalDeclineAction`) -> `POST /api/deals/<id>/arrival/decline`
- **Resulting State**:
  - Confirmed: Displays green StatusTone banner with `earlyArrivalConfirmedTitle` ("Arrival confirmed").
  - Declined: Displays neutral StatusTone banner with `earlyArrivalDeclinedTitle` ("Early arrival not confirmed").

### 2.3 Strict Separation of Arrival, Delivery & Security
- **Arrival != Delivery**: Arrival confirmation never modifies delivery state, never marks delivery complete, and never starts the 48-hour protection window prematurely.
- **Delivery Code Security**: `traveler_can_view_delivery_code` remains false. The Traveler can NEVER view the delivery code.
- **30-Minute Buffer**: Post-pickup delivery code safety buffer remains strictly locked and cannot be bypassed by reporting or confirming early arrival.

### 2.4 Route Visibility
- **Route Section**: Rendered when `deal.route` exists and has carrying legs.
- **Basis Indicator**: Displays `routeBasisSnapshot` ("Frozen at booking") when `basis == 'funded_snapshot'`.
- **Ordered Timeline**:
  - Uses `RouteLine` component from `design/components/route.dart`.
  - Ordered stops with departure and arrival timestamps.
  - Mode badges displaying `routeFlightMode` (Flight icon) and `routeDriveMode` (Drive icon).
  - Only carrying legs for this deal are shown.

### 2.5 Authoritative Server-Side Activity Lists
- **Active Sending Cleanup**:
  - `activeDealsProvider` queries `GET /api/deals?activity=active`.
  - `historyDealsProvider` queries `GET /api/deals?activity=completed`.
  - Deliveries and Home screens consume these providers directly rather than filtering client-side.
  - Delivered deals (`delivery_confirmed_at != null`) immediately leave the Active Sending list and appear in History.

### 2.6 Protection & Payout Floor Presentation
- Displays `earlyArrivalScheduledArrivalLabel` with formatted `fundedScheduledArrivalFloorAt`.
- Displays `earlyArrivalPayoutProtectedGateLabel` with formatted `payoutEligibleFrom`.
- Explains the payout floor with `earlyArrivalPayoutFloorExplanation` whenever a schedule floor or early arrival is active.

### 2.7 Notifications & Deep-Link Routing
- Parsed channels:
  - `deal.arrival_reported` -> `NotificationChannel.dealArrivalReported`
  - `deal.arrival_confirmed` -> `NotificationChannel.dealArrivalConfirmed`
  - `deal.arrival_declined` -> `NotificationChannel.dealArrivalDeclined`
- All three resolve to `OpenDeal(dealId)` destination, invalidating detail before navigation.

### 2.8 Trilingual Localization & RTL
- All copy localized in English (`app_en.arb`), French (`app_fr.arb`), and Arabic (`app_ar.arb`).
- Tested on multiple device configurations with Arabic RTL layout, verifying zero layout overflow.

---

## 3. Verification & Quality Gates

- **Automated Tests**:
  - `mobile/test/phase_i1b_journey_timing_test.dart`: 12 tests passed (100% green).
  - `mobile/test/phase8fh6b_payout_screens_test.dart`: 16 tests passed (100% green).
- **Static Analysis**: `flutter analyze` completed with 0 errors, 0 warnings, 0 infos.
- **Code Formatting**: Dart format verified across all modified files.
- **Backend Integrity**: Zero backend modifications. Deployed backend `v1.0.0-rc.26+4d8d715` untouched.
