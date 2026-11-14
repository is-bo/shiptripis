# L13B: Reviews, mobile

Package L13B of `docs/WASSLA_DISCOVERY_PRO_PLAN.md`, on the contract of
`docs/PHASE_L13A_REVIEWS.md`. Mobile only; no backend change.

## What the app does

- **Reviews screen** (`features/reviews/reviews_screen.dart`), routes `/reviews/person/:id` and
  `/reviews/trip/:id[?request=<id>]`. The summary is the server's `rating` (the number the card
  showed; never averaged on the client), the list pages lazily on the server's `next_offset`
  (`reviewsFeedProvider`, a `FeedController`), a row already held is dropped. A hidden comment shows
  "Comment removed by Wassla". Nothing names an author, a deal or a tracking number.
- **Ways in:** the rating on the Person page, on the Trip preview, and on the Find Travelers trip
  sheet (which passes the sender's request as `request`). A card shows the average only, never review
  text. An unrated person ("New") has no link.
- **Report** (`report_review_sheet.dart`): five reasons plus an optional note, `POST
  /api/ratings/<id>/reports`. The Find Travelers context (`journey` + `request`) is sent only when the
  screen was opened with a request. `own_review`, `review_removed` and `review_not_found` have their
  own sentences; the last two re-read the list. A reported review says "received" or "reviewed"
  (`my_report`) and offers no menu.
- **My ratings:** `moderation` and `my_report` are read. A removed rating says "Removed by Wassla, not
  counted", is left out of the average and offers no report; a hidden comment is marked and still
  counts. Report works here too.
- States: skeleton, empty, switched off (`state: disabled`), gone (`trip_not_found` /
  `profile_not_found`), error with retry, stale note, RTL, 320 px and 1.6x text.

## Contract fix found on the way

`PublicPerson.rating` was parsed as a bare number while the server (L2A) sends `{state, average,
count}`, so every card read "New". It is now a `TravelerRating`, and the test fixture matches the
server. `_PagedList` moved to `PagedFeedList` (shared, with a scrolling header).

## Screenshots

`/mnt/project-files/l-series-screens/L13B/` (EN and AR): reviews, menu, report sheet, empty, person
link, My ratings.

## Tests

`mobile/test/l13b_reviews_test.dart` (27) and one Find Travelers test in
`phase_j5_find_travelers_test.dart`. Flutter 1,521 passing after.
