"""Read-only presentation of one manual DZD payout.

This module answers exactly one question for the operator in front of the
screen: *what do I do about this payout right now, and what must be true before
I do it*. It decides nothing financial. Every value it returns is either read
straight from a committed row or derived from rows by pure arithmetic, and the
backend refuses anything the screen is wrong about — H4's gate, not this file,
is what stops a transfer.

Three rules hold everywhere below.

**Nothing sensitive is projected.** The CCP number, the CCP key and the RIP
leave the database only through `reveal_profile`, which is separately
capability-gated and audited. What this module knows about a destination is a
last-four mask and a public reference.

**A state is a sentence, not an enum.** ``sent`` and ``paid`` mean different
things to a Finance operator — one says the operator attests money left the
bank, the other says ShipTrip's own settlement completed — so they never share
a label, a tone or a chip.

**A blocked action is absent or disabled, never merely rejected.** The gate
still runs server-side; this only means the operator finds out before clicking
rather than after.
"""

from __future__ import annotations

from django.conf import settings
from django.utils import timezone

from apps.disputes.models import Dispute
from apps.finance.models import PaymentOrder, PayoutProfileReview
from apps.finance.payout_domain import active_holds
from apps.finance.payout_evidence import CHEQUE_LABELS, RECEIPT_LABELS
from apps.finance.payout_manual_profiles import approved_profile
from .permissions import has_admin_permission
from .console_presenters import age_label, format_minor_amount

#: The operator-facing name for every state this rail can be in, with the
#: sentence that says what it means for the money. Deliberately not
#: `get_status_display()`: that vocabulary is shared with the Stripe rail,
#: where "Sent" means Stripe accepted a transfer rather than "a person went to
#: the bank".
STATE_LABELS: dict[str, tuple[str, str, str]] = {
    "not_eligible": (
        "Protection period",
        "wait",
        "The 48-hour protection window after delivery has not closed yet.",
    ),
    "blocked": (
        "Setup required",
        "attn",
        "Something about the destination or the Deal has to be resolved before "
        "this payout can move.",
    ),
    "frozen": (
        "Frozen by a dispute",
        "bad",
        "An active dispute holds this money. No transfer may be prepared.",
    ),
    "eligible": (
        "Ready for payout",
        "wait",
        "Every gate has passed. An operator may claim this payout and prepare "
        "the transfer instruction.",
    ),
    "scheduled": (
        "Claimed, not started",
        "wait",
        "An operator owns the instruction. Nothing has been sent and the "
        "preparation can still be released.",
    ),
    "processing": (
        "Processing",
        "attn",
        "The instruction is committed. Finance is performing the DZD transfer "
        "outside ShipTrip and owes a receipt.",
    ),
    "sent": (
        "Transfer sent",
        "info",
        "An operator attested the DZD transfer was sent and attached a receipt. "
        "ShipTrip has not recorded settlement yet.",
    ),
    "paid": (
        "Paid",
        "ok",
        "Settlement is recorded against the ledger. The obligation is discharged.",
    ),
    "failed": ("Failed", "bad", "The last attempt did not complete."),
    "cancelled": ("Cancelled", "bad", "This payout will not be settled."),
}

