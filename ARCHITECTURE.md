# ShipTrip — Architecture (MVP v1)

Peer-to-peer delivery + product-purchase platform for Algeria. Pricing in DZD.

**Stack:** Flutter · API Gateway · Django monolith · Go services · PostgreSQL · Redis · Supabase Storage

---

## 1. Repo layout

```
shiptrip/
├── mobile/                    # Flutter app (iOS + Android)
├── backend/
│   ├── monolith/              # Django REST + admin
│   └── services/              # Go services
│       ├── chat-service/
│       ├── notification-service/
│       ├── kyc-service/
│       └── media-service/
└── ARCHITECTURE.md            # this file
```

---

## 2. System topology

```
                    +------------------+
   Flutter <------> |   API Gateway    |  TLS · JWT validation · rate limit · CORS
   (HTTPS/WSS)      | (Kong/Traefik —  |  routes /api/* → Django, /ws/* → Go
                    |   TBD)           |
                    +---+----------+---+
        /api/* --------+          +-------- /ws/chat, /ws/notif
                       v                    /api/media, /api/kyc
              +----------------+        +-----------------------+
              | Django monolith|        | Go services           |
              | REST + admin   |        | chat / notif / kyc /  |
              +-------+--------+        | media                 |
                      |                 +----+------------+-----+
                      | writes               | reads      | uploads
                      v                      v            v
              +----------------+   +----------+   +-------------------+
              |  PostgreSQL    |<--|  Redis   |   | Supabase Storage  |
              |   (shared)     |   | pub/sub  |   | (KYC docs, parcel |
              +----------------+   +----------+   |  photos, etc.)    |
                                                  +-------------------+
```

**Internal traffic** (Django ↔ Postgres ↔ Redis ↔ Go services, Go-to-Go calls) stays on the private network. Only the gateway is publicly exposed.

---

## 3. API Gateway

Single ingress for all client traffic. Must support WebSocket upgrade (rules out plain AWS API Gateway REST).

**Responsibilities:**
- TLS termination, HTTP/2, CORS
- JWT validation at the edge → injects `X-User-Id` and `X-User-Role` headers to upstreams
- Rate limiting / quotas (replaces DRF throttles)
- Path routing:
  - `/api/auth/*`, `/api/trips/*`, `/api/parcels/*`, `/api/matches/*`, `/api/payments/*`, `/api/wallet/*` → Django
  - `/api/kyc/*` → Go kyc-service
  - `/api/media/*` → Go media-service
  - `/ws/chat` → Go chat-service
  - `/ws/notif` → Go notification-service
- Centralized access logs + Prometheus metrics

**Candidates:** Kong, Traefik, Nginx — final choice TBD. Recommendation: **Traefik** for easy WS + auto-TLS via Let's Encrypt.

---

## 4. Django monolith (`backend/monolith/`)

Each module is a Django app under `apps/<name>/`.

| Module | Owns | Key models |
|---|---|---|
| `accounts` | Auth, JWT refresh, phone verification | User, PhoneOTP, RefreshToken |
| `trips` | Traveler trip CRUD, ticket reference, admin approval | Trip, TripStopover, TicketDocument |
| `parcels` | Sender delivery requests + product-purchase requests | DeliveryRequest, ProductRequest, ParcelMedia |
| `matching` | Suggestions, offers, counter-offers, accept/reject | Match, Offer, MatchEvent |
| `verification` | 2-step delivery codes (generate, hash, validate) | PickupCode, DeliveryCode |
| `payments` | Stripe intents, webhooks, commission calc, escrow | PaymentIntent, Transaction, WalletEntry |
| `wallet` | Traveler balance, withdrawal requests | Wallet, Withdrawal |
| `chat` | Conversation + message persistence (Go reads/writes) | Conversation, Message |
| `notifications` | Notification record store (Go pushes via WS) | Notification, NotificationPreference |
| `admin_panel` | Admin actions, audit log, dispute placeholder | AdminAuditLog |
| `core` | Pricing engine, commission tiers, Redis publisher, base serializers | (services + utils) |

