# CLAUDE.md — instructions for Claude instances on ShipTrip

If you are a Claude instance opening this repo, **read this file fully before
acting.** It encodes the operational rules that survive across sessions and
across the two contributors. ARCHITECTURE.md is the *what*; this file is the
*how*.

---

## 0a. Open notes (Claude B → Claude A handoff)

**Dispatcher migrated to generic `targets` routing (2026-05-28).** Go was
only routing 2 of Django's 16 published channels, and was reading legacy
per-channel keys (`recipient_id`/`sender_id`/`traveler_id`) instead of
the canonical `targets:[uid,...]` field that `redis_bus.publish_after_commit`
attaches to every envelope. Now:
- `notification/dispatcher.go` subscribes to all 16 channels (see
  `subscribeChannels`, mirrors `apps/core/channels.py`).
- Single generic `dispatch` path: unmarshal `targetsEnvelope{event_id, targets}`,
  fan the raw payload to each target's local sockets via `hub.Send`, schedule
  one receipt write through the existing `receiptConcurrency=64` pool.
- Per-channel `offerAcceptedPayload` / `offerCreatedPayload` structs and
  their dispatchers deleted — payload semantics (match_id, offer_id, code,
  …) are mobile's concern. Go forwards the raw payload as the envelope body.
- `dispatch` logs at WARN when `targets` is missing (so any missed Django
  migration is visible) and at DEBUG when targets exist but no socket on
  this pod owns them (another pod likely already delivered).
- Mobile previously silently missed: `handover.code_issued`,
  `match.in_transit`, `match.completed`, `payment.captured`,
  `payment.refunded`, `match.created`, `offer.updated`, parcel + trip
  events, `kyc.status_changed`. All wired now.
- Confirmed every Django `publish_after_commit` call (14 sites across
  trips/parcels/matching/payments/verification) passes `targets=[uid,...]`
  as kwarg. The audit task is resolved.

**KYC gRPC client wired + hardened.** Done across recent commits:
- `task contract:go-grpc` target added to `backend/Taskfile.yml` (mirrors the existing python-grpc target; uses host `protoc` + `protoc-gen-go` + `protoc-gen-go-grpc`) and now runs in `check-drift` so generated Go stubs stay in lockstep with the proto.
- Generated stubs at `backend/services/internal/kyc/kycpb/`.
- `backend/services/internal/kyc/grpc_client.go` implements the `Recorder` interface (translates the typed-string `DocumentType`/`Status` ↔ proto enums, attaches `authorization: Bearer <token>` metadata per RPC, 16 MiB max msg size both sides per §G5).
- **Keepalive**: 30s pings / 10s timeout / `PermitWithoutStream: true` so idle TCP between rare KYC submissions isn't silently dropped by conntrack/NAT.
- **Retry policy** via gRPC service-config: 4 attempts on `UNAVAILABLE`/`DEADLINE_EXCEEDED`, 0.2s→2s exponential. Safe because Django dedupes on `idempotency_key` (commit `d6f4dc6`).
- `cmd/kyc/main.go` dials at boot via `LoadKYCGRPC()` — `KYC_GRPC_TARGET` is **required**, missing config fails service start (§9 "evidence > assertions"). `NoopRecorder` is retained for unit-test scaffolding but no longer the default.
- `GRPC_AUTH_MODE` defaults to `mtls` per §G5 — missing value in prod surfaces as a startup error (mtls is still TODO) instead of silently downgrading to bearer.
- mTLS still a TODO in both `grpc_client.go` and `runkycgrpc.py` (§G5).

**Set in dev `.env`:** `KYC_GRPC_TARGET=django:50051`, `GRPC_AUTH_MODE=bearer` (must be set explicitly — no implicit default), `GRPC_BEARER_TOKEN=<shared with Django>`.

**Go services hardened from senior review (commit `6239048`).** Each fix is a
silent failure mode that production traffic would have surfaced:
- `kyc/handler.go`: every uploaded S3 key is tracked, deferred cleanup gated on
  a success flag. Previously a back/selfie upload failing *after* front landed
  left an orphan in MinIO.
