# L12A: Proposal deadline and trip-fit alerts, backend (contract)

Package L12A of `docs/WASSLA_DISCOVERY_PRO_PLAN.md` (section 4), built against
`docs/WASSLA_DISCOVERY_PRO_SPEC.md` section 17, with Ismail's numbers of 2026-11-13: **a proposal
waits 6 hours for an answer, or until the pickup time if that comes first, with one reminder 1 hour
before.** Backend and console. L12B builds the app on this contract.

No compatibility decision exists outside `apps/matching`: the deadline reads the pickup time the
engine already computed for the offer it is writing, and the trip-fit alert calls
`compatible_journeys_for_request` and keeps its ranking order.

## 1. Policy

Two groups in the `marketplace` section (`apps/core/marketplace_policy.py`), both on the console's
"Marketplace features" form, saved as one audited settings revision (`manage_settings`):

```
"offers":    {"response_deadline_enabled": true, "response_hours": 6, "reminder_before_hours": 1}
"discovery": {..., "trip_fit_alerts_enabled": true, "trip_fit_max_travelers": 30, "trip_fit_daily_cap": 5}
```

| Key | Bounds | Meaning |
| --- | --- | --- |
| `offers.response_deadline_enabled` | bool | Off: new proposals get no deadline. Proposals that have one keep it. |
| `offers.response_hours` | 1 to 168 | The deadline is the sending time plus this, or the pickup time if sooner. |
| `offers.reminder_before_hours` | 0 to 167, **smaller than `response_hours`** | One reminder this long before the deadline; 0 for none. Refused on save and on the form otherwise. |
| `discovery.trip_fit_alerts_enabled` | bool | Off: no trip-fit alert; route alerts work as before. |
| `discovery.trip_fit_max_travelers` | 1 to 100 | Travelers told about one request, best ranked first. |
| `discovery.trip_fit_daily_cap` | 1 to 50 | Trip-fit alerts one traveler receives in a rolling 24 hours. |

A revision with no such keys reads as these defaults.

## 2. Response deadline (`apps/matching/offer_deadlines.py`)

### Setting it

`create_sender_offer` and `counter_offer` (`apps/matching/v1_services.py`), the only two places an
offer row is written, read the time once (`sent_at`) inside their locks, pass it to the engine as
`at`, and write:

```
expires_at = min(sent_at + response_hours, evaluation.compatibility.pickup_at)
```

`pickup_at` is the engine's own pickup time for this match (for a flight, the departure), from the
evaluation the write already runs; the engine refuses a pair whose pickup is not after `at`, so the
deadline is always in the future. The policy comes from the revision the offer is priced under
(`policy.settings_version`), so one write never mixes two revisions. `Offer.expires_at` is
immutable: a later schedule change (L9A) does not move it, and acceptance re-validates as before.

### Jobs

Written in the offer's transaction (`schedule_deadline_jobs`), payload
`{"offer_id": <id>, "expires_at": "<ISO 8601>"}`:

| Kind | Key | Runs at |
| --- | --- | --- |
| `offer_response_reminder` | `offer_response_reminder:<offer id>:<expires_at>` | `expires_at - reminder_before_hours`, only when that is after `sent_at` and the reminder is not 0 |
| `offer_expiry` | `offer_expiry:<offer id>:<expires_at>` | `expires_at` |

Migration `finance/0030_l12a_offer_deadline_jobs` (choices only). Neither handler reads the switch:
a deadline, once set, is honoured.

### Reminder (`handle_response_reminder`)

