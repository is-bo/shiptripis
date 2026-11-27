# Builder briefs for the loop-end plan

These eleven briefs split `docs/handoff/LOOP_END_PLAN.md` (revision 2, commit `e66bb5b`) into
pieces that one builder can hold in its head. Each brief can be handed over as it is.

**Not valid yet.** A brief may be handed over only when Astra's re-check of the plan says
"approve" and Ismail has answered D1 to D9 (plan section 2). If an answer changes a brief, the
planner changes the brief first.

## Order, effort and who can run together

Every builder is Claude Opus.

| Brief | Effort | Branch | Starts when |
|---|---|---|---|
| `F1.md` | Extra high | `claude/f1-payout-availability` (#69) | The plan is approved |
| `G1-A.md` | Extra high | `claude/g1-guest-checkout-csrf` (#67) | The plan is approved |
| `N1.md` | Extra high | `claude/n1-notification-first-open` (#71) | The plan is approved |
| `P3B-A.md` | High | `claude/p3b-profile-photos-app` (#66) | The plan is approved |
| `S1-A.md` | Extra high | new, from the N1 branch | The plan is approved |
| `G1-B.md` | Extra high | the G1 branch | G1-A is pushed and green |
| `G1-C.md` | Extra high | the G1 branch | G1-B is pushed and green |
| `S1-B.md` | Extra high | the S1 branch | S1-A is pushed and green |
| `P3B-B.md` | Extra high | the P3B branch | N1 and S1 are merged, and P3B-A is green |
| `P3B-C.md` | High | the P3B branch | P3B-B is pushed and green |
| `F1b.md` | Extra high | new, from `main` | F1 is merged |

- **Five builders can run at once at the start:** F1, G1-A, N1, P3B-A and S1-A. They touch
  different files.
- **One builder per branch at a time.** The next brief on a branch starts from the previous one's
  pushed, green head and its status file.
- **Merge order:** F1 and G1 in either order (the second merges `main` in, regenerates the schema
  contract, and the whole finance suite runs again), then C1. N1, then S1, then P3B. F1b after F1,
  before payouts are switched on.

## How the lead hands a brief over

1. Start a Claude Opus builder at the effort in the table.
2. Tell it to read `CLAUDE.md`, then its brief, and give it Ismail's answers to D1 to D9.
3. Until this branch is on `main`, the builder reads the brief and the plan with
   `git fetch origin claude/project-thread-mb20d4` and
   `git show origin/claude/project-thread-mb20d4:docs/handoff/builders/<brief>`.
4. When a builder stops and asks, bring the question to the planner. Do not let the builder patch
   around it.
5. When the last brief on a branch is green, check its evidence table, write the Astra prompt as
   plan section 3.6 says, and give it to Ismail at once. One prompt per pull request.

## What still needs Ismail at the time

- The device kill test of S1 and the device check of P3B need a test build.
- Every merge follows the usual rule: all CI checks green and Astra's approval.
- Switching payouts on waits for F1b and for his OK when it runs.
