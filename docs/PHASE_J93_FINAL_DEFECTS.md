# J9.3 — Final Remaining Defect Remediation

Date: 2026-09-20
Starting `main`: `35b3d4fbafb07a9e55489e5ca39622cb369a20a8`
Implementation branch: `codex/j93-final-defects`
Initial independently verified implementation SHA: `e0e9b5ff062dcb93a9ca9e6821163d935826d2af`. A CI-discovered queue-cost follow-up is described below.

## Scope and outcomes

| Finding | Classification | Root cause | Remediation |
| --- | --- | --- | --- |
| J9-BE-01 | MAJOR | Journey route writes and publication checked leg chronology but not whether the first departure was already elapsed. Lifecycle later expired the record. | Route create/edit rejects a first departure at or before authoritative server time. Publication rechecks under lock with one captured, timezone-aware server instant. Existing leg ordering and arrival rules remain. |
| DEF-ADM-02 | MAJOR | `require_profiles()` raised `PermissionDenied` before distinguishing a disabled deployment from an unauthorized operator. | Payout-review queue, detail and cheque evidence first enforce Finance/Super capabilities; authorized operators see an explicit HTTP 503 configuration-unavailable page while disabled. Unauthorized staff still receive 403. The feature flag remains disabled where configured. |
| DEF-ADM-03 | MAJOR | Finance reporting's deliberate standalone-PostgreSQL guard raised a generic `RuntimeError` that console views did not translate. | A typed `FinanceSnapshotUnavailable` is rendered as a controlled 503 on Finance HTML views and as a 503 code on the control-plane JSON endpoint. No snapshot or financial values are fabricated. Standalone PostgreSQL still sets read-only repeatable-read isolation and the 10-second statement timeout. |
| DEF-MOB-13 | MAJOR | A loaded Deal with no sender/traveler perspective rendered `SizedBox.shrink()`. | Unrelated accounts, 403, 404 and gone links use one localized unavailable state with screen-reader live-region semantics and safe Home/Back recovery. Chat and Deal details remain hidden. |
| DEF-MOB-04 | MINOR | Request pricing surfaced raw `serverDetail` in a primary notice. | Pricing failure copy now comes from structured API kind/code through the existing localized mapper; unknown failures use a safe generic localized response. Raw server prose is never rendered there. |
| DEF-MOB-10 | MINOR | The Journey editor had a lower capacity bound only, while the new Journey serializer lacked the retired Trip contract's ceiling. | Adopted the existing server-side V1 Trip maximum of **200.00 kg per leg** in the Journey serializer and mobile route draft. Both enforce 0.01–200.00 kg and at most two decimal places; no client-only limit was invented. No transport-mode-specific capacity limit exists in the V1 specification. |
| DEF-MOB-11 | MINOR | Nonempty malformed CCP key/RIP values returned “required”. | Shared digits validator distinguishes empty from malformed; localized EN/FR/AR copy covers CCP number 1–20 digits, key exactly 2, RIP exactly 20. |
| DEF-MOB-12 | MINOR | Email verification and reset treated nonempty wrong-length codes as “required”. | Both use one six-digit validator: empty is required; malformed is localized “Code must be 6 digits” or equivalent. The entry component remains limited to six digits. |

The narrow adjacent misuse audit found the CCP and code cases above. No other adjacent launch-critical nonempty-malformed `validationRequired` use was found. The server remains authoritative for capacity, time, KYC, money and private Deal access. No models or migrations changed.

## Codex targeted verification

- New J9.3 Django tests: **14 passed** (Journey timing/capacity/edit/publish, payout-review roles/flag, Finance snapshot environment and PostgreSQL statements).
- Existing directly affected Journey suite: **22 passed**; matching route/timing suite: **31 passed**.
- J9.1 banned-admin direct-URL regression: **1 passed**.
- New J9.3 Flutter tests: **18 passed** (Deal participants/unrelated/403/404, EN/FR/AR, semantics/recovery, quote error copy, capacity, DZD, verification and reset code).
- Existing directly affected Flutter route, payout and J9.2 re-entrancy suites: **59 passed**.
- Changed-file Ruff check: pass. Changed-file Dart analyze: no issues. Flutter localization generation: pass, untranslated report `{}`. Impeccable changed-screen detector: `[]`.
- Django `makemigrations --check --dry-run`: **No changes detected**.
- Full Django/Flutter suites, broad Admin/Finance/regression suites, full analyzer/formatter, deploy check and static/config checks were **not run by Codex** under the J9.3 test budget; they are assigned to Gemini.

## Verification and release gates

- Independent Gemini verification: **GREEN** on the exact implementation SHA with a clean tree. Full Flutter **974 passed**, analyzer **0 issues**, Dart formatter **188 files unchanged**, EN/FR/AR localization parity `{}`, Journey/matching **133 passed and 10 skipped**, Admin/Finance **100 passed**, deployment safety **40 passed**, and six adversarial probes passed. Ruff, schema drift, production deployment check, and static/Caddy checks passed. All eight J9.3 findings and prior J9.1/J9.2 fixes were independently judged closed with no new regression.
- Full Django caveat: the `test_local` SQLite discovery reported **1,590 passed, 100 skipped, 1 failure**: a test explicitly requiring PostgreSQL. Gemini reran that test on PostgreSQL and it passed. The PostgreSQL-backed CI full-Django job remains the merge gate; this report does not claim a full PostgreSQL Django suite pass.
- [PR #7 CI run 35477127627](https://github.com/is-bo/shiptripis/actions/runs/35477127627) on the verified implementation plus documentation-only record had five green jobs, but its PostgreSQL Django job found one performance regression: `test_the_review_queue_stays_cheap_and_bounded_as_it_fills` measured 16 queries against a limit of 14 (2,244 passed, 34 skipped, 1 failed). The enabled payout-review route had performed two fresh capability checks after the J9.3 feature-gate change. The follow-up fix keeps the existing `require_capabilities()` check on enabled routes and performs the explicit capability check in `_require_console_profiles()` only when the feature is disabled. Thus enabled and disabled paths still deny unauthorized/banned staff, while the enabled queue avoids the duplicate reads. Focused SQLite tests (the failing query-budget test plus all seven J9.3 Admin tests) passed **8/8** after the fix, and the J9.1 banned-admin direct-URL regression passed **1/1**; changed-file Ruff passed. A local PostgreSQL rerun could not authenticate to the local development database, so the PostgreSQL CI result remains the required gate. The new implementation SHA needs independent verification before CI rerun, merge or deployment.
- Railway TEST deployment, `/healthz`, `/readyz`: **PENDING** renewed independent verification, green CI, merge and exact merged-SHA deploy. Stripe/Chargily TEST and `PAYOUT_DZD_EXECUTION_ENABLED=false` must remain unchanged.
- APK: **NOT BUILT**; final release-candidate packaging remains after J9.3 verification, merge and deployment.
- Remaining known J9 product defects after the original independent verification: **0 CRITICAL, 0 MAJOR, 0 MINOR**. The CI-discovered performance regression is fixed locally but remains unverified on PostgreSQL and independently; CI and TEST runtime release gates remain.

The previous J9.1 banned-admin, account isolation and discovery-race fixes and J9.2 quote identity, exact-money, transaction guard, re-entrancy and mobile departure protections were not intentionally changed. Directly affected tests above passed and Gemini independently reconfirmed the broader regression matrix.
