# K6 package L: topology, DB pooling, web capacity, load test, capacity model

Plan sections 14.3, 14.5, 14.6, 14.15 and 14.16. Base SHA `b5e1118`.
Every figure below is labelled **measured** (taken on the local harness in
`backend/loadtest/`) or **extrapolated** (derived from measured figures plus a
stated assumption). Nothing was run against Railway TEST or LIVE. Raw Locust
stats and monitor summaries for every run are in
[`capacity-runs/`](capacity-runs/).

## Short version

* **Keep one Railway service.** Idle TEST memory (0.62 GB) matches the sum of
  the measured processes almost exactly, the web tier uses a fraction of one
  core at current traffic, and nothing is close to a limit. Split only on the
  triggers in section 1. The first split, when it comes, is **realtime**, not
  workers.
* **No PgBouncer.** Default peak is 22 connections per container (44 during a
  rolling deploy) against a 90-connection budget; under load, active backends
  never exceeded 5. It becomes necessary at the third replica or a
  `max_connections` cut. The constraints for adopting it are listed.
* **No Gunicorn change.** Throughput is CPU/GIL-bound per worker. Four threads
  per worker gave no more throughput than two (44.6 vs 46.4 RPS) and cost 4
  more connections. When web needs more capacity, raise `WEB_CONCURRENCY` (an
  existing env knob, 2 to 3 to 4). No code change is needed.
* **Biggest cheap win is not infrastructure.** The two default-page list
  endpoints are `GET /api/journeys/search` with no `page_size` (the Flutter
  browse, 100 rows, 241 KB) and `GET /api/parcels/open` (100 rows, 157 KB).
  They are **4.4 % of requests and about 40 % of web server time**. Serving
  20-row pages lifted throughput per core by about 38 % and cut p95 at 250
  users from 2.4 s to 0.95 s.
* **Safe envelope today (extrapolated):** about 20-30 RPS on the current 2x2
  shape, which is roughly **90-130 concurrently active app users** at p95 of
  0.5 s or better. Memory holds about **750 users with the app open**
  (realtime sockets) inside a 1 GiB budget.

## Environment and method

| Item | Value |
| --- | --- |
| Box | Intel i3-10100 (4 cores / 8 threads, 3.6 GHz), 16 GB, Windows 10. Locust, Caddy, Postgres, Python and Go all share it. |
| Web | `serve.py`: W Waitress processes x T threads, the Gunicorn `gthread` shape on Windows, behind **Caddy 2.10.0** (the Railway image version) with `least_conn`. |
| Django | `settings_loadtest.py`: `base.py` with `DEBUG` off, `CONN_MAX_AGE=60` + `CONN_HEALTH_CHECKS` (as shipped), and Redis-backed DRF throttles and route cache as in `prod.py`. |
| Redis | `miniredis` (in-process Go implementation), because this box has no `redis-server`. Every Redis round trip still happens. Its speed is **not** evidence about real Redis. |
| Postgres | Embedded PostgreSQL 16.2 (`pgserver`), `max_connections=100`, loopback. |
| Also running | `run_finance_worker`, `run_reservation_releaser`, and the Go `chat` and `notification` relays (built from `backend/services`, pools as `start.py` sets them), so DB connections and memory are the combined-container picture. KYC gRPC, the KYC Go service and email were not run. |
| Data | Real reviewed geography catalogue (56,134 places). 400 travelers, 1,200 senders, 800 Journeys, 2,400 requests, 600 Deals created through `create_sender_offer` + `accept_offer` (420 funded), 300 pending offers, 3,360 chat messages, 40,000 notifications, 5 Super Admins. |
| Traffic | `locustfile.py`: senders 60 %, travelers 38 %, operators 2 %; 2-8 s think time. Requests match the Flutter call sites (same paths, same params, and no `page_size` where the app sends none). Production per-user throttles stay on and a 429 counts as an error. Chat sends are about 0.5 % of requests. |

Offered load works out at **about 0.22 requests/s per active user**. Numbers
are 3-5 minute runs after ramp-up. "Web CPU" is the sum across web workers,
where 100 % = one core.

## 4. Load results (measured)

