"""Task-focused HTML operations console built on ShipTrip's audited services.

The REST operations surface remains available for integrations. These views
serve the nontechnical owner/operator: queues, coherent context and explicit
actions in operator units. Every mutating route checks the same named
capability as its API counterpart and delegates to the same domain service.
"""

from __future__ import annotations

import logging
import os
from copy import deepcopy
from datetime import timedelta
from functools import wraps

import redis
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import connection, transaction
from django.db.models import Avg, Count, Prefetch, Q
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.core.admin_display import (
    format_eur,
    humanize_action,
    humanize_object,
    tone_for,
)
from apps.core.business_settings import (
    activate_business_settings,
    calculate_offer_economics,
    get_active_business_settings,
)
from apps.core.models import BusinessSettingsVersion
from apps.core.policy_display import boost_packages, policy_rows
from apps.core.storage import store_for_bucket, storage_for
from apps.deals.models import Deal, DealEvent
from apps.disputes.models import Dispute, DisputeEvidence
from apps.disputes.services import (
    DisputeError,
    evidence_download_url,
    preview_dispute_resolution,
    resolve_dispute,
    set_dispute_status,
)
from apps.finance.models import (
    LedgerEntry,
    LedgerTransaction,
    PaymentAttempt,
    PaymentProvider,
    PaymentProviderEvent,
    PaymentRefund,
    Payout,
    ScheduledJob,
)
from apps.finance.policy import InvalidPaymentPolicy, phase3_policy
from apps.finance.providers import (
    MODE_LIVE,
    MODE_NOT_CONFIGURED,
    MODE_TEST,
    MODE_UNKNOWN,
    available_providers,
)
from apps.finance.services import (
    complete_manual_payout,
    request_refund as request_payment_refund,
    settle_refund_manually,
)
from apps.finance.settlement import read_deal_money
from apps.core.financial_locks import lock_deal_aggregate
from apps.kyc.models import KycSubmission
from apps.locations.models import (
    AirportLocalityMapping,
    Country,
    GeographyCatalogueImport,
    Place,
)
from apps.notifications.models import OutboundMessage
from apps.parcels.models import DeliveryRequest
from apps.routing.providers import route_provider_status
from apps.trips.models import Journey, JourneyLeg, JourneyLegProof
from apps.trips.services import has_current_kyc_approval

from .console_forms import (
    DisputeResolutionForm,
    DisputeStatusForm,
    FxSettingsForm,
    InvitationForm,
    ManualPayoutForm,
    ManualRefundForm,
    PricingSettingsForm,
    ProviderSettingsForm,
    RefundRequestForm,
    ReviewDecisionForm,
    RoleChangeForm,
    StaffAccessForm,
)
from .console_presenters import (
    age_label,
    datetime_cell,
    decimal_eur,
    decimal_micros,
    format_minor_amount,
    journey_route,
    journey_route_nodes,
    money_cell,
    money_pair_cell,
    parcel_summary,
    percent_from_bps,
    place_label,
    place_node,
    ref_cell,
    request_route,
    request_route_nodes,
    route_cell,
    status_cell,
    text_cell,
)
from .health import storage_health
from .models import AdminAuditLog, AdminInvitation
from .ops_serializers import AdminSettingsCreateSerializer
from .permissions import (
    AdminRole,
    ROLE_GROUP_NAMES,
    ROLE_PERMISSIONS,
    has_admin_permission,
    user_admin_roles,
)
from .services import (
    change_admin_role,
    create_admin_invitation,
    record_admin_action,
    review_flight_proof,
    review_kyc_submission,
    revoke_admin_invitation,
    set_admin_access,
)

logger = logging.getLogger(__name__)
User = get_user_model()


ROLE_DESCRIPTIONS = {
    AdminRole.OPS: (
        "Runs marketplace operations: delivery requests, journeys, Deals, "
        "lifecycle incidents, ratings and boosts."
    ),
    AdminRole.SUPPORT: (
        "Views users, Deals and disputes for support. Cannot review private "
        "verification evidence or change finance settings."
    ),
    AdminRole.FINANCE: (
        "Handles payments, refunds, payouts, ledger reconciliation and finance "
        "worker queues. Cannot read private evidence."
    ),
    AdminRole.TRUST: (
        "Reviews KYC, flight proofs and dispute evidence, with relevant user "
        "and Deal context."
    ),
    AdminRole.SUPER_ADMIN: (
        "Owner access to every console area, staff roles and business settings."
    ),
}


def capability_required(*codes: str):
    """Require staff authentication and at least one named admin capability."""

    def decorator(view):
        @staff_member_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not any(has_admin_permission(request.user, code) for code in codes):
                raise PermissionDenied(
                    "You do not have permission to use this operations area."
                )
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def _render(request, template: str, context: dict | None = None, *, status=200):
    payload = {
        **admin.site.each_context(request),
        "is_console": True,
        "request_id": getattr(request, "request_id", ""),
        **(context or {}),
    }
    # Render to a concrete response so each guided console route has stable
    # HTML semantics (the technical Django admin remains lazy where it needs
    # its own changelist context). The request is passed through so admin
    # context processors and CSRF helpers behave normally.
    response = render(request, template, payload, status=status)
    response["Cache-Control"] = "private, no-store"
    return response


def _operation_error(request, label: str, exc: Exception) -> None:
    code = getattr(exc, "code", "operation_failed")
    logger.exception(
        "admin_console.operation_failed action=%s code=%s request_id=%s",
        label,
        code,
        getattr(request, "request_id", ""),
    )
    reference = getattr(request, "request_id", "")
    suffix = f" Reference: {reference}." if reference else ""
    messages.error(
        request,
        f"{label} could not be completed ({code}). "
        f"Review the current record before retrying.{suffix}",
    )


def _query_without_page(request) -> str:
    query = request.GET.copy()
    query.pop("page", None)
    return query.urlencode()


def _page(request, queryset, *, page_size: int = 50):
    return Paginator(queryset, page_size).get_page(request.GET.get("page"))


def _table(
    request,
    *,
    title: str,
    description: str,
    columns: tuple[str, ...],
    rows: list[dict],
    page_obj,
    empty_title: str,
    empty_text: str,
    filter_choices: tuple[tuple[str, str], ...] = (),
    search_placeholder: str = "Search",
    actions: tuple[dict, ...] = (),
    eyebrow: str = "Operations",
):
    # A column of amounts has to line up under a header that agrees with it, or
    # the alignment reads as an accident. The cell kind already says which
    # columns hold money, so nothing has to be declared twice.
    numeric_kinds = {"money", "money-lead", "money-pair"}
    first = rows[0]["cells"] if rows else ()
    column_specs = [
        {
            "label": label,
            "numeric": index < len(first)
            and first[index].get("kind", "") in numeric_kinds,
        }
        for index, label in enumerate(columns)
    ]
    return _render(
        request,
        "admin/console/table.html",
        {
            "title": title,
            "eyebrow": eyebrow,
            "description": description,
            "columns": column_specs,
            "rows": rows,
            "page_obj": page_obj,
            "query_without_page": _query_without_page(request),
            "empty_title": empty_title,
            "empty_text": empty_text,
            "filter_choices": filter_choices,
            "current_status": request.GET.get("status", ""),
            "query": request.GET.get("q", ""),
            "search_placeholder": search_placeholder,
            "actions": actions,
        },
    )


def _leg_route_nodes(leg) -> list[dict]:
    """Origin and destination of one leg, carrying the mode that joins them."""

    origin = place_node(leg.origin_place, getattr(leg.origin, "public_label", ""))
    destination = place_node(
        leg.destination_place, getattr(leg.destination, "public_label", "")
    )
    destination["mode"] = leg.mode
    destination["mode_label"] = leg.get_mode_display()
    destination["flight_number"] = leg.flight_number or ""
    return [origin, destination]


def _filter_choice(queryset, request, *, field="status"):
    value = request.GET.get(field, "").strip()
    if not value:
        return queryset
    model_field = queryset.model._meta.get_field(field)
    allowed = {key for key, _label in model_field.choices}
    if value in allowed:
        return queryset.filter(**{field: value})
    return queryset.none()


def _search(queryset, request, fields: tuple[str, ...]):
    query = request.GET.get("q", "").strip()[:200]
    if not query:
        return queryset
    condition = Q()
    for field in fields:
        condition |= Q(**{f"{field}__icontains": query})
    return queryset.filter(condition)


#: What each private store holds, in the operator's own words. The label is the
#: point: "kyc" is a bucket name, "Identity evidence" is what breaks when it is
#: unreachable.
_STORAGE_LABELS = {
    "parcel": ("Parcel photos and private media", "Item photos senders upload."),
    "proof": ("Flight proof", "Boarding passes and tickets awaiting review."),
    "dispute": ("Dispute evidence", "Files parties attach to a dispute."),
    "kyc": ("Identity evidence", "KYC documents and selfies awaiting review."),
}


def _storage_rows() -> list[dict]:
    """Per-class object storage readiness, each probed with its own credential.

    Separate rows rather than one verdict, because the failure this replaces
    was precisely a single verdict: the media bucket answered, the console said
    storage was fine, and KYC evidence had been unreadable for weeks. A bucket
    name is not access and a presigned URL is not access — only a request is.
    """

    rows: list[dict] = []
    health = storage_health()
    classes = health.get("classes", {}) if isinstance(health, dict) else {}
    for name in ("parcel", "proof", "dispute", "kyc"):
        entry = classes.get(name) or {}
        label, purpose = _STORAGE_LABELS[name]
        credential = entry.get("credential", "")
        if not entry.get("bucket_configured"):
            state, tone, detail = (
                "Not configured",
                "bad",
                f"{purpose} No bucket is configured, so nothing can be stored or reviewed.",
            )
        elif entry.get("reachable"):
            state, tone, detail = (
                "Reachable",
                "ok",
                f"{purpose} Answered with the {credential} credential.",
            )
        else:
            state, tone, detail = (
                "Unreachable",
                "bad",
                f"{purpose} The {credential} credential was refused or the store "
                "did not answer; evidence will show as temporarily unavailable.",
            )
        rows.append(
            {"name": label, "label": state, "tone": tone, "detail": detail}
        )
    return rows


