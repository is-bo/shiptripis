# Phase K1 — Reliability and Performance Safety Foundation

**Date:** 2026-09-20
**Starting SHA:** `8bcf1ada37614342a1bf3feec007fcea45954d29`
**Branch:** `codex/k1-reliability-foundation`
**State:** code, independent verification, CI, merge, and TEST deployment are
complete. Shared persistent Redis is explicitly deferred because the Railway
project's current Free plan cannot provision another resource; TEST is running
the reviewed embedded-Redis compatibility mode and the queue-durability defect
therefore remains open.

K1 addresses the reliability foundation identified by the full-stack
performance audit without changing financial economics, payout rules, or the
later K2–K6 optimization scope. No migration, Railway mutation, deployment,
provider cutover, or real-money operation is part of this implementation.

## 1. Reconfirmation of audit findings

| Finding | Result | Evidence and K1 decision |
| --- | --- | --- |
| Process-local Redis is ephemeral | **Confirmed** | The combined launcher always replaced `REDIS_URL` with loopback Redis started with persistence disabled. K1 makes shared external Redis mandatory for production-style launch and retains embedded Redis behind an explicit local-only switch. |
| Redis stream work can be lost on restart | **Confirmed, with nuance** | FCM stream entries are transport obligations and can disappear after their database job is marked successful. Active transactional email obligations are stored in `OutboundMessage`; a lost email stream delivery can be re-enqueued after receipt timeout. Redis loss is still a reliability defect, but the audit overstated permanent loss for the active email path. |
| A cache failure makes `/readyz` return 503 | **Confirmed** | The old probe required every check to be `ok`. K1 keeps the Redis check visible as `degraded` while only database/schema failure returns 503. |
| Caddy rejects an application-valid KYC request | **Confirmed** | Both Caddy configurations imposed 12 MB globally while Go accepts a whole multipart request up to `25 << 20` bytes. K1 retains 12 MB for ordinary routes and allows 27 decimal MB for KYC routes. |
| Stripe and Chargily do not reuse HTTP connections | **Confirmed** | Default gateways used the `requests` module directly. K1 uses bounded, reusable, thread-local sessions. |
| A single 15-second provider timeout is used | **Confirmed** | K1 separates connection and read budgets; it does not adopt the audit's arbitrary eight-second recommendation. |
| Two synchronous Gunicorn workers can starve | **Confirmed by model** | Two simultaneous blocking provider calls consumed both request slots. K1 uses two `gthread` workers with two threads each and bounds provider connection setup. |
| Current database budget is about 13 minimum / 43 peak | **Confirmed** | Source calculation and an observed 13-connection Railway snapshot agree. K1 removes the unused KYC pool and reduces combined-container Go pool ceilings. |
| KYC owns a PostgreSQL pool only for readiness | **Confirmed** | KYC performed no product SQL; it only pinged the pool. K1 removes that dependency. |
| Four workers × two threads is the right immediate topology | **Rejected** | The 1 GiB service reached 1,014.98 MB in the inspected 24-hour window. Extra Python processes would make OOM risk worse. K1 adds threads to the existing two workers. |
| PgBouncer is required now | **Rejected** | The post-K1 one-instance peak is 22 and rolling peak is 44 against the observed PostgreSQL limit of 100. PgBouncer remains K6 scope. |

The audit input is preserved in [PERFORMANCE_AUDIT.md](PERFORMANCE_AUDIT.md).
Its finance, mobile, Admin, SSE, and deeper query recommendations remain outside
K1 and were not implemented.

## 2. Redis topology and responsibility classification

### Before K1

`backend/railway/start.py` always launched:

```text
redis-server --bind 127.0.0.1 --save "" --appendonly no
```

It then forced every combined-container child to use that loopback instance,
even if Railway supplied another `REDIS_URL`. The state was neither persistent
nor shareable across replicas.

### Responsibilities

