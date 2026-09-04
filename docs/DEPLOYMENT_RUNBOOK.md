# ShipTrip Deployment Runbook

This is an operator-controlled procedure. It does not authorize a production deployment. The root `railway.json` currently selects the combined `backend/railway/Dockerfile` topology: one application service (Django, gRPC, Go services, durable workers, local ephemeral Redis, Caddy/static web) plus managed PostgreSQL. The per-service Railway files are a future split topology and must not be mixed into the same release accidentally.

## 1. Release record and freeze

- [ ] Name the immutable release `vMAJOR.MINOR.PATCH+<short-sha>` and record commit/image digest.
- [ ] Confirm the worktree/release artifact excludes unrelated uncommitted files and secrets. Mobile compatibility is separately approved; do not build from the Phase 5C working tree.
- [ ] Assign release commander, database operator, finance observer, rollback decision-maker, and provider owner.
- [ ] Freeze business-settings/provider changes and record the active settings version.
- [ ] Confirm no unresolved dispute settlement, manual refund/payout, provider-event retry, or permanently failed `ScheduledJob` will be obscured by the release.

## 2. Evidence gates

Require green Django SQLite and PostgreSQL suites, Ruff, migration check, schema drift, Go format/build/vet/race/unit/integration, production boot/refusal tests, `manage.py check --deploy`, static/CSP/link check, local smoke/load report, defensive security review, and a mobile gate when Phase 5C resumes. Review the complete diff after the last edit.

Run migration planning with the exact release artifact and production settings (environment values supplied securely):

```powershell
Set-Location backend/monolith
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan --settings=config.settings.prod
python manage.py check --deploy --settings=config.settings.prod
```

Compare the plan to a restored production snapshot. Measure every data migration/index/constraint and rehearse lock/statement timeouts. A plan mismatch or unexplained lock is a stop condition.

## 3. Railway/environment preflight

- [ ] Verify the Railway CLI/account/project/environment/service target manually. A linked CLI context is not proof that the correct production environment is selected.
- [ ] Verify root `railway.json` and Dockerfile path in the release artifact.
- [ ] Reconcile Railway variables against `backend/.env.example`; check presence and safe shape, never print values.
- [ ] `SHIPTRIP_ENVIRONMENT=production`, `DJANGO_DEBUG=false`, explicit hosts/origins, immutable `RELEASE_ID`.
- [ ] Database, HTTPS S3, Redis/topology, JWT, handover, transactional-email, and gRPC secrets are distinct and stored only in the platform secret store. The current combined launcher intentionally supplies a loopback ephemeral Redis URL; do not mistake it for durable authority or a split-topology managed Redis service.
- [ ] **Private pre-launch exception:** when shared Redis is not yet available, set `KYC_RATE_LIMIT_LOCAL_MODE=true`, leave `KYC_RATE_LIMIT_REDIS_URL` empty, and keep the combined Railway service at exactly one replica. This keeps KYC enabled with a loopback fixed-window limiter for controlled testing only. Shared non-loopback Redis is still mandatory before public launch; unset local mode and provide `KYC_RATE_LIMIT_REDIS_URL` before scaling or opening access.
- [ ] Mock/legacy payment switches are false. Stripe/Chargily/Sender.net remain disabled unless this release explicitly includes their separately approved activation.
- [ ] Confirm public domain/TLS, bucket privacy/CORS/encryption, database connection ceiling, disk/memory/CPU, restart policy, health timeout, and alert destinations in the Railway dashboard.
- [ ] Confirm the current plan’s backup feature, retention, point-in-time recovery, and restore mechanism. Do not infer these from repository configuration.

## 4. Backup and restore readiness

Create a platform snapshot if the Railway plan supports it and record its identifier/time. Also create a logical pre-release backup from a trusted operator host using a secret-injected connection URL (never place the URL on a shared command line or in logs):