def _provider_rows() -> list[dict]:
    rows: list[dict] = []
    try:
        policy = phase3_policy()
        for item in available_providers(policy):
            if item.provider not in (PaymentProvider.STRIPE, PaymentProvider.CHARGILY):
                continue
            if item.available:
                label, tone, detail = "Enabled", "ok", "Ready for new checkouts."
            elif item.enabled and item.configured and not item.configuration_valid:
                # The state this phase exists to stop being invisible: the
                # operator switched the rail on, the deployment holds a key, and
                # the configuration still describes an environment nobody can
                # identify. "Enabled" would be a lie and "Disabled" would send
                # them to the wrong switch.
                label, tone, detail = (
                    "Enabled, but unavailable",
                    "bad",
                    "Enabled in business settings and refused for new checkouts: "
                    "the deployment's credentials and API environment do not "
                    "agree, so which environment this rail would transact in "
                    "cannot be established.",
                )
            elif item.enabled and not item.configured:
                label, tone, detail = (
                    "Configuration incomplete",
                    "bad",
                    "Enabled in business settings, but deployment credentials are incomplete.",
                )
            elif item.configured and not item.enabled:
                label, tone, detail = (
                    "Configured but disabled",
                    "wait",
                    "Credentials are present; business settings do not offer this rail.",
                )
            elif item.enabled and not item.accepts_new_checkouts:
                label, tone, detail = (
                    "New checkouts disabled",
                    "wait",
                    "Existing webhooks and reconciliation remain available.",
                )
            else:
                label, tone, detail = (
                    "Disabled",
                    "mute",
                    "The rail is not available for new payments.",
                )
            # Which rail the credentials point at, from their documented shape
            # rather than their value. An operator on a private pre-launch
            # deployment has to be able to see that nothing is armed against
            # real money, and "read the key and check the prefix" is not an
            # acceptable way to find that out.
            mode = {
                MODE_TEST: "Test credentials.",
                MODE_LIVE: "LIVE credentials — real money.",
                MODE_UNKNOWN: "Credential environment could not be identified.",
                MODE_NOT_CONFIGURED: "",
            }.get(item.credential_mode, "")
            if mode:
                detail = f"{detail} {mode}"
                if item.credential_mode == MODE_UNKNOWN and tone == "ok":
                    tone = "wait"
            rows.append(
                {
                    "name": item.provider.title(),
                    "label": label,
                    "tone": tone,
                    "detail": detail,
                }
            )
    except InvalidPaymentPolicy:
        rows.extend(
            {
                "name": name,
                "label": "Configuration incomplete",
                "tone": "bad",
                "detail": "The active payment policy could not be read.",
            }
            for name in ("Stripe", "Chargily")
        )

    email_enabled = bool(getattr(settings, "TRANSACTIONAL_EMAIL_ENABLED", False))
    email_configured = bool(
        getattr(settings, "EMAIL_HOST", "")
        and getattr(settings, "DEFAULT_FROM_EMAIL", "")
        and getattr(settings, "EMAIL_SENDING_DOMAIN_VERIFIED", False)
    )
    if email_enabled and email_configured:
        label, tone, detail = "Enabled", "ok", "Transactional dispatch is enabled."
    elif email_enabled:
        label, tone, detail = (
            "Configuration incomplete",
            "bad",
            "Email is enabled but required deployment configuration is incomplete.",
        )
    elif email_configured:
        label, tone, detail = (
            "Configured but disabled",
            "wait",
            "Configuration is present; dispatch remains off.",
        )
    else:
        label, tone, detail = (
            "Disabled",
            "mute",
            "External transactional sending is inactive.",
        )
    rows.append({"name": "Email", "label": label, "tone": tone, "detail": detail})
    return rows


def _attention_items(user) -> list[dict]:
    items: list[dict] = []

    def add(permission, title, hint, count, route, query="", tone="attn"):
        if not has_admin_permission(user, permission):
            return
        url = reverse(route)
        if query:
            url = f"{url}{query}" if query.startswith("#") else f"{url}?{query}"
        items.append(
            {
                "title": title,
                "hint": hint,
                "count": int(count),
                "url": url,
                "tone": tone if count else "mute",
            }
        )

    add(
        "view_kyc",
        "KYC submissions to review",
        "Travelers remain blocked from publishing until these are decided.",
        KycSubmission.objects.filter(status=KycSubmission.Status.PENDING).count(),
        "admin_console:kyc-queue",
        "status=pending",
    )
    add(
        "view_flight_proofs",
        "Flight proofs to review",
        "Flight legs are not matchable until their proof is approved.",
        JourneyLegProof.objects.filter(status=JourneyLegProof.Status.PENDING).count(),
        "admin_console:proof-queue",
        "status=pending",
    )
    add(
        "view_disputes",
        "Open disputes",
        "Payout stays frozen while an active dispute needs a decision.",
        Dispute.objects.filter(status__in=Dispute.ACTIVE_STATUSES).count(),
        "admin_console:disputes",
        "attention=1",
        "bad",
    )
    add(
        "view_payment_attempts",
        "Failed or unapplied payments",
        "Captured or attempted money needs finance review.",
        PaymentAttempt.objects.filter(
            Q(status=PaymentAttempt.Status.FAILED) | Q(is_unapplied=True)
        ).count(),
        "admin_console:payments",
        "attention=1",
        "bad",
    )
    add(
        "issue_refunds",
        "Refunds requiring operator action",
        "Automatic settlement is blocked or has exhausted retries.",
        PaymentRefund.objects.filter(
            requires_manual_action=True,
            status__in=(PaymentRefund.Status.PENDING, PaymentRefund.Status.PROCESSING),
        ).count(),
        "admin_console:refunds",
        "manual=1",
        "bad",
    )
    add(
        "view_payouts",
        "Payouts requiring action",
        "Eligible manual payouts and failed releases are waiting.",
        Payout.objects.filter(
            Q(status=Payout.Status.FAILED)
            | Q(status=Payout.Status.ELIGIBLE, method=Payout.Method.MANUAL)
        ).count(),
        "admin_console:payouts",
        "attention=1",
        "bad",
    )
    add(
        "view_provider_health",
        "Failed transactional email",
        "The obligation is durable, but delivery has not succeeded.",
        OutboundMessage.objects.filter(status=OutboundMessage.Status.FAILED).count(),
        "admin_console:email",
        "status=failed",
        "bad",
    )
    add(
        "view_scheduled_jobs",
        "Failed background jobs",
        "Investigate the stored error before requeueing the job.",
        ScheduledJob.objects.filter(status=ScheduledJob.Status.FAILED).count(),
        "admin_console:jobs",
        "status=failed",
        "bad",
    )
    if has_admin_permission(user, "view_provider_health"):
        warnings = sum(1 for row in _provider_rows() if row["tone"] == "bad")
        add(
            "view_provider_health",
            "Provider configuration warnings",
            "A provider is enabled without the configuration required to operate.",
            warnings,
            "admin_console:system",
            "#providers",
            "bad",
        )
    return items


@capability_required("view_dashboard")
def overview(request):
    attention = _attention_items(request.user)
    # "Nothing to do" and "not checked" must never look the same, so a cleared
    # queue stays on the page - filed below the work rather than mixed into it.
    raised_items = [item for item in attention if item["count"]]
    clear_items = [item for item in attention if not item["count"]]
    raised = len(raised_items)
    recent = []
    if has_admin_permission(request.user, "view_audit_log"):
        recent = list(AdminAuditLog.objects.select_related("actor")[:6])
    return _render(
        request,
        "admin/console/overview.html",
        {
            "title": "What needs attention",
            "attention": attention,
            "raised_items": raised_items,
            "clear_items": clear_items,
            "raised": raised,
            "providers": (
                _provider_rows()
                if has_admin_permission(request.user, "view_provider_health")
                else []
            ),
            "recent_audit": recent,
        },
    )


@capability_required("view_users")
def users(request):
    queryset = _search(
        User.objects.prefetch_related("kyc_submissions")
        .annotate(
            request_count=Count("parcel_requests", distinct=True),
            journey_count=Count("journeys", distinct=True),
            sent_deal_count=Count("deals_as_sender", distinct=True),
            carried_deal_count=Count("deals_as_traveler", distinct=True),
        )
        .order_by("-date_joined"),
        request,
        ("email", "full_name"),
    )
    account = request.GET.get("status")
    if account == "active":
        queryset = queryset.filter(is_active=True, is_banned=False)
    elif account == "restricted":
        queryset = queryset.filter(Q(is_active=False) | Q(is_banned=True))
    page_obj = _page(request, queryset)
    rows = []
    for user in page_obj.object_list:
        submissions = sorted(
            user.kyc_submissions.all(), key=lambda item: item.created_at, reverse=True
        )
        latest = submissions[0] if submissions else None
        account_value = (
            "banned" if user.is_banned else ("active" if user.is_active else "disabled")
        )
        deal_count = user.sent_deal_count + user.carried_deal_count
        counted = [
            f"{count} {noun}"
            for count, noun in (
                (user.request_count, "requests"),
                (user.journey_count, "journeys"),
                (deal_count, "Deals"),
            )
            if count
        ]
        activity = " · ".join(counted) if counted else "No marketplace activity"

        rows.append(
            {
                "cells": (
                    text_cell(
                        user.full_name or "Name not provided",
                        user.email,
                        href=reverse("admin_console:user-detail", args=(user.pk,)),
                        kind="strong",
                    ),
                    text_cell(user.get_role_display()),
                    status_cell(account_value),
                    status_cell(
                        latest.status if latest else "none",
                        latest.get_status_display() if latest else "Not submitted",
                    ),
                    text_cell(activity),
                    datetime_cell(user.date_joined, relative=True),
                )
            }
        )
    return _table(
        request,
        title="Users",
        description="Identity, marketplace role, verification state and account restrictions.",
        eyebrow="People",
        columns=(
            "Person",
            "Marketplace role",
            "Account",
            "Identity",
            "Activity",
            "Joined",
        ),
        rows=rows,
        page_obj=page_obj,
        empty_title="No users found",
        empty_text="Try a different name, email or account filter.",
        filter_choices=(("active", "Active"), ("restricted", "Restricted")),
        search_placeholder="Search name or email",
    )


@capability_required("view_users")
def user_detail(request, pk: int):
    user = get_object_or_404(User.objects.prefetch_related("groups"), pk=pk)
    kyc = list(user.kyc_submissions.order_by("-created_at")[:10])
    stats = {
        "requests": DeliveryRequest.objects.filter(sender=user).count(),
        "journeys": Journey.objects.filter(traveler=user).count(),
        "deals": Deal.objects.filter(Q(sender=user) | Q(traveler=user)).count(),
        "disputes": Dispute.objects.filter(
            Q(opened_by=user) | Q(deal__sender=user) | Q(deal__traveler=user)
        )
        .distinct()
        .count(),
        "rating": user.ratings_received.aggregate(value=Avg("score"))["value"],
    }
    return _render(
        request,
        "admin/console/user_detail.html",
        {
            "title": user.full_name or user.email,
            "person": user,
            "roles": user_admin_roles(user),
            "kyc_submissions": kyc,
            "kyc_current": has_current_kyc_approval(user),
            "stats": stats,
            "may_view_sensitive": has_admin_permission(
                request.user, "view_user_sensitive"
            ),
        },
    )


def _kyc_queryset(request):
    queryset = (
        KycSubmission.objects.select_related("user")
        .prefetch_related("user__kyc_submissions")
        .order_by("-created_at")
    )
    queryset = _filter_choice(queryset, request)
    return _search(queryset, request, ("user__email", "user__full_name"))


