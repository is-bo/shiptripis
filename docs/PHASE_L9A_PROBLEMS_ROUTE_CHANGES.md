# L9A: Problems and route changes, backend (contract)

Package L9A of `docs/WASSLA_DISCOVERY_PRO_PLAN.md` (section 4, as narrowed on 2026-11-13), built
against `docs/WASSLA_DISCOVERY_PRO_SPEC.md` section 12. Backend and console. L9B builds the app
screens on this contract. There is no courier kind and nothing here prepares for the parked
professional and courier work (`docs/parked/WASSLA_PROFESSIONAL_AND_COURIER_PLAN.md`).

Two features, one rule: **a report or a schedule change never writes a `Deal` column and never calls
a lifecycle transition.** Money moves only through the existing dispute, cancellation and staff
no-show actions. A search of `apps/problems/*.py` and `apps/trips/schedule_changes.py` for status
writes and transition calls finds none, and a test keeps it that way
(`test_problems_and_schedule_changes_never_write_a_deal_status_or_transition`).

## 1. Problem reports (`apps.problems`)

### Model

`problems.ShipmentProblem` (table `problems_shipment_problem`, migration `problems/0001_initial`):

| Field | Notes |
| --- | --- |
| `deal` | FK `deals.Deal`, `PROTECT`, `related_name="problems"` |
| `reported_by`, `reporter_role` | the party, `sender` or `traveler` |
| `kind` | see below |
| `note` | up to 1,000 characters, optional, shown to both parties |
| `status` | `open`, `escalated`, `acknowledged`, `closed` |
| `escalated_at` | set when the kind goes to staff at once |
| `acknowledged_by/at/reason`, `closed_by/at/reason` | staff only; reasons are internal |
| `closed_by_audit` | FK `admin_panel.AdminAuditLog`, set when a recorded no-show closed it |

Constraints: one live (not closed) report per `(deal, reported_by, kind)`; a closed row has its
closer and time; an acknowledged row has its acknowledger; an escalated row has `escalated_at`.

### Kinds

`sender_unavailable` (traveler only), `traveler_no_show` (sender only), `recipient_unavailable`,
`parcel_mismatch`, `parcel_damaged`, `trip_disrupted` (a flight, drive or crossing cancelled or
delayed), `customs_delay`, `other`. `parcel_damaged`, `parcel_mismatch` and both no-show kinds are
**escalated** at once; the others are `open`.

### API

`GET /api/deals/<id>/problems` (either party; anyone else gets 404):

```json
{
  "deal_id": 12,
  "tracking_number": "WSL-3NZ5FHHQ",
  "viewer_role": "sender",
  "no_show_kind": "traveler_no_show",
  "can_report_no_show": false,
  "no_show_reason": "pickup_time_not_reached",
  "no_show_available_at": "2026-11-16T19:40:27Z",
  "reportable_kinds": ["recipient_unavailable", "parcel_mismatch", "..."],
  "results": [
    {"id": 5, "kind": "parcel_mismatch", "status": "escalated", "reporter_role": "traveler",
     "reported_by_me": false, "note": "...", "escalated": true, "created_at": "...",
     "acknowledged_at": null, "closed_at": null}
  ]
}
```

`reportable_kinds` lists the general kinds the deal takes now (empty outside the reportable
statuses); the no-show kind is answered by `can_report_no_show`, so the app never guesses the window.
No email, phone, address, staff identity or staff reason is ever in a party payload (a key walk test).

`POST /api/deals/<id>/problems` with `{"kind", "note"}`: `201 {"problem": row, "created": true}`, or
`200` with `"created": false` and the live report when the same person already has one of that kind.

