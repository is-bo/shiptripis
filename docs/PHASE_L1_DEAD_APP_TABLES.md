# Phase L1: drop the old payments, wallet and handover-code tables

Loop-end plan section 7.1, brief `docs/handoff/builders/L1.md`, decision D4 (Ismail approved
dropping the earlier product version's tables, 2026-11-27). Server only. No route, payload, screen or
app change. Nothing deployed.

## What changed

Package L1A (11 November) removed the routes and services of `apps.payments`, `apps.wallet` and
`apps.verification` but had to keep their models, because no table could be dropped. This package
drops them.

- **Eight tables dropped**: `payments_intent`, `payments_event`, `payments_refund`, `wallet_wallet`,
  `wallet_entry`, `wallet_hold`, `wallet_withdrawal`, `verification_handover_code`. One migration per
  app (`0002_delete_legacy_tables`) removes the foreign keys to `accounts_user`, `matching_offer` and
  `matching_match` and then the models.
- **The apps stay as empty shells** (`__init__.py`, `apps.py`, `migrations/`) and stay in
  `INSTALLED_APPS`, because the drop migration has to run on every existing database. The brief's
  stated reason ("older migrations of other apps name them") is not true: no other app's migration
  names these three. A later cleanup can remove the shells once every database has applied `0002`.
- **Admin**: the eight view-only Django admin pages and `apps/core/historical_admin.py` (only they
  used it) are gone. This also covers the `historical_admin.py` line of L4.
- **Chat rule**: `apps/matching/services.py` loses `_legacy_chat_eligibility` and the legacy block of
  `chat_history_visible`. Both read only `PaymentIntent`. The Deal (`funded_at`, closed states) is now
  the only gate.
- **Helper knowledge**: the wallet, module-table and glossary lines about the old tables are updated,
  and `INSTRUCTIONS.txt` is regenerated.
- **Comments** that said the tables "stay as history" (`finance/models.py`, `core/financial_locks.py`,
  `handover/models.py`, `matching/views.py`) now say they were dropped.

## Why the chat change alters no current answer

The removed branch ran only when `match.journey_id is None`.

- `matching_match` has the check constraint `match_legacy_or_v1_route`: a row has either a `trip` and
  no journey or legs, or a journey with both legs. `journey_id is None` therefore means an old
  `Trip` match.
- The only code that creates a `Match` is `apps/matching/v1_services.py` (`Match.objects.create`, one
  call, always with `journey`, `start_leg` and `end_leg`). Search: `Match.objects.(create|
  get_or_create|update_or_create|bulk_create)` and `Match(` outside tests. No fixture, seed or
  management command creates one. No code sets `journey` back to null.
- With `PaymentIntent` gone, the old branch could only have answered "not eligible". An old-style row
  now answers through the Deal check, still "not eligible" (`no_accepted_offer` instead of
  `payment_pending`). No such row can be written.

`apps/matching/tests/test_chat_eligibility.py` holds the rule for every current case: a proposal
without a Deal, an outsider, and each of the 16 Deal states funded and not funded, for both parties,
send and read. It was committed first (`0ddb28b`) and passed on `main` before any deletion, and
passes unchanged after.

## Inventory (each item: the search that shows nothing live uses it)

Searched across the whole repository (Python, Go, Dart, templates, settings, JSON fixtures, the
helper skill), excluding the apps' own files and dated reports under `docs/`.

| Item | Search | Live readers |
| --- | --- | --- |
| `PaymentIntent`, `PaymentEvent`, `payments.Refund` | `\bPaymentIntent\b`, `PaymentEvent`, `from apps.payments`, `apps.payments`, `payments_(intent\|event\|refund)`, `"payments".`, `get_model("payments"` | `matching/services.py` (the chat branch, removed); tests (rewritten). Other `PaymentIntent` hits are Stripe's object in `finance/providers` comments |
| `Wallet`, `WalletEntry`, `Hold`, `Withdrawal` | `\b(Wallet\|WalletEntry\|Hold\|Withdrawal)\b`, `apps.wallet`, `wallet_(wallet\|entry\|hold\|withdrawal)`, reverse names `wallets`, `payments_made` | none. "Hold" hits are the V1 payout hold (`finance/payout_*`) and console labels |
| `HandoverCode` (verification) | `\bHandoverCode\b`, `apps.verification`, `verification_handover_code`, `handover_codes` | none. Other hits are V1 `DealHandoverCode` (`apps.handover`) |
| `core/historical_admin.py` | `historical_admin`, `HistoricalRecord` | the three admin files only |
| Migrations of other apps | `("payments"\|"wallet"\|"verification", ...)` and `to="payments.` in `apps/*/migrations` | none |
| Go services, sqlc queries | table names in `backend/services`, `backend/contracts` | none |
| Mobile | no payload field is removed; `mobile/lib` has no `/api/wallets`, `/api/payments` caller (L1B, asserted by `mobile/test/legacy_removal_test.dart`) | none |

## Schema contract

`backend/contracts/sql/schema.sql` loses 719 lines and gains none: the eight tables, their eight
identity sequences, 13 primary-key and unique constraints, 12 foreign keys and 37 indexes (including
the partial unique `handover_one_active_per_match_kind`). Every removed object belongs to one of the
eight tables. Regenerated from a PostgreSQL 16 database migrated from scratch.

## Tests

| Test | What happened | Surface |
| --- | --- | --- |
| `core/tests/test_l1a_retired_surfaces.py::HistoricalAdminTests` (2) | removed | the view-only Django admin pages of the eight tables |
| `matching/tests/test_matching.py::ChatEligibilityTests::test_pending_payment_blocked` | removed | a `PaymentIntent` in `processing` on an old match |
| `matching/tests/test_matching.py::ChatEligibilityTests` (7 others) | moved onto a V1 Deal; "payment succeeded" is now "Deal funded", "match cancelled" is "Deal cancelled" | the chat-eligibility endpoint |
| `chat/tests/test_chat.py` (14) | moved onto Deals funded through the real test payment rail; `test_send_blocked_when_match_cancelled` became `..._deal_cancelled` (V1 closes chat on the Deal) | chat send, list, inbox |
| `chat/tests/test_live_history.py` (all), `chat/tests/test_p3c_chat_photos.py::ChatPhotoTests` | same fixture change; the closed-history test closes the Deal | history paging, commit order, inbox photos |
| `test_l1a_retired_surfaces.py::RetiredProductBoundaryTests`, `test_v1_matching.py::test_v1_deal_requires_funding_before_chat_and_has_no_legacy_payment_or_handover_route` | dropped the `PaymentIntent`/`HandoverCode`/`Hold` "count is 0" lines; the routes still answer 404 | dropped tables |
| `matching/tests/test_chat_eligibility.py` (3, 34 cases) | new | the chat rule for every Deal state |

## Seen, not fixed (follow-ups)

- `ChatThreadSerializer.get_route` reads `pickup_city`/`origin_id`, which V1 requests never fill, so
  every inbox row's `route` is empty. The test now asserts the real answer, `""`.
- `REASON_V1_PAYMENT_UNAVAILABLE` in `matching/services.py` has no reader (DC).
- `test_matching.py` cancel and list tests still build old `Trip` matches (L2).
