"""The Finance queue for Traveler DZD payout methods waiting on a person.

H4 built the review decision and H4.1 put one *approve* control on the manual
payout screen. Both of those start from a payout — so a Traveler who has just
submitted a CCP account and a crossed cheque, and who has no funded delivery
yet, was invisible to Finance. There was no list, no count, no detail and no way
to refuse: the only reachable decision in the whole console was "approve", and
only once money was already owed.

This module is that missing surface, and it is deliberately only that:

* **It owns no state machine.** Every decision goes to
  `apps.finance.payout_manual_profiles.review_profile`, which re-checks the
  evidence, the identity attestation and the name comparison inside its own
  transaction. The three outcomes here are the three `PayoutProfileReview`
  statuses H4 already writes.
* **It reads, it does not compute.** Readiness is `approved_profile`, the one
  authority every other surface asks. Nothing here decides whether a profile is
  usable.
* **It is cheap.** The H5 control-plane snapshot costs roughly ninety queries
  and several seconds; a queue an operator opens all day must not. This reads
  the payout-method rows directly, with the reviews, the evidence and the
  identity facts each fetched once for the whole page.

What it may show is bounded by H4.1's rule: no account value, masked or
otherwise, appears in a list. The full CCP number, CCP key and RIP exist on the
detail page only, inside the same deliberate, audited reveal the manual payout
screen uses.
"""

from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Exists, OuterRef, Prefetch
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.debug import (
    sensitive_post_parameters,
    sensitive_variables,
)

from apps.finance.models import (
    DzdPayoutProfileRevision,
    PayoutIdentityAttestation,
    PayoutIdentityReviewAssignment,
    PayoutProfileReview,
    TravelerPayoutMethod,
)
from apps.finance.payout_evidence import CHEQUE_LABELS, read_evidence
from apps.finance.payout_manual_profiles import (
    REVIEW_DECISIONS,
    approved_profile,
    reveal_profile,
    review_profile,
)
from apps.finance.payout_profiles import (
    assign_identity_review,
    profile_name_consistency,
    require_capabilities,
)

from .permissions import has_admin_permission


#: One bucket per row, in the order an operator cares about them. `waiting` is
#: the only one that is Finance's move; the other three are recorded outcomes.
BUCKETS = (
    (
        "waiting",
        "Waiting for review",
        "Submitted and not yet decided. Finance has to look at these.",
        "bad",
    ),
    (
        "correction",
        "Correction requested",
        "Sent back to the Traveler. They have to resubmit.",
        "attn",
    ),
    (
        "rejected",
        "Rejected",
        "Refused. The Traveler must submit a different account.",
        "attn",
    ),
    (
        "approved",
        "Approved",
        "Usable as a payout destination for future deliveries.",
        "ok",
    ),
)

#: The wording each decision gets on the page and in the audit trail's reading.
DECISIONS = {
    "approved": (
        "Approve",
        "The account holder matches the attested identity and the cheque is "
        "legible. The Traveler can be paid to this account.",
        "ok",
    ),
    "needs_attention": (
        "Needs correction",
        "Something is wrong but fixable — an unreadable cheque, a mismatched "
        "name, a wrong digit. The Traveler is asked to submit again.",
        "attn",
    ),
    "rejected": (
        "Reject",
        "This account cannot be used. The Traveler is told the account was "
        "refused, not why.",
        "bad",
    ),
}

#: How a payout method's stored status and reason read to a person. The machine
#: code stays beside the sentence — H4.1's rule — because an operator reporting a
#: problem needs the string the logs use, and a sentence alone cannot be grepped.
METHOD_STATUS = {
    "pending_review": "Waiting on Finance",
    "needs_review": "Not usable for payouts",
    "ready": "Usable for future payouts",
    "setup_required": "Not set up",
    "unavailable": "Unavailable",
    "disabled": "Switched off by the Traveler",
}

METHOD_REASON = {
    "profile_review_required": "submitted and not yet decided",
    "profile_correction_required": "a correction was asked for",
    "profile_rejected": "the account was refused",
    "cross_user_account_review": "this account is claimed by another Traveler too",
}

