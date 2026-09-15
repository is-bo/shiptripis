# J1 TEST release report — 2026-09-15

J1 is deployed to TEST with green CI and financial reconciliation. Full acceptance
remains incomplete because real-device push, chat send/receipt and the reported
phone-specific regressions have not been demonstrated after installation.

| # | Requested result | Evidence / outcome |
|---|---|---|
| 1 | Starting SHA | `f68731f4203a05fb5e64a7bdad3aa0a80b530bae` |
| 2 | Branch | `codex/j1-lifecycle-payout-realtime` |
| 3 | Files changed | 52 files through release main; grouped file list below. Completion adds this report and updates phase/status documentation only. |
| 4 | Schema/migrations | Additive `chat.0003_chatmessage_client_message_id_and_more`, `finance.0025_alter_scheduledjob_kind`; exported SQL; schema gate green. sqlc explicitly skips empty query directories; Go contracts verified. |
| 5 | Payout root cause | Initial EUR/Both lacked explicit legal country; stale revisions and nested `method.mobile` decoding corrected. Blanket DZD error not reproduced. |
| 6 | EUR preference | Deployed 200 and matching GET readback for six synthetic Both users; all changes rolled back. |
| 7 | DZD preference | Same six deployed 200/readback checks pass. |
| 8 | Both preference | Same six deployed 200/readback checks pass. |
| 9 | Stripe TEST setup | Existing synthetic TEST account: public HTTP onboarding 201, HTTPS Stripe-hosted URL, expiry, no-store. URL never persisted/logged or followed. |
| 10 | Stripe refresh | Public HTTP 200, nested method/Stripe state, no-store. Account correctly remains `setup_required`; onboarding completion not fabricated. |
| 11 | DZD setup/state | Eight deployed GETs 200; public authenticated HTTP 200. Input, evidence/create/replacement/review covered by automated suites; no new bank evidence submitted in deployment checks. |
| 12 | Journey root cause | Browse relied on stored active status even after all usable travel windows passed. |
| 13 | Expiry semantics | Derived SQL: no usable inventory/no active funded dependency => expired; travel evidence => in_progress, then completed after final arrival. Explicit cancellation remains cancelled. |
| 14 | Matching exclusion | Three elapsed stored-active deployed Journeys project completed and are not discoverable. Automated natural-expiry/matching tests pass. |
| 15 | Multi-leg | Focused test proves a later valid leg remains discoverable; broad CI passes. |
| 16 | Funded Deals | Preserved by expiry; allocated/frozen records are not deleted. Regression passes. |
| 17 | Dispute root cause | Mobile inferred action from coarse state. |
| 18 | Dispute action | Server party/window/prior-dispute rules drive action; deadline and existing-dispute tests pass. Deployed completed detail checks omit expired action. |
| 19 | Rating root cause | Old question heading persisted after submission; deadline state needed refresh. |
| 20 | Rating result | Server available/submitted_waiting/revealed/expired/unavailable states; blind semantics preserved. Widget deadline timer lifecycle corrected; affected tests and full Flutter CI pass. |
| 21 | Home root cause | Not established on device. Existing query already requests server `activity=active`; deployed data never reproduced completed-in-active. |
| 22 | Activity result | Deployed 8 Deals: 1 active, 7 completed; zero delivered rows in Active; public active list count 1. |
| 23 | Route root cause | Seven historical Deals lack snapshots. The active Deal has its snapshot; device rendering cause remains unconfirmed. |
| 24 | Route result | All 8 deployed detail requests 200: 1 safe ordered frozen route, 7 null historical routes. Outsider projection denied; no fabricated current-Journey fallback. |
| 25 | Notification root causes | Inbox depended on post-commit callback/transport; zero active devices independently prevents push receipt. |
| 26 | FCM/push | FCM project/credential alignment established; zero active and two inactive devices. Actual device registration/foreground/background receipt remains blocked. |
| 27 | Active/read/resolved | Derived owner-scoped resolution independent of read state. Deployed checks across eight users pass. Durable notification jobs commit transactionally. |
| 28 | Badge | Deployed active count equals legacy unread badge key and excludes resolved unread rows; seven such rows across the two owner accounts. |
| 29 | History | Bucket counts match SQL; rollback-only funded payment notice enters History while unread, with no event dispatch. |
| 30 | Chat root cause | Missing sender target and client retry identity corrected; original phone symptom not reproduced end to end. |
| 31 | Immediate sender echo | UUID optimistic reconciliation + sender target/ACK contracts pass automated tests. Deployed authenticated chat WS handshake 101. |
| 32 | Recipient realtime | Go race/Redis integration passes. No eligible funded synthetic pair exists on TEST, so deployed persisted send/recipient receipt is NOT claimed. No real-user message sent. |
| 33 | Idempotency | Same UUID/body => same row/200; first write 201; conflicting body 409; focused and CI checks pass. |
| 34 | Reconnect | Existing persisted after-ID catch-up retained; independent HTTP cursor prevents ACK skipping missed inbound rows. Automated coverage passes; deployed reconnect/message proof pending. |
| 35 | Auth/privacy | Owner/party boundaries, no provider refs/bank data leakage, route allowlist, rollback/retry isolation reviewed and tested. No browser or subagents used. |
| 36 | Astra fast tests | J1 10 backend regressions, targeted H6A, optimistic chat/mobile/deadline checks; corrected live-event module 9/9 in 4.66s; Ruff/static/targeted Go pass. |
| 37 | Gemini prompts | Exact-SHA handoffs for `11e07d6` and `ee86382`; readonly verification/no fixes/deploys. Original full reused-DB instruction corrected to a fresh dedicated database in round 2. |
| 38 | Gemini results | R1: 1,115 Django pass/774 fail/61 errors/34 skip from depleted database; Flutter timer failure. R2 fresh: 1,944 pass/2 obsolete event assertions/34 skip; affected Flutter 57 pass. Corrections verified locally; CI closes remaining prerequisites by explicit user authorization. |
| 39 | CI | [34898155599](https://github.com/is-bo/shiptripis/actions/runs/34898155599): all six jobs SUCCESS at `9c1f7b7`. Prior [34894741388](https://github.com/is-bo/shiptripis/actions/runs/34894741388) had 1,946 Django pass/34 skip and all runtime gates green; only pg_dump wrappers failed, then corrected without SQL changes. No completion polling. |
| 40 | Implementation SHA | Initial `11e07d699776a0b657524cbf16d30234b6f90d5a`; final CI-reviewed `9c1f7b7df5e037ad1aecdac08cc1ede3d74f60b5`. |
| 41 | Main SHA | Deployed main `5ea3a4c04f563a4503b4dd96a5a81fafbd8acbd4` adds only release-checkpoint docs after CI. Final completion docs are a later main commit; its SHA is returned in the final task response. |
| 42 | Cleanup | Fast-forward main; atomic remote main update and phase-branch deletion; local branch deleted; local main/origin/main equal. |
| 43 | Deployment | `40a8a568-7ac1-4994-b923-f36cc7ae67a6` SUCCESS; `v1.0.0-rc.31+5ea3a4c`. Existing Railway environment named production, application money intent TEST. Uploaded clean exact Git archive. |
| 44 | healthz | 200, correct release. |
| 45 | readyz | 200, database/migrations/rate-limit cache all ok, correct release. |
| 46 | Migrations/workers | Zero pending migrations. Gunicorn, Caddy, Redis, finance, reservation, Django KYC gRPC, Go chat/notification/KYC/email processes all present. |
| 47 | Deployed payouts | Preference rollback/readback, no-store GETs, genuine TEST hosted link and refresh described above. No payout/checkout/transfer executed. |
| 48 | Deployed Journeys | Three elapsed rows excluded; no historical rows rewritten. |
| 49 | Deployed activity/route | All 8 participant detail reads pass; seven completed excluded; one snapshot/seven null routes. |
| 50 | Deployed notifications | Public inbox/History/badge HTTP 200; owner-scoped counts match derived SQL; unread-resolved check passes. Notification WS handshake 101. |
| 51 | Deployed chat | Authenticated WS handshake 101. Safe eligible synthetic send fixture absent; full send/echo/recipient/reconnect check blocked. |
| 52 | H5 integrity | Exactly one read-only TEST snapshot at `2026-09-15T00:15:45.520133+00:00`, integrity `ok`, no warnings. |
| 53 | Reconciliation | All six comparison differences and row mismatches zero, unbalanced transaction count zero, global ledger net zero. Provider cash reconciliation unavailable without provider balance observation; not claimed. One existing TEST payout needs attention. |
| 54 | Stripe TEST | Confirmed configured TEST secret and expected Connect mode; no secret output. |
| 55 | Chargily TEST | Confirmed TEST key and TEST API origin. |
| 56 | DZD disabled | `PAYOUT_DZD_EXECUTION_ENABLED=false` before/after deployment. |
| 57 | No LIVE | No LIVE operation, real-money operation, launch cutover or J2 implementation. Email remains disabled. Only release ID changed in runtime configuration. |
| 58 | Remaining findings | BLOCKER: install/device payout/Home/route/chat regressions and push registration/receipt acceptance; eligible safe synthetic chat fixture absent. No unresolved CI runtime/schema failure. MINOR: larger mobile presentation/History pagination polish remains J3. |

Android [build 34894794431](https://github.com/is-bo/shiptripis/actions/runs/34894794431)
passed analysis/tests, ARM64 profile/AOT payload checks, signature verification
and upload. [Download artifact 10368810330](https://github.com/is-bo/shiptripis/actions/runs/34894794431/artifacts/10368810330).
It contains `shiptrip-j1-test-cc55084-cc55084-profile-arm64.apk` plus SHA256SUMS.
Archive SHA256: `e52e6cc07c5376af933ee41e1ffb07be877d265c3775d17264bb7bc11228147c`.
No mobile code changed after this APK's SHA; it targets the current TEST origin.

Source verification compared 21 deployed files against the exact uploaded Git
archive. Git on this Windows host exported CRLF, so comparing raw LF repository
blobs initially failed; every archive byte hash matches deployed bytes. The H5
result was already saved and was not rerun for that local comparison correction.
Initial local public readiness calls intermittently timed out; the deployed-host
public HTTPS request returned 200 with all readiness checks ok.


## Files through the deployed main checkpoint

- `backend/contracts/sql/schema.sql`
- `backend/monolith/apps/chat/migrations/0003_chatmessage_client_message_id_and_more.py`
- `backend/monolith/apps/chat/models.py`
- `backend/monolith/apps/chat/serializers.py`
- `backend/monolith/apps/chat/tests/test_chat.py`
- `backend/monolith/apps/chat/views.py`
- `backend/monolith/apps/core/redis_bus.py`
- `backend/monolith/apps/core/tests/test_phase8ff4_events.py`
- `backend/monolith/apps/deals/route.py`
- `backend/monolith/apps/deals/serializers.py`
- `backend/monolith/apps/deals/tests/test_phase_i1a_journey_timing.py`
- `backend/monolith/apps/deals/tests/test_phase_j1.py`
- `backend/monolith/apps/disputes/services.py`
- `backend/monolith/apps/finance/jobs.py`
- `backend/monolith/apps/finance/migrations/0025_alter_scheduledjob_kind.py`
- `backend/monolith/apps/finance/models.py`
- `backend/monolith/apps/finance/payout_mobile.py`
- `backend/monolith/apps/finance/payout_profile_api.py`
- `backend/monolith/apps/finance/tests/test_phase8fh6a_mobile.py`
- `backend/monolith/apps/matching/compatibility.py`
- `backend/monolith/apps/matching/discovery.py`
- `backend/monolith/apps/matching/v1_services.py`
- `backend/monolith/apps/notifications/models.py`
- `backend/monolith/apps/notifications/resolution.py`
- `backend/monolith/apps/notifications/serializers.py`
- `backend/monolith/apps/notifications/transport.py`
- `backend/monolith/apps/notifications/views.py`
- `backend/monolith/apps/ratings/services.py`
- `backend/monolith/apps/trips/lifecycle.py`
- `backend/monolith/apps/trips/serializers.py`
- `backend/monolith/apps/trips/views.py`
- `backend/services/internal/chat/dispatcher.go`
- `backend/services/internal/chat/dispatcher_test.go`
- `docs/IMPLEMENTATION_STATUS.md`
- `docs/PHASE_J1_LIFECYCLE_PAYOUT_REALTIME.md`
- `mobile/lib/app/app_state.dart`
- `mobile/lib/data/repositories.dart`
- `mobile/lib/domain/chat.dart`
- `mobile/lib/domain/deal.dart`
- `mobile/lib/features/chat/chat_thread_controller.dart`
- `mobile/lib/features/deals/deal_screen.dart`
- `mobile/lib/features/notifications/notifications_screen.dart`
- `mobile/lib/features/profile/dzd_setup_screen.dart`
- `mobile/lib/features/profile/payout_methods_screen.dart`
- `mobile/lib/l10n/app_ar.arb`
- `mobile/lib/l10n/app_en.arb`
- `mobile/lib/l10n/app_fr.arb`
- `mobile/lib/l10n/app_localizations.dart`
- `mobile/lib/l10n/app_localizations_ar.dart`
- `mobile/lib/l10n/app_localizations_en.dart`
- `mobile/lib/l10n/app_localizations_fr.dart`
- `mobile/test/phase_j1_contract_test.dart`

**J1 FAIL — full acceptance incomplete; TEST backend release checks pass.**

**Ready for J2 pricing / deposit / guest payer / Boost backend? NO.**