@capability_required("view_kyc")
def kyc_queue(request):
    page_obj = _page(request, _kyc_queryset(request))
    rows = []
    for submission in page_obj.object_list:
        previous = next(
            (
                item
                for item in sorted(
                    submission.user.kyc_submissions.all(),
                    key=lambda row: row.created_at,
                    reverse=True,
                )
                if item.pk != submission.pk and item.created_at < submission.created_at
            ),
            None,
        )
        rows.append(
            {
                "cells": (
                    text_cell(
                        submission.user.full_name or submission.user.email,
                        submission.user.email,
                        href=reverse("admin_console:kyc-detail", args=(submission.pk,)),
                        kind="strong",
                    ),
                    text_cell(submission.get_document_type_display()),
                    status_cell(submission.status, submission.get_status_display()),
                    text_cell(
                        previous.get_status_display()
                        if previous
                        else "First submission",
                        (
                            timezone.localtime(previous.created_at).strftime("%d %b %Y")
                            if previous
                            else ""
                        ),
                    ),
                    datetime_cell(submission.created_at, relative=True),
                )
            }
        )
    return _table(
        request,
        title="KYC review",
        description="Review a Traveler's identity evidence without leaving the submission.",
        eyebrow="Verification",
        columns=("Applicant", "Document", "State", "Previous attempt", "Submitted"),
        rows=rows,
        page_obj=page_obj,
        empty_title=(
            "No KYC submissions waiting"
            if request.GET.get("status") == "pending"
            else "No KYC submissions"
        ),
        empty_text="Nothing is waiting on an identity decision right now.",
        filter_choices=tuple(KycSubmission.Status.choices),
        search_placeholder="Search applicant",
    )


def _handle_review(request, form, *, kind: str, object_id: int):
    if not form.is_valid():
        return False
    try:
        if kind == "kyc":
            review_kyc_submission(
                actor=request.user,
                submission_id=object_id,
                decision=form.cleaned_data["decision"],
                reason=form.cleaned_data.get("reason", ""),
            )
        else:
            review_flight_proof(
                actor=request.user,
                proof_id=object_id,
                decision=form.cleaned_data["decision"],
                reason=form.cleaned_data.get("reason", ""),
            )
    except Exception as exc:
        _operation_error(request, "Review decision", exc)
        return False
    messages.success(request, "The review decision was saved and audited.")
    return True


@capability_required("view_kyc")
def kyc_detail(request, pk: int):
    submission = get_object_or_404(KycSubmission.objects.select_related("user"), pk=pk)
    form = ReviewDecisionForm(request.POST or None)
    if request.method == "POST":
        if not has_admin_permission(request.user, "review_kyc"):
            raise PermissionDenied("KYC review permission is required.")
        if _handle_review(request, form, kind="kyc", object_id=submission.pk):
            return redirect("admin_console:kyc-detail", pk=submission.pk)
    # Identity slots are always stored images, so each one gets a real preview
    # rather than a link an operator has to open before they can judge it.
    #
    # Reachability is checked here rather than left to the browser. A presigned
    # URL is produced by local signing and is well-formed even when the
    # credential has no grant on the bucket, so rendering one blind is how a
    # storage failure turns into a broken image with no explanation. One HEAD
    # per slot, and only for a reviewer who may see evidence at all.
    may_view_evidence = has_admin_permission(request.user, "view_evidence")
    store = storage_for("kyc")
    evidence = []
    evidence_unavailable = False
    for slot, label, key in (
        ("front", "Document front", submission.front_image_key),
        ("back", "Document back", submission.back_image_key),
        ("selfie", "Applicant selfie", submission.selfie_image_key),
    ):
        if not key:
            continue
        reachable = store.readable(key) if may_view_evidence else True
        if not reachable:
            evidence_unavailable = True
            logger.error(
                "admin_console.kyc_evidence_unreachable submission=%s slot=%s "
                "store=%s request_id=%s",
                submission.pk,
                slot,
                store.name,
                getattr(request, "request_id", ""),
            )
        evidence.append(
            {
                "slot": slot,
                "label": label,
                "previewable": reachable,
                "available": reachable,
            }
        )
    return _render(
        request,
        "admin/console/verification_detail.html",
        {
            "title": submission.user.full_name or submission.user.email,
            "kind": "kyc",
            "subject": "Identity verification",
            "record": submission,
            "applicant": submission.user,
            "waiting_for": age_label(submission.created_at),
            "evidence": evidence,
            "evidence_unavailable": evidence_unavailable,
            "evidence_reference": getattr(request, "request_id", ""),
            "form": form,
            "may_review": has_admin_permission(request.user, "review_kyc"),
            "may_view_evidence": may_view_evidence,
            "previous": submission.user.kyc_submissions.exclude(
                pk=submission.pk
            ).order_by("-created_at")[:8],
        },
    )


def _evidence_unavailable(request, *, target, action: str):
    """Say that stored evidence exists but cannot be served right now.

    Deliberately not `_operation_error`: an operator needs to tell "nothing was
    submitted" from "something was submitted and the object store is refusing
    us", and neither answer may mention a bucket, a credential, an access key
    or a provider error string. The request reference is what support and the
    logs are correlated on.
    """

    reference = getattr(request, "request_id", "")
    suffix = f" Reference: {reference}." if reference else ""
    messages.error(
        request,
        "Evidence is temporarily unavailable. The submission is intact; the "
        f"secure document store could not be reached.{suffix}",
    )
    return redirect(
        "admin_console:kyc-detail"
        if action.startswith("kyc.")
        else "admin_console:proof-detail",
        pk=target.pk,
    )


def _private_object_redirect(
    request, *, store, key: str, target, action: str, metadata: dict
):
    """Hand an authorized reviewer a short-lived URL for one private object.

    `store` is a logical `apps.core.storage` class, not a bucket name, because
    the credential that may read a bucket is a property of the bucket and
    getting that pairing wrong is invisible at signing time: presigning is a
    local HMAC that succeeds with any key, and the denial only happens later in
    the reviewer's browser. `readable()` is therefore checked *before* signing,
    so a storage problem becomes a sentence rather than a broken image.
    """

    if not store.bucket or not key:
        raise Http404
    if not store.readable(key):
        logger.error(
            "admin_console.evidence_unreachable store=%s action=%s request_id=%s",
            store.name,
            action,
            getattr(request, "request_id", ""),
        )
        return _evidence_unavailable(request, target=target, action=action)
    try:
        url = store.presigned_get(
            key,
            expires_in=int(
                getattr(settings, "DISPUTE_EVIDENCE_URL_TTL_SECONDS", 300)
            ),
            content_disposition="inline",
        )
        record_admin_action(
            actor=request.user,
            action=action,
            target=target,
            metadata=metadata,
        )
    except Exception as exc:
        _operation_error(request, "Private evidence access", exc)
        return redirect(
            "admin_console:kyc-detail"
            if action.startswith("kyc.")
            else "admin_console:proof-detail",
            pk=target.pk,
        )
    response = HttpResponseRedirect(url)
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


@capability_required("view_kyc")
def kyc_evidence(request, pk: int, slot: str):
    if not has_admin_permission(request.user, "view_evidence"):
        raise PermissionDenied("Private evidence access is required.")
    submission = get_object_or_404(KycSubmission, pk=pk)
    keys = {
        "front": submission.front_image_key,
        "back": submission.back_image_key,
        "selfie": submission.selfie_image_key,
    }
    if slot not in keys or not keys[slot]:
        raise Http404
    return _private_object_redirect(
        request,
        store=storage_for("kyc"),
        key=keys[slot],
        target=submission,
        action="kyc.evidence_viewed",
        metadata={"slot": slot},
    )


def _proof_queryset(request):
    queryset = JourneyLegProof.objects.select_related(
        "leg__journey__traveler",
        "leg__origin_place__parent",
        "leg__origin_place__country",
        "leg__destination_place__parent",
        "leg__destination_place__country",
        "leg__origin",
        "leg__destination",
    ).order_by("-created_at")
    queryset = _filter_choice(queryset, request)
    return _search(
        queryset,
        request,
        (
            "leg__journey__traveler__email",
            "leg__journey__traveler__full_name",
            "leg__flight_number",
        ),
    )


@capability_required("view_flight_proofs")
def flight_proof_queue(request):
    page_obj = _page(request, _proof_queryset(request))
    rows = []
    for proof in page_obj.object_list:
        leg = proof.leg
        rows.append(
            {
                "cells": (
                    text_cell(
                        leg.journey.traveler.full_name or leg.journey.traveler.email,
                        leg.journey.traveler.email,
                        href=reverse("admin_console:proof-detail", args=(proof.pk,)),
                        kind="strong",
                    ),
                    route_cell(_leg_route_nodes(leg)),
                    text_cell(
                        leg.flight_number or "Flight number not provided",
                        f"Departs {leg.depart_at.strftime('%d %b %Y, %H:%M')}",
                    ),
                    status_cell(proof.status, proof.get_status_display()),
                    datetime_cell(proof.created_at, relative=True),
                )
            }
        )
    return _table(
        request,
        title="Flight-proof review",
        description="Review the actual proof next to its Traveler, route, flight and date.",
        eyebrow="Verification",
        columns=("Traveler", "Leg route", "Flight", "State", "Submitted"),
        rows=rows,
        page_obj=page_obj,
        empty_title=(
            "No flight proofs waiting"
            if request.GET.get("status") == "pending"
            else "No flight proofs"
        ),
        empty_text="No flight leg is waiting on a transport decision.",
        filter_choices=tuple(JourneyLegProof.Status.choices),
        search_placeholder="Search Traveler or flight",
    )


@capability_required("view_flight_proofs")
def flight_proof_detail(request, pk: int):
    proof = get_object_or_404(_proof_queryset(request), pk=pk)
    form = ReviewDecisionForm(request.POST or None)
    if request.method == "POST":
        if not has_admin_permission(request.user, "review_flight_proofs"):
            raise PermissionDenied("Flight-proof review permission is required.")
        if _handle_review(request, form, kind="proof", object_id=proof.pk):
            return redirect("admin_console:proof-detail", pk=proof.pk)
    may_view_evidence = has_admin_permission(request.user, "view_evidence")
    proof_available = (
        store_for_bucket(proof.bucket, default="proof").readable(proof.object_key)
        if may_view_evidence
        else True
    )
    if may_view_evidence and not proof_available:
        logger.error(
            "admin_console.proof_evidence_unreachable proof=%s request_id=%s",
            proof.pk,
            getattr(request, "request_id", ""),
        )
    return _render(
        request,
        "admin/console/verification_detail.html",
        {
            "title": proof.leg.journey.traveler.full_name
            or proof.leg.journey.traveler.email,
            "kind": "proof",
            "subject": "Transport verification",
            "record": proof,
            "applicant": proof.leg.journey.traveler,
            "leg": proof.leg,
            "waiting_for": age_label(proof.created_at),
            "route_nodes": _leg_route_nodes(proof.leg),
            "route": " → ".join(
                (
                    place_label(
                        proof.leg.origin_place,
                        getattr(proof.leg.origin, "public_label", ""),
                    ),
                    place_label(
                        proof.leg.destination_place,
                        getattr(proof.leg.destination, "public_label", ""),
                    ),
                )
            ),
            "evidence": (
                {
                    "slot": "proof",
                    "label": "Flight proof",
                    "previewable": proof.content_type
                    in ("image/jpeg", "image/png", "image/webp"),
                    "available": proof_available,
                },
            ),
            "evidence_unavailable": not proof_available,
            "evidence_reference": getattr(request, "request_id", ""),
            "form": form,
            "may_review": has_admin_permission(request.user, "review_flight_proofs"),
            "may_view_evidence": may_view_evidence,
        },
    )


