# Phase I1A — Journey timing, early arrival and the payout floor

Backend contract for I1B. This document is authoritative for the Flutter work:
where it and an older screen disagree, this wins. Where it and
`docs/SHIPTRIP_V1_SPEC.md` disagree, the specification wins and this document is
the bug.

**The one rule that shapes everything below.** Three facts that look similar are
kept separate on purpose, and Flutter must never collapse them:

| Fact | Who establishes it | What it starts |
|---|---|---|
| The **traveler arrived** | traveler reports, sender confirms | nothing financial |
| The **parcel was delivered** | a verified delivery code | the 48-hour protection window |
| The **payout may be released** | the server's release gate | settlement |

A confirmed early arrival does not deliver a parcel, does not release a delivery
code, does not start protection and does not pay anybody.

---

## 1. The funded arrival snapshot

At funding, inside the funding transaction, the Deal freezes the arrival basis it
was funded against. Written once by
`apps.deals.lifecycle.snapshot_on_funding` → `apps.deals.arrival.build_funding_snapshot`,
and never rewritten.

Two Deal columns hold it:

| Column | Meaning |
|---|---|
| `funded_scheduled_arrival_floor_at` | the frozen scheduled-arrival instant — **the payout floor** |
| `arrival_snapshot` | its provenance, plus the frozen carrying route |

`arrival_snapshot` keys:

```json
{
  "policy_version": "i1a.v1",
  "provenance": "funding",
  "snapshot_at": "2026-09-11T21:14:02.881Z",
  "stored_timezone": "UTC",
  "material_early_threshold_seconds": 21600,
  "journey_id": 41,
  "journey_schema_version": 2,
  "match_id": 88,
  "matching_version": "v1.2",
  "basis": "match_delivery_interpolation",
  "scheduled_arrival_at": "2026-09-20T18:00:00Z",
  "arrival_leg_id": 133,
  "arrival_leg_position": 1,
  "route": [
    {
      "leg_id": 132, "position": 0, "mode": "DRIVE",
      "origin_place_id": 9001, "destination_place_id": 9002,
      "origin_location_id": null, "destination_location_id": null,
      "depart_at": "2026-09-20T06:00:00Z", "arrive_at": "2026-09-20T09:30:00Z"
    }
  ]
}
```

### Provenance

`provenance` has exactly two values, and Flutter never needs to branch on it —
it exists so a dispute or an audit can say where an instant came from.

* `funding` — frozen at funding from live, locked rows. Every Deal funded from
  I1A onward.
* `legacy_match_snapshot_v1` — recovered by the I1A migration from the accepted
  `Match.compatibility_snapshot`, for Deals funded before I1A. Its `route` is
  deliberately empty (see §7).

### 2. Which Journey fact establishes the floor

Resolved once, most specific first:

1. **`match.compatibility_snapshot["delivery_at"]`** → `basis = "match_delivery_interpolation"`.
   The server's own interpolated arrival at *this sender's* delivery anchor,
   computed by `apps.matching.compatibility` when the match was made and never
   recomputed. This is the instant the compatibility decision was actually taken
   against, which makes it the honest answer to "what arrival did these two
   parties agree to?".
2. **The latest `arrive_at` among the legs this Deal's capacity is allocated on**
   → `basis = "allocated_leg_arrival"`. The parcel's last carrying leg.
3. **The matched `end_leg.arrive_at`** → `basis = "matched_end_leg_arrival"`.
4. Nothing usable → `basis = "unavailable"`, floor is `null`.

**The funded schedule is a single instant in V1**, because `JourneyLeg.arrive_at`
is a single instant. If a later phase introduces an arrival *window*, the floor
takes the window's **end**. The floor exists to resist early-arrival abuse, so it
must never be reducible by widening a schedule.

A null floor is not a fabricated one. `payout_release_gate_at` then reduces to
the pre-I1A rule exactly, which is the behaviour such a Deal already had.

### 3. Immutability after funding

`apps.trips.services.journey_editability` already refuses to edit a Journey that
carries a Deal or a pending/accepted Match, so a schedule edit under a funded
Deal is refused with `journey_not_editable` or `journey_has_dependent_state`.

The snapshot is the second wall. Nothing in the arrival or payout path reads a
`Journey` or `JourneyLeg` row after funding, so even a direct row change — an
operator, a data fix, a future feature — leaves the funded Deal's floor, route
and payout timing exactly where they were. That is asserted by
`test_a_journey_schedule_edit_after_funding_cannot_move_the_floor`.

---

