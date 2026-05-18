# Go services — handover

Last updated: 2026-05-15. You are **Claude B** (Go side). Pair with Claude A
(Django + Flutter). Before touching anything, read `../../CLAUDE.md` end to
end and `../../ARCHITECTURE.md` §3–§7. This file is the Go-specific
quickstart on top of those.

---

## Layout

```
backend/services/
├── cmd/                # service entrypoints (main.go per binary)
│   ├── chat/           # empty — schema not landed
│   ├── kyc/            # ✅ multipart upload + S3, NoopRecorder stub
│   └── notification/   # ✅ WS hub + Redis pub/sub consumer
├── internal/           # service-private code (one pkg per service)
│   ├── chat/           # empty
│   ├── kyc/            # handler, client (Recorder iface), NoopRecorder
│   └── notification/   # hub, dispatcher, handler, presence
├── pkg/                # shared libs across services
│   ├── auth/           # HS256 JWT validator + 30s leeway (G2)
│   ├── config/         # env loaders → typed structs (LoadPostgres, …)
│   ├── db/             # pgxpool wrapper
│   ├── health/         # /healthz + /readyz
│   ├── logger/         # slog setup
│   ├── redisbus/       # pub/sub + SetEX/Del helpers + drop-on-overflow
│   ├── storage/        # S3-compat client (G4, no MinIO-isms)
│   └── wsproto/        # coder/websocket wrapper, ping interval = 10s
└── go.mod              # module: shiptrip
```

---

## What's live

### `cmd/notification` — done, single vertical slice

- WS upgrade → registers a `*wsproto.Conn` in the per-pod `Hub` keyed by
  `user_id` (decoded from the JWT bearer).
- Subscribes to Redis pub/sub channel `offer.accepted`; on each event:
  fans out to **sender + traveler** sockets owned by this pod, writes
  `delivered:<event_id>` (60s TTL), back-fills
  `core_published_event.delivered_at`. This is the G1 + G6b path.
- Presence (`presence:<user_id>`, 15s TTL) refreshed by an independent
  5s ticker per socket — **tighter than the 10s WS ping** by design
  (CLAUDE.md §5).
- `markDelivered` uses a **detached `context.Background()`** with a 5s
  timeout so shutdown mid-fanout doesn't abort the delivery receipt
  UPDATE (which would otherwise make the G6b sweep flag a real delivery
  as a miss).
- `main.go` derives `rootCtx` from `signalCtx` via
  `context.WithCancel(signalCtx)` and calls `rootCancel()` on any
  unexpected leg exit so HTTP + dispatcher always tear down together.

**Deferred:**
- FCM fallback (Redis stream `notif:fcm`, 2s wait, check delivered key)
  — blocked on `fcm_token` schema + routing strategy decision from
  Islam.
- All other event types (`offer.countered`, `match.completed`,
  `payment.succeeded`, etc.) — vertical slice only for now.

### `cmd/kyc` — done, wired end-to-end

- `POST /kyc/submit` (multipart): bearer auth → `MaxBytesReader(25 MiB)`
  → `ParseMultipartForm(16 MiB)` → validates `document_type` +
  32-char-hex `idempotency_key` → streams each image to S3 under
  `kyc-docs/<user_id>/<idempotency_key>-<field>.<ext>` (deterministic,
  retries overwrite, no orphans) → calls `Recorder.RecordSubmission`.
- On RecordSubmission failure: `cleanupOrphans` best-effort deletes the
  three S3 objects on a detached 5s context.
- Recorder is `kyc.GRPCClient` — generated stubs at
  `internal/kyc/kycpb/`, hand-written wrapper at `internal/kyc/grpc_client.go`.
  Dials Django at `KYC_GRPC_TARGET` (e.g. `django:50051`) on boot with
  `WithBlock`-equivalent readiness probe so misconfig fails fast.
- Auth: `GRPC_AUTH_MODE=bearer` + `GRPC_BEARER_TOKEN` shared with
  Django's `runkycgrpc` interceptor. mTLS (CLAUDE.md §G5) still TODO on
  both sides — wait for cert-manager / mkcert pipeline.
- Image constraints: ≤8 MiB each, JPEG/PNG only; the storage client
  enforces overflow on the write path.
- `kyc.NoopRecorder` is retained for unit-test scaffolding only.

