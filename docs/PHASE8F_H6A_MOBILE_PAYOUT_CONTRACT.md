# Phase 8F-H6A — Mobile payout contract

Contract `h6a.v1`; starting main `7c3d55154cebde5b381844231cb6ce80a67ae72c`.
This is Gemini H6B's implementation authority. All `/api` routes below require
authentication and derive ownership from the principal. No schema, migration,
financial policy, provider execution or Flutter implementation is added.

## Methods and preference

`GET /api/payouts/methods` is the single summary. Existing `methods` and
`policy_version` remain. Legacy `execution_enabled` is deprecated and must never
be used as an action gate. New response fields:

```json
{
 "contract_version":"h6a.v1","preference":"both","preference_required":false,
 "revisions":{"EUR":2,"DZD":3},
 "eur":{"state":"ready","ready":true,"blocking_reason":null,
        "available_actions":["refresh","manage_eur"],"country":"FR",
        "supported_countries":["FR"],"supported":true,"checked_at":"2026-09-11T12:00:00Z"},
 "dzd":{"state":"pending_review","ready":false,
        "blocking_reason":"payout_profile_under_review",
        "available_actions":["replace_dzd_profile"],"country":"DZ","supported":true,
        "profile":{"reference":"<UUID>","review_state":"pending_review",
                   "ccp_last_four":"7890","rip_last_four":"1234","submitted_at":"2026-09-11T12:00:00Z"},
        "replacement_scope":"future_payouts_only"},
 "available_actions":["refresh","manage_eur","replace_dzd_profile"],
 "preference_scope":"future_payouts_only"
}
```

Preference is exactly `eur_only`, `dzd_only`, `both`; null means neither is
configured and `preference_required=true`. Never invent a default in that case.
Readiness is separate from preference; support is country/deployment support,
not permission to execute money.

`PATCH /api/payouts/methods` atomically updates both preferences:

```json
{"preference":"both","eur_revision":2,"dzd_revision":3,
 "country":"FR","consent_policy":"payout_profile_v1"}
```

Use GET revisions (zero initially). Country may be omitted when an existing EUR
version supplies it; initial EUR selection requires a supported legal account
country. Any revision/country failure rolls back both changes. Refetch on error.
The old per-currency POST remains: `currency`, `enabled`, `expected_revision`,
`country`, `consent_policy`.

EUR only selects eligible EUR Stripe routing; it never enables non-Stripe EUR
funding. DZD only selects eligible manual DZD routing. Both locks Stripe funding
to EUR and Chargily funding to DZD. Examples use the same PATCH with respectively
`eur_only`, `dzd_only`, or `both`. Every funded payout has exactly one snapshotted
rail. Preferences affect future payouts only; the client cannot select a rail
for an already-funded Deal.

## Method states and actions

EUR states: `not_configured`, `setup_required`, `pending_verification`, `ready`,
`needs_attention`. H2 `evaluate_readiness` remains authoritative; pending review
maps to pending verification, unavailable/disabled/held accounts need attention.
DZD states: `not_configured`, `setup_required`, `pending_review`, `ready`,
`needs_attention`, `inactive`. H4 evidence, review and current identity validity
decide readiness; masked digits do not.

| Action | Client behavior |
|---|---|
| `configure_eur` | Collect legal account country/consent, enable preference if needed, request onboarding |
| `resume_eur_setup` | Request a new authenticated onboarding link |
| `manage_eur` | Request Stripe dashboard access |
| `configure_dzd` | Enable preference if desired, upload cheque and submit profile |
| `replace_dzd_profile` | Upload fresh proof and create a new profile version |
| `view_payout` | Open owner-only payout detail |
| `refresh` | Refetch the current surface; EUR method card uses Stripe refresh POST |

Actions are revalidated on execution. Never show execute, mark sent/paid,
Finance receipt, reverse or release-hold controls to Travelers. H6B entry point:
**Profile → Payout methods**, with EUR/DZD cards and preference selector. Home
can link to that destination.

