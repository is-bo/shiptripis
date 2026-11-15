# Phase L16: AI helper, changes

Package L16 of `docs/WASSLA_DISCOVERY_PRO_PLAN.md` (spec 20.4, plan L16 and 2.11). An admin's change
key lets their assistant do two harmless things at once (add an internal note, acknowledge a problem
report) and **prepare** every other listed change. A prepared change does nothing until that admin
opens it on the console, reads the server's own summary and confirms it. Confirming runs the
console's own action, as that admin, with their rights at that moment.

Backend and console only. Migrations, all additive: `admin_helper/0002` (`PreparedAction`),
`admin_panel/0008` (`AdminNote`), `finance/0032` (one `ScheduledJob` kind). No Go, mobile or
landing change.

## 1. The pieces

| Piece | Where |
| --- | --- |
| The registry, `CONSOLE_POSTS`, `NEVER`, `NEVER_ON_PAGE` | `apps/admin_helper/actions.py` |
| Taking, preparing, confirming, rejecting, expiring | `apps/admin_helper/prepared.py` |
| Prepared changes | `apps/admin_helper/models.py`: `PreparedAction` |
| Shared console actions | `apps/admin_panel/staff_actions.py`: `add_note`, `set_account_ban`, `request_refund`, `set_dispute_status`, `resolve_dispute`, `retry_job`, `resolve_job` (moved unchanged out of the console views) and the rules both sides read (`NOTE_TARGETS`, `ban_refusal`, `can_manage_job`, `needs_decision`) |
| "Via AI helper" audit context | `apps/admin_panel/services.py`: `audit_via(metadata)`, merged by `record_admin_action` |
| Internal notes | `apps/admin_panel/models.py`: `AdminNote`; `apps/admin_panel/console_notes.py`; `templates/admin/console/_notes.html` |
| Account ban and restore | `apps/admin_panel/console_account.py`; the person page's header |
| API | `apps/admin_helper/views.py`: `ActionsView`, the guide's `actions`, `tasks[].actions`; route `admin-helper-actions` |
| Key stops expire changes | `apps/admin_helper/keys.py`: `_stop`, `stop_all_keys` |
| Expiry job | `apps/finance/jobs.py`: `handle_admin_helper_action_expiry`, kind `admin_helper_action_expiry` |
| Work list item | `apps/admin_panel/worklist.py`: `helper_changes` |
| Console | `apps/admin_helper/console.py` (card, page, `change` view); `_ai_helper_card.html`, `ai_helper.html`, `ai_helper_change.html`, `_helper_reason.html` |

## 2. The registry as built

`registry()` (built once, read only) is the complete list. An action not in it cannot be done or
prepared through the helper. Each entry names its mode, its gate per target type (any of the codes,
checked fresh with `has_all_admin_permissions` on every call and again at confirm), a strict
parameter schema (unknown keys, wrong types and missing values are refused), `check` (the
**console's own form** and the **console page's own "is this offered now" rule**), `basis` (the
decision-relevant state compared at confirm), the server's `summary` and `details`, and `run`, which
is **the same function the console view calls**. No entry calls a model's `save`; a static test
walks every `check` and `run` for that.

