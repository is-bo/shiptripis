"""What the helper can read, type by type (spec 20.3, plan 2.11 and L15).

One entry per record type: the admin capabilities of the console page it
mirrors (any of them opens it, exactly as on that page), the rows it reads, its
allowlist serializer, its console address and its next-step text. **A type
without an entry does not exist for the helper.**

Every serializer below is written key by key. None reuses a console presenter
or a model serializer, so a field added to a model or to a console page never
reaches the helper by accident. What is never sent, whatever the role:
files and file names, document numbers, dates of birth, emails, phones,
addresses and coordinates, payout and bank details, pickup and delivery codes,
keys and secrets, chat messages, a guest payer's email. A person is the 2.11
form only (`Context.person`). User-written text is only in a record, under
``untrusted_user_text``, each field cut to 500 characters.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from django.contrib.auth import get_user_model
from django.db.models import Count, IntegerField, OuterRef, Q, QuerySet, Subquery
from django.db.models.functions import Coalesce
from django.urls import reverse

from apps.admin_panel.people_links import PROFILE_CAPABILITIES
from apps.admin_panel.permissions import has_admin_permission
from apps.deals.models import Deal, DealEvent
from apps.disputes.models import Dispute, DisputeEvent
from apps.finance.models import PaymentAttempt, PaymentRefund, Payout, ScheduledJob
from apps.parcels import tracking
from apps.parcels.models import DeliveryRequest
from apps.problems.models import ShipmentProblem
from apps.ratings.models import Rating, RatingReport
from apps.trips.models import Journey
from apps.trips.proofs import leg_proof_state, proof_state_annotation

from .people import short_name

User = get_user_model()

#: The longest user-written text the helper is given, per field.
UNTRUSTED_LIMIT = 500
TIMELINE_LIMIT = 30


@dataclass
class Context:
    """One helper call: who asks, and how to write their links.

    ``admin`` is the account `keys.resolve_key` loaded for this call, so what
    it may open is read once per call, never carried over from an earlier one.
    """

    request: object
    admin: object
    now: datetime

    def __post_init__(self):
        self._may: dict[str, bool] = {}

    def may_open(self, record_type: str) -> bool:
        """The console page of ``record_type`` would open for this admin."""

        if record_type not in self._may:
            gate = REGISTRY[record_type].gate
            self._may[record_type] = any(has_admin_permission(self.admin, code) for code in gate)
        return self._may[record_type]

    def url(self, path: str) -> str:
        return self.request.build_absolute_uri(path)

    def person(self, user) -> dict | None:
        """Plan 2.11: ``id``, ``display`` and ``console_url``, nothing else.

        The link is given only when this admin may open a person's page, as a
        console page prints the name as plain text otherwise.
        """

        if user is None:
            return None
        return {
            "id": user.pk,
            "display": short_name(user),
            "console_url": (
                self.url(reverse("admin_console:user-detail", args=(user.pk,)))
                if self.may_open("person")
                else None
            ),
        }

    def link(self, record_type: str, pk, label: str) -> dict:
        """A typed link to another record. Its label (a status), console page
        and record address are given only when this admin may open it."""

        if not self.may_open(record_type):
            return {"type": record_type, "id": pk, "label": None, "console_url": None, "record": None}
        return {
            "type": record_type,
            "id": pk,
            "label": label,
            "console_url": self.url(REGISTRY[record_type].console_path_for(pk)),
            "record": f"records/{record_type}/{pk}",
        }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _minutes_since(value: datetime | None, now: datetime) -> int | None:
    if value is None:
        return None
    return max(0, int((now - value).total_seconds() // 60))


def _money(cents, currency: str = "EUR") -> dict | None:
    if cents is None:
        return None
    return {"amount_eur_cents": int(cents), "currency": currency}


def _place(place) -> str | None:
    """A catalogue place's name: a city or an airport, never an address."""

    return place.name if place is not None else None


def _status(obj) -> dict:
    return {"status": obj.status, "status_label": obj.get_status_display()}


def _untrusted(**fields: str) -> dict[str, str]:
    return {
        name: text[:UNTRUSTED_LIMIT]
        for name, text in fields.items()
        if isinstance(text, str) and text.strip()
    }


