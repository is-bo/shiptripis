# Wassla — Architecture (V1)

Peer-to-peer parcel-delivery marketplace. V1 is delivery only: the
Kaba/ProductRequest flow is retired. All marketplace money is canonical EUR,
stored as integer cents; Chargily shows a server-calculated DZD conversion.
`docs/SHIPTRIP_V1_SPEC.md` is authoritative where this file and the
specification disagree. Corrected in package L1A (2026-11-11) where the
earlier version described a topology, apps and pricing that no longer exist.

**Stack:** Flutter · Caddy · Django monolith · Go services · PostgreSQL · Redis · S3-compatible object storage (MinIO in local development)

---

## 1. Repo layout

```
shiptripis/
├── mobile/                       # Flutter app (iOS + Android)
├── web/                          # static public site served by the gateway
├── infra/vps/                    # the production host: compose stack, the
│                                 # combined app image (Dockerfile, launcher.py,
│                                 # runtime.py, gateway.Caddyfile), the public
│                                 # edge Caddyfile, backups, systemd units
├── backend/
│   ├── docker-compose.yml        # local development stack
│   ├── Taskfile.yml              # local orchestration (task <subcommand>)
│   ├── gateway/Caddyfile         # local development gateway
│   ├── contracts/
│   │   ├── grpc/kyc.proto        # Go KYC service -> Django recorder
│   │   └── sql/                  # schema.sql exported from Django; sqlc.yaml
│   │                             # is a template (no queries, no generated repos)
│   ├── loadtest/                 # Locust load test harness
│   ├── monolith/                 # Django (Python): config/ and apps/
│   └── services/                 # Go module
│       ├── cmd/                  # chat, notification, email, kyc
│       ├── internal/             # one package per binary
│       └── pkg/                  # auth, config, db, health, logger,
│                                 # metrics, redisbus, retry, storage, wsproto
├── tools/                        # CI and release checks, geography catalogue,
│                                 # admin preview scripts
└── docs/                         # specification, runbooks, phase reports
```

---

## 2. System topology (VPS)

```
   Flutter / browser
        | HTTPS + WSS
        v
   +---------------------------+
   | edge Caddy                |  infra/vps/Caddyfile: TLS, origin checks,
   | (compose service `caddy`) |  /metrics and /debug denied publicly
   +-------------+-------------+
                 | http://app:8080
                 v
   +----------------------------------------------------------------+
   | app container (infra/vps/Dockerfile, started by runtime.py)    |
   |                                                                |
   |  internal Caddy :8080 (infra/vps/gateway.Caddyfile)            |
   |    /ws/chat*            -> chat         :8081  (Go)            |
   |    /ws/notifications*   -> notification :8082  (Go)            |
   |    /kyc/*, /api/kyc/*   -> kyc          :8083  (Go)            |
   |    public site paths    -> web/ files                          |
   |    everything else      -> Django       :8000  (gunicorn)      |
   |                                                                |
   |  also: Django gRPC KYC recorder, email consumer (Go),          |
   |        Django job loops                                        |
   +--------+-----------------------+-------------------+-----------+
            |                       |                   |
            v                       v                   v
     PostgreSQL (compose)     Redis (compose)     S3-compatible storage
```

`infra/vps/launcher.py` supervises every process in the app container and
drains them on SIGTERM (compose gives it `stop_grace_period: 40s`). Migrations
and the geography catalogue import are maintenance operations run by the
`maintenance` compose service, never by container start. PostgreSQL and Redis
are separate compose services on the private network; only the edge Caddy is
published.

---

## 3. Gateway routing

- The edge Caddy (`infra/vps/Caddyfile`) terminates TLS and proxies everything
  to the app container's internal Caddy.
- The internal Caddy (`infra/vps/gateway.Caddyfile`) routes by path as drawn
  above, bounds request bodies (with a larger limit for KYC uploads), and
  serves the static public site, including the clean `/terms` and `/privacy`
  URLs. `tools/check_static_web.py` checks those routes in CI.
- `backend/gateway/Caddyfile` is the same routing for local development.
- **No JWT validation at the gateway.** Each service validates its own tokens.

---

## 4. Database boundary

- **Django owns 100% of migrations.** All schema changes go through
  `manage.py makemigrations`; Go never runs migrations.
