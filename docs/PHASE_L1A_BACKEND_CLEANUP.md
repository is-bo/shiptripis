# Phase L1A — backend cleanup, including Railway removal

Date: 2026-11-11. Package L1A of `docs/WASSLA_DISCOVERY_PRO_PLAN.md`. Base:
`feature/discovery-professional-delivery` at `d8869ad`. No deployment, nothing merged to `main`.

The evidence for every removal, what was kept and why, and the open questions are in
`docs/WASSLA_L1_CLEANUP_INVENTORY.md`. This file records what was built, the contract that results,
and the test counts.

## What changed

1. **Railway is gone; the VPS path is the only one.** The process launcher moved to
   `infra/vps/launcher.py` and the internal gateway config to `infra/vps/gateway.Caddyfile` (the build
   step that rewrote it is folded in). The Railway config files, Dockerfiles, the embedded Redis, the
   boot-time migrate and catalogue import, Go's `PORT` fallback and `SHIPTRIP_EMBEDDED_REDIS` were
   removed. Runbooks describe the VPS.
2. **Legacy API surfaces removed:** the DZD payments API and its unauthenticated mock webhook, the
   DZD wallet and withdrawal API with its payment signals, the match-scoped handover API (the one that
   published plaintext codes to both parties), the airport trip API, `compatible-journeys`, the
   unrouted traveler-first matching views, the DZD pricing engine, and the serializers only they used.
   Their models, admin and migrations stay.
3. **One tombstone module.** `apps/core/retired_routes.py` answers `410` with a stable code for the
   six paths the plan names. Every other removed route answers `404`.
4. **Two settings removed** whose only readers were removed code: `PAYMENTS_MOCK_WEBHOOK_ENABLED` and
   `PAYMENTS_LEGACY_MUTATIONS_ENABLED`, in Django, the VPS guard and the env examples.
5. **Six Redis channels removed** that nothing publishes (`trip.*`, `match.created`,
   `handover.confirmed`, `handover.code_issued`), in the three places the plan names.
6. **Legacy history admins are view-only** (`apps/core/historical_admin.py`), and the withdrawal
   "mark sent" action is gone.
7. **Matching closing writes use the canonical lock mode.** Cancel, decline and withdraw in
   `apps/matching/views.py` lock with `select_for_update(no_key=True)`, and the module is in the
   lock-order gate.
8. **`ARCHITECTURE.md` corrected** where it was false.

## Contract

- Removed routes return `404` to every caller: `/api/payments/intents*`, `/api/payments/webhook/mock`,
  `/api/wallets*`, `/api/withdrawals*`, `/api/matches/<id>/handover*`, `/api/trips*`,
  `/api/airports`, `/api/matches/compatible-journeys`.
- Tombstones (authenticated; other methods `405`; anonymous `401`):

  | Path | Method | `code` |
  | --- | --- | --- |
  | `/api/matches/apply` | POST | `legacy_matching_flow_retired` |
  | `/api/matches/apply-to-trip` | POST | `legacy_matching_flow_retired` |
  | `/api/matches/<pk>/offers/counter` | POST | `legacy_matching_flow_retired` |
  | `/api/parcels/delivery` | POST | `legacy_delivery_flow_retired` |
  | `/api/parcels/quote/delivery` | GET | `legacy_dzd_quote_retired` |
  | `/api/parcels/product` | POST | `product_request_retired` (new code on this path; it previously had none) |

- No live route, payload, price, lifecycle or payout result changed. No migration was added or
  deleted; `makemigrations --check` reports no changes.
- The VPS launcher refuses a loopback `REDIS_URL`; Go services no longer read `PORT`.

## Tests

| Suite | Before | After |
| --- | --- | --- |
| Django (PostgreSQL) | 2,529 passed, 34 skipped (2,563 collected) | 2,447 passed, 0 skipped (2,447 collected) |
| Go (`go test -race ./...`, top-level tests) | 199 passed | 199 passed |
| VPS unit (`infra/vps/tests`) | 29 OK | 29 OK |
| Static web and edge routing check | passed | passed |
| `caddy validate` (both gateway Caddyfiles, CI's 2.8 image) | valid | valid |
| Flutter | not run here (no SDK in this environment) | CI runs it; L1A changed only two Dart test fixtures (a Railway URL string) |
| VPS container integration (`infra/vps/tests/integration.py`) | nine groups passed (V3 baseline report) | all nine groups passed, against images built from this branch |

Django: 132 test IDs removed (34 of them were already skipped, which is every skip the baseline had) and 16 added, so 2,563 − 132 + 16 =
2,447 collected. The removed tests and the surface each covered are listed in the inventory,
section 1.10. Added:

- `apps/core/tests/test_l1a_retired_surfaces.py` (8): each tombstone's 410 and code, method and
  authentication; every removed route is 404 to signed-in and anonymous callers; a historical
  ProductRequest match cannot re-enter payment, handover, chat, counter or accept (ported); the
  legacy admins are view-only and still render.
- `test_deployment_safety.py` (7): three new VPS checks (the launcher requires the shared Redis,
  starts no Redis daemon, and never migrates or imports at container start), and four renamed or
  moved from Railway wording (the launcher selects production settings, compose gives it time to
  drain, the catalogue reaches the image, the mock payment rail stops the boot).
- `test_v1_matching.py` (1, renamed): a V1 deal has no legacy payment or handover route (404).

The 132 removed IDs are 127 removed tests plus those 5 renames.

Go: one test rewritten (`TestHTTPAddrIgnoresTheGatewayPort` replaces `TestHTTPAddrUsesRailwayPort`);
channel fixtures in five tests moved to live channels.

## Known limits

- Flutter was not run locally; CI covers it.
- The mobile app still has two unused repository methods that name removed routes
  (`compatibleJourneys`, `airports`) and still maps the six removed channel names for stored inbox
  rows. Both belong to L1B.