```powershell
$env:PGDATABASE = 'shiptrip'
$env:PGHOST = '<private-or-approved-host>'
$env:PGPORT = '5432'
$env:PGUSER = '<backup-role>'
$env:PGPASSWORD = '<secret-from-vault>'
pg_dump --format=custom --no-owner --no-privileges --file "shiptrip-pre-release.dump"
pg_restore --list "shiptrip-pre-release.dump" | Select-Object -First 20
Remove-Item Env:PGPASSWORD
```

Encrypt the dump at rest with the organization’s approved tool, upload it to a restricted backup vault, record checksum/size/PostgreSQL version, and enforce least-privilege access. Recommended starting retention—subject to legal/platform approval—is seven daily, four weekly, and twelve monthly recovery points.

Restore verification must target a **new empty database**, never production:

```powershell
$env:PGDATABASE = '<new-restore-verification-db>'
$env:PGPASSWORD = '<restore-role-secret>'
pg_restore --exit-on-error --no-owner --no-privileges --dbname $env:PGDATABASE "shiptrip-pre-release.dump"
Remove-Item Env:PGPASSWORD
```

Run Django checks, migration plan (expected empty), row-count/invariant queries, sampled ledger balance checks, provider-event uniqueness checks, and application smoke tests against the isolated restore. Record recovery time and recovery point. A backup without a successful recent restore is not a release gate.

## 4b. Geography catalogue (from Phase 8E)

The release ships the reviewed catalogue as
`backend/monolith/apps/locations/data/geography_manifest_2026.json.gz`, and the
combined launcher applies it with `manage.py import_geography --skip-if-current`
**after** the gateway is listening. Read the sequence rather than repeating it:

- [ ] Confirm the release-data test passes, so the artefact is the reviewed
      manifest (uncompressed SHA-256
      `b4aad209f4ae7ecb264fc9ae4b5d9b4b61b7ff9d918ca470729db93d1abb7692`,
      56,134 places / 3,833 alternate names / 165 mappings / 161 airports).
- [ ] Expect the first boot after this release to log
      `applying bundled geography catalogue (skip-if-current)` and then the
      import counts. Rehearsed at 145.7 s and a 280 MB peak against
      PostgreSQL 16; every boot after it is a ~1 s indexed no-op.
- [ ] The service is **ready before the catalogue lands**. During that window
      canonical place search returns nothing and request/journey creation is
      refused. This is expected on a first deployment and is not a rollback
      trigger; the import is one transaction, so a partial catalogue is never
      visible.
- [ ] Verify afterwards on **Operations → Geography catalogue**: the applied
      manifest digest, the per-country counts, and 161 airport-to-locality
      links. `No catalogue import is recorded` means the import failed — check
      the deployment log for `geography catalogue import FAILED`. Re-running is
      safe: the command is transactional and rerunnable.
- [ ] Do not add `--deactivate-missing` to the boot path. Retiring catalogue
      rows a live deployment is matching on is an operator decision, not a
      restart side effect.

## 5. Deploy sequence

The combined launcher currently runs migrations and `collectstatic` before starting the web process, then starts Django web, Django gRPC, reservation releaser, durable finance worker, Go services, and Caddy, and finally applies the bundled geography catalogue (§4b). Because application and migration are one rollout unit, migrations must be backward-compatible with the previous release.