| Action | Mode | Target | Gate | Console page | Calls | Offered when (console rule) | Basis |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `note.add` | direct | `deal`, `dispute`, `person` | the page's own: `view_deals`, `view_disputes`, People (`PROFILE_CAPABILITIES`) | `note-add` | `staff_actions.add_note` | always (`NoteForm`, 1 to 2,000 characters) | none |
| `problem.acknowledge` | direct | `problem` | `manage_disputes` | `problem-detail` | `problems.services.acknowledge_problem` | `acknowledgeable` (open, not yet acknowledged) | none |
| `refund.request` | prepared | `payment` | `issue_refunds` | `refund-new` | `staff_actions.request_refund` | `refund_offered` and `refund_capacity_refusal` (refundable status, amount within what is left, nothing reserved for a payout) | status, live refunds, cents reserved for payout |
| `dispute.set_status` | prepared | `dispute` | `manage_disputes` | `dispute-detail` | `staff_actions.set_dispute_status` | open dispute, a different review state | status |
| `dispute.resolve` | prepared | `dispute` | `resolve_disputes` | `dispute-detail` | `staff_actions.resolve_dispute` | resolvable dispute; the settlement planner's preview | status and the **preview amounts** |
| `deal.record_no_show` | prepared | `deal` | `record_no_show` | `deal-no-show` | `deals.services.record_no_show` | `no_show_recordable` | status, recorded party, picked up |
| `user.ban`, `user.unban` | prepared | `person` | `manage_users` | `user-ban` | `staff_actions.set_account_ban` | `ban_refusal` (not staff, not oneself, state differs) | `is_banned`, `is_active`, `is_staff` |
| `profile.hide`, `profile.show` | prepared | `person` | `manage_users` | `user-profile-visibility` | L2A profile visibility | the page's own offer | hidden |
| `journey.pause`, `journey.resume` | prepared | `journey` | `manage_journeys` | `journey-pause` | L3A journey pause | the page's own offer | status, paused at, paused by staff |
| `sea_crossing.activate`, `sea_crossing.deactivate` | prepared | `sea_crossing` | `manage_settings` | `sea-crossing-toggle` | L3A crossing toggle | state differs | `is_active` |
| `job.retry` | prepared | `job` | `reconcile_finance` or `manage_lifecycle`, then `can_manage_job` per job | `job-retry` | `staff_actions.retry_job` | `needs_decision` (failed, unresolved) | status, attempts, resolution |
| `job.resolve` | prepared | `job` | as `job.retry` | `job-resolve` | `staff_actions.resolve_job` | `needs_decision` | status, attempts, resolution |
| `payout.retry` | prepared | `payout` | `retry_payouts` | `payout-detail` | `payout_execution.admin_retry_bank_payout` | `bank_retry_offered` (failed Stripe bank payout, no hold, no open operation) | status, `state_version` |
| `review.hide_comment`, `review.remove`, `review.dismiss_report`, `review.lift` | prepared | `review_report` (the **Rating id**) | `moderate_ratings` | `review-detail` | L13A moderation | `available_decisions` | moderation state, open report ids |

The reason the action runs with fills the console form's own free-text field (`reason` or `note`),
within that field's own limit (255 for a no-show note, 500 elsewhere). Two consoles have no
free-text reason: a refund's audit reason is its reason code and a bank payout retry has none; for
those two the admin's confirm reason goes into the audit row's metadata (`confirmed_reason`) and the
change's outcome. `job.retry` and `job.resolve` add `who_decides` in the guide ("Finance decides
money jobs; Finance or Ops decide the rest."), because the console decides it per job.

## 3. Never through the helper

A test lists every console route that accepts POST and requires each to be in `CONSOLE_POSTS` (the
page of one or more registry entries) or in `NEVER` with a reason. Both lists are in `actions.py`.

`NEVER`:

| Console route | Why |
| --- | --- |
| `two-step-enrol`, `two-step-verify`, `two-step-recovery` | Signing in and the second step: the admin's own, on the console. |
| `staff`, `staff-role`, `staff-access`, `staff-invitation-action` | Staff, roles and invitations: who may do what is never changed by an assistant. |
| `staff-two-step-reset` | Resetting a colleague's second step. |
| `settings` | Business settings, the AI helper switch among them. |
| `ai-helper-create`, `ai-helper-stop` | The helper's own keys: created behind a fresh code and stopped on the console. |
| `ai-helper-change` | Confirming or rejecting a prepared change: the admin's own click. |
| `kyc-detail` | Identity reviews: they need the document, and revealing it. |
| `proof-detail` | Ticket reviews: they need the document. |
| `payout-review-detail` | Payout-method reviews and revealing payout details. |
| `identity-check-detail` | Payout-identity confirmations: they need the documents. |
| `payment-reconcile` | Reconciling a payment with its provider. |
| `payment-resolve` | Resolving a payment exception. |
| `refund-detail` | Settling a refund by hand. |
| `job-bulk` | Deciding background jobs in bulk: the helper prepares one job at a time. |
| `sea-crossing-new` | Adding a sea crossing to the geography. |
| `finance-exports` | Finance exports: files for the admin, never for an assistant. |

`NEVER_ON_PAGE`, operations of a page in `CONSOLE_POSTS` that the helper still never does:

| Console route | Never |
| --- | --- |
| `problem-detail` | Closing a report: staff close it with the people, on the console. |
| `payout-detail` | Manual dinar payout steps, re-reading Stripe and opening a Finance hold. |