Locks Match then Offer (the decline path's rows, in its order), then does nothing unless the offer
is still pending on a pending match, its deadline equals the payload's, and the deadline has not
passed (`offer_gone`, `deadline_changed`, `not_pending`, `deadline_passed`). Otherwise it publishes
**`offer.response_reminder`** to the person who did not write the offer (the traveler for a
sender's proposal, the sender for a traveler's counter):

```
{"match_id", "parcel_id", "journey_id", "offer_id", "tracking_number"}
```

Event id derived from the offer id, so a replay notifies nobody twice. Push class `marketplace`,
the same as `offer.created`; EN, FR, AR copy. In the bell inbox it resolves as soon as the offer no
longer waits on that person (`apps/notifications/resolution.py`).

### Expiry (`handle_offer_expiry`)

Same locks, same order. If the offer is still pending and the deadline has passed: offer
`status = expired`, `responded_at = now`; for a V1 offer the match becomes `cancelled`, exactly as a
decline leaves it; the request is not touched (it stays open, so the sender may propose to anyone,
the same traveler included). `MatchEvent.Kind.OFFER_EXPIRED` (actor null, payload `expires_at`).
Publishes the existing **`offer.updated`** with `status: "expired"` to both people (event id derived
from the offer). New push copy keyed `("offer.updated", "expired")` in EN, FR, AR, neutral wording
("Nothing was reserved or charged").

Expiry touches no reservation, deal, order, ledger, boost or rating row and writes no reliability
signal (test compares those tables row for row). A job claimed before the deadline (a worker clock
ahead) is deferred to the deadline.

### Refusal from the deadline on

`deadline_passed(offer, at)` is true when the offer is pending or expired and `expires_at <= at`.
Every write that answers or ends an offer checks it **inside its row locks**, whether or not the
expiry job has run, and refuses with **409 `offer_expired`** plus `expires_at`:

| Path | Where |
| --- | --- |
| Accept, counter | `v1_services` (`OfferExpired`), in the unlocked pre-check and again under the locks |
| Decline, withdraw | `apps/matching/views.py` |
| Cancel the match | `apps/matching/views.py`, when its pending offer has lapsed |

An offer that ended another way (superseded by a competing acceptance, journey cancelled) keeps
answering `offer_not_pending` before its deadline.

### Offer payload

Every offer payload (`OfferSerializer`, `OfferListSerializer`) already carried `expires_at` and
`awaiting_party` (`"sender"` or `"traveler"`) with `awaiting_user_id`; the plan's `awaiting` is
that existing field, not a second one. From the deadline on, even before the job runs, the payload
says `status: "expired"`, `allowed_actions: []`, `awaiting_party: null`, `awaiting_user_id: null`.
The match itself reads `pending` until the job runs (normally within a minute), then `cancelled`.

## 3. Trip-fit alerts (`apps/discovery/trip_fit.py`)

`notify_fitting_travelers(request, policy=, at=)` is called by `handle_route_alert_fanout` for a
request, after the existing gates (listings switch on, request still listable) and before the route
alerts. One job, two audiences.

1. With `trip_fit_alerts_enabled`, it calls `compatible_journeys_for_request(request, phase2_policy())`
   and keeps the eligible evaluations in the engine's ranking order. The engine's own queryset
   re-reads the journey gates at run time: discoverable, not paused, traveler active, not banned,
   current ID check, tickets approved.
2. One traveler, one alert: a traveler with two fitting trips is told about the better ranked one.
3. In one transaction it locks the candidate travelers' user rows (id order), skips travelers
   already told about this request and those at `trip_fit_daily_cap` in the last 24 hours, and tells
   at most `trip_fit_max_travelers` per request (counting those told by an earlier run).
4. For each, a `discovery.TripFitAlert` row (unique per request and journey; migration
   `discovery/0002_l12a_trip_fit_alert`) and **`discovery.request_fits_trip`** to the journey owner:

   ```
   {"request_id", "journey_id"}
   ```

   Event id derived from the request and the journey. Push class `marketplace` (honours
   `marketplace_enabled`); EN, FR, AR copy "A parcel fits your trip".
5. It returns every traveler told about this request, including by an earlier run, and the
   route-alert step excludes them, so a traveler gets one notification about one parcel.

Return value of the fan-out job is unchanged (`notified:<route alerts sent>`).

## 4. Channels

Added in the three places (rule 1.5.8): `apps/core/channels.py`, the push matrix in
`apps/notifications/push.py`, `subscribeChannels` in `backend/services/internal/notification/dispatcher.go`
(`TestSubscribeChannelsMatchDjango` passes).

| Channel | To | Payload |
| --- | --- | --- |
| `offer.response_reminder` | the person who must answer | match ids, `offer_id`, `tracking_number` |
| `discovery.request_fits_trip` | the journey owner | `request_id`, `journey_id` |
| `offer.updated` (existing) with `status: "expired"` | both people | match ids, `offer_id`, `status` |

## 5. Console

Settings › Marketplace features gains six fields: "Tell travelers when a new parcel fits their
trip", "Travelers told about one parcel, at most", "“A parcel fits your trip” alerts per traveler per
day", "Give proposals a response deadline", "Hours to answer a proposal", "Remind the person who must
answer, hours before the deadline". The section heading is now "Discovery, routes, prices and
proposals". A reminder not shorter than the delay is refused on the form with its reason.

Screenshots (`/mnt/project-files/l-series-screens/L12A/`): `settings-marketplace-en.png`,
`settings-marketplace-reminder-error-en.png`.

## 6. Tests

New: `apps/matching/tests/test_l12a_offer_deadlines.py` (34), `apps/discovery/tests/test_l12a_trip_fit.py`
(12). They cover: the policy defaults, bounds and the reminder rule; the deadline from policy on a
proposal and a counter; the pickup time used instead when it comes first, on both; no reminder when
the deadline is closer than the reminder delay, and none at 0; nothing with the switch off, and an
existing deadline kept after it is turned off; the reminder's notify case and each no-op case, run
twice, and its recipient on a counter; expiry against a decline (offer, event, match, request) with
the deal, event, allocation, order, ledger, boost and rating tables identical; both people told once;
the same traveler proposable again; `offer_expired` on accept, counter, decline, withdraw and cancel
with the job not yet run, and on accept, counter and decline after it ran; the locked re-check;
acceptance racing expiry on two real transactions (acceptance holding the locks wins and the expiry
finds nothing; both at the deadline leave one expired offer and no deal); the console form.
Trip-fit: only compatible journeys (not a wrong route, an unproven ticket, a paused trip or the
sender), the cap per request in the engine's order, one alert per traveler, the daily cap over 24
hours, the replay, the skip of route-alert recipients (also on a replay), the switch, listings off,
a closed request, the privacy walk on the notification, the push copy, and the query count at 1 and
at 20 journeys: choosing whom to tell is flat, and each traveler told costs exactly one inbox write.

One existing test rewritten to the new rule: `test_alerts.py::test_a_request_opening_notifies_request_watchers`
used the request's fitting traveler as the route-alert watcher; under spec 17.2 that traveler now
gets the trip-fit alert instead, so the watcher is a traveler without a fitting trip. Two existing
console tests (`test_marketplace_policy.py`) post the new form fields and expect the saved policy to
carry them.

Counts: Django 2,895 collected before, 2,941 after (+46), all passing locally in 4 shards.
`makemigrations --check` clean, ruff clean, `schema.sql` re-exported (additions only), Go
`go test -race ./...` passes.

## 7. Judgment calls (for Ismail's end review)

1. **Withdraw and cancel refuse after the deadline too**, not only accept, counter and decline:
   from the deadline on the proposal has expired, so expiry is its single ending and both people get
   the same "expired" message.
2. **One alert per traveler per request**: a traveler with two fitting trips is told once, about the
   better ranked trip, because the limit counts travelers.
3. **Trip-fit alerts need the listings switch on as well as their own**: the alert opens the
   request's public preview, which listings off removes.
4. **The payload reads `expired` from the deadline on**, before the job stores it, so the app never
   shows "Answer by" for a time that has passed.
5. **Push classes**: the reminder and the trip-fit alert are `marketplace`, like the proposal itself
   and the other discovery signals; the expiry keeps `offer.updated`'s class.
6. **The trip-fit push copy names no cities**: payloads carry ids only (no route on a lock screen);
   the app shows the route from the preview.
