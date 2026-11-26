# F1: payout setup availability and actions are explicit on the server (2026-11-26)

Phone test 2, plan `docs/WASSLA_PHONE_TEST_2_PLAN.md` section 1.3, package F1 (Claude Opus, extra high).
Server only: no migration, no new switch, no new rail, no Go or Dart change. Owner answer Q2 = no: the
DZD rail stays the CCP postal account with the full crossed cheque. Nothing is deployed by this change.
F2 (the app) consumes the shapes below.

Round 2 (same day) answers the Astra review of `317b55e` (ten findings, section "Round 2" below).
Round 3 answers the Astra review of `f3f37a3`: one blocker, four should-fix items, two nits and two
pre-existing faults (section "Round 3" below).

## The defect

The live server runs with `PAYOUT_PROFILES_ENABLED=false`, `STRIPE_CONNECT_ENABLED=false`, an empty
Connect country list and no private payout store. `GET /api/payouts/methods` answered a bare 404 and the
app showed a generic error, so the owner saw the payout pages as broken. With profiles on, the read
model still offered actions the server then refused: EUR choices with an empty country list, DZD setup
whatever the account, `configure_dzd` without a cheque store, setup buttons for a sender-only or
unverified account. A history detail offered every current setup action, whichever rail the payout was
funded on. The H2 projection inside each method carried its own `can_start_onboarding` and
`can_manage` flags, which ignored those gates too.

## What the server answers now

One gate, `payout_mobile.setup_gate(user)`, is read from the checks that refuse the write:
`require_profiles`, `holds_payout_setup` (the rule `_traveler` enforces), the `is_email_verified` flag
`EmailVerifiedToWrite` checks, `require_connect_enabled`, `allowed_countries()` and the private payout
store's configuration (`payout_evidence.require_evidence_store`, the bucket and key the cheque upload
writes with). Every action, choice and reason below comes from it. Reading it calls no provider and
writes nothing.

### Outcomes

| Situation | Code | Read (`GET /api/payouts/methods`, `GET /api/payouts/profiles/dzd`) | Direct write |
| --- | --- | --- | --- |
| Not signed in, deactivated or banned (a staff ban clears `is_active`) | none (authentication) | 401 | 401, before any payout check |
| Payout profiles switched off | `payout_profiles_disabled` (new) | 200, stored setup visible, `setup.unavailable_reason`, no action, no choice | 409 on every member setup write, before the body is read |
| Sender-only account | `payout_traveler_required` (new) | 200, same, with this reason | 403 |
| Email not confirmed | `email_verification_required` (existing) | 200, same, with this reason | 403 (`EmailVerifiedToWrite`) |
| Stripe Connect off or not configured | `stripe_connect_unavailable` (existing) | `eur.unavailable_reason`, no EUR action, `eur.supported=false` | 409 |
| Connect on, no account country open | `stripe_connect_no_countries` (new) | `eur.unavailable_reason`, EUR not selectable | 409, with `supported_countries: []` and the DZD alternative |
| Declared account country not open (for example DZ) | `payout_country_unsupported` (existing) | `eur.country_supported=false`; `eur.unavailable_reason` when the country of the traveler's Stripe account left the list | 400, with `supported_countries`, `account_country` and the DZD alternative |
| The Stripe account was opened for another country than the declaration | `stripe_account_country_mismatch` (new) | `eur.state=needs_attention`, `eur.account_country`, no EUR setup action | 409 on onboarding, with `account_country` |
| The EUR preference changed while an onboarding call was waiting for Stripe | `payout_preference_changed` (new, round 3) | nothing (the read shows the newer preference) | 409 on onboarding; nothing is bound over the newer preference |
| An account creation is unresolved and waits for Finance | `stripe_account_unresolved` (existing code) | `eur.state=needs_attention`, no EUR setup action | 409 (was 400) |
| Private cheque store not configured | `payout_evidence_unavailable` (existing) | `dzd.unavailable_reason`, no DZD form action; choosing DZD stays open | 503 on the upload and on the profile submission |
| Stripe outage | `stripe_connect_provider_error` (existing) | nothing (the read calls no provider) | 502; see "Stripe failures" |
| Cheque store outage | `payout_evidence_unavailable` (existing) | nothing | 503 |

