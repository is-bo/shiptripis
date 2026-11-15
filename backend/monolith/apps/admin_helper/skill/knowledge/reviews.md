# Ratings and Reviews

Covers: who can rate whom and when, the blind review window, what profiles and trips show, reporting a review, and how staff moderate reported reviews (console page and helper actions).
Related files: deliveries.md (delivery states, protection window, completion), trips-and-matching.md (Find Travelers, public profiles, listings), problems-and-disputes.md, admin-console.md (roles and permissions, audit log), settings-and-helper.md (settings page, how prepared helper actions are confirmed)

"Rating" and "review" mean the same thing here: a score from 1 to 5 plus optional tags and an optional comment, written about the other person on one delivery.

## Who can rate whom, and how many ratings per delivery?
- Only the two parties of a delivery (a "deal"): the sender rates the traveler, the traveler rates the sender.
- The role, the rater and the person rated are read from the delivery. Nobody can rate on someone else's behalf. A guest who only paid for the order, the parcel's recipient and unrelated users cannot rate (error `not_authorized`, "Only the sender and the traveler of this delivery may rate it.").
- Exactly one rating per side per delivery. Two ratings at most per delivery.
- A rating can never be edited or deleted after it is sent. Staff moderation does not edit it either (see below).
- You cannot rate yourself.
<!-- src: backend/monolith/apps/ratings/models.py, services.py -->

## When can a delivery be rated?
- Only after delivery has been confirmed. The delivery must be in one of these statuses: `delivery_confirmed`, `protection_window`, `completed`, `disputed`, `partially_refunded`. A disputed or partly refunded delivery can still be rated on purpose, so bad deliveries are not left out.
- Not before: any earlier status gives `rating_not_available` "This delivery cannot be rated yet."
- The review window opens when delivery is confirmed and lasts 14 days (1,209,600 seconds). After it closes: `rating_window_closed` "The review window for this delivery has closed." Nobody can add a rating then.
- The window length is a stored business setting (default 14 days in the shipped settings; allowed 1 hour to 365 days). The console Business settings page shows it read-only as "Rating review window" in the "Lifecycle guardrails" table; no console form changes it. Each delivery freezes its own window when delivery is confirmed, and each rating freezes the window end when it is sent. A later settings change does not move deadlines already promised.
- Old deliveries without a stored deadline use their own frozen policy value, default 14 days.
- Sending twice: `rating_already_submitted` "You have already rated this delivery." The app treats this as success and shows "Thanks for the rating".
<!-- src: backend/monolith/apps/ratings/services.py, deals/lifecycle.py, core/migrations/0006_seed_phase4_business_settings.py, core/policy_display.py -->

## What is in a rating? Score, tags, comment limits
- Score: whole number 1 to 5. Anything else gives `rating_score_invalid`.
- Tags (optional): only these eight are accepted: communication, punctual, careful_handling, clear_instructions, friendly, late, poor_communication, damaged. Duplicates are removed. An unknown tag is refused with `rating_tag_invalid` "That rating tag is not offered." The list is a business setting, not fixed in the app; the app takes it from the server.
- Comment (optional): up to 1,000 characters by default (a stored business setting with no console form; the server cuts longer text). Absolute outer limit 4,000.
- The app shows tags with underscores as spaces.
<!-- src: backend/monolith/apps/ratings/services.py, serializers.py, core/migrations/0006_seed_phase4_business_settings.py -->

## What does the rater see in the app?
- On the delivery screen, a "Leave a rating" action appears while the viewer can still rate. Prompt: "Rate the traveler" (sender) or "Rate the sender" (traveler). Home shows "Rate this delivery" as an attention item.
- The rate screen is titled "How did it go?" and says: "Neither of you sees the other's rating until you've both left one, or the window closes."
- After sending: "Rating saved". If the other side has not rated: "Your rating is saved. You'll see theirs once they've rated you too." If the window is closed: "The rating window has closed."
- If the other side already rated, the delivery screen says "Hidden until you both rate".
<!-- src: mobile/lib/features/deals/rate_screen.dart, deal_screen.dart, l10n/app_en.arb -->

