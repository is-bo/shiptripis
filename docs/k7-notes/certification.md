# K7 package C: final end-to-end, mobile and resilience certification

Plan sections 15.10, 15.11, 15.12 and 19. Base SHA `f77ae0e`. Nothing was run
against Railway TEST or LIVE, and no production code changed. Two tests were
added: a backend profile/budget test and a mobile slow-network test.

Evidence labels used below:

* **measured**: taken in this package on this workstation.
* **verified by test**: an automated test that asserts the behaviour and was
  run in this package.
* **cited**: taken from an earlier K-series record and not re-run here.
* **pending**: needs Railway TEST, a real device, or the Redis cutover.

## 1. Representative flows (15.10)

### Method

`backend/monolith/apps/core/tests/test_phase_k7_certification_profile.py`
builds one deterministic PostgreSQL world containing:

* the K4 canonical marketplace: a funded V1 Deal with chat, 10
  notifications, 4 more funded threads, an open compatible request and a
  dispute;
* the K3 manual-DZD Finance world: a released payout, a reviewed DZD
  profile, KYC and a Super Admin operator.

It reads every flow through the endpoint the Flutter app or the Admin console
actually calls. The method is K4's: one warm read, then the latency median of
six reads. Queries and DB time come from `CaptureQueriesContext` on the last
read, and bytes are the rendered body.

Run it with `SHIPTRIP_K7_PROFILE=1` to print the JSON profile. It also enforces
query ceilings (the K3/K4 ceiling wherever one exists) and K4's payload
guards.

Caveats:

* The embedded PostgreSQL reports DB time in about 15.6 ms ticks, so
  "DB ms" is coarse.
* API clients use `force_authenticate`, as K4 did. JWT decoding and the user
  lookup are therefore excluded, and `/api/me` shows 0 queries.
* Latency is in-process with no network. Under the Railway private network,
  add roughly 0.5-1 ms per query.

`GET /api/journeys/search` and `GET /api/parcels/open` are **not** app flows:
no Flutter screen calls them (their repository methods have no callers). They
are therefore excluded from this benchmark.

### Results (measured, one run; a second run agreed within about 10 %)

