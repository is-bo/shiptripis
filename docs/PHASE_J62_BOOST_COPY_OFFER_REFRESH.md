# Phase J6.2 — Boost terminology cleanup and offer live refresh

Status: implemented, TEST only. Stripe TEST, Chargily TEST,
`PAYOUT_DZD_EXECUTION_ENABLED` false, no LIVE provider activation and no
real-money operation.

Starting point: `378e195` (J6.1 PASS). Branch `claude/j62-boost-copy-offer-refresh`.

J6.1 left two MINOR findings this phase closes: the Boost fee was still called
"ShipTrip boost share" on the Deal, payment and offer screens, and an offer already
open on a Traveler's phone did not update when the sender changed their Boost. No
Boost economics, commission, acceptance rule, ledger, payout, Deal lifecycle, J4
matching or historical record changed.

---

## 1. Terminology

Under J2 the sender adds a Boost, the Traveler receives all of it, and ShipTrip
charges the sender a separate fee on it. "ShipTrip boost share" described the
retired split model, where ShipTrip kept part of the Boost. The fee now has one
name everywhere a user sees it:

| | EN | FR | AR |
|---|---|---|---|
| The fee on the Boost | **Boost fee** | **Frais Boost** | **رسوم التعزيز** |
| The Boost the Traveler receives | Boost bonus | Bonus Boost *(was "Bonus de mise en avant")* | مكافأة التعزيز |

The ARB key was renamed with the meaning: `moneyPlatformBoostRevenue` →
`moneyBoostFee`. The Arabic follows the app's established Boost noun (التعزيز),
parallel to "رسوم ShipTrip" for the delivery fee. French already said "Boost" on
every J2 surface; "mise en avant" was the retired package's word.

The sender's hierarchy now reads identically on the offer, Deal and payment
screens: Base delivery reward · Boost bonus · Traveler receives · ShipTrip fee ·
Boost fee · You pay (Total on the payment screen). The Traveler sees Base delivery
reward · Boost bonus · You receive, and never a fee.

| Surface | Before | After |
|---|---|---|
| Deal screen, sender | ShipTrip boost share | Boost fee |
| Payment screen, sender | ShipTrip boost share | Boost fee |
| Offer (negotiation) screen, sender | ShipTrip boost share | Boost fee |
| Boost screen, "What the Boost costs" card | ShipTrip fee | Boost fee |
| Request detail Boost button, FR | Mettre en avant cette demande | Booster cette demande *(the screen it opens was already titled that)* |
| Boost screen compatibility note, FR | Une mise en avant ne change pas… | Un Boost ne change pas… |

The Boost screen row matters as much as the rename: "ShipTrip fee" is what the
*delivery* commission is called on every other screen, so a card about the Boost
alone was using the delivery fee's name for a different amount.

**Searched and unchanged.** The J5 propose sheet shows no fee line. Push and inbox
copy name no amount. `boostPlatformKeeps` ("ShipTrip keeps") and the other
"mise en avant" strings belong to the retired package and are not rendered by any
screen. The Admin/Finance console keeps its technical "platform Boost revenue"
wording, which is correct there. No database row, audit text, notification payload
or `BoostIntentEvent` was rewritten.

## 2. The event

**A Boost edit emitted nothing.** `set_boost_intent` wrote the request, recomputed
ranking and appended a `BoostIntentEvent`, but published no channel. `offer.updated`
existed, but it is a lifecycle event (counter, decline, cancellation): it raises
the bell, sends a push ("Offer updated — Open ShipTrip to review the changes"),
and the client maps it to matches, the match, its offers, the request, the
journey, the inbox and the badge. Reusing it would have woken a Traveler's phone on
every Boost tweak and re-read seven resources to update one number.

**New channel: `offer.economics_changed`** (`apps/core/channels.py`). A neutral
refresh hint, modelled on the existing `deal.updated`:

* **Identifiers only.** `{"match_id", "offer_id"}` plus the bus envelope
  (`event_id`, `ts`, `targets`). No amount, no rate, no status.
* **Published from `set_boost_intent`, inside its transaction**, so it goes out on
  commit and a refused or rolled-back edit publishes nothing. A no-op edit (same
  amount) returns before it and publishes nothing.
