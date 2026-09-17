"""The Person profile: one operational page for everything about one user.

Before J6.4 a user's page was a card of four counts, and everything else about
the same person — their requests, journeys, Deals, payments, payout method,
disputes — was a different screen with a `?user_id=` filter, when it was
reachable at all. J6.4 makes this page the place an operator goes to understand
a person.

Three rules shape it.

**Bounded, not exhaustive.** A person with years of history must not make this
page expensive, and the Finance dashboard beside it already costs ninety
queries. So the page loads one tab at a time. The Overview is a fixed set of
grouped aggregates — one query per fact, whatever the history holds — and every
history tab is its own paginated list with its related rows joined or
prefetched up front. The query count of a tab does not grow with the history.

**Every section is gated on the capability that owns its data.** Reaching the
page needs any capability that already shows this person's name somewhere in
the console (`people_links.PROFILE_CAPABILITIES`), so the header adds nothing an
operator could not already see. Below it, Payments need payment capabilities,
Payouts need payout capabilities, Audit needs the audit log, and so on. A tab a
role cannot read is not rendered, not merely empty.

**Nothing sensitive by default.** No payout account value, masked or otherwise,
appears here: the payout method shows its review state and links to the review
page, where the audited reveal lives. No ID document is embedded: the Identity
tab links to the KYC review, which audits every open. No chat content: the
console has no authorized support access to conversations, so this page does
not invent one. Ratings are shown only once the product's own blind rule has
revealed them.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import (
    Avg,
    CharField,
    Count,
    Exists,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
)
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone

from apps.core.admin_display import format_eur, humanize_action, humanize_object
from apps.deals.activity import ACTIVE, ACTIVITY_STATES, CANCELLED, COMPLETED, activity_q
from apps.deals.models import Deal, DealTermsSnapshot
from apps.disputes.models import Dispute, DisputeEvidence
from apps.finance.models import (
    DzdPayoutProfileRevision,
    FinanceHold,
    PaymentAttempt,
    PaymentOrder,
    PaymentRefund,
    Payout,
    PayoutEvidence,
    PayoutIdentityAttestation,
    PayoutIdentityReviewAssignment,
    StripePayoutAccount,
    TravelerPayoutMethod,
)
from apps.finance.operations import payment_attention_queryset
from apps.kyc.models import KycSubmission
from apps.matching.models import Offer
from apps.matching.offer_economics import OfferEconomicsReader
from apps.notifications.models import Notification
from apps.parcels.lifecycle import with_lifecycle
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.ratings.models import Rating
from apps.trips.models import Journey, JourneyLeg

from .console_presenters import (
    datetime_cell,
    format_minor_amount,
    journey_route_nodes,
    money_cell,
    money_pair_cell,
    parcel_summary,
    request_route_nodes,
    route_cell,
    status_cell,
    text_cell,
)
from .console_views import _query_without_page, _render, capability_required
from .models import AdminAuditLog
from .people_links import (
    PROFILE_CAPABILITIES,
    RETURN_CONTEXTS,
    display_name,
    initials,
    person_href,
    return_crumbs,
)
from .permissions import ROLE_GROUP_NAMES, has_admin_permission, user_admin_roles

User = get_user_model()

PAGE_SIZE = 20

#: The tabs, in reading order, and the capabilities that may see each one. An
#: empty tuple means "anyone who can open the profile".
TABS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("overview", "Overview", ()),
    ("identity", "Identity", ("view_users", "view_kyc", "review_payout_profiles", "attest_payout_identity")),
    ("activity", "Activity", ("view_requests", "view_journeys", "view_deals", "view_matches")),
    ("deliveries", "Deliveries", ("view_deals",)),
    ("payments", "Payments", ("view_payment_orders", "view_payment_attempts")),
    ("payouts", "Payouts", ("view_payouts", "view_finance_summary", "review_payout_profiles")),
    ("trust", "Trust & support", ("view_disputes", "view_ratings", "view_support_context")),
    ("audit", "Audit", ("view_audit_log",)),
)

ACTIVITY_VIEWS = (
    ("requests", "Parcel requests", ("view_requests",)),
    ("journeys", "Journeys", ("view_journeys",)),
    ("offers", "Offers", ("view_deals", "view_matches")),
)

TRUST_VIEWS = (
    ("disputes", "Disputes", ("view_disputes",)),
    ("ratings", "Ratings", ("view_ratings",)),
    ("notifications", "Notifications", ("view_support_context",)),
)

PAYOUT_CAPS = ("view_payouts", "view_finance_summary", "review_payout_profiles")
FINANCE_ISSUE_CAPS = ("view_payment_attempts", "view_payouts")

ACTIVE_REQUEST_STATES = (
    ParcelRequest.Status.AWAITING_DEPOSIT,
    ParcelRequest.Status.OPEN,
    ParcelRequest.Status.MATCHED,
    ParcelRequest.Status.IN_TRANSIT,
)
ACTIVE_JOURNEY_STATES = (
    Journey.Status.PENDING_VERIFICATION,
    Journey.Status.ACTIVE,
    Journey.Status.IN_PROGRESS,
)
REQUEST_STATUS_LABELS = dict(ParcelRequest.Status.choices)


class Capabilities:
    """`has_admin_permission` per code, read once per request.

    Django caches a user's permission set on first read, so this is about
    keeping the templates and builders terse rather than about queries.
    """

    def __init__(self, user):
        self.user = user
        self._seen: dict[str, bool] = {}

    def __call__(self, *codes: str) -> bool:
        return any(self._one(code) for code in codes)

    def _one(self, code: str) -> bool:
        if code not in self._seen:
            self._seen[code] = has_admin_permission(self.user, code)
        return self._seen[code]


# ---------------------------------------------------------------------------
# Small shared pieces
# ---------------------------------------------------------------------------


def _source(request) -> str:
    source = request.GET.get("from", "")
    return source if source in RETURN_CONTEXTS else ""


def _tab_url(person, tab, *, source="", **params) -> str:
    query = [("tab", tab)]
    if source:
        query.append(("from", source))
    query.extend((key, value) for key, value in params.items() if value)
    from urllib.parse import urlencode

    return f"{reverse('admin_console:user-detail', args=(person.pk,))}?{urlencode(query)}"


def _page(request, queryset):
    return Paginator(queryset, PAGE_SIZE).get_page(request.GET.get("page"))


def _list(columns, rows, *, page_obj=None, empty="", layout="", note="", title=""):
    """A responsive list: columns on a wide screen, labelled cards on a phone."""

    for row in rows:
        row["cells"] = [
            {**cell, "label": column} for column, cell in zip(columns, row["cells"])
        ]
        row["openable"] = any(cell.get("is_primary") for cell in row["cells"])
    numeric = {"money", "money-lead", "money-pair"}
    first = rows[0]["cells"] if rows else []
    return {
        "columns": columns,
        "head": [
            {"label": column, "numeric": index < len(first) and first[index].get("kind") in numeric}
            for index, column in enumerate(columns)
        ],
        "rows": rows,
        "page_obj": page_obj,
        "empty": empty,
        "layout": layout,
        "note": note,
        "title": title,
    }


def _person_cell(user, *, secondary="", caps=None, source="", self_id=None):
    if user is None:
        return text_cell("—")
    if self_id is not None and user.pk == self_id:
        return text_cell("This person", secondary)
    return text_cell(
        display_name(user),
        secondary or user.email,
        href=person_href(user.pk, source=source),
    )


def _date_text(value, fmt="%d %b %Y"):
    return timezone.localtime(value).strftime(fmt) if value else ""


def _kyc_summary(submissions):
    now = timezone.now()
    approved = next(
        (
            row
            for row in submissions
            if row.status == "approved" and not (row.expires_at and row.expires_at <= now)
        ),
        None,
    )
    if approved:
        return {"label": "ID approved", "tone": "ok", "state": "approved", "record": approved}
    pending = next((row for row in submissions if row.status == "pending"), None)
    if pending:
        return {"label": "ID waiting for review", "tone": "attn", "state": "pending", "record": pending}
    if submissions:
        latest = submissions[0]
        label = {"rejected": "ID rejected", "expired": "ID expired", "approved": "ID expired"}.get(
            latest.status, "ID not approved"
        )
        return {"label": label, "tone": "bad", "state": latest.status, "record": latest}
    return {"label": "No ID submitted", "tone": "mute", "state": "none", "record": None}


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------


def _header(request, person, caps, *, source):
    from .console_payout_reviews import BUCKET_LABELS, BUCKET_TONES, reviewable_methods

    submissions = list(person.kyc_submissions.order_by("-created_at")[:10])
    kyc = _kyc_summary(submissions)
    account = (
        ("Banned", "bad")
        if person.is_banned
        else ("Active", "ok")
        if person.is_active
        else ("Sign-in disabled", "bad")
    )
    staff_roles = []
    if person.is_staff:
        staff_roles = [ROLE_GROUP_NAMES[slug] for slug in user_admin_roles(person)]
        if person.is_superuser and "Super Admin" not in staff_roles:
            staff_roles.append("Super Admin")

    payout_review = None
    if caps("review_payout_profiles"):
        method = (
            reviewable_methods()
            .filter(traveler=person)
            .select_related("current_version__dzd_profile_revision")
            .first()
        )
        if method is not None:
            reference = method.current_version.dzd_profile_revision.public_reference
            payout_review = {
                "bucket": method.bucket,
                "label": BUCKET_LABELS[method.bucket],
                "tone": BUCKET_TONES[method.bucket],
                "url": reverse("admin_console:payout-review-detail", args=(reference,))
                + "?from=person",
            }

    actions = []
    if payout_review and payout_review["bucket"] == "waiting":
        actions.append({"label": "Review payout method", "url": payout_review["url"], "primary": True})
    if kyc["state"] == "pending" and caps("view_kyc"):
        actions.append(
            {
                "label": "Review ID",
                "url": reverse("admin_console:kyc-detail", args=(kyc["record"].pk,)),
                "primary": not actions,
            }
        )

    return {
        "name": display_name(person),
        "has_name": bool((person.full_name or "").strip()),
        "initials": initials(person),
        "email": person.email,
        "phone": person.phone if caps("view_user_sensitive") else None,
        "id": person.pk,
        "joined": person.date_joined,
        "account": {"label": account[0], "tone": account[1]},
        "role": person.get_role_display(),
        "staff_roles": staff_roles,
        "verification": [
            {"label": "Email verified" if person.is_email_verified else "Email not verified",
             "tone": "ok" if person.is_email_verified else "mute"},
            {"label": "Phone verified" if person.is_phone_verified else "Phone not verified",
             "tone": "ok" if person.is_phone_verified else "mute"},
            {"label": kyc["label"], "tone": kyc["tone"]},
        ],
        "kyc": kyc,
        "payout_review": payout_review,
        "actions": actions,
        "crumbs": return_crumbs(source),
    }


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


def _request_counts(person):
    counts = {}
    rows = (
        with_lifecycle(DeliveryRequest.objects.filter(sender=person))
        .values("lifecycle_status")
        .annotate(total=Count("pk"))
        .order_by()
    )
    for row in rows:
        counts[row["lifecycle_status"]] = row["total"]
    return {
        "total": sum(counts.values()),
        "active": sum(counts.get(state, 0) for state in ACTIVE_REQUEST_STATES),
    }


def _journey_counts(person):
    counts = dict(
        Journey.objects.filter(traveler=person)
        .values_list("status")
        .annotate(total=Count("pk"))
        .order_by()
    )
    return {
        "total": sum(counts.values()),
        "active": sum(counts.get(state, 0) for state in ACTIVE_JOURNEY_STATES),
    }


def _deal_counts(person):
    as_sender, as_traveler = Q(sender_id=person.pk), Q(traveler_id=person.pk)
    return Deal.objects.filter(as_sender | as_traveler).aggregate(
        total=Count("pk"),
        sender=Count("pk", filter=as_sender),
        traveler=Count("pk", filter=as_traveler),
        active=Count("pk", filter=activity_q(ACTIVE)),
        completed=Count("pk", filter=activity_q(COMPLETED)),
        cancelled=Count("pk", filter=activity_q(CANCELLED)),
        no_shows=Count(
            "pk",
            filter=(as_sender & Q(no_show_party="sender"))
            | (as_traveler & Q(no_show_party="traveler")),
        ),
        cancelled_by_person=Count("pk", filter=Q(cancelled_by_id=person.pk)),
    )


def _dispute_counts(person):
    return Dispute.objects.filter(
        Q(deal__sender=person) | Q(deal__traveler=person)
    ).aggregate(
        total=Count("pk", distinct=True),
        open=Count("pk", filter=Q(status__in=Dispute.ACTIVE_STATUSES), distinct=True),
    )


def _revealed_q(now):
    return Q(review_window_ends_at__lte=now) | Q(both_sides=True)


def _ratings_base(person):
    other_side = Rating.objects.filter(deal_id=OuterRef("deal_id")).exclude(
        rater_role=OuterRef("rater_role")
    )
    return Rating.objects.filter(Q(rater=person) | Q(ratee=person)).alias(
        both_sides=Exists(other_side)
    )


def _rating_summary(person):
    now = timezone.now()
    revealed = _revealed_q(now)
    return _ratings_base(person).aggregate(
        received_average=Avg("score", filter=revealed & Q(ratee_id=person.pk)),
        received=Count("pk", filter=revealed & Q(ratee_id=person.pk)),
        given=Count("pk", filter=revealed & Q(rater_id=person.pk)),
        hidden=Count("pk", filter=~revealed),
    )


def _payout_readiness(person):
    """The Traveler's payout setup, as the app itself reads it.

    `payout_summary` is the H6A read model the mobile app renders, so this page
    and the Traveler's own screen cannot disagree about whether they can be paid.
    It costs a constant handful of queries for one person.
    """

    from apps.finance.payout_mobile import payout_summary

    summary = payout_summary(person)
    words = {
        "ready": ("Ready", "ok"),
        "pending_review": ("Waiting for review", "attn"),
        "pending_verification": ("Stripe verifying", "wait"),
        "needs_attention": ("Needs attention", "bad"),
        "setup_required": ("Setup not finished", "attn"),
        "not_configured": ("Not set up", "mute"),
        "inactive": ("Switched off", "mute"),
    }
    preference = {
        "both": "EUR and DZD",
        "eur_only": "EUR (Stripe)",
        "dzd_only": "DZD (Algerian CCP)",
        None: "Not chosen",
    }[summary["preference"]]
    eur = words.get(summary["eur"]["state"], (summary["eur"]["state"], "mute"))
    dzd = words.get(summary["dzd"]["state"], (summary["dzd"]["state"], "mute"))
    return {
        "preference": preference,
        "eur": {"label": eur[0], "tone": eur[1], "state": summary["eur"]["state"]},
        "dzd": {"label": dzd[0], "tone": dzd[1], "state": summary["dzd"]["state"]},
        "ready": summary["eur"]["ready"] or summary["dzd"]["ready"],
        "chosen": summary["preference"] is not None,
    }


def build_overview(request, person, caps, header, source):
    facts, attention = [], []

    if caps("view_requests"):
        requests = _request_counts(person)
        facts.append({
            "label": "Parcel requests", "value": requests["active"], "unit": "active",
            "detail": f"{requests['total']} in total",
            "url": _tab_url(person, "activity", source=source, view="requests"),
        })
    else:
        requests = None
    if caps("view_journeys"):
        journeys = _journey_counts(person)
        facts.append({
            "label": "Journeys", "value": journeys["active"], "unit": "active",
            "detail": f"{journeys['total']} in total",
            "url": _tab_url(person, "activity", source=source, view="journeys"),
        })
    else:
        journeys = None
    deals = None
    if caps("view_deals"):
        deals = _deal_counts(person)
        facts.append({
            "label": "Deliveries", "value": deals["active"], "unit": "active",
            "detail": f"{deals['completed']} completed · {deals['cancelled']} cancelled",
            "url": _tab_url(person, "deliveries", source=source),
        })
    if caps("view_disputes"):
        disputes = _dispute_counts(person)
        facts.append({
            "label": "Disputes", "value": disputes["open"], "unit": "open",
            "detail": f"{disputes['total']} in total",
            "url": _tab_url(person, "trust", source=source, view="disputes"),
            "tone": "bad" if disputes["open"] else "",
        })
        if disputes["open"]:
            attention.append({
                "label": f"{disputes['open']} open dispute{'s' if disputes['open'] != 1 else ''}",
                "detail": "Payout stays frozen until it is decided.",
                "url": _tab_url(person, "trust", source=source, view="disputes"), "tone": "bad",
            })
    if caps("view_ratings"):
        ratings = _rating_summary(person)
        average = ratings["received_average"]
        facts.append({
            "label": "Rating received",
            "value": f"{average:.1f}" if average is not None else "New",
            "unit": "/ 5" if average is not None else "",
            "detail": f"{ratings['received']} revealed rating{'s' if ratings['received'] != 1 else ''}",
            "url": _tab_url(person, "trust", source=source, view="ratings"),
        })

    payout = None
    if caps(*PAYOUT_CAPS):
        payout = _payout_readiness(person)
    review = header["payout_review"]
    if review and review["bucket"] == "waiting":
        attention.append({
            "label": "Payout method waiting for approval",
            "detail": "Submitted DZD payout details need review.",
            "url": review["url"], "tone": "bad",
        })
    if header["kyc"]["state"] == "pending" and caps("view_kyc"):
        attention.append({
            "label": "ID waiting for review",
            "detail": "The Traveler cannot publish journeys until it is decided.",
            "url": reverse("admin_console:kyc-detail", args=(header["kyc"]["record"].pk,)),
            "tone": "attn",
        })

    issues = None
    if caps(*FINANCE_ISSUE_CAPS):
        issues = {"payments": 0, "payouts": 0}
        if caps("view_payment_attempts"):
            issues["payments"] = payment_attention_queryset(
                PaymentAttempt.objects.filter(order__owner=person)
            ).count()
            if issues["payments"]:
                attention.append({
                    "label": f"{issues['payments']} payment{'s' if issues['payments'] != 1 else ''} needing Finance review",
                    "detail": "An unapplied capture or amount anomaly needs a decision.",
                    "url": _tab_url(person, "payments", source=source), "tone": "bad",
                })
        if caps("view_payouts"):
            issues["payouts"] = Payout.objects.filter(
                traveler=person, status__in=(Payout.Status.FAILED, Payout.Status.BLOCKED)
            ).count()
            if issues["payouts"]:
                attention.append({
                    "label": f"{issues['payouts']} payout{'s' if issues['payouts'] != 1 else ''} failed or blocked",
                    "detail": "Open the payout to see what it is waiting for.",
                    "url": _tab_url(person, "payouts", source=source), "tone": "bad",
                })

    uses = []
    if (requests and requests["total"]) or (deals and deals["sender"]):
        uses.append("Sender")
    if (journeys and journeys["total"]) or (deals and deals["traveler"]):
        uses.append("Traveler")

    return {
        "facts": facts,
        "attention": attention,
        "payout": payout,
        "issues": issues,
        "deals": deals,
        "uses": uses,
    }


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def build_identity(request, person, caps, header, source):
    submissions = []
    if caps("view_users", "view_kyc"):
        page = _page(request, person.kyc_submissions.order_by("-created_at"))
        for row in page.object_list:
            href = reverse("admin_console:kyc-detail", args=(row.pk,)) if caps("view_kyc") else ""
            submissions.append({
                "cells": (
                    text_cell(row.get_document_type_display(), f"Submission {row.pk}",
                              href=href, opens_row=bool(href), kind="strong"),
                    status_cell(row.status, row.get_status_display()),
                    datetime_cell(row.created_at),
                    datetime_cell(row.reviewed_at),
                    text_cell(_date_text(row.expires_at) or "No expiry"),
                )
            })
        kyc_list = _list(
            ("ID document", "State", "Submitted", "Decided", "Expires"),
            submissions, page_obj=page, layout="kyc",
            empty="This person has never submitted an ID document.",
            title="ID verification",
        )
    else:
        kyc_list = None

    payout_identity = None
    if caps("review_payout_profiles", "attest_payout_identity", "view_kyc"):
        attestations = list(
            PayoutIdentityAttestation.objects.filter(traveler=person)
            .select_related("attested_by", "revocation")
            .annotate(superseded=Exists(
                PayoutIdentityAttestation.objects.filter(supersedes_id=OuterRef("pk"))
            ))
            .order_by("-attested_at", "-pk")[:10]
        )
        checks = list(
            PayoutIdentityReviewAssignment.objects.filter(traveler=person, closed_at__isnull=True)
            .select_related("reviewer")
            .order_by("-pk")[:5]
        )
        rows = []
        for row in attestations:
            revoked = hasattr(row, "revocation")
            state = ("Revoked", "bad") if revoked else ("Superseded", "mute") if row.superseded else ("Current", "ok")
            rows.append({
                "by": display_name(row.attested_by),
                "at": row.attested_at,
                "state": state[0], "tone": state[1],
                "kyc": row.kyc_submission_id,
            })
        payout_identity = {
            "attestations": rows,
            "checks": [
                {
                    "reviewer": display_name(check.reviewer),
                    "at": check.created_at,
                    "url": (
                        reverse("admin_console:identity-check-detail", args=(check.public_reference,))
                        if caps("attest_payout_identity") else ""
                    ),
                }
                for check in checks
            ],
        }

    return {
        "kyc_list": kyc_list,
        "payout_identity": payout_identity,
        "contact": {
            "email_verified": person.is_email_verified,
            "phone_verified": person.is_phone_verified,
            "phone": person.phone if caps("view_user_sensitive") else None,
            "wilaya": person.get_wilaya_display() if caps("view_user_sensitive") and person.wilaya else None,
            "sensitive": caps("view_user_sensitive"),
            "language": person.get_preferred_language_display() if person.preferred_language else "Not chosen",
        },
    }


# ---------------------------------------------------------------------------
# Activity: requests, journeys, offers
# ---------------------------------------------------------------------------


def _requests_list(request, person, caps, source):
    latest_deal = Deal.objects.filter(delivery_request_id=OuterRef("pk")).order_by("-created_at", "-pk")
    queryset = (
        with_lifecycle(DeliveryRequest.objects.filter(sender=person))
        .select_related(
            "pickup_place__parent", "pickup_place__country",
            "delivery_place__parent", "delivery_place__country",
            "pickup_location", "delivery_location",
        )
        .annotate(
            latest_deal_id=Subquery(latest_deal.values("pk")[:1]),
            latest_deal_boost=Subquery(
                DealTermsSnapshot.objects.filter(deal__delivery_request_id=OuterRef("pk"))
                .order_by("-deal__created_at", "-deal_id")
                .values("boost_amount_minor")[:1]
            ),
        )
        .order_by("-created_at", "-pk")
    )
    page = _page(request, queryset)
    rows = []
    for item in page.object_list:
        deal_href = (
            reverse("admin_console:deal-detail", args=(item.latest_deal_id,))
            if item.latest_deal_id and caps("view_deals") else ""
        )
        # The request's own Boost column is the sender's *current* intent; once a
        # Deal exists the Boost that counts is the one frozen into its terms.
        boost = item.latest_deal_boost if item.latest_deal_id else item.boost_eur_cents
        window = " – ".join(filter(None, (_date_text(item.ready_window_start), _date_text(item.ready_window_end))))
        rows.append({
            "cells": (
                text_cell(f"Request {item.pk}", parcel_summary(item), kind="strong",
                          href=deal_href, opens_row=bool(deal_href)),
                route_cell(request_route_nodes(item)),
                text_cell(window or "No ready window",
                          f"deliver by {_date_text(item.deadline_at)}" if item.deadline_at else ""),
                money_cell(item.traveler_reward_eur_cents) if item.traveler_reward_eur_cents else text_cell("—"),
                (money_cell(boost) if boost else text_cell("No Boost" if boost == 0 else "—")),
                {**status_cell(item.lifecycle_status, REQUEST_STATUS_LABELS.get(item.lifecycle_status)),
                 "secondary": f"Deal {item.latest_deal_id}" if item.latest_deal_id else ""},
                datetime_cell(item.created_at),
            )
        })
    return _list(
        ("Request", "Route", "Dates", "Reward", "Boost", "State", "Created"),
        rows, page_obj=page, layout="requests",
        empty="This person has not posted a parcel request.",
        note="State follows the delivery lifecycle. A request opens its Deal once it has one.",
    )


def _journeys_list(request, person, caps, source):
    legs = JourneyLeg.objects.select_related(
        "origin_place__parent", "origin_place__country",
        "destination_place__parent", "destination_place__country",
        "origin", "destination",
    ).order_by("position")
    queryset = (
        Journey.objects.filter(traveler=person)
        .select_related(
            "start_place__parent", "start_place__country",
            "destination_place__parent", "destination_place__country",
            "start_location", "destination_location",
        )
        .prefetch_related(Prefetch("legs", queryset=legs))
        .annotate(
            deliveries=Count("deals", filter=~Q(deals__status__in=(
                Deal.Status.CANCELLED, Deal.Status.EXPIRED, Deal.Status.REFUNDED,
                Deal.Status.PARTIALLY_REFUNDED,
            )), distinct=True),
        )
        .order_by("-created_at", "-pk")
    )
    page = _page(request, queryset)
    rows = []
    for journey in page.object_list:
        journey_legs = list(journey.legs.all())
        href = reverse("admin_console:journey-detail", args=(journey.pk,)) if caps("view_journeys") else ""
        modes = " + ".join(dict.fromkeys(leg.get_mode_display() for leg in journey_legs)) or "No legs"
        capacity = min((leg.capacity_kg for leg in journey_legs), default=None)
        rows.append({
            "cells": (
                text_cell(f"Journey {journey.pk}", modes, href=href, opens_row=bool(href), kind="strong"),
                route_cell(journey_route_nodes(journey)),
                text_cell(
                    _date_text(journey_legs[0].depart_at, "%d %b %Y, %H:%M") if journey_legs else "—",
                    f"arrives {_date_text(journey_legs[-1].arrive_at, '%d %b, %H:%M')}" if journey_legs and journey_legs[-1].arrive_at else "",
                ),
                text_cell(f"{capacity:g} kg" if capacity is not None else "—",
                          "smallest segment" if capacity is not None else ""),
                text_cell(str(journey.deliveries), "matched" if journey.deliveries else ""),
                status_cell(journey.status, journey.get_status_display()),
            )
        })
    return _list(
        ("Journey", "Route", "Dates", "Capacity", "Deliveries", "State"),
        rows, page_obj=page, layout="journeys",
        empty="This person has not published a journey.",
    )


def _offers_list(request, person, caps, source):
    queryset = (
        Offer.objects.filter(Q(match__sender=person) | Q(match__traveler=person))
        .select_related(
            "match", "match__parcel__deliveryrequest", "match__journey", "proposer", "deal__terms",
        )
        .order_by("-created_at", "-pk")
    )
    page = _page(request, queryset)
    offers = list(page.object_list)
    reader = OfferEconomicsReader()
    reader.prime([offer.match for offer in offers])
    rows = []
    for offer in offers:
        match = offer.match
        projection = reader.project(offer, match)
        deal_href = ""
        if offer.status == Offer.Status.ACCEPTED and caps("view_deals"):
            deal = getattr(offer, "deal", None) if _has_deal(offer) else None
            if deal is not None:
                deal_href = reverse("admin_console:deal-detail", args=(deal.pk,))
        person_side = "Sender" if match.sender_id == person.pk else "Traveler"
        sent_by_person = offer.proposer_id == person.pk
        legacy = offer.economics_version != Offer.EconomicsVersion.V1_EUR
        journey_href = (
            reverse("admin_console:journey-detail", args=(match.journey_id,))
            if match.journey_id and caps("view_journeys") else ""
        )
        rows.append({
            "cells": (
                text_cell(f"Offer {offer.pk}", f"Request {match.parcel_id}", kind="strong",
                          href=deal_href, opens_row=bool(deal_href)),
                text_cell(f"Journey {match.journey_id}" if match.journey_id else "—", href=journey_href),
                text_cell(f"As {person_side}", "sent by this person" if sent_by_person else f"sent by the {offer.get_proposed_by_display().lower()}"),
                status_cell(offer.status, offer.get_status_display()),
                (text_cell("Legacy DZD offer") if legacy else money_cell(offer.traveler_reward_minor)),
                (money_cell(projection["boost_amount_minor"]) if projection["boost_amount_minor"]
                 else text_cell("No Boost" if projection["boost_amount_minor"] == 0 else "—")),
                (money_cell(projection["traveler_total_minor"], emphasis=True)
                 if projection["traveler_total_minor"] is not None else text_cell("—")),
                text_cell(_date_text(offer.created_at, "%d %b %Y, %H:%M"),
                          f"{offer.get_status_display().lower()} {_date_text(offer.responded_at)}" if offer.responded_at else ""),
            )
        })
    return _list(
        ("Offer", "Journey", "Side", "State", "Base reward", "Boost", "Traveler total", "Created"),
        rows, page_obj=page, layout="offers",
        empty="No offers were sent or received by this person.",
        note=("Totals use the offer's own economics: frozen at acceptance, provisional while "
              "pending, and not shown for offers that can no longer be accepted."),
    )


def _has_deal(offer):
    try:
        offer.deal  # noqa: B018 - reverse one-to-one, joined by select_related
    except Deal.DoesNotExist:
        return False
    return True


def build_activity(request, person, caps, header, source):
    views = [(key, label) for key, label, codes in ACTIVITY_VIEWS if caps(*codes)]
    keys = [key for key, _ in views]
    current = request.GET.get("view", "")
    if current not in keys:
        current = keys[0] if keys else ""
    builders = {"requests": _requests_list, "journeys": _journeys_list, "offers": _offers_list}
    return {
        "views": [
            {"key": key, "label": label, "current": key == current,
             "url": _tab_url(person, "activity", source=source, view=key)}
            for key, label in views
        ],
        "list": builders[current](request, person, caps, source) if current else None,
    }


# ---------------------------------------------------------------------------
# Deliveries
# ---------------------------------------------------------------------------


def build_deliveries(request, person, caps, header, source):
    base = Deal.objects.filter(Q(sender=person) | Q(traveler=person))
    counts = base.aggregate(
        all=Count("pk"),
        active=Count("pk", filter=activity_q(ACTIVE)),
        completed=Count("pk", filter=activity_q(COMPLETED)),
        cancelled=Count("pk", filter=activity_q(CANCELLED)),
    )
    state = request.GET.get("state", "")
    if state not in ACTIVITY_STATES:
        state = "all"
    queryset = base if state == "all" else base.filter(activity_q(state))
    queryset = (
        queryset.select_related(
            "sender", "traveler", "terms", "payout",
            "delivery_request__pickup_place__parent", "delivery_request__pickup_place__country",
            "delivery_request__delivery_place__parent", "delivery_request__delivery_place__country",
            "delivery_request__pickup_location", "delivery_request__delivery_location",
        )
        .prefetch_related(Prefetch(
            "payment_orders",
            queryset=PaymentOrder.objects.filter(purpose=PaymentOrder.Purpose.DEAL_BALANCE).exclude(
                status=PaymentOrder.Status.CANCELLED
            ),
            to_attr="balance_orders",
        ))
        .order_by("-created_at", "-pk")
    )
    page = _page(request, queryset)
    rows = []
    for deal in page.object_list:
        is_sender = deal.sender_id == person.pk
        other = deal.traveler if is_sender else deal.sender
        order = deal.balance_orders[0] if deal.balance_orders else None
        payout = getattr(deal, "payout", None) if _has_payout(deal) else None
        rows.append({
            "cells": (
                text_cell(f"Deal {deal.pk}", _date_text(deal.created_at),
                          href=reverse("admin_console:deal-detail", args=(deal.pk,)),
                          opens_row=True, kind="strong"),
                text_cell("Sender" if is_sender else "Traveler"),
                _person_cell(other, source=""),
                route_cell(request_route_nodes(deal.delivery_request)),
                status_cell(deal.status, deal.get_status_display()),
                (status_cell(order.status, order.get_status_display()) if order
                 else text_cell("Legacy" if deal.is_legacy else "No balance order")),
                (status_cell(payout.status, payout.get_status_display()) if payout and not is_sender
                 else text_cell("—")),
                (money_cell(deal.terms.sender_total_with_boost_minor if is_sender else deal.terms.traveler_total_minor)
                 if _has_terms(deal) else text_cell("—")),
            )
        })
    segments = [
        {"key": key, "label": label, "count": counts[key], "current": key == state,
         "url": _tab_url(person, "deliveries", source=source, state=key if key != "all" else "")}
        for key, label in (("all", "All"), ("active", "Active"), ("completed", "Completed"), ("cancelled", "Cancelled"))
    ]
    return {
        "segments": segments,
        "list": _list(
            ("Deal", "Role", "Counterparty", "Route", "Lifecycle", "Payment", "Payout", "Amount"),
            rows, page_obj=page, layout="deals",
            empty="No Deals in this state.",
            note=("Delivery completion and payout completion are separate: a completed delivery "
                  "can still have a payout waiting for its protection window."),
        ),
    }


def _has_payout(deal):
    try:
        deal.payout  # noqa: B018
    except Payout.DoesNotExist:
        return False
    return True


def _has_terms(deal):
    try:
        deal.terms  # noqa: B018
    except DealTermsSnapshot.DoesNotExist:
        return False
    return True


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------


def build_payments(request, person, caps, header, source):
    queryset = (
        PaymentOrder.objects.filter(owner=person)
        .prefetch_related(Prefetch(
            "attempts",
            queryset=PaymentAttempt.objects.order_by("-created_at", "-pk"),
        ))
        .order_by("-created_at", "-pk")
    )
    page = _page(request, queryset)
    technical = caps("view_payment_attempts")
    rows = []
    for order in page.object_list:
        attempts = list(order.attempts.all())
        latest = attempts[0] if attempts else None
        subject = f"Deal {order.deal_id}" if order.deal_id else (
            f"Request {order.delivery_request_id}" if order.delivery_request_id else ""
        )
        provider = "No attempt yet"
        provider_detail = ""
        if latest is not None:
            provider = latest.get_provider_display()
            provider_detail = (
                f"{latest.get_status_display()} · "
                f"{format_minor_amount(latest.provider_amount_minor, latest.provider_amount_exponent, latest.payment_currency)}"
            )
        href = (
            reverse("admin_console:payment-detail", args=(latest.pk,))
            if latest is not None and technical else ""
        )
        row = {
            "cells": (
                text_cell(order.get_purpose_display(), subject, kind="strong", href=href, opens_row=bool(href)),
                money_cell(order.amount_eur_cents, emphasis=True),
                text_cell(f"Paid {format_eur(order.paid_eur_cents)}",
                          f"Refunded {format_eur(order.refunded_eur_cents)}" if order.refunded_eur_cents else
                          (f"Credited {format_eur(order.credited_eur_cents)}" if order.credited_eur_cents else "")),
                text_cell(provider, provider_detail),
                status_cell(order.status, order.get_status_display()),
                datetime_cell(order.created_at),
            ),
        }
        if technical:
            # Provider references only, and only behind a disclosure. No checkout
            # URL, idempotency key or provider secret is ever read here.
            row["technical"] = [
                {"label": "Order reference", "value": str(order.public_reference)},
                *[
                    {
                        "label": f"Attempt {attempt.pk} · {attempt.get_provider_display()} · {attempt.provider_mode}",
                        "value": attempt.provider_payment_id or attempt.provider_session_id or "No provider reference yet",
                    }
                    for attempt in attempts[:5]
                ],
            ]
        rows.append(row)
    return {
        "list": _list(
            ("Purpose", "Amount", "Collected", "Provider", "State", "Created"),
            rows, page_obj=page, layout="payments",
            empty="This person owes no payment obligations.",
            note="Amounts are the canonical EUR obligation. A DZD payment shows what Chargily charged beside it.",
        ),
    }


# ---------------------------------------------------------------------------
# Payouts
# ---------------------------------------------------------------------------


def build_payouts(request, person, caps, header, source):
    from .console_payout_reviews import DECISIONS

    readiness = _payout_readiness(person)
    dzd = None
    method = (
        TravelerPayoutMethod.objects.filter(traveler=person, currency="DZD")
        .select_related("current_version__dzd_profile_revision")
        .first()
    )
    profile = method.current_version.dzd_profile_revision if method and method.current_version_id else None
    if profile is not None:
        latest = (
            profile.reviews.select_related("reviewer").order_by("-pk").first()
        )
        dzd = {
            "revision": profile.sequence,
            "submitted_at": profile.submitted_at,
            "revisions": method.dzd_revisions.count(),
            "latest": (
                {"label": DECISIONS[latest.status][1], "tone": DECISIONS[latest.status][2],
                 "by": display_name(latest.reviewer), "at": latest.created_at}
                if latest else None
            ),
            "review": header["payout_review"],
            "may_review": caps("review_payout_profiles"),
        }
    stripe = None
    if caps("view_finance_summary", "view_payouts"):
        account = (
            StripePayoutAccount.objects.filter(traveler=person, active=True)
            .order_by("-created_at").first()
        )
        if account is not None:
            stripe = {
                "status": account.status.replace("_", " ").capitalize(),
                "payouts_enabled": account.payouts_enabled,
                "bank": account.eur_bank_present,
                "checked_at": account.readiness_checked_at,
                "country": account.verified_country or account.declared_country,
            }

    history = None
    if caps("view_payouts"):
        queryset = (
            Payout.objects.filter(traveler=person)
            .select_related("deal")
            .annotate(
                receipts=Count("attempts__manual_receipts", distinct=True),
                confirmed_receipts=Count(
                    "attempts__manual_receipts",
                    filter=Q(attempts__manual_receipts__completed_attested=True),
                    distinct=True,
                ),
            )
            .order_by("-created_at", "-pk")
        )
        page = _page(request, queryset)
        rows = []
        for payout in page.object_list:
            manual_dzd = payout.method == Payout.Method.MANUAL and payout.payout_currency == "DZD"
            rail = "Manual DZD transfer" if manual_dzd else payout.get_method_display()
            settlement = (
                format_minor_amount(payout.payout_amount_minor, payout.payout_amount_exponent or 0, payout.payout_currency)
                if payout.payout_currency and payout.payout_currency != "EUR" else ""
            )
            receipt = "—"
            if manual_dzd:
                receipt = (
                    "Transfer confirmed" if payout.confirmed_receipts
                    else "Receipt attached" if payout.receipts else "No receipt yet"
                )
            rows.append({
                "cells": (
                    text_cell(f"Deal {payout.deal_id}", str(payout.public_reference)[:8],
                              href=reverse("admin_console:payout-detail", args=(payout.pk,)),
                              opens_row=True, kind="strong"),
                    money_pair_cell(payout.amount_eur_cents, settlement),
                    text_cell(rail),
                    status_cell(payout.status, payout.get_status_display()),
                    text_cell(_date_text(payout.paid_at, "%d %b %Y, %H:%M") or "Not paid",
                              f"eligible {_date_text(payout.eligible_at)}" if payout.eligible_at else ""),
                    text_cell(receipt),
                    datetime_cell(payout.created_at),
                )
            })
        history = _list(
            ("Payout", "Amount", "Method", "State", "Paid", "Transfer receipt", "Created"),
            rows, page_obj=page, layout="payouts",
            empty="No payouts have been created for this person.",
        )
    return {"readiness": readiness, "dzd": dzd, "stripe": stripe, "history": history}


# ---------------------------------------------------------------------------
# Trust & support
# ---------------------------------------------------------------------------


def _disputes_list(request, person, caps, source):
    queryset = (
        Dispute.objects.filter(Q(deal__sender=person) | Q(deal__traveler=person))
        .select_related("deal", "opened_by")
        .order_by("-opened_at", "-pk")
    )
    page = _page(request, queryset)
    rows = []
    for dispute in page.object_list:
        deal_href = reverse("admin_console:deal-detail", args=(dispute.deal_id,)) if caps("view_deals") else ""
        rows.append({
            "cells": (
                text_cell(str(dispute.public_reference)[:8], dispute.get_category_display(),
                          href=reverse("admin_console:dispute-detail", args=(dispute.pk,)),
                          opens_row=True, kind="strong"),
                text_cell(f"Deal {dispute.deal_id}", href=deal_href),
                _person_cell(dispute.opened_by, secondary=dispute.get_opened_by_role_display(), self_id=person.pk),
                status_cell(dispute.status, dispute.get_status_display()),
                datetime_cell(dispute.opened_at),
                text_cell(dispute.get_resolution_display() if dispute.resolution else "—",
                          _date_text(dispute.resolved_at)),
            )
        })
    return _list(
        ("Dispute", "Deal", "Opened by", "State", "Opened", "Resolution"),
        rows, page_obj=page, layout="disputes",
        empty="This person has not been part of a dispute.",
    )


def _ratings_list(request, person, caps, source):
    now = timezone.now()
    base = _ratings_base(person)
    queryset = (
        base.filter(_revealed_q(now))
        .select_related("rater", "ratee", "deal")
        .order_by("-created_at", "-pk")
    )
    page = _page(request, queryset)
    hidden = base.exclude(_revealed_q(now)).count()
    rows = []
    for rating in page.object_list:
        received = rating.ratee_id == person.pk
        other = rating.rater if received else rating.ratee
        rows.append({
            "cells": (
                text_cell("Received" if received else "Given", kind="strong"),
                _person_cell(other),
                text_cell(f"{rating.score} / 5", "★" * rating.score),
                datetime_cell(rating.created_at),
                text_cell(f"Deal {rating.deal_id}",
                          href=reverse("admin_console:deal-detail", args=(rating.deal_id,)) if caps("view_deals") else ""),
            )
        })
    note = ""
    if hidden:
        note = (f"{hidden} rating{'s are' if hidden != 1 else ' is'} still inside the blind review "
                "window and not shown, exactly as the app keeps it from the other party.")
    return _list(
        ("Direction", "Counterparty", "Score", "Date", "Deal"),
        rows, page_obj=page, layout="ratings",
        empty="No revealed ratings yet.", note=note,
    )


def _notifications_list(request, person, caps, source):
    queryset = (
        Notification.objects.filter(recipient=person)
        .annotate(deal_ref=KeyTextTransform("deal_id", "payload"))
        .only("pk", "channel", "created_at", "read_at")
        .order_by("-created_at", "-pk")
    )
    page = _page(request, queryset)
    rows = []
    for item in page.object_list:
        deal_ref = str(item.deal_ref or "")
        rows.append({
            "cells": (
                text_cell(humanize_action(item.channel), kind="strong"),
                text_cell(f"Deal {deal_ref}" if deal_ref.isdigit() else "—",
                          href=reverse("admin_console:deal-detail", args=(int(deal_ref),))
                          if deal_ref.isdigit() and caps("view_deals") else ""),
                datetime_cell(item.created_at),
                {"primary": "Read" if item.read_at else "Unread", "kind": "status",
                 "tone": "mute" if item.read_at else "info"},
            )
        })
    return _list(
        ("Notification", "About", "Sent", "State"),
        rows, page_obj=page, layout="notifications",
        empty="No in-app notifications have been sent to this person.",
        note="What was sent and whether it was read. Message contents are not shown.",
    )


def build_trust(request, person, caps, header, source):
    views = [(key, label) for key, label, codes in TRUST_VIEWS if caps(*codes)]
    keys = [key for key, _ in views]
    current = request.GET.get("view", "")
    if current not in keys:
        current = keys[0] if keys else ""
    summary = None
    if caps("view_deals", "view_disputes"):
        deals = _deal_counts(person) if caps("view_deals") else None
        disputes = _dispute_counts(person) if caps("view_disputes") else None
        summary = {"deals": deals, "disputes": disputes}
    builders = {"disputes": _disputes_list, "ratings": _ratings_list, "notifications": _notifications_list}
    return {
        "summary": summary,
        "views": [
            {"key": key, "label": label, "current": key == current,
             "url": _tab_url(person, "trust", source=source, view=key)}
            for key, label in views
        ],
        "list": builders[current](request, person, caps, source) if current else None,
    }


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def _ids(queryset):
    return queryset.annotate(_audit_id=Cast("pk", CharField())).values("_audit_id")


def audit_about_q(person) -> Q:
    """Audit rows whose target is this person or a record that belongs to them.

    One indexed `(target_type, target_id)` predicate per record type, OR'd into
    one query. Record types are listed explicitly rather than discovered, so a
    new audited model is a deliberate addition here, not a silent leak.
    """

    parties = Q(sender=person) | Q(traveler=person)
    targets = {
        "accounts.user": None,
        "kyc.kycsubmission": KycSubmission.objects.filter(user=person),
        "finance.travelerpayoutmethod": TravelerPayoutMethod.objects.filter(traveler=person),
        "finance.dzdpayoutprofilerevision": DzdPayoutProfileRevision.objects.filter(method__traveler=person),
        "finance.payoutidentityattestation": PayoutIdentityAttestation.objects.filter(traveler=person),
        "finance.payoutidentityreviewassignment": PayoutIdentityReviewAssignment.objects.filter(traveler=person),
        "finance.payoutevidence": PayoutEvidence.objects.filter(owner=person),
        "finance.stripepayoutaccount": StripePayoutAccount.objects.filter(traveler=person),
        "finance.payout": Payout.objects.filter(traveler=person),
        "finance.financehold": FinanceHold.objects.filter(
            Q(payout__traveler=person) | Q(deal__sender=person) | Q(deal__traveler=person)
        ),
        "finance.paymentattempt": PaymentAttempt.objects.filter(order__owner=person),
        "finance.paymentrefund": PaymentRefund.objects.filter(order__owner=person),
        "deals.deal": Deal.objects.filter(parties),
        "disputes.dispute": Dispute.objects.filter(Q(deal__sender=person) | Q(deal__traveler=person)),
        "disputes.disputeevidence": DisputeEvidence.objects.filter(
            Q(dispute__deal__sender=person) | Q(dispute__deal__traveler=person)
        ),
    }
    condition = Q(target_type="accounts.user", target_id=str(person.pk))
    for target_type, queryset in targets.items():
        if queryset is not None:
            condition |= Q(target_type=target_type, target_id__in=_ids(queryset))
    return condition


#: Record types as an operator names them. Anything unlisted falls back to the
#: console's generic wording.
AUDIT_RECORDS = {
    "accounts.user": "Account",
    "kyc.kycsubmission": "ID submission",
    "finance.travelerpayoutmethod": "Payout method",
    "finance.dzdpayoutprofilerevision": "DZD payout details",
    "finance.payoutidentityattestation": "Identity confirmation",
    "finance.payoutidentityreviewassignment": "Identity check",
    "finance.payoutevidence": "Payout document",
    "finance.stripepayoutaccount": "Stripe payout account",
    "finance.payout": "Payout",
    "finance.financehold": "Finance hold",
    "finance.paymentattempt": "Payment",
    "finance.paymentrefund": "Refund",
    "deals.deal": "Deal",
    "disputes.dispute": "Dispute",
    "disputes.disputeevidence": "Dispute evidence",
}

#: Recorded automatically every time a review page computes the name check, so
#: a single look at a payout method writes several. They remain in the full
#: audit log; on a person's page they would bury the decisions.
AUDIT_AUTOMATIC = ("payout_identity.compared",)


def build_audit(request, person, caps, header, source):
    views = [("about", "About this person")]
    if person.is_staff:
        views.append(("by", "Actions by this person"))
    current = request.GET.get("view", "")
    if current not in dict(views):
        current = "about"
    queryset = AdminAuditLog.objects.select_related("actor")
    queryset = (
        queryset.filter(actor=person)
        if current == "by"
        else queryset.filter(audit_about_q(person)).exclude(action__in=AUDIT_AUTOMATIC)
    )
    page = _page(request, queryset.order_by("-created_at", "-id"))
    rows = []
    for entry in page.object_list:
        rows.append({
            "cells": (
                datetime_cell(entry.created_at),
                text_cell(humanize_action(entry.action), entry.reason[:120] if entry.reason else "", kind="strong"),
                (_person_cell(entry.actor, self_id=person.pk) if entry.actor_id else text_cell("System")),
                text_cell(
                    AUDIT_RECORDS.get(entry.target_type)
                    or (humanize_object(entry.target_type) if entry.target_type else "—"),
                    f"#{entry.target_id}" if entry.target_id else "",
                ),
            )
        })
    return {
        "views": [
            {"key": key, "label": label, "current": key == current,
             "url": _tab_url(person, "audit", source=source, view=key)}
            for key, label in views
        ],
        "list": _list(
            ("When", "What happened", "By", "Record"),
            rows, page_obj=page, layout="audit",
            empty="No audited administrative action concerns this person.",
            note=("Account, identity, payout, payment, Deal and dispute actions. Values are never "
                  "recorded, only that an action happened. Automatic name checks are in the full audit log."),
        ),
    }


BUILDERS = {
    "overview": build_overview,
    "identity": build_identity,
    "activity": build_activity,
    "deliveries": build_deliveries,
    "payments": build_payments,
    "payouts": build_payouts,
    "trust": build_trust,
    "audit": build_audit,
}


# ---------------------------------------------------------------------------
# The view
# ---------------------------------------------------------------------------


@capability_required(*PROFILE_CAPABILITIES)
def person_profile(request, pk: int):
    person = get_object_or_404(User, pk=pk)
    caps = Capabilities(request.user)
    source = _source(request)
    tabs = [(key, label) for key, label, codes in TABS if not codes or caps(*codes)]
    keys = [key for key, _ in tabs]
    tab = request.GET.get("tab", "")
    if tab not in keys:
        tab = "overview"
    header = _header(request, person, caps, source=source)
    body = BUILDERS[tab](request, person, caps, header, source)
    return _render(
        request,
        "admin/console/person.html",
        {
            "title": header["name"],
            "person": person,
            "header": header,
            "tab": tab,
            "tabs": [
                {"key": key, "label": label, "current": key == tab,
                 "url": _tab_url(person, key, source=source)}
                for key, label in tabs
            ],
            "body": body,
            "source": source,
            "page_query": _query_without_page(request),
            "caps": {
                "payouts": caps(*PAYOUT_CAPS),
                "view_payouts": caps("view_payouts"),
                "review_payout_profiles": caps("review_payout_profiles"),
            },
        },
    )