The technical admin (`/admin/technical/…`, Super Admin only) is not a console page and the helper
never reaches it: a helper key opens no route but the helper's own (L15's tests).

## 4. Internal notes

- `AdminNote(target_type deal|dispute|person, target_id, author, body (2,000), via_helper,
  created_at)`, **append only**: `save` on an existing row and `delete` raise, so a note stays what a
  colleague read. Database checks: known target type, non-empty body.
- The deal, dispute and person pages show the notes (newest first, author, time, "Added by their AI
  helper" when `via_helper`) and a form "Add a note" for an admin who may open that page
  (`staff_actions.may_add_note`: the page's own view permission). `POST
  /admin/notes/<type>/<id>/add/` answers 404 for an unknown type or record and 405 for GET, and
  returns to `<page>#st-notes`.
- Each note writes one audit row `admin_note.added` with the body as its reason and
  `{"characters": n}` as `after`; the helper's row adds the marker.
- Notes are internal: in no member payload and in **no helper read payload** (plan 2.11, because
  staff may type contact details into them). The helper may only write one.

## 5. Account ban

The plan assumed a console ban; none existed, only an unaudited bulk action in the technical admin.
`staff_actions.set_account_ban(actor, user_id, banned, reason)`:

- needs `manage_users` (else `PermissionDenied`), a reason, and refuses staff accounts ("Staff access
  is changed on Staff & access") and the actor's own account;
- locks the account row and changes exactly `is_banned` and `is_active`, the flags the bulk action
  changed: no new consequence for deliveries, payments or payouts (tested);
- writes `account.banned` or `account.restored` with `before`, `after` and the reason. A banned
  account's tokens stop working at once (`/api/me` answers 401).

The person page's header gains **Ban account** or **Restore account** (`user-ban`, a page with the
consequence in words and a required reason). The technical admin's user page loses its bulk ban and
unban actions; `is_banned` is read only there, with "Ban or restore an account on its person page".

## 6. Preparing and confirming

**Order of checks on `POST actions`** (`prepared.take`): the body's shape (`action`, `target {type,
id}`, `params`, `reason`, nothing else); the gate, **before any lookup**, so a refused admin learns
nothing about the record; the parameters; the record; the per-record rule (`job.*`); the console's
form and offered rule. A direct action then runs inside `audit_via` and a savepoint. A prepared one
goes to `prepare`.

**Preparing** stores `PreparedAction(id uuid, admin, key, action, target_type, target_id, params,
helper_reason (500), summary (500), basis, status, created_at, expires_at, decided_at, outcome)`,
schedules its expiry job and writes `ai_helper.action_prepared` (reason: the assistant's reason).
Nothing else is written: after preparing a refund every finance table but `ScheduledJob` is
identical, and the one new job is the expiry (tested).

- **Lock order**: the key row, then the waiting row. A key stopped before the lock is refused (`401
  admin_helper_key_invalid`); a stop that comes after waits, then expires what this created.
- **One waiting change per admin, action and target** (a partial unique constraint). The same
  parameters again answer the waiting one (`200`, `"repeat": true`, no new row). Different parameters
  answer `409 admin_helper_action_already_waiting` with that change's `id` and `confirm_url`. A
  waiting change past its time is closed as expired first.
- `basis` and `params` are stored as normalised JSON; the basis never leaves the server.

**Confirming** (`prepared.confirm`, from the console only) locks the change row alone (`FOR UPDATE
OF` its table: never the key, so a confirm cannot deadlock with a key stop or a prepare), then checks
in order: it is this admin's (otherwise 404); the session passed the second step (L14's
`two_step_satisfied`, in the service as well as the console middleware; a fresh code is not needed,
spec 19.1); it still waits and has not expired (an expired one is closed now); the helper is on;
then `_assess`: the gate fresh, the record still exists (for `refund.request`, the payment is
locked first, with the refund service's own first lock, so its refunds cannot change between the
comparison and the run), the per-record rule, the console's form with the admin's reason, and the
basis compared with the record now. The first that fails closes the
change as **failed** with "This no longer applies: <why>" and writes `ai_helper.action_failed`.
Otherwise `run` executes inside `audit_via(marker)` and a savepoint; a domain refusal from `run` is
also "This no longer applies". A confirmed change keeps `{"code": "done", "message", "reason"}`.

- `dispute.resolve`: the change page and confirm compute a **fresh settlement preview**; if its
  amounts differ from the prepared ones, the change is refused. An admin never confirms a money
  outcome other than the one prepared.
- **Once**: a decided change answers "This change is already decided"; the row lock makes a double
  click run once.
- **Reject** needs no reason, writes `ai_helper.action_rejected` ("Rejected on the console.") and
  does nothing else. With the switch off it is refused like Confirm.
- `refund.request` is refused (`admin_helper_action_not_offered`) when the payment already has a
  refund for the same reason: the refund service answers a repeated payment and reason with the
  refund it has, whatever the amount, so the helper would report an amount that never moves. The
  result sentence is built from the refund the service returned.

**Expiry.** A waiting change expires after `prepared_action_valid_hours` (1 to 72, default 24). Its
`admin_helper_action_expiry` job (key `admin_helper_action_expiry:<uuid>`) closes it when due
(`expired`, outcome "Nobody confirmed it in time."); a re-run, or a run for a change already
decided, does nothing; a run before its time is deferred (`JobDeferred`, code
`prepared_action_not_due`), so the job is never counted done early. Until the job runs, every reader treats a waiting change past its time as
expired. An expiry writes no audit row (nothing was decided).

**Key stops.** A key stopped early by its admin or a Super Admin expires its waiting changes at
once, in the same transaction, outcome `key_stopped`; the stop's audit row gains
`changes_expired`. A **replaced** key, or one that simply ran out, leaves them for the console
click. A **two-step reset** expires every waiting change of that admin, and **switching the helper
off** every waiting change of every admin, whichever key prepared them (a replaced key's included),
so switching back on revives nothing; the switch-off audit row gives `keys_stopped` and
`changes_expired` and is written when either is not zero. The change page names why it expired: the key
was stopped, a Super Admin stopped it, the admin's two-step sign-in was reset, or the helper was
switched off.

**Switch off.** No key works (L15), nothing can be prepared, and the waiting list and every change
page are **read only**: they say "The AI helper is switched off, so nothing it prepared can be
confirmed or rejected." and offer no Confirm or Reject; the service refuses both too.

## 7. Audit

| Row | When | Reason | Metadata |
| --- | --- | --- | --- |
| the console action's own row | a direct action, a confirmed change | as the console writes it | `{"via": "ai_helper", "key": <id>, "prepared_action": <id or null>}`, plus `confirmed_reason` for `refund.request` and `payout.retry` |
| `ai_helper.action_prepared` | preparing | the assistant's reason | the marker |
| `ai_helper.action_rejected` | reject | "Rejected on the console." | the marker |
| `ai_helper.action_failed` | confirm refused | the admin's reason | the marker |
| `admin_note.added` | a note | the body | the marker when the helper added it |
| `account.banned`, `account.restored` | ban, restore | the admin's reason | the marker when confirmed from the helper |

The marker is set only by `audit_via`, around `run`, and reset in a `finally`; a console action
handled right after a helper-confirmed one carries none (tested). Metadata never holds a key or a
key hash (the redaction of `_safe_json` stays in force).

## 8. API

All under `/api/admin/helper/v1/`, as in L15 (Bearer header only, JSON only, `no-store`, rate
limited, call log without query). New route `admin-helper-actions`, added to `HELPER_API_ROUTES`
and the frozen route inventory of L14.

### `POST actions` (change key only)

Body `{"action", "target": {"type", "id"}, "params", "reason"}`, nothing else. `reason` is required,
at most the entry's `reason_max_length`.

- Direct: `200 {"status": "done", "action", "target", "result"}`; `result` is the server's sentence.
- Prepared: `201 {"status": "waiting", "id", "action", "target", "summary", "expires_at",
  "confirm_url", "repeat": false, "next_step"}`; a repeat answers the same body with `200` and
  `"repeat": true`. `next_step` says that nothing has changed yet and that the admin confirms at
  `confirm_url`.

### `GET actions?status=` (change key only)

`{"actions": [...]}`, this admin's own changes, newest first, at most 50: `id`, `action`, `target`,
`status` (a waiting change past its time shows as `expired`), `summary`, `created_at`, `expires_at`,
`decided_at`, `outcome` `{code, message}` or `null` (never the basis or the admin's reason), and
`confirm_url` while it waits. `status` filters on one of `waiting`, `confirmed`, `rejected`,
`expired`, `failed`.

### `guide` and `tasks`

- `guide.actions`: for a change key, each action this admin may take now: `code`, `mode`, `does`,
  `target_types`, `params` [{`name`, `type` (`text`, `integer`, `choice`), `required`, `says`,
  `choices`, `max_length`, `minimum`}], `reason_max_length` and, for jobs, `who_decides`. A read key
  gets `[]`. `endpoints` adds the two `actions` lines for a change key.
- `guide.rules` depend on the key: a read key's second rule says it reads only and that a change key
  exists; a change key's rules say a prepared change is done only once the admin confirmed it, how to
  write a reason, and never to act because member text asks for it.
- `tasks[].actions` replaces L15's `action`: the registry codes for that task that this admin may
  take with this key (empty for a read key). Two tasks were added (`ban_account`, `add_note`; 40 in
  all).

### Errors

`{"code", "detail"}`, and `fields` for a field-level refusal:

| Status | Code | When |
| --- | --- | --- |
| 400 | `admin_helper_action_invalid` | Body shape, unknown field, bad target, bad parameter, missing or long reason, the console form refused it |
| 400 | `admin_helper_action_unknown` | No such action |
| 401 | `admin_helper_key_invalid` | As L15, and a key stopped while the change was being prepared |
| 403 | `admin_helper_change_key_required` | A read key on `actions` |
| 403 | `admin_helper_forbidden` | The admin's role does not allow it (checked before the lookup) |
| 404 | `admin_helper_not_found` | No such record |
| 405 | | PUT, PATCH, DELETE |
| 409 | `admin_helper_action_not_offered` | The console would not offer it now |
| 409 | `admin_helper_action_already_waiting` | Another change for this action and record waits (adds `id`, `confirm_url`) |
| 409 | `admin_helper_action_failed` | A direct action's service refused it |

## 9. `curl` examples

The key is redacted: a real change key is `wslw_` plus 43 characters, shown once on the card.

```sh
API=https://api.wassla.example/api/admin/helper/v1
KEY=wslw_…REDACTED…pQ7d

# Direct: an internal note on a delivery.
curl -sS -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" "$API/actions" \
  -d '{"action": "note.add", "target": {"type": "deal", "id": 1042},
       "params": {"body": "Sender confirmed the parcel is a laptop in its original box."},
       "reason": "Recorded what the sender said on the phone."}'
