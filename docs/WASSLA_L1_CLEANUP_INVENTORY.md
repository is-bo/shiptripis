# Wassla L1 cleanup inventory

Package L1A, 2026-11-11. Baseline: `feature/discovery-professional-delivery` at `d8869ad`.
Rules: `docs/WASSLA_DISCOVERY_PRO_PLAN.md` section L1A. A removal needs evidence: no route, no
importer, no caller in the mobile app, no admin console screen, no job handler. No table, column or
migration was removed. Section 4 is the mobile section added by L1B.

How the evidence was gathered:

- **Routes.** The full URL table was dumped from the resolver before and after (`get_resolver()`
  walk, 620 rows before and 597 after). The diff is exactly the rows listed below.
- **Importers.** `git grep -w <symbol>` across the repository for every removed class, function and
  module. After L1A the only hits for removed names are dated historical reports under `docs/`.
- **Mobile.** `grep` of `mobile/lib` for every removed path. Two unused repository methods still named
  removed paths; neither had a caller. L1B removed them (section 4).
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
| `infra/vps/MIGRATION.md` (the Railway-to-VPS data migration runbook) | Ismail, 2026-11-11: the app was never in production and has no real users, so there is no data to move. |
| Railway URLs in test fixtures (`test_h8a_guards.py`, two mobile tests) | Replaced with `https://api.wassla.example`; the tests check URL handling, not the host. |

Runbooks corrected: `docs/DEPLOYMENT_RUNBOOK.md`, `docs/ROLLBACK_RUNBOOK.md`,
`docs/PUSH_NOTIFICATIONS_RUNBOOK.md`, `infra/vps/EMAIL.md`, `tools/geography/README.md`,
`backend/loadtest/README.md`, plus comments in settings, CI and the services. `ARCHITECTURE.md` was
rewritten where it was false (see section 1.8).

### 1.2 Legacy matching write path

| Removed | Evidence |
| --- | --- |
| `TravelerApplyView`, `SenderApplyView`, `CounterOfferView`, `OfferAcceptView`, `_quote_for_parcel` (`apps/matching/views.py`) | Not routed, not imported anywhere (the module docstring said so itself). |
| `RetiredLegacyMatchingWriteView` (`apps/matching/v1_views.py`) | The 410 answer for the retired matching paths; see section 1.7. |
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

### 1.7 The six 410 routes are gone too

The plan asked for one tombstone module answering `410` for `matches/apply`, `matches/apply-to-trip`,
`matches/<pk>/offers/counter`, `parcels/delivery` (POST), `parcels/quote/delivery` (GET) and
`parcels/product`. It was built and then removed in the same pull request: Ismail confirmed the app
was never released, so no stale client calls these paths, and the orchestrator asked for them to
answer `404` like every other removed route. Their implementations were deleted:
`DeliveryCreateView`, `ProductCreateView`, `DeliveryQuoteView`, `RetiredLegacyMatchingWriteView`, and
the serializers only they used (`_ParcelBase`, `DeliveryCreateSerializer`,
`ProductCreateSerializer`). The ProductRequest refusal inside the live V1 offer services
(`product_request_retired` on counter and accept, and in chat eligibility) is a data guard, not a
route, and stays. Every removed route is asserted `404` in
`apps/core/tests/test_l1a_retired_surfaces.py`.

### 1.8 Redis channels nobody publishes

`trip.created`, `trip.updated`, `trip.cancelled`, `match.created`, `handover.confirmed`,
`handover.code_issued`, removed from `apps/core/channels.py`, the Go notification dispatcher's
subscribe list and the push template table. Evidence: before L1A their only publishers were the
removed legacy views and services (`git grep` of the baseline); after L1A nothing names them. There
are no stored inbox rows to render (section 3), so L1B can drop the app's mapping of these names too.

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
| `apps/parcels/tests/test_parcels.py`: `DeliveryCreateTests`, `ProductCreateTests`, `DeliveryQuoteTests` | 5 | The legacy delivery create, product create and DZD quote 410 answers, now 404 |
| `test_v1_matching.py::test_legacy_matching_write_routes_are_gone` | 1 | The `matches/apply*` 410 answers, now 404 |
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
| Legacy chat eligibility through `PaymentIntent` (`apps/matching/services.py::_legacy_chat_eligibility`) | Chat eligibility for legacy match rows; every function in that module has a live caller. See section 3. |
| `schema_version` 1 and 2 branches (matching, trips, parcels, finance) | No real rows need them (section 3), but they are tied to database check constraints and to matching, finance and pricing reads; removing them needs a narrowing migration. See section 3. |
| `GET /api/journeys/search` and the open-requests reads | Plan: kept until L2B replaces them. |
| `backend/monolith/Dockerfile`, `backend/gateway/Caddyfile`, `backend/docker-compose.yml` | Local development stack; no Railway dependency. |
| Go `DATABASE_URL` loader | Generic; the VPS runtime refuses it explicitly. Not Railway-only. |
| `docs/SHIPTRIP_V1_SPEC.md` mentions of Railway | The owner's specification; the plan states it overrides the spec's Railway note. |
| Dated historical reports under `docs/` that mention Railway, `apps.payments` routes or the removed settings (`PHASE_*`, `V1_VPS_READINESS.md`, `V2_EMAIL_READINESS.md`, `PERFORMANCE_AUDIT.md`, `k6-notes/`, `k7-notes/`, older `IMPLEMENTATION_STATUS.md` entries) | Rule: dated historical reports are left as written. |

