# F1: payout setup availability and actions are explicit on the server (2026-11-26)

Phone test 2, plan `docs/WASSLA_PHONE_TEST_2_PLAN.md` section 1.3, package F1 (Claude Opus, extra high).
Server only: no migration, no new switch, no new rail, no Go or Dart change. Owner answer Q2 = no: the
DZD rail stays the CCP postal account with the full crossed cheque. Nothing is deployed by this change.
F2 (the app) consumes the shapes below.

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
store's configuration (`payout_evidence.evidence_store_configured`, the bucket and key the cheque upload
writes with). Every action, choice and reason below comes from it. Reading it calls no provider and
writes nothing.

### Outcomes

| Situation | Code | Read (`GET /api/payouts/methods`, `GET /api/payouts/profiles/dzd`) | Direct write |
| --- | --- | --- | --- |
| Payout profiles switched off | `payout_profiles_disabled` (new) | 200, stored setup visible, `setup.unavailable_reason`, no action, no choice | 409 on every member setup write, before the body is read |
| Sender-only, deactivated or banned account | `payout_traveler_required` (new) | 200, same, with this reason | 403 |
| Email not confirmed | `email_verification_required` (existing) | 200, same, with this reason | 403 (unchanged, `EmailVerifiedToWrite`) |
| Stripe Connect off or not configured | `stripe_connect_unavailable` (existing) | `eur.unavailable_reason`, no EUR action, `eur.supported=false` | 409 |
| Connect on, no account country open | `stripe_connect_no_countries` (new) | `eur.unavailable_reason`, EUR not selectable | 409, with `supported_countries: []` and the DZD alternative |
| Declared account country not open (for example DZ) | `payout_country_unsupported` (existing) | `eur.unavailable_reason` when the stored country left the list | 400, with `supported_countries` and the DZD alternative |
| Private cheque store not configured | `payout_evidence_unavailable` (existing) | `dzd.unavailable_reason`, no DZD form action; choosing DZD stays open | 503 on the upload |
| Stripe outage | `stripe_connect_provider_error` (existing) | nothing (the read calls no provider) | 502, stored readiness unchanged |
| Cheque store outage | `payout_evidence_unavailable` (existing) | nothing | 503 |

Precedence on the read: profiles, then account, then email, then the rail's own reason. A write refused
for an empty country list says `stripe_connect_unavailable` when Connect is also off, as the read does.
Refusals answer `{"code", "detail"}`; the two country refusals add `supported_countries` and
`alternative: {"currency": "DZD", "rail": "manual"}`. `detail` is English and not for display.

Temporary failures (502, 503 from a configured store) are distinct from unavailable setup (200 read with
a reason, or 403/409 on a write) and from an empty history (`GET /api/payouts` 200 with `count: 0`, which
was never gated and still is not).

### Actions

| Action | Offered when (all of) | The write it leads to |
| --- | --- | --- |
| `configure_eur` | member gate open; Connect on and configured; a country open; no Stripe account yet; stored country (if any) still open | PATCH preference, then `POST .../stripe/onboarding` |
| `resume_eur_setup` | member gate open; Connect on; usable account; state `setup_required`; EUR enabled; stored country open | `POST .../stripe/onboarding` |
| `refresh` (EUR card) | member gate open; Connect on; usable account | `POST .../stripe/refresh` |
| `manage_eur` | as `refresh`, and Stripe details submitted | `POST .../stripe/dashboard` |
| `configure_dzd` | member gate open; private store configured; no DZD profile yet | `POST /api/payouts/proofs`, then `POST /api/payouts/profiles/dzd` |
| `replace_dzd_profile` | as `configure_dzd`, with a profile | the same two calls |
| `view_payout`, `refresh` (history) | always, owner-scoped reads | `GET /api/payouts/<uuid>` |