## 4. The payout floor formula

```
payout_eligible_from = max(
    delivery_confirmed_at + protection_window_seconds,   # = Deal.protection_ends_at
    funded_scheduled_arrival_floor_at                    # null ⇒ ignored
)
```

Implemented as `apps.deals.arrival.payout_release_gate_at`, which reads the two
**stored columns** and recomputes neither. Returns `null` before a delivery is
confirmed: there is no gate instant yet, only an unstarted protection window.

`apps.deals.arrival.payout_release_gate_basis` names the binding constraint, and
the release writes it to `Payout.eligibility_basis`:

* `delivery_protection` — the 48-hour window was the later of the two.
* `schedule_floor` — the funded arrival was the later of the two.

### Worked cases

| Case | Scheduled arrival | Actual delivery | Actual + 48h | Floor | `payout_eligible_from` | Basis |
|---|---|---|---|---|---|---|
| Normal / on time | 10 Sep 18:00 | 10 Sep 18:15 | 12 Sep 18:15 | 10 Sep 18:00 | **12 Sep 18:15** | `delivery_protection` |
| Early | 10 Sep 18:00 | 9 Sep 12:00 | 11 Sep 12:00 | 10 Sep 18:00 | **11 Sep 12:00** | `delivery_protection` |
| Very early | 15 Sep 18:00 | 10 Sep 12:00 | 12 Sep 12:00 | 15 Sep 18:00 | **15 Sep 18:00** | `schedule_floor` |
| Late | 10 Sep 18:00 | 12 Sep 10:00 | 14 Sep 10:00 | 10 Sep 18:00 | **14 Sep 10:00** | `delivery_protection` |

All four are asserted in `PayoutFloorTests`.

### What the floor does *not* do

* It does not shorten protection. A late delivery still gets the full 48 hours
  measured from the actual delivery.
* It does not move. A Journey edit cannot reduce it, a confirmed early arrival
  cannot remove it, and a re-run release job cannot move it backward.
* It does not replace any existing blocker. Disputes, Finance holds, provider
  disputes, refund state and payout-setup requirements all still apply; the floor
  is one more condition, never a substitute for one.
* It never creates a payout `block_reason`. A Deal waiting on its arrival floor
  is not the traveler's problem to fix, so it is not reported as one.

### Operational note for anyone shifting a Deal's clock

`funded_scheduled_arrival_floor_at` is now one of the Deal's stored deadlines, so
any deliberate time-shift of a Deal — an H7-style rehearsal control, a test
fixture, a support fix — must move it with the other six lifecycle timestamps.
Left behind, the Deal describes a parcel delivered days before its journey was due
to arrive, and the arrival floor correctly refuses to release the payout.
`apps.deals.tests.phase4_factories.rewind_deal` already includes it.

---

## 5. "Materially early" — one threshold, server-side

`MATERIAL_EARLY_ARRIVAL_THRESHOLD_SECONDS = 21_600` (**6 hours**), defined once
in `apps.deals.arrival`.

Chosen because it has to clear ordinary en-route jitter (a flight landing forty
minutes early is not news), it has to clear the handover machinery that already
exists (a thirty-minute delivery-code buffer plus travel to a meeting point), and
it has to still catch the case the sender genuinely needs to hear about — "I am
here a day early", where a recipient has to be found.

The threshold is **snapshotted onto each Deal at funding**, so changing the
constant later cannot reinterpret a Deal that is already running. Read it from
`arrival.material_early_threshold_seconds` in the projection.

> **Flutter must not use this number to decide anything.** It is exposed so the
> UI can say "six hours" in copy. Whether *this* arrival is early is
> `arrival.is_materially_early_now`, and whether the action exists is
> `arrival.report_available`.

---

## 6. Arrival states, request and confirmation flow

```
not_reported
     │  traveler: report_early_arrival
     ▼
pending_confirmation
     │                        │
     │ sender: confirm        │ sender: decline
     ▼                        ▼
confirmed                 declined ──► traveler may report again
```

`DealArrivalReport` is the audit row: who claimed, when, against which basis, by
how much, what the sender answered, and when.

### Preconditions for `report_early_arrival`

All checked server-side, under the lifecycle row lock:

* the caller is the Deal's **traveler**;
* the Deal is **in carriage** (`picked_up`, `in_transit`, `delivery_ready`);
* `delivery_confirmed_at` is null;
* the Deal is not closed and has no active dispute;
* the Deal has a funded arrival basis;
* `funded_scheduled_arrival_floor_at − now ≥ threshold`;
* no claim is already pending, and none has already been confirmed.

