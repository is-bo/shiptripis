# K6 — Infrastructure, Caching, Workers, Observability & Load

Status: **in progress.** Branch `claude/k6-infrastructure-scaling`, stacked on the
K5 branch head `b5e1118` (K5 is complete locally; see its record). By owner
decision (2026-09-23) there is no per-phase CI run or Railway deploy: one CI
run and one TEST release happen at the end of K7.

## Baseline (Railway TEST, idle, 24 h, 2026-09-23)

| Service | CPU avg | Memory avg | Memory peak |
| --- | ---: | ---: | ---: |
| `shiptrip` (Django + Gunicorn + Caddy + embedded Redis + Go workers) | ~0.006 vCPU | 0.62 GB | 1.14 GB |
| `Postgres` (managed) | ~0.001 vCPU | 0.12 GB | 0.13 GB |

The project has exactly these two services. Redis is still the embedded
loopback instance with persistence off (`SHIPTRIP_EMBEDDED_REDIS=true`), as
recorded in K1 §11: Railway refused to provision Redis with `Free plan resource
provision limit exceeded`.

## Packages (delegated, reviewed before integration)

- **R — persistent shared Redis (14.1, 14.2).** Responsibility map, one shared
  `REDIS_URL` for every process, idempotent consumer groups, pending-entry
  recovery, eviction safety, a read-only stream inspector, cutover/rollback and
  restart-proof runbook. Findings: `docs/k6-notes/redis.md`.
- **L — topology, pooling, web capacity, load, capacity model (14.3, 14.5,
  14.6, 14.15, 14.16).** Local load harness, connection budget, Gunicorn
  sizing, scale triggers. Findings: `docs/k6-notes/capacity.md`.
- **O — workers, retries, breakers, background work, caching, observability,
  alerts (14.4, 14.7–14.14).** Findings:
  `docs/k6-notes/reliability-observability.md`.
- **At the final TEST release (end of K7):** provision managed Redis with
  proven persistence, cut over per the package R runbook, prove restart
  survival, and run the failure drills (14.17) on TEST.

## Resume here

Packages R, L and O were launched in helper worktrees from `b5e1118`. If a
session ends before they report: check `git worktree list` for
`.claude/worktrees/agent-*` branches with commits or uncommitted work, review
and integrate them onto this branch, assemble the `docs/k6-notes/*` findings
into this record, then start K7.

**Possible owner action:** provisioning Redis may again hit the Railway free
plan limit. If it does, the owner must upgrade the Railway plan (or supply an
approved persistent Redis) before the final release can complete the cutover.