- Go talks to the shared PostgreSQL through `pkg/db` (pgxpool) with inline SQL.
  The `sqlc.yaml` packages have no queries, so no repositories are generated.
- CI's `check-drift` job re-exports `contracts/sql/schema.sql` from a migrated
  database and fails on a diff.

### Connection budget (load-bearing)

`infra/vps/postgresql.conf` sets `max_connections = 100`. The launcher computes
the peak from its settings (Django web workers × threads, the gRPC executor,
the job loops, and the chat, notification and email pools) and refuses to start
if twice that peak, which is a rolling deploy, would exceed the limit minus a
reserve of 10. Change the pool sizes through those environment variables, never
by editing the services.

---

## 5. Auth — shared JWT, leeway both sides

- Django (`accounts` app) issues JWTs. Refresh-token rotation lives in Django; Go never mints or rotates.
- HS256 with secret in `JWT_HS256_SECRET` env var, distributed to Django and every Go service.
- Go reads the integer `user_id` claim and refuses a token without one (`pkg/auth/jwt.go`).
- Access token TTL: **5 minutes** by default (`JWT_ACCESS_TTL_SECONDS`).
- Refresh token TTL: 30 days by default (`JWT_REFRESH_TTL_SECONDS`), rotated on every use.
- **Clock-skew leeway: 30s on both sides.**
  - Go: `golang-jwt/jwt/v5` → `jwt.WithLeeway(30 * time.Second)`
  - Django: `SIMPLE_JWT["LEEWAY"] = timedelta(seconds=30)`
- Log a warning when `iat > now + 5s` (still accepted under leeway). Drift you don't see is drift you don't fix.

---

## 6. Internal sync — gRPC + idempotency

KYC submit is heavy (multipart, multi-MB images). Two-phase:

1. **Flutter** → POST multipart to `/kyc/submit` (or `/api/kyc/submit`) → Caddy → **kyc-service (Go)**
2. kyc-service streams the images to the KYC bucket (`S3_BUCKET_KYC`) with its own credential
3. kyc-service calls Django via private gRPC: `KYCSubmissionService.RecordSubmission(...)`
4. Django runs `INSERT INTO kyc_submission ... ON CONFLICT (idempotency_key) DO NOTHING RETURNING id` — Flutter-generated UUID is the idempotency key, so retries during flaky network are no-ops
5. gRPC response includes the row id; kyc-service returns `{ status: "under_review", submission_id }` to Flutter

### gRPC channel security

- `GRPC_AUTH_MODE=mtls` verifies both peers against a shared CA.
- `GRPC_AUTH_MODE=bearer` is accepted in production only with
  `GRPC_ALLOW_PRIVATE_BEARER=true` and a long `GRPC_BEARER_TOKEN`, because the
  KYC service and the Django recorder run in the same container on the private
  network. This is what the VPS uses; `config/settings/prod.py` refuses any
  other combination at boot.

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
redis_bus.publish_after_commit(
    channels.OFFER_ACCEPTED,
    {"offer_id": offer.pk, "match_id": offer.match_id},
    targets=[offer.match.sender_id],
)
```

`publish_after_commit` defers to `transaction.on_commit`, so a rolled-back
transaction publishes nothing. Channel names are `<domain>.<event>` and live in
`apps/core/channels.py`; the notification service's subscribe list must match
it, which `TestSubscribeChannelsMatchDjango` enforces.

The notification service subscribes to every channel. If it holds a socket for
a target user it pushes to that socket and writes a **delivery receipt** to
Redis: `SET delivered:<event_id>:<user_id> 1 EX 60`.

### Streams — FCM queue (durable, single-consumer)

Same Django publish flow ALSO XADDs to a Redis Stream:

```
XADD notif:fcm * user_id <uuid> event_id <uuid> payload <json>
```

Stream config:
- `MAXLEN ~ 10000` (cap memory growth — drop oldest if backed up)
- Consumer group `notif-fcm-workers`
- Workers run in the notification service

Worker loop:
1. `XREADGROUP` on `notif:fcm` for the `notif-fcm-workers` group
2. Wait 2 seconds (gives the WebSocket hub time to deliver and write its receipt)
3. Check `EXISTS delivered:<event_id>:<user_id>` — if 1, `XACK` and skip FCM
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

### Detection-only sweep for live events

- Every Django Redis publish writes a `PublishedEvent` row (`channel`, `event_id`, `payload_hash`, `published_at`, `delivered_at`).
- `manage.py sweep_published_events` (a maintenance operation in `infra/vps/runtime.py`) compares rows still undelivered after 5 minutes against the Redis `delivered:<event_id>:<user_id>` receipts and reports the misses.
- Live events are not re-published; they are detected. Messages that must arrive, such as transactional email, are PostgreSQL outbox rows instead (`apps/notifications/outbox.py`).

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
              +---> The notification service receives pub/sub.
              |     Socket held → push + SET delivered:<event_id>:<user_id> EX 60
              |
              +---> FCM worker picks up stream entry.
                    Wait 2s.
                    delivered:<event_id>:<user_id> exists? → XACK, done.
                    presence:<user_id> exists?   → wait 2s, recheck delivery.
                    Still no delivery → POST to FCM, XACK.
```