**Important:** Django **never stores binary bytes**. All photos / docs / tickets reference Supabase object keys stored in their respective models.

**KYC is NOT here** — it's a Go service.

**Cross-cutting:**
- `core/pricing.py` — single source of truth for commission tiers + base fee
- `core/redis_bus.py` — wrapper for publishing events Go consumes
- Middleware: gateway-header trust (`X-User-Id`), request logging. **No** rate limiting (gateway handles it).

---

## 5. Go services (`backend/services/`)

Four binaries. Shared packages: `pkg/db` (pgx), `pkg/redis`, `pkg/auth` (JWT verify), `pkg/wsproto`, `pkg/supabase`.

### 5.1 chat-service
- WebSocket hub, per-conversation rooms
- Trusts `X-User-Id` from gateway; revalidates JWT as defense-in-depth
- Subscribes to Redis `chat.message.<conversation_id>`
- Persists messages to Postgres `chat_message` (Django-defined schema)
- Typing indicators + presence held in memory

### 5.2 notification-service
- One WebSocket per user (gateway routes `/ws/notif`)
- Subscribes to Redis `notif.user.<user_id>`
- Replays pending notifications from Postgres on connect
- Marks read via WS message → Postgres update

### 5.3 kyc-service
- HTTP API at `/api/kyc/*` for ID upload, status polling, admin review actions
- Owns KYC state machine: `pending → submitted → under_review → approved | rejected`
- **Calls media-service internally** (server-to-server) to push ID front/back/selfie to Supabase. Flutter sends the multipart payload to kyc-service; kyc-service does the orchestration.
- Required gate: travelers cannot publish trips until status = `approved`

### 5.4 media-service
- Single Go upload endpoint at `/api/media/*` (and internal endpoint for service-to-service)
- Receives multipart uploads, validates MIME + size limits per bucket, uploads to Supabase Storage using service-role key (held server-side; never exposed to Flutter)
- Returns `{ bucket, object_key, signed_url, expires_at }`
- **No compression in v1**, but **strict size limits enforced**
- **Thumbnails generated on read** (lazy) — not pre-generated on upload
- **No virus scanning in v1**

**Supabase buckets (separate per content type):**

| Bucket | Visibility | Max size | Used by |
|---|---|---|---|
| `kyc-docs` | private | 10 MB | kyc-service only |
| `parcel-photos` | private (signed URLs) | 5 MB | parcels module |
| `product-photos` | private (signed URLs) | 5 MB | product requests |
| `tickets` | private | 10 MB | trips module |

(Sizes are starting points — adjust after first real-world testing.)

---

## 6. Upload flow

**Sender posts a parcel with a photo:**
```
Flutter → POST /api/parcels (multipart)
  → Gateway (validates JWT, injects X-User-Id)
    → Django parcels endpoint
      → calls media-service internally with the photo
        → media-service uploads to Supabase `parcel-photos` bucket
        ← returns { bucket, object_key }
      ← Django stores object_key in DeliveryRequest.photo_key
    ← 201 Created with parcel + signed photo URL
```

**Traveler submits KYC:**
```
Flutter → POST /api/kyc/submit (multipart: id_front, id_back, selfie)
  → Gateway
    → Go kyc-service
      → for each file: calls media-service internally → Supabase `kyc-docs`
      → stores object keys in kyc.submissions table
      → publishes `kyc.submitted` to Redis (admin notification fan-out)
    ← 202 Accepted (status: under_review)
```

Flutter never gets Supabase credentials. Flutter never uploads directly to Supabase.

---

## 7. Flutter (`mobile/`)

Feature-first folder structure. State management: **pick Riverpod or BLoC, stay consistent.**

