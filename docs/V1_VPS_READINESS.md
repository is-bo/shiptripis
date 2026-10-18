# Waçla V1 — VPS infrastructure preparation

Date: 18 October 2026. This is code preparation and isolated cloud verification,
not a production launch approval. No VPS was purchased/provisioned; no Railway,
DNS, object-storage, provider, mobile-origin or external server state was changed.
No real email or money movement was performed.

## Repository audit

* Repository: `/workspace/shiptripis`, in the exact attached managed cloud
  environment requested by the owner.
* Starting branch: `work`; starting HEAD:
  `07c2a11111b26357da5ddedc2fa428854c4ee3ee`.
* Starting working tree and stash list: empty. Stayed on `work`; main was neither
  checked out nor changed. No owner files/stashes were deleted or overwritten.
* **Checkout discrepancy:** this cloud checkout contains the K-Series release
  history and ShipTrip branding, not the owner's described completed Waçla rename.
  No rename was undone and no broad rename was invented. New infrastructure uses
  Waçla. Reconcile this commit with the owner's intended renamed development
  branch before V2/V3; do not assume it was already present in the supplied tree.
* Implementation commit: record final Git HEAD from the completion report;
  this document deliberately avoids a self-referential commit hash.

Inspected the authoritative V1 specification and implementation status; Railway
Dockerfile/launcher/Caddy; production/base/payment/Connect settings and env example;
Go service mains/config/auth/WebSocket/health contracts; Django finance/lifecycle/
outbox commands and handler map; existing CI/schema/static/deployment-safety gates;
deployment and K1/K6/K-Series reports, Redis/capacity/observability appendices.
The reports are historical evidence, not assertions about today's live Railway.

The legacy development `backend/docker-compose.yml` has tab indentation and
development services/settings; it was not rewritten. The existing root Railway
build bundles all processes, expects platform TLS, and automatically migrates and
imports geography. Its smaller two-worker defaults and optional ephemeral Redis
are unsuitable as unexamined VPS defaults. The new package reuses its proven
supervision and routing while isolating VPS-specific behavior.

## Final architecture and reuse

See [infra/vps/README.md](../infra/vps/README.md) for the diagram, operational
sequence, command reference and troubleshooting. Supporting contracts:
[environment/secrets](../infra/vps/ENVIRONMENT.md),
[migration runbook](../infra/vps/MIGRATION.md).

| Compose service | Responsibility / ownership |
| --- | --- |
| `app` | One non-root, read-only combined application unit; Gunicorn 4×2, Django gRPC, one reservation releaser, one finance worker, Go chat/notification/KYC/email and private routing/static Caddy. |
| `postgres` | Project-compatible PostgreSQL 16, private network, SCRAM host auth, named data volume, data checksums on first initialization, fsync/full-page writes/synchronous commit. |
| `redis` | One authenticated Redis for every consumer, named data volume, AOF every second plus RDB, noeviction and persistence failure write-stop. |
| `caddy` | Public 80/443 TLS edge, configurable hostname/ACME contact, Admin source CIDRs and WebSocket browser-origin controls; no app secrets or DB network. |
| `maintenance` | Explicit one-shot migrations, geography and housekeeping, serialized with a PostgreSQL advisory lock; never starts domain worker loops. |
| `backup` | Explicit encrypted restic/pg_dump operations, HTTPS S3-compatible offsite destination, separate backup-only credentials and password. |

The combined topology follows K6's measured decision. Splitting every worker
would add ownership/restart surfaces without demonstrated benefit. The existing
supervisor already detects every exited child and drains process groups. VPS
calls it with migration/catalogue initialization disabled. Default Railway
behavior is unchanged. A build-time adapter reuses **all** existing internal
Caddy routes, adds trusted private proxy handling, and leaves the Railway
Caddyfile unchanged. The outer edge overwrites forwarded protocol/host/client IP,
preventing client spoofing through the extra hop.

API, both WebSocket routes, KYC aliases and size limits, Admin/custom consoles,
static/EN/FR/AR/legal pages, health, redirects/payment webhooks and security headers
retain existing routing. Production cookies, SSL redirect, CSRF, explicit hosts,
granular Admin authorization and banned-user revocation remain enabled. The local
test override uses a private CA, not weaker production Django settings.

Only the intended gateway is host-published. PostgreSQL/Redis/gRPC/metrics and
internal management interfaces are private. The edge applies an additional source
network gate to Admin, while Django still enforces its existing authorization.
Future VPN/CDN ingress changes require a reviewed trusted-proxy/source-IP contract.
No Docker socket is mounted in any service.

