# Phase 4 — handover, protection, disputes, cancellation, ratings and boosts

Engineering reference for the V1 delivery lifecycle after funding. The
authoritative product statement remains `docs/SHIPTRIP_V1_SPEC.md`; this
document explains how the specification's Phase 4 rules are implemented, why
each mechanism is shaped the way it is, and what a future change must not
break.

Phase 3 ended with money that could be collected, reconciled and refunded, and
a payout record that structurally could not be released. Phase 4 supplies the
key to that gate, and everything that has to be true before it turns.

---

## 1. Audit of the legacy handover code

There was already a handover implementation (`apps/verification`). It was
audited before anything was written, and the conclusion was that **none of it
is reusable for V1 Deals**. It stays in the tree, keeps serving its historical
rows, and remains refused for V1.

What the audit found:

| Aspect | Legacy `apps.verification` | Why it is unusable for V1 |
|---|---|---|
| Aggregate | `HandoverCode` hangs off a `Match` | V1 handover is a property of a funded `Deal`, not of a negotiation |
| Lock order | `verify_code` takes `HandoverCode` with `select_for_update`, **then** `Match` | Inverts the global order (Request → Match → … → Deal → handover). This is the residual finding recorded at the end of Phase 3B |
| Code material | Plaintext published on the Redis bus in `handover.code_issued` with `targets=[sender_id, traveler_id]` | The **traveler receives the delivery code**, directly violating the hard invariant. `redis_bus.publish_after_commit` also writes a `Notification` row per target, so the plaintext lands in the database inbox |
| Delivery-code timing | `_advance_match_to_in_transit` issues the delivery code immediately on pickup | No 30-minute safety buffer exists at all |
| Entropy | 6 numeric digits (≈20 bits) | Below the Phase 4 floor; the attempt cap becomes the only real defence |
| Recipient | No recipient concept | The delivery code has nobody to be sent to |
| Money | Calls `release_hold_to_payee` on the legacy DZD wallet at delivery | No protection window, no dispute freeze, wrong currency, wrong ledger |
| Authorization | `get_active_code` filters on `issued_to=viewer`, but the surrounding view docstring claims "traveler sees the delivery code" | The filter is correct today by accident of who codes are issued to; the intent recorded in the code is wrong |

Reused: nothing but the *ideas* — hash at rest, attempt caps, one-time
semantics. Every line of Phase 4 handover is new, lives in `apps/handover`, and
enters through `lock_deal_lifecycle`.

The V1 refusal in `apps/verification/views.py` (409
`v1_deal_handover_not_available` for any Match carrying a `journey_id`) is
retained. Phase 4 does not reactivate the legacy path, and no migration moves
legacy rows into the new tables.

---

## 2. Deal lifecycle

`apps/deals/lifecycle.py` is the state machine. Nothing outside it writes a
lifecycle field on a `Deal`.

```
offer_accepted → payment_required → funded → pickup_ready → picked_up
  → in_transit → delivery_ready → delivery_confirmed → protection_window
  → completed
```

Side and terminal states: `cancelled`, `expired`, `payment_failed`, `disputed`,
`refunded`, `partially_refunded`.

| Transition | Function | Trigger |
|---|---|---|
| → `funded` | `apps.deals.services.fund_deal` | balance `PaymentOrder` fully covered |
| `funded` → `pickup_ready` | `apply_pickup_ready` | recipient recorded |
| `pickup_ready` → `picked_up` → `in_transit` | `apply_pickup_confirmed` | verified pickup code |
| `in_transit` → `delivery_ready` | `apply_delivery_code_released` | stored safety-buffer instant reached |
| `delivery_ready` → `delivery_confirmed` → `protection_window` | `apply_delivery_confirmed` | verified delivery code |
| `protection_window` → `completed` | `apply_completed` | protection expired, no dispute |
| any → `disputed` | `apply_disputed` | dispute opened |
| `disputed` → terminal | `apply_dispute_resolved` | admin resolution |

Three properties hold for every one of them:

* **Callers arrive holding the lock.** Each `apply_*` takes an already-locked
  `LockedLifecycleAggregate`. Acquiring locks inside the transition would let
  two callers take them in two orders.
