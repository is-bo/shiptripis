# P3B: profile photos in the app, chat included (2026-11-25)

Ismail's phone test of 2026-11-24: "Is there no option for profile pictures? Add it." Fix plan package
P3B (Sonnet, high), built on the server of P3A (`docs/PHASE_P3A_PROFILE_PHOTOS.md`, spec section 21) and
P3C (`docs/PHASE_P3C_CHAT_PHOTOS.md`, which publishes `counterparty_photo`). The app only: nothing under
`backend/` changed except one helper-knowledge sentence and the regenerated `INSTRUCTIONS.txt`. No
migration, no Go change. Nothing is deployed by this change.

## The owner's rules, as built

| Rule (Ismail, 2026-11-24) | Where |
| --- | --- |
| Optional photo: add, change, remove | Profile, "Profile photo" section (`profile_photo_section.dart`) |
| Everyone sees a photo, guests included, wherever the person appears by first name | `AppAvatar(photo:)` on every person surface below; no guest branch anywhere |
| No staff pre-check, so no "waiting" state | none built; a valid upload shows at once |
| Staff removal shows the member "removed by Wassla" with the reason | the section's notice, with "Dismiss" (`DELETE /api/me/photo`) |
| Photos in the chat list and the chat header | `_ThreadRow` and the new `AppTopBar.titleLeading` slot |
| No "Report this photo" | none built |
| New Arabic is Modern Standard Arabic, the brand stays "Wassla" in Latin script | `app_ar.arb` |

## The profile section

