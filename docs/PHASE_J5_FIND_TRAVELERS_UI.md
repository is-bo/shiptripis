# Phase J5 — Find Travelers Mobile Redesign

Visual and architectural implementation of the dense, route-first, scannable Sender discovery interface for ShipTrip mobile.

Starting main: `d27dbe051d65ac8c75ed3bf52c4b88913775c2e9`  
J4 commit: `8bf6443c5b9ba07db8ceaa53e9ea7bbcfaf94488`  
Branch: `gemini/j5-find-travelers-ui`

ShipTrip stayed strictly in **development / TEST mode** throughout:
- `PAYMENTS_ENVIRONMENT=test`
- Stripe TEST mode only
- Chargily TEST mode only
- `PAYOUT_DZD_EXECUTION_ENABLED=false`
- Zero real money moved, zero production API cutovers performed.

---

## 1. What was Replaced

The legacy `DiscoveryScreen` (`mobile/lib/features/requests/discovery_screen.dart`):
* Rendered massive ~540dp cards that allowed barely 1.2 cards on screen at 390×844.
* Repeated redundant request information and displayed raw detour/distance numbers (`under_5km`, `Barely a detour`, `300–750 km`) which are meaningless constants under canonical locality matching.
* Lacked traveler identity or trust badges (only displayed raw `traveler_id`).
* Combined ineligible requests and zero candidates into one generic empty state.
* Encouraged "Boost request" indiscriminately on empty states, falsely implying Boost creates compatibility.

---

## 2. The J5 Interface Architecture

### A. Card Density & Viewport Target (~155dp)
* The redesign replaces the 540dp card with a compact ~155dp card.
* At the standard phone target (390×844), **3 to 4 candidates are simultaneously visible and scannable**.
* Visual hierarchy:
  1. **Inline Route**: `Origin [· IATA] → [Stops] → Destination [· IATA]` with continuation indicators (`… →` / `→ …`).
  2. **Metadata & Fit**: Departure date/time, route-fit badge (`Excellent route match`, `Good route match`, `Compatible route`), and timing fit.
  3. **Traveler Identity & Trust**: First name, circular avatar with initials fallback, verified identity badge, completed deliveries count, and verified star rating or "New" badge (no fabricated 5.0 score for unrated users).
  4. **Pricing & Action**: Suggested price with currency symbol (`€X.XX`), "Propose" primary CTA button and info trigger for the detail sheet.

### B. InlineRoute Component (`mobile/lib/design/components/route.dart`)
* `InlineRoute` and `InlineRouteStop`:
  * Supports 2 to N stops with airport IATA code formatting (`Paris · CDG → Algiers · ALG → Jijel`).
  * `continuesBefore`: prepends `… →` when the journey begins before the matched pickup.
  * `continuesAfter`: appends `→ …` when the journey extends beyond the matched delivery.
  * **Strict Semantic Travel Sequence**:
    * In LTR: Stop 0 is left, arrows point right (`→`), following native reading order.
    * In RTL: Stop 0 is right, arrows point left (`←`), following native Arabic reading order (`Stop 0 → Stop 1 → Stop 2`).
  * Responsive wrapping with `Wrap` to avoid RenderFlex overflow on small screens or high text scaling.
  * Accessible `Semantics` label announcing `Origin to Destination`.

### C. Match Reasons & Trust Grouping (`_TripDetailSheet`)
* Maps strictly the frozen J4 backend `match_reasons` codes:
  * `direct_leg` → *"Carried in one leg"*
  * `transfers` → *"N transfer(s)"*
  * `whole_trip_matches` → *"This whole trip is your route"*
  * `picks_up_in` → *"Picks up in your city"*
  * `arrives_in` → *"Delivers to your city"*
  * `arrives_before_deadline` → *"Arrives before your deadline"*
  * `has_room_for` → *"Has enough capacity for your parcel"*
* **Honest Trust Signals Separation**: Trust badges are NOT lumped under "Why this trip fits".
  * `identity_verified` → Verified identity badge under traveler profile.
  * `flight_proof_approved` → *"Flight ticket verified"* under trip details.
* **Safe Fallback**: Any unknown future match code is ignored safely or rendered with an honest fallback, preventing client crashes.

### D. Screen States & Server-Authoritative Gating
1. **No Candidates State (`_NoCandidatesView`)**:
   - Strictly does **NOT** display a "Boost request" button (Boost never creates compatibility or alters traveler ordering).
   - Displays clear messaging with **Back to request** and **Refresh** CTAs.
2. **Request Ineligible State (`_IneligibleView`)**:
   - `awaitingDeposit`: Offers **Publish your request** to complete deposit.
   - `alreadyMatched`: Displays informative notice that parcel is already matched, with **Back to request** CTA.
   - `closed` / `inProgress`: Provides appropriate navigation without dead ends.
3. **Action Gating**:
   - Primary "Make an offer" action is gated by `serverActions.canProposeOffer`.
   - "View journey" is gated by `serverActions.canViewJourney`.

### E. Controller & Riverpod State Management
* `FindTravelersController` (`AsyncNotifier<FindTravelersScreenState>`):
  * Manages paging with `limit` and `offset` using server-provided `next_offset` and `has_more`.
  * Sorting options: `best_match` (authoritative ranking) and `soonest_departure`. Changing sort reloads from offset 0.
  * Deduplication: incoming pages are deduplicated by `journeyId` to prevent duplicate cards during concurrent list mutations.
  * Pull-to-refresh refreshes list state and request metadata concurrently.

---

## 3. Responsive & Multi-Device Verification

Tested across diverse screen dimensions, orientations, and accessibility settings:
- Small Android (320×640)
- Standard Android (411×869)
- iPhone with home indicator safe area (390×844)
- Landscape orientation (844×390)
- Large accessibility text scale (1.6× at 390×844)

All device layouts render cleanly without RenderFlex overflows.

---

## 4. Test Verification Suite

### Dedicated J5 Test Suite (`test/phase_j5_find_travelers_test.dart`)
24 tests passing:
- InlineRoute: 2 stops with airport IATA, 3 stops, continues before/after indicators, RTL direction.
- Candidate Card: rated traveler score, unrated "New" badge, verified identity badge, completed deliveries count, initials fallback, route-fit badges.
- Density: 4 candidate cards fit visible at 390×844 with compact ~155dp height.
- Screen States: no_candidates state strictly omits Boost CTA; ineligible awaitingDeposit / alreadyMatched states; error retry.
- Pagination & Sorting: sort change reload from offset 0; deduplication by journeyId.
- Match Reasons & Actions: detail sheet reason mappings; action gating.
- Responsiveness: 320×640, 411×869, 390×844, landscape, and 1.6× text scale.

### Legacy J1.2 Route Test Suite (`test/phase_j12_test.dart`)
17 tests passing: decoupled from old DiscoveryScreen layout while preserving canonical route projection assertions.

### Full Mobile Suite
618 tests passing (`D:\flutter\bin\flutter.bat test`).

### Static Analysis & Formatting
- `flutter analyze --fatal-infos`: 0 issues found.
- `dart format --output=none --set-exit-if-changed lib test`: Clean.