Net result: every notification is delivered exactly once, via WS if connected, via FCM if not. A crash mid-delivery is recovered by `XAUTOCLAIM`.

---

## 9. Object storage — S3-compatible

- Local development: MinIO in `backend/docker-compose.yml`.
- Production: an env-configured S3 endpoint. No code change between providers.
- Django addresses storage by logical class through `apps.core.storage`
  (`storage_for(<class>)`); Go uses `pkg/storage`.
- Buckets: `S3_BUCKET_PARCEL` (parcel media), `S3_BUCKET_PROOF` (travel proof),
  `S3_BUCKET_DISPUTE` (dispute evidence), `S3_BUCKET_KYC` (identity documents,
  written by the KYC service with its own credential) and `S3_BUCKET_PAYOUT`
  (payout evidence). See the credential table in section 11.
- Uploads go through a service, never straight from the app to the bucket:
  KYC images through the Go KYC service, everything else as multipart to
  Django. Reads are short-lived signed URLs.

**Caveat:** MinIO and real S3 differ on multipart edge cases and presigned URL date semantics. Test against the production provider, not just MinIO.

---

## 10. Rate limiting

The KYC upload path has its own Redis-backed rate limiter
(`internal/kyc/rate_limiter.go`). Django throttles its API through DRF throttle
classes (the `DRF_*_THROTTLE_RATE` settings). The shared Go token bucket,
semaphore and read-through cache described in earlier versions of this file
were never built.

---

## 11. Django apps (`backend/monolith/apps/`)

| App | Responsibility |
|---|---|
| `core` | Redis publisher (`redis_bus.publish_after_commit`) and channel names, versioned business settings, financial lock order, storage classes |
| `accounts` | User, authentication, JWT issue and rotation, email verification |
| `kyc` | KYC submission records and the gRPC server the Go KYC service calls |
| `trips` | Journey and JourneyLeg (V1); the legacy Trip and Airport tables stay as history |
| `locations` | Canonical Place catalogue and preferred Locations |
| `parcels` | Delivery requests (V1) and parcel media; ProductRequest rows are history |
| `discovery` | Public listings of requests and journeys, interest signals, route and trip-fit alerts, public profiles |
| `routing` | Provider-neutral route and geocoding boundary |
| `matching` | Compatibility, find-travelers, quotes, Match and Offer negotiation (sender proposes first) |
| `deals` | Funded delivery lifecycle, recipients, arrival, cancellation |
| `finance` | EUR payment orders and attempts (Stripe, Chargily), settlement, payouts |
| `handover` | Deal-scoped pickup and delivery codes |
| `disputes` | Disputes, which freeze payout |
| `problems` | Problem reports and schedule changes beside the deal; they never write `Deal.status` |
| `ratings` | Post-delivery ratings |
| `boosts` | Paid visibility boosts on requests |
| `notifications` | In-app inbox, push device registration, FCM stream, transactional email outbox |
| `chat` | Deal chat persistence and REST API; Go relays new messages to sockets |
| `admin_panel` | The operations console and the admin API |
| `admin_helper` | The staff AI helper: read tools, audited change actions and its knowledge skill |
| `payments`, `wallet`, `verification` | Pre-V1 DZD payment, wallet and match-handover tables, kept as history. No API; view-only in the Django admin |

Django **never stores binary bytes**. All photos and documents live in object
storage.