#: Known domain refusals, said as something an operator can act on. Anything
#: else falls back to the domain's own authored English, which never carries a
#: stack trace, a provider detail or an exception repr.
REFUSALS = {
    "Current attested identity required.": (
        "Nobody has attested this Traveler's legal name against their KYC yet. "
        "Assign an identity review below; the profile cannot be approved or "
        "refused until that is recorded."
    ),
    "Full crossed cheque evidence required.": (
        "The crossed cheque is missing or its upload never completed. The "
        "Traveler has to submit the profile again with a readable photo."
    ),
    "Approved KYC required.": (
        "This Traveler has no current approved KYC submission, so no identity "
        "review can be assigned. Trust has to approve their KYC first."
    ),
    "Identity reviewer capability required.": (
        "That operator cannot attest identities. Choose someone with the "
        "identity-attestation capability."
    ),
    "Payout capability required.": (
        "You do not hold the capabilities this review needs."
    ),
    "Payout profiles are disabled.": (
        "Payout profiles are switched off in this environment. Nothing can be "
        "reviewed until the rail is enabled."
    ),
}


def _refuse(request, label, exc):
    raw = " ".join(getattr(exc, "messages", None) or [str(exc)]).strip()
    messages.error(request, f"{label} was refused. {REFUSALS.get(raw, raw)}")


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _reviews_prefetch():
    return Prefetch(
        "current_version__dzd_profile_revision__reviews",
        queryset=PayoutProfileReview.objects.select_related("reviewer").order_by("pk"),
    )


def reviewable_methods():
    """Every DZD method whose *current* version carries a profile revision.

    Superseded revisions are deliberately out of scope. A Traveler who replaces
    their details has replaced what a future payout would be sent to, and a
    queue that still asked Finance to decide the old one would be asking for a
    decision with no effect.
    """

    return (
        TravelerPayoutMethod.objects.filter(
            currency="DZD",
            current_version__dzd_profile_revision__isnull=False,
        )
        .select_related(
            "traveler",
            "current_version",
            "current_version__dzd_profile_revision",
            "current_version__dzd_profile_revision__evidence",
        )
        .prefetch_related(_reviews_prefetch())
    )


def awaiting_review_count() -> int:
    """How many payout methods are Finance's move, in one indexed query.

    This is the number the Finance Overview publishes under Needs attention, so
    it has to mean exactly one thing: a submitted profile revision that nobody
    has decided. A profile sent back for correction is the Traveler's move and
    is not counted here; it is still one click away in the queue.
    """

    reviewed = PayoutProfileReview.objects.filter(
        profile_id=OuterRef("current_version__dzd_profile_revision_id")
    )
    return (
        TravelerPayoutMethod.objects.filter(
            currency="DZD",
            current_version__dzd_profile_revision__isnull=False,
        )
        .annotate(has_review=Exists(reviewed))
        .filter(has_review=False)
        .count()
    )


def _bucket(reviews):
    if not reviews:
        return "waiting"
    return {
        "approved": "approved",
        "needs_attention": "correction",
        "rejected": "rejected",
    }[reviews[-1].status]


def _identity_facts(traveler_ids):
    """Current attestation and open assignment for a whole page, in two queries.

    Asking each row separately is what turns a twenty-row queue into forty
    extra round trips, and this page is opened far more often than it is acted
    on.
    """

    now = timezone.now()
    attested = set(
        PayoutIdentityAttestation.objects.filter(
            traveler_id__in=traveler_ids,
            revocation__isnull=True,
            successors__isnull=True,
            kyc_submission__status="approved",
        )
        .exclude(kyc_submission__expires_at__lte=now)
        .values_list("traveler_id", flat=True)
    )
    assignments = {
        row.traveler_id: row
        for row in PayoutIdentityReviewAssignment.objects.filter(
            traveler_id__in=traveler_ids, closed_at__isnull=True
        )
        .select_related("reviewer")
        .order_by("traveler_id", "pk")
    }
    return attested, assignments


