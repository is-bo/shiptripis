# K6 — Infrastructure, Caching, Workers, Observability & Load

Status: **complete — merged and released** with K5 and K7 (is-bo/shiptripis#20,
`main` `a08a87a`, TEST `v1.0.0-rc.50+a08a87a`). Branch
`claude/k6-infrastructure-scaling` (now deleted), stacked on the K5
branch head `b5e1118` (K5 is complete locally; see its record). Packages R, O,
L and P are integrated; the final capacity numbers were re-measured with a
screen-shaped traffic mix on `1ed3eb4` (`e0c9914`). LIVE was not touched.

This record is the summary. The detailed findings, runbooks and raw evidence
are the three package notes, which act as its appendices:

| Package | Commit | Plan items | Appendix |
| --- | --- | --- | --- |
| R — persistent shared Redis readiness | `a444163` | 14.1, 14.2 | [`k6-notes/redis.md`](k6-notes/redis.md) |
| O — workers, retries, breakers, background work, caching, observability, alerts | `94573e0` | 14.4, 14.7–14.14 | [`k6-notes/reliability-observability.md`](k6-notes/reliability-observability.md) |
| L — topology, pooling, web capacity, load test, capacity model | `f77ae0e` | 14.3, 14.5, 14.6, 14.15, 14.16 | [`k6-notes/capacity.md`](k6-notes/capacity.md), raw runs in [`k6-notes/capacity-runs/`](k6-notes/capacity-runs/) |
| Integration fix (R × O) | `3966d46` | — | this record, "Verification" |
| P — mobile lazy paging (journeys search, parcels open) | `5606529` | 14.6 follow-up | premise withdrawn (no screen calls either endpoint); see "Correction — traffic mix" |

## Owner decisions (2026-09-23)

- **No per-phase CI or deploy.** One CI run and one TEST release happen at the
  end of K7.
- **Managed Redis provisioning and cutover are deferred to pre-launch.** K6
  delivers the code and configuration readiness, the stream inspector and the
  cutover/restart-proof/rollback runbook (package R). The TEST release at the
  end of K7 keeps embedded Redis. The Redis-restart failure drill (14.17) and
  the "durable stream obligations survive restart" proof (14.18) run at that
  cutover. Railway's free plan refused Redis in K1, so a plan upgrade may be
  needed.

## Baseline (Railway TEST, idle, 24 h, 2026-09-23)

| Service | CPU avg | Memory avg | Memory peak |
| --- | ---: | ---: | ---: |
| `shiptrip` (Django + Gunicorn + Caddy + embedded Redis + Go workers) | ~0.006 vCPU | 0.62 GB | 1.14 GB |
| `Postgres` (managed) | ~0.001 vCPU | 0.12 GB | 0.13 GB |

The project has exactly these two services. Redis is still the embedded
loopback instance with persistence off (`SHIPTRIP_EMBEDDED_REDIS=true`), as
recorded in K1 §11: Railway refused to provision Redis with `Free plan resource
provision limit exceeded`.

## Load and capacity (measured locally, package L)

Local harness in `backend/loadtest/` (i3-10100, 4 cores; Waitress W×T behind
Caddy 2.10.0 as the Gunicorn `gthread` stand-in; PostgreSQL 16.2; miniredis;
finance/releaser loops and Go chat/notification running). The traffic mix is
built from the Flutter screens: each task issues exactly one screen's requests
(session catch-up, Deal detail, chat, Offers list, notification inbox, Find
Travelers, Journey detail with `compatible-requests`, a small Admin console
share). Production throttles stay on, 2–8 s think time, about 0.32 RPS per
active user. Runs start only on a quiet box. Nothing ran against TEST or LIVE.
Re-measured on `1ed3eb4`.

