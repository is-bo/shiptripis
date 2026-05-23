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
- [x] 2026-05-23 Audit Django publish targets — confirmed every publisher in `apps/*/views.py` and `apps/verification/services.py` passes `targets=[...]` to `publish_after_commit`. Go now reads top-level `targets` uniformly; `recipient_id`/`sender_id` keys remain in payloads as channel-specific data only.

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

(none — see Done; both items moved.)

### Soon

- [ ] **Drop unused `offerAcceptedPayload.Ts` / `offerCreatedPayload.Ts`** (per CLAUDE.md §0a follow-up).
- [ ] **FCM consumer** is scaffolded behind `FCM_ENABLED=false`. Needs `fcm_token` schema from Islam before unblocking.

### Done

- [x] 2026-05-23 Subscribe to ALL Django channels — dispatcher refactored to a single `targets: [user_id, ...]` envelope (done by Islam in his Commit 1; payload convention confirmed across every Django publisher).
- [x] 2026-05-23 Notification service added to `docker-compose.yml` + `Dockerfile.notification`; Caddy upstream renamed `notification-service` → `notification` (fixes 502 on `/ws/notifications`).
- [x] 2026-05-22 `c7e80a8` Hardened Go services from senior review.
- [x] 2026-05-22 `c04a369` Chat service V1.
- [x] 2026-05-22 `f00b3e6` FCM consumer scaffold (gated).

---

## Shared / cross-cutting

- [ ] **mTLS for gRPC** (CLAUDE.md G5) — both sides still on bearer in dev. Production gate before V1 launch.
- [ ] **Handover code `targets` payload** — see Islam's "audit publish targets" task.