**Codegen:** `task contract:go-grpc` regenerates `internal/kyc/kycpb/`;
`task check-drift` runs it and `git diff --exit-code`s the result, so
proto changes that don't ship regenerated stubs fail CI.

### `cmd/chat` — not started

Blocked on the `chat_message` / `chat_thread` schema from Islam.
sqlc.yaml has the slot reserved. When unblocked: model after
`cmd/notification` (same Hub + WS upgrade pattern + Redis fan-out), but
this one persists every message to Postgres via sqlc.

---

## Conventions that survive across sessions

These are not in CLAUDE.md because they're Go-side patterns, not
project-wide rules. Follow them so the services stay consistent.

- **Drop-on-overflow back-pressure.** `pkg/redisbus`, `pkg/wsproto`, and
  `notification.Hub.Send` all use bounded channels + non-blocking sends.
  Never `<-chan` with `select` that blocks; always `default:` drop +
  log. A slow consumer must NOT stall a fast producer.
- **`sync.Once` for `Close()`.** Any type with a `Close()` method that
  cleans up background goroutines uses `sync.Once` so double-close is
  safe. See `redisbus.Client.Close`.
- **`signal.NotifyContext` + derived `rootCtx`.** Every `main.go` looks
  the same: build `signalCtx` for SIGINT/SIGTERM, derive `rootCtx` via
  `WithCancel`, defer `rootCancel`. Goroutines select on `rootCtx.Done()`
  not `signalCtx.Done()` so any leg can pull the plug.
- **Detached contexts for delivery receipts.** Anything that writes "I
  delivered X" (Redis `delivered:`, Postgres `delivered_at`,
  S3 cleanup) uses `context.WithTimeout(context.Background(), …)`. A
  request being cancelled MUST NOT cancel the bookkeeping.
- **Per-service `*_DB_MAX_CONNS` env var.** Pool sizes are budgeted in
  CLAUDE.md §3. Every `main.go` defines its own const +
  `LoadPostgres("FOO_DB_MAX_CONNS", N)` with the budgeted default.
  Don't ad-hoc bump the default — update §3 first.
- **All env reads via `pkg/config`.** Never `os.Getenv` directly in
  `main.go` or handlers. Use `config.String/HTTPAddr/LoadX`.
- **Hand-written proto-mirror types until codegen lands.** See
  `internal/kyc/client.go` — `DocumentType`/`Status` are string consts
  that mirror the proto enum names. When codegen lands, replace by
  wrapping the generated stub, don't rewrite the call sites.
- **No business logic in `cmd/`.** `main.go` is wiring only:
  load config → build pool/store/validator → assemble handler →
  serve. Everything testable lives in `internal/<service>/`.

## Conventions NOT to copy

- Don't add a `pkg/ratelimit/`. Rate limiting is at Caddy
  (`docs/decisions/0001-gateway-caddy.md` + project memory).
- Don't write SQL migrations from Go. Tell Islam what columns you need;
  he writes the Django migration; you regenerate via sqlc.
- Don't add a 6th Go service (CLAUDE.md §5).

---

## Day-one checklist for a fresh Claude B session

1. `cd backend/services && go build ./... && go vet ./...` — must be clean.
2. `gofmt -l .` — must be empty (`pkg/auth/jwt_test.go` may show; that's
   pre-existing drift, leave it).
3. Skim `cmd/notification/main.go` and `cmd/kyc/main.go` to see the
   wiring template.
4. Skim `internal/notification/dispatcher.go` for the G1+G6b pattern;
   `internal/kyc/handler.go` for the multipart-upload pattern.
5. Check `git log --oneline -20` for what landed since last session.
6. Check `../../.claude/MEMORY.md` for cross-session decisions.

---

## What needs Islam (Claude A) — keep this list current

| # | Item | Why we're blocked |
|---|---|---|
| 1 | `chat_message` / `chat_thread` schema | `cmd/chat` is empty |
| 2 | `fcm_token` schema + routing decision | notification FCM fallback can't ship |
| 3 | mTLS pipeline (cert-manager / mkcert) | gRPC + future Go-↔-Go calls run on bearer until this lands; CLAUDE.md §G5 |

When any of these lands, **update this table** and the §0 handoff in
`../../CLAUDE.md` in the same commit as the Go work that consumes it.
