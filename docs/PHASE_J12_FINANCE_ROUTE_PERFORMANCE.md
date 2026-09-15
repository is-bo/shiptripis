# Phase J1.2 — Finance payout approval, route reliability and API performance

Closes the three foundation problems the owner's J1.1 device acceptance left
open: Finance had no usable DZD approval workflow, Find Travelers drew a route
of unlabelled dots, and the app intermittently hung far longer than the server
took to answer.

Starting main: `b193cc01d284a767b17cc8aad423847e396fff76`.
Branch: `claude/j12-finance-route-performance`.

Deployed TEST runtime this phase was measured against: `v1.0.0-rc.31+5ea3a4c` at
`https://shiptrip-production-f7f7.up.railway.app`, with `PAYMENTS_ENVIRONMENT=test`,
Stripe TEST, Chargily TEST and `PAYOUT_DZD_EXECUTION_ENABLED=false` throughout.
No money moved, no provider object was created, and no LIVE operation was
performed at any point.

---

## Part A — the DZD payout approval workflow

### Root cause

The decision itself was never missing. `apps.finance.payout_manual_profiles.review_profile`
has existed since H4: it re-checks the crossed cheque, requires a current
identity attestation, runs the name comparison and writes an immutable
`PayoutProfileReview`. H4.1 put one **Approve** control on the manual payout
screen and wired it to that command.

What was missing is everything around it, and the shape of the gap is what made
it invisible:

1. **Every existing surface starts from a payout.** `admin_console:payout-detail`
   resolves a `Payout`, reads its *frozen* instruction version and offers Approve
   for the profile bound to it. A Traveler who submits a CCP account and a
   crossed cheque and has no funded delivery yet has no payout — so they appeared
   on no screen, in no count and in no queue. Nothing anywhere told Finance the
   submission existed.
2. **Only one of the three outcomes was reachable.** The console form posted
   `approve=True` and nothing else. `PayoutProfileReview.status` has always had
   three values, but `needs_attention` was reachable only as a *downgrade* of an
   approval over a name mismatch, and `rejected` was reachable only through the
   API.
3. **The prerequisite had no surface either.** `review_profile` refuses without a
   current `PayoutIdentityAttestation`, which is created by
   `assign_identity_review` (Finance) followed by `attest_identity` (Trust).
   Neither had a console route. So on a fresh submission the one Approve control
   that did exist would have refused with *"Current attested identity required."*
   and the operator had no way to resolve it.

None of this is a defect in the H4 rail. It is a missing operator surface, and
that is what J1.2 builds.

### The workflow

**Finance Overview → Needs attention.** A new row, first in the list:

> **N · Payout methods awaiting review** — *A Traveler submitted a CCP account
> and a crossed cheque. They cannot be paid in dinars until it is reviewed.* ·
> Finance acts

It links straight to the queue. It is not a popup and it is not dismissible: it
is present on the page an operator opens every day for as long as anything is
waiting, and it disappears when nothing is. It is deliberately **not** an H5
metric — a submitted profile is not money, it has no amount, and the control
plane publishes no figure for it — so it carries a count and no amount, and it
costs exactly one indexed query on top of a page that already costs ninety.

**The queue** — `admin_console:payout-reviews`, a Finance destination in the
console navigation. Four buckets, decided in SQL from each profile's latest
review so the page filters, counts and pages by them in the database: four
counts in one `GROUP BY`, then one page of twenty-five rows. Thirteen queries
whether the queue holds one profile or ten thousand. The distinction between the
buckets is the point:

| Bucket | Meaning | Whose move |
|---|---|---|
| Waiting for review | Submitted, nobody has decided | **Finance** |
| Correction requested | Sent back to the Traveler | Traveler |
| Rejected | Refused; a different account is needed | Traveler |
| Approved | Usable for payouts funded after the approval | nobody |

Only the first is counted on the Overview. A profile sent back for correction is
not Finance work, and counting it as such is exactly how a real submission ends
up waiting behind a queue nobody is working.

