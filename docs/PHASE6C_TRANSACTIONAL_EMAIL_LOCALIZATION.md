# ShipTrip V1 Phase 6C — Transactional email wiring and localization

Status: **IMPLEMENTED / EXTERNAL SENDING INACTIVE**

Phase 6C closes the application-level transactional-email gaps identified by
the Phase 6B review. It does not configure a provider, DNS, a production
webhook, or a production process. PostgreSQL remains the obligation store and
real external sending remains disabled until the separate activation runbook.

## 1. Language ownership and fallback

Communication language is an explicit enum with exactly `en`, `fr`, and `ar`.
It is not inferred from request headers, names, domains, countries, or browser
state.

### Authenticated users

`accounts.User.preferred_language` stores the durable preference. New email and
Google sign-ups default to English when the client omits it. Historical rows
remain blank rather than being rewritten with invented intent; a blank or
invalid internal value resolves deterministically to the complete English
catalogue.

The authenticated profile contract exposes the resolved value and accepts:

```http
PATCH /api/me
Content-Type: application/json

{"preferred_language":"fr"}
```

The serializer rejects values outside `en`, `fr`, and `ar`.

### Parcel recipients

`deals.DealRecipient.communication_language` is Deal-scoped because recipients
have no ShipTrip account. `PUT /api/deals/{id}/recipient` accepts the optional
field alongside the existing recipient details. When a new recipient omits it,
the service snapshots the sender's resolved preference onto the recipient row.
An update that omits it preserves the stored choice. Historical blank rows
resolve to English.

This is the only language used for the recipient delivery-code email. The
server never guesses from personal or geographic data.

### Guest payers

The guest-payment rail remains in V1. A guest link snapshots either the
explicit `communication_language` supplied by its owner or that owner's
resolved preference. Guest checkout accepts an `email` used only for a minimal
payment receipt/status message. Once transactional email is enabled, the email
is required before checkout; while sending is deliberately disabled, omission
remains backward-compatible.

The email address grants no User identity, Deal membership, chat, dispute,
location, recipient, or other authority. A guest email contains only a payment
reference, authoritative EUR amount, currency, and public status.

## 2. Outbound locale snapshot

`notifications.OutboundMessage.language` is captured when the logical
obligation is inserted. The existing fields retain their roles:

- `kind` is the template kind;
- unique `key` is the deterministic logical-event key;
- `language` is the rendering-locale snapshot; and
- `context` is the allow-listed, non-secret rendering context.

Changing a User or recipient preference later cannot mutate a queued email.
Re-enqueueing an existing key returns the original row and therefore preserves
both its locale and its original context.

## 3. Localization architecture

English source strings use Django `gettext`. Complete French and Arabic
catalogues live under `backend/monolith/locale/{fr,ar}/LC_MESSAGES`, and the
compiled catalogues are committed for runtime use. `tools/compile_po.py`
provides deterministic, dependency-free catalogue compilation on hosts without
GNU `msgfmt`.

One translated `EmailDocument` feeds both alternatives, covering subject,
preheader, eyebrow, heading, paragraphs, callout, code/highlight label, CTA,
facts, footnote, support text, security text, and transactional footer. Plain
text and conservative table-based HTML therefore cannot select different
locales.

Arabic HTML sets `lang="ar"` and `dir="rtl"` on the document and body, uses
explicit right alignment, mirrors the callout border and fact-row padding, and
does not depend on email-client support for CSS logical properties. Codes and
displayed URLs remain explicitly LTR. EUR amounts use bidi isolation so the
symbol and digits do not reorder. The layout remains image-free, single-column,
table-based, and fully usable when the progressive `<style>` block is stripped.

`ADMIN_INVITATION` remains English for launch, matching the English operations
surface. It is the only deliberate user-facing catalogue exception.

## 4. Authoritative event wiring

