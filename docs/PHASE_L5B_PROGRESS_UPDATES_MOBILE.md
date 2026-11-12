# L5B: Progress updates and reminders, mobile

Package L5B of `docs/WASSLA_DISCOVERY_PRO_PLAN.md`, on top of L5A
(`docs/PHASE_L5A_PROGRESS_UPDATES_BACKEND.md`). The app draws what the server offers and decides nothing
about order or time. A report is a statement: nothing here moves a deal, a payment or a payout. No backend,
migration or contract change.

## 1. What a member sees

- **Journey page, "Trip progress"** (owner, journey live): one step per leg on the shared lifecycle rail,
  each listing its reports ("Departed · Dec 2, 10:05"). The current leg is the first one not yet arrived.
  One large button offers the first action the server lists for it ("I'm at the port", "I've departed",
  "I've arrived"). Before the 24-hour window opens the button is off and the line under it says when it
  opens; otherwise the line says "Needs a connection. Nothing is saved for later." A strip under the
  button offers **Undo** for the latest report the server still lets the traveler take back (10 minutes,
  and not when a later report depends on it).
- **Home, "Needs your action"**: "Did you depart from {place}?" / "Did you arrive in {place}?" with
  "Yes, departed" (or arrived) and "Not yet". It comes from `GET /api/journeys/progress/pending`, which is
  read only when the traveler has a live journey. "Not yet" asks nothing of the server: it hides the
  question for this app session; the server's reminders keep their own schedule. A failed read shows
  nothing (Home never fails because a reminder could not load).
- **Reminder notification**: the push (`journey.leg_reminder`) and the inbox row open the journey with
  `?leg=<id>&ask=<kind>`, and the same question appears as a sheet. If the server no longer offers that
  step (answered on another device, window moved) no sheet opens and the stepper shows what is true now.
  The inbox row resolves server-side once the leg is reported.
- **Sender's deal timeline**: each live traveler report is a done step ("Your traveler has departed",
  "... has arrived", "... is at the port") with the line "Reported by the traveler". A retracted report
  is not shown. Sender view only.
- **Bell**: `deal.progress_reported` ("Update from your traveler") opens the deal;
  `journey.leg_reminder` ("How is your trip going?") opens the question.
- **Offline**: a report needs the network. There is no queue. A request that cannot reach the server shows
  "No connection, so your update was not sent. Try again when you are back online." and the button stays
  ready. Server refusals read as instructions (too early, out of order, journey cannot take updates, undo
  window closed, a later update depends on it).

## 2. Files

- `mobile/lib/domain/progress.dart`: `ProgressKind`, `JourneyProgress`, `LegProgress`, `ProgressReport`,
  `ProgressAction`, `PendingProgressQuestion`, and `DealProgressUpdate.fromTimeline` (applies retractions).
- `mobile/lib/data/repositories.dart`: `JourneyRepository.progress`, `pendingProgress`, `reportProgress`,
  `retractProgress`.
- `mobile/lib/app/app_state.dart`: `journeyProgressProvider` (refreshed with `LiveResource.journey`),
  `pendingProgressProvider` (new `LiveResource.progress`), `dismissedProgressQuestionsProvider`.
- `mobile/lib/features/journeys/progress_actions.dart` (words and the one write),
  `progress_widgets.dart` (stepper, question, sheet, Home card).
- Live layer: `deal.progress_reported` and `journey.leg_reminder` added to the known events; the reminder
  refreshes the inbox, the open journey and Home's question.
- Strings: 37 keys in EN, FR and AR (`progress*`, `dealProgress*`, two notification titles).

## 3. Gate screenshots (EN and AR, 360 px wide)

`/mnt/project-files/l-series-screens/L5B/`: `journey-stepper-{en,ar}.png`,
`journey-stepper-not-open-yet-{en,ar}.png`, `journey-stepper-offline-error-{en,ar}.png`,
`reminder-sheet-{en,ar}.png`, `home-question-{en,ar}.png`, `sender-deal-timeline-{en,ar}.png`. No new text
field, so no keyboard-open shot.

## 4. Tests

`mobile/test/l5b_progress_test.dart` (29): contract parsing, retractions, push and inbox destinations, live
events, stepper send/undo/locked/offline/refusal/AR/draft, reminder sheet, Home question (send, Not yet,
none, no live trip makes no request, failed read, AR), sender timeline. Two older journey-detail tests got
a `/progress` route because a live journey now reads it.
