# Trips and Matching

Covers: How travelers publish journeys (legs, tickets, pausing, schedule changes), the route catalogue, and how Find Travelers, matching, Home discovery and alerts decide what is shown.
Related files: deliveries.md, pricing.md, money.md, accounts-and-verification.md, problems-and-disputes.md, messages-and-notices.md, admin-console.md, settings-and-helper.md

A "journey" is a traveler's trip, made of one or more "legs" (one flight, drive or ferry crossing each). The old single-flight "Trip" record is no longer used by the app.

## What is a journey and what are its statuses?
Journey statuses (field `status`):
| Status | Meaning |
|---|---|
| `draft` | Saved, private. Route can be edited. |
| `pending_verification` | A status that exists, but current code never moves a journey into it: publishing needs approved ID and tickets and goes from `draft` straight to `active`. Treat it like `draft` if you ever see it. |
| `active` | Published. Findable and can receive offers. |
| `in_progress` | A funded parcel has been picked up; travel has begun. |
| `completed` | A pickup was confirmed on it and every leg's planned arrival time has passed. |
| `cancelled` | Cancelled by the traveler. |
| `expired` | Computed by the server: no leg is left in the future and no funded deal depends on it. |
- Expiry, in-progress and completed are worked out when read (not by a background timer), from the clock and confirmed pickups, not from the traveler's progress reports. An `active` journey with no future departure left and no funded parcel shows as `expired`. A later leg stays sellable even after the first leg has left.
- A traveler's journey list can be filtered by these statuses.
<!-- src: backend/monolith/apps/trips/models.py, trips/lifecycle.py, trips/views.py -->

## How does a traveler create and publish a journey?
1. Create a draft with start city, end city, notes (max 2000 characters) and 1 to 20 legs.
2. Upload a ticket proof for each flight (and sea) leg.
3. Publish. Publishing is refused unless all of these hold:
   - The traveler has a current approved ID check (KYC) that has not expired. Error `traveler_kyc_not_approved`: "Current traveler KYC approval is required for this journey."
   - Every flight/sea leg has an approved ticket proof. Error `flight_proof_not_approved`: "Every flight leg requires a currently approved ticket proof." (sea: `sea_proof_not_approved`).
   - The first leg departs in the future (`journey_departure_not_future`: "The first leg departure must be in the future."). No grace period.
   - Legs are connected, each starts where the previous ends (`journey_legs_disconnected`), and times increase (`journey_leg_time_order_invalid`: a leg cannot depart before the previous one arrives, and departures must be strictly increasing).
   - Every leg has an arrival time after its departure (`journey_leg_arrival_required`, `journey_leg_time_invalid`).
   - The first/last leg match the journey start/end (`journey_endpoints_mismatch`).
   - Only `draft`, `pending_verification` or already `active` journeys can be published (`journey_status_not_publishable`). Only the owner can publish (`journey_not_owned`).
4. On publish: status becomes `active`, route alerts are queued, and "did you depart/arrive" reminders are queued for each leg.
- KYC and ticket approval are checked again at every new offer and acceptance. If KYC expires or a ticket is later rejected the journey stops being offerable/listed.
<!-- src: backend/monolith/apps/trips/services.py -->

## What can a leg contain? (modes, capacity, limits)
- Modes: `FLIGHT`, `DRIVE`, `SEA`. Other modes (bus, train) do not exist.
- Each leg: origin and destination (catalogue city or airport), departure time, arrival time (required), capacity in kg (0.01 to 20000 kg; typo guard, not a business cap), optional volume capacity (1 to 200000 litres), optional max parcel count (1 to 10000).
- A journey can have up to 20 legs. There is no product limit on how much a traveler can carry.
- Flight legs: must start and end at airports and carry a flight number (max 16 chars). "Flight legs require a flight number." / "Canonical flight legs must start and end at airports." Drive and sea legs cannot have a flight number.
- Endpoints must differ; a place that is temporarily unmatched is refused ("This place is temporarily unavailable for matching.").
- Drive legs: the server stores the road distance and route when it can; the client cannot send these fields.
- Optional per-journey settings: refused item categories and "accepts fragile".
  - Categories are `documents`, `small_box`, `electronics`, `clothing`, `other`. A journey cannot refuse all five ("A journey must accept at least one kind of item.").
  - If the traveler refuses a category or fragile items, requests of that kind do not match (check `item_accepted_by_traveler`).