| Users | Shape | RPS | p50 | p95 | p99 | Errors | Web CPU | Machine CPU | Web RSS (total) | DB conns (max / max active) |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 100 | 2x2 | 23.0 | 45 ms | 450 ms | 1.2 s | 0 | 102 % | 54 % | 262 MB | 12 / 3 |
| 150 | 2x2 | 33.5 | 65 ms | 900 ms | 1.4 s | 0 | 135 % | 41 % | 263 MB | 10 / 2 |
| 250 | 2x2 | 46.4 | 950 ms | 2.4 s | 3.3 s | 0 | 185 % (saturated) | 55 % | 268 MB | 12 / 3 |
| 250 | 2x4 | 44.6 | 1.0 s | 2.6 s | 3.8 s | 0 | 201 % (saturated) | 59 % | 281 MB | 16 / 3 |
| 250 | 4x2 | 54.3 | 64 ms | 1.1 s | 1.8 s | 0 | 269 % | 68 % | 525 MB | 16 / 4 |
| 250 | 2x2, 20-row pages | 53.1 | 310 ms | 950 ms | 1.2 s | 0 | 170 % | 63 % | 242 MB | 10 / 4 |
| 500 | 4x2 | 55.8 | 4.2 s | 7.1 s | 8.1 s | 0 | 342 % | **94 %** (box limit) | 533 MB | 16 / 4 |
| 1,000 | 4x2, 20-row pages | 90.1 | 6.3 s | 7.8 s | 8.8 s | 0 | 357 % | **88 %** (box limit) | 497 MB | 14 / 5 |

How to read it:

* **2x2 is healthy to about 100 active users.** It saturates at about 46 RPS,
  where both workers sit at 90-100 % of a core. Machine CPU is only 55 % at
  that point, so the limit is the per-process GIL, not the box.
* **Threads do not buy throughput here, workers do.** 2x4 matched 2x2. 4x2
  served the whole 250-user offered load at a p50 of 64 ms.
* **500 and 1,000 users exceed what this box can test.** Machine CPU reaches
  88-94 % with Locust, Postgres, Caddy and four Python workers sharing four
  cores. Requests queue and nothing fails: no errors, no connection refusals,
  no DB exhaustion. So 1,000 concurrent users is **not** a result this box can
  certify. The ~90 RPS ceiling at 1,000 users is a lower bound for 4 workers
  on a dedicated 4-core host.
* **Measured CPU cost:** about **40 ms of web CPU per request** for the Flutter
  mix (23.0 RPS / 1.02 cores; 46.4 / 1.85), and about **32 ms** with 20-row
  pages on the two heavy lists.
* **Where the time goes at 100 users** (count x median, as a share of server
  time): Journey browse 26 % (1.9 % of requests), open-request feed 14 %
  (2.5 %), unread-count 12 % (15.5 %; it is polled on every screen),
  compatible-requests 6 %. Uncontended medians: Journey browse 1.0 s, open
  feed 0.41 s, Find Travelers 0.16 s, compatible-requests 0.26 s, everything
  else 15-60 ms.

### Environment caveats

* One shared box. Locust competes with the server, so every saturation point
  is a lower bound.
* Waitress is not Gunicorn. The process x thread shape and GIL ceiling are the
  same; accept balancing (approximated by Caddy `least_conn`) and worker
  recycling are not.
* Windows working set is not Linux RSS. Django processes measured about
  100 MB idle, which cross-checks against TEST (below).
* Loopback DB and Redis. Railway's private network adds roughly 0.5-1 ms per
  round trip. That costs latency (3-10 queries per request) but not web CPU.
* miniredis says nothing about Redis capacity. Redis figures below are
  extrapolated.
* **Not measured:** the KYC upload path (Go + gRPC recorder), payment
  webhooks and checkout, email, FCM push fanout, and long soak (the longest
  run was 5 minutes, so memory creep beyond that is unknown).

## 1. Topology (section 14.3)

### Per-process memory

| Process | Idle | Under load | Source |
| --- | ---: | ---: | --- |
| Django web worker (each) | ~100 MB | 120-135 MB, flat after warm-up | measured |
| `run_finance_worker`, `run_reservation_releaser` (each) | ~100 MB | ~100 MB, CPU about 0 | measured |
| `runkycgrpc` | ~100 MB | n/a | extrapolated (same Django import graph) |
| Go chat / notification (each) | 20-55 MB | + per-socket cost, below | measured |
| Caddy | ~30 MB | 45-60 MB at 90 RPS | measured |
| `migrate` at boot (no-op / full) | 110 MB / 172 MB | transient | measured |
| `import_geography --skip-if-current` (current / new digest) | 125 MB / **275 MB** | transient, after readiness | measured |

