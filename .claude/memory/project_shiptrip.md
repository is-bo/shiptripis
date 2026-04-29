---
name: ShipTrip project
description: P2P delivery + product-purchase platform for Algeria; Flutter + API gateway + Django monolith + Go services + Postgres
type: project
---
ShipTrip is a peer-to-peer platform connecting Senders (post delivery requests or product-purchase requests) with Travelers (list trips, fulfill requests). Pricing in DZD. Algeria-focused — corridor between Algeria and France.

**Repo layout:**
- `mobile/` — Flutter app (iOS + Android). Scaffolded 2026-04-29 with Riverpod (Notifier API, v3) + go_router + flutter_animate + google_fonts + country_flags v4 (no width/height — wrap in SizedBox). Aesthetic = "Mediterranean transit": parchment cream + emerald + terracotta + gold; Fraunces display + DM Sans body + JetBrains Mono. State management: **Riverpod**.
- `backend/monolith/` — Django REST monolith (auth, trips, parcels, matching, payments, wallet, chat persistence, notifications store, admin)
- `backend/services/` — Go microservices: realtime chat, notifications, **KYC**, **media gateway** (all photo/document uploads → Supabase storage)

**Stack decisions (target build):**
- Mobile: Flutter
- Public ingress: API Gateway (Kong / Traefik / Nginx — TBD; must support WS upgrade, so plain AWS API Gateway REST is out). Gateway terminates TLS, validates JWT, injects X-User-Id header, handles rate limiting + CORS.
- Backend monolith: Django (REST + admin)
- Async / specialized services: Go — chat (WS), notifications (WS), KYC (ID/selfie processing + admin review API), media gateway (single upload endpoint for all binary content)
- DB: PostgreSQL (shared between Django and Go services)
- Object storage: **Supabase Storage** — all media (KYC docs, parcel photos, product item photos, ticket scans) uploaded via the Go media gateway, never directly from Flutter to Supabase
- Service comms: Shared Postgres + Redis pub/sub (Django publishes events, Go services subscribe). Internal traffic stays on private network — never through gateway.
- Realtime: WebSockets only in v1 (no FCM push yet)
- Payments v1: Stripe-style cards (local DZ rails — CIB/Edahabia/Baridimob — deferred)
- Deferred to post-MVP: ratings/reviews, dispute resolution flow, boost feature, insurance, image attachments in chat

**KYC + media in Go (NOT in Django):**
- KYC service: ID upload, admin verify, KYC state machine — lives in `backend/services/`
- Media gateway service: single Go upload endpoint that receives ALL binary content from the app (KYC docs, parcel photos, product item photos, ticket uploads) and pushes to Supabase Storage. Returns Supabase object key/URL; Django stores only the reference, never the bytes.
- Required in MVP — travelers cannot list trips until KYC approved
- Django reads KYC status from shared Postgres (or via internal API call to Go KYC service — TBD)
- Flutter never uploads directly to Supabase — always goes Flutter → API gateway → Go media service → Supabase.
- Supabase auth: media-service holds service-role key server-side; Flutter never sees Supabase credentials.
- Buckets: separate per content type (e.g. `kyc-docs`, `parcel-photos`, `product-photos`, `tickets`) — not one shared bucket with prefixes.
- Image handling v1: no compression on upload, but enforce **size limits** (per-bucket max bytes). Thumbnails generated **on read** (lazy), not pre-generated.
- No virus scanning in v1.
- KYC service calls media-service **internally** (server-to-server). Flutter sends KYC payload to kyc-service; kyc-service then forwards files to media-service. Flutter does NOT upload to media-service first and pass the key.

**Commission rules (load-bearing):**
- Delivery payments: 25% platform commission flat
- Product requests: 2,500 DZD base fee + tiered commission (0% under 30k, 7% 30–55k, 5% 55–100k, 3% 100k+)
- Traveler always receives 100% of item price for product requests

**Verification flow (load-bearing):**
- 2-step code: sender gives code 1 at pickup → traveler enters → "In Transit"; sender gives code 2 to final receiver → confirms delivery
- Trips require admin approval (ticket upload mandatory)

**Why:** Modular architecture and clean separation between monolith (CRUD/business logic) and Go services (realtime + KYC + media).
**How to apply:** When discussing ShipTrip features:
- Don't put KYC in Django — it's a Go service.
- Don't suggest FCM/push for v1.
- Don't propose ratings/disputes/boost for MVP.
- All public traffic flows through the API gateway — Flutter never hits Django/Go directly.
- Rate limiting belongs in gateway, not DRF throttles.
- All media uploads go: Flutter → API gateway → Go media service → Supabase Storage. Django only stores Supabase object references, never raw bytes. Don't suggest direct-to-Supabase signed URLs from Flutter for v1 — server-mediated upload is the chosen design.