@capability_required("view_flight_proofs")
def flight_proof_evidence(request, pk: int):
    if not has_admin_permission(request.user, "view_evidence"):
        raise PermissionDenied("Private evidence access is required.")
    proof = get_object_or_404(JourneyLegProof, pk=pk)
    return _private_object_redirect(
        request,
        # The row records the bucket it was written to, so a proof stored
        # before the 8F-A bucket move still resolves to the credential that can
        # read it rather than to today's default.
        store=store_for_bucket(proof.bucket, default="proof"),
        key=proof.object_key,
        target=proof,
        action="flight_proof.evidence_viewed",
        metadata={"content_type": proof.content_type, "size_bytes": proof.bytes},
    )


@capability_required("view_requests")
def delivery_requests(request):
    queryset = DeliveryRequest.objects.select_related(
        "sender",
        "pickup_place__parent",
        "pickup_place__country",
        "delivery_place__parent",
        "delivery_place__country",
        "pickup_location",
        "delivery_location",
    ).order_by("-created_at")
    queryset = _filter_choice(queryset, request)
    queryset = _search(
        queryset, request, ("title", "sender__email", "sender__full_name")
    )
    if request.GET.get("user_id", "").isdigit():
        queryset = queryset.filter(sender_id=request.GET["user_id"])
    page_obj = _page(request, queryset)
    rows = [
        {
            "cells": (
                text_cell(f"Request {item.pk}", parcel_summary(item), kind="strong"),
                text_cell(
                    item.sender.full_name or item.sender.email, item.sender.email
                ),
                route_cell(request_route_nodes(item)),
                status_cell(item.status, item.get_status_display()),
                datetime_cell(item.created_at, relative=True),
            )
        }
        for item in page_obj.object_list
    ]
    return _table(
        request,
        title="Delivery requests",
        description="Sender requests in product language, against the canonical route they were posted for.",
        eyebrow="Marketplace",
        columns=("Request", "Sender", "Route", "State", "Created"),
        rows=rows,
        page_obj=page_obj,
        empty_title="No delivery requests found",
        empty_text="There are no requests in this state or search.",
        filter_choices=tuple(DeliveryRequest.Status.choices),
        search_placeholder="Search request or Sender",
    )


def _journey_queryset(request):
    legs = (
        JourneyLeg.objects.select_related(
            "origin_place__parent",
            "origin_place__country",
            "destination_place__parent",
            "destination_place__country",
            "origin",
            "destination",
        )
        .prefetch_related("proofs")
        .order_by("position")
    )
    queryset = (
        Journey.objects.select_related(
            "traveler",
            "start_place__parent",
            "start_place__country",
            "destination_place__parent",
            "destination_place__country",
            "start_location",
            "destination_location",
        )
        .prefetch_related(Prefetch("legs", queryset=legs))
        .order_by("-created_at")
    )
    queryset = _filter_choice(queryset, request)
    queryset = _search(queryset, request, ("traveler__email", "traveler__full_name"))
    if request.GET.get("user_id", "").isdigit():
        queryset = queryset.filter(traveler_id=request.GET["user_id"])
    return queryset


def _proof_summary(journey) -> tuple[str, str]:
    flight_legs = [
        leg for leg in journey.legs.all() if leg.mode == JourneyLeg.Mode.FLIGHT
    ]
    if not flight_legs:
        return "Not required", "mute"
    # Publication requires an approved proof on EVERY flight leg. Historical
    # rejected attempts do not invalidate a later approval.
    missing_approval = [
        list(leg.proofs.all())
        for leg in flight_legs
        if not any(
            proof.status == JourneyLegProof.Status.APPROVED
            for proof in leg.proofs.all()
        )
    ]
    if not missing_approval:
        return "Approved", "ok"
    if any(not proofs for proofs in missing_approval):
        return "Missing", "bad"
    proofs = [proof for leg_proofs in missing_approval for proof in leg_proofs]
    if any(proof.status == JourneyLegProof.Status.PENDING for proof in proofs):
        return "Pending review", "attn"
    if any(proof.status == JourneyLegProof.Status.REJECTED for proof in proofs):
        return "Rejected", "bad"
    return "Missing", "bad"


@capability_required("view_journeys")
def journeys(request):
    page_obj = _page(request, _journey_queryset(request))
    rows = []
    for journey in page_obj.object_list:
        legs = list(journey.legs.all())
        proof_text, proof_tone = _proof_summary(journey)
        modes = (
            " + ".join(dict.fromkeys(leg.get_mode_display() for leg in legs))
            or "No legs"
        )
        capacity = min((leg.capacity_kg for leg in legs), default=None)
        rows.append(
            {
                "cells": (
                    text_cell(
                        f"Journey {journey.pk}",
                        modes,
                        href=reverse(
                            "admin_console:journey-detail", args=(journey.pk,)
                        ),
                        kind="strong",
                    ),
                    text_cell(
                        journey.traveler.full_name or journey.traveler.email,
                        journey.traveler.email,
                    ),
                    route_cell(journey_route_nodes(journey)),
                    text_cell(
                        f"{capacity:g} kg" if capacity is not None else "Not set",
                        "smallest segment" if capacity is not None else "",
                    ),
                    text_cell(
                        legs[0].depart_at.strftime("%d %b %Y") if legs else "—",
                        legs[0].depart_at.strftime("%H:%M") if legs else "",
                    ),
                    {"primary": proof_text, "kind": "status", "tone": proof_tone},
                    status_cell(journey.status, journey.get_status_display()),
                )
            }
        )
    return _table(
        request,
        title="Journeys",
        description="Ordered flight and drive legs, segment capacity and proof readiness in one queue.",
        eyebrow="Marketplace",
        columns=(
            "Journey",
            "Traveler",
            "Ordered route",
            "Capacity",
            "Departs",
            "Flight proof",
            "State",
        ),
        rows=rows,
        page_obj=page_obj,
        empty_title="No journeys found",
        empty_text="There are no journeys in this state or search.",
        filter_choices=tuple(Journey.Status.choices),
        search_placeholder="Search Traveler",
    )


@capability_required("view_journeys")
def journey_detail(request, pk: int):
    journey = get_object_or_404(_journey_queryset(request), pk=pk)
    for leg in journey.legs.all():
        leg.console_route_nodes = _leg_route_nodes(leg)
    return _render(
        request,
        "admin/console/journey_detail.html",
        {
            "title": f"Journey {journey.pk}",
            "journey": journey,
            "route": journey_route(journey),
            "route_nodes": journey_route_nodes(journey),
            "proof_summary": _proof_summary(journey),
        },
    )


def _deal_queryset(request):
    queryset = (
        Deal.objects.select_related(
            "sender",
            "traveler",
            "terms",
            "payout",
            "delivery_request__pickup_place__parent",
            "delivery_request__pickup_place__country",
            "delivery_request__delivery_place__parent",
            "delivery_request__delivery_place__country",
            "delivery_request__pickup_location",
            "delivery_request__delivery_location",
        )
        .prefetch_related("payment_orders", "disputes")
        .order_by("-created_at")
    )
    queryset = _filter_choice(queryset, request)
    queryset = _search(queryset, request, ("sender__email", "traveler__email"))
    if request.GET.get("user_id", "").isdigit():
        queryset = queryset.filter(
            Q(sender_id=request.GET["user_id"]) | Q(traveler_id=request.GET["user_id"])
        )
    return queryset


def _deal_payment_state(deal) -> str:
    orders = list(deal.payment_orders.all())
    if not orders:
        return "No V1 order"
    return ", ".join(dict.fromkeys(order.get_status_display() for order in orders))


def _deal_protection_state(deal) -> tuple[str, str]:
    active = [
        item for item in deal.disputes.all() if item.status in Dispute.ACTIVE_STATUSES
    ]
    if active:
        return "Dispute open · payout frozen", "bad"
    if deal.protection_ends_at and deal.protection_ends_at > timezone.now():
        return (
            f"Protected until {timezone.localtime(deal.protection_ends_at):%d %b %H:%M}",
            "wait",
        )
    payout = getattr(deal, "payout", None)
    if payout:
        return payout.get_status_display(), tone_for(payout.status)
    return "No payout record", "mute"


@capability_required("view_deals")
def deals(request):
    page_obj = _page(request, _deal_queryset(request))
    rows = []
    for deal in page_obj.object_list:
        terms = getattr(deal, "terms", None)
        protection, protection_tone = _deal_protection_state(deal)
        rows.append(
            {
                "cells": (
                    text_cell(
                        f"Deal {deal.pk}",
                        deal.created_at.strftime("%d %b %Y"),
                        href=reverse("admin_console:deal-detail", args=(deal.pk,)),
                        kind="strong",
                    ),
                    text_cell(
                        deal.sender.email,
                        f"to {deal.traveler.email}",
                    ),
                    route_cell(request_route_nodes(deal.delivery_request)),
                    money_cell(terms.traveler_reward_minor if terms else None),
                    money_cell(terms.platform_fee_minor if terms else None),
                    money_cell(
                        terms.sender_total_minor if terms else None, emphasis=True
                    ),
                    text_cell(_deal_payment_state(deal)),
                    status_cell(deal.status, deal.get_status_display()),
                    {"primary": protection, "kind": "status", "tone": protection_tone},
                )
            }
        )
    return _table(
        request,
        title="Deals",
        description="Agreed route, parties, money, payment, lifecycle and protection state.",
        eyebrow="Marketplace",
        columns=(
            "Deal",
            "Sender to Traveler",
            "Route",
            "Traveler reward",
            "ShipTrip fee",
            "Sender total",
            "Payment",
            "Lifecycle",
            "Protection",
        ),
        rows=rows,
        page_obj=page_obj,
        empty_title="No Deals found",
        empty_text="There are no Deals in this state or search.",
        filter_choices=tuple(Deal.Status.choices),
        search_placeholder="Search Sender or Traveler",
    )


@capability_required("view_deals")
def deal_detail(request, pk: int):
    queryset = _deal_queryset(request).prefetch_related(
        Prefetch(
            "events",
            queryset=DealEvent.objects.select_related("actor").order_by("created_at"),
        ),
        "payment_orders__attempts",
        "payment_orders__refunds",
    )
    deal = get_object_or_404(queryset, pk=pk)
    audits = []
    if has_admin_permission(request.user, "view_audit_log"):
        audits = AdminAuditLog.objects.filter(
            target_type="deals.deal", target_id=str(deal.pk)
        ).select_related("actor")[:20]
    return _render(
        request,
        "admin/console/deal_detail.html",
        {
            "title": f"Deal {deal.pk}",
            "deal": deal,
            "terms": getattr(deal, "terms", None),
            "route": request_route(deal.delivery_request),
            "route_nodes": request_route_nodes(deal.delivery_request),
            "protection": _deal_protection_state(deal),
            "audits": audits,
        },
    )


