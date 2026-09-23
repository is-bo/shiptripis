# K6 package R — persistent shared Redis: cutover readiness

**Scope:** plan §14.1 (persistent shared Redis) and §14.2 (responsibility map).
**Base:** `claude/k6-infrastructure-scaling` at `b5e1118`.
**Owner decision (2026-09-23):** managed Redis is provisioned and cut over
before launch, not during K6/K7. This package delivers code/config readiness,
the stream inspector and the runbook. No Railway resource or variable was
touched; LIVE was not touched.

This extends [PHASE_K1 §2 and §11](../PHASE_K1_RELIABILITY_FOUNDATION.md). K1's
topology decisions stand: one `REDIS_URL` for every process, an explicit
`SHIPTRIP_EMBEDDED_REDIS=true` switch for the loopback daemon, and no silent
fallback from shared to embedded.

## 1. Responsibility map

All keys live in the one logical DB named by `REDIS_URL` (Railway: DB 0).
"Owner" is the writing process inside the combined `shiptrip` container.

| Use | Owner → reader | Keys / stream / group | TTL / cap | Class | If lost |
| --- | --- | --- | --- | --- | --- |
| DRF throttles | Django web | `shiptrip:1:throttle_<scope>_<ident>` | rate window (60 s–1 h) | disposable security state | counters reset. A Redis outage fails requests closed. |
| Other default-cache keys | Django web | `shiptrip:1:readyz:<release>` (5 s), `shiptrip:1:connect_return_refresh:<id>` (15 s) | as listed | disposable | nothing. The payout refresh cooldown is a convenience, not a lock. |
| Route-provider cache | Django web/workers | `shiptrip-routing:1:route-provider:<provider>:<ns>:<op>:<sha256>` | `ROUTE_PROVIDER_CACHE_TTL_SECONDS` (86 400) | disposable, fail-open | repeat provider calls |
| KYC upload limiter | Go `kyc` | `shiptrip:rate-limit:{kyc-upload}:v1:…` (Lua fixed window) | window (PEXPIRE) | disposable security state | budgets reset. A Redis outage rejects uploads. |
| Realtime pub/sub | Django → Go `chat`/`notification` | channels `chat.message.new`, `trip.*`, `parcel.*`, `match.*`, `offer.*`, `payment.*`, … (not keys) | none | ephemeral signal | live update missed. Inbox rows are in PostgreSQL, and the `notification_dispatch` job retries publishing. |
| WS delivery receipts | Go `chat`/`notification` → FCM consumer, `sweep_published_events` | `delivered:<event_id>:<user_id>` | 60 s | ephemeral dedup | possible duplicate push |
| Presence | Go `notification` | `presence:<user_id>` | 15 s | ephemeral | rebuilt by heartbeat |
| FCM worker heartbeat | Go `notification` → admin deep health | `fcm:worker:<consumer>`, `fcm:worker:active` | 45 s | ephemeral | health shows "degraded" until the next loop |
| Go health sentinels | each Go service | `healthz:{chat,email,kyc,notification}` | 5 s | ephemeral | none |
| Email send marker | Go `email` | `email:sent:<event_id>` | 10 min | dedup hint | the PostgreSQL receipt is authoritative |
| **Email transport** | Django `OutboundMessage` dispatch → Go `email` | stream `email:send`, group `email-send-workers`, consumer `EMAIL_CONSUMER_NAME` or `HOSTNAME` | MAXLEN ≈ 10 000 | transport backed by a DB obligation | Delayed only: no receipt within 2 min makes Django re-enqueue the same event ID. Secret-bearing kinds (verification, reset, invitation, delivery code) never use this stream. |
| **Push transport** | Django `notification_dispatch` job → Go `notification` | stream `notif:fcm`, group `notif-fcm-workers`, consumer `FCM_CONSUMER_NAME` or `HOSTNAME` | MAXLEN ≈ 10 000 | **durable obligation.** This is the only copy once the DB job succeeded. | **push permanently lost** (the in-app inbox row survives) |
| Push feedback | Go `notification` → Django `run_finance_worker` | stream `notif:fcm:results`, group `notif-fcm-results-django`, consumer `notif-fcm-results-django-1` | MAXLEN ≈ 10 000 | durable-ish, idempotent | device `last_success_at`/invalid marks are stale until the next send |

- **Locks and idempotency:** Redis holds none. Financial idempotency, capacity,
  holds and payouts stay PostgreSQL-authoritative (K1).
- **Pending-entry recovery:** this already existed and has been verified. Both
  Go consumers run an XAUTOCLAIM sweeper every 30 s, which claims entries idle
  for more than 60 s from any consumer, including dead hostnames from earlier
  deploys. The Django feedback consumer re-reads its own PEL (`0`) before
  reading new entries (`>`). Groups are created with `MKSTREAM`, and
  `BUSYGROUP` is ignored.

