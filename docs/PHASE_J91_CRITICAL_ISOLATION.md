# J9.1 — Critical Security, Privacy and State Isolation

**Starting SHA:** `c78d9eab1e978da27d374b63ccd8f997be10afba`

**Branch:** `codex/j91-critical-isolation`

**Scope:** DEF-ADM-01, DEF-MOB-07, DEF-MOB-08 only. J9 MAJOR and MINOR findings remain open. The J8.3 APK is not launch-ready.

## DEF-ADM-01 — banned staff revocation

`has_admin_permission` checked authentication and staff status before granting a capability, with a superuser shortcut, but omitted `is_banned`. A ban that left `is_active=True` let an existing staff session or JWT pass capability checks. The existing finance `has_all_admin_permissions` already denied banned accounts, which exposed the inconsistency.

The shared `has_admin_access` predicate now requires an authenticated, active, staff, unbanned user. `has_admin_permission` applies it before the superuser shortcut, so HTML capability decorators, DRF Admin permissions, and service checks share the revocation rule. The staff-only console routes use a decorator backed by that predicate. Django's model Admin uses `ShipTripAdminSite.has_permission`; the owner-only technical route also checks this site permission before rendering. Requests through a session load the user from the database, and JWT authentication resolves the current user before the capability check. A denied route renders no sensitive body.

The focused regression establishes a session and JWT before changing `is_banned` in the database. Banned Super, Finance, and Trust operators lose the overview, direct role-specific console URL, and role-specific Admin API URL; Super also loses the technical route and Django model Admin. Before the ban, their Admin capability and representative API route work. `has_admin_permission`, `has_all_admin_permissions`, and `admin.site.has_permission` deny after the ban.

## DEF-MOB-08 — ratings privacy across sessions

`receivedRatingsProvider` was one unkeyed `FutureProvider`. A mounted listener kept its `AsyncValue` after logout because `SessionController._invalidateEverything()` only invalidated role context. Account B could read A's result without another HTTP request.

Private ratings now use a query keyed by `(accountId, authenticationGeneration)` and a public projection that switches query on session changes. Sign-out projects an empty list immediately; sign-in selects a fresh query even when the same account signs in again. The query rejects an in-flight response if its session is no longer current. The same concrete unkeyed, private-read pattern was found in payout details and signed parcel photo URLs, so those reads use the same session key and stale-response guard. All three public provider states switch away from the previous session; UI hiding is not the protection.

### User-specific provider audit

| Data | Current isolation | J9.1 action |
| --- | --- | --- |
| Received ratings | **Account and authentication generation keyed**; signed-out state empty | Fixed and tested A→B and A→A |
| Sent ratings | No standalone sent-ratings provider; deal rating state is in `dealDetailProvider` | No change |
| Profile | `accountProvider` derives directly from `sessionProvider`; completed-delivery count is account keyed | No change |
| Payouts, payout methods, payout history, earnings | Shared queries are account keyed and guarded after reads | No change |
| Payout detail | Previously only keyed by payout reference, a private cached result | Scoped to account and authentication generation |
| Requests, request detail, posting deposit, journeys, journey detail | Shared queries are account keyed and guarded after reads | No change |
| Deals, deliveries, matches, match detail, offers | Shared queries are account keyed and guarded after reads | No change |
| Notifications | Shared badge queries and screen inbox query are account keyed and guarded | No change |
| Chat | Thread list is account keyed; thread controller watches account ID and is auto disposed | No change |
| Parcel photo URL | Previously only keyed by request/media IDs, a private signed URL | Scoped to account and authentication generation |
| Discovery, boost, saved places, push preferences, compatible requests | Screen-local `autoDispose` providers/controllers; auth routing removes their screens on logout | No persistent shared cache changed |

The app continues to use account-keyed shared queries and route disposal for screen-local state. Authentication generation is added only to the private reads that had a retained-listener risk or a sensitive URL. `refreshVolatileState` remains a mutation refresh helper; it is not relied on for session privacy.

## DEF-MOB-07 — Find Travelers query race

`loadMore()` captured `current` before awaiting the network and later wrote `current.copyWith(...)`. A sort or refresh could replace the result set while the old page was in flight, then the old page restored the prior sort and candidates.

Each first-page query now increments `_queryGeneration`. Pagination captures that generation and the exact loading-state object it created. A response or error can update state only when both still match. This identifies request ID (fixed for one controller), intended sort, page cursor, and refresh generation without comparing only the sort string. Sort and refresh clear an in-flight pagination spinner; older first-page responses also cannot replace a newer query. Tests complete delayed futures out of order for sort, refresh with the same sort, a second sort, and ordinary pagination with deduplication.

## Codex targeted verification

| Gate | Result |
| --- | --- |
| J9.1 Admin ban regression | 1 passed; Super, Finance, Trust, direct HTML, Django Admin and JWT API cases |
| Existing Admin role boundary tests | 3 passed |
| J9.1 ratings isolation | 3 passed; A→logout→B, A→logout→A with changed server data, and an in-flight A response after B login |
| J9.1 Find Travelers races | 4 passed |
| Existing Find Travelers and profile tests | 27 passed |
| Changed Dart file analyzer | No issues |
| Changed Python file Ruff lint | Passed |
| Formatter | Edited Dart source and tests formatted; Python new files formatted. Full repository formatter awaits Gemini rerun. |
| Migrations | No schema or migration changes |

Full Flutter, full Django, broad Admin/mobile, schema drift, localization, and CI are reserved for Gemini verification. No APK, merge, push, CI trigger, or deployment in this handoff. Stripe and Chargily remain TEST; `PAYOUT_DZD_EXECUTION_ENABLED=false`; no real-money or LIVE activation.

## Verification and release ledger

| Stage | Status |
| --- | --- |
| Gemini verification of `7d2dbc40fd952e1963ab3a859c08c15ad9152e5a` | RED: the three critical repros passed, but 3 payout-detail widget tests and formatter failed; new Admin test required static files in a clean checkout |
| J9.1 follow-up | Payout-detail tests now establish an authenticated session; Admin ban test overrides static storage; discovery source was formatted. The J8.1 test file's canonical Git content was already formatter-clean on this workstation. Focused reruns: 3 payout-detail and 1 Admin test passed; changed Dart analysis, targeted formatter, and Ruff passed. Broad Gemini rerun pending. |
| CI | Not triggered; pending Gemini green report |
| Merge and push | Not done |
| Railway TEST deployment | Not done; required after reviewed merge for the Admin runtime change |
| Healthz and readyz on deployed SHA | Pending deployment |
| New APK | Not built; deferred until later J9 remediation phases |

The J8.3 APK remains **not a release candidate**. Remaining J9 MAJOR and MINOR findings are outside J9.1.

Gemini's first broad pass reported 938 Flutter passes and 3 payout-detail test
failures, with a clean analyzer and localization result. Its J9 adversarial
Admin suite had 13 passes and 2 failures attributed to the already-open
`DEF-ADM-02` payout-profile feature gate. J9.1 remains unapproved until Gemini
re-verifies the follow-up commit. No CI, merge, TEST deployment, or APK build
has occurred.
