# VPS environment and secret reference

All examples are placeholders. Supply values only on the future server during
V3, using the owner’s vault. `stack.env` is literal unquoted configuration; secret
JSON strings safely support punctuation. Do not shell-source either env file.
Do not copy `backend/.env` into images or use its development values on a VPS.
`APP_IMAGE`, `BACKUP_IMAGE`, `RELEASE_ID`, `SECRETS_DIR`, `STACK_ENV_FILE`,
`BACKUP_ENV_FILE`, `SITE_ADDRESS`, `ADMIN_CIDRS`, production switches, PostgreSQL
identity, mandatory storage config and distinct application secrets are required
before initial startup. Optional features remain disabled unless explicitly supplied.

## Host / topology

| Variable | Meaning and V3 source |
| --- | --- |
| `APP_IMAGE` | App image tagged with full reviewed Git SHA or immutable digest; build from that clean checkout. |
| `BACKUP_IMAGE` | Backup image from reviewed code, same immutable tagging rule. Retain alongside app release. |
| `RELEASE_ID` | Full 40-character reviewed Git SHA, emitted by health/logging. |
| `SECRETS_DIR` | Absolute private host directory holding the four secret files. |
| `STACK_ENV_FILE` | Absolute path to the one active stack config, normally `/etc/wacla/stack.env`. |
| `BACKUP_ENV_FILE` | Absolute path to separate 0600 offsite-backup config. |
| `SITE_ADDRESS` | Single actual owner-selected DNS hostname, without scheme/path; no assumed domain. |
| `ACME_EMAIL` | Owner’s certificate-expiry/contact mailbox. No real certificate request during V1. |
| `BIND_IP` | Public gateway binding; normally `0.0.0.0`; local integration override uses loopback. |
| `ADMIN_CIDRS` | Space-separated approved source CIDRs or secure-access egress addresses; `/0` refused. |
| `WEBSOCKET_ORIGINS` | Space-separated explicit HTTPS browser origins. Native Flutter without Origin is supported; unknown browser origins rejected. |
| `WACLA_CONFIG` | Host CLI override for config path; defaults to `/etc/wacla/stack.env`. |
| `WACLA_STATE` | Private host CLI state directory; defaults to `/var/lib/wacla`. Do not delete release/recovery state. |

## Django / workers

| Variable | Meaning and V3 source |
| --- | --- |
| `SHIPTRIP_ENVIRONMENT` | Must remain `production` for this Django profile; historical config name is intentionally preserved. |
| `DJANGO_DEBUG` | Must be `false`. |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated actual hostname plus `localhost` for internal health probes; never wildcard. |
| `CORS_ALLOWED_ORIGINS` | Comma-separated HTTPS browser origins; empty valid for native-only API. |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated HTTPS origins used by Admin/browser POSTs. Must match actual deployment. |
| `POSTGRES_DB`, `POSTGRES_USER` | Stable lower-case database/owner identifiers chosen before initialization. Do not change to try resetting data. |
| `WEB_CONCURRENCY`, `WEB_THREADS` | Gunicorn processes/threads; initial 4 × 2 based on K6 measurements. |
| `KYC_GRPC_WORKERS` | Django gRPC executor threads; initial 4. |
| `CHAT_DB_MAX_CONNS`, `NOTIF_DB_MAX_CONNS`, `EMAIL_DB_MAX_CONNS` | Go pool maxima; initial 8, 6, 2. |
| `RESERVATION_RELEASE_INTERVAL_SECONDS` | Single releaser poll interval; 60 seconds. |
| `FINANCE_JOB_INTERVAL_SECONDS` | Single durable finance/lifecycle/outbox loop interval; 30 seconds. |
| `GRPC_AUTH_MODE` | `bearer` over container loopback for retained combined topology. mTLS is already supported by the application for a future split. |
| `GRPC_ALLOW_PRIVATE_BEARER` | Explicit `true` opt-in required by existing production safeguards. Token below is dedicated. |
| `GOOGLE_OAUTH_CLIENT_IDS` | Optional owner-verified OAuth audience list; leave empty until configured. |
| `LOG_LEVEL` | Go structured log level; `info` initially. |
| `PERFORMANCE_ACCESS_LOG_ENABLED` | `true` to retain safe route-template/status/timing logs. |
| `PERFORMANCE_DB_METRICS_ENABLED` | Optional query timing, initially `false` to avoid overhead. |
| `SENTRY_DSN` | Optional external error destination; blank in V1. Review PII policy before activation. |