* **Transitions are idempotent.** A repeat returns `changed=False` rather than
  appending a second event, moving a deadline or re-arming a job.
* **Deadlines come from the Deal's frozen policy**, never from live settings.

### Policy snapshotting

`Deal.lifecycle_policy` is written once, by `snapshot_on_funding`, inside the
funding transaction. It freezes the delivery-code buffer, the protection window,
the rating window, the handover attempt budget and the whole cancellation
policy. `Deal.agreed_pickup_at` is frozen at the same moment, resolved from
(in order) the server's interpolated pickup instant in the compatibility
snapshot, the sender's declared ready-window start, or the matched start leg's
departure — all server-computed.

A settings revision published tomorrow therefore cannot shorten today's safety
buffer, move today's protection deadline, or change a cancellation penalty a
party has already been quoted. A Deal funded before Phase 4 shipped has an empty
snapshot and falls back to the documented defaults (30 minutes, 48 hours,
14 days), which is the conservative reading rather than "no rules apply".

---

## 3. Handover codes

### Material and storage

`apps/handover/codes.py`. Three operations, three derived keys, all built from
`hmac`/`hashlib`/`secrets` — no new dependency.

* **Generation.** `secrets.choice` over a 32-symbol Crockford base32 alphabet
  with `I`, `L`, `O`, `U` removed. At the seeded length of 8 that is `32**8 =
  2**40`. Readability is a security property here: a code two strangers cannot
  read to each other is a code they work around.
* **Verification.** `code_hash = HMAC-SHA256(pepper, "deal_id:kind:code")`,
  compared with `hmac.compare_digest`. Binding the Deal id and the kind means a
  hash lifted from one row cannot be replayed against another, and a pickup
  hash can never satisfy a delivery submission. The pepper is derived from
  `HANDOVER_CODE_SECRET`, an environment secret, so a stolen database dump
  cannot be brute-forced offline.
* **Sealing.** `sealed_code` is encrypt-then-MAC of the plaintext under a
  *different* derived key, with `(deal_id, kind)` as authenticated associated
  data. Layout: version byte, 16-byte nonce, ciphertext, 32-byte tag.

### Why a recoverable copy exists at all — an explicit security decision

The specification requires that the sender can **see** the pickup code after
funding and **reveal** the delivery code after the buffer. A hash cannot answer
that, and rotating on every view would invalidate a code the traveler has
already been given, or a delivery code the recipient already holds by email.

So the plaintext is stored **sealed, never plain**, and:

* verification never decrypts and revealing never compares — different keys,
  different call paths;
* unsealing has exactly two callers, the sender reveal/rotate path and the
  recipient-notification renderer, both authorization- and state-gated;
* every unseal writes a `HandoverCodeAccess` audit row naming who opened what
  and why, and never the value;
* the traveler has no unsealing path at all;
* production refuses to boot unless `HANDOVER_CODE_SECRET` is at least 32
  characters and differs from `DJANGO_SECRET_KEY`, so compromising Django
  session signing is not the same event as compromising parcel handover.

### The traveler and the delivery code

This is the invariant the whole module is arranged around. It holds at four
independent layers:

1. **Service.** `reveal_code` refuses any actor who is not `deal.sender_id`,
   before the seal is opened. There is no argument that yields a code to the
   traveler.
2. **API.** `apps/handover/urls.py` exposes exactly two reveal routes and two
   rotate routes; all four call the sender-gated service. The traveler's only
   code endpoints are the two submit routes, which take a candidate and return
   an outcome.
3. **Serialization.** `RevealedCodeSerializer` is used only on those four
   sender responses. `handover_state` — the projection both parties read, and
   the block embedded in the Deal detail payload — contains no code material and
   states `"traveler_can_view_delivery_code": false` as an assertable contract.
4. **Everything else.** Nothing writes code material to a `DealEvent` payload, a
   `Notification` row, a `PublishedEvent`, a log line, or the Django admin
   (`code_hash` and `sealed_code` are excluded from every admin surface). The
   Deal timeline projection in `apps/deals/timeline.py` is a payload-key
   *allowlist*, so a future event kind that carried a secret would be invisible
   to a party by default.