```
lib/
├── core/                  # theme, i18n (en/fr/ar+RTL), router, api client (gateway), ws client
├── features/
│   ├── auth/              # signup, login, OTP, phone verify
│   ├── kyc/               # ID upload, status screen
│   ├── home/              # role switch (Sender / Traveler)
│   ├── sender/
│   │   ├── request_delivery/
│   │   ├── request_product/
│   │   └── my_requests/
│   ├── traveler/
│   │   ├── create_trip/
│   │   ├── my_trips/
│   │   └── browse_requests/
│   ├── matching/          # offer, counter-offer, accept
│   ├── verification/      # show/enter pickup + delivery codes
│   ├── payments/          # Stripe sheet, payment summary
│   ├── wallet/            # balance, withdraw
│   ├── chat/              # WS-backed conversation list + thread
│   └── notifications/     # WS-backed feed
└── shared/                # widgets, models, dto
```

All HTTP calls hit `https://api.shiptrip.dz/api/*`. WS connects to `wss://api.shiptrip.dz/ws/*`. There is no other base URL.

---

## 8. Feature list — MVP v1

**Auth & identity:** phone+email signup, OTP verify, JWT (15min) + refresh (7d, hashed).

**KYC (Go):** ID front/back + selfie upload. Admin approval required before traveler can list trips.

**Sender:** request delivery (type, weight, photo, pickup/delivery, date), request product (item, max price), my-requests list with status.

**Traveler:** create trip (origin, destination, dates, stopovers, max weight, accepted types, mandatory ticket), trip-approval queue (admin-gated), browse compatible requests.

**Matching:** suggestions, offer / counter-offer / accept, on-accept → payment required → chat unlocked.

**Verification:** 2-step codes. Code 1 (pickup) sender → traveler. Code 2 (delivery) sender → final receiver → traveler enters.

**Payments (Stripe v1):** payment intent on match acceptance, commission engine, wallet ledger (held → released on delivery), manual admin-approved withdrawals.

**Chat & notifications (Go):** 1:1 chat per match (text-only), notifications for match offer / accepted / payment / code requested / delivered.

**Admin (Django web, out of mobile scope):** users + KYC approval, trip approval, withdrawal approval, financials, audit log.

---

## 9. Commission rules (load-bearing)

**Delivery payments:**
- Platform takes **25%** flat from each delivery
- Sender sees and pays the full total price
- Traveler sees the total and the 25% deduction

**Product-request payments:**
- Base fee: **2,500 DZD**
- Tiered commission on item price:

| Item price (DZD) | Commission |
|---|---|
| Under 30,000 | 0% |
| 30,000 – 54,999 | 7% |
| 55,000 – 99,999 | 5% |
| 100,000 and above | 3% |

- Sender pays: item price + base fee + commission
- Traveler receives **100% of item price** (no commission deducted from them)

---

## 10. Deferred to v2

- Ratings & reviews
- Dispute resolution UI
- Boost (paid promotion)
- Insurance
- Local DZ payment rails (CIB / Edahabia / Baridimob)
- Push notifications (FCM)
- Image / file attachments in chat
- Image compression on upload
- Virus scanning
- Pre-generated thumbnails

---

## 11. Decisions taken at kickoff

| Topic | Decision |
|---|---|
| Public ingress | Single API gateway (Kong/Traefik/Nginx — TBD) fronts Django + Go |
| Auth at edge | Gateway validates JWT, injects `X-User-Id` to upstreams |
| Service comms | Shared Postgres + Redis pub/sub (private network) |
| Realtime transport | WebSockets via gateway (must support WS upgrade) |
| Object storage | Supabase Storage; all uploads through Go media-service |
| Django + bytes | Django **never** stores raw bytes; only Supabase object keys |
| Buckets | Separate bucket per content type (kyc-docs, parcel-photos, product-photos, tickets) |
| Compression | None in v1; size limits enforced; thumbnails on read |
| Virus scanning | Deferred |
| KYC ↔ media | KYC service calls media-service **internally** (Flutter doesn't pre-upload) |
| KYC location | Go service, not a Django app |
| Payments v1 | Stripe-style cards; local DZ rails deferred |
| Ratings / disputes / boost | Deferred to v2 |
| Old Node prototype | Removed — clean slate |

---

## 12. Next step

Begin Flutter base UI/UX: design system (theme, typography, spacing, color tokens), routing skeleton, role-switch home, then auth + KYC screens. Backend scaffolding follows once screens validate the data shapes.
