You are an independent second-pass reviewer. This review is read-only: do not write, commit or push code, and do not comment on GitHub. You may read files and run read-only git commands.

Review pull request #70, "N2: the bell names the ticket decision", in this repository (is-bo/shiptripis), at head `0ff0b17de3b947d83812526b3e773f0c3e947fb6`. Use a three-dot diff against `origin/main`, and run `git fetch origin` first if the commit is missing.

## Sources
- The Flutter app is under `mobile/lib/`.
- The rules are in `CLAUDE.md`, especially "Mobile rules" and "Every user-facing string exists in English, French and Arabic (Modern Standard Arabic)". The brand is written "Wassla" in Latin script.
- The package is section 4 "N2" of `docs/WASSLA_PHONE_TEST_2_PLAN.md`, and the finding is section 1.5.
- The write-up is `docs/PHASE_N2_TICKET_DECISION_BELL.md`.
- The screenshots are in `docs/screenshots/n2/`.

## What N2 claims
- A `leg_proof.status_changed` bell row now says what was decided, for flight and ferry:
  - approved;
  - needs attention (rejected);
  - a new ticket is needed.
- It reads the existing payload fields: `mode`, then `outcome`, falling back to `status`. A new-upload request is stored as rejected and is told apart only by `outcome`.
- A drive, a missing field or an unknown value keeps the old "Verification update" label.
- The identity-check row (`kyc.status_changed`) is unchanged, and tapping a ticket row still opens the journey.
- The wording matches the server push copy in `backend/monolith/apps/notifications/push.py`.
- No server change.

## What to hunt for (concrete failures only)
1. **Contract.** Check that the payload keys and values the app reads are exactly what the server publishes. Look at the staff ticket review in `backend/monolith/apps/admin_panel/services.py` around the leg-proof decision and at the `apps/notifications` push matrix. Cover every outcome the server can emit. Can a real approval or new-upload event fall into the generic label, or be mislabelled?
2. **Privacy.** Can a staff reason, a document id or other private data reach the row or its semantics?
3. **Copy.** Check the EN/FR/MSA correctness and consistency with the push copy, whether the Arabic is Modern Standard Arabic, and the brand spelling.
4. **Layout.** Long French or Arabic text in the row at 320–360 px, large text, and RTL.
5. **Tests.** Do they assert each case, the fallbacks and navigation? Was anything weakened?

## Output format
- One opening sentence.
- A table: Severity (Blocker / Should-fix / Nit) | File and line | Concrete failure | Suggested fix.
- What you checked and found sound, and what you could not check.
- Final line: "Overall verdict: approve" or "Overall verdict: reject".

Report only real, reachable problems. No style opinions.
