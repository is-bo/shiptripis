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
- [x] 2026-07-20 **Pickup code: don't regenerate on re-fetch** — VERIFIED already-correct end-to-end (was implemented across earlier commits; confirmed this session). The pickup code is auto-issued idempotently on payment capture (`payments/views.py` `has_active` guard, inside the same atomic block as the capture; test `test_capture_auto_issues_pickup_code` asserts exactly one ACTIVE code). Every *re-view* path reads without rotating: the sender's `HandoverCodeScreen` calls the non-rotating `GET .../handover/code` on load + reads plaintext from the WS `handover.code_issued` cache (`liveCodeFor`), and `request_detail_screen`'s inline `_CodeCard` reads the same cache. `issue_code` (which rotates the prior ACTIVE → ROTATED) is only hit on an explicit user "Regenerate" tap. No code change needed.
- [x] 2026-07-20 **Mobile: post-payment screen → "your code is X" + push to sender** — VERIFIED done. On payment success `payment_screen` does `context.go('/handover/code/<mid>?kind=pickup')` → the read-only `HandoverCodeScreen` (digits + Copy button). The plaintext arrives via the `handover.code_issued` WS event auto-published on capture (see the idempotent auto-issue above), cached in `LiveEventState.codesByMatch`.
- [x] 2026-07-20 **Mobile: traveler "enter pickup code" entry surface** — VERIFIED present. After payment the traveler is routed to `/match/<id>` (via the `payment.captured`/`match.created` notification deep-links) where `match_detail_screen._HandoverPanel` shows a prominent "Enter pickup code" CTA (status=accepted) → `/handover/verify/<id>?kind=pickup`, plus a "Match locked in — wait for the pickup code" live banner. The verify screen exists (`handover_verify_screen.dart`). Entry-with-context (match detail) was kept over a bare deep-link to the verify form.
- [x] 2026-07-20 **Mobile: sender follow-package screen after pickup code accepted** — VERIFIED done. When the traveler verifies pickup, Django flips the match to `in_transit` and publishes `match.in_transit` to both parties; `live_event_router` deep-links the sender to `/tracking/<id>` (banner "Your parcel is on its way") and the traveler to `/handover/verify/<id>?kind=delivery`. The follow-package "boules" on `/tracking` + `request_detail` bind to `Match.status` and update via both the live event and the 12s poll.
- [x] 2026-07-20 **Mobile: counter-offer flow only when sender requested a specific traveler** — VERIFIED done (confirmed this session). Enforced on BOTH sides: server rejects counters on broadcast requests (`matching/views.py:348` — `CounterOfferView` returns 409 "Counter not allowed on broadcast requests" when `parcel.target_traveler_id is None`; test `test_counter_blocked_on_broadcast_request`), and `match_detail_screen` only shows the Counter button + price input when `canCounter = match.parcel?.targetTravelerId != null` (else Decline-only). The traveler's first application (`find_parcels_screen` apply sheet) is a plain first-offer, not a counter — correct. No code change needed.

### Soon