| Code | HTTP | When |
| --- | --- | --- |
| `not_a_party` | 404 | the caller is neither party |
| `problem_kind_invalid` | 400 | unknown kind |
| `problem_note_too_long` | 400 | note over 1,000 (`max_length`) |
| `problem_kind_not_allowed_for_role` | 403 | a no-show kind by the wrong party |
| `problem_report_not_allowed` | 409 | a general kind outside funded to `delivery_ready` (`deal_status`) |
| `no_show_report_not_allowed` | 409 | the window is shut; `reason` and, when too early, `available_at` |

No-show `reason` values: `deal_not_funded`, `deal_not_active`, `pickup_time_unknown`,
`pickup_time_not_reached`, `pickup_already_confirmed`, `no_show_already_recorded`, and on the read
only, `already_reported`.

**The no-show window** (`apps.problems.services.no_show_window`): the deal is funded, in a pre-pickup
status, no no-show is recorded, `agreed_pickup_at` is set and `now >= agreed_pickup_at`, and
`pickup_confirmed_at` is empty. The report locks the deal row (no key update) so it is judged
against a racing pickup confirmation or staff decision, and never writes it.

**Effects of a report:** one `problem_reported` timeline event (`problem_id`, `problem_kind`,
`problem_status`, `reporter_role`); one `deal.problem_reported` notification to the **other** party
with the deal resources, `problem_id`, `problem_kind` and `tracking_number` (the note is not in the
push). Nothing else.

### Staff

- Console **Disputes › Problems** (`/admin/disputes/problems/`, route `problems`): escalated first,
  then open, acknowledged, closed; oldest first inside each. Filter by state, "attention" (escalated
  only), search by tracking number or either party's email. The overview shows "Problems to look at"
  with the escalated count.
- Problem page (`/admin/disputes/problems/<id>/`, route `problem-detail`): the report, both people,
  the delivery's state and pickup times, handling history, audit lines. **Acknowledge** (open or
  escalated) and **Close** (any live report), each with a required reason up to 500 characters,
  audited as `problem.acknowledged` / `problem.closed` with the tracking number as reference. The
  parties get a neutral `deal.updated` refresh and see only the new state.
- Who: reading needs `view_disputes`, acting `manage_disputes` (checked again in the service). These
  are the disputes capabilities: a problem is the dispute's lighter sibling and the same people
  handle both. No new capability.
- **No-show link.** On a live no-show report, staff holding `record_no_show` see "Record a no-show",
  linking to `/admin/marketplace/deals/<deal>/no-show/?party=<sender|traveler>`: the deal and the
  party, nothing else. That page (route `deal-no-show`, capability `record_no_show`) is the console
  face of the existing action: same service, same rule (a traveler no-show refunds the sender in
  full; a sender no-show is recorded without a refund), a required note. The deal page offers the
  same page while the delivery waits for pickup.
- **Recording closes the reports.** `apps.admin_panel.services.record_deal_no_show` wraps the
  existing `record_no_show` in one transaction with the `deal.no_show_recorded` audit row and closes
  every live no-show report on the deal with `closed_by_audit` set to that row. The admin API
  (`POST /api/admin/deals/<id>/no-show`) now calls the same function, so a replay of an already
  recorded no-show writes no second audit row.

## 2. Schedule changes (`apps.trips.schedule_changes`)

Times only; stops cannot be added or removed on a live journey.

### Models

`trips.JourneyScheduleChange` (migration `trips/0012_schedule_changes`): `journey`, `proposed_by`,
`status` (`pending_senders`, `applied`, `withdrawn`), `reason` (up to 500), `original` and `proposed`
(every leg's `{leg_id, position, depart_at, arrive_at}`), `affected` (each parcel's classification),
`applied_at`, `withdrawn_at`, `withdrawn_by` (`traveler` or `no_longer_valid`). One waiting change
per journey (unique partial index).

`trips.JourneyScheduleChangeConsent`: `change`, `deal`, `state` (`pending`, `accepted`, `declined`),
`reasons` (`deadline`, `shift`, `pickup`), `arrival_before`, `arrival_after`, `pickup_before`,
`pickup_after`, `decided_at`. One per `(change, deal)`.