<!-- src: trips/serializers.py, trips/constraints.py, trips/models.py -->

## Which transport modes are allowed between which places?
- DRIVE: only inside one road network. Algeria is one network. France, Spain and Germany are one continental network. Algeria to Europe cannot be driven. Error `journey_leg_mode_unavailable`: "Leg N cannot be driven between DZ and FR; this segment must be a flight."
- FLIGHT: any two airports.
- SEA: see the sea legs section. Off by default.
- Checked at write, at publish, and again at matching.
<!-- src: trips/transport_rules.py -->

## Are sea legs available?
- Switched off by default. Admin setting: console Business settings, "Marketplace features" card, "Allow sea legs" (`sea_legs_enabled`, default off).
- When on, a sea leg needs: both ends are port cities (catalogue cities that end a crossing) and an active sea crossing joins them in that direction. Refusal reasons: `sea_legs_disabled` ("sea legs are not available at the moment"), `sea_crossing_unavailable` ("no active sea crossing joins these two ports"), `sea_endpoint_not_port_city` ("both ends of a sea leg must be port cities").
- Sea legs need a ticket proof like flights. The sea leg distance is the great-circle distance between the two port cities, stored at write time.
- Turning the switch off, or deactivating a crossing, closes the whole journey that uses it to new offers and removes it from listings (not only parcels that would sail). Funded deals are untouched.
- Seeded crossings (reviewed list, each in both directions). Active, 12 lines: Marseille to Algiers, Bejaia, Skikda, Oran, Annaba; Valencia to Mostaganem, Algiers, Oran; Almeria to Oran, Ghazaouet; Alicante to Algiers; Barcelona to Algiers. Seeded but inactive (7 lines, waiting for staff confirmation): Sete to Algiers, Bejaia, Oran, Skikda, Annaba; Alicante to Oran; Barcelona to Oran. Live state is in the database, so staff may have changed it.
- Staff manage crossings in the console under System, Geography, Sea crossings (add, activate/deactivate). Needs the `manage_settings` permission and a reason; each change is audited. There is no edit: add a new crossing and deactivate the wrong one. The AI helper can prepare `sea_crossing.activate` / `sea_crossing.deactivate` for an admin with `manage_settings` to confirm.
- The app reads `GET /api/geography/sea-crossings` (enabled flag plus active crossings).
<!-- src: trips/transport_rules.py, locations/sea_crossings.py, locations/data/sea_crossings.json, admin_panel/console_urls.py -->

## What countries and places can be used?
- Launch countries: Algeria (DZ), France (FR), Spain (ES), Germany (DE).
- Catalogue (seed file): about 1541 Algerian, 34875 French, 8132 Spanish, 10749 German localities (cities/communes), plus regions, and 161 passenger airports (DZ 31, FR 49, ES 42, DE 39). Live counts may differ after later imports.
- Journeys and parcels use "localities" as the matching identity. An airport is mapped to the city it serves (one primary "served" mapping). An airport with no active mapping cannot be used for matching, and a city is matched whether the traveler picked the city or its airport.
- Place search: `GET /api/geography/places` (filters q, country, place_type, parent; 25 per page, max 100). Airports are only offered when mapped to a city.
- A place retired from the catalogue stops matching (fails closed).
<!-- src: locations/models.py, locations/geography_views.py, locations/data/geography_manifest_2026.json.gz -->

