# F1: payout setup says what is open, and onboarding serves one declaration (2026-11-27)

Phone test 2, plan section 1.3, package F1; round 6 closes rules F-C, F-F and F-G of brief F1
(`docs/handoff/builders/F1.md`). Server, plus one app string. No migration, no new switch, no new rail.
Nothing deployed. Rounds 1 to 5 are in git, up to `bd74c3a`; this is the design as it now stands.

## The defect

With payout profiles off, `GET /api/payouts/methods` was a bare 404. With them on, the read offered
actions the server refused. Five review rounds then found the same hole in new shapes: onboarding talks
to Stripe between short transactions, and a preference change or a staff change could land in between.

## The gate

`payout_mobile.setup_gate(user)` reads the checks that refuse the write: `require_profiles`, the one
eligibility function `payout_profiles.member_refusal` (active, not banned, traveler role, confirmed
email), `require_connect_enabled`, `allowed_countries()` and the private payout store. Every action,
choice and reason below comes from it. A read calls no provider and writes nothing.

| Situation | Code | Read | Direct write |
| --- | --- | --- | --- |
| Signed out, deactivated or banned | authentication | 401 | 401 |
| Payout profiles off | `payout_profiles_disabled` | 200, stored setup, no action | 409 |
| Sender-only account / email not confirmed | `payout_traveler_required` / `email_verification_required` | 200, this reason | 403 |
| Connect off / no country open | `stripe_connect_unavailable` / `stripe_connect_no_countries` | `eur.unavailable_reason` | 409 |
| A Stripe account is being created | `payout_setup_in_progress` (new) | `eur.unavailable_reason`, only `resume_eur_setup`, no `dzd_only` | 409 on a change of the EUR country or of EUR on/off, and on an onboarding call that cannot settle it yet |
| Declared or account country not open | `payout_country_unsupported` | `eur.country_supported`, reason | 400, `supported_countries`, DZD alternative, `account_country` when it is the account's own |
| Account opened for another country | `stripe_account_country_mismatch` | `eur.account_country`, no setup action | 409 |
| The rows changed twice under one call, or the call names another country | `payout_preference_changed` | nothing (the read shows the newer rows) | 409, nothing bound, no link |
| Cheque store not configured | `payout_evidence_unavailable` | `dzd.unavailable_reason`, DZD stays choosable | 503 |
| Stripe outage | `stripe_connect_provider_error` | nothing | 502 |

