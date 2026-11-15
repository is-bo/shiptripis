# Phase L18A: Loose ends before acceptance, backend

Package L18A of `docs/WASSLA_DISCOVERY_PRO_PLAN.md` (plan L18A and 5.1f). While proving the skill, L17
listed seven oddities in the code (`docs/PHASE_L17_ADMIN_HELPER_SKILL.md`, section 8). The advisor
decided each one (5.1f); this package does the backend half of the four that are fixed and the one
that is removed. L18B does the app half against the contract in section 6.

Backend only. **No migration**, no Go, mobile or landing change. Two new throttle scopes (section 5).

## 1. Removed: the staff dispute paths nothing called

In `apps/disputes/services.py`:

- `open_dispute` lost its `as_admin` parameter and the branch it opened, which skipped the party check,
  the "already resolved" check and the window. Only a party opens a dispute now, and only inside its
  window. No console page, staff API route or helper action ever passed it.
- `close_dispute` is gone. It ended a dispute without a resolution and left a frozen payout frozen.
- The `closed` status value, `closed_at` column, `OpenedByRole.ADMIN` and `DisputeEvent.Kind.CLOSED`
  stay (plan 1.5 rule 5: no column or choice is narrowed). The three guards that named `CLOSED`
  (`set_dispute_status`, `preview_dispute_resolution`, `resolve_dispute`) now read
  `not dispute.is_active`, so a finished dispute of either kind is still refused with
  `dispute_already_finished`; `resolve_dispute`'s message is "This dispute is already finished."
- **Kept, by the advisor's decision:** the branch that records `payout_already_settled` when
  `freeze_payout` answers `paid`. A party's window closes when protection ends and no payout is released
  before then, so it is not expected; it stays as the honest handling of that return value (the console
  shows "Payout already settled"). Its comment says so. It stays covered by a test (section 7).
- Not touched, on purpose (5.1f): the deal statuses `offer_accepted` and `payment_failed`, the journey
  status `pending_verification`.

## 2. A sender verifies their email

V1 specification, "Sender launch verification is email-only".

- One permission class, `apps.accounts.permissions.EmailVerifiedToWrite` (unsafe methods need
  `is_email_verified`, reads pass), answers **403**
  `{"code": "email_verification_required", "detail": "Confirm your email address first."}`.
  Constant `apps.accounts.permissions.EMAIL_VERIFICATION_REQUIRED`. DRF runs it before the view reads
  the body, so a refusal validates, prices and writes nothing.
- `POST /api/parcels/delivery/v1` (the only path that creates a delivery request) uses it, and so does
  payout setup (section 2b). Nothing else is gated: the price quote, photo staging, journeys, offers,
  ID upload (Go service), Profile, everything else. No identity check is added for senders.
- A Google account is created verified (unchanged).

### The resend endpoint (advisor, 2026-11-15)

The only code was issued at sign-up; it expires (`EMAIL_VERIFY_CODE_TTL_SECONDS`) and has an attempt
cap, and nothing could issue another. `POST /api/auth/verify-email/resend` (name
`auth-verify-email-resend`):

- signed in (`IsAuthenticated`), throttle scope `email_verify_resend` (default 5/hour);
- always **204**, with no body;
- a verified account is sent nothing;
- otherwise, under a lock on the member row: every unused code is retired (`used_at` set), the pending
  email of each is withdrawn (`cancel_message`, so a delayed old code never arrives after the new one),
  and a fresh code is issued and queued by `_send_verify_email`, the sign-up path (outbox key
  `email_verification:<code id>`).

### 2a. Proving the email ends what an unproven person held (advisor, item 5)

Found by this package's second review: anyone can sign up with someone else's address, and from the
gate on the confirmed flag opens doors, so the moment the address is proved must leave the prover
alone in the account.

- `apps.accounts.sessions.end_all_sessions(user)`: every outstanding refresh token is blacklisted and
  every active push device is switched off (`apps.notifications.push.deactivate_all_push_devices`).
  Idempotent.
- **Google sign-in on an existing unconfirmed account with the same email** claims it
  (`_claim_unconfirmed_account`, under a lock on the account row, in one transaction with the new
  identity link): `end_all_sessions`, password made unusable, email confirmed, and what the unproven
  person typed replaced as for a new account: the name from Google; phone, wilaya and language from
  the sign-in request; the phone flag false. A confirmed account links as before and nothing of it
  changes (password, sessions, devices, profile). The owner can set a password through the reset email.
