# Wassla: professional transporters and courier handoff (parked plan)

Status: **parked by Ismail on 2026-11-13. Not part of the current build. Nothing in this file may be
started without his explicit instruction.**

## 1. Why this file exists

On 2026-11-13 Ismail decided that Wassla is for fast delivery: urgent parcels, mostly on flights and
drives made the same day. Professional transporters are not needed for that. He plans to add them
later, on a subdomain of their own, and asked that the plan be kept in the repository instead of
being thrown away. He also agreed to park courier handoff (with the custody history built around it),
because handing a parcel to a local courier and waiting up to five days does not fit same-day
delivery.

This file holds, complete and word for word, everything the specification and the plan said about
those two features on the day they were parked, so that the work can be picked up without
re-deciding or re-designing it. The current build documents no longer contain these rules:

- `docs/WASSLA_DISCOVERY_PRO_SPEC.md` keeps the section numbers and says "parked" where a section
  moved here.
- `docs/WASSLA_DISCOVERY_PRO_PLAN.md` no longer lists the packages below.

The two documents as they stood before the change are in git at commit `50547be` on
`feature/discovery-professional-delivery`:

```
git show 50547be:docs/WASSLA_DISCOVERY_PRO_SPEC.md
git show 50547be:docs/WASSLA_DISCOVERY_PRO_PLAN.md
```

## 2. What is parked

| Package | What | Model | Effort | Depended on |
| --- | --- | --- | --- | --- |
| L6A (professional half) | Professional profile, business document check, ticket exemption, the "Professional" tab of the verification inbox, suspend and reinstate | Opus | high | L3A |
| L6B | Professional Mode in the app, Pro badge, public professional profile | Sonnet | medium | L6A |
| L7A | Manifest, backend projections | Sonnet | medium | L6A |
| L7B | Manifest dashboard in the app | Sonnet | high | L7A, L6B |
| L8A | Custody, courier handoff, recipient confirmation, backend and web pages | Opus | xhigh | L5A |
| L8B | Custody and handoff in the app | Sonnet | high | L8A, L7B |

None of these was started. No code for them exists.

## 3. Decisions Ismail already made for these features

They were locked on 2026-11-10 and 2026-11-11 and are part of the text below. They are listed here so
that nobody asks him again when the work resumes, unless the move to a subdomain changes one.

- Same account. A user can send, travel as an individual and operate professionally.
- A professional needs the existing ID check and **one** business document (auto-entrepreneur card,
  commercial register extract, or another business registration), reviewed once. After that they skip
  **every** per-trip ticket proof, flight and sea.
- Only a verified professional gets: the Pro badge and business name, the manifest dashboard, and the
  ticket exemption. Everything else is for every traveler.
- A professional's routes go live without per-route approval. The traveler still accepts or declines
  each booking. Staff can pause any route and suspend any professional.
- No capacity cap set by staff.
- Courier handoff is open to every traveler, behind a switch that ships off. A handoff is never a
  delivery, never starts the protection window and never pays out.
- The courier's cost is inside the traveler's price. Wassla charges no courier amount and pays no
  courier.
- After a handoff, delivery is confirmed by the recipient (with the delivery code), by the sender, or
  by staff after review. If nobody confirms within 5 days (a setting), staff review it.
- One verification inbox for staff, with a Professional tab beside ID and Tickets.

## 4. Where the code stood when this was parked

Integration branch `feature/discovery-professional-delivery` at `50547be`: packages L1A to L5B, L4C,
L11A and L11B merged. What these features would build on already exists:

- Multi-stop routes with flight, road and sea legs, capacity per leg, pause (L3A, L3B).
- One function for ticket proof, `backend/monolith/apps/trips/proofs.py`. The professional exemption
  changes `leg_proof_satisfied` and its SQL twin `proof_gap_exists` together and nothing else.
- Traveler pricing and the listed price (L4A, L4B).
- Tracking numbers (L11A, L11B). Plan rule 1.5.12 applies to every page and screen below.
- Progress reports and leg reminders (L5A, L5B).
- The marketplace policy reader, `backend/monolith/apps/core/marketplace_policy.py`. At `50547be` it
  still carried two unused sections, `courier_handoff` and `professional`. The current build removes
  them in package L6A (no dead switches). They must be added back by the package that needs them.