Idle sum for the Railway container: 2 web + gRPC + 2 loops at ~100 MB, plus
4 Go services at ~20-30 MB, plus Caddy at ~30 MB. That is **about 0.60-0.63
GB, matching the TEST average of 0.62 GB**. The TEST peak of 1.14 GB is
**not explained by request load**; TEST is idle at about 0.006 vCPU. Two
unverified explanations fit:

1. Railway charting old and new deployments together during a rolling deploy
   (2 x ~0.6 GB).
2. A first-boot catalogue import (+275 MB) together with boot-time processes.

Either way, deploy-time memory is the peak to budget for, not traffic.

### Realtime memory (measured, `ws_memory.py`, idle authenticated sockets)

| Component | Per socket | Per app-open user (2 sockets: `/ws/notifications` + `/ws/chat`) |
| --- | ---: | ---: |
| Go chat relay | 56 KiB | |
| Go notification relay | 68 KiB | |
| Caddy proxying each socket | 145 KiB | |
| **Total** | | **~0.4 MiB** |

4,000 chat sockets opened with zero failures. Go's cost is goroutines plus
buffers. Caddy's cost is two copy buffers per proxied socket, and it is the
larger share.

### Decision

**Keep the single combined service.** Nothing measured justifies a split
today: CPU is idle, memory is 60 % of a 1 GiB design budget, the DB is at 22
of 90 connections, and Redis is already external. Splitting now would double
deploy surfaces and connection pools for no capacity gain.

### Split and scale triggers

Apply them in order; each names the cheaper step first.

| # | Signal (sustained 15 min unless noted) | Action |
| --- | --- | --- |
| T1 | Web CPU > 60 % of the web-worker cores, **or** p95 of core reads (Deals, chat, notifications) > 800 ms while CPU-bound | Ship the 20-row page fix first (section 3). Then `WEB_CONCURRENCY` 2 to 3 to 4 (env only), provided the memory trigger T3 has headroom. |
| T2 | T1 still firing at `WEB_CONCURRENCY=4` | Add a second replica, after re-checking the connection budget (section 2). Beyond 2 replicas, PgBouncer first. |
| T3 | Container memory > 75 % of its limit at steady state, **or** online app users > ~750 (about 300 MB of realtime socket memory), **or** the deploy-time peak reaches the limit | Split **realtime** (Go chat + notification behind its own edge) into a second service. Its memory scales with online users, not requests, and every web deploy currently drops every socket. |
| T4 | Oldest due `finance_scheduled_job` older than 5 min, **or** a loop run takes longer than its interval | Split the job loops into a worker service. A second finance worker is already safe, because claiming uses `SKIP LOCKED`. |
| T5 | More than one child-process crash a week (any child exiting kills the whole container, per `start.py`), **or** reconnect storms after deploys that users can see | Split realtime (as in T3) to decouple failure and deploy domains. |

No other split (KYC, email, gateway) has a trigger. They are light and are
not on the request path.

## 2. DB connection budget (section 14.5)

**Postgres limit (assumed):** `max_connections` = 100. That is the default of
the official image behind Railway's Postgres template; Railway's docs do not
state a figure, and `start.py` already assumes 100. `start.py` keeps a
reserve of 10, so the budget is **90**. The superuser reserve of 3 sits
inside the reserve.

**Django semantics:** with `CONN_MAX_AGE=60` a connection is held per thread
and reused across requests. Web peak is therefore workers x threads, not
concurrent requests. Measured: DB connections never exceeded the static
figure, and active backends peaked at 5 even at 90 RPS.

| Holder | Default (2x2) | `WEB_CONCURRENCY=4` | Notes |
| --- | ---: | ---: | --- |
| Web workers x threads | 4 | 8 | persistent, one per thread |
| KYC gRPC recorder (`--max-workers 4`) | 4 | 4 | |
| Finance loop + reservation releaser | 2 | 2 | |
| Go chat / notification / email pool max | 5 + 5 + 2 | 12 | min 2 each; 6-10 measured in use |
| **Steady peak per container** | **22** | **26** | `start.py` `steady_peak` |
| Rolling deploy (old + new container) | 44 | 52 | `start.py` refuses to boot above 90 |
| One-off: migrate, import_geography, admin shell | +3 | +3 | |
| **Worst case, 1 replica** | **47 / 90** | **55 / 90** | |
| 2 replicas, rolling | 88 + 3 = **91 / 90** | 104 + 3 | at or over budget |

