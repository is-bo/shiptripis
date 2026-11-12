# L3B: Routes for everyone, mobile and admin screens

Package L3B of `docs/WASSLA_DISCOVERY_PRO_PLAN.md`, built on the L3A contract
(`docs/PHASE_L3A_ROUTES_BACKEND.md`). The server decides everything; these screens collect, show and
explain. Flight and road behaviour is unchanged for every existing input.

## 1. What a traveler can do now

- Build a journey with a ferry leg: Lille → Marseille by road, Marseille → Algiers by ferry, Algiers →
  Constantine by road, on a 360 px phone in Arabic, with no horizontal scroll and nothing under the
  pinned Save button (`test/l3b_sea_screens_test.dart`, screenshots in the thread).
- Choose Ferry only where the server's list says a line joins the two cities and the owner's switch is
  on. When the only thing missing is the switch, one line says "Ferry legs are switched off for now".
- Set, per leg, optional **Volume (litres)** and **Number of parcels** under "More capacity options".
- Set, per stop, what it takes (pickups, drop-offs), an optional time window and a note, in a sheet.
  The sheet says who sees the note: only the traveler until a delivery that uses the stop is paid for,
  then that delivery's sender.
- Say what they carry: five item categories on by default (the last one cannot be switched off) and
  fragile items.
- Upload a ticket for a flight or a ferry leg, with copy and a short "a good photo shows" list for each.
- Pause and resume their own live journey; see a banner while paused. A staff pause shows the same
  banner with no Resume button and no reason (the reason is internal): the traveler is told to contact
  support.
- A sender sees ferry legs on trip cards, the trip preview and the funded deal, "Ferry ticket verified"
  in the checks block, a caveat when volume could not be checked (`volume_unverified`), and, after
  funding, where and when to meet from the traveler's stop window and note.

## 2. Mobile design rules

- **The server is the authority.** Sea is *offered* from `GET /api/geography/sea-crossings` (switch on,
  a line exists in that direction, neither end is an airport) and the server still refuses whatever it
  likes. `proof_required` and `proof_state` come from the server; the client no longer derives either
  from the mode (`TransportMode.requiresProof` is deleted).
- **Fail soft.** The list is its own provider with retry off. If it fails, flight and road legs edit as
  before, a notice says ferry lines did not load (with Try again) only when a ferry could matter, and
  nothing is rewritten. A list that arrives late or changes never changes a leg the traveler already
  has: a ferry leg whose line went away keeps its mode and shows the server's reason on that leg.
- **A server refusal lands on its leg.** `journey_leg_mode_unavailable` carries `leg_position` and, for
  sea, `reason` (`sea_legs_disabled`, `sea_crossing_unavailable`, `sea_endpoint_not_port_city`). A
  refusal raised from a serializer wraps each value in a one-element list, so `ApiException.intExtra`
  and the new `stringExtra` unwrap it.
- **A ferry joins cities.** A sea leg sends the stops' city ids even when the same stops carry airports
  for a flight on the other side. Stop options send only the stops that differ from the default; the
  first stop sends its pickup choice for both sides and the last its drop-off choice, so the request
  never contradicts the server's own normalisation.
- **Ticket state is shown, not guessed.** An unknown `proof_state` reads as "not uploaded", never as
  approved.

## 3. Admin console (server-rendered)

- **Geography → Sea crossings** (`#st-sea-crossings`): a table with From, To, Distance and State; "Add a
  crossing" and "Turn on/off" each ask for a reason and write one audit row (`sea_crossing.*`).
  Permission `manage_settings`. The add form resolves a city by country and name with the same resolver
  the seed command uses (`apps.locations.sea_crossings.resolve_port`). Distance is asked only when a
  city has no catalogue coordinates.
- **Settings → Marketplace features** gains the "Sea legs" switch with a warning line.
- **Verification → Ticket proofs** (was Flight proofs): title, a Mode column and filter, and where a
  flight shows its number a ferry shows the document kind. Detail copy follows the mode.
- **Journey detail**: pause or resume with a reason (`manage_journeys`, audited `journey.paused` and
  `journey.resumed`; a staff pause turns an owner pause into a staff pause), stops with their options,
  what the traveler carries, capacity by leg including volume and parcels, and the leg's ticket state.

## 4. Names

| Was | Now |
| --- | --- |
| `NotificationChannel.flightProofStatusChanged` | `legProofStatusChanged` |
| `ApiErrorCode.proofOnlyForFlight` | `proofNotRequired` |
| `staleFlightProofInvalid` (l10n) | `staleTicketInvalid` |
| `proofExplainer` (l10n) | `proofExplainerFlight` (+ `proofExplainerSea`) |
| `maxJourneyLegCapacityKg` 200 | 20000 (the server's typo guard) |

Kept on purpose because they are stored in audit and role rows or are public paths:
`flight_proof.*` audit actions, `view_flight_proofs` and `review_flight_proofs` permissions, and the
`verification/flight-proofs/` URL paths.

## 5. Tests

- Mobile: `test/l3b_sea_route_model_test.dart` (30: wire, offers, never-silently-demoted, what is sent,
  stop options, what I carry) and `test/l3b_sea_screens_test.dart` (18: Lille → Constantine in en and ar
  at 360 px with no overflow and a clear footer, switch off, failed list with retry, refusal on the leg,
  carry and stop options on the wire, editor by mode, proof screen per mode, pause, staff pause).
- Backend: `apps/admin_panel/tests/test_l3b_console.py` (34: crossings page and permissions, add and
  toggle with audit rows, ticket queue mode filter, ferry detail, pause, resume, takeover, permissions)
  and `apps/discovery/tests/test_marketplace_policy.py` (the Sea legs switch in the saved policy).