#: A payout event, said in operator language. Anything absent falls back to the
#: raw code with underscores opened out, which keeps a future backend reason
#: readable instead of blank.
EVENT_LABELS: dict[str, tuple[str, str]] = {
    "settlement_award": ("Payout obligation created", "The Deal was funded."),
    "funding_snapshot": (
        "Destination and rate frozen",
        "Currency, payout method version and exchange rate were snapshotted at "
        "funding and cannot change for this payout.",
    ),
    "protection_release": (
        "Protection period closed",
        "48 hours passed after delivery confirmation with no active dispute.",
    ),
    "protection_window_expired": (
        "Protection period closed",
        "The protection window expired.",
    ),
    "settlement_eligibility": (
        "Became eligible",
        "Delivery, protection, disputes and funding all cleared.",
    ),
    "payout_release_check": (
        "Release re-checked",
        "The release gate was re-evaluated.",
    ),
    "manual_instruction_created": (
        "Operator claimed the payout",
        "Source funds were reserved and the instruction was written. Nothing "
        "has been sent.",
    ),
    "manual_preparation_released": (
        "Claim released",
        "The uncommitted preparation was handed back and the reservation freed.",
    ),
    "manual_instruction_committed": (
        "Transfer started",
        "The operator committed to performing the external DZD transfer.",
    ),
    "manual_transfer_sent": (
        "Transfer sent",
        "The operator attested the exact transfer was sent and attached a receipt.",
    ),
    "manual_transfer_settled": (
        "Settlement recorded",
        "The receipt was attested complete and the EUR obligation was "
        "discharged in the ledger.",
    ),
    "hold_opened": ("Hold opened", "Progression is stopped until it is released."),
    "hold_cleared": ("Hold released", "The hold no longer stops this payout."),
    "instruction_amended": (
        "Instruction amended",
        "An audited pre-commit amendment was applied.",
    ),
    "dispute_active_at_protection_expiry": (
        "Dispute froze the payout",
        "A dispute was active when the protection window closed.",
    ),
    "dispute_freeze_with_commitment": (
        "Dispute opened after commitment",
        "The money was already committed externally when the dispute arrived.",
    ),
}

#: A hold's machine reason, said plainly. The raw code stays visible as
#: secondary detail so an engineer and an operator are reading the same row.
HOLD_REASONS: dict[str, str] = {
    "manual_transfer_review": "Opened by Finance for correction or recovery review",
    "operation_under_review": "An external operation's outcome is being reviewed",
    "dispute": "A dispute is holding this money",
    "provider_dispute": "The payment provider opened a dispute on the source charge",
    "refund": "A refund against the source payment",
    "fraud": "A fraud review",
    "compliance": "A compliance review",
    "treasury": "A treasury hold",
}

#: What each block reason actually asks the operator to do.
BLOCK_REASONS: dict[str, tuple[str, str]] = {
    "payout_setup_required": (
        "Traveler payout profile needs review",
        "The frozen destination has no approved crossed-cheque review, so no "
        "transfer may be prepared.",
    ),
    "payout_preference_required": (
        "Traveler has not chosen a payout method",
        "There is no destination to send to.",
    ),
    "fx_snapshot_missing": (
        "No frozen exchange rate",
        "The DZD amount cannot be established without the rate snapshotted at "
        "funding.",
    ),
    "legacy_instruction_required": (
        "Legacy payout, outside this rail",
        "This payout predates versioned instructions and is not settled here.",
    ),
}

#: The review verdict on the frozen profile, as a chip.
REVIEW_STATES: dict[str, tuple[str, str]] = {
    "approved": ("Approved", "ok"),
    "needs_attention": ("Needs attention", "attn"),
    "rejected": ("Rejected", "bad"),
}


def _humanize(code: str) -> str:
    return (code or "").replace("_", " ").capitalize() or "—"


def _person(user) -> str:
    """A safe operator or Traveler name. Never an internal primary key."""

    if user is None:
        return ""
    return user.full_name or user.email or f"Account {user.pk}"


def state_of(payout, *, holds=(), blockers=()) -> dict:
    """The state as an operator experiences it, not as the column stores it.

    A payout under a Finance hold is stored as `eligible` — the hold is a
    separate row, and clearing it returns the payout to exactly where it was.
    That is right for the model and wrong for the chip: a queue that labels a
    held payout "Ready for payout" is telling an operator to go and send money
    that the same page then refuses to send. So a hold, and any other live
    blocker on an otherwise-ready payout, wins the headline.
    """

    label, tone, meaning = STATE_LABELS.get(
        payout.status, (_humanize(payout.status), "mute", "")
    )
    if payout.status in ("eligible", "scheduled", "processing", "sent"):
        if holds:
            return {
                "code": payout.status,
                "label": "On hold",
                "tone": "attn",
                "meaning": "A Finance hold stops this payout. Nothing may be "
                "prepared, committed or recorded until it is released.",
            }
        if blockers:
            return {
                "code": payout.status,
                "label": "Blocked",
                "tone": "attn",
                "meaning": "This payout cannot progress. What is stopping it is "
                "listed below.",
            }
    return {"code": payout.status, "label": label, "tone": tone, "meaning": meaning}


