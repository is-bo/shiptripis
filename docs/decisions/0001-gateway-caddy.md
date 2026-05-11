# ADR 0001 — Gateway: Caddy (not Nginx)

**Date:** 2026-05-12
**Status:** Accepted
**Scope:** Shared (both Claudes)

## Decision

Caddy is the API gateway for ShipTrip across dev, staging, and production.

## Why not Nginx

| Concern | Nginx | Caddy |
|---|---|---|
| Config language | Mini-DSL with quirks (e.g. `location` regex precedence is non-obvious) | Caddyfile is line-oriented, directives are explicit, ordering is documented |
| TLS in prod | Manual cert handling + cron or external manager | Built-in ACME — auto cert + auto renewal, zero config |
| WS routing | Works, but `proxy_pass` + `Upgrade` + `Connection` headers must be set manually | `reverse_proxy` knows about websockets; no per-route header gymnastics |
| Health-check endpoint | Need a `location = /healthz` block | `respond /healthz "ok" 200` one-liner |
| Reload semantics | `nginx -s reload` works, but config-syntax errors take down the active config if you don't `-t` first | `caddy reload` validates first, refuses on error, keeps old config running |
| Windows + WSL ergonomics | Works, but every cert/permissions issue is on you | Plays well with Docker Desktop's network model; no extra dance |

For our shape — a single Django origin + 4 Go services + WebSockets +
auto-renewing TLS in prod — Caddy is the lower-friction choice. Nginx
wins on **raw RPS** and **third-party module breadth**, neither of which
moves the needle for V1.

## Production posture

```
{
    admin off
    # No auto_https off — production gets ACME automatically.
}

api.shiptrip.dz {
    # ... same routes as dev Caddyfile ...
}
```

`auto_https off` is for the docker-compose dev stack only (HTTP on
`:80`). Production omits that line; Caddy provisions Let's Encrypt
certs on first start.

## Operational notes

- **Graceful shutdown for WS rolling deploys**: set
  `{shutdown_timeout 30s}` in the prod global block. This lets the
  WS-owning Go pods drain connections during k3s rollouts (CLAUDE.md G1).
- **Health check**: `:80/healthz` already returns 200; k3s liveness +
  readiness probes use it.
- **HTTP→HTTPS redirect**: automatic with Caddy when an HTTPS site
  block exists; no extra config.

## What this does NOT decide

- TLS posture for inter-service gRPC (mTLS — see CLAUDE.md G5).
- WAF / rate-limiting (deferred; consider Caddy's
  `rate_limit` module in V2 if needed).

## Reversibility

Caddyfile → Nginx config is a mechanical translation if we ever need it
(a few hundred lines, no business logic). The cost of switching later
is days, not weeks.
