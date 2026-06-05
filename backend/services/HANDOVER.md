# Go services — handover

Last updated: 2026-05-30. You are **Claude B** (Go side). Pair with Claude A
(Django + Flutter). Before touching anything, read `../../CLAUDE.md` end to
end (especially §0a open notes, §2 guardrails G1–G6b, §3 pool budget) and
`../../ARCHITECTURE.md` §3–§7. This file is the Go-specific quickstart on top
of those — when it disagrees with the code, **the code wins**; fix this file.

---

## 30-second orientation

The Go workspace is **feature-complete for the V1 spine** and was green
(`go build`/`vet`/`test -race ./...`) as of `002b969` — re-run the day-one
checklist to confirm before trusting it. Three services run:
`notification`, `chat`, `kyc`. None is on Django's critical path — Django
publishes to Redis after commit; Go subscribes. No subscriber = events go to
void, Django keeps working.

There is **no unblocked feature work** on the board right now. The open items
(see the blocked-on-Islam table) all wait on Django schema or shared infra.
The highest-value *unblocked* work is **test coverage** for the packages that
the hardening pass left untested — see "Known gaps".

---

## Layout

```
backend/services/
├── cmd/                # service entrypoints (main.go = wiring only)
│   ├── chat/           # ✅ WS relay for chat.message.new
│   ├── kyc/            # ✅ multipart upload + S3 + real gRPC client
│   └── notification/   # ✅ WS hub + 16-channel pub/sub + FCM (gated)
├── internal/           # service-private code (one pkg per service)
│   ├── chat/           # hub, dispatcher (+test), handler  — stateless relay
│   ├── kyc/            # handler, client iface, grpc_client, kycpb/ (stubs)
│   └── notification/   # hub, dispatcher, handler, presence, fcm
├── pkg/                # shared libs
│   ├── auth/           # HS256 JWT validator + 30s leeway (G2) — tested
│   ├── config/         # env loaders → typed structs
│   ├── db/             # pgxpool wrapper
│   ├── health/         # /healthz + /readyz
│   ├── logger/         # slog setup
│   ├── metrics/        # expvar-backed Group (Counter/Gauge/GaugeAdd) — NEW
│   ├── redisbus/       # pub/sub + SetEX/Del + streams + drop-on-overflow
│   ├── storage/        # S3-compat client (G4, no MinIO-isms) — tested
│   └── wsproto/        # coder/websocket wrapper, ping interval = 10s
└── go.mod              # module: shiptrip
```

---

## What's live (current, not the 2026-05-15 version)

### `cmd/notification` — done, all 16 channels

- WS upgrade → registers `*wsproto.Conn` in the per-pod `Hub` keyed by
  `user_id` (from the JWT bearer).
- Subscribes to **all 16 Django channels** (`dispatcher.go:subscribeChannels`,
  mirrors `monolith/apps/core/channels.py`). Routing is **generic**: every
  envelope carries `targets:[uid,...]` (attached by
  `redis_bus.publish_after_commit`); `dispatch` unmarshals only
  `targetsEnvelope{event_id, targets}` and fans the **raw payload** to each
  target's local sockets. Payload semantics (match_id, offer_id, code) are
  mobile's concern — Go never parses them. Per-channel structs were deleted;
  do not reintroduce them.
- G1 + G6b receipt path: writes `delivered:<event_id>` (60s TTL) + back-fills
  `core_published_event.delivered_at`, through a bounded receipt pool.
- **Bounded dispatch worker pool** (`dispatchSem`, cap 128) feeds
  **bounded receipt pool** (`receiptSem`, cap 64). Both drop-on-saturation
  with `event_id` logged + metrics counters. `Run` drains
  `dispatchWG` *before* `receiptWG` (a late dispatch can still enqueue a
  receipt) — see the `defer` ordering, don't swap it.
- **SetEX retry**: one 100 ms retry on the `delivered:<event_id>` write before
  giving up (a Redis blip in the FCM 2 s grace window would otherwise cause a
  duplicate push). Metered `*_delivered_setex_failures_total` / `_final_total`.
- Presence (`presence:<user_id>`, 15 s TTL) refreshed by a 5 s ticker per
  socket — **tighter than the 10 s WS ping** by design (CLAUDE.md §5). Initial
  refresh on upgrade **retries once** after 50 ms; failure is metered but does
  **not** fail the upgrade (FCM fallback covers the gap; aborting would make a
  transient Redis issue more user-visible than the duplicate it prevents).
