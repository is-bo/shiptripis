# CLAUDE.md — instructions for Claude instances on ShipTrip

If you are a Claude instance opening this repo, **read this file fully before
acting.** It encodes the operational rules that survive across sessions and
across the two contributors. ARCHITECTURE.md is the *what*; this file is the
*how*.

---

## 1. Two Claudes, two scopes

This repo is co-built by **two Claude instances** working with two human
contributors.

### Claude A (Islam's machine — Django + mobile)
- `mobile/` — Flutter app (iOS + Android)
- `backend/monolith/` — Django apps + migrations
- `backend/contracts/sql/schema.sql` — exported by Django, not edited by hand
- Django gRPC server in `apps/kyc/grpc_server.py`
- Redis publisher in `apps/core/redis_bus.py`

### Claude B (contributor's machine — Go services)
- `backend/services/` — Go workspace
- `backend/contracts/grpc/*.proto` — owned jointly, but Go re-generates stubs
- `backend/contracts/sql/sqlc.yaml` + sqlc-generated repos under `services/internal/*/repo/`
- Go gRPC clients in `services/internal/kyc/`

### Shared (touch only with explicit user approval)
- `backend/gateway/Caddyfile`
- `backend/docker-compose.yml`
- `backend/Taskfile.yml` (master)
- `backend/.env.example`
- `ARCHITECTURE.md`
- `CLAUDE.md` (this file)
- `contracts/grpc/*.proto`

If you're Claude A and the task touches `services/` → stop and tell the user
this is Claude B's scope. Same in reverse.

---

## 2. The 6 production guardrails (do not skip)

These came out of brutal architecture review. Each one neutralizes a
class of distributed-systems failure. They are NOT optional polish.

### G1 — Multi-pod presence + delivery receipts
- Pub/Sub for WS fan-out. Every Go pod subscribes; only the pod with the
  user's local socket sends.
- WS-owning pod writes `SET delivered:<event_id> 1 EX 60` after sending.
- FCM consumer (Redis Stream `notif:fcm`) reads, **waits 2s**, checks
  `delivered:<event_id>`, only then falls back to FCM.
- Presence: `SET presence:<user_id> EX 15` on every pong. `DEL` on
  disconnect. TTL must be < WS ping interval — never equal.
- `XAUTOCLAIM` sweeper every 30s reclaims PEL entries idle > 60s.
- Stream `MAXLEN ~ 10000`. Don't let it grow unbounded.

### G2 — JWT clock-skew leeway, both sides
- Go: `jwt.WithLeeway(30 * time.Second)` in `services/pkg/auth/jwt.go`
- Django: `SIMPLE_JWT["LEEWAY"] = timedelta(seconds=30)`
- Log a warning when `iat > now + 5s` even when accepted under leeway.
  Drift you don't see is drift you don't fix.

### G3 — Schema-drift CI gate (BOTH steps in CI)
```yaml
check-drift:
  cmds:
    - task contract:sync-db        # re-export schema.sql from Django
    - task contract:generate       # re-run sqlc
    - git diff --exit-code contracts/sql/ services/internal/*/repo/
```
Running only `generate` checks Go matches a stale schema file — exactly
the failure mode this exists to prevent.

### G4 — S3-compatible abstraction (no MinIO-specific code)
- All object storage access via `pkg/storage/s3.go` using `aws-sdk-go-v2`
  with custom endpoint.
- Never call MinIO admin APIs from app code.
- Test presigned URL flows against the actual prod provider in staging
  (MinIO and Backblaze/Hetzner differ on date semantics).

### G5 — gRPC mTLS (NOT static bearer)
- Self-signed CA generated once with cert-manager (K3s) or mkcert (local).
- Django + each Go service get their own cert.
- Both sides verify peer cert against shared CA.
- 90-day cert lifetime; cert-manager auto-renews.
- `GRPC_AUTH_MODE=bearer` is permitted **only** in `docker-compose` local
  dev. Production is `mtls`. The default in `.env.example` is `mtls`.
- gRPC max message size: `16 << 20` (16 MB) on **both** client and server.
  Asymmetric limits produce cryptic `RESOURCE_EXHAUSTED` errors.

### G6 — Redis publish ALWAYS after commit
- Use `transaction.on_commit(lambda: redis_bus.publish(...))` in Django.
- Direct calls to `redis_bus.publish()` inside a transaction body are
  forbidden — they leak ghost events on rollback.
