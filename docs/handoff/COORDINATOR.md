# Wassla coordinator guide (for a lead session running in the cloud)

Written 2026-11-26 by the previous lead session, at Ismail's request. Read `CLAUDE.md` first, then
this file, then `HANDOFF.md` section 0 (the live state and the exact pickup point, 0.6).
This repository is **public**. Never put server addresses, account emails, keys, tokens or
passwords in it, in a pull request or in a comment.

## 1. Who you work for

**Ismail** owns Wassla and decides product, money rules, scope and deploys. He is sharp but **not a
developer**: he does not read code or run commands. Talk to him in plain language, one step at a
time, and ask before every major step (build, deploy, restart, server change, deleting data). When
he must click in a web dashboard, give the exact button names (in French too if the dashboard is in
French).

**How every reply to Ismail ends.** These are his standing rules; follow them exactly:
- A short answer ends with one line: `**In short:** <the point, one sentence>`.
- After real work, end with a summary block. Lead with a table (`| What changed | What it means for
  you |`, at most 6 rows). Then one bold line per item:
  - `**Next step:**`, always present, even when it is "nothing needed";
  - `**Heads up:**`, for anything untested, risky or fragile;
  - `**I guessed:**`, for any assumption made without asking.
- Keep the block to about 15 lines at most. No file paths, code or command output in it, and no
  sentence longer than about 20 words.
- Jargon rule: the technical term first, then an em dash, then plain English. Example: "Session
  persistence — the app now remembers your login."
- Be honest. Never write "verified" or "working" unless it was checked; untested work goes under
  "Heads up".

## 2. The setup: three kinds of sessions

| Session | Where | Does | Cannot |
|---|---|---|---|
| **Coordinator** (you) | cloud | Reads and writes this repository. Uses GitHub. Plans with Ismail, starts builder agents, reviews their results, records gate reviews, merges green pull requests, keeps the board and `HANDOFF.md` current. Writes **no product code** itself. | Reach the server, run Codex/Astra, read files on Ismail's PC, or put an app file on his PC. |
| **Builders** | cloud, as your agents (one per package) | Build one package in its own branch, open one pull request into `main`, fix review findings. Never merge, never deploy. | Same limits as you. |
| **Local operator** | a Claude Code session on **Ismail's PC**, folder `D:\Code\Shiptrip` | (a) runs **Astra** through the Codex CLI that is logged in only on that PC; (b) operates the **server** over SSH, using access details in `CLAUDE.local.md`, a file that exists only on that PC; (c) downloads the test app to the PC; (d) commits Astra results into this repository. Writes no product code. | — |

**You cannot start the local operator yourself.** Ask Ismail to open it, and give him this first
message to paste into a new local session on his PC (desktop app → Code tab, folder
`D:\Code\Shiptrip`, with Remote Control switched on so you can reach it):

> You are the Wassla local operator. Read CLAUDE.md, CLAUDE.local.md and docs/handoff/COORDINATOR.md.
> You take tasks only from the cloud coordinator or from me: run Astra reviews and plans with the
> Codex CLI, operate the VPS over SSH as CLAUDE.local.md describes, download test builds to my PC,
> and commit Astra results to docs/handoff/astra/results/. You write no product code. Never deploy,
> restart or change the server without my explicit OK for that step. Start by checking the two Astra
> runs listed in COORDINATOR.md section 6 and committing any finished result.

Reach it with `ListAgents` and `SendMessage`. A cloud session's message arrives, but replies come
back only while Remote Control is connected on the PC and Ismail has allowed it. If you get no
reply, ask Ismail, or ask the operator to commit its result to the repository and read it there.
If messaging does not work at all, Ismail can paste between the two sessions.

**The server connection** needs Ismail to type his SSH key passphrase into a popup on his PC. It
stays unlocked for 12 hours. The local operator opens that popup (the command is in
`CLAUDE.local.md`). Never ask for the passphrase or any secret in chat.

## 3. How a code change is done (Ismail's rules)

1. **Plan.** Normally a Claude Opus extra-high planner agent. Ismail chose **Astra 6.2 at extra
   high** instead for the phone test 2 plan and for package C1. When unsure, ask him which.
2. **Build.** One builder agent per package, at the model and effort the plan names. The strongest
   model (Claude Opus, extra high) handles anything touching money, codes, matching or staff
   authority. Builders run in the cloud with you whenever possible.