**Decision: no PgBouncer now.** One replica at any `WEB_CONCURRENCY` fits
with 35+ spare connections. Two replicas fit only if they redeploy one at a
time, or if the Go pool maxima drop, which is safe given measured use: chat
and notification 5 to 3 frees 8 per rolling pair. Three or more replicas need
PgBouncer or a larger `max_connections`.

**Risk:** `start.py`'s rolling-peak check is per container and does not know
about replicas. Two replicas at defaults would pass it while exceeding the
budget.

**Constraints if PgBouncer is ever adopted (transaction pooling):**

* **Finance `REPEATABLE READ` snapshot**
  (`apps/finance/control_plane/snapshot.py`) runs
  `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY` and
  `SET LOCAL statement_timeout` inside `transaction.atomic()`. It is
  transaction scoped, so it is compatible. It must never be moved to a
  session-level `SET`.
* **`select_for_update`** (the financial lock graph, chat send, job claiming
  with `SKIP LOCKED`) is always inside a transaction. Compatible.
* **Advisory locks:** none in the codebase (grepped). Nothing to migrate.
* **Server-side cursors:** Django `.iterator()` on PostgreSQL opens named
  cursors. It is used by `sweep_published_events`, payout setup
  reconciliation, the parcel media purge, and data migrations. These break
  under transaction pooling, so
  `DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True` is required.
* **Go pgx** caches prepared statements by default. That needs PgBouncer
  1.21+ with `max_prepared_statements > 0`, or `default_query_exec_mode` set
  to `exec` or `simple_protocol` in the Go DSN.
* **Django psycopg 3** does not use server-side prepared statements unless
  `prepare_threshold` is set. Keep it unset.
* **Session state:** there is no `LISTEN/NOTIFY` and no session-level `SET`.
  Django's time-zone setting is a startup parameter PgBouncer tracks.
  `CONN_HEALTH_CHECKS` stays on.
* Migrations and `import_geography` (one long transaction) should connect
  directly, not through the pooler.

## 3. Web capacity and Gunicorn (section 14.6)

Current config (`start.py`): `gthread`, `--workers 2` (`WEB_CONCURRENCY`, 1-4),
`--threads 2` (`WEB_THREADS`, 1-4), `--timeout 120`, no `--max-requests`.

| Knob | Measured effect | Recommendation |
| --- | --- | --- |
| Threads 2 to 4 | no throughput (44.6 vs 46.4 RPS), +4 DB connections, same memory | **keep 2**. Two threads still hide one slow provider call per worker, as the `start.py` comment intends. |
| Workers 2 to 4 | +1 core of throughput per worker (roughly +20-25 RPS each at 40 ms/request), +120-135 MB, +2 steady / +4 rolling DB connections | **keep 2 now**; raise via env on trigger T1 |
| `--timeout 120` | no timeouts in any run | keep; slow provider calls justify it |
| `--max-requests` | worker RSS flat at 120-135 MB within each 5-minute run | not added without soak evidence; revisit if Railway memory creeps |

**No config change made.** Nothing measured is clearly better *and* free.
More workers cost memory against a design budget the owner set, for traffic
TEST does not have. `WEB_CONCURRENCY` already provides the lever without a
deploy of code.

**For Codex/Claude (API contract, not changed here):** the Flutter client
calls `GET /api/journeys/search` (browse) and `GET /api/parcels/open` with no
`page_size`, so each call renders the 100-row default (241 KB and 157 KB).
Either the client sends `page_size=20` with incremental loading, or those two
endpoints get a smaller default. The second is a contract change for Codex. A
lighter list projection for the open-request feed would also help. Measured
gain: about 38 % more throughput per core for the whole mix. `unread-count` is
the next target: 15.5 % of requests, polled on every screen, 3 correlated
queries (K4 kept its semantics).

## 5. Capacity model (section 14.16)

Assumption for extrapolation: a Railway vCPU gives 1.0-1.5x the per-request
CPU cost measured on this i3 core (40 ms), so **40-60 ms per request**.
Healthy means web CPU at or below 60 % of worker cores.