def _dispute_queryset(request):
    queryset = (
        Dispute.objects.select_related(
            "deal__sender",
            "deal__traveler",
            "deal__terms",
            "deal__payout",
            "opened_by",
            "resolved_by",
        )
        .prefetch_related("evidence", "events", "deal__payment_orders")
        .order_by("-opened_at")
    )
    if request.GET.get("attention") == "1":
        queryset = queryset.filter(status__in=Dispute.ACTIVE_STATUSES)
    else:
        queryset = _filter_choice(queryset, request)
    if request.GET.get("user_id", "").isdigit():
        queryset = queryset.filter(
            Q(deal__sender_id=request.GET["user_id"])
            | Q(deal__traveler_id=request.GET["user_id"])
            | Q(opened_by_id=request.GET["user_id"])
        )
    return _search(
        queryset,
        request,
        ("public_reference", "deal__sender__email", "deal__traveler__email"),
    )


def _money_at_stake(dispute) -> int:
    if dispute.collected_total_eur_cents:
        return dispute.collected_total_eur_cents
    terms = getattr(dispute.deal, "terms", None)
    return int(terms.sender_total_minor) if terms else 0


@capability_required("view_disputes")
def disputes(request):
    page_obj = _page(request, _dispute_queryset(request))
    rows = []
    for dispute in page_obj.object_list:
        evidence_count = len(dispute.evidence.all())
        rows.append(
            {
                "cells": (
                    text_cell(
                        dispute.public_reference,
                        f"Deal {dispute.deal_id}",
                        href=reverse(
                            "admin_console:dispute-detail", args=(dispute.pk,)
                        ),
                        kind="strong",
                    ),
                    text_cell(
                        dispute.deal.sender.email,
                        f"against {dispute.deal.traveler.email}",
                    ),
                    text_cell(
                        dispute.get_category_display(),
                        f"opened by the {dispute.get_opened_by_role_display()}",
                    ),
                    text_cell(f"{age_label(dispute.opened_at)} open"),
                    status_cell(dispute.status, dispute.get_status_display()),
                    money_cell(_money_at_stake(dispute), emphasis=True),
                    text_cell(
                        f"{evidence_count} item{'s' if evidence_count != 1 else ''}"
                    ),
                )
            }
        )
    return _table(
        request,
        title="Disputes",
        description="One queue for age, participants, claim, evidence and the money held against it.",
        eyebrow="Disputes",
        columns=(
            "Dispute",
            "Sender against Traveler",
            "Claim",
            "Age",
            "State",
            "Money at stake",
            "Evidence",
        ),
        rows=rows,
        page_obj=page_obj,
        empty_title="No open disputes"
        if request.GET.get("attention") == "1"
        else "No disputes found",
        empty_text="No case is waiting on a decision.",
        filter_choices=tuple(Dispute.Status.choices),
        search_placeholder="Search reference or participant",
    )


def _dispute_context(
    request, dispute, *, status_form=None, resolution_form=None, preview=None
):
    audits = []
    if has_admin_permission(request.user, "view_audit_log"):
        audits = AdminAuditLog.objects.filter(
            Q(target_type="disputes.dispute", target_id=str(dispute.pk))
            | Q(target_type="deals.deal", target_id=str(dispute.deal_id))
        ).select_related("actor")[:30]
    return {
        # The browser tab and the page name the claim, not the UUID. The
        # reference is still on the page for anyone who has to quote it.
        "title": f"{dispute.get_category_display()} · Deal {dispute.deal_id}",
        "dispute": dispute,
        "status_form": status_form
        or DisputeStatusForm(
            initial={"status": dispute.status}, auto_id="id_status_%s"
        ),
        "resolution_form": resolution_form or DisputeResolutionForm(),
        "resolution_preview": preview,
        "may_manage": has_admin_permission(request.user, "manage_disputes"),
        "may_resolve": has_admin_permission(request.user, "resolve_disputes"),
        "may_view_evidence": has_admin_permission(request.user, "view_evidence"),
        "audits": audits,
        "terms": getattr(dispute.deal, "terms", None),
        "money": _dispute_money(dispute),
    }


def _dispute_money(dispute):
    if not hasattr(dispute.deal, "terms"):
        return None
    with transaction.atomic():
        aggregate = lock_deal_aggregate(dispute.deal_id)
        return read_deal_money(aggregate.deal)


@capability_required("view_disputes")
def dispute_detail(request, pk: int):
    dispute = get_object_or_404(
        _dispute_queryset(request).prefetch_related(
            "deal__events__actor",
            "deal__payment_orders__attempts",
            "deal__payment_orders__refunds",
        ),
        pk=pk,
    )
    status_form = DisputeStatusForm(
        initial={"status": dispute.status}, auto_id="id_status_%s"
    )
    resolution_form = DisputeResolutionForm()
    preview = None
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "status":
            if not has_admin_permission(request.user, "manage_disputes"):
                raise PermissionDenied("Dispute management permission is required.")
            status_form = DisputeStatusForm(request.POST, auto_id="id_status_%s")
            if status_form.is_valid():
                try:
                    before = dispute.status
                    with transaction.atomic():
                        updated = set_dispute_status(
                            dispute_id=dispute.pk,
                            status=status_form.cleaned_data["status"],
                            admin_actor_id=request.user.pk,
                            note=status_form.cleaned_data.get("note", ""),
                        )
                        record_admin_action(
                            actor=request.user,
                            action="dispute.status_changed",
                            target=updated,
                            before={"status": before},
                            after={"status": updated.status},
                            reason=status_form.cleaned_data.get("note", ""),
                        )
                    messages.success(request, "The dispute review state was updated.")
                    return redirect("admin_console:dispute-detail", pk=dispute.pk)
                except Exception as exc:  # domain errors are sanitized for the operator
                    _operation_error(request, "Dispute state update", exc)
        elif action in ("preview-resolution", "confirm-resolution"):
            if not has_admin_permission(request.user, "resolve_disputes"):
                raise PermissionDenied("Dispute resolution permission is required.")
            resolution_form = DisputeResolutionForm(request.POST)
            if resolution_form.is_valid():
                values = resolution_form.service_values()
                try:
                    if action == "preview-resolution":
                        preview = preview_dispute_resolution(
                            dispute_id=dispute.pk,
                            resolution=values["resolution"],
                            sender_refund_eur_cents=values["sender_refund_eur_cents"],
                            traveler_payout_eur_cents=values[
                                "traveler_payout_eur_cents"
                            ],
                        )
                    elif request.POST.get("confirm_resolution") == "yes":
                        before = {
                            "status": dispute.status,
                            "resolution": dispute.resolution,
                        }
                        with transaction.atomic():
                            updated = resolve_dispute(
                                dispute_id=dispute.pk,
                                admin_actor_id=request.user.pk,
                                **values,
                            )
                            record_admin_action(
                                actor=request.user,
                                action="dispute.resolved",
                                target=updated,
                                before=before,
                                after={
                                    "status": updated.status,
                                    "resolution": updated.resolution,
                                    "sender_refund_eur_cents": updated.sender_refund_eur_cents,
                                    "traveler_payout_eur_cents": updated.traveler_payout_eur_cents,
                                    "platform_fee_eur_cents": updated.platform_fee_eur_cents,
                                },
                                reason=values.get("note", ""),
                            )
                        messages.success(
                            request,
                            "The dispute was resolved and the settlement was audited.",
                        )
                        return redirect("admin_console:dispute-detail", pk=dispute.pk)
                    else:
                        messages.error(
                            request,
                            "Confirm the financial consequence before resolving.",
                        )
                except Exception as exc:
                    _operation_error(request, "Dispute resolution", exc)
    return _render(
        request,
        "admin/console/dispute_detail.html",
        _dispute_context(
            request,
            dispute,
            status_form=status_form,
            resolution_form=resolution_form,
            preview=preview,
        ),
    )


@capability_required("view_disputes")
def dispute_evidence(request, pk: int, evidence_id: int):
    if not has_admin_permission(request.user, "view_evidence"):
        raise PermissionDenied("Private evidence access is required.")
    evidence = get_object_or_404(DisputeEvidence, pk=evidence_id, dispute_id=pk)
    try:
        url = evidence_download_url(
            evidence_id=evidence.pk,
            actor_id=request.user.pk,
            is_staff=True,
        )
    except DisputeError as exc:
        _operation_error(request, "Evidence access", exc)
        return redirect("admin_console:dispute-detail", pk=pk)
    record_admin_action(
        actor=request.user,
        action="dispute.evidence_viewed",
        target=evidence,
        metadata={"kind": evidence.kind, "content_type": evidence.content_type},
    )
    response = HttpResponseRedirect(url)
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


@capability_required("view_payment_attempts", "view_payment_orders")
def payments(request):
    queryset = PaymentAttempt.objects.select_related(
        "order__owner", "order__deal", "payer"
    ).order_by("-created_at")
    if request.GET.get("attention") == "1":
        queryset = queryset.filter(
            Q(status=PaymentAttempt.Status.FAILED) | Q(is_unapplied=True)
        )
    else:
        queryset = _filter_choice(queryset, request)
    query = request.GET.get("q", "").strip()[:200]
    if query:
        queryset = queryset.filter(
            Q(order__public_reference__icontains=query)
            | Q(payer__email__icontains=query)
            | Q(guest_email__icontains=query)
            | Q(provider_payment_id__icontains=query)
        )
    page_obj = _page(request, queryset)
    rows = []
    for attempt in page_obj.object_list:
        payer = (
            attempt.payer.email
            if attempt.payer_id
            else (attempt.guest_email or "Guest payer")
        )
        actions = ""
        if (
            has_admin_permission(request.user, "issue_refunds")
            and attempt.status == PaymentAttempt.Status.SUCCEEDED
        ):
            actions = reverse("admin_console:refund-new", args=(attempt.pk,))
        settlement = format_minor_amount(
            attempt.provider_amount_minor,
            attempt.provider_amount_exponent,
            attempt.payment_currency,
        )
        rows.append(
            {
                "cells": (
                    text_cell(attempt.get_provider_display(), payer),
                    text_cell(
                        f"Deal {attempt.order.deal_id}"
                        if attempt.order.deal_id
                        else attempt.order.get_purpose_display(),
                        str(attempt.order.public_reference),
                    ),
                    money_pair_cell(
                        attempt.amount_eur_cents,
                        f"order expects {format_eur(attempt.order.amount_eur_cents)}",
                    ),
                    text_cell(
                        settlement
                        if attempt.payment_currency != "EUR"
                        else "Charged in EUR",
                        "provider settlement"
                        if attempt.payment_currency != "EUR"
                        else "",
                    ),
                    status_cell(attempt.status, attempt.get_status_display()),
                    ref_cell(
                        attempt.provider_payment_id
                        or attempt.provider_session_id
                        or "—"
                    ),
                    datetime_cell(attempt.updated_at, relative=True),
                    text_cell("Request refund", href=actions, kind="strong")
                    if actions
                    else text_cell("—"),
                )
            }
        )
    return _table(
        request,
        title="Payments",
        description="The canonical EUR obligation leads; what a provider actually moved sits beside it.",
        eyebrow="Finance",
        columns=(
            "Provider / payer",
            "Deal / reference",
            "Canonical EUR",
            "Provider settlement",
            "State",
            "Provider reference",
            "Updated",
            "Action",
        ),
        rows=rows,
        page_obj=page_obj,
        empty_title="No payments require attention"
        if request.GET.get("attention") == "1"
        else "No payments found",
        empty_text="No payment attempt matches this view.",
        filter_choices=tuple(PaymentAttempt.Status.choices),
        search_placeholder="Search payer or reference",
    )


