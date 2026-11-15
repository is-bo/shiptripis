# Phase L10: final acceptance

Plan: `docs/WASSLA_DISCOVERY_PRO_PLAN.md`, package L10. Report for Ismail:
`docs/WASSLA_L_SERIES_RELEASE_REPORT.md`. L10 changes no product code. It adds acceptance tests, the
gallery and the reports. A fault it finds goes back to the coordinator as a package of its own.

## 1. What was added

| File | Tests | What |
| --- | --- | --- |
| `apps/core/tests/l10_world.py` | none | `AcceptanceWorld`, built on L3A's `SeaWorld`. It sets up a traveler, a sender with a confirmed email, and staff for trust, finance and ops. Every step goes through the API the app calls: post a trip, upload and approve a ticket, publish, set a price, post a parcel, pay the deposit, propose, accept, pay, add the recipient, pick up, report progress, deliver. `carry()` runs one parcel from discovery to payout and checks money, codes and tracking on the way. |
| `test_l10_same_day.py` | 3 | The flight with an approved ticket (with the tracking number checked in every email), the drive with two stops, and the sea leg with the switch on. |
| `test_l10_marketplace.py` | 5 | Both proposal deadlines, the trip-fit alert leading to "I can carry this", a no-show recorded by staff, and a review hidden then removed. |
| `test_l10_staff_and_accounts.py` | 4 | Staff two-step sign-in, the exports reconciled with the dashboard (a `TransactionTestCase`, because the snapshot needs committed rows), and the Google and password-reset claims. |
| `test_l10_switch_matrix.py` | 10 | Every L-series switch turned off by a new settings revision, plus the "on" run of each switch whose effect happens in the background. |

These files are sharded like any other test file (`config/test_shards.py` counts a new file as an
average one). They take about 80 seconds on one worker.

## 2. Contract notes for whoever touches these tests

- The listed price reaches the sender in Find Travelers under `economics.listed`. The proposal is
  sent at `listed.amount_eur_cents`, and the deal's reward is `deal.terms.traveler_reward_minor`.
- A parcel's ready window must contain the leg's departure, or Find Travelers leaves the trip out
  (`pickup_within_ready_window`).
- Progress reports must follow the trip's order (`progress_out_of_order`). `carry()` reports every leg
  up to the parcel's last one.
- Publishing a flight or sea leg needs an approved ticket first (`sea_proof_not_approved`,
  `flight_proof_not_approved`).
- `carry()` runs jobs in the future, and those jobs expire other open parcels. A test that needs a
  second open parcel acts on it first (see `ExportsReconcileTests`).
- With `PAYOUT_PROFILES_ENABLED` off (the test default), a manually settled payout is in provider
  mode `legacy_unknown`. The payout export is downloaded in that mode (finding 2 in the report).
- Exports refuse an end date in the future, so the test freezes the clock after the last event.
- `ExportsReconcileTests` is a `TransactionTestCase`, which starts from empty tables when another
  transaction test ran before it in the same shard. So it seeds the settings revision
  (`seed_business_settings`, as the finance concurrency tests do) and the staff roles' capabilities
  (`seed_admin_roles`, from `ROLE_PERMISSIONS`). `serialized_rollback` is not used: after a flush,
  Django recreates the content types, and the serialized copy then collides with them (first CI run,
  shard 2).
- The marketplace switch helper `activate_marketplace(section)` replaces the whole marketplace
  section with a new revision. The reminder job a switch-off consumes is gone, so the "on" and "off"
  runs are separate tests.

## 3. How the AI helper conversations were run

- **Server.** A throwaway `LiveServerTestCase` (not committed) built L15's `build_world`, a Super Admin
  with a read key and a change key, and an ops admin's expired key. It served on localhost until told
  to stop, and then listed the prepared changes on the server.
- **Assistant.** Each conversation was one Haiku agent told to follow `apps/admin_helper/skill/SKILL.md`
  only and to call the server with curl.
- **Results.** All eleven match `PHASE_L17` section 4; the report's section 3 has the table.
- **Change key check.** The server's prepared changes held only conversation 6's waiting refund.
  Conversation 7 prepared nothing, in either of its two runs.

## 4. How the missing screens were taken

- **L2B and L3B app screens.** The packages' own widget tests were copied into a throwaway folder and
  wrapped so that each test ends with a capture of the screen. The capture uses the app's real fonts
  and Material icons, at 2x. The folder was deleted afterwards. A test's last state is what it shows,
  so a few captures land on a navigation marker; those were not kept.
- **L3B console pages.** A live server and Chromium, with a verified Super Admin session.
- **Small phone and tablet review.** The same wrapping, with the device size and the language
  overridden. That covers L2B, L3B, L4B, L5B, L9B, L12B, L13B and L18B, at 320 × 640 in FR and AR and
  at 834 × 1194 in EN and AR. No layout overflowed. When a test stopped early because a string it
  expects is in another language, the screen was still captured; those stops are not product faults.
- **Debug banner.** The L2B and L3B app captures show Flutter's debug banner in the corner. The review
  captures do not.

## 5. Done when (plan L10)

| Item | Evidence |
| --- | --- |
| 1. Whole suites, counts against the baseline | Report section 1 |
| 2. Scripted scenarios, including the L17 conversations | Report sections 2 and 3; the tests in section 1 above |
| 3. Invariant greps | Report section 4 |
| 4. Switch matrix | Report section 5; `test_l10_switch_matrix.py` |
| 5. Migrations | Report section 6 |
| 6. Performance | Report section 7 |
| 7. Design review and gallery, missing L2B and L3B screens | Report section 8; `/mnt/project-files/l-series-screens/gallery.html`, `L2B/`, `L3B/`, `L10/` |
| 8. Release report and implementation status | `docs/WASSLA_L_SERIES_RELEASE_REPORT.md`; `docs/IMPLEMENTATION_STATUS.md` |
| 9. Switches still off, "Before real users", open decisions | Report sections 9, 10 and 11 |

## 6. Known limits

- The scenarios run on the mock rail in test mode. The Stripe and Chargily live paths are covered by
  their own provider tests, not by a real payment.
- The design review ran at the widget-test level with the real fonts. It is not a run on a device.
- The helper conversations used a harness agent following the skill, not Claude Code's own `/wassla`
  command, the same as L17.
