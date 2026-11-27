# Brief P3B-B: the photo slot rule, one operation at a time, one owner

**Builder:** Claude Opus, high effort.
**Branch:** `claude/p3b-profile-photos-app`, pull request #66. You start from P3B-A's pushed,
green head. Pull first. You are the last brief on the branch, so you also finish the pull
request.
**Read first:** `CLAUDE.md`, the mobile rules included; `docs/handoff/builders/README.md`; the
plan sections 3, 4 (rule R9), 5.5 and 10 (AR-8) and the P3B r8 rows of Appendix A;
`docs/handoff/status/P3B.md` as P3B-A left it; `backend/monolith/apps/accounts/photos.py` from
top to bottom.

## 1. Your job

Close the three rules that are left: P-E, P-F and P-G. Each closes one round-8 finding with the
smallest change. Do not rebuild the photo controller.

## 2. What the code does today (checked at `7727b19`)

- The photo is one row per member. `remove_own_photo(user, *, version=None)` deletes the row.
  The DELETE carries `?version=`. `own_view` returns state, url, version, `removed_at` and the
  reason.
- A staff removal keeps `version`. So a Remove dialog that the member opened before the staff
  removal still matches, and deletes the removal notice the member never read.
- The phone's controller is `ProfilePhotoController` in `lib/app/profile_photo_state.dart`.

## 3. What you build

**P-E. A write names the state it saw.**

- Server (`backend/monolith/apps/accounts/photos.py`, `remove_by_staff`): a staff removal gives
  the row a new `version`.
- Server (`MePhotoView`, `replace_photo`, `remove_own_photo`): when a photo row exists, every
  member write (a replacement, a removal, the dismissal of a notice) must carry the `version` it
  saw, in the way the DELETE already does. A missing or different `version` is the existing 409
  `profile_photo_changed`, checked under the member lock (`_hold_member`) before a new object is
  published, and the object uploaded for that request is released. When no row exists, an upload
  needs no `version`.
- Phone: every such write sends the `version` the screen was drawn from. A 409 carries no new
  state; the phone reads again (P-G).
- No new column, and the member's removal still deletes the row. `version` never appears in a
  payload where it is not today.

**P-F. One photo operation at a time** (`lib/app/profile_photo_state.dart`,
`lib/features/profile/profile_photo_section.dart`).

- A command (pick, retry, discard, remove, dismiss) is accepted or refused before the first
  await, and marks the controller busy in the same call. Two taps in one frame can never both be
  accepted.
- The photo controls are keyed by the `version` they show (and by "no photo"), so a rebuild for
  another state replaces the control and ends a held gesture.

**P-G. One owner for the member's own photo** (plan rule R9). The member's own photo is part of
the account snapshot that S1 gave one owner. A stored upload, a removal and a 409 all make that
owner read again. No photo code sets the snapshot from another call's answer. Every surface that
shows the member's own photo, kept previews included, reads from that owner.

## 4. What you remove

Any code that applies an upload's or a removal's answer to the shown photo by itself. Any second
copy of "which photo is current".

## 5. What is not yours

The session core and the boundary (S1). The closed families P-A, P-B and P-C. The staff console's
photo page beyond the one line in `remove_by_staff`.

## 6. Tests

Red first: the three round-8 should-fix findings of plan Appendix A (the old Remove dialog after
a staff removal; Retry and Discard in one frame; an older `/api/me` after a 409).

- **P-E:** a removal, a dismissal and a replacement, each carrying the `version` from before a
  staff removal: 409, the notice is still there, the uploaded object is released. A write with
  no `version` on an existing row: 409. A first upload with no row: accepted. A replacement
  against a replacement from a second device: the second gets 409.
- **P-F:** both orders of every pair of commands in one frame; pointer down on Dismiss, the
  `version` changes, pointer up: nothing runs.
- **P-G:** a 409 followed by an older `/api/me`; an upload answer followed by an older read; a
  kept preview after a 409 shows the new state.
- **Device check (P-B):** write the steps to prepare the same input twice on an Android phone
  and on an iPhone. The result is recorded in the phase document at the phone test.

## 7. Done when

1. The three findings are tests, red before and green after, and every case of section 6 passes.
2. Screenshots in English and Arabic at 360 px for each photo state that changed.
3. The pull request description lists, per rule P-A to P-G: the rule, where its one mechanism
   lives and its tests.
4. The phase document and the status entry are written.
5. Every CI check is green, "Schema drift" included.
