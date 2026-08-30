# ShipTrip

ShipTrip matches parcel senders with travelers, handles offers and escrow-like
payment state, and provides real-time chat and notifications. The repository is
a monorepo containing:

- `backend/monolith`: Django REST API, admin, data model, payment state, and the
  authoritative KYC gRPC server.
- `backend/services`: Go chat, notification, KYC upload, and email workers.
- `backend/gateway`: Caddy public gateway.
- `mobile`: Flutter Android/iOS client.

## Local development

Requirements: Docker Desktop with Compose.

```bash
cp backend/.env.example backend/.env
cd backend
docker compose up --build
```

The gateway is available on `http://localhost:8080`; Django health is
`/healthz`. Development credentials in `.env.example` are intentionally unsafe
and must never be used in a hosted environment.

## Quality gates

GitHub Actions runs Go formatting/build/vet/race tests, Redis integration tests,
Django migrations/Postgres tests/Ruff, schema-drift checks, and Flutter format,
analysis, and tests.

## Railway deployment

The root `railway.json` builds `backend/railway/Dockerfile`, a free-plan layout
that runs the gateway, Django, gRPC, Go workers, and loopback-only Redis in one
compute service backed by managed Railway Postgres and two private buckets.
Redis pub/sub/stream data is ephemeral in this constrained layout, while all
authoritative records remain in Postgres.

Paid deployments can split the same processes into one public `gateway` service
plus private `django-web`, `django-grpc`, `chat`, `notification`, `kyc`, and
`email` services backed by managed Redis. Their service-level configuration is
versioned next to each Docker build:

- `backend/gateway/railway.json`
- `backend/monolith/railway.web.json`
- `backend/monolith/railway.grpc.json`
- `backend/services/railway.json`

Secrets and resource references are configured in Railway, never committed.
Only the combined gateway receives a public domain. Mock and legacy payment
paths are refused in production; Stripe and Chargily remain disabled until a
separately approved provider-activation procedure is completed. The initial
deployment is private pre-launch infrastructure, not an invitation to users.

## Android artifact

After deployment, run the manual **Build Android** GitHub workflow and supply
the gateway HTTPS origin. Its default path builds a GitHub-Secrets-signed APK
and AAB; a clearly labeled debug APK is available only as a development
fallback. See `docs/ANDROID_BUILD_RUNBOOK.md` for signing, download,
installation, and optional RC GitHub Release steps.