| Responsibility | Classification | Redis-outage behavior / authority |
| --- | --- | --- |
| Django default cache | Disposable cache | Recomputable; PostgreSQL remains authoritative. |
| DRF throttle counters | Disposable security state | Loss must not silently bypass security. Cache errors fail requests closed at the request boundary; web-process restart does not repair the external dependency. |
| KYC upload limiter | Disposable security state | Redis errors prevent the limited upload path from proceeding. |
| Route provider cache | Disposable cache | Recomputable and fail-open. Production uses the same shared `REDIS_URL`; development may use local memory. |
| Payout refresh/deduplication cache | Disposable coordination hint | PostgreSQL idempotency and financial state remain authoritative. Redis is not a money lock. |
| Chat and notification pub/sub | Ephemeral realtime signal | Durable chat messages and notification inbox rows are in PostgreSQL. Clients can refetch after a dropped realtime signal. |
| Presence and delivery-receipt fanout | Ephemeral realtime state | Rebuilt by heartbeats/reconnects; no financial authority. |
| FCM Redis stream | **Delivery transport / queue state** | Pending/unacknowledged push transport can be lost with ephemeral Redis. The in-app notification row survives, but a push side effect may not be replayed once its database scheduling job has succeeded. |
| Email Redis stream | **Delivery transport backed by a DB obligation** | The active path persists `OutboundMessage` before enqueue. Missing receipts cause retry/re-enqueue, so the obligation survives even if a stream entry does not. |

Financial idempotency, capacity reservations, scheduled finance work, holds,
and payouts remain PostgreSQL-authoritative. K1 adds no Redis-based financial
lock.

### After K1 code is deployed

- Production-style launch requires a valid, non-loopback `redis://` or
  `rediss://` `REDIS_URL`.
- The launcher injects that exact URL into Django, KYC, chat, notification, and
  email processes.
- Production routes both Django cache aliases through that URL and refuses a
  conflicting `ROUTE_PROVIDER_CACHE_URL`.
- Missing, malformed, or loopback production Redis configuration fails startup
  explicitly.
- Local development may opt into the prior ephemeral daemon only with
  `SHIPTRIP_EMBEDDED_REDIS=true`.
- Embedded mode refuses a conflicting external URL.

This is code/config preparation only. A persistent shared Railway Redis service
still has to be provisioned and wired after Gemini GREEN. The durable stream
risk is therefore **not operationally resolved until that controlled TEST
cutover**.

## 3. Health and readiness contract

- `/healthz` proves only that Django can answer HTTP and remains dependency
  free.
- `/readyz` treats PostgreSQL access and the applied migration graph as hard
  dependencies. Either failure returns HTTP 503 and `not_ready`.
- The Redis-backed default cache is still exercised. Failure is returned as
  `checks.rate_limit_cache = degraded`, overall status `degraded`, and HTTP 200.
- Production cache connect/read waits are bounded to one second so the probe
  reaches that degraded response instead of hanging behind a dead Redis route.
- Redis outage is not hidden: it remains visible in the probe and permissioned
  deep-health surfaces, and Redis-dependent security paths fail closed where
  they are enforced.
- Object storage and provider availability remain detailed operational health,
  not web-process restart triggers.

Restarting a healthy process cannot repair external Redis. This contract keeps
database-backed core HTTP available without claiming the Redis subsystem is
healthy.

## 4. KYC edge/body contract

The Go service's authoritative limit is:

```go
const MaxRequestBytes int64 = 25 << 20 // 26,214,400 bytes
```

Both Caddy configurations now apply:

- `12MB` to non-KYC requests;
- `27MB` to `/kyc/*` and `/api/kyc/*`.

The 27,000,000-byte edge ceiling exceeds the service's whole-request hard cap
without relaxing ordinary API routes. A static regression test derives the Go
constant and proves both edge configurations remain compatible.

## 5. Provider transport and timeout policy

Stripe checkout/refund, Stripe Connect, and Chargily now obtain one
`requests.Session` per provider per worker thread. This matches the two-worker,
threaded Gunicorn deployment without sharing mutable session state across
threads. Authentication, payloads, and idempotency headers remain request-local,
and provider response cookies are rejected rather than carried into later calls.
Each HTTP/HTTPS adapter has a small bounded pool (`2` pool keys, maximum `4`
connections), blocks rather than creating unbounded spillover connections, and
sets urllib3 automatic retries to zero. Sessions close during orderly process
shutdown.

Default timeouts are now explicit:

| Phase | Default | Production bound | Reasoning |
| --- | ---: | ---: | --- |
| Connect | 3.05 seconds | greater than 0, at most 10 seconds | Bounds DNS/TCP/TLS setup so a broken route cannot occupy scarce capacity for the full read budget. |
| Read | 15 seconds | greater than 0, at most 30 seconds | Preserves the reviewed provider response allowance and existing timeout/fallback behavior instead of inventing an unsupported eight-second cutoff. |