## What is a ticket proof and how is it reviewed?
- Needed for every `FLIGHT` and `SEA` leg. `DRIVE` legs need none. Nobody is exempt.
- Upload: photo field, JPEG, PNG or WebP only, max 10 MiB. Kinds: `ticket`, `boarding_pass`, `booking_confirmation`. Upload only while the journey is `draft` or `pending_verification` (`journey_proof_upload_closed`: "Proof can only be added before journey publication.").
- Errors: `proof_file_too_large` (413, "File exceeds 10 MiB."), `proof_media_type_unsupported` (415), `proof_not_required` (drive leg), `proof_kind_unknown`, `proof_storage_unavailable` (503). A retry with the same idempotency key does not create a duplicate.
- Proof statuses: `pending`, `approved`, `rejected`. Per leg the app shows `proof_state`: `not_required`, `missing`, `pending`, `approved`, `rejected` (approved beats pending beats rejected).
- Staff review in the console: Verification, Tickets tab (page "Verification", flight-proofs queue). Decisions: Approve, "Ask for a new upload", Reject. A reason (max 2,000 characters) is required for the last two and the traveler reads it exactly. "Ask for a new upload" stores the proof as `rejected` too; the audit records that a new upload was asked for. Needs `view_flight_proofs` to see and `review_flight_proofs` to decide. The traveler gets an email and an in-app update.
- Editing a draft route: changing mode, places, flight number or times of a ticket leg sends its approved/pending proofs back to `pending` (history kept). Rejected proofs stay rejected. Removed legs lose their proofs. The edit response says how many were reset.
<!-- src: trips/views.py, trips/proofs.py, trips/services.py, admin_panel/services.py, admin_panel/console_forms.py -->

## Can a traveler edit a journey?
- Only while `draft` or `pending_verification`, and only the owner. Otherwise 409 `journey_not_editable`: "A journey in status 'active' can no longer be edited."
- Also refused if a delivery or a pending/accepted proposal is attached (`journey_has_dependent_state`).
- An edit sends the whole route again; fields left out are cleared.
- After publishing, only times (schedule change), pause/resume and price can change.

## Can a traveler cancel a journey?
- Allowed unless `in_progress` or `completed` (`journey_not_cancellable`).
- Refused while any deal is accepted, funded or in later stages (`journey_has_funded_deal`: "A journey with a funded or operational deal cannot be cancelled.").
- On cancel: unpaid reservations are released, and pending proposals (matches/offers) are expired/cancelled.
<!-- src: trips/services.py -->

## How does pausing a journey work?
- Pausing hides the journey from discovery and refuses new offers. Offers already pending cannot be accepted while paused. Funded deals continue untouched.
- Traveler: pause/resume own journey (statuses `active`, `in_progress` only; else `journey_not_pausable`). No reason needed. Idempotent.
- Staff: console, Marketplace, Journeys, journey page, "Pause journey" / "Resume journey" ("Take over the pause" if the traveler already paused). Needs `manage_journeys` and a reason (max 500 characters, audited, never shown to the traveler). Staff may also pause drafts.
- A staff pause can only be lifted by staff. The traveler sees: "Wassla staff paused this journey; contact support to resume it." (`journey_paused_by_staff`). Staff cannot lift a traveler's own pause: "The traveler paused this journey; only they can resume it."
- The AI helper can prepare `journey.pause` / `journey.resume` (an admin with `manage_journeys` confirms it on the console; a reason is required).
<!-- src: trips/services.py, admin_panel/console_journey_pause.py, admin_helper/actions.py -->

## Can a traveler set their own price?
- Optional: a price per kg and a minimum per parcel, both or neither (EUR cents). Error `journey_price_invalid` reason `price_incomplete`: "Set both a price per kg and a minimum per parcel, or neither."
- Settings (console Business settings, "Marketplace features" card: "Let travelers set a price", "Largest price per kg a traveler may set", "Largest minimum per parcel a traveler may set"): on by default; max per kg default EUR 100 (allowed EUR 1 to 1,000); max minimum per parcel default EUR 500 (allowed EUR 1 to 10,000). These are typo guards. Above them: "The price per kg is above the largest Wassla allows." Switch off: "Setting a price on a route is not available right now." (`traveler_pricing_disabled`). Clearing or resending the same price is always allowed.
- Can be changed while the journey is draft, pending, active or in progress. Each change is logged. A change only affects offers made afterwards; existing offers and deals keep the price they froze.
- Only the owner can set it. Staff have no console or helper action to change a journey's price.
- It is a default, never a floor: see the listed price section.
<!-- src: trips/pricing.py, core/marketplace_policy.py -->