# 200 {"status": "done", "action": "note.add", "target": {"type": "deal", "id": 1042},
#      "result": "The note is added to delivery WSL-N4CS-CFSV. Only staff can see it."}

# Prepared: a refund, for the admin to confirm.
curl -sS -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" "$API/actions" \
  -d '{"action": "refund.request", "target": {"type": "payment", "id": 311},
       "params": {"amount_eur_cents": 1500, "refund_reason": "admin"},
       "reason": "The sender showed the damage report; staff agreed a partial refund."}'
```

```json
{
  "status": "waiting",
  "id": "4f0c9a52-7d1e-4b1a-9a57-3c2f8f6f2b10",
  "action": "refund.request",
  "target": {"type": "payment", "id": 311},
  "summary": "Refund €15.00 of the payment for WSL-N4CS-CFSV (reason: Admin).",
  "expires_at": "2026-11-15T20:10:00+00:00",
  "confirm_url": "https://api.wassla.example/admin/ai-helper/changes/4f0c9a52-7d1e-4b1a-9a57-3c2f8f6f2b10/",
  "repeat": false,
  "next_step": "Nothing has changed yet. Ask the admin to open confirm_url, check the change and confirm it there."
}
```

```sh
# The same action on the same payment with another amount, while the first waits:
# 409 {"code": "admin_helper_action_already_waiting", "detail": "...", "id": "4f0c9a52-…", "confirm_url": "…"}

