# L2A: Discovery backend and marketplace policy (contract)

Package L2A of `docs/WASSLA_DISCOVERY_PRO_PLAN.md`; the product rules are `docs/WASSLA_DISCOVERY_PRO_SPEC.md`
sections 2.1 and 4. This is the contract the L2B mobile work builds against.

## 1. What exists after L2A

- **Marketplace policy** (`apps/core/marketplace_policy.py`): the `marketplace` section of the active
  `BusinessSettingsVersion.policy`, read as frozen dataclasses. Missing section or key means the default.
  An unknown key, a wrong type (booleans and integers are checked strictly) or a value out of bounds is
  refused when the revision is saved (`AdminSettingsCreateSerializer`, code
  `marketplace_policy_unavailable`), so an active revision can never hold a bad section.
- **Admin switches**: Settings page section "Marketplace features" (`id="st-settings-marketplace"`):
  `listings_enabled`, `profiles_enabled`, `interest_daily_cap`, with reason and confirmation. Saving
  creates and activates a new audited revision (`settings.version_created`), like every other setting.
  Needs `manage_settings`.
- **App `apps.discovery`**: models `PublicProfile`, `PublicProfileRoute`, `RouteAlert`,
  `TravelerInterest` (migration `discovery/0001_initial`), and the endpoints below.
- **Removed**: `GET /api/journeys/search` and `GET /api/parcels/open`, their views, serializer, query
  helper and tests. The refusal `airport_filter_retired` is no longer sent by any server code.

### Marketplace policy keys and defaults

| Key | Default | Bounds |
| --- | --- | --- |
| `sea_legs_enabled` | false | bool |
| `discovery.listings_enabled` | true | bool |
| `discovery.profiles_enabled` | true | bool |
| `discovery.interest_daily_cap` | 10 | 1 to 100 |
| `courier_handoff.enabled` | false | bool |
| `courier_handoff.unconfirmed_review_days` | 5 | 1 to 30 |
| `courier_handoff.link_valid_days` | 30 | 1 to 90 |
| `professional.applications_enabled` | true | bool |
| `traveler_pricing.enabled` | true | bool |
| `traveler_pricing.max_price_per_kg_eur_cents` | 10000 | 100 to 100000 |
| `traveler_pricing.max_min_price_eur_cents` | 50000 | 100 to 1000000 |
| `reminders.enabled` | true | bool |
| `reminders.depart_after_minutes` | 30 | 5 to 1440 |
| `reminders.arrive_after_minutes` | 60 | 5 to 1440 |
| `reminders.repeat_after_minutes` | 180 | 15 to 1440 |
| `reminders.max_repeats` | 2 | 0 to 5 |
| `route_change.material_shift_minutes` | 360 | 30 to 10080 |

Only the three `discovery` keys are read in L2A. The rest are read by the packages that own them.

## 2. Common rules for every endpoint

- Authenticated (`IsAuthenticated`), throttled with the existing `user` rate and the existing
  `matching_discovery` scope. No new throttle setting.
- Every switch is read from the active policy on each request; nothing is cached.
- A tier that is switched off answers **HTTP 200** with `{"state": "disabled", "results": [], "next_offset": null}`
  (the person page answers `{"state": "disabled"}`).
- A list answers `{"state": "results" | "empty", "results": [...], "next_offset": int | null}`.
  `limit` 1 to 50 (default 20), `offset` 0 to 1000. `next_offset` is null on the last page.
- **Places**: any active catalogue place id is accepted, including an airport, and is resolved to its
  matching locality (`Place.resolve_matching_locality`, the identity matching uses). A filter on a city
  also matches the airports mapped to it as their primary SERVED city. An unknown or inactive id answers
  `400 {"code": "place_not_found"}`. A different locality with the same name is a different city.
- **Countries**: `origin_country` and `destination_country` are ISO codes (`^[A-Z]{2}$`).
- Policy unavailable (no active settings, or a bad Phase 2 policy): `503` with the policy's error code.
- Every card is built key by key from an allowlist. No email, phone, surname, address, coordinates,
  location row, recipient, KYC data, user id, flight number, description or declared value appears in
  any discovery payload (enforced by `apps/discovery/tests/test_privacy.py`).

## 3. Endpoints

### `GET /api/discovery/matches?role=sender|traveler`

Fan-in over the existing engines. It does not evaluate compatibility itself.

- `sender`: the caller's open schema-3 delivery requests (not past their deadline), newest first, at
  most 3. Each group is
  `{"request": {"id", "pickup", "delivery", "deadline_at"}, "results": [...], "more_available": bool}`.
  `results` is exactly the `results` of `GET /api/matches/find-travelers?parcel_id=<id>&limit=3` (the J4
  page builder `find_travelers`).
- `traveler`: the caller's discoverable journeys with a leg still ahead, soonest next departure first,
  at most 3. Each group is
  `{"journey": {"id", "origin", "destination", "next_departure_at"}, "results": [...], "more_available": bool}`.
  `results` is the first 3 rows of `GET /api/matches/compatible-requests?journey_id=<id>` in its public
  shape (no recommendation).
