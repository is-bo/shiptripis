"""Opening a dispute, feeding it evidence, and settling the money at the end.

A dispute is the only thing that can stop a payout, and its resolution is the
only thing that can move money after a delivery has been confirmed. Four rules
shape everything below.

**The Deal is locked first, always.** Every writer here enters through
`lock_deal_lifecycle`, which takes the Deal row before it takes disputes and the
payout. Taking a dispute row and then reaching for its Deal is precisely the
inversion Phase 3B removed from the legacy handover path, and the canonical
order is what leaves the protection-expiry/dispute race with no losing
interleaving: whichever transaction arrives second blocks on the Deal row and
then reads the winner's committed state.

**The bundle is captured before anybody can tidy anything up.**
`build_evidence_bundle` runs inside the opening transaction and stores
*references* -- ids, amounts, statuses and instants -- to everything a later
investigation needs. It carries no handover code in any form, no recipient
contact details and no exact private address, because a secret written into a
bundle is a secret in every admin export of that dispute forever.

**Exactly one economic resolution may win.** Two administrators resolving the
same dispute at the same moment serialize on the Deal and then on the Dispute
row; the loser re-reads `resolved` and returns that row unchanged rather than
raising a second refund. `apps.finance.settlement` owns the money -- nothing
here writes a `Payout`, and nothing here writes a lifecycle field on a `Deal`
except through `apps.deals.lifecycle`.

**Evidence files are never handed out as bucket paths.** Uploads land in a
private bucket and leave it only as a short-lived signed URL issued after an
authorization check, so revoking access is a matter of not signing rather than
of hoping a URL was never copied.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Max, Min, Q
from django.utils import timezone

from apps.core.financial_locks import (
    LockedLifecycleAggregate,
    lock_deal_lifecycle,
    models_q_deal_or_deposit,
)
from apps.core.phase4_policy import DisputePolicy, phase4_policy
from apps.core.storage import (
    ext_for_content_type,
    image_bytes_match_extension,
    make_key,
    put_object,
    s3_client,
)
from apps.deals import lifecycle
from apps.deals.models import Deal, DealEvent, DealTermsSnapshot
from apps.finance.models import (
    PaymentAttempt,
    PaymentOrder,
    PaymentRefund,
    Payout,
)
from apps.finance.payout_release import freeze_payout
from apps.finance.settlement import (
    DealMoney,
    SettlementPlan,
    apply_settlement,
    plan_settlement,
    read_deal_money,
)

from .models import Dispute, DisputeEvent, DisputeEvidence

logger = logging.getLogger(__name__)


class DisputeError(RuntimeError):
    """A dispute operation was refused. Carries a stable machine code."""

    code = "dispute_error"

    def __init__(self, message: str, *, code: str | None = None, **details):
        super().__init__(message)
        if code:
            self.code = code
        self._details = details

    def details(self) -> dict:
        return dict(self._details)


class NotAuthorized(DisputeError):
    code = "not_authorized"


#: The bundle's shape is versioned so a resolution reviewed in two years can be
#: read with the rules it was captured under, rather than with today's.
BUNDLE_VERSION = 1

#: Statuses an administrator may move a live dispute between. `resolved` and
#: `closed` are terminal and are reached through their own operations.
ADMIN_SETTABLE_STATUSES = (
    Dispute.Status.OPEN,
    Dispute.Status.AWAITING_EVIDENCE,
    Dispute.Status.UNDER_REVIEW,
)

#: Video containers this platform accepts, and the extension each one is stored
#: under. `apps.core.storage` owns image verification through Pillow; video has
#: no equivalent decoder here, so the container signature is checked below.
_VIDEO_EXT_BY_CONTENT_TYPE = {
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
    "video/x-matroska": "mkv",
}


# --- small helpers ------------------------------------------------------------


def _instant(value: datetime | None) -> str | None:
    """JSON-safe instant. The bundle is a `JSONField`, not a Django encoder."""

    return value.isoformat() if value is not None else None


def _decimal(value) -> str | None:
    """Decimals travel as strings so no float ever rounds a weight or a price."""

    return str(value) if value is not None else None


def _dispute_event(
    dispute: Dispute,
    kind: str,
    payload: dict | None = None,
    *,
    actor_id: int | None = None,
) -> DisputeEvent:
    """Append one immutable row to the dispute's own timeline.

    Same payload rule as the Deal timeline: ids, amounts, statuses and instants.
    Free-text notes written by staff are stored here for the audit record and
    are projected away from a party by `apps.disputes.serializers`.
    """

    return DisputeEvent.objects.create(
        dispute=dispute, kind=kind, actor_id=actor_id, payload=payload or {}
    )


def _party_role(deal: Deal, actor_id: int) -> str:
    if actor_id == deal.sender_id:
        return Dispute.OpenedByRole.SENDER
    if actor_id == deal.traveler_id:
        return Dispute.OpenedByRole.TRAVELER
    return ""


def visible_disputes_for(user_id: int):
    """Every dispute on a Deal this user is a party to.

    Membership of the Deal is the whole rule. A dispute is visible to both
    parties even when the other one opened it, because a frozen payout and a
    resolution that moves money are facts about both of them.
    """

    return (
        Dispute.objects.filter(
            Q(deal__sender_id=user_id) | Q(deal__traveler_id=user_id)
        )
        .select_related("deal")
        .prefetch_related("evidence", "events")
    )


# --- opening ------------------------------------------------------------------


def _assert_dispute_window_open(deal: Deal, *, at: datetime) -> None:
    """Refuse a party's dispute outside the two windows that allow one.

    A dispute is available from the moment the parcel leaves the sender's hands
    -- after pickup there is no unilateral cancellation, and "something went
    wrong" has to become a reviewable record rather than a refund somebody
    granted themselves -- and it stays available until the protection deadline
    the Deal stored at delivery confirmation. Those are the same 48 hours the
    payout gate waits for, read from the same column, so the two cannot
    disagree about whether the door is still open.
    """

    if deal.status in lifecycle.IN_CARRIAGE_STATUSES:
        return
    if deal.delivery_confirmed_at is not None:
        if deal.protection_ends_at is None:
            # No stored deadline means the payout gate will not release either
            # (`evaluate_payout_release` answers `protection_not_armed`), so
            # there is no money racing this dispute and no reason to refuse it.
            return
        if at >= deal.protection_ends_at:
            raise DisputeError(
                "The payment protection window for this delivery has closed.",
                code="dispute_window_closed",
                protection_ends_at=_instant(deal.protection_ends_at),
                deal_status=deal.status,
            )
        return
    raise DisputeError(
        "This parcel has not been picked up yet. Cancel the delivery instead.",
        code="dispute_not_available",
        deal_status=deal.status,
    )


def _assert_already_resolved(aggregate: LockedLifecycleAggregate) -> None:
    """Refuse a party's second dispute once one has already been decided.

    A resolved dispute has moved money: refunds have been raised and the payout
    has been released, cancelled or settled. Letting a party open a second one
    inside the same protection window is re-litigation, and it is the door
    through which the same euro gets paid to two people -- the first resolution
    pays the traveler, the second refunds the sender in full, and each half
    looks correct on its own.

    `plan_settlement` now bounds every refund by what the platform still holds,
    so the money cannot actually leave twice. This is the second wall, and the
    better error: a party is told to contact support rather than being handed a
    dispute that will fail to do what they expect.

    An administrator is deliberately not blocked. They may need the record, and
    the settlement bounds hold for them too.
    """

    for row in aggregate.disputes:
        if row.status == Dispute.Status.RESOLVED:
            raise DisputeError(
                "This delivery has already had a dispute resolved. Contact "
                "support if something is still wrong.",
                code="dispute_already_resolved",
                dispute_id=row.pk,
                resolution=row.resolution,
            )


def open_dispute(
    *,
    deal_id: int,
    actor_id: int,
    category: str,
    reason_text: str,
    as_admin: bool = False,
) -> Dispute:
    """Open a dispute, freeze the payout and snapshot the evidence, atomically.

    The Deal aggregate is taken first and everything else follows inside it, so
    a dispute and a protection expiry racing for the same money always resolve
    in a defined order.

    Idempotent by design. A retrying client that already has an active dispute
    gets that row back untouched: no second freeze, no second bundle and no
    duplicate timeline entries. The idempotent answer is given *before* the
    window is checked, because a dispute opened in carriage moves the Deal to
    `disputed` -- a status which is in neither window -- and a client retrying
    its own successful call must not be told it is too late.

    `as_admin` is passed only by the operations endpoint. It skips the party
    check and the window, which is the one way a dispute can be opened after the
    protection window has closed and, therefore, the one way `payout_frozen` can
    come back false with `payout_already_settled` true instead.
    """

    at = timezone.now()
    category = (category or "").strip()
    if category not in Dispute.Category.values:
        raise DisputeError(
            "That is not a dispute category.",
            code="dispute_category_invalid",
        )
    reason_text = (reason_text or "").strip()
    if not reason_text:
        raise DisputeError(
            "Describe what went wrong so the dispute can be reviewed.",
            code="dispute_reason_required",
        )

    with transaction.atomic():
        aggregate = lock_deal_lifecycle(deal_id)
        deal = aggregate.deal

        role = (
            Dispute.OpenedByRole.ADMIN if as_admin else _party_role(deal, actor_id)
        )
        if not role:
            raise NotAuthorized(
                "Only a party to this delivery can open a dispute on it."
            )

        existing = aggregate.active_dispute()
        if existing is not None:
            return existing

        if not as_admin:
            _assert_already_resolved(aggregate)
            _assert_dispute_window_open(deal, at=at)

        previous_status = deal.status
        dispute = Dispute.objects.create(
            deal=deal,
            opened_by_id=actor_id,
            opened_by_role=role,
            status=Dispute.Status.OPEN,
            category=category,
            reason_text=reason_text[:4_000],
            evidence_bundle=build_evidence_bundle(aggregate),
            # Copied, not referenced: the record still explains which deadline
            # it was opened against once the Deal has been closed out.
            protection_ends_at=deal.protection_ends_at,
        )
        _dispute_event(
            dispute,
            DisputeEvent.Kind.OPENED,
            {
                "category": category,
                "opened_by_role": role,
                "deal_status": previous_status,
                "protection_ends_at": _instant(deal.protection_ends_at),
            },
            actor_id=actor_id,
        )
        _dispute_event(
            dispute,
            DisputeEvent.Kind.BUNDLE_CAPTURED,
            {
                "bundle_version": BUNDLE_VERSION,
                "captured_at": dispute.evidence_bundle.get("captured_at"),
                "sections": sorted(dispute.evidence_bundle),
            },
        )

        payout_status = freeze_payout(
            aggregate, reason="dispute_opened", dispute_id=dispute.pk
        )
        changed_fields: list[str] = []
        if payout_status == Payout.Status.FROZEN:
            dispute.payout_frozen = True
            changed_fields.append("payout_frozen")
        elif payout_status == Payout.Status.PAID:
            # Only reachable for an admin-opened dispute: a party's window
            # closes before the protection window does, and no payout can be
            # released until after that. The money has left, so the record says
            # so instead of pretending it is still here to be split.
            dispute.payout_already_settled = True
            changed_fields.append("payout_already_settled")
        if changed_fields:
            dispute.save(update_fields=[*changed_fields, "updated_at"])
            _dispute_event(
                dispute,
                DisputeEvent.Kind.PAYOUT_FROZEN,
                {"payout_status": payout_status},
            )

        lifecycle.apply_disputed(
            aggregate, dispute_id=dispute.pk, actor_id=actor_id
        )
        lifecycle.record_event(
            deal,
            DealEvent.Kind.DISPUTE_OPENED,
            {
                "dispute_id": dispute.pk,
                "reason": category,
                "actor_role": role,
                "previous_status": previous_status,
            },
            actor_id=actor_id,
        )
        _cancel_protection_ending_reminders(aggregate)
        _notify_opened(aggregate, dispute)
    return dispute


def _cancel_protection_ending_reminders(aggregate: LockedLifecycleAggregate) -> None:
    """A dispute supersedes the still-open protection-window reminder."""

    from apps.notifications.outbox import cancel_message

    deal = aggregate.deal
    for user_id in (deal.sender_id, deal.traveler_id):
        cancel_message(
            key=f"protection_ending:{deal.pk}:{user_id}:v1",
            reason="superseded by an open dispute",
        )


def _notify_opened(aggregate: LockedLifecycleAggregate, dispute: Dispute) -> None:
    from apps.notifications.models import OutboundMessage
    from apps.notifications.outbox import enqueue_message

    deal = aggregate.deal
    context = {
        "deal_reference": f"ST-{deal.pk}",
        "dispute_reference": f"DSP-{dispute.pk}",
    }
    for user_id, email in (
        (deal.sender_id, getattr(deal.sender, "email", "")),
        (deal.traveler_id, getattr(deal.traveler, "email", "")),
    ):
        if not email:
            continue
        enqueue_message(
            kind=OutboundMessage.Kind.DISPUTE_OPENED,
            key=f"dispute_opened:{dispute.pk}:{user_id}",
            to_email=email,
            recipient_user_id=user_id,
            deal_id=deal.pk,
            context=context,
        )


# --- the evidence bundle ------------------------------------------------------


def build_evidence_bundle(aggregate: LockedLifecycleAggregate) -> dict:
    """An immutable snapshot of references, taken at the instant of opening.

    Not a copy of the platform's state -- an index into it. Everything here is
    an id, an amount, a status or an instant, captured while the aggregate is
    held so that a party cannot edit, withdraw or rotate anything between the
    dispute being opened and an administrator reading it.

    **What this must never contain, and why.** No `code_hash`, no `sealed_code`
    and no plaintext handover code; no recipient name, email or phone; no exact
    private location label or precise coordinate. A bundle is copied into every
    admin export, support ticket and audit extract that ever touches this
    dispute, so a secret written here is a secret everywhere, permanently. The
    handover, recipient and location blocks below are built by naming the fields
    they include rather than by excluding the fields they must not, which is the
    same allowlist discipline `apps.deals.timeline` applies to the Deal
    timeline.
    """

    deal = aggregate.deal
    request_row = aggregate.request_graph.request
    return {
        "bundle_version": BUNDLE_VERSION,
        "captured_at": _instant(timezone.now()),
        "deal": _deal_block(deal),
        "terms": _terms_block(deal),
        "timeline": _timeline_block(deal),
        "offers": _offers_block(aggregate),
        "payments": _payments_block(deal, request_row),
        "handover": _handover_block(deal),
        "chat": _chat_block(deal),
        "journey": _journey_block(aggregate),
        "delivery_request": _delivery_request_block(request_row),
        "no_show": _no_show_block(deal),
    }


def _deal_block(deal: Deal) -> dict:
    """The Deal's identity and its whole lifecycle clock."""

    return {
        "id": deal.pk,
        "status_at_open": deal.status,
        "sender_id": deal.sender_id,
        "traveler_id": deal.traveler_id,
        "match_id": deal.match_id,
        "accepted_offer_id": deal.accepted_offer_id,
        "delivery_request_id": deal.delivery_request_id,
        "journey_id": deal.journey_id,
        "is_legacy": deal.is_legacy,
        "lifecycle_policy": dict(deal.lifecycle_policy or {}),
        "created_at": _instant(deal.created_at),
        "funded_at": _instant(deal.funded_at),
        "agreed_pickup_at": _instant(deal.agreed_pickup_at),
        "pickup_confirmed_at": _instant(deal.pickup_confirmed_at),
        "delivery_code_available_at": _instant(deal.delivery_code_available_at),
        "delivery_code_released_at": _instant(deal.delivery_code_released_at),
        "delivery_confirmed_at": _instant(deal.delivery_confirmed_at),
        "protection_ends_at": _instant(deal.protection_ends_at),
        "rating_window_ends_at": _instant(deal.rating_window_ends_at),
        "completed_at": _instant(deal.completed_at),
        "cancelled_at": _instant(deal.cancelled_at),
        "cancelled_by_id": deal.cancelled_by_id,
        "cancellation_reason": deal.cancellation_reason,
    }


