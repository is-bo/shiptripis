You are an independent reviewer of a **plan**, not of code. This is your **second and last pass** on this plan. It is read-only: do not write, commit or push anything, and do not comment on GitHub. You may read files and run read-only git commands.

## What happened, and what this is
You reviewed revision 1 of a plan to end the review loop on four pull requests of this repository (is-bo/shiptripis) and answered "Plan verdict: revise", with seven ranked required changes. The planner revised the plan once. **You now re-check only what changed.** Under the plan's stop rule there is no third pass: whatever you still object to goes to the owner, Ismail, as a decision. So say exactly what remains open and how much it matters.

- Run `git fetch origin` first. Everything below is on branch `claude/project-thread-mb20d4`.
- **Revision 2 is `docs/handoff/LOOP_END_PLAN.md` at commit `e66bb5b58f9a1f2190b2764bb4dab966ee787b9f`.** Read it with `git show e66bb5b:docs/handoff/LOOP_END_PLAN.md`.
- Revision 1 was commit `b295f3ab62dca7682f45dc15eabe61cde7385dba`. The change is `git diff b295f3a e66bb5b -- docs/handoff/LOOP_END_PLAN.md`. Most of the file changed, so read revision 2 whole and use the diff only to confirm what moved.
- **Your first review** is `docs/handoff/astra/results/loop-end-plan-astra-result.md` at the tip of that branch, as Ismail pasted it.
- **Section 14 of the plan** maps each of your seven required changes to the place where the plan now makes it, and names the two points the planner did not take as you wrote them.
- The builder briefs are in `docs/handoff/builders/` at the tip of the branch. They restate the plan for eleven builders. You do not review them. If you open one and it contradicts the plan, say so in one line.
- The four rejected code heads are unchanged, for testing a mechanism against reality: P3B `7727b1926c8a40a725148cc383d9678f6be59475`, G1 `57684cb7fe0ec002ca69684d058c8f998bba7448`, F1 `bd74c3a8048ad0e0e0abb2be94e72883ce8ac6c5`, N1 `3e7fc1780878b3e017a9dd9f921a90774346142b`. Do not review that code line by line: it is about to change.

## Three review rules from the owner (treat as correct)
These apply to this review and to every later one.

1. **No old data.** The app has never been live. There are no users, no stored provider data, and no rows, URLs, events, jobs or app versions from before a package that a deploy would inherit. Do not report a problem whose only trigger is such data. Do report anything reachable from an empty database through the new code.
2. **Out of scope goes to a follow-up, not into the package.** A problem that exists on `main` the same way without the package, or sits in code the package neither changes nor depends on, is listed separately. It does not block.
3. **Root causes, not single cases.** A new variant of a known problem is reported as the design rule that allows the whole family, with a change to that rule, not as a patch for one case.