Each row carries the Traveler's name and email, the profile revision and the
payout-method version, the submission time, the crossed-cheque state, the
bucket, the blocker where there is one (*Identity not attested*, with the
assigned reviewer named), and who decided it and when. **No account value
appears in the list** — not the CCP number, not the RIP, not the last four of
either. H4.1's rule is unchanged: a list is read over shoulders and screenshotted
into chat, and the destination belongs on the one screen that audits every look
at it.

**The detail** — `admin_console:payout-review-detail`. The order is the order of
the decision, not the order of the model:

1. **Identity.** Whether a legal name has been attested, the server's name
   comparison against the account holder (`consistent` / `alias_match` /
   `mismatch` — a classification, never the names), and a link to the user
   record. Where nothing is attested, the blocker is stated first and Finance can
   assign an identity review to any operator holding `attest_payout_identity`
   through the existing `assign_identity_review` command. The decision controls
   are **absent**, not merely refused, until that is recorded.
2. **Destination.** CCP account, CCP key and RIP masked at rest; the payout
   method's status in plain English with its machine code beside it. The full
   values exist only inside *Reveal payout details* — a POST, never rendered on a
   GET, `no-store`, audited by H4's existing `payout_profile.revealed` record,
   with a per-field copy control, and cleared from the page after five minutes by
   the same `payout.js` the manual payout screen uses.
3. **The cheque.** Its approved label verbatim in French, Arabic and English,
   with the Arabic set `lang="ar" dir="rtl"`. Opening it goes through a new
   session-authenticated route scoped to *this profile's own* evidence — the URL
   names the profile, not a document, so there is no path from here to an
   arbitrary evidence id. Every open is audited by H4's `read_evidence`.
4. **The decision.** Three buttons, each with a sentence saying what it means for
   the Traveler, because *Reject* and *Needs correction* feel similar to the
   person clicking and are completely different to the person waiting.
5. **History.** Every decision recorded against the revision, newest first, with
   the reviewer and the name-check result. Reveals and cheque opens are
   deliberately **not** listed: a review history that names who looked at whose
   bank details is surveillance, not review. They remain in the audit log.

### What changed in the domain, and what did not

One change, in `review_profile`:

```python
review_profile(*, actor, reference, approve=None,
               accept_name_difference=False, decision=None)
```

`decision` is the explicit form and accepts the three statuses
`PayoutProfileReview` already has. `approve=True/False` is retained verbatim for
the H4 API and maps onto `approved`/`rejected`, so no existing caller changes
behaviour. **There is no second state machine**: `approved_profile` still asks
the same question of the same latest review row, and every gate — evidence,
attestation, revocation, KYC expiry, supersession — is untouched.

The only other change is the safe reason code left on the method, so the
Traveler's card can tell one refusal from the other:

| Decision | `method.status` | `method.status_reason` |
|---|---|---|
| Approve | `ready` | *(empty)* |
| Needs correction | `needs_review` | `profile_correction_required` |
| Reject | `needs_review` | `profile_rejected` |

**Approval touches no funded destination.** The only thing an approval does
beyond appending its review row is re-run `evaluate_payout_release` for Deals
whose payout is frozen on that same revision — the identical call H4.1's Approve
control already makes, and one that decides *release timing* and nothing else.
It cannot reach `Payout.active_instruction_version`, `dzd_profile_revision` or
any amount; a funded instruction stays bound to the profile revision frozen at
funding, and the queue page says so.

**Nothing needs a manual refresh.** Every one of these surfaces is server
rendered per request, so the attention count, the bucket counts and the queue
are computed from current rows on each load, and a decision redirects and
re-renders. There is no client-held copy of any of it to go stale.

Preserved and re-verified: Finance/Super capability gating on every route and on
the command; immutable profile revisions (three decisions leave the revision's
`sequence` untouched and append three rows); the identity/review binding; no
editable bank destination anywhere on the review screen; no NIP field; masked
CCP/RIP by default. **An approval never repoints a funded payout** — a funded
instruction is bound to the profile revision frozen at funding, and the queue
page says so in as many words.

### What the Traveler sees afterwards

`dzd_method()` already published the reviewer's decision as
`profile.review_state`, and the app decoded it and then ignored it: every
refusal rendered *"Your payout profile requires verification or an update."*
The card now distinguishes them, in all three languages, with no reviewer note
and no internal code:

- `needs_attention` → *Your payout details need a correction. Submit them again
  with a clear photo of the whole crossed cheque.*
- `rejected` → *This CCP account was not accepted for payouts. Submit a different
  account in your own name.*
- an older server that omits the field keeps today's sentence.

After an approval the card reaches `ready` on the next read, and the console
re-evaluates payout release for any Deal whose payout was frozen on that
revision, so the queue and the payout agree without an operator going to find
the payout.

---

## Part B — the funded route

### Root cause: the server was already right

A canonical CDG → ALG → Jijel journey was built, matched, accepted and funded
through the real mock payment rail, and `GET /api/deals/<id>` read back:

```
basis            funded_snapshot
legs             position 0 FLIGHT, position 1 DRIVE
stops            Paris Charles de Gaulle (CDG) → Houari Boumediene (ALG) → Jijel
times            depart_at and arrive_at present on both legs
withheld         polyline, route metadata, distance, duration, capacity,
                 proofs, flight number, coordinates
```

That is the full I1A contract over **canonical geography** — the shape every V1
journey actually has, where a leg carries `origin_place`/`destination_place` and
leaves the legacy `origin`/`destination` `Location` columns NULL. The existing
I1A suite proved the projection over the legacy shape only; this phase added the
canonical evidence, and the projection needed no change to produce it.

So for a funded Deal whose snapshot carries a route, the Sender sees the route.
**The Deals the owner was opening do not carry one.** Migration
`deals/0008_phase_i1a_journey_timing` backfilled every pre-I1A funded Deal with
`arrival_snapshot["route"] = []`, deliberately: a funded route cannot be
recovered from mutable leg rows, and reconstructing one from the current Journey
would present a guess as a frozen record. `funded_route` therefore returns
`None`, and J1.1's explicit *"the travel route wasn't recorded for this
delivery"* notice is the correct and final answer for those Deals.

**No route is fabricated and no live-Journey fallback was reintroduced.** What
the owner needs to see a route is a Deal funded on the current build; the
acceptance checklist below says so.

### Find Travelers — a real client defect, fixed

This one was genuine, and it was not the screen's layout. `GET /api/matches/compatible-journeys`
sends each covered leg with **two** endpoint key pairs, exactly one of which is
populated:

```json
"origin": null, "destination": null,
"origin_place": {"id": 4, "name": "Paris CDG", "display_label": "Paris CDG",
                 "place_type": "airport", "country_code": "FR",
                 "iata_code": "CDG", "matching_locality_id": 1}
```

`CoveredLeg.fromJson` read only `origin`/`destination`. Every V1 journey is
canonical, so on the live contract that pair is null on every leg of every
candidate — the route line received `label: ''` for each stop and drew a column
of unlabelled dots. The journey-level fallback could not rescue it either:
`AppLocation.fromJson` had no branch for a canonical place summary, so
`start_location`/`destination_location` parsed to a location with an empty
`publicLabel`, an empty `city` and no IATA code, and `coarseLabel` returned `''`.

Fixed in three places, with no server change:

- `AppLocation.fromPlaceJson` parses the canonical place summary, and
  `AppLocation.maybe` now recognises all three shapes it can be handed. Nothing
  is invented: the catalogue's own `display_label` becomes the public label,
  because a canonical place *is* public geography, and no coordinates are
  synthesised, so `isExact` stays false and no screen can be tricked into
  rendering a pin.
- `CoveredLeg` falls back to `origin_place`/`destination_place`.
- `CandidateJourney` and `CandidateRequest` fall back to `start_place` /
  `destination_place` / `pickup_place` / `delivery_place`.

The legacy shape still wins wherever it is present, so a version-2 journey is
unaffected.

### Deferred to J4/J5

This fixed the projection defect and nothing else. The compact route-first
redesign is not started. Specifically deferred:

- the candidate card's information hierarchy and density;
- route stop **detail** lines on discovery (IATA and parent locality are decoded
  and available, and the discovery card still renders labels only — the deal
  screen already uses both);
- empty, refused and partially-compatible candidate states;
- the propose sheet's layout and the boost entry point;
- sorting, filtering and pagination controls on Find Travelers.