def _timeline(*entries: tuple[datetime | None, str]) -> list[tuple[datetime, str]]:
    return sorted(
        ((at, label) for at, label in entries if at is not None), key=lambda entry: entry[0]
    )


@dataclass(frozen=True)
class Resource:
    type: str
    #: One line for `guide`.
    what: str
    #: The console page's capabilities: any of them opens it.
    gate: tuple[str, ...]
    queryset: Callable[[], QuerySet]
    #: The record's own fields, key by key.
    fields: Callable[[object, Context], dict]
    console_path: Callable[[object], str]
    next_step: Callable[[object], str]
    timeline: Callable[[object], list[tuple[datetime, str]]]
    #: User-written fields, or ``None`` when the type holds none.
    untrusted: Callable[[object], dict[str, str]] | None = None
    #: A queue row's money and people, for the types a work-list queue lists.
    row: Callable[[object, Context], dict] | None = None
    #: The console route, for addresses built from an id alone.
    route: str = ""

    def console_path_for(self, pk) -> str:
        return reverse(self.route, args=(pk,))

    def record(self, obj, ctx: Context) -> dict:
        payload = {
            "type": self.type,
            "id": obj.pk,
            **self.fields(obj, ctx),
            "next_step": self.next_step(obj),
            "timeline": [
                {"at": at.isoformat(), "label": label}
                for at, label in self.timeline(obj)[-TIMELINE_LIMIT:]
            ],
            "console_url": ctx.url(self.console_path(obj)),
        }
        if self.untrusted is not None:
            payload["untrusted_user_text"] = self.untrusted(obj)
        return payload

    def queue_row(self, obj, ctx: Context) -> dict:
        extra = self.row(obj, ctx) if self.row is not None else {}
        return {
            "type": self.type,
            "id": obj.pk,
            **extra,
            "waiting_minutes": _minutes_since(getattr(obj, "waiting_since", None), ctx.now),
            "next_step": self.next_step(obj),
            "console_url": ctx.url(self.console_path(obj)),
            "record": f"records/{self.type}/{obj.pk}",
        }


# --- person ------------------------------------------------------------------------


def _count_of(queryset: QuerySet, field: str) -> Coalesce:
    """How many rows of ``queryset`` point at the outer user, as one subquery."""

    counted = (
        queryset.filter(**{field: OuterRef("pk")})
        .order_by()
        .values(field)
        .annotate(total=Count("pk"))
        .values("total")
    )
    return Coalesce(Subquery(counted, output_field=IntegerField()), 0)


def _person_queryset():
    return User.objects.annotate(
        requests_count=_count_of(DeliveryRequest.objects.all(), "sender"),
        journeys_count=_count_of(Journey.objects.all(), "traveler"),
        deals_as_sender_count=_count_of(Deal.objects.all(), "sender"),
        deals_as_traveler_count=_count_of(Deal.objects.all(), "traveler"),
    )


def _account_status(user) -> str:
    if user.is_banned:
        return "banned"
    if not user.is_active:
        return "deactivated"
    return "active"


def _month(at: datetime | None) -> str | None:
    """Year and month only, as on the public profile card."""

    return f"{at.year:04d}-{at.month:02d}" if at else None


def _person_fields(user, ctx: Context) -> dict:
    # Plan 2.11 allows exactly these, and a privacy test freezes the list:
    # adding a field is a decision, not an edit.
    return {
        "person": ctx.person(user),
        "account_status": _account_status(user),
        "member_since": _month(user.date_joined),
        "activity": {
            "requests": user.requests_count,
            "trips": user.journeys_count,
            "deliveries_as_sender": user.deals_as_sender_count,
            "deliveries_as_traveler": user.deals_as_traveler_count,
        },
    }


def _person_next(user) -> str:
    if user.is_banned:
        return "This account is banned. Open their page to see why and what they were doing."
    return "Open their page to see their requests, trips, deliveries and payments."


# --- request -----------------------------------------------------------------------


def _request_queryset():
    return DeliveryRequest.objects.select_related("sender", "pickup_place", "delivery_place")


