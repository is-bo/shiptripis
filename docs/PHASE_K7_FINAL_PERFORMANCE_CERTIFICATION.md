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