def _terms_block(deal: Deal) -> dict | None:
    """The frozen economics. What each side was promised, in EUR cents."""

    terms = DealTermsSnapshot.objects.filter(deal_id=deal.pk).first()
    if terms is None:
        return None
    return {
        "id": terms.pk,
        "currency": terms.currency,
        "traveler_reward_minor": int(terms.traveler_reward_minor),
        "commission_rate_bps": int(terms.commission_rate_bps),
        "platform_fee_minor": int(terms.platform_fee_minor),
        "sender_total_minor": int(terms.sender_total_minor),
        "pricing_version": terms.pricing_version,
        "business_settings_version_id": terms.business_settings_version_id,
        "created_at": _instant(terms.created_at),
    }


def _timeline_block(deal: Deal) -> list[dict]:
    """The Deal timeline, stored payloads and all.

    Payloads are safe to copy verbatim because `apps.deals.lifecycle.record_event`
    forbids a secret from ever entering one: they carry ids, amounts and statuses
    by construction. This is the platform-side record, so it is captured
    unnarrowed; per-viewer narrowing is `apps.deals.timeline`'s job.
    """

    return [
        {
            "id": event.pk,
            "kind": event.kind,
            "actor_id": event.actor_id,
            "payload": dict(event.payload or {}),
            "created_at": _instant(event.created_at),
        }
        for event in DealEvent.objects.filter(deal_id=deal.pk).order_by(
            "created_at", "pk"
        )
    ]