The old `PAYMENTS_PROVIDER_TIMEOUT_SECONDS` remains the read-timeout fallback,
and explicit per-client scalar overrides remain compatible with existing tests.
No automatic mutation retry was added. Domain retries still use the existing
idempotency key and failure classifications.

Every Stripe/Stripe Connect/Chargily call emits a vendor-neutral structured
timing record with only provider, operation type, duration, and outcome
category. URL, path IDs, headers, keys, request/response bodies, and provider
details are excluded.

## 6. Gunicorn and memory evidence

Read-only Railway inspection found a two-vCPU, 1 GiB combined service. A process
snapshot before K1 showed:

| Process | RSS snapshot |
| --- | ---: |
| Gunicorn worker A | 191,012 KiB (about 186.5 MiB) |
| Gunicorn worker B | 163,128 KiB (about 159.3 MiB) |
| Gunicorn master | 28,672 KiB (about 28.0 MiB) |
| Django gRPC | 123,492 KiB |
| Finance worker | 113,520 KiB |
| Reservation worker | 112,964 KiB |
| All measured container memory, current | 681.83 MB |
| 24-hour maximum | 1,014.98 MB of 1,024 MB |

Per-process RSS double-counts some shared memory; it is a worker sizing signal,
not a sum that can be equated with the container memory metric. Post-K1 memory
must be measured after TEST deployment.

K1 retains two Python workers and changes the class from synchronous to
`gthread`, with two threads per worker. That gives four request slots while
adding thread overhead rather than two more 160–187 MiB worker processes.
The Gunicorn 120-second hard timeout is unchanged; provider connection/read
budgets now bound the relevant blocking operation much earlier.

`WEB_CONCURRENCY` and `WEB_THREADS` are validated in the range 1–4. The default
and reviewed production-style configuration is `2 × 2`.

## 7. PostgreSQL connection budget

The database reported `max_connections = 100`. The before-K1 model is:

| Process | Minimum | Peak | Purpose |
| --- | ---: | ---: | --- |
| Gunicorn (2 sync workers) | 2 | 2 | HTTP ORM work |
| Django KYC gRPC | 1 | 4 | Authenticated KYC record writes |
| Finance scheduled worker | 1 | 1 | Durable finance jobs |
| Reservation releaser | 1 | 1 | Capacity expiry/release |
| Go chat | 2 | 15 | Chat persistence/realtime reads |
| Go notification | 2 | 10 | Notification persistence/dispatch |
| Go KYC | 2 | 5 | Readiness ping only; no product SQL |
| Go email | 2 | 5 | `OutboundMessage` delivery/receipts |
| **Total** | **13** | **43** | Per combined container |

K1 removes Go KYC's PostgreSQL dependency and sets combined-launcher ceilings
of chat `5`, notification `5`, and email `2`:

| Process | Minimum | Peak after K1 |
| --- | ---: | ---: |
| Gunicorn (2 workers × 2 threads) | 2 | 4 |
| Django KYC gRPC (4 threads) | 1 | 4 |
| Finance + reservation loops | 2 | 2 |
| Go chat | 2 | 5 |
| Go notification | 2 | 5 |
| Go email | 2 | 2 |
| Go KYC | 0 | 0 |
| **Total** | **11** | **22** |

The launcher computes, validates, and prints this budget at startup. Unsafe or
non-numeric pool/concurrency overrides fail before processes start.

### Deployment/replica model

| Topology | Peak connections |
| --- | ---: |
| One instance | 22 |
| One-instance rolling overlap (old + new) | 44 |
| Two stable replicas | 44 |
| Two replicas while one replacement overlaps | 66 |
| Three stable replicas | 66 |
| Three replicas while one replacement overlaps | 88 |

The current single instance and its rolling overlap fit beneath 100 with ample
room for PostgreSQL administration. Three replicas during a rolling replacement
leave only 12 connections for all other clients, so replica growth still
requires an owner-reviewed global budget. K1 does not add PgBouncer.

## 8. Performance observability