### Preconditions for `confirm_early_arrival` / `decline_early_arrival`

* the caller is the Deal's **sender**;
* a claim is pending;
* the Deal is not closed and the delivery is not yet confirmed.

**The server never self-confirms.** A report sits at `pending_confirmation` until
the sender answers it. An answer cannot be reversed: a confirm after a decline
(or the reverse) is refused with `no_open_arrival_report`.

If the parcel is delivered while a claim is outstanding, the claim stays on the
record as what it was — unanswered — and the sender's actions are withdrawn.

---

## 7. What the sender sees of the route

`deal.route` on the detail projection. Visible to **both parties** after funding,
`null` before it and `null` to anybody who is not a party.

```json
{
  "basis": "funded_snapshot",
  "journey_id": 41,
  "legs": [
    {
      "leg_id": 132, "position": 0, "mode": "DRIVE",
      "origin":      {"kind": "place", "id": 9001, "name": "Jijel",
                      "display_label": "Jijel · Algeria", "place_type": "locality",
                      "iata_code": null, "country_code": "DZ", "parent_name": "Algeria"},
      "destination": {"kind": "place", "id": 9002, "name": "Algiers", "…": "…"},
      "depart_at": "2026-09-20T06:00:00Z",
      "arrive_at": "2026-09-20T09:30:00Z",
      "carries_parcel": true
    }
  ]
}
```

* **Ordered** by `position`, ascending.
* **Only this Deal's carrying legs** — the legs its capacity is allocated on. The
  traveler's other segments and other bookings are not in it.
* `basis` is `funded_snapshot` for a Deal funded from I1A onward, and
  `live_journey` for a pre-I1A Deal whose funded route could not be recovered.
  Render the same either way; the field exists so the app never presents a live
  read as a frozen record.
* Endpoint `kind` is `place` for canonical catalogue places and
  `coarse_location` for legacy version-1 journeys, which are projected at their
  **public/coarse** label only.

### Route privacy — what is deliberately absent

No `route_polyline`, `route_metadata`, `departure_airport_metadata`,
`arrival_airport_metadata`, `distance_meters`, `route_duration_seconds`,
`allowed_detour_meters`, `capacity_kg`, `flight_number`, leg proofs, exact
coordinates or private labels. Do not ask for any of them in I1B: the route
projection is not a relaxation of `apps.trips.serializers`, which withholds
exactly that set from a non-owner.

**Route rules are unchanged by I1A.** Algeria ↔ non-Algeria is FLIGHT, Algeria
domestic is DRIVE, continental-Europe cross-border DRIVE is allowed, no ferry,
canonical `Place` matching, no radius/detour semantics.

### Why the arrival instant is safe to show, and only after funding

`apps.matching.public_contract` withholds `delivery_at` from a counterparty
because it is interpolated from a route position, so a second-resolution
timestamp is itself a metre-resolution position. That rule governs **pre-funding**
disclosure and is unchanged: nothing in I1A exposes an arrival instant, a route or
a schedule before `funded_at` exists.

After funding, the specification already unlocks exact pickup and dropoff to the
two parties (`SHIPTRIP_V1_SPEC.md` §5, *Privacy*). The sender's own delivery point
and the traveler's own route are then both known to the people being shown this,
so `funded_scheduled_arrival_at` is not a new disclosure — it is the arrival these
two parties bought and sold. It stays out of every pre-funding surface, out of
every notification payload, and out of any projection a non-party can read.

---

## 8. Active Sending semantics

`activity_state` is on **both** the list row and the detail payload, and the list
endpoint filters on the same rule.

| Value | Deal states |
|---|---|
| `active` | `offer_accepted`, `payment_required`, `payment_failed`, `funded`, `pickup_ready`, `picked_up`, `in_transit`, `delivery_ready` — and `disputed` before a confirmed delivery |
| `completed` | `delivery_confirmed`, `protection_window`, `completed`, and **any** Deal with a non-null `delivery_confirmed_at` — including `disputed` after delivery |
| `cancelled` | `cancelled`, `expired`, `refunded`, `partially_refunded` |

Two decisions worth stating:

* **`delivery_confirmed_at`, not the status column, decides active vs completed.**
  `disputed` overwrites the status and a dispute can be opened either side of a
  delivery, so the timestamp is the unambiguous fact.
* **A refund outranks the delivery fact.** If the sender has been refunded, the
  platform did not deliver this parcel for them, whatever the handover log says.

