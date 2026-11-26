<!-- Astra 6.2, high effort, read-only. Run by Ismail on his second Codex account, 2026-11-26; pasted into the project thread and committed by the local operator. Code head f3f37a3 (PR head 8d1a1cd). -->

The original funding race is fixed, but I would reject PR #69 because Stripe onboarding can overwrite a newer payout-country declaration and make future funding use the superseded destination.

### Round-1 findings

| # | Status | Note |
|---|---|---|
| 1 | **Fixed** | Profiles-on funding acquires the traveler’s advisory lock before querying method rows. The PATCH, single-currency POST and DZD submission acquire the same lock before inserting a method or changing the enabled set. The PostgreSQL test has a proof gap described below. |
| 2 | **Fixed** | EUR remains selectable when another country is open. `eur.country_supported` describes the saved declaration, and both preference routes persist the normalized country. |
| 3 | **Partly fixed** | The DE-account/FR-declaration case now suppresses `configure_eur` and returns 409 on ordinary onboarding. A stale onboarding request can still restore DE over a committed FR declaration. |
| 4 | **Partly fixed** | An unsuccessful recovery search suppresses `configure_eur` for the tested case. Changing the declaration or the Stripe environment can still make the read and write disagree about the unresolved operation. |
| 5 | **Fixed** | Both member view families check authentication, profiles, traveler eligibility and email in that order. The overlapping refusals are covered across all seven writes. |
| 6 | **Fixed** | For newly submitted profiles, masking uses the CCP number after removing leading zeros. `1234` returns `34` and an empty RIP suffix. A one-digit CCP returns two empty suffixes. |
| 7 | **Fixed** | The DZD GET returns `setup` and `contract_version` from the common summary. Tests compare both reads with profiles on and off. |
| 8 | **Fixed** | DZD submission checks the private store configuration before consuming the proof. The test verifies 503 while the store is closed and successful reuse of the same proof after it reopens. |
| 9 | **Fixed** | The post-binding 502 now says the account was saved. A direct onboarding retry reuses it and retries schedule provisioning when needed. There is a separate gap in how the phone discovers that retry. |
| 10 | **Fixed** | The handoff documents 401 for a staff-banned inactive account. The test obtains a real bearer token before the ban and uses it for the subsequent reads and writes. |

### New findings

| Severity | File and line | Concrete failure (inputs or state → wrong result) | Suggested fix |
|---|---|---|---|
| **Blocker** | [payout_accounts.py:725][bind], [payout_accounts.py:654][bindnew] | Start onboarding with an enabled, bound DE account. While the request is checking the platform, a PATCH commits FR and installs an unbound FR version. Onboarding then locks the method, compares the DE account with its **earlier** DE declaration, and appends a bound DE version over FR. The next funding snapshot can use DE. There is also a sequential failure: an already-bound DE account plus an explicit, allowed `country="FR"` returns a DE link because the early return precedes the country check. | Carry the starting method version through onboarding. At binding, verify the locked method is still enabled and its version and country still match. Check the account country before the early return. If Stripe already created an account, retain its provider identity for recovery without replacing the newer preference. |
| **Should-fix** | [payout_mobile.py:120][precedence], [payout_accounts.py:809][declared] | A traveler has a standing DE account, an unbound FR declaration, and an FR-only allowlist. GET reports `payout_country_unsupported`. Onboarding accepts the FR declaration, reaches the standing DE account and returns 409 `stripe_account_country_mismatch`. F2 gets two explanations for the same state, and restoring DE is unavailable. | Use one country decision for the read and the write. Cover both cases where the allowlist closes the standing account’s country or the saved declaration’s country. |
| **Should-fix** | [payout_accounts.py:367][unresolved], [payout_accounts.py:433][fingerprint] | After an ambiguous FR creation, changing the declaration to DE makes onboarding fail the stored request fingerprint with generic 400. Before a failed search, GET still offers `configure_eur`. After a failed search, it promises `stripe_account_unresolved`. Separately, an unresolved operation under a previous platform or mode suppresses setup even though the write uses a fresh identity in the current environment. | Resolve the applicable creation operation by method, platform and mode on both paths. Surface a conflicting unresolved intent consistently and preserve its original key and request. |
| **Should-fix** | [payout_mobile.py:141][resume], [test_phase8fh6a_mobile.py:1087][retrytest] | The new failure test’s own account has pending transfers, an outstanding requirement and `details_submitted=false`. If the first hosted-link call fails, the traveler never receives a link. Refetch offers only `refresh`, which cannot mint one. The test succeeds by calling onboarding directly, bypassing the actions F2 is instructed to render. | Offer an onboarding retry when the bound account still needs traveler input. Test the sequence from 502 through GET to a successful **advertised** action. |
| **Should-fix** | [test_f1_payout_method_set_race.py:99][racetest] | The wait probe accepts any other backend waiting on any lock in the database. An unrelated waiter can release the leading worker before the trailing worker reaches the advisory lock. Both final-rail assertions can then pass under serial execution. | Capture both worker backend PIDs. Wait for the trailing PID’s ungranted advisory lock on this traveler’s key and verify the leading PID blocks it before releasing the barrier. |
| **Nit** | [test_phase8fh6a_mobile.py:191][riptest], [test_phase8fh41_console.py:328][queuetest] | The replacement test still searches for twenty `1` digits after its RIP fixture changed. The queue test used to catch either displayed suffix because both were `0000`. With distinct suffixes, it now checks only the CCP mask, so a displayed RIP mask would pass. | Assert against the submitted `data["rip"]` and check both actual masked suffixes on the queue. |

