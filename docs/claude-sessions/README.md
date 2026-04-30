# Claude Code session transcripts

Raw JSONL exports from Claude Code sessions used to build ShipTrip.

These are **not** resumable across machines (Claude Code keys session IDs to
local path hashes), but they contain the full reasoning, prompts, tool calls,
and code. A contributor's Claude instance can ingest them as context to
pick up where the previous session left off.

See `../../HANDOFF.md` for the recommended onboarding flow.

## Index

| File | Date | Size | Summary |
| --- | --- | --- | --- |
| `2026-04-28-architecture-and-mobile-ui-batch1.jsonl` | 2026-04-28 | 1.7 MB | System architecture (API gateway + Django + Go), mobile UI batch 1: onboarding, role select, shell, sender/traveler home, make request, create trip, search filter, mock data, design tokens |
| `2026-04-30-mobile-ui-batch2.jsonl` | 2026-04-30 | 2.3 MB | Mobile UI batch 2: auth (sign in/up + forgot + OAuth buttons), payment, pickup code, flight tracking, offer detail, offer-to-traveler, nav redesign (white + yellow), onboarding overflow fix, replaced ugly map with parchment route illustration |

## Reading a transcript

Each line is one message. Use `jq`:

```bash
# Human-readable conversation only (no tool calls)
jq -r 'select(.type=="user" or .type=="assistant") |
       (.message.content[]? | select(.type=="text") | .text) // empty' \
   2026-04-30-mobile-ui-batch2.jsonl | less

# Every file written by Claude in the session
jq -r '.message.content[]?
       | select(.name=="Write" or .name=="Edit")
       | .input.file_path' \
   2026-04-30-mobile-ui-batch2.jsonl | sort -u
```

On Windows without `jq`, open in VS Code and search.