Precedence, the same on the read and on every write (profile routes and the three Stripe routes):
authentication, then profiles, then account, then email, then the rail's own reason. A write refused for
an empty country list says `stripe_connect_unavailable` when Connect is also off, as the read does.
Refusals answer `{"code", "detail"}`; the two country refusals add `supported_countries` and
`alternative: {"currency": "DZD", "rail": "manual"}`. `detail` is English and not for display.

Temporary failures (502, 503 from a configured store) are distinct from unavailable setup (200 read with
a reason, or 403/409 on a write) and from an empty history (`GET /api/payouts` 200 with `count: 0`, which
was never gated and still is not).

**Stripe failures.** A failed account read or creation leaves the stored readiness as it was. A failure
after the account is bound (the payout schedule or the hosted link) keeps the account and its method
version; the 502 says so in `detail`, the read then offers `resume_eur_setup`, and that call reuses the
account, finishes the schedule and mints the link. It never creates a second account.

### Actions

| Action | Offered when (all of) | The write it leads to |
| --- | --- | --- |
| `configure_eur` | member gate open; Connect on and configured; a country open; no account bound to the current version; no account of another country, no account whose country closed, no unresolved creation | PATCH preference (with a country from `supported_countries` when `country_supported` is false), then `POST .../stripe/onboarding` |
| `resume_eur_setup` | member gate open; Connect on; usable account; EUR enabled; the account country decision passes (below); state `setup_required`, or Stripe still needs the traveler (details not submitted, an outstanding or past-due requirement, or the payout schedule not finished) and the account is not closed for good | `POST .../stripe/onboarding` |
| `refresh` (EUR card) | member gate open; Connect on; usable account | `POST .../stripe/refresh` |
| `manage_eur` | as `refresh`, and Stripe details submitted | `POST .../stripe/dashboard` |
| `configure_dzd` | member gate open; private store configured; no DZD profile yet | `POST /api/payouts/proofs`, then `POST /api/payouts/profiles/dzd` |
| `replace_dzd_profile` | as `configure_dzd`, with a profile | the same two calls |
| `view_payout`, `refresh` (history) | always, owner-scoped reads | `GET /api/payouts/<uuid>` |

Member gate = profiles on, an active non-banned traveler or dual-role account, confirmed email.
`refresh` and `manage_eur` no longer disappear when the account's country leaves the list: the server
accepts both regardless of country, and the readiness then says `payout_country_unsupported`. A new
setup collects the account country first, so a saved declaration whose country has closed does not stop
`configure_eur`.

**The account country decision** (round 3, `payout_accounts.account_country_refusal`, used by the read
and by onboarding). A connected account never changes country, and a traveler has one active account per
platform and mode, so once one exists only it can serve EUR. With such an account: its own country must
be open (otherwise `payout_country_unsupported`), and the declaration must name it (otherwise
`stripe_account_country_mismatch`). Without one: the declared country must be open.

## Response shapes for F2

`contract_version` is now `f1.v1`. Everything from `h6a.v1` stays, with these additions and one change.

`GET /api/payouts/methods` (and the `PATCH` response, which returns the same body):

```json
{
  "contract_version": "f1.v1",
  "preference": "both",
  "preference_required": false,
  "revisions": {"EUR": 2, "DZD": 3},
  "setup": {
    "available": true,
    "unavailable_reason": null,
    "preference_options": ["eur_only", "dzd_only", "both"]
  },
  "eur": {
    "state": "setup_required", "ready": false, "blocking_reason": "payout_setup_required",
    "available_actions": [], "country": "FR", "country_supported": true, "account_country": null,
    "supported_countries": ["FR"], "supported": false, "selectable": true,
    "unavailable_reason": "stripe_connect_unavailable", "checked_at": null
  },
  "dzd": {
    "state": "pending_review", "ready": false, "blocking_reason": "payout_profile_under_review",
    "available_actions": ["replace_dzd_profile"], "country": "DZ",
    "supported": true, "selectable": true, "unavailable_reason": null,
    "profile": {"reference": "<UUID>", "review_state": "pending_review",
                "ccp_last_four": "7890", "rip_last_four": "9012", "submitted_at": "..."},
    "replacement_scope": "future_payouts_only"
  },
  "available_actions": ["replace_dzd_profile"],
  "preference_scope": "future_payouts_only",
  "methods": ["...per-method projection, each with the same `mobile` object..."],
  "policy_version": "payout_profile_v1",
  "execution_enabled": false
}
```

