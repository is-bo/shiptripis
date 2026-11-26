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
| The picked file is gone | "We couldn't read that photo. Choose it again." The selection is cleared, the buttons are usable |
| Recovered after the phone closed the app | the photo, "Your phone closed Wassla while you were choosing a photo. Use the photo you picked?", "Use this photo" and "Discard this photo". Never uploaded unasked |
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
    scale to 1024 never enlarges); the orientation and the scale are one matrix; transparency is flattened
    onto white; an out-of-memory decode is retried at a larger sample. HEIF that `BitmapFactory` cannot read
    goes through `ImageDecoder` (API 28 and up), which applies the orientation itself.
  - **iOS** (`AppDelegate.swift`): ImageIO builds a thumbnail from the file URL with the transform applied
    and `kCGImageSourceThumbnailMaxPixelSize` 1024 (never above the picture's own size), which decodes at the
    reduced size and reads HEIC like any other format; the JPEG is written without properties, so it carries
    no metadata.
  - The earlier pipeline (a Dart header probe through `ImageDescriptor`, then `flutter_image_compress`) is
    gone, and so is the dependency: the probe itself fully decoded a HEIC on Android, a panorama sampled by
    1, and the compressor rotated but never reflected.
  - **Known limit on iOS.** `image_picker_ios` 0.8.13+7, asked for a gallery photo with no resize options,
    loads the file's data, makes a `UIImage` and re-encodes it (`UIImageJPEGRepresentation`), which decodes
    the picture at full size before this code sees it. A custom picker would avoid that; it is not built.
- **The type is read from the bytes.** The upload is declared by the first bytes of the prepared file
  (JPEG, PNG or WebP), never by its name, and named `photo.<ext>` to match. The native resizer is told to
  write JPEG, so in practice the content type is always `image/jpeg`; a `.webp` name on JPEG bytes is sent
  as a JPEG (tested). Bytes that are none of the three are "unsupported" on the phone.
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
  a photo write finished (counted at each write's start and end) keeps the session's newer photo and
  applies the rest.
- After an upload or a removal, the retained reads that hold the member's own photo are invalidated: the
  own public profile (Home's opt-in card and the Public profile preview) and every person page.
- A failed replacement can be discarded; "Remove photo" for the server's photo stays available beside it;
  a removal clears the obsolete error and the pending pick.
- **If the phone ends the app while the picker is open.** The picker keeps **one** lost result for every
  kind of pick, so every pick in the app (the profile photo, the identity check, ticket proofs, item photos,
  the payout cheque, dispute evidence) goes through `PickGuard` (`core/media/pick_guard.dart`): before a
  picker opens, any earlier lost result is consumed and thrown away and a marker (`purpose:account:nonce`) is
  written to secure storage; the pick that wrote the marker clears it, and nobody else does. At the next
  launch the profile section accepts a lost result only if the marker names the profile photo and the same
  signed-in account; a result whose marker names anything else is consumed and discarded. It is offered for
  confirmation, once, and never uploaded unasked.
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
- `AppAvatar` draws the photo with `CachedNetworkImage`, `cacheKey` = the photo's `version`, over the
  initials. While it loads, and if it fails, the initials show. The whole avatar is one semantics node
  labelled with the person's name; the image is excluded. A refreshed payload brings a new signed address
  for the same version, so nothing is downloaded again (tested). The image is keyed by its address too, so
  an avatar that failed on an expired address loads again as soon as a fresh one arrives for the same
  version (tested on the same mounted avatar).
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
- **Secure storage gains one key**, the pending pick (purpose, account id and a nonce). The test that pins
  the keys the store may write (`handover_isolation_test.dart`) lists it now, with the reason: it names no
  code, token or person.
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
  the recovered photo (offered, confirmed, discarded, another account's, no marker, nothing lost, the
  marker written and cleared, a refused picker).
- `p3b_photo_layout_test.dart` (22): 17 states (empty, active, active without an address, removed with and
  without a reason, uploading, too large, unsupported, inactive, storage, offline, general, 401, file gone,
  picker refused, recovered, failed replacement) on 360 px, 320 px, landscape and 1.6x text in English,
  French and Arabic: the message is on screen, every action is reachable (inside the screen and not
  covered) and nothing overflows; then 5 of them inside the real app (`ShipTripApp` on its real router, Profile tab, real
  tab shell with its Arabic labels) under the bottom navigation on Android, Android with the gesture bar,
  iPhone, 320 px and landscape, in English and Arabic:
  the end of the list is above the bar and every action of the section is reachable and above it.
- `p3b_photo_prepare_test.dart` (13): the Dart side of the platform method with a fake channel: one `prepare`
  call with the path, the answer used, `not_found` as a file error, every other code, a missing method, a
  null or empty answer as an unsupported photo; the signature check for JPEG, PNG and WebP.
- `p3b_photo_round2_test.dart` (25), round two (below): an upload never going out under another account
  (a sign-in while the file is read, while the photo is prepared, and while the request is in flight); a
  public-profile write begun before a removal; the launch confirmation against a photo changed meanwhile; a
  file that vanishes during a failed upload; Profile, restart, KYC, restart; a double tap; and the life of
  each prepared file.
- `p3b_avatar_test.dart` (16): initials only, cache key = version, a refreshed address asks the network for
  nothing, loading and error fall back to initials, an expired address replaced by a fresh one on the same
  mounted avatar, a fresh address that joined a load in flight and is tried when that load fails, one retry
  and then initials, semantics, person row order in LTR and RTL, the top bar slot.
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
`FakeTokenStore` holds the pending pick).

**Tests rewritten, and why.** `phase_j4_test.dart` and `phase_j5_find_travelers_test.dart` sent
`avatar_url` and asserted `avatarUrl`; P3A removed that key, so they now send and assert `photo`.
`handover_isolation_test.dart` pinned the keys secure storage may hold at seven; the pending photo pick
makes eight, and the test says why. The device-shape loop that used to sit in `p3b_profile_photo_test.dart`
(three states) is replaced by `p3b_photo_layout_test.dart` (seventeen states, and the real Profile screen).
No test was skipped, deleted or weakened.

No new runtime dependency (the `flutter_image_compress` of the first second-pass is removed again). Android
names `androidx.exifinterface:exifinterface` for its own code. Two dev dependencies, both already resolved
through `cached_network_image`: `flutter_cache_manager` and `file`, so a test can implement the image cache.

## Checks

`dart format --set-exit-if-changed lib test`: nothing to change. `flutter analyze --fatal-infos`: no
issues. `flutter test`: 1828 passed. `tools/check_ios_config.py`: passes. CI on the pull request: all ten
jobs green. `l10n_untranslated.json` stays empty.

## Gate screenshots

`docs/screenshots/p3b/`, English (`en-`) and Arabic (`ar-`) at 360 px, rendered from the real widgets with
a throwaway golden rig (not committed) and a drawn portrait:

- `profile-photo-1-empty`, `-2-uploading`, `-3-active`, `-4-removed-by-wassla`, `-5-too-large`,
  `-6-offline`, `-7-remove-confirm`, `-8-recovered`, `-9-failed-replacement`: the Profile photo section in
  each main state;
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
  6. Android with "Don't keep activities": close the app while the camera is open, reopen Profile, and the
     photo is offered for confirmation; then Profile, restart, identity check (selfie), restart, Profile: the
     selfie is **not** offered.
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
