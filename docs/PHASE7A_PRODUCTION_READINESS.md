# ShipTrip Phase 7A — Production Readiness

Status: implementation complete locally; external activation and launch approval remain blocked. This phase does not deploy, activate payment/email providers, perform legal approval, or modify `mobile/`.

## Release decision

The production profile is fail-closed and all public entry points select `config.settings.prod`. Launch is still **NO-GO** until the external checklist at the end of this document is signed off. This 2026-08-30 hardening checkpoint is not yet an immutable release commit/tag; Phase 5C mobile work remains uncommitted and out of scope.

## Production controls added or verified

- `manage.py`, WSGI, ASGI, both monolith Dockerfiles, Railway commands, and the combined Railway launcher select production settings. Production refuses `DEBUG`, wildcard hosts, a non-production environment label, weak secrets, missing database/Redis/object-storage configuration, non-HTTPS storage, unsafe CORS/CSRF origins, mock/legacy payment mutation flags, unsafe gRPC authentication, half-configured Stripe, and an invalid handover secret.
- Stripe and Chargily credentials remain optional at boot. Provider availability is controlled by audited `BusinessSettingsVersion`; missing credentials refuse new checkout rather than falling back to mock. Webhooks remain available for already in-flight money when a provider is disabled for new work.
- `/healthz` is a cheap liveness response. `/readyz` checks PostgreSQL, unapplied migrations, and the shared rate-limit cache, and returns 503 when incompatible. `/api/admin/health/deep` requires `view_operational_incidents` and reports safe aggregate status for Redis, durable jobs, provider events, outbound messages, provider configuration, and bucket configuration.
- Production DRF throttle counters use Redis. Endpoint scopes cover registration, login, Google sign-in, password reset, email verification, discovery/routing, guest payment, checkout, webhook retries, handover submission/reveal, evidence/media upload, chat writes, and admin invitations. Provider webhooks retain a separate generous budget.
- Authenticated Go KYC submissions now consume an atomic Redis fixed-window budget before multipart parsing or object storage. The account-derived key is authoritative (default 6 attempts/hour); malformed and oversized retries consume it too. Exhaustion returns structured HTTP 429 with `Retry-After`; a missing limiter or Redis error fails closed with a safe HTTP 503 and performs no storage/recorder work. The optional hashed-IP dimension defaults disabled and cannot be enabled without an explicit trusted address source.
- The combined Railway launcher refuses to start without `KYC_RATE_LIMIT_REDIS_URL`, validates its Redis URL, rejects loopback, and maps it only into the KYC child. This preserves the existing per-container ephemeral Redis lifecycle for the other combined processes while making the storage-abuse budget shared across KYC replicas.
- Requests receive a server-generated `X-Request-ID`. Production application/request logs are JSON, carry release metadata, and allow-list request fields; bodies, query strings, tokens, codes, secrets, recipient data, and exact locations are excluded.
- Django and Caddy bound request bodies to 12 MiB. Media APIs retain their 10 MiB decoded-file limit and MIME/image verification. The public gateway adds no-sniff, referrer, framing, and static-site CSP headers; Railway adds HSTS after its TLS terminator.
- KYC image parts retain the 8 MiB/part and 48-megapixel bounds, compare declared MIME to the byte signature and decoder format, and now perform a complete image decode so a header-valid but truncated JPEG/PNG is refused before upload. Failed submission cleanup no longer logs sensitive private object keys.
- A PostgreSQL payment/cancellation race found by the release gate is closed: `cancel_order` cannot mark captured funds cancelled unless every applied cent already has a durable refund obligation. If payment won the lock race, cancellation is a no-op and the paid state remains coherent; domain workflows that intentionally cancel captured money continue to create the refund obligation first.
- Authentication hardening requires a verified Google email before account linking, serializes OTP attempt consumption with a database row lock, and uses shared distributed throttles.
- Legacy finance refund and dispute-status routes now enforce Phase 6A granular permissions and immutable admin audit records. Parcel-media upload responses no longer expose bucket names or object keys.
- Previously unbounded legacy histories are capped without changing their response envelope: chat inbox 100, trips 100, legacy payment intents 100, wallet holds/withdrawals 200. Current V1 finance, notifications, chat messages, and admin lists were already paginated or capped.