* **Scope is exactly the offers whose figures moved:** pending V1 EUR offers, on
  pending matches for that request, not expired. One event per such offer.
  Countered, declined, withdrawn, expired and accepted offers are not signalled;
  after acceptance the request is `matched` and the edit itself is refused
  (`boost_request_not_active`), so nothing can be published for a frozen offer.
  Legacy DZD offers carry no Boost and are excluded. Travelers on other requests
  receive nothing.
* **Targets the Traveler only.** The sender made the edit; their own save already
  runs `refreshVolatileState`, which re-reads their mounted offer and list.
* **Resolved on arrival** (`notifications/resolution.py`, beside `deal.updated`):
  the inbox row goes straight to history, so the badge never moves.
* **Not push-eligible:** no `_PUSH_SPECS` entry, so no FCM, no lock-screen text.
* **Go:** added to the notification dispatcher's `subscribeChannels`, which relays
  it to the Traveler's open sockets like any other targeted event.

The read that finds the offers takes no lock. The request row is already held by
`set_boost_intent`, and acceptance — the only writer that could close one of these
offers concurrently — serialises on that row.

## 3. The client

**One new live resource, `LiveResource.offerEconomics(matchId)`.**
`resourcesForLiveEvent('offer.economics_changed', …)` returns exactly
`{matches, offerEconomics(matchId)}`: the Open offers list (its rows print the
total) and the open offer. Not the inbox, not the badge, not requests, journeys,
deals or payments — the one early return sits before the block that adds the bell
to every other event.

**Only a pending offer listens.** The negotiation screen watches its match and
registers `offerEconomics(matchId)` while, and only while, the server marks the
latest offer's figures `provisional`. When the offer is accepted, declined,
countered away or expires, the next read reports `frozen` or `unavailable` and the
screen unregisters. A closed or historical offer never subscribes. Its callback
invalidates `matchDetailProvider(matchId)` and nothing else: one
`GET /api/matches/<id>`. The offer history list is not re-read, because past
offers publish no total a Boost could change.

**Nothing is computed.** The screen never adds, subtracts or patches an amount.
The event says "re-read"; the hero, the breakdown, the provisional note and the
accept dialog all come from the re-read offer.

**Feedback.** When a re-read changes a figure the viewer can see on the *same*
offer, one `InfoNotice` appears above the money: "Offer updated. These are the
latest amounts." / "Offre mise à jour. Ces montants sont les plus récents." /
"تم تحديث العرض. هذه أحدث المبالغ." It is a live region, so a screen reader
announces it; it does not block, navigate or accept anything. It does not appear on
first load, when a re-read changes nothing, or for a new offer (a counter has its
own heading). A Traveler is not told the offer updated because a sender-only
figure moved. Removing the Boost removes the Boost row, the base row and the
provisional note, and the hero drops to the base.

**Heading row.** Rendering the screens at 320 px with real fonts and large text
showed the offer heading was a `Row` of an `Expanded` title and a fixed pill, so a
long French status ("En attente du voyageur") crushed "Votre offre". It is now a
full-width `Wrap`: title and pill sit at opposite ends as before when they fit, and
the pill takes its own line when they do not. Nothing is truncated.

**Inbox.** `NotificationChannel.offerEconomicsChanged` renders as an Offer row in
history and opens the negotiation. An installed pre-J6.2 build ignores the socket
frame (unknown event names never trigger a read) and lists the history row as an
unrecognised, non-tappable item.

## 4. Stale acceptance fallback

Unchanged and still the guarantee. Realtime only shortens the time a stale figure
is on screen; it cannot close the race, because the Traveler can tap Accept before
the event lands. Acceptance still sends the totals the dialog showed and the server
still refuses a difference with 409 `offer_economics_changed`, committing nothing.
The screen refreshes, the snack explains, and accepting again is an explicit
choice of the new figures. Tested on both sides (§7).

## 5. Performance

* **No polling, no global refresh.** One event → at most one
  `GET /api/matches/<id>` (only if that pending offer is open) and one
  `GET /api/matches` (only if the Open offers list is mounted; it is shared with
  Home through the same provider).
* **Coalesced and deduplicated** by the existing `LiveUpdates`: a burst of edits
  inside the 75 ms window is one read, and a replayed or duplicated `event_id`
  (socket reconnect, push copy) is none.
* **J1.2 catch-up untouched.** `offerEconomics` carries an id, so it is not a
  collection and resume/reconnect reconciliation is not widened by it; the route
  resources for `/matches/<id>` already re-read the offer on resume.