### The 30-minute buffer

Locked rule: the delivery code is unavailable to everybody for exactly the
snapshotted buffer after pickup confirmation.

`apply_pickup_confirmed` stores `delivery_code_available_at =
pickup_confirmed_at + buffer`. The delivery code row is created immediately, in
status `buffered`, with `available_at` copied onto it and a check constraint
(`handover_buffered_requires_available_at`) refusing a buffered row without one.

Generating the material early and gating on state is deliberate: the release is
then a state change on an existing row, rather than a creation that could
partially fail thirty minutes later with the parcel already delivered.

During the window: `reveal_code` refuses with `delivery_code_buffer_open`,
`rotate_code` refuses for the same reason (rotating inside the buffer would be a
way to ask for a code early), the recipient's message does not exist, and the
traveler is refused as always.

`release_delivery_code` is the only transition out. It compares `at` against the
**stored** instant under the Deal row lock, so a job that fires early, a clock
that drifts, or a `run_at` that was moved forward cannot shorten the window. It
promotes the code, calls `apply_delivery_code_released`, and arms the recipient
notification **in the same transaction** — so "the code was revealed early" and
"the recipient was emailed early" are the same impossible event rather than two
separate risks.

A sender who opens the app after the window but before the worker has run
triggers the identical release inline, so a stopped worker delays nothing except
the email.

### Attempts, rate limiting and replay

Per code: `failed_attempts` up to `max_failed_attempts` (seed 5) triggers a
timed lockout; `max_lockouts` (seed 3) locks the code permanently, which puts a
human back in the loop via sender rotation rather than letting a guesser wait out
one more lockout. Per Deal and kind: a sliding window over the append-only
`HandoverAttempt` table (seed: 12 attempts per hour) — a table rather than a
counter, because a counter cannot answer "how many attempts in the last hour"
after a process restart. At the transport layer, both submit endpoints carry a
`handover_submit` scoped throttle.

Every rejection that depends on the submitted value collapses into one uniform
message and one code (`handover_code_invalid`). Nothing reports how close a
guess was, and the serializer deliberately does not validate the code's shape —
an early format check would be a free oracle that costs the guesser no attempt.

Replay is closed by consumption under the lock: a success sets the row `used`
inside the same transaction as the Deal transition, so a retried request, a
double tap or a second device finds `code_not_available` rather than running the
side effects twice.

---

## 4. Recipient

`DealRecipient` (`apps/deals/recipient.py`) — required name and email, optional
phone and delivery note. Collected after funding, and recording it is the gate
into `pickup_ready`: the delivery-code notification has nowhere to go without an
address, and discovering that thirty minutes after the parcel has left the
sender's hands is too late to fix.

Only the sender may record or change it, and only before pickup is confirmed —
after that, a silent edit would be a way to redirect a parcel already in transit.
Each write bumps a revision and appends a timeline event carrying the revision
number and nothing else; a diff of a third party's contact details is not
something the traveler or an admin browsing a timeline needs.

Projection (`recipient_projection`): the sender and staff see the full record;
the traveler sees `{"recorded": true}` before pickup and name plus delivery note
after it, never the email — that address is how the platform reaches the
recipient with a code the traveler must not have; anybody else gets `None`, so
the field is absent rather than present-and-empty. The recipient appears in no
matching, discovery, public Journey or guest-payer surface.

---

## 5. Recipient delivery-code notification

The existing email path (`redis_bus.enqueue_email_after_commit`) is a Redis
stream. A stream is not a promise: a restart can drop it, and the only durable
trace is a `PublishedEvent` row holding a payload *hash*. That is acceptable for
a verification OTP a user can request again. It is not acceptable for a delivery
code sent to somebody who has no account and no way to ask for a resend.

So Phase 4 adds `OutboundMessage` (`apps/notifications/`), a durable
Postgres-backed obligation, and the stream becomes only how the obligation is
carried.

**The code is not in the row.** `context` holds what a template needs — a name,
a Deal reference — and never a secret. The code is named by
`secret_ref = "handover_code:<id>"` and resolved from the sealed row at render
time, inside the dispatching process. The plaintext therefore never exists in
the notification table, the in-app inbox, or the published-event audit.