- [x] 2026-07-20 **`auth_storage.dart` role hydration race** — VERIFIED addressed (in the 2026-07-13 role-hydration boot gate; reconfirmed). `AuthNotifier` seeds the saved UI role into `roleProvider` BEFORE the shell mounts (auth_notifier.dart:65-74), and `RoleNotifier.build()`→`_hydrate()` reads the same storage key, so a "both" user no longer sees a first-frame sender→traveler flip. No code change needed.
- [x] 2026-07-20 **Sender flow: counter-offer UI in `match_detail_screen`** — VERIFIED done (present in `_MatchBody`): when the viewer is the counterparty on the current pending offer and `canCounter` (targeted request), a Counter toggle reveals a price input (`AppInput` + commission blurb) that POSTs to `matches/<id>/offers/counter` via `_doCounter`. Works symmetrically for sender and traveler.
- [x] 2026-07-20 **Real traveler names on offer/traveler cards** — VERIFIED done (in the 2026-07-13 pass; reconfirmed). `MatchSerializer` emits `sender_name`/`traveler_name` (= `User.full_name`); `MatchSummary` carries `travelerName`, and `travelerLabel()` renders it, falling back to `Traveler #<id>` only when null. Used at `request_detail_screen` lines 398 + 674. KYC badge remains out of scope.
- [x] 2026-07-20 **WS-driven live offer updates** — VERIFIED already-wired (confirmed this session). `live_event_router.dart` handles every offer/match channel Django publishes (`offer.created`/`offer.updated`/`offer.accepted`/`match.created` — string values confirmed against `core/channels.py`) and invalidates both `matchDetailProvider(mid)` + `offerListProvider(mid)` on each (all payloads carry `match_id`; Django publishes with correct `targets` in `matching/views.py`). The router is alive app-wide (`main.dart:41` + `app_shell.dart:38`), so an event while a party is on `match_detail_screen` (which watches both providers at build) triggers an immediate refetch. Pull-to-refresh also already present (`RefreshIndicator` → `_refreshAndWait`, lines 110-120/154-155). No code change needed.
- [x] 2026-07-20 **Notifications UX polish** — VERIFIED done (confirmed this session). (1) Unread badge on the notifications nav tab: present in `app_shell.dart` (`i == 2` → `notificationsNotifierProvider.unreadCount`); the chat tab got the same treatment this session. (2) Clear stale `error` on successful refresh: `NotificationsNotifier.refresh()` sets `error: null` both at start and on the success path. (3) Spinner on subsequent refreshes: pull-to-refresh drives the `RefreshIndicator` spinner; WS-reconnect refetch is intentionally silent (background). No code change needed.
- [x] 2026-07-20 **Chat: live "Mailroom" thread list** — `GET /api/chat/threads` (`ChatThreadsView`) returns the viewer's paid/eligible matches (gated per-row through the same `chat_eligibility` source of truth the send path uses), each with counterparty id+name, route (`ALG → CDG`), status, last-message snippet + timestamp, and the viewer's unread count (annotated subquery). Ordered by most-recent activity; empty threads still listed. Opening a thread (`GET .../chat/messages`) now marks the counterparty's messages read so the badge clears. Mobile: `ChatThread` model + `listThreads()` in the repo; `chatThreadsProvider` (Notifier, live-refreshes on `chat.message.new`); `chat_list_screen.dart` rewritten from the static `_convos` mock to a `ConsumerWidget` with loading/empty/error + pull-to-refresh, tap→`/chat/<id>`; nav bar chat tab now carries an unread badge (`totalUnread`); thread screen refreshes the inbox on dispose. +6 Django tests (215 green); `flutter analyze` clean (edited files); ruff clean.
- [x] 2026-07-20 **Post-apply refresh** — VERIFIED already-correct (confirmed this session). `find_parcels_screen._openApplySheet` creates a *new* Match+Offer then `context.push('/match/${match.id}')`; `matchDetailProvider`/`offerListProvider` are `autoDispose.family` keyed on that fresh id, so they fetch clean on first mount (no stale prior state to invalidate). The apply handler also invalidates `openParcelSearchProvider` + `matchListProvider` so the list surfaces drop the now-claimed parcel. No code change needed.

### Done