## 5. Before resuming: what will have changed

Read the current spec, plan and progress file first. In particular:

1. **The subdomain.** This text designs professionals inside the one mobile app. Ismail's later idea
   is a separate subdomain. Whether that means a web dashboard, a second app or the same app must be
   settled with him before any package below is issued.
2. **Verification inbox.** The current build ships it with two tabs (ID, Tickets) and one review
   screen. The Professional tab is added to it, not built again.
3. **Problems.** Problem reports now live in their own app, `apps.problems`, not in `apps.custody`.
   The courier kinds (`courier_refused`, `courier_lost`, "tracking reference invalid") are added to
   it when courier handoff returns.
4. **Deal list filters and reference search** (in L7A and L7B below) were parked with the manifest.
5. **Staff two-step sign-in** (L14) covers every staff page, new ones included.
6. **The AI helper** (L15, L16) has tests that force every new console page to have a how-to task or
   a "no task" entry, and every new console action to be in the action table or the "never" list. The
   rows that were planned for these features are in part B3 below.
7. **Reviews** (L13A, L13B) exist; a public professional profile links to the Reviews screen.
8. **Proposal deadline.** A proposal now expires after 6 hours or at the pickup time, whichever comes
   first (spec 17.1). A professional's "offers awaiting an answer" list should show that time.
9. **The delivery rule.** With courier handoff parked, only the traveler confirms delivery, by
   entering the recipient's code. The three extra confirmation paths in L8A are the only planned
   exception to plan rule 1.5.3 and need the same care as before (Opus, xhigh).

---

# Part A. Product rules, as they stood in the specification

Section numbers are the specification's own. Text is unchanged.

## 6. Verification and proof

| | Individual traveler | Verified professional |
| --- | --- | --- |
| Identity | Existing ID check (KYC) | Existing ID check (KYC) |
| Professional status | none | One business document, reviewed once |
| Flight leg | Ticket proof for each flight leg | No ticket proof |
| Sea leg | Ticket or booking proof for each sea leg | No ticket proof |
| Road leg | No proof | No proof |

- A verified professional skips **every** per-trip ticket proof, flight and sea. They need no extra
  document for sea.
- "Verified professional" is evaluated when a gate runs, not copied onto the journey. If a professional
  is suspended, or loses verified status, their journeys with flight or sea legs that have no approved
  ticket proof stop being discoverable and stop accepting offers until proofs are approved or the
  status returns. Funded deals are not touched.
- The single place that answers "is this leg's proof requirement satisfied" is one backend function.
  No other code may decide it by comparing a mode.

## 7. Professional transporters

### 7.1 Professional Mode

- Same account. A user can send, travel as an individual and operate professionally.
- To apply, the user enters business name, registration number, country of registration and business
  city, chooses the document type (auto-entrepreneur card, commercial register extract, other business
  registration) and uploads a photo of it. The existing ID check must also be approved.
- Statuses: not verified, verification pending, more information required, verified, suspended. A
  rejected application returns to not verified with the reason shown, and the user may apply again.

### 7.2 What only a verified professional gets

- The Pro badge and business name on cards, on their public profile and in tracking.
- The manifest dashboard (section 9).
- No per-trip ticket proof.

Everything else, including sea legs, multi-stop routes, pricing, courier handoff and progress updates,
is for every traveler.

### 7.3 Public professional profile

Business name, Pro badge, ID-verified flag, cities served (derived from their published routes, at
locality level), transport modes used, rating, completed deliveries, currently published routes. Never
the registration number, the document, or any address.

### 7.4 Routes

A professional's routes go live without per-route approval. The traveler still accepts or declines
each booking. Staff can pause any route afterwards.

## 9. Manifest dashboard (verified professionals)

Lives inside the existing navigation. Deliveries holds it; Home surfaces today's work.

- **Today** (on Home): what needs doing now. Collections due, parcels to deliver, offers waiting for an
  answer, courier handoffs awaiting confirmation, problems. Actions first, statistics never first.
- **Route manifest** (Deliveries, per journey): stops in order; at each stop the parcels to collect and
  to drop; per leg the occupied and free capacity; every parcel with its own status.
