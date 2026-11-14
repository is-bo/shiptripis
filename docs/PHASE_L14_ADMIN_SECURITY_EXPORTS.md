# L14: Staff two-step sign-in and finance exports

Spec 19.1 and 19.2; plan L14 (with the advisor's answer of 2026-11-14). Backend and console only.
Staff instructions are in `docs/ADMIN_OPERATIONS.md` ("Two-step sign-in", "Finance exports").

## Two-step sign-in

### How it works

- `apps/admin_panel/two_step.py` holds every rule. Codes follow RFC 6238 (HMAC-SHA-1, 6 digits,
  30-second steps, one step of tolerance either side), written with the standard library and
  tested against the RFC 6238 and RFC 4226 vectors. A code is accepted only for a step after
  `last_accepted_step`, so a code cannot be used twice and an older code cannot follow a newer one.
- `AdminTwoStep` (one per user: sealed secret, `confirmed_at`, `last_accepted_step`,
  `failed_attempts`, `locked_until`) and `AdminRecoveryCode` (`code_hash`, `used_at`), migration
  `admin_panel/0007`. The secret is sealed with `apps/finance/sensitive_data.py` (model
  `admin_panel.AdminTwoStep`, record = the row's UUID, field `secret`), so a sealed value moved to
  another row does not open. Recovery codes are 16 base32 characters (80 bits), shown once, stored
  as SHA-256 digests, used once (a conditional update, so two tabs cannot both spend one).
- Five wrong codes, app or recovery, lock the second step for 15 minutes. The lock is taken under a
  row lock (`select_for_update(no_key=True)`), so parallel guesses cannot pass the limit.
- The only answers are `two_step_satisfied(request)` and `fresh_two_step(request, minutes=10)`.
  The verification lives in the session only, bound to the user's id: `mark_verified` rotates the
  session key and stores `{"user", "at"}`. Every password sign-in clears it (a `user_logged_in`
  receiver), and signing out ends the session.
- `ADMIN_TWO_STEP_REQUIRED` defaults to true. `config/settings/prod.py` refuses to start with it
  false, and production also refuses to start without a valid payout keyring, because enrolment
  seals with it (`apps/admin_panel/apps.py`).

### Where the gate is

- **Console and technical admin:** `AdminTwoStepMiddleware` (after the auth and message
  middleware). Every path under `/admin/` sends a signed-in staff member who has not passed the
  second step to `/admin/two-step/?next=…`, except: `/admin/login/`, `/admin/logout/`,
  `/admin/invitations/accept` (the invitation page, before any account can enrol) and the
  two-step pages themselves. The test walks every console and technical admin route (more than 150
  concrete paths) and asserts the redirect.
- **Staff API:** `HasAdminPermission` refuses with `403 {"code": "admin_two_step_required"}` before
  it checks the capability. The staff API is session-only (`apps/admin_panel/staff_api.py`,
  `StaffAPIView` / `StaffSessionMixin`: DRF `SessionAuthentication`, CSRF on writes). A bearer token
  is not read by any staff route, so it cannot reach one, alone or beside a session. Staff JWTs from
  the member sign-in still sign in to the app and open no staff route.
- **Fresh code:** staff role changes (console and `POST /api/admin/accounts/<id>/role`, which answers
  `403 admin_fresh_two_step_required`) and the reset. The console sends a stale session to the code
  page and back; the POST is not replayed. L15 calls `fresh_two_step` for helper keys.

### Route inventory

Frozen in `apps/admin_panel/tests/test_l14_two_step.py` (`STAFF_API_ROUTES`); a new staff route
fails the test until it is listed. Each route below refuses a bearer token alone, refuses an
unverified session, and answers a verified one.

`api/admin/` + `accounts`, `accounts/<pk>/role`, `audit-log`, `boosts`, `dashboard`, `deals`,
`deals/<pk>`, `deals/<pk>/no-show`, `disputes`, `disputes/<pk>/resolve`, `disputes/<pk>/status`,
`flight-proofs`, `flight-proofs/<pk>/review`, `health/deep`, `invitations`,
`invitations/<uuid>/revoke`, `journeys`, `kyc`, `kyc/<pk>/review`, `matches`, `offers`,
`payment-attempts`, `payment-orders`, `payments/orders/<reference>/refund`,
`payments/refunds/<pk>/settle`, `payout-identity-reviews/<reference>`, `payouts`,
`payouts/<pk>/complete`, `payouts/<pk>/manual`, `payouts/<pk>/manual/begin`,
`payouts/<pk>/manual/confirm`, `payouts/<pk>/manual/prepare`, `payouts/<pk>/manual/release`,
`payouts/evidence/<reference>`, `payouts/profiles/<reference>/reveal`,
`payouts/profiles/<reference>/review`, `payouts/receipts`, `provider-events`, `provider-health`,
`ratings`, `refunds`, `refunds/<pk>/settle`, `refunds/request`, `requests`, `roles`,
`scheduled-jobs`, `settings`, `users`, `users/<pk>` (49 gated routes).

**Open without the second step** (`OPEN_STAFF_API_ROUTES`): `api/admin/invitations/accept` only.
It creates the account from a one-time invitation, returns nothing that opens another route, and the
new admin still has to enrol before anything else answers (tested). L15 adds the helper routes.

### Callers of `/api/admin/` found

No console JavaScript, mobile or Go code calls it. Two callers existed and now go through a verified
console session:

- the data-scale probe (`backend/loadtest/data_scale_probe.py`): its seeded console session is
  marked verified in-process by `backend/loadtest/seed.py` with
  `apps.admin_panel.tests.two_step_helpers.verified_session_value`, the helper the tests use. No
  setting, header, parameter or route can do this from outside the process.
- the operator's health check in `docs/DEPLOYMENT_RUNBOOK.md` step 8: sign in to the console with the
  second step, then open `/api/admin/health/deep` in the same browser.

Texts that sent staff to a staff API route now name the console page: the dispute money position
(Disputes), the business settings list (Settings), and the `PayoutAdmin` and core admin docstrings.
No admin-only token sign-in route exists.

### Recovery procedure

1. Lost phone, codes left: "Use a recovery code" on the code page.
2. No codes left, or three or fewer: a Super Admin resets it on Staff (reason required, fresh code
   required, not for oneself; only a Super Admin can reset a Super Admin). The target's key and codes
   are deleted, every session of theirs is ended, and they enrol again at the next sign-in.
3. The last Super Admin: on the server, `python manage.py reset_admin_two_step <email> --reason
   "<why>"`. It does the same and writes the audit row with `actor` empty and
   `metadata.via = "manage.py"`.

Audit actions: `admin.two_step_enrolled`, `admin.two_step_locked`,
`admin.two_step_recovery_code_used`, `admin.two_step_reset`.

## Finance exports

- Permission `export_finance` (Finance, Super Admin), migration `admin_panel/0007`. Console page
  **Finance → Exports** (`/admin/finance/exports/`, route `finance-exports`).
- Form: kind, money (live, test, or unknown for older records; the same split as the finance
  dashboard), from, to. Range required, at most 366 days, not in the future, whole UTC days, both
  ends included. Each row belongs to the range by its own date: payment by capture time, refund by
  request time, commission by the delivery's funding time, payout by creation time. Rows dated after
  the moment the export started are left out, so the counted lines are the lines sent.
- One audit row per download, written before the first byte: `finance.export_downloaded`,
  `after = {kind, mode, from, to, lines}`, `metadata.as_of`. The page lists the last ten.
- The response is streamed (`StreamingHttpResponse`), `Cache-Control: private, no-store`,
  `X-Content-Type-Options: nosniff`, file name `wassla-<kind>-<mode>-<from>-to-<to>.csv`.
- UTF-8 with a byte-order mark, RFC 4180 quoting, CRLF. A cell starting with `=`, `+`, `-`, `@`, a
  tab or a carriage return gets a leading apostrophe; a plain number such as `-12.50` stays a number.
- Amounts are stored integers written as decimals; nothing is recomputed and the page writes no
  finance row (tested on the SQL it sends).

### Columns (frozen by `test_the_columns_are_frozen`)

| Kind | Columns |
| --- | --- |
| transactions | Date (UTC), Type (`payment` or `refund`), Tracking number, Payment reference, Provider, Provider reference, Purpose (`deposit`, `delivery`, `boost`), Paid by (`owner` or `guest`), Amount, Currency, Dinar amount, Status, Sender id, Sender name |
| commissions | Funded date (UTC), Tracking number, Traveler reward, Wassla fee, Sender total, Refunded to sender, Fee kept, Currency, Deal status, Sender id, Sender name, Traveler id, Traveler name |
| payouts | Created date (UTC), Tracking number, Payout reference, Method, Status, Amount, Currency, Dinar amount, Eligible date (UTC), Paid date (UTC), Failure reason, Traveler id, Traveler name |

Sources: transactions read the payment attempt and refund rows (a capture the order could not
absorb is listed with status `succeeded_unapplied`; a refund has no stored dinar amount, so that
cell is empty). Commissions read the deal's terms snapshot and, from the ledger, the refund leg on
provider clearing ("Refunded to sender") and the platform-commission entries ("Fee kept"), in the
chosen mode. Payouts read the payout row. People are their Wassla id and name; no email, phone,
address, bank, card or document detail is selected (a test walks every cell, including a guest
payer's stored email).

Tests compare the totals with the finance dashboard for the same data: succeeded payments with
`gross_funded`, succeeded refunds with `refunds_finalized`, fee kept with `recognized_revenue`, an unpaid
payout with `traveler_outstanding`. The query count of an export is the same at 10 and 1,000 lines.

## Screenshots

`/mnt/project-files/l-series-screens/L14/` (console, English): `enrol-default-en`,
`enrol-default-narrow-en`, `enrol-wrong-code-en`, `recovery-codes-shown-en`, `verify-default-en`,
`verify-default-narrow-en`, `verify-wrong-code-en`, `verify-locked-en`,
`recovery-default-narrow-en`, `staff-two-step-en`, `staff-two-step-narrow-en`,
`staff-reset-open-en`, `staff-reset-reason-missing-en`, `finance-exports-default-en`,
`finance-exports-default-narrow-en`, `finance-exports-range-error-en`, `finance-exports-recent-en`.

## Tests

Django 2,990 before, 3,046 after: `apps/admin_panel/tests/test_l14_two_step.py` (39) and
`test_l14_exports.py` (17). About 40 existing staff test files now sign in through
`apps/admin_panel/tests/two_step_helpers.staff_login` (or `verify_session`); no test turns the gate
off. New dependency: `segno==1.6.6` (pure Python QR code).

## Known limits

- The verification lasts as long as the Django session (default two weeks); signing out or signing
  in again asks again.
- A machine without the payout keyring cannot enrol staff (the page says so with a 503). Production
  cannot start without it. Local development sets the keyring, or `ADMIN_TWO_STEP_REQUIRED=false`.
- A finance row committed by a transaction that started before the export but finished during it can
  be in the file but not in the audit count. The window is a fraction of a second.
- Two shadowed duplicates remain unreachable (the admin panel's routes are mounted first): the four
  staff routes in `apps/disputes/urls.py` and `finance` `admin/payouts/<pk>/complete`. They are
  session-only like the others; removing them is a cleanup candidate.
- The console is English only.