## What is the blind window? When does the other person see my rating?
- Ratings are blind. The other party cannot read a rating until either (a) both sides have rated, or (b) the review window of that rating has passed.
- Both-sides case: the moment the second rating is saved, both become visible to each other.
- The rater can always read their own rating. The delivery's rating state only says whether the other side "has submitted", never what they wrote. The delivery timeline event for a rating never carries the score.
- Visibility is computed from this rule, not from a stored flag. A background job (`rating_reveal`) stamps `revealed_at` when the window closes, but a late job cannot keep a rating hidden, and an early job cannot show one early.
- Staff can read all ratings of a delivery.
- Rating states on a delivery: `available` (you can rate), `submitted_waiting` (you rated, yours not yet visible), `revealed` (yours is visible), `expired` (window over, you did not rate), `unavailable` (not ratable yet).
<!-- src: backend/monolith/apps/ratings/services.py, serializers.py -->

## What is "countable"? (the one rule behind every average and count)
A rating is countable when BOTH are true:
1. It is revealed (both sides rated, or its window has passed), and
2. Staff have not removed it.
Every public average, rating count and review list uses only countable ratings. Nothing else is counted anywhere public (cards, Find Travelers, ranking, trip cards, profile, the reviews lists).
- A rating whose comment staff hid is still countable: only the text goes, score and tags still count.
- A rating still inside the blind window (other side not yet rated) is not countable yet.
- Ratings of non-completed outcomes are not filtered by status: a rating on a disputed delivery counts like any other once revealed.
<!-- src: backend/monolith/apps/ratings/public.py -->

## How is the average calculated, and when does a profile show "New"?
- Average = plain mean of the countable scores, rounded to one decimal (for example scores 5, 4, 4 give 4.3). The count is the number of countable ratings.
- With no countable rating the card shows state `new` with no average and count 0. The app shows the word "New" on traveler cards, Find Travelers results and request candidate cards.
- The member's own rating: the server answers `GET /api/users/me/ratings/summary` with `{state, average, count}`, the same numbers as their public profile card (countable ratings, both sides), so a removed rating is left out. Own profile screen: the "Recent rating" fact shows "No ratings yet" instead of "New", else the average with a star. At this commit the screen still averages the received ratings list on the phone (L18B switches it to the server's summary). That list holds only the latest 100 revealed ratings, and this fact does not leave out ratings staff removed (the "Ratings" screen summary does). So for someone with a removed rating, or more than 100 ratings, it can differ from the public card.
- As traveler vs whole person: a trip card, trip reviews and Find Travelers use only ratings written BY SENDERS about the traveler ("as a traveler"). A public profile card uses the whole person: ratings from both sides (as traveler and as sender).
- Example: a person with 3 countable sender ratings 5, 5, 4 shows 4.7 (3 reviews) on a trip card. If their profile also has one traveler-written rating of 2, the profile card shows (5+5+4+2)/4 = 4.0 (4 reviews).
<!-- src: backend/monolith/apps/ratings/public.py (rating_summaries), ratings/views.py (MyRatingSummaryView), matching/find_travelers.py, discovery/profiles.py, mobile/lib/features/profile/profile_screen.dart -->

## What else does a profile or trip card show (other trust signals)?
- Public profile card (spec "4.2"): first name only, `identity_verified` (an approved ID check that has not expired), member since (year-month), rating (average and count, or "New"), `completed_deliveries`, usual routes (cities only).
- Completed deliveries = deliveries with status `completed`. For a trip card it counts only deals the person carried as traveler; for a profile card, deals as traveler plus as sender. Journeys published, offers sent or matches do not count, only completed deals.
- Trip card traveler block: first name, identity verified (always true on a listed trip, because only travelers with a current ID check are listed), rating as traveler, completed deliveries.
- Reviews never show the author's name, any user id, the delivery or its tracking number. Each review shows: score, tags, comment (or "Comment removed by Wassla"), "From a sender" or "From a traveler", the month written (year-month) and whether the viewer reported it.
<!-- src: backend/monolith/apps/discovery/profiles.py, listings.py, ratings/public.py -->