- `kyc/handler.go`: 10s `context.WithTimeout` around `RecordSubmission`. The
  gRPC SDK's own retry (4 attempts × ≤2s backoff) is fenced in by this.
- `cmd/kyc/main.go`: full `http.Server` timeouts (Read 60s, Write 60s, Idle
  120s). Previously only `ReadHeaderTimeout` was set.
- `notification/dispatcher.go`: **`offer.created` is now wired.** Routing uses
  the single `recipient_id` Django sends in `apps/matching/views.py:240,375`
  — not the speculated `targets:[user_id,...]` shape. Per-channel struct/switch
  stays readable while the channel set is small.
- `notification/dispatcher.go`: `markDelivered` runs in its own goroutine so a
  slow Redis or Postgres can't stall the pub/sub loop.
- `notification/handler.go`: presence `Refresh` uses a detached short ctx per
  tick (mirrors the `Drop` pattern) so graceful shutdown doesn't gap presence.
- `cmd/notification/main.go`: `IdleTimeout` on `/healthz`+`/readyz`. WS conns
  are hijacked at upgrade so `Read/WriteTimeout` would only risk the upgrade.
- `pkg/wsproto/wsproto.go`: writer drains `c.send` on exit and logs the
  dropped count. Previously queued messages vanished silently on write error.
- `pkg/storage/s3.go`: `Put` uses a fail-fast `limitErrReader` returning
  `ErrTooLarge` at `maxPutBytes+1` instead of post-PutObject truncation +
  Delete. Saves bandwidth and prevents transient orphans on every oversize PUT.

Skipped from review:
- `pkg/storage/s3.go` `errors.AsType` — verified to exist in stdlib, agent was
  wrong.
- Unexporting `NoopRecorder` — still referenced as a unit-test scaffold by
  HANDOVER.md and `client.go` doc-comments.

Smaller follow-ups (still on the list, not blockers):
- ~~`offerAcceptedPayload.Ts` / `offerCreatedPayload.Ts` unmarshalled but
  unused~~ — fixed in `dbd1097`.

**Senior-Go review pass (commits `c7e80a8` + `dbd1097`).** Punch list from
a from-scratch review of the whole Go workspace, focused on concurrency
correctness, scalability hazards, and goroutine lifetime:
- `notification/fcm.go`: `handle()` was called serially inside the
  XReadGroup batch loop — with `xreadCount=16` and a 2s grace period
  per entry, a full batch serialized to 32s+ (throughput ~0.5 msg/s/pod).
  Now dispatched concurrently through a `handleConcurrency=32` semaphore;
  `sync.WaitGroup` tracked by `Run`/`Sweep` so XAck can't be cut short
  on shutdown.
- `notification/fcm.go`: `ack()` had a dead conditional ctx reassignment
  that never affected the XAck call — removed; always uses the detached ctx.
- `notification/dispatcher.go` + `chat/dispatcher.go`: `go d.markDelivered(...)`
  was unbounded goroutine fan-out per pub/sub message; a Redis burst with
  slow Postgres would spawn thousands the `shutdownTimeout` never waits for.
  Now bounded via `receiptConcurrency=64` semaphore + `WaitGroup` drained
  on `Run` exit. Drop-on-saturation logs `event_id` + `sockets` so G6b's
  daily audit catches anything missed.
- `notification/handler.go`: `refreshPresenceLoop` was fire-and-forget;
  a hung Redis refresh could outlive the handler. Now tracked with a
  per-handler `sync.WaitGroup` and waited before `Drop` fires.
- `pkg/storage/s3.go`: `limitErrReader` could return `(n>0, ErrTooLarge)`
  in the same Read call (violates `io.Reader` contract) and allowed one
  extra byte past `max`. Rewritten with a probe-byte read after `max` so
  an exact-fit body returns `io.EOF` and an oversize body returns `(0,
  ErrTooLarge)`. Three internal tests lock the contract.