- **FCM consumer scaffolded, gated behind `FCM_ENABLED` (default false).**
  `LogOnlySender` stub; `FCMSender` is the prod swap point. Consumer flow
  (`XReadGroup` → 2 s wait → check `delivered:<event_id>` → send/skip → `XAck`)
  + `XAUTOCLAIM` sweeper are wired and shutdown-drained. Blocked on Islam's
  `fcm_token` schema + a Django publisher to the `notif:fcm` stream.

### `cmd/chat` — done, stateless relay

- WS relay for `chat.message.new` only. **Django owns persistence**; this
  service just fans the event to the targets' local sockets. Per-pod `Hub`
  mirrors notification's but is deliberately **not shared** (clean lifecycle
  boundary; if a third WS service appears, extract `pkg/wshub` then).
- **Generic targets routing** (mirrors notification): unmarshals only
  `targetsEnvelope{event_id, ts, targets}` and fans the raw payload to each
  target's local sockets. Django attaches `targets:[uid,...]` to every publish
  via `redis_bus.publish_after_commit`; the relay never inspects message_id /
  thread_id / body. The old per-channel `recipient_id` struct was removed — do
  not reintroduce it (it broke the one-contract invariant notification already
  follows).
- `dispatcher.go` uses unexported `router` + `receiptStore` interface seams
  (with `dbReceiptStore` as the production impl) so unit tests inject stubs (no
  Postgres/Redis needed). **This is the pattern to copy** — notification now has
  the same seams.
- No presence loop (notification owns `presence:<uid>`). A user with a chat WS
  but no notification WS gets a duplicate FCM for chat events — accepted V1
  tradeoff.
- Tests cover targets routing, multi-target fan-out (with uid 0 skipped),
  no-local-sockets skip, bad-payload/empty-targets drop, receipt-error logging,
  unknown-channel dispatch.

### `cmd/kyc` — done, wired end-to-end

- `POST /kyc/submit` (multipart): bearer auth → size caps → validates
  `document_type` + 32-char-hex `idempotency_key` → streams each image to S3
  under `kyc-docs/<user_id>/<idempotency_key>-<field>.<ext>` (deterministic;
  retries overwrite, no orphans) → calls `Recorder.RecordSubmission`. Every
  uploaded key is tracked; deferred cleanup is gated on a success flag, so a
  later-image failure can't orphan an earlier upload. `RecordSubmission` is
  fenced by a 10 s `context.WithTimeout`.
- Recorder is the **real gRPC client** (`internal/kyc/grpc_client.go` +
  generated `internal/kyc/kycpb/`): keepalive (30 s/10 s, `PermitWithoutStream`),
  retry policy (4 attempts on `UNAVAILABLE`/`DEADLINE_EXCEEDED`, safe because
  Django dedupes on `idempotency_key`), 16 MiB max msg both sides (G5).
  `KYC_GRPC_TARGET` is **required at boot** — missing config fails start.
  `NoopRecorder` retained for unit-test scaffolding only.
- Auth: `GRPC_AUTH_MODE` defaults to `mtls` (prod); **`bearer` is dev-only** and
  must be set explicitly with `GRPC_BEARER_TOKEN`. mTLS is still a TODO on both
  sides (`grpc_client.go` returns an explicit error in `mtls` mode today).

**Codegen:** `task contract:go-grpc` regenerates `internal/kyc/kycpb/`;
`task check-drift` runs it + `git diff --exit-code`, so proto changes that
don't ship regenerated stubs fail CI.

---

## Known gaps (highest-value unblocked work)

**Test-coverage gap closed (2026-06-01).** The three previously-untested
packages now have unit tests; `go test -race ./...` exercises them:

| Package | Now covered |
|---|---|
| `internal/notification` | targets routing (100%), multi-target fan-out w/ uid-0 skip, bad-envelope drops, dispatch + receipt pool saturation/drop, ctx-cancel on saturated pool, `dbReceiptStore.MarkDelivered` SetEX retry (succeed-on-2nd / both-fail / cancel-during-backoff) |
| `internal/chat` | same SetEX-retry coverage added (`receipt_test.go`) + UPDATE-error metering; routing already covered |
| `pkg/redisbus` | `recordDrop` event_id parsing + `pubsub_drops_total` / per-channel counters, nil-metrics safety, unparseable-payload tolerance |
| `pkg/metrics` | `Counter`/`Gauge`/`GaugeAdd`/`Sanitize` + folded-label names (100%) |
| `internal/kyc` | `handleSubmit` happy path (201) + idempotent replay (200), passport-no-back, 401 unauth, full validation-rejection table (bad/missing doc_type, short/non-hex idem key, missing front/back/selfie, bad content type, empty file, too-many-parts), recorder-not-configured (503), recorder error (502), partial-upload orphan cleanup (500). `handleSubmit` 96.6%, `uploadImage` 95.7%, validation paths 100% (2026-06-03) |