def _request_fields(item, ctx: Context) -> dict:
    return {
        "tracking_number": tracking.for_request(item),
        **_status(item),
        "from": _place(item.pickup_place),
        "to": _place(item.delivery_place),
        "weight_kg": str(item.actual_weight_kg) if item.actual_weight_kg is not None else None,
        "deadline_at": _iso(item.deadline_at),
        "traveler_reward": _money(item.traveler_reward_eur_cents),
        "boost": _money(item.boost_eur_cents),
        "sender": ctx.person(item.sender),
        "deliveries": [
            ctx.link("deal", deal.pk, deal.get_status_display())
            for deal in Deal.objects.filter(delivery_request=item).order_by("pk")
        ],
    }


def _request_next(item) -> str:
    return {
        "awaiting_deposit": "The sender has not paid the posting deposit yet. Nothing to do.",
        "open": "It is waiting for a traveler. Nothing to do unless the sender asks for help.",
        "matched": "A traveler took it. Follow the delivery from its deal.",
        "in_transit": "It is on its way. Follow the delivery from its deal.",
    }.get(item.status, "It is finished. Open it only to answer a question about it.")


# --- journey -----------------------------------------------------------------------


def _journey_queryset():
    return Journey.objects.select_related("traveler", "start_place", "destination_place")


def _journey_fields(journey, ctx: Context) -> dict:
    legs = (
        journey.legs.select_related("origin_place", "destination_place")
        .annotate(proof_state_value=proof_state_annotation())
        .order_by("position")
    )
    return {
        **_status(journey),
        "traveler": ctx.person(journey.traveler),
        "from": _place(journey.start_place),
        "to": _place(journey.destination_place),
        "paused": journey.paused_at is not None,
        "paused_by_staff": journey.paused_by_staff,
        "price_per_kg": _money(journey.price_per_kg_eur_cents),
        "minimum_price": _money(journey.min_price_eur_cents),
        "legs": [
            {
                "position": leg.position,
                "mode": leg.mode,
                "from": _place(leg.origin_place),
                "to": _place(leg.destination_place),
                "departs_at": _iso(leg.depart_at),
                "arrives_at": _iso(leg.arrive_at),
                "ticket": leg_proof_state(leg),
            }
            for leg in legs
        ],
    }


def _journey_next(journey) -> str:
    if journey.paused_at is not None:
        return "This trip is paused. Open it to see why before resuming it."
    return "Open the trip to see its legs, tickets and the deliveries it carries."


# --- deal --------------------------------------------------------------------------


def _deal_queryset():
    return Deal.objects.select_related(
        "delivery_request", "sender", "traveler", "terms", "payout"
    )


def _deal_terms(deal) -> dict | None:
    terms = getattr(deal, "terms", None)
    if terms is None:
        return None
    return {
        "currency": terms.currency,
        "traveler_reward_cents": terms.traveler_reward_minor,
        "wassla_fee_cents": terms.platform_fee_minor,
        "sender_total_cents": terms.sender_total_minor,
    }


def _deal_payout(deal):
    try:
        return deal.payout
    except Payout.DoesNotExist:
        return None


def _deal_fields(deal, ctx: Context) -> dict:
    payout = _deal_payout(deal)
    return {
        "tracking_number": tracking.for_deal(deal),
        **_status(deal),
        "sender": ctx.person(deal.sender),
        "traveler": ctx.person(deal.traveler),
        "money": _deal_terms(deal),
        "funded_at": _iso(deal.funded_at),
        "agreed_pickup_at": _iso(deal.agreed_pickup_at),
        "picked_up_at": _iso(deal.pickup_confirmed_at),
        "delivered_at": _iso(deal.delivery_confirmed_at),
        "protection_ends_at": _iso(deal.protection_ends_at),
        "no_show": deal.no_show_party or None,
        "disputes": [
            ctx.link("dispute", dispute.pk, dispute.get_status_display())
            for dispute in deal.disputes.order_by("pk")
        ],
        "problems": [
            ctx.link("problem", problem.pk, f"{problem.get_kind_display()} · {problem.get_status_display()}")
            for problem in deal.problems.order_by("pk")
        ],
        "payout": ctx.link("payout", payout.pk, payout.get_status_display()) if payout else None,
    }


