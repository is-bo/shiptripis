# L12B: Proposal deadline and trip-fit alerts, mobile

Package L12B of `docs/WASSLA_DISCOVERY_PRO_PLAN.md`, built on the contract in
`docs/PHASE_L12A_PROPOSAL_DEADLINE_TRIP_FIT.md` and spec section 17. The app says how long a proposal has
left, shows an expired proposal as a designed state with its next step, and opens the right screen from the
two new alerts. **No backend change, no new setting, no money change.**

## 1. The deadline line (`features/offers/offer_deadline.dart`)

`OfferDeadline(offer, viewerId, dense, onElapsed)` reads only `expires_at`, `status` and
`awaiting_user_id`. Whose turn it is comes from the server's field, as everywhere else.

| State | Text |
| --- | --- |
| Pending, more than an hour left, the viewer must answer | "Answer by {day, time}" |
| Pending, more than an hour left, the other person must answer | "Waiting for an answer until {day, time}" |
| Last hour, viewer | "Answer within {n} minutes" (hourglass, amber) |
| Last hour, other | "Waiting for an answer, {n} minutes left" |
| Under a minute | "less than a minute" in the same sentences |
| Time ran out while the screen was open | "The time to answer has passed", and the screen re-reads |
| Expired (list rows) | "Expired {day, time}" |
| No deadline (switch was off) | nothing |

Times are in the device's time zone (`readDate` already converts). Minutes are rounded up. One timer,
re-armed on each tick: a minute apart while the deadline is far, 15 seconds apart in the last hour, exactly at
the deadline. `clockProvider` (`core/time/clock.dart`) is the only clock, so tests choose the moment. At zero
the line asks the screen to re-read (`onElapsed`); it never expires anything, and the buttons stay gated on
`allowed_actions`, so the server's word replaces the countdown.

Shown on the proposal screen (under the heading), on each Open offers row in Deliveries, and on each proposal
row of a request's detail screen (dense).

## 2. The expired state

- **Proposal screen.** Status pill "Expired", a notice "This proposal expired" ("No answer came in time.
  Nothing was reserved or charged..." with a sender and a traveler wording), the amounts read-only, and one
  next step on the action bar: **"Propose to another traveler"** for the sender (Find Travelers on that
  parcel) and **"Browse parcels"** for the traveler. No Accept, Counter or Decline.
- **`offer_expired` refusal** (409, from accept, counter, decline, withdraw): `ApiErrorCode.offerExpired`, a
  stale-state code. The screen refreshes and shows the state above; no error banner.
- **Rows.** An expired proposal reads "Expired {when}" in Deliveries and the request's proposal list.

## 3. The two channels

| Channel | Bell | Push and socket | Opens |
| --- | --- | --- | --- |
| `offer.response_reminder` | "A proposal is about to expire" | refreshes the proposal like any `offer.` event | the proposal (`/matches/<id>`) |
| `discovery.request_fits_trip` | "A parcel fits your trip" | inbox and badge only | Browse parcels, `/discover/requests?focus=<request>&journey=<journey>` |

Both follow the existing "marketplace activity" setting the server assigns; no new setting.

**The trip-fit alert** opens that parcel's preview with an "I can carry this" that speaks for the named trip
(no "Which trip?" chooser), under the line "Suggested for your trip {from -> to}". The app does not decide the
pair still fits: the server's `incompatible_candidate` refusal and its reasons are shown as for any other trip.
A trip that is no longer live falls back to the chooser. Browse reads on, up to 8 pages, until it finds the
parcel (the list is newest first, so it is almost always on the first). If the whole list does not hold it, a
notice says "This parcel is no longer open" above the list. The same notice exists for a trip
("This trip is no longer listed"), which also repairs the silent miss route alerts had.

## 4. Strings

19 keys in EN, FR and AR (`offerAnswerBy`, `offerWaitingUntil`, `offerAnswerWithin`, `offerWaitingWithin`,
`offerMinutesLeft`, `offerDeadlinePassed`, `offerExpiredOn`, `offerExpiredTitle`, `offerExpiredBodySender`,
`offerExpiredBodyTraveler`, `offerExpiredActionSender`, `offerExpiredActionTraveler`,
`notificationOfferReminder`, `notificationFitsTrip`, `requestFitsTripHint`, `discoveryFocusGone*` x4).
`l10n_untranslated.json` stays `{}`.

## 5. Tests

`mobile/test/l12b_proposal_deadline_test.dart` (32): the contract (deadline and awaited user read as
published, an expired offer has no actions, `offer_expired` is a stale code, both channels parse, destinations,
missing ids, push locations, live resources); each deadline state for each side, the countdown ticking and
re-reading at zero; the expired state for sender and traveler and the `offer_expired` refusal landing there;
both lists; the bell; the preview from the alert (that trip with no chooser, parcel on page 2, parcel gone,
the server's reason, a trip no longer live); every state in EN, FR and AR at 360 px. Test support gained an
optional `now` on `containerFor`, `discoveryContainer` and `pumpDiscovery`.

Flutter 1,461 before, 1,493 after. `flutter analyze --fatal-infos` and `dart format` clean.

## 6. Screenshots

`/mnt/project-files/l-series-screens/L12B/`, 360 px, `-en` and `-ar`: `proposal-answer-by`,
`proposal-countdown`, `proposal-waiting-until`, `proposal-waiting-countdown`, `proposal-expired-sender`,
`proposal-expired-traveler`, `deliveries-open-offers-countdown`, `request-expired-proposal`,
`bell-reminder-and-fit`, `parcel-preview-from-alert`, `parcel-gone`. No form field was added, so there is no
keyboard-open shot.

## 7. Judgment calls (for Ismail's end review)

1. **No server endpoint for one request card.** The trip-fit alert finds the parcel by reading the public
   list on, newest first, up to 8 pages. A `GET /api/discovery/requests/<id>` would be exact; it is a backend
   change, so it is left to Codex if wanted (reported on the board).
2. **The countdown is only the last hour**, as the plan says; far from the deadline the exact time is shown.
3. **Expired proposals are not added to the bell** as a new row type: `offer.updated` keeps the generic
   "Offer" row; the push and the proposal screen carry the wording.
4. **The expired proposal screen hides the deadline line** because the notice says it.
