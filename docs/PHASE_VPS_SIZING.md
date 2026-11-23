# VPS sizing for the 4 vCPU, 8 GB server (2026-11-23)

Ismail's request of 2026-11-23: host Wassla on his netcup VPS (Ubuntu 24.04, 4 vCPU, 8 GB RAM,
160 GB SSD). The stack in `infra/vps/` was sized for 8 vCPU and 16 GB. Docker refuses a container
CPU limit above the host's CPU count (the app asked for 4.5), and the memory caps added up to about
15 GB. Nothing is deployed by this change.

## What changed

| Where | Before | Now |
| --- | --- | --- |
| `compose.yml` app (and `maintenance` base) | `mem_limit: 6g`, `cpus: 4.5` | `3g`, `3` |
| `compose.yml` postgres | `mem_limit: 4g`, `shm_size: 1g` | `2g`, `256m` |
| `compose.yml` redis | `mem_limit: 3g` | `1g` |
| `postgresql.conf` | `shared_buffers 1GB`, `effective_cache_size 3GB`, `maintenance_work_mem 256MB` | `512MB`, `1536MB`, `192MB` |
| `redis.conf` | `maxmemory 1536mb` | `512mb` (still `noeviction`) |
| `stack.env.example` | `WEB_CONCURRENCY=4` | `3` |

Unchanged: `max_connections = 100` and every connection budget, so the Go and Django pool sizes and
the launcher's checks need no change; caddy, maintenance and backup caps.

Steady state is 6.25 GB of caps (app 3, postgres 2, redis 1, caddy 0.25), plus the 0.75 GB backup
job at night, leaving room for the host. Caps are ceilings, not reservations. The redis cap leaves
headroom above `maxmemory` for the fork used by AOF rewrite and RDB saves.

The README, `ENVIRONMENT.md` and the admin helper's notes now state the new server size;
`INSTRUCTIONS.txt` is regenerated and matches the skill sources.

## Checks

- `python -m unittest discover -s infra/vps/tests -p 'test_*.py'`: 32 passed.
- `docker compose -f infra/vps/compose.yml config --quiet` with placeholder values: valid.
- `skill.instructions_text()` equals the committed `INSTRUCTIONS.txt`.

## To confirm on the server

After the first start, `vps monitor` and `docker stats` show real memory use. If the app container
approaches its cap, lower `WEB_CONCURRENCY` to 2 or raise the app cap at postgres's expense.