Compose supplies `DJANGO_SETTINGS_MODULE=config.settings.prod`,
`POSTGRES_HOST=postgres`, `POSTGRES_PORT=5432`, `POSTGRES_CONNECTION_LIMIT=100`,
`POSTGRES_CONNECTION_RESERVE=15`, `PORT=8080` and the release ID. Do not set a
separate `DATABASE_URL`, `REDIS_URL` or `ROUTE_PROVIDER_CACHE_URL`. Runtime derives
authenticated Redis from its shared password file; all stream names/group IDs and
existing retry controls keep application defaults. Optional tuning not listed here
must be reviewed against `backend/.env.example` and actual loaders before use.

## Object storage

| Variable | Meaning and V3 source |
| --- | --- |
| `S3_ENDPOINT_URL` | External HTTPS S3-compatible endpoint; owner’s storage provider, never local public filesystem. |
| `S3_REGION` | Exact provider region. |
| `S3_USE_PATH_STYLE` | Provider addressing mode; verify signed URL behavior before launch. |
| `S3_BUCKET_PARCEL` | Private parcel-media bucket with existing authorization/signed URL policy. |
| `S3_BUCKET_PROOF` | Private transport-proof bucket; keep separate name explicit even if current provider shares storage. |
| `S3_BUCKET_DISPUTE` | Private evidence bucket; no public ACL. |
| `S3_BUCKET_KYC` | Private identity-evidence bucket. |
| `KYC_S3_ENDPOINT_URL`, `KYC_S3_REGION`, `KYC_S3_USE_PATH_STYLE` | KYC credential scope/endpoint used by Go KYC and authorized Django evidence access. |
| `S3_BUCKET_PAYOUT`, `PAYOUT_S3_ENDPOINT_URL`, `PAYOUT_S3_REGION`, `PAYOUT_S3_USE_PATH_STYLE` | Separate private payout-evidence store; leave blank while payout profiles disabled, preserve existing real values for migration. |

Keep existing bucket names/references when migrating. Never rename/move existing
objects because the product name changed. Marketing assets are bundled `/web`,
not uploaded sensitive evidence. Bucket encryption, CORS, access logs, signed URL
reachability and provider lifecycle policy are V3 verification items.

## Payments / email / push boundaries