Placed after the verification card, which stays first because it gates carrying. One card: the photo (or
initials) beside one sentence on who sees it, the two actions, and the format rule ("JPEG, PNG or WebP, up
to 10 MB. It is cropped to a centred square.").

| State | What the member sees |
| --- | --- |
| Empty | initials, "Take a photo" and "Choose from library" |
| Uploading | the picked file as a centred square with a progress ring, buttons disabled |
| Active | the photo, "Change photo" (asks camera or library in a sheet) and "Remove photo" (asks first) |
| Removed by Wassla | a notice with the server's reason (a generic sentence when it gave none), "Dismiss", and the two upload buttons |
| Too large | "That image is too large. Choose one under 10 MB." The file is dropped, no retry |
| Unsupported type | "That file type isn't accepted." The file is dropped, no retry |
| Account inactive | "Your account can't add a photo right now. Contact support..." (`account_inactive`, also for banned). No retry |
| Storage unavailable | the file stays selected, "Try again" |
| Offline or timeout | the file stays selected, "Try again" |
| General error | the file stays selected, "Try again" |
| Camera or library refused | "We couldn't open your camera or photos. Check that Wassla is allowed to use them..." |

- **Picking.** `image_picker` (already a dependency; the iOS camera and library strings now name the
  profile photo in English, French and Arabic) with `maxWidth` and `maxHeight` 1024 and quality 88, behind
  `profilePhotoPickerProvider`, the seam a test overrides. A file over 10 MiB or not JPEG, PNG or WebP is
  refused on the phone, never sent.
- **Never retried automatically.** One `PUT /api/me/photo` per tap of a button. The app has no retry loop,
  timer or reconnect hook for it; "Try again" is the member pressing a button, and each press is a new
  upload. `ApiClient.upload` gained a `method` argument for the `PUT`; like every write it is sent once.
- **Any HTTP 413 is "too large"**, whatever its body, because Caddy answers an oversized body without
  JSON. `ProfilePhotoFailure.of` reads the status first, then the code.
- **Removing** asks first (`confirmAction`). Dismissing the Wassla notice does not ask: it is the same
  `DELETE`, which the server answers 204 even when there is nothing.
- The session moves to the photo the server answered, and not before (`SessionController.uploadPhoto` and
  `removePhoto`, with the same stale-session guards as the profile update).

## Where a photo is drawn

| Surface | Field |
| --- | --- |
| Person row on cards, trip preview sheet, Find Travelers trip sheet | `PublicPerson.photo` |
| Trip card, profile card (Browse, Home, person page) | the same |
| Request card | `RequestCard.senderPhoto`, beside "From <name>" |
| Find Travelers card and Matches for you | `CandidateTraveler.photo` (`avatarUrl` and its parse are removed) |
| Person page header | `ProfileCard.person.photo` |
| Route alerts that follow a person | `RouteAlert.subjectPhoto` |
| Proposal: negotiation header, proposal rows on Deliveries and on the request page | `Match.counterpartyPhoto(viewerId)` (`sender_photo`, `traveler_photo`) |
| Chat list rows | `ChatThread.counterpartyPhoto` |
| Chat header | a small avatar before the name, through `AppTopBar.titleLeading` |
| My own passport card and photo section | `Account.photo` (`OwnPhoto`) |

- A deleted counterparty shows initials whatever the row carries (`chatCounterpartyPhoto`); message bubbles
  carry no avatar; the header shows no avatar until the thread row is known; a blocked or closed thread
  still shows the photo; "Blocked people" shows none.
- `AppAvatar` draws the photo with `CachedNetworkImage`, `cacheKey` = the photo's `version`, over the
  initials. While it loads, and if it fails, the initials show. The whole avatar is one semantics node
  labelled with the person's name; the image is excluded. A refreshed payload brings a new signed address
  for the same version, so nothing is downloaded again (tested).
- Parsing is forgiving: a block missing `url` or `version`, or empty, is no photo and costs no card.
- The deal screen names nobody (the server's Deal payload has no person), so it shows no photo.

## Decisions taken here

- **Section placement: after verification.** Above it, the section pushed "Verify email" out of the first
  screen of Profile.
- **The own photo is not in the launch snapshot** (`Account.toSnapshotJson`): a signed address would be
  stale on disk. Profile shows the photo as soon as `/api/me` answers.
- **`Journey.traveler_photo` is ignored by the app.** Journey detail is opened only by its owner and does
  not name the traveler, so nothing would display it. The server field stays.
- **The request preview sheet keeps text only** ("From <name>" as its subtitle); the request card has the
  avatar.
- **The upload code lives in `auth_repository.dart`**, beside the rest of `/api/me`.
- **A 401 on upload.** The client's refresh-and-replay reuses the same multipart body, which Dio refuses to
  send twice, so the member sees "try again" and nothing reaches the server twice. This is how every
  upload already behaved.
- **Reason text in Arabic.** The staff reason is the staff's own words in any language, so it is wrapped in
  Unicode isolates to keep a right-to-left sentence in order around it.
- **iOS Arabic permission text.** It writes the brand as "وصلة" and predates this package; it was kept and
  only gained the profile photo.

## Tests

New files, in `mobile/test/`:

- `p3b_profile_photo_test.dart` (37): every state above; one PUT with the declared type; 413 with and
  without a JSON body; the local size and type refusals; a refused camera; no automatic retry after five
  minutes; one PUT per press; removal asks first and Cancel leaves the photo; the Wassla notice with and
  without a reason, dismissal, and a new photo replacing it; Arabic; every state at 360 px, 320 px,
  landscape and 1.6x text in English, French and Arabic without overflow.
- `p3b_avatar_test.dart` (11): initials only, cache key = version, a refreshed address asks the network for
  nothing, loading and error fall back to initials, semantics, person row order in LTR and RTL, the top
  bar slot.
- `p3b_photos_everywhere_test.dart` (14): trip, request, Find Travelers and profile cards, a signed-out
  guest's Browse trips and requests, the person page (also Arabic at 360 px), alerts, the negotiation
  header, the passport and photo section.
- `p3b_chat_list_photo_test.dart` (6): a photo row and an initials row, a deleted counterparty, a closed
  thread, a photo that cannot load, a malformed block, Arabic at 360 px.
- `test/support/photo_cache.dart`: a stand-in image cache (a test runner has no application directory),
  which also records the cache key of each image.

Extended: `contract_test.dart` (group "profile photos": every new field present and null, the own photo's
states, the snapshot holding none, `avatar_url` ignored, `counterparty_photo`, the stable error codes, any
413 is too large, which refusals offer a retry); `store_report_block_delete_test.dart` (the header photo:
photo, no photo, deleted, blocked, unknown row, semantics, Arabic at 320 px); `phase8ff4_chat_test.dart`
(`counterparty_photo` in the thread fixture); `support/fake_api.dart` (fixtures take a `photo`).

**Tests rewritten, and why.** `phase_j4_test.dart` and `phase_j5_find_travelers_test.dart` sent
`avatar_url` and asserted `avatarUrl`; P3A removed that key, so they now send and assert `photo`. No test
was skipped, deleted or weakened.

Two dev dependencies, both already resolved through `cached_network_image`: `flutter_cache_manager` and
`file`, so a test can implement the image cache.

## Checks

`dart format --set-exit-if-changed lib test`: nothing to change. `flutter analyze --fatal-infos`: no
issues. `flutter test`: 1738 passed. `tools/check_ios_config.py`: passes. CI on the pull request: all ten
jobs green. `l10n_untranslated.json` stays empty.

## Gate screenshots

`docs/screenshots/p3b/`, English (`en-`) and Arabic (`ar-`) at 360 px, rendered from the real widgets with
a throwaway golden rig (not committed) and a drawn portrait:

- `profile-photo-1-empty`, `-2-uploading`, `-3-active`, `-4-removed-by-wassla`, `-5-too-large`,
  `-6-offline`, `-7-remove-confirm`: the Profile photo section in each main state;
- `trip-card` (one with a photo, one with initials), `find-travelers-card` (the same), `person-page`,
  `proposal` (the negotiation header), `chat-list` (a photo row and an initials row), `chat-header`.

## Handoff

- **Nothing to deploy for the server.** P3A and P3C carry the contract. A phone needs a new build to see
  any of this; one release build can carry P4 and P3B together.
- **Not tested on a device.** The rig and the widget tests stand in for the camera and the network; the
  first real check is the next phone build: take a photo, choose one, remove it, and see a second member's
  photo on a card and in chat.
- **Ismail's own step** (from the fix plan): update the Google Play "Data safety" form, because photos are
  now collected (optional, for app functionality). The App Store privacy answers already list photos.
- **Left out on purpose:** a crop tool (the server crops the centred square and the screen previews it),
  a push when staff remove a photo (Profile shows the state), a "report this photo" button (owner), and
  any switch (P3A has none).
