# Phase 8F-H1 — payout foundations

H1 implements the dormant backend contracts defined by
[H0](PHASE8F_H0_PAYOUT_FINANCE_ARCHITECTURE.md). Starting local main and
origin/main were `94aad9be50960f47cc73b47033a704effc4101b8`. The uncommitted G3
status entry and H0 architecture/status documentation are preserved in this work.
No provider execution, Connect setup, evidence upload, Finance dashboard or
mobile payout interface is introduced.

**Status (8 September 2026):** the "H2 prerequisites and limits" section at the
end of this document has been acted on by
[H2](PHASE8F_H2_STRIPE_CONNECT_ONBOARDING.md), which implements Stripe Connect
onboarding and readiness behind flags that remain false. Item 1 — rotating the
exposed Stripe TEST secret — is still outstanding and is an owner action.

## Domain and ownership

Django remains the migration authority. `apps/finance/payout_models.py` is
imported by the existing finance models module; it is not another Django app.
Existing `Payout` and `TravelerPayoutMethod` remain authoritative.

| Contract | H1 behavior |
|---|---|
| TravelerPayoutMethod | Explicit currency/enabled preference, separate review/readiness status, revision conflict detection and current immutable version. `is_default` and old provider fields remain readable but do not route versioned payouts. Preference toggles preserve readiness. |
| PayoutMethodVersion | Immutable sequence, rail/currency/country, destination reference, policy consent, actor/time and content hash. Future edits produce versions. |
| StripePayoutAccount | Local provider identity, platform and mode, country, safe capability/bank/readiness projections and generation. One active account per traveler/platform/mode. No raw Account, bank number, Account Link or credentials. |
| DzdPayoutProfileRevision | Encrypted given/family names, CCP number, two-digit CCP key and 20-digit RIP/NIP; masks, independently keyed account fingerprint, review/evidence/attestation references. No IBAN field. |
| Identity attestation | Finance assigns a scoped approved-KYC review. An authorized assigned Trust reviewer explicitly attests encrypted legal names/aliases. Supersession and revocation are separate immutable history. Editable User names are never legal-name authority. |
| PayoutEvidence / PayoutProfileReview | Reference-only dedicated payout storage contract and append-only review history. Complete evidence upload, review and receipt workflow belongs to H4. |
| PayoutAmountRevision | Original/current EUR obligation and settlement amounts remain distinguishable. A settlement references its decision, ledger correction and actor. Award increases above the funded obligation are refused. |
| PayoutInstructionConfirmation / Amendment | Owner records confirmation for an exact destination and state version; Finance requires that record and a reviewed current same-rail destination. Original snapshot remains intact. |
| PayoutAttempt / ProviderOperation | Local prepared intent, immutable request identity, explicit mode, stable idempotency/hash, sequences, account scope and safe result references. No dispatch function or provider request exists in these services. |
| PayoutFundingAllocation | Applied succeeded same-mode source, canonical EUR amount, source charge/purpose and unique replay key. Source/order locks bound allocations against refunds, credited-deposit share and the payout obligation. Allocations cannot be reused in H1; recovery/release belongs to H3. |
| FinanceHold / ProviderDispute | Independent scoped holds with opening/clearing actor, generation and exposure; provider dispute records remain separate from ShipTrip disputes. H1 operator primitives handle their own manual/treasury/compliance holds. Provider ingestion and broader scoped workflows remain later phases. |
| PayoutEvent | Append-only per-payout sequence/UUID, prior/new state, safe reason, actor, operation/evidence/ledger references and occurrence/recording times. H1 sends no new payout notifications. |

## Money, routing and snapshots

Canonical money is always integer EUR cents. Rails are exactly `manual` with
DZD and `stripe_transfer` with EUR; preference names retain existing `manual`
and `stripe_connect` values. Legacy rows are explicitly grandfathered.

| Enabled currencies | Stripe funding | Chargily funding |
|---|---|---|
| DZD | DZD | DZD |
| EUR | EUR | EUR obligation blocked for unsupported funding |
| EUR and DZD | EUR | DZD |
| Neither | Setup required; preserve any captured obligation | Same |

Readiness never picks another currency. Preflight rejects necessarily
unsupported EUR funding, including non-Stripe deposit/Boost sources. Late
captures still retain the obligation and its blocked reason.