## Authoritative environment contract

`backend/.env.example` is the source inventory. Never copy its development values into a hosted environment.

| Group | Production variables | Requirement |
| --- | --- | --- |
| Core | `SHIPTRIP_ENVIRONMENT`, `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, `FRONTEND_BASE_URL`, `RELEASE_ID`, optional `SENTRY_DSN` | Environment must be `production`; debug false; hosts explicit; browser origins HTTPS. Empty CORS is valid for native/API-only use. |
| Database | `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`, optional Go `DATABASE_URL`, `DJANGO_DB_CONN_MAX_AGE`, per-service `*_DB_MAX_CONNS` | Split values are required by Django. Go accepts a validated PostgreSQL URL or the split values. |
| Redis | `REDIS_URL`, `KYC_RATE_LIMIT_REDIS_URL`, optional stream/group/name variables | Both URLs use `redis://` or `rediss://`. The constrained combined launcher supplies loopback `REDIS_URL` internally for ordinary cache/transport work, but requires a non-loopback managed `KYC_RATE_LIMIT_REDIS_URL` shared across every replica. Split topology must likewise point KYC at shared Redis. Redis is not financial or lifecycle authority. |
| KYC upload budget | `KYC_UPLOAD_USER_LIMIT`, `KYC_UPLOAD_USER_WINDOW_SECONDS`; optional paired `KYC_UPLOAD_IP_LIMIT`, `KYC_UPLOAD_IP_WINDOW_SECONDS`, `KYC_UPLOAD_CLIENT_IP_SOURCE` | Account budget defaults to 6/hour and cannot be disabled. IP defaults to `0`/off; enabling it requires a 60–86400 second window and one explicit source: `remote`, `x-real-ip`, or `x-forwarded-for`. A proxy-header source is allowed only after ingress sanitization is verified. |
| Storage | `S3_ENDPOINT_URL`, `S3_REGION`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_USE_PATH_STYLE`, `S3_BUCKET_KYC`, `S3_BUCKET_PARCEL`, `S3_BUCKET_DISPUTE`, Go `KYC_S3_BUCKET` | Endpoint must be HTTPS in production. Buckets must exist and be private. |
| JWT/gRPC | `JWT_HS256_SECRET`, `GRPC_AUTH_MODE`, `GRPC_BEARER_TOKEN` plus opt-in, or CA/server/client certificate paths; `KYC_GRPC_TARGET`, `GRPC_DJANGO_BIND` | JWT secret is shared exactly with Go. Prefer mTLS; Railway private bearer requires an explicit opt-in and 32+ characters. |
| Stripe | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, optional `STRIPE_API_BASE`, `STRIPE_API_VERSION`, tolerance | Secret and webhook secret are both present or both absent. The source does not use a publishable key. |
| Chargily | `CHARGILY_SECRET_KEY`, optional independent `CHARGILY_WEBHOOK_SECRET`, `CHARGILY_API_BASE` | May be absent while disabled. FX is an audited/snapshotted business setting, never an environment variable. |
| Payment common | `PAYMENTS_PUBLIC_BASE_URL`, `PAYMENTS_PROVIDER_TIMEOUT_SECONDS`; all three mock/legacy switches false | HTTPS public API origin is required even before provider activation so the deployment shape is fixed. |
| Email | `EMAIL_ENABLED`, `EMAIL_PROVIDER`, SMTP host/port/user/password/TLS, from name/address, support address, `DEFAULT_FROM_EMAIL`, `TRANSACTIONAL_EMAIL_SECRET`, `EMAIL_SENDING_DOMAIN_VERIFIED`, stream/group/name | A dedicated 32+ character transactional secret is always required because queued OTP/code obligations may exist while delivery is disabled. Enabling production mail requires an explicit host/from address and verified sending domain. Sender.net additionally requires username/password/TLS. |
| Handover/disputes | `HANDOVER_CODE_SECRET`, evidence bucket and URL TTL, endpoint throttle variables | Handover secret is 32+ characters and distinct from Django/JWT secrets. |
| Routing | provider class/options/cache URL/namespace/TTL/call budget | An empty provider is an explicit unavailable/degraded state, not a synthetic production provider. |
| Admin bootstrap | `SHIPTRIP_SUPER_ADMIN_EMAIL`, password, optional name | Supply only for the controlled bootstrap command; remove the plaintext password variable immediately afterward. |
| Processes | `WEB_CONCURRENCY`, worker intervals, service HTTP addresses, `PORT`, `LOG_LEVEL` | Validate against the database connection budget before scaling. |

No Stripe publishable key, Chargily public key, or maps API key is listed because the current source does not consume one.

## Health and operational thresholds

`/healthz` calls no dependency. `/readyz` exercises PostgreSQL/migration compatibility and a short write/read through the shared rate-limit cache; it never calls S3, SMTP, or payment providers. Alert from the permissioned deep-health aggregates and direct database queries:

```sql
-- Durable job backlog and manual action
SELECT status, kind, count(*), min(run_at) AS oldest_run_at
FROM finance_scheduled_job
GROUP BY status, kind ORDER BY status, kind;