| Flow | Endpoint | ms | Queries | DB ms | Bytes | vs baseline |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Public landing | static `/`, `/en/` (Caddy `file_server`, no Django/DB) | n/a | 0 | 0 | 29,043 (7,230 gz) | Caddy gzip + `max-age=300`; K4 confirmed edge compression on TEST |
| Public legal | static `/terms`, `/privacy` | n/a | 0 | 0 | 7,402 / 6,968 (2,497 / 2,421 gz) | static |
| Auth login | `POST /api/auth/sign-in` | 49.4 | 3 | 0 | 823 | none; time is the Argon2 hash (by design) |
| Auth restore | `POST /api/auth/refresh` (rotate + blacklist) | 3.9 | 7 | 16 | 465 | none |
| Auth profile | `GET /api/me` | 1.2 | 0* | 0 | 313 | none |
| Sender Home | `GET /api/deals?scope=current` | 22.5 | 4 | 15 | 22,317 | K5 surface, ceiling 8 |
| Sender Home (K4-identical) | `GET /api/deals` | 17.3 | **4** | 0 | 22,317 | K4: 13.8 ms / **3** q / 21,643 B. **+1 query, +3.1 % bytes** from K5 `attention`. Within the K4 ceiling (8) and exactly at the V1 matching list budget (4). Not a regression, but no headroom left under the ≤ 4 budget. |
| Sender Home / all screens | `GET /api/notifications/unread-count` | 40.5 | 3 | 15 | 44 | K4: 35.2 ms / 3 q, unchanged |
| Requests | `GET /api/parcels` | 25.8 | 6 | 16 | 9,048 | K4: 24.0 / 6 / 9,116, unchanged |
| Request detail | `GET /api/parcels/<id>` | 21.2 | 5 | 0 | 1,511 | K4: 19.0 / 5 / 1,517, unchanged |
| Find Travelers | `GET /api/matches/find-travelers?parcel_id=` | 52.2 | 9 | 16 | 11,440 | K4: 43.6 / 9 / 11,489, unchanged |
| Sender Offers | `GET /api/matches?role=sender` | **84.1** | 3 | 62 | **47,941** | no baseline. **Observation:** about 9.6 KB per match row across 5 rows (compatibility snapshot plus two nested offers with economics). This is the slowest and heaviest app read, and the app reads every page of it. |
| Offer chain | `GET /api/matches/<id>/offers` | 6.2 | 2 | 0 | 3,505 | none |
| Sender Deal | `GET /api/deals/<id>` | 23.5 | 9 | 15 | 8,526 | K4: 21.0 / 9 / 8,349, unchanged |
| Deal history | `GET /api/deals?scope=history&page_size=20` | 5.9 | 1 | 0 | 52 | K5 lazy page (empty in this world) |
| Payment status | `GET /api/deals/<id>/payment` | 9.8 | 4 | 0 | 1,581 | none |
| Payment order | `GET /api/payments/orders/<ref>` | 7.8 | 3 | 0 | 1,224 | none |
| Traveler Home | `GET /api/deals?scope=current` | 21.9 | 4 | 15 | 22,318 | as sender |
| Traveler Home | `GET /api/matches/compatible-requests?journey_id=` | 32.5 | 10 | 31 | 5,239 | none |
| Journeys | `GET /api/journeys` | 31.7 | 7 | 0 | 10,912 | K4: 27.2 / 7 / 10,991, unchanged |
| Journey detail | `GET /api/journeys/<id>` | 30.1 | 7 | 0 | 3,165 | K4: 25.7 / 7 / 3,184, unchanged |
| Traveler Offers | `GET /api/matches?role=traveler` | 84.2 | 3 | 46 | 47,941 | same observation as sender Offers |
| Traveler Deal | `GET /api/deals/<id>` | 29.4 | **16** | 15 | 9,198 | no traveler baseline. At K4's sender-side ceiling (16), so the K7 guard is 20. **Observation.** |
| Earnings | `GET /api/payouts?page=1&page_size=30` | 17.1 | 8 | 16 | 1,011 | K4: 15.7 / 8 / 1,005, unchanged |
| Payout detail | `GET /api/payouts/<ref>` | 12.3 | 6 | 16 | 672 | none |
| Payout methods | `GET /api/payouts/methods` | 3.3 | 1 | 0 | 667 | K4: 3.0 / 1 / 663, unchanged |
| Chat inbox | `GET /api/chat/threads` (5 threads) | 8.1 | 1 | 15 | 1,205 | K4: 7.7 / 1 / 1,252, unchanged |
| Chat messages | `GET /api/matches/<id>/chat/messages?latest=1` | 5.7 | 4 | 0 | 259 | K4: 4.7 / 4 / 264, unchanged |
| Notifications | `GET /api/notifications?bucket=all` | 37.3 | 4 | 16 | 1,683 | K4: 34.3 / 4 q. Bytes are not comparable: this world holds fewer lifecycle notification rows (the K3 fixture stubs realtime publish). The view is unchanged since K4 (`git log`). |
| Ratings | `GET /api/deals/<id>/ratings`, `/api/users/me/ratings` | 3.6 / 3.1 | 3 / 1 | 0 | 397 / 2 | none |
| Disputes | `GET /api/deals/<id>/disputes`, `/api/disputes/<id>` | 7.0 / 5.4 | 4 / 3 | 0 | 571 / 569 | none |
| Admin Overview | console `/` | 26.6 | 14 | 0 | 15,331 | K3 after: 27.8 / 16. K6: 25-30 / 14. Unchanged. |
| Admin People | `users/` | 19.4 | 4 | 0 | 15,649 | K3 after: 34.3 / 6. K6: 44-53 / 4. Unchanged. |
| Admin Person detail | `users/<id>/` | 50.0 | 20 | 16 | 12,717 | K3 after: 42.5 / 22 |
| Admin KYC queue | `verification/kyc/` | 13.7 | 5 | 0 | 11,704 | none |
| Admin KYC detail | `verification/kyc/<id>/` (S3 HEAD stubbed) | 12.7 | 4 | 15 | 11,689 | **Unstubbed with no object store: 8,855 ms.** This is the K6 finding (serial evidence HEADs, 4 s × 2 attempts, on the request path); it also applies to KYC review. |
| Admin Finance | `finance/dashboard/?mode=test` | 494.9 | 23 | 78 | 14,926 | K3 after: 604.7 / 27. K6: 484-620 / 23. Unchanged. |
| Admin Payouts | `finance/payouts-hub/?mode=test` | 605.9 | 18 | 93 | 15,111 | K3 after: 647.9 / 22. K6: 619-628 / 18. Unchanged. |
| Admin Payout detail | `finance/payouts/<id>/` | 38.5 | 15 | 31 | 20,037 | K3 after: 38.3 / 19. K6: 37-45 / 15. Unchanged. |
| Admin Disputes | `disputes/` | 30.1 | 5 | 16 | 11,036 | K3 after: 73.4 / 7. K6: 12-14 / 3 (no disputes in its world) |
| Admin Dispute detail | `disputes/<id>/` | 50.2 | **29** | 0 | 15,746 | no baseline. **Observation:** 29 queries for one dispute with no evidence. Scaling with evidence and events is untested. |
| Admin audit | `audit/` | 15.2 | 4 | 0 | 15,821 | none |