The primary funding authority is the latest **applied succeeded balance
attempt**, ordered by success time and ID. A fully credited deposit-only
balance can use its applied succeeded deposit source. Failed/unapplied captures
do not become authority. EUR allocations additionally require a Stripe charge
reference. Mixed or unknown modes are not eligible for automatic execution.

Funding freezes the source, provider/mode, method version and initial
destination, original positive EUR amount, initial settlement amount, routing
policy and timestamp. DZD freezes the Chargily attempt's FX when Chargily is
primary; Stripe-to-DZD uses the active server business-settings revision at
funding. EUR carries no FX. The integer calculation is
`ceil(eur_cents * rate_micros / 100_000_000)`: 6,000 cents at 260 DZD/EUR is
15,600 DZD. Later settings/preferences cannot rewrite these fields.

Missing FX remains null with `fx_snapshot_missing`; the captured EUR obligation
is retained. Do not fill it with today's rate. Remediation requires a later
explicit architecture-compatible workflow. A zero settlement award appends an
explicit cancellation revision and keeps the original funded amount. Existing
prepared intents are cancelled before amount or destination changes. Committed
or unrecovered exposure blocks amendments/revisions.

The existing states remain, with `blocked` and `sent` added. `blocked` means an
obligation is still owed; `sent` never means proven paid. Event-producing domain
changes validate transitions. Delivered disputes cannot shorten the stored
48-hour protection deadline. Funding records a durable PostgreSQL release-check
job; lifecycle release still checks delivery, protection, dispute/refund state
and Finance holds. Versioned rows cannot use the old arbitrary manual completion
service.

## Privacy and access

`sensitive_data.py` uses AES-256-GCM through `cryptography`, with a fresh 12-byte
nonce and a versioned envelope containing key ID, nonce and ciphertext/tag. AAD
binds the payout domain, model, immutable public UUID, field and schema version.
There is no Django SECRET_KEY or other legacy-key fallback.

`PAYOUT_DATA_KEYRING` is a JSON object of key IDs to base64 32-byte keys;
`PAYOUT_DATA_ACTIVE_KEY_ID` selects writes. Retain retired keys while retained
records reference them. `PAYOUT_ACCOUNT_FINGERPRINT_KEY` must be a distinct
32-byte key. HMAC-SHA256 covers a versioned normalized postal-account tuple;
Unicode decimal digits/whitespace normalize without discarding leading zeros.
Fingerprints remain internal and never appear in API projections.

Keys are validated at startup only when profiles are enabled and again on
cryptographic operations. Missing/malformed keys fail closed without secret
values in errors. With profiles disabled, existing production startup requires
no new payout secret. The multi-process launcher strips payout keys and payout
storage credentials from Go/gateway child environments. H1 does not generate or
install production keys.

Name comparison normalizes case, whitespace, common punctuation, Latin accents
and Arabic marks. Exact/normalized matches are `consistent`; supported aliases,
compound-name reorderings and script changes require review; different names
are `mismatch`; absent attestation is `insufficient_attestation`. Every result
requires human review and never automatically verifies account ownership.

New capabilities are `view_finance_summary`, `view_payout_sensitive`,
`view_payout_evidence`, `review_payout_profiles`, `attest_payout_identity`,
`manage_payout_holds`, and `retry_payouts`. Finance gains its financial
capabilities without generic KYC browsing. Trust gains scoped identity
attestation without broad payout access. Ops/Support gain no sensitive payout
access. Super Admin retains full capability authority. Sensitive operations use
fresh **AND** checks, including role downgrade/inactive/ban revocation.

Audit records identify method/profile/attestation/confirmation/amendment/hold
actions using safe IDs, revisions and reason codes. Postal values and legal
names are write-only API input and ciphertext at rest; projections contain
only masks and references. H4 must add audited sensitive-reveal/evidence access,
not expose model fields through generic serializers/admin pages.

## Dormant APIs and configuration

All routes are authenticated and return unavailable when profiles are disabled:

- `GET /api/payouts/methods`: owner-only safe versions, masks and status.
- `POST /api/payouts/methods`: explicit enabled preference, currency, revision,
  country where relevant and current policy consent.