- **Stop view:** the list of parcels for one stop. The traveler works through it one parcel at a time.
  Each parcel is confirmed with its own code. There is no "confirm all".
- **Shipments** (Deliveries): every parcel across routes, with filters for route, pickup city,
  destination city, status, expected date and "has a problem", and a search by reference.
- **Earnings** (Profile, existing payout screens): per route, the accepted prices, amounts paid, fees,
  pending and completed payouts, refunds and disputed parcels. Read from the existing finance
  projections. No new money calculation.

## 10. Custody, courier handoff and final delivery

### 10.1 Custody

- Every parcel has its own append-only custody history: who holds it, since when, and how we know.
- Collection is recorded when the pickup code is confirmed, as today. Right after it the traveler may
  record the parcel's condition and photos. This is optional and never blocks the pickup.
- Each event states its source, and the source is shown to the sender: **confirmed by Wassla**,
  **reported by the traveler**, **reported by the courier**, **confirmed by the recipient**,
  **recorded by Wassla staff**.

### 10.2 Courier handoff

- Available to every traveler, behind the admin switch "Courier handoff", which ships **off**.
- Allowed only for a parcel the traveler has collected, with no open dispute.
- The traveler records: courier company, branch or location, tracking reference if any, the courier's
  representative if any, the time, and an optional receipt photo.
- Wassla creates a **one-time handoff link**, shown as a QR code. It is separate from the pickup code
  and the delivery code and is never reused as either.
- The courier opens the link with no account and confirms they received the parcel. The page shows the
  shipment reference and a short parcel description, and nothing private.
- Evidence grades, lowest to highest: reported by the traveler; receipt attached; confirmed by the
  courier on the link; reviewed by staff.
- With the same link the courier may later report "out for delivery", "delivered" or "delivery failed".
  These are courier reports. They are shown as such and decide nothing.
- The traveler may cancel a handoff the courier has not confirmed ("I took it back").
- The sender sees: **"Handed to a local courier, awaiting final delivery."**

### 10.3 What a handoff never does

It never marks the deal delivered. It never starts the protection window. It never releases a payout.
It never changes the deal's status. It is recorded beside the deal's state machine.

### 10.4 Final delivery

- **Personal delivery:** unchanged. The traveler enters the recipient's delivery code.
- **After a courier handoff**, delivery is confirmed by one of:
  1. the **recipient**, on their own web page, by entering the delivery code they received by email;
  2. the **sender**, in the app, stating the recipient has the parcel;
  3. **Wassla staff**, after review, with a reason and evidence.
- Each of these runs the same delivery-confirmation transition as today, so the 48-hour protection
  window, the arrival floor, disputes and payout behave identically.
- When a handoff is recorded, the recipient gets an email with a link to a tracking page. The page
  shows progress with no private data and offers "I received my parcel" and "I have a problem".
- **If nobody confirms within 5 days of the handoff**, the parcel goes to a staff review queue. Staff
  contact the recipient and the sender, then either confirm delivery with evidence or leave it for a
  dispute. The 5 days is an admin setting.

## Rules about these features that sat inside other sections of the specification

From section 1 ("What this adds"):

> 3. **Professional transporters.** A verified business on the same account, with a Pro badge, a business
>    profile, a manifest dashboard and no per-trip ticket proof.
> 4. **Custody and courier handoff.** Every parcel keeps its own custody history. A traveler may hand a
>    parcel to a local courier for the last part. A handoff is never a delivery and never pays out.

From section 2 (what this overrides in the V1 specification):

> | §6 and AGENTS.md: modes are FLIGHT and DRIVE; only flight legs need proof | Section 6: flight **and sea** legs need a ticket proof, except for a verified professional |

> | §17: only the traveler confirms delivery, by entering the recipient's code | Section 10: unchanged for personal delivery; after a courier handoff the recipient, the sender or staff confirm |

From section 4.2 (public cards):

> - **Trip card:** traveler first name, or business name for a verified professional; ID-verified flag;
>   Pro badge; rating and completed-delivery count; ordered stops at **locality level** with transport

