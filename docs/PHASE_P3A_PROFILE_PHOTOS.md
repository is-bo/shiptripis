# P3A: profile photos, server side (2026-11-24)

Ismail's phone test of 2026-11-24: "Is there no option for profile pictures? Add it." Fix plan of
2026-11-24, package P3A, built to the owner's answers of the same day (fix plan section 7), which
override the plan's section 4 defaults. Server only: the app screens are package P3B. One additive
migration per app (`accounts/0007`, `admin_panel/0010`). Nothing is deployed by this change.

## The owner's rules, as built

| Rule (Ismail, 2026-11-24) | Where |
| --- | --- |
| Everyone sees a photo, guests included, wherever the person appears by first name | `apps/accounts/photos.py` `public_photo`, called by every person block below |
| No staff pre-check: a valid upload is visible at once | no pending state; `ProfilePhoto.State` is `active` or `removed` |
| Staff remove a photo with a required reason, audited, behind a new permission | `apps/admin_panel/console_photos.py`, `photos.remove_by_staff`, `moderate_profile_photos` |
| The member sees "removed by Wassla" with the reason; nobody else sees the photo | `photos.own_photo` in `GET /api/me`; `public_photo` returns null |
| Optional; add, replace, remove; stable error codes | `PUT` / `DELETE /api/me/photo` (`apps/accounts/views.py` `MePhotoView`) |
| Re-encoded on the server, helper beside `image_bytes_match_extension` | `apps/core/storage.py` `square_jpeg_without_metadata` |
| Old objects deleted after commit; races decided by `version` | `photos.replace_photo`, `remove_own_photo`, `remove_by_staff`, `erase` |
| Account deletion deletes the row, then the object | `apps/accounts/deletion.py` `_erase` calls `photos.erase` |
| Reversal of plan decision 5.1b recorded, spec section added | plan 5.1b, spec section 21 (and the three card lines of 4.2) |
| New console POST on the helper's "never" list, knowledge updated | `apps/admin_helper/actions.py` `NEVER`, `tasks.py`, two knowledge files, `INSTRUCTIONS.txt` |
| Route display (P2) not regressed | no change to `card_place`, `city_name` or any stop projection |

## Contract

**Public person block.** `photo`: `{"url": "<signed URL>", "version": "<random>"}` or `null`. It is on:

- `GET /api/discovery/trips` and the person page's trips: `traveler.photo`;
- `GET /api/discovery/requests` and the person page's requests: `sender.photo`;
- `GET /api/discovery/people`, `GET /api/discovery/people/<id>` (`profile.photo`) and the own preview
  (`GET /api/discovery/profile/me`, `card.photo`): the profile card's `photo`;
- `GET /api/discovery/alerts`: `subject.photo`;
- `GET /api/matches/find-travelers` and the sender's "Matches for you": `traveler.photo`. The
  placeholder `avatar_url` (always null) is removed;
- `GET /api/matches`, `GET /api/matches/<id>` and the cancel answer: `sender_photo` and
  `traveler_photo` beside `sender_name` and `traveler_name`. The Deal payload names nobody: the delivery
  screen reads its counterparty from the proposal, so no Deal field was added.

Null when there is no photo, when Wassla removed it, and for a banned or deactivated account. The URL
is signed when the payload is built (no discovery payload is cached anywhere, server or proxy), lives
`PROFILE_PHOTO_URL_TTL_SECONDS` (default 1800, 30 minutes), and points at
`profile-photos/<22 random characters>.jpg` in the private media bucket (`storage_for("media")`, G4).
The key never contains the user id. `version` is random and changes with every upload; the app caches
the image by it.

**The member's own view.** `GET /api/me` gains `photo`: null, or always the same five keys:

```json
{"state": "active",  "url": "<signed>", "version": "...", "removed_at": null, "reason": null}
{"state": "removed", "url": null,       "version": "...", "removed_at": "<iso>", "reason": "<staff's words>"}
```

**Writes.**

| Call | Answer |
| --- | --- |
| `PUT /api/me/photo`, multipart field `photo`, `media_upload` throttle | 200 with the own block |
| `DELETE /api/me/photo` (also dismisses a removal notice), not throttled | 204, also when there was nothing |