`internal/kyc` test seam: `Handler.Storage` was narrowed from `*storage.Client`
to an `objectStore` interface (`Put`/`Delete`) so a `fakeStore` injects without
live MinIO — `*storage.Client` satisfies it unchanged, so prod wiring is identical.

Both `dbReceiptStore`s now expose `keyExpirer` + `receiptExecer` micro-seams
(behaviour-preserving) so the SetEX retry is testable without live Redis/PG.
`metrics.Sanitize` was exported so tests can reconstruct a published var's key.

What still can't be unit-tested without integration infra (live Redis/PG/gRPC):
`Dispatcher.Run`, `redisbus.Subscribe`/`pump`, the FCM consumer's
`XReadGroup`/`Sweep` loop, and `kyc.GRPCClient` dial. The compose harness below
now exists to exercise these end-to-end.

**Compose harness landed (2026-06-03).** The Go services are now in
`backend/docker-compose.yml` and actually runnable:
- One parameterized `services/Dockerfile` (`SERVICE` build-arg → `cmd/<SERVICE>`)
  builds all three; `kyc-service` / `notification-service` / `chat-service`
  blocks each `env_file: .env` + healthcheck on their `/healthz`.
- New `django-grpc` service runs `manage.py runkycgrpc` so port 50051 actually
  serves — previously the `django` block mapped 50051 but only ran `runserver`,
  so the kyc gRPC dial had nothing to talk to. The 50051 mapping moved here.
- `backend/.env.example` created (was entirely absent despite CLAUDE.md §7b's
  `cp -n .env.example .env` flow + base.py:2 referencing it). Root `.gitignore`
  gained `!.env.example` so the template is trackable under the `.env.*` ignore.
- **Heads-up for Claude A:** Django settings read `GRPC_INTERNAL_TOKEN`
  (base.py:153) but `runkycgrpc.py` reads `GRPC_BEARER_TOKEN` via `os.getenv`.
  The runner wins for the gRPC bearer flow, so `.env.example` sets
  `GRPC_BEARER_TOKEN`. The unused `GRPC_INTERNAL_TOKEN` in settings is a latent
  inconsistency on the Django side — not touched (Claude A scope).

**KYC verified end-to-end (2026-06-04).** Full cold-start stack came up and a
real multipart POST through Caddy → kyc-service → MinIO → gRPC → Django →
Postgres returned 201 (first) then 200 (idempotent replay on same key); the 3
images landed in MinIO and the `kyc_submission` row was inserted. Two fixes the
live run surfaced (both committed):
- **`pkg/storage/s3.go` PutObject was broken against any plain-http S3 endpoint.**
  aws-sdk-go-v2 (≥v1.36) defaults `RequestChecksumCalculation=when_supported`,
  which appends a CRC32 *trailing* checksum; for an unseekable Body over non-TLS
  the SDK aborts with "unseekable stream is not supported without TLS and
  trailing checksum". Fix: set `when_required` at config load AND pass the
  seekable `multipart.File` straight through `Put` (was wrapped in a plain-Reader
  `limitErrReader`, which stripped `io.Seeker` and forced the SDK to fail). The
  fail-fast wrapper is kept only for non-seekable bodies. This was a real prod
  bug — it would have failed every upload against MinIO/Backblaze/Hetzner over
  http; exactly the §G4 "providers differ" caution. `go test -race ./...` green.
- **`createbuckets` compose job** provisions `kyc-docs` (+`shiptrip-parcel`) via
  `minio/mc`; without it kyc-service `/readyz` stays 503 on a fresh volume
  (HeadBucket 404). App code must not create buckets (§G4), so this lives in
  compose.

**Pre-existing wart (not fixed — flagged for owner):** `imageKey()`
(handler.go:328) hardcodes a `kyc-docs/` prefix *inside* the object key while
the bucket is also `kyc-docs`, so objects land at `kyc-docs/kyc-docs/<uid>/…`.
Functional (keys are deterministic, store+fetch stay consistent) but the doubled
segment is ugly. Drop the literal prefix from `imageKey` if you want clean paths
— but it's a stored-key change, so coordinate: existing rows reference the old
keys.