@capability_required("issue_refunds")
def refund_request(request, attempt_id: int):
    attempt = get_object_or_404(
        PaymentAttempt.objects.select_related("order__owner", "order__deal"),
        pk=attempt_id,
    )
    form = RefundRequestForm(
        request.POST or None,
        initial={"amount_eur": decimal_eur(attempt.amount_eur_cents)},
    )
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                refund = request_payment_refund(
                    order_id=attempt.order_id,
                    attempt_id=attempt.pk,
                    amount_eur_cents=form.amount_eur_cents(),
                    reason=form.cleaned_data["reason"],
                    requested_by_id=request.user.pk,
                )
                record_admin_action(
                    actor=request.user,
                    action="refund.requested",
                    target=refund,
                    after={
                        "status": refund.status,
                        "amount_eur_cents": refund.amount_eur_cents,
                    },
                    reason=form.cleaned_data["reason"],
                )
            messages.success(request, "The refund request was created and audited.")
            return redirect("admin_console:refund-detail", pk=refund.pk)
        except Exception as exc:
            _operation_error(request, "Refund request", exc)
    return _render(
        request,
        "admin/console/action_form.html",
        {
            "title": "Request refund",
            "description": (
                f"Payment {attempt.pk} · {format_eur(attempt.amount_eur_cents)} "
                f"canonical EUR · {attempt.get_provider_display()}"
            ),
            "form": form,
            "submit_label": "Request refund",
            "danger": True,
            "back_url": reverse("admin_console:payments"),
        },
    )


@capability_required("issue_refunds", "settle_manual_refunds")
def refunds(request):
    queryset = PaymentRefund.objects.select_related("order__owner", "attempt").order_by(
        "-created_at"
    )
    queryset = _filter_choice(queryset, request)
    if request.GET.get("manual") == "1":
        queryset = queryset.filter(
            requires_manual_action=True,
            status__in=(PaymentRefund.Status.PENDING, PaymentRefund.Status.PROCESSING),
        )
    page_obj = _page(request, queryset)
    rows = []
    for refund in page_obj.object_list:
        returned = (
            refund.amount_eur_cents
            if refund.status == PaymentRefund.Status.SUCCEEDED
            else None
        )
        rows.append(
            {
                "cells": (
                    text_cell(
                        f"Refund {refund.pk}",
                        str(refund.order.public_reference),
                        href=reverse("admin_console:refund-detail", args=(refund.pk,)),
                        kind="strong",
                    ),
                    text_cell(refund.get_reason_display()),
                    money_cell(refund.amount_eur_cents, emphasis=True),
                    money_cell(returned),
                    text_cell(refund.get_provider_display()),
                    status_cell(
                        "manual_required" if refund.requires_manual_action else "none",
                        "Manual required"
                        if refund.requires_manual_action
                        else "Automatic",
                    ),
                    status_cell(refund.status, refund.get_status_display()),
                )
            }
        )
    return _table(
        request,
        title="Refunds",
        description="Requested and returned amounts, provider capability and what an operator still has to do.",
        eyebrow="Finance",
        columns=(
            "Refund",
            "Reason",
            "Requested",
            "Returned",
            "Provider",
            "Settlement",
            "State",
        ),
        rows=rows,
        page_obj=page_obj,
        empty_title="No refunds requiring action"
        if request.GET.get("manual") == "1"
        else "No refunds found",
        empty_text="No money is waiting to go back to a Sender.",
        filter_choices=tuple(PaymentRefund.Status.choices),
    )


@capability_required("issue_refunds", "settle_manual_refunds")
def refund_detail(request, pk: int):
    refund = get_object_or_404(
        PaymentRefund.objects.select_related(
            "order__owner", "attempt", "requested_by", "settled_by"
        ),
        pk=pk,
    )
    form = ManualRefundForm(request.POST or None)
    if request.method == "POST":
        if not has_admin_permission(request.user, "settle_manual_refunds"):
            raise PermissionDenied("Manual refund settlement permission is required.")
        if form.is_valid():
            try:
                with transaction.atomic():
                    updated = settle_refund_manually(
                        refund_id=refund.pk,
                        admin_actor_id=request.user.pk,
                        settlement_reference=form.cleaned_data["settlement_reference"],
                        settlement_note=form.cleaned_data.get("settlement_note", ""),
                    )
                    record_admin_action(
                        actor=request.user,
                        action="refund.manually_settled",
                        target=updated,
                        after={"status": updated.status},
                        reference=updated.settlement_reference,
                    )
                messages.success(request, "The manual refund evidence was recorded.")
                return redirect("admin_console:refund-detail", pk=refund.pk)
            except Exception as exc:
                _operation_error(request, "Manual refund settlement", exc)
    return _render(
        request,
        "admin/console/finance_detail.html",
        {
            "title": f"Refund {refund.pk}",
            "kind": "refund",
            "record": refund,
            "form": form,
            "may_act": has_admin_permission(request.user, "settle_manual_refunds")
            and refund.requires_manual_action
            and refund.status != PaymentRefund.Status.SUCCEEDED,
        },
    )


@capability_required("view_payouts")
def payouts(request):
    queryset = Payout.objects.select_related("traveler", "deal").order_by("-created_at")
    if request.GET.get("attention") == "1":
        queryset = queryset.filter(
            Q(status=Payout.Status.FAILED)
            | Q(status=Payout.Status.ELIGIBLE, method=Payout.Method.MANUAL)
        )
    else:
        queryset = _filter_choice(queryset, request)
    page_obj = _page(request, queryset)
    rows = []
    for payout in page_obj.object_list:
        if payout.status == Payout.Status.NOT_ELIGIBLE:
            readiness = "Protection window open"
        elif payout.status == Payout.Status.FROZEN:
            readiness = "Frozen by dispute"
        elif payout.status == Payout.Status.ELIGIBLE:
            readiness = "Ready for settlement"
        else:
            readiness = payout.get_status_display()
        rows.append(
            {
                "cells": (
                    text_cell(
                        payout.traveler.full_name or payout.traveler.email,
                        payout.traveler.email,
                        href=reverse("admin_console:payout-detail", args=(payout.pk,)),
                        kind="strong",
                    ),
                    text_cell(f"Deal {payout.deal_id}"),
                    money_cell(payout.amount_eur_cents, emphasis=True),
                    text_cell(readiness),
                    text_cell(payout.get_method_display()),
                    status_cell(payout.status, payout.get_status_display()),
                    datetime_cell(payout.paid_at or payout.eligible_at, relative=True),
                )
            }
        )
    return _table(
        request,
        title="Payouts",
        description="What ShipTrip owes each Traveler, whether it can move yet, and what is holding it.",
        eyebrow="Finance",
        columns=(
            "Traveler",
            "Deal",
            "Reward",
            "Readiness",
            "Method",
            "State",
            "Relevant time",
        ),
        rows=rows,
        page_obj=page_obj,
        empty_title="No payouts requiring action"
        if request.GET.get("attention") == "1"
        else "No payouts found",
        empty_text="No Traveler settlement is waiting.",
        filter_choices=tuple(Payout.Status.choices),
    )


@capability_required("view_payouts")
def payout_detail(request, pk: int):
    payout = get_object_or_404(Payout.objects.select_related("traveler", "deal"), pk=pk)
    form = ManualPayoutForm(
        request.POST or None,
        initial={
            "payout_currency": "EUR",
            "payout_amount": decimal_eur(payout.amount_eur_cents),
        },
    )
    if request.method == "POST":
        if not has_admin_permission(request.user, "settle_payouts"):
            raise PermissionDenied("Payout settlement permission is required.")
        if form.is_valid():
            try:
                with transaction.atomic():
                    updated = complete_manual_payout(
                        payout_id=payout.pk,
                        admin_actor_id=request.user.pk,
                        **form.service_values(),
                    )
                    record_admin_action(
                        actor=request.user,
                        action="payout.manually_completed",
                        target=updated,
                        after={
                            "status": updated.status,
                            "payout_currency": updated.payout_currency,
                            "payout_amount_minor": updated.payout_amount_minor,
                            "fx_rate_micros": updated.fx_rate_micros,
                            "method": updated.method,
                        },
                        reference=updated.reference,
                    )
                messages.success(
                    request, "The payout evidence was recorded and audited."
                )
                return redirect("admin_console:payout-detail", pk=payout.pk)
            except Exception as exc:
                _operation_error(request, "Manual payout", exc)
    return _render(
        request,
        "admin/console/finance_detail.html",
        {
            "title": f"Payout {payout.pk}",
            "kind": "payout",
            "record": payout,
            "form": form,
            "may_act": has_admin_permission(request.user, "settle_payouts")
            and payout.status == Payout.Status.ELIGIBLE
            and payout.method == Payout.Method.MANUAL,
        },
    )


@capability_required("reconcile_finance")
def ledger(request):
    queryset = LedgerTransaction.objects.prefetch_related(
        Prefetch(
            "entries",
            queryset=LedgerEntry.objects.select_related("user", "deal").order_by("id"),
        )
    ).order_by("-created_at")
    page_obj = _page(request, queryset)
    rows = []
    for item in page_obj.object_list:
        entries = list(item.entries.all())
        amount = (
            sum(abs(entry.amount_eur_cents) for entry in entries) // 2 if entries else 0
        )
        rows.append(
            {
                "cells": (
                    text_cell(item.get_kind_display(), item.key, kind="strong"),
                    money_cell(amount, emphasis=True),
                    text_cell(f"{len(entries)} balanced entries"),
                    text_cell(
                        f"Reverses {item.reverses_id}"
                        if item.reverses_id
                        else "Original transaction"
                    ),
                    datetime_cell(item.created_at, relative=True),
                )
            }
        )
    return _table(
        request,
        title="Ledger & reconciliation",
        description="Append-only accounting transactions first; technical entries remain available by transaction.",
        eyebrow="Finance",
        columns=("Transaction", "Economic amount", "Entries", "Correction", "Created"),
        rows=rows,
        page_obj=page_obj,
        empty_title="No ledger transactions",
        empty_text="No financial facts have been posted yet.",
    )