Reviewed and rejected:
- Hub `Send` slice alloc (per fan-out, not per message); calling `c.Send`
  under RLock would let a slow producer hold the read lock.
- `cmd/notification/main.go` cancelling rootCtx on nil fcm return — the
  cancel is idempotent and an unexpected nil return SHOULD cascade.

**FCM consumer scaffolded (commit `f00b3e6`).** Gated behind `FCM_ENABLED`
(default false) so it ships dark until Claude A lands the `fcm_token` schema
and the Django publisher to `notif:fcm`:
- `notification/fcm.go`: `Consumer.Run` (XReadGroup → wait 2s → check
  `delivered:<event_id>` → send/skip → XAck) + `Consumer.Sweep` (XAUTOCLAIM
  every 30s, MinIdle 60s) per G1.
- `FCMSender` exported interface is the prod swap point; `LogOnlySender`
  is the V1 stub. Replace with Firebase Admin SDK client once schema lands.
- `ack()` uses a detached context so a cancelled parent doesn't leave
  events unacked mid-shutdown.
- `cmd/notification/main.go` drains consumer + sweeper goroutines on
  shutdown via `for range 2 { <-doneCh }`.

**Chat-service V1 landed (commit `c04a369`).** Stateless WS relay for
`chat.message.new`. Django still owns persistence — this service only fans
events to the recipient's local socket:
- `internal/chat/hub.go`: per-pod `map[user_id]map[*Conn]struct{}`,
  mirrors `notification.Hub`. Intentionally NOT shared with notification
  (clean lifecycle boundary; if a third service appears, extract `pkg/wshub`).
- `internal/chat/dispatcher.go`: uses unexported `router` + `receiptStore`
  interfaces as test seams. Production wires real `*Hub` + `*dbReceiptStore`;
  unit tests build `Dispatcher` directly with stubs (no Postgres/Redis).
- `internal/chat/handler.go`: WSHandler with **no presence refresh loop**
  (notification owns `presence:<user_id>`). A user with chat WS but no
  notification WS will get duplicate FCM — acceptable V1 tradeoff.
- `cmd/chat/main.go`: serves `:8081`, `CHAT_DB_MAX_CONNS` default 15
  (CLAUDE.md §3: 2 pods × 15 conn). Only `IdleTimeout` set on http.Server
  since WS upgrade hijacks the conn.
- 5 tests + 3 subtests cover routing, no-local-sockets skip, bad-payload
  drops, receipt-error logging, and unknown-channel dispatch.

---

## 0. Current state (handoff — last updated 2026-05-28)

### What's done

**Backend (Django monolith, `backend/monolith/`):**
- `apps/accounts` — User (sender/traveler/both), email signup, Google OAuth,
  password reset, JWT (HS256, `user_id`+`role`+`typ`+`jti` claims), ban/unban.
- `apps/core` — pricing engine, `redis_bus.publish_after_commit`,
  `published_event` audit table, channel constants.
- `apps/trips` — Airport (DZ + FR seed), Trip + Stopover + Tracking, full CRUD.
- `apps/parcels` — multi-table inheritance (Delivery + Product), full CRUD.
- `apps/matching` — Match + Offer chain, frozen pricing, partial unique
  constraints (one-accepted / one-pending per match). 21 tests.
- `apps/payments` — PaymentIntent (mock provider, instant success), idempotency
  via (provider, intent_id) + client key; PaymentEvent ledger; Refund. 14 tests.
  Swap to real Stripe = one file (`providers.py`).
- `apps/wallet` — append-only ledger (no stored balance), Hold table for
  escrow, post_save signals bridge payments → wallet open_hold and
  reverse_hold_for_refund. 12 tests.
- `apps/verification` — HandoverCode (argon2id), PICKUP + DELIVERY codes,
  6-digit numeric, 5-attempt lockout, code rotation. DELIVERY verify fires
  `release_hold_to_payee` → traveler is paid. 12 tests.
- `apps/kyc` — schema-only model (`kyc_submission`); Go service owns the API.
- `apps/admin_panel` — User ban/unban actions, KYC review surface,
  PublishedEvent audit view, site branding.