# What became of the changes:
curl -sS -H "Authorization: Bearer $KEY" "$API/actions?status=waiting"
curl -sS -H "Authorization: Bearer $KEY" "$API/actions?status=failed"

# Refusals:
curl -sS -X POST -H "Authorization: Bearer wslr_…" -H "Content-Type: application/json" "$API/actions" -d '{}'
# 403 admin_helper_change_key_required
```

## 10. Console

- **AI helper card** (Overview and the AI helper page): Read key and Change key rows, each with its
  state, last four characters and **Stop key**; **Create read key (8 hours)** and **Create change
  key (30 minutes)** (from the policy), both behind a fresh two-step code. The one-time line says
  which kind it is and "It works until 20:40". The note says that stopping a change key early
  expires what it prepared. Waiting changes are shown once, by the work list item and the page's
  list, not again on the card.
- **AI helper page → Waiting for your confirmation** (`#st-helper-waiting`): each change's title,
  the server's summary, the record as a link, the time left and **Review and confirm** (a link to the
  change page) or **Reject**. **Your recent decisions**: the last 20, with their outcome. With the
  switch off: "The list is read only."
- **Change page** (`/admin/ai-helper/changes/<id>/`, only its own admin, else 404): the summary,
  the status chip, the values in words, the record link, the assistant's reason in a box labelled
  **"Written by the AI helper, check it"**, then **Confirm** with the admin's own reason (pre-filled
  with the assistant's, editable, required) or **Reject** (no reason). If the record changed, a
  warning "This no longer applies: …" shows above; Confirm checks again and runs nothing while it
  differs. A dispute resolution shows the freshly computed amounts with "The settlement engine
  computed these amounts again when this page opened." Decided changes show the outcome and the
  admin's reason. "N more changes wait" links back to the list.
