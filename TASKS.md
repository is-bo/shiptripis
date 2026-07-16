# TASKS.md — running task list (Islam + Alaa)

**Workflow rule (both Claudes):**

1. `git pull` before reading this file (or doing anything).
2. When you finish a task, move it under **Done** with a date + commit SHA.
3. When you discover new work, add it under the right owner.
4. Commit & push this file as part of the same PR/commit that does the work,
   so the other side sees it immediately.

If you're a Claude session, **read this file at session start** (just like
CLAUDE.md). Don't claim a task that's `in-progress` for the other owner.

---

## Islam (Claude A — Django + mobile)

### Now (blocking demo polish)

- [ ] **KYC key migration (only before real KYC data ships)** — Alaa fixed `imageKey` to drop the doubled `kyc-docs/` prefix (keys are now `<uid>/<idem>-<field>.<ext>`, bucket-relative). New uploads are clean; existing data is not. One-time migration: (1) strip leading `kyc-docs/` from existing `kyc_submission` key columns in a reversible data migration; (2) `mc mv --recursive local/kyc-docs/kyc-docs/ local/kyc-docs/` for existing objects. No-op on a fresh/dev volume. Full spec in `services/HANDOVER.md` → "imageKey prefix fix".
- [ ] **Pickup code: don't regenerate on re-fetch** — the code is currently rotated on every issue call. Should be saved once on the accepted match and shown to the sender from "My requests" until the traveler enters it.
- [ ] **Mobile: post-payment screen → "your code is X" + push to sender** — after sender pays, they land on a screen showing the pickup code with copy button; same code is pushed via notification.
- [ ] **Mobile: traveler "enter pickup code" entry surface** — traveler gets a notification after payment ("ready for pickup, enter code"); deep-link routes to `/handover/verify/<match_id>?kind=pickup`.
- [ ] **Mobile: sender follow-package screen after pickup code accepted** — when `match.in_transit` fires, sender's notification deep-links to `/tracking/<match_id>` (the progress screen).
- [ ] **Mobile: counter-offer flow only when sender requested a specific traveler** — if the sender posted a *general* request, traveler offer is accept/decline only (price was sender-computed). If the sender targeted *this traveler*, traveler can counter.
- [ ] **Email-service Django side: `email:send` stream publisher + `EmailVerificationCode` model + SMTP settings** — Go email-service is built and gated dark (Alaa, 2026-06-05). Full 5-piece spec in `backend/services/HANDOVER.md` (email-service section). In short: (1) add `redis_bus.enqueue_email_after_commit(to,subject,body,*,kind)` doing `XADD email:send MAXLEN ~ 10000` + PublishedEvent (first XADD in Django — redis_bus is pub/sub-only today); (2) `EmailVerificationCode` model (clone `PasswordResetCode`) + reversible migration + `task contract:sync-db`; (3) signup issues a verify code + publishes `kind="verify"`, add `POST /accounts/verify-email` that sets `is_email_verified=True`; (4) password-reset view: swap synchronous `send_mail` → `enqueue_email_after_commit(kind="reset")`; (5) prod SMTP `EMAIL_*` + `DEFAULT_FROM_EMAIL` + a `mailhog` compose service for local e2e. When it lands: flip `EMAIL_ENABLED=true` + `EMAIL_SMTP_*` — no Go change needed.

### Soon

- [ ] **`auth_storage.dart` role hydration race** — first frame paints sender UI, then hydration may flip to traveler. Acceptable but worth a splash gate.
- [ ] **Sender flow: counter-offer UI in `match_detail_screen`**.
- [ ] **Real traveler names on offer/traveler cards** — `_OfferRow` + `_TravelerCard` in `request_detail_screen.dart` (and the incoming-match cards) still render `Traveler #<id>`. Needs `MatchSummary` to carry the traveler's display name (Django join in `apps/matching` serializer → `parcels`/`matching` providers). KYC badge intentionally out of scope for now.
- [ ] **WS-driven live offer updates** — when a sender accepts while the traveler is on `match_detail_screen` (or vice-versa), the screen doesn't auto-refresh; `offer.created`/`offer.accepted`/`offer.updated` WS events should invalidate `offerListProvider(matchId)` + `matchDetailProvider`. Today only user actions call `_refreshAll()`. Also: no pull-to-refresh on that screen.
- [ ] **Notifications UX polish** — unread badge on the notifications bottom-nav tab; clear stale `error` on successful refresh; surface a spinner on subsequent (non-initial) refreshes. (From 2026-06-11 UX audit.)
- [ ] **Chat: live "Mailroom" thread list** — `chat_list_screen.dart` (the Conversations bottom-nav tab) is still a static mockup with hardcoded convos. Needs a `GET /api/chat/threads` endpoint returning the user's eligible (paid) matches with last-message snippet + unread count + counterparty name, then a Riverpod provider to replace the `_convos` const. Live 1:1 threading already works end-to-end via `request_detail_screen` → `/chat/<match_id>`; this is just the inbox surface.
- [ ] **Post-apply refresh** — after a traveler applies in `find_parcels_screen`, `match_detail_screen` should invalidate its offer list on first load so the new offer shows without a manual back-and-forth.

