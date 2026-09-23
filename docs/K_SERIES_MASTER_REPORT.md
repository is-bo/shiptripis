# K-Series Master Report — Performance & Reliability Program (K1–K7)

Plan §20. Date 2026-09-23. Every figure below comes from a phase record or its
appendix; measured local figures, TEST figures and extrapolations are labelled.
Values not yet known are marked ⟪TBD⟫ and are filled after the final release.

Phase records: [K1](PHASE_K1_RELIABILITY_FOUNDATION.md) ·
[K2](PHASE_K2_ADMIN_UX.md) · [K3](PHASE_K3_FINANCE_ADMIN_PERFORMANCE.md) ·
[K4](PHASE_K4_BACKEND_API_PERFORMANCE.md) · [K5](PHASE_K5_MOBILE_PERFORMANCE.md) ·
[K6](PHASE_K6_INFRASTRUCTURE_SCALING.md) ·
[K7](PHASE_K7_FINAL_PERFORMANCE_CERTIFICATION.md).

## Phase status

1. **K1 — Reliability foundation: released.** PR #10 merged at `fdf62e9`; TEST
   `v1.0.0-rc.46+2be5df3`. External shared Redis made mandatory, readiness
   degrades without restart, bounded provider timeouts, reusable provider
   sessions, `gthread` 2×2. Persistent Redis itself was refused by the Railway
   free plan; TEST runs the documented embedded-Redis exception.
2. **K2 — Admin UX: released.** PR #12 merged at `bf8dd8b`; TEST
   `v1.0.0-rc.47+c47eac7`. Workflow continuity after POST, shared pagination,
   sticky in-page navigation, scoped visual consistency.
3. **K3 — Finance/Admin performance: released.** PR #14 merged at `8010046`;
   TEST `v1.0.0-rc.48+fe1e5bf`. Finance Overview 3,861 → 605 ms, Payouts Hub
   5,910 → 648 ms, Payout Review detail 780 → 24 queries.
4. **K4 — General backend/API performance: released.** PR #16 merged at
   `89de1ec`; TEST `v1.0.0-rc.49+89de1ec`. Chat inbox 11 → 1 query, Journey
   list −29 % bytes, catalogue ETags (repeat fetch 0 bytes).
5. **K5 — Mobile performance: complete locally, release pending.** Branch
   `claude/k5-mobile-performance`, draft PR is-bo/shiptripis#19. Cold start
   26 → 6 requests; Flutter full suite 1069 passed at K5 end.
6. **K6 — Infrastructure, workers, observability, load: complete locally,
   release pending.** Redis cutover ready (owner-deferred), bounded worker
   retries, 30 s drain, safe access log, ops telemetry, final capacity model
   (`e0c9914`).
7. **K7 — Realtime, high-scale, certification: complete locally, release
   pending.** Packages A–E and review fixes integrated; verdicts in the K7
   record.
8. **Final `main` SHA:** ⟪TBD: merge SHA of the K5–K7 PR⟫ (today `b5e33e4`).
9. **Deployed Railway TEST release:** ⟪TBD: `v1.0.0-rc.50+<sha>`, deployment
   id, `/healthz`, `/readyz`, smoke and drill results⟫.

## Verdicts by area

10. **Reliability:** sound. No restart-loop dependency on degradable services;
    retries bounded with backoff and idempotency; failure isolation acceptable
    within the combined container. Exception: Redis/queue durability (item 15).
11. **Admin UX:** K2 continuity and consistency stand; K3–K7 changed no
    console behaviour. Not browser-re-verified in K7.
12. **Finance performance:** within K3 budgets, re-measured in K6 and K7
    (Finance Overview ~0.5 s / 23 queries, Payouts Hub ~0.6 s / 18). No Redis
    caching needed.
13. **Backend/API:** major N+1s gone and pinned by flat-count tests (K4, K5,
    K7-E); pagination reaches every record (K5 Deal scope, K7-D dispute list);
    Offers list payload −75 % (K7-D); matching output byte-identical.
