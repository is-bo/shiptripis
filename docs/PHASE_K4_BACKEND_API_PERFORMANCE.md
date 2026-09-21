# K4 — General Backend & API Performance Remediation

Status: **implemented; independent Gemini verification, CI, merge, and deployment pending**.

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

Gemini result: **pending**.

CI, merge, Railway TEST deployment, health/readiness, authenticated production-
style benchmarks, and branch cleanup: **pending**. K4 must not merge or deploy
until Gemini independently verifies the exact implementation SHA.