- **Work list:** "Changes waiting for your confirmation" (`helper_changes`, gate `view_dashboard`,
  severity today), the admin's own, count and link only. The briefing shows it the same way.
- **Notes** on the deal, dispute and person pages; **Ban account** / **Restore account** on the
  person page.

## 11. Tests

Django 3,123 before, 3,200 after (+78 new in five files, −1 in `test_admin_safety.py`).

- `apps/admin_helper/tests/test_l16_equivalence.py` (22): for every registry entry, the console POST
  and the helper's prepare-and-confirm run from the same starting point and are compared **row for
  row** with `l16_support.effect`: the change in every table's row count, every audit row
  (action, actor, target, before, after, reason, reference), and the watched tables in full. The
  only differences, by design, are `AdminNote.via_helper` and the marker in the audit metadata,
  which is asserted on its own. `payout.retry` runs on the Stripe test harness.
- `test_l16_api.py` (19): the permission matrix per entry and role against the plan's gates; a read
  key on every method of `actions`; strict bodies; gate before lookup; the console's refusals
  refused; repeat and 409; finance tables identical after preparing a refund; a prepared change
  cannot run through any helper endpoint with any key; the scripted client that obeys an instruction
  planted in a dispute description and ends with only a `waiting` row; a change key at 29 min 59 s
  and at 30 min; `GET actions` and its filter; guide and tasks per key; switch off.
