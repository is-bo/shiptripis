# Package H1: repository files and branches

Documents and files only. No product code, no behaviour change, nothing deployed. Plan section 7.3;
brief `docs/handoff/builders/H1.md`. Git keeps every removed file.

## Files

Each path was searched across the repository (`git grep` over workflows, scripts, documents,
`CLAUDE.md`, `AGENTS.md`, `HANDOFF.md`) before the decision.

| File | Evidence | Decision |
|---|---|---|
| `TASKS.md` | Two-owner list ("Islam + Alaa"); `CLAUDE.md` ended the split. Named only by `HANDOFF.md` (the cleanup candidates), by a superseded handover and by the `docs/superpowers` notes removed below. The two "deliberate behaviour" notes it keeps (B2 handover code issued once, B7 asymmetric counter-offer) are rules now in `CLAUDE.md` ("traveler can never retrieve the delivery code", "the sender proposes first") and the specification. | Removed |
| `ShipTrip_Progress_Report.pdf`, `tools/make_progress_pdf.py` | The script only builds that PDF, to a Windows path (`C:\Users\...`). No workflow, script or runbook names either. | Removed |
| `backend/services/AGENTS.md`, `opencode.jsonc`, `.mcp.json`, `.codegraph` | Configuration of a code-graph tool and an editor agent. `backend/services/HANDOVER.md` itself calls them "editor/agent config, not project work". Only the `.dockerignore` names them, to keep them out of the image. | Removed; the three matching `.dockerignore` lines too |
| `.cursor/`, `.codegraph/` (root) | Same tool, same class; only a rules file and a `.gitignore`. Not in the brief; named as candidates in `HANDOFF.md` 5.3. | Removed |
| `package.json` (`{}`), `package-lock.json` | No workflow runs `npm`; the one Node check (`node --test tools/web/globe.test.mjs`) needs no package file. | Removed |
| `docs/superpowers/` (3 specs, 1 plan, June to August) | Notes of an earlier agent tool. Named only by `HANDOFF.md` (history) and by themselves. | Removed |
| `docs/handoff/astra/n2-review.md`, `c1-plan.md` | Prompts of finished rounds (N2 merged, C1 plan answered). Their results stay in `docs/handoff/astra/results/`. | Removed |
| Other `docs/handoff/astra/*.md` and `drafts/` | Prompts for F1, G1, N1 and P3B, whose pull requests are open. Their branches edit these files, and `HANDOFF.md` points at the G1 draft. | Kept until each package merges |
| `backend/services/HANDOVER.md` | Named by live code outside H1's scope: `internal/kyc/handler.go:443`, `pkg/config/config.go:301` and the admin-helper knowledge sources. | Kept; follow-up for DC |
| `web/.impeccable/design.json` | The design-system file of the Impeccable audit that the V1 specification requires (section on audits); named by `docs/LANDING_HERO_IMPLEMENTATION.md`. | Kept (unsure, so it stays) |
| `docs/k6-notes/`, `docs/k7-notes/` | Linked from `PHASE_K6_*`, `PHASE_K7_*`, `K_SERIES_MASTER_REPORT.md`, `backend/loadtest/README.md`; a test docstring cites `k7-notes/certification.md`. | Kept |
| `backend/loadtest/` | Its README links `docs/k6-notes/capacity.md`; `data_scale_probe.py` backs `k7-notes/data-scale.md`; `ARCHITECTURE.md` lists it. | Kept |
| `tools/preview/` | Named by `docs/ADMIN_OPERATIONS.md`, `docs/V2_EMAIL_READINESS.md` and `PHASE6B_*`. | Kept |
| `tools/local_load_test.py` | Named by `docs/PHASE7A_PRODUCTION_READINESS.md`. | Kept |

## Documents checked against the code

- `ARCHITECTURE.md`: `tools/` line made complete; four Django apps added to the table (`discovery`,
  `routing`, `problems`, `admin_helper`); the delivery marker is `delivered:<event_id>:<user_id>`
  (as in `internal/notification/dispatcher.go`), fixed in three places. Checked and right: topology,
  JWT leeway and TTL, presence TTL, 25% default commission, Go packages and binaries.
- `PRODUCT.md`: the corridor sentence now names the four launch countries and the fast-delivery
  target; the non-goals no longer list the admin console and landing site, which exist, and name the
  parked scope.
- `DESIGN.md`: checked against `mobile/lib/design/`, the bundled fonts and `Money` (no `+` or `-`
  operator). Nothing wrong.
- `README.md` held the text `project 07`; it is now six lines that point to `CLAUDE.md`, `HANDOFF.md`
  and the documents above.
- Not in H1: `web/README.md` still says "EU ↔ Algeria launch scope".

## Link check

`*.md` links to files, run over `git ls-files`: three broken before, none after.
`V1_VPS_READINESS.md` listed two files since removed (`infra/vps/render_internal_caddy.py`,
`backend/railway/start.py`) as links, now plain names marked "since removed"; one Astra result linked a
Windows pub-cache path, now plain text.

## Branches

The list is in the pull request. Ismail approves it before any branch is deleted.
