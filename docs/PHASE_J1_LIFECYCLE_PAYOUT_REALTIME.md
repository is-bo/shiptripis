# J1 — Lifecycle correctness, payout setup and realtime foundations

Implementation checkpoint, 2026-09-14. **Not released; Gemini verification, CI and TEST deployment remain gates.**

Starting main: `f68731f4203a05fb5e64a7bdad3aa0a80b530bae`.
Branch: `codex/j1-lifecycle-payout-realtime`.
User reproduction: latest APK, Both account mode. The latest local owner artifact
is `ShipTrip-TEST-f68731f.apk`; its build manifest names that starting SHA and the
current TEST origin. An obsolete APK is not an established explanation.

## Evidence and scope

Read-only deployed checks used the existing Railway ShipTrip service, release
`v1.0.0-rc.30+4ec23a1`, deployment `a400f0d4-e4cd-4b85-9817-35ab03f79e35`.
The environment is named `production` in Railway but `PAYMENTS_ENVIRONMENT=test`.
No deployment, provider account creation, bank execution, financial transaction,
LIVE activation or environment change was performed. Local payment providers,
bank documents and settlement tests are synthetic fixtures only.

| Reported issue | Established evidence | Implementation / remaining proof |
| --- | --- | --- |
| EUR/Both preference error | Deployed mobile-shaped PATCH without country returns 400 `payout_country_unsupported` for initial setup; GET returns 200. | Ask for an explicitly selected legal country from the server's supported list, submit country and freshly read revisions. |
| DZD error | Same deployed rollback-only DZD preference PATCH returns 200; DZD GET and public authenticated HTTP GET return 200. | Refresh revisions before submission; field-specific digit validation. The user's blanket DZD failure is not reproduced. |
| Stripe state | Onboarding/refresh return `method.mobile`; mobile decoded `method` as the mobile projection. | Decode the nested projection; preserve hosted URL handling and server readiness. |
| Expired Journeys | Three stored-active deployed Journeys have every arrival in the past. Stored status alone was the browse filter. | Derive inventory/lifecycle in SQL before filtering/limiting, with time checks retained under offer locks. |
| Dispute action | Client inferred permission from coarse lifecycle. | Detail returns `available_actions`; `open_dispute` uses the service's party/window/prior-dispute rules. |
| Rating prompt | Existing widget retained its question heading after `submitted=true`. | Submitted heading; explicit server rating states; one-shot detail refresh at server deadlines. |
| Home completed items | Deployed data: seven completed, one active, zero delivered rows satisfying the active predicate. Home already requests `activity=active`. | Preserve existing authoritative filtering; no speculative status rewrite. Reported device stale state remains to be reproduced. |
| Missing route | Active deployed Deal has a funded route. Seven older completed Deals have no frozen route and use legacy live-Journey fallback. | Preserve funded projection; remove unsupported historical live fallback. Exact active-device rendering failure remains unconfirmed. |
| Push | Public HTTP inbox/badge 200; authenticated raw TLS WebSocket handshakes 101 at both `/ws/chat` and `/ws/notifications`. FCM enabled and credential project matches. Zero active devices, two inactive Android records. | Committed inbox plus durable retry obligation. Real device re-registration/receipt remains required; server transport cannot deliver to no registered device. |
| Chat refresh | Existing open-chat widget already supports pre-ACK display and inbound delivery; focused test passes. Server omitted sender target and had no client retry identity. | Add UUID retry/echo protocol and preserve existing optimistic controller. Original on-device failure is not yet reproduced end to end. |

Deployed preference probes used authenticated Django views with provider I/O
forbidden and an outer transaction explicitly rolled back. They prove contract
responses, not durable user preference changes or provider onboarding success.
Public HTTP checks additionally verify gateway/auth/JSON/no-store behavior.
Raw protocol handshakes are not a browser and do not prove message receipt.

## Payout contract

H6A version and fields remain compatible. Preferences are `eur_only`, `dzd_only`,
`both`; a new EUR preference requires a legal country, never guessed from UI
locale or app role. Setup now enables the required preference before hosted
onboarding, preserving DZD when adding EUR. Setup, resume, manage and refresh
continue to use server actions. Fresh GET revisions prevent a loading/error
screen from silently submitting revision zero for an existing method.