14. **Mobile:** no N+1 HTTP cascades, no root rebuilds, startup not blocked on
    the network, lazy lists, display-size photo decode, cancelled/shared reads,
    one bounded checkout loop, robust socket lifecycle. Four device checks
    remain (item 32).
15. **Redis durability:** **not resolved on any deployed environment.** Code,
    boot gate (refuses unreachable Redis or `allkeys-*`), stream inspector and
    cutover/restart-proof runbook are ready; provisioning is owner-deferred to
    pre-launch. Until then FCM push obligations in embedded Redis can be lost on
    restart (inbox rows survive; email is backed by PostgreSQL).
16. **Workers/queues:** bounded (FCM cap 5 with jitter, stale drops, SMTP 5xx
    permanent, `EMAIL_TIMEOUT` 20 s), drained within `drainingSeconds` 30,
    observable (`ops_snapshot`, `email_stats`, drop counters). Lag under
    backlog not measured.
17. **Realtime:** keep WebSocket. Slow-consumer silent drop and 3
    unsubscribed arrival channels fixed; burst absorption in both relays;
    Go survives reconnect storms. Open: Redis resubscribe window, Django
    catch-up burst.
18. **DB connections:** 22 steady / 44 rolling of a 90 budget per container;
    at most 5 active backends at 129 RPS. No PgBouncer until a third replica.
    `start.py`'s check is not replica-aware (fix before replica 2).
19. **Load test (local, screen-shaped mix, 0 errors in every run):** 100 users
    2x2 p50/p95/p99 27/100/160 ms; 250 users 2x2 72/240/340 ms; 2x2 ceiling
    ~88 RPS (400 users); 350 users 4x2 p95 230 ms; box knee ~130 RPS at 500
    users (box-limited); ~20 ms web CPU per request.
20. **Launch capacity (extrapolated):** ~125–190 concurrently active users on
    today's 2x2; ~250–375 with `WEB_CONCURRENCY=4` (env only).
21. **1K-user readiness:** not certified. ~320 RPS needs three to four 4x2
    replicas, PgBouncer, a replica-aware budget and the realtime split;
    extrapolated, not measured.
22. **10K-user plan:** horizontal web replicas behind PgBouncer, realtime as its
    own service (one socket per user, catch-up jitter), vertical PostgreSQL
    first, `pg_trgm` and retention/partitioning on their triggers, Find
    Travelers candidate-query rewrite. Details: K7 §15.13.
23. **Read replicas:** not adopted. Trigger: DB CPU > ~65 % sustained or
    read-dominant; never for financial or matching reads.
24. **CQRS:** not adopted; strong consistency required for Deal and financial
    state; no projection justified.
25. **Sharding:** not adopted; single-primary financial locking has no
    replacement and the DB is far from saturation.
26. **Partitioning:** not adopted; per-recipient reads flat from 1 M to 5 M
    notifications. Trigger: > ~5 M notifications, > ~10 M chat, or an
    overrunning retention delete.
27. **SSE:** not adopted; only one of five conditions holds.
28. **Search infrastructure:** no Elasticsearch. `pg_trgm` is the first
    technique to adopt, per admin table at its measured crossover (~20 k audit
    rows first).
29. **Largest latency improvement:** normal path — K3 Payouts Hub 5,910 →
    648 ms (−89 %); failure path — K7-D admin evidence storage checks against a
    hung store 26,019 → 3,745 ms.
30. **Largest query reduction:** K3 Payout Review detail 780 → 24 queries.
    Largest growth removed: K7-E Find Travelers 108 → 7 at 20 Journeys, now
    constant in the number of candidates.
31. **Largest mobile improvement:** cold start 26 → 6 requests (19 per-Deal
    detail reads removed); photo decode ~12–17 MB → ~2.5 MB per image.

## Remaining work