> - **Profile card:** first name, or business name for a verified professional; ID-verified flag; Pro
>   badge; member since (month and year); rating and completed-delivery count; up to three "usual

From section 5.1:

> - A route is an ordered list of stops. Legs are the segments between consecutive stops. This is the
>   existing `Journey` and `JourneyLeg` model. A professional route is the same model, not a new one.

From section 8 (pricing):

> - Every traveler, individual or professional, **may** set a price on a journey: a price per kg and a
>   minimum per parcel, in EUR. Both or neither.

> - If a courier is used for the last part, **the courier's cost is included in the traveler's price**.
>   Wassla never charges a separate courier amount and never pays a courier.

From section 12 (problem kinds):

> - A traveler or sender can report a problem on a parcel: sender unavailable, traveler did not come,
>   recipient unavailable, parcel does not match, parcel damaged, crossing cancelled, customs delay,
>   courier refused the parcel, courier lost the parcel, tracking reference invalid, other.

From section 13 (admin):

> - **One verification inbox** with three tabs and counters: ID, Professional, Tickets (flight and sea).
>   One review screen for all three: approve, ask for more, reject with a reason.
> - **No per-corridor or per-capability approval.** No per-route approval.
> - **Switches** (versioned settings, changed with a reason): sea legs; courier handoff; discovery
>   listings; discovery profiles; professional applications; reminder timings; days before an
>   unconfirmed courier delivery is reviewed; the daily "I can carry this" cap; traveler price bounds.
>   Sea legs and courier handoff ship **off** and are turned on by Ismail. Everything else ships on.
> - **Controls:** pause any journey; suspend any professional; hide any public profile; activate or
>   deactivate a sea crossing; confirm a courier delivery after review.
> - **Visibility:** for any deal, the custody history, handoff record with evidence, progress reports,
>   problems and route changes.

From section 16 (tracking number):

> - It is the parcel's number for its whole life. The request, its proposals, the delivery, its
>   payments, refunds, payout, disputes, problems, custody history and courier handoff all show the same
>   number. A request that reopens after a cancelled delivery keeps its number.

> - A courier company's own tracking reference (section 10.2) is a different thing and is always
>   labelled "courier reference".

From section 20 (AI helper):

> - Work that needs eyes on a document (identity, ticket, professional, payout-method and courier
>   delivery reviews) is reported as a count with a link. The helper cannot decide it.

>   resume a journey; suspend or restore a professional; activate or deactivate a sea crossing; retry or

---

# Part B. Build plan, as it stood in the implementation plan

Text is unchanged. Package ids, models and effort are the plan's own. The plan's general rules
(sections 1.4 to 1.7 of `docs/WASSLA_DISCOVERY_PRO_PLAN.md`) apply to every package here.

## B1. Shared design decisions

From plan 1.5, rule 3:

> 3. **Beside the machine.** Custody, handoff, progress, problems and route changes never write
>    `Deal.status` and never call a lifecycle transition, with the single exception of the three
>    confirmed-delivery paths in L8A, which call the existing `apply_delivery_confirmed`.

From plan 2.1, the two policy sections:

```
  "courier_handoff": {"enabled": false, "unconfirmed_review_days": 5, "link_valid_days": 30},
  "professional":    {"applications_enabled": true},
```

Sea legs and courier handoff ship off; professional applications ship on.

From plan 2.2, the proof function took the professional fact:

> - `leg_proof_satisfied(leg, *, traveler_is_verified_professional) -> bool`

### 2.4 Verified professional

`apps.professionals.services.is_verified_professional(user, *, at=None) -> bool` is the only answer.
True when the user's `ProfessionalProfile.status` is `verified` and the user is not banned.

### 2.6 Custody is its own app

New Django app `apps.custody` owns custody events, courier handoffs, the recipient link and problems.
It may read deals and call `deals.lifecycle.record_event` for the timeline. It may not write a deal.

### 2.7 Durable timers

Reminders and the 5-day review use the existing `finance.ScheduledJob` through
`finance.services.schedule_job`, with new kinds and handlers registered in `apps/finance/jobs.py`
`HANDLERS`. Each handler re-reads state and does nothing if the work is no longer needed.

### 2.8 Pages for people without an account