Refusal codes (`{"code", "detail"}`): `profile_photo_missing` (400), `profile_photo_too_large` (413,
with `max_bytes`), `profile_photo_media_type_unsupported` (415: not JPEG, PNG or WebP by declaration and
by bytes, undecodable, or more than 40 million pixels), `profile_photo_storage_unavailable` (503, the
provider's message only in the log), `account_inactive` (403).

**What is stored.** Never the upload. `square_jpeg_without_metadata(body, size=512)` decodes it with
the existing pixel ceiling (now the named constant `MAX_IMAGE_PIXELS`), applies `exif_transpose`,
flattens transparency onto white, takes the centred square with `ImageOps.fit`, resizes to 512 px, and
writes a JPEG from a fresh image built from the pixels only. The output carries only the JFIF header: no
EXIF, XMP, ICC profile or comment. Any decoder failure is `ImageRejected`.

**Model.** `accounts.ProfilePhoto` (`accounts_profile_photo`), one-to-one with the user: `state`,
`bucket`, `object_key`, `bytes`, `version`, `uploaded_at`, `removed_at`, `removed_by`,
`removed_reason`. A check constraint holds the two shapes: active has a key and no removal; removed has
no key, a time and a reason.

## The race rule

Every photo write takes the member's row lock (`photos._hold_member`, the same lock account deletion
holds), so the member's uploads and removals, a staff removal and account deletion run one after the
other. Each upload gets a new random `version`. **A staff removal names the version the operator was
shown (a hidden field of the console form) and applies only while that version is still the active
photo.**

- Replacement first, then the removal: the removal finds another version and refuses with
  `profile_photo_changed`; the console says the member changed their photo and shows the new one.
  A fresh photo is never marked removed.
- Removal first, then a replacement: the removed photo's object is deleted after commit, so nothing
  of it stays visible; the upload is a new photo with a new version, visible at once. The member may
  upload after a removal (nothing in the specification says otherwise).
- An upload writes its object before taking the lock, under its own random key; if the row write then
  fails (for example the account was deleted meanwhile), that object is deleted. Every object a row
  stops naming is deleted after commit.

`ConcurrentRemovalTests` proves the first case with two real transactions on PostgreSQL.

## Staff

- Permission `moderate_profile_photos`, granted where ID review is: Trust / Verification and Super
  Admin (`permissions.py` matrix and the seed in `admin_panel/0010`).
- Console person page: the header shows the photo in place of the initials (any staff who can open the
  page: the photo is public anyway). The Overview's Account card has a "Profile photo" line: Shown to
  everyone, Not shown while the account is restricted, Removed by Wassla (when, by whom, the reason), or
  None. "Remove photo" is a header action for staff with the permission while a photo is active.