- Envelope: `{"state": "results" | "none" | "no_active_items", "groups": [...]}`. `none` means items
  exist but none has a result.
- `pickup`, `delivery`, `origin`, `destination` and every other place block in this contract are
  `{"place_id", "label", "country_code"}`.

### `GET /api/discovery/trips`

Query: `origin_country`, `destination_country`, `origin_place_id`, `destination_place_id`,
`departing_after`, `limit`, `offset`.

A journey is listed when all of these hold: it is discoverable (`trips.lifecycle.discoverable`), schema
version 2 or later; the traveler is active, not banned, with a current approved KYC; no FLIGHT leg lacks
an approved ticket proof; no leg still ahead is full; it has a leg still ahead; it is not the caller's.
Order: soonest next departure, then id.

Route filters follow direction: the pickup is the origin of a leg that has not departed (after
`departing_after` when given), and the drop-off is the destination of that leg or a later one. Without
an origin filter, `departing_after` applies to the next departure.

Trip card:

```json
{
  "journey_id": 12,
  "traveler": {"display_name": "Yacine", "identity_verified": true, "rating": 4.8, "completed_deliveries": 3},
  "stops": [{"place_id": 1, "label": "Paris", "country_code": "FR"}, ...],
  "legs": [{"mode": "FLIGHT", "depart_at": "...", "arrive_at": "..."}, ...],
  "departs_at": "...",
  "next_departure_at": "...",
  "arrives_at": "...",
  "capacity_band": "under_5kg" | "5_to_10kg" | "10_to_20kg" | "20kg_plus"
}
```

`display_name` is the first name only. `rating` and `completed_deliveries` are the traveler-side trust
summary J4 uses. `capacity_band` is the band of the smallest free weight across the legs still ahead.
The pro badge and business name (L6A) and the listed price (L4A) are added by those packages.

### `GET /api/discovery/requests`

Same query. A request is listed when it is a schema-3 delivery request, `open`, not targeted at a
traveler, its deadline and ready window have not passed, it has a weight, it has no active deal, its
sender is active and not banned, and it is not the caller's. Order: newest first, then id.
`departing_after` keeps requests whose ready window ends on or after it.

Request card: `request_id`, `sender {"display_name"}`, `pickup`, `delivery`, `title`, `category`,
`fragile`, `weight_kg` (string), `ready_window_start`, `ready_window_end`, `deadline_at`,
`currency` (`"EUR"`), `traveler_reward_eur_cents`, `boost_eur_cents`, `total_offered_reward_eur_cents`.

### `POST /api/discovery/requests/<id>/interest` ("I can carry this")

Body `{"journey_id": int}`. The request must be listed and not the caller's (`404 request_not_found`);
the journey must be the caller's (`404 journey_not_found`). The server runs the matching engine's
`explain_candidate`; an incompatible pair answers
`409 {"code": "incompatible_candidate", "rejection_codes": [...]}`. A compatible pair creates one
`TravelerInterest` (unique per request and journey) and notifies the sender once on
`discovery.traveler_interested` with `{"request_id", "journey_id"}` only.

Answer: `201` when created, `200` when the same signal already exists (nothing is sent again):
`{"request_id", "journey_id", "sent_at", "created"}`. It never creates a match, an offer or a reservation.