### Classification

The rules were settled by the advisor on 2026-11-13 (spec 12, plan L9A and 5.1e).

A parcel is affected when the change touches a leg its allocation covers, and it is live
(`offer_accepted`, `payment_required`, or a pre-pickup or in-carriage status). Its arrival is the
drop-off leg's arrival; its pickup is the departure of its first leg. The baseline is **what that
sender last agreed to**: the latest applied change they accepted; otherwise, for the arrival, the
drop-off arrival frozen in `arrival_snapshot` at funding, and for the pickup, the `pickup_at` of the
match's compatibility snapshot; otherwise the time in force. A change that applied without asking
does not move the baseline, so small changes cannot add up unnoticed.

A parcel **not collected yet** is **material** when any of these holds:

- `deadline`: the new arrival is after the request's `deadline_at` (exactly at it is fine) and later
  than the agreed arrival;
- `shift`: the new arrival is more than `marketplace.route_change.material_shift_minutes` (default
  360) from the agreed arrival, earlier or later (exactly the threshold is fine);
- `pickup`: the new pickup is more than the same threshold from the agreed pickup, either way, or it
  moved earlier to before the deal's `agreed_pickup_at`.

A parcel **already collected** (pickup confirmed, not delivered) is **informed**: no consent row,
never material, never holds the change back, listed with `"informed": true`. Its sender is told when
the change applies, with the old and new times on the timeline and in their view, and their view
names the actions that exist today (`report_problem`, `open_dispute`). A consent that was pending or
declined when the parcel was collected stops counting: pickup confirmation settles the journey's
waiting change after commit.

### API

| Route | Who | What |
| --- | --- | --- |
| `GET /api/journeys/<id>/schedule-changes` | owner | every change, newest first, with legs and parcels |
| `POST /api/journeys/<id>/schedule-changes/preview` | owner | what the change would do; writes nothing |
| `POST /api/journeys/<id>/schedule-changes` | owner | propose; `201` with the change |
| `POST /api/journeys/<id>/schedule-changes/<change>/withdraw` | owner | withdraw a waiting change |
| `GET /api/deals/<id>/schedule-change` | sender | the latest change that touched this parcel |
| `POST /api/deals/<id>/schedule-change/accept` or `/decline` | sender | answer; may change while it waits |

Body: `{"legs": [{"id", "depart_at", "arrive_at"}], "reason"}` listing the legs that change, with
timezone-aware ISO instants; unlisted legs keep their times. The traveler's view
(`id, journey_id, status, reason, created_at, applied_at, withdrawn_at, withdrawn_by, legs[],
parcels[], waiting_for`) lists every leg (`*_before`, `*_after`, `changed`) and every affected parcel
by tracking number with `material`, `informed`, `reasons`, arrivals, pickups and `consent_state`.
The sender's view carries only their own parcel and only the legs it rides, with `informed`,
`can_answer` and `actions`. The preview adds `notices`: `[{"code": "ticket_recheck", "text": ...}]`
when a flight or sea leg's times change ("Your ticket will be checked again. Until staff approve it,
this trip takes no new proposals. Deliveries already paid for continue.").

Refusals (`code`, HTTP): `journey_not_owned` 403, `journey_not_reschedulable` 409 (not active or in
progress), `schedule_change_invalid` 400 (`index` of the bad row), `schedule_change_empty` 409,
`schedule_change_pending` 409 (`schedule_change_id`), `leg_already_arrived` 409,
`leg_already_departed` 409 (a departed leg keeps its departure; its arrival may move),
`leg_departure_in_past` 409, the existing leg-sequence codes from `validate_leg_times`,
`schedule_change_not_found` 404, `schedule_change_not_pending` 409,
`schedule_change_answer_not_needed` 409 (also for a collected parcel).

### Lifecycle