## How is the "listed price" a sender sees calculated?
For a priced journey and one parcel, the listed reward is the largest of:
1. traveler price per kg times the parcel's chargeable weight, rounded up to a whole cent;
2. the traveler's minimum per parcel;
3. Wassla's own minimum for this match.
Worked example: traveler 8 EUR/kg (800 cents), minimum 10 EUR (1000), parcel chargeable weight 3 kg, Wassla minimum 7 EUR (700). Terms: 2400, 1000, 700. Listed reward 24.00 EUR, basis `per_kg`. With a 1 kg parcel: 800, 1000, 700 gives 10.00 EUR, basis `traveler_minimum`. On a tie the traveler's own term is named. Fee and sender total come from the same commission rate as the quote (see pricing.md).
- No listed price if the journey has no price or traveler pricing is off. The sender can still offer any reward at or above Wassla's minimum.
- Home trip cards show the traveler's price per kg and minimum (not a per-parcel reward).
<!-- src: matching/listed_price.py, discovery/listings.py -->

## How does a traveler report progress on a leg, and what are the reminders?
- Report kinds: `at_port` (sea legs only), `departed`, `arrived`. Only on `active` or `in_progress` journeys, only by the owner.
- Order: `departed` needs the previous leg's `arrived`; `arrived` needs `departed`; `at_port` is refused after `departed`. Errors `progress_out_of_order`, `progress_kind_not_allowed`.
- Earliest: 24 hours before the planned time. Else `progress_too_early`: "It is too early to report this."
- A report can be retracted within 10 minutes, unless a later report depends on it (`progress_retract_window_closed`: "A report can be retracted for ten minutes only."; `progress_has_followup`).
- It is the traveler's statement, not proof. It is copied to the timeline of every funded parcel on that leg, labelled "reported by the traveler", and the sender is notified. It changes no deal status and moves no money.
- Reminders ("did you depart / arrive?"): sent only for a leg that carries a funded parcel and is not yet reported. First reminder is 30 minutes after planned departure and 60 minutes after planned arrival; repeated every 180 minutes, up to 2 repeats. Also shown on Home as "needs attention". Reminders stop if the journey is not live, the time changed, or the traveler reported.
- Stored marketplace settings (`reminders`), with no form on the console Settings page: `enabled` true; `depart_after_minutes` 30 (5-1440); `arrive_after_minutes` 60 (5-1440); `repeat_after_minutes` 180 (15-1440); `max_repeats` 2 (0-5).
<!-- src: trips/progress.py, core/marketplace_policy.py -->