@capability_required("manage_admins")
def staff(request):
    form = InvitationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            create_admin_invitation(
                actor=request.user,
                email=form.cleaned_data["email"],
                role=form.cleaned_data["role"],
                ttl=timedelta(hours=form.cleaned_data["expires_in_hours"]),
            )
            messages.success(
                request,
                "Invitation created. The one-time link is in the durable email queue; it is never shown in the browser.",
            )
            return redirect("admin_console:staff")
        except Exception as exc:
            _operation_error(request, "Staff invitation", exc)
    staff_users = list(
        User.objects.filter(is_staff=True).prefetch_related("groups").order_by("email")
    )
    for member in staff_users:
        roles = (
            (AdminRole.SUPER_ADMIN,)
            if member.is_superuser
            else user_admin_roles(member)
        )
        # Fixed-role accounts normally have one role; retaining an empty value
        # keeps legacy/unassigned staff visibly actionable without guessing.
        member.console_role = roles[0] if roles else ""
    invitations = AdminInvitation.objects.select_related(
        "invited_by", "accepted_by"
    ).order_by("-created_at")[:100]
    return _render(
        request,
        "admin/console/staff.html",
        {
            "title": "Staff",
            "form": form,
            "staff_users": staff_users,
            "invitations": invitations,
            "roles": [
                {
                    "slug": slug,
                    "name": ROLE_GROUP_NAMES[slug],
                    "description": ROLE_DESCRIPTIONS[slug],
                    "permissions": len(ROLE_PERMISSIONS[slug]),
                }
                for slug in ROLE_GROUP_NAMES
            ],
        },
    )


@capability_required("manage_permissions")
def staff_role(request, pk: int):
    member = get_object_or_404(User, pk=pk, is_staff=True)
    if request.method != "POST":
        return redirect("admin_console:staff")
    form = RoleChangeForm(request.POST)
    if form.is_valid():
        try:
            change_admin_role(
                actor=request.user,
                user_id=member.pk,
                role=form.cleaned_data["role"],
            )
            messages.success(request, f"{member.email}'s role was updated and audited.")
        except Exception as exc:
            _operation_error(request, "Staff role change", exc)
    else:
        messages.error(request, "Confirm the role change and try again.")
    return redirect("admin_console:staff")


@capability_required("manage_admins")
def staff_access(request, pk: int):
    member = get_object_or_404(User, pk=pk, is_staff=True)
    if request.method != "POST":
        return redirect("admin_console:staff")
    form = StaffAccessForm(request.POST)
    if form.is_valid():
        try:
            set_admin_access(
                actor=request.user,
                user_id=member.pk,
                enabled=form.cleaned_data["enabled"],
            )
            messages.success(
                request, f"Access for {member.email} was updated and audited."
            )
        except Exception as exc:
            _operation_error(request, "Staff access change", exc)
    else:
        messages.error(request, "Confirm the access change and try again.")
    return redirect("admin_console:staff")


@capability_required("manage_admins")
def staff_invitation_action(request, pk, action: str):
    if request.method != "POST":
        return redirect("admin_console:staff")
    invitation = get_object_or_404(AdminInvitation, pk=pk)
    if request.POST.get("confirm") != "yes":
        messages.error(request, "Confirm the invitation action and try again.")
        return redirect("admin_console:staff")
    try:
        if action == "revoke":
            revoke_admin_invitation(actor=request.user, invitation_id=invitation.pk)
            messages.success(request, "The invitation was revoked.")
        elif action == "replace":
            with transaction.atomic():
                invitation = AdminInvitation.objects.select_for_update().get(pk=pk)
                if invitation.used_at:
                    raise ValidationError("An accepted invitation cannot be replaced.")
                if invitation.is_active:
                    revoke_admin_invitation(
                        actor=request.user, invitation_id=invitation.pk
                    )
                create_admin_invitation(
                    actor=request.user,
                    email=invitation.email,
                    role=invitation.role,
                )
            messages.success(
                request,
                "A replacement invitation was queued and the old one cannot be used.",
            )
        else:
            raise Http404
    except Exception as exc:
        _operation_error(request, "Invitation action", exc)
    return redirect("admin_console:staff")


def _dig(policy: dict, path: str):
    node = policy
    for part in path.split("."):
        node = node[part]
    return node


def _set_path(policy: dict, path: str, value) -> None:
    node = policy
    parts = path.split(".")
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = value


def _save_settings_revision(
    request, *, path_updates: dict, commission_rate_bps: int | None, reason: str
):
    with transaction.atomic():
        active = BusinessSettingsVersion.objects.select_for_update(no_key=True).get(
            status=BusinessSettingsVersion.Status.ACTIVE
        )
        latest = (
            BusinessSettingsVersion.objects.select_for_update(no_key=True)
            .order_by("-version")
            .first()
        )
        policy = deepcopy(active.policy)
        before = {path: _dig(policy, path) for path in path_updates}
        for path, value in path_updates.items():
            _set_path(policy, path, value)
        commission = (
            active.commission_rate_bps
            if commission_rate_bps is None
            else commission_rate_bps
        )
        serializer = AdminSettingsCreateSerializer(
            data={
                "commission_rate_bps": commission,
                "pricing_version": active.pricing_version,
                "policy": policy,
                "activate": True,
                "reason": reason,
            }
        )
        serializer.is_valid(raise_exception=True)
        revision = BusinessSettingsVersion.objects.create(
            version=(latest.version if latest else 0) + 1,
            commission_rate_bps=commission,
            pricing_version=active.pricing_version,
            policy=policy,
            created_by=request.user,
        )
        activate_business_settings(revision)
        after = {path: _dig(policy, path) for path in path_updates}
        if commission_rate_bps is not None:
            before["commission_rate_bps"] = active.commission_rate_bps
            after["commission_rate_bps"] = commission_rate_bps
        record_admin_action(
            actor=request.user,
            action="settings.version_created",
            target=revision,
            before=before,
            after={"version": revision.version, **after},
            reason=reason,
        )
    return revision


def _settings_initial(active):
    return {
        "pricing": {
            "commission_percent": percent_from_bps(active.commission_rate_bps),
            "deposit_percent": percent_from_bps(
                _dig(active.policy, "payments.posting_deposit.percent_bps")
            ),
            "deposit_min_eur": decimal_eur(
                _dig(active.policy, "payments.posting_deposit.min_eur_cents")
            ),
            "deposit_max_eur": decimal_eur(
                _dig(active.policy, "payments.posting_deposit.max_eur_cents")
            ),
            "global_floor_eur": decimal_eur(
                _dig(active.policy, "pricing.global_floor_cents")
            ),
            "weight_rate_eur": decimal_eur(
                _dig(active.policy, "pricing.weight_rate_cents_per_kg")
            ),
            "recommendation_multiplier_percent": percent_from_bps(
                _dig(active.policy, "pricing.recommendation_multiplier_bps")
            ),
        },
        "fx": {
            "eur_dzd_rate": decimal_micros(
                _dig(active.policy, "payments.chargily.eur_dzd_rate_micros")
            )
        },
        "providers": {
            "stripe_enabled": _dig(active.policy, "payments.providers.stripe_enabled"),
            "chargily_enabled": _dig(
                active.policy, "payments.providers.chargily_enabled"
            ),
            "chargily_new_checkouts": _dig(
                active.policy, "payments.chargily.new_checkouts_enabled"
            ),
        },
    }


@capability_required("view_settings")
def business_settings(request):
    active = get_active_business_settings()
    initial = _settings_initial(active)
    action = request.POST.get("action") if request.method == "POST" else ""
    pricing_form = PricingSettingsForm(
        request.POST if action == "pricing" else None,
        initial=initial["pricing"],
        auto_id="id_pricing_%s",
    )
    fx_form = FxSettingsForm(
        request.POST if action == "fx" else None,
        initial=initial["fx"],
        auto_id="id_fx_%s",
    )
    provider_form = ProviderSettingsForm(
        request.POST if action == "providers" else None,
        initial=initial["providers"],
        auto_id="id_providers_%s",
    )
    may_manage = has_admin_permission(request.user, "manage_settings")
    if not may_manage:
        for form in (pricing_form, fx_form, provider_form):
            for field in form.fields.values():
                field.disabled = True
    if request.method == "POST":
        if not may_manage:
            raise PermissionDenied(
                "Business settings management permission is required."
            )
        try:
            if action == "pricing" and pricing_form.is_valid():
                values = pricing_form.scaled_values()
                _save_settings_revision(
                    request,
                    path_updates={
                        "payments.posting_deposit.percent_bps": values[
                            "deposit_percent_bps"
                        ],
                        "payments.posting_deposit.min_eur_cents": values[
                            "deposit_min_eur_cents"
                        ],
                        "payments.posting_deposit.max_eur_cents": values[
                            "deposit_max_eur_cents"
                        ],
                        "pricing.global_floor_cents": values["global_floor_cents"],
                        "pricing.weight_rate_cents_per_kg": values[
                            "weight_rate_cents_per_kg"
                        ],
                        "pricing.recommendation_multiplier_bps": values[
                            "recommendation_multiplier_bps"
                        ],
                    },
                    commission_rate_bps=values["commission_rate_bps"],
                    reason=pricing_form.cleaned_data["reason"],
                )
                messages.success(
                    request, "Pricing settings were saved as a new audited version."
                )
                return redirect("admin_console:settings")
            if action == "fx" and fx_form.is_valid():
                _save_settings_revision(
                    request,
                    path_updates={
                        "payments.chargily.eur_dzd_rate_micros": fx_form.rate_micros()
                    },
                    commission_rate_bps=None,
                    reason=fx_form.cleaned_data["reason"],
                )
                messages.success(
                    request, "The Chargily FX rate was saved for future attempts."
                )
                return redirect("admin_console:settings")
            if action == "providers" and provider_form.is_valid():
                _save_settings_revision(
                    request,
                    path_updates={
                        "payments.providers.stripe_enabled": provider_form.cleaned_data[
                            "stripe_enabled"
                        ],
                        "payments.providers.chargily_enabled": provider_form.cleaned_data[
                            "chargily_enabled"
                        ],
                        "payments.chargily.new_checkouts_enabled": provider_form.cleaned_data[
                            "chargily_new_checkouts"
                        ],
                    },
                    commission_rate_bps=None,
                    reason=provider_form.cleaned_data["reason"],
                )
                messages.success(
                    request, "Provider availability was saved as a new audited version."
                )
                return redirect("admin_console:settings")
        except Exception as exc:
            _operation_error(request, "Business settings change", exc)
    active = get_active_business_settings()
    # The commission is the number the owner is most likely to change and the
    # one a percentage field explains least. The worked example comes from the
    # same pricing engine the marketplace uses, so it cannot drift from it.
    example_raw = calculate_offer_economics(3_000, active)
    example = {
        "traveler_reward": format_eur(example_raw["traveler_reward_minor"]),
        "platform_fee": format_eur(example_raw["platform_fee_minor"]),
        "sender_total": format_eur(example_raw["sender_total_minor"]),
    }
    commission = {
        "percent": f"{percent_from_bps(active.commission_rate_bps):.2f}".rstrip(
            "0"
        ).rstrip(".")
        + "%",
        "example": example,
    }
    deposit = {
        "percent": f"{percent_from_bps(_dig(active.policy, 'payments.posting_deposit.percent_bps')):.2f}".rstrip(
            "0"
        ).rstrip(".")
        + "%",
        "minimum": format_eur(
            _dig(active.policy, "payments.posting_deposit.min_eur_cents")
        ),
        "maximum": format_eur(
            _dig(active.policy, "payments.posting_deposit.max_eur_cents")
        ),
    }
    fx_rate = decimal_micros(
        _dig(active.policy, "payments.chargily.eur_dzd_rate_micros")
    )
    fx = {"rate": f"{fx_rate:,.2f}", "reads": f"1 EUR = {fx_rate:,.2f} DZD"}
    protection_labels = {
        "Delivery-code buffer after pickup",
        "Payout protection window",
        "Payment grace after acceptance",
        "Sender free-cancellation cutoff",
        "Late-cancellation compensation",
        "Late-cancellation compensation cap",
        "Rating review window",
        "Dispute evidence limit",
    }
    return _render(
        request,
        "admin/console/settings.html",
        {
            "title": "Business settings",
            "active": active,
            "pricing_form": pricing_form,
            "fx_form": fx_form,
            "provider_form": provider_form,
            "may_manage": may_manage,
            "rows": policy_rows(
                active.policy, commission_rate_bps=active.commission_rate_bps
            ),
            "protection_rows": [
                row
                for row in policy_rows(
                    active.policy, commission_rate_bps=active.commission_rate_bps
                )
                if row.label in protection_labels
            ],
            "boost_packages": boost_packages(active.policy),
            "providers": _provider_rows(),
            "example": example,
            "commission": commission,
            "deposit": deposit,
            "fx": fx,
        },
    )


