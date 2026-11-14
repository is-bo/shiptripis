# L13A: Reviews, reports and moderation, backend (contract)

Package L13A of `docs/WASSLA_DISCOVERY_PRO_PLAN.md` (section 4), built against
`docs/WASSLA_DISCOVERY_PRO_SPEC.md` section 18. Backend and console. L13B builds the app on this
contract.

**One rule for what counts.** Every public average, count and list of ratings is computed over
`apps.ratings.public.countable` and nothing else: revealed under the blind rule (the window frozen on
the row has passed, or both sides rated: the same predicate as `services.is_revealed`, in SQL) and
not removed by staff. `trust_signals` (every trip, profile and Find Travelers card, and the ranking
that reads it), the two reviews lists, the console person page and the admin user API all use it. A
rating whose comment staff hid still counts.

The `Rating` row is never edited. A decision is a `RatingModeration` row beside it; lifting deletes
that row; the history of decisions is the audit log.

## 1. Schema (`apps.ratings`, migration `ratings/0002`)

| Model | Fields | Rules |
| --- | --- | --- |
| `RatingReport` (`ratings_report`) | `rating`, `reporter`, `reason` (`offensive`, `personal_information`, `unrelated`, `untrue`, `other`), `note` (500), `status` (`open`, `dismissed`, `actioned`), `decided_by`, `decided_at`, `decision_reason` (500, staff-internal), `created_at` | unique on `rating` + `reporter` (`ratings_report_once`); `decided_at` set exactly when the report is closed (`ratings_report_decided_when_closed`) |
| `RatingModeration` (`ratings_moderation`) | `rating` (one to one), `state` (`comment_hidden`, `removed`), `decided_by`, `decided_at`, `reason` (500, staff-internal) | at most one per rating |

Capability `moderate_ratings` (migration `admin_panel/0006`, seeded on Trust / Verification and
Super Admin). Additive only; `backend/contracts/sql/schema.sql` re-exported (additions only).

## 2. Public reviews

### `GET /api/discovery/people/<public id>/reviews?limit=&offset=`

The person's whole record, both sides, like the profile card. `limit` 1 to 50 (default 20),
`offset` up to 1,000.

- Profiles switch off: `200 {"state": "disabled", "results": [], "next_offset": null, "rating": null}`.
- Profile not visible (turned off, hidden by staff, member banned): `404 profile_not_found`.

### `GET /api/discovery/trips/<journey id>/reviews?limit=&offset=[&request=<id>]`

The journey owner's ratings **as a traveler** (written by their senders), like the trip card and
Find Travelers. Access, settled by the advisor on 2026-11-14 (`apps.ratings.public.trip_reviews_access`):

1. The owner, and a viewer who shares a match with the owner, always read them.
2. A sender coming from Find Travelers passes `request`, their own open request. The server asks the
   matching engine for its single-pair verdict (`apps.matching.discovery.explain_candidate`, the
   one "I can carry this" uses); a compatible candidate reads the reviews **whatever the listings
   switch says**. Every failure of this path (not the viewer's request, not open, not compatible,
   unknown journey) answers exactly `404 trip_not_found`, so it tells nothing about the pair or the
   journey.
3. Otherwise the public path: listings switch off answers `state: "disabled"` (as above); a journey
   that is listed now passes; anything else is `404 trip_not_found`.

### Payload (both endpoints)

```json
{
  "state": "results" | "empty" | "disabled",
  "rating": {"state": "rated", "average": 4.5, "count": 2} | {"state": "new", "average": null, "count": 0},
  "results": [
    {
      "id": 31,
      "score": 4,
      "tags": ["on_time"],
      "comment": "Careful and on time" | null,
      "comment_removed": false,
      "written_by": "sender" | "traveler",
      "month": "2026-11",
      "my_report": null | "received" | "reviewed"
    }
  ],
  "next_offset": 20 | null
}
```

- `rating` is `trust_signals` itself, so it is the number the card shows.
- Countable ratings only, newest first. A blind rating and a removed rating never appear.
- A hidden comment is `comment: null` with `comment_removed: true`; the app shows "Comment removed by
  Wassla". An empty comment is `null` with `comment_removed: false`.
- `id` is the rating's id, needed to report it. Never the author's name, a member id, the deal or
  its tracking number.

## 3. Reports: `POST /api/ratings/<id>/reports`

Body: `{"reason": "...", "note": "..." (optional, 500), "journey": <id>, "request": <id>}`.
`journey` and `request` come together or not at all (`400`): they are the Find Travelers context of
section 2, rule 2, for reporting a traveler's review while public listings are off.

