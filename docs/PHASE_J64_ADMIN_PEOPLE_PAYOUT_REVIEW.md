# Phase J6.4 — Admin People profile and simplified payout-method review

Status: implemented, TEST only. Stripe TEST, Chargily TEST,
`PAYOUT_DZD_EXECUTION_ENABLED` false, no LIVE provider activation and no
real-money operation.

Starting point: `b842622` (J6.3 docs). Branch `claude/j64-admin-people-payout-review`.
No schema change, no migration, no change to payout accounting, routing, the
ledger, commission, reconciliation or any H5 definition.

The owner reported four things: a pending DZD payout method was visible only
inside Finance; the review page buried the decision under warnings, codes and
blockers; **Approve did not work**; and clicking a person did not show the person.
J6.4 fixes all four in the operations console and nowhere else.

---

## 1. Why Approve did not work

The decision itself was never broken. `review_profile` has recorded approvals
since H4. What was broken is the prerequisite in front of it.

`review_profile` refuses every decision — approve, reject and correction alike —
unless the Traveler has a current `PayoutIdentityAttestation`: a reviewer's
statement of the Traveler's legal name, read from their approved ID. That record
is created by two existing commands:

1. `assign_identity_review` — Finance names a reviewer holding
   `attest_payout_identity`;
2. `attest_identity` — that reviewer records the legal given and family names.

J1.2 gave step 1 a console control. **Step 2 had no console surface at all**; it
existed only as `POST /api/finance/admin/payout-identity-reviews/<ref>`, a JSON
endpoint nobody operating the console could reach. So on every fresh submission
the flow was: open the review, assign an identity review (to yourself, as the
owner), and then nothing — the page kept saying "no decision can be recorded until
that happens", with no way to make it happen. That is the reported bug.

J6.4 does not weaken the gate. It gives step 2 a console surface, and composes
steps 1 and 2 for the one role that holds both capabilities.

## 2. The identity prerequisite, resolved by role

The review page now branches on one value, `stage`, computed server-side:

| Stage | When | What the operator sees |
|---|---|---|
| `decide` | identity attested, cheque attached | Approve and Reject |
| `confirm` | identity missing, operator can attest **and** assign **and** see the ID (Super Admin) | "Identity check required": the approved ID image beside two name fields, then **Confirm identity and approve** |
| `assign` | identity missing, operator cannot attest (Finance) | "Identity check required — Who can do this: Trust & Verification or a Super Admin", and **Request identity check** |
| `waiting` | a check has been requested | "Waiting on *reviewer* · asked *date*", with "Ask someone else" collapsed |
| `kyc` | no current approved ID to check a name against | "ID not approved yet", with **Open KYC review** when the ID is pending |
| `no_evidence` | no complete cheque | "Nothing to decide yet" |
| `read_only` | operator holds the page but not the decision capabilities | a one-line note |

No stage shows a button the server would refuse.

**Super Admin (one guided step).** `confirm_identity` assigns the check to the
operator (reusing an open, still-valid assignment of theirs if one exists) and
attests it, inside one transaction so a refused attestation leaves no dangling
assignment. Both are the existing commands, with their own capability checks and
their own audit rows (`payout_identity.assigned`, `payout_identity.attested`).
Then, only if the operator pressed **Confirm identity and approve**, the page runs
the audited name comparison: if the names are consistent it records the approval
through `review_profile`; if they are spelled differently it records **nothing
more** and says so — "Identity confirmed, but not approved yet" — so the operator
decides the name difference with the cheque in front of them. **Confirm identity
only** stops after the attestation.

Required on the form: both names, and a ticked "I entered these names from the
approved ID document". Nothing is prefilled — not from the payout account holder,
which is the claim being checked, and not from the user's display name, which the
user edits freely. An optional second spelling (Arabic script, a transliteration)
is recorded as an attested alias through the same command.