def _offers_block(aggregate: LockedLifecycleAggregate) -> list[dict]:
    """The negotiation that produced the agreed price, in order.

    Offer notes are left out: they are free text a party wrote to the other
    party, and the amounts are what a resolution turns on.
    """

    return [
        {
            "id": offer.pk,
            "match_id": offer.match_id,
            "parent_offer_id": offer.parent_offer_id,
            "status": offer.status,
            "proposed_by": offer.proposed_by,
            "proposer_id": offer.proposer_id,
            "currency": offer.currency,
            "economics_version": offer.economics_version,
            "traveler_reward_minor": offer.traveler_reward_minor,
            "commission_rate_bps": offer.commission_rate_bps,
            "platform_fee_minor": offer.platform_fee_minor,
            "sender_total_minor": offer.sender_total_minor,
            "created_at": _instant(offer.created_at),
            "responded_at": _instant(offer.responded_at),
        }
        for offer in sorted(aggregate.request_graph.offers, key=lambda row: row.pk)
    ]


def _payments_block(deal: Deal, request_row) -> dict:
    """Every obligation, capture, refund and payout that touched this Deal.

    Both orders are captured, not just the Deal balance: a funded Deal's money
    can also sit in the posting deposit whose cash was credited into it, and a
    resolution that ignored the deposit would be reviewing half the money.
    """

    orders = list(
        PaymentOrder.objects.filter(
            models_q_deal_or_deposit(deal.pk, request_row.pk)
        ).order_by("pk")
    )
    order_ids = [row.pk for row in orders]
    payout = Payout.objects.filter(deal_id=deal.pk).first()
    return {
        "orders": [
            {
                "id": order.pk,
                "purpose": order.purpose,
                "status": order.status,
                "currency": order.currency,
                "amount_eur_cents": int(order.amount_eur_cents),
                "credited_eur_cents": int(order.credited_eur_cents),
                "paid_eur_cents": int(order.paid_eur_cents),
                "refunded_eur_cents": int(order.refunded_eur_cents),
                "credit_source_id": order.credit_source_id,
                "paid_at": _instant(order.paid_at),
                "cancelled_at": _instant(order.cancelled_at),
                "created_at": _instant(order.created_at),
            }
            for order in orders
        ],
        "attempts": [
            {
                "id": attempt.pk,
                "order_id": attempt.order_id,
                "provider": attempt.provider,
                "status": attempt.status,
                "amount_eur_cents": int(attempt.amount_eur_cents),
                "payment_currency": attempt.payment_currency,
                "provider_amount_minor": int(attempt.provider_amount_minor),
                "fx_rate_micros": attempt.fx_rate_micros,
                "is_unapplied": attempt.is_unapplied,
                "succeeded_at": _instant(attempt.succeeded_at),
                "created_at": _instant(attempt.created_at),
            }
            for attempt in PaymentAttempt.objects.filter(
                order_id__in=order_ids
            ).order_by("pk")
        ],
        "refunds": [
            {
                "id": refund.pk,
                "order_id": refund.order_id,
                "attempt_id": refund.attempt_id,
                "amount_eur_cents": int(refund.amount_eur_cents),
                "reason": refund.reason,
                "status": refund.status,
                "succeeded_at": _instant(refund.succeeded_at),
                "created_at": _instant(refund.created_at),
            }
            for refund in PaymentRefund.objects.filter(
                order_id__in=order_ids
            ).order_by("pk")
        ],
        "payout": (
            None
            if payout is None
            else {
                "id": payout.pk,
                "status": payout.status,
                "method": payout.method,
                "amount_eur_cents": int(payout.amount_eur_cents),
                "eligible_at": _instant(payout.eligible_at),
                "scheduled_for": _instant(payout.scheduled_for),
                "paid_at": _instant(payout.paid_at),
                "created_at": _instant(payout.created_at),
            }
        ),
    }


