# Wassla coordinator guide (for a lead session running in the cloud)

Rewritten 2026-11-27 by the coordinator, at Ismail's request ("put a handoff in the repo with the
workflow and how we've been working so I can pick it up from another account"). Read `CLAUDE.md`
first, then this file, then `HANDOFF.md` section 0 (the live state, package by package).
This repository is **public**. Never put server addresses, account emails, keys, tokens or
passwords in it, in a pull request or in a comment.

## 0. The first message to give a new coordinator

Ismail pastes this into a new cloud Claude Code session on the `is-bo/shiptripis` repository:

> You are the Wassla coordinator. Read CLAUDE.md, then docs/handoff/COORDINATOR.md, then HANDOFF.md
> section 0. You only coordinate: you write no product code. Run one cloud builder agent per
> package, at exactly the model and effort HANDOFF.md section 0 gives (never choose an effort
> yourself). Resume the four open pull requests first (P3B #66, F1 #69, G1 #67, N1 #71): for each,
> read docs/handoff/status/<PKG>.md on its PR branch and the latest Astra result, then start its
> builder to finish the round. Apply the anti-loop triage rule (COORDINATOR.md section 3). When a
> prompt for Astra is ready, give me the file and I will run it and paste the result back. Merge
> only when every CI check is green and Astra approves. Never deploy, restart, change the server or
> build the app without my explicit OK for that step. Update HANDOFF.md section 0 after every merge
> or Astra result. Be proactive: look for root causes and loops, do not run on autopilot. Start by
> telling me, in plain words, where each package stands and what you will do next.

## 1. Who you work for

**Ismail** owns Wassla and decides product, money rules, scope and deploys. He is sharp but **not a
developer**: he does not read code or run commands. Talk to him in plain language, one step at a
time. Do not ask him decisions you can make yourself (triage, order, which finding is real); do ask
before every build, deploy, restart, server change or data deletion, and before any change to a
money, code or matching result (plan rule 1.7). When he must click in a web dashboard, give the
exact button names (in French too if the dashboard is in French).

Words: the product is **Wassla**. The requirements document of 11 November 2026 is "the cahier des
charges". Never use the word "partner".

**How every reply to Ismail ends.** His standing rules:
- A short answer ends with one line: `**In short:** <the point, one sentence>`.
- After real work, end with a summary block: a table (`| What changed | What it means for you |`,
  at most 6 rows), then one bold line per item: `**Next step:**` (always), `**Heads up:**` (untested,
  risky or fragile), `**I guessed:**` (any assumption made without asking). About 15 lines at most,
  no file paths, code or command output, no sentence longer than about 20 words.
- Jargon: the technical term first, then an em dash, then plain English.
- Be honest. Never write "verified" or "working" unless it was checked.

## 2. The workflow (how we have been working)

**The coordinator only coordinates.** It writes no product code. It:
- runs **one cloud builder agent per package**, each in its own branch and pull request into `main`;
- gives each builder **exactly the model and effort the plan names** for that package. The
  coordinator never chooses an effort itself. The only change allowed is the escalation rule below;
- reads every Astra result, verifies each finding against the code (Astra's report is a claim, not
  proof), applies the triage rule (section 3), and sends the real findings back to the same builder;
- records the gate review on the pull request and merges when the merge rule holds (section 4);
- keeps the board (`docs/WASSLA_L_SERIES_PROGRESS.md`, table "Fixes after the phone tests") and
  `HANDOFF.md` section 0 current after **every** merge or Astra result, in a docs-only commit
  straight to `main`, so another account can always continue.

**Be proactive, not on autopilot.** Look for the root cause behind repeated findings, spot loops,
and fix the process (prompt, triage, builder model) instead of sending the same round again.

**Escalation rule (Ismail, 2026-11-26).** A package built on Claude Sonnet that Astra rejects again
moves to **Claude Opus at extra high**. N1 has moved: it is now on Opus extra high.

**Reviews: Astra 6.2 (OpenAI, through Codex) reviews every package at high effort.** Do not ration
it. The loop is:
1. The builder writes the review prompt to `docs/handoff/astra/<pkg>-review*.md` on its PR branch,
   with the exact head SHA, and pushes.
2. The coordinator gives Ismail the prompt file (attach it, or its path on the PR branch).
3. **Ismail runs Astra himself**, in the cloud (Codex on a second account) when the PC operator cannot (section 2b), and pastes the
   result back into the project chat.
4. The builder commits the result verbatim to `docs/handoff/astra/results/<pkg>-astra-round<N>-result.md`
   on its PR branch, and the coordinator posts it as a comment on the pull request.
5. Approve and CI green: gate and merge. Reject: triage, then the next builder round.

If Codex hits its weekly limit, tell Ismail; he holds the reset credits and uses them himself.

**Optional: the local operator.** A Claude Code session on Ismail's PC (folder `D:\Code\Shiptrip`,
Remote Control on) can run Astra with the Codex CLI logged in there:
`codex exec -m gpt-6.2-astra -s read-only -c model_reasoning_effort=high --output-last-message OUT.md - < PROMPT.md`
and does all VPS work over SSH (access details only in his uncommitted `CLAUDE.local.md`). It
writes no product code. Reach it with `ListAgents` / `SendMessage`; if it does not answer, ask
Ismail. To start one, Ismail opens a new local session in that folder and pastes:

> You are the Wassla local operator. Read CLAUDE.md, CLAUDE.local.md and docs/handoff/COORDINATOR.md.
> You take tasks only from the cloud coordinator or from me: run Astra reviews and plans with the
> Codex CLI, operate the VPS over SSH as CLAUDE.local.md describes, download test builds to my PC,
> and commit Astra results to docs/handoff/astra/results/. You write no product code. Never deploy,
> restart or change the server without my explicit OK for that step.

The SSH key needs Ismail's passphrase in a popup on his PC (12 hours). Never ask for it in chat.

## 3. Anti-loop triage rule (new, 2026-11-27)

Several packages went through four to seven Astra rounds because each round raised new edge cases,
some of them outside the package or about data that does not exist. From now on:
- **Legacy and upgrade findings are not applicable.** The app has never been live and has no users:
  rows written by older code, old app versions, URLs issued before the change, migrations of old
  data. Declare them N/A on the pull request and do not build them.
- **Out-of-scope findings go to a follow-up package note**, not into the current package. Record
  them in `HANDOFF.md` section 0.8 (follow-up packages) with the round and result file they came from.
- **Fixes go to the root cause.** When a round finds a new variant of the same problem, change the
  design that allows the family, not the single case.
- **Every Astra prompt states these three rules**, so Astra reviews only the package's scope.

## 4. Merge rule and hard rules

- Merge only when **every CI check is green** ("Schema drift" included), **Astra approves**, and the
  gate comment is on the pull request (each "Done when" line, the scope, screenshots, the second pass).
  Merge squash and delete the branch, then update the board and `HANDOFF.md` section 0.
- **Every deploy, restart, server change or app build needs Ismail's explicit OK for that step.**
  The app is built once, after every package is merged. Test builds: a `release` APK from the
  GitHub "Build Android" workflow, downloaded to his PC, then the artifact and run are deleted.
- Long runs (whole suites) go to GitHub CI from the pushed branch; run only targeted tests locally.
- Never ask for, print or log secrets. Never run `docker compose config` with the real environment,
  `down --volumes`, `FLUSHALL`, volume prunes or `do-release-upgrade`.
- If something fails or does not match the docs, stop and explain instead of improvising.

## 5. Where things are

- **Live state, every package and the next steps:** `HANDOFF.md` section 0.
- **Packages, findings and owner answers (Q1 to Q5):** `docs/WASSLA_PHONE_TEST_2_PLAN.md`.
- **Astra prompts:** `docs/handoff/astra/` on each PR branch. **Results:** `docs/handoff/astra/results/`
  (on the PR branch first, on `main` after merge) and as the latest comment on each pull request.
- **C1 plan and Ismail's answers:** `docs/handoff/astra/results/c1-plan.md`, section 3.
- **Live server:** release `5ee8cd2`. Nothing newer is deployed. Payments in TEST mode, Stripe
  Connect off, payout profiles off, push (FCM) off. Demo data on the live database, to remove before
  launch.