def _deal_next(deal) -> str:
    return {
        "offer_accepted": "The sender still has to pay. Nothing to do.",
        "payment_required": "The sender still has to pay. Nothing to do.",
        "funded": "Paid. The traveler picks the parcel up next.",
        "pickup_ready": "Waiting for the pickup. Nothing to do unless someone reports a problem.",
        "picked_up": "On its way. Nothing to do unless someone reports a problem.",
        "in_transit": "On its way. Nothing to do unless someone reports a problem.",
        "delivery_ready": "Waiting for the recipient's code. Nothing to do.",
        "delivery_confirmed": "Delivered. The protection window runs before the payout.",
        "protection_window": "Delivered. The payout follows when the protection window ends.",
        "disputed": "A dispute is open. Decide it from the dispute page.",
    }.get(deal.status, "This delivery is finished. Open it only to answer a question about it.")


def _deal_timeline(deal) -> list[tuple[datetime, str]]:
    statuses = dict(Deal.Status.choices)
    entries = []
    for event in DealEvent.objects.filter(deal=deal).order_by("created_at", "pk"):
        label = event.get_kind_display()
        # Only the status of a status change is read from a payload: a
        # payload's other keys are not part of the helper's allowlist.
        status = event.payload.get("status") if isinstance(event.payload, dict) else None
        if event.kind == DealEvent.Kind.STATUS_CHANGED and status in statuses:
            label = f"Status: {statuses[status]}"
        entries.append((event.created_at, label))
    return entries


# --- dispute -----------------------------------------------------------------------


def _dispute_queryset():
    return Dispute.objects.select_related(
        "deal__delivery_request", "deal__sender", "deal__traveler", "opened_by"
    )


def _dispute_fields(dispute, ctx: Context) -> dict:
    return {
        "tracking_number": tracking.for_deal(dispute.deal),
        **_status(dispute),
        "category": dispute.get_category_display(),
        "opened_by": dispute.get_opened_by_role_display(),
        "opened_at": _iso(dispute.opened_at),
        "sender": ctx.person(dispute.deal.sender),
        "traveler": ctx.person(dispute.deal.traveler),
        "payout_frozen": dispute.payout_frozen,
        "resolution": dispute.get_resolution_display() if dispute.resolution else None,
        "sender_refund": _money(dispute.sender_refund_eur_cents),
        "traveler_payout": _money(dispute.traveler_payout_eur_cents),
        "deal": ctx.link("deal", dispute.deal_id, dispute.deal.get_status_display()),
    }


def _dispute_next(dispute) -> str:
    return {
        "open": "Read both sides and the evidence, then move it to review or ask for more evidence.",
        "awaiting_evidence": "Waiting for the people to add evidence. Check it again later.",
        "under_review": "Decide it: refund the sender, pay the traveler, or split the money.",
    }.get(dispute.status, "This dispute is decided. Open it only to answer a question about it.")


def _dispute_row(dispute, ctx: Context) -> dict:
    return {
        "tracking_number": tracking.for_deal(dispute.deal),
        **_status(dispute),
        "category": dispute.get_category_display(),
        "people": [ctx.person(dispute.deal.sender), ctx.person(dispute.deal.traveler)],
    }


def _dispute_timeline(dispute) -> list[tuple[datetime, str]]:
    return [
        (event.created_at, event.get_kind_display())
        for event in DisputeEvent.objects.filter(dispute=dispute).order_by("created_at", "pk")
    ]


# --- payment -----------------------------------------------------------------------


def _payment_queryset():
    return PaymentAttempt.objects.select_related(
        "order__delivery_request", "order__deal__delivery_request", "payer"
    )


def _charged(attempt) -> dict | None:
    """What the provider moved, when it was not euros (the dinar rail)."""

    if attempt.payment_currency == "EUR":
        return None
    return {
        "amount_minor": attempt.provider_amount_minor,
        "exponent": attempt.provider_amount_exponent,
        "currency": attempt.payment_currency,
    }


def _payment_fields(attempt, ctx: Context) -> dict:
    return {
        "tracking_number": attempt.order.tracking_number,
        "reference": str(attempt.order.public_reference),
        "purpose": attempt.order.get_purpose_display(),
        "provider": attempt.get_provider_display(),
        "mode": attempt.provider_mode,
        **_status(attempt),
        "amount": _money(attempt.amount_eur_cents),
        "order_amount": _money(attempt.order.amount_eur_cents),
        "charged": _charged(attempt),
        "paid_by": "owner" if attempt.payer_id else "guest",
        "payer": ctx.person(attempt.payer),
        "unapplied": attempt.is_unapplied,
        "failure_code": attempt.failure_code or None,
        "resolved_by_staff": bool(attempt.operational_resolution),
    }