def _handover_block(deal: Deal) -> dict:
    """Which codes existed, what happened to them, and every submission made.

    Field by field, deliberately. `code_hash` and `sealed_code` are the two
    columns that must never leave `handover_deal_code`, and the way to guarantee
    that is to name what goes in rather than to remember what to leave out.
    Attempts carry a result and never the value submitted, exactly as the
    `HandoverAttempt` table itself does.
    """

    from apps.handover.models import DealHandoverCode, HandoverAttempt

    return {
        "codes": [
            {
                "id": code.pk,
                "kind": code.kind,
                "status": code.status,
                "rotation": code.rotation,
                "code_length": code.code_length,
                "issued_to_id": code.issued_to_id,
                "failed_attempts": code.failed_attempts,
                "lockout_count": code.lockout_count,
                "locked_until": _instant(code.locked_until),
                "available_at": _instant(code.available_at),
                "released_at": _instant(code.released_at),
                "used_at": _instant(code.used_at),
                "used_by_id": code.used_by_id,
                "superseded_at": _instant(code.superseded_at),
                "created_at": _instant(code.created_at),
            }
            for code in DealHandoverCode.objects.filter(deal_id=deal.pk).order_by(
                "pk"
            )
        ],
        "attempts": [
            {
                "id": attempt.pk,
                "code_id": attempt.code_id,
                "kind": attempt.kind,
                "actor_id": attempt.actor_id,
                "result": attempt.result,
                "created_at": _instant(attempt.created_at),
            }
            for attempt in HandoverAttempt.objects.filter(
                deal_id=deal.pk
            ).order_by("pk")
        ],
    }


def _chat_block(deal: Deal) -> dict:
    """A reference to the conversation, not a copy of it.

    `apps.chat` has no thread table: a thread *is* a Match, read in `created_at`
    order, and the model says so. So the reference is the match plus enough
    shape to establish that the conversation existed and when it ran. Message
    bodies stay in `chat_message`, which is the authoritative record; copying
    two people's private conversation into a bundle would put it into every
    export of this dispute forever, for a benefit an administrator already has
    by reading the thread itself.
    """

    from apps.chat.models import ChatMessage

    stats = ChatMessage.objects.filter(match_id=deal.match_id).aggregate(
        count=Count("pk"), first_at=Min("created_at"), last_at=Max("created_at")
    )
    return {
        "thread": "match",
        "match_id": deal.match_id,
        "message_count": int(stats["count"] or 0),
        "first_message_at": _instant(stats["first_at"]),
        "last_message_at": _instant(stats["last_at"]),
    }