def amounts_of(payout) -> dict:
    """The three numbers that must never be mistaken for each other.

    EUR is the obligation, the rate is frozen evidence, and DZD is the exact
    figure the operator types into a banking screen. The DZD figure is computed
    by the server at funding and merely displayed here — this function does no
    conversion, so there is no client-side arithmetic that could disagree with
    the frozen amount.
    """

    rate = payout.fx_rate_micros or 0
    return {
        "eur_cents": payout.amount_eur_cents,
        "rate_micros": rate,
        # Whole DZD per EUR is the way the rate is actually quoted; the
        # fractional part is shown only when the frozen rate has one.
        "rate_text": (
            f"{rate // 1_000_000:,}"
            if rate and rate % 1_000_000 == 0
            else f"{rate / 1_000_000:,.6f}".rstrip("0").rstrip(".")
            if rate
            else "—"
        ),
        "dzd_minor": payout.payout_amount_minor,
        "dzd_text": format_minor_amount(payout.payout_amount_minor, 0, "DZD"),
        "dzd_number": (
            f"{int(payout.payout_amount_minor):,}"
            if payout.payout_amount_minor is not None
            else "—"
        ),
        "currency": payout.payout_currency,
        "frozen_at": payout.fx_snapshot_at,
        "source": payout.fx_source,
    }


def _latest_review(profile):
    if profile is None:
        return None
    return PayoutProfileReview.objects.filter(profile=profile).order_by("-pk").first()


def destination_of(payout, profile, version) -> dict:
    """The frozen destination, masked, with the version it is bound to.

    The Traveler may have replaced their CCP details since this Deal was
    funded. The payout is bound to the version that existed at funding, and
    nothing on this screen may nudge an operator toward the newer one — so a
    newer revision is reported as context, never as an alternative destination.
    """

    review = _latest_review(profile)
    review_label, review_tone = REVIEW_STATES.get(
        getattr(review, "status", ""), ("Pending review", "wait")
    )
    newer = None
    if profile is not None:
        current = profile.method.current_version
        if current and current.dzd_profile_revision_id != profile.pk:
            newer = {
                "sequence": current.sequence,
                "submitted_at": getattr(
                    current.dzd_profile_revision, "submitted_at", None
                ),
            }
    return {
        "present": profile is not None,
        "ccp_masked": f"•••• {profile.ccp_last_four}" if profile else "—",
        "rip_masked": f"•••• {profile.rip_last_four}" if profile else "—",
        # There is no last-four for the two-digit CCP key: showing any part of
        # it is showing the key. It is masked whole and only ever revealed.
        "key_masked": "••" if profile else "—",
        "profile_reference": str(profile.public_reference) if profile else "",
        "submitted_at": profile.submitted_at if profile else None,
        "version_sequence": version.sequence if version else None,
        "version_reference": str(version.public_reference) if version else "",
        "locked_at": payout.snapshot_at,
        "review": {
            "label": review_label,
            "tone": review_tone,
            "reason": _humanize(getattr(review, "reason_code", "")),
            "reviewer": _person(getattr(review, "reviewer", None)),
            "decided_at": getattr(review, "created_at", None),
            "approved": approved_profile(profile, funded_payout=payout),
        },
        "newer_version": newer,
    }


def proof_of(profile) -> dict:
    """The Traveler's crossed cheque: their evidence of their own account.

    Not the transfer receipt, and never presented as one — the two are
    different documents from different people proving different things, and the
    approved trilingual label is carried verbatim.
    """

    evidence = getattr(profile, "evidence", None) if profile else None
    return {
        "present": bool(evidence and evidence.upload_state == "complete"),
        "reference": str(evidence.public_reference) if evidence else "",
        "mime": getattr(evidence, "mime_type", ""),
        "uploaded_at": getattr(evidence, "created_at", None),
        "labels": CHEQUE_LABELS,
    }