### What I checked and found sound

- I fetched the remote and reviewed `origin/main...origin/claude/f1-payout-availability`. The code head is `f3f37a3`. The sole later commit, `8d1a1cd`, adds the review prompt.
- I found no production method insertion or `enabled` change bypassing the set lock, and no new set-lock holder that then waits for a previously unheld Deal, Payout or User row. Checkout preflight still reads methods without the lock. It makes an admission decision from one query. The profiles-on path that persists the funded instruction goes through `create_snapshot` and takes the lock. Existing payouts return before destination selection. [Preflight and snapshot][snapshot]
- The CCP validator accepts Arabic-Indic decimal digits, whitespace, hyphens and zero-padding within ten digits. It checks the postal prefix and embedded account number without computing either key. Equivalent spellings reach the fingerprint with identical inputs. On new submissions, the two masks together do not expose any additional CCP digits beyond the CCP suffix. DZD preference versions also discard the EUR country, and submitted DZD profile versions record `DZ`. [CCP validation and masks][ccp] · [Preference versioning][pref]
- I found no cross-traveler account adoption in the reviewed binding paths or modification of an already-funded instruction by the new binding code. The blocker affects **subsequent** funding. The updated tests retain comparisons of the complete funded payout and bound version across DZD replacement. [Account ownership check][owner] · [Funded-row assertions][fundedtest]

Two **pre-existing** paths matter to the requested idempotency and deadlock checks:

- **A retry can create a second provider account.** If Stripe created the first account but its response was lost, an expired-window retry searches by metadata. A 403 on that search marks the original *creation* `failed`. After permissions are restored, the next onboarding request advances to a fresh key and can create a second Stripe account. The local uniqueness constraint cannot detect the first account because it was never bound. A failed recovery read must preserve the ambiguous creation identity. [Recovery search][search] · [Failure classification][failed] · [Key advancement][advance]
- **Onboarding and refresh can deadlock independently of the new set lock.** Onboarding locks the method before the standing account. A concurrent refresh locks the account before updating the method when readiness changes. PostgreSQL can abort either transaction. Both paths should acquire the method and account in the same order. [Onboarding locks][prepare] · [Refresh account lock][apply] · [Method status update][sync]

**Verification limits.** This was a read-only source review. I inspected the tests and transaction boundaries without running Django, reproducing the PostgreSQL interleavings, calling Stripe or storage, or verifying CI. The mask conclusion applies to profiles written by the reviewed code. The GETs return previously stored masks verbatim.

