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

C is integrated (`41fc5fb`). A, B and D are running in helper worktrees.

Packages A, B and C run in helper worktrees from `f77ae0e` (check
`git worktree list`; review and cherry-pick their commits onto the stack).
Then: re-run K6 capacity with a corrected traffic mix (`find-travelers`,
`compatible-requests` instead of journeys search / parcels open); assemble this
record; independent review of K6+K7 runtime changes; full Flutter + Django
suites; one PR (K5–K7) → CI → merge; Railway TEST release
`v1.0.0-rc.50+<sha>`, `/healthz`, `/readyz`, smoke, TEST-safe resilience drills
(worker restart, rolling deploy); release record; K-Series Master Report
(plan §20). Redis provisioning/cutover stays pre-launch (owner).