## What revision 2 changed, against your first review
| Your first verdict | Item | Where revision 2 answers it |
|---|---|---|
| Contract: one fault undefined | Fault model | 3.1: ordinary participants, four kinds of fault, the recovery assumption, the bounds |
| Contract: three undecidable lines | Severity | 3.2: seven ordered questions; M, A, C and L reworded with your additions; C has its time boundary; rule 2 puts a failure that a planned mechanism introduces in scope |
| Contract: stop on a Should-fix; limits of "switched off" | Stop rule | 3.4 |
| Contract: what a first prompt must contain | Prompt contents | 3.6. Your pre-registered criteria are Appendix B |
| Unsound | S-1 | 5.3 S-1 (on disk before acknowledged; only the platform's confirmation counts; one engine), 5.5, 5.6 item 3, 5.7 |
| Unsound | S-3 | 5.3 S-3 (an unreadable record is never overwritten; permanent loss defined; every end names its sign-in), AR-3, AR-4 |
| Unsound | S-5 | 5.2 (the sign-out contract), 5.3 S-5 (no eviction; removal only on 205 or `sign_out_proof_invalid`), 8.2, 10.1 (N1 merges before S1) |
| Unsound | G-D | 6.3 G-D1 to G-D6, 6.5, decision D4 |
| Unsound | F-C | 7.3 F-C1 to F-C5, 7.5, 7.7 (new package F1b), decisions D5 and D9 |
| Unsound | N-D | 8.2 N-D (named writers, named fields, forms that carry what staff saw; no model override), 8.3 |
| Unsound | P-E | 9.2 P-E (a revision that outlives the photo; required on every member write), 9.4 |
| Sound with changes | S-2, S-4, S-6 | 5.3, 5.5, and `ReadOrder` in section 4 |
| Sound with changes | G-E, G-F | 6.3 G-E1 to G-E3, G-F1 and G-F2, 6.5 |
| Sound with changes | F-F, F-G | 7.3, 7.5 |
| Sound with changes | N-B | 8.2 N-B, 8.3 |
| Sound with changes | P-F, P-G | 9.2 (the transition table; one store), 9.4 |
| Missing family | Authority and privacy after work leaves the process | Rule R10 in section 4; new family N-F in 8.2; sockets and the notification tray in S-4; decision D8 |
| Register | AR-1 to AR-7 of revision 1 | Section 11: two entries kept (the old AR-2 and AR-5), three new, five removed with the reason for each |
| Scope and order | S1's server prerequisite; G1 and F1; `ReadOrder`; the parser defect; the device check; Appendix A | 10.1, 10.5, G-D2, 9.4, Appendix A |

## What to do
Work through these five parts. Give concrete sequences in the terms of the plan's fault model (3.1). No style opinions.

1. **Your seven required changes.** For each: met, partly met or not met. Where it is not fully met, give the exact sequence that still breaks and the smallest change of wording or mechanism that closes it.
2. **Each family you did not call Sound.** For the seven you judged Unsound and the ten you judged Sound with changes: does the revised invariant exclude your counterexample, does the revised mechanism enforce it in one place inside the revised fault model, and are your missing matrix rows present? Then the new family N-F and the new package F1b, judged the same way.
3. **The contract.** Can you now apply every line of 3.1, 3.2 and 3.4 to a finding you might write? Name any line you still cannot apply. Confirm that Appendix B is your list, or correct it.
4. **The register and the decisions.** Check each entry of section 11 against the blocker classes of 3.2, and the removed entries against the mechanism that is said to close them. Say whether D4 and D5 are now safe as worded in section 2 and as built in 6.3 and 7.3. Say whether D8 and D9 state their consequence correctly.
5. **The two points not taken as written** (end of section 14): N1 merges whole before S1, instead of a split server contract landing with S1; and a payment that appears after staff closed the item has one way out, `returned`, with no staff action that credits the order. Accept each, or show the sequence that makes it unsafe.

Limits, so that this pass ends the planning:
- Stay inside the revisions. Do not reopen a part you accepted in your first review, a closed family, or an unchanged sentence. If you find a blocker-class problem in an unchanged part, list it apart under "New, outside the revisions", with its sequence, and say why your first review did not raise it.
- Do not propose an extra mechanism unless you show that a family cannot be closed without it. Prefer tightening an invariant or removing a mechanism.
- Entries marked **[Guess]** are known unknowns with a named check or a named fallback. Challenge one only if being wrong about it would break an invariant even with that fallback, and say which.
- Report variants of one cause as one item.

## Output format
- One opening sentence.
- **Required changes:** a table: # | Met / Partly met / Not met | What is still missing, as a sequence | Smallest change.
- **Families:** a table: Family | First verdict | Verdict now (Sound / Sound with changes / Unsound) | Counterexample or missing rows | Smallest change. One row per family of part 2, including N-F and F1b.
- **Contract:** the lines you still cannot apply, or "usable".
- **Register and decisions:** one line per register entry and per decision D4, D5, D8, D9.
- **Not taken as written:** accept or object, for each of the two.
- **New, outside the revisions:** a list, or "none".
- **For the owner:** everything that remains open, each as one plain item: what could go wrong for a user or for money, whether a phone test would meet it, and the options you see. This list is what Ismail decides from.
- What you could not check.
- A final line, one of three:
  - "Plan verdict: approve". Builders can start.
  - "Plan verdict: approve with the listed changes". Builders can start once the planner has applied the changes you listed. State each change precisely enough to apply without judgment, because you will not see the plan again.
  - "Plan verdict: revise". Use it only if a family is still Unsound, a missing family has a blocker-class consequence, or a contract line is unusable. It goes to the owner, not to a third pass.