[bind]: https://github.com/is-bo/shiptripis/blob/f3f37a35193332bf52605db5e6216c2f27384485/backend/monolith/apps/finance/payout_accounts.py#L725
[bindnew]: https://github.com/is-bo/shiptripis/blob/f3f37a35193332bf52605db5e6216c2f27384485/backend/monolith/apps/finance/payout_accounts.py#L654
[precedence]: https://github.com/is-bo/shiptripis/blob/f3f37a35193332bf52605db5e6216c2f27384485/backend/monolith/apps/finance/payout_mobile.py#L120
[declared]: https://github.com/is-bo/shiptripis/blob/f3f37a35193332bf52605db5e6216c2f27384485/backend/monolith/apps/finance/payout_accounts.py#L809
[unresolved]: https://github.com/is-bo/shiptripis/blob/f3f37a35193332bf52605db5e6216c2f27384485/backend/monolith/apps/finance/payout_accounts.py#L367
[fingerprint]: https://github.com/is-bo/shiptripis/blob/f3f37a35193332bf52605db5e6216c2f27384485/backend/monolith/apps/finance/payout_accounts.py#L433
[resume]: https://github.com/is-bo/shiptripis/blob/f3f37a35193332bf52605db5e6216c2f27384485/backend/monolith/apps/finance/payout_mobile.py#L141
[retrytest]: https://github.com/is-bo/shiptripis/blob/f3f37a35193332bf52605db5e6216c2f27384485/backend/monolith/apps/finance/tests/test_phase8fh6a_mobile.py#L1087
[racetest]: https://github.com/is-bo/shiptripis/blob/f3f37a35193332bf52605db5e6216c2f27384485/backend/monolith/apps/finance/tests/test_f1_payout_method_set_race.py#L99
[riptest]: https://github.com/is-bo/shiptripis/blob/f3f37a35193332bf52605db5e6216c2f27384485/backend/monolith/apps/finance/tests/test_phase8fh6a_mobile.py#L191
[queuetest]: https://github.com/is-bo/shiptripis/blob/f3f37a35193332bf52605db5e6216c2f27384485/backend/monolith/apps/finance/tests/test_phase8fh41_console.py#L328
[snapshot]: https://github.com/is-bo/shiptripis/blob/f3f37a35193332bf52605db5e6216c2f27384485/backend/monolith/apps/finance/payout_snapshots.py#L144
[ccp]: https://github.com/is-bo/shiptripis/blob/f3f37a35193332bf52605db5e6216c2f27384485/backend/monolith/apps/finance/sensitive_data.py#L128
[pref]: https://github.com/is-bo/shiptripis/blob/f3f37a35193332bf52605db5e6216c2f27384485/backend/monolith/apps/finance/payout_profiles.py#L142
[owner]: https://github.com/is-bo/shiptripis/blob/f3f37a35193332bf52605db5e6216c2f27384485/backend/monolith/apps/finance/payout_accounts.py#L633
[fundedtest]: https://github.com/is-bo/shiptripis/blob/f3f37a35193332bf52605db5e6216c2f27384485/backend/monolith/apps/finance/tests/test_phase8fh6a_mobile.py#L789
[search]: https://github.com/is-bo/shiptripis/blob/f3f37a35193332bf52605db5e6216c2f27384485/backend/monolith/apps/finance/payout_accounts.py#L766
[failed]: https://github.com/is-bo/shiptripis/blob/f3f37a35193332bf52605db5e6216c2f27384485/backend/monolith/apps/finance/payout_accounts.py#L841
[advance]: https://github.com/is-bo/shiptripis/blob/f3f37a35193332bf52605db5e6216c2f27384485/backend/monolith/apps/finance/payout_accounts.py#L424
[prepare]: https://github.com/is-bo/shiptripis/blob/f3f37a35193332bf52605db5e6216c2f27384485/backend/monolith/apps/finance/payout_accounts.py#L410
[apply]: https://github.com/is-bo/shiptripis/blob/f3f37a35193332bf52605db5e6216c2f27384485/backend/monolith/apps/finance/payout_accounts.py#L475
[sync]: https://github.com/is-bo/shiptripis/blob/f3f37a35193332bf52605db5e6216c2f27384485/backend/monolith/apps/finance/payout_accounts.py#L567

Overall verdict: reject