---

## Part C — latency and timeouts

### What was measured

Two independent measurements, deliberately: production HTTP logs for what the
owner's device actually experienced, and local query counts for *why*.

**Deployed TEST runtime, Railway HTTP logs, 15 Sep 2026 11:12–11:27 UTC** — a
real owner session including sign-up, posting a parcel, paying a deposit,
cancelling a delivery and browsing travellers:

| Endpoint | Observed |
|---|---|
| `GET /api/me` | 9–50 ms |
| `GET /api/deals` | 5–63 ms |
| `GET /api/deals?activity=active` | 5–52 ms |
| `GET /api/deals/<id>` | 23–40 ms |
| `GET /api/parcels` | 11–27 ms |
| `GET /api/parcels/<id>` | 19–28 ms |
| `GET /api/matches` | 56–115 ms |
| `GET /api/matches/compatible-journeys` | 32–58 ms |
| `GET /api/chat/threads` | 11–57 ms |
| `GET /api/notifications` | 39–55 ms |
| `GET /api/notifications/unread-count` | 28–169 ms |
| `GET /api/journeys` | 15–49 ms |
| `POST /api/payments/orders/…/checkout` | 364 ms (reaches Stripe TEST) |
| `POST /api/parcels/media` | 694 ms (upload) |
| **`GET /admin/finance/manual-dzd/`** | **4 510 ms** |
| **`GET /admin/finance/payouts-hub/`** | **4 585 ms** |
| `GET /ws/chat`, `GET /ws/notifications` | 261 ms – 129 329 ms |

Railway's own percentiles over that 207-request sample read p50 26 ms, p90
200 ms, **p95 8 729 ms, p99 110 664 ms** — and those two tail figures are
**entirely websocket rows**. `/ws/chat` and `/ws/notifications` are long-lived
connections whose "duration" is how long the socket stayed up, not how long a
response took. They are served by separate Go processes behind Caddy and never
occupy a gunicorn worker. Excluding them, nothing in the sample exceeded 700 ms.

**Local query counts** (embedded PostgreSQL, one funded Deal):

| Surface | Queries | Local time |
|---|---|---|
| `GET /api/me` | 1 | 3 ms |
| `GET /api/deals?activity=active` | 1 | 5 ms |
| `GET /api/matches` | 2 | 75 ms |
| `GET /api/deals`, `/api/parcels`, `/api/chat/threads`, `/api/journeys` | 3 each | 11–29 ms |
| `GET /api/notifications` | 4 | 73 ms |
| `GET /api/matches/compatible-journeys` | 5 | 39 ms |
| `GET /api/deals/<id>` | 9 | 25 ms |
| `GET /api/payouts/methods` | 15 | 13 ms |
| `GET /api/payouts` | 16 | 26 ms |
| `GET /admin/finance/dashboard/` | 86 | 3 876 ms |
| `GET /admin/finance/payouts-hub/` | 100 | 5 572 ms |
| `GET /admin/finance/manual-dzd/` | 100 | 5 570 ms |
| `GET /admin/finance/payouts/<id>/` | 33 | 50 ms |
| `GET /admin/finance/payout-accounts/` | 5 | 24 ms |

### Findings

**Application query performance for the app API is healthy.** No endpoint the
app calls exceeds sixteen queries, and none of them grows with data: a deal list
costs the same three queries at one Deal and at five, and candidate discovery
costs the same five queries at 1, 10 and 40 publishable journeys. There is no
N+1 anywhere on the app's read path.

**Matching is not a latency source.** Candidate discovery scans up to the
policy's scan limit, scores every candidate in memory over rows two prefetches
already loaded, and returns a bounded page. Measured: 5 queries and 40–52 ms at
40 candidates, and 32–58 ms in production. Its *presentation* is poor — that is
Part B and J4/J5 — but its cost is not.

**Infrastructure shows no pressure.** Over six hours the service averaged
0.0069 vCPU and peaked at 0.0897; memory sat between 0.55 and 0.65 GB with no
restarts and no cold starts. Database connections are persistent with health
checks (`CONN_MAX_AGE=60`, `CONN_HEALTH_CHECKS=True`), so a request does not pay
a new connection per call and a stale one is discarded rather than used; Redis
is the container's own loopback instance serving the Go chat, notification and
email workers and the KYC limiter, and none of it is on an app request path.
This is not a resourcing problem and nothing was over-provisioned to make it go
away.

