# VPS deploy: the final health check waits for cold workers (2026-11-23)

On the live server (2026-11-23) a deploy and a rollback both stopped at the very end although the
site was healthy, and left `/var/lib/wacla/deployment-pending.json` behind. That file refuses every
later deploy and `start` until a rollback recovery is run. Nothing is deployed by this change.

## Cause

`ready()` in `infra/vps/vps` brings `app` and `caddy` up and then runs the container's
`runtime.py health` once. That probe asks each port (8080 to 8082 `/readyz`, 8083 and 8085
`/healthz`) with a 2 second timeout. Just after the containers start, each cold gunicorn worker
spends about 2.1 s on its first Django `/readyz` (logged as `slow_http_request` 2183 ms, 2103 ms,
2060 ms). The single probe hit `TimeoutError`, the exec failed, `ready()` failed, and the deploy
aborted before it wrote `release.json` or removed the pending marker.

## Fix

`ready()` now repeats the health exec until it passes or 30 seconds have gone by (monotonic clock,
2 seconds between tries). If it never passes, the last `CalledProcessError` is raised, exactly as
before, so a genuinely unhealthy app still fails the deploy with the same message and exit code and
the same pending marker. `dc` is reused; output is still not captured, so nothing new is printed.

Host side only: `runtime.py` and its 2 s per-probe timeout are unchanged, so no image rebuild is
needed. `deploy`, `rollback` and `start` all call `ready()` and all get the retry.

## Checks

- `python -m unittest discover -s infra/vps/tests -p 'test_*.py'` (CI: `vps-readiness.yml`).
  New tests in `ReleaseRecoveryTests`: health passes on the first try (one exec, no wait); fails
  twice then passes (three execs, two waits); never passes (raises after 30 s of fake time, so the
  test is instant); a deploy whose health never passes keeps the pending marker and the current
  release.
- The suite is POSIX-only (`fcntl`, `geteuid`). It was run on a Windows machine with `fcntl`
  stubbed, so only `ReleaseRecoveryTests` could run there; CI runs the whole suite on Linux.

## To confirm on the server

After the next deploy, the pending file is gone and `vps health` passes. A deploy may print one or
two tracebacks from the early probes before the last one succeeds.