def _database_status():
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return {
            "label": "Healthy",
            "tone": "ok",
            "detail": "Application database query succeeded.",
        }
    except Exception:
        return {
            "label": "Unavailable",
            "tone": "bad",
            "detail": "Database health query failed.",
        }


def _redis_status():
    client = None
    try:
        client = redis.Redis.from_url(
            settings.REDIS_URL, socket_timeout=1, socket_connect_timeout=1
        )
        client.ping()
        return {
            "label": "Healthy",
            "tone": "ok",
            "detail": "Redis responded to the application.",
        }
    except Exception:
        return {
            "label": "Degraded",
            "tone": "attn",
            "detail": "Redis did not respond; durable PostgreSQL obligations remain authoritative.",
        }
    finally:
        if client is not None:
            client.close()


@capability_required(
    "view_provider_health", "view_operational_incidents", "view_scheduled_jobs"
)
def system_status(request):
    jobs = ScheduledJob.objects.all()
    pending = jobs.filter(status=ScheduledJob.Status.PENDING)
    oldest = pending.order_by("run_at").values_list("run_at", flat=True).first()
    kyc_local = os.environ.get("KYC_RATE_LIMIT_LOCAL_MODE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    kyc_shared = bool(os.environ.get("KYC_RATE_LIMIT_REDIS_URL", "").strip())
    if kyc_shared:
        limiter = "Shared Redis"
    elif kyc_local:
        limiter = "Single-replica local mode"
    else:
        limiter = "Not configured"
    try:
        routing = route_provider_status()
    except Exception:
        routing = {"available": False, "code": "route_provider_status_unavailable"}
    # Every signal on this page is rendered from the same three fields, so an
    # operator learns one shape rather than four. Nothing here infers a worker
    # heartbeat the platform does not actually record.
    if routing.get("available"):
        routing_signal = {
            "label": "Healthy",
            "tone": "ok",
            "detail": "The routing provider answered.",
        }
    else:
        routing_signal = {
            "label": "Needs attention",
            "tone": "attn",
            "detail": "The routing provider did not answer; distance and detour checks fall back.",
        }
    if limiter == "Shared Redis":
        limiter_signal = {
            "label": "Healthy",
            "tone": "ok",
            "detail": "The shared limiter is active, which is safe on any number of replicas.",
        }
    elif limiter == "Single-replica local mode":
        limiter_signal = {
            "label": "Warning",
            "tone": "wait",
            "detail": "Local mode is only safe while exactly one application replica runs.",
        }
    else:
        limiter_signal = {
            "label": "Needs attention",
            "tone": "attn",
            "detail": "Configure the shared limiter before running more than one replica.",
        }
    release = getattr(settings, "RELEASE_ID", "") or ""
    release_signal = (
        {"label": release, "tone": "ok", "detail": "Deployed build identifier."}
        if release and release != "unknown"
        else {
            "label": "Unknown",
            "tone": "mute",
            "detail": "No release identifier is set for this deployment.",
        }
    )
    return _render(
        request,
        "admin/console/system.html",
        {
            "title": "System & operations",
            "release": getattr(settings, "RELEASE_ID", "unknown"),
            "release_signal": release_signal,
            "database": _database_status(),
            "redis": _redis_status(),
            "kyc_limiter": limiter,
            "limiter_signal": limiter_signal,
            "routing_signal": routing_signal,
            "storage": _storage_rows(),
            "providers": _provider_rows(),
            "routing": routing,
            "jobs": {
                "pending": pending.count(),
                "running": jobs.filter(status=ScheduledJob.Status.RUNNING).count(),
                "retrying": pending.filter(attempts__gt=0).count(),
                "failed": jobs.filter(status=ScheduledJob.Status.FAILED).count(),
                "oldest_age": age_label(oldest) if oldest else "None",
            },
            "email": {
                "pending": OutboundMessage.objects.filter(
                    status=OutboundMessage.Status.PENDING
                ).count(),
                "failed": OutboundMessage.objects.filter(
                    status=OutboundMessage.Status.FAILED
                ).count(),
                "dispatched": OutboundMessage.objects.filter(
                    status=OutboundMessage.Status.DISPATCHED
                ).count(),
            },
            "finance": {
                "provider_retryable": PaymentProviderEvent.objects.filter(
                    processing_result=PaymentProviderEvent.ProcessingResult.RETRYABLE
                ).count(),
                "provider_failed": PaymentProviderEvent.objects.filter(
                    processing_result=PaymentProviderEvent.ProcessingResult.FAILED
                ).count(),
                "manual_refunds": PaymentRefund.objects.filter(
                    requires_manual_action=True,
                    status__in=(
                        PaymentRefund.Status.PENDING,
                        PaymentRefund.Status.PROCESSING,
                    ),
                ).count(),
                "eligible_payouts": Payout.objects.filter(
                    status=Payout.Status.ELIGIBLE
                ).count(),
            },
        },
    )


@capability_required("view_scheduled_jobs", "view_operational_incidents")
def background_jobs(request):
    queryset = _filter_choice(ScheduledJob.objects.order_by("run_at"), request)
    page_obj = _page(request, queryset)
    return _table(
        request,
        title="Background jobs",
        description="Durable obligations. Use the job reference to investigate logs before any technical requeue; payloads and raw errors stay private.",
        columns=("Work", "State", "Attempts", "Scheduled", "Reference"),
        rows=[
            {
                "cells": (
                    text_cell(job.get_kind_display(), kind="strong"),
                    status_cell(job.status, job.get_status_display()),
                    text_cell(f"{job.attempts} / {job.max_attempts}"),
                    datetime_cell(job.run_at),
                    text_cell(f"Job {job.pk}"),
                )
            }
            for job in page_obj.object_list
        ],
        page_obj=page_obj,
        empty_title="No background jobs in this state",
        empty_text="No durable work matches the selected filter.",
        filter_choices=tuple(ScheduledJob.Status.choices),
    )


@capability_required("view_provider_health")
def email_queue(request):
    queryset = _filter_choice(OutboundMessage.objects.order_by("-created_at"), request)
    page_obj = _page(request, queryset)
    return _table(
        request,
        title="Transactional email",
        description="Durable email obligations and transport state. Message bodies, tokens and raw transport errors are not displayed.",
        columns=(
            "Message",
            "State",
            "Attempts",
            "Next attempt",
            "Created",
            "Reference",
        ),
        rows=[
            {
                "cells": (
                    text_cell(message.get_kind_display(), kind="strong"),
                    status_cell(message.status, message.get_status_display()),
                    text_cell(f"{message.attempts} / {message.max_attempts}"),
                    datetime_cell(message.next_attempt_at),
                    datetime_cell(message.created_at),
                    text_cell(f"Message {message.pk}"),
                )
            }
            for message in page_obj.object_list
        ],
        page_obj=page_obj,
        empty_title="No email in this state",
        empty_text="No email obligations match the selected filter.",
        filter_choices=tuple(OutboundMessage.Status.choices),
    )


@capability_required("view_operational_incidents", "view_journeys")
def geography(request):
    countries = Country.objects.annotate(
        place_count=Count("places"),
        active_place_count=Count("places", filter=Q(places__active=True)),
    ).order_by("name")
    return _render(
        request,
        "admin/console/geography.html",
        {
            "title": "Geography catalogue",
            "countries": countries,
            "places": Place.objects.count(),
            "active_places": Place.objects.filter(active=True).count(),
            "airports": Place.objects.filter(
                place_type=Place.PlaceType.AIRPORT, active=True
            ).count(),
            "primary_mappings": AirportLocalityMapping.objects.filter(
                active=True,
                is_primary=True,
                relationship_type=AirportLocalityMapping.RelationshipType.SERVED,
            ).count(),
            # Which reviewed manifest this database actually holds. Counts alone
            # cannot answer "is this the catalogue the release shipped?" after a
            # partial or a superseded import; the digest can.
            "catalogue_import": GeographyCatalogueImport.objects.first(),
        },
    )


@capability_required("view_audit_log")
def audit_log(request):
    queryset = AdminAuditLog.objects.select_related("actor").order_by(
        "-created_at", "-id"
    )
    queryset = _search(
        queryset,
        request,
        ("action", "target_type", "target_id", "reason", "reference", "actor__email"),
    )
    page_obj = _page(request, queryset)
    rows = [
        {
            "cells": (
                text_cell(item.actor.email if item.actor else "System", kind="strong"),
                text_cell(humanize_action(item.action), item.action),
                text_cell(
                    humanize_object(item.target_type),
                    f"#{item.target_id}" if item.target_id else "",
                ),
                text_cell(item.reason or "—", item.reference),
                datetime_cell(item.created_at, relative=True),
            )
        }
        for item in page_obj.object_list
    ]
    return _table(
        request,
        title="Audit log",
        description="Who did what, to which record, and when. The immutable log keeps the safe before/after context behind each row.",
        eyebrow="Reference",
        columns=("Who", "Action", "Object", "Reason / reference", "When"),
        rows=rows,
        page_obj=page_obj,
        empty_title="No administrative actions",
        empty_text="No audited operator action matches this search.",
        search_placeholder="Search actor, action or reference",
    )


@staff_member_required
def technical_records(request):
    if not request.user.is_superuser:
        raise PermissionDenied(
            "Technical records are limited to the owner/Super Admin."
        )
    return _render(
        request,
        "admin/console/technical.html",
        {
            "title": "Technical records",
            "apps": admin.site.get_app_list(request),
        },
    )
