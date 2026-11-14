"""How an admin does each thing in the console (spec 20.5, plan L15).

The helper's ``tasks`` answer. One entry per thing an admin can do in the
console, keyed to the capability of the console page it starts on (any of
them opens it, exactly as on that page) and to that page's route. The steps
are written here, once, so an assistant never makes up a procedure.

Every console route is either covered by a task (`Task.covers`) or named in
`NO_TASK` with the reason, and a test holds both lists to the console's
routes, so the how-to cannot fall behind the console.

``action`` is the code of the helper change that does the same thing (L16);
none exists in L15, so it is ``None`` everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Task:
    code: str
    title: str
    #: Example questions an admin asks for this task.
    asks: tuple[str, ...]
    #: Plain sentences, in order.
    steps: tuple[str, ...]
    #: The capabilities of the console page the task starts on: any opens it.
    permission: tuple[str, ...]
    #: The console page the task starts on (a route that takes no argument).
    route: str
    #: Every console route the task explains, ``route`` included.
    covers: tuple[str, ...]
    #: True when the work means looking at a document: the helper cannot
    #: decide it, only send the admin to it.
    needs_document: bool = False
    #: The helper change that does the same thing (L16), or ``None``.
    action: str | None = None


TASKS: tuple[Task, ...] = (
    # --- the day's work -----------------------------------------------------------
    Task(
        code="see_my_work",
        title="See what needs you now",
        asks=("What should I do first?", "Is anything urgent?"),
        steps=(
            "Open Overview.",
            "Read the list under What needs attention from the top: the most urgent work is first.",
            "Open an item to go to its queue. A queue with nothing waiting says so at the end.",
        ),
        permission=("view_dashboard",),
        route="admin_console:overview",
        covers=("overview",),
    ),
    # --- people -------------------------------------------------------------------
    Task(
        code="find_person",
        title="Find a person and see their activity",
        asks=("Who is this sender?", "What has this traveler done on Wassla?"),
        steps=(
            "Open People, then Users.",
            "Search by name or email, or follow the person's name from any delivery, dispute or payment.",
            "Their page shows what needs attention first, then their requests, trips, deliveries and payments.",
        ),
        permission=("view_users",),
        route="admin_console:users",
        covers=("users", "user-detail"),
    ),
    Task(
        code="hide_public_profile",
        title="Hide or show a person's public profile",
        asks=("How do I hide someone's public profile?", "How do I show a hidden profile again?"),
        steps=(
            "Open the person's page from People, then Users.",
            "In the Discovery section, press Hide profile (or Show profile again on a hidden one).",
            "Write the reason, then confirm with the same button.",
        ),
        permission=("manage_users",),
        route="admin_console:users",
        covers=("user-profile-visibility",),
    ),
    # --- verification -------------------------------------------------------------
    Task(
        code="review_id_check",
        title="Review an ID check",
        asks=("How do I approve a traveler's ID?", "What do I do with an ID check?"),
        steps=(
            "Open Verification, then the ID tab. The oldest check is first.",
            "Open a check and look at the document and the selfie.",
            "Press Approve, Ask for a new upload (say what is wrong) or Reject.",
        ),
        permission=("view_kyc",),
        route="admin_console:kyc-queue",
        covers=("verification", "kyc-queue", "kyc-detail", "kyc-evidence"),
        needs_document=True,
    ),
    Task(
        code="review_ticket",
        title="Review a ticket",
        asks=("How do I approve a flight ticket?", "Why can't a traveler's flight be matched?"),
        steps=(
            "Open Verification, then the Tickets tab. The oldest ticket is first.",
            "Open a ticket and compare it with the trip leg: date, route and the traveler's name.",
            "Press Approve, Ask for a new upload (say what is wrong) or Reject.",
        ),
        permission=("view_flight_proofs",),
        route="admin_console:proof-queue",
        covers=("proof-queue", "proof-detail", "proof-evidence"),
        needs_document=True,
    ),
    Task(
        code="confirm_payout_identity",
        title="Confirm a traveler's legal name for their payout method",
        asks=("What is a payout identity check?", "How do I confirm a legal name?"),
        steps=(
            "Open Verification, then Payout identity checks. Only the checks assigned to you are listed.",
            "Open a check and compare the name on the payout method with the approved ID.",
            "Press Confirm identity, or the option that also approves the payout method when the page offers it.",
        ),
        permission=("attest_payout_identity",),
        route="admin_console:identity-checks",
        covers=("identity-checks", "identity-check-detail"),
        needs_document=True,
    ),
    Task(
        code="moderate_review",
        title="Decide a reported review",
        asks=("Someone reported a review. What do I do?", "How do I remove a rating?"),
        steps=(
            "Open Verification, then Reported reviews. The oldest report is first.",
            "Open a review and read it as written and the reports about it.",
            "Choose Dismiss the reports, Hide the comment or Remove the rating, write the reason and confirm.",
            "A decision can be undone later with Lift the decision.",
        ),
        permission=("moderate_ratings",),
        route="admin_console:reviews",
        covers=("reviews", "review-detail"),
    ),
    # --- marketplace --------------------------------------------------------------
    Task(
        code="find_request",
        title="Find a delivery request",
        asks=("Where is parcel WSL-…?", "What did this sender ask to send?"),
        steps=(
            "Open Marketplace, then Delivery requests.",
            "Search by tracking number.",
            "The row shows its status, route and price; its delivery, once a traveler took it, is under Deals.",
        ),
        permission=("view_requests",),
        route="admin_console:requests",
        covers=("requests",),
    ),
    Task(
        code="look_at_journey",
        title="Look at a traveler's trip",
        asks=("What trip is this traveler on?", "Is this trip's ticket approved?"),
        steps=(
            "Open Marketplace, then Journeys.",
            "Open the trip: each segment shows its times and its ticket state, and Who is carrying lists its deliveries.",
        ),
        permission=("view_journeys",),
        route="admin_console:journeys",
        covers=("journeys", "journey-detail"),
    ),
    Task(
        code="pause_journey",
        title="Pause or resume a traveler's trip",
        asks=("How do I stop a trip taking new offers?", "How do I resume a paused trip?"),
        steps=(
            "Open the trip from Marketplace, then Journeys.",
            "Press Pause journey (or Resume journey on a trip staff paused).",
            "Write the reason: the traveler does not see it. Deliveries already paid are not affected.",
        ),
        permission=("manage_journeys",),
        route="admin_console:journeys",
        covers=("journey-pause",),
    ),
    Task(
        code="follow_delivery",
        title="Follow one delivery",
        asks=("Where is this delivery?", "Has the traveler picked it up?"),
        steps=(
            "Open Marketplace, then Deals, and search by tracking number.",
            "The deal page shows what each side owes, the handover and payout hold, its disputes and problems.",
            "What happened, in order, at the bottom is its full timeline.",
        ),
        permission=("view_deals",),
        route="admin_console:deals",
        covers=("deals", "deal-detail"),
    ),
    Task(
        code="record_no_show",
        title="Record a no-show",
        asks=("The traveler did not come. What do I do?", "How do I record that the sender was not there?"),
        steps=(
            "Open Disputes, then Problems, and open the no-show report; or open the deal and press Record a no-show.",
            "Talk to both people first.",
            "Choose who did not come, write a note and press Record the no-show. A traveler no-show refunds the sender in full.",
        ),
        permission=("record_no_show",),
        route="admin_console:problems",
        covers=("deal-no-show",),
    ),
    # --- disputes and problems ----------------------------------------------------
    Task(
        code="decide_dispute",
        title="Move a dispute along and decide it",
        asks=("How do I resolve a dispute?", "How do I ask for more evidence?"),
        steps=(
            "Open Disputes. Open the dispute.",
            "Read Money at stake, what each side says and the evidence.",
            "To ask for evidence or start the review, use Move the review along and press Update state.",
            "To decide, use Resolve this dispute: choose the outcome, press Preview consequence, read it, then Confirm resolution.",
        ),
        permission=("view_disputes",),
        route="admin_console:disputes",
        covers=("disputes", "dispute-detail", "dispute-evidence"),
    ),
    Task(
        code="handle_problem",
        title="Handle a reported problem",
        asks=("A sender reported a damaged parcel. What do I do?", "How do I close a problem report?"),
        steps=(
            "Open Disputes, then Problems. The reports waiting for staff are first.",
            "Open a report and read it in the reporter's words.",
            "Press Acknowledge with a short reason so the people know staff are on it.",
            "When it is settled, press Close report with a reason. Money moves only through a dispute, a cancellation or a no-show.",
        ),
        permission=("view_disputes",),
        route="admin_console:problems",
        covers=("problems", "problem-detail"),
    ),
    # --- payments and refunds -----------------------------------------------------
    Task(
        code="check_payment",
        title="Check a payment",
        asks=("Did this sender pay?", "Why is this payment flagged?"),
        steps=(
            "Open Finance, then Payments, and search by tracking number or reference.",
            "Open the payment to see its order, its amount and what the provider recorded.",
        ),
        permission=("view_payment_attempts", "view_payment_orders"),
        route="admin_console:payments",
        covers=("payments", "payment-detail"),
    ),
    Task(
        code="reconcile_payment",
        title="Reconcile a flagged payment",
        asks=("Money arrived but no order took it. What do I do?", "How do I clear a payment alert?"),
        steps=(
            "Open the payment from Finance, then Payments.",
            "To ask the provider again, press Queue reconciliation.",
            "When the money is accounted for, press Archive attention item and write how it was resolved.",
        ),
        permission=("reconcile_finance",),
        route="admin_console:payments",
        covers=("payment-reconcile", "payment-resolve"),
    ),
    Task(
        code="request_refund",
        title="Request a refund",
        asks=("How do I refund a sender?",),
        steps=(
            "Open the payment from Finance, then Payments.",
            "Press Request refund, enter the amount and the reason, then press Request refund.",
            "The refund then appears under Finance, then Refunds.",
        ),
        permission=("issue_refunds",),
        route="admin_console:payments",
        covers=("refund-new",),
    ),
    Task(
        code="settle_refund",
        title="Settle a refund by hand",
        asks=("A refund is stuck. What do I do?",),
        steps=(
            "Open Finance, then Refunds. The ones a person has to send are marked.",
            "Open the refund and read why the automatic refund stopped.",
            "Send the money by the provider's own dashboard, then press Mark refund settled with its reference.",
        ),
        permission=("issue_refunds", "settle_manual_refunds"),
        route="admin_console:refunds",
        covers=("refunds", "refund-detail"),
    ),
    # --- payouts ------------------------------------------------------------------
    Task(
        code="follow_payout",
        title="Follow a traveler's payout",
        asks=("When will this traveler be paid?", "Why is this payout blocked?"),
        steps=(
            "Open Finance, then Payouts, and open the payout.",
            "What is stopping this payout says what it waits for.",
            "A failed bank payout has Retry bank payout; Hold for Finance review stops it until a person releases the hold.",
        ),
        permission=("view_payouts",),
        route="admin_console:payouts",
        covers=("payouts", "payout-detail", "payout-evidence"),
    ),
    Task(
        code="finance_payouts",
        title="See every payout by stage",
        asks=("Which payouts are waiting?",),
        steps=(
            "Open Finance, then Payouts.",
            "Each stage lists its payouts; open one to see what it waits for.",
        ),
        permission=("view_finance_summary",),
        route="admin_console:finance-payouts",
        covers=("finance-payouts",),
    ),
    Task(
        code="send_dzd_payout",
        title="Send a dinar payout by hand",
        asks=("How do I pay a traveler in dinars?",),
        steps=(
            "Open Finance, then Manual DZD.",
            "Press Claim and prepare transfer on a payout, so nobody else sends it too.",
            "Follow the steps on the page: reveal the details, send the transfer from the bank, then record the transfer evidence.",
            "If you cannot finish, press Release the claim.",
        ),
        permission=("view_finance_summary",),
        route="admin_console:finance-dzd",
        covers=("finance-dzd",),
    ),
    Task(
        code="review_payout_method",
        title="Review a traveler's payout method",
        asks=("How do I approve a payout method?",),
        steps=(
            "Open Finance, then Payout method reviews.",
            "Open a method and check the details against the documents.",
            "Approve it, ask for a correction, or reject it. A name that needs confirming goes to a payout identity check first.",
        ),
        permission=("review_payout_profiles",),
        route="admin_console:payout-reviews",
        covers=("payout-reviews", "payout-review-detail", "payout-review-evidence"),
        needs_document=True,
    ),
    Task(
        code="check_payout_accounts",
        title="Check travelers' payout accounts",
        asks=("Can this traveler receive payouts?",),
        steps=(
            "Open Finance, then Payout accounts.",
            "Each traveler's row says whether their account can receive a payout and what is missing.",
        ),
        permission=("view_finance_summary",),
        route="admin_console:payout-accounts",
        covers=("payout-accounts",),
    ),
    # --- finance overview ---------------------------------------------------------
    Task(
        code="finance_overview",
        title="See where the money is",
        asks=("How much money is held right now?",),
        steps=(
            "Open Finance, then Overview.",
            "It shows what needs Finance first, then the money held, owed and paid out.",
        ),
        permission=("view_finance_summary",),
        route="admin_console:finance-dashboard",
        covers=("finance-dashboard",),
    ),
    Task(
        code="finance_exceptions",
        title="See refunds and disputes that hold money",
        asks=("Which refunds and disputes hold money?",),
        steps=(
            "Open Finance, then Refunds & disputes.",
            "Open a row to go to its refund or dispute. Nothing on this page moves money.",
        ),
        permission=("view_finance_summary",),
        route="admin_console:finance-exceptions",
        covers=("finance-exceptions",),
    ),
    Task(
        code="reconcile_finance",
        title="Reconcile the books",
        asks=("Do the books balance?",),
        steps=(
            "Open Finance, then Reconciliation.",
            "Each check says whether it matches; open a row that does not to see the records behind it.",
        ),
        permission=("view_finance_summary",),
        route="admin_console:finance-reconciliation",
        covers=("finance-reconciliation", "finance-rows"),
    ),
    Task(
        code="export_finance",
        title="Download a finance export",
        asks=("How do I export the transactions?", "How do I get the commissions for a month?"),
        steps=(
            "Open Finance, then Exports.",
            "Choose the export and the dates, then press Download CSV.",
        ),
        permission=("export_finance",),
        route="admin_console:finance-exports",
        covers=("finance-exports",),
    ),
    Task(
        code="read_ledger",
        title="Read the ledger",
        asks=("Show me the ledger entries for this payment.",),
        steps=(
            "Open Finance, then Ledger.",
            "Filter by reference to see every entry one payment or payout made.",
        ),
        permission=("reconcile_finance",),
        route="admin_console:ledger",
        covers=("ledger",),
    ),
    # --- staff and settings -------------------------------------------------------
    Task(
        code="manage_staff",
        title="Invite staff and change their access",
        asks=("How do I invite a new admin?", "How do I remove someone's access?"),
        steps=(
            "Open Staff, then Staff & access.",
            "To invite someone, fill in Invite a staff member and press Send the invitation.",
            "To change a role, choose it on their row and press Set role.",
            "An invitation can be revoked or replaced from the Invitations list.",
        ),
        permission=("manage_admins",),
        route="admin_console:staff",
        covers=("staff", "staff-role", "staff-access", "staff-invitation-action"),
    ),
    Task(
        code="reset_two_step",
        title="Reset a staff member's two-step sign-in",
        asks=("A colleague lost their phone. How do they sign in?",),
        steps=(
            "Open Staff, then Staff & access.",
            "On their row press Reset two-step and write the reason.",
            "They set it up again at their next sign-in. Their AI helper keys stop too.",
        ),
        permission=("manage_admins",),
        route="admin_console:staff",
        covers=("staff-two-step-reset",),
    ),
    Task(
        code="change_settings",
        title="Change the business settings",
        asks=("How do I change the commission?", "How do I switch the AI helper off?"),
        steps=(
            "Open Settings, then Business settings.",
            "Change the form you need and press its save button. Each save makes a new settings version.",
        ),
        permission=("view_settings",),
        route="admin_console:settings",
        covers=("settings",),
    ),
    # --- system -------------------------------------------------------------------
    Task(
        code="check_health",
        title="Check that the system is healthy",
        asks=("Is anything broken?", "Are payments and email working?"),
        steps=(
            "Open System, then Health.",
            "A provider marked in red is enabled without what it needs to work; fix its configuration.",
        ),
        permission=("view_provider_health", "view_operational_incidents", "view_scheduled_jobs"),
        route="admin_console:system",
        covers=("system",),
    ),
    Task(
        code="check_jobs",
        title="See background jobs",
        asks=("Did any background job fail?",),
        steps=(
            "Open System, then Background jobs.",
            "Open a job to see what it does, its state and its error category.",
        ),
        permission=("view_scheduled_jobs", "view_operational_incidents"),
        route="admin_console:jobs",
        covers=("jobs", "job-detail"),
    ),
    Task(
        code="fix_job",
        title="Retry or resolve a failed background job",
        asks=("How do I retry a failed job?",),
        steps=(
            "Open the job from System, then Background jobs.",
            "Press Queue retry to run it again, or Archive failure with a reason when it must not run again.",
            "Several jobs can be handled at once from the list with Apply audited action.",
        ),
        permission=("reconcile_finance", "manage_lifecycle"),
        route="admin_console:jobs",
        covers=("job-retry", "job-resolve", "job-bulk"),
    ),
    Task(
        code="check_email",
        title="Check failed email",
        asks=("Why did a person not get our email?",),
        steps=(
            "Open System, then Email queue, and filter on failed.",
            "Each row says why sending failed. The message is kept and is sent again.",
        ),
        permission=("view_provider_health",),
        route="admin_console:email",
        covers=("email",),
    ),
    # --- reference ----------------------------------------------------------------
    Task(
        code="browse_geography",
        title="Look up a city, airport or sea crossing",
        asks=("Which airports does Wassla know in Spain?",),
        steps=(
            "Open Reference, then Geography catalogue.",
            "Search by name; sea crossings are listed in their own section.",
        ),
        permission=("view_operational_incidents", "view_journeys"),
        route="admin_console:geography",
        covers=("geography",),
    ),
    Task(
        code="manage_sea_crossings",
        title="Add, turn on or turn off a sea crossing",
        asks=("How do I add a ferry crossing?",),
        steps=(
            "Open Reference, then Geography catalogue.",
            "To add one, press Add a crossing, fill it in and press Add crossing.",
            "To change one, press Turn on or Turn off on its row, write the reason and confirm.",
        ),
        permission=("manage_settings",),
        route="admin_console:geography",
        covers=("sea-crossing-new", "sea-crossing-toggle"),
    ),
    Task(
        code="read_audit_log",
        title="See who did what",
        asks=("Who changed this setting?", "What did this admin do today?"),
        steps=(
            "Open Reference, then Audit log.",
            "Filter by person, action or record. Every staff action is there, with its reason.",
        ),
        permission=("view_audit_log",),
        route="admin_console:audit",
        covers=("audit",),
    ),
)

#: Console routes with no how-to, each with the reason.
NO_TASK: dict[str, str] = {
    "two-step": "Signing in; the admin is already signed in to use the helper.",
    "two-step-enrol": "Signing in; the admin is already signed in to use the helper.",
    "two-step-recovery-codes": "Signing in; recovery codes are never discussed with the helper.",
    "two-step-verify": "Signing in; the admin is already signed in to use the helper.",
    "two-step-recovery": "Signing in; recovery codes are never discussed with the helper.",
    "finance-control-plane": "A data feed of the Finance pages, not a page an admin works on.",
    "technical": "The owner's escape hatch into raw records, outside the guided console.",
    "ai-helper": "The helper's own keys are handled by the admin on the console, never through it.",
    "ai-helper-create": "The helper's own keys are handled by the admin on the console, never through it.",
    "ai-helper-stop": "The helper's own keys are handled by the admin on the console, never through it.",
}

BY_CODE = {task.code: task for task in TASKS}
