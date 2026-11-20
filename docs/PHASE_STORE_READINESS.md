# STORE: what the App Store and Google Play need from the code (2026-11-20)

Ismail's request of 2026-11-20, from the store readiness report (project memory
`store-readiness-audit`): fix every code item. Nothing is deployed or published and no store or
provider was contacted. The map provider is unchanged (Ismail: later). The items that are not code
(privacy policy text, the live server, store accounts and listings) stay with Ismail; his steps are in
`docs/WASSLA_SETUP_FOR_ISMAIL.md` sections 5, 6, 10 and 11.

## What was built

| Item | What | Where |
| --- | --- | --- |
| Account deletion (App Store 5.1.1(v), Google Play) | `GET/POST /api/me/deletion`; Profile, "Delete account"; Apple token revoke | `apps/accounts/deletion.py`, `apple_revoke.py`, `views.py`; `mobile/lib/features/profile/delete_account_screen.dart` |
| Web deletion page (Google Play) | `/delete-account` in English, French and Arabic, with the in-app steps and an email route | `web/delete-account.html`, both Caddyfiles, `tools/check_static_web.py` |
| Report and block in chat (App Store 1.2) | Report a received message, block or unblock the other member, staff queue | `apps/chat/moderation.py`, `apps/accounts/blocks.py`, `apps/chat/views.py`, `apps/admin_panel/console_chat_reports.py`; `mobile/lib/features/chat/`, `features/profile/blocked_people_screen.dart` |
| A block stops dealing | Proposals, counter-offers, acceptance and "I can carry this" refused with `party_blocked` | `apps/matching/v1_services.py` (`PartiesBlocked`), `apps/discovery/interest.py` |
| Apple with Google on iPhone (4.8) | Google is offered on iOS only together with Sign in with Apple | `mobile/lib/core/auth/social_sign_in.dart` |
| App id | `eu.wassla.app` on Android and iOS, Firebase defaults, the method channel, docs | `mobile/android/`, `mobile/ios/`, `lib/core/push/` |
| iOS push | `aps-environment` in both entitlement files, `remote-notification` background mode; Apple sign-in picks the second file | `ios/Runner/*.entitlements`, `ios/Flutter/SocialSignIn.xcconfig`, `ios/scripts/check_social_sign_in.sh` |
| Privacy manifest | `PrivacyInfo.xcprivacy`: no tracking; collected data types; UserDefaults and file-timestamp reasons | `ios/Runner/PrivacyInfo.xcprivacy` |
| Info.plist | `ITSAppUsesNonExemptEncryption` false, `CFBundleLocalizations` en/fr/ar, camera and photo strings in three languages | `ios/Runner/Info.plist`, `ios/Runner/{en,fr,ar}.lproj/InfoPlist.strings` |
| Real version | Profile shows the installed version and build | `lib/core/env/app_version.dart`, `profile_screen.dart` |
| iOS release workflow | Manual, signed `flutter build ipa`, optional TestFlight upload | `.github/workflows/ios-release.yml`, `tools/mobile_release_config.py` |
| Android | `allowBackup=false` with backup and data-extraction rules; adaptive and monochrome icon; dead `network_security_config.xml` removed | `android/app/src/main/` |
| Retired paid boost | Every code path of the J1 paid package removed; the table stays | `apps/boosts/`, `apps/finance/`, `apps/matching/`, `apps/admin_panel/`, `mobile/lib/domain/boost.dart` |

## Contracts

- `GET /api/me/deletion` answers `{blockers: [...], password_required, apple_authorization_required}`.
  Blockers, in order: `open_deliveries`, `open_disputes`, `pending_payouts`, `pending_refunds`,
  `open_requests`, `active_journeys`.
- `POST /api/me/deletion` takes `password` and `apple_authorization_code`; 204 once deleted. Refusals:
  `password_incorrect` (400), `account_deletion_blocked` (409, with `blockers`),
  `apple_authorization_required` (409), `apple_authorization_refused` (400), `apple_revoke_unavailable`
  (503), `staff_account` (403), `account_deleted` (410). Sign-in throttle.
- `POST /api/chat/messages/<id>/report` takes `reason` (`spam`, `harassment`, `scam`, `inappropriate`,
  `other`), `note` (up to 500), `block`; 201 the first time, 200 with the same report after.
  `report_own_message` (400); a non-party gets 403.
- `POST` and `DELETE /api/matches/<id>/block`: 204, idempotent, parties only. `GET /api/me/blocks`
  lists `{user_id, name, deleted, blocked_at}`; `DELETE /api/me/blocks/<user_id>` lifts one.