def _evidence_state(profile):
    evidence = profile.evidence if profile.evidence_id else None
    if evidence is None:
        return {"present": False, "label": "No cheque attached", "tone": "bad"}
    if evidence.upload_state != "complete":
        return {"present": False, "label": "Upload incomplete", "tone": "bad"}
    return {
        "present": True,
        "label": "Crossed cheque attached",
        "tone": "ok",
        "reference": str(evidence.public_reference),
        "uploaded_at": evidence.created_at,
    }


def queue_rows(methods, *, bucket=""):
    """The safe queue projection. No account value appears here, masked or not."""

    methods = list(methods)
    attested, assignments = _identity_facts({m.traveler_id for m in methods})
    rows = []
    for method in methods:
        profile = method.current_version.dzd_profile_revision
        reviews = list(profile.reviews.all())
        key = _bucket(reviews)
        if bucket and key != bucket:
            continue
        latest = reviews[-1] if reviews else None
        assignment = assignments.get(method.traveler_id)
        rows.append(
            {
                "reference": str(profile.public_reference),
                "bucket": key,
                "bucket_label": next(b[1] for b in BUCKETS if b[0] == key),
                "bucket_tone": next(b[3] for b in BUCKETS if b[0] == key),
                "traveler": {
                    "id": method.traveler_id,
                    "name": method.traveler.full_name or method.traveler.email,
                    "email": method.traveler.email,
                },
                "revision": profile.sequence,
                "method_version": method.current_version.sequence,
                "submitted_at": profile.submitted_at,
                "evidence": _evidence_state(profile),
                "reason": latest.reason_code if latest else "",
                "decided_by": (
                    (latest.reviewer.full_name or latest.reviewer.email)
                    if latest
                    else ""
                ),
                "decided_at": latest.created_at if latest else None,
                "identity_attested": method.traveler_id in attested,
                "identity_reviewer": (
                    (assignment.reviewer.full_name or assignment.reviewer.email)
                    if assignment
                    else ""
                ),
                "blocked": key == "waiting" and method.traveler_id not in attested,
            }
        )
    return rows


def bucket_counts(methods):
    counts = {key: 0 for key, *_ in BUCKETS}
    for method in methods:
        counts[_bucket(list(method.current_version.dzd_profile_revision.reviews.all()))] += 1
    return counts


