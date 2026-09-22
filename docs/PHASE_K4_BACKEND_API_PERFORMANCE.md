# K4 — General Backend & API Performance Remediation

Status: **implemented, reviewed and locally verified; CI, merge, and Railway TEST deployment in progress**.

K4 started from exact `main` SHA
`9dac1d37b0d79f603bba54eec65c3c8a53b05738` on branch
`codex/k4-backend-api-performance`. It deliberately excludes the K3 Finance/Admin
surfaces except for the mobile payout API contract and does not change financial,
matching, KYC, handover, lifecycle, permission, or audit semantics.

## Measurement method

Measurements use an isolated local PostgreSQL cluster, Django's in-process API
client, and one deterministic canonical marketplace world: a funded V1 Deal and
chat, five funded inbox threads for the inbox profile, ten notifications, an open
compatible request/Journey, payout state, and release geography. Each latency is
the median of six warmed reads. Query count and summed database time come from
`CaptureQueriesContext`; payload bytes are rendered response bytes.

The same profiler was run in a detached worktree at the exact starting SHA and
again against K4. The local PostgreSQL adapter reports individual durations at a
coarse 15–16 ms resolution, so many fast reads appear as 0 ms. DB time is retained
below as captured, but query shape/count and wall-clock medians are more useful for
these small fixtures. SQL inspection found the material duplicate group in the
chat inbox: each of five joined V1 matches re-read its Deal in both visibility and
send-eligibility helpers, for ten avoidable Deal queries.

## Baseline and result

| API | Before ms | After ms | Before queries | After queries | Before DB ms | After DB ms | Before bytes | After bytes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Chat inbox, five threads | 14.77 | 7.72 | 11 | 1 | 0 | 0 | 1,199 | 1,252 |
| Chat messages | 5.15 | 4.67 | 4 | 4 | 0 | 0 | 259 | 264 |
| Notifications | 35.06 | 34.34 | 4 | 4 | 16 | 16 | 5,843 | 5,947 |
| Unread count | 35.45 | 35.21 | 3 | 3 | 16 | 16 | 44 | 44 |
| Deal list | 13.37 | 13.84 | 3 | 3 | 0 | 0 | 21,523 | 21,643 |
| Active Deals | 14.75 | 14.18 | 3 | 3 | 0 | 0 | 21,523 | 21,643 |
| Deal detail | 21.89 | 20.99 | 9 | 9 | 16 | 0 | 8,307 | 8,349 |
| Journey list | 30.92 | 27.24 | 7 | 7 | 0 | 16 | 15,532 | 10,991 |
| Journey detail | 26.91 | 25.73 | 8 | 7 | 0 | 0 | 3,165 | 3,184 |
| Request list | 23.68 | 23.96 | 5 | 6 | 0 | 0 | 9,080 | 9,116 |
| Request detail | 19.12 | 18.95 | 5 | 5 | 0 | 15 | 1,511 | 1,517 |
| Find Travelers | 46.15 | 43.60 | 9 | 9 | 16 | 16 | 11,440 | 11,489 |
| Payout list, default | 16.23 | 15.55 | 7 | 8 | 0 | 0 | 953 | 1,005 |
| Payout history, explicit page | 16.77 | 15.67 | 8 | 8 | 0 | 0 | 1,003 | 1,005 |
| Payout account | 3.16 | 2.98 | 1 | 1 | 0 | 0 | 663 | 663 |
| Countries | 1.58 | 1.54 | 1 | 1 | 0 | 0 | 90 | 90 |
| Places | 6.94 | 6.16 | 3 | 3 | 0 | 0 | 2,486 | 2,493 |
| Airports | 1.52 | 1.47 | 1 | 1 | 0 | 0 | 1,294 | 1,294 |

Generated identifiers/timestamps explain small byte variation on unchanged
representations. The chat envelope now includes additive count/next/previous
metadata, which accounts for its 53-byte increase. The Journey collection is
4,541 bytes (29.2%) smaller because list rows no longer embed detail-only route
geometry, provider metadata, proof evidence, and audit timestamps.

## Confirmed changes

### Chat

The inbox N+1 was confirmed. Its queryset already joined `deal`, but
`chat_history_visible` and `_v1_chat_eligibility` ignored Django's relation cache
and queried Deal independently. Both now consume `match.deal`, preserving the
same authoritative `funded_at`, terminal-state, party, and ProductRequest rules.
Five threads now cost one query rather than eleven, and a regression test proves
the count remains flat as threads grow.