def _payment_next(attempt) -> str:
    if attempt.operational_resolution:
        return "Staff already recorded how this was resolved. Nothing to do."
    if attempt.is_unapplied:
        return "Money was captured but no order took it. Open it and reconcile it or refund it."
    if attempt.status == PaymentAttempt.Status.FAILED:
        return "The payment failed. Open it to see the reason and decide if anything is owed."
    return "Open the payment to see its order and what the provider recorded."


def _payment_row(attempt, ctx: Context) -> dict:
    return {
        "tracking_number": attempt.order.tracking_number,
        **_status(attempt),
        "amount": _money(attempt.amount_eur_cents),
        "people": [person for person in (ctx.person(attempt.payer),) if person],
    }


def _payment_timeline(attempt) -> list[tuple[datetime, str]]:
    return _timeline(
        (attempt.created_at, "Checkout started"),
        (attempt.succeeded_at, "Payment captured"),
        (attempt.operational_resolved_at, "Resolved by staff"),
    )


# --- refund ------------------------------------------------------------------------


def _refund_queryset():
    return PaymentRefund.objects.select_related(
        "order__delivery_request", "order__deal__delivery_request", "requested_by", "attempt"
    )


def _refund_fields(refund, ctx: Context) -> dict:
    return {
        "tracking_number": refund.order.tracking_number,
        **_status(refund),
        "amount": _money(refund.amount_eur_cents),
        "provider": refund.get_provider_display(),
        "reason": refund.get_reason_display(),
        "needs_staff": refund.requires_manual_action,
        "failure_code": refund.failure_code or None,
        "requested_by": ctx.person(refund.requested_by),
        "payment": ctx.link("payment", refund.attempt_id, refund.attempt.get_status_display()),
    }


def _refund_next(refund) -> str:
    if refund.requires_manual_action and refund.status in (
        PaymentRefund.Status.PENDING,
        PaymentRefund.Status.PROCESSING,
    ):
        return "Automatic refund stopped. Open it and settle it by hand, or fix what blocks it."
    if refund.status == PaymentRefund.Status.SUCCEEDED:
        return "The money was returned. Nothing to do."
    return "Open the refund to see where it is."


def _refund_row(refund, ctx: Context) -> dict:
    return {
        "tracking_number": refund.order.tracking_number,
        **_status(refund),
        "amount": _money(refund.amount_eur_cents),
        "people": [person for person in (ctx.person(refund.requested_by),) if person],
    }


def _refund_timeline(refund) -> list[tuple[datetime, str]]:
    return _timeline(
        (refund.created_at, "Refund requested"),
        (refund.succeeded_at, "Refund succeeded"),
    )


# --- payout ------------------------------------------------------------------------


def _payout_queryset():
    return Payout.objects.select_related("deal__delivery_request", "traveler")


def _payout_amount(payout) -> dict | None:
    if not payout.payout_currency or payout.payout_currency == "EUR":
        return None
    return {
        "amount_minor": payout.payout_amount_minor,
        "exponent": payout.payout_amount_exponent,
        "currency": payout.payout_currency,
    }


def _payout_fields(payout, ctx: Context) -> dict:
    return {
        "tracking_number": tracking.for_deal(payout.deal),
        "reference": str(payout.public_reference),
        **_status(payout),
        "method": payout.get_method_display(),
        "amount": _money(payout.amount_eur_cents),
        "paid_in": _payout_amount(payout),
        "blocked_because": payout.block_reason or None,
        "eligible_at": _iso(payout.eligible_at),
        "traveler": ctx.person(payout.traveler),
        "deal": ctx.link("deal", payout.deal_id, payout.deal.get_status_display()),
    }


def _payout_next(payout) -> str:
    if payout.status == Payout.Status.FAILED:
        return "The payout failed. Open it to see why, fix the cause and retry it."
    if payout.status == Payout.Status.ELIGIBLE and payout.method == Payout.Method.MANUAL:
        return "It is ready to send by hand. Open it and follow the manual payout steps."
    if payout.status == Payout.Status.PAID:
        return "The traveler was paid. Nothing to do."
    return "Open the payout to see what it is waiting for."


