You are an independent reviewer of a **plan**, not of code. This review is read-only: do not write, commit or push anything, and do not comment on GitHub. You may read files and run read-only git commands.

## What happened, and what this is
Four pull requests in this repository (is-bo/shiptripis) went through 25 review rounds with you and were all rejected again today:

| Package | Pull request | Rounds | Head you rejected last | Branch |
|---|---|---|---|---|
| P3B, profile photos in the app | #66 | 8 | `7727b1926c8a40a725148cc383d9678f6be59475` | `claude/p3b-profile-photos-app` |
| G1, guest checkout | #67 | 7 | `57684cb7fe0ec002ca69684d058c8f998bba7448` | `claude/g1-guest-checkout-csrf` |
| F1, payout availability | #69 | 5 | `bd74c3a8048ad0e0e0abb2be94e72883ce8ac6c5` | `claude/f1-payout-availability` |
| N1, notification permission at first open | #71 | 5 | `3e7fc1780878b3e017a9dd9f921a90774346142b` | `claude/n1-notification-first-open` |

The owner stopped all builders. A planner then grouped every finding into root-cause families and wrote one plan: for each open family one invariant, one mechanism that enforces it, and a test matrix; plus a review contract and a stop rule. **You review that plan before any code is written.** Builders will implement it strictly. A later finding inside a family will count as a gap in this plan, so say now what is wrong with it.

- Run `git fetch origin` first.
- **The plan is `docs/handoff/LOOP_END_PLAN.md` at commit `b295f3ab62dca7682f45dc15eabe61cde7385dba`**, on branch `claude/project-thread-mb20d4`. Read it with `git show b295f3a:docs/handoff/LOOP_END_PLAN.md`. The commit after it on that branch only adds this prompt.
- Your earlier reports are in `docs/handoff/astra/results/` on `main` (G1 and P3B), on the F1 branch (F1 rounds 1 to 5) and on the N1 branch (N1 rounds 1 to 4). Your reports for G1 round 7, P3B round 8 and N1 round 5 are not committed yet; **Appendix A of the plan restates every finding of those three and of F1 round 5.** If Appendix A misstates one of your findings, say so.
- Rules are in `CLAUDE.md`. Money, codes, matching and staff authority are "strongest model" areas there.
- You may read the code at the four heads above to test a mechanism against reality. Do not review the code line by line: it is about to change.

## Three review rules from the owner (treat as correct)
These apply to this review and to every later one.

1. **No old data.** The app has never been live. There are no users, no stored provider data, and no rows, URLs, events, jobs or app versions from before a package that a deploy would inherit. Do not report a problem whose only trigger is such data. Do report anything reachable from an empty database through the new code.
2. **Out of scope goes to a follow-up, not into the package.** A problem that exists on `main` the same way without the package, or sits in code the package neither changes nor depends on, is listed separately. It does not block.
3. **Root causes, not single cases.** A new variant of a known problem is reported as the design rule that allows the whole family, with a change to that rule, not as a patch for one case.

## What the plan claims (so you can attack it)
- **A review contract** (section 3): a fault model that says what a finding may assume (3.1), a severity table with four blocker classes and an "accepted risk" class kept in a written register (3.2), scope per package as a list of families (3.3), and a stop rule (3.4): two passes on this plan, then one full review and one re-check per package.
- **Nine shared design rules** (section 4), and one small phone helper, `ReadOrder`.
- **A new package, S1 "session core"** (section 5): one stored record for the sign-in, one transition at a time, no direct change from one member to another, one function that removes credentials, the whole app tree rebuilt when a member session ends, an API client bound to one member session, and a durable list of ended sign-ins that is sent until the server answers. It takes over the family "an action started as member A runs as member B" from P3B and "every way the phone leaves a sign-in also ends it on the server" from N1.
- **G1** (section 6): final means terminal, as a check constraint; one predicate for "not settled"; the gate refuses while a payment is unverified; a staff resolution is taken on a fresh provider read and then fences automatic paths; the sweep defines the settle obligation; job completions are fenced by a claim id; the close intent and its job wake share a transaction; one gate function serves the server and the screens.
- **F1** (section 7): the session advisory lock is deleted; while an account creation is outstanding, writes to the euro preference are refused under the method row lock; eligibility is read on the locked row; one snapshot of facts per response.
- **N1** (section 8): the sign-in row alone decides whether a registration or a sign-out applies; a save of a user row writes only the fields that writer changed; the phone side moves to S1.
- **P3B** (section 9): one version per photo slot moved by every visible change, and every member write carries the version it saw; an explicit transition table in the photo controller; `ReadOrder`; the account-switch code is removed in favour of S1.
- **Order** (section 10): G1 and F1 in parallel, then C1; S1, then N1, then P3B.