### Flags

1. **A durable obligation shares an instance with cache.** `notif:fcm` has no
   TTL. Under any `allkeys-*` policy Redis could evict it silently. Under the
   `volatile-*` policies and `noeviction` it cannot, because every
   disposable key above carries a TTL (checked: no Django `timeout=None`, and
   every Go `SET` uses EX/PEXPIRE). The fix is enforced below.
2. **`cache.clear()` is a FLUSHDB.** Django's `RedisCache.clear()` flushes the
   whole shared DB, including streams, groups and PELs. No code calls it (it was
   searched for). Operator rule: never run `cache.clear()`, `FLUSHDB` or
   `FLUSHALL` against TEST or LIVE Redis.
3. **Key collisions.** Every purpose has its own prefix. `shiptrip:1:` (Django)
   and `shiptrip:rate-limit:` (KYC) share a first segment but not a second, so
   they cannot collide. The real collision risk is one Redis serving two
   environments: TEST and LIVE, or a PR environment, would consume each
   other's streams. Use one Redis per environment.
4. **Consumer names default to `HOSTNAME`.** Each deploy leaves one idle
   consumer per group. This is harmless: the sweeper reclaims its PEL. Prune
   only with `XGROUP DELCONSUMER` when that consumer shows `pending=0`, because
   deleting a consumer with pending entries discards them.
5. **The stream cap is a durability boundary.** `MAXLEN ~10000` trims the
   oldest entries even if they are unread or pending, so a backlog over 10 k
   (a worker down for hours at scale) drops push work. This is acceptable for
   V1 volume. Watch `lag` in the inspector.
6. **A consumer-group start race was found and fixed (§2).**
   `XGROUP CREATE … $` skipped anything Django appended before the Go worker
   created its group. `finance-jobs` starts before `notification`/`email`, so
   the first pushes on an empty Redis were silently skipped. This happened on
   every embedded-Redis deploy and would happen again at cutover. The Go
   integration tests already had to work around the same race.
7. **A lost group was fatal-by-loop.** If a shared Redis came back without its
   data, `XREADGROUP` returned `NOGROUP` forever. The worker logged every second
   and never recreated the group, while Django kept appending unread work.
   Fixed (§2).
8. `sweep_published_events` (manual, not scheduled) SCANs with `COUNT 10`. Each
   missing receipt costs O(keyspace/10) round trips, which are slower over the
   private network than over loopback. This is minor and was left unchanged.

## 2. Code and config changes

| File | Change |
| --- | --- |
| `backend/services/pkg/redisbus/redis.go` | `GroupStartID` creates a group with a 10-minute look-back instead of `$` (skips early entries) or `0` (replays up to 10 k old pushes after a group rename). Adds `IsNoGroup`. |
| `backend/services/internal/email/consumer.go`, `internal/notification/fcm.go` | Create the group at `GroupStartID`. On `NOGROUP`, recreate it and keep consuming. A narrow `streamClient` seam makes this unit-testable without Redis. |
| `backend/railway/start.py` | `probe_shared_redis` runs in shared mode before migrations. It fails startup if Redis is unreachable (30 s retry for private-network warm-up), rejects the credentials, or uses an `allkeys-*` policy. It prints policy, maxmemory, AOF and RDB settings (never the URL or password), and warns loudly when persistence is off or CONFIG is hidden. Embedded mode is unchanged. |
| `backend/monolith/apps/core/management/commands/inspect_redis_streams.py` | New read-only inspector. Per stream it reports length, first-entry age and last ID. Per group it reports pending, lag, last-delivered ID and oldest pending (ID, owner, age, idle, deliveries). It also lists consumers with their idle time, the eviction verdict, AOF/RDB status and the FCM heartbeat. `--json`, `--stream`, `--url`, `--require-drained` (non-zero exit on any pending, undelivered or ungrouped entries). |
| Tests | Go: `pkg/redisbus/group_test.go`, `internal/email/consumer_test.go`, `internal/notification/fcm_consumer_test.go`. Django: `apps/core/tests/test_inspect_redis_streams.py` and 7 launcher tests in `apps/finance/tests/test_deployment_safety.py`. |

**Decisions**

- **K1's two-variable switch is kept, not collapsed to one.** Embedded mode
  refuses an external `REDIS_URL`, so a half-applied change fails the boot
  loudly and Railway keeps the previous deployment. Stage both changes and
  deploy once.
- **Startup fails; it never falls back.** Go workers already exit when PING
  fails, but only after the migrations have run. The pre-flight names the
  problem first.
- **`/readyz` is unchanged.** It is public and polled by Railway, and the
  eviction policy changes only by operator action. The boot gate checks the
  policy on every deploy, the inspector shows it on demand, and admin deep
  health already reports FCM stream pending and lag (§14.13).

