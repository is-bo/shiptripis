# Wassla: instructions for agents

The rules for every agent in this repository, whatever the tool, are in **`CLAUDE.md`**. Read it in
full before any work, then `HANDOFF.md` for where the work stands and what is next.

The rules that are never broken, repeated here in case only this file is read:

- Never deploy without the explicit approval of Ismail, the owner.
- Work goes to `main` (the working branch since 2026-11-16) through one pull request per package or
  task, merged only when every CI check is green, "Schema drift" included.
- Never skip, delete or weaken a test to get green.
- Do not build the parked scope (professional transporters, manifest dashboard, custody history,
  courier handoff) and do not leave hooks for it.
- There are no real users: no effort on legacy data or backward compatibility.
- Work in ponytail mode, always: the smallest complete change, never a shortcut in money, code, sign-in or
  staff code (`CLAUDE.md`, "Working style: ponytail").
- The server is the authority for money, codes, verification and matching.
