# Phase L15: AI helper, keys and read access

Package L15 of `docs/WASSLA_DISCOVERY_PRO_PLAN.md` (spec 20.1 to 20.3, 20.5, 20.6 and 20.8, plan
2.11). An admin's own AI assistant reads that admin's briefing and follows it down to single records,
with that admin's rights at the moment of each call and the data limits of plan 2.11. **Nothing in
this package changes anything**: the change key, prepared changes and their actions are L16.

Backend and console only. New app `apps.admin_helper` (migration `admin_helper/0001`), one new
`ScheduledJob` kind (`finance/0031`). No Go, mobile or landing change.

## 1. The pieces

| Piece | Where |
| --- | --- |
| Keys, call log | `apps/admin_helper/models.py`: `AdminHelperKey`, `AdminHelperCall` |
| Policy reader | `apps/admin_helper/policy.py`: `AdminHelperPolicy`, `admin_helper_policy()` |
| Key life | `apps/admin_helper/keys.py`: `issue_key`, `resolve_key`, `stop_key`, `stop_all_keys`, `stop_keys_if_switched_off` |
| Authentication, throttle, call recording | `apps/admin_helper/api.py`: `HelperKeyAuthentication`, `HelperKeyThrottle`, `HelperView` |
| Endpoints | `apps/admin_helper/views.py`, `apps/admin_helper/urls.py` |
| Record types | `apps/admin_helper/resources.py`: `REGISTRY` |
| How-to list | `apps/admin_helper/tasks.py`: `TASKS`, `NO_TASK` |
| Call log pruning | `apps/admin_helper/calls.py`, job kind `admin_helper_call_prune` |
| Console card, page, form | `apps/admin_helper/console.py`, `templates/admin/console/_ai_helper_card.html`, `ai_helper.html`, the AI helper section of `settings.html` |
| One work list | `apps/admin_panel/worklist.py`: `work_items(admin)`, `work_item(code, admin)`, `rows(code, admin)` |

## 2. Policy

Top-level section `admin_helper` of `BusinessSettingsVersion.policy`, read in the style of plan 2.1.
A missing section means the defaults; a section with an unknown key, a wrong type or a value out of
bounds is refused when a revision is saved (`admin_helper_policy_unavailable`, through the settings
serializer), and an active revision the reader cannot read counts as **off** (every key refused).

| Key | Default | Bounds |
| --- | --- | --- |
| `enabled` | `true` | boolean |
| `read_key_hours` | 8 | 1 to 8 |
| `change_key_minutes` | 30 | 5 to 60 (L16) |
| `prepared_action_valid_hours` | 24 | 1 to 72 (L16) |
| `requests_per_minute` | 60 | 10 to 300 |

Console form: **Settings → AI helper** (`manage_settings`), one audited settings revision with a
reason. The staff API's settings endpoint validates the same section.

## 3. Keys

- `AdminHelperKey(id uuid, admin, kind read|change, key_hash, hint, created_at, expires_at,
  revoked_at, revoked_reason, last_used_at, use_count)`. A key is `wslr_` (read) or `wslw_` (change)
  plus 43 URL-safe random characters (32 bytes). Only its SHA-256 is stored; `hint` is its last four
  characters. A partial unique constraint allows one unrevoked key per admin and kind.
- `issue_key(admin=, kind=, request=)` is the only way a key comes to exist. It needs the signed-in
  admin's own request, console access, a two-step code entered in the last 10 minutes
  (`fresh_two_step`, L14; otherwise `admin_fresh_two_step_required`) and the helper switched on
  (otherwise `admin_helper_disabled`). It locks the admin row, stops the previous key of the same
  kind (`replaced`), fixes `expires_at` from the policy of that moment and returns the plain key once.
  `expires_at` never moves; use does not extend it.
- `resolve_key(plain)` returns the key, with its admin loaded fresh, only when the helper is on, the
  key is unstopped and unexpired, and `has_admin_access` is true for that admin (active, staff, not
  banned). Every other case is the same `401 admin_helper_key_invalid`, so an unknown key cannot be
  told from an expired, stopped or switched-off one. Rights are not checked here: each endpoint
  checks its own gate on the admin this call loaded.
