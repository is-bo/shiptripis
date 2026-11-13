"""The staff verification inbox (spec 13): one inbox, two tabs, three decisions.

**Two tabs.** *ID* is the identity (KYC) queue; *Tickets* is the ticket-proof
queue, flight and sea. Each tab is the existing queue page under one shared
header, so every link that already points at a queue or a submission (person
pages, the work list, old notifications) still lands where it did.

**One definition of "waiting".** This module is the only place that says
which rows are waiting for a decision. The navigation total, each tab's
counter, the landing tab and the overview's work list all read
`waiting_counts`, and a tab opens its queue filtered to exactly the rows that
were counted, so no two numbers on the console can disagree.

**Three decisions** for both kinds: approve, ask for more, reject. "Ask for
more" stores the existing rejected status (the KYC status enum belongs to the
Go service and is not widened, and a ticket proof gains no status). What sets
it apart is recorded where it is read: the audit entry's ``outcome``, the
notification payload's ``outcome`` and the email, so the person reads "we need
a new upload" and submits again exactly as after a rejection.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.urls import reverse

from apps.kyc.models import KycSubmission
from apps.trips.models import JourneyLegProof

from .models import AdminAuditLog
from .permissions import has_admin_permission

# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

APPROVED = "approved"
RESUBMISSION_REQUESTED = "resubmission_requested"
REJECTED = "rejected"

#: In the order the review screen offers them.
DECISIONS = (APPROVED, RESUBMISSION_REQUESTED, REJECTED)

#: The status each decision stores. Both models share the three values.
DECISION_STATUS = {
    APPROVED: "approved",
    RESUBMISSION_REQUESTED: "rejected",
    REJECTED: "rejected",
}

#: The person is told why, so a decision that is not an approval needs a reason.
REASON_REQUIRED = frozenset({RESUBMISSION_REQUESTED, REJECTED})


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

#: The status a row is in while it waits for a reviewer, for both kinds.
WAITING_STATUS = "pending"


@dataclass(frozen=True, slots=True)
class InboxTab:
    key: str
    label: str
    #: The capability that shows this tab (the queue view's own guard).
    permission: str
    route: str
    model: type


TABS: tuple[InboxTab, ...] = (
    InboxTab("id", "ID", "view_kyc", "admin_console:kyc-queue", KycSubmission),
    InboxTab(
        "tickets",
        "Tickets",
        "view_flight_proofs",
        "admin_console:proof-queue",
        JourneyLegProof,
    ),
)
_TAB_BY_KEY = {tab.key: tab for tab in TABS}


def visible_tabs(user) -> tuple[InboxTab, ...]:
    return tuple(tab for tab in TABS if has_admin_permission(user, tab.permission))


def waiting(tab: InboxTab):
    """The rows of one tab that wait for a decision."""

    return tab.model._default_manager.filter(status=WAITING_STATUS)


def tab_url(tab: InboxTab) -> str:
    """The tab's queue, filtered to exactly the rows its counter counts."""

    return f"{reverse(tab.route)}?status={WAITING_STATUS}"


def waiting_counts(request) -> dict[str, int]:
    """Rows waiting per visible tab, computed at most once per request.

    The shell's navigation, the tab header and the overview all ask on the
    same page, so the counts are kept on the request: one count query per
    visible tab, whatever reads them.
    """

    cached = getattr(request, "_verification_waiting", None)
    if cached is None:
        cached = {tab.key: waiting(tab).count() for tab in visible_tabs(request.user)}
        request._verification_waiting = cached
    return cached


def waiting_total(request) -> int | None:
    """The navigation total, or `None` for a role that sees neither tab."""

    counts = waiting_counts(request)
    return sum(counts.values()) if counts else None


def inbox_header(request, current: str) -> list[dict]:
    """The tab row shared by both queues, in spec order."""

    counts = waiting_counts(request)
    return [
        {
            "key": tab.key,
            "label": tab.label,
            "url": tab_url(tab),
            "count": counts[tab.key],
            "current": tab.key == current,
        }
        for tab in TABS
        if tab.key in counts
    ]


def landing_url(request) -> str | None:
    """The first visible tab with work waiting, otherwise the first visible tab."""

    counts = waiting_counts(request)
    tabs = [_TAB_BY_KEY[key] for key in counts]
    if not tabs:
        return None
    first_with_work = next((tab for tab in tabs if counts[tab.key]), tabs[0])
    return tab_url(first_with_work)


# ---------------------------------------------------------------------------
# Reading a decision back
# ---------------------------------------------------------------------------

#: The audit actions a decision writes, per model. Their names predate the
#: inbox and live in stored audit rows, so they are kept (plan 2.9).
_DECISION_ACTIONS = {
    KycSubmission: ("kyc.approved", "kyc.rejected"),
    JourneyLegProof: ("flight_proof.approved", "flight_proof.rejected"),
}


def resubmission_requested(model, ids) -> frozenset[int]:
    """Which of these rejected rows were "ask for more" rather than "reject".

    One query for a whole page. Each row is decided once (a new upload is a new
    row), so its decision's audit entry is the authority.
    """

    ids = [str(pk) for pk in ids]
    if not ids:
        return frozenset()
    meta = model._meta
    rows = AdminAuditLog.objects.filter(
        target_type=f"{meta.app_label}.{meta.model_name}",
        target_id__in=ids,
        action__in=_DECISION_ACTIONS[model],
        metadata__outcome=RESUBMISSION_REQUESTED,
    ).values_list("target_id", flat=True)
    return frozenset(int(pk) for pk in rows)


def recorded_decision(record) -> str | None:
    """The decision a decided row was given, read from its audit entry.

    `None` for a row still waiting. The row is locked by the caller.
    """

    if record.status == WAITING_STATUS:
        return None
    if record.status != "rejected":
        return record.status
    return (
        RESUBMISSION_REQUESTED
        if resubmission_requested(type(record), (record.pk,))
        else REJECTED
    )


#: How a decided row reads to staff once "ask for more" is known.
RESUBMISSION_LABEL = "New upload requested"


def decision_label(record, requested: frozenset[int]) -> tuple[str, str]:
    """The state chip of one row: ``(tone key, label)``."""

    if record.status == "rejected" and record.pk in requested:
        return RESUBMISSION_REQUESTED, RESUBMISSION_LABEL
    return record.status, record.get_status_display()