Daily cap: `interest_daily_cap` new signals per traveler over the last 24 hours (rolling, so it does not
depend on the traveler's time zone): `429 interest_daily_cap_reached`. Listings off:
`409 discovery_listings_disabled`.

### `GET /api/discovery/people?role=sender|traveler`

`role` is the **viewer's** role: a sender sees travelers, a traveler sees senders. Optional
`origin_place_id`, `destination_place_id`, `limit`, `offset`.

Listed: profiles the member turned on, not hidden by staff, of active and not banned members, never the
caller. A traveler is a member with a journey published in the last 365 days or a usual route; a sender
likewise with a request created in the last 365 days (not awaiting deposit). With a route, a person is
on it through a usual route or through those recent items. Order: most recent activity or consent first.

Profile card:

```json
{
  "id": "<opaque uuid>",
  "display_name": "Samira",
  "identity_verified": true,
  "member_since": "2026-11",
  "rating": null,
  "completed_deliveries": 0,
  "usual_routes": [{"origin": {...}, "destination": {...}}]
}
```

The trust summary on a profile card covers both sides of the member's deliveries.

### `GET /api/discovery/people/<uuid>`

`{"state": "results", "profile": <card>, "trips": [<trip card>, ≤10], "requests": [<request card>, ≤10]}`.
Items follow the listing rules and are empty while listings are off. A profile that is unknown or not
visible answers `404 profile_not_found`.

### `GET /api/discovery/profile/me` and `PUT /api/discovery/profile/me`

Answer (both):
`{"state": "visible" | "not_visible" | "hidden" | "disabled", "is_discoverable", "show_prompt", "consent_version", "usual_routes", "card"}`.
`card` is exactly what others see (the person page returns the same object). `hidden` tells the member
only that the profile is not currently visible; the staff reason is never sent. Reading never creates a
row; a member who never opened discovery gets the off-by-default answer with `card.id: null`.

`PUT` body (at least one field): `is_discoverable` (bool), `usual_routes` (list of at most 3
`{"origin_place_id", "destination_place_id"}`, replaces the list, order kept), `prompt_dismissed` (bool).
Turning the profile on records `consent_version` (`l2a-2026-11`) and `consented_at` and dismisses the
prompt. Turning it off and dismissing the prompt always work; turning it on while profiles are off
answers `409 discovery_profiles_disabled`. Route errors: `usual_route_same_city`,
`usual_route_duplicate`, `place_not_found` (400); more than three is a `400` validation error.

`show_prompt` is true while profiles are on, the member has not turned it on, is not hidden and has not
dismissed it (spec 4.3).

### `GET`, `POST /api/discovery/alerts` and `DELETE /api/discovery/alerts/<id>`

`POST` body: `watches` (`trips` | `requests`), `origin_place_id`, `destination_place_id`, optional
`subject_profile_id` (a profile uuid, to follow one person). Answer `201` with the alert, or `200` with
the identical active alert. Alert:
`{"id", "watches", "origin", "destination", "subject": {"id", "display_name"} | null, "created_at"}`.

Refusals: `route_alert_same_city` (400), `route_alert_self` (400), `place_not_found` (400),
`profile_not_found` (404, the person is not visible), `discovery_profiles_disabled` (409, following
while profiles are off), `discovery_listings_disabled` (409), `route_alert_limit_reached` (409, 10
active alerts). `GET` lists the caller's active alerts, newest first. `DELETE` answers `204`, or
`404 route_alert_not_found` for an alert that is not the caller's or is already deleted.

## 4. Route alert fan-out

Publishing a journey (`trips.services.publish_journey`), a request created straight into `open`, and a
deposit opening a request (`finance.services._publish_request_after_deposit`) each record one
`ScheduledJob` of kind `discovery_route_alerts` in the same transaction (key
`discovery_route_alerts:journey:<id>` or `...:request:<id>`). The worker's handler re-reads everything:
it does nothing when listings are off or the item is no longer listed. A journey matches an alert on any
pair of its stops still ahead, in travel order; a request on its pickup and delivery cities. An alert
following a person fires only while that person's profile is visible and profiles are on. The owner of
the item and banned or inactive members are never notified.

At most one notification per alert per 6 hours: a single guarded `UPDATE` of `last_notified_at` claims
the alert. The notification is `discovery.route_alert` with `{"alert_id", "journey_id" | "request_id"}`,
idempotency key `route_alert:<alert>:<kind>:<id>`, so a replayed job notifies nobody twice.

## 5. Notifications

| Channel | Payload | Target | Push |
| --- | --- | --- | --- |
| `discovery.route_alert` | `alert_id`, `journey_id` or `request_id` | the alert's owner | marketplace category (honours `marketplace_enabled`), Android channel `deliveries`, EN/FR/AR |
| `discovery.traveler_interested` | `request_id`, `journey_id` | the request's sender | same |

Both are in the Go dispatcher's `subscribeChannels` and in the bell inbox.

## 6. Admin

- Person page, new tab **Discovery** (`view_users`): profile state, consent, usual routes, staff hide
  record; two read-only lists, route alerts and "I can carry this" signals (sent and received).
- **Hide profile** / **Show profile again** (`manage_users`, reason required):
  `POST /admin/users/<id>/public-profile/`. Audited as `discovery.profile_hidden` and
  `discovery.profile_unhidden`. Hiding never changes the member's own switch.

## 7. Error codes added

`place_not_found`, `request_not_found`, `journey_not_found`, `incompatible_candidate`,
`interest_daily_cap_reached`, `discovery_listings_disabled`, `discovery_profiles_disabled`,
`profile_not_found`, `usual_route_same_city`, `usual_route_duplicate`, `route_alert_same_city`,
`route_alert_self`, `route_alert_limit_reached`, `route_alert_not_found`, `profile_visibility_unchanged`,
`reason_required` (admin), `marketplace_policy_unavailable`.

## 8. Performance

Query counts are flat in the number of rows (asserted at 1 and 20 rows, and pinned) in
`apps/discovery/tests/test_query_counts.py`: trips 7, requests 4, people 6, person page 10, Matches 11
per group whatever the number of candidates. Own profile and alerts are flat in their routes and alerts.
Matches has at most 3 groups by design.

## 9. Tests

`apps/discovery/tests/`: `test_marketplace_policy.py`, `test_listings.py`, `test_matches.py`,
`test_profiles.py`, `test_alerts.py`, `test_interest.py`, `test_admin.py`, `test_privacy.py`,
`test_query_counts.py`. Existing tests extended: the parcel create path and the deposit publication
path assert the fan-out job; the J13 lifecycle and posting-deposit tests use `/api/discovery/requests`.

Counts: Django 2,438 passed before, 2,539 passed after (13 removed, 114 added), 0 skipped.