- Contracts: `contracts/sql/schema.sql` exported via `task contract:sync-db`;
  `sqlc.yaml` wires 4 Go services (chat/notif/kyc/media); query dirs ready.
- Gateway: Caddy (see `docs/decisions/0001-gateway-caddy.md`).
- All migrations reversible. Full suite green (115/115).

**Backend (Go services, `backend/services/`):**
- `cmd/notification` — WS hub + Redis pub/sub consumer. Subscribes to
  all 16 Django channels (`apps/core/channels.py`); single generic
  dispatch path routes by the canonical `targets:[uid,...]` field on
  every envelope. Writes `delivered:<event_id>` and back-fills
  `core_published_event.delivered_at` through a bounded receipt pool.
  FCM consumer scaffolded behind `FCM_ENABLED` (LogOnlySender stub;
  awaits Django publisher + fcm_token schema). G1 + G6b paths wired.
- `cmd/chat` — WS relay for `chat.message.new`. Stateless fan-out
  (Django owns persistence). Per-pod Hub mirrors notification's. 5 unit
  tests + 3 subtests via test-seam interfaces (no Postgres/Redis needed).
- `cmd/kyc` — multipart `/kyc/submit`, streams images to MinIO under
  `kyc-docs/<user_id>/<idempotency_key>-<field>.<ext>` (deterministic
  so retries overwrite, no orphans), then calls Recorder. Real gRPC
  client wired with keepalive + retries; `KYC_GRPC_TARGET` required at
  boot. `NoopRecorder` retained for unit-test scaffolding only.
- Shared: `pkg/redisbus`, `pkg/wsproto`, `pkg/storage` (S3 abstraction
  per G4), `pkg/auth` (HS256 + 30s leeway per G2), `pkg/config`.
- Contracts: `contracts/grpc/kyc.proto` checked in. sqlc + chat/media
  protos still pending Claude A schema work.

**Mobile (Flutter, `mobile/`):**
- Onboarding, auth, traveler+sender homes, create-trip, delivery+product
  request flows with live pricing.
- Builds against ngrok.

### What's NOT done (and what unblocks who)

All backend V1 spine tasks complete. Remaining work:

| # | Task | Blocks Go? |
|---|---|---|
| — | Mobile: matching screens + mock payment UI + follow-package circles | no |
| — | Mobile: handover-code issue/verify screens | no |

### Decoupling — Go can start whenever

Three contracts only:
1. **Postgres schema** (`contracts/sql/schema.sql`) — Django exports, Go reads via sqlc.
2. **Redis pub/sub + streams** — Django publishes after commit; Go subscribes. No subscriber = events go to void; Django keeps working.
3. **gRPC** — only KYC, Django→Go. Stubbed in dev with bearer + Python fake.

Go services (chat, notif, kyc, media) are NOT on Django's critical path. Claude A
can build the full money + matching + verification spine without Go running.
When Claude B is ready, run `task contract:generate` against current schema and
start. See §1 for scopes, §3 for connection-pool budget.

---

## 1. Two Claudes, two scopes

This repo is co-built by **two Claude instances** working with two human
contributors.

### Claude A (Islam's machine — Django + mobile)
- `mobile/` — Flutter app (iOS + Android)
- `backend/monolith/` — Django apps + migrations
- `backend/contracts/sql/schema.sql` — exported by Django, not edited by hand
- Django gRPC server in `apps/kyc/grpc_server.py`
- Redis publisher in `apps/core/redis_bus.py`

### Claude B (contributor's machine — Go services)
- `backend/services/` — Go workspace
- `backend/contracts/grpc/*.proto` — owned jointly, but Go re-generates stubs
- `backend/contracts/sql/sqlc.yaml` + sqlc-generated repos under `services/internal/*/repo/`
- Go gRPC clients in `services/internal/kyc/`

### Shared (touch only with explicit user approval)
- `backend/gateway/Caddyfile`
- `backend/docker-compose.yml`
- `backend/Taskfile.yml` (master)
- `backend/.env.example`
- `ARCHITECTURE.md`
- `CLAUDE.md` (this file)
- `contracts/grpc/*.proto`