Delivery semantics: the row is the single obligation, keyed for idempotency
(`recipient_delivery_code:<deal>:<code>`), armed in the same transaction as the
release, and driven by a durable `outbound_message` `ScheduledJob`. Dispatch is
claim → carry → mark, so a crash between the last two re-carries an *identical*
body rather than losing it: exactly-once logically, at-least-once physically,
with retries idempotent because the body is a pure function of the row.

Rotating a delivery code arms a new message under a new key, so a recipient who
lost the first email is not left holding a code that no longer works.

Sender.net production configuration remains a later phase. The provider boundary
is unchanged: Django renders, the Go email service transports.

---

## 6. Protection window and payout eligibility

`apply_delivery_confirmed` stores `protection_ends_at = delivery_confirmed_at +
protection_window` from the frozen snapshot (seed 48 hours) and arms a durable
`protection_expiry` job.

`apps/finance/payout_release.py::evaluate_payout_release` is the **only** normal
path out of `Payout.Status.NOT_ELIGIBLE`. Four conditions, checked together
under one lock:

1. delivery was confirmed by a verified delivery code,
2. the stored `protection_ends_at` has passed,
3. no dispute on the Deal is active,
4. the money reconciles — balance obligation paid, nothing refunded, no refund
   in flight.

It is safe to call as often as anything likes: a duplicate job, a worker
restart and an operator re-check all converge. It never pays anybody;
`complete_manual_payout` and the payout rails still have to walk through the
door it opens, with their own evidence requirements, and Phase 3's
`fin_payout_release_requires_eligibility` check constraint still refuses any
released state without an eligibility instant.

On a clean expiry the Deal is completed. The payout continues on its own
lifecycle and each later state change is recorded on the Deal timeline as a
`payout_status_changed` event. **This is a deliberate product decision:**
holding the Deal open until an operator's bank transfer clears would misreport a
finished delivery as unfinished for days, and V1 payouts are manual by default.

### What a settlement may allocate

`read_deal_money` reports two figures, and the difference between them is the
one that matters: `collected_eur_cents` is everything the platform ever took,
and `settleable_eur_cents` is what it still has — collected minus anything
already paid out to the traveler.

**Every bound in `plan_settlement` is against `settleable`, not `collected`.**
A settlement computed from `collected` after a payout has settled sends the same
euro to two people, and each half looks correct in isolation: the payout was
legitimately released by a dispute resolution, and the refund was legitimately
computed from what the Deal took in. The Phase 4 review reproduced exactly that
end to end through shipped endpoints, and it left the ledger asserting that the
traveler owed the platform the reward back.

Two walls stand against it now. `plan_settlement` refuses a refund larger than
what is still held and floors the traveler's share at what they were already
sent, so a decision the platform cannot fund is an explicit refusal
(`settlement_refund_out_of_range`, `settlement_exceeds_paid_out`) rather than an
approximation. And a party cannot open a second dispute once one has been
resolved (`dispute_already_resolved`) — re-litigation goes to support, which is
where a claw-back has to be handled anyway. An administrator may still open one
for the record, and the settlement bounds hold for them too.

The remaining honest limit: a payout that is already **paid** can coexist with a
dispute an administrator opened afterwards. The money has left and no code can
recall it; the dispute records `payout_already_settled`, and a settlement can
allocate only what is left. So the invariant the platform actually guarantees is:
*no active dispute coexists with a payout that is eligible, scheduled or
processing, and no settlement can allocate money that has already gone.*

### The protection-expiry vs dispute race

Two writers compete for the same money at the same instant. Both enter through
`lock_deal_lifecycle`, which takes the Deal row **before** disputes and before
the payout. Whichever transaction commits first, the second blocks on the Deal
row and then reads the first's committed state. So:

* dispute first → the timer sees an active dispute, freezes, returns
  `frozen_by_dispute`;
* timer first → the payout becomes `eligible` and the Deal completes; a dispute
  arriving afterwards through the party route is already outside its window and
  is refused, and an admin-opened one pulls the payout straight back to
  `frozen`.

