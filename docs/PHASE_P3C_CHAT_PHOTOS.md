# P3C: chat photos, server side (2026-11-24)

Owner's answer after P3A (2026-11-24): photos should appear in chat, in the conversation list and the
chat header, wherever the other person is named; the 30-minute signed-URL life stays as built. Fix plan
section 8, package P3C (Sonnet, high), built on P3A (`apps/accounts/photos.py`). Server only: the app
screens are P3B. No migration, no Go change, no Dart change. Nothing is deployed by this change.

## Contract

`GET /api/chat/threads` rows (`ChatThreadSerializer`) gain `counterparty_photo`: `{"url", "version"}` or
`null`, which is `public_photo(<the other person>)`. Nobody sees their own photo on their own row: the
counterparty is the traveler for the sender and the sender for the traveler. The chat header reads the
same row, so it needs no other call.

Null when there is no photo, when Wassla removed it, for a banned or deactivated account, and for a
deleted account (the thread is still listed, with `counterparty_deleted` true; account deletion already
deleted the photo row). The URL is signed when the row is built, lives
`PROFILE_PHOTO_URL_TTL_SECONDS` (30 minutes) and names no user id or email.

The row's other keys are unchanged.

## No extra queries

`ChatThreadsView` adds `sender__profile_photo` and `traveler__profile_photo` to its `select_related`, the
P3A pattern (`_photo_of` then reads the loaded row). The inbox costs the same number of queries for one
thread as for five. The K4 performance tests are unedited.

## What does not change

- `ChatMessageSerializer` and the `chat.message.new` publish are untouched, so no signed URL ever enters
  Redis or `PublishedEvent`; message bubbles show no avatar.
- The "Blocked people" list (`GET /api/me/blocks`) gets no photo.

## Recorded decisions

- **A blocked or closed thread still shows the photo**, because it still shows the name. A block removes
  the ability to write, not the person's identity on the row.
- **The "Blocked people" list gets no photo.** The owner asked for the chat list and the chat header only.
- No photo is signed for a thread the viewer cannot open: the row exists only when the thread is listed.

## Docs

- Spec 21.2 lists the chat list and the chat header and no longer says chat is out of scope.
- Helper knowledge `accounts-and-verification.md` (profile photos section) names chat; `INSTRUCTIONS.txt`
  regenerated with `manage.py build_helper_instructions`.
- P3A's own PHASE document keeps its decision "Chat is out of scope" as the record of that day; this
  document replaces it.

## Tests

New, `apps/chat/tests/test_p3c_chat_photos.py` (12):

- both directions: the sender sees the traveler's photo and the traveler the sender's; a person with a
  photo does not see it on their own row;
- allowlist: the row keys are the previous keys plus `counterparty_photo`; the block is exactly
  `{url, version}`; the URL's path ends in the stored key and holds no user id or email;
- null: no photo, removed by staff, banned, deactivated, deleted (thread still listed with
  `counterparty_deleted`);
- a thread blocked from either side still shows the photo to both; the blocked-people list has no photo
  key;
- query count: one thread equals five, five different travelers each with an active photo (checked to
  fail, 6 queries against 2, when the two `select_related` entries are removed);
- publish unchanged: message payloads (sent and listed) and the `chat.message.new` payload keep their
  keys, and the publish keeps its arguments.

## Handoff to P3B

- `ChatThread` parses `counterparty_photo` (`{url, version}` or null) and caches the image by `version`.
- Show the photo on the chat list row and in the chat header; initials when it is null (a deleted
  counterparty included); no avatar on message bubbles; no photo on the blocked-people list.
- P3B touches no `backend/`, spec or helper file: this package owns them.