If you're Claude A and the task touches `services/` → stop and tell the user
this is Claude B's scope. Same in reverse.

---

## 2. The 6 production guardrails (do not skip)

These came out of brutal architecture review. Each one neutralizes a
class of distributed-systems failure. They are NOT optional polish.

### G1 — Multi-pod presence + delivery receipts
- Pub/Sub for WS fan-out. Every Go pod subscribes; only the pod with the
  user's local socket sends.
- WS-owning pod writes `SET delivered:<event_id> 1 EX 60` after sending.
- FCM consumer (Redis Stream `notif:fcm`) reads, **waits 2s**, checks
  `delivered:<event_id>`, only then falls back to FCM.
- Presence: `SET presence:<user_id> EX 15` on every pong. `DEL` on
  disconnect. TTL must be < WS ping interval — never equal.
- `XAUTOCLAIM` sweeper every 30s reclaims PEL entries idle > 60s.
- Stream `MAXLEN ~ 10000`. Don't let it grow unbounded.

### G2 — JWT clock-skew leeway, both sides
- Go: `jwt.WithLeeway(30 * time.Second)` in `services/pkg/auth/jwt.go`
- Django: `SIMPLE_JWT["LEEWAY"] = timedelta(seconds=30)`
- Log a warning when `iat > now + 5s` even when accepted under leeway.
  Drift you don't see is drift you don't fix.

### G3 — Schema-drift CI gate (BOTH steps in CI)
```yaml
check-drift:
  cmds:
    - task contract:sync-db        # re-export schema.sql from Django
    - task contract:generate       # re-run sqlc
    - git diff --exit-code contracts/sql/ services/internal/*/repo/
```
Running only `generate` checks Go matches a stale schema file — exactly
the failure mode this exists to prevent.

### G4 — S3-compatible abstraction (no MinIO-specific code)
- All object storage access via `pkg/storage/s3.go` using `aws-sdk-go-v2`
  with custom endpoint.
- Never call MinIO admin APIs from app code.
- Test presigned URL flows against the actual prod provider in staging
  (MinIO and Backblaze/Hetzner differ on date semantics).

### G5 — gRPC mTLS (NOT static bearer)
- Self-signed CA generated once with cert-manager (K3s) or mkcert (local).
- Django + each Go service get their own cert.
- Both sides verify peer cert against shared CA.
- 90-day cert lifetime; cert-manager auto-renews.
- `GRPC_AUTH_MODE=bearer` is permitted **only** in `docker-compose` local
  dev. Production is `mtls`. The default in `.env.example` is `mtls`.
- gRPC max message size: `16 << 20` (16 MB) on **both** client and server.
  Asymmetric limits produce cryptic `RESOURCE_EXHAUSTED` errors.

### G6 — Redis publish ALWAYS after commit
- Use `transaction.on_commit(lambda: redis_bus.publish(...))` in Django.
- Direct calls to `redis_bus.publish()` inside a transaction body are
  forbidden — they leak ghost events on rollback.
- For every publish, also `INSERT INTO published_event(...)` for the V1
  detection-only audit (see G6b).

### G6b — Detection-only outbox (V1)
- Table `published_event(id, channel, event_id, payload_hash, published_at, delivered_at)`.
- Daily Django cron: select rows where `delivered_at IS NULL AND published_at < now - 5min`,
  cross-check against Redis `delivered:*`. Mismatches → Sentry.
- Full transactional outbox is V2. We don't auto-recover — but we
  detect every miss.

---

## 3. Connection pool budget (do not exceed)

Postgres `max_connections = 100`. Documented allocation:

```
Django gunicorn  : 4 workers × 5 conn  = 20
Go chat-service  : 2 pods × 15 conn    = 30
Go notif-service : 1 pod × 10 conn     = 10
Go kyc-service   : 1 pod × 5 conn      = 5
Reserved         :                     = 10
                                       ----
                                         75
```