## Stripe-hosted flow

| POST endpoint | Input | Response |
|---|---|---|
| `/api/payouts/methods/stripe/onboarding` | `{}` or `{"country":"FR"}` | 201 `{onboarding_url,expires_at,method}` |
| Same endpoint to resume | `{}` | Fresh short-lived link, same account |
| `/api/payouts/methods/stripe/dashboard` | `{}` | 201 `{dashboard_url}` |
| `/api/payouts/methods/stripe/refresh` | `{}` | 200 `{method}` with `mobile` state |

Only the authenticated owner receives URLs. Responses are private/no-store;
URLs are not persisted, logged, emailed, pushed or put in history. Flutter
temporarily holds the returned URL to open it, never constructs one, and never
collects Stripe bank/KYC data. Returning does not mean success: refresh state.
H2 signed return-state and ownership checks remain. Legacy `account_reference`
is null; provider account identifiers are not mobile data.

## DZD profile contract

Exactly six product inputs: first name, last name, CCP account number, CCP key,
RIP, full crossed-cheque image. **No NIP field is accepted or added.**

1. `GET /api/payouts/profiles/dzd` returns `{method,dzd}`. Method is null before
   configuration; otherwise it is the legacy safe projection plus `mobile`.
2. `POST /api/payouts/proofs`, multipart `image`, returns 201 `{reference,labels}`.
   JPEG/PNG/WebP; maximum 8 MiB, 20 million pixels, single frame, validated MIME
   and signature. Existing private encrypted storage remains.
3. `POST /api/payouts/profiles/dzd` creates/replaces, returning 201 method:

```json
{"expected_revision":3,"first_name":"Example","last_name":"Traveler",
 "ccp_number":"1234567890","ccp_key":"12","rip":"12345678901234567890",
 "proof_reference":"<fresh owned proof UUID>","consent_policy":"payout_profile_v1"}
```

CCP: 1–20 normalized digits; key: exactly 2; RIP: exactly 20. Names: required,
maximum 160 characters. Sensitive values are write-only. Replacements require
fresh owned proof and create immutable versions with pending review. Historical
payouts stay bound to their funded version. Current setup changes do not repair
or repoint old instructions; explicit Finance amendment stays H1/H4 authority.

| Language | Exact proof label | Exact helper |
|---|---|---|
| FR | Photo du chèque barré complet | Téléversez une photo claire du chèque barré complet. |
| AR | صورة كاملة لشيك مُسطَّر | حمّل صورة واضحة وكاملة للشيك المُسطَّر. |
| EN | Photo of the full crossed cheque | Upload a clear photo of the full crossed cheque. |

## History, detail and authoritative states

`GET /api/payouts?page=1&page_size=30` returns `{count,next,previous,results}`;
maximum page size 100. Without pagination parameters, retain the legacy array,
bounded to 100 latest items. Items retain old safe fields and add `mobile`, the
normalized object below. `reference` now returns the public payout UUID instead
of free-text settlement reference, which could contain provider/operator data.
Use `id` for legacy identity and `mobile.reference` for detail.

`GET /api/payouts/<public UUID>` returns the normalized object directly; other
users receive 404. `GET /api/deals/<id>` adds one `payout_summary` for its Traveler;
other viewers receive null. Existing shared `protection` fields remain. No
history is duplicated in Deal responses.

```json
{
 "reference":"<UUID>","deal_id":42,"rail":"manual_dzd",
 "settlement_currency":"DZD","amount_eur_cents":6000,
 "dzd_amount":15600,"fx_rate_micros":260000000,
 "state":"eligible","display_state":"ready","message_key":"payout.ready",
 "protection_active":false,"protection_ends_at":"2026-09-11T10:00:00Z",
 "server_time":"2026-09-11T12:00:00Z","eligible_at":"2026-09-11T10:00:01Z",
 "blocking_reason":null,"available_actions":["view_payout","refresh"],
 "updated_at":"2026-09-11T10:00:01Z","sent_at":null,"paid_at":null,
 "destination_scope":"funded_snapshot"
}
```