def _journey_block(aggregate: LockedLifecycleAggregate) -> dict:
    """The journey, the legs this parcel was allocated to, and their proofs."""

    from apps.trips.models import JourneyLegProof

    deal = aggregate.deal
    journey = aggregate.deal_aggregate.journey
    match = next(
        (row for row in aggregate.request_graph.matches if row.pk == deal.match_id),
        None,
    )
    leg_ids = sorted(
        {row.journey_leg_id for row in aggregate.deal_aggregate.allocations}
        | {
            leg_id
            for leg_id in (
                getattr(match, "start_leg_id", None),
                getattr(match, "end_leg_id", None),
            )
            if leg_id is not None
        }
    )
    return {
        "id": journey.pk,
        "status": journey.status,
        "matched_leg_ids": leg_ids,
        "start_leg_id": getattr(match, "start_leg_id", None),
        "end_leg_id": getattr(match, "end_leg_id", None),
        "allocations": [
            {
                "id": row.pk,
                "journey_leg_id": row.journey_leg_id,
                "allocated_weight_kg": _decimal(row.allocated_weight_kg),
                "status": row.status,
                "released_at": _instant(row.released_at),
                "release_reason": row.release_reason,
            }
            for row in aggregate.deal_aggregate.allocations
        ],
        "leg_proofs": [
            {
                "id": proof.pk,
                "leg_id": proof.leg_id,
                "kind": proof.kind,
                "status": proof.status,
                "reviewer_id": proof.reviewer_id,
                "reviewed_at": _instant(proof.reviewed_at),
                "created_at": _instant(proof.created_at),
            }
            for proof in JourneyLegProof.objects.filter(
                leg_id__in=leg_ids
            ).order_by("pk")
        ],
    }


def _location_reference(location) -> dict | None:
    """A location as the platform may quote it, at public precision only.

    `normalized_label`, `private_label` and the exact coordinates may hold a
    doorstep address. Those never enter a bundle; the public label, the city and
    the country are what an investigator needs to know where a delivery was
    meant to run between.
    """

    if location is None:
        return None
    return {
        "id": location.pk,
        "kind": location.kind,
        "public_label": location.public_label,
        "city": location.city,
        "region": location.region,
        "country_code": location.country_code,
    }


def _delivery_request_block(request_row) -> dict:
    """What was posted: the parcel, its declared value and its stated windows."""

    parcel = request_row.parcelrequest_ptr
    return {
        "id": request_row.pk,
        "status": parcel.status,
        "schema_version": request_row.schema_version,
        "sender_id": parcel.sender_id,
        "title": request_row.title,
        "category": request_row.category or parcel.item_type,
        "description": parcel.description,
        "handling_notes": request_row.handling_notes,
        "fragile": request_row.fragile,
        "actual_weight_kg": _decimal(request_row.actual_weight_kg),
        "length_cm": _decimal(request_row.length_cm),
        "width_cm": _decimal(request_row.width_cm),
        "height_cm": _decimal(request_row.height_cm),
        "declared_value_eur_cents": request_row.declared_value_eur_cents,
        "sender_proposed_reward_eur_cents": request_row.traveler_reward_eur_cents,
        "ready_window_start": _instant(request_row.ready_window_start),
        "ready_window_end": _instant(request_row.ready_window_end),
        "deadline_at": _instant(parcel.deadline_at),
        "pickup_location": _location_reference(request_row.pickup_location),
        "delivery_location": _location_reference(request_row.delivery_location),
        "created_at": _instant(parcel.created_at),
    }


def _no_show_block(deal: Deal) -> dict:
    """The admin-reviewed no-show decision, if one was ever recorded."""

    return {
        "party": deal.no_show_party,
        "recorded_at": _instant(deal.no_show_recorded_at),
        "recorded_by_id": deal.no_show_recorded_by_id,
        "note": deal.no_show_note,
    }


# --- evidence -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _StoredFile:
    bucket: str
    key: str
    content_type: str
    size_bytes: int
    sha256: str


def _assert_evidence_budget(dispute: Dispute, policy: DisputePolicy) -> None:
    count = DisputeEvidence.objects.filter(dispute_id=dispute.pk).count()
    if count >= policy.max_evidence_items:
        raise DisputeError(
            "This dispute already holds the maximum number of evidence items.",
            code="dispute_evidence_limit_reached",
            max_evidence_items=policy.max_evidence_items,
        )


def _video_bytes_match_extension(body: bytes, expected_ext: str) -> bool:
    """Verify a declared video container against the bytes that actually arrived.

    An ISO base-media file -- mp4 and QuickTime's own variant alike -- opens
    with an `ftyp` box, so the four bytes at offset 4 are the box type. Matroska
    and WebM share the EBML magic. The brand inside `ftyp` is deliberately not
    pinned: phones emit a long tail of brands and refusing an unlisted one would
    reject a party's genuine evidence, while the box itself is what separates a
    video from a renamed executable.
    """

    if expected_ext in ("mp4", "mov"):
        return len(body) >= 12 and body[4:8] == b"ftyp"
    if expected_ext in ("webm", "mkv"):
        return body[:4] == b"\x1aE\xdf\xa3"
    return False


