# L11A: Tracking number, backend (contract)

Package L11A of `docs/WASSLA_DISCOVERY_PRO_PLAN.md`, built against `docs/WASSLA_DISCOVERY_PRO_SPEC.md`
section 16. One number per parcel, created with the request, shown by every server surface that used
to print `ST-<id>`, and searchable by staff. No amount, code, state or matching result changed.

## 1. What exists after L11A

- **A number on every request.** `ParcelRequest.tracking_number`, for example `WSL-7K3M9QXD`: `WSL-`
  and 8 characters from `23456789ABCDEFGHJKMNPQRSTVWXYZ`. Random, unique, drawn on the first save and
  never changed. A request that reopens after a cancelled deal keeps it, so every deal on that request
  shows the same number.
- **One module.** `apps/parcels/tracking.py` is the only place that creates, formats or parses a number.
  Every surface reads it through `for_request(request)` or `for_deal(deal)`.
- **`ST-<id>` and its email context key are gone** from `apps/`, `templates/` and the preview
  tools. Emails carry `tracking_number` instead and show it as "Tracking number".
- **Staff find a parcel by its number** in every console list that is about a parcel, in the finance
  control plane and in the JSON admin lists. Case, the `WSL` prefix and the hyphen are optional; the
  match is exact.
- **It identifies, it never authorises.** No endpoint opens anything from a typed number, and no public
  surface carries one.

## 2. Schema (additive)