def receipts_of(payout) -> list[dict]:
    """Every transfer receipt ever attached, newest first.

    Revisions append. A correction adds a document; it never replaces the one
    an operator already attested to, which is why this is a list and not a
    field.
    """

    from apps.finance.models import ManualPayoutReceipt

    rows = (
        ManualPayoutReceipt.objects.filter(attempt__payout=payout)
        .select_related("evidence", "operator", "attempt")
        .order_by("-attempt__sequence", "-revision")
    )
    return [
        {
            "revision": row.revision,
            "instruction": row.attempt.sequence,
            "reference": str(row.evidence.public_reference),
            "operator": _person(row.operator),
            "recorded_at": row.recorded_at,
            "completed_attested": row.completed_attested,
            "mime": row.evidence.mime_type,
        }
        for row in rows
    ]


def blockers_of(payout, destination, *, holds) -> list[dict]:
    """Everything that would refuse a transfer, named before it is clicked.

    Order is the order an operator can act on them: what they can fix, then
    what they must wait for, then what belongs to someone else.
    """

    found: list[dict] = []
    if payout.block_reason:
        title, detail = BLOCK_REASONS.get(
            payout.block_reason,
            (_humanize(payout.block_reason), "The backend recorded this block."),
        )
        found.append({"title": title, "detail": detail, "code": payout.block_reason})
    if (
        destination["present"]
        and not destination["review"]["approved"]
        # `payout_setup_required` is the backend's name for exactly this, and it
        # is already in the list above. Saying it twice reads as two problems.
        and payout.block_reason != "payout_setup_required"
    ):
        found.append(
            {
                "title": "Traveler payout profile needs review",
                "detail": "The frozen crossed cheque has no current approval, so "
                "the destination is not usable.",
                "code": "profile_review_required",
            }
        )
    for hold in holds:
        found.append(
            {
                "title": "Finance hold",
                "detail": HOLD_REASONS.get(
                    hold.reason_code, _humanize(hold.reason_code)
                ),
                "code": hold.reason_code,
            }
        )
    deal = payout.deal
    if not deal.delivery_confirmed_at:
        found.append(
            {
                "title": "Delivery is not confirmed",
                "detail": "No verified delivery code has closed this Deal.",
                "code": "delivery_unconfirmed",
            }
        )
    elif deal.protection_ends_at and deal.protection_ends_at > timezone.now():
        found.append(
            {
                "title": "Protection period still active",
                "detail": f"Ends {timezone.localtime(deal.protection_ends_at):%d %b %Y, %H:%M} UTC.",
                "code": "protection_open",
            }
        )
    if deal.disputes.filter(status__in=Dispute.ACTIVE_STATUSES).exists():
        found.append(
            {
                "title": "Active dispute",
                "detail": "A dispute freezes this payout until it is resolved.",
                "code": "dispute_active",
            }
        )
    balance = (
        PaymentOrder.objects.filter(deal_id=payout.deal_id, purpose="deal_balance")
        .exclude(status="cancelled")
        .order_by("-pk")
        .first()
    )
    if balance is None:
        found.append(
            {
                "title": "No live balance obligation",
                "detail": "This Deal has no payment order to draw the payout from.",
                "code": "balance_order_missing",
            }
        )
    elif balance.outstanding_eur_cents or balance.refunded_eur_cents:
        found.append(
            {
                "title": "Funding is not settled",
                "detail": "The Sender's payment is not fully captured, or part of "
                "it is being refunded.",
                "code": "funding_unsettled",
            }
        )
    if not settings.PAYOUT_DZD_EXECUTION_ENABLED:
        found.append(
            {
                "title": "DZD execution is switched off",
                "detail": "Manual DZD execution is globally disabled in this "
                "environment. Nothing on this page can move money.",
                "code": "dzd_execution_disabled",
            }
        )
    return found


STEPS = (
    (
        "Check the Traveler's crossed cheque",
        "Confirm the account evidence matches the attested name and approve the "
        "profile.",
    ),
    (
        "Claim the payout",
        "Preparing the transfer reserves the source funds and makes you its "
        "owner. Nothing is sent.",
    ),
    (
        "Send the exact DZD amount from your bank",
        "ShipTrip does not perform this transfer. Reveal the destination, send "
        "the exact amount shown, and keep the receipt.",
    ),
    (
        "Attach the transfer receipt",
        "Upload proof of the DZD transfer you just made and attest that the "
        "exact amount was sent.",
    ),
    (
        "Confirm settlement",
        "Only when the receipt proves the transfer completed. This discharges "
        "the EUR obligation in the ledger.",
    ),
)


