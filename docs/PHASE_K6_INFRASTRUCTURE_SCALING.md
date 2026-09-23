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
- **Managed Redis provisioning and cutover: deferred to pre-launch by owner
  decision (2026-09-23).** K6 makes the code, configuration and runbook ready
  (package R) so the cutover is one variable change plus the restart proof; the
  owner will provision persistent Redis before launch. The TEST release at the
  end of K7 keeps embedded Redis. Failure drills that need shared Redis (14.17
  Redis restart) run at that cutover.

## Resume here

Packages R, L and O were launched in helper worktrees from `b5e1118`. If a
session ends before they report: check `git worktree list` for
`.claude/worktrees/agent-*` branches with commits or uncommitted work, review
and integrate them onto this branch, assemble the `docs/k6-notes/*` findings
into this record, then start K7.

**Owner action before launch:** provision persistent managed Redis (the
Railway free plan refused it in K1, so a plan upgrade may be needed) and run the
package R cutover runbook. Do not provision it during K6/K7.