\* `force_authenticate` skips the user load.

**Regressions: none beyond budgets.** Every surface with a K3/K4 baseline is
at or below its baseline query count, with one exception: the Deal list is +1
query. That is the known K5 `attention` cost, inside both budgets, and the
list's query count stays flat in the number of Deals
(`test_phase_k5_list_attention.py`, passed). Latency differences of 1-5 ms
fall inside run-to-run noise on this box.

**Observations for Codex (not defects, no change made):**

1. The Match list is about 9.6 KB per row and the slowest app read. A list
   projection, like K4's Journey list, is the candidate fix.
2. The traveler's Deal detail runs 16 queries.
3. The Admin dispute detail runs 29 queries.
4. The request-path S3 HEADs on KYC detail and payout review detail (K6)
   remain.
5. The JSON `AdminDisputeListView` still hard-slices `[:100]`. The console
   list paginates, so no operator loses records, but the API does.

### Under load (cited, provisional)

The K6 package L runs (`docs/k6-notes/capacity.md`, 2x2 shape) measured:

| Users | p50 | p95 | p99 | Errors |
| ---: | ---: | ---: | ---: | ---: |
| 100 | 45 ms | 450 ms | 1.2 s | 0 |
| 150 | 65 ms | 900 ms | 1.4 s | 0 |

Throughput saturated at about 46 RPS, and DB connections peaked at 5 active.
**These numbers are provisional.** The Locust mix modelled
`GET /api/journeys/search` and `GET /api/parcels/open` as app traffic, but no
Flutter screen calls them. The K6 page-size finding is therefore withdrawn,
and the lead is re-running capacity with a corrected mix.

No confirmatory 100-user run was done here. The harness world had been swept
from disk, and this package was told not to run large loads.

Other 15.10 metrics:

* CPU and memory per process, and realtime socket memory (about 0.4 MiB per
  app-open user): cited from K6, with the same provisional caveat for
  anything derived from the mix.
* Redis lag: not measurable locally, because miniredis is not a Redis
  performance proxy. **Pending the Redis cutover.**
* Worker lag under backlog: **not measured.** K6 measured workers at idle
  only.

## 2. Mobile certification (15.11)

Everything below was run in this package: 18 test files, **224 passed**.

