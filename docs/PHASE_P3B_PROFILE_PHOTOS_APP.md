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
| Unsupported type | "That file type isn't accepted." Only when a decoder refused the picture. The file is dropped, no retry |
| Account inactive | "Your account can't add a photo right now. Contact support..." (`account_inactive`, also for banned). No retry |
| Storage unavailable | the file stays selected, "Try again" |
| Offline or timeout | the file stays selected, "Try again" |
| General error | the file stays selected, "Try again" |
| Camera or library refused | "We couldn't open your camera or photos. Check that Wassla is allowed to use them..." |
| The picked file is gone | "We couldn't read that photo. Choose it again." The selection is cleared, the buttons are usable |
| The pick could not be given an owner | "We couldn't open your camera or photos safely just now. Try again in a moment." No picker was opened |
| A result not provably this press's | "We couldn't be sure that photo was the one you chose, so it wasn't used. Choose it again." The file is deleted, never shown or sent |
| The platform could not get the photo ready | "We couldn't get that photo ready. Try again, or choose a different photo." (memory, a write, a missing method: not the picture's fault) |
| A failed replacement of an active photo | the error, "Try again", "Change photo", "Remove photo" (the server photo's) and "Discard this photo" |
| Active photo the server could not sign | initials, "Change photo" and "Remove photo": it is still the member's photo |

- **Picking.** `image_picker` returns the **original**, behind `profilePhotoPickerProvider` (the seam a test
  overrides); the iOS camera and library strings name the profile photo in English, French and Arabic. The
  picker's own `maxWidth` resize is not used: on Android it decodes the whole file first (about 183 MiB for
  a 48 MP photo).
- **Preparing is one platform method**, `wassla/photo_prepare` (`prepare(path)` answers the path of a new
  JPEG), written for each platform and called from `core/media/photo_prepare.dart`. The JPEG is upright (all
  eight EXIF orientations, mirrored ones included), at most 1024 px on its long edge, has no metadata, and is
  at a new path in the app's cache.
  - **Android** (`PhotoPrepare.kt`): the bounds are read without decoding; the sample is the smallest power
    of two that keeps the decode within about 6 megapixels, **whatever the picture's shape** (a 48 MP photo
    and a 32000 x 1500 panorama both decode at about 3 MP, and the long edge stays above 1200 px, so the
    scale to 1024 never enlarges); a decode that returns nothing or runs out of memory is retried at a
    larger sample, up to three times, on both decoders; HEIF that `BitmapFactory` cannot read goes through
    `ImageDecoder` (API 28 and up), which applies the orientation itself and is sampled in the same way
    from the picture's own size in `onHeaderDecoded`. **Whatever the decoder produced is only the source:**
    the output is always drawn into a fresh sRGB ARGB_8888 bitmap of a size computed first (upright, longer
    side at most 1024, **neither side below one pixel**, so a 4096 x 1 strip is 1024 x 1), white first so
    transparency becomes white, and that bitmap is what is compressed; no profile, gain map or wide-gamut
    pixels reach the file. The arithmetic is pure Kotlin (`PhotoGeometry`) and is mirrored as an
    executable specification in `p3b_photo_prepare_test.dart`.
  - **iOS** (`AppDelegate.swift`): ImageIO builds a thumbnail from the file URL with the transform applied
    and `kCGImageSourceThumbnailMaxPixelSize` 1024 (never above the picture's own size), which decodes at the
    reduced size and reads HEIC like any other format; the JPEG is written without properties, so it carries
    no metadata. The app now uses the **UIScene lifecycle** (see "Round three, 3").
  - **Leftover files.** Both platforms delete the prepared files of an earlier run (prefix `wassla-photo-`)
    when the engine starts: a new engine owns none, so any that remain belong to a run that ended.
  - The earlier pipeline (a Dart header probe through `ImageDescriptor`, then `flutter_image_compress`) is
    gone, and so is the dependency: the probe itself fully decoded a HEIC on Android, a panorama sampled by
    1, and the compressor rotated but never reflected.
  - **Known limit on iOS.** `image_picker_ios` 0.8.13+7, asked for a gallery photo with no resize options,
    loads the file's data, makes a `UIImage` and re-encodes it (`UIImageJPEGRepresentation`), which decodes
    the picture at full size before this code sees it. A custom picker would avoid that; it is not built.
- **The type is read from the bytes.** The upload is declared by the first bytes of the prepared file
  (JPEG, PNG or WebP), never by its name, and named `photo.<ext>` to match. The native resizer is told to
  write JPEG, so in practice the content type is always `image/jpeg`; a `.webp` name on JPEG bytes is sent
  as a JPEG (tested). Bytes that are none of the three mean the platform did not do its job, so they are a
  failed preparation, not a verdict on the picture.
- **Never retried automatically.** One `PUT /api/me/photo` per press of a button. The app has no retry loop,
  timer or reconnect hook for it, and **the client does not re-send it after a token refresh either**:
  `ApiClient.upload` marks the request `st.no_replay`, so a 401 refreshes the token and the member sees "try
  again"; the next press sends the file with the new token. `ApiClient.upload` gained a `method` argument
  for the `PUT`.
- **Any HTTP 413 is "too large"**, whatever its body, because Caddy answers an oversized body without
  JSON. `ApiClient.upload` reads the body as text and decodes it only after the status is known, so HTML,
  broken JSON or an empty body still reach `ApiException` with their 413 (a 5xx's body is read the same
  way). `ProfilePhotoFailure.of` reads the status first, then the code.
- **State lives in a provider, not the widget** (`app/profile_photo_state.dart`): the Profile list is lazy,
  so scrolling the section away disposes it. The pending file, its outcome and the busy flag are scoped to
  the account (a new account starts from nothing), so scrolling back neither offers a second upload nor
  hides a failure.
- **Removing** asks first (`confirmAction`). Dismissing the Wassla notice does not ask: it is the same
  `DELETE`, which the server answers 204 even when there is nothing.
- The session moves to the photo the server answered, and not before (`SessionController.uploadPhoto` and
  `removePhoto`, with the same stale-session guards as the profile update). A profile read that began before
  a photo write was applied (counted when the server accepted it and the session applied it; a write that failed
  changed nothing and is not counted) keeps the session's newer photo and applies the rest.
- After an upload or a removal, the retained reads that hold the member's own photo are invalidated: the
  own public profile (Home's opt-in card and the Public profile preview) and every person page.
- A failed replacement can be discarded; "Remove photo" for the server's photo stays available beside it;
  a removal clears the obsolete error and the pending pick.
- **If the phone ends the app while the picker is open, nothing is recovered.** The picker keeps **one**
  lost result for every kind of pick, and a copy of the chosen file that finishes late can answer the
  callback of the *next* pick of any kind, so the plugin gives no way to bind a result to the pick that
  asked for it. The decision (round three, 1): **the profile photo never recovers a lost photo** (the
  "use the photo you picked" offer is gone) **and refuses any result it cannot prove came from its own
  launch.** Every pick in the app goes through `PickGuard` (`core/media/pick_guard.dart`): it makes itself
  the pending pick in secure storage (purpose and a nonce, one serialized step in the credentials' own
  queue that answers the marker it replaced) **before** the picker opens, and if storage refuses, or the
  sign-in moved, the picker does not open and the member is told so (`PickBlockedException`); it consumes
  and **deletes** any earlier lost result; and the pick is *tainted* when a lost result was found or the
  marker it replaced was not empty (an earlier pick never ended; a sign-out leaves a bare `signed-out`
  tombstone for the same purpose). A tainted pick, and any pick whose result arrives within 30 seconds of
  such a finding, is refused by the profile photo: the file is deleted, the member is asked to choose
  again. The pick that wrote a marker clears it, and nobody else does.
- **A second tap cannot open the picker twice.** `pick` reserves the operation before its first await
  (`picking`), so the buttons are disabled at once and only the first call writes and clears the marker.
- **No prepared file outlives its pick.** A file is deleted when another pick replaces it, when it is
  discarded, uploaded or removed with the photo, on sign-out or when the account changes (the controller
  listens to the account from the container, because a provider nobody watches pauses its own listeners), and
  when the session ends; a file an upload is still reading is deleted by that upload when it lets go.
## Where a photo is drawn

| Surface | Field |
| --- | --- |
| Person row on cards, trip preview sheet, Find Travelers trip sheet | `PublicPerson.photo` |
| Trip card, profile card (Browse, Home, person page) | the same |
| Request card and request preview sheet | `RequestCard.senderPhoto`, beside "From <name>" |
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
- `AppAvatar` draws the photo with `CachedNetworkImage` over the initials; the bytes are stored on disk by
  the photo's `version` (`core/media/avatar_cache.dart`, round three 7 and 12). While it loads, and if it fails, the initials show. The whole avatar is one semantics node
  labelled with the person's name; the image is excluded. A refreshed payload brings a new signed address
  for the same version, so nothing is downloaded again once the bytes are on disk (tested against a real cache
  manager). A load is named by version **and** address, so an avatar that failed on an expired address
  loads again as soon as a fresh one arrives, and two avatars holding different addresses for one version
  never share a load (tested with the first request held).
- Parsing is forgiving: a block missing `url` or `version`, or empty, is no photo and costs no card.
- The deal screen names nobody (the server's Deal payload has no person), so it shows no photo.

## Decisions taken here

- **Section placement: after verification.** Above it, the section pushed "Verify email" out of the first
  screen of Profile.
- **The own photo is not in the launch snapshot** (`Account.toSnapshotJson`): a signed address would be
  stale on disk. Profile shows the photo as soon as `/api/me` answers.
- **`Journey.traveler_photo` is ignored by the app.** Journey detail is opened only by its owner and does
  not name the traveler, so nothing would display it. The server field stays.
- **The upload code lives in `auth_repository.dart`**, beside the rest of `/api/me`.
- **Reason text in Arabic.** The staff reason is the staff's own words in any language, so it is wrapped in
  Unicode isolates to keep a right-to-left sentence in order around it.
- **iOS Arabic permission text.** Both Arabic prompts write the brand as "Wassla", like `app_ar.arb`.
- **Secure storage gains one key**, the pending pick (the purpose and a nonce, or `signed-out`). The test
  that pins the keys the store may write (`handover_isolation_test.dart`) lists it now, with the reason: it
  names no code, token, account or person.
- **A latent bug found on the way, fixed:** `_PressScale` (every button's press animation) called
  `setState` when a finger that went down on a button and then scrolled the list lifted after the list had
  dropped the button.

## Tests

New files, in `mobile/test/`:

- `p3b_profile_photo_test.dart` (26): every state through the real screen; one PUT with the declared type;
  the type and the name from the bytes (PNG bytes, and a `.webp` name on JPEG bytes); 413 with and without
  a JSON body; a prepared file over 10 MB and a result that is not JPEG, PNG or WebP refused on the phone;
  a refused camera; no automatic retry after five minutes; one PUT per press; removal asks first and Cancel
  leaves the photo; the Wassla notice with and without a reason, dismissal, and a new photo replacing it.
- `p3b_photo_state_test.dart` (34), one group per second-pass finding: an unsigned active photo (initials,
  change, remove) and a PUT answered with no address; a 401 with the real interceptor (the token is
  refreshed, the PUT is sent once, the next press sends it) and a read that meets a 401 still replayed; a
  413 as HTML, broken JSON, an empty body and JSON of another shape, a 502, a 200 that is not JSON; the
  own profile read Home keeps, and Home to Profile to removal to Home with a warm image cache; a late
  `/api/me` read against a PUT and against a DELETE (and one begun after the write, which is believed);
  the upload surviving scrolling away and back, a failure while scrolled away, and a sign-out; a missing
  file before and after a failed upload; two picks of one name drawing their own files; discarding a failed
  replacement, removing around it, a removal that fails; the request preview sheet's avatar for a guest;
  the photo the phone lost (never offered, shown or sent; a restored identity file that answers a new
  profile pick refused and deleted; a lost result found at the start of a pick; the suspicion window and a
  pick believed after it; a pick that cannot be given an owner opening no picker; the marker written and
  cleared; a refused picker).
- `p3b_photo_layout_test.dart` (22): 19 states (empty, active, active without an address, removed with and
  without a reason, uploading, too large, unsupported, inactive, storage, offline, general, 401, file gone,
  picker refused, a pick an earlier pick may have answered, a failed preparation, a pick with no owner,
  failed replacement) on 360 px, 320 px, landscape and 1.6x text in English,
  French and Arabic: the message is on screen, every action is reachable (inside the screen and not
  covered) and nothing overflows; then 5 of them inside the real app (`ShipTripApp` on its real router, Profile tab, real
  tab shell with its Arabic labels) under the bottom navigation on Android, Android with the gesture bar,
  iPhone, 320 px and landscape, in English and Arabic:
  the end of the list is above the bar and every action of the section is reachable and above it.
- `p3b_photo_prepare_test.dart` (19): the Dart side of the platform method with a fake channel: one `prepare`
  call with the path, the answer used, `not_found` as a file error, `unsupported` as the only refusal of the
  picture, every other code, a missing method and a null or empty answer as a failed preparation; the
  signature check for JPEG, PNG and WebP; and the executable specification of the Kotlin arithmetic
  (samples, retries, the eight orientations, a 4096 x 1 strip, no side below one pixel).
- `p3b_photo_round2_test.dart` (25), round two (below): an upload never going out under another account
  (a sign-in while the file is read, while the photo is prepared, and while the request is in flight); a
  public-profile write begun before a removal; the launch confirmation against a photo changed meanwhile; a
  file that vanishes during a failed upload; Profile, restart, KYC, restart; a double tap; and the life of
  each prepared file.
- `p3b_avatar_test.dart` (17): initials only, load key = version and address, loading and error fall back to
  initials, an expired address replaced by a fresh one on the same mounted avatar, a fresh address never
  joined to the load of an expired one, two avatars with different addresses for one version loading
  separately with the first request held, one retry and then initials, semantics, person row order in LTR
  and RTL, the top bar slot.
- `p3b_avatar_cache_test.dart` (10): the disk cache run for real (real manager, real folder, fake network):
  the record on disk holds the version and no address (with the rewrite switched off, the record
  holds the address), a version on disk answers any address without the network, one address is one request, a fresh
  address is not joined to an expired one in flight, two answers leave one picture.
- `p3b_photo_round4_test.dart` (15), round three (below): the marker queue (exchange, conditional release,
  a stale sign-in, the sign-out tombstone, a sign-out queued behind a marker write, storage that refuses),
  a sign-in that lands while the picker is open or the photo is prepared, a file check overtaken by a
  sign-in, the launch confirmation after a failed write, and the two different failure messages.
- `p3b_photos_everywhere_test.dart` (14): trip, request, Find Travelers and profile cards, a signed-out
  guest's Browse trips and requests, the person page (also Arabic at 360 px), alerts, the negotiation
  header, the passport and photo section.
- `p3b_chat_list_photo_test.dart` (6): a photo row and an initials row, a deleted counterparty, a closed
  thread, a photo that cannot load, a malformed block, Arabic at 360 px.
- `test/support/photo_cache.dart` (a stand-in image cache, which also records the cache key of each image
  and builds PNGs by hand) and `test/support/photo_rig.dart` (the section over a fake server with a fake
  picker, resizer and lost-picker store).

Extended: `contract_test.dart` (group "profile photos": every new field present and null, the own photo's
states including an active one with no address, the snapshot holding none, `avatar_url` ignored,
`counterparty_photo`, the stable error codes, any 413 is too large, which refusals offer a retry);
`store_report_block_delete_test.dart` (the header photo: photo, no photo, deleted, blocked, unknown row,
semantics, Arabic at 320 px); `phase8ff4_chat_test.dart` (`counterparty_photo` in the thread fixture);
`support/fake_api.dart` (fixtures take a `photo`; `FakeResponse.raw` sends a body exactly as written; the
adapter now reads a request body to its end, as a real one does, so a file it came from is closed;
`FakeTokenStore` holds the pending pick and can refuse to write it; `photo_rig.dart` takes a clock for the
suspicion window).

**Tests rewritten, and why.** `phase_j4_test.dart` and `phase_j5_find_travelers_test.dart` sent
`avatar_url` and asserted `avatarUrl`; P3A removed that key, so they now send and assert `photo`.
`handover_isolation_test.dart` pinned the keys secure storage may hold at seven; the pending photo pick
makes eight, and the test says why. The device-shape loop that used to sit in `p3b_profile_photo_test.dart`
(three states) is replaced by `p3b_photo_layout_test.dart` (nineteen states, and the real Profile screen).
In round three, `p3b_profile_photo_test.dart` "a result that is not JPEG, PNG or WebP is refused" now expects
"We couldn't get that photo ready" and not "That file type isn't accepted": the rule changed (bytes the
platform method wrote that are not an image are a failed preparation, and only a decoder's refusal is an
unsupported photo, finding 11); the avatar tests that expected a refreshed address to ask the network for
nothing, and a fresh address to join a load in flight, now state the new rule (a load is named by version and
address; the disk cache answers by version). The recovery tests were rewritten to the rule that nothing is
recovered (finding 1). No test was skipped, deleted or weakened.

No new package (the `flutter_image_compress` of the first second-pass is removed again). Android names
`androidx.exifinterface:exifinterface` for its own code. `flutter_cache_manager`, already resolved through
`cached_network_image`, moved from dev to regular dependencies in round three because the avatar disk cache
is built on it; `file` stays a dev dependency for the tests.

## Checks

`dart format --set-exit-if-changed lib test`: nothing to change. `flutter analyze --fatal-infos`: no
issues. `flutter test`: 1860 passed. `tools/check_ios_config.py`: passes. CI on the pull request: all jobs
green. `l10n_untranslated.json` stays empty.

## Gate screenshots

`docs/screenshots/p3b/`, English (`en-`) and Arabic (`ar-`) at 360 px, rendered from the real widgets with
a throwaway golden rig (not committed) and a drawn portrait:

- `profile-photo-1-empty`, `-2-uploading`, `-3-active`, `-4-removed-by-wassla`, `-5-too-large`,
  `-6-offline`, `-7-remove-confirm`, `-9-failed-replacement` (`-8-recovered` was removed in round three
  with the screen it showed): the Profile photo section in each main state;
- `request-preview-sheet`: the sender's avatar beside "From <name>";
- `trip-card` (one with a photo, one with initials), `find-travelers-card` (the same), `person-page`,
  `proposal` (the negotiation header), `chat-list` (a photo row and an initials row), `chat-header`.

## Handoff

- **Nothing to deploy for the server.** P3A and P3C carry the contract. A phone needs a new build to see
  any of this; one release build can carry P4 and P3B together.
- **Device checks still owed.** The native preparation (Kotlin and Swift) has never been compiled or run: the
  workstation has no Android or iOS toolchain, the repository has no native test setup, and the pull-request
  checks build neither app, so the first compile is the next Android release build and the next iOS build.
  On a phone, with that build:
  1. a large JPEG (48 MP, or the largest the phone has) from the gallery, and a photo taken with the camera:
     no out-of-memory, and the preview and the uploaded photo are upright;
  2. a large HEIC (an iPhone photo, or an Android 10+ gallery HEIC) on both platforms;
  3. a panorama (very wide, such as 12000 x 1500 or wider) on both platforms;
  4. all eight EXIF orientations, with an asymmetric picture (a letter or a face on one side), the four
     mirrored ones (2, 4, 5, 7) included: the uploaded photo reads the right way round, not mirrored;
  5. a PNG with transparency: the background is white, not black;
  6. Android with "Don't keep activities": close the app while the camera is open, reopen Profile: nothing is
     offered; take a photo within 30 seconds and it is refused with "We couldn't be sure ..."; take one
     later and it goes up. Then Profile, restart, identity check (selfie), restart, Profile: the selfie never
     appears in the profile slot;
  7. a 4096 x 1 PNG and a 1 x 4096 PNG: a 1024 x 1 and a 1 x 1024 JPEG, no crash;
  8. an Ultra HDR JPEG and a wide-gamut (Display P3) photo on Android 14: the uploaded photo is plain sRGB;
  9. a very large HEIC on Android 9 to 12 (the `ImageDecoder` path), and a decode that fails for memory on a
     low-RAM phone: it retries larger and still produces a photo;
  10. iOS 26 and the next iOS: the app launches (scene manifest and `FlutterSceneDelegate`), plugins work
      (sign-in, push, picker), and the photo channel answers (a photo prepares);
  11. leftover files: pick a photo, kill the app before uploading, relaunch: no `wassla-photo-*.jpg` remains
      in the cache (Android) or temporary (iOS) folder;
  12. the avatar disk cache on a phone: after a photo has loaded, the cache database
      (`wassla_profile_photos`) holds the version in its `url` column and no signed address.
- **Not tested on a device.** The rig and the widget tests stand in for the camera and the network; the
  first real check is the next phone build: take a photo, choose one, remove it, and see a second member's
  photo on a card and in chat.
- **Ismail's own step** (from the fix plan): update the Google Play "Data safety" form, because photos are
  now collected (optional, for app functionality). The App Store privacy answers already list photos.
- **Left out on purpose:** a crop tool (the server crops the centred square and the screen previews it),
  a push when staff remove a photo (Profile shows the state), a "report this photo" button (owner), and
  any switch (P3A has none).

## Second-pass review

Astra 6.2 rejected the first version (head `dac68e8`). The lead verified the findings against the code and
the pinned plugin source; every one was accepted and is fixed on the same branch.

| # | Finding | Outcome |
| --- | --- | --- |
| 1 | **Blocker.** image_picker_android 0.8.13+21 computes `inSampleSize` from a fresh `BitmapFactory.Options`, so the 1024 px resize decodes the full original (about 183 MiB for 48 MP) | Fixed in the first pass and replaced in round two (A). The picker returns the original. `photo_prepare.dart` reads the size from the header and `flutter_image_compress` is given the `inSampleSize` (pinned `flutter_image_compress_common` 1.1.1 passes it to `BitmapFactory.decodeFile`), writing a JPEG of about 1024 px. Tested: the arithmetic, the header read of a large generated PNG, the argument the compressor receives, the fallback. **Device check still owed** (see Handoff) |
| 2 | The multipart type came from the path; the resizer can keep a `.webp` name on JPEG bytes | Fixed. The type and the filename come from the prepared file's signature. Output is always JPEG, so `image/jpeg` is what goes. Tested with a `.webp` name on JPEG bytes and PNG bytes |
| 3 | An active photo with `url: null` dropped the whole own-photo block | Fixed. `OwnPhoto` keeps state and version; initials, "Change photo" and "Remove photo" stay. A PUT answered with no address is a success. The public `PersonPhoto` with no address is still "no image". Tested |
| 4 | A 401 on the PUT was replayed after the refresh | Fixed. `ApiClient.upload` marks the request non-replayable: the token is refreshed, the file is not re-sent, the member sees "try again". Tested with the real interceptor (one refresh, one PUT, the next press sends) and a read still replays |
| 5 | A 413 was read after JSON decoding; the fake `jsonEncode`d the HTML | Fixed. The upload body is read as text and decoded after the status is known, for 4xx and 5xx. `FakeResponse.raw` sends bodies as written. Tested at the adapter boundary: HTML, broken JSON, empty, another JSON shape, a 502, a 200 that is not JSON |
| 6 | Own previews stayed stale after a PUT or DELETE | Fixed. After either, `ownProfileProvider` and `personProvider` are invalidated. Tested at provider level and Home to Profile to removal to Home with a warm image cache |
| 7 | A late `/api/me` read overwrote a newer photo | Fixed. The session counts photo writes at start and end; a read (or a profile update) that began under another count keeps the session's photo and applies the rest. Tested against a PUT and a DELETE, plus the rest-still-applies and after-the-write cases |
| 8 | Upload state lived in the lazy list's child | Fixed. It lives in `profilePhotoProvider`, scoped to the account. Tested: scrolling away and back, a failure while away, a sign-out |
| 9 | A `FileSystemException` from the length check or `MultipartFile.fromFile` was not caught | Fixed. Both paths clear the selection, leave the buttons usable and say "Choose it again". Tested before preparing and when "Try again" finds the file gone |
| 10 | An avatar that failed on an expired URL did not reload for a fresh one with the same version | Fixed. The image is also keyed by its address; the bytes stay cached by version. Tested on the same mounted avatar, and that a loaded photo is not fetched again |
| 11 | Two picks could share `scaled_<basename>` and show the old preview | Fixed. Every prepared file has its own path; the preview is keyed by it. Tested at the unit level and through the screen |
| 12 | No way to discard a failed replacement; the error outlived a removal | Fixed. "Discard this photo"; "Remove photo" stays; a removal clears the error and the pick. Tested, including a removal that fails |
| 13 | The request preview sheet dropped the sender's avatar | Fixed. The sheet shows it beside "From <name>". Tested for a guest; screenshot added |
| 14 | Process death while the picker is open | Fixed. A marker (account id) is written before the picker opens; at the next launch the same account is offered the photo for confirmation, once. Never uploaded silently. Tested (offered, confirmed, discarded, another account, no marker, nothing lost). The picker's own leftover is read only for the right account |
| 15 | The layout matrix covered three states and no real shell | Fixed. `p3b_photo_layout_test.dart`: 17 states by 4 phone shapes by 3 languages, and 5 states in the real Profile screen under the bottom navigation on 5 phone shapes in 2 languages, asserting the message, the reachable actions and no overflow |
| 16 | iOS Arabic prompts wrote the brand as "وصلة" | Fixed. Both say "Wassla" |

Items 1, 11 and 14 were reopened by the next review: see round two.

## Round two

Astra 6.2 re-reviewed head `0f50142` and marked 9 findings fixed and 7 partly fixed, with 2 new blockers and
5 should-fixes. All were accepted.

| Finding | Outcome |
| --- | --- |
| **A. Photo preparation** (HEIC probed by a full decode on Android; a 32000 x 1500 panorama sampled by 1, about 183 MiB; mirrored EXIF orientations 2, 4, 5 and 7 lost their reflection; iOS decoded in full; items 1 and 11 partly fixed) | Replaced, not patched. One platform method, `wassla/photo_prepare`, in Kotlin and Swift (above). The decode is bounded by total pixels, all eight orientations are undone with a matrix (Glide's mapping) and ImageIO's transform, the output is a new JPEG at a new path. `flutter_image_compress` and the Dart header probe are removed. Tested on the Dart side with a fake channel (the call, the answer, every error mapping). **The native code is untested here**: no toolchain, no native test setup; the sample-size arithmetic and the eight orientations are device checks (see Handoff). The iOS picker's own full-size re-encode is recorded as a known limit |
| **B. Blocker: account switch mid-upload** (the credential generation was captured after `MultipartFile.fromFile`) | Fixed. `AuthRepository.uploadPhoto` captures the identity before any asynchronous work and `ApiClient.upload(expectedIdentity:)` refuses to send if it changed. The controller also asks the session, at every await, whether the account is still the one the step began for. Tested: a sign-in while the file is read, while the photo is prepared (zero PUTs, no leaked file), and while the request is in flight (B keeps its own photo and state) |
| **C6.** A public-profile write begun earlier could install the old photo | Fixed. `OwnProfileController` compares the session's photo-write count before and after its write and reads again if it moved. Tested against a held write and a removal |
| **C7.** The launch `_confirm` assigned `/api/me` directly | Fixed. It takes the same newest-photo guard (and applies the rest of the answer). Tested with a held launch response |
| **C9.** A cache file vanishing between Dio's length read and its stream open gave a retry that could not work | Fixed. After a retryable failure the controller checks the file still exists; if not it clears the pick and asks to pick again. Tested |
| **C10.** A fresh URL arriving while the old request was pending joined it, and when it failed the avatar stayed on initials | Fixed. A failed load is tried once more on a load of its own (the failed entry is evicted first) with the address held now; then initials. Tested with a held old load that then fails |
| **C14 and the KYC mix-up.** One Android lost-result cache serves every picker | Fixed. Every pick of every purpose (profile photo, identity check, ticket proofs, item photos, payout cheque, dispute evidence) goes through `PickGuard`: the previous lost result is consumed first, a `purpose:account:nonce` marker is written, only the writer clears it, and the profile photo accepts only its own purpose and account. Tested: Profile, restart, KYC, restart does not offer the ID photo; Profile, restart, Profile does; a marker is only cleared by its own pick |
| **C15.** The shell tests used a test-only `_Shell` | Fixed. They run inside the real `ShipTripApp` on its real router, Profile tab, real tab shell and its Arabic labels, on five phone shapes |
| **D. Double tap on pick** | Fixed. `picking` is reserved before the first await, so the buttons are disabled at once and a second call opens nothing and clears nothing. Tested at the controller and in the screen |
| **D. Leftover prepared JPEGs** | Fixed. Deleted when replaced, discarded, uploaded or removed with the photo, on sign-out and on account change, and at the end of the session; a file an upload is reading is deleted by that upload when it lets go. Tested for each case, including sign-out mid-upload |

Two things found while testing, fixed: the first test double for the image cache and the in-app controller
both assumed a provider nobody watches rebuilds or listens when its account changes (it does neither until it
is read), so the controller now listens from the container and checks the account itself; and the fake
server's request streams are now read to the end, as a real adapter does.

Screenshots: no screen changed in round two (the only visible change is that the buttons are disabled while
the camera or library is open), so none were regenerated.

**Could not do here.** Compile or run the Kotlin or the Swift, or build an Android or iOS binary; run a native
test (there is no native test setup in the repository, and none is added unrun). The device checks above are
the owner's or the next build's.

## Round three

Astra 6.2 rejected head `d8c3607` with 4 blockers and 9 should-fixes. All were accepted and fixed on the same
branch (rebased on `main` at `eb1665d`, a docs-only move).

| Finding | Fix | Test |
| --- | --- | --- |
| **1. Blocker: a late Android picker result crossing purposes** (a restored copy of an identity file could answer a new profile pick) | **Decision: the profile photo no longer recovers a lost photo at all, and refuses any result it cannot prove came from its own launch.** Reason: `image_picker_android` keeps one lost result for every picker and lets a copy worker that outlived its app complete the plugin's *current* callback; nothing in the plugin binds a result to the pick that asked, so no marker can prove a recovered file is the profile photo's. `recoverLostPick`, `confirmRecovered`, the "Use this photo" notice and their strings are gone. A pick is tainted when a lost result is found at its start or the marker it replaced was not empty, and a result that arrives tainted, or within 30 seconds of such a finding, is deleted and refused with "We couldn't be sure that photo was the one you chose" | `p3b_photo_state_test.dart` group 14 (a restored identity file answering a new profile pick is refused and deleted and never shown or sent; a lost result found at the start taints the pick; the window, then a pick is believed; nothing is offered at launch), `p3b_photo_round2_test.dart` C14 (Profile, restart, KYC, restart, Profile: the ID file never reaches the profile slot) |
| **2. Blocker: marker durability and ordering** (a failed write was swallowed; begin, cleanup and sign-out were separate steps) | `TokenStore.exchangePendingPick` (write the marker and answer the one it replaced, in the credentials' own queue, refusing if the sign-in moved) and `releasePendingPick` (conditional). A marker that cannot be written, or whose sign-in moved, throws `PickBlockedException` **before any picker opens**; every picker call site (profile photo, identity check, ticket proof, item photo, payout cheque, dispute evidence) tells the member in a translated message (EN, FR, MSA). Sign-out, in the same queue, leaves a bare `signed-out` tombstone instead of the marker so the next pick still hears of it | `p3b_photo_round4_test.dart` group 2 (exchange and conditional release, a stale sign-in writes nothing, the tombstone, a sign-out queued behind a held marker write lands after it, storage that refuses opens no picker and reads no lost result, counted by a fake picker), group 14 "a pick that could not be given an owner opens no picker", layout scenario "the pick could not be given an owner" |
| **3. Blocker: iOS launch with the UIScene lifecycle** | Migrated exactly as Flutter's own template and migration do (pinned Flutter 3.47.1, `ios.tmpl/Runner/AppDelegate.swift` and `lib/src/migrations/uiscene_migration.dart`; guide: https://flutter.dev/to/uiscene-migration). `AppDelegate` is `FlutterAppDelegate, FlutterImplicitEngineDelegate`; plugins and the `wassla/photo_prepare` channel are registered in `didInitializeImplicitFlutterEngine` through `engineBridge.pluginRegistry`; `Info.plist` gains `UIApplicationSceneManifest` with `FlutterSceneDelegate` (no extra Swift file, so the Xcode project is unchanged) | `tools/check_ios_config.py` now fails if the manifest, the delegate or either registration is missing (it passes). **Not run on iOS** |
| **4. Blocker: the account-switch window** (B's tokens saved while the account provider still said A) | The credential generation is read at the press (`_Launch`: owner, generation, operation), checked after every wait, and carried to the dispatch: `SessionController.uploadPhoto` and `AuthRepository.uploadPhoto` take it as `expectedIdentity`, and `ApiClient.upload` refuses to send if it moved. A flow that finds itself no longer live deletes its file and starts over, so it is never left busy | `p3b_photo_round4_test.dart` group 4 (the generation moves while the picker is open, with the account still 42: nothing prepared, nothing sent, state reset; while the photo is prepared: the file is deleted; a pick after the credentials settled works), `p3b_photo_round2_test.dart` B |
| **5.** Awaits on the file system were followed by state writes | `_prepare` and `_upload` re-ask `_live` after every file wait (`readHead`, `length`, `exists`, deletes) before setting state, invalidating or returning success | group 5: a failed upload whose `File.exists` is held while a sign-in lands writes no retry notice, deletes the file, sends once (confirmed to fail without the check) |
| **6.** A failed overlapping PUT made the launch confirmation replace the server's photo with null | The session counts photo writes it **applied**, not started or finished; a failed write is not counted | group 6: a failed PUT, then a confirmation carrying photo `v7` keeps `v7`; the same for a removal notice. The earlier "newer photo stays" test still passes |
| **7.** Two avatars with different signed addresses for one version shared a load | A load is named by version and address (`avatarCacheKey`); the disk cache loads once per address and stores by version, and drops a response whose version arrived first | `p3b_avatar_test.dart` (two mounted avatars, first request held; a fresh address not joined to an expired one), `p3b_avatar_cache_test.dart` (the real manager) |
| **8.** Bounded decode for a large HEIF; larger-sample retries for null or out-of-memory | `ImageDecoder` samples from `onHeaderDecoded` and both decoders retry at a larger sample up to three times (`PhotoGeometry.nextSample`) | the arithmetic as an executable specification; **device check** |
| **9.** The decoder's bitmap could carry a profile, wide gamut or a gain map | Always drawn into a fresh sRGB ARGB_8888 bitmap, with an sRGB target colour space asked of both decoders (API-guarded); that bitmap is compressed | **device check** (Ultra HDR, Display P3) |
| **10.** A 4096 x 1 PNG gave a zero short side | `PhotoGeometry.outputSize` computes the upright size, clamped to at least one pixel a side, and the picture is drawn into exactly it | specification: 4096 x 1 is 1024 x 1, 1 x 4096 is 1 x 1024, a quarter turn included; no side below 1 or above 1024 over a grid of sizes |
| **11.** Every platform error was "unsupported" | `unsupported` is the only refusal of the picture; anything else (memory, a write, a missing method, an empty answer, bytes that are not an image) is `PhotoPrepareFailed`, with its own message ("We couldn't get that photo ready ...", EN, FR, MSA) | `p3b_photo_prepare_test.dart` (mapping), group 11 (both messages through the screen), layout scenario |
| **12.** `flutter_cache_manager` wrote the signed address into its on-disk record (spec 21.2) | `AvatarCacheManager` stores the picture under the version and rewrites every record so its address column holds the version; the address lives in memory for the length of a request | `p3b_avatar_cache_test.dart` reads the record that reaches the disk: no signature, no `https://`, `"url":"v1"`; with the rewrite switched off the same test fails and shows the address, so it tests the fix |
| **13.** The preparation tests had lost their executable arithmetic and the "no marker, no offer" check | Both restored. Gradle cannot run a Kotlin unit test here (no JDK 17, no Android SDK), so the arithmetic is mirrored in Dart, named as such in the test file; the no-marker check is now "no marker, no picker" with a counting fake | `p3b_photo_prepare_test.dart` last group; group 14 and `p3b_photo_round4_test.dart` group 2 |
| Also: stale prepared files | Both platforms delete the `wassla-photo-` files of an earlier run when the engine starts (Android on the same single thread as `prepare`, so before any photo of the run; iOS older than the call) | **device check** |

Two things found while testing: a marker is written *before* the lost result is consumed, so a test that
waits for the marker must also wait for the picker to open; and a test double for a held secure-storage write
must hold only the first write, since a sign-out writes the same key.

Screenshots: the "recovered" screen is gone, so `en-` and `ar-profile-photo-8-recovered.png` were deleted.
The three new notices (a refused pick, a failed preparation, a pick with no owner) are the same notice
component as "too large", covered by the layout matrix (three more scenarios on every phone shape and
language); no new screenshot was rendered.

**Could not fully fix, and why.**

- **Finding 1 is a refusal, not a proof.** The plugin cannot bind a result to its pick, so a late copy that
  answers a profile pick with no stale marker, no lost result and no sign-out before it cannot be told from a
  real answer. The window and the taint cover the cases the phone can produce (a pick open when the app was
  ended, a lost result, a sign-out), and recovery is gone, but no code here can close the case entirely; the
  only complete fix is a picker that returns the pick's own identity (a custom picker), which is not built.
- **Findings 8, 9, 10 and 13 (Kotlin) and 3 (Swift)** have never been compiled or run: no JDK 17, Android SDK,
  Xcode or Swift on the workstation, the pull-request checks build neither app, and Gradle cannot run a
  Kotlin test here. The Dart specification proves the arithmetic, not that the Kotlin matches it. The device
  checks 6 to 12 above are what a build must confirm.

## Round five

Astra 6.2 rejected head `c8b4e68`: 8 of the 13 round-3 findings partly fixed, 3 new blockers and 4
should-fixes. All were accepted. The builder's answers, finding by finding (the numbers are Astra's round-4
table; the new findings are named by what they are).

| Finding | Fix | Test |
| --- | --- | --- |
| **New blocker: two KYC taps replaced the first marker** (the second launch was refused as `already_active`, and its cleanup deleted the first pick's only owner) | `PickGuard` is reserved **before its first await**, for every purpose: a second tap, of any screen, finds the guard taken and returns null without touching storage or the picker. A pick's marker is released only by that pick, after its picker has answered | `p3b_photo_round5_test.dart` group 1 (a second identity-check tap while the first awaits storage: one exchange, one picker, the first's marker intact until its picker answers; another purpose does nothing; a failed pick frees the guard) |
| **New blocker: `pickImage` and `pickVideo` returned files from uncertain tickets** (a restored KYC copy answering a parcel photo pick was staged as the item photo) | The ownership check moved **into the guard**: a tainted ticket, or one inside the 30-second window, deletes the file and throws `PickBlockedException(uncertain: true)` before anything is returned, for every caller. The profile photo uses the same wrapper (`PickGuard.run`); `begin`, `end` and `trusts` are no longer public. The five screens show "We couldn't be sure that photo was the one you chose" for it | group 2 (item photo, ticket proof, cheque, identity and a video with a stale marker: no file returned and the file deleted; a lost result taints; a clean pick returns its file), and `phase8fb_request_form_test.dart`: the real form with a stale identity marker stages nothing and uploads nothing |
| **New blocker: a retry during B's sign-in sent A's file with B's bearer** | A prepared photo keeps the **account and credential generation it was prepared under** (`PickedPhoto.owner`, `.identity`). "Try again" is checked against those, never against whoever is signed in by then, and `_upload` checks them before it dispatches. With B's tokens saved and B not yet published, A's retry sends nothing, deletes A's file and starts over | group 4 (the exact interval: tokens moved, account still A; a retry after the credentials were replaced; and the same session may retry as often as it likes) |
| **Should-fix: a late step reset a newer operation** (`_abandon` matched on the account id; a discard reset after the deletion finished) | Every press takes an epoch of its own (`_launch`, `_launchFor`); `_abandon` acts only for the operation that still owns the state. `discard()` detaches the photo synchronously and deletes the file afterwards | group 5 (an older press's preparation finishing while the next press is preparing leaves it alone and it uploads; a discard leaves clean state before the file is gone). Both fail with the old logic |
| **Should-fix: a sign-out during the marker write opened the previous member's picker** | `PickGuard.run` rechecks the credential generation after every storage wait and again on the answer, and the profile flow passes `proceed: () => _live(launch)`, asked last, just before the picker would open. The marker is released on every early exit | group 3 (the guard, the profile flow, and a photo arriving after a sign-out is deleted unseen) |
| **Should-fix: two valid addresses wrote two files for one version** | Requests stay independent; installing is serialized per version, and a response that finds the picture already there is dropped unwritten (`_installOnce`) | `p3b_avatar_cache_test.dart` "installing a version": the first body held open while the second answers in full leaves one file (fails without the change), and a failed first install does not stop the next |
| **Should-fix: the iOS sweep took its cutoff inside the scheduled task** | The cutoff is taken when the engine registers the channel and passed to the sweep (`removeLeftovers(before:)`) | `tools/check_ios_config.py` still passes. **Not run on iOS** |
| **Finding 2: Android `apply()` durability** (`flutter_secure_storage` 9.2.4 writes through `SharedPreferences.Editor.apply()`, which cannot report a failed disk write) | The pending-pick marker moved out of secure storage on Android. `PendingPickStore` (`pending_pick_store.dart`) has two implementations: `CommittedPendingPickStore` calls `wassla/pick_marker` (`PickMarkerStore.kt`), whose every change is `commit()` and whose failure is an error, so no picker opens; every other platform keeps the keychain, whose write is synchronous. Same queue as the credentials. The marker holds a purpose and a nonce, nothing secret. `handover_isolation_test.dart` now pins the marker's key in its own file (the rule it enforces is unchanged: nothing but the listed keys is ever written) | group 6 (exchange, conditional release and the sign-out tombstone through a fake channel; a write the disk refused opens no picker and reads no lost result), plus the existing marker tests, which run on the keychain implementation |
| **Finding 8: retry sequence 4, 4, 4, 8; a large HEIF still reached a full-frame intermediate** | The decode samples are now one list, `PhotoGeometry.sampleLadder(firstSample)`: the header's sample, then twice, four times and eight times it (a header sample of 4 gives 4, 8, 16, 32), used by both decoders. The `ImageDecoder` path reads the picture's size in `onHeaderDecoded` and **refuses a picture over 64 MP before any pixel is decoded** (the code `failed`, so the member hears "We couldn't get that photo ready ... choose a different photo"). 64 MP is my choice and a judgement, not a measurement: a phone's 48 MP photo is within it, and a non-tiled HEIF decodes whole whatever sample is asked for | `PhotoGeometryTest.kt` (the ladder, the limit), run by JUnit. **Device check owed** (a 48 MP HEIC on Android 9 to 12, and one over 64 MP) |
| **Finding 9: an ICC segment in the output** (Skia writes the output colour space's profile, sRGB included) | The encoded JPEG is passed through `JpegMetadata.withoutMetadata`: every APP1 to APP15 segment and comment before the scan is removed, APP0 and everything from the scan on are copied unread; bytes it cannot read are a failed preparation, never uploaded unclean | `JpegMetadataTest.kt` (ICC, EXIF and comments removed; a scan that looks like segments copied unread; a plain JPEG unchanged; non-JPEG and cut-short input refused). **Device check owed**: inspect a device-produced file for `ICC_PROFILE` |
| **Finding 11: every decoder exception was "unsupported"** | The `ImageDecoder` path maps: a file gone is `not_found`, an `IOException` with the file present is `unsupported` (the decoder refused it), anything else is `failed` | read in review; **device check** |
| **Finding 13: the arithmetic tests ran a Dart copy** | The Dart copy is **deleted** (a second implementation of a rule that has a home) and its cases moved into `PhotoGeometryTest.kt`, which runs the real `PhotoGeometry`. `PhotoGeometry` and `JpegMetadata` use no Android type, so `tools/test_android_pure.sh` compiles them with `kotlinc` and runs JUnit with no SDK or Gradle; it is a step of the Flutter job in CI and `testImplementation` was not added to Gradle | 16 Kotlin tests, run locally and by CI |
| **Finding 1** (a live KYC pick without a marker after overlapping launches) | Closed by the first two rows: a second launch can no longer replace or release the first's marker, and no result is returned unproven | as above |
| **Findings 3, 6, 7, 10, 12** | Fixed in round four, unchanged | |
| **Finding 4** (a retry during the switch paired A's file with B's generation) | Closed by the retry binding above | group 4 |
| **Finding 5** (`profile_photo_state.dart:423` reset on `ref.mounted` alone) | Closed by the epoch ownership above | group 5 |

**Tests changed, and why.** `p3b_photo_prepare_test.dart`: the last group (the Dart copy of the Kotlin
arithmetic) is deleted and moved to Kotlin, as above. `p3b_photo_round2_test.dart`: two tests called
`PickGuard.begin` and `end`, which no longer exist; "only the pick that wrote the marker clears it" became "a
second pick while one is open does nothing at all" (the stronger rule the same finding asks for), and "every
purpose is a different marker" runs through `run`. `p3b_photo_round4_test.dart`: the storage-refusal test calls
`run` instead of `begin`. `handover_isolation_test.dart`: the pick marker's key is pinned in
`pending_pick_store.dart`, not `token_store.dart`. No test was skipped or weakened.

**Could not do here.** Compile or run the Android app or the Swift, or run a native decoder: the Kotlin that
runs is the pure part only (`PhotoGeometry`, `JpegMetadata`); `PhotoPrepare.kt`, `PickMarkerStore.kt`,
`MainActivity.kt` and `AppDelegate.swift` have never been compiled. New device checks: with a build, pick a
photo on Android and confirm the marker survives killing the app while the picker is open (the next pick is
refused for 30 seconds), and inspect a prepared JPEG for an ICC segment.

## Round six

Astra 6.2 rejected head `f4394f1` (`docs/handoff/astra/results/p3b-astra-round5-result.md`): 2 new blockers
and 5 should-fixes, plus the round-3 findings 1, 4, 5, 8, 11 and 13 still partly open and round-4 finding 2.
All were accepted. The builder's answers (the new findings are named by what they are).

| Finding | Fix | Test |
| --- | --- | --- |
| **Blocker: a restored KYC copy worker could complete a later Profile gallery pick** (also round-3 finding 1 and round-4 finding 2: the plugin gives a result to whichever pick is waiting, whenever its copy ends, so no Dart-side window can be enough) | The result is bound to its launch **at the source**. `PickGuard.run` announces on `wassla/pick_launch` that its picker is about to open (`opened`, before the picker; a refusal stops the pick and no picker opens) and that it has answered (`closed`, always, in a `finally`). `MainActivity.onActivityResult` hands a result for one of the plugin's request codes to the plugin only while `PickLaunchGate` says a pick **of this process** is open; a result the phone restored after it ended the app arrives with none open and is dropped before the plugin starts copying it, so no worker exists that could answer a later pick. A new engine starts with the gate shut. The guard's own tainted-pick rules stay as a second line. The guard also judges a result **the moment the picker answers**, not after the marker's release has waited (a window that ended during the release no longer makes a late file believable) | `p3b_photo_round6_test.dart` groups 1 and 2: order of the announcements (`opened`, picker, `closed`), a picker that throws, a refused opening (no picker, marker released), a refused closing (pick unaffected), nothing announced when the caller no longer wants the pick or off Android; a window that ends during the release still refuses (fails without the change); the plugin's request codes are parsed from the pinned plugin's Java and compared with the Kotlin gate's set. `PickLaunchGateTest.kt` (6 JUnit tests) runs the gate itself |
| **Blocker: a press during the switch from A to B paired A's id with B's generation** (a sign-in moves the token store's generation when it starts; A stays published until B answers; also round-3 finding 4) | `SessionSignedIn` now stores the credential generation (`identity`) it was published under; the controller's launch reads **account and generation from the published session** and never from the token store, and `_live` requires the session, the launch and the store to agree. A removal is checked the same way as an upload: `AuthRepository.removePhoto` and `ApiClient.deleteVoid` take `expectedIdentity` and send nothing when the credentials changed since the press | group 3: a press (pick and removal) while B's sign-in is held, B's tokens saved and A still published: no picker, no PUT, no DELETE, state clean (fails with the old pairing); the session publishes the generation it was restored or signed in under; B can use the flow once settled; a removal after a sign-out sends nothing |
| **Should-fix: a stale `_upload` deleted a newer operation's retry file** (round-3 finding 5) | `_upload(launch, photo)` takes the exact photo `_prepare` returned (or the retry's) and returns at once when it is no longer the pending photo, so a late continuation can never touch a newer selection | read in review: the window is the `await` that deletes the replaced file, which a test cannot hold without a seam in `deleteQuietly`; the check is `identical(state.picked, photo)` |
| **Should-fix: a refused tombstone commit stopped the expiry** | `TokenStore._clearCredentials` runs the credentials' deletion first and treats a refused `closeBySignOut` as no reason to stop: the marker stays as it was (a purpose and a nonce) and the next pick finds it and is careful; the generation-checked expiry callback then runs | group 4 (a real `TokenStore` whose marker store refuses the tombstone: `clearIfIdentityCurrent` and `clear` both finish and the credentials are gone) |
| **Should-fix: a stalled body held the per-version install queue** | `AvatarCacheManager._fetch` reads each response's body **on its own** (capped at 4 MiB) and only the publication of the bytes (`putFile`) is queued for the version | `p3b_avatar_cache_test.dart`: a first body that never finishes holds up no other address |
| **Should-fix: a body that failed halfway left a partial file** | Because the body is read into memory first, nothing is written until it is complete: a failed body leaves no file and no record | the same file: a body that fails halfway leaves no file at all |
| **Should-fix: JUnit not declared for Gradle** | `testImplementation("junit:junit:4.13.2")` in `android/app/build.gradle.kts`, the version the shell harness runs | CI job "Android — compile and Gradle unit tests" runs `:app:testDebugUnitTest` (passed: 12 + 5 + 6 tests) |
| **Finding 8: the 64 MP limit only existed in the `ImageDecoder` fallback** | `PhotoPrepare` refuses a HEIF, HEIC or AVIF over the limit at the **successful bounds read** (`PhotoGeometry.isFullFrameFormat`, `withinSourceLimit`), before any decoder is asked for pixels; a JPEG or PNG samples as it decodes and is not limited | `PhotoGeometryTest.kt` (`onlyTheFullFrameFormatsAreHeldToTheSourceLimit`) |
| **Finding 11: a file gone after the `isFile` check was `unsupported`** | When `BitmapFactory` answers null, the file is checked again before the picture is called unsupported: gone is `not_found` | read in review; **device check** |
| **Finding 13: no native fixture preparing a photo twice** | Not done: it needs a device or an emulator. The pure Kotlin (`PhotoGeometry`, `JpegMetadata`, `PickLaunchGate`) is run by 23 JUnit tests | **Device check owed** |

**Tests changed, and why.** `p3b_photo_round4_test.dart` "a pick after the credentials settled works as usual"
moved the token store's generation by hand with the same account published. A login now stores its
generation with the account, so a store that moved with no session change is not a login the app can reach; the
test signs in for real (same member) and then picks. `p3b_photo_round4_test.dart` and
`p3b_photo_state_test.dart` pass `expectedIdentity` to `removePhoto` (the signature gained it). No test was
skipped or weakened.

**Compiled in CI since round 6.** The new CI job "Android — compile and Gradle unit tests" runs
`flutter build apk --debug` (a debug APK, never uploaded or released) and `./gradlew :app:testDebugUnitTest`, and
checks that the three photo test classes produced results. It passed, so `MainActivity.kt`, `PhotoPrepare.kt`,
`PickMarkerStore.kt` and `PickLaunchGate.kt` compile and the 23 JUnit tests run under Gradle. The Swift
(`AppDelegate.swift`) has still never been compiled, and no native decoder or device ran anything.

**Device checks owed.** With a build, kill the app while the camera or library is open, come back, and confirm
the restored result is dropped (the log shows no copy) and that a Profile pick afterwards works; pick a 48 MP
HEIC and one over 64 MP.

## Round seven

Astra 6.2 rejected head `ead30e2` (`docs/handoff/astra/results/p3b-astra-round6-result.md`): 3 blockers and 6
should-fixes. Every round before had found one more way for an action of member A to land on member B while
one replaced the other, so this round fixes the cause and not the instance.

**The cause.** An action read "who am I" more than once, from places that move at different moments: the
published account, the token store's generation, and the bearer in secure storage. Each fix closed one
pairing and left the next.

**The design.** `SessionNotifier.beginAction()` captures one immutable `MemberScope` (`member_scope.dart`):
the account, the authentication it was published by (`SessionSignedIn.generation`) and the credentials it was
published under (`SessionSignedIn.identity`). It answers null while nobody is signed in, **and while the
credentials have already moved on from the published account** (a sign-in is replacing it). Every action
(a pick, a removal, a photo write, a profile read, a profile update) takes the scope **once, when the
member first touches the control**, carries it (a prepared photo keeps its own; a dialog keeps the one it was
opened with), and `SessionNotifier.isCurrent(scope)` is the only question asked when it commits. Nothing
re-reads the account or the generation from live state in between. For the two writes that send a bearer
(`PUT` and `DELETE /api/me/photo`) the request also names the account (`ApiClient.upload` and `deleteVoid`
take `expectedAccount`), and the request interceptor refuses to attach a bearer whose `user_id` claim
(`bearer_account.dart`) is a different account: that is what the token store of another window cannot
see.

| Finding | Fix | Test |
| --- | --- | --- |
| **Blocker: a refresh during the A-to-B switch wrote A's snapshot under B's generation** (also `_updateProfile`) | `refreshAccount` and `_updateProfile` begin an action (refused while the credentials have moved on), check `isCurrent` on the answer, and remember the profile under the scope's credentials, never under whatever the store holds now | `p3b_photo_round7_test.dart` group 1: with B's credentials saved and the role-context write held, a refresh makes no request and writes no snapshot, a profile update is not sent, a read begun earlier and answering inside the interval is dropped, and the only snapshot that ends up stored is B's |
| **Blocker: the removal dialog took the identity on confirm** | The screen takes the scope **before** the dialog (and before the camera/library sheet) and passes it through; `remove(scope)` answers `ProfilePhotoRemoval` (`done`, `stale` or `failed(error)`): a removal for a member who is gone sends nothing and the screen says nothing, instead of "Photo removed" | group 2: the real dialog opened over A, B signs in, the dialog is confirmed: no DELETE, no snack (fails if the scope is taken after the dialog); a stale removal is `stale`, not `done` |
| **Blocker: a second Android task has its own token store but the same bearer** | `launchMode="singleTask"` (the template's `singleTop` with an empty task affinity allowed a second instance in another task): one activity, one engine, one generation for the device; and the bearer-account check above, so a write from a window that is out of date is refused instead of sent | group 3: a removal and an upload under a bearer of another account are refused and nothing is sent, the member's own bearer goes through, the claim reader, the manifest pin |
| **Should-fix: the launch gate reset when a second activity started** | `PickLaunchGate` names the activity that opened the pick: another activity's start-up or closing leaves it alone, a result at an activity that opened none is not forwarded, and a pick ends with its destroyed activity | `PickLaunchGateTest.kt` (8 tests, JUnit by Gradle in CI) |
| **Should-fix: the picker opened for a member who left during `opened`** | `PickGuard.run` rechecks the credentials and `proceed` right after the announcement, inside the `try` whose `finally` ends the launch; a handler the Android build lacks (or any refusal) stops the pick | group 5 (sign-out during the announcement, a caller that gave up, no native gate) |
| **Should-fix: a failed overlapping sign-in left A refusing every action** | When a sign-in is refused by the server or the network (the repository now reads the answer **before** it saves anything), the member who was signed in is published again under the generation they hold | group 4 (a wrong password for B, then A picks a photo and it is sent) |
| **Should-fix: an in-flight DELETE across a same-member sign-in kept the controls busy** | The stale branch of `remove` calls the epoch-checked `_abandon`, as the upload path does | group 4 (the controls are usable again, and the result is not "done") |
| **Should-fix: a full disk could leave an untracked avatar file** | `AvatarCacheManager._publish` writes the file under its own name, **awaits** the record write (the stock `putFile` starts it without waiting), and deletes the file if either fails | `p3b_avatar_cache_test.dart`: a record the database refuses removes the file again, and a write the disk refuses leaves no record |
| **Should-fix: the round-6 test pressed before B's answer** | Group 1 holds the role-context write after B's credentials are saved and presses there; the pre-answer case stays as it was | group 1 |
| Round-3 finding 1 (partly): the gate's one Boolean | As the gate row above | |

**Tests changed, and why.** Every photo test that called `ProfilePhotoController.pick(source)`,
`remove()`, `SessionNotifier.uploadPhoto` or `removePhoto` now goes through the new signatures (a scope):
`pickPhoto` and `removeOwnPhoto` in `test/support/photo_rig.dart` make the press the way a screen does, and the
direct session calls take `beginAction()`. Their assertions are unchanged. No test was skipped, deleted or
weakened.

**Known limits.** `bearerAccountId` is read only to refuse; a bearer that is not a readable JWT is not refused
by the app (the server still decides). The second-window case is closed by `singleTask` first and by the
bearer check as a net; neither has run on a device.