**Buckets are not all owned by the same credential.** `apps.core.storage`
addresses object storage by *logical class*, and each class names both its
bucket and the key that owns it:

| Class | Bucket setting | Credential |
|---|---|---|
| `media` / `parcel` | `S3_BUCKET_PARCEL` | `S3_*` — Django's own |
| `proof` | `S3_BUCKET_PROOF` | `S3_*` |
| `dispute` | `S3_BUCKET_DISPUTE` | `S3_*` |
| `kyc` | `S3_BUCKET_KYC` | `KYC_S3_*` — the Go KYC service's |

Identity evidence lives in its own bucket so its access policy can be tightened
independently of marketplace media, and on the deployed environment only the
KYC service's key is granted there. This is easy to get wrong invisibly:
`generate_presigned_url` is a local HMAC that never contacts the store, so it
signs a perfectly well-formed URL with a credential that has no grant — and the
denial only appears later, in the browser, as a file that will not load. Use
`storage_for(<class>)`, and `ObjectStore.readable(key)` when a page is about to
embed or link an object; a signed URL is not evidence that the object can be
fetched. `manage.py check_object_storage` probes each class with its own key.

---

---

## 12. Go services (`backend/services/`)

| Binary | Purpose |
|---|---|
| `cmd/chat` | WebSocket relay for new chat messages (server to client only; Django is the write path) |
| `cmd/notification` | WebSocket hub for notifications, presence, and the FCM stream consumer |
| `cmd/email` | Consumer of the non-secret email stream; sends through Sender.net's REST API (or SMTP in development) |
| `cmd/kyc` | HTTP KYC upload, streams to object storage, records through Django gRPC |

Shared via `services/pkg/`: `auth` (JWT verify with leeway), `config`, `db`
(pgxpool), `health`, `logger`, `metrics`, `redisbus` (pub/sub and streams),
`retry`, `storage` (S3), `wsproto` (WebSocket envelope).

---

## 13. Money rules (load-bearing)

- EUR is canonical, stored as integer cents. DZD appears only as Chargily's
  server-calculated conversion of an EUR amount.
- The sender proposes first; the negotiated amount is the traveler reward.
- Commission is a percentage of the reward (25% at launch), admin-configurable
  through a versioned business setting and snapshotted on the offer and deal.
  Example: reward €30, fee €7.50, sender total €37.50.
- Payout protection is 48 hours after delivery; a dispute freezes payout.

The pricing engine (chargeable weight, matched distance, minimum and
recommended reward) is specified in `docs/SHIPTRIP_V1_SPEC.md` section 8.

---

## 14. Decisions taken

| Topic | Decision |
|---|---|
| Hosting | One VPS: compose stack in `infra/vps/` (edge Caddy, app container, PostgreSQL, Redis, backups) |
| Auth at edge | None. Each service validates JWT itself with the shared HS256 secret and 30s leeway |
| Access TTL | 5 min by default (`JWT_ACCESS_TTL_SECONDS`) |
| DB ownership | Django owns all migrations; Go uses inline SQL through pgxpool |
| Schema-drift CI | `check-drift` re-exports `schema.sql` and fails on a diff |
| Internal RPC | gRPC; mTLS, or bearer only on the private network with `GRPC_ALLOW_PRIVATE_BEARER=true` |
| gRPC msg size | 16 MB on both sides |
| Redis WS fan-out | Pub/Sub, best-effort; the notification service subscribes to every channel in `apps/core/channels.py` |
| Redis FCM queue | Stream + consumer group, MAXLEN cap, XAUTOCLAIM sweeper |
| Presence | `presence:<user_id>` 15s TTL, refreshed on pong, DEL on disconnect |
| Durable messages | Transactional email is a PostgreSQL outbox row; Redis only carries it. Provider `sender_net` (Sender.net REST API, token in `secrets/app.json`) in production, `smtp` in development; Django sends secret-bearing mail itself, the Go email service sends the rest |
| Object storage | S3-compatible, one credential per storage class |
| KYC upload path | Flutter → kyc-service → object storage + Django gRPC |
| Pricing freeze | Snapshotted on the Offer and Deal, never retroactive |

---

## 15. Later

Work planned after V1 is tracked in `docs/WASSLA_DISCOVERY_PRO_PLAN.md` and
`docs/IMPLEMENTATION_STATUS.md`, not here.