- **A completed password reset**, for every account: the new password, `end_all_sessions` and the
  confirmed flag land in the same transaction as the code check. A wrong code changes nothing.
- **Known limit:** an access token already issued lives to its expiry (`JWT_ACCESS_TTL_SECONDS`, 300
  seconds by default). Nothing can renew it.

### 2b. Payout setup needs a confirmed email (advisor, item 6)

`ProfileView` (`apps/finance/payout_profile_api.py`) and `ConnectView`
(`apps/finance/payout_account_api.py`) carry `EmailVerifiedToWrite`, so every member route of the
two families refuses unsafe methods while the flag is false: `PATCH`/`POST /api/payouts/methods`,
`POST /api/payouts/profiles/dzd`, `POST /api/payouts/proofs`, and `POST
/api/payouts/methods/stripe/{onboarding,refresh,dashboard}`. Reads answer as before. Staff views of
the families set their own `permission_classes` and are unchanged. Without this a stranger could attach
their own payout method to an account opened under someone else's address and wait for the owner to
claim it and earn. ID submission is not gated (Go service; staff review every document).

## 3. The member's own rating from the server

`GET /api/users/me/ratings/summary` (name `ratings-mine-summary`), signed in:

```json
{"state": "rated", "average": 4.5, "count": 3}
{"state": "new", "average": null, "count": 0}
```

The same block as the member's public profile card (`rating`): every rating they received, on either
side, that counts. There is still one average in the product: the rating projection moved out of
`trust_signals` into `apps/ratings/public.py` as `rating_summaries(user_ids, *, at, side)`, which
groups over `countable` in one query. `trust_signals` (every card, Find Travelers, ranking) and this
endpoint both call it; `RATING_NEW` and `RATING_RATED` moved there with it. One query per call,
whatever the history (tested).

## 4. Support contact

`GET /api/support` (name `support-contact`): `{"email": "<EMAIL_SUPPORT_ADDR>"}`, or
`{"email": null}` when the setting is empty or blank. The same server setting the emails print. No new
setting and no invented address: it is `null` until Ismail sets one. No sign-in and no authentication
at all (`authentication_classes = ()`), so a stale token cannot turn it into a 401; throttle scope
`support_contact` (default 30/min); GET only.

## 5. Settings

| Setting | Default | Where |
| --- | --- | --- |
| `DRF_EMAIL_VERIFY_RESEND_THROTTLE_RATE` | `5/hour` | `config/settings/base.py`, `backend/.env.example`, CI `10000/min` |
| `DRF_SUPPORT_CONTACT_THROTTLE_RATE` | `30/min` | same |

No switch was added.

## 6. Contract for L18B

| Need | Call | Answer |
| --- | --- | --- |
| Post a parcel while unverified | `POST /api/parcels/delivery/v1` | 403, `code: email_verification_required` |
| Change payout setup while unverified | payout write routes (section 2b) | 403, `code: email_verification_required`; reads unchanged |
| After Google sign-in on an unconfirmed account, or a password reset | (server side) | older refresh tokens refused (401 on refresh) and push devices off: the app signs in again and re-registers |
| "Send the code again" | `POST /api/auth/verify-email/resend` (signed in) | 204 always; 429 when throttled |
| Confirm the code | `POST /api/auth/verify-email` (unchanged) | 204 or 400 "Invalid code." |
| Profile rating | `GET /api/users/me/ratings/summary` | `{state, average, count}`; `average` one decimal or `null`; the all-time figure of the public profile card, so the label is "Rating" |
| Contact support | `GET /api/support` (no sign-in) | `{"email": string or null}`; `null` means no action anywhere |

`me.is_email_verified` is unchanged and tells Profile whether to offer "Verify email".

## 7. Tests

Django: **3,212 before, 3,248 after**, +36.

New:

- `apps/disputes/tests/test_l18a_removed_paths.py` (2): a search of `apps/` and `config/` Python and
  the helper's knowledge notes proves `as_admin` and `close_dispute` have no definition, caller or
  mention; `open_dispute` takes no staff switch.
- `apps/parcels/tests/test_l18a_email_gate.py` (7): unverified refused with the code and every request,
  order and attached-photo table untouched; refused before validation; verified passes; verifying opens
  the door; a Google account posts; Google sign-in verifies an unconfirmed password account; quote,
  account and list stay open.
