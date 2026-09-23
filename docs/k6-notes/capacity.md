# K6 package L: topology, DB pooling, web capacity, load test, capacity model

Plan sections 14.3, 14.5, 14.6, 14.15 and 14.16. Base SHA `b5e1118`; load
runs re-taken on `1ed3eb4`.
Every figure below is labelled **measured** (taken on the local harness in
`backend/loadtest/`) or **extrapolated** (derived from measured figures plus a
stated assumption). Nothing was run against Railway TEST or LIVE. Raw Locust
stats and monitor summaries for every run are in
[`capacity-runs/`](capacity-runs/).

**Superseded mix.** The first runs (base `b5e1118`) modelled
`GET /api/journeys/search` and `GET /api/parcels/open` as app traffic. No
Flutter screen calls either one, and together they were about 40 % of web
server time, so those numbers, the envelope built on them and the "20-row page"
fix were withdrawn. The results, envelope and triggers below are the re-run
(base `1ed3eb4`, after K7-D/E) with a mix rebuilt from the app's screens. The old run files are in
[`capacity-runs/superseded/`](capacity-runs/superseded/).

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
* **No Gunicorn change.** Throughput is CPU/GIL-bound per worker: 2x2
  saturates at 88 RPS with the box only 58 % busy. When web needs more
  capacity, raise `WEB_CONCURRENCY` (an existing env knob, 2 to 3 to 4). No
  code change is needed.
* **App traffic is cheap per request.** About **20 ms of web CPU per request**
  (measured, uncontended), with no single endpoint dominating: the
  notification inbox, Find Travelers and the Offers list are each 10-14 % of
  server time. There is no cheap infrastructure-free win left on the scale of
  the withdrawn page-size fix.
* **Safe envelope today (extrapolated):** about 40-60 RPS on the current 2x2
  shape, which is roughly **125-190 concurrently active app users**
  (measured: 250 users at p95 240 ms on 2x2). `WEB_CONCURRENCY=4` makes that
  **~250-375**. Memory holds about **750 users with the app open** (realtime
  sockets) inside a 1 GiB budget.

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
| Traffic | `locustfile.py`: senders 60 %, travelers 38 %, operators 2 %; 2-8 s think time. One task = one app screen, issuing exactly that screen's requests and parameters (taken from `mobile/lib/data/repositories.dart` and the providers in `app_state.dart`; mix below). Production per-user throttles stay on and a 429 counts as an error. |
| Quiet box | Each run waits for 60 s with no foreign load (no `pytest`, nothing outside the harness above 60 % of a logical CPU), and logs any foreign CPU user during the run (`*-competitors.txt`). A first pass was discarded: a desktop application was using ~6 of the 8 logical CPUs, and a reviewer's `pytest` overlapped one run. In the kept runs the foreign load was other Claude sessions at 25-40 % of one logical CPU (2-4 % of the box), plus Windows Defender / System Restore for about 40 s at the start of the 100-user run. No `pytest` ran during any kept run. |

Offered load works out at **about 0.32 requests/s per active user** (the old
mix: 0.22; a session catch-up is six reads). Numbers are 5-minute steady-state
windows after ramp-up (`--reset-stats`; the monitor samples the same window).
"Web CPU" is the sum across web workers, where 100 % = one core.

### Traffic mix (per simulated user, relative task weights)

