# K6 package O — reliability, retries, breakers, background work, caching, observability

Base: `b5e1118`. Scope: plan §14.4, §14.7–14.14. Redis connection and
consumer-group creation/claiming code (package owning the Redis cutover) was
read but not modified; Gunicorn worker/thread/timeout sizing (package L) was
not changed. No payment, payout, refund, ledger, matching, lifecycle, KYC or
handover semantics changed. Nothing was deployed; no Railway access was used.

## 1. Retry / backoff inventory (§14.11)

| Component | Policy found | Issue | Action |
| --- | --- | --- | --- |
| Stripe / Stripe Connect HTTP | No in-request retry (`max_retries=0`); `Idempotency-Key` on every mutation; 429/5xx/transport → `ProviderUnavailable`; 401/403 → `ProviderNotConfigured`; 4xx → rejected | None. Retries happen only through durable jobs that reuse the stored key (`recover_checkout_attempt`, payout operations) | None |
| Chargily HTTP | Same transport/classification; Chargily has no idempotency header | A retried checkout create could open a second provider session; harmless (unpaid sessions expire, webhook + reconcile are authoritative) and retries are job-driven only | None; recorded |
| FX | No external call: rate comes from versioned business settings | — | None |
| Route/geocoding provider | Pluggable `ROUTE_PROVIDER_CLASS`; no production adapter is in the repo (empty ⇒ `UnavailableRouteProvider`) | A future adapter must bring its own timeout; `BudgetedRouteProvider` caps call count, not duration | Recorded for whoever adds the adapter |
| Google sign-in cert fetch | google-auth default: new session per call, **120 s timeout**, `TransportError` uncaught (HTTP 500) | Worst request-path starvation vector in the app | **Fixed**: `(3.05, 5)` s timeout, per-thread reused transport, `TransportError` → 503 (not 401) |
| Finance `ScheduledJob` | Exp. backoff 60 s·2ⁿ⁻¹ capped 6 h, no jitter; max 8/12/24/32; `Retryable`/`Permanent`/`Deferred`; FAILED rows = dead letter (admin + deep health `manual_action`, `finance.job_exhausted` error log); stuck RUNNING requeued after 900 s | No jitter needed: one claimant, `SKIP LOCKED`, batch-limited | None |
| `OutboundMessage` (email obligations) | Django SMTP path: exp. backoff, max 10. Stream path: re-XADD the **same** event id every fixed 2 min receipt timeout, max 10 ⇒ ~20 min horizon, then FAILED | A Go/SMTP outage > ~20 min fails every obligation created in it (operator re-drive needed). Changing it also delays DISPATCHED marking, so left as a recommendation | Recommend `next_attempt_at = max(2 min, _retry_delay(n))` together with a cheap receipt poll |
| Django SMTP (secret-bearing mail) | `EMAIL_TIMEOUT` unset ⇒ **no socket timeout**; runs in the finance worker's serial loop | One stalled relay wedges payout/refund/expiry jobs indefinitely | **Fixed**: `EMAIL_TIMEOUT` = 20 s (`EMAIL_SMTP_TIMEOUT_SECONDS`) |
| Go FCM consumer | PEL + XAUTOCLAIM (60 s idle, 30 s sweep), no cap; partial token failures re-XADDed with **no attempt count and no delay** | (a) a token failing transiently on every try (sender-ID mismatch, APNs credential fault) loops every 2 s forever; (b) a whole-entry transient failure is swept forever | **Fixed**: `attempt` field, cap 5, backoff 5/10/20/30/30 s with jitter (ceiling + send < sweep idle, pinned by a test); entries older than 1 h are acked and dropped with a warning |
| Go email consumer | PEL + XAUTOCLAIM, no cap; every failure retryable | A 5xx SMTP rejection (unknown mailbox) is resent every ~60–90 s for as long as the stream holds it, while Django re-XADDs duplicates every 2 min | **Fixed**: 5xx server replies and unbuildable messages are `PermanentError` ⇒ ack (Django's obligation keeps the bounded budget); entries older than 30 min are dropped. Dial/TLS/auth/4xx stay retryable |
| Webhooks (Stripe, Chargily, Connect) | `PaymentProviderEvent` unique `(provider, event_id)`; processing via `PROVIDER_EVENT_PROCESS` job; provider retries on non-2xx | None | None |
| Mobile client | Retries idempotent reads only, with jitter; WS reconnect exp. backoff + jitter | None | None |

Shared helpers: Go `pkg/retry` (`Backoff`, `EntryAge`). Python already has
one `_retry_delay` shape in `finance/jobs.py` and `notifications/outbox.py`;
no new Python helper was worth the churn.

## 2. Worker isolation (§14.4)

- **Bounded concurrency**: FCM and email consumers use a 32-slot semaphore,
  16-entry batches, 2 s `BLOCK`; send timeouts 15 s (FCM) / 30 s (SMTP) are
  detached from shutdown so an ack is not lost mid-send. WebSocket sockets are
  unbounded per process (one goroutine set per socket), acceptable at V1 scale.
- **Crash recovery**: PEL + XAUTOCLAIM for streams; `requeue_stuck_jobs` for
  finance jobs; any child exit makes `start.py` exit ⇒ Railway restarts the
  container (`ON_FAILURE`, max 5 retries — after the fifth the service stays
  down; worth an alert).
- **Graceful shutdown — gap fixed**: Railway's default gap between SIGTERM and
  SIGKILL is **0 s**, so every in-process drain (Go 15 s drains, Gunicorn
  graceful, `start.py`'s 20 s child deadline) was unreachable. `railway.json`
  now sets `drainingSeconds: 30`; `start.py` names the 20 s deadline
  (`CHILD_STOP_TIMEOUT_SECONDS`) and a test pins `drainingSeconds` above it.
- **Residual**: email `sendTimeout` 30 s exceeds the Go 15 s drain, so a send
  in flight at shutdown can be abandoned and redelivered (at-least-once, one
  duplicate at worst). In embedded-Redis mode `start.py` SIGTERMs Redis
  together with the consumers, so final acks fail (moot: the stream is
  ephemeral there anyway).
- **Noisy neighbour — gap fixed**: secret-bearing SMTP runs inside the finance
  worker loop; now bounded by `EMAIL_TIMEOUT` (see above).
- **Observable lag**: FCM backlog was in deep health but its pending/lag read
  bytes-vs-str and **never matched** (always `null`); fixed. Email stream
  backlog and oldest-pending age added (see §6).

## 3. Circuit breakers (§14.12) — rejected

Capacity: 2 Gunicorn workers × 2 threads = **4 slots** (package L owns these
numbers). Worst single provider call: 3.05 s connect + 15 s read = **18.05 s**
(no urllib3 retries). Worst request path: Connect onboarding = account create
+ account link = 2 calls ≈ **36 s**. Checkout create, account refresh and the
Connect webhook refresh are one call each.

With a fully black-holed provider, all 4 slots are held only when ≥4
provider-bound requests are in flight inside one 18 s window, i.e. a sustained
rate ≥ 4 / 18 s ≈ **13 provider-bound requests per minute**. At early-launch
volume (≈1 checkout/min) expected occupancy is 1/60 × 18 ≈ 0.3 slots and
P(≥4 concurrent) ≈ 3 × 10⁻⁴. A per-process in-memory breaker (two processes)
would need several consecutive failures per process to open — which, at this
volume, arrive after the outage has already done its limited damage — and a
false open would fail real checkouts. **Rejected.** Re-open the decision if
any of: sustained provider-bound traffic > ~3/min, `provider_http_call`
`outcome=transport_error` ≥ 3 in 5 min in production, or fewer request slots.
The one unbounded vector found (Google certs, 120 s) was fixed with a timeout
instead. Admin KYC-evidence HEADs are bounded at 4 s × 2 attempts × ≤3 slots
(see §5).

## 4. Background work (§14.10)

Nothing moved. Already off the request path: transactional email (outbox job →
Go SMTP or worker SMTP), push (notification-dispatch job → one pipelined
XADD), receipt sweeps and cleanup (management commands). On the request path
by necessity: checkout create (user needs the URL), Connect onboarding link,
payout-account refresh (15 s dedupe), Connect `account.updated` webhook refresh
(changes payout eligibility — not made eventually consistent), explicit
Reconciliation (operator action, K3). Realtime publish is one after-commit
Redis PUBLISH (2 s connect bound). No analytics exist.

## 5. Caching (§14.7–14.9)

Re-measured on local PostgreSQL (embedded, own data dir) with the K3 fixtures
(11 manual-DZD lifecycles + one pending review), 7 warmed requests, median /
max. A second Python process was running on the machine; two runs agreed
within ~25 %.

| Surface | Median ms | Max ms | Queries | K3 ceiling |
| --- | ---: | ---: | ---: | ---: |
| Finance Overview | 484–620 | 797 | 23 | 35 |
| Payouts Hub | 619–628 | 854 | 18 | 30 |
| Manual DZD list | 624–681 | 774 | 18 | 30 |
| Manual DZD detail | 37–45 | 46 | 15 | 28 |
| Payout Reviews | 27 | 30 | 10 | 16 |
| Payout Review detail (S3 HEAD stubbed) | 31 | 32 | 13 | 32 |
| Payments | 25 | 28 | 4 | 10 |
| Reconciliation (explicit, deep) | 3,289–3,349 | 3,540 | 82 | 95 |
| People | 44–53 | 56 | 4 | 8 |
| Admin Overview | 25–30 | 30 | 14 | 22 |
| Disputes | 12–14 | 16 | 3 | 10 |
| `/api/geography/countries` 200 / 304 | 1.3 / 1.3 | — | 1 | — |
| `/api/airports` 200 / 304 | 1.7 / 1.6 | — | 1 | — |

The committed K3 (6) and K4 (5) budget tests pass. Finance pages sit at the K3
"after" level (~0.5–0.7 s, deployed TEST 420–785 ms) with ~20 queries;
remaining time is Python projection/rendering inside one short REPEATABLE READ
snapshot, which a cache would not make safer. ETag revalidation returns 304
with an empty body. **Decision: no Redis caching; no stampede protection
(no shared cache exists to stampede).**

Finding (not changed, K3/admin scope): Payout Review detail performs up to
three **serial S3 HEADs** (`kyc_evidence_slots` → `ObjectStore.readable`) on
the request path. Locally, with no object store, that is **8.6–8.9 s**
(4 s probe timeout × 2 attempts); in an object-store outage it holds a
request slot up to ~24 s. Options: stop after the first connection-level
failure, or reuse a ≤60 s reachability verdict as `storage_health` does.

## 6. Observability and alerts (§14.13–14.14)

Existing: Sentry (errors + 10 % traces when `SENTRY_DSN` set); JSON logs with
an allow-list; `X-Request-ID`; 4xx/5xx warning line; `slow_http_request`
(≥ 500 ms, optional query count/time); `provider_http_call` timing per
Stripe/Chargily call; `/readyz` (DB+migrations hard, Redis `degraded`);
permissioned `/api/admin/health/deep`; Go expvar `/debug/vars` on loopback
ports (never scraped); Railway built-in CPU/memory/HTTP metrics.

Implemented (cheap, no vendor):

- `http_request` line per request (route template, status, duration, actor
  class, query count/time when enabled), `PERFORMANCE_ACCESS_LOG_ENABLED`
  (default on). **Gunicorn's access log is removed** from `start.py` and
  `railway.web.json`: its request line wrote concrete paths — including
  `/api/payments/guest/<token>` capabilities — to Railway logs.
- `ops_snapshot` line every 5 min from the finance worker
  (`--ops-snapshot-seconds`): overdue jobs + oldest overdue age, running,
  unresolved failed; overdue/failed outbound + oldest age; PostgreSQL client
  connections vs `max_connections`; cgroup container memory vs limit;
  FCM/email stream length, pending, lag, oldest-pending age.
- Deep health: `email_stream` backlog, FCM `stream_oldest_pending_age_seconds`,
  and the bytes/str fix that made FCM pending/lag always `null`.
- Go: `ws_stats` line every minute from chat and notification (sockets, users,
  connects since boot, plus every expvar counter such as pub/sub drops).

| Metric | Source on Railway (no paid vendor) | Alert threshold |
| --- | --- | --- |
| API p95 latency | Railway HTTP metrics; per route from `http_request.duration_ms` | p95 > 800 ms for 10 min |
| Finance/Admin p95 | `http_request` where `actor_class=admin`, finance routes | p95 > 1.5 s for 15 min (Reconciliation excluded) |
| Error rate | Railway HTTP metrics; `http_request.status ≥ 500`; Sentry | 5xx > 1 % over 5 min, or > 5 in 1 min |
| Slow requests | `slow_http_request` count | > 20 in 5 min |
| DB connection saturation | `ops_snapshot.ops.connections / max_connections` | > 70 % (warn), > 85 % (page) |
| Memory headroom | Railway memory metric; `ops_snapshot` cgroup bytes | > 85 % of limit for 10 min |
| Redis stream lag / oldest pending | `ops_snapshot` `*_stream_lag`, `*_stream_oldest_pending_age_seconds`; deep health | lag > 100 for 5 min; oldest pending > 300 s |
| Provider timeout rate | `provider_http_call` `outcome ∈ {transport_error, provider_unavailable}` | ≥ 3 in 5 min per provider |
| Worker backlog | `ops_snapshot` `jobs_oldest_overdue_seconds`, `outbound_oldest_overdue_seconds`, `jobs_failed_unresolved` | overdue > 600 s; any new unresolved failure |
| Worker liveness | absence of `ops_snapshot` (finance) / `ws_stats` (Go) lines | none for 15 min |
| WebSocket churn | `ws_stats` `connects_total` delta vs `sockets` | connects/min > 3 × sockets |
| `/readyz` degraded | External free uptime monitor on `/readyz` (body `status`) | 503 twice in a row; `degraded` > 5 min |
| Container restarts | Railway deploy/crash events | any crash; restart budget (5) near exhaustion |

Railway's log search filters these JSON fields; threshold alerting on logs
depends on the plan, so the zero-cost path is: Railway metrics/alerts where
available, a free external monitor on `/readyz`, Sentry's free tier for error
rate, and a daily/export review of the structured lines.

## 7. Verification

- Go (`backend/services`): `go build ./...`, `go vet ./...`,
  `go vet -tags integration ./...`, `go test -count=1 ./...` — all pass. New
  unit tests: `pkg/retry`, SMTP classification against a fake SMTP server
  (550 permanent, 451/dial retryable), FCM retry invariants, hub stats,
  metrics snapshot/Every. New integration tests (`-tags integration`,
  real Redis, CI only): bounded partial-retry chain; stale entry dropped.
- Django (`--ds=config.settings.test_pg`, own data dir): new/changed modules
  17 passed; deployment safety + accounts auth + core health 85 passed;
  finance-worker snapshot + provider HTTP + notifications 77 passed; K3/K4
  budget modules 11 passed. `ruff check .` clean.