| Users | Shape | RPS | p50 | p95 | p99 | Errors | Web CPU | DB conns (max / active) |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 100 | 2x2 | 32.1 | 27 ms | 100 ms | 160 ms | 0 | 64 % | 10 / 3 |
| 250 | 2x2 | 79.4 | 72 ms | 240 ms | 340 ms | 0 | 159 % | 10 / 4 |
| 400 | 2x2 | 88.3 | 1.4 s | 1.8 s | 2.1 s | 0 | 181 % (saturated) | 10 / 4 |
| 250 | 4x2 | 79.3 | 31 ms | 130 ms | 210 ms | 0 | 179 % | 14 / 4 |
| 350 | 4x2 | 110.6 | 53 ms | 230 ms | 350 ms | 0 | 278 % | 14 / 5 |
| 500 | 4x2 | 128.6 | 770 ms | 1.2 s | 1.4 s | 0 | 353 % (box at 90 %) | 14 / 5 |

- The 2x2 shape is healthy to about 250 active users and saturates near
  88 RPS on the per-process GIL, not the box (58 % busy). Four workers halve
  p95 at 250 users and stay healthy at 350.
- 500 users on 4x2 is this box's knee: the machine sits at 90 % CPU (95 %
  peak) and requests queue, with no errors. 1,000 users is not certified.
- Cost: about 20 ms web CPU per request with cores to spare (23–28 ms at 4x2
  as the shared box fills). No endpoint dominates; the notification inbox,
  Find Travelers and the Offers list are each 10–14 % of server time.
- **Correction — traffic mix (resolved).** The first package L runs modelled
  `GET /api/journeys/search` and `GET /api/parcels/open` (100 rows each) as app
  traffic and found them to be ~40 % of web server time. Package P established
  that **no app screen calls either endpoint**, so those numbers and the
  page-size fix were withdrawn. The re-run above uses the screen-shaped mix;
  per-request cost halved (40 → 20 ms) and the safe envelope rose. The old run
  files are kept in
  [`k6-notes/capacity-runs/superseded/`](k6-notes/capacity-runs/superseded/).
  Package P still made the two unused repository methods request 20-row pages.

**Capacity envelope (extrapolated,** assuming a Railway vCPU costs 20–30 ms
per request): today's 1 replica 2x2 is safe to about 40–60 RPS, which is
**~125–190 concurrently active users** (measured: 250 at p95 240 ms).
`WEB_CONCURRENCY=4` makes that **~250–375**; two 4x2 replicas reach ~500–750
but need the connection-budget fix below. About 1,000 active users (~320 RPS,
6.4–9.6 vCPU of web CPU) needs three to four 4x2 replicas, PgBouncer and a
realtime split. Sockets cost ~0.4 MiB per app-open user, so ~750 online users
fit a 1 GiB budget. Redis load is 2–3 orders of magnitude below single-node
capacity. The full model and scale triggers T1–T5 are in
[capacity.md §1 and §5](k6-notes/capacity.md). T1 is now simply: web CPU
> 60 % of worker cores or core-read p95 > 800 ms → raise `WEB_CONCURRENCY`.

## Plan items

"Changed" means code or configuration changed in K6. "No change" states the
evidence that justified leaving it. "Deferred" states why.