`GET /api/deals?activity=active|completed|cancelled`. An unknown value is a 400.
`?status=` is unchanged and still available.

> **The delivered-Deal-stuck-in-Sending bug is fixed by using `activity_state`.**
> Do not re-derive it in Dart from `status`; that is the bug. Payout progress for
> a completed shipment belongs in the delivery/payout experience — it is fully
> readable there (`payout_summary`, `protection.payout_floor`) and nothing is
> hidden by moving the shipment off the active list.

---

## 9. API

### `POST /api/deals/<id>/arrival/report` — traveler

### `POST /api/deals/<id>/arrival/confirm` — sender

### `POST /api/deals/<id>/arrival/decline` — sender

No request body. Response, 200:

```json
{
  "deal": { "…the full detail projection…" },
  "arrival_report_id": 17,
  "arrival_report_status": "pending_confirmation",
  "changed": true
}
```

`changed: false` means this call was a duplicate and nothing moved — a retried
report, or a repeated confirmation. **Treat it as success.** A dropped response
must not look like a failure to the person who tapped the button.

Refusals:

| Status | When |
|---|---|
| 403 | wrong party (`not_traveler`, `not_sender`) |
| 404 | not a party to this Deal, or an unknown action segment |
| 409 | every state refusal (`not_materially_early`, `arrival_requires_carriage`, `delivery_already_confirmed`, `arrival_report_pending`, `arrival_already_confirmed`, `no_open_arrival_report`, `dispute_active`, `deal_closed`, `arrival_basis_missing`) |

409 bodies carry `{"code": …, "detail": …}` and, for `not_materially_early`, also
`early_by_seconds` and `threshold_seconds`.

### `GET /api/deals/<id>` — the journey-timing blocks

```json
{
  "activity_state": "active",
  "funded_scheduled_arrival_floor_at": "2026-09-20T18:00:00Z",
  "arrival_confirmed_at": null,
  "delivery_confirmed_at": null,

  "arrival": {
    "state": "pending_confirmation",
    "basis": "match_delivery_interpolation",
    "funded_scheduled_arrival_at": "2026-09-20T18:00:00Z",
    "material_early_threshold_seconds": 21600,
    "is_materially_early_now": true,
    "seconds_until_scheduled_arrival": 334800,
    "server_time": "2026-09-16T21:00:00Z",
    "reported_at": "2026-09-16T20:58:11Z",
    "reported_early_by_seconds": 334909,
    "decided_at": null,
    "arrival_confirmed_at": null,
    "confirmed_arrival_is_not_delivery": true,
    "delivery_confirmed_at": null,
    "report_available": false,
    "report_unavailable_reason": "arrival_report_pending",
    "decision_available": true,
    "decision_unavailable_reason": null,
    "available_actions": ["confirm_early_arrival", "decline_early_arrival"]
  },

  "protection": {
    "protection_ends_at": null,
    "delivery_confirmed_at": null,
    "payout_floor": {
      "protection_ends_at": null,
      "funded_scheduled_arrival_floor_at": "2026-09-20T18:00:00Z",
      "payout_eligible_from": null,
      "basis": null,
      "gate_open": false,
      "server_time": "2026-09-16T21:00:00Z"
    },
    "payout": { "…unchanged…" }
  },

  "route": { "…§7…" }
}
```

`arrival` is **viewer-dependent**: `available_actions` and the `*_available`
flags are computed for the authenticated caller. The same Deal read by its sender
and by its traveler is deliberately not the same document.

### H6A payout projection — additive

`payout_summary` (traveler only) gains three keys and one new reason:

| Key | Meaning |
|---|---|
| `funded_scheduled_arrival_floor_at` | the frozen floor, or `null` |
| `earliest_release_at` | `payout_eligible_from` — the authoritative gate instant |
| `blocking_reason: "scheduled_arrival_pending"` | protection has closed, the arrival floor has not |

`display_state` stays `release_pending` in that case. Every other H6A state,
reason and field is unchanged.

---

## 10. Available actions

Server-derived, in `arrival.available_actions`:

| Actor | Action |
|---|---|
| traveler | `report_early_arrival` |
| sender | `confirm_early_arrival`, `decline_early_arrival` |

An empty list means no arrival action is available to this viewer right now.
`report_unavailable_reason` / `decision_unavailable_reason` say why, as machine
codes for the app to localise.

---

## 11. Authorization

| Action | Who | Everyone else |
|---|---|---|
| report an arrival | the Deal's matched traveler | 403 `not_traveler` |
| confirm / decline | the Deal's sender | 403 `not_sender` |
| read the Deal, its arrival block and its route | either party (and staff) | 404 |