EUR example: `rail:stripe_eur`, `settlement_currency:EUR`, `dzd_amount:null`,
`fx_rate_micros:null`, same canonical EUR cents/state vocabulary. Unknown legacy
routing uses `rail:unavailable`. Both preferences never create a per-Deal selector.

| Display state | Meaning |
|---|---|
| `awaiting_delivery` | Delivery not confirmed |
| `protection_active` | Stored protection deadline still ahead |
| `release_pending` | Protection elapsed; server has not released payout |
| `ready` | Eligible/scheduled and projected destination/hold gates clear |
| `processing` | External execution or Finance processing started |
| `sent` | In transit/sent, not settled |
| `paid` | Authoritatively settled |
| `needs_attention` | Failed/returned/blocked/disputed/held/setup issue |
| `cancelled` | Cancelled obligation |

Raw `state` retains the existing Payout enum. Use `display_state` for rendering.
Recorded sent/paid facts remain visible even when a later hold stops new work.
An elapsed timer alone never proves eligibility; ready does not bypass execution
flags. Protection remains the existing 48-hour policy, with server time/deadline.

### EUR bank stage: what decides `sent`, `paid` and `returned`

The EUR settlement fact comes from H3's **bank disbursement**, never from the
platform Transfer or its `PayoutAttempt`. A Transfer only moves ShipTrip's money
into the connected account's Stripe balance; the Traveler is paid when the bank
payout reaches `paid`. The two fail independently, and when a paid bank payout is
later returned, H3 hands the money back to the connected account and puts the
attempt back to `accepted` — so an attempt-derived reading cannot express
`returned` at all and would keep showing money the Traveler no longer has.

The current bank stage is the payout's active `StripeDisbursementAllocation`, or
its most recent allocation when none is active: a returned or failed bank payout
releases its allocation, and an operator's audited bank-only retry binds a newer
disbursement over the top. Multiple allocations are therefore normal history.

| `StripeDisbursement.status` | `display_state` | `blocking_reason` |
|---|---|---|
| none yet (no allocation) | from the Payout state alone | — |
| `planned`/`committed`/`unknown`/`pending` | `processing` | null |
| `in_transit` | `sent` | null |
| `paid` | `paid` | null |
| `failed`/`canceled` | `needs_attention` | `payout_failed` |
| `returned` (paid, then returned) | `needs_attention` | `payout_returned` |

A returned or failed bank stage outranks every local status, including a `paid`
the same disbursement recorded earlier. The historical movement is preserved:
`paid_at` keeps its original value, raw `state` is the restored `failed`
obligation, and H3's ledger compensation is untouched. The client renders this;
it never recomputes it and never infers a return from timestamps.

Blocking codes: `payout_setup_required`, `payout_profile_under_review`,
`payout_profile_needs_attention`, `protection_active`, `payout_on_hold`,
`dispute_active`, `payout_failed`, `payout_returned`; country state uses
`payout_country_unsupported`. Unknown internal blockers become `payout_on_hold`.
No raw exception, requirement payload or operational prose is exposed.

History rendering is bounded: dispute, Finance-hold, connected-account-hold and
current-setup facts are read once per page, and DZD profile verdicts are memoised
per profile revision, so a 100-row page costs the same queries as a 1-row page.
Clients may page freely; they must not fan out to the detail endpoint per row.

Money is stored integer authority: EUR 60.00 × frozen 260 remains 15,600 DZD.
Flutter formats values/countdowns; it must never calculate FX, settlement
amounts, readiness, eligibility, routing, protection policy or financial actions.

## Notifications, privacy and localization

