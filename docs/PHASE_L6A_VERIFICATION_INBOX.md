# L6A: Staff verification inbox (contract)

Package L6A of `docs/WASSLA_DISCOVERY_PRO_PLAN.md` (section 4, as narrowed on 2026-11-13), built
against `docs/WASSLA_DISCOVERY_PRO_SPEC.md` section 13. Backend and console only; there is no mobile
half. The professional half of this package is parked
(`docs/parked/WASSLA_PROFESSIONAL_AND_COURIER_PLAN.md`) and nothing here prepares for it.

## 1. What exists after L6A

- **One inbox, two tabs.** The console's Verification section has one entry, **Verification**,
  which replaces "KYC review" and "Ticket proofs". It opens the inbox: **ID** (identity submissions)
  and **Tickets** (flight and sea ticket proofs), each with its counter, under one shared header.
  "Payout identity checks" stays a separate entry in the same section (it is a step of dinar payout
  approval, not part of spec 13's inbox).
- **One definition of waiting.** `apps/admin_panel/verification_inbox.py` owns it: a row waits while
  its status is `pending`. `waiting_counts(request)` gives one count per tab the staff member may
  see, at most once per request (kept on the request), and everything reads it: the navigation
  total (on the Verification section tab and the entry), the tab counters, the landing tab and the
  overview's two work items ("ID checks to review", "Tickets to review"). Each tab links to its queue
  filtered to `?status=pending`, so a tab shows exactly the rows its counter counted.
- **Landing.** `GET /admin/verification/` (route `verification`) redirects to the first visible tab
  with something waiting, otherwise to the first visible tab (ID for a role that sees both).
- **Tab visibility.** A tab is shown when the staff member holds its queue's own capability:
  `view_kyc` for ID, `view_flight_proofs` for Tickets. With neither, the entry is absent and the
  landing route answers 403.
- **Kept routes.** `kyc-queue`, `kyc-detail`, `kyc-evidence`, `proof-queue`, `proof-detail` and
  `proof-evidence` keep their names and paths, so links from person pages, the payout review page,
  the work list and old notifications still land.
- **One review screen.** `verification_detail.html` serves both kinds with the same header,
  evidence, context, history and decision area, and three decisions: **Approve**, **Ask for a new
  upload**, **Reject**. The last two need a reason. A decided record shows "New upload requested" or
  "Rejected" in its header, in the queue's State column, in the ID queue's "Previous attempt" column
  and in the person's earlier-submissions history.
- **Evidence** is still opened only through the audited staff redirect.

## 2. The three decisions

| Decision value | Stored status | Audit action | Audit `metadata.outcome` | Email / push |
| --- | --- | --- | --- | --- |
| `approved` | `approved` | `kyc.approved` / `flight_proof.approved` | `approved` | Unchanged |
| `resubmission_requested` | `rejected` | `kyc.rejected` / `flight_proof.rejected` | `resubmission_requested` | New: "We need a new upload" |
| `rejected` | `rejected` | `kyc.rejected` / `flight_proof.rejected` | `rejected` | Unchanged |

- The KYC status enum (owned by the Go service) is not changed and `JourneyLegProof` gains no status.
  "Ask for a new upload" is told apart where it is read: the audit entry's `outcome`, the
  notification payload's `outcome`, the email context's `outcome`.
- **Services.** `review_kyc_submission` and `review_flight_proof` take `decision` in
  `verification_inbox.DECISIONS` and a `reason`, required for `resubmission_requested` and
  `rejected` (`AdminReviewError` otherwise). Both still lock the row, check the capability fresh,
  refresh `is_kyc_verified` (KYC) and write the audit row with actor, target, before, after and reason.
- **Replays and races.** A decided row asked again for the *same* decision (a double-submitted form)
  succeeds without writing anything. A *different* decision on a decided row, including "reject"
  against "ask for a new upload" although both store `rejected`, is refused, so a second reviewer is
  never told their choice was saved when the first one's stands.
- **Admin API.** `POST /api/admin/kyc/<id>/review` and `POST /api/admin/flight-proofs/<id>/review`
  accept the same three values; a missing reason is a 400 on `reason`.
- **Payloads.** `kyc.status_changed` carries `{submission_id, status, outcome}`;
  `leg_proof.status_changed` carries `{proof_id, journey_id, mode, status, outcome}`. No channel was
  added or renamed. The email contexts gain `outcome`.
- **Copy.** Push (EN, FR, AR): ID "We need a new upload"; tickets "We need a new flight ticket" /
  "We need a new ferry ticket". Email (EN, FR, AR, in `locale/*/django.po` and the compiled `.mo`):
  "We need a new upload of your identity document" / "... of your flight ticket" / "... of your
  ferry ticket", the reason, and "Open the Wassla app to upload it again." The push picks its copy
  from `outcome` only on the two verification channels.
- **Submitting again.** Exactly as after a rejection: a new KYC submission (Go service, recorded by
  `RecordSubmission`) or a new ticket upload while the journey waits in verification. The new upload
  is a new row in the same tab. The app needs no change: it already offers to submit again after a
  rejection and reads the push.

## 3. Removed

- `apps/core/marketplace_policy.py`: `CourierHandoffPolicy`, `ProfessionalPolicy`, their two fields on
  `MarketplacePolicy`, their parsing and key sets, and their lines in the module docstring. A
  revision that carries either section is now refused as an unknown key when it is saved.
- `apps/trips/proofs.py`: the docstring sentence about an exemption. The functions are unchanged.
- The navigation entries "KYC review" and "Ticket proofs", and their overview work-item titles.

No migration.

## 4. Tests

`apps/admin_panel/tests/test_l6a_verification_inbox.py`, 28 tests:

- counters and the navigation total equal each queue's own rows, for Trust, Super Admin, a
  KYC-only and a tickets-only staff member, Support and Ops; the total falls after a decision;
- tab visibility by capability; 403 on the landing route without either; landing tab in its three
  cases; tab links filtered to what they count; the overview keeps one item per tab;
- the inbox header costs one query per visible tab however many readers ask, and the queue page's
  query count does not grow with its rows;
- each of the three decisions for both kinds: stored status, audit action, actor, reason, before,
  after and `outcome`, the email context, the published payload and its target; reason required for
  two of them (service, console form and API); unknown decision refused; replay silent, a different
  decision on a decided row refused;
- "ask for a new upload" leaves a ticket's leg unmatchable and a later approval opens it;
- an applicant can submit a new ID and a traveler a new ticket after "ask for a new upload";
- the review screen offers the same three decisions for both kinds, refuses a missing reason, reads
  "New upload requested" afterwards, a rejection still reads "Rejected", a viewer without review
  rights sees no decision buttons and gets 403 on a post;
- the email in EN, FR and AR for an ID and for a flight and a ferry ticket, and the push titles in
  EN, FR and AR.

`apps/discovery/tests/test_marketplace_policy.py`: the defaults and bounds tests lose the two
sections; new test: a revision carrying `courier_handoff` or `professional` cannot be saved.

Existing tests rewritten to the new names (spec 13 renames the console entries): `test_l3b_console`
(three label assertions), `test_phase8d_console` (two), `test_admin_dashboard` (one),
`test_phase6c_email_events` (the email context now carries `outcome`).

## 5. Screenshots

`/mnt/project-files/l-series-screens/L6A/`. The console is English only; the person-facing copy is
shown in all three languages through the emails.

| File | What |
| --- | --- |
| `overview-worklist-en.png` | Overview work list with one item per tab |
| `inbox-id-tab-en.png` | Inbox, ID tab, counters, a previous attempt that was asked for a new upload |
| `inbox-tickets-tab-en.png` | Inbox, Tickets tab |
| `inbox-tickets-decided-en.png` | Tickets filtered to decided rows: "New upload requested" |
| `inbox-id-tab-narrow-en.png` | Inbox at 390 px |
| `review-id-pending-en.png` | Review screen for an ID, three decisions, history |
| `review-ticket-pending-en.png` | Review screen for a ticket, same layout |
| `review-ticket-reason-missing-en.png` | "Ask for a new upload" without a reason: refused with the message |
| `review-ticket-new-upload-requested-en.png` | After the decision: header chip, reason sent, decided note |
| `review-id-narrow-en.png` | Review screen at 390 px |
| `email-id-new-upload-{en,fr,ar}.png` | The ID email for "ask for a new upload" |
| `email-ticket-new-upload-{en,fr,ar}.png` | The flight ticket email for "ask for a new upload" |

## 6. Known limits

- In the app's notification list, both kinds of decision keep the generic "Account" row (the app
  renders that row by channel, not by status); the push and the email carry the distinction.
- The technical Django-admin queue panel (superuser only) keeps its own changelist counts, by
  design: it counts rows behind links to raw changelists, not console queues. Its two labels now
  read "ID checks to review" and "Tickets to review".