- Chat: a send while blocked answers 403 `{"reason": "blocked"}`; eligibility carries `blocked_by_me`;
  a thread carries `blocked_by_me`, `counterparty_deleted` and `last_message_removed`; a removed
  message has `removed: true` and an empty `body`.
- Console: Trust > "Reported chat messages" (`trust/chat-reports/`), new capability `moderate_chat`
  (Trust and Super Admin). Audit actions `chat.reports_dismissed`, `chat.message_removed`,
  `chat.message_restored`. Work-list item `chat_reports`, urgent after 24 hours.
- Settings: `APPLE_TEAM_ID`, `APPLE_SIGN_IN_KEY_ID`, `APPLE_SIGN_IN_PRIVATE_KEY`. Production refuses to
  start with `APPLE_SIGN_IN_CLIENT_IDS` set and any of the three missing.
- Removed routes: `/api/boosts/packages`, `/api/boosts/preview`, `/api/parcels/<id>/boosts`,
  `/api/admin/boosts` (all already answered 410 or read a table nothing writes).

## Migrations

`accounts 0006` (`User.deleted_at`, `UserBlock`), `chat 0004` (`ChatMessage.removed_at/removed_by`,
`ChatMessageReport`), `admin_panel 0009` (`moderate_chat` capability, seeded on Trust),
`finance 0033` and `0034` (choices only: the paid-boost ledger kind, refund reason and job kind; no
SQL). `contracts/sql/schema.sql` regenerated. No table or column is dropped: `BoostPurchase`, its
table, `PaymentOrder.Purpose.BOOST` and `boost_reference` wait for a cleanup Ismail approves.

## Decisions (judgment calls)

- **Deletion waits for anything open.** It never cancels a request or a trip, never moves money. The
  member closes those through the existing flows, which keep their own refund and notice rules.
- **Deletion empties the account row instead of removing it.** Every reference to a member is
  `PROTECT`, and deliveries, payments, payouts and their payout details, ID check decisions, reviews,
  disputes and chats are records others and the law rely on. The email becomes
  `deleted-<id>@deleted.wassla.invalid`, so the real address can sign up again. Others see "Deleted
  account".
- **Apple first, then delete.** The server revokes the Apple token before it deletes, outside the row
  lock; a refused or unreachable Apple leaves the account untouched. The client id used is the first of
  `APPLE_SIGN_IN_CLIENT_IDS`. On Android an Apple-linked account is told to delete from an iPhone or
  write to support, because Apple gives a fresh code only on Apple devices.
- **A block is both ways and stops new dealing, not a paid delivery.** Chat sending, proposals,
  counters, acceptance and "I can carry this" stop; a funded delivery goes on (codes, progress,
  payout). History stays readable. Only the blocker lifts it.
- **Only the recipient reports, once.** Staff see only reported messages, with the 5 before and after,
  never a whole conversation. Chat text never reaches the AI helper; it sees only the count and cannot
  decide a report.
- **New capability `moderate_chat`** rather than reusing `moderate_ratings`, so chat access is granted
  on purpose.
- **Web page in three languages on one page,** matching the site's English-only support pages while
  giving French and Arabic readers the steps.
- **Policy keys of the paid package** (`packages`, `max_active_per_request`, ...) are still validated
  in settings versions: removing the validation would accept versions refused today. For Ismail's
  cleanup, with the table and `view_boosts`.

## Tests

New: `apps/accounts/tests/test_store_account_deletion.py` (15), `apps/chat/tests/test_store_report_block.py`
(10), `apps/finance/tests/test_deployment_safety.py` (Apple key at boot),
`mobile/test/store_report_block_delete_test.dart` (13), the version footer in
`profile_passport_test.dart`.

Rewritten to a changed rule (CLAUDE.md, never weakened):

- `mobile/test/egs_social_sign_in_test.dart`: "iOS offers Google without Apple" became "iOS offers
  Google only with Apple" (App Store 4.8).
- Paid boost tests removed with the code they covered (`apps/boosts/tests/test_boosts.py`,
  `test_phase_j61_offer_boost_projection.py` paid projection); asserts on `boost_order_ids`,
  `boost_funded` and `BoostPurchase` became the J2 equivalents (`test_j2_boost.py`,
  `test_l12a_offer_deadlines.py`, `test_h8a_guards.py`, `test_phase8fh5_control_plane.py`,
  `test_j2_h5_regression.py`); `api/admin/boosts` left the frozen staff route list in
  `test_l14_two_step.py` because the route is gone.

## Not verifiable here

No macOS, Xcode or Android SDK in this environment: the iOS build, the entitlements on a signed app and
the Android icon were checked by `tools/check_ios_config.py`, the release config script and a rendered
preview, not on a device.