| Quantity | Current shape (1 replica, 2x2) | Scaled in place (1 replica, 4x2) | 2 replicas, 4x2 | Basis |
| --- | --- | --- | --- | --- |
| Web throughput ceiling | 33-50 RPS | 67-100 RPS | 133-200 RPS | extrapolated from measured 46 RPS/2 workers |
| Safe sustained RPS (60 % CPU) | **20-30** | 40-60 | 80-120 | extrapolated |
| Concurrently active app users (0.22 RPS each) | **~90-130** | ~180-270 | ~360-540 | extrapolated from the measured mix |
| ...with 20-row page fix (32 ms/request) | ~115-170 | ~230-340 | ~460-680 | extrapolated |
| DB connections, steady / rolling | 22 / 44 | 26 / 52 | 52 / 104 (needs PgBouncer or smaller Go pools) | computed; ≤ 5 active measured |
| Web memory | 0.25 GB | 0.5 GB | 0.5 GB per replica | measured |
| Container memory, idle | 0.62 GB | ~0.85 GB | ~0.85 GB per replica | measured (TEST) + measured deltas |
| Online app users (sockets) within 1 GiB | ~750 | ~350 | ~350 per replica | measured 0.4 MiB/user, 1 GiB budget assumed |
| Redis load | ~50-60 ops/s | ~100-120 ops/s | ~200-250 ops/s | extrapolated: 2 throttle ops/request + ~3/chat send |
| Worker (job loop) throughput | bounded batches every 30 s / 60 s, CPU about 0 at idle | same | same | measured idle; backlog not tested |

Reading the model:

* **Early launch (100 concurrent users) fits today's shape**, with little
  margin at p95. The page-size fix buys the next ~50 %, and `WEB_CONCURRENCY=4`
  roughly doubles it again, all inside one service.
* **1,000 concurrently active users** is about 220 RPS. That needs about 4-5
  vCPU of web workers: two 4x2 replicas, PgBouncer (or reduced Go pools plus
  one-at-a-time deploys), and realtime split out, because 1,000 online users
  is ~0.4 GB of sockets alone. It is **extrapolated, not measured**. This box
  saturated at 90 RPS.
* **Redis** is 2-3 orders of magnitude below single-node Redis capacity at
  every row. Memory is DRF throttle history (at most 600 timestamps per user
  per minute) plus streams. It is not a scaling concern at these sizes.
* **Postgres** is not the bottleneck at any measured point: at most 5 active
  backends at 90 RPS, and TEST Postgres uses 0.12 GB. Watch query latency
  (Railway network round trips), not connection count.

### Scale triggers, summarized

1. Web CPU > 60 %, or core-read p95 > 800 ms: page fix, then
   `WEB_CONCURRENCY` up to 4.
2. Still firing at 4 workers: second replica, fixing the connection budget
   first.
3. Memory > 75 % of limit, > ~750 online users, or deploy peak at limit:
   split realtime.
4. Job lag > 5 min: split workers.
5. Frequent child crashes or visible reconnect storms: split realtime.
6. A third replica, or a `max_connections` below 100: PgBouncer, with the
   constraints above.

## Harness

`backend/loadtest/` (see its README): settings, seeder, Windows Gunicorn
stand-in with Caddy, Locust mix, resource monitor, WebSocket memory probe,
and miniredis. Locust is in its own venv. Waitress is a dev-only install. The
Go tools are a separate module. Nothing was added to
`backend/monolith/requirements.txt` or `backend/services/go.mod`.

## Open risks

* **1,000 users is not certified.** The single-box test saturated at ~90 RPS.
  A dedicated load generator against a staging copy (never TEST or LIVE
  without an owner decision) is the way to certify it.
* **`start.py`'s connection check is not replica-aware.** Two default replicas
  pass it while exceeding the budget during overlapping deploys.
* **The TEST 1.14 GB memory peak is unexplained by load.** It is most likely
  deploy overlap or catalogue import. Check it against the Railway deploy
  timeline before choosing a memory limit.
* **Untested paths:** KYC uploads, payment webhooks, push fanout and email.
  Real-Redis latency and soak memory are also unmeasured.
* **Premise correction:** the brief described an embedded Redis. Since K1,
  `start.py` requires an external `REDIS_URL`; embedded Redis is an explicit
  local-only switch.
* **Harness hazard:** during this work another session deleted this package's
  `%TEMP%\shiptrip-pg-*` data directory and its scratchpad. Run artifacts
  survived because they live in the gitignored `backend/loadtest/.data/`.
  Keep `LOADTEST_PGDATA` somewhere no other session cleans.
