# ShipTrip — Claude Handoff

This repo is being co-built with Claude Code. If you're a contributor's Claude
instance picking up the work, **read this file first**, then ingest the session
transcripts in `docs/claude-sessions/`.

## You are not the only Claude

The original Claude session was on a Windows machine at `C:\Users\islam\shiptrip`.
Sessions can't be resumed across machines (the JSONL is keyed to the local path
hash), but the transcripts contain the full reasoning, decisions, and code.

## What to do at session start

1. Read this file.
2. Read `ARCHITECTURE.md` for the system design.
3. Read `.claude/MEMORY.md` and the files it points to in `.claude/memory/`.
   These are project memories — they persist across sessions and capture
   non-obvious decisions.
4. Skim the most recent session in `docs/claude-sessions/`. The latest one
   has the freshest context. Older ones are useful for understanding *why*
   things are the way they are.
5. Check `git log --oneline -20` to see what was actually committed
   (sessions sometimes plan things that didn't get merged).

## Session transcripts

Sorted newest first. They are raw Claude Code JSONL exports — not
human-readable prose. Search them with `jq` or just `grep` for keywords.

| File | Date | Summary |
| --- | --- | --- |
| `docs/claude-sessions/2026-04-30-mobile-ui-batch2.jsonl` | 2026-04-30 | Auth screens, payment, pickup code, flight tracking, offer detail, offer-to-traveler, nav redesign (white + yellow accent), fixed onboarding overflow, removed map illustration |
| `docs/claude-sessions/2026-04-28-architecture-and-mobile-ui-batch1.jsonl` | 2026-04-28 | Architecture: API gateway + Django monolith + Go services (chat/notifications/KYC/media gateway). Mobile UI: onboarding, role select, app shell, sender/traveler home, make request, create trip, search filter, mock data, design system |

## How to read a JSONL session

Each line is a JSON object representing one message (user, assistant, or tool
result). Useful one-liners (PowerShell or bash with `jq`):

```bash
# Just the user prompts and Claude's text replies (no tool noise)
jq -r 'select(.type=="user" or .type=="assistant") | .message.content[0].text // empty' \
    docs/claude-sessions/2026-04-30-mobile-ui-batch2.jsonl

# Find every file Claude wrote
jq -r 'select(.message.content[0].input.file_path) | .message.content[0].input.file_path' \
    docs/claude-sessions/2026-04-30-mobile-ui-batch2.jsonl
```

If you don't have `jq`, just open the file in an editor and search for
relevant keywords.

## Project state at last handoff (2026-04-30)

**Mobile (Flutter):**
- Routes wired: `/`, `/auth/sign-{in,up}`, `/auth/forgot`, `/role`, `/app`,
  `/sender/{new,search,offer}`, `/offer`, `/payment/:id`, `/code/:id`,
  `/tracking/:id`, `/traveler/new`
- All screens implemented with mock data — no backend wiring yet
- `flutter analyze` warning-clean, release APK builds (~50 MB)
- Latest APK: `~/.claude/cache/shiptrip-builds/shiptrip-v2-2026-04-30.apk`
  (NOT in repo — too large)

**Backend:**
- Architecture documented in `ARCHITECTURE.md`
- API Gateway → Django monolith (CRUD) + Go services (realtime + KYC + media)
- Django never stores bytes; media gateway uploads to Supabase Storage with
  per-bucket separation: `kyc-docs`, `parcel-photos`, `product-photos`,
  `tickets`. KYC service calls media gateway server-to-server.
- Code skeletons exist; not yet wired up.

## Conventions to keep

- **Riverpod 3** — use `Notifier` + `NotifierProvider`, not `StateNotifier`
- **country_flags v4** — wrap `CountryFlag.fromCountryCode()` in a
  `SizedBox(width, height)`; the package no longer accepts size params
- **Theme** — Mediterranean parchment + emerald + terracotta + gold,
  with `#FBBC04` (sun yellow) as the signature accent for nav and key CTAs
- **Bottom nav** — white pill, yellow accent only on the selected icon
  (no grey, no dark indicator pill)
- **Forms** — use `AppInput` for all text fields, `NumberStepper` instead of
  sliders, `InlineCalendar` for dates, `showAirportPicker()` for airports
- **No `Spacer` inside scrollable columns** — wrap with
  `SingleChildScrollView` + `IntrinsicHeight` to avoid overflow on
  short screens (this bit us once on onboarding)

## Pending work

The 2026-04-30 session ended with all UI screens shipped and building. Next
likely steps:
- Wire backend (Django) endpoints + Go services
- Replace mock data layer (`mobile/lib/shared/mock/`) with real API client
- Implement actual OAuth (Google + Apple) — UI only currently
- Real flight tracking via OpenSky API instead of fake animation
- Stripe / CIB payment integration
- KYC flow end-to-end

Check `.claude/memory/` for any updated priorities since this was written.