- For every publish, also `INSERT INTO published_event(...)` for the V1
  detection-only audit (see G6b).

### G6b — Detection-only outbox (V1)
- Table `published_event(id, channel, event_id, payload_hash, published_at, delivered_at)`.
- Daily Django cron: select rows where `delivered_at IS NULL AND published_at < now - 5min`,
  cross-check against Redis `delivered:*`. Mismatches → Sentry.
- Full transactional outbox is V2. We don't auto-recover — but we
  detect every miss.

---

## 3. Connection pool budget (do not exceed)

Postgres `max_connections = 100`. Documented allocation:

```
Django gunicorn  : 4 workers × 5 conn  = 20
Go chat-service  : 2 pods × 15 conn    = 30
Go notif-service : 1 pod × 10 conn     = 10
Go kyc-service   : 1 pod × 5 conn      = 5
Reserved         :                     = 10
                                       ----
                                         75
```

Headroom for one extra Go pod: 25 conn. **Before scaling Go horizontally,
update `pgxpool.MaxConns` or raise `max_connections`.** Don't ad-hoc this.

---

## 4. Workflow rules (across sessions)

### Before starting any backend task
1. `git pull`
2. Read `ARCHITECTURE.md` if you haven't this session
3. Check `docs/claude-sessions/` for the most recent session log
4. Run `task check-drift` locally — if it fails, fix it before doing
   anything else
5. Make sure your scope (A or B) actually owns this task

### Before any Django migration (Claude A)
1. Make sure the migration is reversible (`./manage.py migrate <app> <prev>` works)
2. Run `task contract:sync-db` to update `contracts/sql/schema.sql`
3. Commit migration + schema.sql in the **same** PR. Splitting them
   breaks Claude B's build.
4. If the migration changes a Go-read table (`chat_message`, `notification`,
   `kyc_submission`, `media_object`, `published_event`), **flag it in the
   PR description** so Claude B reruns sqlc.

### Before any Go schema-touching change (Claude B)
1. Don't write migrations. Tell Islam what columns you need.
2. After Islam's migration lands, `task contract:generate` regenerates
   sqlc repos. If the diff looks wrong, the schema is wrong — push back.

### Before merging anything
- `task check-drift` must pass.
- `task test` must pass on both `monolith/` and `services/`.
- Mobile lint clean: `cd mobile && flutter analyze` (warning-clean).

### Before claiming work is "done"
Pattern: `evidence > assertions`.
- "It compiles" — show the build log
- "Tests pass" — show the test output
- "It's deployed" — show the health-check response
Don't say a task is done because the diff looks plausible.

---

## 5. Things that are easy to get wrong

- **Don't put `redis.publish` inside a Django `with transaction.atomic():`
  block.** Wrap it in `transaction.on_commit`. Always.
- **Don't use `presence:<user_id>` TTL of 30s.** It's 15s. Tighter than
  the 10s WS ping. Otherwise stale presence masks dropped sockets.
- **Don't fall back to FCM immediately on stream read.** Wait 2s for the
  WS-owning pod to write `delivered:<event_id>`, then check, then maybe
  another 2s if presence is online.
- **Don't put a static bearer token in production gRPC.** mTLS only.
- **Don't store JWT secrets in code.** `.env` only.
- **Don't compress images server-side in V1.** Out of scope. Use the
  client-enforced size cap.
- **Don't pre-generate thumbnails.** Lazy on read in V1.
- **Don't add a 6th Go service.** The win curve from polyglot is
  already flattening. Resist split-of-the-week temptations.
- **Don't change `Airport.iata` to surrogate `id`** without a data
  migration plan. Historic trips have FK to it.
- **Don't merge a PR with a failing `check-drift`.** Ever.

---

## 6. Pricing rules (load-bearing — do not vary)

Single source of truth: `monolith/apps/core/pricing.py`. Mobile app
mirrors but does not authoritatively compute. **Pricing is frozen on the
Offer row at creation time** (`commission_dzd`, `base_fee_dzd`,
`total_dzd` columns). Rate changes never retroactively rewrite Offers.

- Delivery: 25% flat commission, sender pays total
- Product:
  - Base fee 2,500 DZD
  - Tiered: <30k=0%, 30k–55k=7%, 55k–100k=5%, 100k+=3%
