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

## Open PRs (awaiting review/merge — as of 2026-06-08)

- **PR #1** `feat/kyc-mtls-client` → `main` — imageKey doubled-prefix fix +
  shared `pkg/*` test coverage (`b5f4bbe`) **and** Go-client mTLS for the KYC
  gRPC dial (`f88259a`). **Merging this is what delivers the imageKey migration
  note to Islam** (see Islam/Now). Mergeable, all Go tests green.
- **PR #2** `feat/email-service-and-fcm-sender` → `main` — 4th Go service, the
  SMTP email transport, shipped gated dark (`EMAIL_ENABLED=false`). Independent;
  needs Islam's Django `enqueue_email_after_commit` publisher before it does
  anything live. Mergeable.

---

## Islam (Claude A — Django + mobile)

### Now (blocking demo polish)

- [ ] **Regenerate `contracts/sql/schema.sql`** — TripMedia + role-default migrations not reflected; CI `check-drift` fails. Run `task contract:sync-db`, commit the diff.
- [ ] **KYC key migration (only before real KYC data ships)** — Alaa fixed `imageKey` to drop the doubled `kyc-docs/` prefix (keys are now `<uid>/<idem>-<field>.<ext>`, bucket-relative). New uploads are clean; existing data is not. One-time migration: (1) strip leading `kyc-docs/` from existing `kyc_submission` key columns in a reversible data migration; (2) `mc mv --recursive local/kyc-docs/kyc-docs/ local/kyc-docs/` for existing objects. No-op on a fresh/dev volume. Full spec in `services/HANDOVER.md` → "imageKey prefix fix".
- [ ] **Pickup code: don't regenerate on re-fetch** — the code is currently rotated on every issue call. Should be saved once on the accepted match and shown to the sender from "My requests" until the traveler enters it.
- [ ] **Mobile: post-payment screen → "your code is X" + push to sender** — after sender pays, they land on a screen showing the pickup code with copy button; same code is pushed via notification.
- [ ] **Mobile: traveler "enter pickup code" entry surface** — traveler gets a notification after payment ("ready for pickup, enter code"); deep-link routes to `/handover/verify/<match_id>?kind=pickup`.
- [ ] **Mobile: sender follow-package screen after pickup code accepted** — when `match.in_transit` fires, sender's notification deep-links to `/tracking/<match_id>` (the progress screen).
- [ ] **Mobile: counter-offer flow only when sender requested a specific traveler** — if the sender posted a *general* request, traveler offer is accept/decline only (price was sender-computed). If the sender targeted *this traveler*, traveler can counter.

### Soon

- [ ] **`auth_storage.dart` role hydration race** — first frame paints sender UI, then hydration may flip to traveler. Acceptable but worth a splash gate.
- [ ] **Sender flow: counter-offer UI in `match_detail_screen`**.
- [ ] **Real traveler names on offer/traveler cards** — `_OfferRow` + `_TravelerCard` in `request_detail_screen.dart` (and the incoming-match cards) still render `Traveler #<id>`. Needs `MatchSummary` to carry the traveler's display name (Django join in `apps/matching` serializer → `parcels`/`matching` providers). KYC badge intentionally out of scope for now.
- [ ] **WS-driven live offer updates** — when a sender accepts while the traveler is on `match_detail_screen` (or vice-versa), the screen doesn't auto-refresh; `offer.created`/`offer.accepted`/`offer.updated` WS events should invalidate `offerListProvider(matchId)` + `matchDetailProvider`. Today only user actions call `_refreshAll()`. Also: no pull-to-refresh on that screen.
- [ ] **Notifications UX polish** — unread badge on the notifications bottom-nav tab; clear stale `error` on successful refresh; surface a spinner on subsequent (non-initial) refreshes. (From 2026-06-11 UX audit.)
- [ ] **Post-apply refresh** — after a traveler applies in `find_parcels_screen`, `match_detail_screen` should invalidate its offer list on first load so the new offer shows without a manual back-and-forth.