Member gate = profiles on, an active non-banned traveler or dual-role account, confirmed email.
`refresh` and `manage_eur` no longer disappear when the account's country leaves the list: the server
accepts both regardless of country, and the readiness then says `payout_country_unsupported`.

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
    "available_actions": [], "country": "FR", "supported_countries": ["FR"],
    "supported": false, "selectable": true, "unavailable_reason": "stripe_connect_unavailable",
    "checked_at": null
  },
  "dzd": {
    "state": "pending_review", "ready": false, "blocking_reason": "payout_profile_under_review",
    "available_actions": ["replace_dzd_profile"], "country": "DZ",
    "supported": true, "selectable": true, "unavailable_reason": null,
    "profile": {"reference": "<UUID>", "review_state": "pending_review",
                "ccp_last_four": "7890", "rip_last_four": "1234", "submitted_at": "..."},
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
- `setup.preference_options`: exactly the `preference` values the PATCH accepts now. `eur_only` and `both`
  need `eur.selectable`; `dzd_only` needs `dzd.selectable`.
- `eur.selectable`: the PATCH would accept EUR with a country from `supported_countries`. It does **not**
  need Connect, because the preference never did (see "Left as it was").
- `eur.supported`: Connect on and configured, a country open, and the stored country (if any) open.
  `dzd.supported`: payout profiles on.
- `unavailable_reason` (both rails): why that rail's setup actions or choice are missing, null when
  nothing is.
- `preference`, `revisions`, `state`, `ready`, `profile` and `methods` stay the stored preference and
  readiness and are readable whatever the switches say. `dzd.state` keeps `inactive` for a profile whose
  currency is not chosen; `dzd.profile.review_state` still tells a submitted cheque apart.
- Changed: `preference_required` is `false` while profiles are off, because funding then asks for no
  preference.

`GET /api/payouts/profiles/dzd` returns `{method, dzd}` as before; `dzd` carries `selectable` and
`unavailable_reason`. The `mobile` object inside every method projection (methods list, DZD submit
response, Stripe onboarding and refresh responses) carries the same rail fields.

`methods[].stripe_setup` keeps its readiness fields and loses `available`, `can_start_onboarding` and
`can_manage`. Nothing in the app read them; `mobile.available_actions` is the one answer.

History (`GET /api/payouts`, `GET /api/payouts/<uuid>`, the Deal's `payout_summary`): a payout in
`needs_attention` for `payout_setup_required` or `payout_profile_needs_attention` adds only the setup
actions of its own rail (`stripe_eur` → EUR actions, `manual_dzd` → DZD actions, `unavailable` → both),
and only those usable now. With profiles off, an unverified email, a sender-only account or Connect off
for an EUR payout, it shows `["view_payout", "refresh"]`. History itself stays readable and owner-scoped.

## Enforcement changes

- Profiles off: every `ProfileView` and `ConnectView` write answers 409 `payout_profiles_disabled` instead
  of 404. The staff API routes under `ProfileView` (evidence read and receipt upload, reveal, review,
  manual payout detail, identity review) answer the same 409 instead of 404, through the shared base
  (not separately tested; nothing calls them with profiles off); the staff console pages keep their own
  503 page. The two member reads stay open.
- `_traveler` raises `TravelerRequired` and `require_profiles` raises `PayoutProfilesDisabled`, both
  `PermissionDenied` subclasses with a stable code, so every existing caller and test is unaffected.
- The Stripe Connect routes (onboarding, refresh, dashboard) now run `_traveler` before reading the body,
  as every profile write already did. Before, a sender-only account that had somehow kept an EUR method
  could still call them; now each answers `payout_traveler_required`.

## Left as it was

Funding selection and preflight, preference revisions and consent, DZD profile versioning, bank review,
identity attestation, Stripe account creation and readiness, provider execution, the 48-hour protection,
the arrival floor, dispute freezes, integer EUR cents, frozen FX and every funded instruction. Reading or
changing availability creates no account, transfer, preference or method version. Tests prove every
column of the funded `Payout` row and of its bound `PayoutMethodVersion` is unchanged across reads under
every switch and a DZD replacement.

Three existing rules are mirrored, not changed. The lead may want to raise them with Ismail:

1. **EUR can be chosen while Stripe onboarding is off**, as long as the country list is not empty
   (`set_preference` checks the country, not Connect). The live server's list is empty, so EUR is closed
   there. After an O5 rollback that keeps `FR` listed with Connect off, a new traveler could choose EUR,
   could not onboard, and card-funded deliveries would wait on payout setup. The read model says so
   (`selectable: true`, `unavailable_reason: stripe_connect_unavailable`); closing it is a money-rule
   change.
2. **Keeping EUR needs an open country.** A PATCH that keeps EUR re-checks its country, so once the list no
   longer holds it only `dzd_only` is accepted. `preference_options` says exactly that.
3. A direct onboarding call with no EUR preference still answers `payout_setup_invalid` ("enable EUR
   first"), because the account service checks the preference before the country.

## Tests

`apps/finance/tests/test_phase8fh6a_mobile.py`, F1 section (17 cases):

- profiles off, with Connect on and off: stable read, 409 on all seven writes, empty history 200, no row
  or audit written;
- profiles on, with Connect on and off: each rail by its own gate, EUR selectable without Connect,
  onboarding refused with Connect off;
- empty allowlist, with Connect on and off: its own code on the read and on both EUR PATCHes, nothing
  written;
- legitimate FR declaration through onboarding; DZ declaration refused with the DZD alternative, then DZD
  chosen;
- sender-only, banned and unverified accounts: no action, no choice, coded 403 on all seven writes,
  nothing written;
- EUR switched off (the live switches) while DZD preference, cheque upload and profile submission work;
- saved preferences after Connect off, an emptied list and profiles off; the read and the refused write
  agree; no stored row changes;
- stale revisions on the PATCH and the DZD submission;
- another user's payout UUID, history, methods and cheque reference;
- private fields write-only, only offerable action names, no execution state, the funded payout and its
  instruction unchanged under every switch;
- history and detail: only the funded rail's usable setup action, none with profiles off, Connect off or
  an unverified email;
- store not configured and Stripe outage as temporary failures.

Rewritten because the rule changed (named in the pull request):
`test_phase8fh1_foundations.py::test_profile_endpoints_disabled_and_owner_only` (404 becomes the stable
read and 409); `test_phase8fh2_accounts.py` `TestMobileContract`, two cases that asserted the removed
`can_start_onboarding`/`can_manage`/`available` flags now assert the same facts on
`eur_method`. Signature-only updates pass the gate in `test_phase8fh1_foundations.py`,
`test_phase8fh4_manual.py`, `test_phase_j12_finance_route_performance.py` and
`test_pre_h8_hardening.py`; the `configured_h4` fake store gained `require_bucket`.

## Checks

See the pull request for the exact local runs and CI. No migration, so no contract regeneration.

## Handoff to F2

- Render the payout pages from `setup`, the rail objects and history. Never infer availability from a
  404 again: there is none for these reads.
- `setup.available=false`: show the reason (profiles off: "Payout setup is not open yet"; traveler
  required; verify email, which opens the existing verify-email screen), keep the saved preference and
  methods visible read-only, and offer no choice.
- Preference selector: enable exactly `setup.preference_options`; explain a disabled EUR choice from
  `eur.unavailable_reason`; never open the country dialog with an empty `supported_countries`.
- EUR card: buttons from `eur.available_actions` only; explain their absence from
  `eur.unavailable_reason`. DZD card likewise; `payout_evidence_unavailable` reads as "temporarily
  unavailable".
- History detail: the setup button maps `configure_eur`, `resume_eur_setup`, `manage_eur`,
  `configure_dzd` and `replace_dzd_profile` to their screens; there is no `configure_payout_method`.
- Writes: map 403/409 codes above to the same explanations, 502/503 to "try again later", and refetch
  `GET /api/payouts/methods` after any refusal.
