# K7 package B: conditional DB techniques, Find Travelers, data growth and retention

Master plan sections 15.7, 15.8 and 15.9. Base SHA `f77ae0e`. Every figure is
labelled **measured** (taken locally, method below) or **extrapolated**
(measured unit cost times a stated assumption). Nothing ran against Railway
TEST or LIVE. **No application code, schema or index changed in this package.**

## Short version

* **None of the section 15.7 techniques is justified now.** Read replicas,
  partitioning, Elasticsearch, CQRS and sharding are all one or more orders of
  magnitude from their triggers. `pg_trgm` is the only one with a trigger inside
  a plausible first year, and only for operator console searches.
* **Admin `%ILIKE%` search crosses ~100 ms at 20k-100k rows depending on the
  table.** The first to cross is the audit log (about 20k rows), then scheduled
  jobs (about 35-40k) and the email queue (about 55k), then People (about
  80-100k users). All are operator pages, not app paths.
* **Find Travelers is bounded but not flat.** The 200-candidate scan cap bounds
  Python evaluation. The SQL candidate query still grows with every Journey
  that overlaps the request window **on any corridor**: 71 ms at 24
  overlapping Journeys, 455 ms at 1,000 and 680 ms at 10,000. Paging re-runs
  the whole evaluation. There is also a bounded N+1 of up to ~210 queries.
  Verdict: keep the contract, fix the N+1 (contract-neutral), and revisit
  ranking only on the trigger below.
* **The fastest-growing table is not a product table.** It is the JWT
  refresh-token blacklist: about 2 rows per token refresh, and with a 300 s
  access token that is about 8 rows per active user per day. It is never
  flushed. Nothing periodic (sweep, prune, flush) runs anywhere today.
* **Retention needs scheduling more than new code.** Built-in or existing
  commands already cover the clearly disposable data (`flushexpiredtokens`,
  `clearsessions`, `prune_scheduled_jobs`). None of them is scheduled. No new
  pruning command was added (reasons in section 3).

## Method

| Probe | What was measured | How |
| --- | --- | --- |
| Growth unit costs | Rows written per table by one real V1 Deal, one chat message and one token refresh | Throwaway test under `test_pg`: exact `count(*)` of every table around `apps.deals.tests.phase4_factories` (`fund_scenario`, `record_recipient`, `confirm_pickup`, `release_delivery_code`, `confirm_delivery`), then `run_due_jobs` past the protection deadline. A real chat `POST` and a real `/api/auth/refresh`. The throwaway test was not committed. |
| Admin search | Wall time, query count and slowest-statement time of the **real console and admin API views** at 10k / 100k / 300k / 1M rows | `backend/loadtest/data_scale_probe.py search`: grows the tables with SQL clones of real rows, runs `VACUUM ANALYZE`, calls the view in-process with a Super Admin session or JWT, then runs `EXPLAIN (ANALYZE, BUFFERS)` on every captured SELECT. The *miss* term (`zqxj-no-such-text`) is the worst case; the *hit* term (`benali`) matches about 4 % of users. |
| Find Travelers | Same, for `GET /api/matches/find-travelers` and `GET /api/matches/compatible-requests`, against 24 / 100 / 1k / 10k Journeys overlapping the request window (and the same number of extra open requests for the journey side) | `data_scale_probe.py matching`: Journeys built through the seeder's `_journey` helper (approved KYC and ticket proof, discoverable). 10 % are on the request's exact corridor; the rest are on random real FR to DZ corridors. The per-user discovery throttle is disabled in-process so the throttle is not what gets measured. |
| Inbox | Notification list and unread count for the heaviest recipient at 1M and 5M `notification` rows | `data_scale_probe.py inbox` |

Environment: the K6 harness world (`seed.py` defaults: 1,605 users, 800
Journeys, 600 Deals, 3,360 chat messages, 43,000 notifications), on the real
56,134-place catalogue and embedded PostgreSQL 16.2 on the same i3-10100 box as
K6. Loopback has no network round trip; Railway adds roughly 0.5-1 ms per query
(K6 capacity notes). That matters for the N+1 findings. Wall times include
template or JSON rendering.

---

## 1. Section 15.7: conditional advanced DB techniques