| Item | What was measured or audited | Decision | Evidence |
| --- | --- | --- | --- |
| 14.1 Persistent shared Redis | Every Redis user, consumer-group creation, pending-entry recovery, eviction exposure, boot behaviour | **Changed; ready, proof pending owner cutover.** Consumers create groups with a 10-minute look-back (the old `$` start skipped pushes appended before the worker booted) and recreate a lost group on `NOGROUP`. `start.py` probes shared Redis before migrations and refuses unreachable Redis, bad credentials or an `allkeys-*` policy. New read-only `inspect_redis_streams` (with `--require-drained`). Required settings: AOF `everysec`, RDB, `noeviction`. Provisioning deferred by owner decision. | [redis.md §2–§4](k6-notes/redis.md) |
| 14.2 Responsibility map | Every key, stream, group, channel, TTL and owner | **Documented.** `notif:fcm` is the only durable obligation held solely in Redis; email is backed by `OutboundMessage`; Redis holds no locks or financial idempotency. Flags: stream `MAXLEN ~10000` is a durability boundary; `cache.clear()` is a FLUSHDB; one Redis per environment. | [redis.md §1](k6-notes/redis.md) |
| 14.3 Topology | Per-process memory (idle sum 0.60–0.63 GB matches TEST 0.62 GB), realtime memory per socket, CPU under load | **No change: keep one combined service.** CPU is idle and memory is 60 % of a 1 GiB budget. The first split, when a trigger fires, is realtime, not workers. The TEST 1.14 GB peak is not explained by load (likely deploy overlap or a catalogue import). | [capacity.md §1](k6-notes/capacity.md) |
| 14.4 Worker isolation | Concurrency bounds, crash recovery, shutdown path, lag visibility | **Changed.** `railway.json` `drainingSeconds: 30` (Railway's default of 0 s made every in-process drain unreachable; a test pins it above the 20 s child deadline). `EMAIL_TIMEOUT` 20 s so a stalled relay cannot wedge the finance loop. FCM pending/lag in deep health never matched (bytes vs str); fixed, and email stream backlog added. | [reliability-observability.md §2](k6-notes/reliability-observability.md) |
| 14.5 PostgreSQL pooling | Connection budget per holder; active backends under load | **No change: no PgBouncer.** 22 steady / 44 rolling per container against a budget of 90; active backends never exceeded 5 at 129 RPS. Needed at a third replica or a lower `max_connections`; transaction-pooling constraints recorded (disable server-side cursors, pgx prepared statements). | [capacity.md §2](k6-notes/capacity.md) |
| 14.6 Web capacity | Workers × threads, per-request CPU, memory, timeouts | **No Gunicorn change.** Keep 2 workers × 2 threads; raise `WEB_CONCURRENCY` (env only) on trigger T1. No `--max-requests` without soak evidence. About 20 ms web CPU per request on the app mix; the earlier page-size finding was withdrawn (see the correction above). | [capacity.md §3](k6-notes/capacity.md) |
| 14.7 Finance caching | Re-measured K3 admin surfaces locally: Finance pages 0.5–0.7 s median with ~20 queries, all within K3 ceilings | **No change: no Redis caching.** The time left is Python projection inside one short `REPEATABLE READ` snapshot, which a cache would not make safer. | [reliability-observability.md §5](k6-notes/reliability-observability.md) |
| 14.8 Reference/route caching | K4 ETags (`/api/geography/countries`, `/api/airports` 200/304 in 1.3–1.7 ms); route cache in the responsibility map | **No change.** No measurable gain left. | [reliability-observability.md §5](k6-notes/reliability-observability.md) |
| 14.9 Stampede protection | Whether any expensive shared cached computation exists | **No change.** There is no shared cache to stampede. | [reliability-observability.md §5](k6-notes/reliability-observability.md) |
| 14.10 Background work | Everything on the request path | **No change.** Email, push, sweeps and cleanup are already off the request path; what remains (checkout create, Connect onboarding, payout refresh, `account.updated`, explicit Reconciliation) is there by necessity or correctness. | [reliability-observability.md §4](k6-notes/reliability-observability.md) |
| 14.11 Retry/backoff | Every provider, worker and client retry | **Changed.** Google certificate fetch bounded to (3.05, 5) s (was 120 s) and returns 503 on transport failure. FCM retries carry an attempt count (cap 5, jittered 5–30 s); FCM entries older than 1 h and email entries older than 30 min are dropped with a warning; SMTP 5xx is permanent. New Go `pkg/retry`. Stripe, Chargily, finance jobs, webhooks and mobile were already correct. | [reliability-observability.md §1](k6-notes/reliability-observability.md) |
| 14.12 Circuit breakers | Worst provider hold (18 s per call, ~36 s Connect onboarding) against 4 request slots | **Rejected with evidence.** All slots are held only above ~13 provider-bound requests per minute; at ≈1 checkout/min the chance is ≈3 × 10⁻⁴. Re-open conditions recorded. | [reliability-observability.md §3](k6-notes/reliability-observability.md) |
| 14.13 Observability | Existing Sentry, logs, `/readyz`, deep health, Railway metrics | **Changed.** One allow-listed `http_request` line per request replaces Gunicorn's access log, which wrote guest capability paths to logs. Finance worker logs an `ops_snapshot` every 5 min (job and outbound backlog, DB connections, memory, stream lag). Go chat/notification log `ws_stats` every minute. No paid vendor. | [reliability-observability.md §6](k6-notes/reliability-observability.md) |
| 14.14 Alerts | Thresholds for every listed signal | **Documented** (13 metrics with source and threshold). Zero-cost path: Railway metrics, a free external `/readyz` monitor, Sentry free tier. Not configured on Railway in K6. | [reliability-observability.md §6](k6-notes/reliability-observability.md) |
| 14.15 Load testing | 100–500 users locally with the screen-shaped mix (table above) | **Done for early launch.** 100 and 250 users healthy on 2x2; the box's knee is ~130 RPS (500 users on 4x2); 1,000 not certified; 10,000 not attempted. Not measured: KYC upload, payment webhooks, email, push fanout, soak beyond 5 min. | [capacity.md §4](k6-notes/capacity.md), [capacity-runs/](k6-notes/capacity-runs/) |
| 14.16 Capacity model | Envelope per shape and scale triggers | **Documented** (above). Measured and extrapolated figures are labelled separately. | [capacity.md §5](k6-notes/capacity.md) |
| 14.17 Failure drills | See below | **Not run on TEST** (no deploys by owner decision). Partly covered by unit tests and code. | below |
| 14.18 Success criteria | See below | **Partly met.** Redis criteria ready, proof pending owner cutover. | below |

## Failure drills (14.17)

No drill ran on TEST or staging in K6. Coverage today:

| Drill | Covered now by | Remaining |
| --- | --- | --- |
| Worker restart | PEL + XAUTOCLAIM sweeper (60 s idle, 30 s sweep) reclaims entries from dead consumers; unit tests cover lost-group recreation and cursor paging; `requeue_stuck_jobs` for finance jobs | Observe once on the final TEST release |
| Email outage | Bounded retries: SMTP 5xx permanent, 30-minute stale-entry drop, `OutboundMessage` budget (10 attempts), `EMAIL_TIMEOUT` 20 s; fake-SMTP classification tests | Observe once on the final TEST release |
| FCM outage | Attempt cap 5 with jittered backoff, 1-hour stale-entry drop; unit and (CI-only) real-Redis integration tests | Observe once on the final TEST release |
| Stripe/Chargily slowdown | Per-call timeouts (3.05 s connect, 15 s read, no in-request retry); breaker analysis above | Optional slowdown check on TEST |
| Web rolling deploy | `drainingSeconds: 30` above the 20 s child deadline, pinned by a test | Observe on the final TEST release |
| Object-storage failure | Probe timeouts only (4 s × 2 attempts); see the Payout Review follow-up | Drill on the final TEST release |
| Redis restart | Runbook restart proof ([redis.md §4](k6-notes/redis.md)) | **Runs at the owner's pre-launch Redis cutover** |

## Success criteria (14.18)

| Criterion | State |
| --- | --- |
| Redis is shared and persistent | **Ready, proof pending owner cutover.** Code, boot gate, inspector and runbook are in place; TEST still runs embedded Redis. |
| Durable stream obligations survive restart | **Ready, proof pending owner cutover.** The runbook's restart proof is the evidence. |
| Process topology is justified and safe | Met: single service kept on measured memory and CPU; split triggers defined. |
| DB connection budget is safe | Met for one replica (47/90 worst case). Two replicas need the `start.py` fix below. |
| Workers are bounded and observable | Met: bounded retries and concurrency, drain window, stream lag in deep health and `ops_snapshot`. |
| Observability can diagnose latency and lag | Met at log/metric level: `http_request`, `slow_http_request`, `provider_http_call`, `ops_snapshot`, `ws_stats`. Alerts are defined, not yet wired. |
| Early-launch load is measured | Met locally (100 users, 2x2, p95 100 ms; 250 users, p95 240 ms). Not measured on Railway. |
| Scale triggers are documented | Met (T1–T5 and PgBouncer trigger). |

## Verification

- **Integration fix `3966d46`.** Package R's consumer tests used epoch-era
  stream IDs (such as `1-0`), which package O's stale-entry drop discards. The
  tests now anchor fake IDs to the current time.
- After integrating R, O and L: all 14 Go packages pass `go test ./...`;
  `go vet ./...` is clean, including the `integration` tag. 77 Django
  launcher, ops-snapshot, inspector and Google-verifier tests pass
  (`config.settings.test_local`). `ruff check` is clean.
- **Not run locally:** the real-Redis Go integration tests and `-race` (no
  `redis-server` or Docker on this workstation; CI runs both at the end of K7).
  Package-level test runs are listed in each appendix.

## Open follow-ups

1. **Email stream resend horizon.** The `email:send` path re-enqueues the same
   event every fixed 2 minutes, up to 10 times (~20 minutes), then fails the
   obligation. An outage longer than that needs an operator re-drive.
   Recommend exponential backoff (`max(2 min, _retry_delay(n))`) with a cheap
   receipt poll.
2. **Payout Review detail storage checks.** Up to three serial S3 HEAD checks
   run on the request path; in an object-storage outage one request can hold a
   slot for ~24 s. Stop after the first connection failure, or reuse a
   ≤ 60 s reachability verdict as `storage_health` does.
3. **Connection budget check is per container.** `start.py` does not know
   about replicas, so two default replicas pass it while exceeding the budget
   during overlapping deploys (91/90). Fix before adding replicas.
4. **Recipient addresses in Go email logs.** Failure logs from the go-mail
   library can include recipient addresses. Redact before launch.
5. **Operator rules.** Never run `cache.clear()`, `FLUSHDB` or `FLUSHALL`
   against a shared Redis (it deletes streams, groups and pending entries).
   Use one Redis per environment.
6. **Page size (package P) — premise invalid.** No app screen calls the two
   endpoints; the unused repository methods now request 20-row pages
   (`5606529`). Lowering the server's 100-row default is a contract change
   left to Codex, and not needed for capacity. Capacity was re-measured with
   the corrected mix (above).
7. Smaller items recorded in the appendices: unexplained TEST 1.14 GB memory
   peak (check against the deploy timeline); Railway restart budget of 5
   (worth an alert); the notification inbox, Find Travelers, the Offers list
   and `unread-count` are the largest web CPU consumers (optional tuning);
   untested paths (KYC upload, webhooks, push fanout, email, Finance console
   under load, soak).

## Release

K6 shipped with K5 and K7 in is-bo/shiptripis#20, merged as `a08a87a` (CI 6/6
green on the re-run), and is released to Railway TEST as
`v1.0.0-rc.50+a08a87a`. On TEST the 30 s drain held: during the rolling
redeploy and worker restart, 122 `/readyz` checks returned 0 non-200 and the
old container stopped every service cleanly within the window. The release
record is in [the K7 record](PHASE_K7_FINAL_PERFORMANCE_CERTIFICATION.md#release).

**Owner action before launch:** provision persistent managed Redis (the
Railway free plan refused it in K1, so a plan upgrade may be needed) and run the
package R cutover runbook, including the restart proof. Do not provision it
during K6/K7.