## What to do
Work through these six parts. Give concrete sequences, in the terms of the plan's fault model (3.1). No style opinions.

1. **The contract (section 3).**
   - Is the fault model usable? Name any kind of failure you reported as a Blocker in the 25 rounds that 3.1 or 3.2 would now downgrade, and say for each whether you accept the downgrade. If you do not, give the wording change that keeps it a Blocker without reopening everything.
   - Is each line of the severity table decidable for a finding you might write? Point to any line you could not apply.
   - Can you work inside the stop rule (3.4): one full review and one re-check per package? Say what a code-review prompt must contain for your first pass to be complete.
   - **Pre-register your criteria.** List the checks you will run on each package's code review and what will make you reject. Later rounds will be held to this list.
2. **Each open family.** For S-1 to S-6, G-D, G-E, G-F, F-C, F-F, F-G, N-B, N-D, P-E, P-F and P-G:
   - (a) Does the invariant, if it held, exclude every finding listed for that family, in Appendix A and in your earlier reports? If not, name the finding and why.
   - (b) Does the mechanism enforce the invariant in one place, and does it hold inside the fault model? If not, give the exact interleaving, crash point or provider answer that breaks it.
   - (c) Which rows are missing from the test matrix?
   - (d) Does the mechanism open a new family? Say what you would attack next, so it can be planned now.
3. **Closed families.** The plan marks twelve families closed because your latest report on each package raised nothing in them (G-A, G-B, G-C, F-A, F-B, F-D, F-E, N-A, N-C, P-A, P-B, P-C). Disagree only with a concrete failure reachable at the head listed above.
4. **Scope and structure.**
   - Is any finding wrongly moved out of scope or into the accepted-risk register (section 11)? Check each register entry against the blocker classes.
   - Is extracting S1 sound? Name anything in P3B or N1 that S1 as specified would not cover.
   - Is the merge order safe? Name any intermediate state of `main` that would be wrong.
5. **A missing family.** Is there a root cause across your 25 reports that the plan does not name?
6. **The decisions in section 2.** D4 and D5 change a money rule and a payout rule. Say whether each is safe as worded.

Limits, so this review does not start a new loop:
- Do not propose an extra mechanism unless you show that a family cannot be closed without it. Prefer removing a mechanism or tightening an invariant.
- Entries marked **[Guess]** in the plan are known unknowns. Challenge one only if being wrong about it would break an invariant, and say which.
- Report variants of one cause as one item.

## Output format
- One opening sentence.
- **Contract:** your answers to part 1, then your pre-registered criteria as a numbered list.
- **Families:** a table: Family | Verdict (Sound / Sound with changes / Unsound) | Counterexample or missing rows | Required change. One row per open family.
- **Closed families:** only the ones you dispute, with the concrete failure.
- **Scope, structure and order:** a short list.
- **Missing families:** a list, or "none".
- **Decisions D4 and D5:** safe, or the wording change.
- **Required changes, ranked:** the changes the plan must make before building starts, most important first. Mark each "must" or "should".
- What you could not check.
- A final line: "Plan verdict: approve" or "Plan verdict: revise". Use "revise" only for an Unsound family, a missing family with a blocker-class consequence, or a contract line you cannot work with.