Stripe responses retain hosted URL `no-store` behavior; the mobile method lives
at `method.mobile`. There is no IBAN field, provider identifier exposure or
frontend readiness calculation. DZD retains exactly six product inputs, no NIP,
encrypted evidence, masked output, immutable revisions, and review authority.
Malformed CCP/key/RIP returns field errors without echoing sensitive values.
Preference edits still affect future routing only; funded instructions are
unchanged. Local H6A tests cover EUR/DZD/Both, auth, Stripe synthetic setup,
resume/manage/refresh and DZD evidence/replacement/review.

## Journey lifecycle

`apps.trips.lifecycle.with_lifecycle` projects status without rewriting historical
rows. Explicit draft, verification, cancelled, completed and expired statuses
retain precedence. For active/in-progress rows:

* A later leg departure is usable inventory even when the first leg has passed.
  Legacy schema-1 DRIVE matching can pick up along a leg until arrival; canonical
  node matching retains its departure semantics.
* A funded pickup or stored `in_progress` is evidence of travel begun. It reads
  `in_progress` until all known leg arrivals have passed, then `completed`.
* Without travel evidence, no remaining usable inventory and no active funded
  dependency reads `expired`. Natural expiry is never cancellation.
* An active funded dependency can retain its Journey status while new discovery
  excludes elapsed inventory. No funded Deal, allocation or snapshot is deleted.

Owner status filters use the derived value. Public browse/detail and sender
discovery exclude elapsed inventory before pagination/candidate limits. Existing
compatibility re-evaluates pickup time during offer creation/acceptance under
locks. In-progress Journeys can sell legitimately remaining carrying segments.
No ranking, route-fit, capacity model or J4 projection redesign is included.

## Delivery actions, activity and route

`available_actions` currently adds `open_dispute` only for a participant who can
open a new dispute. The existing POST remains authoritative, including idempotent
retrieval of an existing dispute after the window. Existing disputes stay visible.
The 48-hour opening deadline and the scheduled-arrival payout floor remain
different facts. J1 does not release or reschedule payout.

Ratings add `available`, `submitted_waiting`, `revealed`, `expired`, `unavailable`.
Submitting removes `can_rate`; blind counterpart content remains absent until
both submit or the frozen reveal period passes. Legacy deadline SQL uses the
same frozen duration/default as rating submission. Mobile refreshes detail once
at the next server-issued protection/rating deadline, not by periodic polling.

Home and Deliveries Active use backend `activity=active`; History uses completed
classification. Delivery confirmation outranks ongoing protection, payout or
ratings. Refund/cancellation precedence is unchanged. The existing tests cover
this authority and the repository query contract.

Funded route is participant-only, ordered, limited to allocated snapshot legs,
public canonical/coarse endpoints, mode and schedule. No proof, capacity,
provider/payment metadata, other Journey legs or exact private location is added.
Pre-I1 Deals without historical route evidence return `route: null`; current
allocations do not establish the historical booked route. This supersedes I1A's
live-Journey historical fallback. New funding still freezes route atomically.

## Notifications: transport and resolution

For targeted events, inbox rows and one `ScheduledJob(notification_dispatch)`
commit with the underlying event. Rollback leaves neither. After commit, transport
tries promptly; a pending job at +30 seconds recovers callback/Redis failures
through the existing DB worker, retry/backoff, stuck-job recovery and exhaustion
monitoring. FCM enqueue and WebSocket publish are attempted independently. A
transport error does not change committed money or leak tokens/provider errors.
PublishedEvent remains the audit receipt. Sender chat echoes do not create sender
inbox rows or push.

Delivery is at least once: consumers reconcile by event/message identity. A
successful Redis enqueue is not an end-device receipt, and complete Redis loss
after successful enqueue still requires inbox/chat catch-up. No claim of
exactly-once push or guaranteed device receipt is made.

`GET /api/notifications?bucket=active|history|all` defaults to active. The
owner-scoped server projection filters before pagination. `resolved` is separate
from `read_at`: read active actions remain active; unread resolved actions go to
History. Payment, arrival confirmation, recipient, delivery code, rating,
dispute, chat and pending-offer conditions derive from their owned entities.
Informational notifications resolve when viewed. Neutral `deal.updated`
invalidations belong in History immediately.