- Stopping: `stop_key` (own key, or anyone's by a Super Admin with a reason, `manage_admins`) writes
  one audit row `ai_helper.key_stopped`. A two-step reset (console or
  `manage.py reset_admin_two_step`) stops the admin's keys (`two_step_reset`) and its own audit row
  `admin.two_step_reset` carries `helper_keys_stopped`. Activating a revision that switches the helper
  off stops **every** live key (`switched_off`) inside `activate_business_settings`'s transaction, so
  the console form and the staff API both do it, and a rolled-back activation stops nothing; one audit
  row `ai_helper.keys_stopped` on the revision gives `keys_stopped` and the keys' ids,
  admins, kinds and hints. Switching back on does not revive them.
- Stop reasons: `replaced`, `stopped`, `stopped_by_super_admin`, `two_step_reset`, `switched_off`.
- Audit rows never hold a key or its hash: `ai_helper.key_created` holds kind, hint, expiry and the
  replaced key ids.

## 4. Authentication and authority

- `Authorization: Bearer <key>` and nothing else: a key in a query parameter, a cookie, a body or a
  second header word is refused. The authentication class is installed only on the helper's views,
  and those views accept nothing else: a console session or a member's JWT gets `401`. A helper key
  opens no other route: the other API families and the console refuse it (tested on a sample of each).
- The helper routes do not use `HasAdminPermission`. They are `HELPER_API_ROUTES` in
  `apps/admin_panel/staff_api.py`, added to L14's `OPEN_STAFF_API_ROUTES` (the routes that answer
  without a session's second step), which is now exactly `admin-invitation-accept` plus the six helper
  route names. Nothing else was added.
- Every endpoint and record type names the gate of the console page it mirrors and checks it with
  `has_all_admin_permissions` (the fresh check) on every call: any one of the gate's codes opens it,
  exactly as `capability_required` opens the page. The overall endpoints (`guide`, `briefing`,
  `search`, `tasks`) mirror Overview, `view_dashboard`. The gate is checked before any lookup, so a
  refused admin cannot tell whether a record exists. A role change, ban, deactivation or loss of staff
  applies on the next call with the same key.
- GET and HEAD only; anything else is `405`.
- Throttle: `requests_per_minute` per key in each clock minute, one atomic cache counter per key and
  minute; over it `429 admin_helper_rate_limited` with `Retry-After` in seconds.
- Every response, refusals included: `Cache-Control: no-store`.
- Call log: `AdminHelperCall(key, method, path, status, at)` for every authenticated call, written
  after the response; the path is stored **without its query string**, so a search term never reaches
  the log. The key's `last_used_at` and `use_count` move with it. Each UTC day with calls schedules
  one `admin_helper_call_prune` job for 30 days after its end, which deletes calls older than 30 days.

Errors are `{"code", "detail"}`:

| Status | Code | When |
| --- | --- | --- |
| 401 | `admin_helper_key_invalid` | No key, malformed, unknown, expired, stopped, switched off, admin without access |
| 403 | `admin_helper_forbidden` | The admin may not open the console page this mirrors |
| 404 | `admin_helper_not_found` | Unknown record type, queue code or id |
| 400 | `admin_helper_bad_request` | Bad `limit`, `cursor` or `q` |
| 405 | | Any method but GET and HEAD |
| 429 | `admin_helper_rate_limited` | Over the per-minute limit |

## 5. The one work list

`_attention_items` left `console_views.py`; `apps/admin_panel/worklist.py` builds the list for both
the console overview and the helper briefing (1.5 rule 10). A `WorkItem` has `code`, `permission`,
`title`, `hint`, `next_step`, `count`, `oldest_waiting_since`, `severity`, `route`, `query` and
`queue_type` (the record type its rows are, or `None` for a count only). Each item's `permission` is
the gate of the console page it opens, so it shows exactly to the admins who can open that page.

Raised items come first, by severity (`urgent`, `today`, `info`), then the longest wait, then the
fixed order. Severity is a fixed rule per item, written next to it:

| Code | Title | Gate | Severity |
| --- | --- | --- | --- |
| `id_checks` | ID checks to review | `view_kyc` | today; urgent after 24 h |
| `tickets` | Tickets to review | `view_flight_proofs` | today; urgent after 2 h |
| `disputes` | Open disputes | `view_disputes` | urgent |
| `problems` | Problems to look at | `view_disputes` | urgent |
| `reviews` | Reported reviews | `moderate_ratings` | today; urgent after 72 h |
| `payout_methods` | Payout methods awaiting approval | `review_payout_profiles` | today; urgent after 48 h |
| `payout_identity` | Payout identity checks assigned to you | `attest_payout_identity` | today; urgent after 48 h |
| `payments` | Payments needing finance review | `view_payment_attempts` or `view_payment_orders` | urgent |
| `refunds` | Refunds requiring operator action | `issue_refunds` or `settle_manual_refunds` | urgent |
| `payouts` | Payouts requiring action | `view_payouts` | today; urgent after 24 h |
| `email` | Failed transactional email | `view_provider_health` | today |
| `jobs` | Background jobs needing attention | `view_scheduled_jobs` or `view_operational_incidents` | urgent |
| `providers` | Provider configuration warnings | `view_provider_health`, `view_operational_incidents` or `view_scheduled_jobs` | urgent |

"After N h" means the oldest waiting row has waited longer than N hours. An item with nothing waiting
is `info` and not raised. The console overview shows the severity and "Oldest waiting" on each raised
item. The thresholds are a judgment call for the owner's end review (also in
`docs/ADMIN_OPERATIONS.md`).