1. **Propose.** Locks the journey (then the legs), checks the times fit the trip and the publication
   time rules (`apps.trips.services.validate_leg_times`, extracted from the existing sequence check),
   classifies. No material parcel: it **applies at once**. Otherwise it **waits**, each material
   parcel's sender gets a consent row, a `schedule_change_proposed` timeline event and a
   `journey.schedule_change_proposed` notification.
2. **Answer.** `accept` or `decline`, changeable while it waits and the parcel is not collected; the
   traveler gets `journey.schedule_change_answered`. The last acceptance applies it in the same
   transaction.
3. **Settle.** Re-run whenever a deal on the journey closes or is collected (funded cancellation,
   pre-funding release, staff no-show refund, pickup confirmation, after commit) and by a durable `schedule_change_settle` job every
   30 minutes while it waits. Settling re-checks that the times still fit (a leg departed or
   arrived since, the journey no longer live, the legs changed: **withdrawn as `no_longer_valid`**,
   traveler and asked senders told), re-classifies (a parcel funded meanwhile is asked too), and
   applies once no material parcel lacks an acceptance.
4. **Apply.** Writes the new leg times; a re-timed flight or sea leg goes through the existing
   `_invalidate_leg_proofs` path a route edit uses, so its ticket is pending again and the trip takes
   no new proposals until staff approve it (on apply, never on proposal); records `schedule_change_applied` on every affected parcel and
   tells its sender (`journey.schedule_change_applied`), and the traveler when it had waited; calls
   `apps.trips.progress.schedule_leg_reminders(journey)` so the reminders follow the new times (the
   old jobs find the time moved and do nothing).
5. **Withdraw.** The traveler takes a waiting change back; times stay; asked senders get
   `journey.schedule_change_withdrawn`.

`Deal.arrival_snapshot`, `funded_scheduled_arrival_floor_at`, `agreed_pickup_at` and the deal's
status are never written.

### Declining, then cancelling

While a sender's decline stands on a waiting change, their cancellation is **caused by the
traveler** (`CancellationQuote.caused_by = "traveler"`): no late penalty, so the amounts are exactly
the existing traveler-cancellation outcome (full refund of what was collected, no compensation). The
deal's `cancellation_reason` is `declined_schedule_change`, the `cancelled_after_funding` event
carries `caused_by`, the settlement note says so, and the email says "cancelled after the traveler
changed the times" (EN, FR, AR). No new refund rule. If the change is withdrawn first, a later
cancellation is the sender's again.

## 3. Channels

All in `apps/core/channels.py`, `apps/notifications/push.py` (EN, FR, AR, essential, Deliveries) and
`backend/services/internal/notification/dispatcher.go`:

| Channel | To | Payload |
| --- | --- | --- |
| `deal.problem_reported` | the other party | deal resources, `problem_id`, `problem_kind`, `tracking_number` |
| `journey.schedule_change_proposed` | each asked sender | `journey_id`, `schedule_change_id`, deal resources, `tracking_number` |
| `journey.schedule_change_answered` | traveler | the same, `consent_state` |
| `journey.schedule_change_applied` | affected senders; the traveler if it waited | the same (traveler: no deal) |
| `journey.schedule_change_withdrawn` | asked senders; the traveler if no longer valid | the same |

`journey.schedule_change_proposed` resolves in the inbox once the sender answered or the change is
no longer waiting. `problem_id` and `schedule_change_id` are allowed push data fields.

Timeline kinds added to `DealEvent.Kind`: `problem_reported`, `problem_acknowledged`,
`problem_closed`, `schedule_change_proposed`, `schedule_change_accepted`,
`schedule_change_declined`, `schedule_change_applied`, `schedule_change_withdrawn`. Party-visible
payload keys: `problem_id`, `problem_kind`, `problem_status`, `reporter_role`, `schedule_change_id`,
`consent_state`, `material`, `material_reasons`, `arrival_before`, `arrival_after`, `informed`,
`caused_by`.