* **Backend:** one extra indexed `SELECT` per Boost edit, and per open offer one
  inbox row plus the existing durable dispatch job — the same obligation every
  targeted event carries.

## 6. Deferred: legacy paid package in the J4 total

J6.1's MINOR stands: the J4 Find Travelers envelope's
`total_offered_reward_eur_cents` is `chosen reward + boost_eur_cents` and ignores a
retired paid package. There is no authoritative historical field on that envelope
a client could present instead, and the backend reader that knows the package
totals (`unbound_paid_boost_totals_by_request`) is not published there. Fixing it
is a backend contract change, not a presentation-only correction, so it is
deferred. Legacy-only; the offer and the Deal are correct.

## 7. Test evidence

**Backend** — `apps/matching/tests/test_phase_j62_offer_economics_signal.py`, 5
tests: increase, decrease and removal each publish one identifier-only signal to
the Traveler, relayed after commit on the new channel, with the re-read offer
carrying the new total, the badge unchanged, no push spec, three history rows and
nothing for the sender; a no-op edit and a refused edit publish nothing, and
nothing is relayed before commit; only the open counter (not the countered offer)
is signalled, an expired or declined offer is not, and another request's Traveler
is not; an accepted offer's request refuses the edit and nothing is published; the
stale-accept guard still refuses the pre-edit totals and accepts the re-read ones.

**Mobile** — `test/phase_j62_boost_copy_offer_refresh_test.dart`, 21 tests:
EN/FR/AR fee and bonus names, the retired phrase absent from every ARB and Dart
source, and French naming the Boost one way; the sender's offer hierarchy in
order; Deal, payment and Boost screens say Boost fee; FR and AR sender breakdowns on
a 320 px phone without overflow; the event's exact resource set; the inbox row
opens the negotiation; the Open offers list re-reads once while the badge does
not; Boost increase, decrease and removal on an open offer (hero, rows, note,
update line, one detail read, no history read); the sender's re-read; an unchanged
re-read shows no update line; a burst plus WS/push duplicates plus a replay cost one
read; another match's signal, chat, `deal.updated` and protocol frames cost none;
an accepted offer ignores the signal; an offer that closes while open stops
listening; a stale confirm is refused, the late signal is harmless, and the new
totals are sent and accepted; the Arabic update line is RTL on a small phone.
`test/support/harness.dart` gained an optional `extraRoutes` so a routed test can
follow `openDeal`.

**Mutation checks.** Never registering the subscription fails six tests (increase,
decrease, removal, sender, burst, Arabic); registering it unconditionally fails
both closed-offer tests.

**Visual check.** Rendered through the throwaway golden rig with real fonts (not
committed): EN Traveler, AR Traveler at 320 px, FR sender at 320 px, EN sender, AR
sender at 1.3× text, FR Traveler at 320 px and 1.3× text, FR and AR Boost screens.
The update line sits above the money, mirrors in Arabic, and the sender breakdown
reads in the stated order in all three languages.

**Totals** — see `docs/IMPLEMENTATION_STATUS.md` for the full-suite counts, CI
runs, deployment and APK.

## 8. Findings

**New in J6.2:** none open.

**Found while searching, pre-existing, not changed here:**

1. **Request creation price card (MAJOR, pre-existing — backend contract +
   frontend).** Found by reading code, not reproduced on a device. With a Boost
   preset chosen, the card shows "Traveler receives" as base + Boost
   (`boost.total_offered_reward_eur_cents`) but "Total sender cost" as the base
   total (`chosen_economics.sender_total_minor`), so a €30.00 base with +€5.00 reads
   €37.50 where the Deal will be €43.75. The draft quote publishes no
   Boost-inclusive sender total, and adding the Boost block's cost to it in Dart
   would be client-derived money. Related: before a reward is entered the quote
   omits `total_offered_reward_eur_cents`, which parses as €0.00; and
   `PricingBoostQuote` reads fee and sender-total keys the server never sends
   (dormant — nothing renders them). Needs a server total on the draft quote, then
   the card can show Boost fee and the real total.
2. **Arrival events never reach the socket (MINOR, backend).** The Go notification
   dispatcher does not subscribe to `deal.arrival_reported`,
   `deal.arrival_confirmed` or `deal.arrival_declined`, so those refresh open
   screens only through push or resume catch-up. `services/HANDOVER.md` also still
   says "24 channels".
3. **Legacy package total in J4 (MINOR)** — §6, deferred.
