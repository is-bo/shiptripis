---
name: Rate limiting lives at the Caddy gateway, not in app code
description: Architectural decision — rate limiting is Caddy's responsibility, not the Go services or Django. Do not build pkg/ratelimit.
type: feedback
---
Rate limiting (per-IP, per-user, reconnect-storm protection per CLAUDE.md §10) is enforced at the **Caddy gateway**, not in Go services or Django.

**Why:** Centralizes the policy in one place that already sees every request, keeps app code free of per-route token-bucket boilerplate, and matches the gateway's role as the single ingress. Decided 2026-05-13 while planning the Go pkg surface — rejected building `pkg/ratelimit` for `cmd/chat` / `cmd/notif` WS reconnects.

**How to apply:**
- Do not propose or build `pkg/ratelimit` in `backend/services/pkg/`.
- Do not add `golang.org/x/time/rate` token buckets into Go handlers.
- Do not add Django middleware for rate limiting.
- If a per-route limit is needed, add it to `backend/gateway/Caddyfile` (shared file — explicit user approval per CLAUDE.md §1 before editing).
- The §10 thundering-herd reconnect storm is mitigated by mobile client jitter (already mandatory) + Caddy connection limits — not by server-side accept-throttling.