A non-party never learns a Deal exists: the queryset is scoped to the two parties
before anything else happens, so both the detail read and the action return 404.

The recipient has no authenticated surface here and gains none. Their path is
unchanged: they receive the delivery code by email at the end of the 30-minute
buffer and hand it to the traveler in person.

---

## 12. Delivery-code security — unchanged

I1A changes **nothing** about who may hold a delivery code.

* `handover.traveler_can_view_delivery_code` is still stated and still `false`.
* The 30-minute post-pickup buffer still applies, measured from the Deal's own
  frozen `delivery_code_available_at`.
* A confirmed early arrival reveals nothing. It does not release the code, does
  not shorten the buffer, and does not change who may reveal it.
* No arrival event payload carries code material; `apps.deals.timeline`'s
  allowlist is the wall and the new payload keys sit inside it.

---

## 13. Notification events

In-app inbox plus FCM. Payloads carry resource identities only —
`deal_id`, `match_id`, `parcel_id`, `journey_id` — so no schedule, place, route
or provider detail can reach a lock screen. No new email template is introduced.

| Channel | To | Push copy (en) |
|---|---|---|
| `deal.arrival_reported` | sender | "Traveler arrived early" / "Open ShipTrip to confirm the early arrival." |
| `deal.arrival_confirmed` | traveler | "Early arrival confirmed" / "The sender confirmed your arrival. Delivery is still to come." |
| `deal.arrival_declined` | traveler | "Early arrival not confirmed" / "Open ShipTrip to review the delivery." |

All three are `essential` category on the `deliveries` Android channel, localised
in en/fr/ar. Each is published with a deterministic `idempotency_key` bound to the
report id, so a duplicated action produces **one** inbox row and one push — the
existing `Notification` uniqueness does the deduplication.

Delivery, protection and payout notifications are unchanged.

---

## 14. Timeline events

New `DealEvent` kinds, visible to both parties:

| Kind | When |
|---|---|
| `arrival_snapshot_frozen` | at funding, naming the basis and the instant |
| `early_arrival_reported` | the traveler's claim |
| `early_arrival_confirmed` | the sender's confirmation |
| `early_arrival_declined` | the sender's decline |

`early_arrival_confirmed` carries `starts_protection_window: false` and
`releases_delivery_code: false`, restated on the record both parties read.

---

## 15. What Flutter must NOT calculate

* **Whether an arrival is early.** Use `arrival.is_materially_early_now` and
  `arrival.report_available`. Never compare the device clock to a schedule.
* **The materiality threshold.** It is a Deal-frozen number for copy only.
* **When a payout becomes eligible.** Use `protection.payout_floor.payout_eligible_from`
  and `payout_summary.earliest_release_at`. Never take the later of two instants
  yourself.
* **Whether a Deal is an active shipment.** Use `activity_state`, or ask the list
  endpoint for a bucket. Never re-derive it from `status`.
* **Which actions exist.** Use `arrival.available_actions`.
* **Whether an arrival implies a delivery.** It never does.
* **Any countdown's own deadline.** Every instant is server-issued; render from
  it, and use `server_time` to correct for device clock skew rather than trusting
  the device clock.

---

## 16. What remains for I1B

Frontend only. The backend contract above is frozen.

1. **Traveler:** an "I arrived early" affordance gated on
   `arrival.report_available`, with the refusal reason rendered when it is
   unavailable rather than the button silently vanishing. Pending state after
   the report, and a clear statement that delivery is still to come.
2. **Sender:** confirm / decline the reported arrival, with the reported instant
   and how early it was. Confirmation must not read as "delivered".
3. **Sender:** the ordered funded route — stops, modes (FLIGHT/DRIVE) and
   scheduled times — from `deal.route`.
4. **Both:** the payout/protection picture including the arrival floor, using
   `protection.payout_floor` and the H6A `scheduled_arrival_pending` reason.
5. **Deliveries experience:** switch active/completed/history grouping to
   `activity_state` (or the `?activity=` filter) so a delivered Deal leaves
   active Sending, and surface payout progress in the delivery/payout view
   instead.
6. **States:** loading, empty, error, offline, Arabic RTL, localisation
   (fr/ar/en) and bottom-navigation overlap for every new surface, per the
   permanent UI rules.
7. **Push routing:** deep-link the three `deal.arrival_*` channels to the Deal.

Not in I1B: any change to the delivery-code model, the protection window, the
matching rules, or H8 production enablement.