| Item | Proving tests (file: test) | Status |
| --- | --- | --- |
| Cold start | `k5_cold_start_test`: "the app paints and works while Firebase is still starting". `k5_request_budget_test`: "cold start to Home stays inside its request budget". `k5_session_snapshot_test`: "a snapshot signs in before /api/me answers". | verified by test |
| Warm resume | `k5_request_budget_test`: "resume reads the profile once; push state rebuilds nothing", "a phone-shaped return reads the profile once; a flicker, never". `k5_realtime_test`: "the background closes both; the return reconnects each once". | verified by test; real OS lifecycle order **needs device check** |
| Offline launch | `k5_cold_start_test`: "an offline launch without a snapshot offers a way out". `k5_session_snapshot_test`: "offline with a snapshot stays in, then revalidates on a timer", "offline without a snapshot holds the splash, as before". | verified by test |
| Slow network | **New** `k7_slow_network_test`: "a read that times out once is retried and succeeds", "a read that keeps timing out ends as a retryable timeout after three attempts", "a write that times out is reported once and never replayed". `phase_j12_test`: "the whole read cannot outlast three full attempts", "a timeout says the screen kept what it had". `phase8ff4_session_test`: "slower sign-in response cannot replace the newer login". | verified by test; real throttled network **needs device check** |
| Account switch | `k5_request_budget_test`: "a different account sees none of the first one's Deals". `k5_realtime_test`: "an account switch closes the previous account's sockets". `phase8ff4_chat_test`: "account identity recreates the provider and rejects the old ACK". | verified by test |
| Logout/login | `k5_session_snapshot_test`: "sign-out deletes the snapshot before its network call", "the revalidation timer dies with sign-out". `k5_realtime_test`: "sign-out closes everything and never redials". `phase8ff4_session_test`: "an in-flight refresh cannot overwrite logout and new login". | verified by test |
| Large history | `k5_lazy_lists_test`: "200 requests build only the rows near the viewport", "200 finished journeys in History build lazily too", "200 ratings: summary first, rows built lazily". `k5_request_budget_test`: "history is read only when opened, then a page per scroll". `k5_list_paging_test`: "a server that never stops saying "next" is bounded". `k5_json_decode_budget_test`. | verified by test. K5 deferral: a UI-thread JSON parse above about 25 current Deals on low-end phones. |
| Image-heavy flow | `k5_lazy_lists_test`: "photo decode size" group, "the request item photo decodes at its drawn width". | verified by test (decode sizing). Memory on a real low-end phone **needs device check**. |
| Chat | `phase8ff4_chat_test` (ordering, replay-safe reconciliation, "reconnect walks more than one bounded delta page without gaps", pending send through ACK, "dispose rejects stale send completion…"). | verified by test |
| Notifications | `k5_realtime_test`: "bell badge" group. `k5_request_lifetime_test`: "the bell and "Mark all read" come from one read". `notification_socket_test`: 4 tests. `phase8fd_push_test`: routing and permission. | verified by test. Real FCM delivery and the 20 s socket ping **need device check** (as K5 recorded). |
| Payment polling | `k5_polling_test`: "checkout re-reads" group (7) and "guest link fallback poll" group (3). `phase_j7d_payment_result_test`. | verified by test |
| No stale cross-account state | `k5_request_lifetime_test`: "sign-out and account switch" group. `phase8ff4_session_test`: "a delayed profile refresh cannot revive the previous account", "an old 401 is never replayed with the next account token". `j91_ratings_isolation_test`, `handover_isolation_test`. | verified by test |

The only gap was that no client-level test covered slow network or timeouts.
It is closed by `mobile/test/k7_slow_network_test.dart` (3 tests), which
passes, is formatted, and is clean under `flutter analyze --fatal-infos`.

## 3. Resilience certification (15.12)

| Item | Evidence | Status |
| --- | --- | --- |
| Redis restart | Go: `TestRunRecreatesAMissingGroupAndKeepsConsuming`, `TestFCMRunRecreatesAMissingGroupAndKeepsConsuming`, `TestGroupStartIDLooksBackAFixedWindow`, `TestIsNoGroup`. Django: `test_health` "readiness reports optional cache degradation without restart signal"; `test_redis_bus` "publish/xadd failure keeps audit row for sweep"; `test_ops_snapshot` "redis outage still reports database backlog". Restart-proof runbook: `docs/k6-notes/redis.md` §4. | verified by test (code paths). The live drill is **pending the Redis cutover** (owner decision: Redis provisioned before launch). |
| Worker restart | `test_recovery` "event job claimed before worker crash is requeued and applied"; `TestSweepReclaimsEveryPendingPageUntilTheCursorEnds` and `TestFCMSweep…` (PEL reclaim); `test_outbox` "the sweep picks up a message whose job was lost". | verified by test. On-platform drill **pending TEST release**. |
| Rolling deploy | `test_deployment_safety` "railway lets the combined launcher drain before sigkill", "default combined database budget is rolling deploy safe", "combined overrides cannot exhaust the rolling database budget". `k5_realtime_test` reconnect/backoff groups (the client side of a socket drop). | verified by test. Observed deploy **pending TEST release**. The connection check is not replica-aware (K6 risk). |
| Provider slowdown | `test_provider_http` "default transport uses separate bounded connect and read timeouts"; `test_deployment_safety` "production refuses unbounded provider timeouts"; `test_google_verifier` "every certificate fetch uses the bounded timeout". Breaker rejection is reasoned in K6 O §3. | verified by test. KYC/payout-review S3 HEAD stall (8.9 s locally) remains a request-path exposure. |
| Email/FCM failure | Go: `TestSMTP5xxRejectionIsPermanentWithItsReplyCode`, `TestSMTP4xxAndTransportFailuresStayRetryable`, `TestPartialRetryWaitStaysInsideTheSweeperIdleWindow`, `TestTransientRetryPayload`. Django: `test_outbox` "a transport failure leaves the obligation pending and retryable", "the retry after a failure sends the same code"; `test_deployment_safety` "production bounds django smtp and logs access safely". Real-Redis bounded-retry tests (`TestFCMPartialRetryChainIsBounded`, `TestFCMEntryPastItsRetryWindowIsDropped`) run in CI only. | verified by test (unit). Integration tier runs in CI. Real outage drill **pending TEST release**. |
| DB connection headroom | Budget 22 steady / 44 rolling of 90, and at most 5 active backends under load (K6, cited). Pinned by the `test_deployment_safety` budget tests. | verified by test (budget). The load figure is cited and provisional. |
| Queue recovery | `test_recovery` (durable job re-drive and exhaustion stays visible); `test_redis_bus` "sweep is bounded and oldest first", "bounded sweep still reaches newer events"; Go XAUTOCLAIM sweeps; `test_inspect_redis_streams` (drain gate). | verified by test. Stream survival across a restart is **pending the Redis cutover**. |

