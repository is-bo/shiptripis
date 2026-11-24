# P3A: profile photos, server side (2026-11-24)

Ismail's phone test of 2026-11-24: "Is there no option for profile pictures? Add it." Fix plan of
2026-11-24, package P3A, built to the owner's answers of the same day (fix plan section 7), which
override the plan's section 4 defaults. Server only: the app screens are package P3B. Additive
migrations `accounts/0007`, `admin_panel/0010` and `finance/0035` (a job kind, no schema change).
Nothing is deployed by this change. The second-pass review's outcomes are at the end.

## The owner's rules, as built

| Rule (Ismail, 2026-11-24) | Where |
| --- | --- |
| Everyone sees a photo, guests included, wherever the person appears by first name | `apps/accounts/photos.py` `public_photo`, called by every person block below |
| No staff pre-check: a valid upload is visible at once | no pending state; `ProfilePhoto.State` is `active` or `removed` |
| Staff remove a photo with a required reason, audited, behind a new permission | `apps/admin_panel/console_photos.py`, `photos.remove_by_staff`, `moderate_profile_photos` |
| The member sees "removed by Wassla" with the reason; nobody else sees the photo | `photos.own_photo` in `GET /api/me`; `public_photo` returns null |
| Optional; add, replace, remove; stable error codes | `PUT` / `DELETE /api/me/photo` (`apps/accounts/views.py` `MePhotoView`) |
| Re-encoded on the server, helper beside `image_bytes_match_extension` | `apps/core/storage.py` `square_jpeg_without_metadata` |
| Old objects deleted durably; races decided by `version` | `photos.release_object`, `delete_if_unreferenced`, the `profile_photo_object_delete` job |
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
  screen reads its counterparty from the proposal, so no Deal field was added;
- `GET /api/journeys/<id>`, the caller's `GET /api/journeys` and every journey answer of the trips
  views: `traveler_photo` beside `traveler_name` (named like the proposal's, since a bare `photo` on a
  journey would read as the trip's own picture). `traveler_name` itself is unchanged.

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
| `DELETE /api/me/photo` (also dismisses a removal notice), no throttle at all | 204, also when there was nothing |

The PUT body is read by `photos.PhotoUploadHandler` only: in memory, never a temporary file, refused
with `profile_photo_too_large` as soon as the declared body passes 10 MiB plus 64 KiB of multipart
framing or the file bytes pass 10 MiB, before reading on.

Refusal codes (`{"code", "detail"}`): `profile_photo_missing` (400), `profile_photo_too_large` (413,
with `max_bytes`), `profile_photo_media_type_unsupported` (415: not JPEG, PNG or WebP by declaration and
by bytes, undecodable, or more than 40 million pixels), `profile_photo_storage_unavailable` (503, the
provider's message only in the log), `account_inactive` (403: the account is deactivated or banned;
removing a photo is never refused for the account's state).

**What is stored.** Never the upload. `square_jpeg_without_metadata(body, size=512)` decodes it with
the existing pixel ceiling (now the named constant `MAX_IMAGE_PIXELS`; a WebP is measured from its
RIFF header before Pillow opens it), applies `exif_transpose`, flattens transparency (an alpha channel
or a PNG `tRNS` colour key) onto white, takes the centred square with `ImageOps.fit`, resizes to 512
px, and
writes a JPEG from a fresh image built from the pixels only. The output carries only the JFIF header: no
EXIF, XMP, ICC profile or comment. Any decoder failure is `ImageRejected`.

**Model.** `accounts.ProfilePhoto` (`accounts_profile_photo`), one-to-one with the user: `state`,
`bucket`, `object_key`, `bytes`, `version`, `uploaded_at`, `removed_at`, `removed_by`,
`removed_reason`. A check constraint holds the two shapes: active has a key and no removal; removed has
no key, a time and a reason.

## The race rule

Every photo write takes the member's row lock (`photos._hold_member`, the same lock account deletion
holds) by primary key, whatever the account's state, so the member's uploads and removals, a staff
removal and account deletion run one after the other. Whether the member may upload (active and not
banned) is decided after the lock is held. Each upload gets a new random `version`. **A staff removal names the version the operator was
shown (a hidden field of the console form) and applies only while that version is still the active
photo.**

- Replacement first, then the removal: the removal finds another version and refuses with
  `profile_photo_changed`; the console says the member changed their photo and shows the new one.
  A fresh photo is never marked removed.
- Removal first, then a replacement: the removed photo's object is deleted after commit, so nothing
  of it stays visible; the upload is a new photo with a new version, visible at once. The member may
  upload after a removal (nothing in the specification says otherwise).
`ConcurrentRemovalTests` proves the first case with two real transactions on PostgreSQL, and
`LockedWhateverTheStateTests` proves that two removals of a deactivated or banned member's photo queue.

## Stored objects: one cleanup rule

**"Delete object K once no `ProfilePhoto` row names it"**, run by a durable `ScheduledJob` of kind
`profile_photo_object_delete` (`finance/0035`, handler `photos.handle_object_delete_job`), the
repository's one scheduler for delayed work (CLAUDE.md: critical delayed jobs survive Redis and
process restarts). Keys are random and never reused, so a key no row names now is never named again.