| Kind | Authoritative transition | Logical key |
|---|---|---|
| `KYC_STATUS` | locked trust-admin approval or rejection | `kyc_status:{submission_id}:{decision}` |
| `FLIGHT_PROOF_STATUS` | locked trust-admin proof approval or rejection | `flight_proof_status:{proof_id}:{decision}` |
| `SECURITY_EVENT` | successful password-reset confirmation | `security_event:password_reset:{reset_code_id}` |
| `PAYMENT_FAILED` | `PaymentAttempt` becomes actual `failed` | `payment_failed:attempt:{attempt_id}:owner` |
| `REFUND_STATUS` | refund created `pending`, then authoritatively `succeeded` | `refund_status:refund:{refund_id}:{status}:{audience}` |
| `GUEST_PAYMENT` | guest attempt authoritatively fails or succeeds | `guest_payment:attempt:{attempt_id}:{status}` |
| `PROTECTION_ENDING` | delivery confirmation schedules one reminder per party | `protection_ending:{deal_id}:{user_id}:v1` |

KYC and proof retries that repeat the settled decision return without creating
a second obligation. Replayed provider and reconciliation events converge on
the existing deterministic payment/refund keys.

The credential-change message contains only the event type. It contains no
password, reset code, reset token, session token, or recovery material. The
password change commits before transport is attempted; later delivery failure
leaves the new credential authoritative and the message pending for retry. No
separate authenticated password-change endpoint currently exists, so password
reset confirmation is the only supported credential-change hook.

Payment `processing`, local expiry, cancellation, and an abandoned UI do not
produce a failure email. Refund mail states only pending/completed and uses the
authoritative backend cents; it exposes no provider or reconciliation detail.

The protection reminder policy is one message 24 hours before the stored
protection deadline. `PROTECTION_ENDING_REMINDER_SECONDS` defaults to `86400`;
the chosen interval is snapshotted in message context and the dispatch time is
stored in both `OutboundMessage` and its `ScheduledJob`. Opening a dispute
supersedes that reminder and atomically cancels its pending message and dispatch
job, so a disputed delivery cannot receive a stale protection-window prompt.

If a provider first reports a failure and later provides an authoritative success,
any pending owner/guest failure notice is cancelled before the success receipt is
queued. Already-dispatched messages remain immutable history.

## 5. Deliberately unwired kinds

`PAYMENT_PROCESSING` remains unwired because it is transient and non-actionable.
`PAYMENT_REQUIRED`, `PAYMENT_SUCCEEDED`, and `EVIDENCE_REQUEST` remain optional
templates without new callers: immediate in-app state already covers the first
two, while no domain action exists to request more evidence. Existing delivery,
dispute, cancellation, payout, rating, verification, reset, and handover email
paths remain wired as before.

## 6. Delivery-code secrecy and durability

Localization does not alter the secret path:

```text
secret_ref -> trusted final renderer -> selected locale -> SMTP adapter
```

The plaintext delivery code never enters `OutboundMessage.context`, Redis,
`PublishedEvent`, Notification payloads, Deal events, audit metadata, admin,
generic logs, message keys, or error text. Secret-bearing messages continue to
bypass Redis and render only at the trusted provider boundary. English, French,
and Arabic tests drive a real Deal, open the seal only in the renderer, and
assert the code is absent everywhere it is persisted.

Every message still has a PostgreSQL row and durable `ScheduledJob`. Redis is a
transport accelerator for ordinary messages, not the source of truth. Existing
event-ID requirements, Go consumer deduplication, pending-entry recovery, SMTP
receipt handling, retry accounting, and sweeps for lost jobs are unchanged.

## 7. Additive schema and API changes

The four additive migrations are:

- `accounts.0005_user_preferred_language`;
- `deals.0006_dealrecipient_communication_language`;
- `finance.0006_guestpaymentlink_communication_language`; and
- `notifications.0004_outboundmessage_language`.

The PostgreSQL schema contract was regenerated. The sqlc query directories are
still empty, so sqlc generation is an explicit no-op.

Required Flutter follow-up, outside this phase:

1. expose an EN/FR/AR account preference and send `preferred_language` at
   signup/Google signup or through `PATCH /api/me`;
2. add an EN/FR/AR selector when the sender enters recipient details and send
   `communication_language`;
3. optionally expose the same choice when issuing a guest link; and
4. collect the guest payer's receipt `email` in guest checkout.

Until the recipient selector lands, omission remains compatible and snapshots
the sender preference. No Flutter file was modified in Phase 6C.

## 8. Activation and review boundary

No Sender.net credential, SMTP production credential, DNS record, payment
credential, payment-provider activation, or webhook registration was added.
No real external email or payment was sent. Native French and Arabic copy
review and a Gmail/Outlook/Apple Mail/narrow-Android compatibility pass remain
required before production sending.