## Durable data and background work

PostgreSQL has a named volume, a 100-connection ceiling and durable settings;
health checks exercise both server readiness and an authenticated query. Initialization
only happens on an empty volume; neither restart nor deployment recreates data.
Migrations are explicit and serialized, with restore/migration compatibility
rehearsal required. Backward image compatibility must be reviewed; the CLI cannot
infer reversibility from Django migration status.

Redis retains streams, groups, pending entries and retry metadata after container
recreation. All consumers derive the same authenticated `redis://redis:6379/0`
endpoint. Production embedded mode and a separate route-cache URL are forbidden.
`noeviction` preserves non-TTL stream keys; memory exhaustion produces visible
write failures rather than silently discarding obligations. AOF everysec can lose
approximately a second on hard host failure; this is not synchronous replication
or a substitute for a server-loss recovery plan.

The single finance loop owns all current ScheduledJob handlers: notification
dispatch, deposit expiry/refund, payment grace, attempt expiry, provider reconcile/
event process, refund reconciliation, payout release/execute/reconcile/account
refresh/sweep, delivery-code release, protection expiry, rating reveal, boost expiry
and outbound messages. It also runs the existing outbox sweep and FCM results
consumer. The separate reservation loop is retained as its existing DB-backed
backstop. No extra cron duplicates those responsibilities.

Host daily maintenance owns only expired JWT cleanup, detection-only published
event reconciliation and owner-enabled retention. Retention defaults off, with
explicit job/push/staged-media durations and existing safety minimums. No financial,
ledger, audit, legal or KYC retention period is invented. Email keeps PostgreSQL
outbox, templates/localization, trusted secret-bearing SMTP rendering and Go stream
worker intact; `EMAIL_ENABLED=false` is enforced. S3 private bucket separation,
signed URLs and authorization remain unchanged. Existing objects are not migrated.

## Secrets and financial boundary

Configuration is one placeholder-only `stack.env.example`, secret JSON example,
shared database/Redis password files and separate backup env/password. Runtime
injection is read-only, respects host UID/GID permissions and rejects duplicate
secret sources. Root build context excludes secrets/env/dumps; the backup context
is an allowlist of its Dockerfile/script. Actual generated test secrets are outside
the repository. No real credential, private key or customer dump is committed.

Independent ≥32-character Django/JWT/gRPC/handover/outbox keys are required.
Migration must preserve historical authentication/encryption keys and provider
references. TEST-only guards require Stripe/Chargily TEST, payments environment
test, mock/legacy mutation false, DZD execution false, automatic Connect payout
execution false and SMTP off. Existing production startup safeguards are retained.
No Sender.net adapter or credentials were introduced.

## Operations, backups and recovery

`vps` validates config, builds immutable images from a clean reviewed SHA, starts/
stops, checks health/logs, serially migrates/imports catalogue, initializes/backups/
verifies/restores, deploys and rolls back. Stop and diagnostics remain usable if
configuration is missing/invalid. A host operation lock prevents overlapping
mutations. Monitoring is read-only and can run during long backups.

Build refuses an existing tag and cannot retag new bytes as the currently running
release. Deployment checks backup reachability before stopping, records source and
target recovery state, quiesces the single application, backs up, migrates and
waits for health. Failure preserves the source recovery target and blocks accidental
restart/new deploy. Rollback requires explicit schema-compatibility review, keeps
the database, and never automatically reverses financial/schema history.

Backup streams a custom PostgreSQL archive directly to restic command-input mode,
with no database-sized RAM/plaintext staging in the backup container. It fails on
dump errors, encrypts/authenticates data and metadata, verifies content-addressed
SHA-256 chunks and applies owner-selected retention only after success. Full read
verification and isolated restore are independently usable without the real VPS.
The fixed isolated restore database has no production network/volume attachment or
destination-override parameter. The host restore command's private temporary dump
is removed on exit. Independent password escrow and V3 offsite permissions/restore
rehearsal remain essential. Snapshots alone are insufficient; daily backups do not
promise point-in-time recovery.

Bootstrap prepares Ubuntu packages, Docker/Compose, trusted deploy user/key/sudo,
private secret directories, unattended security updates, fail2ban, UFW and a Docker
forwarded-ingress guard. Password/root SSH is disabled only by a separate explicit
key-access-confirmed step after another login succeeds. Scripts are prepared and
syntax-checked, not executed against a real server. Docker-group access is
root-equivalent. Systemd units define boot/daemon-restart stack recovery, daily
backup/housekeeping, host monitoring and a local alert hook; activation is V3.

