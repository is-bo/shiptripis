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
- [ ] **Pickup code: don't regenerate on re-fetch** — the code is currently rotated on every issue call. Should be saved once on the accepted match and shown to the sender from "My requests" until the traveler enters it.
- [ ] **Mobile: post-payment screen → "your code is X" + push to sender** — after sender pays, they land on a screen showing the pickup code with copy button; same code is pushed via notification.
- [ ] **Mobile: traveler "enter pickup code" entry surface** — traveler gets a notification after payment ("ready for pickup, enter code"); deep-link routes to `/handover/verify/<match_id>?kind=pickup`.
- [ ] **Mobile: sender follow-package screen after pickup code accepted** — when `match.in_transit` fires, sender's notification deep-links to `/tracking/<match_id>` (the progress screen).
- [ ] **Mobile: counter-offer flow only when sender requested a specific traveler** — if the sender posted a *general* request, traveler offer is accept/decline only (price was sender-computed). If the sender targeted *this traveler*, traveler can counter.
- [ ] **Email-service Django side: `email:send` stream publisher + `EmailVerificationCode` model + SMTP settings** — Go email-service is built and gated dark (Alaa, 2026-06-05). Full 5-piece spec in `backend/services/HANDOVER.md` (email-service section). In short: (1) add `redis_bus.enqueue_email_after_commit(to,subject,body,*,kind)` doing `XADD email:send MAXLEN ~ 10000` + PublishedEvent (first XADD in Django — redis_bus is pub/sub-only today); (2) `EmailVerificationCode` model (clone `PasswordResetCode`) + reversible migration + `task contract:sync-db`; (3) signup issues a verify code + publishes `kind="verify"`, add `POST /accounts/verify-email` that sets `is_email_verified=True`; (4) password-reset view: swap synchronous `send_mail` → `enqueue_email_after_commit(kind="reset")`; (5) prod SMTP `EMAIL_*` + `DEFAULT_FROM_EMAIL` + a `mailhog` compose service for local e2e. When it lands: flip `EMAIL_ENABLED=true` + `EMAIL_SMTP_*` — no Go change needed.
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

- [ ] (none unblocked) — FCM real sender + email-service are both built and gated dark; both wait on Islam (see below + the Islam section).

### Soon

- [ ] (none)

### Done

- [x] 2026-06-05 **email-service (4th Go service)** — `cmd/email` + `internal/email` (sender iface, go-mail `smtpSender`, FCM-cloned stream consumer w/o grace-wait, `email:sent:<id>` dedup), `config.LoadEmail`, compose `email-service` block + `.env.example` `EMAIL_*` + `go.mod` go-mail v0.7.2. Gated `EMAIL_ENABLED=false`; verified booting green (health 200, consumer-disabled, clean shutdown) vs throwaway Redis. No Postgres (off §3 budget). Build/vet/gofmt/`test -race ./...` green. Django spec handed to Islam.
- [x] 2026-06-05 **FCM real sender wired** — `internal/notification/fcm_firebase.go` (firebase-admin-go v4 `SendEachForMulticast`, partial-failure tolerant, flags unregistered/invalid tokens), replaces `Sender:nil` in `cmd/notification/main.go`. Still behind `FCM_ENABLED=false`. Build/vet/`test -race ./internal/notification` green.
- [x] 2026-05-30 Production hardening pass (final-product reframe): new `pkg/metrics` (expvar Group, `/debug/vars` on both services); SetEX retry on `delivered:<event_id>`; bounded dispatch worker pool (128/pod, drop-on-saturation with event_id); pubsub buffer 64→1024 + drop event_id/counter; presence initial-write retry. All build/vet/race green.
- [x] 2026-05-28 `78ac9e4` Dispatcher: subscribe to all 16 Django channels via generic `targets=[uid,...]` envelope. Per-channel structs dropped; `dispatch` now fans by `targets` for every channel uniformly. Existing audit/receipt path unchanged.
- [x] 2026-05-22 `c7e80a8` Hardened Go services from senior review.
- [x] 2026-05-22 `c04a369` Chat service V1.
- [x] 2026-05-22 `f00b3e6` FCM consumer scaffold (gated).

---

## Shared / cross-cutting

- [ ] **mTLS for gRPC** (CLAUDE.md G5) — both sides still on bearer in dev. Production gate before V1 launch.