def _payout_row(payout, ctx: Context) -> dict:
    return {
        "tracking_number": tracking.for_deal(payout.deal),
        **_status(payout),
        "amount": _money(payout.amount_eur_cents),
        "people": [ctx.person(payout.traveler)],
    }


def _payout_timeline(payout) -> list[tuple[datetime, str]]:
    return _timeline(
        (payout.created_at, "Payout created"),
        (payout.eligible_at, "Ready to pay"),
        (payout.sent_at, "Sent"),
        (payout.paid_at, "Paid"),
    )


# --- job ---------------------------------------------------------------------------


def _job_queryset():
    return ScheduledJob.objects.all()


def _job_state(job) -> str:
    if job.resolution:
        return "resolved"
    if job.status == ScheduledJob.Status.FAILED:
        return "needs_attention"
    return job.status


def _job_fields(job, ctx: Context) -> dict:
    return {
        "work": job.get_kind_display(),
        "status": _job_state(job),
        "status_label": (
            job.get_resolution_display()
            if job.resolution
            else "Needs attention"
            if job.status == ScheduledJob.Status.FAILED
            else job.get_status_display()
        ),
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "error_category": job.last_error_code or None,
        "next_run_at": _iso(job.run_at) if job.status == ScheduledJob.Status.PENDING else None,
    }


def _job_next(job) -> str:
    if job.status == ScheduledJob.Status.FAILED and not job.resolution:
        return "It stopped for good. Open it, read the error category, then retry it or resolve it with a reason."
    return "Nothing to do. It runs or ran on its own."


def _job_row(job, ctx: Context) -> dict:
    return {
        "work": job.get_kind_display(),
        "status": _job_state(job),
        "error_category": job.last_error_code or None,
        "people": [],
    }


def _job_timeline(job) -> list[tuple[datetime, str]]:
    return _timeline(
        (job.created_at, "Scheduled"),
        (job.last_attempt_at, "Last attempt"),
        (job.completed_at, "Finished" if job.status == ScheduledJob.Status.SUCCEEDED else "Stopped"),
        (job.resolved_at, "Resolved by staff"),
    )


# --- problem -----------------------------------------------------------------------


def _problem_queryset():
    return ShipmentProblem.objects.select_related(
        "deal__delivery_request", "reported_by", "deal__sender", "deal__traveler"
    )


def _problem_fields(problem, ctx: Context) -> dict:
    return {
        "tracking_number": tracking.for_deal(problem.deal),
        "kind": problem.get_kind_display(),
        **_status(problem),
        "reported_by": problem.get_reporter_role_display(),
        "reporter": ctx.person(problem.reported_by),
        "deal": ctx.link("deal", problem.deal_id, problem.deal.get_status_display()),
    }


def _problem_next(problem) -> str:
    if problem.kind in ShipmentProblem.NO_SHOW_KINDS and problem.status in (
        ShipmentProblem.Status.ESCALATED,
        ShipmentProblem.Status.ACKNOWLEDGED,
    ):
        return "Someone says the other person did not come. Open it, check, then record the no-show or close it."
    if problem.status == ShipmentProblem.Status.ESCALATED:
        return "Nobody has looked at it yet. Open it and acknowledge it."
    if problem.status == ShipmentProblem.Status.ACKNOWLEDGED:
        return "Staff are on it. Close it with a reason when it is settled."
    if problem.status == ShipmentProblem.Status.OPEN:
        return "The other person was told. Staff do not need to act yet."
    return "It is closed. Nothing to do."


def _problem_row(problem, ctx: Context) -> dict:
    return {
        "tracking_number": tracking.for_deal(problem.deal),
        "kind": problem.get_kind_display(),
        **_status(problem),
        "people": [ctx.person(problem.deal.sender), ctx.person(problem.deal.traveler)],
    }


def _problem_timeline(problem) -> list[tuple[datetime, str]]:
    return _timeline(
        (problem.created_at, "Reported"),
        (problem.escalated_at, "Sent to staff"),
        (problem.acknowledged_at, "Acknowledged by staff"),
        (problem.closed_at, "Closed"),
    )


