# ShipTrip — Architecture (MVP v1)

Peer-to-peer delivery + product-purchase platform for Algeria. Pricing in DZD.

**Stack:** Flutter · Caddy · Django monolith · Go services · PostgreSQL · Redis · MinIO (S3-compatible)

---

## 1. Repo layout

```
shiptrip/
├── mobile/                       # Flutter app (iOS + Android)
├── ship-trip-backend/
│   ├── docker-compose.yml        # boots Postgres, Redis, MinIO, Django, Go, Caddy
│   ├── Taskfile.yml              # master orchestrator (task <subcommand>)
│   ├── .env.example
│   ├── gateway/
│   │   └── Caddyfile             # /api/v1/kyc + /ws/v1/* → Go, rest → Django
│   ├── contracts/                # the DMZ between Django and Go
│   │   ├── Taskfile.yml
│   │   ├── rest/                 # OpenAPI specs (manual + Django-generated)
│   │   ├── grpc/
│   │   │   └── kyc.proto
│   │   └── sql/
│   │       ├── schema.sql        # exported from Django, single source for sqlc
│   │       └── sqlc.yaml
│   ├── monolith/                 # Django (Python)
│   │   ├── Taskfile.yml
│   │   ├── Dockerfile
│   │   └── apps/                 # accounts, trips, parcels, matching,
│   │                             # payments, wallet, verification,
│   │                             # notifications (publisher only),
│   │                             # chat (schema only), kyc (gRPC server),
│   │                             # admin_panel, core
│   └── services/                 # Go workspace (1.22+)
│       ├── Taskfile.yml
│       ├── go.mod
│       ├── build/                # multi-stage Dockerfiles per service
│       ├── cmd/                  # main.go per executable (chat, notif, kyc)
│       ├── internal/             # domain code + sqlc-generated repos
│       └── pkg/                  # shared libs
│           ├── auth/             # JWT validation (HS256, leeway)
│           ├── config/           # envconfig
│           ├── db/               # pgxpool
│           ├── health/           # /healthz
│           ├── logger/           # slog JSON
│           ├── ratelimit/        # token bucket + semaphore
│           ├── redisbus/         # pub/sub + streams
│           └── wsproto/          # WS envelope helpers
└── ARCHITECTURE.md               # this file
```

---

## 2. System topology

```
                    +-------------------+
   Flutter <------> |   Caddy gateway   |  TLS · routing · CORS · WS upgrade
   (HTTPS/WSS)      |  (auto-TLS, WS)   |  no JWT validation here — services do their own
                    +---+-----------+---+
   /api/v1/kyc     /ws/v1/*           /api/v1/*  (everything else)
        v               v                  v
   +----------+   +-----------+      +-----------------+
   | kyc-svc  |   | chat-svc  |      | Django monolith |
   | (Go)     |   | notif-svc |      | DRF + admin     |
   +----+-----+   |   (Go)    |      +--------+--------+
        | gRPC    +-----+-----+               |
        | (mTLS)        |                     |
        v               |                     |
   +-----------+        |              writes |
   | Django gRPC|       |                     v
   | server     |       |               +----------------+
   +-----+-----+        |               |   PostgreSQL   |
         |              |               |   (shared)     |
         | writes       | reads/writes  +-------+--------+
         v              v                       ^
   +-------------------------+   pgx pool       |
   |        PostgreSQL       |<-----------------+
   +-------------------------+
                ^
                |
   +-------------------------+   pub/sub (WS fan-out) + streams (FCM queue)
   |          Redis          |
   +-------------------------+
                ^
                |
   +-------------------------+   S3 API
   |   MinIO (dev)  /  S3-   |
   |   compatible (prod)     |
   +-------------------------+
```

Caddy is the only publicly exposed service. Internal traffic (Django ↔ Postgres ↔ Redis, Go ↔ Postgres ↔ Redis, Go ↔ Django gRPC, Go ↔ MinIO) stays on the private docker / K3s network.

---

## 3. Caddy gateway (`gateway/Caddyfile`)

