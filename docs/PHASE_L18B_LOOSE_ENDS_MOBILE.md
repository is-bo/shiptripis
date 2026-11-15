# Phase L18B: Loose ends before acceptance, mobile

Package L18B of `docs/WASSLA_DISCOVERY_PRO_PLAN.md` (plan L18B and 5.1f). The app half of what L18A
built (`docs/PHASE_L18A_LOOSE_ENDS_BACKEND.md`, section 6). Mobile and the helper's knowledge notes
only. **No backend code, no migration, no new setting.**

## 1. Own rating from the server

The Profile "Rating" fact reads `GET /api/users/me/ratings/summary` (`ownRatingSummaryProvider`,
`RatingRepository.ownSummary`, parsed as the existing `TravelerRating`) and does no arithmetic. The
label is **"Rating" / "Note" / "التقييم"**, not "Recent rating": the figure is the all-time one on the
public card, so a rating staff removed is already left out. `receivedRatingsProvider` stays for the
Ratings list; `refreshOwnRatings` re-reads both after a report.

## 2. Welcome caption

"HANDOVER · 6 CHARACTERS" is now **"HANDOVER CODE" / "CODE DE REMISE" / "رمز التسليم"**: no number in any
language, because the length is an admin setting.

## 3. Contact support

One shared action, `lib/features/common/contact_support.dart`: `openSupportEmail` builds a `mailto:`
to the address from `GET /api/support` (`supportEmailProvider`, no sign-in needed) with the subject
"Help with Wassla", or "Help with Wassla delivery <tracking number>" from a delivery. If no email app
opens, a note names the address. It appears on: Profile (a row in the support section), the dispute
detail screen, the delivery's problem list (`ProblemsSection`), the dispute-window-closed state of
"Open a dispute" (it used to draw a label with no action), and the staff-paused journey banner. While
the server answers `null`, or the read fails, **every one of them is absent**: the staff-paused banner
then reads "Wassla paused this journey." with no word about contacting anyone, and the dispute-window
text no longer says "contact support" (the action carries it). `authVerifyNoCode` no longer sends the
member to support either; it offers the resend.

## 4. Email not confirmed

- **One handler**, `lib/features/auth/email_gate.dart`: `isEmailVerificationRequired(error)` and
  `handleEmailVerificationRequired(context, error, {onConfirmed})` push the existing verify-email screen
  and report whether the member confirmed. New code constant `ApiErrorCode.emailVerificationRequired`.
- **Callers**: posting a request (`RequestCreateScreen._handleSubmitFailure`), payout setup writes
  (`PayoutMethodsScreen` both action handlers, `DzdSetupScreen` submit). Each screen is never left, so
  everything the member typed is still there when they come back.
- **Verify-email screen**: "Send the code again" (`POST /api/auth/verify-email/resend`; 429 shown as the
  usual failure note), a clear-the-field-on-resend, copy that says only the newest email's code works,
  uses the account's own address when the route carries none, and pops `true` on success.
- **Router**: `/auth/verify-email` is now reachable while signed in (the signed-in redirect sent every
  `/auth/*` path to Home, so the screen that sign-up pushes right after signing in was never shown).
- **Profile** offers "Verify email" while `is_email_verified` is false.
- **Password reset** ends with `goNamed(signIn)` and says every device was signed out. A refresh answered
  401 already means "sign in again" through the existing session-expiry path.

## 5. Screenshots

`/mnt/project-files/l-series-screens/L18B/`, 360 x 800, each as `-en` and `-ar`:
`profile-verify-support-rating`, `profile-support-row`, `verify-email-resend`, `dispute-support`,
`problem-list-support`, `paused-staff-support`, `paused-staff-no-support`.

## 6. Tests

Flutter **1,521 before, 1,533 after** (+12), `flutter analyze --fatal-infos` clean.

New, `test/l18b_loose_ends_test.dart` (12): Profile shows the server's figure under "Rating" and fetches
no list to average; a member with nothing counted reads "No ratings yet"; the label in three languages;
the caption has no digit in three languages; Profile support opens `mailto:` with a subject; no address
means no action; the tracking number is in the subject from a delivery; "Verify email" shows only while
unverified; a refused call opens verify-email, resend posts, the right address is verified, the host
screen is still there and `onConfirmed` runs; another refusal is not the gate; a reset ends on sign-in.

Existing tests changed: `FakeBackend` answers `GET /api/support` (`null`) and the rating summary by
default so tests about something else need not; the profile tests state the server's summary instead of
a ratings list; the staff-pause test expects the no-contact wording; the problem-list test settles once
more for the support read.

## 7. Judgment calls

1. **No banner before posting.** L18A suggested checking `me.is_email_verified` before the posting flow.
   A banner on the request form reads the session, and the form's 81 layout tests build a session that
   never settles, so it broke them for no product reason. The 403 handler gives the same result (the
   member confirms and returns to the untouched form); Profile offers "Verify email" up front. If the
   advisor wants the banner, it is one `InfoNotice` in `RequestCreateScreen` plus the test containers
   signed in.
2. The verify-email route is open to signed-in members (section 4); without it neither sign-up nor this
   package's flow could show the screen.
3. The support read fails quietly: a failed `GET /api/support` hides the action rather than showing a
   dead button.
4. The helper's knowledge notes (app-walkthrough, accounts-and-verification, messages-and-notices,
   reviews) were updated for the app as it now is; `INSTRUCTIONS.txt` regenerated (16 lines).

## 8. Known limits

- The resend cannot withdraw an email already being sent, so an older code may arrive after a new one;
  the copy says to use the newest email.
- The "Verify email" screen asks for the six-digit code only; there is no deep link from the email.
