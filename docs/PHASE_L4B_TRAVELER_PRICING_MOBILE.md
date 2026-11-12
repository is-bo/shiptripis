# L4B: Traveler pricing, mobile

Package L4B of `docs/WASSLA_DISCOVERY_PRO_PLAN.md`, on top of L4A
(`docs/PHASE_L4A_TRAVELER_PRICING_BACKEND.md`). The app renders what the server says and does no price
arithmetic: no worked example anywhere, no fee or total computed on the phone. No backend, migration or
contract change.

## 1. What a member sees

- **"Your price"** (optional) on the create and edit screens: "Price per kg" and "Minimum per parcel",
  with the line "Senders see your price plus Wassla's fee. Wassla's minimum for each parcel still
  applies." Both or neither; each must be a positive euro amount up to the ceiling staff set. Errors
  show after the first save attempt; a refusal from the server shows on the field it names until the
  value changes.
- **Journey page** (owner): a "Your price" card with the price, or "No price set", and Set a price /
  Change. It opens a sheet that saves through `PATCH /api/journeys/<id>/pricing`, so the price can
  change while a pending offer or a deal has locked the route. "Remove price" sends two nulls. The sheet
  says a new price applies to offers made from now on. The card is absent when pricing is switched off
  and nothing is set, shows a price read-only on a finished journey.
- **Find Travelers**: each card shows "€X for this parcel" (the server's listed price). A "Lowest
  price" sort (`listed_price`) sits beside Best match and Soonest trip, only while pricing is on.
- **Propose sheet**: with a listed price the sheet opens on it: "Their price for this parcel", the fee
  and the sender's total (the server's `listed.economics`), primary "Offer €X" (sends the listed
  reward), secondary "Offer a different amount" (opens the amount field, starting on the listed price,
  with "Offer at least €Y" from the server's minimum; below the listed price it adds "they may decline
  or counter"; "Use their price" goes back). A card to a sent offer is three taps: the card, "Make an
  offer", "Offer €X". Without a listed price the sheet is exactly what it was.
- **Trip cards and the trip preview** (Browse trips, Home, a person's page): "from €X per kg, minimum
  €Y"; the preview adds a Price row.

## 2. How it is built

| Piece | Where |
| --- | --- |
| `JourneyPrice`, `TravelerPricingPolicy`, `Journey.price` | `lib/domain/journey.dart` |
| `ListedPrice`, `ListedBasis`, `CandidateEconomics.listed` | `lib/domain/find_travelers.dart` |
| `TripCard.price` | `lib/domain/public_discovery.dart` |
| `setPrice`, `pricingPolicy`, price on create and update | `JourneyRepository` |
| `travelerPricingPolicyProvider` | `lib/app/app_state.dart` |
| draft, fields, section | `lib/features/journeys/journey_price.dart` |
| journey page card and sheet | `lib/features/journeys/journey_price_card.dart` |
| propose sheet, sort pill | `lib/features/requests/discovery_screen.dart` |
| candidate card, trip card, preview | `traveler_candidate_card.dart`, `discovery_widgets.dart`, `discovery_actions.dart` |

Rules the code holds to:

- **A route edit always sends the price.** `PATCH /api/journeys/<id>` with the two fields left out
  clears the price (L4A), so `JourneyRepository.update` always sends both, null included; the edit
  screen seeds its draft from the stored price. With pricing switched off the fields are hidden but the
  stored price still goes back unchanged (the server allows re-sending the stored price). Create sends
  them only when set.
- **The switch and ceilings come from `GET /api/journeys/pricing-policy`**, read in its own provider
  with no retry: a failure hides only the price, never the route form. The client checks the ceiling
  only to say so early; the server stays the authority and its `journey_price_invalid` (reasons
  `price_incomplete`, `price_per_kg_above_maximum`, `min_price_above_maximum`) is mapped onto the field.
  `traveler_pricing_disabled` and `journey_price_not_editable` get their own messages.
- **Backend state is authoritative.** The listed reward sent is the one the server gave; a
  `reward_below_minimum` answer (the minimum moved) drops the sheet into the amount field with the new
  minimum. Nothing is shown as sent until the server says so.

## 3. Judgment calls (not reviewed by Ismail)

1. "Offer a different amount" starts on the listed price, not on the request's chosen reward, so going
   lower is an edit. With a listed price the old "Use suggested" button is hidden (the traveler's number
   is the suggestion); without one the sheet is unchanged.
2. The "Lowest price" pill shows only while the policy says pricing is on (otherwise it would equal best
   match and do nothing).
3. The journey page lets the owner change the price on any journey that is not completed, cancelled or
   expired, mirroring the server; the server's `journey_price_not_editable` is handled if it disagrees.
4. The trip preview sheet also shows the price (plan lists the cards; the earlier carry-over said "card
   and preview").
5. The listed price is not repeated on the trip detail sheet on Find Travelers; the propose sheet is the
   place that shows it with its fee and total.
6. Test support: `pumpDiscovery` gained `keyboardInset`; `tripCardFixture` gained `price`.

## 4. Tests

Flutter 1,353 to 1,374 (+21: `test/l4b_traveler_pricing_test.dart`, 21 tests). Two L3B tests (`pausing a
journey` detail screen, `the last kind of item cannot be switched off`) now answer the new policy route
and settle its read; no assertion changed. `money_test` and the perspective tests are untouched and
green. The new tests cover: the contract decoding; the draft rules (empty, half, both, ceiling, precision,
server refusal until the value changes); the listed price on the card and the sort sent as
`listed_price`; no price line and no sort pill when pricing is off; card to sent offer in three taps
with the listed reward on the wire; the different-amount path with the server's minimum, the
below-listed note and the amount sent; the unchanged sheet without a price; a listed price that fell
under the minimum; trip card and preview lines; the editor resending the stored price (also with pricing
off) and stopping on half a price; the journey page card, the sheet's PATCH body, the two nulls, a
ceiling refusal on its field, no card when off, read-only when finished; the repository sending the
price on a whole-route write. `flutter analyze --fatal-infos`, `dart format`, `flutter gen-l10n` clean,
`l10n_untranslated.json` empty (EN, FR, AR).

## 5. Gate screenshots

360 px wide, EN and AR, in `/mnt/project-files/l-series-screens/L4B/`:
`editor-your-price-filled`, `-error`, `-keyboard`; `journey-your-price-set`, `-empty`;
`journey-price-sheet`, `-keyboard`; `find-travelers-listed-price`; `propose-sheet-listed`,
`-different-amount`; `browse-trips-priced`; `trip-preview-priced`; each as `<name>-en.png` and
`<name>-ar.png`.

## 6. Known limits

- The price section is on the journey create and edit screens and the journey page; there is no price
  field in the sea or flight leg rows (a price belongs to the journey).
- The preview of a person's trips (person page) shows the card line only.
