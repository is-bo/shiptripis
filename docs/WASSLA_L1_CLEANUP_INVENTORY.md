# Wassla L1 cleanup inventory

Package L1A, 2026-11-11. Baseline: `feature/discovery-professional-delivery` at `d8869ad`.
Rules: `docs/WASSLA_DISCOVERY_PRO_PLAN.md` section L1A. A removal needs evidence: no route, no
importer, no caller in the mobile app, no admin console screen, no job handler. No table, column or
migration was removed. L1B adds the mobile section to this file.

How the evidence was gathered:

- **Routes.** The full URL table was dumped from the resolver before and after (`get_resolver()`
  walk, 620 rows before and 597 after). The diff is exactly the rows listed below.
- **Importers.** `git grep -w <symbol>` across the repository for every removed class, function and
  module. After L1A the only hits for removed names are dated historical reports under `docs/`.
- **Mobile.** `grep` of `mobile/lib` for every removed path. Two unused repository methods still name
  removed paths; neither has a caller (see "Left for L1B").
- **Admin console.** `grep` of `apps/admin_panel` for every removed module and model surface.
- **Jobs.** `grep` of `infra/vps/runtime.py`, `run_finance_jobs` and every management command.

## 1. Removed

### 1.1 Railway deployment (commit `19c5d52`)

Ismail decided on 2026-11-11 that Railway does not stay on this branch. The VPS (`infra/vps/`) is the
only host.

| Removed | Evidence |
| --- | --- |
| `railway.json`, `backend/gateway/railway.json`, `backend/monolith/railway.web.json`, `backend/monolith/railway.grpc.json`, `backend/services/railway.json` | Read only by Railway. No workflow, compose file or script references them. |
| `backend/railway/Dockerfile` | Built only by `railway.json`. The VPS image is `infra/vps/Dockerfile`. |
| `backend/gateway/Dockerfile` | Built only by `backend/gateway/railway.json`. Local compose runs the stock `caddy:2-alpine` image with `backend/gateway/Caddyfile` mounted. |
| `infra/vps/render_internal_caddy.py` | Rewrote the Railway Caddyfile into the VPS one at image build. Its two edits (`trusted_proxies static private_ranges`, `Referrer-Policy`) are now written directly in `infra/vps/gateway.Caddyfile`; the result was compared line by line with the old rendered output and passes `caddy validate`. |
| `backend/railway/start.py` moved to `infra/vps/launcher.py`, without its Railway-only branches: the embedded `redis-server` (`SHIPTRIP_EMBEDDED_REDIS`, `LOCAL_REDIS_URL`), the boot-time `migrate` and geography import (`apply_geography_catalogue`, `migrate_database`, `import_catalogue`) and `main()` | The VPS always called `launcher.run(migrate_database=False, import_catalogue=False)` (`infra/vps/runtime.py`) and requires a shared Redis; it runs migrations and the catalogue import through the `maintenance` service. Only Railway reached those branches. The launcher now refuses a loopback `REDIS_URL`. |
| `backend/railway/Caddyfile` moved to `infra/vps/gateway.Caddyfile` | Same routing; see the render script row. |
| `backend/services/railway-entrypoint.sh` renamed `entrypoint.sh` | Same script; the name was the only Railway part. |
| `SHIPTRIP_EMBEDDED_REDIS` (VPS guard, `stack.env.example`, `compose.yml`, `ENVIRONMENT.md`, `.env.example`) | Its only reader was the Railway embedded-Redis branch. |
| Go `config.HTTPAddr` fallback to `PORT` | `PORT` was Railway's injected variable. In the combined container it belongs to the gateway, so honouring it would collide with Caddy. Every service has its own `*_HTTP_ADDR`. |
| Admin console "Single-replica local mode" limiter label (`console_views.system_status`) | Shown only when the embedded Redis was on. |
| Railway URLs in test fixtures (`test_h8a_guards.py`, two mobile tests) | Replaced with `https://api.wassla.example`; the tests check URL handling, not the host. |