- `setup.available` / `setup.unavailable_reason`: can any setup write be made now, and if not, the
  member-level reason (`payout_profiles_disabled`, `payout_traveler_required`,
  `email_verification_required`).
- `setup.preference_options`: exactly the `preference` values the PATCH can accept now. `eur_only` and
  `both` need `eur.selectable`; `dzd_only` needs `dzd.selectable`.
- `eur.selectable`: the PATCH accepts EUR with a country from `supported_countries`. It does **not** need
  Connect, because the preference never did (see "Left as it was"), and it does not need the saved
  country to be open: a PATCH that names an open country replaces the saved one.
- `eur.country_supported`: whether the saved declaration's country is open, `null` when none is saved.
  When it is `false`, keeping EUR without a new country is refused (`payout_country_unsupported`).
- `eur.account_country`: the country of the traveler's Stripe account, when one exists.
- `eur.supported`: Connect on and configured, a country open, and the saved country (if any) open.
  `dzd.supported`: payout profiles on.
- `unavailable_reason` (both rails): why that rail's setup actions or choice are missing, null when
  nothing is.
- `preference`, `revisions`, `state`, `ready`, `profile` and `methods` stay the stored preference and
  readiness and are readable whatever the switches say. `dzd.state` keeps `inactive` for a profile whose
  currency is not chosen; `dzd.profile.review_state` still tells a submitted cheque apart.
- `ccp_last_four` and `rip_last_four` can be shorter than four digits or empty (see "CCP account").
- Changed: `preference_required` is `false` while profiles are off, because funding then asks for no
  preference.

`GET /api/payouts/profiles/dzd` returns `{contract_version, method, dzd, setup}`: the same
`contract_version`, `dzd` and `setup` as the methods read, plus the DZD method projection. The `mobile`
object inside every method projection (methods list, DZD submit response, Stripe onboarding and refresh
responses) carries the same rail fields.

`methods[].stripe_setup` keeps its readiness fields and loses `available`, `can_start_onboarding` and
`can_manage`. Nothing in the app read them; `mobile.available_actions` is the one answer.

