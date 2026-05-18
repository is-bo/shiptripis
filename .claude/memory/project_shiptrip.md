---
name: ShipTrip project
description: P2P delivery + product-purchase platform for Algeria; Flutter + Caddy + Django monolith + Go services + Postgres + Redis + MinIO/S3
type: project
---
ShipTrip is a peer-to-peer platform connecting Senders (delivery requests or product-purchase requests) with Travelers (list trips, fulfill requests). Pricing in DZD. Algeria-focused, primary corridor Algeria ↔ France.

V1 architecture is **locked** (commit 058f25d). Source of truth: `ARCHITECTURE.md` + `CLAUDE.md`. Read those before acting; this memory is just a session-start hook.

**Two Claudes split:**
- Claude A (Islam): `mobile/`, `backend/monolith/` (Django apps + migrations), `contracts/sql/schema.sql`, Django gRPC server, Django redis publisher.
- Claude B (this user, on this machine — writes Go): `backend/services/` (Go workspace), `contracts/grpc/*.proto` (jointly), sqlc consumption, Go gRPC clients.
- Shared (require explicit user approval to touch): `gateway/Caddyfile`, `docker-compose.yml`, master `Taskfile.yml`, `.env.example`, `ARCHITECTURE.md`, `CLAUDE.md`.

**Stack (V1, locked):**
- Mobile: Flutter (Riverpod 3 Notifier API, country_flags v4 wrapped in SizedBox).
- Public ingress: **Caddy** (auto-TLS, native WS, no JWT validation at edge — services validate themselves).
- Monolith: Django (REST + admin) — owns 100% of migrations.
- Go services: `cmd/chat`, `cmd/notif` (WS hub + FCM consumer in one binary), `cmd/kyc` (HTTP + MinIO + Django gRPC client).
- DB: shared Postgres. Django uses ORM; Go uses `pgxpool` + sqlc-generated repos reading `contracts/sql/schema.sql`.
- Object storage: **MinIO** in dev, S3-compatible (Hetzner/Backblaze/Wasabi) in prod, abstracted via `pkg/storage/s3.go` (aws-sdk-go-v2). No MinIO-specific admin calls.
- Service comms: shared Postgres + Redis (pub/sub for WS fan-out, streams for FCM queue) + gRPC mTLS for Django↔Go (KYC RecordSubmission).
- Realtime: WS first, **FCM fallback** (yes, FCM is V1 — only custom topics/segmentation are V2).
- Payments V1: Stripe-style cards. Local DZ rails (CIB/Edahabia/Baridimob) deferred.

**6 production guardrails (do not skip — see CLAUDE.md §2):**
- G1 multi-pod presence + delivery receipts (`presence:<uid>` 15s TTL, `delivered:<event_id>` 60s TTL, FCM consumer waits 2s before fallback, XAUTOCLAIM sweeper 30s).
- G2 JWT clock-skew leeway 30s on both sides.
- G3 schema-drift CI gate runs BOTH `task contract:sync-db` AND `task contract:generate` then `git diff --exit-code`.
- G4 S3-compatible abstraction, no MinIO-specific code.
- G5 gRPC mTLS in prod (bearer only allowed in docker-compose dev). 16 MB max msg size both sides.
- G6 Redis publish always inside `transaction.on_commit`, plus `published_event` audit row (G6b detection-only outbox; full outbox is V2).

**Connection pool budget (load-bearing):** Postgres `max_connections=100`. Allocation: Django 20, chat 30 (2×15), notif 10, kyc 5, reserved 10 = 75 used. Headroom for one extra Go pod = 25 conn — update `pgxpool.MaxConns` before scaling.

**Commission rules (load-bearing, frozen on Offer at creation):**
- Delivery: 25% flat platform commission, sender pays total.
- Product: 2,500 DZD base fee + tiered commission on item price (0% <30k, 7% 30–55k, 5% 55–100k, 3% 100k+). Traveler always receives 100% of item price.
- Single source: `monolith/apps/core/pricing.py`. Integer DZD, no floats.

**Verification flow (load-bearing):** 2-step argon2-hashed handover code (PICKUP → "In Transit", DELIVERY → confirm). Trips require admin approval (ticket upload mandatory).

**Local dev (Windows + WSL Ubuntu):** docker-compose up from inside WSL. Redis exposed on **host port 6380** (native redis-server holds 6379); inside compose network services still use `redis:6379`. Don't run native `psql`/`redis-cli` against containers — separate instances.

**Why:** V1 architecture survived a brutal review and the 6 guardrails each neutralize a specific distributed-systems failure class. Drifting from them is what causes silent prod outages.
**How to apply:** When working on backend tasks:
- Verify scope (Claude A vs B) before touching files.
- Never put `redis.publish` inside an open Django transaction — always `transaction.on_commit`.
- `presence:<user_id>` TTL is 15s, not 30s. WS ping interval is 10s. TTL must be tighter than ping.
- FCM consumer waits 2s, then checks `delivered:<event_id>`, then maybe 2s more if presence online — never fall back immediately.
- Production gRPC = mTLS, never static bearer.
- Don't add a 6th Go service. Don't pre-generate thumbnails. Don't compress images server-side in V1. Don't change `Airport.iata` to surrogate id without a migration plan.
- Pricing changes go in `pricing.py`, never in schema. Old Offers settle at frozen rates.
- Mobile: no `Spacer` inside scrollable columns; reconnect logic must use exponential backoff with ±30% jitter.
- Don't merge with failing `check-drift`.