Monitoring covers liveness/readiness/deep health, container health and memory,
CPU/load, host RAM/disk, PostgreSQL connection pressure, Redis persistence, queue
lag, worker snapshot absence, financial jobs, email backlog, backup freshness and
safe HTTP status logs. External alert delivery remains unconfigured. There is no
public monitoring interface. Docker logs rotate; raw access URLs are not logged.

## Resources and capacity limits

| Allocation | Initial configuration |
| --- | --- |
| App | 4.5 CPU, 6 GiB ceiling; four Gunicorn gthread processes × two threads, gRPC four threads. |
| PostgreSQL | 2 CPU, 4 GiB ceiling; 1 GiB shared buffers, 3 GiB effective cache, 8 MiB work_mem, 100 connections. |
| Redis | 1 CPU, 3 GiB ceiling; 1.5 GiB maxmemory leaves rewrite/fork/allocator headroom. |
| Edge | 0.5 CPU, 256 MiB ceiling. |
| Backup / maintenance | Transient 1 CPU, 768 MiB / 1 GiB; schedule away from peak and monitor. |

Long-lived memory ceilings total approximately 13.25 GiB; usual actual use should
be much lower, but backup/maintenance concurrency and the OS need the remainder.
Redis fork copy-on-write can still approach its ceiling under sustained writes;
calibrate rewrite/memory policy on V3 load rather than increasing maxmemory blindly.
The 40-second application/60-second stateful stop windows exceed existing child
drain bounds. Database connection model: Python 8 HTTP + 4 gRPC + 2 loops = 14;
Go 8 + 6 + 2 = 16; steady peak 30, conservative overlap model 60, below 85 usable
connections with 15 reserved. Operations add only a few connections; no replicas
are enabled. Recalculate before scaling, not merely per replica.

Reuse K6's 4×2 latency evidence, not its one-GiB memory defaults or extrapolated
user-capacity claims. This cloud runner is only three visible CPUs with a two-CPU
cgroup quota and vfs Docker; it is not the target Hetzner machine. No actual
Hetzner throughput/capacity claim is made. Disk planning must reserve images for
rollback, PostgreSQL/WAL/Redis growth, logs and a full independent restore plus
temporary dump. Alert at 80% disk and expand before reaching it. No automatic
Docker/volume prune or schema/data cleanup is a default operation.

## File inventory

38 created files and 6 modified existing files (44 total). No application schema,
mobile runtime source, provider adapter or production data was changed.

### Created

* [.github/workflows/vps-readiness.yml](../.github/workflows/vps-readiness.yml)
* [docs/V1_VPS_READINESS.md](../docs/V1_VPS_READINESS.md)
* [infra/vps/.dockerignore](../infra/vps/.dockerignore)
* [infra/vps/Caddyfile](../infra/vps/Caddyfile)
* [infra/vps/Dockerfile](../infra/vps/Dockerfile)
* [infra/vps/ENVIRONMENT.md](../infra/vps/ENVIRONMENT.md)
* [infra/vps/MIGRATION.md](../infra/vps/MIGRATION.md)
* [infra/vps/README.md](../infra/vps/README.md)
* [infra/vps/app-secrets.example.json](../infra/vps/app-secrets.example.json)
* [infra/vps/backup.env.example](../infra/vps/backup.env.example)
* [infra/vps/backup/Dockerfile](../infra/vps/backup/Dockerfile)
* [infra/vps/backup/backup.sh](../infra/vps/backup/backup.sh)
* [infra/vps/bootstrap.sh](../infra/vps/bootstrap.sh)
* [infra/vps/compose.local.yml](../infra/vps/compose.local.yml)
* [infra/vps/compose.yml](../infra/vps/compose.yml)
* [infra/vps/docker-firewall.sh](../infra/vps/docker-firewall.sh)
* [infra/vps/monitor.py](../infra/vps/monitor.py)
* [infra/vps/postgresql.conf](../infra/vps/postgresql.conf)
* [infra/vps/redis-start.sh](../infra/vps/redis-start.sh)
* [infra/vps/redis.conf](../infra/vps/redis.conf)
* [infra/vps/render_internal_caddy.py](../infra/vps/render_internal_caddy.py)
* [infra/vps/requirements.lock](../infra/vps/requirements.lock)
* [infra/vps/restore.yml](../infra/vps/restore.yml)
* [infra/vps/runtime.py](../infra/vps/runtime.py)
* [infra/vps/stack.env.example](../infra/vps/stack.env.example)
* [infra/vps/systemd/wacla-alert@.service](../infra/vps/systemd/wacla-alert@.service)
* [infra/vps/systemd/wacla-backup.service](../infra/vps/systemd/wacla-backup.service)
* [infra/vps/systemd/wacla-backup.timer](../infra/vps/systemd/wacla-backup.timer)
* [infra/vps/systemd/wacla-docker-firewall.service](../infra/vps/systemd/wacla-docker-firewall.service)
* [infra/vps/systemd/wacla-monitor.service](../infra/vps/systemd/wacla-monitor.service)
* [infra/vps/systemd/wacla-monitor.timer](../infra/vps/systemd/wacla-monitor.timer)
* [infra/vps/systemd/wacla-scheduled.service](../infra/vps/systemd/wacla-scheduled.service)
* [infra/vps/systemd/wacla-scheduled.timer](../infra/vps/systemd/wacla-scheduled.timer)
* [infra/vps/systemd/wacla-stack.service](../infra/vps/systemd/wacla-stack.service)
* [infra/vps/tests/integration.py](../infra/vps/tests/integration.py)
* [infra/vps/tests/test_monitor.py](../infra/vps/tests/test_monitor.py)
* [infra/vps/tests/test_safety.py](../infra/vps/tests/test_safety.py)
* [infra/vps/vps](../infra/vps/vps)