def _store_evidence_file(
    *, dispute: Dispute, kind: str, upload, policy: DisputePolicy
) -> _StoredFile:
    """Validate an upload against policy *and* against its own bytes, then store.

    The declared content type is a claim made by the client, so it is checked
    twice: once against what an administrator has allowed, and once against what
    the file actually is. Passing the first and failing the second is exactly
    what an attacker uploading an executable named `evidence.jpg` looks like.

    The object lands in a private bucket and its key never leaves this process
    boundary; `evidence_download_url` is the only way back to the bytes.
    """

    if upload is None:
        raise DisputeError(
            "Attach a file for photo or video evidence.",
            code="dispute_evidence_file_required",
        )
    content_type = (upload.content_type or "").split(";")[0].strip().lower()
    if content_type not in policy.allowed_evidence_content_types:
        raise DisputeError(
            "That file type is not accepted as dispute evidence.",
            code="dispute_evidence_type_not_allowed",
            allowed_content_types=list(policy.allowed_evidence_content_types),
        )
    if int(getattr(upload, "size", 0) or 0) > policy.max_evidence_bytes:
        raise DisputeError(
            "That file is larger than the evidence size limit.",
            code="dispute_evidence_too_large",
            max_evidence_bytes=policy.max_evidence_bytes,
        )

    is_photo = kind == DisputeEvidence.Kind.PHOTO
    ext = (
        ext_for_content_type(content_type)
        if is_photo
        else _VIDEO_EXT_BY_CONTENT_TYPE.get(content_type)
    )
    if ext is None:
        raise DisputeError(
            "That file type does not match the kind of evidence declared.",
            code="dispute_evidence_type_mismatch",
        )
    body = upload.read()
    # `size` is what the client said; `len(body)` is what arrived. The limit is
    # applied to both so a lying multipart header cannot smuggle a large file.
    if len(body) > policy.max_evidence_bytes:
        raise DisputeError(
            "That file is larger than the evidence size limit.",
            code="dispute_evidence_too_large",
            max_evidence_bytes=policy.max_evidence_bytes,
        )
    matches = (
        image_bytes_match_extension(body, ext)
        if is_photo
        else _video_bytes_match_extension(body, ext)
    )
    if not body or not matches:
        raise DisputeError(
            "That file is not a valid image or video of the declared type.",
            code="dispute_evidence_content_mismatch",
        )

    bucket = getattr(settings, "S3_BUCKET_DISPUTE", settings.S3_BUCKET_KYC)
    key = make_key(f"disputes/{dispute.pk}", ext)
    put_object(bucket=bucket, key=key, body=body, content_type=content_type)
    return _StoredFile(
        bucket=bucket,
        key=key,
        content_type=content_type,
        size_bytes=len(body),
        sha256=hashlib.sha256(body).hexdigest(),
    )


def add_evidence(
    *,
    dispute_id: int,
    actor_id: int,
    kind: str,
    text: str = "",
    upload=None,
    is_staff: bool = False,
) -> DisputeEvidence:
    """Attach one piece of evidence to a live dispute.

    Open to both parties -- a traveler defending themselves needs the same
    surface as a sender complaining -- and to a staff user holding
    `disputes.view_dispute_evidence`, who may file what a party sent through
    support. Evidence is append-only, so nothing here edits or replaces a row.

    No Deal lock is taken. Evidence moves no money, and holding the aggregate
    across an object-store upload would block every other writer on this Deal
    for the length of a phone's video upload. The item budget is therefore
    checked before and after the upload rather than under a lock: the worst a
    lost race can produce is one item over the cap, and the alternative costs a
    real invariant to defend a policy limit.
    """

    dispute = Dispute.objects.select_related("deal").get(pk=dispute_id)
    deal = dispute.deal
    if not is_staff and actor_id not in (deal.sender_id, deal.traveler_id):
        raise NotAuthorized(
            "Only a party to this delivery can add evidence to its dispute."
        )
    if dispute.status not in Dispute.ACTIVE_STATUSES:
        raise DisputeError(
            "This dispute is no longer accepting evidence.",
            code="dispute_not_active",
            dispute_status=dispute.status,
        )
    if kind not in DisputeEvidence.Kind.values:
        raise DisputeError(
            "Evidence must be text, a photo or a video.",
            code="dispute_evidence_kind_invalid",
        )

    policy = phase4_policy().disputes
    _assert_evidence_budget(dispute, policy)

    stored: _StoredFile | None = None
    body_text = ""
    if kind == DisputeEvidence.Kind.TEXT:
        body_text = (text or "").strip()[:4_000]
        if not body_text:
            raise DisputeError(
                "Write something for a text statement.",
                code="dispute_evidence_text_required",
            )
    else:
        stored = _store_evidence_file(
            dispute=dispute, kind=kind, upload=upload, policy=policy
        )

    with transaction.atomic():
        # Re-checked after the upload. An orphaned object in a private bucket is
        # a cheaper failure than a lock held across the network.
        _assert_evidence_budget(dispute, policy)
        evidence = DisputeEvidence.objects.create(
            dispute=dispute,
            submitted_by_id=actor_id,
            kind=kind,
            text=body_text,
            storage_bucket=stored.bucket if stored else "",
            storage_key=stored.key if stored else "",
            content_type=stored.content_type if stored else "",
            size_bytes=stored.size_bytes if stored else None,
            content_sha256=stored.sha256 if stored else "",
        )
        _dispute_event(
            dispute,
            DisputeEvent.Kind.EVIDENCE_ADDED,
            {
                "evidence_id": evidence.pk,
                "evidence_kind": evidence.kind,
                "content_type": evidence.content_type,
                "size_bytes": evidence.size_bytes,
                "content_sha256": evidence.content_sha256,
            },
            actor_id=actor_id,
        )
        lifecycle.record_event(
            deal,
            DealEvent.Kind.DISPUTE_EVIDENCE_ADDED,
            {
                "dispute_id": dispute.pk,
                "evidence_id": evidence.pk,
                "evidence_kind": evidence.kind,
            },
            actor_id=actor_id,
        )
    return evidence


def evidence_download_url(*, evidence_id: int, actor_id: int, is_staff: bool) -> str:
    """Issue a short-lived signed URL for one stored evidence file.

    The bucket is private and the key is never serialized to a client, so this
    is the only route from an authorized caller to the bytes. The URL is signed
    for minutes rather than hours: a link pasted into a support chat should stop
    working long before the conversation is over.
    """

    evidence = DisputeEvidence.objects.select_related("dispute__deal").get(
        pk=evidence_id
    )
    deal = evidence.dispute.deal
    if not is_staff and actor_id not in (deal.sender_id, deal.traveler_id):
        raise NotAuthorized("This evidence belongs to someone else's delivery.")
    if not evidence.storage_key:
        raise DisputeError(
            "This evidence is a written statement and has no file.",
            code="dispute_evidence_not_a_file",
        )
    return s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": evidence.storage_bucket, "Key": evidence.storage_key},
        ExpiresIn=int(
            getattr(settings, "DISPUTE_EVIDENCE_URL_TTL_SECONDS", 300) or 300
        ),
    )