Funded payout setup events follow Finance's frozen-instruction blocker
projection, never current preference. Profile-only attention follows the
corresponding current currency's readiness. Historical/malformed identifiers
cannot bypass ownership or cause unchecked casts. Non-Deal payment events retain
informational behavior rather than being discarded by a Deal-only predicate.

Badge response exposes `active` and `unread_active`; legacy `unread` aliases
**active**, for installed clients. Mark-read does not resolve a live action.
History retains original rows/payloads. Mobile adds a minimal History entry and
requests the server bucket; larger navigation/pagination polish belongs to J3.

Push diagnosis: inactive devices last seen September 8; one has success recorded
September 7, one failure September 9. No raw device token was printed, altered
or reactivated. Credential alignment and WebSocket availability are established;
foreground/background real-device receipt and deep-link operation remain a
post-install verification requirement.

## Chat protocol

POST messages accepts optional UUID `client_message_id` for backward
compatibility. The unique key is `(match, sender, client_message_id)`. The Match
lock serializes sequence allocation/commit and eligibility. First send: 201;
same UUID/body retry: 200 with the same persisted row; conflicting body: 409
`chat_idempotency_conflict`. Membership and paid-conversation gates remain.
GET, ACK and event include the UUID. Broadcast targets both participants.

Mobile generates a cryptographic UUID before sending, shows the local pending
message, retains that UUID for retry, reconciles own echoes and ACKs to one
persisted message, and retains failed sends for retry. Reconciliation uses the
independent HTTP cursor, so a higher ACK does not skip lower inbound messages.
Existing latest/before/after history, reconnect catch-up and pagination remain.
Go relays the raw authorized payload without interpreting message identity.

## Schema, review and verification

Additive migrations:

* `chat.0003_chatmessage_client_message_id_and_more`: nullable UUID and composite
  unique constraint; legacy NULL rows remain valid. Index creation can lock the
  chat table during migration; assess volume before a future non-TEST rollout.
* `finance.0025_alter_scheduledjob_kind`: notification dispatch enum choice.

Exported `backend/contracts/sql/schema.sql` from the migrated local PostgreSQL
schema database. SQL query directories remain empty, so the repository's sqlc
generation rule is an explicit skip; Go raw contracts are tested. No protobuf
contract changed. Deployment must apply migrations before new code; rollback
code must retain support for pending notification jobs or drain them first.

Focused evidence at implementation time: J1 backend 10 selected tests pass;
H6A preference/setup/refresh and DZD replacement tests pass; J1 mobile country
and nested decoding tests pass; chat optimistic widget and controller tests
pass; Go targeted routing tests pass (0.529s). Ruff and targeted Dart analysis
pass. The only shown Django warning is the existing Django 6 URLField default
deprecation. Final commands/results are recorded in the verifier handoff.

Reviewed owner boundaries, immutable money routing, retry/commit ordering,
delayed-job persistence, route privacy, additive migration recovery, and
candidate filtering before limits. No subagents or browser automation used.
Broad Django/PostgreSQL, Flutter, Go integration and APK builds are delegated
to the user-run Gemini verifier at an immutable SHA, with no source changes.

## Remaining release gates and J3 work

Gemini verification, CI, merge/main synchronization, branch cleanup, TEST
deployment/migrations/workers, health/ready probes and read-only H5 integrity /
zero-difference reconciliation are **pending**, not PASS. No CI run was triggered
at this checkpoint. After Gemini passes, trigger CI once, record its link and
stop for the user's result; do not poll. Deployment must keep Stripe/Chargily
TEST and DZD execution false.

BLOCKER for release acceptance: reproduce the reported blanket DZD failure,
stale Home/active route rendering and chat behavior on the installed device;
complete actual device registration/receipt and synthetic authorized chat
send/echo after deployment. The server/widget evidence above narrows these
issues but does not establish all device root causes.

J3 owns fuller notification History/pagination UX, payout error presentation,
country-list presentation, delivery/rating presentation and chat polish.
No J2 pricing/deposit/guest-payer/Boost work or J4 matching redesign was begun.
