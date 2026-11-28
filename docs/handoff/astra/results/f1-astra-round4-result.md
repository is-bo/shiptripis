<!-- Astra 6.2, high effort, read-only. Run by Ismail in the cloud, 2026-11-27; pasted into the project chat together with the P3B, P3C and N1 results (tables arrived tab-separated, reformatted as Markdown; a few inline links were lost in the paste) and committed by the F1 builder. Code head c559318 (PR head ae7ef13). -->

I would reject PR #69 at c559318 because a preference PATCH can commit after onboarding releases the method lock and before it sends the first Stripe POST, leaving the traveler’s only active account in the country they just replaced.

### Round-3 items

| # | Status | Note |
|---|---|---|
| 1 · Stale country in the request | Fixed | A phone that posts country=DE after FR was saved gets 409 payout_preference_changed before any Stripe call. The locked version check also catches a change during platform verification. |
| 2 · Late timeout and recovery of the wrong account | Fixed | A late timeout cannot reopen a failed operation or erase an accepted account ID. Recovery matches shiptrip_operation, and binding checks the country Stripe returned. |
| 3 · First POST for a superseded intent | Partly fixed | A new call recovering a crashed FR worker searches after DE is declared. A worker that already obtained its FR plan can still make the first POST after DE commits. |
| 4 · Stale readiness during standing-account binding | Fixed | Planning locks the method, reloads and locks the standing account, then binds and projects readiness in that transaction. The named regression test misses the original race. |
| 5 · Setup after a platform or mode switch | Fixed | The EUR read uses the configured platform and mode. A historical binding leaves configure_eur available when setup in the new environment can proceed. |
| 6 · Unresolved creation and closed country | Partly fixed | GET and POST agree when FR closes and DE remains open. They still return different reasons when the last open country closes. |
| 7 · Preference change during link issuance | Partly fixed | A DE-to-FR PATCH discards the DE link, and the response uses the checked method. A change away and back that rebinds the same account still passes the final check under a different version. |
| 8 · Two calls for one declaration | Partly fixed | Both succeed when both get through planning before the first binds. If the first binds while the second is checking platform identity, the second still reports a traveler preference change. |
| 9 · Misleading account_country | Fixed | A refused DZ declaration beside a usable FR account returns account_country=null. A refusal caused by the standing account’s own country carries that country. |
| 10 · Replay and search assertions | Fixed | The test captures the first create call independently and compares every gateway argument. The search test asserts the metadata key, operation reference and creation-time bound. |

### New findings and remaining failure cases

| Severity | File and line | Concrete failure (inputs or state → wrong result) | Suggested fix |
|---|---|---|---|
| **Blocker** | payout_accounts.py:1025 · payout_accounts.py:882 | A plans FR and releases its locks. B commits a revision-checked PATCH to DE. A then sends its first create_account(FR). The binding guard preserves DE, but the newly created FR account occupies the sole active slot. The next DE setup returns stripe_account_country_mismatch. This requires neither a crash nor an expired key. | Serialize dispatch with a PATCH that supersedes it. A PATCH that wins must invalidate the unsent plan. Once dispatch wins, the PATCH must observe the in-flight creation. Another unlocked check before the POST would leave the same gap. |
| Should-fix | payout_accounts.py:589 | A and B read the same unbound FR version. While B waits for platform_identity(), A creates and binds FR. B rejects the version change before looking at the standing account. It returns 409 payout_preference_changed even though the only writer was A’s successful binding. | Under the method lock, recognize the exact binding successor of B’s starting declaration. Keep the conflict for an intervening traveler declaration, including a change away and back. |
| Should-fix | payout_accounts.py:1175 | While an FR link is being minted, another session declares DE, declares FR again and onboards the standing FR account. The old call returns 201 because the account ID matches again. The URL is for the right account, but the response describes a different declaration from the one the call served. | Carry the bound version ID from account resolution through link issuance and compare it under the final method lock. |
| Should-fix | payout_mobile.py:133 · payout_accounts.py:516 | With Connect on, no standing account and an FR creation marked not_found, close the last allowed country. GET reports stripe_connect_no_countries. POST with the saved declaration reports stripe_account_unresolved. F2 receives two explanations for the same state. | Give empty-allowlist and unresolved-creation refusals one precedence on both paths. Extend the existing precedence test with an empty list. |
| Should-fix | payout_accounts.py:905 · payout_accounts.py:955 | A superseded-operation search sees no account. Before its result is recorded, the original create caller records the account as accepted. The search’s conditional update affects zero rows, yet it still tells the traveler that Finance must investigate. In the opposite order, accepting the account leaves provider_object_status="not_found" alongside its known ID. | On a zero-row update, reload the settled operation and answer from the standing account and current declaration. Clear the obsolete search marker when recording definitive success. |
| Should-fix | payout_accounts.py:1030 · payout_accounts.py:982 | B plans a replay and pauses. A records the account, and a refresh records newer Stripe state. B resumes, timestamps its request and receives Stripe’s cached original create response. _apply_snapshot treats that old body as newer than the refresh and can regress account and method readiness. | Use the replay to establish account identity. Preserve any newer readiness observation, or retrieve current account state before projecting readiness. |
| Should-fix | payout_account_api.py:105 · payout_accounts.py:1205 | After a same-mode platform switch, GET correctly hides refresh and dashboard actions for the old account. A direct refresh, or dashboard POST for an account with details submitted, still sends the old account ID using the new platform credential. Stripe’s refusal becomes a misleading 502. | Apply the same environment check when resolving accounts for these writes, before provider I/O. |
| Nit | test_phase8fh6a_mobile.py:1641 · test_phase8fh6a_mobile.py:1309 | The readiness test finishes refresh before onboarding reads the standing account, so the former stale-copy implementation also sees ready. The supersession test changes FR to DE, so removing the declaration UUID from the fingerprint still passes on the country difference alone. | Place the refresh between standing-account selection and binding. Add an ambiguous FR create followed by FR → DE → FR inside the replay window, and assert a search with zero create calls. |

### What I checked

I fetched origin, reviewed the three-dot package diff against origin/main, and inspected c559318831160de31f9c7b5ac24df66b83ab8677 separately. The only later branch commit, ae7ef13, adds the review prompt.

The fingerprint distinguishes two immutable FR versions, including FR → DE → FR. For the request builder and constants at this head, I found no path that replays one key with a different body. One boundary matters here: disabling EUR and re-enabling FR preserves the version ID, so an ambiguous FR operation remains replayable across that off/on cycle. The fingerprint identifies the stored version, not each act of consent. (Creation identity · Preference versioning)

I found no cross-traveler binding or second Stripe account from ordinary concurrent retries under the stated Stripe replay guarantees. A definitive answer can still settle an earlier search miss. The outstanding-operation predicate protects an accepted ID and a definite refusal from late transport errors.

I traced member refresh, hosted return, webhook processing, scheduled refresh, execution readiness and admin reconciliation. I found no reversed method/account lock acquisition. Funding takes the method-set lock before selecting the immutable instruction. I also found no production caller of resume_account or the removed helpers.

The rewritten H2 recovery tests retain their key, account-count and expired-window assertions through ensure_account. This was a read-only source review. I did not run Django, exercise PostgreSQL concurrency, call Stripe, check CI or independently run mutation tests.

Overall verdict: reject