1. Announce the release window and confirm the backup/restore evidence.
2. Ensure the new image is built from the reviewed commit and tagged with the release identifier.
3. Keep all external providers in their existing state. Do not combine first production deploy and provider activation.
4. Trigger one application deployment through the approved Railway UI/CLI workflow. Do not create an automatic GitHub Actions production deployment.
5. Watch migration output. Abort on an unexpected plan, precondition failure, lock timeout, or table rewrite beyond rehearsal.
6. Watch child startup. All required processes must listen; any child exit makes the combined launcher fail.
7. Require `/healthz` 200 with the expected release, then `/readyz` 200 with database, migrations, and `rate_limit_cache` all `ok`. Railway entrypoint health checks target `/readyz`; do not route new traffic on liveness alone.
8. Authenticate as a least-privilege Ops user and inspect `/api/admin/health/deep`, provider health, scheduled jobs, provider events, email backlog, and audit log. From Phase 8E the provider block also reports `stripe_mode` / `chargily_mode` — `test`, `live`, `unknown` or `not_configured` — derived from each credential's documented shape. It is the supported way to confirm which rail a deployment is armed against; reading a key to find out is not. `unknown` on a configured rail means the credential and the API base disagree, or the key is not a shape this code recognises: treat it as a stop condition, not as `test`.
9. Verify public EN/FR/AR routes, assets, security headers, legal/support placeholders, 404 behavior, API/admin framing refusal, and TLS/HSTS.
10. Run the production smoke checklist below with controlled test accounts and no live provider calls unless activation is separately authorized.
11. Observe error rate, p95 latency, PostgreSQL connections/locks, worker claims, retry backlog, Redis status, and 4xx/5xx request IDs for at least one normal job interval plus the agreed soak period.
12. Record success and unfreeze business settings. Provider activation, if approved, follows `PROVIDER_ACTIVATION_RUNBOOK.md` as a separate change.

For a future split topology, deploy backward-compatible Django/database first, then durable workers, gRPC/Go services, gateway/static web. Keep old and new versions mutually compatible throughout the rolling window.

## 6. Production smoke checklist

Use unique controlled accounts/data and clean them only through approved product/admin flows. Capture request IDs and object references, never secrets/codes.

- [ ] Liveness/readiness/deep health and release identifier.
- [ ] Registration, email verification (requires email activation), login, refresh rotation, logout, password reset (requires email activation), Google OAuth if configured.
- [ ] Sender creates a V1 DeliveryRequest; exact locations stay hidden before funding.
- [ ] Verified traveler creates FLIGHT/DRIVE Journey; flight proof review and KYC gate publication.
- [ ] Compatible discovery respects route/time/capacity; sender proposes; boost does not override incompatibility.
- [ ] Offer acceptance creates a reservation transactionally and payment grace is durable.
- [ ] Posting deposit and Deal payment: mark `requires activation` for real Stripe/Chargily; local/test provider only outside production.
- [ ] Funded Deal reveals exact locations only to parties.
- [ ] Chat send/history/notification pagination and WebSocket degradation/recovery.
- [ ] Push health reports configured plus a fresh worker heartbeat; FCM stream
      lag/pending is bounded and no token or credential appears in logs.
- [ ] Controlled push proves inbox row -> stream -> Firebase acceptance; record
      physical receipt separately. Keep `FCM_ENABLED=false` if the matching
      mobile project IDs, private mounted Admin credential, or test token is absent.
- [ ] Pickup code: only sender reveals, traveler submits, rate/attempt lockout works.
- [ ] Delivery code: unavailable for 30 minutes, traveler never retrieves it, recipient email requires activation, valid submission confirms delivery.
- [ ] Protection opens for 48 hours; payout remains blocked.
- [ ] Dispute freezes payout; evidence signed URL is short-lived and authorization-gated; granular admin status/resolve audit appears.
- [ ] Refund and payout: `requires activation` for external movement; verify manual queues, permissions, audit, idempotency, and reconciliation without moving real funds unless explicitly authorized.
- [ ] Scheduled jobs: pending/retry/oldest/manual-action metrics and worker progress.
- [ ] Admin invitations expire, cannot be reused, respect roles, are throttled, and emit audit/mail obligations.
- [ ] Static website localized routes/assets/CSP/cache/404; no placeholder support/legal content may pass final launch approval.

## 7. Completion record

Record release, commit/image digest, migration set/durations, snapshot and logical-backup references, restore evidence, smoke results, health screenshots with no sensitive data, metrics before/after, incidents, active business-settings version, provider state, and the named GO/NO-GO approver.
