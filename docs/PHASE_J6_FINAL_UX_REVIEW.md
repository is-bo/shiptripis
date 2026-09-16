# Phase J6 — Final UX, Device and End-to-End Acceptance Review

One hard pass over the product as it actually renders, rather than over what
the phase reports say it renders. Starting main `3d7be28`, branch
`claude/j6-final-ux-review`.

ShipTrip stayed in **development / TEST** throughout. Stripe TEST, Chargily
TEST, `PAYOUT_DZD_EXECUTION_ENABLED` false, no LIVE provider touched, no real
money moved, no production cutover started.

---

## 1. How the review was done

No physical Android device and no emulator were available on this workstation:
`flutter devices` lists only Chrome and Edge, `flutter emulators` reports no AVD
images, and the project has no `web/` platform. So the device pass was run as a
**rendered-pixel harness** rather than as an assertion pass — the real widget
tree, the real theme, the four bundled variable fonts and the Material icon font
loaded into `flutter test`, each screen pumped at a real viewport and written out
as a PNG through `matchesGoldenFile --update-goldens`, then read as an image.

That is what caught the blocker. Every existing RTL test asserted *which icon
constant* a screen named, and the constant was right; the glyph the phone draws
was not. Only a picture shows that.

The harness itself is deliberately **not committed**: it pins an absolute Windows
path to the Flutter SDK's `materialicons-regular.otf`, and golden PNGs do not
survive a move to a Linux CI runner. It is three files and reproducible in about
ten minutes — a `FontLoader` over `assets/fonts/*.ttf` plus the SDK icon font, a
`shoot()` helper wrapping `expectLater(find.byType(MaterialApp), matchesGoldenFile(…))`,
and the existing `test/support/harness.dart` device profiles.

### Viewports and locales covered

| Viewport | Covered |
|---|---|
| 320×640 small Android | yes |
| 390×844 iPhone with home indicator | yes |
| 411×869 Android, and with gesture inset | yes (existing suite) |
| 844×390 landscape | yes (existing suite) |
| 390×844 at 1.6× text scale | yes |
| Arabic RTL | yes, every screen shot in the pass |
| French | yes, request/deposit/discovery |

Physical device: **no**. Emulator: **no**. Deployed Finance console browser
session: **no** — it needs an operator login this environment does not hold, and
that is recorded as an access limitation rather than inferred. The Finance
surfaces were reviewed as source; J1.2's browser QA against real PostgreSQL rows
remains the last real operator pass over them.

---

## 2. BLOCKER — every directional glyph in Arabic pointed the wrong way

Material's `arrow_forward_rounded`, `arrow_back_rounded`, `chevron_left_rounded`
and `chevron_right_rounded` all carry `matchTextDirection: true`. Flutter already
mirrors them under an RTL `Directionality`. Ten call sites *also* flipped the
constant by hand:

```dart
isRtl ? Icons.arrow_back_rounded : Icons.arrow_forward_rounded
```

Two mirrors cancel. In Arabic the arrow rendered pointing **right**, back at the
origin it had just left.

The rendered proof, under one `Directionality` each:

| Named constant | ambient LTR | ambient RTL |
|---|---|---|
| `arrow_forward_rounded` | → | ← |
| `arrow_back_rounded` | ← | → |
| `chevron_right_rounded` | › | ‹ |

So on Find Travelers in Arabic, a Paris → Algiers trip laid its stops out
correctly (Paris on the right, Algiers on the left, which is right for Arabic
reading order) and then drew an arrow from Algiers *towards* Paris. The route —
the single most important fact on the Sender's main discovery screen — read
backwards, in the market's primary language. The same double flip reversed the
row chevron on Home, Profile, Notifications, journey detail, both location
pickers, the preferred-point field, the place component, the Find Travelers card
and the post-pickup CTA.

The fix is to delete the manual flips and let the framework mirror once.
`navigation.dart`'s back button and `identity.dart`'s round back button were
already doing this correctly and were left alone.

The test that locked the bug in is instructive, and its comment states the wrong
premise out loud:

```dart
// Pointing forward in Arabic means pointing left. A hard-coded
// `arrow_forward` would send the eye back to the origin.
expect(find.byIcon(Icons.arrow_back_rounded), findsOneWidget);
```

Both RTL arrow tests now assert the **rendered** direction — the glyph carries
`matchTextDirection` and the ambient direction is RTL — instead of which constant
was typed. A source guard in the new J6 suite fails if any screen reintroduces
the hand flip.

---

## 3. Findings by area

### Auth and onboarding — no findings

Sign up, sign in, role choice, verify e-mail, session restore and the router's
single `SessionState` redirect were reviewed as source. One guard, no per-screen
auth checks, no dead ends. Not redesigned.

### Home — one MINOR

Assembled from server booleans (`awaiting_user_id`, `can_submit_*`, `can_rate`),
completed work stays in History via the linked Deal's `activityState`, "See all"
appears only past three rows, and the first load shows its own shape rather than
claiming a calm inbox. The one nit: while `dealsProvider` is loading, the
attention section renders `SectionHeader(title: '')` — an empty header above a
skeleton. Deferred.

### Create request and pricing — no material findings

Minimum and Recommended are two side-by-side tiles with distinct labels and
distinct colour weight, "Your offer" is an editable field between ± €0.50
steppers, below-recommendation is an informational notice rather than an error,
below-minimum is an inline error that blocks the step, and the breakdown reads
from `effectiveEconomics` — server figures, not client arithmetic. €0.50 steps
render correctly in all three locales. The four-step form re-checks every earlier
step before Post and jumps back to the owning step on a server field error.

This screen gets the Boost economics right — `pricingTravelerReceives` is fed
`boost.totalOfferedReward`, i.e. base + Boost. The standalone Boost screen did
not, which is what made the asymmetry worth chasing.

### Boost — five MAJOR, two MINOR, all fixed

The breakdown card made four false statements about money on one screen:

| Rendered | Actually |
|---|---|
| heading "Remaining balance at delivery" | the cost of the Boost |
| "Traveler receives €5.00" | the Boost alone, not the reward |
| "Total sender cost €6.25" | Boost plus its fee, not the sender's total |
| "Your current amount is paid in full…" | the deposit screen's notice, on the Boost screen |

The platform fee was computed in the client — `((cents * bps) + 9999) ~/ 10000` —
with a hard-coded `2500` bps fallback, so a server on any other rate would have
been contradicted on screen. Exceeding the maximum raised
`pricingBelowMinimumError` with the *maximum* substituted, producing "Offer must
be at least €100.00" for being too high, with `'€100.00'` hard-coded in every
language. Boost history printed `sender_increased`, `frozen_into_deal` and
`consumed_by_funding` verbatim. And nowhere did the screen say the thing the
sender needs — that base reward plus Boost is what the Traveler receives.

Now: the card is headed "What the Boost costs"; the rows are "Added to the
Traveler reward", "ShipTrip fee" and "You pay for the Boost"; a saved Boost takes
the server's own `economics` split verbatim; an unsaved amount is projected from
the rate the server published and is labelled an estimate; with no policy at all
no fee is shown rather than one invented; the maximum has its own string; history
reads as sentences with an unknown future code degrading to "Boost updated"; and
"The Boost is added on top of the delivery reward you already offered. Base
reward + Boost is what the Traveler receives." sits under the figures.

Also fixed: the lock notice printed one sentence as both title and body, and
"Boost this request" appeared three times on one screen (top bar, card title,
section header) — now twice.

The legacy timed/package Boost vocabulary (`boostDuration`, `boostRankingTop`,
`boostChoosePackage`, `boostActiveUntil`, `boostBuyAction`, …) is still in the
ARB but **no screen renders any of it** — verified key by key. Dead strings,
recorded as deferred cleanup, not a live 24h reference.

### Deposit — one MAJOR, one MINOR fixed, one MINOR deferred

A Custom amount outside the server's bounds was accepted locally and refused a
round trip later as a snackbar with no connection to the field that caused it.
There is now an inline error against the server's own minimum and the full
amount, and Pay deposit is disabled while it stands.