- `users/<id>/photo/remove/` (`user-photo-remove`): the photo, a required reason ("The member sees this
  reason on their profile"), and the version. It writes `AdminAuditLog` action
  `profile_photo.removed`, target the person (`accounts.user`), before and after
  `{"state", "version"}`, and the reason, so the entry shows on the person's Audit tab. No new tab, no
  `/api/admin` route.

## Decisions taken here

- **No switch.** The owner did not ask for one and the plan does not require one. Staff can remove any
  photo at once, and a photo is optional. A switch that hid photos would have to be read on every
  payload that names a person (Find Travelers, proposals, alerts, `/api/me`), adding a query to pinned
  query budgets and a fail-closed 503 to reads that a photo should never break; a switch that only
  stopped uploads would read as "off" while photos stayed visible. So there is no "switched off" code,
  and P3B needs no "not available" state for photos.
- **"Report this photo" is left out.** The existing reports carry one chat message
  (`ChatMessageReport`) or one review (`RatingReport`), each with its own model, member endpoint, staff
  queue and decisions; blocking only exists between the parties of a match, from the chat. Carrying a
  photo report would mean a new report model, endpoint and queue: new scope. A member can block a
  counterparty or write to support (`GET /api/support`), and staff remove the photo.
- **Staff removal deletes the image.** Nothing displays a removed photo, the owner included, so keeping
  the object would only keep data. The audit entry and the row (reason, time, actor) are the record.
- **Banned and deactivated accounts publish no photo**, the same as their public profile.
- **Chat is out of scope** (the owner's list does not name it; the fix plan said it can follow later).
- **Deal payload unchanged**: it names nobody. The proposal carries both parties' photos.

## Tests

New (37, all passing locally on PostgreSQL):

- `apps/core/tests/test_p3a_image_reencode.py` (6): GPS, camera, date and comment gone, only the JFIF
  marker left, 512 by 512; upright from the orientation tag; the centred square; transparency on
  white; a decompression bomb refused before it is expanded; anything else refused.
- `apps/accounts/tests/test_p3a_profile_photos.py` (16): upload stored re-encoded with a random key
  and shown at once; PNG and WebP; every refusal code with nothing stored; storage failure; the
  `media_upload` throttle; guests refused; replace and remove delete the old object only after commit;
  a failed row write deletes its own object; the race rule in both orders and with two real concurrent
  transactions; account deletion removes the row, then the object; banned and deactivated accounts.
- `apps/discovery/tests/test_p3a_photo_privacy.py` (4): every surface, as a guest and as a member,
  carries the active photo with a URL that names nobody; the L2A forbidden keys and private strings
  stay absent with photos present; a removed photo is gone everywhere (no version, no reason) except
  the owner's `GET /api/me`; no photo is null everywhere.
- `apps/admin_panel/tests/test_p3a_photo_removal.py` (8): the person page and the form; removal audited
  with actor, target, before, after and reason, visible on the page and the Audit tab; a reason is
  required; a replaced photo is not removed; Ops, Support and Finance get 403 and no button; a member is
  sent to the staff login; the permission is granted exactly where ID review is.
- `apps/admin_helper/tests/test_p3a_photos.py` (3): the route is on the "never" list with a how-to; no
  helper payload (guide, briefing, tasks, search, every queue and record) carries a photo, its URL, key
  or version.

Rewritten (reason: the owner's decision to add photos to every person block):

- `apps/matching/tests/test_phase_j4_find_travelers.py` `test_the_traveler_block_carries_nothing_private`
  asserted the always-null placeholder `avatar_url`; it now asserts `photo`, null when there is none.
- `apps/discovery/tests/test_listings.py` `test_an_open_request_is_listed_with_its_card` and
  `apps/discovery/tests/test_alerts.py` `test_following_a_person_needs_their_visible_profile` pin the
  exact sender and subject blocks; each now includes `"photo": None` (that member has no photo).

Unchanged and green: the pinned query counts (`apps/discovery/tests/test_query_counts.py`, the Find
Travelers and person-page budgets). List surfaces join the photo onto the person row they already load
(`select_related("<person>__profile_photo")`), so no surface gained a query.

## Screenshots

`docs/screenshots/p3a/`, from the real console on a local preview (photo storage on local disk):

- `console-person-photo-active-en.png`: the person page with the photo and "Remove photo";
- `console-remove-photo-form-en.png`: the removal form with the photo and the reason;
- `console-person-photo-removed-en.png`: after removal, initials and "Removed by Wassla" with the reason;
- `console-person-audit-removed-en.png`: the audit entry on the person's Audit tab.

The console is English only, so there are no Arabic captures. No new user-facing server copy was added
(API refusals are codes the app words), so `django.po` is unchanged.

## Handoff to P3B

- Read `photo` from the person blocks above and `GET /api/me` `photo`; cache by `version`.
- Remove the app's `avatarUrl` parse (`lib/domain/find_travelers.dart`): the server no longer sends it.
- States to design: empty, uploading, active, removed by Wassla with the reason (dismissed with
  `DELETE`), too large (413), unsupported type (415), storage unavailable (503), offline, error with
  retry. No "waiting for review" and no "not available" state exist.
- Upload: multipart `photo` to `PUT /api/me/photo`. The server crops the centred square itself.
- Ismail's step after P3B: the Google Play "Data safety" form (photos collected, optional, app
  functionality).