@sensitive_variables()
def review_view(profile, *, user, revealed=None):
    """One profile revision, read for the person deciding it.

    The name comparison is the only thing here that touches decrypted values,
    and it returns a classification — `consistent`, `alias_match`, `different` —
    never the names themselves. Reading it is audited by H4's own
    `payout_identity.compared` record.
    """

    method = profile.method
    reviews = list(profile.reviews.all())
    latest = reviews[-1] if reviews else None
    attested, assignments = _identity_facts({method.traveler_id})
    assignment = assignments.get(method.traveler_id)
    identity_ok = method.traveler_id in attested
    comparison = ""
    if identity_ok:
        comparison = profile_name_consistency(actor=user, profile=profile)[
            "classification"
        ]
    is_current = method.current_version.dzd_profile_revision_id == profile.pk
    may_review = has_admin_permission(user, "review_payout_profiles")
    return {
        "reference": str(profile.public_reference),
        "revision": profile.sequence,
        "submitted_at": profile.submitted_at,
        "is_current": is_current,
        "bucket": _bucket(reviews),
        "bucket_label": next(b[1] for b in BUCKETS if b[0] == _bucket(reviews)),
        "bucket_tone": next(b[3] for b in BUCKETS if b[0] == _bucket(reviews)),
        "approved": approved_profile(profile),
        "traveler": {
            "id": method.traveler_id,
            "name": method.traveler.full_name or method.traveler.email,
            "email": method.traveler.email,
        },
        "method": {
            "reference": str(method.public_reference),
            "version": method.current_version.sequence,
            "status": method.status,
            "status_label": METHOD_STATUS.get(method.status, method.status),
            "status_reason": method.status_reason,
            "reason_label": METHOD_REASON.get(method.status_reason, ""),
            "enabled": method.enabled,
        },
        # Masks only. The full values are reachable from the reveal below and
        # from nowhere else on this page.
        "masked": {
            "ccp": f"•••• {profile.ccp_last_four}",
            "key": "••",
            "rip": f"•••• {profile.rip_last_four}",
        },
        "evidence": {**_evidence_state(profile), "labels": CHEQUE_LABELS},
        "identity": {
            "attested": identity_ok,
            "comparison": comparison,
            "assignment": (
                {
                    "reference": str(assignment.public_reference),
                    "reviewer": assignment.reviewer.full_name
                    or assignment.reviewer.email,
                    "assigned_at": assignment.created_at,
                }
                if assignment
                else None
            ),
        },
        "history": [
            {
                "status": row.status,
                "label": DECISIONS[row.status][0],
                "tone": DECISIONS[row.status][2],
                "reason": row.reason_code,
                "reviewer": row.reviewer.full_name or row.reviewer.email,
                "at": row.created_at,
            }
            for row in reversed(reviews)
        ],
        "latest": latest.status if latest else "",
        "revealed": revealed,
        "may": {
            # A decision is only offered where the domain would accept one: the
            # evidence has to exist and an identity has to be attested, or
            # `review_profile` refuses and the operator learns that from an
            # error instead of from the page.
            "review": may_review and identity_ok and _evidence_state(profile)["present"],
            "reveal": has_admin_permission(user, "view_payout_sensitive"),
            "evidence": has_admin_permission(user, "view_payout_evidence"),
            "assign": may_review and not identity_ok,
        },
        "needs_name_acceptance": bool(comparison and comparison != "consistent"),
    }


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


def _profile_or_404(reference):
    profile = (
        DzdPayoutProfileRevision.objects.select_related(
            "method__traveler", "method__current_version", "evidence"
        )
        .prefetch_related(
            Prefetch(
                "reviews",
                queryset=PayoutProfileReview.objects.select_related(
                    "reviewer"
                ).order_by("pk"),
            )
        )
        .filter(public_reference=reference)
        .first()
    )
    if profile is None or profile.method.currency != "DZD":
        raise Http404
    return profile


def reviewer_choices():
    """Staff who can actually attest an identity, for the assignment control."""

    from django.contrib.auth import get_user_model

    from .permissions import has_all_admin_permissions

    User = get_user_model()
    return [
        user
        for user in User.objects.filter(is_staff=True, is_active=True).order_by(
            "email"
        )
        if has_all_admin_permissions(user, "attest_payout_identity")
    ]


def payout_reviews(request):
    """The queue. One bucket at a time, newest submission first."""

    from .console_views import _render

    require_capabilities(request.user, "review_payout_profiles")
    methods = list(reviewable_methods().order_by("-current_version__created_at", "-pk"))
    counts = bucket_counts(methods)
    requested = request.GET.get("bucket", "")
    if requested not in counts:
        requested = "waiting"
    rows = queue_rows(methods, bucket=requested)
    return _render(
        request,
        "admin/console/payout_reviews.html",
        {
            "title": "Payout method reviews",
            "buckets": [
                {
                    "key": key,
                    "label": label,
                    "says": says,
                    "tone": tone,
                    "count": counts[key],
                    "selected": key == requested,
                }
                for key, label, says, tone in BUCKETS
            ],
            "rows": rows,
            "selected": requested,
            "selected_label": next(b[1] for b in BUCKETS if b[0] == requested),
            "total": len(methods),
        },
    )