The courier page and the recipient page follow `apps/finance/guest_web.py`: a server-rendered Django
page, the token in the path, only its hash stored, every failure rendering the same neutral page,
language from the browser with a one-tap switch, no private data.

## B2. Packages

### L6A. Professional profile, verification, admin inbox, proof skip (Opus, high effort)

**Schema.** New app `apps.professionals`.
- `ProfessionalProfile(user one to one, business_name, registration_number, registration_country,
  business_city place, document_kind, status: pending|needs_info|verified|rejected|suspended,
  staff_message, reviewed_by, reviewed_at, verified_at, suspended_at, suspension_reason)`.
- `ProfessionalDocument(profile, bucket, object_key, content_type, bytes, sha256, idempotency_key)`,
  stored and served exactly like `JourneyLegProof` (private bucket, same size and type limits,
  evidence viewed only through the audited staff redirect).
- `ProfessionalProfileEvent` (append-only status history with actor and reason).

**API.**
- `GET /api/professional/profile`, `PUT` (only while not verified and not suspended),
  `POST /api/professional/profile/document`, `POST /api/professional/profile/submit`.
- Submit needs an approved ID check and the applications switch on
  (`professional_applications_closed`).
- `/api/me` gains `professional: {status, business_name}`.
- Verified fields are locked for the user. Staff can correct them with a reason.
- Channel `professional.status_changed` and an email through the outbox, in the user's language.

**Proof skip.** `is_verified_professional` (2.4) feeds `apps/trips/proofs.py`. Matching querysets get
the fact as one annotation so query counts stay flat. The acceptance lock takes the professional
profile row as a witness whenever the skip is what satisfies a leg, exactly as it does for KYC.
Public payloads gain `traveler.professional: {business_name} | null` through one helper, and the match
reason `professional_verified`. The reason `flight_proof_approved` is emitted only when a real
approved proof exists. The offer `terms_snapshot` records whether the skip applied.

**Suspension.** `suspend_professional` and `reinstate_professional` (staff, reason, audit). On
suspension the user's journeys are re-evaluated lazily by the gates; nothing is rewritten, and funded
deals are untouched (spec 6).

**Admin: one verification inbox.**
- One "Verification" entry with the total waiting count. Three tabs with counters: ID, Professional,
  Tickets. The ID and Tickets tabs are the existing queues under a shared header.
- One review screen (`verification_detail.html`) for all three, with three decisions: approve, ask for
  more, reject. A reason is required for the last two.
- Professional: "ask for more" sets `needs_info` and shows the staff message to the user.
- ID and Tickets: "ask for more" records the existing rejected status with the reason and marks the
  audit entry and the notification `outcome: "resubmission_requested"`, so the user reads "we need a
  new upload" and can resubmit. The KYC status enum, owned by the Go service, is not changed.
- New permission codes `view_professional_profiles`, `review_professional_profiles`, added to the
  role matrix by a data migration that grants them wherever the KYC equivalents are held.
- Person page: a Professional section with status, history, suspend and reinstate.

**Tests.** The status machine. A verified professional publishes and is matched on flight and sea legs
with no proof; the same journey is refused the moment they are suspended; funded deals are unchanged.
Acceptance racing a suspension resolves to one consistent outcome. Privacy: registration number and
document never appear in any non-staff payload. Permissions and audit for every staff action.

### L6B. Professional Mode, mobile (Sonnet, medium effort)

- Profile gains "Professional Mode". Screens: what it is and what it needs; the form (business name,
  registration number, country, city with the place picker, document type, photo); pending;
  more-information-needed with the staff message and a re-upload; verified, with what it unlocks;
  suspended, with the reason and how to reach support; applications closed.
- A Pro badge component in the design system, used on trip cards, Find Travelers, the public profile,
  offers, deals and tracking.
- Public professional profile screen (spec 7.3).
- For a verified professional the ticket step is absent from publishing, with one line explaining why.
- States, RTL, upload progress and failure, photo retake.

### L7A. Manifest, backend projections (Sonnet, medium effort)

Read-only. Verified professionals only (`professional_required`), except the deal filters.

- `GET /api/pro/today`: offers awaiting an answer; collections due; parcels ready to deliver; counts
  by state. Later packages add their own sections here.