---

## Conventions that survive across sessions

Go-side patterns, not project-wide rules. Follow them so the services stay
consistent.

- **Generic targets routing, never per-channel structs.** Every Django publish
  carries `targets:[uid,...]`. Route by that. Do not unmarshal payload bodies
  in Go (CLAUDE.md §0a closed this debate).
- **Drop-on-overflow back-pressure, everywhere.** `pkg/redisbus`,
  `pkg/wsproto`, `Hub.Send`, and both dispatch/receipt pools use bounded
  channels + non-blocking sends with a `default:` drop + log (+ a metrics
  counter + `event_id` where available). A slow consumer must never stall a
  fast producer.
- **Metrics via `pkg/metrics`, guarded by `if m != nil`.** Counters are
  monotonic; names are folded labels (`pubsub_drops_<channel>`) and sanitized
  to `[a-z0-9_]` so the future Prometheus swap is one file. Expose
  `/debug/vars` on the service mux (both `main.go`s do).
- **`sync.Once` for `Close()`** on any type that tears down background
  goroutines (see `redisbus.Subscription.Close`).
- **`signal.NotifyContext` + derived `rootCtx`.** Every `main.go`: build
  `signalCtx` for SIGINT/SIGTERM, derive `rootCtx` via `WithCancel`, defer
  `rootCancel`. Goroutines select on `rootCtx.Done()` so any leg can pull the
  plug.
- **Detached contexts for delivery receipts.** Anything writing "I delivered X"
  (Redis `delivered:`, Postgres `delivered_at`, S3 cleanup, presence Drop)
  uses `context.WithTimeout(context.Background(), …)`. A cancelled request must
  not cancel the bookkeeping.
- **Per-service `*_DB_MAX_CONNS`** with the CLAUDE.md §3 budgeted default. Don't
  ad-hoc bump it — update §3 first.
- **All env reads via `pkg/config`.** Never `os.Getenv` in `main.go`/handlers.
- **No business logic in `cmd/`.** `main.go` is wiring only. Everything testable
  lives in `internal/<service>/` behind interface seams.

## Conventions NOT to copy

- Don't add a `pkg/ratelimit/`. Rate limiting is at Caddy
  (`docs/decisions/0001-gateway-caddy.md`).
- Don't write SQL migrations from Go. Tell Islam the columns you need; he writes
  the Django migration; you regenerate via sqlc.
- Don't add a 6th Go service (CLAUDE.md §5).
- Don't reintroduce per-channel payload structs in the dispatcher.

---

## Day-one checklist for a fresh Claude B session

1. `git pull` then `cd backend/services && go build ./... && go vet ./...` —
   must be clean.
2. `go test -race -count=1 ./...` — `chat`, `notification`, `auth`, `storage`,
   `redisbus`, `metrics` should be `ok`. The `cmd/*`, `internal/kyc`, and the
   pure-wiring `pkg/*` (config/db/health/logger/wsproto) show `[no test files]`.
3. `gofmt -l .` — must be empty.
4. Skim `cmd/notification/main.go` + `cmd/kyc/main.go` for the wiring template;
   `internal/notification/dispatcher.go` for the G1+G6b + pool pattern;
   `internal/chat/dispatcher.go` for the test-seam pattern.
5. `git -C ../.. log --oneline -20` for what landed since last session.
6. Read `../../TASKS.md` (Alaa section) + `../../.claude/MEMORY.md`.

---

## email-service (4th service) — landed Go-side 2026-06-05, gated dark

`cmd/email` consumes a durable `email:send` Redis Stream and sends transactional
mail (signup-verify OTP + password-reset OTP) over SMTP via `internal/email`
(go-mail). It's the **4th** Go service — under the §5 "no 6th" cap, and it uses
**no Postgres** (Django owns OTP gen/verify; Go is pure transport), so it does
**not** touch the §3 connection-pool budget. Mirrors the FCM consumer pattern
minus the grace-wait / `delivered:` dedup. Ships **dark** behind
`EMAIL_ENABLED=false`; verified booting green (health 200, `consumer disabled`,
clean shutdown) against a throwaway Redis. Build/vet/gofmt/`test -race ./...`
all green.

**The A/B contract (build Django side to this):**