**The one genuinely slow server surface is the Finance control plane, and it is
operator-only.** Each of the five Finance destinations builds a full H5 snapshot
under `REPEATABLE READ, READ ONLY` with a 10-second statement timeout: 85–100
queries, most of them 30–47 ms because each one re-evaluates the same deeply
correlated payout base — three ledger sub-aggregates per payout, each over
`mode_ledger`'s nested `EXISTS` chain, plus a hold `EXISTS` spanning four scopes.
That is by design and it is financially correct; it is also why the queue built
in Part A reads payout-method rows directly and never touches it. **Restructuring
the H5 metric evaluation is a change to financially authoritative reporting and
is not in this phase's ownership** — see *Handed to the backend* below.

**What the owner actually experienced is client-side, and it is two things.**

*Request amplification.* One foreground produced three identical bursts of the
same six endpoints inside two seconds — visible three separate times in the
logs, at 11:13:48–50, 11:16:52–54 and 11:25:06–09. `/api/deals` was fetched six
times (twice per burst, once unfiltered and once by activity), `/api/matches`,
`/api/parcels`, `/api/chat/threads` and the bell three times each. The cause is
that three independent callers ask for the same catch-up and cannot see each
other: `AppLifecycleState.resumed` calls `_reconcileCurrentScope()`, and then
the chat socket and the notification socket each call it again from their own
`onConnected`. Every one of those re-fires **every mounted collection**.

*An unbounded retry envelope.* Reads carry a 20-second receive timeout and retry
twice on a timeout with jittered backoff. Nothing bounded the sum, so a single
stalled request could hold a screen for three full attempts plus backoff —
around a minute — before the user was told anything. Against a server whose p50
is 26 milliseconds, that is the entire "it loads much longer than expected"
symptom.

### What changed

**No timeout was increased.** Per-attempt timeouts are unchanged at connect 12 s
and receive/send 20 s: they are sized for a phone on a bad connection and
shortening them would turn a slow answer into a false failure.

- **A catch-up settles for five seconds.** `LiveUpdates.reconcileScope` records
  what it just reconciled and, inside that window, only enqueues resources the
  previous catch-up did *not* cover — so a detail route pushed after the first
  one still reconciles immediately, and a genuine reconnect after a real gap
  still catches up in full. A business event arriving over the socket goes
  through `ingest` and is never suppressed. Implemented against an injectable
  clock rather than a timer, so it leaves nothing pending in a widget test.
  Effect: one foreground now causes one round of reads instead of three.
- **A read has a total budget of 30 seconds.** `AppConfig.requestBudget` bounds
  the whole read including retries: a retry that starts after the budget is
  spent cannot finish inside it, so it is not attempted. Worst case falls from
  about 62 seconds to about 30, with each individual attempt unchanged.
- **A cancelled request is no longer reported as a server fault.**
  `ApiFailureKind.cancelled` — which is the app's own doing, when a screen is
  left or a newer read replaces an older one — rendered *"Something went wrong
  on the server"* in the bad tone and invited a retry of something nobody was
  waiting for. It now reads as the timeout state, in the waiting tone.
- **The timeout sentence says what happened to the data.** *"The server didn't
  answer in time. Nothing was lost — try again."* in English, French and Arabic.
  The existing behaviour it now describes was already correct: Riverpod's
  `AsyncError.copyWithPrevious` keeps the previous value, so a failed refresh
  leaves the screen's data on screen and only the *first* load can reach a
  whole-page error. Nothing was changed to hide persistent slowness and no
  automatic infinite retry was added.

### Verdict on §16

The observed problem is a mixture, but not an even one:

| Cause | Contribution |
|---|---|
| Client request amplification | **Primary.** 3× duplicate traffic on every foreground |
| Client retry envelope | **Primary.** up to ~62 s before any error was shown |
| Application query performance (app API) | None found. 1–16 queries, no N+1, flat with data |
| Application query performance (Finance console) | Real, 4–6 s, **operator-only**, by design |
| Infrastructure / resource pressure | None. 0.07 vCPU average, 0.65 GB, no restarts |
| Intermittent network behaviour | Not excluded; the tail the app saw is explained without it |