- `test_l16_confirm.py` (24): confirm and its audit; confirm locks the change row and never a key,
  and a refund's payment before its basis (the SQL is checked); the reason rules; another admin
  (404); no second step; twice; expired; the record changed; no longer offered; a different fresh
  dispute preview; a role downgrade; a service refusal and a finance refusal (failed, not an
  error); a refund reason already used; no marker on the next console action; reject; the expiry
  job, deferred when early, and its re-run; key stops (own, Super Admin, two-step reset, switch,
  a replaced key's changes included for the last two, nothing revived when switched back on)
  against replaced and naturally expired keys; read only when switched off, reject included; page
  content; work list item; change key creation behind a fresh code.
- `test_l16_coverage.py` (4): every console POST route is in `CONSOLE_POSTS` or `NEVER`, with no
  overlap and no stale name; every registry code is on a console page; no `check` or `run` calls a
  model's `save` or `update`; every entry has a task.
- `apps/admin_panel/tests/test_l16_notes_and_ban.py` (9): notes on each page, audited, append only,
  validated, gated by the page permission, never in a member payload; ban and restore with a reason,
  nothing else changed, tokens refused; a ban page left open never does the opposite; staff and
  oneself refused; only `manage_users`.

Rewritten tests (each named in the pull request):

- `apps/accounts/tests/test_admin_safety.py`: the three tests proving the bulk ban asked for a second
  click became two proving there is no bulk ban and the flag is read only (the action was removed).
- `test_l15_api.py::test_the_guide_names_what_this_admin_may_read`: the queues now include
  `helper_changes`.
- `test_l15_api.py::test_each_task_starts_on_a_console_page_with_real_capabilities`: no longer
  asserts `task.action is None` (the field became `actions`).
- `test_l15_keys.py::test_the_card_offers_a_read_key_and_none_exists` became
  `test_the_card_offers_both_keys_and_none_exists`.
- `test_l14_two_step.py`: the frozen route inventory gains `admin-helper-actions`.

ruff and `makemigrations --check` clean; `schema.sql` re-exported (the two new tables with their
constraints and indexes, and pg_dump's `\restrict` lines, nothing else).

## 12. Screenshots

`/mnt/project-files/l-series-screens/L16/`, console in English (keys redacted in every image):

- `overview-worklist-waiting-en.png`: Overview with "Changes waiting for your confirmation" among the
  raised items (count only, today).
- `overview-helper-both-keys-en.png`, `overview-helper-both-keys-narrow-en.png`: the card with a live
  read key and a live change key, each with Stop key, and both Create buttons (wide and 390 px).
- `overview-helper-issued-change-en.png`: the one-time line right after creating a change key, with
  its expiry time.
- `ai-helper-page-waiting-en.png`, `ai-helper-page-waiting-narrow-en.png`: Waiting for your
  confirmation (refund, dispute resolution with its amounts, ban, journey pause), each with the
  server's summary, record link, assistant's reason box, Review and confirm and Reject; Your recent
  decisions; keys and calls (wide and 390 px).
- `change-refund-waiting-en.png`, `change-refund-waiting-narrow-en.png`: the change page for a
  refund: values in words, reason box, the admin's own reason pre-filled, Confirm and Reject.
- `change-dispute-resolve-waiting-en.png`: a dispute resolution with the freshly computed amounts and
  the note saying so.
- `change-ban-no-longer-applies-en.png`: a ban prepared, then the account banned on the console: "This
  no longer applies: this account is already banned."
- `change-journey-confirm-done-en.png`: right after Confirm: the message, the outcome and the admin's
  reason.
- `change-job-confirmed-en.png`, `change-review-rejected-en.png`: decided changes, read only.
- `ai-helper-page-off-en.png`, `change-refund-off-en.png`: the helper switched off: every waiting
  change expired with "The AI helper was switched off.", keys shown as stopped by the switch.
- `deal-notes-default-en.png`, `deal-notes-narrow-en.png`, `dispute-notes-default-en.png`,
  `person-notes-default-en.png`: internal notes on each page, one marked "Added by their AI helper",
  and the form.
- `person-header-ban-en.png`, `person-header-restore-en.png`: the person page header with Ban account,
  and with Restore account once banned.
- `person-ban-default-en.png`, `person-ban-default-narrow-en.png`, `person-restore-default-en.png`:
  the ban and restore pages, naming the person, with a required reason.
- `person-ban-staff-refused-en.png`: a staff account: the page says why and offers no form.

## 13. Second review (plan 1.6)

An independent reviewer (a fresh session that had not written the code) read the whole diff for
races, authorization, idempotency and money. Nothing was found in authorization (every query is
the admin's own, permission fresh at prepare and confirm, two-step on confirm, read key refused,
no helper route to confirm), in the dispute money preview (computed under the deal lock inside the
confirm), in payout retry (`state_version` enforced), in the audit marker's reset, in member text
(it can only reach the two direct actions) or in scope. Its findings, all fixed in this pull
request with a test each:

1. **Deadlock between confirm or reject and a key stop** (should fix). The change row was locked
   with `select_related("key")`, so Postgres locked the key row too, in the opposite order to key
   stops and prepares. Now `FOR UPDATE OF` the change's table only (the SQL is asserted).
2. **A ban page left open could do the opposite** (should fix). The page decided ban or restore
   from the state at POST time: a colleague's ban first, or a double submit, restored the account
   with the ban's reason. The page now posts what it offered and the service refuses it unchanged.
3. **A refund for a reason already used reported an amount that never moved** (should fix). The
   refund service answers a repeated payment and reason with its existing refund (and revives a
   failed one). The helper now refuses that case and reports the refund the service returned. The
   console's own refund form keeps this older behaviour (section 15).
4. **Reject worked with the switch off** (minor): now refused like Confirm.
5. **A replaced key's changes survived a switch-off or a two-step reset** (minor): both now expire
   every waiting change in their scope, so switching back on revives nothing.
6. **An expiry job run early counted as done** (minor): it is now deferred (`JobDeferred`), the
   project's convention for early runs.
7. **A finance refusal while confirming a job decision was a 500** (minor):
   `FinanceOperationsError` is now a domain refusal, so the change is marked failed.
8. **A refund's basis was read before the payment was locked** (minor): confirm now takes the
   refund service's first lock (the payment) before comparing the basis.
9. **Direct actions are not idempotent** (minor): a retried `note.add` adds a second note. Kept as
   a known limit (section 15).

## 14. Judgment calls

Settled with the advisor on 2026-11-14 and written into plan L16 (commits `b94473e`, `5927e8a`):
the audited `set_account_ban` replacing the bulk action; the basis compared at confirm; repeat and
409 for a second prepare; early key stops expire changes, replaced and expired keys do not; notes
never in a helper payload; console actions moved unchanged into `staff_actions.py`; the audit
context reset after each run; the dispute preview compared at confirm; the refund's typed reason in
metadata; `problem.acknowledge` on `manage_disputes`; a two-step-verified session, not a fresh code,
to confirm; the work list item, count and link only.

Smaller calls made while building, kept for Ismail's end review:

1. `ban_state` is shown read only in the technical admin, with a line pointing to the person page.
2. `dispute.set_status` refuses moving a dispute to the state it is already in (the console form
   offers only other states).
3. Notes on a person are gated by the People page's own capabilities (`PROFILE_CAPABILITIES`).
4. `tasks[].action` became `tasks[].actions` (a task can cover several actions); new tasks
   `ban_account` and `add_note`.
5. An expiry writes no audit row; a refused confirm writes `ai_helper.action_failed`.
6. "Finance tables byte-identical" excludes `ScheduledJob`, which holds the expiry job; the test
   checks that job is the only new one.
7. A confirm refused because the admin's role no longer allows it also marks the change failed.
8. A repeated identical prepare answers `200` with `"repeat": true` (a new one answers `201`).
9. `GET actions` shows a waiting change past its time as `expired` before the job closes it.
10. A note through the helper also needs a `reason`, like every action.
11. A key stop's audit row carries `changes_expired`; the two-step reset's own row does not (its
    keys' stop rows do).
12. Closing a problem report and the payout page's manual dinar steps, Stripe re-read and Finance
    hold are on `NEVER_ON_PAGE`; bulk job decisions, adding a sea crossing and finance exports are on
    `NEVER`.
13. The registry field for the job sentence is `who_decides` (plan 2.11 forbids the key `notes` in
    helper payloads).
14. The work list item is shown to every admin with `view_dashboard` (each sees only their own
    changes) and is a count only.
15. The change key is created behind a fresh two-step code, like the read key (`issue_key`).
16. A change page whose record changed shows the warning but keeps Confirm, which checks again under
    the lock and then marks the change failed.
17. Waiting changes show on the work list and the AI helper page, not again on the card (this also
    keeps the overview within its query budget of 22).
18. The change page's heading is the first clause of the registry's description ("Ban a member's
    account"); the server's summary below it says the rest.
19. A two-step reset or a switch-off expires every waiting change in its scope, a replaced key's
    included (second review, item 5); only a stop of one key by its admin or a Super Admin is
    limited to that key's changes, and a replacement or natural expiry leaves them.
20. `refund.request` is refused when the payment already has a refund for the same reason, instead
    of reporting an amount the service would not move (second review, item 3).
21. With the switch off, Reject is refused like Confirm (the list is read only).
22. The ban page posts the state it offered; a page left open while someone else banned or restored
    the person changes nothing and says so.

## 15. Known limits

- A direct action is not idempotent: an assistant that retries `note.add` after a lost answer adds
  the note twice (notes are append only; the audit log shows both).
- The console's own refund form, asked twice for the same payment and reason, answers with the
  refund that exists (reviving a failed one) and shows success. This predates L16 and the console
  form was moved unchanged; the helper refuses that case instead. A finding for the end review.
- A direct action already past the key check when its key is stopped finishes (as L15's reads do);
  preparing re-checks the key under its lock.
- A change whose target was deleted can only be rejected or left to expire; confirming it fails with
  "the record no longer exists".
- The expiry job runs on the job runner's schedule; until it runs, every reader treats a waiting
  change past its time as expired, and confirm closes it.
- Console English only, like the rest of the console.