| Task (screen) | Requests | Sender | Traveler |
| --- | --- | ---: | ---: |
| Session: cold start / resume (K5) | `/api/me`, `/api/chat/threads`, `/api/matches?page_size=100`, `/api/deals?scope=current&page_size=100`, own list (`/api/parcels` or `/api/journeys`, `page_size=100`), `/api/notifications/unread-count` | 4 | 4 |
| Deal detail | `/api/deals/<id>` (own request/Journey detail for users with no Deal) | 6 | 6 |
| Chat thread | `/api/matches/<id>/chat/messages?page_size=50&latest=1` | 6 | 6 |
| Chat inbox | `/api/chat/threads` | 4 | 4 |
| Offers list | `/api/matches?page_size=100` | 3 | 3 |
| Notification inbox | `/api/notifications?bucket=active` (+ `bucket=history` 1 in 4) | 3 | 3 |
| Chat send | `POST .../chat/messages` | 1 | 1 |
| Deliveries history | `/api/deals?scope=history&page_size=20` | 1 | 1 |
| Profile | `/api/deals?status=completed` (count), `/api/users/me/ratings` | 1 | 1 |
| Find Travelers | `/api/matches/find-travelers?parcel_id=&limit=10&offset=0&sort=best_match` | 3 | |
| Request detail | `/api/parcels/<id>` | 2 | |
| Create request (place picker) | `/api/geography/places?q=...&page_size=25` | 2 | |
| Reference data | `/api/geography/countries`, `/api/airports` (ETag revalidation) | 1 | |
| Journey detail | `/api/journeys/<id>` + `/api/matches/compatible-requests?journey_id=` | | 4 |
| Earnings | `/api/payouts?page=1&page_size=30` | | 1 |
| Create Journey (place picker) | `/api/geography/places?...` | | 1 |

Operators (2 % of users, 5-15 s think time) load Admin console pages:
overview 3, People 2, Deals list 2, Deal detail 2, Disputes 1, KYC queue 1,
Requests 1. The seeded Super Admins hold no Finance role, so the Finance pages
(0.5-0.6 s each in K3/K7) are not in the mix; at 2 % of users their effect is
small. The relative screen frequencies are an assumption (there is no
production analytics yet). `GET /api/journeys/search` and
`GET /api/parcels/open` are absent because no screen calls them.

## 4. Load results (measured)

| Users | Shape | RPS | p50 | p95 | p99 | Errors | Web CPU | Machine CPU (avg / max) | Web RSS (total) | DB conns (max / max active) | Web CPU per request |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| 100 | 2x2 | 32.1 | 27 ms | 100 ms | 160 ms | 0 / 9,621 | 64 % | 30 % / 43 % | 240 MB | 10 / 3 | 19.8 ms |
| 250 | 2x2 | 79.4 | 72 ms | 240 ms | 340 ms | 0 / 23,777 | 159 % | 51 % / 61 % | 242 MB | 10 / 4 | 20.0 ms |
| 400 | 2x2 | 88.3 | 1.4 s | 1.8 s | 2.1 s | 0 / 26,508 | 181 % (saturated) | 58 % / 75 % | 243 MB | 10 / 4 | 20.5 ms |
| 250 | 4x2 | 79.3 | 31 ms | 130 ms | 210 ms | 0 / 23,728 | 179 % | 55 % / 71 % | 484 MB | 14 / 4 | 22.6 ms |
| 350 | 4x2 | 110.6 | 53 ms | 230 ms | 350 ms | 0 / 33,113 | 278 % | 75 % / 91 % | 484 MB | 14 / 5 | 25.1 ms |
| 500 | 4x2 | 128.6 | 770 ms | 1.2 s | 1.4 s | 0 / 38,632 | 353 % | **90 % / 95 %** (box limit) | 484 MB | 14 / 5 | 27.5 ms |

How to read it:

* **2x2 is healthy to about 250 active users.** At 250 users it served the
  whole offered load (79 RPS) at p95 240 ms, with each worker at about 80 % of
  a core. At 400 users it saturates at **88 RPS**: both workers sit at 90 % of
  a core, p50 jumps to 1.4 s, and the box is only 58 % busy. The limit is the
  per-process GIL, not the machine.
* **Workers buy throughput and latency.** At 250 users, 4x2 halved p95
  (240 to 130 ms) for the same RPS. 4x2 stays healthy at 350 users (p95
  230 ms).
* **The knee of this box is about 130 RPS.** At 500 users on 4x2 the machine is
  at **90 % CPU (95 % peak)**, with Locust, Postgres, Caddy and four Python
  workers sharing four cores / eight threads. Requests queue (p50 770 ms) and
  nothing fails: no errors, no connection refusals, no DB exhaustion. 128.6
  RPS is a lower bound for 4 workers on a dedicated host.
* **Measured CPU cost:** about **20 ms of web CPU per request** when workers
  have cores to themselves (19.8-20.5 ms across the 2x2 runs). It rises to
  23-28 ms at 4x2 as the box fills, because hyperthreads are shared with
  Locust and Postgres; treat that rise as a test-box artefact.
