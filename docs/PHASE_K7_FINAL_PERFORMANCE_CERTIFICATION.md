# K7 — Realtime, High-Scale Tuning & Final Certification

Status: **in progress.** K7 work is integrated onto
`claude/k6-infrastructure-scaling` (K5 → K6 → K7 stack; owner decision: one CI
run and one Railway TEST release after K7, then merge).

## Packages (delegated, reviewed before integration)

- **A — realtime (15.1–15.6):** SSE vs WebSocket, presence heartbeat load,
  buffers/backpressure, reconnect storms, missed-event recovery, chat scaling.
  Findings: `docs/k7-notes/realtime.md`.
- **B — data scale (15.7–15.9):** replicas, partitioning, `pg_trgm`,
  Elasticsearch, CQRS, sharding verdicts; Find Travelers cost; growth and
  retention. Findings: `docs/k7-notes/data-scale.md`.
- **C — certification (15.10–15.12, §19):** flow benchmarks, mobile and
  resilience certification mapped to evidence, acceptance-criteria check.
  Findings: `docs/k7-notes/certification.md`.

- **D — measured defects from C:** bounded/concurrent storage checks on admin
  KYC + Payout Review detail, admin dispute list reachable beyond 100 rows,
  trimmed Offers list payload (only provably unused fields).

## Review fixes

Confirmed findings from the K6+K7 runtime review, fixed with a test each:

- **Email PII in logs:** send failures log a `SendFailure` (class, go-mail
  stage, SMTP code/RFC 3463 status, relay host) — never go-mail's error text,
  which lists recipients; the stub sender no longer logs the subject.
- **Email duplicate send:** an error after DATA was accepted (RSET/QUIT) is
  treated as sent (`msg.IsDelivered()`).
- **FCM sweeper race:** a handler that could still be sending when its entry
  passes the 60 s reclaim window (queued for a slot, or a long backoff) leaves
  it for the sweeper instead of pushing twice; counted.
- **WS receipt for a discarded frame:** `Conn.Send` refuses once `connCtx` is
  cancelled and checks `done` before a free buffer slot.
- **Shutdown budget:** email `sendTimeout` 30 s → 12 s (+3 s ack) fits the Go
  15 s drain and the launcher's 20 s child stop (< `drainingSeconds` 30);
  pinned by `test_deployment_safety`.
- **Launcher Redis preflight:** a timeout/connection error during `CONFIG GET`
  is a clean `RuntimeError` naming host:port only.
- **SQLite test:** the K7-E prune test asserts the row lock only where the
  backend has `SELECT … FOR UPDATE`.
- **Alertable drops:** FCM stale/exhausted/deferred and email stale counters,
  an `email_stats` log line, and alert rows in
  `docs/k6-notes/reliability-observability.md`.
- **Chat relay drop-when-busy:** same 250 ms bounded wait before
  drop-and-count as E's notification dispatcher.

## Resume here

All implementation packages are integrated: A `71dc984`, B `212c757`,
C `41fc5fb`, D `b2326df`, E `1ed3eb4`. Running: an independent review of all
K6+K7 runtime changes (`b5e1118..1ed3eb4`), and a capacity re-run with the
corrected traffic mix (helper worktree; updates `docs/k6-notes/capacity.md`).
Then: fix confirmed review findings (+ the chat relay's drop-when-busy, same
fix as E's dispatcher), full Flutter + full Django suites, assemble this record
and the K-Series Master Report, one PR (K5–K7) → CI → merge → Railway TEST
release `v1.0.0-rc.50+<sha>` → `/healthz`, `/readyz`, smoke, TEST-safe drills
(worker restart, rolling deploy) → release record. Redis provisioning/cutover
stays pre-launch (owner).
