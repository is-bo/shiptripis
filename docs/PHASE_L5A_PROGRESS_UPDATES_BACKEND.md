# L5A: Progress updates and reminders, backend (contract)

Package L5A of `docs/WASSLA_DISCOVERY_PRO_PLAN.md`, built against `docs/WASSLA_DISCOVERY_PRO_SPEC.md`
section 11. A traveler tells Wassla "at the port", "departed" and "arrived" for each leg; every funded
parcel on that leg shows it, labelled "reported by the traveler"; and a durable reminder asks when the
traveler forgets. A report is a statement: no deal status changes, no money moves, no payout gate moves.

## 1. What exists after L5A

- **Reports.** `trips.JourneyLegProgress(leg, kind, source, reported_by, reported_at, retracted_at)`.
  `kind` is `at_port`, `departed` or `arrived`; `source` is `traveler` (`staff` is stored for a later
  package). One live row per leg and kind (partial unique index on `retracted_at IS NULL`).
  Retraction stamps `retracted_at`; rows are never deleted.
- **Rules** (`apps/trips/progress.py`, all server-side, under the journey row lock):
  owner only; journey status `active` or `in_progress` (paused journeys still report, because funded
  deals continue); `at_port` only on a sea leg and only before `departed`; `departed` needs the
  previous leg `arrived` (first leg: nothing); `arrived` needs `departed`; not more than 24 hours before
  the planned time (departure time for `at_port` and `departed`, arrival time for `arrived`). The same
  report twice returns the existing row (200) and tells nobody again.
- **Fan-out.** For each deal with a `funded` or `in_transit` allocation on the leg: one `DealEvent`
  of kind `traveler_progress` (payload `source: "traveler_reported"`, `progress_id`, `progress_kind`,
  `leg_id`, `reported_at`), and one notification to the sender on channel `deal.progress_reported`
  (ids and the kind only). A retraction adds a `traveler_progress_retracted` event to the same deals
  and a neutral `deal.updated` refresh. `apps/deals/timeline.py` allowlists `source`, `progress_id`,
  `progress_kind` and `leg_id`.
- **Reminders.** New `ScheduledJob` kind `leg_reminder`. Publishing a journey (and editing an active
  one) records, per leg, a departure question at `depart_at + depart_after_minutes` and an arrival
  question at `arrive_at + arrive_after_minutes` (marketplace policy `reminders`, defaults 30 and 60).
  The handler does nothing unless reminders are on, the journey is live, the leg's planned time equals
  the payload's, the leg carries a funded parcel, no live report exists and the kind can be reported
  now. Otherwise it notifies the traveler on `journey.leg_reminder` and schedules the next attempt
  `repeat_after_minutes` later, up to `max_repeats`. Running twice asks once.
- **Resolution.** In the inbox a `journey.leg_reminder` notification resolves when a live report of
  that kind exists for its leg (`apps/notifications/resolution.py`).

## 2. API

| Route | Notes |
| --- | --- |
| `GET /api/journeys/<id>/progress` | Owner only. Per leg: `reports` (with `can_retract`, `retractable_until`) and `next_actions` `[{kind, available_at, can_report_now}]`, server-authored. |
| `POST /api/journeys/<id>/legs/<leg_id>/progress` body `{kind}` | 201 new, 200 repeat. Row: `{id, leg_id, kind, source, reported_at, retracted_at}`. |
| `POST /api/journeys/<id>/progress/<progress_id>/retract` | Within 10 minutes. Repeat is a harmless 200. |
| `GET /api/journeys/progress/pending` | `{results: [{journey_id, leg_id, kind, place_name, planned_at}]}`: the questions due for the caller now (Home). Empty when reminders are off. |

Refusal codes (flat `{code, detail}`): `journey_not_owned` 403, `journey_not_reportable` 409,
`progress_kind_not_allowed` 409, `progress_out_of_order` 409, `progress_too_early` 409 (with
`available_at`), `progress_not_found` 404, `progress_retract_window_closed` 409, `progress_has_followup` 409.
A bad `kind` is a serializer 400.

## 3. Events (three places, plan 1.5 rule 8)

`deal.progress_reported` and `journey.leg_reminder` are in `apps/core/channels.py`, in the push matrix
(`apps/notifications/push.py`, EN, FR, AR, essential class) and in `subscribeChannels` in
`backend/services/internal/notification/dispatcher.go` (the Go list test passes).

## 4. Schema (additive)

`trips_journey_leg_progress` (migration `trips/0011`); choices only on `deals_event.kind`
(`deals/0011`) and `finance_scheduledjob.kind` (`finance/0028`). `backend/contracts/sql/schema.sql`
regenerated.

## 5. Not touched

`Deal`, `apps/deals/arrival.py` (early arrival stays its own fact), every payout gate, every amount.
A test proves each deal row, its allocations and its status events are identical before and after a
full set of reports.

## 6. Tests

`apps/trips/tests/test_l5a_progress.py`: ordering rules, fan-out to exactly the deals on the leg, the
byte-identical deal row, retraction rules, the reminder handler in every no-op case and the notify case
(including running twice and the repeat chain), scheduling on publish, inbox resolution, and the pending
questions. No console or mobile screen changes in this package, so there are no gate screenshots.