- Auto-TLS via Let's Encrypt
- HTTP/2 + WebSocket upgrade
- CORS (allow Flutter app origin)
- Routing:
  - `/api/v1/kyc/*` → kyc-service (Go)
  - `/ws/v1/chat`   → chat-service (Go)
  - `/ws/v1/notif`  → notification-service (Go)
  - `/api/v1/*`     → Django (default)
- Graceful shutdown: `shutdown_timeout 30s` so K3s rolling deploys drain WS instead of dropping them
- **No JWT validation at the gateway.** Each service validates its own tokens (gateway has no business knowing the secret).

---

## 4. Database boundary (the most important rule)

- **Django owns 100% of migrations.** All schema changes go through `manage.py makemigrations`.
- After every migration, the Django Taskfile target runs `task contract:sync-db` which exports the merged schema to `contracts/sql/schema.sql`.
- Go reads `schema.sql` via **sqlc**, generates type-safe repository code into `services/internal/<domain>/repo/`.
- Go writes raw SQL via the generated repos. Go never runs migrations.
- Both sides connect to the shared Postgres directly:
  - Django: standard ORM + `psycopg`
  - Go: `pgxpool` from `pkg/db/`

### CI gate against schema drift (master `Taskfile.yml`)

```yaml
check-drift:
  desc: "Fail CI if schema.sql or sqlc-generated code is stale"
  cmds:
    - task contract:sync-db        # re-export schema.sql from Django state
    - task contract:generate       # re-run sqlc against the exported schema
    - git diff --exit-code contracts/sql/ services/internal/*/repo/
```

Both steps must run in CI. Running only `generate` checks Go matches a stale schema file — exactly the failure mode we're trying to prevent.

### Connection pool sizing (load-bearing)

Default Postgres `max_connections = 100`. Plan:

| Side | Pool | Workers/pods | Total |
|---|---|---|---|
| Django (gunicorn) | `CONN_MAX_AGE = 60` | 4 workers × 5 conn | 20 |
| Go chat-service | `pgxpool.MaxConns = 15` | 2 pods | 30 |
| Go notif-service | `pgxpool.MaxConns = 10` | 1 pod | 10 |
| Go kyc-service | `pgxpool.MaxConns = 5` | 1 pod | 5 |
| Reserved (admin, migrations) | — | — | 10 |
| **Total** | | | **75** |

Headroom for one extra Go pod: 25 conn. **Document this in the deploy runbook before scaling.**

---

## 5. Auth — shared JWT, leeway both sides

- Django (`accounts` app) issues JWTs. Refresh-token rotation lives in Django; Go never mints or rotates.
- HS256 with secret in `JWT_HS256_SECRET` env var, distributed to Django and every Go service.
- Claims (both sides agree on shape): `sub` (user_id UUID), `role`, `exp`, `iat`, `jti`.
- Access token TTL: **5 minutes** (was 15 — tightened to bound JWT-revocation gap).
- Refresh token TTL: 7 days, rotated on every use.
- **Clock-skew leeway: 30s on both sides.**
  - Go: `golang-jwt/jwt/v5` → `jwt.WithLeeway(30 * time.Second)`
  - Django: `SIMPLE_JWT["LEEWAY"] = timedelta(seconds=30)`
- Log a warning when `iat > now + 5s` (still accepted under leeway). Drift you don't see is drift you don't fix.

---

## 6. Internal sync — gRPC + idempotency

KYC submit is heavy (multipart, multi-MB images). Two-phase:

1. **Flutter** → POST multipart to `/api/v1/kyc/submit` → Caddy → **kyc-service (Go)**
2. kyc-service streams files to MinIO under `kyc-docs/<user_id>/<uuid>.<ext>`
3. kyc-service calls Django via private gRPC: `KYCSubmissionService.RecordSubmission(...)`
4. Django runs `INSERT INTO kyc_submission ... ON CONFLICT (idempotency_key) DO NOTHING RETURNING id` — Flutter-generated UUID is the idempotency key, so retries during flaky network are no-ops
5. gRPC response includes the row id; kyc-service returns `{ status: "under_review", submission_id }` to Flutter