The live breakdown printed the deposit twice in adjacent rows, the second
labelled with a whole sentence ("It's credited towards your final payment when a
traveler accepts."). That sentence is now a caption under the figure.

Deferred: the guidance card still duplicates the chips. €5.00 appears three times
on the screen and €3.00 twice. `phase8ff1_deposit_guidance_test.dart` asserts
those rows and their vertical order deliberately, so unpicking it is a design
decision that belongs to whoever owns that phase's intent, not to a review pass.

The full-deposit copy passes the check it was asked for: "Your current amount is
paid in full. If you increase the reward or Boost later, an additional balance
may be due." It does not imply no further balance can ever arise.

### Guest payer — three MAJOR, two MINOR, all fixed

The sheet labelled the amount **still owed** "Paid" (`paymentStatusPaid`), which
is the worst kind of wrong on a money screen. It now reads "Amount due" and
tracks the live order's outstanding figure rather than the amount it was opened
with. Two hard-coded English strings — `'Failed to generate guest link'` — reached
French and Arabic users; both are localised. Revoking said "Done" rather than
"Link cancelled". The link box carried a copy icon directly above a Copy link
button; one of them is gone.

On the polling question the brief asked about: a flat `Timer.periodic(3s)` ran for
as long as the sheet was open, with no backoff and no stop on repeated failure —
twenty reads a minute per open sheet waiting on a payment somebody else may take
ten minutes to make. `payment.*` already invalidates this order's request and
deal over the existing socket, so the sheet now **subscribes to the live update
it was already entitled to** and settles within a round trip of the webhook. The
poll stays as the answer for a sender whose socket is down, and steps
3s, 3s, 5s, 5s, 10s, then 20s. No new realtime subsystem; one `register()` call
on the existing `LiveUpdates`.

### Payment success — two MAJOR, fixed

`'Guest'` and `'Self'` were hard-coded English rendered as the value of a row
whose label already said the same thing, so a French receipt read "Payé par →
Self". The row is now "Paid by → You / Someone else", translated. The contextual
route was a hard-coded `'$origin → $destination'`, so every Arabic receipt
printed the route backwards; it now turns round with the locale.

Everything the brief asked about the four purposes holds: posting deposit says
the request is active and its button goes to Find Travelers (not "View delivery",
and there is no Deal to view); a deal balance shows amount paid, deposit credit
and remaining balance; paid-in-full shows no "Remaining €0" because the row is
gated on `isPositive`; guest-paid states it plainly. The receipt still carries no
payment method and no transaction reference despite the J3 report claiming both —
recorded, not fixed.

### Find Travelers — four MAJOR, two MINOR, all fixed

Judged on its own merits rather than on the J5 report, which overstates the card
("Suggested price… 'Propose' primary CTA") — the shipped card has neither, and
that is the right call: the price is the same on every row because it is the
sender's own, and repeating it is exactly the density the owner objected to.

Density is genuinely good: four candidates fit and scan at 390×844, three at
320×640, and nothing overflows at 1.6× text or in landscape. The route is the
loudest thing on the card, which is correct. No fabricated distance, no repeated
request information, no badge sprawl.

What was wrong:

* The count above the sort chips was a bare `4` with no noun. Now "4 travelers".
* `RouteFit.unknown` was rendered as "Compatible route" — the client naming a
  verdict the server never gave, on a screen whose own header comment forbids
  exactly that. The badge now degrades away and the rest of the card still reads.
* A Traveler with an empty display name was labelled with `findTravelersViewTrip`,
  so the card showed a person called "View trip".
* Every card's `semanticLabel` was the page title, so a screen reader said
  "Travelers for this parcel" once per row and never said who or where. It is now
  name · route · mode and date.

### Find Travelers — empty and ineligible — two MAJOR, fixed

Six states inspected: results, no candidates, awaiting deposit, already matched,
closed, in progress, plus the initial-error retry.

The no-candidates state is right and stays right — it says nobody matches *yet*,
that the request stays active, and that ShipTrip will tell them, and it offers no
Boost CTA because Boost never creates compatibility.

Two problems. A `reason` the client could not parse, or none at all, fell through
to "This request is closed." — telling the sender their request was dead on the
strength of a value the client had failed to read. It now says "This request
can't be matched right now."

And on the question the brief asked directly: the awaiting-deposit state titled
itself "Publish your request", explained "Pay the posting deposit to publish this
request", and then put **"Continue"** on the button. The title and body were
fine; the button named the flow rather than the thing the sender has to do, and a
sender who skims to the button could not tell that money was next. It now reads
**"Pay deposit"**, which is both clearer and what the button actually does — it
opens the deposit checkout.

### Find Travelers — View trip — two MAJOR, fixed

"Why this trip fits" listed *Identity verified* in the same ticked column as
*Picks up in Paris*, which reads as though a verified passport were a reason the
route suited the parcel. The J5 report claims this separation was already done;
it was not. `identity_verified` and `flight_proof_approved` now render under
their own heading, "Checks ShipTrip has done".

The sheet also showed **less** than the card that opened it. Per-stop times are
optional on the wire and were the only thing rendered, so on ordinary data the
detail sheet had no departure, no arrival and no transport mode, while the row
behind it said "Flight · Sep 20". The envelope's own `departs_at` / `arrives_at`
now render as "Flight · Departs Sep 20, 11:00 · Arrives Sep 20, 15:00".

Unknown match codes are still ignored safely. No internal algorithm language, no
score, no detour band.

### Propose offer — four MAJOR, fixed

The worst of the four: the sheet opened with the amount field pre-filled from
`economics.recommendedReward`, **not** from the reward the sender had already
chosen. A sender who posted at €30.00 opened this sheet on €35.00 and, tapping
Send offer, raised their own reward by five euro without ever being told. It now
opens on `request.chosenRewardEurCents`; "Use suggested" is still one tap away.

The field was labelled "Traveller's reward" directly beneath a box ending
"Traveller receives €35.00", where the two numbers mean different things — the
field is the **base** reward and Boost is added on top of it. It is now "Base
delivery reward", with "Your Boost of €5.00 is added on top of this." under it.

`parcelId: widget.requestSummary?.id ?? target.journeyId` would have proposed
against whatever parcel happened to share the journey's id. The sheet now takes
the screen's own `requestId`.

And the trip sheet stayed mounted underneath the propose sheet, so sending an
offer and returning from the negotiation screen landed the sender on a live "Make
an offer" button for a Traveler they had just proposed to. The trip sheet now
closes first.

Offer availability remains server-authoritative throughout — `propose_offer` and
`view_journey` are read from `actions`, never inferred.

### Negotiation screen — one MAJOR, reported rather than fixed

**The negotiation screen understates both sides' money whenever a Boost is set,
and it cannot be fixed in the client.** `Offer` carries `traveler_reward_minor`
and `sender_total_minor` and nothing else; `grep -n boost` over
`apps/matching/serializers.py` and `public_contract.py` returns nothing. Boost
lives on the delivery request and does not enter the projection until the Deal
funds.

So with a €30.00 base reward and a €5.00 Boost, a Sender weighing an offer reads
"Traveler receives €30.00 / ShipTrip fee / You pay €37.50", and a **Traveler
deciding whether to accept reads a hero that says "You receive €30.00"** — when
they will in fact be paid €35.00, and the Sender will in fact pay more than
€37.50 once the Boost and its fee land in the balance. The one number a Traveler
accepts an offer on is the one number this screen gets wrong.

Every figure on that screen is a server field today, which is correct. Closing
the gap means adding Boost to the offer money projection — a change to the
financial contract, which §31 of this phase's brief puts out of bounds. Computing
base + Boost in Dart would be exactly the client-derived financial truth the same
brief forbids, and would be wrong the moment the fee model changes.

**Handed to the backend.** `traveler_reward_minor` needs a companion — the
Traveler's total including Boost — and `sender_total_minor` needs to account for
the Boost and its commission, or the offer needs to carry `boost_eur_cents` so
the client can render the same base / Boost / total the propose sheet already
renders from the request envelope. The Deal screen already does this correctly
from `DealPaymentState.travelerBoostBonus`; the gap is specifically the pre-Deal
negotiation.

### Deliveries — two MAJOR, one MINOR fixed, one MINOR deferred

Live negotiations awaiting somebody's move were headed **"Offer history"** — the
one thing they are not. Now "Open offers". The journeys section's action was
**"Add a leg"**, which named a step inside the composer rather than the screen it
opens; it creates a whole trip, so it now says "Post a trip". Request rows joined
origin and destination with a middle dot, losing the direction every other list
in the app shows; they are now a directed route that turns round in Arabic.

Deferred: a Deal whose `activityState` is `unknown` is listed under **both**
Active and History. Defensible as a safety choice — better somewhere than
nowhere — but it should be one or the other.

Lifecycle transitions themselves are coherent, and completed work leaves Active
correctly because the filter reads the Deal's server-derived activity state
rather than the request's own status, which stops at `matched` for the whole life
of the delivery.

### Delivery detail — no findings

The route section is the best-behaved surface in the app. A funded Deal shows its
frozen snapshot behind a lock pill; a live journey shows a different pill; and an
absent route says so in neutral words that distinguish "not funded yet" from
"funded before snapshots existed", instead of leaving a silent gap. No mutable
Journey data is presented as a frozen Deal route.

### Dispute — no findings

Gated entirely on `deal.availableActions.contains('open_dispute')`, so expired
protection removes the action because the server removed it, not because the
client re-derived a window. A closed dispute stays visible as its own record
because a resolution moved money. A stale cached action cannot survive a refresh:
the deal is invalidated on resume and by `dispute.*` live events.

### Rating — no findings

Driven by the server's rating state rather than re-derived from booleans:
`available` is the only state that offers the action, so the prompt disappears the
moment the viewer rates, and the section goes passive instead of asking again.
Blind semantics hold — a counterpart who has submitted shows "hidden until both",
not their score. A reveal window that closed with no counterpart rating shows
nothing rather than an empty score that would read as a bad review.

Deferred MINOR: revealed rating tags render as `tag.replaceAll('_', ' ')`, so a
server vocabulary code reaches the user de-snake-cased and untranslated.

### Payout methods — no material findings

EUR, DZD and Both, preference switching, Stripe TEST onboarding and the DZD
setup all reviewed. The three refusal states J1.2 separated are intact: a
correction request and a rejection say different things, in all three languages,
with no reviewer note leaked. No raw backend code reaches the card. One nit:
`DzdPayoutState.unknown` uses `stateUnexpectedTitle` as a body sentence.

### Finance / DZD review — one MINOR, fixed

Reviewed as source, not in a browser — see §1. The payout review queue reads well
for an operator: four buckets with the distinction that matters stated out loud
(a profile sent back for correction and a profile nobody has looked at are both
"not approved"), no account value anywhere on the list because a list gets
screenshotted into chat, the audited five-minute reveal confined to the detail
page, and a footer that says what approving actually binds.

One defect: the queue row and the detail page's "Name comparison" chip printed
`compare_names`' raw classification — a row read "name review_alias_spelling",
and the chip read `insufficient_attestation`. Those are values only somebody who
has read `payout_identity.py` can act on. There is now a `NAME_COMPARISON` map
following the same rule `METHOD_REASON` already followed: the sentence is what
the operator reads and the code stays beside it for grepping — "same name,
spelled differently (review_alias_spelling)".

No H5 financial semantics were touched. No accounting code changed.

### Notifications — no findings

Every row navigates from structured data — the dotted channel plus the payload
ids — so no English string is parsed to decide where a tap goes, which is also
what lets the inbox be translated. Active and History are separate buckets from
the server, "Mark all read" is gated on unread rows rather than on the bell
total, and the badge counts live actions. Deferred MINOR: the History screen is
pushed as a bare `MaterialPageRoute` rather than through go_router.

### Chat — no findings

The sender's bubble is inserted **synchronously**, before the send future can
complete, so there is no local delay; a failed send becomes a retryable pending
bubble rather than a lost message; the server's echo is reconciled by
`clientMessageId`; and in-flight sends are cancelled on dispose.

### Performance — no findings beyond J1.2, one improvement

J1.2 established that no app endpoint is slow and that the problem was client
request amplification; its five-second catch-up window and thirty-second read
budget are in place and were not touched. No timeout was raised anywhere in this
phase. The one new saving is the guest sheet's poll, above.

### Navigation — one MAJOR, fixed

The stacked-sheet defect in §Propose offer is the navigation finding. Otherwise:
four tabs in a `StatefulShellRoute.indexedStack` each keeping their own stack and
scroll, notifications pushed above the shell rather than spending a quarter of
the permanent navigation on a rare trip, and every task screen — create, pay,
handover, dispute — pushed on the root navigator so a stray tab tap cannot lose
work. Re-tapping the current tab pops to its root. No dead-end modal stacks
remain and no surprising Home resets were found.

### English copy — one MAJOR, fixed

The app shipped **both spellings of its own core noun**: 63 strings said
"traveller" and 13 said "traveler". Not in separate corners — on the Boost screen
one card read "Travelers receive 100% of the Boost bonus" and, three lines below,
"Only travellers who already match your parcel ever see it". `moneyTravelerReceives`
was "Traveller receives" while `pricingTravelerReceives` was "Traveler receives",
and both appear in payment flows.

Standardised on **Traveler / travelers** per the phase brief's vocabulary, across
all 63 strings, with "Travelling" → "Traveling". Mid-sentence case was left as
ordinary English rather than force-capitalised. Four tests that asserted the
British literal were updated.

No "escrow" anywhere. "Payment secured", "Payment protected" and "Funds held
pending delivery" are the vocabulary in use. No Driver or Courier. The raw
machine codes found are listed under Boost, Finance and Rating above.

### French — no findings

Request creation, deposit, Boost, discovery and payment inspected. "Publiez votre
demande", "Repères pour l'acompte", "Acompte recommandé / minimum", "Payer en
totalité", "ShipTrip calcule l'acompte à partir du total suggéré et applique le
minimum et le maximum en vigueur. Il sera déduit du paiement final : ce n'est pas
un supplément." — natural, not literal, correct `50,00 €` money order, no
overflow at any tested width. The new J6 strings were written in the same
register. Not stylistically rewritten.

### Arabic RTL — the blocker, plus one deferred MINOR

Beyond §2: the travel **sequence** was already semantically correct everywhere —
stop 0 on the right, later stops leftwards, which is native Arabic reading order.
It was only the arrow glyph that contradicted it. Price controls, currency
placement (`€ 5,00`), Boost, deposit, guest payer, payment success, Find
Travelers, the proposal sheet, the trip sheet and delivery detail were all shot in
Arabic and mirror correctly, with chips wrapping right-to-left in the right
order.

Deferred: dates render with Arabic-Indic numerals next to a `·` separator, and
Arabic-Indic zero *is* a dot — so "طيران · ٢٠ سبتمبر" reads at a glance as
"٢٠٠". Also deferred, and not a client fix: canonical place labels arrive
Latin-only, so an Arabic user reads "Paris · CDG → Algiers · ALG" in Latin script
inside otherwise-Arabic cards. That is a backend catalogue gap.

### Accessibility — one MAJOR, fixed

The candidate card's screen-reader label (§Find Travelers). Otherwise: tap
targets clear `AppSpace.minTapTarget` on the surfaces tested, the role switcher
and rating both carry explicit `Semantics` with `selected`/`button`, route
components announce "Origin to Destination", icon-only actions carry labels and
tooltips, status is never colour alone — every `StatusPill` pairs tone with an
icon and a word — and 1.6× text scale produces no overflow on any screen shot in
this pass.

### Visual consistency — no findings

Parchment ground, ink text, terracotta reserved for attention, Fraunces for
display and money heroes, DM Sans for everything else, Noto Sans Arabic under
`ar`, restrained shadows, no gradients. Every screen in the pass reads as the
same product; no surface still looks like generic Material. The wax seal, the
sun-button hero on Home and the parchment receipt all land.

---

## 4. Severity ledger

**BLOCKER — 1 found, 1 fixed.** Directional glyphs double-mirrored in Arabic.

**MAJOR — 20 found, 19 fixed, 1 reported to the backend.**

1. Boost breakdown headed "Remaining balance at delivery"
2. Boost alone labelled "Traveler receives"; Boost + fee labelled "Total sender cost"
3. Boost platform fee computed client-side on a hard-coded 2500 bps fallback
4. Boost over-maximum refused with an "at least" string and a hard-coded €100.00
5. Boost history printed raw wire codes
6. Boost screen never stated base + Boost = Traveler reward
7. Payment receipt rendered hard-coded `Guest` / `Self` in every locale
8. Payment receipt route hard-coded `→`, reversing the route in Arabic
9. Guest sheet labelled the amount still owed "Paid"
10. Guest sheet carried two hard-coded English error strings
11. Guest sheet polled every 3s indefinitely, ignoring the live update it was entitled to
12. Trip sheet listed trust checks under "Why this trip fits"
13. Trip sheet showed less schedule than the card that opened it
14. Propose sheet opened on the recommendation, silently raising the sender's own offer
15. Propose sheet labelled the base reward as though it were the whole reward
16. Propose sheet could address the wrong parcel
17. Trip sheet stayed mounted under the propose sheet
18. Live negotiations headed "Offer history"; "Add a leg" created a whole journey
19. `traveller` and `traveler` both shipped, sometimes in one paragraph
20. **Not fixed, handed to the backend:** the negotiation screen understates
    the Traveler's earnings and the Sender's total whenever a Boost is set,
    because the offer money projection has no Boost field

Plus, counted within the above areas and all fixed: unknown `route_fit` renamed
"Compatible route"; unknown ineligible reason claiming "closed"; the
awaiting-deposit CTA reading "Continue"; a custom deposit outside bounds with no
inline validation; every candidate card announcing the page title to a screen
reader.

**MINOR — 16 found, 7 fixed, 9 deferred.**

Fixed: bare result count; nameless Traveler labelled "View trip"; lock notice
printed twice; "Boost this request" three times on one screen; two copy
affordances on the guest link and a "Done" revoke message; deposit amount printed
twice with a sentence as a label; raw `compare_names` classifications in the
operator console.

Deferred, with reasons:

| Deferred | Why |
|---|---|
| Deposit guidance duplicates the chip amounts | 8F-F1 asserts those rows and their order deliberately |
| `ActivityState.unknown` Deals appear in Active *and* History | defensible safety choice; needs a product decision |
| Arabic date `·` next to Arabic-Indic digits reads as a zero | needs a separator decision across every date |
| Canonical place labels are Latin-only under `ar` | backend catalogue, not a client fix |
| Rating tags rendered as de-snake-cased English | needs the server's tag vocabulary localised |
| Home attention section renders an empty `SectionHeader('')` while loading | cosmetic, one frame |
| Dead legacy Boost strings still in the ARB | nothing renders them; verified key by key |
| `_syncInitial` mutates state during build on the deposit screen | benign today, worth tidying |
| Notifications History pushed outside go_router | works; inconsistent with deep-link handling |

---

## 5. Verification

* `flutter test` — **635 passing**, 0 failing (618 before; +17 new J6 tests,
  `mobile/test/phase_j6_ux_acceptance_test.dart`).
* `flutter analyze --fatal-infos` — **No issues found**.
* `dart format --output=none --set-exit-if-changed lib test` — clean.
* `flutter gen-l10n` — regenerated; `l10n_untranslated.json` is `{}`, so every
  new key exists in EN, FR and AR.
* Backend: `apps/admin_panel` (62 passed) and
  `apps/finance/tests/test_phase_j12_finance_route_performance.py` (16 passed),
  against embedded PostgreSQL. The broader finance and accounting suites were
  **not** re-run: no accounting, payout-routing, Deal-lifecycle or H5 reporting
  code was touched — the only backend change is three presentation labels on one
  operator page.

Two of the worst findings — `depositRemainingBalance` heading the Boost
breakdown, `paymentStatusPaid` labelling the amount still owed — were the same
mistake: a localisation key borrowed from another domain, where the sentence is
right for the screen it was written for and wrong for the screen it landed on.
After fixing both, every `l.<key>` reference in the feature screens was swept for
a key whose domain prefix does not match its file's own area. What is left is all
legitimate shared vocabulary — `money*`, `route*` and `rating*` on the Deal
screen that hosts those sections, `offer*` on the propose sheet that is an offer.
No further cross-domain borrow remains.

The ARB round-trip also collapsed two pre-existing duplicate keys
(`depositExplainer`, `boostExplainer`, each defined twice in all three files).
Last-wins was already the effective behaviour in both Python and the Flutter
tool, and a key-set diff confirms nothing was lost and no value changed.

---

## 6. TEST-only confirmation

Read back from the live Railway `production` environment of project `shiptripis`,
service `shiptrip`, rather than asserted from the runbook:

| Variable | Value |
|---|---|
| `PAYMENTS_ENVIRONMENT` | `test` |
| `STRIPE_SECRET_KEY` | `sk_test_…` — TEST key |
| `STRIPE_CONNECT_EXPECTED_MODE` | `test` |
| `CHARGILY_API_BASE` | `https://pay.chargily.net/test/api/v2` |
| `CHARGILY_SECRET_KEY` | `test_sk_…` — TEST key |
| `PAYOUT_DZD_EXECUTION_ENABLED` | `false` |
| `PAYMENTS_ALLOW_MOCK_PROVIDER` | `false` |
| `PAYMENTS_MOCK_WEBHOOK_ENABLED` | `false` |
| `RELEASE_ID` | `v1.0.0-rc.35+9614db6` (J4; unchanged by this phase) |

No LIVE provider activated, no real money moved, no production cutover begun, and
no variable was written. API origin used for the build:
`https://shiptrip-production-f7f7.up.railway.app` — `/readyz` answered
`v1.0.0-rc.35+9614db6` with database, migrations and rate-limit cache all `ok`.
No Railway deployment was made in this phase; J6 changed mobile code plus three
presentation labels on one operator template, and the labels ship with whatever
deployment comes next.

---

## 7. Launch readiness

For **development / TEST**, the product is in good shape. The lifecycle surfaces
— delivery detail, dispute, rating, payout methods, chat, notifications — are the
strongest parts of the app and produced no findings; they are server-authoritative
where they need to be and honest where data is missing. Navigation, the design
language and accessibility hold up across six viewports and three languages.

What this pass found was concentrated in two places, and both are now closed: the
**Boost and propose money surfaces**, where four labels named the wrong money and
one default silently changed the sender's own offer, and **Arabic**, where a
double-mirrored glyph reversed the route on the main discovery screen.

Remaining before any future LIVE cutover — none of it started here:

1. Provider activation: Stripe LIVE keys, Chargily LIVE keys,
   `PAYOUT_DZD_EXECUTION_ENABLED` true, per `docs/PROVIDER_ACTIVATION_RUNBOOK.md`
   and `docs/PHASE_H8B_PRODUCTION_CUTOVER.md`.
2. A real-money rehearsal on LIVE rails mirroring H7's TEST payout rehearsal.
3. Boost in the offer money projection, so the negotiation screen stops
   understating what a Traveler earns and what a Sender pays. This is the one
   finding from this pass that is still open, and it is a money figure a Traveler
   accepts an offer on.
4. The Finance control plane's 85–100 queries and 4–6 s per page — handed to the
   backend at J1.2 and still open. Operator-only, but it is the one genuinely slow
   server surface.
5. A deployed Finance console operator pass, which needs a login this environment
   does not have.
6. A physical-device pass on real Android hardware. Everything in this phase was
   verified at real viewport sizes with real fonts, but nothing was verified on
   glass.
7. The Arabic place-label gap: canonical place names have no Arabic form, so
   Arabic users read Latin script inside Arabic cards on every route.
8. Legal, privacy and support surfaces, which are outside every J-phase to date.

---

**J6 PASS.**
**ShipTrip DEVELOPMENT/TEST UX acceptance complete: YES.**