### Modified

* [.dockerignore](../.dockerignore)
* [.gitignore](../.gitignore)
* [backend/monolith/apps/finance/tests/test_deployment_safety.py](../backend/monolith/apps/finance/tests/test_deployment_safety.py)
* [backend/railway/start.py](../backend/railway/start.py)
* [docs/IMPLEMENTATION_STATUS.md](../docs/IMPLEMENTATION_STATUS.md)
* [mobile/test/phase_j62_boost_copy_offer_refresh_test.dart](../mobile/test/phase_j62_boost_copy_offer_refresh_test.dart)

## Verification record

All tests use generated fixtures and disposable local containers. No Railway
endpoint, real customer record, external SMTP endpoint or real financial credential
was used. Infrastructure integration runs **production** Django settings with
mock payments forbidden, financial providers TEST/inactive and email off. The full
Django regression suite uses its existing development/test mock-provider fixtures;
that test environment is separate from the infrastructure runtime.

Toolchain: Python 3.12, Go 1.26.2, Docker 28.4.0, Compose 2.40.3, PostgreSQL 16,
Redis 7. Flutter 3.47.1 was installed from the exact official source tag
`6655482ec06e547f90abf8ae7590466f4415978d` after the SDK archive URL returned 404;
its engine/Dart artifacts loaded successfully (Dart 3.13.1). Analytics were disabled.
No release APK was built.

