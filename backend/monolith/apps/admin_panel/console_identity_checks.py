"""Payout identity checks: the Trust side of DZD payout-method approval.

Finance can ask for an identity check (`assign_identity_review`) and the
assigned reviewer records the Traveler's legal name from their approved ID
(`attest_identity`). Until J6.4 only the first of those had a console surface;
the second existed only as a JSON endpoint, so an assigned check could never be
completed from the console and the payout method behind it could never be
decided.

This is that surface and nothing more: the open checks, and for the reviewer a
check is assigned to, the approved ID document beside a two-field form. The
attestation is still `attest_identity`, which re-checks the capability, that the
assignment is theirs and still open, that the ID is still approved, and the
names. No name is ever shown back: an attested legal name is encrypted at rest
and only its comparison classification is ever read out.
"""

from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.debug import (
    sensitive_post_parameters,
    sensitive_variables,
)

from apps.finance.models import PayoutIdentityAttestation, PayoutIdentityReviewAssignment
from apps.finance.payout_profiles import attest_identity

from .console_payout_reviews import (
    REFUSALS,
    identity_form_values,
    kyc_state,
    reviewable_methods,
)
from .people_links import display_name, may_open_people, person_href
from .permissions import has_admin_permission


def _already_confirmed():
    """True when the Traveler has an attestation newer than the assignment.

    An assignment can go stale without being closed: Super Admin may have
    confirmed the identity on the review page while a check assigned to someone
    else was still open. That check is no longer anybody's work.
    """

    return Exists(
        PayoutIdentityAttestation.objects.filter(
            traveler_id=OuterRef("traveler_id"),
            revocation__isnull=True,
            successors__isnull=True,
            kyc_submission__status="approved",
            attested_at__gte=OuterRef("created_at"),
        )
    )


def open_checks():
    return PayoutIdentityReviewAssignment.objects.filter(
        closed_at__isnull=True
    ).annotate(confirmed=_already_confirmed())


def waiting_for(user) -> int:
    """Open checks assigned to this operator that still need them. One query."""

    return open_checks().filter(reviewer=user, confirmed=False).count()


def identity_checks(request):
    from .console_views import _render

    if not has_admin_permission(request.user, "attest_payout_identity"):
        raise PermissionDenied
    scope = "all" if request.GET.get("scope") == "all" else "mine"
    queryset = open_checks().select_related("traveler", "reviewer", "assigned_by")
    if scope == "mine":
        queryset = queryset.filter(reviewer=request.user)
    page = Paginator(
        queryset.order_by("confirmed", "created_at", "pk"), 25
    ).get_page(request.GET.get("page"))
    linkable = may_open_people(request.user)
    rows = [
        {
            "url": reverse("admin_console:identity-check-detail", args=(row.public_reference,)),
            "traveler": display_name(row.traveler),
            "email": row.traveler.email,
            "traveler_href": (
                person_href(row.traveler_id, source="identity-checks") if linkable else ""
            ),
            "reviewer": display_name(row.reviewer),
            "is_mine": row.reviewer_id == request.user.pk,
            "assigned_by": display_name(row.assigned_by),
            "assigned_at": row.created_at,
            "confirmed": row.confirmed,
        }
        for row in page.object_list
    ]
    return _render(
        request,
        "admin/console/identity_checks.html",
        {
            "title": "Payout identity checks",
            "rows": rows,
            "page_obj": page,
            "scope": scope,
            "mine_count": waiting_for(request.user),
        },
    )


@sensitive_post_parameters("__ALL__")
@sensitive_variables()
def identity_check_detail(request, reference):
    from .console_views import _render, kyc_evidence_slots

    if not has_admin_permission(request.user, "attest_payout_identity"):
        raise PermissionDenied
    assignment = (
        open_checks()
        .select_related("traveler", "reviewer", "assigned_by", "kyc_submission")
        .filter(public_reference=reference)
        .first()
    )
    if assignment is None:
        raise Http404
    is_mine = assignment.reviewer_id == request.user.pk
    if request.method == "POST":
        if not is_mine:
            raise PermissionDenied("Only the assigned reviewer can confirm this identity.")
        try:
            attest_identity(
                actor=request.user,
                assignment_reference=assignment.public_reference,
                **identity_form_values(request.POST),
            )
        except (ValidationError, PermissionDenied) as exc:
            raw = " ".join(getattr(exc, "messages", None) or [str(exc)]).strip()
            messages.error(
                request, f"The identity check was not recorded. {REFUSALS.get(raw, raw)}"
            )
        else:
            messages.success(
                request,
                f"Identity confirmed for {display_name(assignment.traveler)}. Finance "
                "can now approve or reject their payout method.",
            )
            return redirect("admin_console:identity-checks")

    kyc = kyc_state(assignment.traveler_id)
    submission = assignment.kyc_submission
    usable = (
        submission.status == "approved"
        and not (submission.expires_at and submission.expires_at <= timezone.now())
    )
    documents, unavailable = ([], False)
    if has_admin_permission(request.user, "view_kyc"):
        documents, unavailable = kyc_evidence_slots(
            submission, user=request.user, request=request
        )
    waiting_method = (
        reviewable_methods()
        .filter(traveler_id=assignment.traveler_id, bucket="waiting")
        .select_related("current_version__dzd_profile_revision")
        .first()
    )
    review_url = ""
    if waiting_method is not None and has_admin_permission(
        request.user, "review_payout_profiles"
    ):
        review_url = reverse(
            "admin_console:payout-review-detail",
            args=(waiting_method.current_version.dzd_profile_revision.public_reference,),
        )
    return _render(
        request,
        "admin/console/identity_check_detail.html",
        {
            "title": f"Identity check · {display_name(assignment.traveler)}",
            "check": {
                "traveler": display_name(assignment.traveler),
                "email": assignment.traveler.email,
                "traveler_href": (
                    person_href(assignment.traveler_id, source="identity-checks", tab="identity")
                    if may_open_people(request.user)
                    else ""
                ),
                "reviewer": display_name(assignment.reviewer),
                "assigned_by": display_name(assignment.assigned_by),
                "assigned_at": assignment.created_at,
                "confirmed": assignment.confirmed,
                "is_mine": is_mine,
                "submission": submission,
                "submission_usable": usable,
                "kyc_state": kyc["state"],
                "kyc_url": (
                    reverse("admin_console:kyc-detail", args=(submission.pk,))
                    if has_admin_permission(request.user, "view_kyc")
                    else ""
                ),
            },
            "documents": documents,
            "documents_unavailable": unavailable,
            "review_url": review_url,
        },
    )