| Variable | Meaning and V1 requirement |
| --- | --- |
| `PAYMENTS_ENVIRONMENT` | `test` only. |
| `PAYMENTS_ALLOW_MOCK_PROVIDER` | `false`; production mock remains forbidden. |
| `PAYMENTS_MOCK_WEBHOOK_ENABLED`, `PAYMENTS_LEGACY_MUTATIONS_ENABLED` | Both `false`; no legacy bypass. |
| `PAYMENTS_PUBLIC_BASE_URL` | HTTPS origin of future API domain, matching owner’s actual gateway. |
| `STRIPE_API_BASE` | Official `https://api.stripe.com`; credential must be TEST if supplied. |
| `CHARGILY_API_BASE` | Official `https://pay.chargily.net/test/api/v2`. |
| `PAYOUT_PROFILES_ENABLED` | Initially `false`; preserve encrypted historical profile keys independently. |
| `PAYOUT_DZD_EXECUTION_ENABLED` | `false`. |
| `STRIPE_CONNECT_ENABLED` | Initially `false`; no external onboarding during V1. |
| `STRIPE_CONNECT_PAYOUTS_ENABLED`, `STRIPE_CONNECT_NON_STRIPE_FUNDING_ENABLED` | Both `false`. |
| `STRIPE_CONNECT_EXPECTED_MODE` | `test`. |
| `STRIPE_CONNECT_API_VERSION` | Existing reviewed Connect version `2026-03-25.dahlia`. |
| `STRIPE_CONNECT_ALLOWED_COUNTRIES` | Empty until reviewed TEST onboarding evidence, within existing application country ceiling. |
| `STRIPE_CONNECT_PLATFORM_ACCOUNT_ID` | Owner-verified platform account; blank while disabled. |
| `STRIPE_CONNECT_ONBOARDING_RETURN_URL`, `STRIPE_CONNECT_ONBOARDING_REFRESH_URL` | Distinct HTTPS URLs on public origin; blank while disabled. |
| `EMAIL_ENABLED` | `false` by default; no V2 activation. |
| `EMAIL_ACTIVATION_APPROVED` | `false`; independent VPS approval latch for eventual V3 activation. |
| `EMAIL_ACTIVATION_NOT_BEFORE` | Empty while disabled. At V3 activation set an ISO timestamp with timezone; older rows require explicit review. |
| `EMAIL_PROVIDER` | `sender_net`, using the existing SMTP interface. |
| `EMAIL_USE_TLS` | `true` prepared for V2; no SMTP activation. |
| `EMAIL_SENDING_DOMAIN_VERIFIED` | `false` until V2/V3 domain evidence. |
| `EMAIL_SMTP_HOST` | `smtp.sender.net`, inert while disabled. |
| `EMAIL_FROM_ADDR`, `EMAIL_SUPPORT_ADDR`, `EMAIL_REPLY_TO` | Blank; owner supplies verified-domain identities and a monitored support inbox. |
| `EMAIL_SMTP_PORT` | Prepared default 587, inert. |
| `EMAIL_SMTP_TIMEOUT_SECONDS` | 10, valid range 1–10; both senders bound SMTP connections. |
| `EMAIL_RATE_LIMIT_PER_MINUTE` | 60 initially, valid 1–600; calibrate against the actual Sender account limit in V3. |
| `EMAIL_FROM_NAME` | `Waçla` presentation name for eventual sending. |
| `FRONTEND_BASE_URL` | Future HTTPS hosted origin; does not change mobile API origin. |
| `FCM_ENABLED` | `false` initially. V3 must match server/mobile Firebase projects before enabling. |
| `FCM_PROJECT_ID` | Optional actual Firebase project; blank while off. |

V2 prepares the existing SMTP path while keeping both activation switches off.
The mounted `app.json` secret allowlist now accepts `EMAIL_SMTP_USERNAME` and
`EMAIL_SMTP_PASSWORD`; leave them empty in V2. Never place them in `stack.env`,
images or Git. Follow [the email runbook](EMAIL.md) for backlog review, domain
authentication, mailbox configuration and eventual V3 activation. Existing
financial/provider guards remain enforced. Configuration validation needs no
external provider call.

## Secrets and generation

`app.json` allows the following existing application keys; omit unused optional
ones instead of adding a second source in `stack.env`. Files are mounted read-only,
then the wrapper injects values into the application environment. Docker/host root
can inspect process memory/environment: this is single-server least privilege,
not a defense against host root compromise. Existing launcher filtering withholds
payment/payout encryption secrets from Go services and internal gateway children.