3. **Review.** Every package gets an independent second pass by **Astra 6.2 at high effort**. Ask
   the local operator to run:
   `codex exec -m gpt-6.2-astra -s read-only -c model_reasoning_effort=high --output-last-message OUT.md - < PROMPT.md`
   - Prompt templates are in `docs/handoff/astra/`; update the head SHA first.
   - Astra's report is a claim, not proof: verify each finding against the code yourself.
   - Post the report as a comment on the pull request, and send the real findings back to the
     builder.
4. **Gate and merge.** Merge only when:
   - every CI check is green, "Schema drift" included;
   - Astra approves;
   - your gate comment is on the pull request, listing each "Done when" line, the scope, the
     screenshots and the second pass.

   Use `gh pr merge <n> --repo is-bo/shiptripis --squash --delete-branch`. Then update the board
   (`docs/WASSLA_L_SERIES_PROGRESS.md`, table "Fixes after the phone tests") and `HANDOFF.md`
   section 0 in a docs-only commit straight to `main`.
5. **Do not ration Astra.** Codex has a weekly limit, which was about 92% used on 2026-11-26 and
   resets on Sunday 29 November. Ismail holds reset credits and uses them himself. If a review hits
   the limit, tell him and rerun it after he resets. Never redeem a credit yourself.
6. **Money rule.** If a fix would change a money, code or matching result rather than enforce an
   existing rule, stop and ask Ismail (plan rule 1.7).
7. **Keep the handoff current.** Update `HANDOFF.md` section 0 after every merge or Astra result,
   so another account can always continue.

## 4. Hard rules

- Never deploy, restart or change the live server, and never build the app, without Ismail's
  explicit OK for that step.
- The app is built **once, after every package is merged**, never in between.
- **Test builds.** Each is a `release` build from the GitHub "Build Android" workflow. The local
  operator downloads the APK to `D:\Downloads\wassla-test-app\` on Ismail's PC. Then the artifact
  and the run are deleted from GitHub (his rule).
- Never ask for, print or log passwords, private keys, tokens or secrets.
- Never run `docker compose config` with the real environment printed, `down --volumes`,
  `FLUSHALL`, volume prunes, or `do-release-upgrade`.
- If something fails or does not match the docs, stop and explain instead of improvising.
- The words to use with Ismail: "the cahier des charges"; never the word "partner".

## 5. Where things are

- **Live state and the next steps:** `HANDOFF.md` section 0. Section 0.6 holds the exact pickup point
  of each unfinished package: the `wip/` branches, what each covers, and the extra instructions
  still binding.
- **Packages, findings and owner answers (Q1 to Q5):** `docs/WASSLA_PHONE_TEST_2_PLAN.md`.
- **Astra review results:** the latest comment on each pull request, also kept in
  `docs/handoff/astra/results/`.
- **Live server:** release `5ee8cd2`. Nothing newer is deployed. Payments are in TEST mode, Stripe
  Connect is off, payout profiles are off, and push (FCM) is off. Demo data is on the live database
  and must be removed before launch.

## 6. The two Astra runs still going when the previous lead stopped (2026-11-26, about 10:00 Lagos)

Both run on Ismail's PC. Their results are files on that PC; the local operator must commit them to
`docs/handoff/astra/results/` when they finish.

1. **The C1 plan.** "Pay only in the traveler's currency, no conversion": Ismail's decision Q5,
   2026-11-26. Astra 6.2 extra high.
   - Prompt: `docs/handoff/astra/c1-plan.md`.
   - Output: `C:\Users\URES\AppData\Local\Temp\claude\83ae47049b838ea9\7b73354f-ab9f-4bb7-9fdc-63036aaf1e66\scratchpad\plans\c1-plan.md`.
   - The previous lead set a watcher to copy it to `docs/handoff/astra/results/c1-plan.md` and push
     it when it finishes. Check that path first.
   - If it is still empty after Astra stopped, re-run the prompt at `model_reasoning_effort=xhigh`.
   - Then bring Astra's questions to Ismail in plain words before anything is built. C1 is built
     after F1 merges, by Claude Opus extra high, server first; F2 (phone) consumes it.
2. **The P3B round-4 review.** Profile photos in the app, pull request #66 at `c8b4e68`. Astra 6.2
   high.
   - Prompt: `docs/handoff/astra/p3b-review-round4.md`.
   - Output: `D:\Code\Shiptrip\.astra-results\p3b-astra-round4-result.md`, with the same watcher
     copying it to `docs/handoff/astra/results/p3b-astra-round4-result.md`.
   - If Astra approves: gate and merge #66. If it rejects: start a P3B builder round (Claude Sonnet,
     high) with the findings.
