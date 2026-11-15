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

- `POST /api/parcels/delivery/v1` (the only path that creates a delivery request) answers **403**
  `{"code": "email_verification_required", "detail": "Verify your email address before posting a
  parcel."}` while `request.user.is_email_verified` is false. The check is the first thing the view
  does: nothing is validated, priced or written, and a staged item photo stays unattached.
  Constant `apps.parcels.views.EMAIL_VERIFICATION_REQUIRED`.
- Nothing else is gated: the price quote, photo staging, journeys, offers, Profile, everything else.
  No identity check is added for senders.
- A Google account is created verified (unchanged). **New:** when Google sign-in links to an existing
  account that never confirmed its email, Google's proof wins (`_claim_unverified_account`): the
  password is made unusable, every refresh token is blacklisted, and the account becomes verified.
  Whoever chose that password never proved they own the address (anyone can sign up with someone
  else's email), so keeping it would leave a stranger inside a verified account; the owner can set a
  password again through the reset email. A verified account is linked as before and keeps its
  password. Found by the second review pass: linking already existed, and marking such an account
  verified without this would have made it worse.

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
| "Send the code again" | `POST /api/auth/verify-email/resend` (signed in) | 204 always; 429 when throttled |
| Confirm the code | `POST /api/auth/verify-email` (unchanged) | 204 or 400 "Invalid code." |
| Profile rating | `GET /api/users/me/ratings/summary` | `{state, average, count}`; `average` one decimal or `null`; the all-time figure of the public profile card, so the label is "Rating" |
| Contact support | `GET /api/support` (no sign-in) | `{"email": string or null}`; `null` means no action anywhere |

`me.is_email_verified` is unchanged and tells Profile whether to offer "Verify email".

## 7. Tests

Django: **3,212 before, 3,238 after**, +26.

New:

- `apps/disputes/tests/test_l18a_removed_paths.py` (2): a search of `apps/` and `config/` Python and
  the helper's knowledge notes proves `as_admin` and `close_dispute` have no definition, caller or
  mention; `open_dispute` takes no staff switch.
- `apps/parcels/tests/test_l18a_email_gate.py` (9): unverified refused with the code and every request,
  order and attached-photo table untouched; refused before validation; verified passes; verifying opens
  the door; a Google account posts; Google sign-in verifies an unconfirmed password account; the
  stranger's password and refresh token stop working; a verified account keeps its password; quote,
  account and list stay open.
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
   owner (unusable password, sessions revoked, verified) rather than leaving it unverified or
   verifying it with a stranger's password still on it.
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
- For Codex (older, not L18A's): `NUM_PROXIES` is not set, so DRF's IP-keyed throttles (the new
  `support_contact`, the existing `email_verify` and others) trust `X-Forwarded-For` as sent.

- Whether staff should be able to open a dispute is an open decision for Ismail (5.1f).
- The support address and the website's placeholder mailboxes are Ismail's to supply ("Before real
  users" in the release report).
- Existing unverified accounts (none in production) must verify before posting.
