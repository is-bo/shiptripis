# Wassla Discovery and Professional Delivery Specification

Status: **locked by Ismail on 2026-11-10; four follow-up answers added on 2026-11-11; additions approved by
Ismail on 2026-11-12 (sections 16 to 20, and the no-show reports in section 12); scope narrowed by
Ismail on 2026-11-13 (professional transporters and courier handoff parked, see "Scope change of
2026-11-13" below).** Baseline: `feature/wassla-v3-baseline` at `dd7f820`.
Working branch: `feature/discovery-professional-delivery`.
Build order and work packages: `docs/WASSLA_DISCOVERY_PRO_PLAN.md`.

This document is an addendum to `docs/SHIPTRIP_V1_SPEC.md`. Where the two differ, **this document wins
for the topics it covers**, because the owner explicitly overrode the V1 specification for them. Everything
this document does not mention stays exactly as the V1 specification says.

A rule in this document is a product decision. An agent must not reinterpret, extend or relax one. If a
rule turns out to be impossible or contradictory in the code, stop and report it to the orchestrator; do
not pick a different rule.

---

## Scope change of 2026-11-13

Ismail decided on 2026-11-13 that Wassla is for **fast delivery: urgent parcels, mostly on flights and
drives made the same day**. Three consequences, all his decisions:

1. **Professional transporters are not part of this build.** No business profile, no business
   document check, no Professional Mode, no Pro badge, no manifest dashboard, no ticket exemption.
   They are planned later, on a subdomain of their own.
2. **Custody history and courier handoff are not part of this build.** A parcel is delivered the way
   the V1 specification says: the traveler enters the recipient's delivery code.
3. **"Same day" is the target, not a rule.** The app refuses no trip for its length or its dates.
   Multi-stop routes stay. Sea legs stay as built, behind their switch, which stays off.

The complete text of what was parked (sections 7, 9 and 10, every rule elsewhere that mentioned them,
and their work packages) is kept in
`docs/parked/WASSLA_PROFESSIONAL_AND_COURIER_PLAN.md`. **Do not start any of it and do not leave
hooks for it.**
Section numbers are unchanged so that existing references stay valid; a parked section keeps its
heading and says where its text went.

Everything else in this document stands. One number changed for the new target: a proposal waits 6
hours for an answer instead of 48, and never past the pickup time (section 17.1).

The file names and the branch name still say "professional delivery". They are kept because merged
work refers to them.

## 1. What this adds

1. **Home discovery.** Senders see travelers, travelers see senders. Real compatible matches come first,
   then real published trips and open requests, then people who chose to be visible.
2. **Routes for everyone.** Every traveler can publish a multi-stop route
   with flight, road and sea legs, choose capacity per leg, set a price, and pick up and drop off at any
   stop.
3. **Professional transporters.** Parked on 2026-11-13. Not in this build.
4. **Custody and courier handoff.** Parked on 2026-11-13. Not in this build.
5. **Progress and reminders.** Travelers report "at the port", "departed", "arrived". The app asks them
   when they forget. Senders see it in tracking.
6. **Admin control.** One verification inbox, switches for the risky capabilities, pause, suspend and
   hide, all audited with a reason.

Added on 2026-11-12:

7. **Tracking number.** One friendly number per parcel, shown everywhere (section 16).
8. **Proposals that do not hang.** A response deadline with a reminder, and an alert to travelers whose
   trip fits a new parcel (section 17).
9. **No-show reports.** Either side can say "the other person did not come" (section 12).
10. **Reviews.** The comments behind a rating are readable, reportable and moderated (section 18).
11. **Admin security and exports.** Two-step sign-in for staff and finance exports (section 19).
12. **Admin AI helper.** Each admin can connect their own AI assistant to a briefing of their work, with
    their own authority and nothing more (section 20).

## 2. What this overrides in the V1 specification

| V1 specification | Replaced by |
| --- | --- |
| §6: no ferry or sea transport; an Algeria to non-Algeria leg must be FLIGHT | Section 5 below: a `SEA` mode exists for everyone, on admin-managed crossings, behind an admin switch |
| §6 and AGENTS.md: modes are FLIGHT and DRIVE; only flight legs need proof | Section 6: flight **and sea** legs need a ticket proof |
| §10: per-leg capacity is weight only, with a 200 kg ceiling per leg | Section 5.5: weight stays the main capacity; volume and parcel count are optional; the ceiling becomes a typo guard, not a policy cap |
| Home shows only the user's own activity | Section 4: Home also shows discovery |
| Brand note: Railway resources remain in place for compatibility | Hosting is the VPS. Railway deployment files and Railway-only code are removed on this branch (plan package L1A) |

Nothing else is overridden. In particular these stay untouched and every phase must prove it:

- EUR is canonical, in integer cents. DZD is only a Chargily or manual-settlement representation.
- The sender proposes first. Boost never bypasses compatibility.
- Exact locations stay hidden until the deal is funded.
- The traveler can never read the delivery code. It stays locked for 30 minutes after pickup.
- Only the traveler confirms delivery, by entering the recipient's code (V1 §17). The exception once
  planned for courier handoff was parked on 2026-11-13.
- Delivery protection is 48 hours. A dispute freezes the payout. The funded arrival floor still gates payout.
- The platform fee is added on top of the traveler's reward.
- Kaba / ProductRequest stays retired.
- Navigation is Home, Deliveries, Chat, Profile. Notifications live in the bell.
- Backend state is authoritative. The client never fakes payment, verification, delivery or payout.

## 3. Launch scope

- **Countries:** Algeria, France, Spain, Germany only. The place catalogue already covers exactly these.
  No new country is imported in this work.
- **Languages:** English, French, Arabic with right-to-left layout, on every new screen, email and web page.
- **Parked on 2026-11-13** (do not start them, do not leave hooks for them; their text is in
  `docs/parked/WASSLA_PROFESSIONAL_AND_COURIER_PLAN.md`): professional transporters, the manifest
  dashboard, custody history, courier handoff.
- **Not in this build** (do not start them, do not leave hooks for them): courier company API
  integrations, fleet or vehicle management, recurring routes, business analytics, business logos or
  photo avatars, free-text public bios, insurance or customs document handling, new countries.

## 4. Home discovery

### 4.1 Three tiers, in this order

1. **Matches for you.** For a sender: for each of their open requests, the travelers who are really
   compatible, from the existing Find Travelers engine. For a traveler: for each of their active
   journeys, the requests that are really compatible, from the existing compatible-requests engine.
   No second matching implementation may exist. Discovery calls the same functions.
2. **Listings.** For a sender: published journeys ("Trips"). For a traveler: open requests ("Parcels
   looking for a traveler"). These are real, current, server-filtered rows.
3. **People.** Users who opted in to a public profile and who match the viewer's side: a sender sees
   travelers, a traveler sees senders.

A tier with nothing to show renders its designed empty state. It is never filled with fake, sample or
"suggested" data.

### 4.2 What a public card may contain

A card is built by an explicit allowlist serializer. Anything not listed is forbidden.

- **Trip card:** traveler first name; ID-verified flag; rating and completed-delivery count; ordered stops at **locality level** with transport
  mode per leg; departure and arrival dates; remaining weight capacity as the existing public band;
  listed price (per kg and minimum) when set.
- **Request card:** locality of pickup and delivery; item title, category and fragile flag; weight;
  ready window and deadline; offered reward; sender first name. Nothing the existing
  compatible-requests contract does not already show a matched traveler, and never the recipient.
- **Profile card:** first name; ID-verified flag; member since (month and year); rating and completed-delivery count; up to three "usual
  routes" the user chose, as locality pairs.

Never on any public surface: last name, email, phone, exact address or coordinates, distance or detour
figures, recipient data, document data, payout data, another user's internal ids beyond the opaque id
needed to open the card.

### 4.3 Opt-in

- Public profiles are **off by default**. Home shows a one-time, dismissible card that previews exactly
  what would be visible and offers "Show my profile" and "Not now". It never blocks the screen.
- The choice lives in Profile, under "Public profile", and can be changed at any time. Turning it off
  removes the profile from discovery immediately.
- A published journey and an open request are listed because publishing them is their purpose. The
  publish and post screens say so in one line.

### 4.4 Actions from discovery

- From a trip card, a sender chooses one of their open requests, or creates a new one pre-filled with
  the route. The app then opens Find Travelers for that request with this journey in focus. If the
  server says the pair is incompatible, the screen states the server's reason. The sender still
  proposes first.
- From a request card, a traveler may tap **"I can carry this"** (kept by Ismail on 2026-11-11) when they have a journey the server
  confirms is compatible. This sends the sender one notification that opens Find Travelers with that
  traveler in focus. It is not an offer, carries no price and reserves nothing. Limits: one per journey
  and request pair, and a daily cap per traveler set in policy.
- From a profile card, a viewer may turn on a **route alert**: a notification when that person, or
  anyone, publishes a trip or posts a request on a chosen route. There is no direct message from a
  profile. Chat still begins only inside a match.

### 4.5 Admin

- Staff can hide a public profile with a reason. A hidden profile is invisible in discovery and the
  owner sees a neutral "not currently visible" state.
- Policy switches: listings on or off, profiles on or off.

## 5. Routes for everyone

### 5.1 Stops and legs

- A route is an ordered list of stops. Legs are the segments between consecutive stops. This is the
  existing `Journey` and `JourneyLeg` model.
- A sender's parcel may be picked up at any stop that accepts pickup and dropped off at any later stop
  that accepts drop-off. It uses capacity only on the legs it actually travels.
- Each stop may carry, all optional:
  - "accepts pickup" and "accepts drop-off" (both on by default; the first stop cannot be a drop-off
    and the last stop cannot be a pickup);
  - a handover time window, which must fit between arriving at and leaving that stop;
  - a short handover note, shown **only** to the sender of a funded deal that uses that stop.
- These are available to every traveler.

### 5.2 Modes

`FLIGHT`, `DRIVE`, `SEA`.

- `DRIVE`: unchanged. Allowed inside one road network (Algeria; France, Spain and Germany together).
- `FLIGHT`: unchanged. Needs airport endpoints and a flight number.
- `SEA`: allowed only between two port cities joined by an **active sea crossing**, and only while the
  admin switch "Sea legs" is on. A sea leg has no flight number.

### 5.3 Sea crossings (the "ports")

- A sea crossing is an admin-managed row: origin port city, destination port city, active or not. Each
  direction is its own row.
- Port cities are ordinary catalogue localities. There is no new place type, so city-identity matching
  is unchanged.
- The initial list is seeded from the table in 5.3.1, which Ismail asked to be researched on
  2026-11-11. Each crossing is seeded in both directions.
- Staff can add, activate and deactivate crossings in the admin Geography area, with a reason, audited.
- Deactivating a crossing, or turning the switch off, blocks new journeys and new offers on journeys
  that use it. It never changes a funded deal.
- The "Sea legs" switch ships **off**. Turning it on is Ismail's decision. The legal and customs
  position for carrying parcels by sea has not been researched by this project.

#### 5.3.1 Initial crossings

Researched on 2026-11-11 from travel news and ferry booking listings for the 2026 summer and the
2026 to 2027 autumn and winter seasons. **The operators' own timetable pages were not opened**, so
this is a list of lines that are reported to run, not a schedule. A crossing only says "a ferry line
joins these two cities". The traveler's ticket, checked for each sea leg, is what proves a sailing.

Seeded **active**, most popular first:

| # | Crossing | Reported operators | Reported service |
| --- | --- | --- | --- |
| 1 | Marseille and Algiers | Algérie Ferries, Corsica Linea, Nouris Elbahr | Year-round; the most frequent line |
| 2 | Marseille and Béjaïa | Algérie Ferries, Corsica Linea | Mainly summer |
| 3 | Marseille and Skikda | Algérie Ferries, Corsica Linea | Summer, some autumn and winter |
| 4 | Marseille and Oran | Algérie Ferries, Nouris Elbahr | Summer, some autumn and winter |
| 5 | Marseille and Annaba | Algérie Ferries | Summer |
| 6 | Valencia and Mostaganem | Baleària | Year-round, up to 4 a week |
| 7 | Almería and Oran | Naviera Armas, Baleària | Year-round, up to 2 a week |
| 8 | Almería and Ghazaouet | Naviera Armas, Baleària | Year-round, up to 2 a week |
| 9 | Alicante and Algiers | Algérie Ferries, Nouris Elbahr | About 2 a month, more in summer |
| 10 | Valencia and Algiers | Baleària | Weekly |
| 11 | Valencia and Oran | Baleària | Weekly |
| 12 | Barcelona and Algiers | Baleària | Weekly |

Seeded **inactive**, because the evidence was a single source or the line is short-season. Staff can
activate one once it is confirmed: Sète and Algiers; Sète and Béjaïa; Sète and Oran; Sète and Skikda;
Sète and Annaba; Alicante and Oran; Barcelona and Oran.

Sources: ulysse.com (ferries Algeria summer 2026), observalgerie.com (Algérie Ferries autumn and
winter 2026 to 2027 bookings, and the Marseille summer line), algerie360.com (September 2026 sailing
changes), ferryhopper.com (Spain to Algeria routes). Lines and seasons change; the admin list is the
place to keep them current.

### 5.4 Distance and pricing for a sea leg

A sea leg's distance is the great-circle distance between the two port cities, the same method as a
flight leg. Pricing bands apply unchanged.

### 5.5 Capacity

- The traveler chooses capacity per leg. There is **no admin capacity cap**, for anyone.
- Weight in kg stays required and is the main capacity. Volume in litres and number of parcels are
  optional per leg.
- The 200 kg per-leg ceiling is replaced by a technical ceiling of 20,000 kg whose only job is to catch
  typos.
- Volume is enforced only when the leg declares a volume **and** the request has dimensions. When the
  leg declares a volume and the request has none, the match is allowed and shows a caveat.
- Parcel count is enforced when declared.
- Capacity is checked before an offer exists and again, under lock, when it is accepted. Overselling
  must stay impossible.

### 5.6 What the traveler accepts

A journey may refuse item categories and may refuse fragile items. The server enforces this in
matching. The default accepts everything the V1 safety rules allow.

### 5.7 Pause

A traveler can pause and resume their own active journey. Staff can pause any journey with a reason.
A paused journey is not discoverable and accepts no new offers. Funded deals continue normally.

## 6. Verification and proof

| | Every traveler |
| --- | --- |
| Identity | Existing ID check (KYC) |
| Flight leg | Ticket proof for each flight leg |
| Sea leg | Ticket or booking proof for each sea leg |
| Road leg | No proof |

- Nobody is exempt from a ticket proof. The exemption for verified professionals was parked on
  2026-11-13 with section 7.
- The single place that answers "is this leg's proof requirement satisfied" is one backend function.
  No other code may decide it by comparing a mode.

## 7. Professional transporters

**Parked on 2026-11-13. Not in this build.** The full text of this section (7.1 to 7.4) is in
`docs/parked/WASSLA_PROFESSIONAL_AND_COURIER_PLAN.md`.

## 8. Pricing

- Every traveler **may** set a price on a journey: a price per kg and a
  minimum per parcel, in EUR. Both or neither.
- For a given request, the **listed price** is the largest of: price per kg times the request's
  chargeable weight (rounded up to a cent); the traveler's minimum per parcel; Wassla's own minimum
  for that match.
- Find Travelers shows the listed price. The sender's offer is pre-filled with it and can be sent in
  one tap.
- The price stays negotiable. The sender may offer less. The traveler accepts, declines or counters.
  The existing offer flow is unchanged.
- **Wassla's admin-controlled minimum always applies.** An offer below it is refused exactly as today.
- The fee is added on top exactly as today. The sender sees the full total before paying.
- A traveler may change the price of an active journey. It affects only offers created afterwards.
  Existing offers and deals keep their snapshot.
- A journey with no price behaves exactly as today.

## 9. Manifest dashboard (verified professionals)

**Parked on 2026-11-13. Not in this build.** The full text of this section is in
`docs/parked/WASSLA_PROFESSIONAL_AND_COURIER_PLAN.md`.

## 10. Custody, courier handoff and final delivery

**Parked on 2026-11-13. Not in this build.** The full text of this section (10.1 to 10.4) is in
`docs/parked/WASSLA_PROFESSIONAL_AND_COURIER_PLAN.md`.

What holds in this build: **final delivery is the V1 rule and nothing else.** The traveler enters the
recipient's delivery code. Nobody else can confirm a delivery, and nothing in sections 11 or 12 marks
a parcel delivered.

## 11. Progress updates and reminders

- For every traveler. Per leg: "departed" and "arrived"; for a sea leg also "at the port".
- A report is a traveler's statement. It appears in the sender's tracking for every funded parcel on
  that leg, labelled "reported by the traveler". It changes no deal status and moves no money.
- **Reminders.** When a leg that carries at least one funded parcel passes its planned departure with
  no "departed" report, the app asks "Did you depart from {city}?". Same for arrival. The traveler
  answers in one tap from the notification, the bell inbox or Home. "Not yet" asks again later. The
  number of repeats and the delays are admin settings, with a small default.
- Reminders always appear in the bell inbox and on Home. Closed-app push uses Firebase (Android) and
  APNs through Firebase (iOS), as today. Nothing else depends on Firebase.

## 12. Problems and route changes

- A traveler or sender can report a problem on a parcel: sender unavailable, traveler did not come,
  recipient unavailable, parcel does not match, parcel damaged, trip cancelled or delayed (a flight,
  a drive or a crossing), customs delay, other. The three courier kinds were parked on 2026-11-13.
- A problem is recorded, the other party is notified, and serious kinds go to staff. Reporting a
  problem never changes a deal's status. Money consequences come only through the existing dispute and
  cancellation rules.
- **No-show reports (added 2026-11-12).** From the agreed pickup time until the pickup is confirmed,
  the traveler can report "the sender did not come" (kind: sender unavailable) and the sender can
  report "the traveler did not come". The button is on the delivery screen and needs one tap and an
  optional note. The other person is notified at once and can answer in chat or report their own side.
  Both kinds go to staff at once. Staff decide; only staff record a no-show, through the existing
  no-show action with its existing money rule. A report alone refunds nothing, cancels nothing and
  marks nobody. One open no-show report per person per delivery.
- **Route changes.** A traveler may change the times of an active journey. Wassla lists the affected
  parcels, notifies their senders and keeps the original schedule on record. A change that would miss a
  parcel's deadline, or move its arrival by more than the policy threshold, needs the sender's
  agreement; a sender who does not agree may cancel, and that cancellation is treated as caused by the
  traveler under the existing cancellation rules (confirmed by Ismail on 2026-11-11). Adding or
  removing stops on an active journey is not part of this build.

## 13. Admin

- **One verification inbox** with two tabs and counters: ID, and Tickets (flight and sea). One review
  screen for both: approve, ask for more, reject with a reason. (The Professional tab was parked on
  2026-11-13.)
- **No per-corridor or per-capability approval.** No per-route approval.
- **Switches** (versioned settings, changed with a reason): sea legs; discovery listings; discovery
  profiles; reminder timings; the daily "I can carry this" cap; traveler price bounds. Sea legs ship
  **off** and are turned on by Ismail. Everything else ships on. The switches once planned for courier
  handoff and professional applications do not exist in this build.
- **Controls:** pause any journey; hide any public profile; activate or deactivate a sea crossing.
- **Visibility:** for any deal, the progress reports, problems and route changes.
- Every staff action writes an audit entry with actor, target, before, after and reason. Staff cannot
  edit a delivery or payment state except through the same guarded transitions the product uses.
- Added on 2026-11-12: search by tracking number on every list (section 16); a queue of reported
  reviews (section 18); two-step sign-in and finance exports (section 19); the AI helper (section 20).

## 14. Experience standard

Every new screen and page must have a designed state for: loading, empty, error with retry, offline,
validation, permission denied, and "feature switched off". Every one must work in English, French and
Arabic, right-to-left, on a small phone, with the keyboard open, and without overlapping the bottom
navigation or the system gesture area. Actions a traveler performs standing next to a vehicle need
large targets and as little typing as possible. Server-authored reasons are shown; the client never
invents one.

## 15. Glossary for agents

| Product word | In the code |
| --- | --- |
| Route, trip | `trips.Journey` with ordered `trips.JourneyLeg` |
| Stop | A leg endpoint; position 0 is the first leg's origin, position k is leg k-1's destination |
| Parcel, shipment, booking | `deals.Deal` (after acceptance); `parcels.DeliveryRequest` (before) |
| Ticket proof | `trips.JourneyLegProof` |
| ID check | `kyc.KycSubmission`, owned at runtime by the Go kyc service |
| Wassla minimum price | `PricingQuote.minimum_reward_eur_cents` from `apps/matching/pricing.py` |
| Fee | `calculate_offer_economics` in `apps/core/business_settings.py` |
| Switches and settings | `core.BusinessSettingsVersion.policy`, a new `marketplace` section |
| Delivery confirmation | `deals.lifecycle.apply_delivery_confirmed` |

---

# Additions approved on 2026-11-12

Sections 16 to 20 were approved by Ismail on 2026-11-12, after a review of the app against the
"cahier des charges" of 11 November 2026. They follow the same rule as the rest of this document: a
rule here is a product decision. Section numbers 1 to 15 are unchanged so that existing references
stay valid.

## 16. Tracking number

- Every delivery request gets **one tracking number when it is created**: `WSL-` followed by 8
  characters taken from `23456789ABCDEFGHJKMNPQRSTVWXYZ` (no 0, 1, I, L, O or U, so it can be read
  aloud and typed without mistakes). Example: `WSL-7K3M9QXD`. It is random, unique, never changed and
  never reused.
- It is the parcel's number for its whole life. The request, its proposals, the delivery, its
  payments, refunds, payout, disputes and problems all show the same
  number. A request that reopens after a cancelled delivery keeps its number.
- It **replaces the `ST-<id>` reference** in every email, page and screen. No other human-facing
  reference for a parcel exists. Payment references stay what they are.
- Who sees it: the sender from creation; the traveler once a proposal exists between them; the
  recipient in the delivery-code email; staff everywhere. It is **never on a
  public discovery card** and never on the page a relative pays from.
- It identifies; it never authorises. Knowing a number opens nothing. There is no public "track by
  number" page in this build.
- When someone types it (admin search), case, the `WSL` prefix and the hyphen are optional.

## 17. Proposals that do not hang

### 17.1 Response deadline and reminder

- Every proposal and every counter-proposal has a **response deadline**: the time it was sent plus a
  number of hours set in policy (**default 6**, changed from 48 on 2026-11-13 for urgent delivery), or
  **the time the traveler is due to collect the parcel on that trip, if that comes first**. A proposal
  never outlives the pickup it is about. Both people see "Answer by {day, time}".
- The person who must answer gets **one reminder** before the deadline (**default 1 hour before**,
  changed from 12). No reminder is sent when the whole delay is shorter than that.
- At the deadline an unanswered proposal **expires**. It can no longer be accepted, refused or
  countered. Both people are told. The sender is free to propose to someone else.
- Expiry is neutral: nothing was reserved, no money moves, and it leaves no mark on either person.
- The server refuses an answer from the deadline on, whether or not its timer has run yet.
- Switch: response deadline on or off, with the two delays. It ships on. Off means new proposals have
  no deadline; proposals that already have one keep it.

### 17.2 Alert when a parcel fits a trip

- When a request becomes open, Wassla finds the published trips that are **really compatible**, with
  the existing engine and no second one, and tells each of those travelers once: "A parcel fits your
  trip {from} to {to}".
- The notification opens the request's public preview with that trip in focus, where the traveler can
  tap "I can carry this" (section 4.4). **The sender still proposes first.** The alert is not an offer
  and reserves nothing.
- It carries only what the public request card shows (section 4.2).
- Limits, all in policy: at most 30 travelers per request, best ranked first; at most 5 such alerts per
  traveler per day; never twice for the same request and trip. It follows the traveler's "marketplace
  activity" notification choice.
- A traveler who would also receive a route alert (section 4.4) for the same request receives only
  this one.
- Switch: on or off. It ships on.

## 18. Reviews, reports and moderation

- Wherever a card shows a person's rating (section 4.2), the viewer can open that person's **reviews**:
  for each rating that is already revealed, the score, the tags, the comment, the month and year, and
  whether a sender or a traveler wrote it. The author's name is not shown.
- The blind rule is unchanged: a rating appears only once both sides have rated or the rating period
  has ended. Ratings are still never edited or deleted.
- Anyone signed in who can read a review may **report it once**, with a reason (offensive, contains
  personal information, not about this delivery, untrue, other) and an optional note. The rated person
  can report from "My ratings".
- Staff see reported reviews in a queue and decide, with a reason, audited:
  - **dismiss** the report;
  - **hide the comment**: the score and tags still count; the text is replaced by "Comment removed by
    Wassla";
  - **remove the rating**: it leaves every public average, count and list.
  A decision can be reversed by staff.
- The author is never told who reported. The reporter sees only "received" then "reviewed".
- The rated person still sees a removed rating in "My ratings", marked "Removed by Wassla, not
  counted".

## 19. Admin security and exports

### 19.1 Two-step sign-in for staff

- Every staff account signs in with its password **and a 6-digit code from an authenticator app**.
  There is no SMS or email code.
- The first sign-in after this ships forces enrolment: a QR code and the same key as text, a code to
  confirm, then 10 one-time recovery codes shown once.
- Until the second step is done in the current session, no console page, no technical admin page and
  no staff API answers.
- Five wrong codes lock the second step for 15 minutes. A code cannot be used twice.
- A Super Admin can reset another admin's second step, with a reason, audited; that admin enrols again
  at their next sign-in. A server command does it for the last Super Admin.
- A **fresh code** (entered in the last 10 minutes) is asked before: creating an AI helper key,
  changing a staff role, resetting someone's second step.
- It cannot be switched off from the console. Only a server setting for local development relaxes it,
  and production refuses to start with that setting off.

### 19.2 Finance exports

- Finance can download, for a date range of at most 366 days: **Transactions** (one line per captured
  payment and one per refund), **Commissions** (one line per funded delivery: traveler reward, Wassla
  fee, sender total, refunds, fee kept) and **Payouts**.
- Amounts are the recorded ones, never recalculated: euros with two decimals and a currency column, and
  the dinar amount when the payment or payout used the Algerian rail.
- Each line carries the tracking number, the references, dates, statuses, whether the owner or a guest
  paid, and the people's internal ids and names. Never an email, a phone, an address, a bank detail or
  document data.
- A new permission, "export finance data", held by Finance and Super Admin. Every export is audited
  with its kind, range and number of lines.
- The format is CSV that opens correctly in Excel, with cells protected against spreadsheet formulas.

## 20. Admin AI helper

### 20.1 What it is

An admin can connect an AI assistant of their own (for example Claude Code or Antigravity) to
Wassla. The assistant reads a briefing of that admin's work, explains what needs doing and gives the
link to the console page for each item. It acts as that admin, with exactly that admin's rights at the
moment of each call: never more, and less where this section says so.

### 20.2 Keys

- Each admin has their own keys, created from the "AI helper" card on the console home page. A key is
  shown **once**; Wassla keeps only a scrambled form of it.
- **Read key:** expires **8 hours after it is created, even if it is in use**. The admin can create a
  new one at any time; that stops the previous one.
- **Change key:** created on demand, lasts **30 minutes**. The duration is a setting (5 to 60
  minutes).
- Creating either key needs a fresh two-step code (section 19.1).
- A key stops working at once when: it expires; the admin stops it; a new key of the same kind is
  created; the admin's account is deactivated or banned; the AI helper switch is turned off.
- Rights are read from the admin's role **on every call**. A role change applies to the next call.

### 20.3 What the helper can read

- The work list, queues and records the admin's role may open in the console.
- For each item: status, age, amounts, the tracking number and other references, the next step, and
  the console link.
- A person appears as first name, last initial and internal id, with a link to their console page.
- **Never sent to the helper, whatever the admin's role:** identity documents, tickets, business
  documents or any file or file link; document numbers; dates of birth; email addresses; phone numbers;
  exact addresses and coordinates; bank and payout details; pickup and delivery codes; any key, token
  or password; chat messages.
- Text written by users (a dispute description, a problem note, a parcel title, a review) is sent only
  on a record's detail, shortened, and always labelled as untrusted user text. It is never in the
  briefing.
- Work that needs eyes on a document (identity, ticket and payout-method reviews) is reported as a
  count with a link. The helper cannot decide it.

### 20.4 What the helper can change

- With a read key: nothing.
- With a change key, **directly**: add an internal note to a delivery, a dispute or a person;
  acknowledge a reported problem.
- With a change key, **prepared only**: the helper prepares the action; nothing happens until the admin
  opens the console, reads the summary and confirms. This covers: request a refund; change a dispute's
  status or resolve it; record a no-show; ban or unban a user; hide or show a public profile; pause or
  resume a journey; activate or deactivate a sea crossing; retry or
  resolve a background job; retry a payout; moderate a review.
- A prepared action is valid for 24 hours, is checked again when the admin confirms, and runs through
  the same guarded action as the console button, with the admin's rights at that moment.
- **Never through the helper, not even prepared:** staff accounts, roles and invitations; business
  settings and switches; AI helper keys; two-step settings; revealing bank details; any review that
  needs a document; the manual dinar payout steps.

### 20.5 The briefing

- One call returns the admin's work for now: each queue they may see, how many items wait, how long the
  oldest has waited, how urgent it is, what to do, and the console link. It also lists the queues that
  are clear, so "nothing to do" and "not checked" never look the same.
- The server decides the order and the urgency. The helper only words it.
- The console home page shows the same list, from the same code, for admins who use no AI.
- **How-to answers.** The helper can also ask Wassla "how does this admin do X?". Wassla answers with
  the tasks that admin's role allows, each as a few plain steps and the console link. The steps are
  written once on the server, so the assistant never makes up a procedure.

### 20.6 Safety and record

- Every change made or prepared through the helper is in the admin audit log as that admin, marked
  "via AI helper", with the key used.
- Every call is recorded (time, key, address, result) and kept 30 days. The admin sees their own
  recent calls on the AI helper page.
- A key is sent only in the request header, over HTTPS. Calls are rate limited per key.
- The helper's interface describes itself (what this admin may read and do, and the rules above), so
  the instructions given to the assistant stay short.

### 20.7 The skill

A short instruction file ("skill") tells the assistant how to use the helper. It must be simple enough
for a small, fast model to follow, and its answers simple enough that someone new to the console can
do the work. It never contains a key or a server address.

- The admin starts it by typing **`/wassla`** and pasting what the console's "Copy" button gives them:
  one line with the address and the key. That is the whole setup.
- **Nothing after the key:** the assistant gives the briefing.
- **Something after the key:** the assistant does that instead: answers "how do I ...?", explains one
  parcel, person or payment, or prepares a change.
- For the rest of the conversation the admin just asks; the key is not pasted again until it expires.
- Ismail asked for the skill to be drafted on 2026-11-12, before the helper exists. The draft is in
  `docs/admin-helper-skill/`. It is checked against the real helper, and proven, in the last package.

### 20.8 Switch

AI helper on or off, with the key durations, the validity of prepared actions and the rate limit. It
ships on. Turning it off stops every key at once.