| Technique | Plan trigger | Measured / current value | Verdict |
| --- | --- | --- | --- |
| **Read replicas** | Primary DB CPU > ~65 % sustained, or read load demonstrably dominant | K6: at most 5 active backends at 90 RPS (box saturated). Average active was 0.4 at 100 users and 1.7 at 1,000 users, so DB busy time is at most ~0.4-1.7 cores. Web saturated first at every point, at about 40 ms of web CPU per request. TEST Postgres uses 0.12 GB. | **No.** The web tier is the bottleneck (K6 triggers T1-T2). Never route matching or financial reads to a replica. |
| **Partitioning** | notifications > ~5M; chat > ~10M; scheduled/event tables at multi-million scale | Load world: 43k notifications, 3.4k chat, 2.1k jobs. TEST is far smaller. At **5M notifications** (2.8 GB with 8 indexes) the list is 36.7 ms and unread-count 52.9 ms, the same as at 1M (36.5 / 39.6 ms). Both are per-recipient index paths. Time to 5M notifications (extrapolated, section 3): ~14 years at 1k DAU, ~1.4 years at 10k DAU. | **No.** Per-recipient reads do not degrade with table size. Partitioning would only help bulk retention deletes. It would also force `recipient_id`/`created_at` into the `(recipient, event_id)` unique key. Revisit when a retention delete (section 3) cannot finish in its maintenance window. |
| **`pg_trgm`** | `%ILIKE%` admin/user search materially slow because of table size | Section 1.1: crosses ~100 ms at about 20k (audit), 35-40k (jobs), 55k (email) and 80-100k (users) rows. At 1M rows each search takes 0.25-1.2 s. | **Not now; the first technique to adopt.** Trigger in 1.1. |
| **Elasticsearch** | Postgres search inadequate for real multilingual/fuzzy requirements | The only end-user search is the place picker: `normalized_name` prefix/exact over a fixed 56k catalogue, 6 ms in K4. Admin search is an exact substring over emails, names and keys. No fuzzy or multilingual requirement exists in the V1 spec. | **No.** |
| **CQRS** | Durable read projections clearly justify eventual consistency | The heaviest reads are list pages (K6: Journey browse and open feed, about 40 % of web time). They are fixed by page size, not projections. Unread-count is 3 indexed queries. Deal/financial state must stay strongly consistent. | **No.** |
| **Sharding** | A strong single primary genuinely saturated at extreme volume, with a credible replacement for financial locking | DB at most ~1.7 cores busy at the box's 90 RPS ceiling. The financial lock graph relies on single-primary `select_for_update`. | **No.** |

### 1.1 `%ILIKE%` search inventory and cost

Django `icontains` on PostgreSQL renders `UPPER(col::text) LIKE UPPER('%q%')`.
No plain b-tree can serve it, so each search is a full scan. The console and
admin API paginate, so every search also runs a `COUNT(*)` over all matches;
that is why a miss costs as much as a hit.

Search sites (all operator-only; no app user search uses `icontains`):

| Surface | Fields | Code |
| --- | --- | --- |
| Console People | `email`, `full_name` | `console_views.users` |
| Console KYC, flight proofs, requests, journeys, deals, disputes | user `email`/`full_name`, title, flight number, `public_reference` | `console_views._search` call sites |
| Console payments | order `public_reference`, payer `email`, `guest_email`, `provider_payment_id` | `console_views.payments` |
| Console background jobs | `key`, `last_error_code`, `last_result` | `console_views.background_jobs` |
| Console email queue | `key`, `kind` | `console_views.email_queue` |
| Console audit | `action`, `target_type`, `target_id`, `reason`, `reference`, actor `email` | `console_views.audit_log` |
| Admin API users, KYC, requests, journeys, matches, deals, admin accounts, audit | same shapes | `admin_panel/views.py::_search` |
| Django admin `search_fields` | many models | `/admin/` model admin |

Measured, worst case (miss term). Slowest statement is server execution time
from `EXPLAIN ANALYZE`; wall is the whole request:

| Surface (rows in searched table) | 10k | 100k | 300k | 1M | ~100 ms crossover |
| --- | ---: | ---: | ---: | ---: | --- |
| Console People (users) | 20 ms / 34 ms wall | 102 / 116 | 271 / 302 | 852 / 857 | **~90-100k users** |
| Admin API users (users; 3 fields) | 25 / 29 | 115 / 138 | 425 / 425 | 1,097 / 1,105 | ~80-90k users |
| Console KYC (KYC = users / 4, joined to users) | 21 / 32 | 207 / 219 | 622 / 684 | 891 / 891 | **~12k submissions** |
| Console jobs (`finance_scheduled_job`) | 26 / 36 | 318 / 288 | 349 / 394 | 1,225 / 1,154 | **~35-40k jobs** |
| Console email (`notification_outbound_message`) | 17 / 28 | 198 / 198 | 383 / 281 | 819 / 757 | ~55k messages |
| Console audit (audit = users / 10) | 5 / 16 (1k rows) | 52 / 67 (10k) | 139 / 151 (30k) | 249 / 257 (100k) | **~20k entries** |

A hit (`benali`, about 4 % of users) costs the same or more. At 1M users the
console page is 1.7 s wall and the admin API 2.2 s, because the COUNT and the
page both walk the matches.

**Trigger (per surface):** add a `pg_trgm` GIN index **on the exact expression
Django emits**, `GinIndex(OpClass(Upper(Cast(col, TextField())), "gin_trgm_ops"))`,
when either of these holds:

* the searched table passes its crossover in the table above; or
* console search p95 exceeds 500 ms in production logs.

Adopt it per table, not globally. Every GIN index costs write amplification on
hot insert paths (jobs, outbound messages).

Expected order of arrival (extrapolated from section 3):

1. `finance_scheduled_job`: about 1.3 rows per active user-day, so about 40k
   rows within a month at 1k DAU without pruning.
2. The audit log.
3. The email queue.
4. KYC.
5. Users.

Scheduling `prune_scheduled_jobs` (section 3) keeps the jobs table below the
crossover much longer than an index would.

Caveats:

* **Could not measure the after state here.** The embedded `pgserver` build
  ships no contrib extensions (`CREATE EXTENSION pg_trgm` fails). The official
  Postgres image behind Railway ships contrib; confirm with
  `SELECT * FROM pg_available_extensions WHERE name = 'pg_trgm'`.