* **Where the time goes at 100 users** (request count x mean latency, as a
  share of server time; uncontended medians): notification inbox 13.6 % of
  time (6.2 % of requests, 73 ms), Find Travelers 11.3 % (2.9 %, 140 ms),
  Offers list 10.7 % (11.6 %, 31 ms), `unread-count` 8.8 % (6.7 %, 43 ms), chat
  inbox 8.1 % (18.8 %, 12 ms), `compatible-requests` 7.1 % (2.8 %, 85 ms),
  Deal detail 5.8 % (28 ms). Everything else is 7-47 ms. No endpoint
  dominates; the six largest together are 60 % of server time.

### Environment caveats

* One shared box. Locust competes with the server, so every saturation point
  is a lower bound.
* Waitress is not Gunicorn. The process x thread shape and GIL ceiling are the
  same; accept balancing (approximated by Caddy `least_conn`) and worker
  recycling are not.
* Windows working set is not Linux RSS. Django processes measured about
  100 MB idle, which cross-checks against TEST (below).
* The seeded world is small per user (at most a few Deals, 2 Journeys or 2
  requests, 25 notifications each). Accounts with long histories cost more
  per list read; the data-scale behaviour is in
  [`../k7-notes/data-scale.md`](../k7-notes/data-scale.md).
* Loopback DB and Redis. Railway's private network adds roughly 0.5-1 ms per
  round trip. That costs latency (3-10 queries per request) but not web CPU.
* miniredis says nothing about Redis capacity. Redis figures below are
  extrapolated.
* **Not measured:** the KYC upload path (Go + gRPC recorder), payment
  webhooks and checkout, email, FCM push fanout, the Finance console pages,
  and long soak (the longest run was 5 minutes, so memory creep beyond that
  is unknown). Threads per worker (2x4) were measured only with the
  superseded mix (no throughput gain over 2x2) and not re-run.

## 1. Topology (section 14.3)

### Per-process memory

| Process | Idle | Under load | Source |
| --- | ---: | ---: | --- |
| Django web worker (each) | ~100 MB | 120-135 MB, flat after warm-up | measured |
| `run_finance_worker`, `run_reservation_releaser` (each) | ~100 MB | ~100 MB, CPU about 0 | measured |
| `runkycgrpc` | ~100 MB | n/a | extrapolated (same Django import graph) |
| Go chat / notification (each) | 20-55 MB | + per-socket cost, below | measured |
| Caddy | ~30 MB | 45-85 MB at 30-130 RPS | measured |
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
| T1 | Web CPU > 60 % of the web-worker cores, **or** p95 of core reads (Deals, chat, notifications) > 800 ms while CPU-bound | Raise `WEB_CONCURRENCY` 2 to 3 to 4 (env only, no code change), provided the memory trigger T3 has headroom. On the measured mix T1 fires at roughly 125-190 active users on 2x2 and 250-375 on 4x2 (section 5). |
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
figure, and active backends peaked at 5 even at 129 RPS.

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
| Threads 2 to 4 | no throughput (44.6 vs 46.4 RPS, superseded mix; not re-run), +4 DB connections, same memory | **keep 2**. Two threads still hide one slow provider call per worker, as the `start.py` comment intends. |
| Workers 2 to 4 | +1 core of throughput per worker (roughly +35-50 RPS each at 20-30 ms/request); at 250 users p95 240 to 130 ms; +120 MB per worker, +2 steady / +4 rolling DB connections | **keep 2 now**; raise via env on trigger T1 |
| `--timeout 120` | no timeouts in any run | keep; slow provider calls justify it |
| `--max-requests` | worker RSS flat at 120-135 MB within each 5-minute run | not added without soak evidence; revisit if Railway memory creeps |

**No config change made.** Nothing measured is clearly better *and* free.
More workers cost memory against a design budget the owner set, for traffic
TEST does not have. `WEB_CONCURRENCY` already provides the lever without a
deploy of code.

**Page-size fix: withdrawn.** The first runs attributed ~40 % of server time
to `GET /api/journeys/search` and `GET /api/parcels/open`, which no app screen
calls. Package P made the two unused repository methods request 20-row pages
anyway; nothing further is needed.