| Key / file | Meaning and source |
| --- | --- |
| `DJANGO_SECRET_KEY` | Distinct ≥32-character random session/signing root; preserve existing value for migration. |
| `JWT_HS256_SECRET` | Distinct ≥32-character shared Django/Go access-token signing key; preserve or coordinate revocation. |
| `GRPC_BEARER_TOKEN` | Dedicated ≥32-character token for authenticated loopback KYC recording. |
| `HANDOVER_CODE_SECRET` | Dedicated ≥32-character pickup/delivery-code secrecy root; must be transferred unchanged for existing records. |
| `TRANSACTIONAL_EMAIL_SECRET` | Dedicated ≥32-character encrypted-outbox root, required even while email disabled; preserve historical decryptability. |
| `S3_ACCESS_KEY`, `S3_SECRET_KEY` | Scoped media/evidence storage credentials from provider. |
| `KYC_S3_ACCESS_KEY`, `KYC_S3_SECRET_KEY` | Separately scoped private KYC credentials. |
| `PAYOUT_S3_ACCESS_KEY`, `PAYOUT_S3_SECRET_KEY` | Optional payout-evidence credentials, separate scope. |
| `PAYOUT_DATA_KEYRING`, `PAYOUT_DATA_ACTIVE_KEY_ID`, `PAYOUT_ACCOUNT_FINGERPRINT_KEY` | Existing payout encryption keyring/active key/fingerprint root; preserve all historical keys. Keyring is a JSON string inside the secret JSON. See existing payout runbooks before generating new keys. |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | Optional matching TEST platform credential/signing pair; omit while inactive. Never LIVE. |
| `STRIPE_CONNECT_WEBHOOK_SECRET` | Optional distinct Connect destination signature secret, not platform webhook secret. |
| `CHARGILY_SECRET_KEY`, `CHARGILY_WEBHOOK_SECRET` | Optional TEST key; webhook override must follow existing signing contract. |
| `FCM_CREDENTIALS_JSON_BASE64` | Optional base64 service-account JSON from correct Firebase project; existing helper materializes private file under `/tmp`, drops payload before children. Never commit/download into public paths. |
| `postgres-password` | ≥64 hex characters in host file; shared by PostgreSQL and app. Choose before database initialization. Changing file alone does not rotate the existing database role. |
| `redis-password` | ≥64 hex characters; shared by Redis and runtime-derived URL. Rotation requires coordinated restart/client handling. |
| `restic-password` | ≥64 hex characters; backup encryption password, independently escrowed; 0640/GID 10001 for the non-root backup container. Do not rotate by overwriting without managing restic repository keys. |

## Backup and retention

`backup.env` contains `RESTIC_REPOSITORY` (restricted offsite repository URI),
`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION` (backup-only S3
identity), and positive owner-selected `BACKUP_KEEP_DAILY`, `BACKUP_KEEP_WEEKLY`,
`BACKUP_KEEP_MONTHLY`. This package supports HTTPS S3-compatible offsite repositories;
SFTP/SSH and other backends need separate client/authentication preparation and are
refused here. Inline repository-URI credentials are forbidden. `RESTIC_PASSWORD_FILE` is fixed by Compose to
the mounted file; never duplicate it as a plaintext password variable. `PGHOST`,
`PGPORT`, `PGUSER`, `PGDATABASE`, `PGPASSWORD` are fixed/injected for this stack.
Tests alone set `BACKUP_TEST_MODE=true` and use a newly created local repository;
the operator CLI refuses this switch. No production offsite credentials are needed
for local backup/restore tests.

`RETENTION_ENABLED=false` by default. Before setting true, the owner must choose
`RETENTION_JOB_DAYS` (existing command minimum 30, **not a legal recommendation**),
`RETENTION_PUSH_DAYS` and `RETENTION_MEDIA_HOURS`. Jobs pruning removes only
succeeded/operator-resolved execution rows, never ledger/payment/audit records.
Push pruning deactivates stale installations; media cleanup removes unclaimed
staged media only. Legal/KYC/financial retention is a separate owner/counsel policy,
not invented or activated here. Existing token expiry cleanup follows the token’s
own expiration rather than creating a new retention duration.