| Table | Change |
| --- | --- |
| `parcels_request` | `tracking_number varchar(12) NOT NULL UNIQUE` (plus Django's `_like` index). |

Three migrations, the way Django documents a unique column with a generated value:

1. `parcels/0011_tracking_number_add`: the column, nullable, no default, not unique.
2. `parcels/0012_tracking_number_fill`: every existing row gets its own number (drawn by
   `tracking.generate`, checked against the numbers already taken, `bulk_update` in batches of 500).
   Reverse is a no-op.
3. `parcels/0013_tracking_number_unique`: required and unique.

`backend/contracts/sql/schema.sql` is regenerated in the same change. Proven on a database that already
holds requests by `apps/parcels/tests/test_l11a_tracking_migration.py`: it rolls the parcels app back
to `0010`, checks the column is gone, migrates to `0012` and checks every row has its own valid number,
migrates to the leaves and checks the numbers survive and the column refuses a duplicate and a null.

## 3. The module (`apps/parcels/tracking.py`)

| Name | What it does |
| --- | --- |
| `ALPHABET`, `PREFIX`, `LENGTH`, `MAX_LENGTH`, `MAX_ATTEMPTS` | The format: 30 characters (no 0, 1, I, L, O, U), `WSL-`, 8, 12 stored characters, 5 attempts. |
| `generate()` | A new random number (`secrets.choice`). Uniqueness is the database's to enforce. |
| `normalize(text) -> str \| None` | The stored form of a typed number, or `None`. Accepts `wsl-7k3m9qxd`, `WSL7K3M9QXD`, `7K3M9QXD`, surrounding spaces and the bidirectional isolates an email client puts around it in Arabic text. Refuses a wrong length or any character outside the alphabet. |
| `is_valid(value)` | Whether a value is already in the stored form. |
| `for_request(request)`, `for_deal(deal)` | The number for any payload, email or page. |
| `insert_with_new_number(instance, insert)` | Runs a request's first save. Each attempt is in its own savepoint; on an `IntegrityError` whose number now exists it draws another, at most 5 attempts in all, then raises `TrackingNumberUnavailable`. Any other integrity error is re-raised unchanged. |

`ParcelRequest`:

- the field has `default=tracking.generate` and `editable=False`;
- `save()` on a new row refuses a value that is not a number in its stored form, then inserts through
  `insert_with_new_number`;
- `save()` on a saved row refuses a changed number (`ValidationError`). The loaded value is remembered
  in `from_db`, so the check costs no query; a row loaded with the number deferred and never assigned
  is not checked at all;
- `validate_unique()` leaves the number out: the unique index is the authority, and a read-then-insert
  check would turn the retry into a validation error.

## 4. Where the number appears

### API payloads, as `tracking_number`

| Payload | Who receives it |
| --- | --- |
| `GET /api/parcels`, `GET /api/parcels/<id>`, and the create and cancel responses | The sender only. For anyone else the key is absent. |
| Matches (list, detail) and every offer (propose, counter, accept, decline, withdraw, offer chain) | The two people of the proposal. A match exists only once the sender has proposed. |
| Deals (list and detail, and the accept response) | Both parties. |
| `GET /api/payments/deals/<id>` | Both parties (top level; the traveler still sees only the order's status). |
| Payment orders (list, detail, posting deposit, the admin refund responses) | The owner. A deposit and a Boost name their request; a balance its deal (`PaymentOrder.tracking_number`). |
| Payouts (list and its `mobile` block, detail) | The traveler. |
| Disputes (party list, detail, staff views) | Both parties and staff. |
| JSON admin lists and the admin deal detail: requests, matches, deals, disputes, payment orders, payment attempts, refunds, payouts | Staff. |

**Not in:** the five public discovery payloads of L2A, Find Travelers candidates, the compatible-requests
list, the pricing quote, and the guest payment view and page. The privacy tests now forbid the key
`tracking_number` and the substring `WSL-` there (`apps/discovery/tests/test_privacy.py`,
`apps/matching/tests/test_phase2b_privacy.py`, `apps/finance/tests/test_guest_payment.py`,
`apps/finance/tests/test_j7c_guest_link_ux.py`).

### Emails

Every context that carried the old deal reference now carries `tracking_number`, read through `for_deal`:
pickup confirmed, delivery code released, delivery confirmed, protection ending, protection ended,
rating available, deal cancelled, dispute opened, dispute resolved, payout status (release and
reconciliation), and **the recipient's delivery-code email**. The owner's payment-failed and refund
emails carry it through `PaymentOrder.tracking_number`, so a posting deposit's emails name the request.
`outbox._facts` shows it as "Tracking number" (FR "Numéro de suivi", AR "رقم التتبع"); in Arabic the
layout isolates it left to right. The payment emails no longer fall back to a deal reference when a
payment reference is missing.

**A guest payer never receives it**: the guest's payment-failed, receipt and refund copies get a context
without the number, and the guest receipt template ignores it anyway (see section 7).

### Finance control plane

`Scope.parse` accepts an exact payout or order UUID, a tracking number (normalised) or `TR-<traveler>`;
`ST-<deal>` is refused like any other text. `Scope.search_kind` says which. A tracking number filters
payouts by their deal's parcel, and, with no other filter, also finds the captures of that parcel's own
orders (an unbound deposit or Boost), as an order UUID already did. Drill-down rows carry
`tracking_number` where they used to carry the deal reference (payouts through their deal, refunds and
ledger rows through their order or deal). The DZD queue shows "Tracking number · Traveler".

### Console

| Page | Change |
| --- | --- |
| Delivery requests, Deals, Disputes, Payments, Refunds, Payouts | First column is the tracking number (mono face). `q` matches it through `normalize`, exactly, alongside the text search each list already had; Refunds and Payouts gain the search (their box used to do nothing). |
| Deal detail | The heading is the tracking number (and the breadcrumb, and the tab title). |
| Dispute, payment attempt, refund, payout (Stripe and manual DZD) detail | The header names the parcel by its tracking number. |
| Person page | Requests, deliveries, payments, payouts, disputes, ratings and notifications show the tracking number where they showed "Deal N" or "Request N". |
| Technical admin (`/admin/parcels/...`) | The number is listed, searchable and read-only. |

Shared search helper: `apps/admin_panel/tracking_search.py` (`tracking_number_condition(text, paths)`
and the lookup paths per list).

## 5. Query counts

Every touched list reads the number through a join it adds to its existing `select_related`, so no list
gained a query per row. `ListQueryCountTests` proves that parcels, matches, deals, payment orders and
payouts cost the same for one row as for two. Measured against the integration branch at `6c00013`
(one sender and one traveler with two deals and two payouts, same fixture on both trees):

| Request | Before | After |
| --- | --- | --- |
| `GET /api/parcels` (sender) | 4 | 4 |
| `GET /api/matches` (sender) | 3 | 3 |
| `GET /api/deals` (sender) | 4 | 4 |
| `GET /api/deals` (traveler) | 4 | 4 |
| `GET /api/payments/orders` (sender) | 2 | 2 |
| `GET /api/payouts` (traveler) | 8 | 8 |
| `GET /api/deals/<id>` (sender) | 8 | 8 |

## 6. Tests

New: `apps/parcels/tests/test_l11a_tracking_number.py` (28) and
`apps/parcels/tests/test_l11a_tracking_migration.py` (1): format and alphabet; normalise accepts and
refuses; a forced collision retries and succeeds; five collisions raise and leave nothing; an unrelated
integrity error is not retried; a supplied non-number is refused; a saved number cannot change; a
reopened request keeps its number on the next deal; every payload above; query counts; every parcel
email kind renders the number in EN, FR and AR; the recipient email, the owner and guest payment emails
and the cancellation emails carry it (or, for the guest, do not); console and JSON admin search with a
typed number, a missing number and a partial number; detail headings; the migration.

Rewritten to the new rule (spec 16 replaced `ST-<id>`): the three finance control-plane and dashboard
tests that searched for or expected `ST-<deal>` now use the tracking number (and a typed lower-case
form); the notification tests that passed the old deal reference pass `tracking_number`; the person-page test that looked for "Request N" and "Deal N" now looks for the tracking number; the guest-receipt
privacy test now checks that a `tracking_number` in the context is not echoed. Fixture strings
`TEST-REF-1` and `ADMIN-TEST-1` were renamed so that `grep -R "ST-"` is empty.

Counts: see the handoff block in `docs/WASSLA_L_SERIES_PROGRESS.md`.

## 7. Judgment calls

1. **No number to a guest payer.** The plan said the guest payment receipt for a deposit carries the
   number; the spec lists who sees it (sender, traveler once a proposal exists, recipient, staff) and
   keeps it off the page a relative pays from, and an existing test already required the guest receipt
   never to echo deal context. The spec wins: no guest email carries it.
2. **The request payload shows it to the sender only.** A traveler learns it from the proposal, never
   from `GET /api/parcels/<id>`, which other members can read.
3. **Console lists lead with the number.** Payments and Payouts moved it into the first column (the
   payer and the traveler moved to the second), as the plan asks; Disputes shows the dispute reference
   under it.
4. **Background-job and technical-record pages keep record ids** ("Deal 12", "Payment attempt 5"): they
   name the database record a job acts on, not a parcel.

## 8. Screenshots

In `/mnt/project-files/l-series-screens/L11A/` (desktop console at 1440 px, emails at 390 px):

- Lists: `requests-list-en`, `deals-list-en`, `disputes-list-en`, `payments-list-en`,
  `refunds-list-en`, `payouts-list-en`.
- Search by number: `requests-search-en` (typed `bbpfx29m`), `requests-search-missing-en` (a valid
  number nobody has), `deals-search-en`, `payments-search-en` (typed without the prefix),
  `payouts-search-en` (typed in lower case).
- Details: `deal-detail-en` (the number is the heading), `dispute-detail-en`, `payment-detail-en`,
  `refund-detail-en`, `payout-detail-en`.
- Person page: `person-activity-en`, `person-deliveries-en`, `person-payments-en`.
- Emails: `email-recipient-delivery-code-{en,fr,ar}`, `email-pickup-confirmed-{en,fr,ar}` (no
  horizontal overflow at 390 px; Arabic keeps the number left to right).

The console is English only, so its screens have no French or Arabic variant. The finance dashboard
pages need PostgreSQL's reporting queries and do not render on the SQLite preview database; their
search is covered by the control-plane and dashboard tests.

Two console fixes came out of the gate pass: the deal heading's mono face was overridden by the
console's `#content h1` rule, and every list's search box rendered at about 174 px instead of its
intended 340 px (a percentage width inside a shrink-to-fit column), which cut its placeholder off.