@sensitive_post_parameters("__ALL__")
@sensitive_variables()
def payout_review_detail(request, reference):
    """One profile revision, and the three decisions a reviewer may record."""

    from .console_views import _render

    require_capabilities(
        request.user, "review_payout_profiles", "view_payout_sensitive"
    )
    profile = _profile_or_404(reference)
    revealed = None
    if request.method == "POST":
        action = request.POST.get("action", "")
        try:
            if action == "reveal":
                revealed = reveal_profile(
                    actor=request.user, reference=profile.public_reference
                )
            elif action == "assign":
                assign_identity_review(
                    actor=request.user,
                    traveler_id=profile.method.traveler_id,
                    reviewer_id=int(request.POST.get("reviewer") or 0),
                )
                messages.success(
                    request,
                    "An identity review was assigned. The reviewer records the "
                    "attested legal name against this Traveler's KYC; the "
                    "profile can be decided once they have.",
                )
                return redirect("admin_console:payout-review-detail", reference=reference)
            elif action == "decide":
                decision = request.POST.get("decision", "")
                if decision not in REVIEW_DECISIONS:
                    raise ValidationError("Unknown payout profile review decision.")
                review = review_profile(
                    actor=request.user,
                    reference=profile.public_reference,
                    decision=decision,
                    accept_name_difference=request.POST.get("accept_name_difference")
                    == "on",
                )
                if review.status == "approved":
                    # An approval can be the last thing a waiting payout needed.
                    # Re-evaluating here is what makes the queue and the payout
                    # agree without an operator going to find the payout.
                    from apps.finance.payout_release import evaluate_payout_release

                    for deal_id in _waiting_deal_ids(profile):
                        evaluate_payout_release(deal_id=deal_id)
                messages.success(
                    request,
                    f"Recorded: {DECISIONS[review.status][0]}. "
                    "The decision is immutable and is on this profile's history.",
                )
                return redirect("admin_console:payout-review-detail", reference=reference)
            else:
                raise ValidationError("Unknown payout review action.")
        except ValueError:
            messages.error(
                request,
                "That request was malformed and was not applied. Reload the page "
                "and try again.",
            )
        except (ValidationError, PermissionDenied) as exc:
            _refuse(request, "The review", exc)
    profile = _profile_or_404(reference)
    response = _render(
        request,
        "admin/console/payout_review_detail.html",
        {
            "title": f"Payout method review · revision #{profile.sequence}",
            "review": review_view(profile, user=request.user, revealed=revealed),
            "decisions": [
                {"key": key, "label": label, "says": says, "tone": tone}
                for key, (label, says, tone) in DECISIONS.items()
            ],
            "reviewers": reviewer_choices(),
        },
    )
    response["Cache-Control"] = "no-store, private"
    return response


def _waiting_deal_ids(profile):
    """Deals whose payout is frozen on *this* profile revision."""

    from apps.finance.models import Payout

    return list(
        Payout.objects.filter(
            dzd_profile_revision_id=profile.pk,
            status__in=("blocked", "eligible", "scheduled"),
        ).values_list("deal_id", flat=True)
    )


@sensitive_variables()
def payout_review_evidence(request, reference):
    """This profile revision's own crossed cheque, and nothing else.

    Scoped the way `console_manual_payout.manual_evidence` is scoped: the
    reference in the URL names the *profile*, and the document served is the one
    that profile owns. There is no path here to an arbitrary evidence id, so a
    capable operator still cannot read another Traveler's document through this
    route.
    """

    from apps.core.storage import StorageNotConfigured
    from botocore.exceptions import BotoCoreError, ClientError

    require_capabilities(
        request.user,
        "review_payout_profiles",
        "view_payout_sensitive",
        "view_payout_evidence",
    )
    profile = _profile_or_404(reference)
    if not profile.evidence_id or profile.evidence.upload_state != "complete":
        raise Http404
    try:
        body, mime = read_evidence(
            actor=request.user, reference=profile.evidence.public_reference
        )
    except (StorageNotConfigured, BotoCoreError, ClientError, ValidationError):
        return HttpResponse(
            "Private payout evidence is temporarily unavailable.",
            content_type="text/plain; charset=utf-8",
            status=503,
            headers={"Cache-Control": "no-store, private"},
        )
    response = HttpResponse(body, content_type=mime)
    response["Cache-Control"] = "no-store, private"
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "no-referrer"
    response["Content-Disposition"] = 'inline; filename="payout-evidence"'
    return response