"The timer released the payout because it read stale dispute state" is not a
reachable interleaving. `Payout.Status.FROZEN` was added for this: it sits
outside the constraint's released set, so freezing can never leave a payout in a
state the database considers releasable.

---

## 7. Disputes

`Dispute` is a first-class record, not a flag: it needs its own state machine,
its own audit trail, an evidence bundle captured before anybody can tidy
anything up, and a resolution that is idempotent under two administrators
clicking at once.

Statuses: `open`, `awaiting_evidence`, `under_review`, `resolved`, `closed`.
The first three are `ACTIVE_STATUSES` — while a row is in one of them the payout
stays frozen. `disputes_one_active_per_deal` (a partial unique index) makes two
rival active disputes impossible; a retrying client resolves to the existing row.

**Window.** A party may open a dispute while the parcel is in carriage — this is
the "no normal cancellation after pickup, open a dispute instead" path — or
after delivery confirmation while `now < protection_ends_at`. Before pickup the
answer is cancellation, not a dispute. After the protection deadline a party is
refused; only an admin may open one, and if the payout was already paid the row
records `payout_already_settled` rather than pretending the money is still here.

**Evidence bundle.** Captured at open time as immutable *references*: the Deal
timeline, offer history, terms and pricing snapshots, payment/refund/payout ids
and statuses, handover code and attempt events, chat reference, journey and
flight-proof references, the delivery-request snapshot, and the no-show record.
It never contains a code in any form, recipient contact details, or exact
private location labels — a secret in the bundle would be a secret in every
admin export forever.

**User evidence.** Text, photo or video. Media is validated against the policy's
size cap, item cap and content-type allowlist, and the declared type is verified
against the actual bytes (Pillow for images; container signature for video).
Files go to a private bucket; access is always a short-lived signed URL issued
after an authorization check, never a bucket path.

### Resolution and the money

Three outcomes: full sender refund, full traveler payout, partial split. All
three run through `apps/finance/settlement.py`, which exists so that a dispute
resolution and a late cancellation cannot disagree about what "reconciles"
means:

> every cent the platform collected is returned to the sender, paid to the
> traveler, or kept as commission. Nothing is created and nothing disappears.

That is checked three times: `plan_settlement` refuses a split that does not sum
to the collected total; `ledger.post` refuses a transaction whose entries do not
sum to zero; and `disputes_resolution_reconciles` refuses to store a resolution
whose three amounts disagree with the total.

Order of operations in `apply_settlement` is fixed:

1. post one compensating ledger transaction that undoes the funded split and
   recognises the resolved one (so the ledger never briefly shows a refund
   against funds still recognised as the traveler's),
2. release **only** the posting-deposit credit that is about to be refunded —
   releasing all of it would leave a phantom deposit liability,
3. raise refunds, balance order first and only then the deposit,
4. set the payout to what the traveler is actually owed.

**Partial split.** The administrator states the sender's refund. What remains is
split `proportional` (the ratio the parties originally agreed; the traveler
takes the floor and the platform absorbs the rounding remainder, so integers sum
exactly) or `platform_waives` (traveler made whole first, platform absorbs the
shortfall — the mode a late-cancellation compensation uses). An explicit
traveler amount overrides the mode, and a negative remainder is refused rather
than turned into a platform loss nobody approved.

**Idempotency.** Every write is keyed on `dispute_resolution:<id>`: the ledger
correction, the deposit-credit release and each refund. Two administrators
serialize on the Dispute row lock; the loser re-reads a resolved row and returns
it unchanged. Exactly one economic resolution wins.

**The reallocation reads the books, not the price.** `_post_reallocation`
derives its deltas from the ledger's current position for the Deal rather than
from the terms frozen at acceptance. Those agree on a first settlement and
diverge on every one after it — computed from the frozen price, a second
settlement re-releases liabilities the first already released and leaves the
books claiming a pool larger than anything ever collected. Recomputing rather
than incrementing is the discipline `_recompute_order_money` already applies to
an order's cash.

**A resolution retires the Deal's live handover codes**, exactly as a
cancellation does. Without it, a sender whose Deal had just been refunded could
still rotate the delivery code and have the platform email a third party a code
for a delivery that no longer exists.

---

## 8. Cancellation and no-show

`apps/deals/cancellation.py`. All amounts computed server-side from the Deal's
frozen policy.

| When | Who | Outcome |
|---|---|---|
| Before an accepted offer | sender | full deposit refund (Phase 3) |
| After acceptance, before funding | either | cancel, release capacity, no payout (Phase 2/3) |
| After funding, before pickup | traveler | full sender refund |
| After funding, > cutoff before agreed pickup | sender | full refund |
| After funding, < cutoff before agreed pickup | sender | traveler compensation = `min(cap, ceil(reward × bps / 10 000))`, remainder refunded |
| After pickup | either | refused — `cancellation_not_available_after_pickup`; use a dispute |

Seeds: cutoff 24 h, compensation 1 000 bps (10 %), cap €15, platform fee on a
late cancellation 0 bps. All admin-configurable and all snapshotted onto the
Deal at funding.

`GET /api/deals/<id>/cancellation` prices a cancellation without performing one,
so the confirmation screen shows a real, server-computed number.
`POST /api/deals/<id>/cancel` then applies whichever policy the Deal's state
implies — one endpoint, because the client must not be the party deciding which
policy applies.

The whole cancellation commits together: capacity release, Deal transition,
refunds, compensation, live-code cancellation and timeline. There is no window
in which capacity is free but money is unresolved, or the sender is refunded but
the leg is still reserved. Racing a pickup confirmation is resolved by the Deal
row lock: whichever commits first wins outright, and the loser is refused
against committed state.

**No-show** is admin-reviewed at launch — no automated risk scoring. What Phase 4
owns is the record (who decided, when, about whom) and the one financial
consequence the specification names: a verified traveler no-show refunds the
sender in full, through the same settlement engine. `deals_no_show_requires_actor`
refuses a no-show row without an actor and a timestamp.

---

## 9. Ratings

Bidirectional, one per side per Deal, 1–5 with optional policy-constrained tags
and a comment, inside a 14-day review window frozen onto the Deal.

Immutable once submitted, and that is what makes the blind window mean anything:
if a rating could be edited after the other side became visible, "blind" would
describe only the first draft. The model refuses any field change except the
reveal flag.

Visibility is **computed as well as stored**. `revealed_at` is stamped by a
durable `rating_reveal` job so the state is queryable and auditable, and the
serializers independently recompute the same predicate — both sides submitted,
or the window closed — so a worker that has not run cannot keep a rating hidden
past its window and an early one cannot expose it. The rater always sees their
own; the timeline records that a rating was submitted and by which side, never
the score.

Only the two Deal parties may rate. A guest payer, the recipient and any
unrelated user are refused, and the rater/ratee are derived from the Deal rather
than from the request body.

---

## 10. Paid boosts

Phase 2 built the ranking hook; Phase 3 reserved `PaymentOrder.Purpose.BOOST`.
Phase 4 joins them.

> A boost changes where a **compatible** request appears in a list. It never
> makes an incompatible request compatible.

That is structural, not a convention: `apps/matching/ranking.py` raises if asked
to rank a candidate that failed hard compatibility, the boost bonus is added to
the ranking score afterwards and capped, and the only columns a purchase ever
writes on a `DeliveryRequest` are `ranking_boost_weight` and
`ranking_boost_expires_at`. Nothing in the boost path touches KYC, capacity,
route eligibility, timing, safety or verification.

Flow: only the request's own sender may buy, only for an active V1 request,
only from an admin-configured package whose price and duration are snapshotted
onto the purchase. The obligation is an ordinary `PaymentOrder` driven by the
existing checkout — there is no second payment system. Activation happens only
when the authoritative payment reconciles (`reconcile_attempt` →
`activate_paid_boost`), never on a client's return from a checkout page.

Failure paths are explicit: a failed checkout leaves the purchase
`pending_payment`; a duplicate success is idempotent; a payment that lands after
the request is no longer boostable marks the purchase `unusable` and **refunds
it** rather than stranding the funds. Expiry is a durable `boost_expiry` job,
and the ranking hook independently checks `ranking_boost_expires_at`, so ranking
is correct even if the job has not run. Purchase history is never deleted.

`BoostPurchase` sits in the lock order with the request graph it belongs to,
because a boost never involves a Deal — that placement is what lets the boost
flow and every payment flow approach the shared `PaymentOrder` from the same
direction.

---

## 11. Durable obligations

Every delayed Phase 4 obligation is a `ScheduledJob` row in PostgreSQL. Redis
may accelerate; it is never the record.

| Kind | Payload | Armed by |
|---|---|---|
| `delivery_code_release` | `deal_id` | pickup confirmation |
| `protection_expiry` | `deal_id` | delivery confirmation |
| `rating_reveal` | `deal_id` | delivery confirmation |
| `boost_expiry` | `boost_purchase_id` | boost activation |
| `outbound_message` | `message_id` | `enqueue_message` |
| `payout_release_check` | `payout_id` | payout creation (Phase 3), now a real gate |

Each handler is idempotent in its own right, refuses to act early (the stored
instant is the authority, not the schedule) by **raising** so the job is retried
rather than retired, and is armed in the same transaction as the fact that made
it true.

That last point is not a formality. `payout_release_check` is armed at funding,
when nobody yet knows when delivery will be confirmed, so its first fire lands
48 hours later — usually while the parcel is still moving. Returning a string
there marked the obligation discharged and consumed the safety net before it
could ever help, which is exactly the situation it exists for.

`dispatch_due_messages` is the same kind of backstop for the outbox: a message
whose job was lost or exhausted still has to go out, and only a sweep that reads
`next_attempt_at` can notice. It runs in the finance worker loop alongside
`requeue_stuck_jobs` — a documented safety net with no caller is not a safety
net.

---

## 12. Phase 4 lock order

Declared in `apps/core/financial_locks.py`:

```
DeliveryRequest/ParcelRequest
→ Match (ascending id)
→ Offer (ascending id)
→ BoostPurchase (ascending id)
→ Journey
→ JourneyLeg (position, id)
→ eligibility witnesses (acceptance only)
→ Deal
→ DealLegAllocation (journey leg, id)
→ DealRecipient
→ DealHandoverCode (ascending id)
→ Dispute (ascending id)
→ Rating (ascending id)
→ PaymentOrder (ascending id)
→ PaymentAttempt (ascending id)
→ PaymentProviderEvent
→ PaymentRefund (ascending id)
→ Payout
→ append-only ledger rows
→ ScheduledJob
```

Everything Phase 4 adds sits between `Deal` and `PaymentOrder`, except
`BoostPurchase`, which sits with its request graph and never touches a Deal.
That single placement decision is what keeps the new edges acyclic.

`lock_deal_lifecycle(deal_id)` takes the whole set — Deal aggregate, recipient,
codes, disputes, ratings — even the parts a given transition does not need, so
the ordering is a property of one function rather than of every caller's
discipline. Every Phase 4 writer starts there. `lock_deal_payment_orders` then
reaches the balance order and the credited posting deposit in ascending id.

Provider-event and `ScheduledJob` claims remain deliberately short transactions
that commit before acquiring business rows, so they are never a reverse edge.

**The legacy `HandoverCode`-before-`Match` ordering is not reintroduced.** It
survives only in `apps/verification`, which is refused for V1 Deals.

---

## 13. API surface

Server timestamps are authoritative everywhere; the client renders countdowns
and never computes a deadline or an amount.

**Deal**
- `GET /api/deals` — lean list (bounded query count)
- `GET /api/deals/<id>` — full state: every lifecycle instant, terms, timeline,
  recipient projection, handover state, protection/payout, dispute summary,
  ratings, cancellation availability, no-show
- `GET|PUT /api/deals/<id>/recipient`
- `GET /api/deals/<id>/cancellation` — priced quote
- `POST /api/deals/<id>/cancel`

**Handover**
- `GET /api/deals/<id>/handover` — both parties, no code material
- `GET /api/deals/<id>/handover/pickup-code` — sender
- `POST /api/deals/<id>/handover/pickup-code/rotate` — sender
- `GET /api/deals/<id>/handover/delivery-code` — sender, after the buffer
- `POST /api/deals/<id>/handover/delivery-code/rotate` — sender, after the buffer
- `POST /api/deals/<id>/handover/pickup` — traveler submits
- `POST /api/deals/<id>/handover/delivery` — traveler submits

**Disputes**
- `POST|GET /api/deals/<id>/disputes`, `GET /api/disputes/<id>`
- `POST /api/disputes/<id>/evidence`, `GET /api/disputes/<id>/evidence/<eid>/url`
- `GET /api/admin/disputes`, `POST /api/admin/disputes/<id>/status`,
  `POST /api/admin/disputes/<id>/resolve`, `POST /api/admin/deals/<id>/no-show`

**Ratings** — `POST|GET /api/deals/<id>/ratings`, `GET /api/users/me/ratings`

**Boosts** — `GET /api/boosts/packages`, `POST|GET /api/parcels/<id>/boosts`

Authoritative instants the client may render from: `funded_at`,
`agreed_pickup_at`, `pickup_confirmed_at`, `delivery_code_available_at`,
`delivery_code_released_at`, `delivery_confirmed_at`, `protection_ends_at`,
`rating_window_ends_at`, `completed_at`, `cancelled_at`, `boost_expires_at`.

---

## 14. Admin primitives

Phase 3's admin routes use `IsAdminUser`, which is `is_staff` and nothing finer.
That is too blunt for Phase 4: reading a party's dispute evidence means reading
their photos and chat references, and resolving a dispute moves money. Neither
should be the same capability as viewing a payout queue, and neither should
require a superuser.

`apps/core/permissions.py` checks named Django permissions with `is_superuser`
as the only blanket override, and staff membership required on top. Migration
`core.0007` seeds four groups matching the specification's roles: Operations
Admin, Support Agent, Finance Admin, Trust & Verification Admin. The full role
and admin-UX design remains Phase 6; this is the primitive it will be built on,
established now because retrofitting authorization is how authorization gaps
happen.

---

## 15. Business settings

Phase 4 policy is parsed by `apps/core/phase4_policy.py`, deliberately separate
from `apps.finance.policy.Phase3Policy`: a settings revision that predates
Phase 4 must still be able to take payments. Rolling back to one degrades
handover, disputes, cancellation, ratings and boosts to a fail-closed 503; it
does not break checkout, reconciliation or refunds.

The protection window is the one value both phases read, and it stays where
Phase 3 put it — `payments.payout.protection_window_seconds` — rather than
becoming a second source of truth for 48 hours.

Seeded in `core.0006`: handover (1800 s buffer, length 8, 5 attempts, 900 s
lockout, 3 lockouts, 12 attempts/hour), cancellation (86 400 s cutoff, 1 000 bps,
€15 cap, 0 bps platform fee), disputes (20 items, 25 MiB, content-type
allowlist, `proportional` fee mode), ratings (1 209 600 s window, tags), boost
(packages, enabled, max active per request).

---

## 16. Security and privacy decisions on the record

1. **Sealed, not plaintext, and never hash-only.** Documented in §3 above with
   its full justification, key separation, audit trail and production boot
   guard.
2. **The delivery code never enters a durable message row.** `secret_ref`
   resolution at render time keeps it out of the notification table, the in-app
   inbox and the published-event audit.
3. **Timeline projection is an allowlist.** A payload key added by a future
   transition is invisible to a party until someone deliberately allows it.
4. **Uniform rejection.** One message, one code, no shape validation at the API
   edge, no "attempts remaining" hint that varies with how wrong a guess was.
5. **Recipient minimisation.** The traveler never receives the recipient's email
   address, because that address is how the platform delivers a code the
   traveler must not hold.
6. **Evidence is references, not copies.** The bundle indexes the authoritative
   rows instead of duplicating sensitive data into a second, drifting store.
7. **Private evidence storage.** Signature-verified uploads, private bucket,
   short-lived signed URLs, ownership checks on both write and read.
8. **Granular admin permissions** rather than a superuser assumption.

---

## 17. Provider status

Stripe and Chargily remain **CODE-CONTRACT VERIFIED**, not LIVE-PROVIDER
VERIFIED. Phase 4 introduces no provider credential, makes no live or sandbox
provider call, and registers no production webhook. Boost payments reuse the
existing Phase 3 rails unchanged.