32. **Remaining performance defects** (none P0):
    - Admin KYC / payout-review evidence checks are bounded (≤ ~3.7 s against
      a hung store) but still on the request path.
    - Traveler Deal detail 16 queries; Admin dispute detail 29 queries.
    - `unread-count` ~38–42 ms, mostly ORM compile and planning.
    - Redis resubscribe gap: no catch-up prompt after a relay-only resubscribe.
    - Reconnect catch-up burst on Django (5–7 GETs per user after a
      server-side drop): estimated at ~100–130 online users as ~700 requests
      in ~1 s, saturating web for 15–20 s at the pre-re-run ceiling; ~6,000 at
      1,000 users.
    - Device checks: 20 s socket ping, real lifecycle order, low-end image
      memory, real FCM delivery.
    - Email outbox resend horizon ~20 min (fixed 2-minute retries).
    - `start.py` connection budget per container, not per replica.
    - Retention jobs exist but none is scheduled; JWT blacklist grows ~8 rows
      per active user-day.
    - `pg_trgm` availability on Railway Postgres unconfirmed.
    - Find Travelers candidate SQL scans every overlapping Journey; page 2
      re-evaluates.
    - Not measured: worker lag under backlog, real-Redis latency, soak > 5 min,
      KYC upload, webhooks, push fan-out, email under load.
33. **Remaining non-performance launch blockers:** persistent Redis
    provisioning, cutover and restart proof (owner; may need a plan upgrade);
    alert wiring and an external `/readyz` monitor; retention scheduling and
    the owner/legal retention decisions (financial, audit, chat, published
    events, read notifications); real-device QA; Admin browser-QA pass. The
    launch-readiness program owns the complete list.
34. **Unexpected product/domain changes:** NO. Matching, ranking, pricing,
    lifecycle, permissions and audit unchanged; K7-E bodies byte-identical.
35. **LIVE financial changes:** NO. The K1–K4 records state no LIVE, provider
    mode or money change; K5–K7 have not deployed (⟪TBD: post-release
    confirmation⟫).
36. **Branch cleanup:** K1–K4 branches deleted locally and on origin (none
    remain). K5/K6 branches: ⟪TBD: after merge⟫. Owner stash, `upstream/*` and
    unrelated branches preserved.
37. **Documentation:** phase records K1–K7 with appendices
    (`k6-notes/`, `k7-notes/`), raw load runs in `k6-notes/capacity-runs/`,
    `IMPLEMENTATION_STATUS.md` updated. Release record for K5–K7:
    ⟪TBD: release record⟫.
38. **Recommended next engineering program:** a launch-readiness program:
    (1) Redis cutover with the restart proof; (2) alerts and uptime monitor;
    (3) schedule retention; (4) device and Admin browser QA; (5) Codex backlog
    from item 32 (resubscribe prompt, catch-up jitter, `unread-count`,
    replica-aware budget, email backoff, Deal/dispute detail queries);
    (6) a staging load test with a dedicated generator before any 1,000-user
    claim.

## Verdict

The verdict lines assume the pending release gate (item 9) comes back green;
if it does not, the K5–K7 lines revert to NO until it does.

**K-SERIES PERFORMANCE / RELIABILITY PROGRAM PASS** — with one owner-deferred
exception (persistent Redis cutover) carried into launch readiness.

**Reliability foundation complete? YES** — K1 scope released; the one open
§19 reliability item, Redis/queue durability, is the Redis line below.

**Admin UX complete? YES**

**Finance/Admin performance complete? YES**

**General backend/API performance complete? YES** — remaining items in 32
are non-P0.

**Mobile performance complete? YES** — four real-device checks remain.

**Persistent Redis/infrastructure scaling complete? NO** — everything except
the Redis cutover is done; the cutover is ready and owner-deferred to
pre-launch.

**Realtime/high-scale certification complete? YES** — for launch scale;
1,000 users is extrapolated, and the Redis-restart drill runs at the cutover.

**No unresolved P0 performance/reliability defects? YES** — the Redis
durability exception is a known, owner-accepted launch blocker, not an
untracked defect.

**No unintended product/domain regressions? YES**

**Ready for final launch-readiness program? YES** — the performance program has
done what it can without production traffic: launch-scale capacity is
measured with headroom, scale triggers are explicit, and every remaining item
(Redis cutover, device QA, alerts, retention) is launch-readiness work by
nature.