# --- review_report -----------------------------------------------------------------


def _review_queryset():
    return Rating.objects.select_related(
        "deal__delivery_request", "rater", "ratee", "moderation"
    ).annotate(
        open_reports=Count("reports", filter=Q(reports__status=RatingReport.Status.OPEN))
    )


def _moderation(rating):
    try:
        return rating.moderation
    except Rating.moderation.RelatedObjectDoesNotExist:
        return None


def _review_fields(rating, ctx: Context) -> dict:
    moderation = _moderation(rating)
    return {
        "tracking_number": tracking.for_deal(rating.deal),
        "score": rating.score,
        "written_by": rating.get_rater_role_display(),
        "writer": ctx.person(rating.rater),
        "about": ctx.person(rating.ratee),
        "open_reports": rating.open_reports,
        "reports": [
            {"reason": report.get_reason_display(), "status": report.status, "at": _iso(report.created_at)}
            for report in rating.reports.order_by("created_at", "pk")
        ],
        "decision": moderation.get_state_display() if moderation else None,
    }


def _review_next(rating) -> str:
    if rating.open_reports:
        return "Read the review and the reports, then dismiss them, hide the comment or remove the rating."
    return "No open report. Nothing to do."


def _review_row(rating, ctx: Context) -> dict:
    return {
        "tracking_number": tracking.for_deal(rating.deal),
        "score": rating.score,
        "open_reports": rating.open_reports,
        "people": [ctx.person(rating.ratee)],
    }


def _review_untrusted(rating) -> dict[str, str]:
    notes = {
        f"report_{index}_note": report.note
        for index, report in enumerate(rating.reports.order_by("created_at", "pk"), start=1)
    }
    return _untrusted(comment=rating.comment, **notes)


def _review_timeline(rating) -> list[tuple[datetime, str]]:
    moderation = _moderation(rating)
    return _timeline(
        (rating.created_at, "Review written"),
        *(
            (report.created_at, f"Reported: {report.get_reason_display()}")
            for report in rating.reports.order_by("created_at", "pk")
        ),
        (moderation.decided_at if moderation else None,
         f"Decision: {moderation.get_state_display()}" if moderation else ""),
    )


def _path(route: str):
    return lambda obj: reverse(route, args=(obj.pk,))


def _request_path(item) -> str:
    return f"{reverse('admin_console:requests')}?q={tracking.for_request(item)}"


class _RequestResource(Resource):
    def console_path_for(self, pk) -> str:
        item = DeliveryRequest.objects.filter(pk=pk).only("tracking_number").first()
        return _request_path(item) if item else reverse("admin_console:requests")