Headroom for one extra Go pod: 25 conn. **Before scaling Go horizontally,
update `pgxpool.MaxConns` or raise `max_connections`.** Don't ad-hoc this.

---

## 4. Workflow rules (across sessions)

### Before starting any backend task
1. `git pull`
2. Read `ARCHITECTURE.md` if you haven't this session
3. Check `docs/claude-sessions/` for the most recent session log
4. Run `task check-drift` locally — if it fails, fix it before doing
   anything else
5. Make sure your scope (A or B) actually owns this task

### Before any Django migration (Claude A)
1. Make sure the migration is reversible (`./manage.py migrate <app> <prev>` works)
2. Run `task contract:sync-db` to update `contracts/sql/schema.sql`
3. Commit migration + schema.sql in the **same** PR. Splitting them
   breaks Claude B's build.
4. If the migration changes a Go-read table (`chat_message`, `notification`,
   `kyc_submission`, `media_object`, `published_event`), **flag it in the
   PR description** so Claude B reruns sqlc.

### Before any Go schema-touching change (Claude B)
1. Don't write migrations. Tell Islam what columns you need.
2. After Islam's migration lands, `task contract:generate` regenerates
   sqlc repos. If the diff looks wrong, the schema is wrong — push back.

### Before merging anything
- `task check-drift` must pass.
- `task test` must pass on both `monolith/` and `services/`.
- Mobile lint clean: `cd mobile && flutter analyze` (warning-clean).

### Before claiming work is "done"
Pattern: `evidence > assertions`.
- "It compiles" — show the build log
- "Tests pass" — show the test output
- "It's deployed" — show the health-check response
Don't say a task is done because the diff looks plausible.

---

## 5. Things that are easy to get wrong

- **Don't put `redis.publish` inside a Django `with transaction.atomic():`
  block.** Wrap it in `transaction.on_commit`. Always.
- **Don't use `presence:<user_id>` TTL of 30s.** It's 15s. Tighter than
  the 10s WS ping. Otherwise stale presence masks dropped sockets.
- **Don't fall back to FCM immediately on stream read.** Wait 2s for the
  WS-owning pod to write `delivered:<event_id>`, then check, then maybe
  another 2s if presence is online.
- **Don't put a static bearer token in production gRPC.** mTLS only.
- **Don't store JWT secrets in code.** `.env` only.
- **Don't compress images server-side in V1.** Out of scope. Use the
  client-enforced size cap.
- **Don't pre-generate thumbnails.** Lazy on read in V1.
- **Don't add a 6th Go service.** The win curve from polyglot is
  already flattening. Resist split-of-the-week temptations.
- **Don't change `Airport.iata` to surrogate `id`** without a data
  migration plan. Historic trips have FK to it.
- **Don't merge a PR with a failing `check-drift`.** Ever.

---

## 6. Pricing rules (load-bearing — do not vary)

Single source of truth: `monolith/apps/core/pricing.py`. Mobile app
mirrors but does not authoritatively compute. **Pricing is frozen on the
Offer row at creation time** (`commission_dzd`, `base_fee_dzd`,
`total_dzd` columns). Rate changes never retroactively rewrite Offers.

- Delivery: 25% flat commission, sender pays total
- Product:
  - Base fee 2,500 DZD
  - Tiered: <30k=0%, 30k–55k=7%, 55k–100k=5%, 100k+=3%
- All amounts are **integer DZD**. No floats. No fractional currency.

If a stakeholder asks to change rates, change `pricing.py`, not the
schema. Old Offers must continue to settle at their frozen rates.

---

## 7. Mobile rules

- **Riverpod 3** — `Notifier` + `NotifierProvider`, never `StateNotifier`.
- **`country_flags` v4** — wrap `CountryFlag.fromCountryCode()` in
  `SizedBox`; v4 dropped width/height params.
- **No `Spacer` inside scrollable columns** — use
  `SingleChildScrollView` + `IntrinsicHeight`. This bit us on onboarding.