One structural note worth carrying forward rather than acting on blind:
`WEB_CONCURRENCY=2` gunicorn sync workers is the concurrency ceiling, and a
single 4.5-second Finance console render occupies half of it. At current TEST
load that is invisible — CPU peaks under a tenth of a core — but it is the reason
the console's cost is worth fixing before it is worth adding workers.

---

## Browser QA

Driven against the real console, rendered from real PostgreSQL rows by the code
on this branch, with five synthetic DZD profiles covering every state. Every
fixture is fake — invented names, a zero-padded CCP account, a generated image
that says *QA SYNTHETIC — NOT A BANK DOCUMENT*. No provider was called.

| Check | Result |
|---|---|
| Finance Overview shows a pending count under Needs attention | PASS — *"2 · Payout methods awaiting review"*, Finance acts |
| One click opens the queue | PASS — links to `/admin/finance/payout-reviews/` |
| Queue discoverable from the Finance navigation | PASS — *Payout method reviews*, between Manual DZD and Refunds |
| Buckets and counts | PASS — 3 waiting / 1 correction / 0 rejected / 1 approved |
| Rows carry the safe fields | PASS — traveler, revision, method version, submitted, cheque state, status, blocker |
| No account value in the list | PASS — no CCP, no RIP, not even a mask |
| Detail is understandable | PASS — identity, name comparison, destination, cheque, decision, history |
| Cheque opens and decrypts | PASS — image rendered through the scoped route |
| Audited reveal | PASS — full values shown, `no-store`, gone on the next GET |
| Approve | PASS — chip *Approved*, method `ready` |
| Needs correction | PASS — chip *Correction requested*, reason `profile_correction_required` |
| Reject | PASS — chip *Rejected*, reason `profile_rejected` |
| History is append-only | PASS — three decisions, newest first, reviewer and name check named |
| Identity assignment | PASS — assigned to the one eligible reviewer; blocked state explained; decision controls absent |
| Ops operator refused | PASS — 403 on all three routes, and no payout link in their navigation |
| Narrow viewport (≈465 px) | PASS — buckets wrap, rows restack as cards, no horizontal overflow |

One defect was found in QA and fixed there: the detail page printed the payout
method's raw status and reason codes with no sentence. It now reads *"Not usable
for payouts — the account was refused"* with `needs_review · profile_rejected`
beneath it, which is H4.1's rule (a person needs the sentence; an operator
reporting a problem needs the string the logs use).

**Limitation.** The deployed TEST console was not driven, because this
workstation has no operator credential for it. The QA above ran the same code
against the same database engine with the same flags; what it cannot cover is a
deployment-specific difference, and the deployment checks below are what stand
in for that.

---

## Tests

**Backend — `apps/finance/tests/test_phase_j12_finance_route_performance.py` (16).**
Queue visibility and the attention count; the waiting/correction split; all
three decisions with their reason codes, immutability and history; no decision
offered *or accepted* without an attested identity; the name-difference
downgrade and its explicit acceptance; Ops, Support and Trust refused on all
three routes and on a posted decision; Super Admin admitted; masked-by-default
and audited reveal; the cheque route scoped to its own profile; the Traveler's
state after each outcome carrying no reviewer identity; and the cost bounds —
the queue flat at ten profiles and under fourteen queries, its page bounded,
paging that repeats no row and clamps a nonsense page number, and the attention
count in exactly one query.

**Backend — `apps/deals/tests/test_phase_j12_route_and_reads.py` (12).**
The canonical funded route: legs really carrying no `Location` rows, funding
freezing a canonical route, every stop named in order with modes and times, the
withheld set intact, the historical empty-route case returning `None` while its
allocations still exist, a non-party refused, and the Traveler's own view. The
discovery seam that actually broke is pinned from the server side too: a covered
leg's exact key set, the legacy pair present and empty, the place pair carrying
the label, and no geometry in either. Plus the read bounds: the four endpoints a user opens, a deal list flat at five
Deals, discovery flat at ten journeys, and discovery bounded by the policy
result limit.