The inbox keeps its existing paginated-envelope shape, its former 100-row
first-page reach, and stable activity ordering, but later pages are now reachable.
No chat visibility or write eligibility rule changed.

### Journeys and serializers

Journey list queries already carried lifecycle annotation, so the reported list
N+1 was rejected. Journey detail did not; it now uses the same authoritative
`with_lifecycle` annotation, removing one hidden serializer query.

`JourneyListSerializer` reuses the authoritative Journey helpers while its leg
projection omits detail-only polylines, routing metadata, proofs, airport metadata,
and audit timestamps. It still exposes the fields used by mobile cards. List legs
carry an `Exists` annotation for approved-proof state, so removing proof rows from
the list prefetch does not change lifecycle calculation. Detail retains the full
serializer and evidence.

### Matching and route calls

Find Travelers remains the canonical J4 implementation: 9 queries, a bounded
candidate scan, one request block outside candidate rows, stable ranked pagination,
and canonical-locality SQL/Python rules. No PostGIS, semantic filter, ranking, or
Redis correctness dependency was introduced. Re-running candidate evaluation on
each offset page was confirmed, but query-slicing or a token cache would alter the
ranked result contract; the existing bounded scan is retained and a stable cursor
or short-lived token remains a future option.

`CachedRouteProvider` now memoizes successful geocodes and directions within its
request-scoped decorator instance before consulting the shared cache. Equivalent
lookups therefore invoke the provider once even when Redis/cache storage is down or
configured as `DummyCache`. Existing keys, TTLs, validation, failure behavior, and
external-call budgets are unchanged.

### Pagination and response contracts

The active Journey list/search, sender/open Request lists, address book, Match
list, PaymentOrder list, and chat inbox no longer use unreachable `[:100]` tails.
Bare-array endpoints remain bare arrays and expose additive `X-Total-Count`,
`X-Page`, `X-Page-Size`, `X-Next-Page`, and `X-Previous-Page` headers. Ordering
uses a primary business timestamp plus primary-key tie-break where needed.

The payout list's prior array-without-page/envelope-with-page ambiguity was
confirmed. It now always returns the existing paginated envelope with a 100-row
default and 100-row maximum. Both Flutter paths already accept this: `getList`
unwraps either arrays or `results`, and the history screen already consumes the
envelope. No Flutter change is required.

Notifications retain page-number pagination for client compatibility, with `id`
as a deterministic secondary sort key. Cursor migration is deferred to K5 because
the current Flutter repository sends page numbers. Legacy Trip and PaymentIntent
slices are explicitly retired V1 surfaces. Countries have a natural ISO upper
bound, so their arbitrary slice was removed without introducing pagination.

### Reference caching and compression

The public, non-personalized countries and airports endpoints now return a strong
content ETag plus `Cache-Control: public, max-age=3600` and answer matching
`If-None-Match` requests with 304. Personalized endpoints are not HTTP cached.

The old claim that production API JSON was uncompressed was rejected by live
read-only verification against Railway TEST. With `Accept-Encoding: gzip`,
`/api/airports` returned exactly one `Content-Encoding: gzip`; transferred bytes
were 3,611 versus 13,683 with identity encoding. Railway's edge already performs
the compression and the response passes through Caddy once, so K4 intentionally
adds neither Django GZip middleware nor a second Caddy encoder. Small countries
JSON remains uncompressed, as expected for threshold-based edge compression.

### Notifications and periodic work

FCM fanout already preloaded devices/users and fetched preferences/notification
rows in batches; the language-query N+1 claim was rejected. Redis enqueue did make
one `XADD` round trip per target. It now uses one non-transactional pipeline while
preserving one stream entry, event identifier, localized payload, and durable
notification row per recipient.

Unread count remains three queries. Its correlated predicates intentionally count
actionable unread notifications rather than raw rows; splitting those meanings
would silently change the badge, so no change was made.

The delivered-event receipt sweeper previously inspected every sufficiently old
undelivered publication. It now processes the oldest 500 rows per run by default,
accepts a validated 1–10,000 batch size, and uses a bounded iterator. Payout
sweepers were already bounded and indexed. The reservation releaser selects IDs
then locks and processes each reservation transactionally; adding `SKIP LOCKED` to
the initial read would release locks before processing and provide no safe claim.
That audit suggestion was rejected rather than creating a false concurrency fix.