## 6. API

All under `/api/admin/helper/v1/`, JSON. Times are ISO 8601 in UTC; money is
`{"amount_eur_cents", "currency": "EUR"}` (a deal's `money` block is the same values, named);
console addresses are absolute. **A person**, wherever one is named, is
`{"id", "display", "console_url"}`: `display` is the first name and last initial ("Amina Z."), or
"Member <id>" when the stored name does not look like a name (an email, digits, an instruction, blank).
`console_url` is `null` when the admin may not open people. **A link** to another record is
`{"type", "id", "label", "console_url", "record"}`; for a type the admin may not open it is
`{"type", "id", "label": null, "console_url": null, "record": null}`.

### `GET guide`

`helper`, `version` (1), `admin` (person form), `roles` (role names), `key` {`kind`, `expires_at`,
`minutes_left`} (no hint), `may_read` {`records`: [{`type`, `what`, `path`}] for the types this admin
may open, `queues`: [{`code`, `title`, `rows` (`queues/<code>` or `null`), `count_only`}] for the
items this admin sees}, `actions` (always `[]` in L15), `endpoints` [{`path`, `does`}], `api`,
`console` and `rules` (eight fixed sentences stating plan 2.11 for the assistant).

### `GET briefing`

`generated_at`; `items`, the raised work in the server's order: `code`, `title`, `why`, `count`,
`oldest_waiting_minutes`, `severity`, `next_step`, `console_url`, `queue` (`queues/<code>` or
`null`); `clear`, the visible items with nothing waiting: `code`, `title`, `console_url`; `system`:
`providers` [{`name`, `state`, `label`}] with `view_provider_health`, and `jobs` {`pending`,
`running`, `retrying`, `failed_unresolved`} with `view_scheduled_jobs`. It equals the console
overview item by item (tested). No user-written text.

### `GET queues/<code>?limit=&cursor=`

The work item's summary (`code`, `title`, `count`, `oldest_waiting_minutes`, `severity`, `next_step`,
`console_url`), `count_only`, `rows` and `next_cursor`. Rows are oldest first, `limit` 1 to 25
(default 25); `next_cursor` is opaque (the last row's wait and id) and `null` at the end.

The four document reviews (`id_checks`, `tickets`, `payout_methods`, `payout_identity`), `email` and
`providers` are **count and link only**: `count_only: true`, `rows: null`.

Each row: `type`, `id`, `waiting_minutes`, `next_step`, `console_url`, `record`, plus per type:

| Queue | Row fields |
| --- | --- |
| `disputes` | `tracking_number`, `status`, `status_label`, `category`, `people` (sender, traveler) |
| `problems` | `tracking_number`, `kind`, `status`, `status_label`, `people` (reporter) |
| `reviews` | `tracking_number`, `score`, `open_reports`, `people` (writer, about) |
| `payments` | `tracking_number`, `status`, `status_label`, `amount`, `people` (payer) |
| `refunds` | `tracking_number`, `status`, `status_label`, `amount`, `people` (who asked for it, when a person did) |
| `payouts` | `tracking_number`, `status`, `status_label`, `amount`, `people` (traveler) |
| `jobs` | `work`, `status`, `error_category`, `people` (empty) |

### `GET records/<type>/<id>`

Every record: `type`, `id`, its fields below, `next_step`, `timeline` (at most the last 30 entries,
`{at, label}` with server labels) and `console_url`. Types holding member-written text add
`untrusted_user_text`, each value cut to 500 characters; **only here** does member text appear.

| Type | Gate | Fields | `untrusted_user_text` |
| --- | --- | --- | --- |
| `person` | any of `PROFILE_CAPABILITIES` (the People page) | `person`, `account_status` (`active`, `banned`, `deactivated`), `member_since` (`YYYY-MM`), `activity` {`requests`, `trips`, `deliveries_as_sender`, `deliveries_as_traveler`}; timeline empty | |
| `request` | `view_requests` | `tracking_number`, `status`, `status_label`, `from`, `to` (city labels), `weight_kg`, `deadline_at`, `traveler_reward`, `boost`, `sender`, `deliveries` (deal links) | `title`, `description`, `handling_notes` |
| `journey` | `view_journeys` | `status`, `status_label`, `traveler`, `from`, `to`, `paused`, `paused_by_staff`, `price_per_kg`, `minimum_price`, `legs` [{`position`, `mode`, `from`, `to`, `departs_at`, `arrives_at`, `ticket` (proof state)}] | `notes` |
| `deal` | `view_deals` | `tracking_number`, `status`, `status_label`, `sender`, `traveler`, `money` {`currency`, `traveler_reward_cents`, `wassla_fee_cents`, `sender_total_cents`}, `funded_at`, `agreed_pickup_at`, `picked_up_at`, `delivered_at`, `protection_ends_at`, `no_show`, `disputes`, `problems` (links), `payout` (link) | `parcel_title` |
| `dispute` | `view_disputes` | `tracking_number`, `status`, `status_label`, `category`, `opened_by`, `opened_at`, `sender`, `traveler`, `payout_frozen`, `resolution`, `sender_refund`, `traveler_payout`, `deal` (link) | `description` |
| `payment` | `view_payment_attempts` or `view_payment_orders` | `tracking_number`, `reference`, `purpose`, `provider`, `mode`, `status`, `status_label`, `amount`, `order_amount`, `charged` {`amount_minor`, `exponent`, `currency`} when the provider moved dinars, else `null`, `paid_by` (`owner` or `guest`), `payer`, `unapplied`, `failure_code`, `resolved_by_staff` | |
| `refund` | `issue_refunds` or `settle_manual_refunds` | `tracking_number`, `status`, `status_label`, `amount`, `provider`, `reason`, `needs_staff`, `failure_code`, `requested_by`, `payment` (link) | |
| `payout` | `view_payouts` | `tracking_number`, `reference`, `status`, `status_label`, `method`, `amount`, `paid_in`, `blocked_because`, `eligible_at`, `traveler`, `deal` (link) | |
| `job` | `view_scheduled_jobs` or `view_operational_incidents` | `work`, `status`, `status_label`, `attempts`, `max_attempts`, `error_category`, `next_run_at` | |
| `problem` | `view_disputes` | `tracking_number`, `kind`, `status`, `status_label`, `reported_by`, `reporter`, `deal` (link) | `note` |
| `review_report` | `moderate_ratings` | keyed by the **Rating id**: `tracking_number`, `score`, `written_by`, `writer`, `about`, `open_reports`, `reports` [{`reason`, `status`, `at`}], `decision` | `comment`, `report_<n>_note` |

The `person` record's field list is frozen by a test (plan 2.11, advisor 2026-11-14): adding a field
needs a decision first. Each serializer is written key by key in `resources.py`; none reuses a console
presenter or a model serializer. A type without a `REGISTRY` entry does not exist for the helper.

### `GET search?q=`

`q` is 1 to 64 characters and one thing: a person's id (digits, up to 12), a tracking number (through
`tracking.normalize`, any spacing or case), or a payment or payout reference (a UUID). The answer is
`{"looked_for": "person_id" | "tracking_number" | "reference", "results": [<link>]}`, only links the
admin may open; never a list of people by name. Anything else is `400` with a sentence saying what
search takes.

