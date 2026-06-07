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

- [ ] **Regenerate `contracts/sql/schema.sql`** — TripMedia + role-default migrations not reflected; CI `check-drift` fails. Run `task contract:sync-db`, commit the diff.
- [ ] **KYC key migration (only before real KYC data ships)** — Alaa fixed `imageKey` to drop the doubled `kyc-docs/` prefix (keys are now `<uid>/<idem>-<field>.<ext>`, bucket-relative). New uploads are clean; existing data is not. One-time migration: (1) strip leading `kyc-docs/` from existing `kyc_submission` key columns in a reversible data migration; (2) `mc mv --recursive local/kyc-docs/kyc-docs/ local/kyc-docs/` for existing objects. No-op on a fresh/dev volume. Full spec in `services/HANDOVER.md` → "imageKey prefix fix".
- [ ] **Pickup code: don't regenerate on re-fetch** — the code is currently rotated on every issue call. Should be saved once on the accepted match and shown to the sender from "My requests" until the traveler enters it.
- [ ] **Mobile: post-payment screen → "your code is X" + push to sender** — after sender pays, they land on a screen showing the pickup code with copy button; same code is pushed via notification.
- [ ] **Mobile: traveler "enter pickup code" entry surface** — traveler gets a notification after payment ("ready for pickup, enter code"); deep-link routes to `/handover/verify/<match_id>?kind=pickup`.
- [ ] **Mobile: sender follow-package screen after pickup code accepted** — when `match.in_transit` fires, sender's notification deep-links to `/tracking/<match_id>` (the progress screen).
- [ ] **Mobile: counter-offer flow only when sender requested a specific traveler** — if the sender posted a *general* request, traveler offer is accept/decline only (price was sender-computed). If the sender targeted *this traveler*, traveler can counter.
- [x] 2026-05-28 `78ac9e4` ~~**Audit Django publish targets**~~ — confirmed: all 14 publish sites already pass `targets=[uid,...]` as kwarg via `redis_bus.publish_after_commit`. Go now reads only `targets`; legacy `recipient_id`/`sender_id`/`traveler_id` in payloads are forwarded raw to mobile but no longer consulted for routing.

### Soon

- [ ] **`auth_storage.dart` role hydration race** — first frame paints sender UI, then hydration may flip to traveler. Acceptable but worth a splash gate.
- [ ] **Sender flow: counter-offer UI in `match_detail_screen`**.

### Done

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

- [x] 2026-06-07 Fix `imageKey` doubled `kyc-docs/` prefix — keys are now bucket-relative (`<uid>/<idem>-<field>.<ext>`) instead of `kyc-docs/kyc-docs/<uid>/…`. Handler test asserts no bucket-name repeat. Flagged the stored-key migration for Islam (see Islam/Now). `go test -race ./internal/kyc/` green.
- [x] 2026-06-07 Test coverage for the untested shared `pkg/*`: `pkg/config` (99%, every env loader incl. URL build + GRPC/FCM validation tables), `pkg/health` (97%, liveness/readiness/MarkReady/panic-containment), `pkg/logger` (100%), `pkg/wsproto` (bearerToken + Send drop semantics + Close once-guard + envelope JSON + ping<TTL invariant), `pkg/db` (NewPool fail-fast validation + orDefault). Now every package is tested except `cmd/*` (wiring-only) and `kycpb` (generated). `go test -race ./...` green. HANDOVER.md gap table + day-one checklist updated.
- [x] 2026-05-30 Production hardening pass (final-product reframe): new `pkg/metrics` (expvar Group, `/debug/vars` on both services); SetEX retry on `delivered:<event_id>`; bounded dispatch worker pool (128/pod, drop-on-saturation with event_id); pubsub buffer 64→1024 + drop event_id/counter; presence initial-write retry. All build/vet/race green.
- [x] 2026-05-28 `78ac9e4` Dispatcher: subscribe to all 16 Django channels via generic `targets=[uid,...]` envelope. Per-channel structs dropped; `dispatch` now fans by `targets` for every channel uniformly. Existing audit/receipt path unchanged.
- [x] 2026-05-22 `c7e80a8` Hardened Go services from senior review.
- [x] 2026-05-22 `c04a369` Chat service V1.
- [x] 2026-05-22 `f00b3e6` FCM consumer scaffold (gated).

---

## Shared / cross-cutting

- [ ] **mTLS for gRPC** (CLAUDE.md G5) — both sides still on bearer in dev. Production gate before V1 launch.