## Rejected or already-correct audit findings

- Place matching-locality N+1: Journey, Request, and matching querysets already
  prefetch active primary mappings into `_active_matching_mappings`.
- Request `_location` Deal N+1: the read queryset already prefetches
  `deliveryrequest__deals`; measured list/detail counts are bounded.
- Deal list/detail conflation: Deal summary and detail serializers are already
  separate. Lists cost three queries; dispute/rating/handover work is confined to
  the one-object detail path. No risky rewrite was justified.
- Find Travelers request duplication: the J4 response already has one top-level
  request object and candidate-only results.
- Provider duplication in the measured locality path: stored route snapshots mean
  no provider call was required. Request-scope memoization protects equivalent
  calls in paths that do need the provider.
- Countries/airports: supported catalogues are small and public. Pagination would
  add client complexity without making records reachable; HTTP validation is the
  useful optimization.
- New database indexes: current plans/counts did not demonstrate a missing index.
  Existing recipient/read/time, owner/status/time, journey/status, and due-time
  indexes serve the measured predicates. No write/storage cost was added on old
  audit speculation.
- General response caching, read replicas, CQRS, sharding, Kafka/RabbitMQ,
  Elasticsearch, and PostGIS remain out of scope and unnecessary.

## Budgets, safety, and compatibility

The PostgreSQL regression test applies broad query ceilings to chat inbox/messages,
notifications, unread count, Deal list/detail, Journey list/detail, Request
list/detail, and Find Travelers. It also sets broad payload ceilings of 250 KB for
Journey list, 150 KB for Deal list, and 50 KB for Find Travelers. Exact counts are
not pinned except for the flat-scaling relationship.

Parity coverage exercises matching compatibility/order/lifecycle/read cost,
Journey lifecycle and list/detail projection, Request location privacy, Deal state
through a canonical funded fixture, paid-chat visibility and pagination,
notification badge behavior, payout authorization, and old/new pagination shapes.
Existing DRF permissions and throttles remain in place. New pagination operates
only on already-authorized querysets; public caching is limited to existing
`AllowAny` catalogues. No automatic mutation retry, global mutable-state cache, or
request-cancellation semantic was introduced. Pagination and bounded sweeps limit
avoidable work when clients disconnect or navigate away.

No models, migrations, schema, SQLC contracts, or indexes changed.

## Codex verification

Short targeted PostgreSQL tests only, as required:

- 5 K4 performance/pagination/cache/projection tests passed.
- 66 routing, notification push, Redis event, Journey, Request, and payout tests
  passed.
- 25 focused J4 compatibility, lifecycle, pagination, and read-cost tests passed.
- Changed-file Ruff and `git diff --check` passed before documentation.

An additional legacy chat/matching test module could not reach assertions because
its unchanged fixture creates `ALG`/`CDG` foreign keys without loading Airport
rows. The canonical funded V1 fixture covers the changed relation-cache path. The
full PostgreSQL suite, broad chat/matching/finance/admin regression, schema drift,
Flutter, Go, native Caddy validation, and production/static checks are explicitly
reserved for Gemini/CI.

## Independent verification and deployment

Gemini returned **GREEN** for exact implementation SHA
`e0721bf9ba7a44e6ac63d51602d33a0f6aab2a79`. Its independent PostgreSQL run
reproduced the central result: five chat threads fell from 11 queries to 1 and
from 14.56 ms to 8.17 ms, Journey list payload fell from 15,579 to 10,912
bytes, Journey detail fell from 8 queries to 7, and matching remained at 9
queries with identical ordering and explanations. It also confirmed matching,
Journey/privacy, payout-contract, notification, route-cache, ETag, outbox, edge
compression, migration, lint, production-check, static-web, Caddy, Go, finance,
and Admin gates as GREEN.

The supplied narrative contained several label/count slips that are not code
findings: the committed K4 module contains 5 tests rather than 18, Find
Travelers lives under `apps.matching.tests`, the implementation consumes the
joined Deal relation rather than a nonexistent `_annotate_chat_eligibility`
helper, and unpaid V1 chat history remains correctly hidden until funding.
This record retains the authoritative code/spec semantics while accepting the
reported benchmark and gate result.