### `GET tasks`

`{"tasks": [{code, title, asks, steps, console_url, needs_document, action}]}`, the how-to list for
this admin: only the tasks whose capability they hold. 38 tasks in `tasks.py`, one per thing an admin
can do in the console, each keyed to the console route and the capability of its page. `action` is
`null` for every task in L15 (L16 fills it). A test lists every console route name and requires each
to be covered by a task or to be on `NO_TASK` with a reason (sign-in routes, the finance data feed, the
technical records and the helper's own key pages).

## 7. `curl` examples

The key below is redacted: a real one is `wslr_` plus 43 characters, shown once on the card.

```sh
API=https://api.wassla.example/api/admin/helper/v1
KEY=wslr_…REDACTED…Xk2Q

curl -sS -H "Authorization: Bearer $KEY" "$API/guide"
curl -sS -H "Authorization: Bearer $KEY" "$API/briefing"
curl -sS -H "Authorization: Bearer $KEY" "$API/queues/refunds?limit=10"
curl -sS -H "Authorization: Bearer $KEY" "$API/queues/refunds?limit=10&cursor=<next_cursor>"
curl -sS -H "Authorization: Bearer $KEY" "$API/records/deal/1042"
curl -sS -H "Authorization: Bearer $KEY" "$API/records/review_report/311"
curl -sS -H "Authorization: Bearer $KEY" "$API/search?q=WSL-N4CS-CFSV"
curl -sS -H "Authorization: Bearer $KEY" "$API/tasks"
```

A briefing answer, shortened:

```json
{
  "generated_at": "2026-11-14T14:56:00Z",
  "items": [
    {"code": "jobs", "title": "Background jobs needing attention", "count": 1,
     "oldest_waiting_minutes": 120, "severity": "urgent",
     "next_step": "Open each job, read its error category, then retry it or resolve it with a reason.",
     "console_url": "https://api.wassla.example/admin/system/jobs/?status=failed",
     "queue": "queues/jobs"}
  ],
  "clear": [{"code": "tickets", "title": "Tickets to review", "console_url": "…"}],
  "system": {"providers": [{"name": "Stripe", "state": "off", "label": "Disabled"}],
             "jobs": {"pending": 12, "running": 0, "retrying": 0, "failed_unresolved": 1}}
}
```

Refusals:

```sh
curl -sS "$API/guide"                                    # 401 admin_helper_key_invalid
curl -sS -H "Authorization: Bearer $KEY" "$API/records/payout/7"   # 403 admin_helper_forbidden for Support
curl -sS -X POST -H "Authorization: Bearer $KEY" "$API/guide"      # 405
```

## 8. Console

- **Overview → AI helper card.** What it is in two lines; the read key's state ("Active until 17:40",
  or "None") with its last four characters; **Create read key (8 hours)** and **Stop key**. Right
  after creation, in the response to that POST only, the block "Copy this into your assistant" holds
  one line, `/wassla <this server's /api/admin/helper/v1> <key>`, a **Copy** button and "It will not
  be shown again." A small script replaces the history entry so reload or Back cannot post again. With
  a stale code the console asks for one first and comes back. The change key is not stubbed (L16).