| Caller | Answer |
| --- | --- |
| Already reported this review | `200` with the first report's state, unchanged |
| The review's author | `409 own_review` |
| The rated person, review revealed | `201`; if staff already removed it, `409 review_removed` |
| Anyone else who can read it (visible profile; for a review written by a sender also a journey listed now, a shared match, or the Find Travelers context) | `201` |
| Anything else, including a blind, removed or unknown review | `404 review_not_found` (one answer, so the route cannot probe ratings) |

Response: `{"rating_id": 31, "state": "received" | "reviewed", "reported_at": "..."}`. A report is
`received` while open and `reviewed` once staff decided; the reporter is never told more. A race
between two taps resolves on the unique constraint.

## 4. My ratings: `GET /api/users/me/ratings`

Each row gains `moderation: null | "comment_hidden" | "removed"` and `my_report: null | "received" |
"reviewed"`. The rated person keeps reading their own rating as written (comment included); a
removed one is shown as "Removed by Wassla, not counted". The admin ratings API
(`/api/admin/ratings`) also carries `moderation`.

## 5. Staff decisions (`apps/ratings/moderation.py`, `decide`)

Each decision needs `moderate_ratings` (checked fresh in the service) and a reason (500), writes one
`AdminAuditLog` row (target `ratings.rating`, reference the tracking number, `before`/`after`
`{"moderation", "open_reports"}`, `metadata.reports_closed` and `reports_closed_as`), and closes
**all** the review's open reports:

| Decision | Audit action | Moderation | Open reports become |
| --- | --- | --- | --- |
| Dismiss | `rating.reports_dismissed` | unchanged | `dismissed` |
| Hide the comment | `rating.comment_hidden` | `comment_hidden` | `actioned` |
| Remove the rating | `rating.removed` | `removed` | `actioned` |
| Lift the decision | `rating.moderation_lifted` | row deleted | `dismissed` |

Staff may move directly between hidden and removed. A decision that changes nothing (dismissing
with no open report, hiding a hidden comment, removing a removed rating, lifting where nothing
stands) is refused `moderation_unchanged`; hiding an empty comment is refused
`rating_has_no_comment`. Decisions on one review are serialised on its `Rating` row, locked
`FOR NO KEY UPDATE` (the module is in the finance lock-order gate). No member is notified.

## 6. Console

- **Reported reviews** (`/admin/trust/reviews/`, `moderate_ratings`, in the Verification section):
  one row per reported review, open reports first (longest waiting at the top), with the score and
  comment, who it is about and who wrote it, the tracking number, the number of reports and their
  reasons, and the state. Filters "Open reports" and "Decided"; search by tracking number,
  participant or comment.
- **Review page** (`/admin/trust/reviews/<rating id>/`): the review as written, the standing
  decision, every report with its reporter and note (staff only), the decisions that apply now,
  each with a required reason, and the audit history.
- **Overview:** "Reported reviews" counts reviews with an open report, linking to the open filter.
- **Person page:** "Rating received" is the countable number and says how many staff removed; the
  ratings list marks hidden and removed ratings and links to the review page for moderators. Holders
  of `moderate_ratings` see the ratings tab.

Screenshots (`/mnt/project-files/l-series-screens/L13A/`, console, EN): `overview-reported-reviews-en.png`,
`reviews-queue-en.png`, `reviews-queue-open-en.png`, `reviews-queue-narrow-en.png`,
`review-open-reports-en.png`, `review-open-reports-narrow-en.png`, `review-reason-missing-en.png`,
`review-removed-en.png`, `person-ratings-en.png`.

## 7. Tests

`apps/ratings/tests/test_l13a_reviews.py`, 49 tests: `countable` and the blind rule; `trust_signals`
before and after a hide, a removal and a lift, with an unchanged query count; payload shape, both
sides, paging, empty and disabled states; trip access by listing, owner, shared match and the Find
Travelers request path, and every failure of that path answering as an unknown journey; privacy walks
of both payloads (L2A's forbidden keys plus deal and member ids, the author's names and email, the
tracking number, blind and removed text); report uniqueness, who may report, received then reviewed;
My ratings marks; every decision and its reversal, refusals, audit rows, the capability matrix;
console queue, review page, overview item and the 403 for other roles; flat, pinned query counts at
1 and 20 reviews (person 7, trip 7, trip from Find Travelers 13, the extra six being the engine's
single-pair verdict).

Django: 2,941 collected before, 2,990 after (+49). The finance lock-order gate lists
`apps/ratings/moderation.py`.
