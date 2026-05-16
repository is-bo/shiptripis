# SESSION_HANDOFF.md — brief for the next Claude session

**Created:** 2026-05-16. Read this **after** `CLAUDE.md` and `ARCHITECTURE.md`, **before** doing any work. Delete or rewrite this file at the end of the next session.

---

## 1. Who you are

You are **Claude A** on Islam's Windows machine at `C:\Users\islam\shiptrip`.
Your scope is **`mobile/` + `backend/monolith/` + mobile-facing contracts**.
Claude B (the contributor's Claude) owns `backend/services/` (Go). See `CLAUDE.md §1` for the strict split.

## 2. First five minutes of the session

Run these in order — non-negotiable:

| # | Action | Why |
|---|---|---|
| 1 | `cd C:\Users\islam\shiptrip && git pull` | Claude B pushes between sessions |
| 2 | Read `CLAUDE.md` **fully**, especially §0a if it still exists | Open blockers between contributors live there |
| 3 | `git log --oneline -10` | See what actually shipped vs what was just planned |
| 4 | Read `.claude/memory/MEMORY.md` + linked files | Personal preferences + workflow rules |
| 5 | `docker compose ps` (from WSL: `wsl -d Ubuntu; cd /mnt/c/Users/islam/shiptrip/backend`) | Confirm containers are up before any backend test |

## 3. Where we left off (2026-05-16)

### Just committed and pushed (`e9861fa` + `126dfeb`)

- **Mobile mock cleanup:**
  - New `mobile/lib/features/traveler/find_parcels_screen.dart` — real `/api/parcels/open` search + `/api/matches/apply` flow
  - Rewrote `follow_package_screen.dart` to poll `matchDetailProvider` every 12s and drive status circles from real `MatchStatus`
  - Fixed `_IncomingMatchCard` bug in `traveler_home.dart` (was reading nonexistent `match.offers` list — now uses `match.latestOffer` + `match.parcel`)
  - Deleted: `pickup_code_screen.dart`, `offer_to_traveler_screen.dart`, `offer_detail_screen.dart`, `shared/mock/mock_data.dart`
  - `/code/:id` route now redirects to `/handover/issue/:id?kind=pickup`
  - Added `parcels_repository.searchOpen` + `matching_repository.apply`

- **CLAUDE.md §0a added** documenting two Go-side blockers found in Claude B's commit `4b4a5e2`:
  1. **Port mismatch:** Caddyfile expects `notification-service:8082` / `kyc-service:8083`; Go binaries default to `:8081` / `:8082`
  2. **WS path mismatch:** Caddy proxies `/ws/notifications` unrewritten; Go mounts handler at `/ws` → 404
  - Claude B should fix both. Once fixed, §0a should be deleted.

### Reviewed but not modified

Claude B's `4b4a5e2 added notification and kyc`:
- `cmd/notification`, `cmd/kyc`, `internal/notification/*`, `internal/kyc/*`, `pkg/config`, `contracts/grpc/kyc.proto`
- Dispatcher subscribes to **only `offer.accepted`** — `offer.created` (sender's "traveler applied" notification) and ~14 other channels Django publishes are silent
- KYC uses `NoopRecorder` (loud failure) until gRPC codegen + Django `apps/kyc/grpc_server.py` land
- FCM fallback, mTLS, mobile WS client — all deferred per §0 of `CLAUDE.md`

## 4. Outstanding mobile bugs / TODOs (not blocking, but on the list)

- `payment_screen.dart` passes `match.id` as `offerId` to `createIntent` — pre-existing bug, needs the real `Offer.id`
- Match cards still show `Traveler #${match.travelerId}` etc. — no real user names/avatars wired
- No CTA from match detail screen surfacing `/handover/issue/:id` when status=`accepted` or `inTransit`
- No mobile WS client yet — backend has nothing to fan out to

## 5. Hard rules from CLAUDE.md (don't re-derive these)

- **Scope:** never touch `backend/services/` — that's Claude B's
- **JWT claims:** `user_id` (int) + `role` + `typ` + `jti`; never put int into `sub`
- **Redis publish:** always inside `transaction.on_commit(...)`, never bare in atomic block
- **Pricing:** Django `apps/core/pricing.py` is the source of truth; mobile mirrors, doesn't compute
- **Migrations:** always reversible; `task contract:sync-db` after every Django migration that touches a Go-read table; commit migration + `contracts/sql/schema.sql` in the same PR
- **Riverpod 3** only (no `StateNotifier`); `country_flags` v4 needs `SizedBox` wrap; no `Spacer` in scrollable columns
- **Bottom nav:** white pill, sun-yellow `#FBBC04` accent on selected icon only

## 6. Connection pool budget (`CLAUDE.md §3`)

Postgres `max_connections=100`: Django 20 + Go services 45 + reserved 10 = 75 used. Headroom 25. Don't scale Go pods without updating `pgxpool.MaxConns`.

## 7. Local dev (Windows + WSL)

```bash
wsl -d Ubuntu
cd /mnt/c/Users/islam/shiptrip/backend
docker compose up -d
docker compose run --rm django python manage.py migrate
curl http://localhost:8000/healthz
```

Ports: `5432` Postgres, `6380` Redis (host; container still `6379`), `9000/9001` MinIO, `8000` Django, `8080` Caddy.

For APK testing: build with `--dart-define=API_BASE_URL=<ngrok-url>`. Last ngrok used: `https://ayanna-nonpopulous-mariano.ngrok-free.dev` (likely expired — restart `ngrok http 8080`).

## 8. Commit + push routine

User wants this every session:
1. `git pull` at session start
2. Re-read `CLAUDE.md` for contributor notes
3. `git commit` + `git push` for every meaningful change so Claude B sees it

Don't batch days of work into one commit. Don't push without committing the CLAUDE.md and `.claude/memory/` updates along with the code change they justify.

## 9. Memory files worth knowing

In `C:\Users\islam\.claude\projects\C--Users-islam\memory\`:
- `project_shiptrip.md` — P2P delivery app for Algeria; Flutter + Django + Go + Postgres
- `project_shiptrip_scope_split.md` — A/B work split
- `project_shiptrip_jwt_claims.md` — JWT shape
- `workflow_session_start.md` — pull + re-read CLAUDE.md at start (added this session)

## 10. When in doubt

Read code, don't guess. Surface trade-offs out loud. Don't add features the user didn't ask for. Use `Skill` tool for installed skills before responding.