Reuse `payout.status_changed` and existing event values `eligible` (ready),
`setup_required`, `processing`, `sent`, `paid`, `needs_attention`, `returned`.
Add `profile_ready` and `profile_needs_attention` on that same channel.
Existing delivered notifications represent protection start; no competing event.
`returned` is emitted only by H3's bank-return reconciliation, carrying
`message_key: payout.returned`; every other bank failure emits `needs_attention`.

Payout payloads have existing allowlisted Deal resource IDs, safe status/event,
public `payout_reference`, and `message_key`. Profile events have only event,
key and currency. Existing envelope: event_id, ts, targets. Never bank/CCP/RIP,
evidence URLs, amounts, connected account/Transfer/bank Payout IDs, hosted URLs,
raw failures or private Deal contents. FCM retains generic safe EN/FR/AR payout
update copy and its strict resource-ID allowlist. Taps refetch with authorization.

Notification rows now commit with opted-in payout business facts. Deterministic
event UUIDs use payout reference/state version/event and existing recipient/event
uniqueness. Replay cannot create duplicate obligations; rollback removes them.
WebSocket/FCM use the same ID after commit. Profile events notify on meaningful
status changes. No second notification subsystem or new financial state exists.

Existing `GET /api/notifications`: 30 default, 100 maximum; channel, event_id,
payload, created_at and read_at. Existing read/unread APIs stay owner-scoped.
Email remains disabled with existing durable email obligations preserved.
Transport limitation: a commit/callback crash may miss push/WS delivery, but the
new payout inbox row survives. Existing transport detection/retry is unchanged.

| Key | EN | FR | AR |
|---|---|---|---|
| `payout.setup_eur` | Set up EUR payouts | Configurer les versements en EUR | إعداد التحويلات باليورو |
| `payout.setup_dzd` | Set up DZD payouts | Configurer les versements en DZD | إعداد التحويلات بالدينار الجزائري |
| `payout.protection_active` | Protection period | Période de protection | فترة الحماية |
| `payout.ready` | Payout ready | Versement prêt | التحويل جاهز |
| `payout.processing` | Payout processing | Versement en cours | التحويل قيد المعالجة |
| `payout.sent` | Payout sent | Versement envoyé | تم إرسال التحويل |
| `payout.paid` | Paid | Payé | تم الدفع |
| `payout.needs_attention` | Needs attention | Action requise | يلزم اتخاذ إجراء |
| `payout.returned` | Payout returned | Versement retourné | أُعيد التحويل |
| `payout.profile_ready` | Payout method ready | Moyen de versement prêt | وسيلة التحويل جاهزة |
| `payout.profile_needs_attention` | Method needs attention | Moyen de versement à vérifier | يلزم التحقق من وسيلة التحويل |
| `payout.release_pending` | Awaiting release | En attente de déblocage | بانتظار إتاحة التحويل |
| `payout.awaiting_delivery` | Awaiting delivery | En attente de livraison | بانتظار التسليم |
| `payout.cancelled` | Payout cancelled | Versement annulé | أُلغي التحويل |

Flutter owns translation/RTL/polish in H6B. Method keys may use
`payout.method.<currency>.<state>`; reason keys `payout.reason.<blocking_reason>`.

## Errors and deferred work

Safe DRF field errors reject unknown fields. Existing domain codes remain:
`payout_profile_invalid` (400, including revision conflict),
`payout_country_unsupported` (400 with supported countries/DZD alternative),
`stripe_connect_unavailable` (409), `stripe_connect_provider_error` (502),
`payout_setup_invalid` (400) or existing safe domain code,
`payout_evidence_unavailable` (503). No raw Stripe/DB errors.
Auth: 401/403; unowned resource: 404; throttle: 429; disabled profiles: 404.

H6B owns UI, entry points, forms and state presentation. Active Sending placement
of completed deliveries remains an I1 lifecycle concern; this phase does not
change that list or arrival/delivery guardrails. No browser work was performed.