Order, the same on the read and on every write: authentication, profiles, account, email, a closed rail,
the creation in progress, then the onboarding decision. `stripe_account_unresolved` ("requires Finance
review") no longer exists.

| Action | Offered when | Write |
| --- | --- | --- |
| `configure_eur` | gate open, Connect on, a country open, no account here, nothing in progress, the decision passes | PATCH preference, then `POST .../stripe/onboarding` |
| `resume_eur_setup` | gate open, Connect on, a country open, and either a creation in progress or a usable account Stripe still needs details for | `POST .../stripe/onboarding` |
| `refresh`, `manage_eur` | gate open, Connect on, a usable account (`manage_eur`: details submitted) | `.../stripe/refresh`, `.../stripe/dashboard` |
| `configure_dzd`, `replace_dzd_profile` | gate open, store configured | `POST /api/payouts/proofs`, then `POST /api/payouts/profiles/dzd` |

**The onboarding decision** (`payout_accounts.onboarding_refusal`, made by the read and by onboarding
under the locks): the traveler's active account here must be in an open country and named by the
declaration; else a creation in progress refuses nothing, because only onboarding settles it; else the
declared country must be open (the read does not count this against `configure_eur`).

## One declaration per creation (F-C)

No lock is held while Stripe answers. What ties a creation to its declaration is a row.

- **The freeze.** Onboarding commits the creation intent (`PayoutProviderOperation`, status `committed`)
  under the method row lock before any request leaves. Every preference write locks the same row
  (`payout_profiles._method`), and `set_preference` refuses a change of the EUR method's `enabled` or
  country while `current_creation(method)` is `prepared`, `committed` or `unknown` (`SetupInProgress`).
  A write that changes neither, and any DZD write, goes through. A dropped connection releases nothing
  that keeps the declaration: the row stays.
- **One restart.** Two onboarding calls can overlap; both send the same idempotency key, so Stripe opens
  one account. When a conditional update changes no row, or the method's version is no longer the one a
  call planned for (`_require_unchanged`, `_record_account`, the link check), the call reads every row
  again and runs once more (`_once_more`). A second change answers `payout_preference_changed`.
- **How it ends.** An account recorded and bound; or Stripe refusing the request (`failed`); or, past
  `IDEMPOTENT_REPLAY_SECONDS` (23 h), a complete listing of the accounts created from one minute before
  the first request to 25 hours after it (`find_account_by_metadata`: `created[gte]`, `created[lte]`,
  `starting_after` while `has_more`, at most 20 pages of 100). One match is recorded and bound. No match
  marks the creation `failed`, and the restart opens a fresh attempt with a new key. Two matches, an
  error or more than 20 pages leave it `unknown`, logged (`finance.account_creation_ambiguous`,
  `finance.account_creation_listing_incomplete`), and the call answers `payout_setup_in_progress`.
  Stripe's list calls have no search delay, so the listing is complete when it is read.
- Inside the window an unclear request is replayed exactly as sent, never searched. A request whose
  country has closed is only looked for. An account found is bound only while its country is still
  open; otherwise it is kept, unbound, and the country decision answers.

## Eligibility on the locked row (F-F)

`member_refusal(user)` is asked of the User row the write has locked: in `_method` (every preference
write), in `_plan_onboarding` before an intent, in `_record_account` before binding, and in the last
transaction before a hosted link is returned. `PayoutSetupMember` asks it at the view, before the body
is read. A creation already committed when staff ban the traveler is still recorded, so the account at
Stripe is known here; it is not bound and no link is handed out. The separate email permission on
payout views and `holds_payout_setup` are gone.

## One answer per response (F-G)

A payout GET computes each rail once and gives the same object to `methods[].mobile` and to the summary,
inside one `consistent_read()` snapshot (`payout_profile_api.one_read`; a read inside a write's own
transaction uses that transaction). A write's response, onboarding's included, is built from rows read
in its own last transaction.

## Response shapes for F2

`contract_version` is `f1.v1`. `setup` holds `available`, `unavailable_reason` and
`preference_options` (exactly the preferences the PATCH accepts now). Each rail adds `selectable` and
`unavailable_reason`; EUR adds `country_supported`, `account_country`, `supported_countries` and
`supported`. While a creation is in progress: `eur.unavailable_reason = "payout_setup_in_progress"`,
`eur.available_actions = ["resume_eur_setup"]`, `selectable` only with the saved country, and no
`dzd_only` option. `methods[].stripe_setup` has no action flags; `mobile.available_actions` is the one
answer. History adds only the setup actions of a payout's own rail.

## Also in F1 (rounds 1 to 5, unchanged)

- The CCP account is checked in one place (`sensitive_data.postal_account`): 1 to 10 digits, a 2-digit
  key, a 20-digit RIP starting `00799999` that carries the number. Masks never show more than half.
- `lock_payout_method_set` (a transaction advisory lock) makes funding read a preference change whole.
- `destination_account` refuses an account outside the configured platform and mode before Stripe.

## Left as it was, for Ismail

1. EUR can be chosen while Connect is off, if a country is listed (the preference checks the country).
2. Keeping EUR needs an open country.
3. While a creation is in progress and the rail is closed (Connect off or no country open), EUR cannot
   be switched off until the rail reopens or the creation settles. Only reachable by switching the rail
   off during a creation.
4. A replay at the 23-hour boundary racing a search of the same creation could open a second account.
   Not reachable without two calls landing in the same second; not built.

## Evidence

Red commit `4100e8c`: the four round-5 findings as tests, failing on the code reviewed at `bd74c3a`.

| Finding or rule | Test | Red at `4100e8c` | Green |
| --- | --- | --- | --- |
| R5 blocker: a dropped connection lets DE commit over an FR request | `test_f1_setup_freeze::test_a_dropped_connection_releases_nothing_that_keeps_the_declaration` | yes | yes |
| R5 should-fix: writes wait on the lock with no deadline | `test_f1_setup_freeze::test_nothing_waits_for_an_onboarding_call_in_flight` | yes | yes |
| R5 should-fix: eligibility after waiting and at the link | `test_f1_setup_eligibility` (link, queued call, locked row, POST and PATCH) | yes | yes |
| R5 should-fix: one GET computes the actions twice | `test_f1_one_answer` (once per rail, one snapshot) | yes | yes |
| Every state against every writer (9 x 10) | `test_f1_setup_states::test_every_writer_in_every_setup_state` | new | yes |
| Whatever a GET offers, its write accepts | `test_f1_setup_states::test_whatever_the_read_offers_its_write_accepts` | new | yes |
| Threads, both orders; crash points; no session advisory lock | `test_f1_setup_freeze` (12 tests) | new | yes |
| The listing | `test_phase8fh2_adapter::TestRecoverySearch`, `test_phase8fh2_accounts` (window cases) | new | yes |

Rewritten to the new rule (the freeze replaces "a superseded creation" and "requires Finance review"):
in `test_phase8fh6a_mobile.py` the stale-bound, created-while-changed, superseded, same-country,
own-platform, outage, late-timeout, closed-country, precedence and link tests; in
`test_phase8fh2_accounts.py` the two past-window tests; `RefusingSearch` and `ByOperation` return
listings. `test_l18a_payout_gate` checks `PayoutSetupMember`; the `fh1` fixtures confirm their email,
because the domain now asks for it. Removed: `test_f1_payout_account_setup_race.py`, whose four
advisory-lock tests are now the row-lock thread tests in `test_f1_setup_freeze.py`.