| Executed gate / command | Result |
| --- | --- |
| `docker build --secret id=system_ca,src=/etc/ssl/certs/ca-certificates.crt -f infra/vps/Dockerfile -t wacla-v1-test:$SHA .` | PASS; complete Go/Python/Caddy application image. |
| `docker build -f infra/vps/backup/Dockerfile -t wacla-backup-test:$SHA infra/vps` | PASS; standalone PostgreSQL/restic image. |
| `python -m unittest discover -s infra/vps/tests -p 'test_*.py'` | PASS; 21 safety/monitor/operator tests. |
| `python infra/vps/tests/integration.py` | PASS; fresh eight-group end-to-end run plus 14 explicit website/Admin-static/health route checks, including nonempty assets and security headers. |
| `python /workspace/.shiptrip-cloud/test-django.py -q --disable-warnings -n 4 --reuse-db` | PASS; 2,369 passed, 34 retired-legacy skips, 30 warnings; 3,943.20 seconds. Isolated PostgreSQL/Redis DB 15. |
| `EMAIL_ENABLED=false python -m pytest -q apps/finance/tests/test_deployment_safety.py --ds=config.settings.test_local` | PASS; 58 existing deployment security tests. |
| `go test -p 4 -race -count=1 ./...` | PASS; full Go tests with race detector. |
| `go test -p 4 -tags integration -race -count=1 ./...` | PASS; full Go tests including real isolated Redis DB 14 integrations. |
| `go vet -p 4 ./...` | PASS. |
| `flutter pub get --enforce-lockfile`; `flutter gen-l10n` | PASS; committed dependency lock respected, generated localization unchanged. |
| `dart format --output=none --set-exit-if-changed lib test` | PASS; no formatting changes. |
| `flutter analyze --fatal-infos` | PASS; no issues. |
| `flutter test --no-pub --concurrency=1 --reporter=expanded` | PASS; 1,074 passed in the complete serial run. Three targeted live-refresh repetitions also passed; format/analyzer remained clean. |
| EN/FR/AR ARB message-key comparison | PASS; 1,466 matching message keys. |
| `ruff check backend/monolith backend/railway/start.py infra/vps` | PASS. |
| `python manage.py makemigrations --check --dry-run` | PASS; no schema/model drift or new migrations. |
| PostgreSQL `pg_dump --schema-only` versus committed schema contract | PASS after the existing CI version/nonce normalization. |
| Regenerated Python/Go gRPC stubs versus committed contracts | PASS after existing CI generator-version normalization; generated outside repository. |
| SQLC query inventory | Zero query files in current contract; same existing CI no-generation case. |
| `python tools/check_static_web.py`; `node --test tools/web/globe.test.mjs` | PASS; website/contracts and globe unit tests. |
| `bash -n infra/vps/bootstrap.sh`; `sh -n infra/vps/backup/backup.sh infra/vps/redis-start.sh infra/vps/docker-firewall.sh` | PASS; no bootstrap action executed. |
| `systemd-analyze verify --root=<isolated-unit-fixture> ...` | PASS; unit syntax/dependency graph and deployment-user drop-ins checked with stub executable/Docker paths, no real unit installed/started. |
| `git diff --check` and staged secret/private-key signature scan | PASS; placeholder-only committed examples. |

Run Go commands under `backend/services`, Django commands under
`backend/monolith`, mobile commands under `mobile`, and remaining commands at
repository root. In this cloud, `source /workspace/.shiptrip-cloud/activate.sh`
selects the installed backend/Go toolchain. The full Django helper applies the
existing CI throttle ceilings; its `POSTGRES_*` and `REDIS_URL` point only at the
random integration fixture's loopback ports with generated test credentials.
Use `DJANGO_SETTINGS_MODULE=config.settings.dev`, `DJANGO_DEBUG=true`,
`PAYMENTS_ALLOW_MOCK_PROVIDER=true`, `EMAIL_ENABLED=false` **for that regression
process only**. The infrastructure suite creates its own strict production-profile
configuration. See its source for reproducible fixtures; never point it at Railway.

### Fixes found by implementation and verification

* The combined launcher previously always migrated/imported geography. Optional
  initialization arguments preserve Railway defaults while making VPS migrations
  explicit, locked and non-concurrent. Raw app startup refuses pending migrations
  before launching any workers. The existing source-slicing test now accepts the
  extended function signature without changing its assertions.
* Go and Django use different KYC bucket variable names. The VPS wrapper maps the
  single configured private bucket into Go's required key, preventing its old
  development-bucket fallback.
* A copied Caddy binary retained a file capability incompatible with the non-root,
  all-capabilities-dropped app. The build removes only that capability. Explicit
  directory/file modes also avoid restrictive cloud build umask failures.
* Inherited managed-cloud HTTP proxy settings sent the edge's private upstream
  request outside its bridge. Explicit internal `NO_PROXY` plus a proxy-free
  local health probe restore correct routing without changing external egress.
* Local Caddy requires a valid contact argument even with internal TLS. The local
  override uses an inert `.invalid` contact and never requests a real certificate.
* The backup permission drill found that root with all capabilities dropped
  cannot bypass a host-owned 0600 secret. Backup now runs as dedicated UID/GID
  10001 with owned status/work directories and 0640/GID 10001 mounted secret
  files; backup-only env credentials stay 0600 and are never mounted into app.
* Large backup tests require streaming command-input mode, full dump failure
  propagation, clean binary export and draining archive bytes after TOC inspection;
  these paths avoid RAM-sized dump staging and false SIGPIPE failures.
* Final review found that root-run systemd commands could create state files
  unusable by the deployment user. Bootstrap now installs explicit deployment-user
  identity drop-ins for all four CLI-based units, and the CLI refuses mixed-owner
  state before creating locks/markers. A regression test covers that refusal.
* Operator tests cover preserving source/target recovery state after an interrupted
  deploy, refusing a new build over an existing tag, excluding ignored/uncommitted
  owner bytes with Git archives, emergency stop despite broken config, and preventing
  conflicting secret sources. The monitor handles absent queue ages safely.