# --- administrative review ----------------------------------------------------


def set_dispute_status(
    *, dispute_id: int, status: str, admin_actor_id: int, note: str = ""
) -> Dispute:
    """Move a live dispute between its review states. Administrators only.

    `resolved` and `closed` are terminal and are not reachable from here: a
    resolution has to go through `resolve_dispute`, which moves the money, and
    reopening a resolved dispute would mean a second economic decision on money
    that has already been paid out or refunded.
    """

    if status not in ADMIN_SETTABLE_STATUSES:
        raise DisputeError(
            "A dispute can only be moved between open, awaiting evidence and "
            "under review.",
            code="dispute_status_invalid",
        )
    deal_id = Dispute.objects.values_list("deal_id", flat=True).get(pk=dispute_id)
    with transaction.atomic():
        aggregate = lock_deal_lifecycle(deal_id)
        dispute = Dispute.objects.select_for_update().get(pk=dispute_id)
        if dispute.status in (Dispute.Status.RESOLVED, Dispute.Status.CLOSED):
            raise DisputeError(
                "This dispute is already finished and cannot be reopened.",
                code="dispute_already_finished",
                dispute_status=dispute.status,
            )
        if dispute.status == status:
            return dispute

        previous = dispute.status
        dispute.status = status
        dispute.save(update_fields=["status", "updated_at"])
        _dispute_event(
            dispute,
            DisputeEvent.Kind.STATUS_CHANGED,
            {
                "status": status,
                "previous_status": previous,
                "note": note[:1_000],
            },
            actor_id=admin_actor_id,
        )
        lifecycle.record_event(
            aggregate.deal,
            DealEvent.Kind.DISPUTE_STATUS_CHANGED,
            {
                "dispute_id": dispute.pk,
                "status": status,
                "previous_status": previous,
            },
            actor_id=admin_actor_id,
        )
    return dispute


def close_dispute(
    *, dispute_id: int, admin_actor_id: int, note: str = ""
) -> Dispute:
    """Close a dispute's file. Administrators only, and it moves no money.

    Two legitimate uses: filing away a dispute that has already been resolved,
    and retiring one that should never have been opened. Neither settles
    anything -- a payout frozen by this dispute stays where the resolution (or
    the absence of one) left it, and only `resolve_dispute` decides a split.
    Idempotent: closing a closed dispute returns it unchanged.
    """

    deal_id = Dispute.objects.values_list("deal_id", flat=True).get(pk=dispute_id)
    with transaction.atomic():
        aggregate = lock_deal_lifecycle(deal_id)
        dispute = Dispute.objects.select_for_update().get(pk=dispute_id)
        if dispute.status == Dispute.Status.CLOSED:
            return dispute

        previous = dispute.status
        dispute.status = Dispute.Status.CLOSED
        dispute.closed_at = timezone.now()
        dispute.save(update_fields=["status", "closed_at", "updated_at"])
        _dispute_event(
            dispute,
            DisputeEvent.Kind.CLOSED,
            {"previous_status": previous, "note": note[:1_000]},
            actor_id=admin_actor_id,
        )
        lifecycle.record_event(
            aggregate.deal,
            DealEvent.Kind.DISPUTE_STATUS_CHANGED,
            {
                "dispute_id": dispute.pk,
                "status": dispute.status,
                "previous_status": previous,
            },
            actor_id=admin_actor_id,
        )
    return dispute


# --- resolution: the financial operation --------------------------------------


def _fee_mode(deal: Deal) -> str:
    """How the money that is not refunded is shared, from the Deal's own policy.

    Read from the snapshot frozen at funding, never from live settings: a
    revision published while a dispute is under review must not change the split
    the parties were operating under when the delivery happened.
    """

    snapshot = (deal.lifecycle_policy or {}).get("disputes")
    mode = snapshot.get("partial_split_fee_mode") if isinstance(snapshot, dict) else None
    return mode if mode in DisputePolicy.FEE_MODES else "proportional"


def _plan_resolution(
    *,
    deal: Deal,
    money: DealMoney,
    resolution: str,
    sender_refund_eur_cents: int | None,
    traveler_payout_eur_cents: int | None,
) -> SettlementPlan:
    """Turn one of three administrative decisions into three reconciling amounts."""

    total = money.collected_eur_cents
    if resolution == Dispute.Resolution.FULL_SENDER_REFUND:
        return plan_settlement(
            money=money,
            sender_refund_eur_cents=total,
            traveler_payout_eur_cents=0,
        )
    if resolution == Dispute.Resolution.FULL_TRAVELER_PAYOUT:
        # No explicit payout: the fee mode decides what the traveler keeps and
        # what the platform keeps out of everything the sender paid.
        return plan_settlement(
            money=money,
            sender_refund_eur_cents=0,
            fee_mode=_fee_mode(deal),
        )

    if sender_refund_eur_cents is None:
        raise DisputeError(
            "A partial split needs the amount to return to the sender.",
            code="dispute_partial_split_requires_amount",
            collected_eur_cents=total,
        )
    refund = int(sender_refund_eur_cents)
    if refund <= 0 or refund == total:
        # "Partial" that returns nothing, or everything, is one of the other two
        # resolutions wearing the wrong label -- and the label is what the
        # parties are told and what the reporting counts.
        raise DisputeError(
            "A partial split must return some, but not all, of the money.",
            code="dispute_partial_split_not_partial",
            collected_eur_cents=total,
            requested_eur_cents=refund,
        )
    return plan_settlement(
        money=money,
        sender_refund_eur_cents=refund,
        traveler_payout_eur_cents=traveler_payout_eur_cents,
        fee_mode=_fee_mode(deal),
    )


def _resolution_deal_status(*, plan: SettlementPlan, collected: int) -> str:
    if plan.sender_refund_eur_cents == 0:
        return Deal.Status.COMPLETED
    if collected > 0 and plan.sender_refund_eur_cents == collected:
        return Deal.Status.REFUNDED
    return Deal.Status.PARTIALLY_REFUNDED