Runbooks corrected: `docs/DEPLOYMENT_RUNBOOK.md`, `docs/ROLLBACK_RUNBOOK.md`,
`docs/PUSH_NOTIFICATIONS_RUNBOOK.md`, `infra/vps/EMAIL.md`, `tools/geography/README.md`,
`backend/loadtest/README.md`, plus comments in settings, CI and the services. `ARCHITECTURE.md` was
rewritten where it was false (see section 1.8).

### 1.2 Legacy matching write path

| Removed | Evidence |
| --- | --- |
| `TravelerApplyView`, `SenderApplyView`, `CounterOfferView`, `OfferAcceptView`, `_quote_for_parcel` (`apps/matching/views.py`) | Not routed, not imported anywhere (the module docstring said so itself). |
| `RetiredLegacyMatchingWriteView` (`apps/matching/v1_views.py`) | Replaced by the tombstone module (section 1.7). |
| `TravelerApplySerializer`, `SenderApplySerializer`, `CounterOfferSerializer`, `CompatibleJourneysQuerySerializer`, `MatchEventSerializer` (`apps/matching/serializers.py`) | Used only by the removed views; `MatchEventSerializer` had no user even at the baseline. |
| `GET /api/matches/compatible-journeys` (`CompatibleJourneysV1View`) | Superseded by `find-travelers` and `quote`. Mobile `compatibleJourneys()` has no caller. `compatible_journeys_for_request` stays because find-travelers uses it. |
| `apps/core/pricing.py` | The pre-V1 DZD pricing engine. No importer outside its own test. |

### 1.3 Legacy DZD payments (`apps/payments`)

| Removed | Evidence |
| --- | --- |
| `views.py`, `serializers.py`, `providers.py`, `urls.py` and the `api/` include: `/api/payments/intents`, `intents/create`, `intents/<pk>`, `intents/<pk>/cancel`, `intents/<pk>/refund`, `/api/payments/webhook/mock` | V1 money is `apps.finance`. The mobile app has no caller (its tests already assert it never calls these). No admin console screen, no job. The mock webhook was unauthenticated. |
| `PAYMENTS_MOCK_WEBHOOK_ENABLED`, `PAYMENTS_LEGACY_MUTATIONS_ENABLED` (base, dev and prod settings, the VPS guard, `stack.env.example`, `ENVIRONMENT.md`, `.env.example`, `PROVIDER_ACTIVATION_RUNBOOK.md`) | Their only readers were the removed views and providers. The production boot guard for the live mock rail, `PAYMENTS_ALLOW_MOCK_PROVIDER`, stays. A deployed `stack.env` that still sets either name is harmless. |

### 1.4 Legacy DZD wallet (`apps/wallet`)

| Removed | Evidence |
| --- | --- |
| `views.py`, `serializers.py`, `urls.py`: `/api/wallets`, `/api/wallets/<currency>`, `.../entries`, `.../holds`, `/api/withdrawals`, `/api/withdrawals/create` | No mobile caller (asserted by its tests), no console screen, no job. V1 payouts are `apps.finance`. |
| `signals.py`, `services.py` and the `ready()` hook | Listened to legacy `PaymentIntent` saves, which nothing writes any more. |
| The Django admin "Mark selected withdrawals as sent" action | Marked money as sent without moving any. See section 1.9. |

### 1.5 Legacy match handover (`apps/verification`)

| Removed | Evidence |
| --- | --- |
| `views.py`, `serializers.py`, `services.py`, `urls.py`: `/api/matches/<id>/handover`, `.../issue`, `.../verify`, `.../code` | These are the routes that published plaintext codes to both parties and locked `HandoverCode` before `Match`. V1 handover is `apps.handover` under `/api/deals/<id>/handover`, which is what the app calls. Treated as a security fix. |

### 1.6 Legacy airport trips (`apps/trips`)

| Removed | Evidence |
| --- | --- |
| `TripListCreateView`, `TripSearchView`, `TripDetailView`, `TripCancelView`, `TripMediaUploadView`, `AirportListView` and their serializers: `/api/trips`, `/api/trips/search`, `/api/trips/<pk>`, `.../cancel`, `.../media`, `/api/airports` | Superseded by journeys. No mobile caller of the trip routes; mobile `airports()` has no caller. `AirportSerializer` stays (parcels use it). |