- `apps/accounts/tests/test_l18a_sessions.py` (8, items 5 and 6 of the plan): `end_all_sessions`
  revokes every refresh token and switches off every push device of that account only, and can run
  twice; after a Google claim the earlier refresh token is refused, the earlier device is inactive, the
  old password fails, the flag is true and name, phone, wilaya and language are the Google request's;
  a claim clears a phone flag the stranger held; a confirmed account that links Google keeps its
  password, sessions, devices and profile; after a reset (unconfirmed or confirmed account) the
  earlier refresh token is refused, the device is inactive, the old password fails and the flag is
  true; a wrong reset code changes nothing.
- `apps/finance/tests/test_l18a_payout_gate.py` (4, item 6): every member payout write route is
  refused with `email_verification_required` for an unconfirmed account and no payout row is written;
  every read route still answers; a confirmed account passes the gate; a walk over the URL
  configuration proves every member `ProfileView`/`ConnectView` route carries the gate and the staff
  ones do not.
- `apps/accounts/tests/test_l18a_verify_email_resend.py` (5): sign-in required; a fresh code replaces
  the old one, which no longer verifies; the waiting sign-up email is withdrawn; a verified account is
  sent nothing; own throttle.
- `apps/ratings/tests/test_l18a_own_summary.py` (5): sign-in required; `new` with only blind ratings;
  equal to the public card before and after a hide, a removal and a lift; both sides count; one query
  whatever the history.
- `apps/notifications/tests/test_l18a_support_contact.py` (6): set, unset, blank, stale token, GET only,
  throttled.

Existing tests changed (advisor: rewrite those that used `as_admin=True` only to reach a state, drop
only those whose subject was the staff path):

