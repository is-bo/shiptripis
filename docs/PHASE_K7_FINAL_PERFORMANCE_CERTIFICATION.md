# K7 — Realtime, High-Scale Tuning & Final Certification

Status: **implementation complete; release gate pending.** All K7 packages,
the independent K6+K7 review fixes and the final capacity re-run are
integrated on `claude/k6-infrastructure-scaling`. CI, merge and the Railway
TEST release are ⟪TBD: release gate result⟫.

| Item | Value |
| --- | --- |
| Branch | `claude/k6-infrastructure-scaling` (stack: K5 `claude/k5-mobile-performance` → K6 → K7; draft PR is-bo/shiptripis#19 carries K5) |
| Start SHA | branch tip `8117a63` (K6 docs); packages A–C measured from `f77ae0e` (K6 L) |
| Implementation SHAs | A `71dc984`, B `212c757`, C `41fc5fb`, D `b2326df`, E `1ed3eb4`, review fixes `312c372` + `dbad52f`, capacity re-run `e0c9914` |
| Baseline `main` | `b5e33e4` (K4 released as `v1.0.0-rc.49+89de1ec`) |
| Final `main` SHA | ⟪TBD: merge SHA⟫ |
| Railway TEST release | ⟪TBD: `v1.0.0-rc.50+<sha>`, deployment id⟫ |

**Owner decisions (2026-09-23).** No per-phase CI or deploy: one CI run and
one Railway TEST release after K7, covering K5–K7. Managed Redis provisioning
and cutover are deferred to pre-launch; the code, configuration and runbook are
ready ([k6-notes/redis.md](k6-notes/redis.md)), and the Redis-restart survival
proof runs at that cutover.

**Appendices** (the detailed evidence; this record is the summary):

| Appendix | Plan items |
| --- | --- |
| [k7-notes/realtime.md](k7-notes/realtime.md) | 15.1–15.6 |
| [k7-notes/data-scale.md](k7-notes/data-scale.md) (incl. "K7-E fixes") | 15.7–15.9 |
| [k7-notes/certification.md](k7-notes/certification.md) | 15.10–15.12, §19 |
| [k6-notes/capacity.md](k6-notes/capacity.md) (final re-run) | load and capacity used by 15.13 |

## Packages

| Package | Commit | Scope | Outcome |
| --- | --- | --- | --- |
| A — realtime | `71dc984` | 15.1–15.6 | Keep WebSocket, no SSE. Fixed a silent slow-consumer drop and 3 arrival channels no socket subscribed to. |
| B — data scale | `212c757` | 15.7–15.9 | No replicas, partitioning, `pg_trgm`, Elasticsearch, CQRS or sharding now, each with a trigger. Retention recommendations. No code change. |
| C — certification | `41fc5fb` | 15.10–15.12, §19 | One-world flow profile + budget test, client slow-network test, evidence map. |
| D — measured defects | `b2326df` | from C | Admin evidence storage checks bounded; dispute JSON list reachable with a stable order; Offers list trimmed. |
| E — contract-neutral query fixes | `1ed3eb4` | from B | Discovery and admin-user N+1s removed; batched job prune; notification dispatcher absorbs bursts. |
| Review fixes | `312c372`, `dbad52f` | independent review of all K6+K7 runtime changes | See "Review fixes". |

## 15.1–15.6 Realtime

| § | Verdict |
| --- | --- |
| 15.1 Transport | **Keep WebSocket** for notifications and chat. WS costs 68 KiB per notification socket, ~7–9 k connects/s per relay and no DB per connect. Only one of the five SSE conditions holds (one-way). Replay is REST catch-up against the durable inbox, which SSE would not improve. |
| 15.2 Presence | Not material: 0.2 SETEX/s per online user (2,000/s at 10 k users). Nothing reads `presence:<uid>`; removing or lengthening the loop is an owner call. |
| 15.3 Backpressure | Two defects fixed (below). Dispatcher burst absorption added in E. One gap flagged: the Redis resubscribe window. |
| 15.4 Reconnect storms | Go survives: 2,000 sockets reconnect in 0.5 s with 0 failures; after an 8 s relay outage 1,993/2,000 were back in 6 s. The real cost is the REST catch-up burst on Django (5–7 GETs per user per reconnect). |
| 15.5 Missed events | Recovery is sound: resume and every socket connect reconcile inbox, unread count, mounted lists, the open Deal and the open chat (`after_id` delta). No important state is realtime-only: all 43 `publish_after_commit` sites write an inbox row and a retrying dispatch job. |
| 15.6 Chat scaling | No bottleneck: a 1,000-message thread reads in 4–6 queries and 4.5–17 ms per page, flat in thread length; fan-out ~6 k frames/s paced with 0 loss. `unread-count` (38–42 ms, mostly ORM compile and planning) flagged for Codex. |

**Defects fixed (A).**

1. **Slow consumers lost events silently and suppressed the push fallback.** A
   full 64-frame send buffer dropped the frame, kept the socket open and still
   counted it as delivered, so FCM skipped the push. Now the socket is closed
   (the client reconnects and catches up) and only sockets that queued the frame
   count. Teardown before the fix took 10.01 s (write timeout); after, well
   under it.
2. **`deal.arrival_reported/confirmed/declined` never reached a live socket.**
   Django published them; the relay never subscribed. Now subscribed, with a
   lockstep test against `apps/core/channels.py`.

## 15.7–15.9 Data scale

| Technique | Verdict | Trigger to reconsider |
| --- | --- | --- |
| Read replicas | **No.** Web saturates first; DB at most 5 active backends at 129 RPS. | Primary DB CPU > ~65 % sustained or read-dominant load. Never for financial or matching reads. |
| Partitioning | **No.** At 5 M notifications the per-recipient list (36.7 ms) and unread count (52.9 ms) match 1 M. | A retention delete cannot finish in its window; notifications > ~5 M (~1.4 years at 10 k DAU); chat > ~10 M. |
| `pg_trgm` | **Not now; first to adopt.** Operator `%ILIKE%` search crosses ~100 ms at ~20 k audit rows, ~35–40 k jobs, ~55 k emails, ~80–100 k users. | Per table at its crossover, or console search p95 > 500 ms. Verify the extension exists on Railway Postgres first. |
| Elasticsearch | **No.** No fuzzy or multilingual search requirement in V1. | A real product requirement PostgreSQL cannot meet. |
| CQRS | **No.** List cost is fixed by page shape; Deal and financial state must stay strongly consistent. | Durable projections clearly justify eventual consistency. |
| Sharding | **No.** The financial lock graph relies on single-primary `select_for_update`. | A strong single primary saturated, with a credible financial-locking replacement. |

**Find Travelers (15.8).** Contract unchanged. E removed the bounded N+1
(108 → 7 queries at 20 Journeys; count no longer grows with candidates). The
candidate SQL still scans every Journey overlapping the request window on any
corridor (71 ms at 24, 455 ms at 1,000, 680 ms at 10,000), and page 2
re-evaluates. Revisit when Find Travelers p95 > 800 ms or > ~1,000 Journeys
overlap a typical 1-day window; options, cheapest first, are in
[data-scale.md §2](k7-notes/data-scale.md).

**Retention (15.9).** The fastest-growing table is the JWT blacklist (~8 rows
per active user-day, never flushed). Nothing periodic runs today:
`flushexpiredtokens`, `clearsessions`, `prune_scheduled_jobs` (now batched),
`prune_push_devices`, `purge_staged_parcel_media` and `sweep_published_events`
exist but are not scheduled. Financial and audit history is never pruned by
automation; chat is dispute evidence. Owner and legal decisions are listed in
[data-scale.md §3–§4](k7-notes/data-scale.md).

## 15.10–15.12 Certification

- **15.10 End-to-end flows.** Every public, auth, sender, traveler, shared and
  admin flow is profiled in one PostgreSQL world by
  `test_phase_k7_certification_profile.py`, which also enforces query ceilings
  and payload guards. No regression beyond budgets; the Deal list is +1 query
  (K5 `attention`), at its ≤ 4 budget. Full table:
  [certification.md §1](k7-notes/certification.md).
- **Load (final, `e0c9914`, local box, 0 errors in every run):**

| Users | Shape | RPS | p50 / p95 / p99 |
| ---: | --- | ---: | --- |
| 100 | 2x2 | 32.1 | 27 / 100 / 160 ms |
| 250 | 2x2 | 79.4 | 72 / 240 / 340 ms |
| 400 | 2x2 | 88.3 (ceiling) | 1.4 / 1.8 / 2.1 s |
| 350 | 4x2 | 110.6 | 53 / 230 / 350 ms |
| 500 | 4x2 | 128.6 (box knee, 90 % CPU) | 770 ms / 1.2 s / 1.4 s |

  About 20 ms web CPU per request. Not measured: Redis lag (no real Redis
  locally), worker lag under backlog, KYC upload, webhooks, push fan-out,
  email, soak beyond 5 minutes.
- **15.11 Mobile.** All twelve items are verified by test (18 files, 224
  passed in C, including the new `k7_slow_network_test.dart`). Needs a real
  device: OS lifecycle order, the 20 s socket ping, image memory on a low-end
  phone, real FCM delivery.
- **15.12 Resilience.** Redis restart, worker restart, rolling deploy, provider
  slowdown, email/FCM failure, DB headroom and queue recovery are verified by
  code-path tests. Live drills: worker restart and rolling deploy
  ⟪TBD: TEST drill results⟫; Redis restart runs at the owner's Redis cutover.

## Before and after (K7, measured locally)

| Surface | Before | After | Source |
| --- | --- | --- | --- |
| Admin evidence storage checks, three slots, hung store | 26,019 ms | 3,745 ms | D |
| Same, nothing listening | 13.6 s | 2.0 s | D |
| Offers list `GET /api/matches`, 5 rows | 47,941 B / 87.6 ms | 11,869 B / 28.6 ms (3 queries both) | D |
| Find Travelers, 5 / 10 / 20 Journeys | 33 / 58 / 108 queries | 7 / 7 / 7 | E |
| `compatible-journeys`, 5 / 10 / 20 | 40 / 75 / 145 | 5 / 5 / 5 | E |
| `compatible-requests`, 5 / 10 / 20 | 34 / 56 / 101 | 8 / 8 / 8 | E |
| `GET /api/admin/users`, 50 rows | 53 queries | 3 | E |
| Notification dispatcher, 2,000-event burst | 1,278 dropped | 0 | E |
| Slow consumer | frame lost, counted delivered, push suppressed | socket closed, client catches up, push fires | A |
| Arrival events delivered live | 0 of 3 channels | 3 of 3 | A |

Response bodies for the E fixes were compared byte for byte before and after
on the same rows; all identical. The K6 per-request cost change (40 → 20 ms)
is a measurement correction (the mix), not an optimisation.

## Findings

**Confirmed and fixed:** the A, D, E and review items above and below.

**Confirmed, not fixed (flagged; see "Deferred"):** Redis resubscribe window;
reconnect catch-up burst on Django; `unread-count` ORM overhead; traveler Deal
detail at 16 queries; Admin dispute detail at 29; presence writes with no
reader; Find Travelers candidate-SQL scan; retention jobs unscheduled.

**Rejected with evidence:** SSE; presence tuning; every 15.7 technique now;
a Find Travelers ranking or result-token change; new pruning commands (the
disposable high-growth tables already have one); isolate JSON parsing (K5).

## Review fixes

Confirmed findings from the K6+K7 runtime review, fixed with a test each:

- **Email PII in logs:** send failures log a `SendFailure` (class, go-mail
  stage, SMTP code/RFC 3463 status, relay host) — never go-mail's error text,
  which lists recipients; the stub sender no longer logs the subject.
- **Email duplicate send:** an error after DATA was accepted (RSET/QUIT) is
  treated as sent (`msg.IsDelivered()`).
- **FCM sweeper race:** a handler that could still be sending when its entry
  passes the 60 s reclaim window (queued for a slot, or a long backoff) leaves
  it for the sweeper instead of pushing twice; counted.
- **WS receipt for a discarded frame:** `Conn.Send` refuses once `connCtx` is
  cancelled and checks `done` before a free buffer slot.
- **Shutdown budget:** email `sendTimeout` 30 s → 12 s (+3 s ack) fits the Go
  15 s drain and the launcher's 20 s child stop (< `drainingSeconds` 30);
  pinned by `test_deployment_safety`. FCM send + ack aligned the same way
  (15 + 3 s → 12 + 3 s, `dbad52f`).
- **Launcher Redis preflight:** a timeout/connection error during `CONFIG GET`
  is a clean `RuntimeError` naming host:port only.
- **SQLite test:** the K7-E prune test asserts the row lock only where the
  backend has `SELECT … FOR UPDATE`.
- **Alertable drops:** FCM stale/exhausted/deferred and email stale counters,
  an `email_stats` log line, and alert rows in
  `docs/k6-notes/reliability-observability.md`.
- **Chat relay drop-when-busy:** same 250 ms bounded wait before
  drop-and-count as E's notification dispatcher.

## Tests

- **Added in K7.** Go: `TestSend_DropsWhenBufferFull`,
  `TestConn_SlowConsumerIsDisconnected`, `TestSubscribeChannelsMatchDjango`,
  `TestScheduleDispatch_*`, plus review-fix tests in `internal/email`,
  `internal/notification`, `internal/chat` and `pkg/wsproto`. Django:
  `test_phase_k7_certification_profile`, `test_phase_k7d_storage_probe_bound`,
  `test_phase_k7d_admin_dispute_list_pagination`,
  `test_phase_k7d_match_list_projection`,
  `test_phase_k7e_discovery_query_counts`,
  `test_phase_k7e_admin_user_list_queries`, `test_phase_k7e_prune_batches`,
  and new `test_deployment_safety` cases. Flutter: `k7_slow_network_test`.
- **Package-level runs** (recorded in the appendices): C ran 21 + 148 Django
  tests, the Go units and 224 Flutter tests, all passing.
- **Full suites on the final tree:** Flutter ⟪TBD: full Flutter result⟫;
  Django (PostgreSQL) ⟪TBD: full Django result⟫; Go ⟪TBD: `go test ./...`,
  `go vet`⟫; `-race` and real-Redis integration ⟪TBD: CI⟫.

## Release gate (§18)

| Gate | State |
| --- | --- |
| Targeted tests green | Yes (package runs above) |
| Full regression green | ⟪TBD: full-suite results⟫ |
| Parity / correctness | E bodies byte-identical; K5 list/detail parity; Finance parity test passes in C |
| Performance improvement measured | Yes (table above) |
| CI green | ⟪TBD: CI run and result⟫ |
| Exact reviewed code merged | ⟪TBD: PR number, merge SHA⟫ |
| Railway TEST deployed | ⟪TBD: release id, deployment id⟫ |
| `/healthz` green | ⟪TBD: /healthz⟫ |
| `/readyz` green | ⟪TBD: /readyz⟫ |
| Representative smoke paths | ⟪TBD: smoke results⟫ |
| TEST-safe drills (worker restart, rolling deploy) | ⟪TBD: drill results⟫ |
| No unintended LIVE change | Nothing in K5–K7 touched LIVE so far; ⟪TBD: post-release confirmation⟫ |
| Branch cleanup | ⟪TBD: branches deleted/kept⟫ |

## Deferred work

For Codex (backend owner), none a P0:

1. Redis resubscribe window: events published while a relay's subscription is
   down are lost from realtime with no catch-up prompt (detect resubscribe,
   close local sockets; weigh against the reconnect wave).
2. Reconnect catch-up burst: jitter the post-reconnect catch-up (0–5 s) once
   online users pass ~300; split realtime so web deploys stop dropping sockets.
3. `unread-count` (~14 ms ORM compile + ~8 ms planning per call).
4. Traveler Deal detail (16 queries) and Admin dispute detail (29, untested
   with evidence and events).
5. Email outbox resend horizon (fixed 2 min × 10 ≈ 20 min): exponential
   backoff with a receipt poll.
6. `start.py` connection budget is per container; make it replica-aware
   before a second replica.
7. Find Travelers candidate SQL and page-2 re-evaluation (on trigger).

For the owner / ops: Redis provisioning and cutover with the restart proof;
schedule the retention commands; decide `core_published_event` and
read-notification retention; legal retention periods for financial, audit and
chat data; confirm `pg_trgm` on Railway Postgres; wire the documented alerts
and a free external `/readyz` monitor; presence loop (remove or lengthen).

Device checks: 20 s socket ping, real lifecycle order, low-end image memory,
real FCM delivery.

## 15.13 Final architecture verdict

**Deployment architecture.** One Railway service `shiptrip`: Caddy edge,
Django on Gunicorn `gthread` 2 workers × 2 threads, KYC gRPC recorder, finance
worker loop and reservation releaser, Go chat, notification, email and KYC
services; `drainingSeconds: 30`. One managed PostgreSQL. One shared Redis per
environment, persistent (AOF `everysec`, RDB, `noeviction`) and required by
`start.py`; TEST runs the documented embedded-Redis exception until the
owner's cutover. No PgBouncer, no replicas, no extra services.

**Not adopted, and why.** SSE (WebSocket is cheap and already recovers via
REST); service split (memory 60 % of budget, CPU idle; triggers T3–T5);
PgBouncer (22 steady / 44 rolling of 90); Gunicorn change (GIL-bound per
worker; `WEB_CONCURRENCY` is the lever); Redis finance caching and stampede
protection (nothing expensive and shared to cache); circuit breakers (slot
exhaustion needs > ~13 provider-bound requests/min); read replicas,
partitioning, `pg_trgm`, Elasticsearch, CQRS, sharding (15.7 table); Find
Travelers result tokens (freshness change needing product sign-off); isolate
JSON parsing (every real page < 8 ms on a Moto G4 estimate).

**Measured launch capacity** (local box; Railway vCPU assumed 1.0–1.5× the
per-request cost). Today's 2x2: ceiling ~88 RPS; safe 40–60 RPS ≈
**125–190 concurrently active users** (250 measured at p95 240 ms). With
`WEB_CONCURRENCY=4`: **~250–375** (350 measured at p95 230 ms). Box knee ~130
RPS at 500 users. Memory holds ~750 app-open users' sockets in 1 GiB.

**Expected 1,000-user behaviour (extrapolated, not measured).** ~320 RPS,
6.4–9.6 vCPU of web CPU: three to four 4x2 replicas, which requires PgBouncer
(third replica), a replica-aware connection budget, and the realtime split
(~0.4 GB of sockets). A server-initiated reconnect of 1,000 users is ~6,000
catch-up GETs; without jitter that is minutes of backlog at today's ceiling.
Certifying 1,000 needs a dedicated load generator against a staging copy.

**10,000-user plan.** 10 k concurrently active is ~3,200 RPS
(extrapolated): horizontal 4x2 web replicas (roughly 27–40 at 20–30 ms per
request and 60 % CPU) behind PgBouncer; realtime as its own service, chat and
notifications on one socket, catch-up jitter; PostgreSQL scaled vertically
first, replicas only on the 15.7 trigger and never for financial or matching
reads; `pg_trgm` on the admin tables at their crossovers; notification
partitioning or batched retention near 5 M rows; Find Travelers candidate
query driven from the leg time-window index; retention jobs scheduled. 10 k
*daily* users at ~10 % concurrency is the 1,000-active case above.

**Exact triggers.**

| Trigger | Action |
| --- | --- |
| T1: web CPU > 60 % of worker cores, or core-read p95 > 800 ms, 15 min | `WEB_CONCURRENCY` 2 → 3 → 4 |
| T2: T1 still firing at 4 workers | second replica, after the replica-aware budget fix |
| Third replica, or `max_connections` < 100 | PgBouncer (transaction pooling; constraints in capacity.md §2) |
| T3: memory > 75 % of limit, > ~750 online users, or deploy peak at limit | split realtime |
| T4: oldest due job > 5 min, or a loop overruns its interval | split the job loops into a worker service |
| T5: > 1 child crash a week, or visible post-deploy reconnect storms | split realtime |
| Online users > ~300 | jitter the post-reconnect catch-up |
| DB CPU > ~65 % sustained, or read-dominant | read replica for non-financial, non-matching reads |
| Notifications > ~5 M, chat > ~10 M, or a retention delete overruns | partitioning |
| Admin search table past its crossover, or console search p95 > 500 ms | `pg_trgm` GIN on the emitted expression, per table |
| Find Travelers p95 > 800 ms, or > ~1,000 Journeys in a 1-day window | candidate-query rewrite |
| Real fuzzy/multilingual search requirement | Elasticsearch |

**Remaining launch blockers outside performance.** Persistent Redis cutover
and restart proof (owner-deferred; FCM pushes queued in embedded Redis can be
lost on restart, inbox rows survive); real-device checks; alert wiring and an
external `/readyz` monitor; retention scheduling and the owner/legal retention
decisions; an Admin browser-QA pass (not re-run in K7). The launch-readiness
program owns the full list; these are the ones the K-series surfaced.

## Remaining release steps

1. Full Flutter, Django and Go suites on the final tree (running).
2. One PR for K5–K7 → CI green.
3. Merge; Railway TEST release `v1.0.0-rc.50+<sha>` of the exact reviewed tree.
4. `/healthz`, `/readyz`, representative smoke, TEST-safe drills (worker
   restart, rolling deploy).
5. Fill every ⟪TBD⟫ in this record and in the
   [K-Series Master Report](K_SERIES_MASTER_REPORT.md); branch cleanup.

Redis provisioning and cutover stay pre-launch (owner).