- **Overview → AI helper page** (`/admin/ai-helper/`, gated like Overview): the admin's keys (kind,
  state, created, last used, calls, stop) and their calls of the last 30 days (time, hint, method and
  path without the query, status). A Super Admin also sees every other admin's live keys (name,
  email, hint, state, last used; never a key) and can stop one with a reason, audited.
- **Settings → AI helper:** the form of section 2.
- **Switched off:** the card says "Switched off" and offers nothing.
- Every helper page and POST answer is `no-store`; the nav item "AI helper" sits under Overview.

## 9. Tests

`apps/admin_helper/tests/` (73 tests): `world.py` builds one world with every private value of plan
2.11 (distinctive last name, email, phone, street, coordinates, KYC file, DZD payout profile with
account details, pickup code, recipient contact details, chat message, guest payer email,
instruction sentences in every member-written field). No model stores a document number or a date of
birth (documents are image files), so the KYC file's storage key stands for them.

- `test_l15_privacy.py`: walks every payload a Super Admin can get (guide, briefing, tasks, four
  searches, every queue, every record type) and fails on any private value, the plain key or its hash,
  any forbidden key name or name part, any person shape other than the three keys; the frozen person
  record; amounts; count-only document reviews; instructions only under `untrusted_user_text` on
  records; the 500-character cut; non-names never sent.