def steps_of(payout, *, reviewed, blocked) -> list[dict]:
    """The five things a Finance operator actually does, in order.

    Written so that no step can be read as "ShipTrip sends the money": step
    three happens in a banking application, outside this system, and every other
    step is ShipTrip recording what a person did.

    Exactly one step is ever *now*. "What do I do next" has one answer or it has
    none, and a list with two highlighted rows answers it worse than a list with
    none — so the position is computed once and everything before it is done,
    the one after it is next, and the rest are later. A blocked payout has no
    current step at all beyond the review it may be waiting on, because there is
    nothing an operator can usefully do until the blocker clears.
    """

    order = ["eligible", "scheduled", "processing", "sent", "paid"]
    rank = order.index(payout.status) if payout.status in order else -1

    if not reviewed:
        current = 0
    elif blocked or rank < 0:
        current = None
    elif rank == 0:
        current = 1
    elif rank in (1, 2):
        # Claimed or committed: the money has not been evidenced yet, so the
        # outstanding act is the bank transfer, whatever else is also pending.
        current = 2
    elif rank == 3:
        current = 4
    else:
        current = None

    # How many leading steps are finished. `processing` shares `scheduled`'s
    # count because committing to send is not the same as having sent.
    done_through = {0: 1, 1: 2, 2: 2, 3: 4, 4: 5}.get(rank, 1 if reviewed else 0)

    steps = []
    for index, (title, detail) in enumerate(STEPS):
        if index == current:
            state = "current"
        elif index < done_through:
            state = "done"
        elif current is not None and index == current + 1:
            state = "next"
        else:
            state = "todo"
        steps.append({"title": title, "detail": detail, "state": state})
    return steps


def timeline_of(payout, profile=None) -> list[dict]:
    """The audit trail, read as an operational history rather than a log.

    Payout events alone start the story too late. What an operator wants to know
    about a destination — when the Traveler submitted it, who reviewed it and on
    what grounds — lives on the profile and its reviews, not on the payout, so
    those rows are merged in and the whole thing is ordered by when it happened.
    Nothing sensitive is carried: a review contributes its verdict, its reason
    code and its reviewer, never any account value.
    """

    entries = []
    if profile is not None:
        entries.append(
            {
                "sequence": 0,
                "title": "Traveler submitted payout details",
                "detail": "The CCP account and the crossed cheque were stored "
                "encrypted as an immutable profile revision.",
                "previous_state": "",
                "new_state": "",
                "actor": _person(profile.method.traveler),
                "at": profile.submitted_at,
                "age": age_label(profile.submitted_at),
                "evidence_reference": "",
                "settled": False,
            }
        )
        for review in profile.reviews.select_related("reviewer").order_by("pk"):
            label, _tone = REVIEW_STATES.get(review.status, ("Reviewed", "mute"))
            entries.append(
                {
                    "sequence": 0,
                    "title": f"Payout profile {label.lower()}",
                    "detail": f"Name check: {_humanize(review.reason_code)}.",
                    "previous_state": "",
                    "new_state": "",
                    "actor": _person(review.reviewer),
                    "at": review.created_at,
                    "age": age_label(review.created_at),
                    "evidence_reference": "",
                    "settled": False,
                }
            )

    rows = payout.events.select_related("actor", "evidence").order_by("-sequence")
    for event in rows:
        title, detail = EVENT_LABELS.get(
            event.reason_code, (_humanize(event.reason_code), "")
        )
        entries.append(
            {
                "sequence": event.sequence,
                "title": title,
                "detail": detail,
                "previous_state": event.previous_state,
                "new_state": event.new_state,
                "actor": _person(event.actor) or "ShipTrip",
                "at": event.occurred_at or event.recorded_at,
                "age": age_label(event.occurred_at or event.recorded_at),
                "evidence_reference": (
                    str(event.evidence.public_reference) if event.evidence_id else ""
                ),
                "settled": event.reason_code == "manual_transfer_settled",
            }
        )
    # Newest first. Two rows written in the same second keep the payout event
    # above the profile row, which is the order they are read in.
    entries.sort(key=lambda entry: (entry["at"], entry["sequence"]), reverse=True)
    return entries


