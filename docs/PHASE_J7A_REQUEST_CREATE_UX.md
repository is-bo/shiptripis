# Phase J7A — Request-creation UX cleanup: Boost moves after publication

Status: implemented, TEST only. Stripe TEST, Chargily TEST,
`PAYOUT_DZD_EXECUTION_ENABLED` false, no LIVE provider activation and no
real-money operation.

Starting point: `92a9fe8` (J6.4 PASS). Branch `claude/j7a-request-create-ux`.
**Mobile only — no backend runtime change, so no Railway deployment.**

Two defects the owner found on a real device, both on the last step of the
request form. The `−` and `+` controls around the offer sat visibly higher than
the field they changed. And Boost was being offered during creation at all,
which is the wrong question at the wrong moment.

---

## 1. The product decision: Boost is a post-publication action

Before a request exists there is nothing to make more attractive. A sender who
wants a traveller to look harder at an unposted parcel can simply offer more —
that is what the offer field is for. Asking the same person, in the same breath,
to *also* attach a separate bonus that carries its own separate fee is two
controls for one intention, and the second one only makes sense once the first
has been tried and has not worked.

So the question moves to where it has an answer:

* **Creating a request** asks route → parcel → timing → **your offer** →
  deposit → pay. No Boost, no Boost fee, no Boost copy, no "total including
  Boost".
* **A published request** — status `open`, unmatched — offers **Add Boost** on
  its detail screen, twice: in a card that says why it is appearing now, and in
  the footer beside Find travelers, which is where the sender is standing when
  they decide the request is not moving.

**The economics did not change.** J2's Boost is still extra reward the traveller
receives in full, with its own platform fee charged on top, editable while the
server permits it and frozen by the existing rules. J6.1–J6.3's authoritative
totals are untouched. J7A changed *when* the question is asked, not what the
answer costs.

### Backend compatibility

No backend change. `boost_eur_cents` on the creation serializer stays
`required=False, min_value=0, default=0`, so an older client that still sends a
zero — or a non-zero — Boost is accepted exactly as before. The shipped mobile
client now **omits the key entirely** rather than sending `0`: `DeliveryRequestDraft`
already dropped it at zero, and an explicit zero would say the sender declined
something they were never shown. The pricing quote is likewise asked without a
Boost parameter.

---

## 2. What changed in the mobile client

### `request_create_screen.dart`

* Removed the Boost card, its three preset chips, its explainer, `_chosenBoostCents`,
  `_quotedBoostCents` and `_chooseBoost`.
* `_fetchPricingQuote` no longer sends `boost_eur_cents`; `_quoteIsCurrent` no
  longer compares one.
* `_submit` passes no `boostEurCents`, so the create body has no such key.
* The offer section is now: a heading (**Your offer**) and its one-line
  explanation, the server's **band** — Minimum and Recommended side by side —
  the stepper, the below-recommended / competitive note, and the server totals.
* `_PricingTotalsCard` reads three `chosen_terms` lines: Traveler receives,
  ShipTrip fee, You pay. The itemised Boost reading (base reward, Boost bonus,
  Boost fee) was unreachable here once creation cannot carry a Boost, and a card
  able to name a Boost on this screen would be naming something the sender was
  never offered. It still reads `traveler_total_minor` and
  `sender_total_with_boost_minor` verbatim, so "You pay" remains the whole
  obligation whatever it is made of. The itemised reading lives where a Boost can
  exist: the Boost screen, the Offer and the Deal.
* `RequestCreatePricingSeed` (test-only) gained optional parcel fields so a test
  can drive a *postable* form and inspect a real create body.
* Footer: Back now takes the width of the word rather than a fixed third of the
  bar. "Retour" broke across two lines in French and "Back" itself broke at 1.6×
  text.

### `AppAmountStepper` — new design-system component

`− [ 30.00 € ] +` was three unrelated widgets in a `Row` aligned on
`CrossAxisAlignment.start`, with each button nudged down by a hard-coded
`EdgeInsets.only(top: 8)`. The amount field carries its own label above its input
box, so the buttons started 8 points below the top of the **label** while the box
started below the whole label line. On a phone the two circles sat about twenty
points above the digits, and the gap grew with the text scale, because the label
grows and the magic 8 does not.

No padding constant fixes that, because the mismatch is a function of the label's
rendered height. So the three controls became one component:

* one bordered box drawn once, with the field's own fill, radius, focus and error
  borders;
* one label above the whole control (suppressed on this screen, where the section
  heading two lines up already says "Your offer", and still attached to the input
  for a screen reader);
* an `IntrinsicHeight` row with `CrossAxisAlignment.stretch`, so both ends are
  **exactly** the input's height and share its vertical centre by construction
  rather than by arithmetic;
* hairline rules between the ends and the field;
* `minWidth`/`minHeight` of 48 on each end, and a glyph that grows with the text
  scale up to a cap.

The component does no arithmetic. The step, the floor and the ceiling belong to
the screen, which gets them from the server.

### Step behaviour

* The step is **€0.50**, unchanged, and is not rounded to whole euros: €12.30
  plus one press is €12.80.
* `−` stops at the server's minimum rather than going below it.
* Pressing sets the field immediately and prices through the **same 350 ms
  debounce as typing**. Under the old code each chip tap fired a read at once;
  with `+`/`−` now the main way to move small amounts, holding `+` through five
  steps would have been five reads. It is one.
* Assigning the new value writes a `TextEditingValue` with the caret at the end;
  a bare `.text =` collapses the selection to offset −1 and drops the caret to
  the head of the number.

### `request_detail_screen.dart`

* The Boost card's action reads **Add Boost** when there is none and **Change
  Boost** when there is; the footer button does the same, from `request.isBoosted`.