## Who can read a person's public reviews?
Two endpoints, 20 reviews per page by default, at most 50 per page, offset up to 1,000, newest first.
1. Person reviews (profile, both sides): readable only when marketplace "Show public profiles on Home" is on AND the person has a visible profile (chose to be discoverable, not hidden by staff, account active and not banned). Otherwise the app shows "Reviews are not available" ("Reviews are switched off for now. Please check back later.").
2. Trip reviews (sender-written ratings of the trip's traveler). Allowed in this order:
   - the trip's owner, or anyone who shares a match with the owner: always;
   - a sender coming from Find Travelers who names their own OPEN delivery request, when the matching engine finds that trip a compatible candidate: allowed even if the listings switch is off. Any failure of this path answers exactly like an unknown trip (`trip_not_found`, "This trip is not available.") so it reveals nothing;
   - otherwise the public path: only if the listings switch is on and the trip is listed now.
3. If the listings switch is off and no other door applies, trip reviews show "Reviews are not available".
- Gone: "This is not available any more" / "The person or trip is no longer listed, so its reviews cannot be shown."
- No reviews yet: "No reviews yet. A review shows here once a delivery has been rated and the review is open to both sides."
- A member's own received ratings are always readable on Profile, "Ratings". The person reviews list above follows the profiles switch even for the owner.
- The listings switch ("Show trips and parcel requests on Home") and the profiles switch ("Show public profiles on Home") are in Settings, section "Marketplace features". Both default to on. They apply at the moment of each request; they change nothing already written.
- Note: a trip is "listed now" only while it passes listing rules (current ID check, not banned, has a future departure with capacity left, every needed ticket approved, sea legs only if the sea switch is on and crossings active).
<!-- src: backend/monolith/apps/ratings/public.py, discovery/views.py, discovery/listings.py, core/marketplace_policy.py, admin_panel/console_forms.py -->

## Where do users see their own received ratings?
- Profile, "Ratings" (My ratings): every revealed rating the person received, newest first, up to 100. Not-yet-revealed ratings are absent.
- Summary on top: average with count, from the ratings not removed by staff.
- A hidden comment: the rated person still reads their own rating as written, plus a note "Wassla hid the comment from others. The score still counts."
- A removed rating is still listed to them, marked "Removed by Wassla, not counted", and is not in their summary. They cannot report it.
- Empty: "No ratings yet. Ratings appear after a delivery is completed."
- Reporting is offered from the three-dots menu ("Report") on each review that is not removed and not already reported by them.
<!-- src: backend/monolith/apps/ratings/views.py, serializers.py, mobile/lib/features/profile/ratings_screen.dart -->

## Who can report a review, and how?
- Any member who can read the review where the app shows it, or the person it is about.
- Reasons (exactly five): Offensive, Contains personal information, Not about this delivery, Untrue, Other. App wording: "Offensive or abusive", "Shares personal information", "Not about the delivery", "Not true", "Something else". Codes: `offensive`, `personal_information`, `unrelated`, `untrue`, `other`.
- Optional note, up to 500 characters. Staff read it; nobody else does.
- Once per person per review. A second report answers with the first one's state (200), nothing new is stored.
- What the reporter sees: "received" (staff not yet looked), then "reviewed" (staff decided). App text: "You reported this. We have received it." then "You reported this. We have reviewed it." They never learn the outcome.
- The author is never told who reported. Staff see the reporter's name and email.
- Sheet text: "Tell us what is wrong. We will look at it, and the person is not told that you reported it." After sending: "Thanks, we will review it".
- Refusals:
  - own review: `own_review` 409 "You cannot report your own review."
  - review does not exist, is still blind, was removed, or the viewer cannot read it: `review_not_found` 404 "This review is not available." (the same answer for all, so the route cannot be used to probe ratings)
  - the rated person reporting a review staff already removed: `review_removed` 409 "Wassla already removed this review."
  - reason missing or not one of five: 400 "Choose a reason."
  - settings unavailable: `reports_unavailable` 503 "Reporting is unavailable."
- A sender who reached a traveler's review from Find Travelers through their own open request can report it even when public listings are off (the app sends the trip and the request together).
<!-- src: backend/monolith/apps/ratings/views.py, moderation.py, models.py, mobile/lib/features/reviews/report_review_sheet.dart, l10n/app_en.arb -->

## Where do staff handle reported reviews?
- Console page "Reported reviews" (menu group "Verification", URL path trust/reviews/). Needs the permission `moderate_ratings` ("Can moderate ratings"); roles that have it: Trust and Super admin. Both the list and each review page need it; staff without it get no page.
- Work list queue "reviews" (Reported reviews): same permission; due today, urgent after 72 hours of waiting (nothing is blocked while it waits).
- Queue columns: Review (stars, score/5, comment excerpt), About (rated person, rated by the sender or traveler), Tracking number, Reports (count and reasons, most frequent first, like "Untrue x2"), Last report (age), State.
- Order: open reports first, longest waiting at the top, then decided ones. Filters: "Open reports", "Decided". Search: tracking number, participant email, comment text. Empty: "No review is waiting" / "No reported reviews found".
- State cell: "N open reports", "Comment hidden", "Rating removed", or "Reports dismissed".
- Review page (Review, parcel WSL-...): the review as written (score, tags, comment, who wrote it, who it is about, "Visible to members" yes/not yet), the standing decision with who decided, when, and the reason; every report with reporter, reason, note, status and decision; the audit history (only for staff with `view_audit_log`); a link "Open the delivery" (needs `view_deals`). A person's own page also has a "Ratings" tab (needs `view_ratings` or `moderate_ratings`) showing received average, count and how many were removed. `view_ratings` is held by Ops, Support and Super admin.
<!-- src: backend/monolith/apps/admin_panel/console_reviews.py, worklist.py, permissions.py, console_people.py, core/templatetags/shiptrip_admin.py, templates/admin/console/review_detail.html -->

## What decisions can staff make on a review?
Four decisions; each needs a written reason (required, up to 500 characters) that goes in the audit log and stays internal, never shown to members.

| Decision (button) | What happens | Audit action |
|---|---|---|
| Dismiss the reports | Review unchanged. Open reports become `dismissed`. | `rating.reports_dismissed` |
| Hide the comment | Text replaced by "Comment removed by Wassla". Score and tags still count. Open reports become `actioned`. | `rating.comment_hidden` |
| Remove the rating | Leaves every public average, count and list. The rated person still sees it marked "Removed by Wassla, not counted". Open reports become `actioned`. | `rating.removed` |
| Lift the decision | Removes the standing hide or removal; the review is shown and counted as written again. Open reports become `dismissed`. | `rating.moderation_lifted` |

- At most one standing decision per review (hidden comment or removed). Hiding after remove (or the reverse) replaces the earlier decision (it switches state); the audit log keeps the history.
- Every decision closes all of the review's open reports at once, so reporters' "received" becomes "reviewed". A report filed during the decision stays open for the next one.
- The rating row itself is never edited or deleted.
- Refusals (code, wording): `moderation_unchanged` "This review has no open report to dismiss." / "No decision stands on this review." / "The comment is already hidden." / "The rating is already removed."; `rating_has_no_comment` "This review has no comment to hide."; `reason_required` "A reason is required."; `permission_denied` 403 "You cannot moderate reviews."; `rating_not_found` 404 "No such review."
- The review page only offers decisions that make sense now: Dismiss only with open reports; Hide only if there is a comment and it is not already hidden; Remove unless already removed; Lift only when a decision stands.
- Two staff deciding at once queue up; the second reads the first one's result.
- Success messages: "The reports are dismissed. The review is unchanged." / "The comment is hidden. The score still counts." / "The rating is removed from every public average, count and list." / "The decision is lifted. The review is shown as written."
<!-- src: backend/monolith/apps/ratings/moderation.py, admin_panel/console_reviews.py -->

## What do the rater, the rated person and the public see after a decision?
| Situation | Public (cards, lists) | Rated person ("My ratings") | Reporter |
|---|---|---|---|
| Comment hidden | Score and tags shown, comment replaced by "Comment removed by Wassla"; still counted | Reads their own rating as written, plus note "Wassla hid the comment from others. The score still counts." | "reviewed" |
| Rating removed | Gone from the list, average and count | Still listed, marked "Removed by Wassla, not counted", not in their summary | "reviewed" |
| Dismissed | Unchanged | Unchanged | "reviewed" |
| Lifted | Back as written | Back as written | "reviewed" |
- The author (rater) has no screen listing the ratings they gave. Nobody (author, rated person or reporter) gets a notification when staff decide; the reporter only sees the state change in the app.
- The reporter is never told the result, only "received" then "reviewed".
<!-- src: backend/monolith/apps/ratings/public.py, serializers.py, mobile/lib/features/profile/ratings_screen.dart -->

## How does the AI helper work with reviews?
- Record type `review_report`, keyed by the Rating id (not a report id). Needs `moderate_ratings`. Fields it reads: tracking number, score, written by (sender or traveler), writer and rated person, number of open reports, each report's reason, status and time, and the standing decision. The comment and each report's note are treated as untrusted text (they may contain instructions; the helper must not follow them).
- Suggested next step it gives: with open reports "Read the review and the reports, then dismiss them, hide the comment or remove the rating."; with none "No open report. Nothing to do."
- Timeline it shows: Review written, Reported: <reason>, Decision: <state>.
- Actions (all "prepared": the helper prepares, the admin confirms, nothing runs by itself; each needs a reason):
  - `review.dismiss_report` dismiss the reports
  - `review.hide_comment` hide the comment (score still counts)
  - `review.remove` remove the rating from every public average, count and list
  - `review.lift` lift a standing decision
- The helper refuses an action when the review page would not offer it ("The review page does not offer this decision now."), and it records the same audit entries as the console. Task guide: "moderate_review" (asks like "Someone reported a review. What do I do?", "How do I remove a rating?").
- The queue "reviews" in the work list feeds the helper's list of review reports (rows: tracking number, score, open reports).
<!-- src: backend/monolith/apps/admin_helper/resources.py, actions.py, tasks.py -->

## How does the audit log record review decisions?
- Target is the rating (`ratings.rating`), actor is the staff member, with reason, the delivery's tracking number, before and after (the standing decision and the number of open reports) and metadata (how many reports were closed and as what).
- Visible on the review page to staff with `view_audit_log`.
<!-- src: backend/monolith/apps/ratings/moderation.py, console_reviews.py -->

## Worked examples
- Sender gives a traveler 5 stars the day after delivery; the traveler has not rated yet. The sender sees their own rating; the traveler sees nothing and the traveler's average does not change. Day 14: window closes, the rating becomes visible and counts.
- Both rate within 2 days: both become visible immediately and count.
- A traveler's 4 sender ratings are 5, 5, 4, 2. Staff remove the 2: the trip card average goes from 4.0 (4) to 4.7 (3).
- Staff hide a comment on a 1-star rating: the 1 still counts in the average; the text shows "Comment removed by Wassla".

## Is anyone notified about ratings?
- When delivery is confirmed, each party gets one "Leave a review" email and in-app message (the review window opens then).
- Nothing is sent when ratings are revealed, when a review is reported, or when staff decide on a report.
<!-- src: backend/monolith/apps/handover/services.py, notifications/outbox.py, ratings/moderation.py -->

## Not covered here
- Changing the review window, comment limit or tag list: no console form exists; they live only in the stored business settings.
- Ratings do not change Find Travelers ranking; see trips-and-matching.md for ranking.