- **Upload.** Before the object is written, its job is recorded for one hour later
  (`profile_photo_object:upload:<key>`). That covers a failed or lost write, a lost commit
  acknowledgement and a crash: by then the upload has committed (the row names the key, so the job
  keeps it) or it has not (the job deletes it). The only immediate delete on failure is for a known
  refusal before commit (`PhotoRefused`, such as a banned account); every other failure is left to the
  job, so an image a committed row names is never deleted.
- **Release.** Replacement and staff removal record `profile_photo_object:release:<old key>` in the
  same transaction as the decision; a deleted row records it from `post_delete` (the member's removal,
  account deletion, a cascade from the user in the Django admin, a bulk delete). After commit, one
  immediate attempt is the fast path.
- **The job** checks that no row names the key, then deletes it. Storage refusing is a retryable error,
  retried with the job loop's backoff (capped at six hours) for 48 attempts, about ten days; after that
  it is a failed job on System > Background jobs, where staff can retry it, and the monitor's
  `financial_job_backlog` alarm fires. An object already gone (S3 answers a delete of a missing key with
  success; a `NoSuchKey` answer is treated the same) counts as deleted. A payload that is not a
  `profile-photos/` key fails permanently without touching storage.

**How the jobs run on the VPS.** No new process or timer. The `app` container's launcher
(`infra/vps/launcher.py`) spawns `manage.py run_finance_worker --interval 30` (`finance-jobs`), the
single loop that claims every due `ScheduledJob` with `SKIP LOCKED` and returns stuck ones to the
queue; if it exits, the launcher stops the container and Compose restarts it. The host monitor
(`wacla-monitor.timer`, every minute) alarms on jobs overdue by more than ten minutes, unresolved failed
jobs, and a missing worker snapshot.

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

- **Banned accounts cannot upload** (they could before the second pass), answered with the existing
  `account_inactive` code rather than a new one: the app shows the same message for both states.
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

New (53, all passing locally on PostgreSQL):

- `apps/core/tests/test_p3a_image_reencode.py` (9): GPS, camera, date and comment gone, only the JFIF
  marker left, 512 by 512; upright from the orientation tag; the centred square; transparency on
  white; a PNG colour key (RGB and grayscale) becomes white; a decompression bomb refused before it is
  expanded; a WebP declaring a huge canvas (VP8X, VP8L, VP8) refused without `Image.open` being
  called; real WebP files measured from their header; anything else refused.