* **Trigrams need at least 3 characters.** Shorter terms fall back to a scan.
* **Very common terms stay slow.** A term like `gmail` still costs a bitmap
  heap scan over most rows for the COUNT. A capped count (for example "more
  than 1,000") is the complementary fix if that ever matters.

**Side finding (API contract, for Codex):** `GET /api/admin/users` runs **54
queries** for one page. `user_admin_roles()` calls
`user.groups.filter(...)`, which bypasses the view's
`prefetch_related("groups")`, and it runs once per row plus the permission
checks. This is independent of table size.

---

## 2. Section 15.8: Find Travelers

Contract (unchanged, verified in code): `compatible_journeys_for_request`
selects discoverable Journeys with **any leg overlapping the request's ready
window**. Corridor is only an ordering signal
(`has_exact_pickup_node`/`has_exact_delivery_node`), because a non-exact
Journey can still be compatible by detour. It takes the first
`candidate_scan_limit` = 200 rows, evaluates each in Python, ranks, and keeps
`result_limit` = 50. `find_travelers` pages that list, so each page re-runs the
whole evaluation.

Measured (median of 5 warm requests; 10 % exact corridor):

| Journeys overlapping the window (any corridor) | Wall | Queries | Candidate SQL | Page 2 (`offset=20`) wall |
| ---: | ---: | ---: | ---: | ---: |
| 24 (load world as seeded) | 71 ms | 16 | 13 ms | 74 ms |
| 100 | 140 ms | 61 | 24 ms | 138 ms |
| 1,000 | 455 ms | 218 | 287 ms | 444 ms |
| 10,000 | 680 ms | 218 | 428 ms | 681 ms |

Journey side, `compatible-requests` (the same scan pattern over open requests):

| Open requests in the Journey's window | Wall | Queries |
| ---: | ---: | ---: |
| 72 (as seeded) | 186 ms | 165 |
| +100 | 212 ms | 225 |
| +1,000 | 470 ms | 485 |
| +10,000 | 519 ms | 515 |

Where the time goes (captured and traced):

1. **Candidate SQL grows with global window volume.** `EXPLAIN ANALYZE` at
   10k shows a sequential scan of `trips_journey`. It evaluates the lifecycle
   `discoverable` CASE plus the exact-node `EXISTS` subplans for every
   Journey (10,776 rows) before a top-200 heapsort. The existing
   `journey_leg_time_window_idx` is used only inside subplans.
2. **Bounded N+1s (contract-neutral):**
   * Find Travelers: `Place.display_label` lazily loads `place.parent` for
     each leg's origin and destination while building compatibility payloads
     (`compatibility.py:175` via `_public_leg_summary`). That is 208 of 218
     queries at the cap.
   * `compatible-requests`: `evaluate_compatibility` (`compatibility.py:588-589`)
     lazily loads each candidate request's `pickup_place`/`delivery_place`,
     2 per candidate (400 at the cap), plus 100 more `parent` loads.
   * On Railway's ~0.5-1 ms per round trip this adds roughly 0.1-0.2 s to Find
     Travelers and 0.25-0.5 s to `compatible-requests` at the cap.
   * Fix: add `origin_place__parent`/`destination_place__parent` to the leg
     prefetch in `_matching_leg_queryset`, and `pickup_place__parent`,
     `delivery_place__parent` to the `compatible_requests_for_journey`
     `select_related`. No rule, order or payload changes.
3. **Python evaluation is capped.** Query count and evaluation stop growing at
   200 candidates (218 queries at both 1k and 10k).

**Verdict: no ranking/result-contract change now.** Load-world traffic sits at
the first row (24 overlapping Journeys, 71 ms). Discovery is throttled to 10
requests a minute per user. In K6, `compatible-requests` was about 6 % of web
time, and Find Travelers was not among the top consumers.

* **Do now (Codex, backend owner):** the two `select_related` fixes above.
  They are cheap and contract-neutral, and they matter on Railway's network
  even at current volume (`compatible-requests` already runs 165 queries in
  the seeded world). They were not implemented here: the package brief was
  measurement-first and the matching module is Codex-owned.
* **Trigger to revisit the scan itself:** Find Travelers p95 > 800 ms (the K6
  core-read line), **or** more than ~1,000 Journeys overlapping a typical
  1-day ready window. That is roughly 30k Journeys a month, the point where
  the candidate SQL passes ~250 ms.
* **Contract-preserving options, cheapest first:**
  1. Drive the candidate query from `trips_journey_leg` time-window rows
     (index) before evaluating lifecycle, so the window, not the whole table,
     is scanned. Same rows, same order.
  2. Precomputed route features: a persisted locality set per Journey,
     maintained on publish/edit, replacing the `EXISTS` subplans.
  3. A short-lived ranked-result token for pages 2+, keyed on request, policy
     version and time bucket. This one changes freshness semantics within the
     TTL and needs product sign-off, as K4 noted.

---

## 3. Section 15.9: data growth and retention

### 3.1 Measured unit costs

Rows written per event, measured through the real services:

| Table | Per completed Deal (fund, recipient, pickup, code release, delivery, protection expiry) | Per chat message | Per token refresh |
| --- | ---: | ---: | ---: |
| `notification` | 18 | 1 (counterparty) | 0 |
| `finance_scheduled_job` | 31 | 1 (`notification_dispatch`) | 0 |
| `core_published_event` | ~12 (about 1 per targeted event, written at dispatch) | ~1 | 0 |
| `notification_outbound_message` | 12 | 0 | 0 |
| `deals_event` | 19 | 0 | 0 |
| `handover_*` (code, attempt, access) | 6 | 0 | 0 |
| `finance_ledger_entry` / `_transaction` | 5 / 2 (to funding; payout execution adds more) | 0 | 0 |
| `finance_provider_event` (webhook) | 1 on the mock rail; real providers send several events per checkout | 0 | 0 |
| `chat_message` | 0 | 1 | 0 |
| `token_blacklist_outstandingtoken` + `blacklistedtoken` | 0 | 0 | **2** (1 blacklisted now; 1 outstanding when the rotated token is next refreshed) |

The token figure comes from `ROTATE_REFRESH_TOKENS` + `BLACKLIST_AFTER_ROTATION`,
the default 300 s access token, and the app refreshing on 401. Every sign-in
adds one more outstanding row.

### 3.2 Growth per active user-day (extrapolated)

Assumptions per active user-day (**assumed, not measured**):

* 20 minutes in the foreground, which is about 4 refreshes;
* 0.025 completed Deals (a user finishes a Deal about every 40 active days,
  two parties per Deal);
* 0.5 chat messages sent (about 20 per Deal).

| Table | Rows / active user-day | 1k DAU, per year | 10k DAU, per year |
| --- | ---: | ---: | ---: |
| Token blacklist (2 tables) | **~8** | 2.9M | **29M** |
| `finance_scheduled_job` | ~1.3 | 0.47M | 4.7M |
| `notification` | ~0.95 | 0.35M | 3.5M |
| `core_published_event` | ~0.8 | 0.29M | 2.9M |
| `chat_message` | ~0.5 | 0.18M | 1.8M |
| `deals_event` | ~0.48 | 0.17M | 1.7M |
| `notification_outbound_message` | ~0.3 | 0.11M | 1.1M |
| Ledger, provider events, audit, handover | < 0.2 each | < 0.1M | < 1M |

Table-size triggers are years away at 1k DAU. At 10k DAU, 5M notifications
arrive in about 1.4 years and 10M chat messages in about 5.5 years. Measured
storage is about 570 bytes per notification row including its 8 indexes
(5M rows = 2.8 GB).

### 3.3 Retention: current state and recommendation

Nothing periodic runs today. `start.py` runs only the finance worker loop, the
reservation releaser and the services. `sweep_published_events`,
`prune_scheduled_jobs`, `prune_push_devices` and `purge_staged_parcel_media`
all exist but are scheduled nowhere.

| Table | Growth | Current policy | Time-range index | Recommendation |
| --- | --- | --- | --- | --- |
| `token_blacklist_outstandingtoken` / `blacklistedtoken` | ~8 / active user-day, **largest** | none, never flushed | none on `expires_at` (a seq scan once a day is fine) | **Disposable.** Run the built-in `manage.py flushexpiredtokens` daily. It deletes only tokens past `exp` (30-day refresh TTL); the blacklist cascades. Safe: an expired refresh token is rejected on `exp` before any blacklist lookup. Steady state is about 30 days of refreshes (~0.24M rows at 1k DAU). |
| `django_session` | admin console only (few staff) | none | `expire_date` | Disposable. Run the built-in `clearsessions` daily. Negligible volume. |
| `finance_scheduled_job` | ~1.3 / active user-day (31 per Deal + 1 per chat message) | `prune_scheduled_jobs`: dry-run by default, ≥ 30 days, deletes only succeeded or operator-resolved rows. **Not scheduled.** | `fin_job_due_idx (status, run_at)`; no `completed_at` index. Selection at 1M rows is a 117 ms parallel seq scan (measured). | Schedule it daily with `--execute --days 90` after an owner review of the dry-run count. **Before it runs against a large backlog, batch it** (for example 5k ids per transaction). Today it locks and deletes every eligible id in one transaction. |
| `core_published_event` | ~0.8 / active user-day | none; the sweep reads only the last 7 days | `published_at`, `(delivered_at, published_at)` (index-only range scan measured) | Delivery telemetry, labelled "outbox audit" in G6b. **Owner decision:** propose 90-day retention. Not implemented, because it is called audit. |
| `notification` (inbox) | ~0.95 / active user-day | none | `created_at`, `(recipient, -created_at)`, `(recipient, read_at)` | User-facing history, **product decision.** Proposal: keep unread forever and delete read notifications older than 12 months in batches. The selection is a seq scan at 5M rows (785 ms measured), so batch by id range. Not needed for performance (section 1). |
| `chat_message` | ~0.5 / active user-day | none | `created_at`, `(match, id)`, `(match, created_at)` | **Keep.** It can be dispute evidence. Tie retention to the Deal's legal retention class, never shorter than dispute and chargeback windows. Legal review required. |
| `notification_outbound_message` | ~0.3 / active user-day | none | `(status, next_attempt_at)`, `(deal, kind)`; **no `created_at` index**, although the console orders by it | Deal-linked rows are evidence (for example "the recipient was sent the code"), so keep them with the Deal. Account rows (`email_verification`, `password_reset`, `admin_invitation`) could go after 90 days: owner decision. Add a `created_at` index if the console email page slows (~55k rows). |
| `notification_outbound_secret` | 1 per verification/reset/invite email | ciphertext erased on dispatch; rows kept; **expired-but-undispatched rows keep ciphertext** | `expires_at`, `consumed_at` | Low volume, but a hygiene gap: erase or delete rows past `expires_at` + 7 days. Candidate for a small command; not added (volume does not justify it now). |
| `accounts_passwordresetcode`, `accounts_emailverificationcode` | ~1-2 per user lifetime | none | `(user, used_at, expires_at)` | Disposable after expiry (Argon2 hash of a 6-digit code). Same small command as above, when one is built. |
| `notification_push_device` | 1 per installation | `prune_push_devices` deactivates (not deletes) after 180 days; not scheduled | `last_seen_at` | Schedule it weekly. |
| `parcels_media` (staged uploads) | per abandoned upload | `purge_staged_parcel_media` (48 h); not scheduled | yes | Schedule it daily (already flagged in IMPLEMENTATION_STATUS). |
| **Financial:** `finance_payment_order`/`_attempt`, `finance_provider_event` (webhook dedup + evidence), `finance_payment_refund`, `finance_payout`, `finance_ledger_*`, `deals_terms_snapshot` | < 0.2 / active user-day | none | various | **Never pruned by automation.** Retain for the statutory accounting period; commonly cited as 10 years for French commercial records, to be confirmed by legal review. Archive to cold storage only through an owner-approved, audited process. |
| **Audit/history:** `admin_panel_audit_log` (model refuses delete), `deals_event`, `disputes_*`, `handover_attempt`, `handover_code_access`, `matching_event`, `kyc_submission` decisions | small | none | `created_at` or `(entity, created_at)` | **Never pruned.** Same class as financial. KYC *evidence files* in object storage need a separate GDPR minimisation policy (spec section 29 retention classes); out of scope here. |
| Redis streams (`email:send`, `notif:fcm`, results) | transport | `MAXLEN ~10000` | n/a | Already bounded (K6 `redis.md`). |

**Why no new pruning command:** everything clearly disposable *and*
high-growth (token blacklist, sessions, succeeded jobs) already has a command.
The missing ones cover low-volume rows (expired codes and secrets), so a new
destructive command would add risk for no measured benefit. The actual gap is
**scheduling**. Two ways to close it:

* a Railway cron service running the daily set, which is operationally the
  simplest; or
* a daily step inside `run_finance_worker`, which is one fewer service but
  mixes concerns.

Either one is an owner and infra decision for the next ops package.

---

## 4. For the lead and Codex

1. **Codex:** the two Find Travelers / `compatible-requests` `select_related`
   N+1 fixes (section 2). They are contract-neutral and cut up to ~200 and
   ~500 queries.
2. **Codex:** `GET /api/admin/users` N+1 through `user_admin_roles()` (54
   queries per page).
3. **Owner/ops:** schedule `flushexpiredtokens`, `clearsessions`,
   `prune_scheduled_jobs` (batched first), `prune_push_devices`,
   `purge_staged_parcel_media` and `sweep_published_events`. Decide the
   `core_published_event` and read-notification retention windows.
4. **Legal:** the retention period for the financial and audit classes, and
   chat as evidence.
5. **`pg_trgm`:** adopt per table on the section 1.1 trigger, jobs and audit
   log first. Verify the extension on Railway Postgres before relying on it.

## Reproduce

```bash
export LOADTEST_PGDATA=C:/Users/<you>/AppData/Local/Temp/k7b-loaddb   # own dir
PY=backend/monolith/.venv/Scripts/python
$PY backend/loadtest/manage_loadtest.py migrate --noinput
$PY backend/loadtest/manage_loadtest.py import_geography --skip-if-current
$PY backend/loadtest/seed.py
$PY backend/loadtest/data_scale_probe.py search   --sizes 10000 100000 300000 1000000
$PY backend/loadtest/data_scale_probe.py matching --sizes 100 1000 10000
$PY backend/loadtest/data_scale_probe.py inbox    --sizes 1000000 5000000
```

Probes only add rows, so run them on a disposable database. The full set needs
about 6 GB of disk (5M notifications alone are 2.8 GB) and about 25 minutes on
this box.