- `POST /api/payouts/profiles/dzd`: new encrypted revision; no upload.
- `GET/POST /api/admin/payout-identity-reviews/<uuid>`: assigned Trust review
  reference/projection and explicit attestation only.

Inputs reject unknown fields, owner identity is server-derived, and profile
requests have a separate rate limit. Stripe setup projects unavailable in H1;
there are no Account Links. EUR countries use a configured allowlist with the
H0 FR/DE/ES safety ceiling, initially empty.

All six flags default to **false**: `PAYOUT_PROFILES_ENABLED`,
`PAYOUT_DZD_EXECUTION_ENABLED`, `STRIPE_CONNECT_ENABLED`,
`STRIPE_CONNECT_PAYOUTS_ENABLED`,
`STRIPE_CONNECT_NON_STRIPE_FUNDING_ENABLED`, and `FINANCE_DASHBOARD_ENABLED`.
Execution services remain absent even if a future operator changes a parsed
execution flag. Dedicated `PAYOUT_S3_*` configuration is empty; no KYC/media
fallback or bucket provisioning exists.

## Migration and operational contract

Finance migrations 0009–0018 stage additive models/nullable UUID fields,
mode fields, UUID/evidence-only backfill, constraints after backfill, immutable
history/snapshot guards, confirmation and request uniqueness, relation guards
and unpaid-legacy quarantine. Admin migrations 0004–0005 add/seed capabilities.

Known historical Stripe Checkout prefixes or verified event `livemode` evidence
may classify an attempt; conflicting/absent evidence remains `legacy_unknown`.
Current credentials are never historical evidence. Existing paid payout fields,
amounts, references and timestamps remain readable and paid. Unknown original
economics, FX, profile, KYC and receipt evidence are not invented. Unpaid legacy
rows become `blocked/legacy_instruction_required`; release and manual completion
cannot bypass that quarantine. `manage.py report_payout_legacy` reports grouped
counts and canonical totals without mutation or sensitive data.

PostgreSQL triggers guard raw/bulk history changes, frozen snapshots, revision
and amendment prerequisites, owner/rail/currency/mode relationships, account
identity and prepared request identity. Partial unique constraints serialize
active accounts and unresolved/prepared attempts. Service locks enforce
cross-row source conservation; a save override is not the conservation control.

Canonical locking extends lifecycle → orders → payment attempts →
events/refunds → payout → methods → accounts → new financial rows →
ledger/jobs. Profile writers take User then method and never acquire old Deals.
No provider I/O occurs under these locks. H3 must revalidate all dispatch
conditions and add recovery/release accounting before any external submission.

Reverse/reapply is only a disposable-database rehearsal. Do not reverse these
migrations after new financial evidence exists. Rollout/rollback is by disabled
flags and retained schema, followed by reviewed remediation.

## H2 prerequisites and limits

1. Separately authorize H2 and rotate the exposed Stripe **TEST** secret before
   any external Connect testing. H1 does not rotate it or inspect its value.
2. Verify the France TEST platform/Connect capability and selected country/bank
   matrix. Do not assume Algeria EUR onboarding or non-Stripe-funded EUR support.
3. Implement and verify v1 controller/account/readiness/hosted-link contracts
   against H0's pinned `2026-03-25.dahlia` API/event version. Keep checkout
   behavior isolated and never persist raw provider bank/KYC payloads.
4. Configure only the TEST credentials and webhook destinations required by
   implemented H2 handlers after separate authorization. Keep money execution
   disabled until H3 reservations, unknown-result recovery, disputes/refunds and
   reconciliation pass their gates.
5. H4 owns dedicated private encrypted evidence storage and DZD review/receipt
   execution; H5 owns Finance metrics; H6 owns mobile and communications.

No external money operation, Connect object, provider/Railway configuration
change, email delivery, storage provisioning, APK/AAB or deployment is part of
H1. Test fixtures simulate existing payment/refund/manual paths locally.

## Verification

Final test and integration evidence is recorded in the H1 entry of
`IMPLEMENTATION_STATUS.md` and the task's delivery report. The sqlc query
directories remain empty: schema export is real, sqlc generation is explicitly
skipped, and CI regenerates the existing Go gRPC contracts.