Nothing was "verified locally" by a live drill. The box has no real Redis, and
the drills are TEST-only by plan (14.17).

## 4. Section 19 acceptance criteria

**Unmet or not yet provable:**

1. **Infrastructure / persistent shared Redis** and **Reliability /
   Redis-queue durability resolved.** TEST still runs embedded Redis with
   persistence off. The code, boot gate and runbook are ready. Pending the
   owner's pre-launch Redis provisioning and cutover, plus the restart proof.
2. **Infrastructure / early-launch load measured** and **Scale / documented
   capacity envelope.** Both are provisional: the K6 mix modelled two
   endpoints the app does not call. They need the lead's corrected re-run. The
   K6 scale trigger T1 cites the withdrawn page-size fix and needs restating
   afterwards.
3. **Backend / pagination exposes all records.** Partially met.
   `AdminDisputeListView` still slices at `[:100]` (the console list
   paginates). Legacy `payments/intents` and `trips` slices are retired V1
   surfaces (K4).
4. **Backend / payloads reasonable.** Met except the Match list (about
   9.6 KB per row; see observations).
5. **Admin / visual consistency and workflow continuity.** Not re-verified in
   this package: no browser QA was run. K2/K3 evidence stands, and a
   browser-QA pass is recommended at the release gate.
6. **Mobile / real-device items.** OS lifecycle order, the socket ping, image
   memory on a low-end phone and real FCM delivery need a device check.

**Met, by the evidence above:**

* **Reliability:** no restart-loop dependency on degradable services.
  Readiness degrades without a restart signal; shared Redis fails fast by
  design. Retries, backoff and idempotency are sane. Failure isolation is
  acceptable, with the combined-container caveat from K6.
* **Admin:** Finance/Admin performance is within budgets (K3 tests pass, and
  the figures above match K3 and K6).
* **Backend:**
  * the measured N+1s are gone;
  * serializers are flat (K4/K5 flat-count tests);
  * compression and caching are correct (K4, TEST);
  * matching semantics are preserved (Find Travelers: same 9 queries and
    same bytes).
* **Mobile:** no N+1 HTTP cascades, no root rebuilds, responsive startup,
  offline and slow network usable, lazy lists, duplicate requests controlled,
  and a robust realtime lifecycle. All verified by test.
* **Infrastructure:** safe DB budget; justified topology; bounded and
  observable workers; observability lines exist. Alert wiring on Railway is
  still to be configured.
* **Scale:** advanced architecture adopted only when justified; future
  triggers documented.
* **Correctness:**
  * the Finance operational-vs-reconciliation parity test passes;
  * Deal attention list/detail parity passes (K5);
  * no production code changed in K7-C.

  Permissions, audit and security were not re-audited beyond these suites, and
  the full Django suite was not run in this package.

## 5. Checks run in this package

| Check | Result |
| --- | --- |
| Django (`test_pg`, own data dir, serial): K7 profile + K4 + K3 + K5 list-attention budgets | 21 passed |
| Django resilience modules: `test_health`, `test_redis_bus`, `test_ops_snapshot`, `test_inspect_redis_streams`, `test_outbox`, `test_push`, `test_recovery`, `test_deployment_safety`, `test_provider_http`, `test_google_verifier` | 148 passed |
| Go unit tests: `pkg/redisbus`, `pkg/retry`, `internal/email`, `internal/notification`, `internal/chat` | ok (the `-tags integration` real-Redis tier is CI only) |
| Flutter: 18 certification files (all `k5_*`, `k7_slow_network`, chat, session, socket, push, isolation, J12, J7D) | 224 passed |
| `ruff check` on the new test | clean |
| `dart format` and `flutter analyze --fatal-infos` on the new test | clean |