## 4. Migrations

All additive: `problems/0001_initial`, `trips/0012_schedule_changes`,
`deals/0012_alter_dealevent_kind`, `finance/0029_alter_scheduledjob_kind`. `schema.sql` re-exported.

## 5. Console

Disputes › **Problems** (queue and page, above); the deal page gains **Problems** (with "Record a
no-show" while the delivery waits for pickup) and **Route changes** (each change touching this
parcel, whether it needed the sender and their answer); the journey page gains **Schedule changes**
(every change with its legs before and after and its parcels). `action_form.html` shows a Back
button instead of the form when an action is not available.

## 6. Tests

`apps/problems/tests/test_l9a_problems.py` (26) and `apps/trips/tests/test_l9a_schedule_changes.py`
(45). Covered: the no-show window at each boundary (a minute before, at, after the agreed pickup;
funding, pickup confirmed, recorded no-show, unknown pickup time); role and kind; the duplicate; the
deal row byte-identical before and after a report; the staff link carries the deal and party only;
recording closes the report with its audit row; acknowledge and close with reasons and permissions;
classification at each boundary (threshold exactly and plus a minute, earlier and later, deadline
exactly and plus a minute, a deadline already missed by the agreed arrival, the pickup side,
off-parcel legs, three small changes that add up, an accepted change as the new baseline, the
setting); a collected parcel informed and never blocking; a pickup confirmed while a consent is
pending; apply at once; wait, accept, decline, change of mind, withdraw, no-longer-valid; arrival snapshot, floor, pickup and status untouched; cancellation after a decline
equals the traveler-cancellation quote and settles the change; a pending offer refused at acceptance
against the new times; reminders follow the new times; ticket proof back to review on apply, with the preview's notice,
and the trip refusing a new proposal until then; an active journey's route edit is refused (existing
test `test_a_live_journey_cannot_be_rewritten_through_the_service`); privacy of both
views; inbox resolution; the settle job.

## 7. Judgment calls

Items 1 to 4 were settled by the advisor on 2026-11-13 and written into spec 12 and plan L9A. The
rest are this package's own calls, for the gate and the end review.

1. **Baseline is what the sender agreed to**, not the times in force.
2. **Pickup side** counts for parcels not collected yet. "Moved earlier to before the agreed pickup
   time" counts only when the pickup moved earlier, because the agreed pickup can sit a few minutes
   after the leg's departure (an interpolated stop).
3. **Collected parcels are informed, never asked**, and never hold a change back.
4. **A re-timed ticket leg goes back to review on apply**, through the existing path.
5. **Unfunded accepted deals** (`offer_accepted`, `payment_required`) are classified and asked too:
   the sender is about to pay for the old times.
6. **Problem capabilities reuse** `view_disputes` and `manage_disputes`; no new capability.
7. **A repeat report returns the live one** with 200 rather than an error.
8. **General reports** are accepted from funding to `delivery_ready`, not before funding and not
   after delivery (a dispute covers that).
9. **The console no-show page** was added: the plan's "existing admin no-show action" was API only.
   The API path now goes through the same function, so a replay writes no second audit row.
10. The unreachable `schedule_leg_reminders` call in `replace_journey_route` was removed (the
    advisor's answer asks for this).
11. **Informed senders are told when the change applies**, not when it is proposed: until then the
    times may still be withdrawn.
12. A waiting change is **withdrawn as `no_longer_valid`** when the journey stops being live, its
    legs change, or the trip has progressed past the new times.

## 8. Known limits

- `agreed_pickup_at` keeps its funded value after a change (no deal column is written); the no-show
  window keeps reading it, so after an accepted later pickup a no-show report opens at the old time.
  Staff decide no-shows by talking to both people, so this is recorded rather than built around.
- The console is English only.
- L9B builds every app screen; until then the push opens Deliveries.