- **Bottom nav** — white pill, sun-yellow accent only on the selected
  icon. No grey, no dark indicator.
- **Forms** — `AppInput` for text, `NumberStepper` instead of sliders,
  `InlineCalendar` for dates, `showAirportPicker()` for airports.
- **Theme** — Mediterranean parchment + emerald + terracotta + gold,
  with `#FBBC04` (sun yellow) as the signature accent.
- **Reconnect logic** — exponential backoff with ±30% jitter is
  mandatory on WS reconnect. Algerian mobile networks will reconnect
  thousands of devices simultaneously after any tower hiccup.

---

## 7b. Running the backend locally (Windows + WSL Ubuntu)

The user is on Windows; Docker Desktop runs through WSL Ubuntu. All
compose commands are run from inside WSL:

```bash
wsl -d Ubuntu
cd /mnt/c/Users/islam/shiptrip/backend
cp -n .env.example .env     # only first time
docker compose up -d        # postgres + redis + minio + django + caddy
docker compose run --rm django python manage.py migrate
curl http://localhost:8000/healthz   # → {"status":"ok"}
```

**Port map:**
- `localhost:5432` → Postgres
- `localhost:6380` → Redis (host 6380, NOT 6379 — native redis-server in
  WSL holds 6379. Inside the compose network, services still talk to
  `redis:6379`, so Django's `REDIS_URL` is unchanged.)
- `localhost:9000` / `:9001` → MinIO API / console
- `localhost:8000` → Django dev server
- `localhost:8080` → Caddy gateway (when up)

**Don't run native `psql` / `redis-cli` against the docker containers
expecting them to share data with native daemons.** Two separate
instances. Use `docker compose exec postgres psql -U shiptrip` and
`docker compose exec redis redis-cli`.

---

## 8. Memory + handoff

- Project memory persists in `.claude/memory/` (committed).
- Session transcripts in `docs/claude-sessions/` (committed; full JSONL).
- **`TASKS.md` at repo root is the live to-do board for both Claudes.**
  Read it at session start. When you finish a task, move it under **Done**
  with date + commit SHA. When you discover new work, add it under the
  right owner. Commit it in the same change so the other side sees it
  on next `git pull`. Don't claim a task that's `in-progress` for the
  other owner.
- A new Claude session at the start should:
  1. `git pull`
  2. Read `CLAUDE.md` (this file)
  3. Read `ARCHITECTURE.md`
  4. Read `TASKS.md` (your owner section)
  5. Read `.claude/MEMORY.md` and the linked memory files
  6. Skim the most recent session in `docs/claude-sessions/`
  7. Check `git log --oneline -20`

If you discover something the user wants persisted across sessions,
write it to `.claude/memory/<topic>.md` and add a one-line entry to
`.claude/MEMORY.md`. Do not put it only in `CLAUDE.md` unless it's a
hard rule for both Claudes.

---

## 9. When in doubt

- **Read code, don't guess.** Memories are point-in-time observations;
  the current code is authoritative.
- **Surface trade-offs, don't hide them.** If a fix has a downside,
  say so before implementing.
- **Don't add features the user didn't ask for.** A bug fix doesn't
  need surrounding cleanup; a one-shot operation doesn't need a helper.
- **Don't write defensive code for impossible cases.** Trust internal
  contracts. Validate at system boundaries only.
- **Use the Skill tool for skills the user has installed.** Don't
  invoke a skill that's already running. Don't simulate skill content.

---

## 10. V2 (deferred — do not start)

These are documented in `ARCHITECTURE.md §15`. Not in V1 scope:

- Ratings & reviews
- Dispute resolution UI
- Boost / paid promotion
- Insurance
- Local DZ payment rails (CIB / Edahabia / Baridimob)
- Push notifications via FCM are V1 — but custom topics, segmentation: V2
- Image compression on upload
- Pre-generated thumbnails
- Virus scanning
- Transactional outbox (V1 has detection-only)
- gRPC for inter-service calls beyond KYC
- HS256 → RS256 migration

If asked to build any of these in V1, push back and check with the user.