- All amounts are **integer DZD**. No floats. No fractional currency.

If a stakeholder asks to change rates, change `pricing.py`, not the
schema. Old Offers must continue to settle at their frozen rates.

---

## 7. Mobile rules

- **Riverpod 3** — `Notifier` + `NotifierProvider`, never `StateNotifier`.
- **`country_flags` v4** — wrap `CountryFlag.fromCountryCode()` in
  `SizedBox`; v4 dropped width/height params.
- **No `Spacer` inside scrollable columns** — use
  `SingleChildScrollView` + `IntrinsicHeight`. This bit us on onboarding.
- **Bottom nav** — white pill, sun-yellow accent only on the selected
  icon. No grey, no dark indicator.
- **Forms** — `AppInput` for text, `NumberStepper` instead of sliders,
  `InlineCalendar` for dates, `showAirportPicker()` for airports.
- **Theme** — Mediterranean parchment + emerald + terracotta + gold,
  with `#FBBC04` (sun yellow) as the signature accent.
- **Reconnect logic** — exponential backoff with ±30% jitter is
  mandatory on WS reconnect. Algerian mobile networks will reconnect
  thousands of devices simultaneously after any tower hiccup.

---

## 7b. Running the backend locally (Windows + WSL Ubuntu)

The user is on Windows; Docker Desktop runs through WSL Ubuntu. All
compose commands are run from inside WSL:

```bash
wsl -d Ubuntu
cd /mnt/c/Users/islam/shiptrip/backend
cp -n .env.example .env     # only first time
docker compose up -d        # postgres + redis + minio + django + caddy
docker compose run --rm django python manage.py migrate
curl http://localhost:8000/healthz   # → {"status":"ok"}
```

**Port map:**
- `localhost:5432` → Postgres
- `localhost:6380` → Redis (host 6380, NOT 6379 — native redis-server in
  WSL holds 6379. Inside the compose network, services still talk to
  `redis:6379`, so Django's `REDIS_URL` is unchanged.)
- `localhost:9000` / `:9001` → MinIO API / console
- `localhost:8000` → Django dev server
- `localhost:8080` → Caddy gateway (when up)

**Don't run native `psql` / `redis-cli` against the docker containers
expecting them to share data with native daemons.** Two separate
instances. Use `docker compose exec postgres psql -U shiptrip` and
`docker compose exec redis redis-cli`.

---

## 8. Memory + handoff

- Project memory persists in `.claude/memory/` (committed).
- Session transcripts in `docs/claude-sessions/` (committed; full JSONL).
- A new Claude session at the start should:
  1. Read `CLAUDE.md` (this file)
  2. Read `ARCHITECTURE.md`
  3. Read `.claude/MEMORY.md` and the linked memory files
  4. Skim the most recent session in `docs/claude-sessions/`
  5. Check `git log --oneline -20`

If you discover something the user wants persisted across sessions,
write it to `.claude/memory/<topic>.md` and add a one-line entry to
`.claude/MEMORY.md`. Do not put it only in `CLAUDE.md` unless it's a
hard rule for both Claudes.

---

## 9. When in doubt

- **Read code, don't guess.** Memories are point-in-time observations;
  the current code is authoritative.
- **Surface trade-offs, don't hide them.** If a fix has a downside,
  say so before implementing.
- **Don't add features the user didn't ask for.** A bug fix doesn't
  need surrounding cleanup; a one-shot operation doesn't need a helper.
- **Don't write defensive code for impossible cases.** Trust internal
  contracts. Validate at system boundaries only.
- **Use the Skill tool for skills the user has installed.** Don't
  invoke a skill that's already running. Don't simulate skill content.

---

## 10. V2 (deferred — do not start)

These are documented in `ARCHITECTURE.md §15`. Not in V1 scope:

- Ratings & reviews
- Dispute resolution UI
- Boost / paid promotion
- Insurance
- Local DZ payment rails (CIB / Edahabia / Baridimob)
- Push notifications via FCM are V1 — but custom topics, segmentation: V2
- Image compression on upload
- Pre-generated thumbnails
- Virus scanning
- Transactional outbox (V1 has detection-only)
- gRPC for inter-service calls beyond KYC
- HS256 → RS256 migration

If asked to build any of these in V1, push back and check with the user.