### 1.7 Retired routes now answer from one tombstone module

`apps/core/retired_routes.py`, mounted last under `api/`. Each answers its retired method with `410`
and a stable code, requires authentication like before, and answers other methods `405`:

| Path | Method | Code |
| --- | --- | --- |
| `matches/apply` | POST | `legacy_matching_flow_retired` |
| `matches/apply-to-trip` | POST | `legacy_matching_flow_retired` |
| `matches/<pk>/offers/counter` | POST | `legacy_matching_flow_retired` |
| `parcels/delivery` | POST | `legacy_delivery_flow_retired` |
| `parcels/quote/delivery` | GET | `legacy_dzd_quote_retired` |
| `parcels/product` | POST | `product_request_retired` |

The implementations behind them were deleted: `DeliveryCreateView`, `ProductCreateView`,
`DeliveryQuoteView`, and the serializers only they used (`_ParcelBase`, `DeliveryCreateSerializer`,
`ProductCreateSerializer`). Every other removed route answers `404`
(`apps/core/tests/test_l1a_retired_surfaces.py`).

### 1.8 Redis channels nobody publishes

`trip.created`, `trip.updated`, `trip.cancelled`, `match.created`, `handover.confirmed`,
`handover.code_issued`, removed from `apps/core/channels.py`, the Go notification dispatcher's
subscribe list and the push template table. Evidence: before L1A their only publishers were the
removed legacy views and services (`git grep` of the baseline); after L1A nothing names them. The
server renders stored inbox rows without these names, so old rows still list. The mobile app keeps
its mapping of these names for stored rows (L1B must keep it).

### 1.9 Admin and documentation

- The Django admin pages of the legacy tables (`PaymentIntent`, `PaymentEvent`, `Refund`, `Wallet`,
  `WalletEntry`, `Hold`, `Withdrawal`, `HandoverCode`) are now view-only through
  `apps/core/historical_admin.py`. With the services gone, an edit there would change history with
  no ledger entry, event or audit row.
- `ARCHITECTURE.md`: corrected the repo layout, the topology (VPS instead of K3s pods), gateway
  routes, the database boundary (no sqlc repositories exist), the connection budget, gRPC security
  (private-network bearer on the VPS), the event examples, storage buckets and upload path, the rate
  limiting that was never built, the Django and Go service tables, and the money rules (EUR, sender
  proposes first, 25% commission; the DZD product tiers were removed).
- Stale comments that pointed at removed code: `apps/matching/views.py`, `parcels/models.py`,
  `payments/models.py`, `wallet/models.py`, `finance/models.py`, `core/financial_locks.py`,
  `handover/models.py`, `handover/services.py`, `test_phase8df_lock_order.py`.

### 1.10 Removed tests (with the surface each covered)

| Removed | Count | Surface |
| --- | --- | --- |
| `apps/core/tests/test_pricing.py` | 27 | Legacy DZD pricing engine |
| `apps/payments/tests/test_payments.py` | 18 | Legacy payment API and mock webhook. `RetiredProductBoundaryTests` was ported to the new L1A test file |
| `apps/wallet/tests/test_wallet.py` | 12 | Legacy wallet API, ledger service and payment signals |
| `apps/verification/tests/test_verification.py` | 15 | Legacy match handover API and services |
| `apps/trips/tests/test_trips.py` | 20 | Legacy trip and airport API (10 were already skipped) |
| `apps/trips/tests/test_legacy_trip_retirement.py` | 2 | The old trip 410 answers, now 404 |
| `test_matching.py`: `TravelerApplyTests`, `SenderApplyTests`, `CounterAcceptTests` | 24 | Legacy apply and counter views (all 24 were already skipped) |
| `test_deployment_safety.py`: `LegacyProviderFirewallTests`, `LegacyMockWebhookFirewallTests` | 3 | Legacy provider registry and mock webhook switches |
| `test_deployment_safety.py`: `test_public_railway_entrypoints_gate_traffic_on_readiness`, `test_railway_requires_external_shared_redis`, `test_embedded_redis_is_explicit_local_compatibility_only`, and the three boot-time import tests (`..._is_guarded_...`, `..._runs_after_readiness_...`, `..._failed_import_does_not_take_the_service_down`) | 6 | Railway health checks, embedded Redis and boot-time catalogue import. The VPS equivalents are `test_the_launcher_requires_the_shared_redis`, `test_no_redis_daemon_is_started_inside_the_container`, `test_starting_the_container_never_migrates_or_imports`, the compose health check and `infra/vps/tests/integration.py` |