- `apps/accounts/tests/test_p3a_profile_photos.py` (29): upload stored re-encoded with a random key
  and shown at once; PNG and WebP; every refusal code with nothing stored; storage failure; the
  `media_upload` throttle; DELETE never throttled, even over the member's quota; an upload near the
  limit never reaches a temporary file, and over the limit is refused while reading and by length; a
  banned member cannot upload but can remove; guests refused; replace and remove delete the old object
  after commit; a refused row write deletes its own object and keeps its job; the race rule in both
  orders and with two real concurrent transactions; two removals of a deactivated or banned member
  queue on the lock; the cleanup job (recorded before the write, a failed write left to the job, a
  failed delete retried until it succeeds, already gone counts as deleted, a named key never deleted,
  a non-photo key refused, cascade and bulk deletes record it, staff removal records it); a lost commit
  acknowledgement keeps the new object; account deletion; banned and deactivated accounts.
- `apps/discovery/tests/test_p3a_photo_privacy.py` (4): every surface, as a guest and as a member,
  carries the active photo with a URL that names nobody (journey detail and list included); the L2A
  forbidden keys and private strings stay absent with photos present; a removed photo is gone
  everywhere (no version, no reason) except the owner's `GET /api/me`; no photo is null everywhere.
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
(`select_related("<person>__profile_photo")`, the journey queryset included), so no surface gained a
query.

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

## Second-pass review (2026-11-24)

Reviewed at `0d7de17`, findings checked by the lead.

**Fixed.**

1. **Lock any account (blocker).** `_hold_member` filtered `is_active=True`, so a deactivated account
   got no lock. It now locks by primary key whatever the state; upload eligibility (active and not
   banned) is checked after the lock is held. Test: `LockedWhateverTheStateTests`.
2. **One durable cleanup mechanism (blockers 2 and 3, lost PUT responses, admin cascades).** The
   after-commit delete that could be lost and the `except BaseException` delete that could remove a
   committed photo's object are gone. One rule, "delete K if no row names it", runs as the
   `profile_photo_object_delete` job: recorded before every write, in the same transaction as every
   release, and from `post_delete`. See "Stored objects: one cleanup rule". Tests: `CleanupJobTests`,
   `LostCommitAcknowledgementTests`.
3. **No temp file for uploads.** `PhotoUploadHandler`, for this route only, keeps the body in memory and
   refuses past the limit while reading. Test: `test_an_upload_never_touches_the_disk`.
4. **WebP size before decoding.** `_declared_canvas_allowed` reads the canvas from the first 30 bytes
   (VP8X, VP8L, VP8) before `Image.open`, in both shared helpers, so parcel uploads are covered too;
   the check after opening stays. Test: `test_a_webp_declaring_a_huge_canvas_is_refused_before_pillow_opens_it`.
5. **PNG transparency.** A `tRNS` colour key is honoured (`has_transparency_data`), composited onto
   white before resizing. Test: `test_a_png_colour_key_is_transparent_and_becomes_white`.
6. **Journey detail.** `traveler_photo` on the journey detail, the caller's list and every journey
   answer, joined in `_journey_queryset`, so no query is added. `traveler_name` is unchanged (the full
   name question is the owner's). Test: the privacy walk.
7. **Never throttle DELETE.** `DELETE /api/me/photo` has no throttle at all. Test:
   `test_removing_is_never_throttled_even_over_the_member_quota`.

**Accepted limits (not fixed).**

- **Signed storage URLs, not an opaque image proxy.** The key is random and the bucket private. A URL
  issued before a ban or a removal keeps working for at most 30 minutes, the same model as parcel media.
- **No idempotency key on PUT.** The app (P3B) never retries a photo upload by itself, so every retry is
  a deliberate new upload by the member; the rule goes into P3B.
- **Caddy's 12 MB edge limit answers a non-JSON 413.** The app resizes to 1024 px before uploading, and
  P3B treats any HTTP 413 as "too large".
- **An upload's own job runs an hour after the upload starts.** A request that took longer than that
  between writing the object and committing its row could lose the image to the job. Between the two
  there is only one row lock and one insert or update, so nothing in the request comes near an hour.
