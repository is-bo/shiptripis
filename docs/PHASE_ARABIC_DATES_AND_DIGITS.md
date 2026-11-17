# Arabic dates and digits (2026-11-17)

Ismail's request: in Arabic, use the Algerian month names (جانفي، فيفري، مارس، أفريل، ماي، جوان،
جويلية، أوت، سبتمبر، أكتوبر، نوفمبر، ديسمبر) instead of the Mashriq ones (يناير، أغسطس...), and
Western digits (0-9) instead of Arabic-Indic ones (٠-٩), on every surface.

## Where Arabic dates and numbers come from

| Surface | Before | After |
| --- | --- | --- |
| App screens (`LocaleFormats`, `Money`, weights, distances) | Already `ar_DZ`: Algerian months, Western digits | Unchanged, still the one home of the rule |
| Flutter's date picker, time picker and `MaterialLocalizations` | Bare `ar`: أغسطس, ٠-٩, and a 12-hour dial with ص/م | `LocaleFormats.materialDelegate` builds Flutter's Arabic strings with the `ar_DZ` formats and a 24-hour clock |
| Boost history date | `MaterialLocalizations.formatFullDate`, a second date formatter | `LocaleFormats.fullDate`, like every other date in the app |
| Date and time together ("14 نوفمبر, 15:00") | Latin comma | Arabic comma: `14 نوفمبر، 15:00` |
| Translated counts ("12 travelers" on Find travelers) | `compact` number format in bare `ar`: ١٢ | Plain integer, like every other count in the ARB files |
| Emails: "Protection ends at", "Payment protection runs until", "Expires at" | Raw ISO timestamp, or `2026-09-01 10:00 UTC` | `1 سبتمبر 2026، 10:00 UTC` (and the same in English and French) through `apps/core/locale_format.py` |
| Push notices | Fixed text, no dates or numbers | Unchanged |
| Staff console, exports | English only, Western digits | Unchanged |
| Public website (`web/ar/index.html`) | One caption said ٣٠٫٠٠ يورو | `30.00 يورو`; the static web check now refuses Arabic-Indic digits and Mashriq month names |

## Decisions

- **One rule per side.** The app keeps `LocaleFormats.intlTag` (`ar` to `ar_DZ`) and now hands the same
  formats to Flutter's widgets, so there is no second Arabic formatter. The server has one small
  module, `apps/core/locale_format.py`, used by the email builder. The month names there are data, not
  `.po` entries, so a translation can never bring أغسطس back.
- **The app's delegate list has one home.** `appLocalizationsDelegates` in `app/app_settings.dart` is
  used by the app and by the test harnesses, which had three copies of the list.
- **Email dates are in UTC and say so.** A recipient's time zone is not known when the email is
  written. The label "Expires at (UTC)" became "Expires at", since the value now ends in "UTC".
- **An Arabic date in a plain-text email is not forced left to right.** The text part wraps machine
  values (codes, tracking numbers, links) in a left-to-right isolate; a value written in Arabic is now
  left alone, otherwise the date would read backwards.
- **The Arabic time picker is 24-hour**, like every time the app prints (`21:40`) and like French.
  Flutter's Arabic default was a 12-hour dial with ص and م.
- Old documents that quote Arabic-Indic digits (for example `PHASE_J6_FINAL_UX_REVIEW.md`) are
  records and were left as they are. Tests that feed Arabic-Indic digits as input, to prove the
  server refuses them, stay.

## Tests rewritten

- `test_v2_readiness.py::test_real_invitation_vault_preserves_explicit_locale_and_actual_expiry`
  checked for `2026-..-.. ..:.. UTC`; the expiry is now written in the email's language, so the test
  checks for `format_utc_datetime(expires_at, language)`.

## New tests

- `mobile/test/arabic_dates_and_digits_test.dart`: every month in Arabic through `LocaleFormats`,
  money, times and translated counts, `MaterialLocalizations`, and the date and time pickers on screen.
  The Material and date picker tests fail with Flutter's stock delegate.
- `apps/core/tests/test_locale_format.py` and two email tests in `test_email_presentation.py`.

## Checks run

Flutter: format, analyze and the whole suite, 1,539 passing (1,533 before plus 6). Django: ruff, and
the notification and core tests locally (234); the whole suite runs on Postgres in CI. Static web
check passes, and fails on the old Arabic page.

## Screenshots

`/mnt/project-files/l-series-screens/arabic-dates/`, Arabic, 360 px wide.