REGISTRY: dict[str, Resource] = {
    resource.type: resource
    for resource in (
        Resource(
            type="person",
            what="A member or staff account: account state and activity counts.",
            gate=PROFILE_CAPABILITIES,
            queryset=_person_queryset,
            fields=_person_fields,
            console_path=_path("admin_console:user-detail"),
            next_step=_person_next,
            # "Member since" is the month alone, so no dated entry repeats it.
            timeline=lambda user: [],
            route="admin_console:user-detail",
        ),
        _RequestResource(
            type="request",
            what="A sender's parcel request before and while it is carried.",
            gate=("view_requests",),
            queryset=_request_queryset,
            fields=_request_fields,
            console_path=_request_path,
            next_step=_request_next,
            timeline=lambda item: _timeline((item.created_at, "Request created")),
            untrusted=lambda item: _untrusted(
                title=item.title, description=item.description, handling_notes=item.handling_notes
            ),
        ),
        Resource(
            type="journey",
            what="A traveler's trip: its legs, tickets, price and pause state.",
            gate=("view_journeys",),
            queryset=_journey_queryset,
            fields=_journey_fields,
            console_path=_path("admin_console:journey-detail"),
            next_step=_journey_next,
            timeline=lambda journey: _timeline(
                (journey.created_at, "Trip created"),
                (journey.published_at, "Published"),
                (journey.paused_at, "Paused"),
            ),
            untrusted=lambda journey: _untrusted(notes=journey.notes),
            route="admin_console:journey-detail",
        ),
        Resource(
            type="deal",
            what="One delivery from acceptance to payout: status, money, disputes, problems.",
            gate=("view_deals",),
            queryset=_deal_queryset,
            fields=_deal_fields,
            console_path=_path("admin_console:deal-detail"),
            next_step=_deal_next,
            timeline=_deal_timeline,
            untrusted=lambda deal: _untrusted(parcel_title=deal.delivery_request.title),
            route="admin_console:deal-detail",
        ),
        Resource(
            type="dispute",
            what="A dispute on a delivery: status, category, money at stake.",
            gate=("view_disputes",),
            queryset=_dispute_queryset,
            fields=_dispute_fields,
            console_path=_path("admin_console:dispute-detail"),
            next_step=_dispute_next,
            timeline=_dispute_timeline,
            untrusted=lambda dispute: _untrusted(description=dispute.reason_text),
            row=_dispute_row,
            route="admin_console:dispute-detail",
        ),
        Resource(
            type="payment",
            what="One payment attempt: amount, provider, state, who paid.",
            gate=("view_payment_attempts", "view_payment_orders"),
            queryset=_payment_queryset,
            fields=_payment_fields,
            console_path=_path("admin_console:payment-detail"),
            next_step=_payment_next,
            timeline=_payment_timeline,
            row=_payment_row,
            route="admin_console:payment-detail",
        ),
        Resource(
            type="refund",
            what="One refund: amount, reason, state, whether staff must settle it.",
            gate=("issue_refunds", "settle_manual_refunds"),
            queryset=_refund_queryset,
            fields=_refund_fields,
            console_path=_path("admin_console:refund-detail"),
            next_step=_refund_next,
            timeline=_refund_timeline,
            row=_refund_row,
            route="admin_console:refund-detail",
        ),
        Resource(
            type="payout",
            what="One traveler payout: amount, method, state, why it waits.",
            gate=("view_payouts",),
            queryset=_payout_queryset,
            fields=_payout_fields,
            console_path=_path("admin_console:payout-detail"),
            next_step=_payout_next,
            timeline=_payout_timeline,
            row=_payout_row,
            route="admin_console:payout-detail",
        ),
        Resource(
            type="job",
            what="One background job: what it does, its state and error category.",
            gate=("view_scheduled_jobs", "view_operational_incidents"),
            queryset=_job_queryset,
            fields=_job_fields,
            console_path=_path("admin_console:job-detail"),
            next_step=_job_next,
            timeline=_job_timeline,
            row=_job_row,
            route="admin_console:job-detail",
        ),
        Resource(
            type="problem",
            what="A problem a sender or traveler reported on a delivery.",
            gate=("view_disputes",),
            queryset=_problem_queryset,
            fields=_problem_fields,
            console_path=_path("admin_console:problem-detail"),
            next_step=_problem_next,
            timeline=_problem_timeline,
            untrusted=lambda problem: _untrusted(note=problem.note),
            row=_problem_row,
            route="admin_console:problem-detail",
        ),
        Resource(
            type="review_report",
            what="A review members reported: the score, the reports and any decision.",
            gate=("moderate_ratings",),
            queryset=_review_queryset,
            fields=_review_fields,
            console_path=_path("admin_console:review-detail"),
            next_step=_review_next,
            timeline=_review_timeline,
            untrusted=_review_untrusted,
            row=_review_row,
            route="admin_console:review-detail",
        ),
    )
}
TYPES = tuple(REGISTRY)


def queue_rows_queryset(record_type: str, rows: QuerySet) -> QuerySet:
    """A work-list queue's rows with what its row serializer reads joined."""

    joins = {
        "dispute": ("deal__delivery_request", "deal__sender", "deal__traveler"),
        "problem": ("deal__delivery_request", "deal__sender", "deal__traveler"),
        "payment": ("order__delivery_request", "order__deal__delivery_request", "payer"),
        "refund": ("order__delivery_request", "order__deal__delivery_request", "requested_by"),
        "payout": ("deal__delivery_request", "traveler"),
        "job": (),
        "review_report": ("deal__delivery_request", "ratee"),
    }[record_type]
    rows = rows.select_related(*joins)
    if record_type == "review_report":
        rows = rows.annotate(
            open_reports=Count("reports", filter=Q(reports__status=RatingReport.Status.OPEN))
        )
    return rows