SELECT id, key, kind, attempts, max_attempts, run_at, last_error
FROM finance_scheduled_job
WHERE status = 'failed' OR (status = 'pending' AND attempts > 0)
ORDER BY run_at LIMIT 200;

-- Webhook recovery
SELECT provider, processing_result, count(*), min(received_at)
FROM finance_provider_event
WHERE processing_result IN ('received','processing','retryable','failed')
GROUP BY provider, processing_result;

-- Durable email obligations
SELECT status, kind, count(*), min(coalesce(next_attempt_at, created_at))
FROM notification_outbound_message
WHERE status IN ('pending','failed') GROUP BY status, kind;
```

Initial alert policy: any permanently failed financial/lifecycle job pages on-call; retryable provider events older than 10 minutes warn and older than 30 minutes page; pending delivery-code email older than five minutes pages; a running job with a stale lock beyond the worker recovery interval warns. Tune only from observed launch traffic.

## Database and migration review

Historical migrations contain normal blocking `AddIndex`/constraint operations and bounded seed/data migrations. No historical migration was rewritten.

Risk points to rehearse on a production-sized clone:

- `deals.0003_allocation_expiry` backfills pending allocation expiries, then adds an index.
- `finance.0003_financial_recovery_state` backfills recovery state and adds an index.
- `accounts.0003_user_role_default_both` updates existing user roles.
- `core.0003`–`0007`, `trips.0002`, and `admin_panel.0002` seed policy, airport, group, and permission rows.
- `kyc.0002_add_idempotency_key` deliberately aborts unless the legacy table is empty.
- Initial and later app migrations create indexes/constraints using ordinary PostgreSQL DDL; on a large populated table these can hold locks. Expected V1 launch volume is small, but measure on a restored snapshot before every release.

Pre-deploy commands:

```powershell
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan --settings=config.settings.prod
python manage.py showmigrations --plan --settings=config.settings.prod
```

Take a verified backup before migration. Stop if the plan differs from the reviewed artifact, a data precondition fails, or lock/statement time exceeds the rehearsal. For future high-volume index changes, use a separate `atomic = False` migration with PostgreSQL `CREATE INDEX CONCURRENTLY`; never edit an already-applied migration.

## Object storage

KYC, flight proof, dispute evidence, and parcel images use random S3-compatible object keys. Evidence access is authorization-gated and presigned; API serializers hide raw bucket/key metadata. Production buckets must deny public ACL/policy, enforce TLS, use provider-side encryption, restrict credentials to required buckets/actions, enable access/audit logs when supported, and define lifecycle retention only after legal approval. KYC uploads validate declared type, byte signature, decoder format, dimensions, and the complete pixel stream; header-valid truncated images are rejected. Dispute policy also validates evidence types and sizes.

Manual payout evidence is currently operator-only `reference`/`receipt_url` metadata, not a ShipTrip-managed object upload; the server does not fetch that URL and public payout serializers omit it. Operators must use an access-controlled provider record, never a publicly shared sensitive receipt. If receipt files are added later, they need a dedicated private bucket/presigned authorization flow rather than reusing a public URL field.

Database rows are authoritative references. A failed database write after an object upload can leave an orphan; run a scheduled inventory reconciliation that compares bucket keys to database references and moves unmatched objects to a quarantine prefix before delayed deletion. Do not delete automatically until the retention/legal policy is approved. Never log signed URLs or object keys for sensitive evidence.

## Performance and capacity

Existing hot-path indexes cover scheduled-job due polling (`status, run_at`), provider-event recovery (`processing_result, next_retry_at`), notifications (`recipient, created_at/read_at`), payment owner/status/reference paths, journey publication, deal/match status, and admin queue filters. Discovery and chat use `select_related`, `prefetch_related`, annotations, and bounded responses. No speculative schema index was added in Phase 7A.

Connection budget is topology-dependent. Current default maximums are Django `WEB_CONCURRENCY × one connection per active request/thread` with persistent connections, chat 15, notification 10, KYC 5, email 5, plus each management worker. For the combined two-Gunicorn-worker topology, reserve at least 35 Go connections plus Django/worker connections and 20% headroom; lower per-service caps before deployment if the managed PostgreSQL plan cannot sustain that total. Verify the actual Railway plan limit externally—this repository cannot establish it.

Run `tools/local_load_test.py` only against loopback. It refuses external hosts, mutation/payment/admin paths, more than 5,000 requests, or concurrency above 50. Example after starting a test stack:

```powershell
python tools/local_load_test.py --base-url http://127.0.0.1:8080 --requests 500 --concurrency 10 --path /healthz --path /api/notifications
```

Use a test JWT through `--bearer-env` for authenticated read flows. Record p50/p95, error rate, `pg_stat_activity`, slow query logs, and connection utilization. No production load test or provider call is authorized.

Local bounded evidence on 2026-08-29: 500 authenticated/read-only requests at concurrency 10 across `/healthz`, `/readyz`, notifications, chat threads, payment orders, payouts, journeys, and parcels completed with 500 HTTP 200 responses and zero errors. The loopback run reported 140.87 requests/second, 13.95 ms median, 466.39 ms p95, and 559.75 ms maximum latency. It used Django's development server and a temporary file-backed SQLite database, so this proves route stability under a small local burst but is **not** a PostgreSQL, Gunicorn, Railway, or production capacity result. The temporary server and database were removed immediately afterward. Production-sized PostgreSQL rehearsal and connection observations remain launch blockers.

## Redis degradation

PostgreSQL `ScheduledJob`, `OutboundMessage`, notification rows, provider events, payment/ledger rows, and handover/deal timestamps remain authoritative. Redis loss degrades WebSocket fan-out, streams, cache, and distributed throttle enforcement; it does not erase payments, refund/payout obligations, delivery/protection timers, or secret-email obligations. Because production request throttles use the shared Redis cache, `/readyz` fails closed and the edge must remove the affected instance from public traffic while Redis is unavailable. The Go KYC service independently fails upload attempts closed with HTTP 503 when its dedicated shared limiter Redis is unavailable; it never falls back to the per-container cache or a process-local counter. Provider retries can safely arrive after recovery. Keep finance workers running where their path is PostgreSQL-only, restore Redis, allow durable outbox/jobs to redrive, run the outbox sweep, and inspect deep health.

## CI/release gates

The existing workflow independently gates Go formatting/build/vet/race tests, real-Redis integration tests, Django Ruff/migrations/PostgreSQL tests, generated schema drift, and Flutter format/analyze/tests. Flutter remains an eventual release gate but was neither changed nor run in Phase 7A while Phase 5C is paused. Before a release candidate, also require production boot/refusal tests, `manage.py check --deploy`, Caddy validation, static link/CSP checks, the local smoke/load report, migration rehearsal, backup restore evidence, and a defensive security review. CI must not auto-deploy production; release remains an explicit operator decision.

Release identifiers use one immutable value (recommended: `vMAJOR.MINOR.PATCH+<short-sha>`) injected as `RELEASE_ID` into Django health/logging and attached to image/deployment metadata. Tag backend, Go binaries, static web, and the compatible mobile build with the same release manifest even when artifacts deploy independently.

## Verification completed on 2026-08-30

Closed on this workstation:

- Go focused KYC/config/Redis tests passed; full `go build ./...`, `go vet
  ./...`, and `go test -count=1 ./...` passed after the final limiter and
  launcher edits. The tagged Redis integration tests are present and report
  explicit skips because `REDIS_TEST_URL` is not configured; no production or
  shared user Redis was contacted.
- Full Django SQLite passed **943 tests / 65 expected skips** with
  `--ignore=config/settings/test_pg.py`; the ignored file is a local-only
  optional PostgreSQL helper matched by pytest's filename convention and is
  not tracked or present in CI. Ruff, `manage.py check`, and
  `makemigrations --check --dry-run` passed.
- Full Django PostgreSQL 16 passed **974 tests / 34 expected skips** against
  the local PostgreSQL service after applying test-safe throttle environment
  values. A fresh uniquely named database was migrated from zero, its schema
  dump matched `contracts/sql/schema.sql` after the CI-documented narrow
  generator-noise normalization, and that temporary database was dropped only
  after an exact-name/zero-connection check. The long-lived development
  database was not used as a schema oracle because it contains legacy objects
  outside the current migration graph.
- Production refusal/deployment tests passed **26 tests**; explicit production
  `manage.py check --deploy --fail-level WARNING` passed with synthetic strong
  secrets and no real credentials. Railway JSON files parsed successfully and
  the combined launcher tests cover required non-loopback shared KYC Redis
  wiring.
- The focused finance/deployment suite passed **61 tests**, including the
  PostgreSQL payment/cancellation race regression. A prior full PostgreSQL run
  exposed 13 failures: 12 were test-suite throttle pollution from using the
  development 5/hour registration policy at full-suite scale, and one was the
  captured-money cancellation race. Re-running with test-safe throttle values
  and the minimal race fix produced the green totals above.

Still requires a capable release host: a real Redis instance for the tagged
atomicity/expiry/pause/recovery integration tests, Docker/Caddy startup and
proxy/header/webhook validation, and a CGO C compiler for `go test -race`.
Those gates are intentionally reported as unavailable rather than inferred
from unit tests or configuration parsing.

## Launch blockers

- Railway project/database/bucket plan limits, backups, retention, domains, TLS, variables, and restore access must be verified in the Railway account. No remote configuration was changed in Phase 7A.
- A complete restore rehearsal and production-sized migration timing report are required.
- Provision the non-loopback managed Redis named by `KYC_RATE_LIMIT_REDIS_URL`, verify every KYC replica reaches the same instance, and run the tagged real-Redis atomicity/outage/recovery integration suite against it. The implementation and deterministic multi-instance/concurrency tests are green, but this workstation has no Redis server.
- Re-run Caddy container validation and the Go `-race` gate in CI or a capable release host; this workstation has no Docker/Caddy binary and no CGO compiler. These unavailable gates must not be inferred from ordinary build/unit success.
- Stripe, Chargily, and Sender.net activation/tests in `PROVIDER_ACTIVATION_RUNBOOK.md` are required when those rails are approved.
- Final privacy/terms/prohibited-items content, support addresses, retention policy, and French/EU/Algerian legal review remain external blockers.
- Phase 5C visual restoration and mobile compatibility/device QA must complete without modifying the server invariants.
- Final security scan, test evidence, provider reconciliation drill, on-call ownership, and explicit launch approval must be recorded in the release ticket.

See `DEPLOYMENT_RUNBOOK.md`, `ROLLBACK_RUNBOOK.md`, and `PROVIDER_ACTIVATION_RUNBOOK.md` for operator execution.