Rewritten because their rule changed (same intent, live endpoint or VPS file): the Railway launcher
and drain tests (now `test_the_launcher_selects_production_settings_explicitly` and
`test_the_vps_container_lets_the_launcher_drain_before_sigkill`), the payment escape-hatch boot test
(one hatch left), `test_v1_deal_requires_funding_before_chat_and_has_no_legacy_payment_or_handover_route`
(asserts 404), the compatible-journeys callers in `test_phase2_matching.py`,
`test_phase2b_contracts.py` and `test_phase2b_privacy.py` (now `quote` and `find-travelers`), the
airports measurement in `test_phase_k4_backend_api_performance.py`, the Go `HTTPAddr` test, and the
channel fixtures in five Go tests and `test_redis_bus.py` (moved to live channels).

## 2. Kept, with the reason

| Kept | Reason |
| --- | --- |
| Models, migrations and history tables of `apps.payments`, `apps.wallet`, `apps.verification`, `apps.trips.Trip`, `ProductRequest` | Rule: no table, column or migration is removed. `Journey.legacy_trip` points at `Trip`. |
| Legacy chat eligibility through `PaymentIntent` (`apps/matching/services.py::_legacy_chat_eligibility`) | Historical match threads still read it; every function in that module has a live caller. |
| `schema_version` 1 and 2 branches (matching, trips, parcels) | Rows of those versions can exist; a branch is unreachable only if production has none, which this package cannot prove from the repository. |
| `GET /api/journeys/search` and the open-requests reads | Plan: kept until L2B replaces them. |
| `backend/monolith/Dockerfile`, `backend/gateway/Caddyfile`, `backend/docker-compose.yml` | Local development stack; no Railway dependency. |
| Go `DATABASE_URL` loader | Generic; the VPS runtime refuses it explicitly. Not Railway-only. |
| `docs/SHIPTRIP_V1_SPEC.md` mentions of Railway | The owner's specification; the plan states it overrides the spec's Railway note. |
| Dated historical reports under `docs/` that mention Railway, `apps.payments` routes or the removed settings (`PHASE_*`, `V1_VPS_READINESS.md`, `V2_EMAIL_READINESS.md`, `PERFORMANCE_AUDIT.md`, `k6-notes/`, `k7-notes/`, older `IMPLEMENTATION_STATUS.md` entries) | Rule: dated historical reports are left as written. |

## 3. Needs Ismail's decision

1. **`infra/vps/MIGRATION.md`** describes moving production data from Railway to the VPS. It is the
   last Railway runbook. Keep it until the data has moved, then delete it? Kept for now.
2. **Paid but undelivered legacy matches.** If production has a legacy `Match` with a succeeded
   `PaymentIntent` and no completed handover, it can no longer complete through the API (the legacy
   handover and payment routes are gone). A one-off query decides whether any such row exists:
   `PaymentIntent.objects.filter(status="succeeded", offer__match__status__in=["accepted", "in_transit", "delivered"])`.
3. **Legacy stored inbox rows** with the six removed channel names still render in the app. Whether
   to delete them or leave them is a data question, not a code one; nothing was deleted.

One change outside the starting list that Ismail may want to confirm: the routed cancel, decline and
withdraw writes in `apps/matching/views.py` now lock `Match` and `Offer` with
`select_for_update(no_key=True)`, the canonical mode, and the module joined the lock-order gate. The
exclusion's stated reason was the unrouted legacy classes, which are gone. Results are unchanged; only
the lock strength is.