- `test_l15_authority.py`: for Ops, Support, Finance, Trust, Super Admin and a staff account with no
  role, every record type, every queue and every overall endpoint answers exactly when the console
  page it mirrors opens (200 or 403 compared one by one); a role downgrade applies on the next call.
- `test_l15_keys.py`: policy bounds; format and hash-only storage (the database dump does not contain
  the plain key); fresh two-step; own keys only; rotation; 7 h 59 min answers and 8 h does not, even
  just used; expiry fixed at creation; switch off stops every key with one audit row, rolls back with
  its activation, and every call reads the switch; unreadable policy; stops and their audit; console
  and server two-step resets; the database constraint; card, one-time line, stale session, POST only,
  page, Super Admin stops, settings form.
- `test_l15_api.py`: the header is the only carrier; session and JWT refused; read only; no-store;
  ban, deactivation and staff loss on the next call; a key opens no other API family and no console
  page; rate limit; call log without query; prune job and prune; 404 and 400; gate before lookup;
  search and links; pagination; guide; briefing equals overview item by item; ordering and severity;
  fixed query counts for briefing and for queues at 1 and 25 rows; task coverage of every console
  route; the helper routes are exactly the open staff routes L14 names.

## 10. Screenshots

`/mnt/project-files/l-series-screens/L15/`, console in English (keys redacted in every image):

- `overview-full-en.png`: Overview, raised items with their severity and oldest wait, and the AI
  helper card with no key.
- `overview-helper-none-en.png`: the card alone, no key.
- `overview-helper-issued-en.png`: the one-time line right after creation, with Copy.
- `overview-helper-off-en.png`: the card with the helper switched off.
- `overview-helper-active-narrow-en.png`: the card at 390 px with a live key.
- `overview-helper-issued-narrow-en.png`: the one-time line at 390 px.
- `ai-helper-page-default-en.png`: the AI helper page, own keys and recent calls (paths without
  query).
- `ai-helper-page-super-admin-en.png`: the Super Admin table of other admins' live keys.
- `ai-helper-page-narrow-en.png`: the AI helper page at 390 px (tables scroll inside their card).
- `settings-helper-default-en.png`: Settings → AI helper.
- `settings-helper-saved-off-en.png`: the message after switching it off ("every key stopped").

## 11. Judgment calls

Accepted by the advisor on 2026-11-14 (plan commit `d4c562f`), kept for Ismail's end review:

1. A work item's gate is its console page's gate (any of its codes), so the overview and the helper
   show an item exactly to the admins who can open its page. Ops now sees the background jobs item.
2. Switching the helper off stops every live key for good (spec 20.2, 20.8), in the activation's
   transaction, with one audit row giving the number stopped.
3. A two-step reset, from the console or the server command, stops that admin's keys.
4. The `person` record adds account state, "member since" (month and year) and activity counts, and
   nothing else; its field list is frozen by a test (now in plan 2.11).
5. The severity thresholds of section 5.
6. Count and link only for the four document reviews, the email queue and providers.
7. `review_report` is keyed by the Rating id; a linked record of a type the admin may not open is a
   bare type and id; search leaves those out.

Smaller calls made while building:

8. Search reads digits as a person id first; tracking numbers and references have their own shapes.
9. The helper's own pages are gated like Overview (`view_dashboard`): every admin may have a key.
10. The call log keeps the path without its query string.
11. `issue_key` is general over the kind, but only read keys are offered; the change key is L16's.
12. `tasks[].action` is always `null` in L15.
13. The guide carries no key hint: the assistant needs none.
14. The one-time line is rendered in the POST's own response (never stored, never in a redirect), and
    the page replaces its history entry so reload cannot post again.
15. No model stores a document number or a date of birth; the privacy walk uses the KYC file key for
    them.

## 12. Known limits

- The throttle counts per clock minute in the shared cache: at a minute's edge a key can make up to
  twice the limit within 60 seconds; a cache flush resets the counters.
- `from` and `to` are city labels and can be `null` when a place has no locality.
- The call log records authenticated calls only; refused keys leave no row (nothing identifies them).
- Console English only, like the rest of the console.