**Finance.** Cannot attest (`attest_payout_identity` is Trust's). The page names
whose move it is and lets Finance request the check. A Finance POST of the Super
action is refused before any command runs and leaves nothing behind.

**Trust & Verification.** A new Verification destination, **Payout identity
checks** (`/admin/verification/payout-identity/`), lists open checks — assigned
to me first, all open checks one click away. The detail page shows the Traveler,
the approved ID image through the existing audited KYC evidence route, and the
same two-field form. It calls `attest_identity` directly; only the assigned
reviewer can submit. A check made stale by a Super Admin confirming the identity
directly reads "Already confirmed" and is not counted as waiting. The main
Overview shows Trust **Payout identity checks assigned to you — N**.

## 3. Global pending-review behaviour

`awaiting_review_count()` is the single authority: a DZD method whose current
profile revision has no review yet. It is one indexed query.

* **Main Overview → Action queues:** "Payout methods awaiting approval — N ·
  Travelers submitted DZD payout details that need review." Placed directly after
  Open disputes, with the other decision queues. Visible to holders of
  `review_payout_profiles` (Finance, Super). One click opens the queue.
* **Finance Overview → Needs attention:** the same number, the same label.

Both read it on every render, so recording a decision clears it immediately. QA:
5 → 2 after three decisions, no manual step.

## 4. The queue

Default view: **Waiting for review**. Correction requested, Rejected and Approved
sit under a quieter **History** label. Each row: Traveler name (a link to their
profile) and email, submitted date and age, status, and a small blocker only when
it genuinely blocks the decision — *ID not approved yet*, *Identity check needed*,
*Identity check with <reviewer>*, or *No cheque attached*. One **Review** button.
Removed from the list: revision and method-version numbers, the cheque column,
reason codes and the long footer. No account value, masked or not, appears.

## 5. The review page

Order: **Person** (name linked to profile, email, ID state, name-on-account check,
member since) · **Payout method** (CCP, key, RIP masked; account holder hidden;
**Show full details** — the audited reveal) · **Crossed cheque** (large inline
preview beside the decision on desktop; "Open full size") · **Decision**.

* **Approve** is one click. If the name on the account differs from the attested
  identity, Approve opens a confirmation whose "I checked the cheque and accept the
  name difference" box is required. Posting Approve without it is refused by the
  console with a sentence and records nothing — previously `review_profile` would
  quietly record *needs correction* and notify the Traveler, which read exactly
  like "Approve does not work". The domain rule is unchanged for the API.
* **Reject** opens a small dialog: the Traveler is told the account was refused
  and asked for a different one; they are not told why. There is no reason field
  because `review_profile` stores none; the Traveler-facing outcome is the existing
  safe `profile_rejected` code.
* **Ask for a correction** is under **More**, not a third primary button. The
  distinct `needs_attention` state is preserved.
* Dialogs are real links (`?confirm=reject#decision`) that the server answers with
  the dialog already open, so decisions work without script; with script they open
  in place as modals and focus Cancel (or the acceptance box), never the committing
  button.
* Once decided: the outcome and "N more waiting"; changing it is under a collapsed
  **Change decision**.
* **Review history (N)** and **Details** (status codes, revision numbers, reference,
  who confirmed identity, the trilingual document label) are collapsed.

## 6. Security, unchanged

| Control | J6.4 |
|---|---|
| Masked values by default | Unchanged: `•••• last4`, key `••`, holder hidden |
| Full reveal | Unchanged `reveal_profile`: POST only, `no-store`, `payout_profile.revealed` audit, auto-hide after five minutes |
| Cheque | Same scoped route (profile reference, never an evidence id); every load audited by `read_evidence` (`payout_evidence.viewed`). The preview now loads inline on the review page, so opening the review is itself an audited view |
| ID image on the identity check | Existing `kyc-evidence` route: `view_kyc` + `view_evidence`, reachability checked first, `kyc.evidence_viewed` audit |
| Capabilities | Queue and review: `review_payout_profiles` (+`view_payout_sensitive`); identity checks: `attest_payout_identity`; unchanged domain checks underneath |
| NIP / immutable revisions | Unchanged; no edit control exists |

## 7. The Person profile

Route: `/admin/users/<id>/` (url name `user-detail`, so every existing link lands
here). Replaces the four-count user page.

**Reaching it** needs any capability that already shows the person's name
somewhere in the console (`people_links.PROFILE_CAPABILITIES`: `view_users`,
`view_kyc`, `view_deals`, `view_disputes`, `view_payouts`, `view_finance_summary`,
`review_payout_profiles`, `attest_payout_identity`, `view_payment_orders`,
`view_payment_attempts`). Finance and Ops hold no `view_users` but were already
shown names and emails in their queues; a name that 403s when clicked is worse
than plain text.

**Header:** initials avatar, name, account number, email, phone (only with
`view_user_sensitive`), joined date, chips for account state (Active / Banned /
Sign-in disabled), marketplace role, staff roles, email and phone verification and
ID state. Actions only when something waits on this operator: **Review payout
method**, **Review ID**.

**Tabs** (each loads alone; a tab a role cannot read is not rendered, and asking for
it by URL returns the Overview):

| Tab | Contents | Capability |
|---|---|---|
| Overview | Needs attention for this person; at-a-glance facts (requests, journeys, deliveries, disputes, revealed rating); account; payout readiness and payment/payout issues | page gate; each fact by its own capability |
| Identity | contact and verification; ID submissions (link to KYC review); legal-name confirmations for DZD payouts (state, who, when — never the name) and open identity checks | `view_users` / `view_kyc` / payout identity capabilities |
| Activity | **Parcel requests** (J1.3 lifecycle state, route, ready window and deadline, reward, Boost — frozen Deal terms once a Deal exists — created; opens its Deal) · **Journeys** (route with modes, dates, smallest capacity, matched deliveries, state; opens Journey) · **Offers** (request, journey, side, state, base reward, Boost, Traveler total from J6.1 `OfferEconomicsReader`; opens the Deal) | `view_requests` / `view_journeys` / `view_deals`, `view_matches` |
| Deliveries | All / Active / Completed / Cancelled (the server's `activity_q`); Deal, role, counterparty (linked), route, lifecycle, balance payment, payout state (Traveler side), amount from frozen terms | `view_deals` |
| Payments | purpose, EUR obligation, paid/refunded/credited, provider and attempt state, created; provider references behind **Technical details** (no checkout URL, no idempotency key) | `view_payment_orders` / `view_payment_attempts` |
| Payouts | preferred payout (EUR / DZD / both), Stripe readiness, DZD details (revision, latest decision, **Review/Open payout method**), payout history with manual-DZD receipt state | `view_payouts` / `view_finance_summary` / `review_payout_profiles` |
| Trust & support | account state, no-shows recorded against the person, cancellations by the person; **Disputes**, **Ratings** (revealed only), **Notifications** (what and whether read, never content) | `view_disputes` / `view_ratings` / `view_support_context` |
| Audit | **About this person** (the person, their ID submissions, payout method/details/identity records, payout documents, Stripe account, payouts, holds, payments, refunds, Deals, disputes, dispute evidence); **Actions by this person** for staff accounts | `view_audit_log` |

Deliberately not shown: payout account values (masked or not), ID images, chat
content, hidden ratings and notification payloads. **Chat:** the console has no
authorized support access to conversations, so the profile says so in one line
and links nowhere; no new privacy exposure was created. The automatic
`payout_identity.compared` rows (written on every review-page render) are omitted
from the person's Audit tab and remain in the full audit log.

## 8. Names link everywhere

A shared `person_link` template tag and `_person_link` helper render a name as a
link only when `may_open_people` is true for the operator. Linked: payout review
queue and page, identity checks, Delivery requests, Journeys (list and detail),
Deals (list: Sender and Traveler; detail), Disputes (list and detail), Payments
(payer), Payout accounts, Payout detail, Manual DZD payout, KYC detail. Queues whose
row already opens the person's record keep that behaviour.

**Return navigation:** a profile opened from a queue carries a closed-vocabulary
`from` (`payout-reviews`, `identity-checks`, `deals`, `disputes`, `kyc`, `payouts`)
resolved to named routes for its breadcrumbs — never a URL from the request. A
payout review opened from a profile carries `from=person`: breadcrumb and **Back to
profile** return there.

## 9. Performance

Measured on PostgreSQL against the QA preview database (one warmed GET each,
session and permission reads included):

| Page | Queries |
|---|---|
| Main Overview (Super) | 15 |
| Payout method queue | 10 |
| Review page — decide / KYC stage | 17 / 14 |
| Profile Overview — Traveler with DZD payout / Sender | 20 / 13 |
| Identity · Requests · Journeys · Offers | 9 · 7 · 8 · 7 |
| Deliveries · Payments · Payouts | 9 · 8 · 19 |
| Disputes · Ratings · Notifications · Audit | 9 · 10 · 9 · 7 |

Every figure is a constant: grouped aggregates for the Overview, one page (20 rows)
per list with its relations joined or prefetched, one Paginator COUNT.
`test_overview_and_every_history_tab_cost_the_same_as_history_grows` renders the
Overview and all twelve history views, adds 25 more requests, journeys,
notifications and audit rows, and asserts every count is **identical**, below a
ceiling of 40. The review page's count is asserted flat across five decisions of
history. The Finance dashboard's ~90-query snapshot is not touched by any of this.

## 10. Browser QA

Real console, real PostgreSQL rows produced by the real services, synthetic people
and documents only (every name ends "(QA)"; cheque and ID images read "QA
SYNTHETIC — NOT A …"), mock payment rail only. Headless Edge for full-page
captures and the in-app browser for interaction and 390 px checks.

| Check | Result |
|---|---|
| A. Main Overview shows pending payout methods | PASS — "5 · Payout methods awaiting approval" in Action queues, Finance and Super |
| B. Queue | PASS — Waiting first (5), History quiet, blockers "ID not approved yet" / "Identity check with Tara Trust (QA)" / "Identity check needed" |
| C. Simple review page | PASS — Person, masked payout method, large cheque, decision; history and details collapsed |
| D. Approve (Finance, identity already confirmed) | PASS — one click, "Approved. This CCP account can now receive…", "4 more waiting" |
| Reveal | PASS — full values with Copy, "this open was audited" |
| E. Reject | PASS — modal opens in place, confirm → "Rejected…", status `profile_rejected` |
| Super Admin one-step identity + approve | PASS — names typed from the ID image, "Identity confirmed and payout method approved" |
| Trust identity check | PASS — Overview "1 · Payout identity checks assigned to you", attested in console, Finance then sees Approve |
| Count after decisions | PASS — 5 → 2 on the main Overview, no manual step |
| F/G. Person profile with Sender and Traveler activity, payments, payouts, dispute, ratings, audit | PASS — all eight tabs render real records |
| Support role | PASS — no Payments/Payouts tabs, no phone, no payout readiness |
| H. Narrow | PASS — 11 pages at 390 px with page width equal to viewport (no horizontal scroll); queue rows and profile lists restack as labelled cards; tabs wrap as pills |

Defects found in QA and fixed before commit: list items inherited Django admin's
square bullets; Reject was wider than Approve (link vs button box sizing); the ID
preview was too small to read a name from; the dialog focused the destructive
button; queue ages read "0 minutes ago"; audit records read
"Dzdpayoutprofilerevision"; on phones the Review button overhung its card and the
amount was indented; the confirmation checkboxes had no accessible name.

## 11. Findings for Codex (backend, not changed here)

* **MINOR — Reject needs an identity attestation.** `review_profile` requires a
  current attestation for every decision, including `rejected` and
  `needs_attention`. An obviously invalid submission from a Traveler with no
  approved ID cannot be refused until they have one. Changing it is a finance
  domain rule change and was out of scope.
* **MINOR — Ban/unban is not audited.** `UserAdmin.ban_users` / `unban_users` use a
  bulk `update()` with no `AdminAuditLog` row, so suspension changes cannot appear
  in a person's Audit tab.
* **MINOR — Open identity checks cannot be closed.** When a Super Admin confirms an
  identity directly, a check assigned to someone else stays open (no domain command
  closes an assignment without attesting). The console labels it "Already
  confirmed" and excludes it from counts.
* **MINOR — Name comparison is audited on every render.** `profile_name_consistency`
  writes `payout_identity.compared` whenever the review page loads (pre-existing).
* **MINOR — No request detail page.** A parcel request without a Deal has no
  console page to open; the profile lists it without a link.

## 12. Tests

* `apps/finance/tests/test_phase_j64_payout_review.py` (12): both overview counts
  and their disappearance; role visibility; queue default and safe fields; one-click
  Approve and page hierarchy; Reject and correction with dialog, immutability and
  history; name-difference acceptance; Super one-step identity + approval with the
  audit trail; checkbox requirement leaving no assignment; name difference stopping
  before approval; Finance refused and told whose move it is, Trust completing the
  check in the console, Finance then approving; KYC-pending stage; masked values,
  audited reveal and audited cheque; flat review-page cost.
* `apps/admin_panel/tests/test_phase_j64_person_profile.py` (5): the complete
  profile through real services; tabs per role with URL fallback and phone gating;
  no payout value, hidden rating or notification payload on any tab; blind-window
  ratings; flat and bounded query counts with pagination.
* `test_phase_j12_finance_route_performance.py`: four assertions updated for the
  deliberate J6.4 changes (no revision in the queue, new copy, and the console
  refusing an unaccepted name difference instead of silently recording a
  correction — the domain substitution is still asserted directly).