* Backup support is explicitly limited to prepared HTTPS S3 backends; unsupported
  SSH/SFTP authentication cannot silently pass validation. Bootstrap accepts public
  keys without a final newline and refuses private-key input/GID conflicts.
* A pre-existing Flutter request-count test raced session restoration on the
  constrained runner (initial full run: 1,073 passed, one failed). It now awaits
  confirmed sign-in before mounting/counting event subscriptions; the exact
  one-extra-read and unchanged-badge assertions are retained. No mobile runtime
  code or API origin changed. Targeted repetitions and the full rerun are recorded
  in the final verification table.
* Restic pack files are deliberately read-only. The corruption test changes
  owner-write permission only on its disposable repository before corrupting
  content, then requires verification failure.
* The throttling integration uses Docker-assigned client identities; fixed IPs
  require explicit IPAM subnets and fail on ordinary Compose-created networks.

A concurrent Flutter rerun hit its wall-clock JSON budget while sharing the
two-CPU runner with backend/container work. It was stopped and is not a pass.
The isolated serial full run passed the unchanged limit: the 100-Deal conversion
measured 2,991 µs against the existing 8,000 µs ceiling (17,950 µs under load).
No assertion or production rule was relaxed.

Early test attempts exposed inherited local test email/payment switches; corrected
only the isolated regression process environment. Production email/mock guards and
all deployment-security assertions remain enabled. No genuine pre-existing
application defect was hidden or reclassified merely to obtain a passing suite.

The fresh integration covered authenticated AOF/RDB Redis recreation with pending
entries/groups, XAUTOCLAIM and continued work; PostgreSQL restart durability,
all migrations and production checks, concurrent-migration lock refusal;
TLS/redirect/API/KYC/Admin and both WebSocket routes; distinct client-IP throttles
and spoofed-header stripping through two proxies; non-root/read-only/private app
properties, exit-zero shutdown and child-crash restart; encrypted >1-MiB dump,
failed-dump snapshot refusal, complete repository integrity reads, isolated restore
recovering `amount_minor=12345`, and rejection of deliberately corrupted packs.
Additional explicit CSS/JS/Admin CSS requests all returned 200 with nonempty bodies.
All generated containers/volumes used for these tests were subsequently removed;
the owner's stopped cloud development containers and data were not touched.

### Checks intentionally reserved for V3

Real Ubuntu boot, Docker-daemon restart, host firewall/IPv6/SSH recovery and disk/load
behavior cannot be established by a cloud container fixture. Public DNS/ACME,
independent offsite S3 credentials/connectivity/permissions, real private-media
reachability, Firebase/OAuth/provider webhook connectivity and external alert
receipt require owner accounts/server/domain and are outside V1 authorization.
No such check is reported as passed. Execute the bootstrap/activation sequence in
`infra/vps/README.md` and every migration rehearsal/cutover gate in
`infra/vps/MIGRATION.md`; prove offsite upload plus `vps verify FULL_SNAPSHOT_ID`
and `vps restore FULL_SNAPSHOT_ID`, then record actual RPO/RTO before launch.

## Remaining V2 / V3 prerequisites

V2: resolve the renamed-branch discrepancy, prepare Sender.net SMTP configuration
using the existing interface, review provider intent/domain verification, secrets,
trusted-code delivery and EN/FR/AR templates, and deliberately update the V1
email-off boundary without activation or sending. No new API adapter is needed.

V3: owner-approved server/account/budget, domain/Admin sources/SSH operator, real
private S3 buckets/credentials, backup repository/key escrow/retention/RPO/RTO,
Firebase/OAuth identifiers, preserved auth/encryption/provider references, real
Ubuntu/systemd/firewall/Docker-restart rehearsal, actual resource/load/disk checks,
offsite backup restore, public TLS/DNS/provider connectivity and external alert
delivery. Review PostgreSQL runtime-role privileges against the current app before
launch; the baseline uses the existing single owner/initialization role on a
private-only server. Resolve mobile-origin compatibility without changing it in V1.

The [migration runbook](../infra/vps/MIGRATION.md) requires a proven consistent
Redis checkpoint while still reachable, write quiescence, final DB transfer,
financial/auth/storage/queue verification, exactly one active writer, and rollback
rules that account for new destination writes/external side effects. If embedded
Railway Redis cannot be exported or proven drained, migration is NO-GO; email
outbox durability is not permission to discard pending push work. Railway stays
unchanged during V1.