## 3. Ismail's decisions

Answered on 2026-11-11: the app has never been in production and has no real users, so there is no
legacy data to protect. That settles the three questions this inventory first asked:

1. **`infra/vps/MIGRATION.md`** (the Railway-to-VPS data move) is deleted: there is no production
   data to move. Two dated reports (`V1_VPS_READINESS.md`, an older `IMPLEMENTATION_STATUS.md`
   entry) still link to it and are left as written.
2. **Paid but undelivered legacy matches** cannot exist, so no production check is needed.
3. **Stored inbox rows with the six removed channel names** do not exist, so the app does not need
   to keep rendering them (see "Left for L1B" in the handoff notes).

The same answer also removes the data reason behind three "kept" rows above: the legacy tables, the
legacy chat-eligibility branch, and the `schema_version` 1 and 2 branches. They stay in this package
anyway. Dropping a table or narrowing the `schema_version` check constraints is a migration that
removes or narrows something, which plan rule 1.5.5 forbids for the whole series, and the branches sit
inside matching, finance and pricing reads that L1A must not change. They are listed for the
orchestrator as a candidate follow-up that needs Ismail to lift rule 1.5.5.

One change outside the starting list that Ismail may want to confirm: the routed cancel, decline and
withdraw writes in `apps/matching/views.py` now lock `Match` and `Offer` with
`select_for_update(no_key=True)`, the canonical mode, and the module joined the lock-order gate. The
exclusion's stated reason was the unrouted legacy classes, which are gone. Results are unchanged; only
the lock strength is.

## 4. Mobile (L1B)

Package L1B, 2026-11-11. No behaviour or visual change. Evidence: an identifier-count sweep of
`mobile/lib` and `mobile/test` (a public member whose name occurs once in `lib` and nowhere in `test`
is dead), a key-by-key search of every ARB key in `lib` and `test`, and `flutter analyze --fatal-infos`
after each step. Framework overrides were excluded by hand.

### 4.1 Removed

- **Repository methods:** `LocationRepository.airports`, `MatchingRepository.compatibleJourneys`,
  `RequestRepository.uploadPhoto`, `MatchingRepository.cancelMatch`, `NotificationRepository.unreadActiveCount`,
  `BoostRepository.retiredHistory`, and the `Airport` model (the routes behind the first two answer 404
  since L1A). Kept on purpose until L2B: `JourneyRepository.searchPage` and `openFeedPage`.
- **Client handling of removed Redis channels:** `trip.created`, `trip.updated`, `trip.cancelled`,
  `match.created`, `handover.confirmed`, `handover.code_issued` in the live-event allow-list and (all but
  `handover.code_issued`) in `NotificationChannel`, its destination map and the inbox icon map.
  The `trip.` branch of the live-event resource map is gone with them.
- **Retired refusal codes:** `legacy_matching_flow_retired`, `legacy_delivery_flow_retired`,
  `legacy_dzd_quote_retired`, `legacy_trip_flow_retired`, `legacy_trip_search_retired`,
  `legacy_payment_retired`. Kept: `product_request_retired`, `legacy_contract_not_supported`,
  `airport_filter_retired`.
- **Unused navigation and model members:** `goChat`, `goProfile`, `openNotifications`,
  `openDzdProfileSetup`; getters on the `Journey`, `Deal`, `Payment`, `Handover`, boost, `Dispute`,
  `Account`, `Rating`, `CanonicalPlace`, `DeliveryRequest` and discovery models that nothing read;
  `Money.formatExact`, `ApiClient.deleteVoid`, `positiveNumber`, `bottomBelowFooter`, and the chat
  controller's write-only `_backgroundError`.
- **Files:** `lib/features/auth/wilayas.dart` (imported nowhere).
- **ARB keys:** 202 keys that no Dart file references, from `app_en.arb`, `app_ar.arb` and
  `app_fr.arb` (the three stay in step), and the generated localisations were regenerated.

### 4.2 Kept

- `PushRepository.unregisterDevice` has no caller, but sign-out should unregister the push
  installation; reported to the orchestrator as a gap, not deleted.
- Assets: every file under `assets/branding` and `assets/fonts` is referenced, so none was removed.