`RequestIDMiddleware` now emits a structured event only when total request time
meets `PERFORMANCE_SLOW_REQUEST_MS` (default `500`). The event contains:

- server-generated request ID;
- HTTP method and source-defined route template, never the concrete path;
- status and total duration;
- actor class (`anonymous`, `authenticated`, or `admin`) without identity;
- optional database query count and aggregate query time.

`PERFORMANCE_DB_METRICS_ENABLED` defaults to false. When enabled for TEST or a
controlled diagnostic window, Django execute wrappers count/time queries but do
not retain SQL or parameters. Production therefore gets low-cost slow-request
summaries by default while staging can collect the evidence required by K3/K4.

Production JSON logging uses an allow-list. Passwords, tokens, guest capability
values, query strings, CCP/RIP, evidence URLs, payment secrets, provider URLs,
and private payloads are not fields. No APM vendor or tracing dependency was
introduced.

## 9. Verification performed by Codex

Codex intentionally ran only K1-scoped checks:

| Gate | Result |
| --- | --- |
| Health/readiness, performance middleware, Stripe, Chargily, and new provider transport assertions | 73 passed |
| Existing Stripe Connect adapter regressions | 57 passed |
| Deployment safety/configuration/static limit tests | 46 passed |
| Changed Go component: `go test ./cmd/kyc ./internal/kyc` | passed (`internal/kyc` cached; command has no direct tests) |
| Repository static web/edge checker | passed (8 HTML, 2 stylesheets, 2 Caddy configurations) |
| Ruff on changed Python | passed |
| Python compilation | passed |
| `git diff --check` | passed |

The workstation has no `caddy` executable or Docker, so Codex could run the
repository's static edge checker but not native `caddy validate`; Gemini must
validate both Caddyfiles with the deployed Caddy version.

The first raw `pytest` command omitted the repository's explicit Django test
settings and failed during collection before tests ran. The corrected commands
used `--ds=config.settings.test_local`. One newly added timing fixture initially
lacked the Stripe webhook secret required by the adapter's existing fail-closed
configuration; the fixture was corrected and the complete 73-test scoped suite
passed.

Broad Django, PostgreSQL concurrency, full Go/race/integration, Flutter,
schema-drift, and migration checks are deliberately delegated to Gemini as
required by the K1 test budget. K1 changes no model or migration.

## 10. Independent verification, CI, merge, and TEST release

Gemini independently returned **GREEN** for exact implementation SHA
`0de95338720eba152bc838719be33097e43eedf2`. Its PostgreSQL 16.13 run reported
2,267 Django tests passing with 34 skipped, all Go packages passing, both Caddy
files valid under Caddy 2.10.0, and zero migration/schema drift. Go race and
real-Redis integration remained delegated to CI.

PR #10's first CI run found six legacy tests that called the private Stripe or
Chargily `_request` helper without the new timing `operation` label. K1 had made
that keyword mandatory even though the pre-K1 helper contract permitted the
direct calls. Commit `2be5df3d607a17f23fb3e771be2cbf36635bb334`
restored a safe `request` default while normal checkout, fetch, and refund paths
continue to emit their specific operation labels. The 124 affected provider and
deployment-safety tests and Ruff passed locally. Fresh CI then passed all six
jobs: 2,273 Django tests with 34 skipped, Flutter, schema drift, production and
native Caddy checks, Go race/unit, and Go real-Redis integration.

PR #10 merged to `main` at
`fdf62e95388c24b4fa556a33eb229f1650fe1e9f`. Exact runtime SHA `2be5df3` was
deployed to Railway TEST as `v1.0.0-rc.46+2be5df3`, deployment
`04a4d51f-4e01-4993-8928-5458284ac484` (**SUCCESS**). No migration was added.
Stripe and Chargily remained TEST, mock payments remained disabled,
`PAYOUT_DZD_EXECUTION_ENABLED` was reconciled from the stale `true` value to
`false` before rollout, and no payout or other money mutation was initiated.
LIVE was not changed.

## 11. Explicit Redis deferral and required later cutover

Provisioning Railway Redis was attempted only after Gemini GREEN. Railway
refused it with `Free plan resource provision limit exceeded`. The owner chose
to defer that resource change. TEST therefore sets
`SHIPTRIP_EMBEDDED_REDIS=true` and deliberately retains loopback Redis with RDB
saves disabled and AOF disabled. Immediately before replacement, both
`notif:fcm` and `email:send` had zero entries and the FCM group had zero pending
items, so that particular rollout did not discard queued TEST transport work.