- `GET /api/journeys/<id>/manifest`: stops in order; at each, parcels to collect and to drop, each
  with reference, title, weight, status and the next action; per leg, used and free weight, volume
  and parcel slots.
- `GET /api/deals` gains filters `journey_id`, `pickup_place_id`, `delivery_place_id`, `status`,
  `expected_before`, and `q` (reference).
- `GET /api/pro/earnings?journey_id=`: totals read from existing deal terms snapshots and payout rows,
  grouped by payout state. Sums only. No new fee, FX or refund arithmetic.
- Fixed query counts, asserted.

### L7B. Manifest dashboard, mobile (Sonnet, high effort)

- Home: a "Today" section for verified professionals, above discovery, listing actions in the order a
  working day needs them.
- Deliveries: a "Routes" view; the route manifest; the stop view, where each parcel row opens the
  existing pickup or delivery screen and returns to the list. There is no "confirm all".
- Shipments: filters and reference search on the existing deliveries list.
- Profile: "Earnings by route" inside the existing payouts area.
- At widths of 840 dp and more, the manifest uses two panes. The last opened manifest is readable
  offline and marked as such; code entry needs the network and says so.

### L8A. Custody, courier handoff, recipient confirmation (Opus, xhigh effort)

**Schema.** App `apps.custody` (2.6).
- `CustodyEvent(deal, kind, source, actor, occurred_at, data)`, append-only. Kinds: `collected`,
  `condition_recorded`, `handed_to_courier`, `courier_accepted`, `handoff_cancelled`,
  `courier_out_for_delivery`, `courier_reported_delivered`, `courier_delivery_failed`, `delivered`.
  Sources as spec 10.1.
- `CollectionRecord(deal one to one, condition, note)` with private photos.
- `CourierHandoff(deal, status: reported|courier_confirmed|cancelled, courier_company, branch,
  representative, tracking_reference, handed_at, receipt, link_token_hash, link_expires_at,
  courier_name, courier_confirmed_at, confirm_ip, confirm_user_agent)`, at most one not-cancelled per
  deal.
- `RecipientLink(deal, token_hash, expires_at, revoked_at)`.
- `CustodyReview(deal, reason, status: open|resolved, resolution, resolved_by, resolved_reason)`.
- `HandoverAttempt.actor` becomes nullable and gains `channel` (`traveler_app` by default,
  `recipient_page`).
- New `DealEvent` kinds for the timeline. `Deal` gets no new field and no new status.

**Handoff.**
- `POST /api/deals/<id>/courier-handoff` by the deal's traveler. Needs: the switch on; pickup
  confirmed; delivery not confirmed; no active dispute. Returns the record and the one-time link.
- `POST /api/deals/<id>/courier-handoff/cancel` while not courier-confirmed.
- `GET /api/deals/<id>/custody`: current holder, events with sources, the handoff, and server-authored
  actions for the viewer.
- `POST /api/deals/<id>/collection-record` by the traveler, once, after pickup.
- Courier page `GET/POST /c/<token>` (2.8): confirm receipt with a name; afterwards report out for
  delivery, delivered, or delivery failed. Throttled per token and per address.

**Final delivery after a handoff.** Three functions in `apps/handover/services.py`, each taking the
deal lifecycle lock and then calling the existing `apply_delivery_confirmed`:
- `confirm_delivery_as_recipient(token, submitted_code)`: verifies the delivery code with the existing
  hashing, attempt recording and lockout, on channel `recipient_page`.
- `confirm_delivery_as_sender(deal_id, actor_id)`: the deal's sender, only while a handoff is active.
- `confirm_delivery_as_staff(deal_id, actor_id, reason, evidence_note)`: permission `manage_lifecycle`,
  only from an open `CustodyReview`, audited.
All three need the deal to accept a delivery exactly as today (`DELIVERY_READY` with a released code).
The delivery event records the method. The traveler-code path is unchanged.
- Recipient page `GET/POST /r/<token>` (2.8): progress without private data; "I received my parcel"
  with the code; "I have a problem", which notifies the sender and opens a `CustodyReview`.
- When a handoff is recorded: an email to the recipient with the page link, in their language, through
  the outbox; a notification to the sender.