**Mobile — `mobile/test/phase_j12_test.dart` (17).**
Canonical leg and journey endpoint decoding with the legacy shape still winning
where present; every stop of a multi-leg canonical route labelled; the Find
Travelers card rendering all three stop names through the real screen and a fake
backend; catch-up coalescing, the uncovered-resource exception, expiry after the
window and a business event never suppressed; the retry budget bounded below
three attempts; a cancelled request not reported as a server fault; and the
three DZD review states on the Traveler's card with no internal code reaching it.

`mobile/test/phase8ff4_live_test.dart` was updated where it asserted the old
behaviour: a socket connecting straight after a resume used to cause a second
full round of reads, and now does not. Its original guarantee — that a pushed
detail route is in the reconcile scope, which is the J1.1 fix — is unchanged and
still asserted.

---

## Handed to the backend

**Requires Astra backend phase — the Finance control plane costs 85–100 queries
and 4–6 seconds per page.** Every one of the five Finance destinations builds a
full H5 snapshot, and most of its queries take 30–47 ms because each metric
re-evaluates the same correlated payout base: `payable`, `connected` and
`transit` are three sub-aggregates per payout over `mode_ledger`, which is
itself three nested `EXISTS` over `PaymentProviderEvent` and `LedgerEntry`, and
`has_hold` is an `EXISTS` spanning four ownership scopes. Making this fast means
materialising the payout base once per snapshot and aggregating from it — a
restructuring of financially authoritative reporting, which this phase must not
do independently. It is operator-only and no app endpoint touches it.

Narrow brief: keep `Queries.metrics()`'s published figures byte-identical and
keep `build_snapshot` inside one `REPEATABLE READ, READ ONLY` transaction;
evaluate the annotated payout base once into a CTE or temporary table and drive
every payout-derived metric, group and attention count from that. The H5 and
H5.2 suites are the guard: no published amount, count or status may change.

**Still open from J1.1 — `ParcelRequest` lifecycle never advances.** Unchanged
by this phase and still worth fixing; `IN_TRANSIT`, `DELIVERED` and `COMPLETED`
exist as choices and no non-test path assigns any of them.

---

## What did not change

No migration, no schema change, no provider configuration change, no money
movement, no payout accounting, no payout routing rule, no financial snapshot
semantics, no ledger or reconciliation logic, no provider payment state machine.
`PAYMENTS_ENVIRONMENT` stays `test`, Stripe stays TEST, Chargily stays TEST,
`PAYOUT_DZD_EXECUTION_ENABLED` stays `false`, and no LIVE or real-money
operation was performed. No J2 work was started: no flexible deposit, no
recommended-price redesign, no universal guest payer, no payment-success screen,
no Boost redesign, no Boost commission and no request reward economics.

---

## Owner acceptance checklist

1. **Finance → Overview.** *Payout methods awaiting review* appears under Needs
   attention when a Traveler has submitted DZD details, with a count, and opens
   the queue in one click.
2. **The queue.** Four buckets. A submitted profile sits under *Waiting for
   review*; one you have sent back sits under *Correction requested*.
3. **A review.** Open one. Read the cheque, reveal the account, and record each
   of *Approve*, *Needs correction* and *Reject* on a test profile. Each one
   appears in History and none replaces another.
4. **Identity.** A Traveler whose legal name nobody has attested shows the
   blocker and an *Assign identity review* control instead of decision buttons.
5. **The Traveler's side.** After a correction the app says to submit again;
   after a rejection it says to use a different account; after an approval the
   DZD card reads ready.
6. **Route.** Fund a **new** delivery on this build and open it: stops,
   FLIGHT/DRIVE and times render. An older delivery still says the route was not
   recorded — that is correct and final for those seven.
7. **Find Travelers.** The route line on each candidate now shows place names
   instead of empty dots. Its layout is still the old one; the redesign is J4/J5.
8. **Speed.** Opening the app and switching back to it should no longer produce
   a long blank wait. If something does hang, it should now give up in about
   thirty seconds and say so with the screen's data still on it.