History (`GET /api/payouts`, `GET /api/payouts/<uuid>`, the Deal's `payout_summary`): a payout in
`needs_attention` for `payout_setup_required` or `payout_profile_needs_attention` adds only the setup
actions of its own rail (`stripe_eur` → EUR actions, `manual_dzd` → DZD actions, `unavailable` → both),
and only those usable now. With profiles off, an unverified email, a sender-only account or Connect off
for an EUR payout, it shows `["view_payout", "refresh"]`. History itself stays readable and owner-scoped.

## CCP account (round 2)

Every CCP RIP is Algérie Poste's bank and agency code `007 99999`, then the CCP number padded with zeros
to ten digits, then a two-digit key. So the server now checks, in one place
(`sensitive_data.postal_account`, used by the input serializer and by `submit_dzd_profile`):

- the CCP number has 1 to 10 digits and is not all zeros; it is stored without leading zeros, so one
  account has one spelling and one fingerprint;
- the CCP key has 2 digits;
- the RIP has 20 digits, starts with `00799999`, and carries this CCP number.

Each refusal is a 400 with a per-field message that names the expected shape and never repeats a value.
The RIP key and the CCP key are not computed: no verified formula was available, and refusing a real
account on a wrong checksum would be worse than accepting a typo that Finance's review of the cheque
catches.

The masks never show more than half of the number (`sensitive_data.postal_account_masks`):
`ccp_last_four` shows the last `min(4, digits // 2)` digits. The RIP's last four digits are the number's
last two digits plus a key computed from the whole number, so `rip_last_four` is shown only beside a
four-digit CCP ending (a number of eight digits or more) and is empty otherwise.

## Enforcement changes

- Profiles off: every `ProfileView` and `ConnectView` write answers 409 `payout_profiles_disabled` instead
  of 404. The staff API routes under `ProfileView` (evidence read and receipt upload, reveal, review,
  manual payout detail, identity review) answer the same 409 instead of 404, through the shared base
  (not separately tested; nothing calls them with profiles off); the staff console pages keep their own
  503 page. The two member reads stay open.
- One permission, `PayoutSetupMember`, runs the member gate on every write of both views, between
  `IsAuthenticated` and `EmailVerifiedToWrite`, so the email refusal never outranks profiles off or the
  account (round 2).
- `_traveler` raises `TravelerRequired` and `require_profiles` raises `PayoutProfilesDisabled`, both
  `PermissionDenied` subclasses with a stable code, so every existing caller and test is unaffected.
- The Stripe Connect routes (onboarding, refresh, dashboard) now refuse sender-only and banned accounts,
  as every profile write already did.
- `set_preference` stores the normalized EUR account country it validated, and never stores a country on
  the DZD rail, whichever route calls it (round 2).
- Onboarding binds the traveler's existing active account to a newer declaration only when the account
  was opened for that country, and refuses otherwise (`stripe_account_country_mismatch`), creating
  nothing. A creation that a search past the replay window could not find is recorded on its operation
  (`provider_object_status="not_found"`), so the read stops offering a setup that will refuse (round 2).
- The DZD profile submission refuses with 503 `payout_evidence_unavailable` when the private store is not
  configured, as the upload does, even with a proof uploaded before (round 2).

### Funding reads the method set whole (round 2, Astra finding 1)

A preference change from DZD only to EUR only disables the DZD row and inserts the EUR row in one
transaction. Row locks did not make that atomic for funding: its method query waited for the DZD row,
then read it disabled, and never saw the EUR row inserted after the query began. The payout was funded
with no rail (`payout_preference_required`), a state neither committed preference had. This predates F1.

`apps.core.financial_locks.lock_payout_method_set(traveler_id)` takes a transaction advisory lock on the
traveler's method set, then the method rows in ascending id. Funding (`create_snapshot`, after the Deal
aggregate) and every writer that adds a method or changes which are enabled (`_method`, behind the User
row; the preference PATCH) take it first, so funding reads a change wholly before or wholly after. It
sits after `Payout` and before `TravelerPayoutMethod` in the canonical order; profile writers hold no
Deal or Payout, and funding never takes the User row, so no cycle exists. No funded amount, rail rule or
instruction changes: only which committed state funding reads.

## Left as it was

Funding selection and preflight, preference revisions and consent, DZD profile versioning, bank review,
identity attestation, Stripe readiness, provider execution, the 48-hour protection, the arrival floor,
dispute freezes, integer EUR cents, frozen FX and every funded instruction. Reading or changing
availability creates no account, transfer, preference or method version. Tests prove every column of
the funded `Payout` row and of its bound `PayoutMethodVersion` is unchanged across reads under every
switch and a DZD replacement.

Three existing rules are mirrored, not changed. The lead may want to raise them with Ismail:

1. **EUR can be chosen while Stripe onboarding is off**, as long as the country list is not empty
   (`set_preference` checks the country, not Connect). The live server's list is empty, so EUR is closed
   there. After an O5 rollback that keeps `FR` listed with Connect off, a new traveler could choose EUR,
   could not onboard, and card-funded deliveries would wait on payout setup. The read model says so
   (`selectable: true`, `unavailable_reason: stripe_connect_unavailable`); closing it is a money-rule
   change.
2. **Keeping EUR needs an open country.** A PATCH that keeps EUR re-checks its country, so once the list no
   longer holds it, EUR is accepted only with a new open country. `country_supported` says so.