def resolve_dispute(
    *,
    dispute_id: int,
    admin_actor_id: int,
    resolution: str,
    sender_refund_eur_cents: int | None = None,
    traveler_payout_eur_cents: int | None = None,
    note: str = "",
) -> Dispute:
    """Decide a dispute and settle its money, in one transaction.

    The Deal aggregate is taken first and the Dispute row second, in the
    canonical order, so two administrators pressing resolve at the same moment
    serialize rather than race. The loser then re-reads the committed status and
    returns the already-resolved row untouched: exactly one economic resolution
    exists per dispute, and a retried request is a no-op rather than a second
    refund.

    The three amounts are produced by `plan_settlement`, which refuses a split
    that does not sum to what the platform actually collected, and stored
    together with that total. `disputes_resolution_reconciles` refuses the same
    thing at the database, and `apps.finance.ledger` refuses it a third time --
    but the arithmetic is checked here rather than left to the constraint,
    because a constraint violation is a 500 and a refusal is an answer.

    The payout is not touched here. `apply_settlement` owns it, and it releases,
    reduces or cancels it as the decided split requires.
    """

    if resolution not in Dispute.Resolution.values:
        raise DisputeError(
            "That is not a dispute resolution.",
            code="dispute_resolution_invalid",
        )
    at = timezone.now()
    deal_id = Dispute.objects.values_list("deal_id", flat=True).get(pk=dispute_id)
    with transaction.atomic():
        aggregate = lock_deal_lifecycle(deal_id)
        dispute = Dispute.objects.select_for_update().get(pk=dispute_id)
        if dispute.status == Dispute.Status.RESOLVED:
            return dispute
        if dispute.status == Dispute.Status.CLOSED:
            raise DisputeError(
                "This dispute was closed without a resolution.",
                code="dispute_already_finished",
                dispute_status=dispute.status,
            )

        deal = aggregate.deal
        money = read_deal_money(deal)
        plan = _plan_resolution(
            deal=deal,
            money=money,
            resolution=resolution,
            sender_refund_eur_cents=sender_refund_eur_cents,
            traveler_payout_eur_cents=traveler_payout_eur_cents,
        )
        apply_settlement(
            plan=plan,
            settlement_key=f"dispute_resolution:{dispute.pk}",
            refund_reason=PaymentRefund.Reason.DISPUTE_RESOLUTION,
            note=f"Dispute #{dispute.pk} resolved as {resolution}",
            actor_id=admin_actor_id,
        )

        dispute.resolution = resolution
        dispute.sender_refund_eur_cents = plan.sender_refund_eur_cents
        dispute.traveler_payout_eur_cents = plan.traveler_payout_eur_cents
        dispute.platform_fee_eur_cents = plan.platform_fee_eur_cents
        dispute.collected_total_eur_cents = money.collected_eur_cents
        dispute.resolution_note = (note or "")[:4_000]
        dispute.resolved_by_id = admin_actor_id
        dispute.resolved_at = at
        dispute.status = Dispute.Status.RESOLVED
        dispute.save(
            update_fields=[
                "resolution",
                "sender_refund_eur_cents",
                "traveler_payout_eur_cents",
                "platform_fee_eur_cents",
                "collected_total_eur_cents",
                "resolution_note",
                "resolved_by",
                "resolved_at",
                "status",
                "updated_at",
            ]
        )

        _retire_live_codes(aggregate, at=at)
        target = _resolution_deal_status(
            plan=plan, collected=money.collected_eur_cents
        )
        lifecycle.apply_dispute_resolved(
            aggregate,
            status=target,
            reason=f"dispute_{resolution}"[:64],
            dispute_id=dispute.pk,
            actor_id=admin_actor_id,
            at=at,
        )
        _dispute_event(
            dispute,
            DisputeEvent.Kind.RESOLVED,
            {
                "resolution": resolution,
                "deal_status": target,
                "note": (note or "")[:1_000],
                **plan.as_dict(),
            },
            actor_id=admin_actor_id,
        )
        lifecycle.record_event(
            deal,
            DealEvent.Kind.DISPUTE_RESOLVED,
            {
                "dispute_id": dispute.pk,
                "resolution": resolution,
                "status": target,
                **plan.as_dict(),
            },
            actor_id=admin_actor_id,
        )
        _notify_resolved(aggregate, dispute)
        logger.info(
            "disputes.resolved dispute=%s deal=%s resolution=%s collected=%s",
            dispute.pk,
            deal.pk,
            resolution,
            money.collected_eur_cents,
        )
    return dispute


def _retire_live_codes(aggregate: LockedLifecycleAggregate, *, at) -> None:
    """Cancel any handover code still live when a dispute is decided.

    Cancellation and no-show already do this. A dispute resolution did not, so
    a sender whose Deal had just been refunded in full could still rotate the
    delivery code, receive a fresh plaintext, and have the platform email a
    third party a code for a delivery that no longer exists.
    """

    from apps.handover.models import DealHandoverCode

    live = [
        row.pk
        for row in aggregate.handover_codes
        if row.status in DealHandoverCode.LIVE_STATUSES
    ]
    if not live:
        return
    DealHandoverCode.objects.filter(pk__in=live).update(
        status=DealHandoverCode.Status.CANCELLED,
        superseded_at=at,
        updated_at=at,
    )


def _notify_resolved(aggregate: LockedLifecycleAggregate, dispute: Dispute) -> None:
    from apps.notifications.models import OutboundMessage
    from apps.notifications.outbox import enqueue_message

    deal = aggregate.deal
    context = {
        "deal_reference": f"ST-{deal.pk}",
        "dispute_reference": f"DSP-{dispute.pk}",
        "resolution": dispute.resolution,
    }
    for user_id, email in (
        (deal.sender_id, getattr(deal.sender, "email", "")),
        (deal.traveler_id, getattr(deal.traveler, "email", "")),
    ):
        if not email:
            continue
        enqueue_message(
            kind=OutboundMessage.Kind.DISPUTE_RESOLVED,
            key=f"dispute_resolved:{dispute.pk}:{user_id}",
            to_email=email,
            recipient_user_id=user_id,
            deal_id=deal.pk,
            context=context,
        )