### Done

- [x] 2026-07-16 **Regenerate `contracts/sql/schema.sql` + local backend brought up**: stood up the full compose stack on a fresh machine (WSL2 Ubuntu 24.04 + native Docker Engine — no Docker Desktop) and re-exported the schema via `pg_dump --schema-only` (the `contract:sync-db` recipe). Was stale: missing `notification`, TripMedia + role-default migrations, and `chat_message`. Now 36→38 tables, `chat_message` + `notification` present → clears the red `check-drift`. Also added `backend/monolith/.dockerignore` (real build fix: `COPY . .` was streaming the 162 MB / ~12k-file host `.venv` into the Django build context and OOM'ing the WSL 9p mount; also excludes `test_local.py`/`.env`/caches). Migrations apply clean; Django `:8000/healthz` + Caddy `:8080/healthz` green; gateway routes to Django (chat endpoint `matches/<id>/chat/messages` live). **Note for Alaa:** the chat sqlc repo is NOT a mobile dependency — the Go chat-service is a stateless WS relay (`hub.go`/`dispatcher.go`/`handler.go`, no HTTP history endpoint); mobile reads thread history from **Django** `GET /api/matches/<id>/chat/messages`. So `contract:generate` for a chat repo is a V1-deferred nicety, not a blocker (this corrects the earlier stale note). Heads-up: pg16 `pg_dump` emits `\restrict`/`\unrestrict` psql meta-commands atop schema.sql — confirm sqlc tolerates them if/when you generate.
- [x] 2026-07-15 **Chat mobile (Flutter side) — live thread wired end-to-end**: `core/chat/` = `chat_repository.dart` (ChatMessage model + `listMessages`/`sendMessage`, maps backend `reason` codes → user copy on 402/403), `chat_ws_client.dart` (long-lived `/ws/chat` client mirroring the notification client: Bearer-header upgrade, §7 exp-backoff+jitter cap 30s, reuses `NotificationEnvelope`), `chat_providers.dart` (Riverpod 3 `NotifierProvider.family` thread notifier — seeds from GET history, stays live on the shared socket filtered by `match_id`, dedupes the WS echo by id; socket lifecycle tied to auth). `features/chat/chat_thread_screen.dart` = real message list (own=emerald-right / other=white-left bubbles), composer, auto-scroll, pull-to-refresh, gated-error copy. Route `/chat/:matchId` swapped stub → real screen; deleted the now-dead `chat_stub_screen.dart`. `flutter analyze` error-free (21 pre-existing info-lints unchanged); full Django suite green (192). **Note:** `chat_list_screen.dart` (the "Mailroom" tab) is still the static mockup — wiring it live needs a "my active threads" list endpoint that doesn't exist yet (logged under Soon). Entry into a live thread today is via `request_detail_screen` → `/chat/<match_id>`.
- [x] 2026-07-13 **Chat backend (Django side) — payment-gated 1:1 messaging** (`99fbe77`): new `apps/chat` with `ChatMessage` model (table `chat_message`) + reversible migration; `POST/GET /api/matches/<id>/chat/messages` (send persists + publishes `chat.message.new` with `targets=[other_member]`; list = paginated oldest-first, parties only). Extracted the chat-eligibility rule into `apps/matching/services.py` so the pre-flight endpoint + send path share one source of truth. Added `CHAT_MESSAGE_NEW` to `core/channels.py`. 8 tests; full suite green (165) on local sqlite; ruff clean. **Follow-up:** schema.sql sync (folded into the Now item above) so Alaa can add the chat sqlc repo for history. Wires the Go chat-service (built 2026-05-22, relay-only) end-to-end.
- [x] 2026-07-13 **UX polish pass** (`0b11296`,`6fdeeb9`,`10f869a`,`fc1afad`,`c2706f7`; + compile fix `84b5a4d`): executed the parked 2026-06-17 plan — nav unread badge, match-detail pull-to-refresh, real sender/traveler names (matching+trips serializers + mobile, 4 render sites), role-hydration boot gate. Also fixed a whole-app compile blocker: Flutter 3.44.4 stopped re-exporting `CupertinoPageTransitionsBuilder` via `material.dart` (explicit cupertino import). `flutter analyze` error-free (21 pre-existing info-lints unchanged); Django 157→green.
- [x] 2026-06-11 UX bug-fix pass (sender + traveler smoothness, `ee44d58`): fixed 3 dead notification deep-links (`trip.created`→nonexistent `/traveler/trips`, plus silent `parcel.cancelled`/`trip.cancelled`/`match.created`); removed pre-filled demo values from payment + create-trip forms (test card / `AH 1004`); added inline validation to the apply-to-carry asking-price field (empty allowed = backend default; non-empty `<100` DZD blocked inline to match serializer `min_value=100`). `flutter analyze` clean. Follow-ups logged under Soon. Also reconciled git: merged Alaa's KYC branch (`c1b8de3`), restored coordination files (CLAUDE.md/.claude/session docs) that had been deleted on-disk, recovered prior-session WIP.
- [x] 2026-06-02 Bug bash + product-grade pass: sign-out, sender "All" tab, notifications persistence (server-backed inbox + WS dedupe), traveler "on the road" surface, profile real data. Notification model + GET/POST endpoints + WS hooks landed; mobile notifications screen rewritten with deep-link routing + mark-read.
- [x] 2026-05-28 `78ac9e4` ~~**Audit Django publish targets**~~ — confirmed: all 14 publish sites already pass `targets=[uid,...]` as kwarg via `redis_bus.publish_after_commit`. Go now reads only `targets`; legacy `recipient_id`/`sender_id`/`traveler_id` in payloads are forwarded raw to mobile but no longer consulted for routing.
- [x] 2026-05-23 `9c4ce7f` Merge demo → main, dispatcher conflict resolved in Alaa's favor.
- [x] 2026-05-23 `605feee` Role: UI-only (no server gating), always-on switch pill.
- [x] 2026-05-23 `08a07a3`/`791822b` Render free-tier blueprint (lives on `demo-prod`).

---

## Alaa (Claude B — Go services)

### Now (blocking demo polish)

- [ ] (none unblocked) — FCM real sender + email-service are both built and gated dark; both wait on Islam (see below + the Islam section).

### Soon

- [ ] (none)

### Done

- [x] 2026-07-11 Test coverage for `internal/notification/fcm_firebase.go` (the real Firebase Admin SDK sender Islam merged via PR #2, previously untested). Added a one-method `multicaster` seam (`*messaging.Client` satisfies it via promoted `SendEachForMulticast`) so `Send` is testable without a live FCM project. `fcm_firebase_test.go` covers: `NewFirebaseSender` fail-loud paths (empty/unreadable/invalid creds → boot error, §9); `Send` branches — empty tokens no-op, all-succeed→nil, partial-failure→nil (no full-batch resend = no duplicate push), all-failed→err (stays in PEL for sweep), transport-error→err with event_id; payload→MulticastMessage field mapping; FCMSender interface satisfaction. Reviewed FCM wiring in `cmd/notification/main.go` — `LogOnlySender`→`firebaseSender` swap leaves the `fcmAlive`/`fcmErr` shutdown drain correct; no change needed. `go test -race ./...` green. Still gated dark (`FCM_ENABLED=false`) pending Islam's `fcm_token` schema + `notif:fcm` publisher.
- [x] 2026-06-08 Wire Go-client mTLS for KYC gRPC (`grpc_client.go:tlsCredentials`): loads client cert/key + private CA from `GRPC_TLS_CA_CERT`/`GRPC_TLS_CLIENT_CERT`/`GRPC_TLS_CLIENT_KEY` (all required when `GRPC_AUTH_MODE=mtls`; missing/bad certs fail boot, §9), builds `credentials.NewTLS` with the CA as the only trusted root. `pkg/config.LoadKYCGRPC` reads + validates the trio; `cmd/kyc/main.go` threads them through. Tests generate a throwaway CA+client cert with `crypto/x509` and cover valid creds + 5 failure modes + mtls-fail-fast-at-boot. `.env.example` documents the vars. **Server half (runkycgrpc.py) + cert pipeline remain Islam/shared** (see Shared below). `go test -race ./...` green.
- [x] 2026-06-07 Fix `imageKey` doubled `kyc-docs/` prefix — keys are now bucket-relative (`<uid>/<idem>-<field>.<ext>`) instead of `kyc-docs/kyc-docs/<uid>/…`. Handler test asserts no bucket-name repeat. Flagged the stored-key migration for Islam (see Islam/Now). `go test -race ./internal/kyc/` green.
- [x] 2026-06-07 Test coverage for the untested shared `pkg/*`: `pkg/config` (99%, every env loader incl. URL build + GRPC/FCM validation tables), `pkg/health` (97%, liveness/readiness/MarkReady/panic-containment), `pkg/logger` (100%), `pkg/wsproto` (bearerToken + Send drop semantics + Close once-guard + envelope JSON + ping<TTL invariant), `pkg/db` (NewPool fail-fast validation + orDefault). Now every package is tested except `cmd/*` (wiring-only) and `kycpb` (generated). `go test -race ./...` green. HANDOVER.md gap table + day-one checklist updated.
- [x] 2026-06-05 **email-service (4th Go service)** — `cmd/email` + `internal/email` (sender iface, go-mail `smtpSender`, FCM-cloned stream consumer w/o grace-wait, `email:sent:<id>` dedup), `config.LoadEmail`, compose `email-service` block + `.env.example` `EMAIL_*` + `go.mod` go-mail v0.7.2. Gated `EMAIL_ENABLED=false`; verified booting green (health 200, consumer-disabled, clean shutdown) vs throwaway Redis. No Postgres (off §3 budget). Build/vet/gofmt/`test -race ./...` green. Django spec handed to Islam.
- [x] 2026-06-05 **FCM real sender wired** — `internal/notification/fcm_firebase.go` (firebase-admin-go v4 `SendEachForMulticast`, partial-failure tolerant, flags unregistered/invalid tokens), replaces `Sender:nil` in `cmd/notification/main.go`. Still behind `FCM_ENABLED=false`. Build/vet/`test -race ./internal/notification` green.
- [x] 2026-05-30 Production hardening pass (final-product reframe): new `pkg/metrics` (expvar Group, `/debug/vars` on both services); SetEX retry on `delivered:<event_id>`; bounded dispatch worker pool (128/pod, drop-on-saturation with event_id); pubsub buffer 64→1024 + drop event_id/counter; presence initial-write retry. All build/vet/race green.
- [x] 2026-05-28 `78ac9e4` Dispatcher: subscribe to all 16 Django channels via generic `targets=[uid,...]` envelope. Per-channel structs dropped; `dispatch` now fans by `targets` for every channel uniformly. Existing audit/receipt path unchanged.
- [x] 2026-05-23 Notification service added to `docker-compose.yml` + `Dockerfile.notification`; Caddy upstream renamed `notification-service` → `notification` (fixes 502 on `/ws/notifications`).
- [x] 2026-05-22 `c7e80a8` Hardened Go services from senior review.
- [x] 2026-05-22 `c04a369` Chat service V1.
- [x] 2026-05-22 `f00b3e6` FCM consumer scaffold (gated).

---

## Shared / cross-cutting

- [ ] **mTLS for gRPC** (CLAUDE.md G5) — production gate before V1 launch. **Go client side DONE** (2026-06-08, Alaa). Remaining:
  - [ ] **Islam:** Django mTLS server branch in `runkycgrpc.py` — replace the `raise SystemExit` stub with `grpc.ssl_server_credentials([(server_key, server_cert)], root_certificates=ca, require_client_auth=True)` + `add_secure_port`.
  - [ ] **Shared:** cert-issuing pipeline — mkcert (local) / cert-manager (K3s) to mint the shared self-signed CA + a cert per service (90-day, auto-renew per §G5). Mount cert paths into the kyc-service + django-grpc containers; set `GRPC_AUTH_MODE=mtls` + the `GRPC_TLS_*` paths.