## What happens when a traveler changes the times of a published journey?
- Only times can change (not places or stops), only on `active`/`in_progress` journeys, by the owner. Legs reported arrived cannot change; a leg reported departed keeps its departure; a new departure must be in the future. Only one waiting change at a time (`schedule_change_pending`). A reason (max 500 chars) is optional. The traveler gets a preview first.
- Each parcel on a changed leg (not yet delivered) is "affected". A parcel is "material" (needs the sender's answer) when:
  - the new arrival is after the sender's deadline (and later than agreed), or
  - the arrival moves by more than the threshold from what the sender last agreed to, or
  - for a parcel not yet picked up, the pickup departure moves by more than the threshold, or earlier than the agreed pickup time.
  Threshold: stored marketplace setting `route_change.material_shift_minutes`, default 360 minutes (6 hours), range 30 to 10080. It has no form on the console Settings page.
- A parcel already picked up is only informed, never asked.
- No material parcel: the change applies at once and affected senders are told. Otherwise it waits: each material sender accepts or declines (can change their answer while waiting); it applies once all are accepted/collected/no longer active. The traveler can withdraw it. The server re-checks every 30 minutes and withdraws it (`no_longer_valid`) if the trip moved on.
- A sender who declines may cancel through the normal cancellation flow; it counts as caused by the traveler (see problems-and-disputes.md). The change never rewrites a deal: the funded arrival snapshot, payout floor and agreed pickup time stay as frozen at funding.
- Applying re-times legs, sends a re-timed flight/sea ticket back to review (notice: "Your ticket will be checked again. Until staff approve it, this trip takes no new proposals. Deliveries already paid for continue."), and re-creates the leg reminders.
- Errors: `schedule_change_empty` ("These are the times already in force."), `schedule_change_pending` ("New times are already waiting for senders. Withdraw them first."), `journey_not_reschedulable`, `schedule_change_answer_not_needed`.
<!-- src: trips/schedule_changes.py, core/marketplace_policy.py -->

## What are stop options (pickup/drop-off at a stop)?
- A stop is a city on the route: stop 0 is the first origin, stop N the last destination. Each stop may accept pickup, drop-off, both or neither, with an optional handover note (max 280 chars) and a handover window (both ends needed, must fit between arriving and leaving the stop).
- No setting means it accepts both. Nothing can be dropped at the first stop or picked up at the last ("Nothing can be dropped off where the trip starts." / "Nothing can be picked up where the trip ends.").
- Matching refuses a parcel at a stop that does not accept it (check `stop_services_allow_handover`). The note is shown only to the parties of a funded deal.
<!-- src: trips/stops.py -->

## How does matching decide a trip fits a request?
A request and a journey are compatible only if every check passes. Failed checks are listed as rejection codes (visible to staff in the match explanation):
- `request_active` (open request), `journey_active` (active or in progress), `journey_not_paused`, `accounts_eligible` (both active, not banned, different people), `traveler_kyc_current`, `journey_leg_sequence`.
- `item_safety_eligible` (sender confirmed the five safety declarations), `item_accepted_by_traveler`, `pricing_inputs_complete` (weight and deadline present), `target_traveler_eligible` (a request aimed at one traveler only matches that person), `request_has_no_active_deal`, `canonical_geography_complete`.
- `pickup_before_delivery`: the pickup city and the drop-off city must both be stops of the journey, pickup before drop-off. Matching is by city, not by distance: an airport counts as the city it serves. There are no detour or kilometre limits for current journeys (detour checks pass automatically).
- `stop_services_allow_handover`, `sea_legs_available`, `flight_proofs_approved`, `sea_proofs_approved`, `flight_coordinates_trusted`.
- `route_time_order_feasible`: pickup time is in the future and before drop-off.
- `pickup_within_ready_window`: the traveler's departure from the pickup stop is inside the sender's ready window.
- `delivery_before_deadline`: arrival at the drop-off stop is on or before the sender's deadline.
- Capacity on every covered leg: `capacity_available_on_every_leg` (parcel actual weight vs remaining kg after active reservations), `volume_available_on_every_leg` (only if the leg has a volume limit and the parcel has dimensions; volume = L x W x H cm / 1000, rounded up to litres; without dimensions the match carries a "volume_unverified" caveat), `parcel_slots_available_on_every_leg` (only if the leg has a parcel count).
- Weight used for capacity is actual weight; chargeable (billing) weight is in the pricing file.
- Worked example: Algiers to Paris parcel, 3 kg, ready 10-12 June, deadline 14 June. Journey: flight Algiers to Paris departs 11 June 09:00, arrives 11 June 12:00, 20 kg free, KYC and ticket approved, not paused. All checks pass, so it is shown. If the flight departed 13 June it fails `pickup_within_ready_window`; if it arrived 15 June it fails `delivery_before_deadline`.
<!-- src: matching/compatibility.py -->

## Why is a trip not shown to a sender in Find Travelers?
Check in order:
1. Request not `open` (states: awaiting deposit, already matched, closed, in progress). The screen then shows state `request_ineligible` with a reason (`awaiting_deposit`, `already_matched`, `closed`, `in_progress`), not an empty list.
2. Journey not discoverable: not active/in progress, paused (by anyone), no leg left in the future, traveler inactive/banned/KYC missing or expired, owner is the same person.
3. Any failed check from the list above (time window, deadline, capacity, ticket not approved, sea leg closed, stop does not accept pickup/drop-off, refused category or fragile).
4. The journey does not pass through both cities in the right order.
5. Limits: only the first 200 candidate journeys are scanned (`candidate_scan_limit`) and at most 50 are returned (`result_limit`). Candidates with an exact pickup and drop-off node, then newest published, are scanned first. Both limits are stored matching settings with no console form.
- An empty result is state `no_candidates` (normal, not an error).
<!-- src: matching/find_travelers.py, matching/discovery.py, trips/lifecycle.py, matching/policy.py, core/migrations/0006_seed_phase4_business_settings.py -->

## How are Find Travelers results ordered and labelled?
- Ordering sorts by score (high first), then less added distance, earlier pickup, then id. Sort options in the app: `best_match` (default), `soonest_departure`, `listed_price` (cheapest listed reward first; unpriced journeys keep best-match order after priced ones). Pages of 10.
- Score = weighted average of factors, each 0 to 1000: route_fit 30, detour 25, time_fit 20, verification 10, freshness 5, neutral_reputation 10 (defaults in the stored ranking settings; no console form). For current journeys route fit and detour are always full score, so in practice order is decided by time slack (deadline minus arrival; full score at 7 or more days), request age (full score fresh, zero at 30 days), the fixed verification score and fixed neutral reputation 500. Ratings do not affect ranking. Scores are never shown to users.
- Labels the sender sees:
  - Route fit: `excellent` (parcel rides the whole trip), `good` (shares the start or end of the trip), `compatible` (traveler passes through). All three are real matches.
  - Timing fit: `comfortable` (arrives 24 hours or more before the deadline) or `fits`.
  - "Why this trip fits" reasons: picks up in, arrives in, direct leg or number of transfers, whole trip matches, arrives before deadline, has room for N kg, identity verified, flight/ferry ticket approved.
  - Traveler card: first name, rating (average to one decimal, or "new"), completed deliveries as a traveler.
- Primary mode shown: flight beats sea beats drive.
<!-- src: matching/ranking.py, matching/find_travelers.py -->

## What can boost do, and what can it not do?
- A boost adds ranking points to a request only while the boost is active (weight above 0 and not expired). Points = boost weight x 25, capped at 200 (settings `boost_points_per_weight`, `max_boost_points`), added to the score of about 0 to 1000.
- Boost never bypasses compatibility: ranking only happens after every check passes (`compatibility_override` is always false). A boosted request that does not fit a trip still does not show. Boost also adds extra reward money, see pricing.md.
- The sender always proposes first.
<!-- src: matching/ranking.py, parcels/models.py -->

## What does a traveler see for matching requests?
- Home "Matches" tier shows, for the sender, up to 3 of their open requests each with up to 3 best trips; for the traveler, up to 3 of their next journeys each with up to 3 best requests. States: `results`, `none`, `no_active_items`.
- Traveler matching scans open, untargeted-or-targeted-at-them requests whose ready window overlaps the journey and whose deadline is not before the first departure, with weight set, no active deal, sender active and not banned.
- Exact capacity left is never published. Cards show a band: `under_5kg`, `5_to_10kg`, `10_to_20kg`, `20kg_plus` (smallest free weight on legs still ahead).
<!-- src: discovery/matches.py, discovery/listings.py -->

## What is Home discovery and what switches control it?
Three tiers: Matches, Listings (trips and open requests anyone can browse), People (opt-in profiles).
Settings (console Business settings, "Marketplace features" card; stored under `discovery`):
| Setting | Default | Range |
|---|---|---|
| `listings_enabled` | true | on/off |
| `profiles_enabled` | true | on/off |
| `interest_daily_cap` | 10 | 1-100 |
| `trip_fit_alerts_enabled` | true | on/off |
| `trip_fit_max_travelers` | 30 | 1-100 |
| `trip_fit_daily_cap` | 5 | 1-50 |
- A switched-off tier answers normally with state `disabled` (the section simply is not offered). If settings are unreadable discovery answers 503 "Discovery is temporarily unavailable."
- Who may read: Listings (trips and requests), People, a person's page and both review lists are public. A visitor without an account gets the same cards and the same disabled states as a member; a member's own trips, requests and profile are left out of their own lists, a visitor's lists leave nothing out. Matches, "I can carry this", the own public profile and route alerts need an account (401 without one). Limit 60 per minute per member. A visitor is counted per network address on one roomy limit, 300 per minute, shared with the place picker, and not on the general anonymous 60 per minute: Algerian mobile networks put hundreds of people behind one address. The app does not offer browsing without an account yet.
- The settings are checked at each request; nothing is cached. An unknown or misspelt key is refused when the settings revision is saved.
<!-- src: core/marketplace_policy.py, discovery/views.py -->

## Which trips and requests are listed on Home?
- Trip listed only if the matching engine could still offer on it: active/in progress, not paused, has a future leg, traveler active, not banned, current KYC, every needed ticket approved, sea legs open, and no leg ahead that is already full (by kg, volume or parcels). Only journeys created with the current route format are listed.
- Request listed only if: delivery request, open, not aimed at one traveler, not expired (deadline and ready window end both in the future), weight set, no active deal, sender active and not banned.
- Trips sorted by next departure; requests newest first. Own items are hidden from the owner. Filters: origin/destination city or country, "departing after". Pages of 20 (max 50), paging limited to offset 1000.
- A trip card shows first name, ID verified, rating, completed deliveries, stops (city labels only), leg modes and times, capacity band, optional price. Request cards show sender first name, cities, title, category, fragile, weight, windows, deadline, reward, boost and total. Never addresses, recipient, dimensions or coordinates.
<!-- src: discovery/listings.py, discovery/serializers.py -->

## What is "I can carry this" and what limits it?
- A traveler taps it on an open listed request with one of their own journeys. The server first checks full compatibility; if not compatible: 409 `incompatible_candidate` "This journey cannot carry this request." with the rejection codes.
- It sends the sender one notification. It is not an offer, has no price, reserves nothing, and the sender still proposes first.
- One signal per request and journey (repeat returns the existing one). Daily cap: 10 per traveler in the last 24 hours (rolling, setting `interest_daily_cap`). At the cap: 429 `interest_daily_cap_reached` "You have reached today's limit. Try again tomorrow."
- Other errors: `discovery_listings_disabled` "Browsing requests is not available right now.", `request_not_found` "This request is no longer open.", `journey_not_found` "Choose one of your own journeys."
- Staff can read these under a person's profile, Discovery tab, "I can carry this".
<!-- src: discovery/interest.py, admin_panel/console_discovery.py -->

## How do public profiles work?
- Off by default. A member opts in (consent wording version `l2a-2026-11` and time are stored). Turning it off and dismissing the Home prompt always work, even when the switch is off; turning on needs `profiles_enabled`.
- Visible only if: member turned it on, staff have not hidden it, account active and not banned, `profiles_enabled` on. Visible to others on the other side of the marketplace; People list shows travelers to senders and the reverse. A person appears if they published a journey (or made a request) in the last 365 days or have a usual route.
- Card: public id (not user id), first name, ID verified, member since (year-month), rating and completed deliveries (both roles), up to 3 usual routes (two different cities each, no duplicates).
- States for the owner: `visible`, `not_visible`, `hidden` (owner is only told it is not currently visible), `disabled`.
- Staff hide/show: console, person page, Discovery area, "Hide profile" / "Show profile again". Needs `manage_users`, a reason (max 500, audited, member not shown it). The AI helper can prepare `profile.hide` / `profile.show` for the admin to confirm.
<!-- src: discovery/profiles.py, admin_panel/console_discovery.py -->

## What are route alerts?
- A member asks to be told when someone publishes a trip (or request) on a city pair, optionally following one public-profile person. Needs the listings switch on (else "Route alerts are not available right now."). Max 10 active alerts per member (`route_alert_limit_reached`: "You can keep at most 10 route alerts."). Same city twice refused; cannot follow yourself; following needs `profiles_enabled`. Deleting an alert deactivates it (staff can still read it, Discovery tab, Route alerts).
- Fan-out runs after a journey is published or a request opens. A trip alert covers every city pair of the stops still ahead. At most one notification per alert every 6 hours. The owner is never notified of their own item. If the traveler was already given a trip-fit alert for that request, the route alert is skipped.
<!-- src: discovery/alerts.py, discovery/models.py -->

## What are trip-fit alerts to travelers?
- When a request becomes listed, travelers whose published trip really fits (same engine as Find Travelers) get one notification "a parcel fits your trip". Not an offer; reserves nothing.
- Limits: at most 30 travelers per request (best ranked first), at most 5 trip-fit alerts per traveler in 24 hours, never twice for the same request and journey; a traveler with two fitting trips is told once about the better one. Settings in the discovery table above.
<!-- src: discovery/trip_fit.py -->

## Which places can a traveler's Home "route" search find, and what can staff see?
- A city filter matches the city and every airport serving it.
- Console Marketplace, Journeys list (needs `view_journeys`): columns Journey, Traveler, Ordered route, Capacity (smallest leg), Departs, Tickets, State; filter by stored journey status; search by traveler. Each journey page shows stops, pause state and status. Ticket proofs are decided on Verification, Tickets.
<!-- src: admin_panel/console_views.py -->

## Not covered here
- Live sea crossing on/off state and current catalogue counts (database-dependent).
- Exact notification wording of leg reminders, trip-fit and route alerts (see messages-and-notices.md).
- Offer deadlines, offer economics and request creation rules (see deliveries.md and pricing.md).