* The not-yet-boosted card opens with a sentence explaining why Boost is
  appearing now: the request is live. A sender who never met Boost during
  creation should not be shown a control with no context.
* **Fixed a pre-existing overflow found by these tests.** The boosted card's
  header row put "Active Boost: €5.00" and a status pill side by side with no
  flex — a `RenderFlex overflowed by 211 pixels` in English at 411 wide, in every
  build since J2. The amount now takes the room and wraps; the pill keeps its
  natural width.

### Copy

Three new strings in `en` / `fr` / `ar`: `boostAddAction` ("Add Boost") and
`boostPostPublicationOnly`. No new copy on the creation screen — `pricingYourOfferLabel`,
`pricingMinimumLabel`, `pricingRecommendedLabel` and `requestProposedRewardHelp`
already said the right things, and none of them mentions a Boost.

### Unchanged on purpose

Deposit screen, checkout, payment order creation, guest payer, publication and
request status: not touched. The deposit's recommendation, custom amount, €3
minimum, pay-in-full, ceiling and remaining balance are all read from the
server's own obligation, which at creation is now simply base reward + delivery
fee because the Boost is zero. `POST /api/parcels/<id>/boost` and the Boost
screen are unchanged.

---

## 3. Tests

`mobile/test/phase_j7a_request_create_ux_test.dart` — **45 tests**, all green.

| Group | What it holds |
|---|---|
| Boost is not offered while the request is being written | Twelve Boost strings absent; no `ChoiceChip`; no text containing "Boost"; every pricing-quote body free of `boost_eur_cents`; the totals card is exactly three server lines; `DeliveryRequestDraft.toJson` omits the key; a real Post through the form carries no `boost_eur_cents` and the reward the sender chose |
| The offer section | Minimum and Recommended both on screen from the server; the recommendation preselected; editable and the quote follows; above recommendation allowed and called competitive; below recommendation allowed and only noted; below minimum refused and Post blocked; unusable text refused and priced against nothing |
| The stepper | `+` adds €0.50 and `−` takes it off, both immediate in the field and reflected in the next quote; `−` stops at the minimum; typing then stepping continues from what was typed; five fast taps move five steps and cost one read |
| Quote refresh (J6.3 guarantees) | Five keystrokes debounced into one read at 350 ms; a slow older answer never replaces a newer one, and the stale figures are marked "updating"; an empty offer is prefilled with the recommendation |
| The control is one component | 18 cases — 320×640, 390×844, 411×869, landscape, 1.3× and 1.6× text, each in EN/FR/AR — asserting one vertical centre, matched heights, symmetrical ends, ≥48 pt tap targets, no exception and nothing clipped off either edge. Plus: Arabic mirrors the control but not the arithmetic; both ends and the input are named for a screen reader; the whole step reads correctly in FR and AR at 320 |
| A published request is where Boost is offered | Add Boost on an unboosted open request with its explanation; Change Boost and the amount when boosted; the server's refusal still honoured; setting a Boost afterwards still posts `boost_eur_cents` and shows the server's 15 % Boost fee, not the 25 % delivery rate |

`mobile/test/phase_j63_request_boost_total_test.dart` was trimmed from 21 to
**10** tests. The pricing-contract group (7) and the deposit group (3) are
untouched and still green; the three groups that drove the creation screen's
Boost chips were testing a control that no longer exists. Their subject matter is
covered elsewhere and the file's header says where: the refresh, debounce and
latest-answer-wins guard in the J7A file; the itemised Boost money lines on the
Offer and Deal surfaces in `phase_j61_offer_boost_projection_test.dart` and
`phase_j62_boost_copy_offer_refresh_test.dart` (27 assertions between them).

**Full mobile suite: 729 tests green.** `flutter analyze`: no issues.
`dart format`: no changes. No backend test tier ran, because no backend file
changed.

---

## 4. Visual verification

Rendered PNGs of the real widgets, inspected rather than asserted, on the
throwaway golden rig (not committed — absolute Windows font path, and golden PNGs
do not survive CI's Linux runner).

Reward step: 320×640, 390×844, 411×869, landscape 844×390, 390×844 at 1.3× and
1.6× text — each in English, French and Arabic. Published request detail with and
without a Boost, in English and Arabic.

What the pictures showed that assertions had not:

* the `−`, the field and the `+` on one centre line at every size, with the
  buttons growing with the field at 1.3× and 1.6× rather than staying put;
* in Arabic the whole control mirrors — `+` on the left, `−` on the right, `€`
  and the digits on the start side — with no change to what the glyphs mean;
* "Your offer" printed twice, as the section heading and again as the field
  label, on the first pass. The field label is now attached for a screen reader
  and not drawn;
* "Back" rendering as "Bac / k" in the footer at 1.6× and "Retour" as "Retou / r"
  in French — a pre-existing footer split, fixed here;
* the boosted detail card's 211-point overflow, which the test run surfaced and
  the Arabic screenshot confirmed fixed.

---

## 5. Release

Branch CI, merge, TEST APK and the deployment decision are recorded in
`docs/IMPLEMENTATION_STATUS.md`.

No Railway deployment: the change set is `mobile/lib` and `mobile/test` only, so
the deployed runtime at `shiptrip-production-f7f7.up.railway.app` is still the
J6.4 release and every TEST safety guarantee is unchanged —
`PAYMENTS_ENVIRONMENT=test`, Stripe `sk_test_`, Chargily `/test/api/v2` with a
`test_sk_` key, `PAYOUT_DZD_EXECUTION_ENABLED=false`. Nothing was created at a
provider and no LIVE or real-money operation was performed.