Durable stream `email:send`, `MAXLEN ~ 10000` (G1), group `email-send-workers`.
Stream entry fields: `event_id` (denormalised) + `payload` (JSON string). The
`payload` JSON is:
```json
{ "event_id":"…", "to":"u@x.com", "subject":"…", "body":"…(rendered plaintext)…", "kind":"verify|reset" }
```
**Django renders subject + body.** Go is a pure transport — it never templates
and never branches on `kind` (log/metric label only). Go dedups on a self-owned
`email:sent:<event_id>` key (10-min TTL), so a sweeper re-delivery won't double
-send. The send path is at-least-once; a rare duplicate carries the *same still-
valid* code.

### Spec for Claude A (Islam) — 5 pieces

1. **Stream publisher** (NEW — `redis_bus` is pub/sub-only today). Add
   `apps/core/redis_bus.py::enqueue_email_after_commit(to, subject, body, *, kind)`:
   inside `transaction.on_commit`, `XADD email:send` with `MAXLEN ~ 10000`
   (approx), fields `{event_id: uuid4().hex, payload: json.dumps({event_id, to,
   subject, body, kind})}`, and INSERT the `PublishedEvent` audit row (G6/G6b).
   Reuse `get_client()`. This is the **first XADD in Django** — model it on the
   existing `publish_after_commit` envelope discipline.
2. **`EmailVerificationCode` model** — near-clone of `PasswordResetCode`
   (`apps/accounts/models.py:66-109`): `issue()`/`verify()`/`is_active()`, argon2
   `make_password`, 6-digit, with new `EMAIL_VERIFY_CODE_TTL_SECONDS` /
   `EMAIL_VERIFY_MAX_ATTEMPTS` settings mirroring `PASSWORD_RESET_*`
   (`config/settings/base.py:135`). Reversible migration + `task contract:sync-db`
   (§4). Go does **not** read this table → no sqlc rerun.
3. **Signup** (`apps/accounts/views.py:28` / `serializers.py:30`): after user
   create, `EmailVerificationCode.issue(user)` then
   `enqueue_email_after_commit(user.email, subject, body, kind="verify")`. Add
   `POST /accounts/verify-email` that verifies the code and sets
   `is_email_verified=True` (the field at `models.py:27` is currently only ever
   set by Google OAuth).
4. **Password reset** (`apps/accounts/views.py:135`): replace the synchronous
   `send_mail(...)` with `enqueue_email_after_commit(..., kind="reset")`. Keep the
   always-202 anti-enumeration response.
5. **Settings**: add real SMTP `EMAIL_*` to `prod.py` + `DEFAULT_FROM_EMAIL`
   (both currently absent — dev is `console`). For local end-to-end, add a
   `mailhog` service to compose (smtp :1025 / UI :8025) and set the `EMAIL_*`
   vars per `.env.example`.

**When this lands:** flip `EMAIL_ENABLED=true` + set `EMAIL_SMTP_*`; no Go change
needed (the real `smtpSender` is already wired in `cmd/email/main.go`). Verify per
the plan: signup → XADD on `email:send` → email-service logs "email sent" →
message in MailHog; kill+restart email-service mid-flow to prove durability.

---

## What needs Islam (Claude A) — keep this list current

| # | Item | Why we're blocked |
|---|---|---|
| 1 | `fcm_token` schema + Django publisher to `notif:fcm` | notification FCM fallback ships dark until then. **Real `FCMSender` is now wired** (`internal/notification/fcm_firebase.go`, firebase-admin v4) — just flip `FCM_ENABLED=true` + set `FCM_PROJECT_ID`/`FCM_CREDENTIALS_PATH` once the publisher + tokens land |
| 2 | `email:send` stream publisher + `EmailVerificationCode` model + SMTP settings | email-service ships dark until then. Full spec above. Flip `EMAIL_ENABLED=true` + `EMAIL_SMTP_*` once it lands — no Go change needed |
| 3 | `chat_message` / `chat_thread` schema | chat is a stateless relay today; persistence + history endpoints (sqlc dirs reserved but empty) wait on this |
| 4 | mTLS pipeline (cert-manager / mkcert) | gRPC runs on dev bearer; `grpc_client.go` errors in `mtls` mode until certs exist (CLAUDE.md §G5). Shared scope — coordinate, get explicit approval |

When any lands, **update this table** and the §0a handoff in `../../CLAUDE.md`
in the same commit as the Go work that consumes it.

---

## Repo state at handoff

- Branch `main`, in sync with `origin/main` at `002b969`.
- Untracked tooling side-state present (`.codegraph/`, `.cursor/`, `.mcp.json`,
  `AGENTS.md`, `opencode.jsonc`) — editor/agent config, **not project work**.
  Leave alone or gitignore; don't commit as part of a feature change.