**The 5-day rule.** `ScheduledJob` kind `courier_delivery_review` at handoff time plus the policy
days. The handler opens a `CustodyReview` when delivery is still unconfirmed, the handoff is not
cancelled and no dispute is active, and notifies the sender. Staff see a "Courier deliveries to
review" queue.

**Channels.** `deal.courier_handoff`, `deal.courier_update`, `deal.delivery_review`.

**Tests (all required).**
- A handoff, a courier confirmation and every courier report leave the `Deal` row, the ledger, the
  payout rows and the money-related scheduled jobs identical.
- Each of the three new confirmations produces the same deal fields, protection end and scheduled jobs
  as the traveler-code path at the same instant.
- Wrong codes on the recipient page lock out exactly as in the app. Expired, revoked and unknown
  tokens render the same page.
- The sender cannot confirm without a handoff. Staff cannot confirm without an open review,
  the permission and a reason.
- Recipient and sender confirming at the same moment yield one transition.
- An active dispute blocks handoff creation and all three confirmations.
- The review job is idempotent and does nothing once delivery is confirmed.
- Privacy tests for both pages and for the custody payload as seen by each party.
- The handoff link, pickup code and delivery code are different secrets and none accepts another.

**Done when.** The grep in L10 for writes to `Deal.status` finds none in `apps/custody`.

### L8B. Custody and handoff, mobile (Sonnet, high effort)

- Deal screen: a custody timeline where every line carries its source label.
- After pickup: an optional "Record condition" sheet with photos; skipping is one tap.
- Traveler: "Hand over to a local courier": a short form, then a full-screen QR code with the link,
  the waiting state, the confirmed state, and "I took it back".
- Sender: the banner "Handed to a local courier, awaiting final delivery", the courier's name and
  tracking reference, and "The recipient has it", which opens a confirmation dialog stating that it
  confirms delivery and starts the 48-hour protection period.
- Manifest: handoffs awaiting courier confirmation appear in Today.
- States including "courier handoff is not available" when the switch is off.

## B3. Pieces of other packages that belonged to these features

**L11A (merged).** The recipient and courier pages were to show the tracking number:

> - The delivery-code email to the recipient carries it. L8A's recipient and courier pages will show it
>   as "Wassla tracking number", with the courier's own reference labelled "courier reference".

**L9A.** Problems were a model of the custody app, with courier kinds:

> **Problems.** `custody.ShipmentProblem(deal, reported_by, kind, note, status: open|acknowledged|
> escalated|closed, closed_by, closed_reason)`. `POST` and `GET /api/deals/<id>/problems`. Kinds as spec
> 12. `parcel_damaged`, `parcel_mismatch`, `courier_lost` and `courier_refused` escalate to staff at
> once. The other party is notified on `deal.problem_reported`. A problem changes nothing on the deal;
> the existing dispute and cancellation actions remain the only paths with money consequences. Staff
> queue with acknowledge and close, each with a reason.

**L9B.** Reporting from the manifest:

> - "Report a problem" from the deal screen and from a manifest row; the problem list on the deal.

**L15.** The work list was to cover the queues these packages add:

> its own (1.5 rule 10). It must cover every queue the overview shows when this package starts,
> including those added by L6A, L8A, L9A and L13A. `oldest_waiting_since` and `severity` are new;

**L16.** The helper's action table had this row, and its "never" list named two reviews:

> | `professional.suspend`, `professional.restore` | prepared | as L6A | L6A suspend |

> two-step; revealing payout details; identity, ticket, professional, payout-method, payout-identity and
> courier-delivery reviews; manual dinar payout steps; payment reconcile and resolve; refund settlement.

**L10.** Final acceptance scenarios:

> 2. Scripted end-to-end scenarios in test mode: the Karim route from Ismail's brief as a verified
>    professional; an individual traveler with a sea leg and a ticket; discovery to an offer at the
>    listed price, payment, pickup, courier handoff, recipient confirmation, protection, payout; the
>    same with nobody confirming, through the 5-day review. (the list continues with scenarios that stay in the plan)

**Carry-over from L4B (board).** L6B was to add the Pro badge and the business name to the trip
cards that L4B built.
