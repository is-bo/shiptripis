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
- [ ] **Audit Django publish targets** — every event must have `targets: [user_id,...]` populated correctly so Go's per-pod routing works. Today some use `recipient_id` (single int). Pick one convention.

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

- [ ] **Subscribe to ALL Django channels in `notification/dispatcher.go`** — today only `offer.accepted` + `offer.created` are wired. Mobile listens for all of these and silently misses them:
  - `handover.code_issued`  *(critical for demo flow — pickup code arrival on traveler side)*
  - `match.in_transit`       *(sender's "package picked up" notification)*
  - `match.completed`        *(sender + traveler "delivery confirmed")*
  - `payment.captured`       *(traveler's "you have a paid match" notification)*
  - `payment.refunded`
  - `match.created`
  - `offer.updated`          *(declined / withdrawn / countered)*
  - `parcel.created`, `parcel.cancelled`
  - `trip.created`, `trip.cancelled`
  Each channel is a 5-line block following the existing `offer.accepted` pattern. Payloads all carry `targets: [user_id, ...]` — fan to those targets.
- [ ] **Confirm `targets` payload convention** — Islam asked the same question (see his list). Once agreed, both sides use it consistently.

### Soon

- [ ] **Drop unused `offerAcceptedPayload.Ts` / `offerCreatedPayload.Ts`** (per CLAUDE.md §0a follow-up).
- [ ] **FCM consumer** is scaffolded behind `FCM_ENABLED=false`. Needs `fcm_token` schema from Islam before unblocking.

### Done

- [x] 2026-05-22 `c7e80a8` Hardened Go services from senior review.
- [x] 2026-05-22 `c04a369` Chat service V1.
- [x] 2026-05-22 `f00b3e6` FCM consumer scaffold (gated).

---

## Shared / cross-cutting

- [ ] **mTLS for gRPC** (CLAUDE.md G5) — both sides still on bearer in dev. Production gate before V1 launch.
- [ ] **Handover code `targets` payload** — see Islam's "audit publish targets" task.
