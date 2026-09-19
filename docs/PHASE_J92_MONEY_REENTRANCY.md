# Phase J9.2 — Transaction, Money & Re-Entrancy Remediation

**Starting SHA:** `74f0fcfde610542bc81b2c38528c924f3f2fab5d`

**Branch:** `codex/j92-money-reentrancy`

**Scope:** `DEF-MOB-01`, `DEF-MOB-02`, `DEF-MOB-03`, `DEF-MOB-05`,
`DEF-MOB-06`, `DEF-MOB-09`, and `DEF-MOB-14` only.

The implementation is complete and independently verified GREEN by Gemini at
`8c565b1f7060ca5f4fa5e384cebacefbd9698161`. CI remains pending. No backend
runtime code, schema, migration, payment economics, matching rule, payout rule,
or deployment configuration changed.

## Defects and fixes

### DEF-MOB-01 — stale pricing quote

The request screen stored the reward used for the last quote and considered the
quote current whenever that reward still matched. Origin, destination, parcel
weight, dimensions, ready-window end, and deadline were ignored.

`RequestQuoteInputs` is now the immutable local identity of every value sent to
`POST /api/parcels/pricing-quote`:

- pickup and delivery place ids;
- actual weight;
- optional length, width, and height;
- ready-window end and deadline;
- chosen reward.

The screen stores the exact identity beside the response. A quote is current
only when record equality matches the current form. The existing monotonically
increasing request sequence and request cancellation remain in place. A response
may now apply only when both its sequence is newest and its captured input
identity still equals the form. Posting also waits for a current quote.

### DEF-MOB-03 — exact EUR parsing

`AppAmountField.centsOf` previously parsed a `double`, multiplied it by 100,
and rounded. It therefore turned `12.345` into 1,235 cents.

The parser now accepts a decimal string with one `.` or `,` separator and at
most two fractional digits. It converts the whole and fractional digit groups
directly to integer cents. It never derives cents with IEEE-754 arithmetic.
Inputs with more than two decimals return `null`, show localized precision
validation in English, French, and Arabic, and cannot be submitted. Nothing is
rounded or truncated.

### DEF-MOB-02 — Offer Accept re-entrancy

Accept now acquires an `_acceptPending` gate before opening the confirmation
dialog. Repeated activation cannot open another dialog. All Offer controls are
disabled while confirmation is open; after confirmation, the existing mutation
busy state takes over. The gate clears on cancel, refusal, or completion.

### DEF-MOB-05 — guest payment re-entrancy

Guest Pay rejects entry while checkout creation is busy or after successful
handoff. The primary control disables immediately. The existing `finally` path
clears busy state after failure so a payer can retry.

### DEF-MOB-06 — Boost save race

Boost save rejects re-entry. Presets, custom amount input, and Save/Remove are
disabled for the entire mutation. After the write, the screen awaits a fresh
server read and replaces its selection and text with the authoritative saved
Boost before reporting success.

### DEF-MOB-14 — form double submission

Immediate entry guards were added to request creation, Journey creation,
dispute opening, and rating submission. Busy state is established before the
first repository call and reset in the existing `finally` paths. Failed calls
remain retryable. The posting deposit order boundary was also guarded while its
shared amount validation was audited.

### DEF-MOB-09 — past Journey creation

Journey creation passes a single captured `now` into route validation. A
departure that is before or exactly equal to that instant is rejected; a
departure after it is accepted. The validation model takes an optional clock
value, which makes boundary tests deterministic. Journey edit behavior was not
changed by this creation-only defect.

**CODEX BACKEND REVIEW NEEDED — independently confirmed:** the current V1
`JourneyRouteWriteSerializer` checks leg ordering and arrival-after-departure but
does not reject a first `depart_at` in the past. `publish_journey` also omits that
check. Gemini reproduced a past-dated Journey passing serializer validation,
being created, and publishing as active. Lifecycle annotation then classifies it
as expired and keeps it out of discovery, but direct API callers can still write
invalid data. This is a separate medium-severity backend integrity follow-up. No
backend behavior was changed because J9.2 explicitly requires reporting a
backend correctness discovery instead of expanding scope.

## Amount-field caller audit

| Screen | Uses `centsOf` | Expected decimal policy | Regression tested |
| --- | --- | --- | --- |
| Request creation — declared value and reward | Yes | Exact EUR cents, `.`/`,` accepted, at most 2 decimals | Yes — exact parser, localized precision, request/pricing suite |
| Posting deposit — custom amount | Yes | Exact EUR cents, within server minimum and maximum | Yes — J6.3 deposit suite |
| Boost — custom amount | Yes | Exact EUR cents, within server maximum; empty means remove | Yes — held-save and Boost economics suites |
| Discovery — proposed reward | Yes | Exact positive EUR cents | Yes — J6.1 proposal coverage plus shared parser |
| Offer — counter amount | Yes | Exact positive EUR cents | Yes — J6.1 Offer coverage plus shared parser |

All active callers were inspected. Invalid exact parsing no longer falls back
to an unrelated default amount on deposit or Boost screens.

## Targeted verification run by Codex

The strict J9.2 test budget was followed. Codex ran only new J9.2 tests and
directly affected mobile modules.

- 125 passed: J9.2 money/quote and form re-entrancy, guest pay, route model,
  request creation, Offer/Boost projection, and Boost economics.
- 10 passed: J6.3 request pricing and deposit regression module.
- `flutter analyze --no-pub` on 19 changed production/test files: no issues.
- `dart format` on changed Dart files: clean.
- `flutter gen-l10n`: successful; `l10n_untranslated.json` is `{}`.
- `git diff --check`: clean.

## Independent Gemini verification

Gemini verified the exact implementation SHA
`8c565b1f7060ca5f4fa5e384cebacefbd9698161` with a clean tree and preserved
stash, and returned **GREEN** for all seven scoped mobile defects.

- Full Flutter: 956 passed across 55 files.
- J9.2 targeted: 118 passed.
- J7/J8 regression: 247 passed.
- J9.1 mobile regression: 23 passed.
- Backend Admin/Journey regression: 23 passed.
- `flutter analyze --fatal-infos`: zero findings.
- Dart formatter: 187 files clean.
- Localization: all 3 locales generated with no untranslated keys.
- Adversarial attempts confirmed one dialog/mutation, retry after failure,
  stale-quote rejection, exact money rejection, locked Boost state, guarded
  forms, and deterministic Journey time boundaries.
- `DEF-ADM-01`, `DEF-MOB-07`, and `DEF-MOB-08` remained closed.

Gemini changed no repository file, stash, branch, deployment, or APK artifact.

## Release state

- Gemini verification: GREEN on
  `8c565b1f7060ca5f4fa5e384cebacefbd9698161`.
- CI: pending branch push and run result.
- Railway deployment: not required; backend runtime code did not change.
- Migration: none.
- APK: not built; J9.3 remains.
- Scoped J9.2 mobile findings: all seven closed.
- Remaining previously tracked J9: 0 critical, 3 major, 4 minor. The newly
  confirmed medium-severity backend Journey integrity gap also requires a later
  owner-classified remediation phase.
