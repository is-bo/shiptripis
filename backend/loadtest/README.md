# ShipTrip local load harness

A reproducible way to put production-shaped traffic on the Django API and the
Go realtime relays **on a workstation**. It never targets a hosted environment: every
component binds to `127.0.0.1`, and the seeded world uses
`@loadtest.shiptrip.invalid` accounts in a dedicated database.

Findings from the first runs, and the capacity model built on them, are in
[`docs/k6-notes/capacity.md`](../../docs/k6-notes/capacity.md).

Nothing here is a production dependency. Locust lives in its own virtualenv
(`backend/loadtest/.venv`), Waitress is a dev-only install in the monolith dev
venv, and the Go tools are a separate module (`tools/`) that
`backend/services` never imports.

## Pieces

| File | Role |
| --- | --- |
| `settings_loadtest.py` | Django settings: `base.py` with `DEBUG` off, `CONN_MAX_AGE=60` + health checks (as shipped), Redis-backed throttles/route cache when `LOADTEST_REDIS_URL` is set, embedded Postgres via `LOADTEST_PGDATA` or any server via `POSTGRES_*`. |
| `manage_loadtest.py` | `manage.py` under those settings (migrate, import_geography, run the job loops). |
| `seed.py` | Builds the world through the real V1 offer/accept services and writes `.data/world.json` (JWTs, ids, admin sessions). |
| `serve.py` | Gunicorn-shaped server for Windows: W Waitress processes x T threads, optionally a real Caddy in front with `least_conn`. |
| `Caddyfile` | The harness edge; mirrors `infra/vps/gateway.Caddyfile` routing (`/ws/chat`, `/ws/notifications`, Django catch-all). |
| `locustfile.py` | Traffic mix built from the Flutter screens (one task = one screen's requests): senders 60 %, travelers 38 %, Admin console operators 2 %, 2-8 s think time. |
| `monitor.py` | Samples per-process RSS/CPU, machine CPU, `pg_stat_activity` and Postgres memory to CSV. |
| `ws_memory.py` + `tools/cmd/wsprobe` | Memory per idle WebSocket for a Go relay or Caddy. |
| `tools/cmd/miniredis` | In-memory Redis stand-in for machines with no `redis-server`. Correct protocol, **not** a Redis performance proxy. |

## One-time setup

```bash
# Locust in its own venv (Python 3.12; keeps gevent & co. out of the app venv)
python -m venv backend/loadtest/.venv
backend/loadtest/.venv/Scripts/python -m pip install locust

# Waitress into the monolith *dev* venv (never requirements.txt)
backend/monolith/.venv/Scripts/python -m pip install waitress

# Go tools (and optionally Caddy, same version as the VPS image)
cd backend/loadtest/tools && go build -o ../.data/bin/ ./cmd/...
GOBIN=$PWD/../.data/bin go install github.com/caddyserver/caddy/v2/cmd/caddy@v2.10.0
```

On Linux/macOS use `bin/` instead of `Scripts/`, and real `redis-server` plus
Gunicorn (`gunicorn config.wsgi --worker-class gthread ...` with
`DJANGO_SETTINGS_MODULE=settings_loadtest` and `PYTHONPATH` covering
`backend/loadtest`) instead of miniredis and `serve.py`.

## Seed

```bash
export LOADTEST_PGDATA=C:/Users/<you>/AppData/Local/Temp/shiptrip-pg-load   # own dir, never a test one
PY=backend/monolith/.venv/Scripts/python
$PY backend/loadtest/manage_loadtest.py migrate --noinput
$PY backend/loadtest/manage_loadtest.py import_geography --skip-if-current   # ~2.5 min, the real 56k-place catalogue
$PY backend/loadtest/seed.py                                                # ~3 min
```

Defaults: 400 travelers (800 Journeys, KYC approved, ticket proof approved),
1,200 senders (2,400 requests), 600 Deals via `create_sender_offer` +
`accept_offer` (70 % marked funded, as the K4 profiler does), 300 pending
offers, 8 chat messages per funded Deal, 25 notifications per user, 5 Super
Admins. Every size is a flag (`seed.py --help`). Re-seeding needs a fresh
database: set `LOADTEST_DB_NAME`, or snapshot one after `import_geography`
with `CREATE DATABASE shiptrip_load_base TEMPLATE shiptrip_load` and recreate
from it.

## Run

```bash
export LOADTEST_REDIS_URL=redis://127.0.0.1:6379/0
.data/bin/miniredis -addr 127.0.0.1:6379 &                  # or a real redis-server
$PY backend/loadtest/serve.py --workers 2 --threads 2 --caddy .data/bin/caddy &   # production shape
$PY backend/loadtest/manage_loadtest.py run_finance_worker --interval 30 &         # optional: the
$PY backend/loadtest/manage_loadtest.py run_reservation_releaser --interval 60 &   # idle job loops

$PY backend/loadtest/monitor.py --out backend/loadtest/.data/u100-monitor.csv --duration 330 &
backend/loadtest/.venv/Scripts/locust -f backend/loadtest/locustfile.py \
    --host http://127.0.0.1:8080 --headless -u 100 -r 5 -t 5m \
    --csv backend/loadtest/.data/u100 --only-summary
```

Start the Go relays too if you want their DB connections and memory in the
picture (`backend/services/cmd/chat`, `cmd/notification` with `DATABASE_URL`,
`REDIS_URL` and the `JWT_HS256_SECRET` from `settings_loadtest.py`), then:

```bash
$PY backend/loadtest/ws_memory.py --service-pid <chat pid> --wsprobe .data/bin/wsprobe \
    --url ws://127.0.0.1:8081/ws/chat --step 500 --steps 8
```

`--chat-send-share 0` makes the run read-only.

## Reading results

* `u100_stats.csv`: per-endpoint and aggregated p50/p95/p99 (the "Aggregated"
  row is the headline), request count, failures. `u100_failures.csv` names
  every non-2xx. A 429 is a real failure: per-user throttles are production
  values and the task weights keep a single user inside them.
* The monitor summary: `web_rss_mb_total` is the Gunicorn-equivalent memory,
  `web-*_cpu_pct` is per worker (100 = one core, the GIL ceiling),
  `db_conns_total` is every backend on the load database (web + job loops +
  Go pools), `machine_cpu_pct` includes Locust itself.
* Throughput ceiling: when `web-*_cpu_pct` sits near 100 on every worker and
  p95 climbs while RPS stops rising, the web tier is saturated at that shape.

## Honest limits

* One box runs Locust, Caddy, Python, Postgres and the relays together, so the
  load generator competes with the server. Machine CPU is recorded so this is
  visible; treat saturation points as lower bounds.
* Waitress is not Gunicorn. The process x thread shape and the GIL ceiling are
  the same; worker recycling and accept balancing are not.
* Windows working-set memory is not Linux RSS. Python/Django processes land
  within ~10-20 % of each other; `postgres_rss_mb` counts shared buffers once
  per backend and overstates.
* miniredis answers the protocol in-process; Redis latency and throughput must
  be taken from real Redis.
* Loopback has no network latency. A real network adds latency to every
  Postgres/Redis round trip, which matters for query-heavy
  endpoints.