## Claude takeover

Codex stopped after recording the Gemini result, leaving the implementation
committed at `e0721bf9ba7a44e6ac63d51602d33a0f6aab2a79` and this record's
verification paragraph uncommitted in the working tree. Nothing was discarded:
that commit and those edits are the base of everything below.

The whole Codex diff was re-reviewed against the repository rather than trusted
because it existed. Three claims were re-derived from the code rather than
accepted: `Deal.match` is a `OneToOneField`, so consuming `match.deal` and
catching `Deal.DoesNotExist` is exactly equivalent to the two removed Deal
queries; `get_route_provider()` builds a fresh `CachedRouteProvider` per call,
so the new `_request_cache` is genuinely short lived rather than a process-wide
cache of mutable state; and the locality/Request "already prefetched" rejections
hold, because every `AirportLocalityMapping` prefetch carries
`select_related("locality", "locality__parent")` and `_read_queryset()` prefetches
`deliveryrequest__deals`.

Flutter compatibility was checked at the call sites rather than asserted.
`JourneyLeg.fromJson` decides `isOwnerView` from `distance_meters`, `proofs` or
`route_metadata`; the list projection keeps `distance_meters` for the owner, so
that flag is unchanged. `proofStatus` and `latestProof`, the only readers of the
dropped `proofs` rows, are used solely by the journey detail and leg proof
screens, and both read `journeyDetailProvider`, which calls
`GET /api/journeys/<id>` and still receives the full serializer. `ApiClient.getList`
unwraps a bare array or a `results` envelope, and the payout history screen reads
the envelope directly, so normalizing the payout list breaks neither path.

### Corrections made during takeover

Two defects were found in the inherited work and fixed.

The bounded outbox sweeper could stop covering new events. V1 delivery detection
never clears a genuine miss, so a row reported as missing stays
`delivered_at IS NULL` for ever. Taking the oldest 500 such rows each run means
that once 500 unrecoverable rows exist, every later publication is invisible to
the sweep — work disappearing permanently, which is precisely what a bounded
worker must not do. The sweep now also takes an upper age bound
(`--max-age-seconds`, default seven days, validated to exceed `--age-seconds`),
so a miss is reported for every run inside the window and then ages out, leaving
the bounded batch free to move forward. A regression test publishes one
thirty-day-old miss and one ten-minute-old miss with `batch_size=1` and asserts
the recent one is the row inspected.

Two newly paginated collections had no deterministic tie-break. `Journey` and
`ParcelRequest` both default to `ordering = ["-created_at"]`, so two rows created
in the same instant could swap between pages and be duplicated or skipped. The
sender's Journey list and Request list now order by `-created_at, -pk`, matching
what the open Request search, Match list, address book, and PaymentOrder list
already do.

### Findings recorded rather than changed

- The chat inbox still evaluates every one of a viewer's matches in Python
  before paginating the eligible list. Bounding it in SQL means restating
  `chat_history_visible` — party, retired-ProductRequest, legacy PaymentIntent
  and funded-Deal rules — inside the queryset, which duplicates domain rules
  across two places for a collection that is small per user. Left as is.
- `chat_history_visible` and `_legacy_chat_eligibility` still issue per-row Offer
  and PaymentIntent reads for legacy, pre-Journey matches. That branch is a
  retired V1 surface and no longer produces new rows.
- `AdminDisputeListView` still hard-slices `[:100]`, so dispute 101 is
  unreachable through that API. It is an operations surface, which belongs to
  K3's Finance/Admin scope rather than K4's, and it is recorded here as a
  follow-up rather than widened into this phase.
- The wallet, legacy Trip, and PaymentIntent list slices remain. Flutter calls
  none of them and the specification lists the wallet as an idea to reuse, not a
  V1 surface.
- `unread_count` remains three queries whose correlated predicates run over all
  of a viewer's active notifications. Making it cheaper means changing what the
  badge counts, so it was left alone, as Codex concluded.
- The additive `X-Total-Count`/`X-Page` family is readable by the Flutter client,
  which is native and not subject to CORS, but no `CORS_EXPOSE_HEADERS` is
  configured. A future browser client that wants to read those headers will need
  one; nothing in the repository reads them from a browser today.

### Claude verification

Run locally against the embedded PostgreSQL cluster, serially:

- Full Django PostgreSQL suite (`pytest -q --ds=config.settings.test_pg
  -p no:randomly`): **2,298 passed, 34 skipped, 4 failed in 40m 59s**. All four
  failures are analysed below; two were K4's and are fixed, two are pre-existing
  and were proved so at the pre-K4 baseline.
- Focused tiers before that: 30 routing/Redis-bus, 60 K4/push/payout-mobile,
  20 chat, 253 trips/parcels/locations, 328 matching/notifications.
  The legacy chat/matching module Codex reported as unable to reach its
  assertions needs no fixture repair: `apps/matching/tests/test_matching.py`
  carries three explicit `@skip` decorators retiring the traveler-first, DZD
  sender-matching, and DZD counter/accept contracts, and those account for the
  suite's skips. Everything not deliberately retired runs and passes.
- `ruff check .`: clean. `makemigrations --check --dry-run`: no changes.
- Production profile `manage.py check --deploy --fail-level WARNING`: no issues.
  `tools/check_static_web.py`: passed. Deployment fail-closed tests: 46 passed.
- Go `build`, `vet`, and `go test ./...` in `backend/services`: clean. The
  `-race` and real-Redis tiers cannot run on this workstation; CI covers both.
- Flutter `dart format --set-exit-if-changed`, `analyze --fatal-infos`, and
  `flutter test`: **974 tests, all passed**. The Journey list projection is the
  only contract change reaching mobile, so the full suite was run.

### The four full-suite failures

Two were caused by K4 and are fixed here. `PayoutVisibilityTests` in
`apps/finance/tests/test_api_contracts.py` asserted the payout list's old bare
array (`len(response.data) == 1`, `response.data == []`). Codex normalized that
endpoint onto the envelope and updated `test_phase8fh6a_mobile.py` but not this
module, so the two tests failed on shape. The assertions now read `count` and
`results`. What the tests protect is unchanged: the traveler still sees exactly
their own payout and the sender still sees none.

Two are pre-existing and order-dependent, not K4's:
`test_j2_h5_regression.py::test_j2_economics_reconcile_in_the_finance_control_plane`
and
`test_phase8fh5_control_plane.py::test_f1_boost_is_funded_once_and_recognised_only_at_close`
both fail inside `set_boost_intent` with
`InvalidPhase4Policy: Business setting 'boost.minimum_amount_eur_cents' must be
an integer`. The active `BusinessSettingsVersion` they read has no boost block:
`TransactionTestCase` classes in the finance suite truncate the tables, and the
`_seed_settings` helpers re-create the revision from
`0005_seed_phase3_payment_settings`, which predates
`0009_seed_boost_economics`. The suite already knows about this —
`apps/core/tests/test_phase8ff4_events.py` re-seeds both migrations with the
comment "TransactionTestCase runs can deplete a reused database's seeds", and
commit `fbe54c8` fixed the same class of problem for the H5 query-plan gate.

That was not taken on trust. The same three modules, in the same order, were run
in a detached worktree at the exact pre-K4 `main` SHA
`9dac1d37b0d79f603bba54eec65c3c8a53b05738`: **1 failed, 63 passed**, the failing
test being `test_f1_boost_is_funded_once_and_recognised_only_at_close` — the same
test, the same count, before any K4 code existed. On the K4 branch the identical
slice gives the identical **1 failed, 63 passed**. K4 touches no boost, business
settings, `phase4_policy`, or `TransactionTestCase` code, and adds no
transactional test class. The pre-existing order dependence is recorded as a
follow-up rather than patched inside a performance phase, where changing finance
test seeding would be unrelated behavior changed to make a test green.

CI is the authority on the full suite: it runs with `pytest-randomly` active
rather than this deterministic alphabetical order, and prior phases merged green
under it.

Edge compression was re-verified directly against Railway TEST at the pre-K4
release `v1.0.0-rc.48+fe1e5bf` before deploying: `/api/airports` returned 13,683
bytes under `Accept-Encoding: identity` and 3,611 bytes with exactly one
`Content-Encoding: gzip`. The `@public` handler in `backend/railway/Caddyfile`
scopes its `encode gzip` to the static site, and the API catch-all
`reverse_proxy` adds none, so the compression is the platform edge's and is
applied once. Codex's rejection of the stale "API JSON is uncompressed" finding
is confirmed.
