# Phase 8F-H4 — manual DZD payout core

Starting main: `98e72a926d41c3766782a3870c173fd19d0cee19` in
`is-bo/shiptripis`. H4 reuses H0 routing and rounding, H1 encryption, immutable
versions, identity attestations, reviews, evidence, attempts, holds and events,
and H3 source reservations and lifecycle locking. It makes no payment-provider
call. Execution defaults off and this release refuses LIVE manual obligations.

## Profile and evidence

The API accepts first name, last name, CCP number, CCP key, RIP and a reference
to a newly uploaded full crossed cheque. Names are bounded to 160 characters;
postal fields preserve leading zeroes and normalize whitespace, hyphens and
Unicode decimal digits. The existing bounds (CCP 1–20 digits, key 2, RIP 20)
are retained; no checksum algorithm is invented. Every replacement creates an
immutable profile and method version. Disabling a preference retains history.
Duplicate normalized account fingerprints flag review rather than rejecting a
shared account. Names are compared with an explicit current KYC attestation;
differences require human review and explicit acceptance.

All five identity/account strings use the existing authenticated encryption and
record/field AAD. Writes use the configured active key (`k2` in deployment).
The independently keyed HMAC fingerprint remains internal. Reads expose only
last-four masks, safe references and review status. There is no separate NIP
product field: migration 0022 corrects H1's historical misnaming to RIP without
discarding ciphertext. Historical migration files and the legacy authenticated
field-label read adapter retain that old spelling solely for compatibility.

Required labels:

- FR: **Photo du chèque barré complet**
- AR: **صورة كاملة لشيك مُسطَّر**
- EN: **Photo of the full crossed cheque**

Evidence accepts JPEG/PNG/WebP only, with MIME, extension, signature/image
verification, an 8 MiB byte limit, 20-million-pixel bound and no animation.
Client filenames are never stored. Random object keys are written with an
if-absent condition through explicitly configured `PAYOUT_S3_*` credentials;
there is no automatic generic or KYC fallback. At the owner's direction, the
existing private KYC bucket is shared and its Railway label is renamed
`shiptrip-private-evidence`. KYC objects retain their paths. Payout files live
under separate `payout/account-documents/` and `payout/transfer-receipts/` prefixes.
The payout logical store is explicitly configured with that bucket's credential;
application authorization and H1 encryption independently protect its contents. The image itself is encrypted using the same H1 system before
storage; PostgreSQL retains metadata, key ID and SHA-256, not the image blob.
Downloads are authenticated no-store responses after decryption/integrity checks,
with no storage URL. Full profile reveal and proof retrieval require Finance or
Super capabilities and record access audits; Support/Ops/Trust are denied.

## Manual instruction and accounting

Funding freezes currency, method/version, provider/mode, canonical EUR amount
and FX. Both preferences still route Stripe to EUR and Chargily to DZD. A
DZD-only preference retains H0's explicit DZD route. No current FX is substituted
for a funded snapshot. `ceil(eur_cents * rate_micros / 100_000_000)` gives exactly
15,600 whole DZD for 6,000 EUR cents at 260 DZD/EUR.

1. Release checks delivery, the stored protection deadline, disputes, Finance
   holds, funding and the frozen profile's current evidence review.
2. **Prepare transfer** creates a H1 `PayoutAttempt`, operator ownership,
   immutable instruction hash, and bounded source reservations, then schedules
   the payout. The hash binds exact EUR, DZD, FX, destination and mode.
3. **Begin external transfer** rechecks gates under lifecycle/order/source/payout
   locks and records `dispatch_committed` / `processing` before showing the send
   instruction. No lease expiry can authorize a second transfer.
4. **Record transfer evidence** requires a separate private receipt and explicit
   attestation. A submission receipt means `sent`. Completed evidence plus
   explicit settlement attestation records `paid`, preserving both events and
   timestamps. This is operator-attested settlement, not bank verification.
5. `ManualPayoutReceipt` adds immutable evidence revisions associated with the
   attempt/operator; corrections append evidence rather than overwriting it.
   Finalization is idempotent and discharges exactly the instruction's EUR
   payable using the existing balanced payout ledger entry. DZD remains snapshot
   metadata and is never counted as platform revenue.

Only a prepared, uncommitted instruction can be released by its owner. A
committed instruction requires recovery review; the code cannot reverse a CCP
transfer. Holds stop progression and preserve committed EUR exposure. The
console permits opening a correction/recovery hold and releasing one's own hold
through the existing audited H1 command. Destination replacement never repoints
a funded payout. H1's explicit precommit amendment mechanism remains available.

Migration 0023 adds only the receipt association. Migration 0024 protects receipt
history, operator commitment and evidence-required sent/paid writes in PostgreSQL.
No migration calls a provider or rewrites old payout economics.

## Functional interfaces

Traveler routes: `POST /api/payouts/proofs`, `POST /api/payouts/profiles/dzd`,
and existing masked `GET /api/payouts/methods`.

Finance routes: `POST /api/admin/payouts/receipts`,
`GET /api/admin/payouts/evidence/<uuid>`, profile `<uuid>/reveal` and
`<uuid>/review` under `/api/admin/payouts/profiles`, and payout `<id>/manual`
with `/prepare`, `/begin`, `/release`, `/confirm` commands. Strict serializers
reject authoritative client financial fields. Existing session/CSRF-protected
Finance payout detail renders the same domain workflow; it has no Mark paid
control, editable amount, editable FX or editable destination.

Durable payout events and existing outbox notifications cover processing, sent,
paid and attention states without account details. Profile submission, proof
attachment, replacement, review and reveal use existing durable audit records.
Email and H5 remain disabled. No H4.1 polish or H6 mobile UI is included.

## Verification and release

Local PostgreSQL tests exercise synthetic profile setup, encrypted image storage,
authorized reveal, funding, exact FX, receipt revisions, balanced settlement,
holds, release, owner isolation, malformed images, API authority, console access,
historical versions and raw-write guards. Four real PostgreSQL races cover two
operators, refund reservation, commitment/hold and duplicate finalization.
Targeted H3 execution tests cover unchanged EUR settlement/accounting and release.
All provider funding is synthetic; no external money operation is involved.

Final CI, deployment, production health and controlled QA results are recorded in
`IMPLEMENTATION_STATUS.md` when completed. At initial implementation review they
are pending; local tests alone do not constitute a deployed H4 PASS.
