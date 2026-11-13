# L9B: Problems and route changes, mobile

Package L9B of `docs/WASSLA_DISCOVERY_PRO_PLAN.md`, on top of L9A
(`docs/PHASE_L9A_PROBLEMS_ROUTE_CHANGES.md`). The app draws what the server says and decides nothing:
which kinds can be reported (`reportable_kinds`), whether the "did not come" window is open
(`can_report_no_show`), who is asked about new times (`can_answer`, `material`, `informed`) and which
actions a collected parcel has (`actions`) are all read from the payloads. A report or an answer never
cancels, refunds or moves a deal. No backend, migration or contract change.

## 1. What a member sees

- **No-show** (deal screen, above the pickup area). When `can_report_no_show` is true: "The sender did
  not come" (traveler) or "The traveler did not come" (sender). One tap opens a sheet with an optional
  note and the line "Wassla staff will look at it. Nothing is cancelled or refunded yet." After sending,
  the deal shows the report's state (With Wassla staff / Being looked at / Closed) and "Message in chat".
  The other person sees a banner "The sender/traveler says you did not come" with "Reply in chat" and,
  when the server allows, their own report action.
- **Report a problem** (deal screen, "Problems reported"): every report on the delivery, from both people,
  with who made it, its state and its note; a "Report a problem" sheet lists the general kinds the server
  offers now (never the no-show kinds, which have their own action). A kind must be chosen before the
  button works. A refusal stays in the sheet in words; offline says nothing was sent. Nothing is queued.
- **Traveler, "Trip times"** on a live journey: "Change times" opens the legs with tappable departure and
  arrival. "Review the changes" calls the preview and shows: whether it applies at once or waits for N
  senders, the server's notice (the ticket re-check line, as sent), the changed legs, the parcels by
  tracking number split into "must agree" (with reasons and arrival before/after) and "will be told". An
  optional note to senders (when some must agree). "Send new times" / "Apply new times". While a change
  waits, the journey shows who was asked and their answers, with "Withdraw the new times"; no second change
  can start. A change the server dropped says the trip moved on.
- **Sender**: the deal shows a prompt when asked, when they declined or accepted a waiting change, and
  for a collected parcel (until delivery). The answer screen compares old and new pickup and arrival,
  says why they are asked, shows the traveler's note and the changed legs, and offers Accept / Decline.
  Decline asks first ("Nothing is cancelled... you can still change your mind") and never cancels; after
  it stands the screen reads the existing cancellation quote and shows the server's amounts with "Counted
  as the traveler's cancellation" (`caused_by`), and "Cancel this delivery" opens the existing cancel
  screen. A collected parcel is told only: no Accept or Decline, and only the actions the server names
  (report a problem, open a dispute).
- **Bell and push**: `deal.problem_reported` opens the deal; `journey.schedule_change_proposed` opens the
  sender's answer screen (the traveler's copy opens the journey); `.._answered`, `.._applied`,
  `.._withdrawn` open the deal (sender) or journey (traveler). Live events refresh the same screens.

## 2. Code

`domain/problems.dart`, `domain/schedule_change.dart` (parsers, no rules); `CancellationQuote.causedBy`;
`ProblemRepository`, journey and deal repository additions; providers `dealProblemsProvider`,
`dealScheduleChangeProvider`, `journeyScheduleChangesProvider` (optional reads: no retry, a failure
renders nothing and never fails the delivery or journey page; pull to refresh and live events re-read).
Screens: `features/problems/problem_widgets.dart`, `features/deals/schedule_change_answer_screen.dart`,
`features/journeys/change_times_screen.dart`, `features/journeys/schedule_change_widgets.dart`. Routes
`/deals/:id/schedule-change`, `/journeys/:id/change-times`. `pickJourneyDateTime` (was private) is shared.
Strings: 132 keys in EN, FR, AR.

## 3. Screenshots (360 px, EN and AR)

In `/mnt/project-files/l-series-screens/L9B/`, named `<screen>-<language>.png`: `no-show-action`,
`no-show-reported`, `no-show-banner`, `no-show-sheet-keyboard` (keyboard open), `problems-list`,
`problem-sheet`, `deal-schedule-notice`, `answer-asked`, `answer-declined` (with the quote),
`answer-informed`, `journey-change-waiting`, `change-times-edit`, `change-times-review`.

## 4. Tests

`test/l9b_problems_route_changes_test.dart` (33): parsers, live events, push and inbox destinations; the
no-show action for each role, hidden while the server says shut, the reported state, the banner, a refusal;
problem list and sheet (kind required, body is `{kind, note}`, no-show kinds not offered, failure stays);
sender prompt, accept, decline (confirm, no cancel, quote and traveler line), collected parcel, withdrawn,
empty, Arabic RTL; traveler section, withdraw, dropped change, review needs a changed time, preview body,
send body, applies at once, refused preview. Flutter 1,428 before, 1,461 after.

## 5. Known limits

- The leg editor does not know which legs already departed or arrived; the server refuses
  (`leg_already_departed`, `leg_already_arrived`) and the screen says so in words.
- Backend note for Codex/L9A: none blocking. `agreed_pickup_at` keeping its funded value is already recorded.