**For Codex (optional, not changed here):** the most expensive reads on the
real mix are the notification inbox (73 ms median for a 25-row page, 13.6 % of
server time), Find Travelers (140 ms, 11.3 %), the Offers list (31 ms, but
11.6 % of requests) and `unread-count` (43 ms for a count, 3 queries). None is
large enough to change the envelope on its own; tune them only if T1 fires
before `WEB_CONCURRENCY` can be raised.

## 5. Capacity model (section 14.16)

Assumption for extrapolation: a Railway vCPU gives 1.0-1.5x the per-request
CPU cost measured on an uncontended i3 core (20 ms), so **20-30 ms per
request**. Healthy means web CPU at or below 60 % of worker cores. An active
user offers 0.32 requests/s (measured mix).

| Quantity | Current shape (1 replica, 2x2) | Scaled in place (1 replica, 4x2) | 2 replicas, 4x2 | Basis |
| --- | --- | --- | --- | --- |
| Web throughput ceiling | 67-100 RPS | 133-200 RPS | 267-400 RPS | extrapolated; measured 88 RPS at 2x2 (GIL-bound) and ≥ 129 RPS at 4x2 (box-bound) |
| Safe sustained RPS (60 % CPU) | **40-60** | 80-120 | 160-240 | extrapolated |
| Concurrently active app users (0.32 RPS each) | **~125-190** | **~250-375** | ~500-750 | extrapolated; measured 250 users at p95 240 ms (2x2) and 350 at p95 230 ms (4x2) |
| DB connections, steady / rolling | 22 / 44 | 26 / 52 | 52 / 104 (needs PgBouncer or smaller Go pools) | computed; ≤ 5 active measured |
| Web memory | 0.24 GB | 0.48 GB | 0.48 GB per replica | measured |
| Container memory, idle | 0.62 GB | ~0.85 GB | ~0.85 GB per replica | measured (TEST) + measured deltas |
| Online app users (sockets) within 1 GiB | ~750 | ~350 | ~350 per replica | measured 0.4 MiB/user, 1 GiB budget assumed |
| Redis load | ~80-120 ops/s | ~160-240 ops/s | ~320-480 ops/s | extrapolated: 2 throttle ops/request + ~3/chat send |
| Worker (job loop) throughput | bounded batches every 30 s / 60 s, CPU about 0 at idle | same | same | measured idle; backlog not tested |

Reading the model:

* **Early launch (100 concurrent users) fits today's shape with margin**:
  measured p95 100 ms at a third of the worker CPU. `WEB_CONCURRENCY=4`
  roughly doubles the envelope inside one service, at the cost of ~0.24 GB.
* **1,000 concurrently active users** is about 320 RPS, or 6.4-9.6 vCPU of
  web CPU. At the 60 % rule that is three to four 4x2 replicas, which needs
  PgBouncer (third replica) and realtime split out, because 1,000 online users
  is ~0.4 GB of sockets alone. It is **extrapolated, not measured**. This box
  reaches its limit at about 130 RPS.
* **Redis** is 2-3 orders of magnitude below single-node Redis capacity at
  every row. Memory is DRF throttle history (at most 600 timestamps per user
  per minute) plus streams. It is not a scaling concern at these sizes.
* **Postgres** is not the bottleneck at any measured point: at most 5 active
  backends at 129 RPS, and TEST Postgres uses 0.12 GB. Watch query latency
  (Railway network round trips), not connection count.

### Scale triggers, summarized

1. Web CPU > 60 %, or core-read p95 > 800 ms: `WEB_CONCURRENCY` up to 4
   (about 125-190 active users on 2x2).
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

* **1,000 users is not certified.** The single-box test reaches its limit at
  ~130 RPS (500 users); 1,000 active users is ~320 RPS.
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
  Keep `LOADTEST_PGDATA` somewhere no other session cleans. The re-run used
  `%TEMP%\shiptrip-k6mix\pg`, outside the swept `shiptrip-pg-*` pattern.
* **Screen frequencies are assumed.** The mix follows the app's screens and
  request shapes exactly, but how often users open each screen is a model.
  Re-weight it from production analytics once they exist; the per-request
  cost (20 ms) is the more robust number.