- [x] 2026-07-17 **Email-service Django side — verify-email + reset OTPs now flow over the `email:send` stream**: completes Alaa's dark-gated email-service (built 2026-06-05). All 5 spec pieces landed: (1) `redis_bus.enqueue_email_after_commit(to,subject,body,*,kind)` — the **first XADD in Django** — `XADD email:send MAXLEN ~ 10000 (approx)` with fields `{event_id, payload:json}`, fires via `transaction.on_commit` (G6) + writes a `PublishedEvent` audit row on channel `email:send` (G6b), swallows `RedisError` so the daily sweep catches misses; validates `kind ∈ {verify,reset}`. (2) `EmailVerificationCode` model (near-clone of `PasswordResetCode`: argon2 `make_password`, 6-digit, `issue()`/`verify()`/`is_active()`, `EMAIL_VERIFY_CODE_TTL_SECONDS`/`EMAIL_VERIFY_MAX_ATTEMPTS` settings) + reversible migration `accounts/0004_emailverificationcode.py`. (3) signup issues a verify code + enqueues `kind="verify"`; new `POST /api/auth/verify-email` sets `is_email_verified=True` (anti-enumeration 400, idempotent 204). (4) password-reset request swapped synchronous `send_mail` → `enqueue_email_after_commit(kind="reset")`, still always-202. (5) `DEFAULT_FROM_EMAIL` (base) + SMTP `EMAIL_*` backend (prod.py). Django renders subject+body; Go is pure transport (never branches on `kind`). **+17 tests; full suite 192→209 green** on local sqlite; `makemigrations --check` clean; ruff clean (the lone `prod.py` F405 is pre-existing on the Sentry line). **Two follow-ups (need the Docker stack / shared-scope approval):** (a) `schema.sql` needs a re-export to add the `email_verification_code` table — couldn't run `pg_dump` this session (VM idle-down); it's NOT a Go-read table so no sqlc rerun, but `check-drift` will flag it until synced. (b) shared-scope, needs your OK: add a `mailhog` service to `docker-compose.yml` + the `EMAIL_*` vars to `.env.example` for local e2e, then flip `EMAIL_ENABLED=true` — no Go change needed.
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

> **Claude A → Claude B handoff (2026-07-24).** Read before your next session.
>
> 1. **Chat is now wired end-to-end — your chat-service needs NO change.** Django
>    now persists `chat_message`, gates send/list on payment (`chat_eligibility`),
>    and publishes `chat.message.new` via `publish_after_commit(..., targets=[other_member_uid])`
>    — exactly the generic `targets` envelope your dispatcher already fans on
>    (confirmed against `apps/chat/views.py`). No `recipient_id`. The relay is
>    correct as-is. This session also shipped the mobile "Mailroom" inbox on top
>    of a new **Django** endpoint `GET /api/chat/threads` (paid matches + last
>    snippet + unread). Mobile reads all chat history from Django
>    (`GET /api/matches/<id>/chat/messages`), NOT sqlc — so a chat sqlc repo stays
>    a **V1-deferred nicety**; don't build it unless asked.
>
> 2. **Heads-up: `contracts/sql/schema.sql` is stale (Django-side) — `check-drift`
>    will be RED, and it's NOT your fault.** Migration `accounts/0004_emailverificationcode.py`
>    added the `email_verification_code` table (for the email-service Django side,
>    landed `13dd535`) but the schema wasn't re-exported — Islam couldn't run
>    `pg_dump` (no Docker up in the code-only sessions). It is **NOT a Go-read
>    table** (Go never touches `email_verification_code`), so there is **no sqlc
>    rerun for you** — do not regenerate against it. Islam will `task contract:sync-db`
>    once Docker is back up. If you see the drift gate red on only that table,
>    that's the reason; don't chase it.
>
> 3. **Nothing blocks you right now.** Your two dark-gated pieces (real `FCMSender`,
>    `email-service`) are both still waiting on Islam-side + shared-scope work, NOT
>    on Go code:
>    - **email-service**: Django side is **DONE** — verify + reset OTPs now XADD to
>      the `email:send` stream (`enqueue_email_after_commit`, first XADD in Django,
>      `MAXLEN ~10000`, fields `{event_id, payload:json}`, kind ∈ {verify,reset}).
>      Payload contract matches your consumer. To light up e2e needs **shared-scope
>      + user approval** (mailhog service in `docker-compose.yml`, `EMAIL_*` in
>      `.env.example`, then flip `EMAIL_ENABLED=true`) — no Go change.
>    - **FCM**: still needs Islam's `fcm_token` schema + `notif:fcm` publisher
>      before you flip `FCM_ENABLED=true`. Not started Islam-side yet.
>
> So: if the user wants you productive, the highest-value Go-side move is to **help
> Islam bring the compose stack up** and run the email e2e (mailhog) — but that's a
> shared-scope change needing the user's OK first. Otherwise you're genuinely
> caught up; no queued Go work.

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