## 3. Required Redis settings (one managed Railway Redis per environment)

- Use the Railway Redis template in the same project and environment, on the
  private network (`redis.railway.internal:6379`, plain `redis://`). The app
  also accepts `rediss://` with a password: redis-py and go-redis both parse
  TLS and credentials from the URL.
- Attach a volume at the data directory (the template uses
  `$RAILWAY_VOLUME_MOUNT_PATH`, normally `/data`).
- Start command (the template's command plus AOF and an explicit policy):

  ```sh
  /bin/sh -c "rm -rf $RAILWAY_VOLUME_MOUNT_PATH/lost+found/ && exec docker-entrypoint.sh redis-server --requirepass $REDIS_PASSWORD --dir $RAILWAY_VOLUME_MOUNT_PATH --appendonly yes --appendfsync everysec --save 60 1 --maxmemory-policy noeviction"
  ```

- **Policy: `noeviction` (the Redis default).** When memory is full, writes
  fail loudly: throttled requests error, and XADD fails and is retried from
  PostgreSQL. Nothing is lost silently. `volatile-lru` is the only acceptable
  alternative. It evicts only TTL keys (cache, throttles, presence) and never
  streams, but it softens throttles under memory pressure. `allkeys-*` is
  refused at boot. A separate logical DB does **not** isolate eviction, because
  `maxmemory` is per instance. Railway's own guide prefers separate cache and
  store instances, which the owner's one-instance constraint rules out.
- Optional `--maxmemory` at about 75% of the Redis service's memory limit, so
  pressure surfaces as write errors rather than an OOM kill. Current Redis use
  is a few MB.

## 4. Cutover runbook (pre-launch window; TEST first, never combined with a provider or LIVE change)

All commands run through `railway ssh` into the `shiptrip` service (cwd
`/app`). The image's `redis-server` package brings `redis-cli`; confirm this
with `redis-cli --version`. In embedded mode the shell has no `REDIS_URL`
(start.py injects it only into children), so prefix commands with
`REDIS_URL=redis://127.0.0.1:6379/0`.

**Pre-checks**

1. Provision Redis as in §3. Check it from the app shell with
   `python manage.py inspect_redis_streams --url "<new private URL>"`. Expect
   `eviction=safe`, `appendonly=yes`, `appendfsync=everysec`, a non-empty
   `save`, `aof_last_write=ok` and every stream absent.
2. Confirm `ROUTE_PROVIDER_CACHE_URL` is unset on `shiptrip`, or identical to
   the new `REDIS_URL`. Production settings refuse any other value.
3. Drain the embedded instance in a quiet window:
   `REDIS_URL=redis://127.0.0.1:6379/0 python manage.py inspect_redis_streams --require-drained`.
   Repeat until it exits 0. Pending `email:send` work is still recoverable
   (it is re-enqueued from `OutboundMessage`). Pending `notif:fcm` work is not:
   wait for it to drain. Do not migrate entries by hand, because
   `delivered:`/receipt state would not follow them.

**Variables:** stage these on `shiptrip` and deploy once.

- `REDIS_URL=${{Redis.REDIS_URL}}`. Use the private reference. The service
  name must match.
- `SHIPTRIP_EMBEDDED_REDIS`: delete it, or set it to `false`.
- Change nothing else in the same deploy.

**Verification**

1. Boot log: one `shared redis redis.railway.internal:6379 maxmemory-policy=noeviction … appendonly=yes appendfsync=everysec save='…'` line, no `WARNING`, and no `starting redis`.
2. `/healthz` returns 200 with the release. `/readyz` returns 200 `ready`
   with `rate_limit_cache: ok`. The Admin system status shows "Shared Redis".
3. `python manage.py inspect_redis_streams`: groups exist for each enabled
   worker (`email-send-workers` if `EMAIL_ENABLED`, `notif-fcm-workers` if
   `FCM_ENABLED`) with `drained=yes`. The FCM heartbeat TTL is above 0 when
   push is enabled.
4. Email round trip: trigger a stream-borne kind. For example, approve or
   reject a TEST KYC submission (`kyc_status`). Verification, reset,
   invitation and delivery-code mail bypass the stream. Expect the
   `OutboundMessage` to carry a `transport_event_id`, its `PublishedEvent` to
   get `delivered_at` within seconds, and `email:send` to show its
   last-delivered ID advanced with `pending=0`.
5. Push round trip (only if FCM is enabled on TEST): send a chat message to a
   TEST user whose app is closed. Expect the push to arrive and `notif:fcm` to
   show its entries advanced with `pending=0`.
6. Pub/sub:
   `redis-cli -u "$REDIS_URL" PUBSUB NUMSUB chat.message.new trip.created`
   should show at least 1 subscriber each. A chat message should appear live
   in a second session.
7. Throttle and route cache:
   `redis-cli -u "$REDIS_URL" --scan --pattern 'shiptrip:1:throttle_*' | head`
   and `--pattern 'shiptrip-routing:1:route-provider:*'` both show keys after
   API and matching traffic. A repeated route query makes no second provider
   call.

**Restart proof** (once, after verification). Markers carry no `payload` and
no `event_id`, so the live workers ack-and-drop them without sending mail or
push.

1. Generic persistence: create a proof stream and group, leave one entry
   pending, and set a sentinel.

   ```sh
   redis-cli -u "$REDIS_URL" XADD k6:proof '*' marker k6
   redis-cli -u "$REDIS_URL" XGROUP CREATE k6:proof k6-proof 0
   redis-cli -u "$REDIS_URL" XREADGROUP GROUP k6-proof c1 COUNT 1 STREAMS k6:proof '>'
   redis-cli -u "$REDIS_URL" SET k6:sentinel 1 EX 3600
   ```

2. Real-consumer PEL: for each live group (shown here for email; for push use
   `notif:fcm notif-fcm-workers`), and only while the inspector shows the
   group `drained=yes`, run:

   ```sh
   printf 'MULTI\nXADD email:send * k6_marker restart-proof\nXREADGROUP GROUP email-send-workers k6-proof COUNT 1 STREAMS email:send >\nEXEC\n' | redis-cli -u "$REDIS_URL"
   ```

   The in-transaction read claims the marker before any blocked live worker
   can, so it sits pending on consumer `k6-proof`. The reply might show an
   entry other than the marker. That happens when a real entry arrived
   between the drain check and the transaction. It is then real work
   borrowed by `k6-proof`, and the sweeper hands it back after 60 s, so it is
   delayed but not lost. Record
   `python manage.py inspect_redis_streams --json`. It should show pending=1
   on `k6-proof` for each group, and pending=1 on `k6:proof`
   (`--stream k6:proof`).
3. Restart the Redis service (Railway restart/redeploy of **Redis only**). The
   app keeps running. go-redis and redis-py reconnect, and API requests may
   fail closed for the few seconds Redis is down.
4. Re-run the inspector. The same stream lengths, the same groups, the same
   pending IDs on `k6-proof`, and `TTL k6:sentinel` above 0 prove that
   entries, groups and PELs survived.
5. Within about 90 s (60 s idle plus the 30 s sweep), each live worker's
   sweeper claims its marker. Logs show `email: bad payload; acking to drop` /
   `fcm: stream entry missing event_id; acking to drop`, and the inspector
   shows `pending=0`.
6. Clean up:

   ```sh
   XGROUP DELCONSUMER email:send email-send-workers k6-proof
   XGROUP DELCONSUMER notif:fcm notif-fcm-workers k6-proof
   DEL k6:proof k6:sentinel
   ```

   Only run each DELCONSUMER after the inspector shows that consumer at
   pending 0. Record the inspector output and the volume and persistence
   evidence, then mark the K1 durability finding resolved.

**Rollback** (stage these and deploy once): set `SHIPTRIP_EMBEDDED_REDIS=true`
and delete `REDIS_URL`.

- First run `python manage.py inspect_redis_streams --require-drained` against
  the shared instance, and wait until it exits 0.
- What can be stranded on the shared instance:
  - `notif:fcm` pending or undelivered entries: pushes are lost, but the inbox
    rows survive.
  - `email:send` entries: not lost. They are re-enqueued from `OutboundMessage`
    into the embedded instance after 2 min.
  - `notif:fcm:results` feedback: device-health marks are delayed.
  - Cache, throttles and presence: disposable.
- **Keep** the shared Redis service. On a later re-cutover its groups still
  exist, so leftover entries are delivered or claimed then. If that happens
  much later, trim `notif:fcm` first (`XTRIM notif:fcm MAXLEN 0`) so users do
  not get stale pushes.
- Rolling-deploy overlap applies in both directions. The outgoing container
  keeps producing to its own Redis until it stops, so push work enqueued in
  those final seconds follows the old instance. Cut over in a quiet window.

## 5. Verification performed here (local, no Redis available)

- `go vet ./...` and `go vet -tags integration ./...` are clean.
  `go test -count=1 ./...` passes in all packages. The new tests cover:
  - the look-back start ID;
  - `NOGROUP` detection;
  - both consumers recreating a lost group and keeping consuming;
  - both sweepers following the XAUTOCLAIM cursor across pages and
    reprocessing every claimed entry.
- Django (`--ds=config.settings.test_local`): the inspector tests, `/readyz`
  tests and the full `test_deployment_safety.py` (59 passed, launcher probe
  included). `ruff check .` is clean.
- **Not run here:** the real-Redis Go integration tier and `-race` (no
  redis-server or Docker on this workstation; CI covers both), and anything
  on Railway. The restart proof above is the evidence the cutover must
  produce.