### gRPC channel security — **mTLS, not static bearer**

- Self-signed CA generated once with `cert-manager` (K3s) or `mkcert` (local dev).
- Django gRPC server presents `django.shiptrip.local` cert; each Go service has its own cert (`kyc.svc`, `chat.svc`, `notif.svc`).
- Both sides verify peer cert against the shared CA.
- Static bearer tokens are **not acceptable** for production. They leak, can't be revoked, and offer no replay protection. Bearer-only mode is permitted for `docker-compose` local dev, gated by `GRPC_AUTH_MODE=bearer|mtls`.
- Cert rotation: 90-day cert lifetime, cert-manager auto-renews; deploys re-mount renewed secret without restart (gRPC handles cert reload).

### gRPC payload limits

Default 4 MB max message size will reject typical KYC selfies. Set explicitly:

```go
grpc.MaxRecvMsgSize(16 << 20)  // 16 MB
grpc.MaxSendMsgSize(16 << 20)
```

…on both client and server. Symmetric or you get cryptic `RESOURCE_EXHAUSTED` errors.

---

## 7. Event bus — Redis Pub/Sub + Streams

Two distinct primitives, two distinct purposes.

### Pub/Sub — WebSocket fan-out (best-effort)

Django publishes after the Postgres transaction commits:

```python
def on_offer_accepted(match):
    transaction.on_commit(lambda: redis_bus.publish(
        f"notif.user.{match.sender_id}",
        json.dumps({"event": "offer_accepted", "match_id": str(match.id)})
    ))
```

`transaction.on_commit` is **mandatory**. Publishing inside the transaction risks ghost events on rollback.

Every Go pod subscribes to every channel. If a pod has the user in its local WS map, it pushes to that socket and writes a **delivery receipt** to Redis: `SET delivered:<event_id> 1 EX 60`. Other pods see no local socket and do nothing.

### Streams — FCM queue (durable, single-consumer)

Same Django publish flow ALSO XADDs to a Redis Stream:

```
XADD notif:fcm * user_id <uuid> event_id <uuid> payload <json>
```

Stream config:
- `MAXLEN ~ 10000` (cap memory growth — drop oldest if backed up)
- Single consumer group `fcm-workers`
- Workers reside in notif-service Go pods

Worker loop:
1. `XREADGROUP GROUP fcm-workers worker-<pod_id> COUNT 10 BLOCK 5000 STREAMS notif:fcm >`
2. Wait 2 seconds (gives WS pods time to deliver and write `delivered:<event_id>`)
3. Check `EXISTS delivered:<event_id>` — if 1, `XACK` and skip FCM
4. Else check `EXISTS presence:<user_id>` — if 1, sleep another 2s and re-check delivery flag
5. If still no delivery: call FCM HTTP API, then `XACK`
6. **`XAUTOCLAIM`** sweeper every 30s reclaims messages idle > 60s in the PEL (handles worker crashes)

This sequence eliminates the duplicate-notification race (WS+FCM both fire) and the silent-loss race (presence stale, FCM skipped).

### Presence tracking

In Go WS handler:
```go
// On every successful pong:
redis.SetEX(ctx, "presence:"+userID, "online", 15*time.Second)
// On WS disconnect:
redis.Del(ctx, "presence:"+userID)
```

TTL is **15s, not 30s** — must be tighter than the WS ping interval (10s) so a disconnect can't masquerade as online for the FCM consumer.

### Detection-only outbox (V1 simplification)

Full transactional outbox deferred to V2. For V1:

- Every Django Redis publish writes a row to `published_event(id, channel, event_id, payload_hash, published_at, delivered_at NULL)`.
- Daily Django cron compares `published_event` rows where `delivered_at IS NULL AND published_at < now - 5 min` against Redis `delivered:*` keys; mismatches go to Sentry.
- We don't auto-recover lost events in V1 — but we **detect** them. Silent failure rate is bounded.

V2 will swap publishing for an outbox-poller worker (or Debezium CDC).

---

## 8. Real-time hybrid — WS first, FCM fallback