### Done

- [x] 2026-06-11 UX bug-fix pass (sender + traveler smoothness, `ee44d58`): fixed 3 dead notification deep-links (`trip.created`→nonexistent `/traveler/trips`, plus silent `parcel.cancelled`/`trip.cancelled`/`match.created`); removed pre-filled demo values from payment + create-trip forms (test card / `AH 1004`); added inline validation to the apply-to-carry asking-price field (empty allowed = backend default; non-empty `<100` DZD blocked inline to match serializer `min_value=100`). `flutter analyze` clean. Follow-ups logged under Soon. Also reconciled git: merged Alaa's KYC branch (`c1b8de3`), restored coordination files (CLAUDE.md/.claude/session docs) that had been deleted on-disk, recovered prior-session WIP.
- [x] 2026-06-02 Bug bash + product-grade pass: sign-out, sender "All" tab, notifications persistence (server-backed inbox + WS dedupe), traveler "on the road" surface, profile real data. Notification model + GET/POST endpoints + WS hooks landed; mobile notifications screen rewritten with deep-link routing + mark-read.
- [x] 2026-05-28 `78ac9e4` ~~**Audit Django publish targets**~~ — confirmed: all 14 publish sites already pass `targets=[uid,...]` as kwarg via `redis_bus.publish_after_commit`. Go now reads only `targets`; legacy `recipient_id`/`sender_id`/`traveler_id` in payloads are forwarded raw to mobile but no longer consulted for routing.
- [x] 2026-05-23 `9c4ce7f` Merge demo → main, dispatcher conflict resolved in Alaa's favor.
- [x] 2026-05-23 `605feee` Role: UI-only (no server gating), always-on switch pill.
- [x] 2026-05-23 `08a07a3`/`791822b` Render free-tier blueprint (lives on `demo-prod`).

---

## Alaa (Claude B — Go services)

### Now (blocking demo polish)

- [ ] **FCM consumer** is scaffolded behind `FCM_ENABLED=false`. Needs `fcm_token` schema from Islam before unblocking.

### Soon

- [ ] (none)

### Done

- [x] 2026-06-08 Wire Go-client mTLS for KYC gRPC (`grpc_client.go:tlsCredentials`): loads client cert/key + private CA from `GRPC_TLS_CA_CERT`/`GRPC_TLS_CLIENT_CERT`/`GRPC_TLS_CLIENT_KEY` (all required when `GRPC_AUTH_MODE=mtls`; missing/bad certs fail boot, §9), builds `credentials.NewTLS` with the CA as the only trusted root. `pkg/config.LoadKYCGRPC` reads + validates the trio; `cmd/kyc/main.go` threads them through. Tests generate a throwaway CA+client cert with `crypto/x509` and cover valid creds + 5 failure modes + mtls-fail-fast-at-boot. `.env.example` documents the vars. **Server half (runkycgrpc.py) + cert pipeline remain Islam/shared** (see Shared below). `go test -race ./...` green.
- [x] 2026-06-07 Fix `imageKey` doubled `kyc-docs/` prefix — keys are now bucket-relative (`<uid>/<idem>-<field>.<ext>`) instead of `kyc-docs/kyc-docs/<uid>/…`. Handler test asserts no bucket-name repeat. Flagged the stored-key migration for Islam (see Islam/Now). `go test -race ./internal/kyc/` green.
- [x] 2026-06-07 Test coverage for the untested shared `pkg/*`: `pkg/config` (99%, every env loader incl. URL build + GRPC/FCM validation tables), `pkg/health` (97%, liveness/readiness/MarkReady/panic-containment), `pkg/logger` (100%), `pkg/wsproto` (bearerToken + Send drop semantics + Close once-guard + envelope JSON + ping<TTL invariant), `pkg/db` (NewPool fail-fast validation + orDefault). Now every package is tested except `cmd/*` (wiring-only) and `kycpb` (generated). `go test -race ./...` green. HANDOVER.md gap table + day-one checklist updated.
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