3. A direct onboarding call with no EUR preference still answers `payout_setup_invalid` ("enable EUR
   first"), because the account service checks the preference before the country.

## Round 2: the Astra review of `317b55e`

| # | Finding | Fix | Test |
| --- | --- | --- | --- |
| 1 | Funding could read half of a preference change and fund with no rail (pre-existing race) | `lock_payout_method_set`, above | `test_f1_payout_method_set_race.py`: two connections, both orders; fails without the lock (`undecided`) |
| 2 | EUR unselectable with a closed saved country although a new country is accepted; lowercase country stored as typed | `selectable` follows what a declaration can be; `country_supported`; `set_preference` stores the normalized country | `test_f1_eur_choice_follows_what_a_declaration_can_be_and_is_stored_normalized` |
| 3 | An account of another country offered `configure_eur` forever | mismatch state, `account_country`, refusal, binding only on the same country | `test_f1_an_account_opened_for_another_country_is_never_offered_as_a_new_setup` |
| 4 | An unresolved creation still offered `configure_eur` | `creation_unresolved` on the read | the H2 case `test_normal_onboarding_also_refuses_to_repost_an_expired_unknown_creation`, extended with the read and the API |
| 5 | Email refusal outranked profiles off and the role | `PayoutSetupMember` on both views | `test_f1_writes_meet_the_same_refusal_order_as_the_read` |
| 6 | A one-to-four-digit CCP number came back whole as its mask | CCP rules and masks, above | `test_f1_a_mask_never_shows_more_than_half_of_the_ccp_number`, `test_f1_a_ccp_account_must_be_one_algerie_poste_can_hold`, `test_f1_one_account_has_one_spelling` |
| 7 | The DZD read lacked `setup` and `contract_version` | common contract on that read | profiles-off and profiles-on F1 tests |
| 8 | A proof uploaded before the store closed could still be submitted | `require_evidence_store` on the submission | `test_f1_a_proof_uploaded_before_the_store_closed_is_not_submitted` |
| 9 | A link failure after binding said "Nothing changed"; a schedule failure was never retried | `AccountKeptProviderError`, accurate `detail`, schedule finished on every route to the account | `test_f1_a_failure_after_binding_keeps_the_account_and_the_retry_reuses_it` (link and schedule) |
| 10 | The write-up promised a 200 read to a banned account | documented 401; real bearer token after a staff ban | `test_f1_a_staff_ban_ends_the_session_before_any_payout_read_or_write` |

The lead's review of the round-2 work in progress also found the preference PATCH copying the EUR
country onto the DZD version (round 1 had prevented it); `set_preference` now refuses that for every
caller, and `test_preference_contract_and_future_route[dzd_only]` covers it.

## Round 3: the Astra review of `f3f37a3`

| Finding | Fix | Test |
| --- | --- | --- |
| Blocker: an onboarding that read DE could bind DE over an FR declaration committed while Stripe was being called, and a bound DE account answered an explicit `country="FR"` with its DE link | Onboarding records the method version it started on. Every locked step checks the method is still enabled and on that version (`PreferenceChanged`, 409 `payout_preference_changed`). An account Stripe returns after the change is kept as the traveler's active account with its operation `accepted`, and is not bound. The country decision runs before an account already bound is reused, both before any Stripe call and again under the method lock | `test_f1_a_declaration_committed_before_stripe_answers_is_never_overwritten`, `test_f1_an_account_created_while_the_declaration_changed_is_kept_unbound`, `test_f1_a_call_naming_another_country_never_gets_the_bound_accounts_link` |
| Should-fix: the read said `payout_country_unsupported` and onboarding said `stripe_account_country_mismatch` for one state | The account country decision above, one function for both | `test_f1_the_read_and_onboarding_make_one_country_decision` (the account's country closed; the declaration's country differs) |
| Should-fix: an ambiguous FR creation followed by a DE declaration failed with a generic 400; an unresolved operation under another platform or mode blocked setup here | The applicable creation is found by method, platform and mode (the key carries all three). Its original country is read back from its stored request, so a replay inside Stripe's window sends the same key and the same request, and the search past it looks for the same account. The account found is then judged by the country decision. The read uses the same lookup | `test_f1_an_ambiguous_creation_is_resolved_as_it_was_sent` (inside and past the window), `test_f1_an_unresolved_creation_belongs_to_its_own_platform` |
| Should-fix: after a link failure the read offered only `refresh`, which cannot mint a link | `resume_eur_setup` while Stripe still needs the traveler (`onboarding_incomplete`) | `test_f1_a_failure_after_binding_keeps_the_account_and_the_retry_reuses_it` now goes 502, then the read, then the advertised action |
| Should-fix: the race test's wait accepted any waiter in the database | It records both workers' backend ids and waits until the trailing worker's advisory lock on this traveler's method set is ungranted and blocked by the leading worker | `test_f1_payout_method_set_race.py` |
| Nit: the replacement test searched for twenty `1` digits; the queue test checked only the CCP mask | The replacement test looks for the submitted CCP number and RIP; the queue test for both numbers and both of the profile's masks | `test_dzd_replacement_immutable_history_and_review`, `test_phase8fh41_console.py::test_the_queue_shows_the_settlement_amount_and_what_it_waits_on` |
| Pre-existing: a 401 or 403 on the recovery search marked the creation `failed`, so the next call moved to a new key and could open a second Stripe account | Only a refusal of the creation request itself marks it `failed`. Any other failure of the replay or the search leaves it `unknown` with its key, so the next call repeats the same recovery | `test_f1_a_refused_recovery_never_opens_a_second_account` (search and replay) |
| Pre-existing: onboarding locked the method then the account, refresh the account then the method | Refresh now locks the traveler's EUR method first, as the canonical order says. It sets the method's status only when the account is that method's current destination | `test_f1_onboarding_and_refresh_lock_the_method_before_the_account` (PostgreSQL) |

Two consequences worth knowing. A kept, unbound account is still the traveler's one active account, so
the read reports it (`account_country`) and the country decision applies to it: declaring its country
again binds it without a second Stripe call. And an ambiguous creation that only Stripe can settle keeps
`configure_eur` on the read; that call is the one that settles it (replay or search), and its answer is
then what the read shows.

## Tests

`apps/finance/tests/test_phase8fh6a_mobile.py`, F1 sections (rounds 1, 2 and 3), and
`apps/finance/tests/test_f1_payout_method_set_race.py` (PostgreSQL threads):

- profiles off, with Connect on and off: stable read (both reads, same contract), 409 on all seven
  writes, empty history 200, no row or audit written;
- profiles on, with Connect on and off: each rail by its own gate, EUR selectable without Connect,
  onboarding refused with Connect off;
- empty allowlist, with Connect on and off: its own code on the read and on both EUR PATCHes, nothing
  written;
- legitimate FR declaration through onboarding; DZ declaration refused with the DZD alternative, then DZD
  chosen; a declaration retained, replaced after its country closed, and normalized on both routes;
- an account of another country, and the way back to it without a second account;
- sender-only, banned and unverified accounts: no action, no choice, coded 403 on all seven writes,
  nothing written; the same order when profiles are off or the account is a sender as well as
  unverified; a real bearer token after a staff ban answers 401 everywhere;
- EUR switched off (the live switches) while DZD preference, cheque upload and profile submission work;
- saved preferences after Connect off, an emptied list and profiles off; the read and the refused write
  agree; no stored row changes;
- stale revisions on the PATCH and the DZD submission;
- another user's payout UUID, history, methods and cheque reference;
- private fields write-only, only offerable action names, no execution state, the funded payout and its
  instruction unchanged under every switch;
- CCP numbers of ten, eight, seven, four, one and zero-padded digits: masks never more than half; eleven
  digits, all zeros, a non-CCP RIP, another account's RIP and a short key refused per field;
- history and detail: only the funded rail's usable setup action, none with profiles off, Connect off or
  an unverified email;
- store not configured (upload and a submission with an earlier proof), Stripe outage, and a link or
  schedule failure after binding with a retry, offered by the read, that reuses the account;
- round 3: a declaration committed while Stripe answers the platform check or the account creation; an
  explicit other country against a bound account; both country cases on the read and the write with no
  Stripe call; an ambiguous creation replayed with its own key and country, or searched past the window;
  another platform's operation; a refused search or replay that keeps the same key and one account; the
  lock order of onboarding and refresh.

Each round-3 test was checked against the code without its fix: binding regardless of the started
version, moving the early return back before the country decision (with the pre-Stripe check also
removed, since either one alone refuses), marking a refused search `failed`, taking the account lock
before the method, and offering `resume_eur_setup` only in `setup_required` each make the named test fail.

Rewritten because the rule changed (named in the pull request):
`test_phase8fh1_foundations.py::test_profile_endpoints_disabled_and_owner_only` (404 becomes the stable
read and 409); `test_phase8fh2_accounts.py` `TestMobileContract`, two cases that asserted the removed
`can_start_onboarding`/`can_manage`/`available` flags now assert the same facts on
`eur_method`. Signature-only updates pass the gate in `test_phase8fh1_foundations.py`,
`test_phase8fh4_manual.py`, `test_phase_j12_finance_route_performance.py` and
`test_pre_h8_hardening.py`; the `configured_h4` fake store gained `require_bucket`.

Round 2 fixture changes, because the CCP rule changed: every synthetic DZD profile now submits a CCP
number of at most ten digits and a RIP built from it (`factories.ccp_rip`), in
`test_phase8fh1_foundations.py`, `test_phase8fh4_manual.py`, `test_phase8fh41_console.py`,
`test_phase8fh6a_mobile.py`, `test_payout_initial_setup_reconciliation.py`, `test_pre_h8_hardening.py`,
`test_phase_j12_finance_route_performance.py` and `apps/admin_helper/tests/world.py`. Their secret and
mask assertions follow the new values; none was dropped. `test_phase_j64_payout_review.py` and
`test_phase_k2_admin_ux.py` use that fixture: J64's staff mask and K2's staff reveal now look for its CCP
number instead of the old all-zero one.

`test_phase8df_lock_order.py` no longer lists `payout_snapshots.py` among the modules that lock rows:
its one row lock moved into `lock_payout_method_set` in `apps/core/financial_locks.py`, which the same
test still holds to `FOR NO KEY UPDATE`. The list's own rule is that a listed module must still lock
something. `test_required_profile_fields` and the
sender-refusal case in `test_phase8fh4_manual.py` now start from a valid account, so each still fails for
the reason it names.

Round 3 strengthened, without changing a rule: the failure-after-binding test reaches the retry through
the read; the race test's wait names the exact lock; the replacement and queue assertions look for the
submitted values.

## Checks

See the pull request for the exact local runs and CI. No migration, so no contract regeneration.

## Handoff to F2

- Render the payout pages from `setup`, the rail objects and history. Never infer availability from a
  404 again: there is none for these reads. A 401 means the session ended (a ban clears it): sign in.
- `setup.available=false`: show the reason (profiles off: "Payout setup is not open yet"; traveler
  required; verify email, which opens the existing verify-email screen), keep the saved preference and
  methods visible read-only, and offer no choice.
- Preference selector: enable exactly `setup.preference_options`; explain a disabled EUR choice from
  `eur.unavailable_reason`; never open the country dialog with an empty `supported_countries`. When
  `eur.country_supported` is `false`, keeping EUR needs a country from `supported_countries`: ask for it.
- EUR card: buttons from `eur.available_actions` only; explain their absence from
  `eur.unavailable_reason`. `stripe_account_country_mismatch`: say the Stripe account was opened for
  `eur.account_country` and offer to declare that country again. `stripe_account_unresolved`: say our
  team is checking the Stripe setup. DZD card likewise; `payout_evidence_unavailable` reads as
  "temporarily unavailable".
- DZD form: the CCP number takes at most 10 digits (today the app allows 20), and the RIP must start with
  `00799999` and carry the CCP number. Show each field's refusal in the user's language rather than the
  server's English `detail`. A mask can be shorter than four digits or empty: show no dots then.
- History detail: the setup button maps `configure_eur`, `resume_eur_setup`, `manage_eur`,
  `configure_dzd` and `replace_dzd_profile` to their screens; there is no `configure_payout_method`.
- Writes: map 403/409 codes above to the same explanations, 502/503 to "try again later", and refetch
  `GET /api/payouts/methods` after any refusal or failure (a 502 after binding has saved the account).
- Round 3: `payout_preference_changed` (409 on onboarding) means the preference changed in another
  session while this one was setting up: refetch and render what the read says, without an error
  message. `payout_country_unsupported` can now name `account_country`: when it does, the country that
  closed is the one of the traveler's Stripe account, so say EUR payouts to that account are not
  available and offer DZD. After a 502 on onboarding, the EUR card offers `resume_eur_setup`; render it.