Decision tree per outbound notification:

```
     Django writes Notification row
              |
              v
     transaction.on_commit:
       PUBLISH notif.user.<id>           ← Pub/Sub fan-out (WS)
       XADD   notif:fcm                  ← Stream (FCM fallback)
              |
              +---> All Go pods receive pub/sub.
              |     Pod with WS → push + SET delivered:<event_id> EX 60
              |
              +---> FCM worker picks up stream entry.
                    Wait 2s.
                    delivered:<event_id> exists? → XACK, done.
                    presence:<user_id> exists?   → wait 2s, recheck delivery.
                    Still no delivery → POST to FCM, XACK.
```

Net result: every notification is delivered exactly once, via WS if connected, via FCM if not. A pod crash mid-delivery is recovered by `XAUTOCLAIM`.

---

## 9. Object storage — MinIO (dev) / S3-compatible (prod)

- Dev: MinIO container in `docker-compose.yml`, single node, ephemeral volume.
- Prod: env-configured S3 endpoint (Hetzner, Scaleway, Backblaze, Wasabi). No code change.
- All access via `pkg/storage/s3.go` using `aws-sdk-go-v2` with custom endpoint.
- Buckets:

| Bucket | Visibility | Max size | Owner |
|---|---|---|---|
| `kyc-docs` | private | 10 MB | kyc-service |
| `parcel-photos` | private (signed URL, 5 min) | 5 MB | Django parcels app |
| `product-photos` | private (signed URL, 5 min) | 5 MB | Django parcels app |
| `tickets` | private | 10 MB | Django trips app |

**Caveat:** MinIO and real S3 differ on multipart edge cases and presigned URL date semantics. Test against the prod provider in staging — not just MinIO.

Direct uploads from Flutter:
- `kyc-docs`: NO. Flutter sends multipart to kyc-service, which streams to MinIO with service credentials.
- `parcel-photos` / `product-photos` / `tickets`: Flutter requests a presigned PUT URL from Django, uploads directly. Django records the resulting object key in `MediaObject`.

---

## 10. Thundering-herd protection (Algerian mobile network reality)

A tower hiccup reconnects thousands of devices simultaneously. Four layers:

1. **Client-side jitter** — Flutter retries with exponential backoff + ±30% jitter
2. **Go-side token bucket** (`pkg/ratelimit/tokenbucket.go`) — per-IP, ~10 req/s burst 50
3. **Semaphore** — concurrent Postgres catch-up queries capped at 25 across the pod (`pkg/ratelimit/semaphore.go`)
4. **Read-through cache** — missed-notifications fetch is cached 5s per user_id; 1000 simultaneous reconnects of the same user trigger one Postgres query

Without all four, a small connectivity blip cascades into a DB connection exhaustion event.

---

## 11. Django apps (`monolith/apps/`)

This Claude owns these.

| App | Responsibility | Notes |
|---|---|---|
| `core` | pricing engine, commission tiers, Redis publisher (`redis_bus.publish_after_commit`), gRPC server bootstrap | single source for pricing rules |
| `accounts` | User, OAuth, JWT mint+rotate, OTP, push tokens | AUTH_USER_MODEL must be set before any other app migrates |
| `trips` | Trip, Airport, TripStopover, FlightTrackingSnapshot | airport seed via data migration from Flutter mock |
| `parcels` | DeliveryRequest, ProductRequest (multi-table inheritance), ParcelMedia | |
| `matching` | Match, Offer (counter chain), MatchEvent | offers freeze pricing at creation |
| `payments` | PaymentIntent, PaymentEvent, Refund | webhook idempotency on `provider_event_id` |
| `wallet` | Wallet, WalletEntry, Withdrawal | settled vs. pending balance |
| `verification` | HandoverCode (PICKUP + DELIVERY), hashed | argon2; max 5 attempts |
| `notifications` | Notification model + Redis publisher | actual delivery is Go's job |
| `chat` | Conversation + ChatMessage **schema only** | tables exist for sqlc; Go owns reads/writes |
| `kyc` | KycSubmission schema + gRPC server | gRPC handles `RecordSubmission` from Go |
| `admin_panel` | Dispute, AdminAuditLog, Django admin views | |