def manual_view(payout, *, user, revealed=None) -> dict:
    """Everything the manual DZD payout screen renders, and nothing else."""

    version = (
        payout.active_instruction_version
        if payout.active_instruction_version_id
        else None
    )
    profile = version.dzd_profile_revision if version else None
    attempt = payout.attempts.select_related("operator").order_by("-sequence").first()
    holds = list(active_holds(payout).select_related("opened_by").order_by("pk"))
    destination = destination_of(payout, profile, version)
    receipts = receipts_of(payout)
    blockers = blockers_of(payout, destination, holds=holds)
    claimed_by_me = bool(attempt and attempt.operator_id == user.pk)
    live_claim = bool(
        attempt and attempt.status in ("prepared", "dispatch_committed", "sent")
    )

    def may(*codes: str) -> bool:
        return all(has_admin_permission(user, code) for code in codes)

    may_execute = may(
        "view_payouts", "retry_payouts", "view_payout_sensitive", "view_payout_evidence"
    )
    unblocked = not blockers

    return {
        "payout": payout,
        "reference": str(payout.public_reference),
        "deal_id": payout.deal_id,
        "traveler": {
            "name": _person(payout.traveler),
            "email": payout.traveler.email,
            "id": payout.traveler_id,
        },
        "state": state_of(payout, holds=holds, blockers=blockers),
        "amounts": amounts_of(payout),
        "destination": destination,
        "proof": proof_of(profile),
        "receipt_labels": RECEIPT_LABELS,
        "receipts": receipts,
        "blockers": blockers,
        "holds": [
            {
                "id": hold.pk,
                "kind": hold.kind,
                "reason_code": hold.reason_code,
                "reason": HOLD_REASONS.get(
                    hold.reason_code, _humanize(hold.reason_code)
                ),
                "generation": hold.generation,
                "opened_at": hold.opened_at,
                "opened_by": _person(hold.opened_by),
                "mine": hold.opened_by_id == user.pk,
            }
            for hold in holds
        ],
        "claim": {
            "claimed": live_claim,
            "mine": live_claim and claimed_by_me,
            "operator": _person(getattr(attempt, "operator", None))
            if live_claim
            else "",
            "instruction": attempt.sequence if attempt else None,
            "committed_at": attempt.committed_at if attempt else None,
            "attempt_state": attempt.status if attempt else "",
        },
        "steps": steps_of(
            payout,
            reviewed=destination["review"]["approved"],
            blocked=bool(blockers),
        ),
        "timeline": timeline_of(payout, profile),
        "milestones": {
            "eligible_at": payout.eligible_at,
            "scheduled_for": payout.scheduled_for,
            "committed_at": attempt.committed_at if attempt else None,
            "sent_at": payout.sent_at,
            "paid_at": payout.paid_at,
        },
        "execution_enabled": settings.PAYOUT_DZD_EXECUTION_ENABLED,
        "state_version": payout.state_version,
        "revealed": revealed,
        # Each control is offered only where the backend would accept it. The
        # server re-checks every one of these; this only keeps the operator from
        # discovering a refusal by clicking.
        "may": {
            "reveal": may("view_payout_sensitive", "view_payouts")
            and destination["present"],
            "evidence": may("view_payout_sensitive", "view_payout_evidence"),
            "review": may(
                "review_payout_profiles",
                "view_payout_sensitive",
                "view_payout_evidence",
            )
            and destination["present"]
            and not destination["review"]["approved"],
            "prepare": may_execute
            and unblocked
            and payout.status == "eligible"
            and not live_claim,
            "begin": may_execute
            and unblocked
            and payout.status == "scheduled"
            and claimed_by_me,
            "release": may_execute
            and payout.status == "scheduled"
            and claimed_by_me
            and not (attempt and attempt.committed_at),
            "receipt": may_execute
            and unblocked
            and payout.status in ("processing", "sent")
            and claimed_by_me,
            "settle": may_execute
            and unblocked
            and payout.status in ("processing", "sent")
            and claimed_by_me,
            "hold": may("manage_payout_holds"),
        },
    }