This is a recorded exception, not a durability fix. FCM stream work created
between future restarts can still be lost. Email obligations remain recoverable
from PostgreSQL `OutboundMessage`, but their in-flight Redis transport is also
ephemeral. Shared multi-replica cache, throttle, pub/sub, and queue semantics
are not operationally available until the later cutover.

The later cutover must be controlled as follows:

1. Upgrade Railway capacity or supply an approved persistent shared Redis
   service; do not reuse an unrelated or nonpersistent endpoint.
2. Provision Redis on the project's private network. Verify an attached volume
   at Redis's data directory and enable/verify AOF (recommended
   `appendfsync everysec`) and/or an owner-approved RDB policy; persistence must
   be proved, not inferred from the template name.
3. Before replacing embedded Redis, inspect `XLEN` and `XPENDING` for
   `notif:fcm` and `email:send`. Schedule a quiet TEST window if either contains
   work, because the old loopback instance cannot be reached after replacement.
4. Stage the app variables without an intermediate deploy:
   `REDIS_URL=${{Redis.REDIS_URL}}`, `SHIPTRIP_EMBEDDED_REDIS=false`; keep
   `ROUTE_PROVIDER_CACHE_URL` absent or exactly equal to `REDIS_URL`.
5. Deploy the then-current reviewed TEST SHA once. Do not combine this with a
   provider activation or LIVE change.
6. Verify `/healthz`, `/readyz`, both Django cache aliases, DRF throttles, the
   KYC limiter, route caching, chat/notification pub-sub, FCM and email consumer
   groups, pending/lag, and the worker heartbeat.
7. Write a harmless sentinel with a TTL, restart/redeploy Redis through the
   approved Railway workflow, and prove the sentinel and stream/group state
   survive. Remove the sentinel, capture volume/persistence evidence, and only
   then mark the durable Redis finding resolved.

## 12. Post-deploy K3 baseline and acceptance evidence

- `/healthz`: HTTP 200, release `v1.0.0-rc.46+2be5df3`.
- `/readyz`: HTTP 200 `ready`; database, migrations, and rate-limit cache `ok`.
- Gunicorn: two `gthread` workers with two threads; observed worker RSS was
  114,208 KiB and 112,836 KiB (about 111.5 and 110.2 MiB).
- Container: about 538 MB current memory and 539.5 MB five-minute peak of a
  1,024 MB limit after rollout.
- PostgreSQL: 12 observed active TEST connections; configured model remains
  11 minimum / 22 peak / 44 rolling-overlap peak.
- Redis: both Django cache aliases passed write/read/delete probes; FCM group
  had one consumer, zero pending and zero lag; the worker heartbeat had a live
  TTL. RDB/AOF persistence is disabled under the documented exception.
- DRF: an isolated, cleaned-up probe allowed exactly 60 anonymous requests at
  the configured `60/min` rate and rejected the 61st.
- KYC: the service is listening and the public route reached it; an
  unauthenticated submission returned 401. CI/native-Caddy checks prove the
  27 MB KYC edge ceiling remains above the 25 MiB service cap while ordinary
  routes remain at 12 MB.
- Chat/notifications: both internal ports are open, dispatchers subscribed,
  unauthenticated WebSocket upgrades fail closed with 401, and the FCM worker
  stayed live after one transient provider gRPC `too_many_pings` reconnect
  warning.
- Email: the Go service is healthy but `EMAIL_ENABLED=false`; PostgreSQL held
  97 pending and 28 cancelled durable obligations. No SMTP delivery claim is
  made while the pre-existing feature switch is off.
- Safe provider reads produced structured timing events without payloads or
  credentials: Stripe success 201.88 ms; a deliberately nonexistent Chargily
  checkout read was rejected in 550.97 ms. No payment mutation occurred.
- Admin read-only baseline: Overview 662.2 ms, Finance Overview 2,312.4 ms,
  People 21.9 ms. Slow-request events contained route templates, status,
  duration, and actor class only.

All K1 code/configuration objectives except operational persistent Redis are
deployed. The durable Redis/queue risk remains explicitly **unresolved** until
section 11 is completed.