Django **never stores binary bytes**. All photos/docs reference `MediaObject(bucket, object_key)`.

---

## 12. Go services (`services/`)

Contributor's Claude owns these.

| Binary | Purpose |
|---|---|
| `cmd/chat` | WS hub, persists to `chat_message` via sqlc |
| `cmd/notif` | WS hub for notifications + FCM consumer worker (single binary, two goroutines) |
| `cmd/kyc` | HTTP `/api/v1/kyc/*`, streams to MinIO, calls Django gRPC |

Shared via `services/pkg/`:
- `auth/` — JWT verify with 30s leeway
- `config/` — envconfig
- `db/` — pgxpool wrapper
- `health/` — `/healthz` + `/readyz`
- `logger/` — slog JSON, includes `request_id`, `user_id`, `service`
- `ratelimit/` — token bucket + semaphore
- `redisbus/` — pub/sub + stream consumer wrapper
- `wsproto/` — JSON envelope `{ id, type, payload, ts }`

---

## 13. Commission rules (load-bearing)

**Delivery payments:**
- Platform takes 25% flat
- Sender pays full total; traveler sees total + 25% deduction

**Product-request payments:**
- Base fee: 2,500 DZD
- Tiered commission on item price:

| Item price (DZD) | Commission |
|---|---|
| Under 30,000 | 0% |
| 30,000 – 54,999 | 7% |
| 55,000 – 99,999 | 5% |
| 100,000+ | 3% |

- Sender pays: item_price + base_fee + commission
- Traveler receives 100% of item_price (no deduction)

Pricing is **frozen on the Offer at creation time**. Rate changes never retroactively touch live offers.

---

## 14. Decisions taken

| Topic | Decision |
|---|---|
| Public ingress | Caddy (auto-TLS, native WS, `shutdown_timeout 30s`) |
| Auth at edge | None. Each service validates JWT itself with shared HS256 secret + 30s leeway |
| Access TTL | 5 min (tightened from 15) |
| DB ownership | Django 100% migrations; Go reads `schema.sql` via sqlc and writes raw SQL through generated repos |
| Schema-drift CI | `task check-drift` runs `sync-db` AND `generate` then `git diff --exit-code` |
| Connection pool budget | Documented sum < `max_connections - 10` reserved |
| Internal RPC | gRPC, **mTLS** (cert-manager / mkcert). Bearer-only for local dev |
| gRPC msg size | 16 MB on both sides |
| Redis WS fan-out | Pub/Sub, all pods subscribe, only WS-owning pod pushes |
| Redis FCM queue | Stream + consumer group, MAXLEN cap, XAUTOCLAIM sweeper |
| Presence | `presence:<user_id>` 15s TTL, refreshed on pong, DEL on disconnect |
| Delivery receipts | `delivered:<event_id>` 60s TTL, set by WS-owning pod |
| Outbox pattern | V1: detection-only (`published_event` audit + Sentry alert). V2: full transactional outbox |
| Object storage | MinIO dev, S3-compat prod, abstracted via `pkg/storage/s3.go` |
| KYC upload path | Flutter → kyc-service → MinIO + Django gRPC |
| Other media uploads | Flutter ↔ Django for presigned URL → Flutter ↔ MinIO direct |
| Pricing freeze | On `Offer` creation, never retroactive |
| Ratings/disputes/boost/insurance | Deferred to V2 |
| Old Node prototype | Removed |

---

## 15. V2 roadmap

- Transactional outbox (Postgres `outbox_events` + Debezium or polling worker)
- Full ratings + reviews
- Dispute resolution UI in mobile
- Boost / paid promotion
- Insurance
- Local DZ payment rails (CIB / Edahabia / Baridimob)
- Image compression on upload
- Pre-generated thumbnails
- Virus scanning
- gRPC for hot-path inter-service calls beyond KYC (only if measurements demand it)
- Move from HS256 → RS256 for JWT (allows public-key-only distribution to Go)