| Test | What happened |
| --- | --- |
| `disputes/tests/test_disputes.py::test_an_admin_may_open_one_outside_the_window` | **Dropped**: its subject was the staff path. |
| `disputes/tests/test_disputes.py::test_closing_a_dispute_without_resolving_releases_the_freeze` | **Dropped**: its subject was `close_dispute`. |
| `disputes/tests/test_disputes.py::test_a_payout_released_first_is_pulled_back_by_an_admin_dispute` | **Rewritten** as `..._by_a_party_dispute`: the lock race (release job takes the Deal row at the deadline, a party's call stamped one second earlier runs after it) replayed by pinning the clock back. Still asserts the payout is pulled back to frozen. |
| `disputes/tests/test_disputes.py::test_no_active_dispute_ever_coexists_with_a_releasable_payout` | **Rewritten** (second ordering only): the same lock race by a party instead of a staff dispute. |
| `disputes/tests/test_disputes.py::test_a_party_dispute_after_release_is_refused_and_the_payout_stands` | **New**: after release a party is refused (`dispute_window_closed`), no dispute row, payout still eligible. |
| `finance/tests/test_phase4_concurrency.py::test_a_dispute_arriving_after_release_pulls_the_payout_back` | **Rewritten**: a party's call stamped before the deadline, as above. |
| `finance/tests/test_phase4_settlement_bounds.py::test_an_admin_dispute_cannot_refund_money_already_paid_out` | **Rewritten** as `test_a_second_dispute_cannot_refund_money_already_paid_out`: the state (a live dispute on a paid-out Deal) is built by the real `open_dispute` with only the "already resolved" gate lifted (`second_dispute` helper). Still asserts `payout_already_settled` is true (the kept branch) and the refund is refused. |
| `finance/tests/test_phase4_settlement_bounds.py::test_nothing_left_the_platform_twice` | **Rewritten**, same helper. |
| `finance/tests/test_phase4_settlement_bounds.py::test_a_partial_recovery_out_of_the_platform_share_still_reconciles` | **Rewritten**, same helper. |

Test helpers that create a sender who posts over HTTP now set `is_email_verified=True` (plan L18A:
no assertion weakened):

| Helper | Change |
| --- | --- |
| `finance/tests/factories.py` `make_user` | new keyword `is_email_verified` (default false); `build_scenario` passes it for the sender only |
| `parcels/tests/test_parcels.py` `_make_user` | verified |
| `parcels/tests/test_phase8fb_item_photo.py` `_make_user` | verified |
| `parcels/tests/test_j2_posting.py` `J2PostingTests.setUp` (also used by `test_phase_j63_request_boost_total.py`) | sender verified |
| `matching/tests/test_phase_j7b_route_matching.py` `OwnerScenarioTests.setUp` | Account A (the sender) verified |

Test helpers that set up a payout over HTTP now set the flag too (item 6; plan L18A: "test helpers
that set up a payout set the flag"):

| Helper | Change |
| --- | --- |
| `finance/tests/factories.py` `build_scenario` | the traveler is verified as well as the sender |
| `finance/tests/test_phase8fh2_accounts.py` | the `traveler` fixture and the six country, ownership and intruder accounts verified; the intruder now reaches the ownership refusal its test is about |
| `finance/tests/test_phase8fh26_business_profile.py` | the `traveler` fixture and the DZ account verified |
| `finance/tests/test_phase8fh6a_mobile.py` | the four `make_user` accounts verified |
| `finance/tests/test_phase8fh4_manual.py` | the three `make_user` accounts verified |
| `finance/tests/test_phase8fh1_foundations.py::test_profile_endpoints_disabled_and_owner_only` | `other` (the account that posts) verified |

No other test was changed.

Checks run: `ruff check .`, `makemigrations --check --dry-run` (no changes),
`build_helper_instructions --check`, the whole Django suite on PostgreSQL.

## 8. Knowledge notes (L17 skill)

Updated so the Super Admin's helper answers from the current code: `accounts-and-verification.md`
(resend, the posting gate, Google linking), `problems-and-disputes.md` (no staff path, no close),
`reviews.md` (the summary endpoint), `messages-and-notices.md` (`GET /api/support`),
`app-walkthrough.md` (one phrase). `INSTRUCTIONS.txt` regenerated. App-side statements that change in
L18B (resend button, Profile figure, support action) are marked as coming in L18B; L18B updates them.

## 9. Judgment calls

1. The resend endpoint (advisor, 2026-11-15).
2. Keep the `payout_already_settled` branch; rewrite the tests that reached it through `as_admin`
   (advisor, 2026-11-15).
3. Google sign-in on an existing unconfirmed account with the same email claims it for the Google
   owner rather than leaving it unverified or verifying it with a stranger's password still on it.
   The advisor widened this (plan item 5): the claim replaces everything the unproven person typed as
   for a new account (name from Google; phone, wilaya and language from the sign-in request; phone
   flag false), and runs `end_all_sessions`. A confirmed account links untouched.
8. One `end_all_sessions(user)` in `apps/accounts/sessions.py` (advisor, item 5): blacklists every
   outstanding refresh token and switches off every active push device through
   `deactivate_all_push_devices` in `apps/notifications/push.py`. A completed password reset runs it
   for every account, sets the password and confirms the email, in one transaction (proving control of
   the mailbox is what a reset does).
9. One permission class, `EmailVerifiedToWrite` in `apps/accounts/permissions.py`, serves both the
   posting gate and the payout gate (advisor, item 6), so the code, the 403 and the detail text
   ("Confirm your email address first.") are the same everywhere. The posting view's in-view check and
   its local constant were removed for it. Safe methods pass, so reads are unchanged; staff payout
   views set their own `permission_classes` and are unchanged; Go ID submission is not gated.
4. The three `CLOSED` guards became `not dispute.is_active` rather than being deleted, because the
   status value stays in the model.
5. The email gate answers 403 (a refusal about the account, like `journey_not_owned`), before the
   serializer, so an unverified sender is told the real reason first.
6. `GET /api/support` sets `authentication_classes = ()` so a stale token in the app cannot make the
   support address unreachable.
7. The own-rating summary is the profile card's whole-person figure; L18B labels it "Rating".

## 10. Known limits

- For L18B (second review): a resend cannot withdraw an email already being sent, so a member may
  receive an older code that no longer works; the copy should say to use the newest email. An
  unverified sender can fill the whole form before the refusal; the app should check
  `me.is_email_verified` before the posting flow starts.
- An access token already issued lives up to its 300-second lifetime after a claim or a reset;
  only refresh tokens are revocable. For L18B: a refresh answered 401 after a claim or a reset means
  "sign in again", not an error to retry.
- `NUM_PROXIES`: no change (advisor). Caddy sets `X-Forwarded-For` and the API has no published port,
  so the IP-keyed throttles see the real client. L10 notes it for a future CDN in front of Caddy.

- Whether staff should be able to open a dispute is an open decision for Ismail (5.1f).
- The support address and the website's placeholder mailboxes are Ismail's to supply ("Before real
  users" in the release report).
- Existing unverified accounts (none in production) must verify before posting.
