# S2: a token refresh survives a lost answer (2026-11-28)

Package S2 of `docs/handoff/LOOP_END_PLAN.md` (section 6), brief `docs/handoff/builders/S2.md`.
Server only. Migration `accounts.0009` (one column, no existing data), `contracts/sql/schema.sql`
regenerated. The phone needs no change: it already repeats a refresh with the token it holds. Nothing
deployed.

## The problem

Every refresh rotates the refresh token and blacklists the one presented (`ROTATE_REFRESH_TOKENS`,
`BLACKLIST_AFTER_ROTATION`). When the answer was lost on a weak network, the phone still held the old
token, presented it again, got `401 Token is blacklisted`, and the member was signed out. A refresh
happens every five minutes of use. The same on `main` before S2.

## The rule

Of one sign-in, two refresh tokens are accepted: the current one, and the one it was rotated from. The
older one stops being accepted when the current one is used. An ended sign-in refuses every token. No
time window and no setting.

## The mechanism

- **One column.** `SignInSession.previous_refresh_jti` (`apps/accounts/models.py`): the `jti` of the
  refresh token presented at the sign-in's last successful rotation. Empty until the first rotation.
- **Reading a token** (`SessionRefreshToken.verify`, `apps/accounts/sessions.py`) checks the signature,
  the expiry, the type and the `jti` only. SimpleJWT's blacklist read is moved under the lock below.
- **The refresh** (`SessionTokenRefreshSerializer.validate`), in one transaction:
  1. Lock the live sign-in row (`SignInSession.live(..., lock=True)`, `SELECT ... FOR UPDATE` on the
     row with `ended_at IS NULL`). None: `401`, "This sign-in has ended." Liveness comes first.
  2. Read the token's blacklist entry under that lock.
  3. Not blacklisted: store its `jti` in the column; SimpleJWT blacklists it and rotates (as before).
  4. Blacklisted and its `jti` equals the column: a repeat. SimpleJWT issues a fresh pair (its
     blacklist call finds the existing entry); the column does not change.
  5. Any other blacklisted token: `401 Token is blacklisted`, as before.
- **Two refreshes of one token** take turns on the row lock. The second reads the first's committed
  blacklist entry and column, and is a repeat. Both get a working pair; the row ends with the
  presented token's `jti`, and the token is blacklisted once.
- **An end and a refresh** also take turns on the row: an end that commits first leaves no live row to
  lock (`401`); a refresh that holds the row first finishes, and the end then refuses its new pair.
- **A ban ends every sign-in.** `set_account_ban` (`apps/admin_panel/staff_actions.py`) calls
  `end_all_sessions` when it bans, in the same transaction as the flags and the audit row. On `main`
  a ban only cleared `is_active`: access tokens were refused, but a refresh still answered 200 and
  the member's phones kept their push devices (N1 follow-up "A ban ends none of the member's
  sign-ins"). The brief's test needs a ban to end the sign-in, and `end_all_sessions` is the existing
  writer for that. A restore sets the flags back; the member signs in again.

Unchanged: the access token's lifetime (`JWT_ACCESS_TTL_SECONDS`, 300 s) and the 30 seconds of
leeway (G2), the sign-out contract, the password writer, the push rules.

## What the rule allows, on purpose

- **A lost pair stays valid until the sign-in ends or the token expires.** A repeat issues a new pair;
  the pair whose answer was lost is never blacklisted, because nobody holds it. The same is true on
  `main` (plan AR-1: a sign-in whose answer never reached the phone stays live, and nobody holds its
  tokens). Ending the sign-in refuses it.
- **A copied token that is still the previous one is accepted once more.** That is the rule itself:
  until the phone uses its new token, the server cannot tell a repeat from a copy. Once the phone
  uses the new token, the copy is refused.

## Evidence

Red commit `2574b39` (7 of 10 tests fail on `main`'s code), fix `253339c`. All in
`backend/monolith/apps/accounts/tests/test_refresh_after_a_lost_answer.py`.

| Brief case | Test | Red at `2574b39` | Green |
|---|---|---|---|
| The lost answer, once: the repeat gets a working pair | `LostAnswerTests::test_a_repeat_after_a_lost_answer_gets_a_working_pair` | 401 | `253339c` |
| The lost answer twice in a row: each repeat gets a working pair | `LostAnswerTests::test_each_repeat_after_answers_lost_twice_in_a_row_gets_a_working_pair` | `[200, 401, 401]` | `253339c` |
| After the phone used the new token, the older one is refused | `LostAnswerTests::test_once_the_phone_used_the_new_token_the_older_one_is_refused` | 401 on the repeat | `253339c` |
| A token two rotations old is refused (and the previous one is still accepted) | `LostAnswerTests::test_a_token_two_rotations_old_is_refused` | 401 on the previous | `253339c` |
| Only a rotation records a token: a blacklist alone refuses | `LostAnswerTests::test_a_token_never_rotated_is_refused_once_blacklisted_by_other_means` | passes (as today) | `253339c` |
| Two refreshes with the same token at the same time (real threads and locks, PostgreSQL) | `ConcurrentRefreshTests::test_two_refreshes_of_one_token_both_get_a_working_pair` | the second never waits for the first | `253339c` |
| A sign-out ends the sign-in: current and older refused | `EndedSignInTests::test_a_sign_out` | passes | `253339c` |
| A password reset ends the sign-in: current and older refused | `EndedSignInTests::test_a_password_reset` | passes | `253339c` |
| A ban ends the sign-in: current and older refused | `EndedSignInTests::test_a_ban` | 200 for the current token | `253339c` |
| Access lifetime 300 s and 30 s of leeway unchanged, on a repeat's token | `AccessLifetimeTests::test_a_repeat_issues_the_same_access_lifetime_with_thirty_seconds_of_leeway` | 401 on the repeat | `253339c` |

Mutations, each run against the whole file: the row lock removed fails the concurrency test; any
blacklisted token accepted fails three `LostAnswerTests`; the column never written fails six tests.

## Tests removed or rewritten

- `apps/core/tests/test_phase_k7_certification_profile.py`: the statement ceiling of `auth.restore`
  goes from 8 to 10. On `main` the first refresh of a sign-in measured 7 there. The brief's lock and
  column add the row's `UPDATE` and the transaction around them (logged as a savepoint pair under the
  test's own transaction; in production it is BEGIN and COMMIT, which are not counted), and the
  blacklist's `INSERT` now runs in a savepoint of that transaction. Measured 10. A refresh happens
  once every five minutes of use, so three more round trips cost nothing measurable.
- No other test was removed or rewritten. The refresh's earlier behaviour for a live, an ended and a
  rotated sign-in stays covered by `test_l18a_sessions.py`, `test_sign_out.py` and
  `test_credential_writers.py`, unchanged.

## Not checked here

- No phone: the app's repeat after a lost answer was not exercised on a device. The phone keeps
  the token it holds until a refresh answer reaches it (no app change, per the brief).
- The whole Django suite runs in CI. Locally, the accounts and notifications suites, the ban, staff
  and payout-eligibility files and the K7 budget ran: 830 passed.
