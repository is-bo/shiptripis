"""The DZD payout-method review queue and its one-decision review page.

J1.2 built this surface and J6.4 rebuilt it around the decision the owner is
actually making. J1.2's page was correct and exhausting: every warning, machine
code and prerequisite sat above the controls, and one prerequisite had no
console surface at all — `attest_identity` was reachable only through a JSON
API, so a fresh submission could be assigned for identity review and then never
decided. That is the "Approve does not work" the owner reported.

What this module is, and is not:

* **It owns no state machine.** Every decision still goes to
  `apps.finance.payout_manual_profiles.review_profile`, which re-checks the
  evidence, the identity attestation and the name comparison inside its own
  transaction. Identity is still established only by `assign_identity_review`
  followed by `attest_identity`. J6.4 composes those two existing, audited,
  capability-checked commands for an operator who holds both capabilities
  (Super Admin); it does not add a path around either.
* **It reads, it does not compute.** Readiness is `approved_profile`.
* **It is cheap.** The queue reads payout-method rows directly, with reviews,
  evidence and identity facts each fetched once for the page.

What it may show is H4.1's rule, unchanged: no account value, masked or
otherwise, appears in a list. The full CCP number, key and RIP exist on the
review page only, inside one deliberate, audited reveal.
"""

from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Case, Count, OuterRef, Prefetch, Subquery, Value, When
from django.db.models.fields import CharField
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
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
    attest_identity,
    profile_name_consistency,
    require_capabilities,
)
from apps.kyc.models import KycSubmission

from .console_presenters import age_label
from .people_links import display_name, initials, may_open_people, person_href
from .permissions import has_admin_permission, has_all_admin_permissions


#: One bucket per row. `waiting` is the only one that is Finance's move; the
#: other three are recorded outcomes and live under History.
BUCKETS = (
    ("waiting", "Waiting for review", "bad"),
    ("correction", "Correction requested", "attn"),
    ("rejected", "Rejected", "mute"),
    ("approved", "Approved", "ok"),
)
BUCKET_LABELS = {key: label for key, label, _ in BUCKETS}
BUCKET_TONES = {key: tone for key, _, tone in BUCKETS}

#: A decision as a verb on its button, and as a fact once it is recorded.
DECISIONS = {
    "approved": ("Approve", "Approved", "ok"),
    "rejected": ("Reject", "Rejected", "bad"),
    "needs_attention": ("Ask for a correction", "Correction requested", "attn"),
}

#: What each recorded decision means for the Traveler, said once, on success.
DECISION_OUTCOMES = {
    "approved": "Approved. This CCP account can now receive the Traveler's DZD payouts.",
    "rejected": (
        "Rejected. The Traveler is told the account was refused and asked to add "
        "a different one."
    ),
    "needs_attention": (
        "Correction requested. The Traveler is asked to submit their payout "
        "details again."
    ),
}

METHOD_STATUS = {
    "pending_review": "Waiting on Finance",
    "needs_review": "Not usable for payouts",
    "ready": "Usable for future payouts",
    "setup_required": "Not set up",
    "unavailable": "Unavailable",
    "disabled": "Switched off by the Traveler",
}

#: `compare_names` classifications, as what the reviewer has to weigh.
NAME_COMPARISON = {
    "consistent": ("Matches the verified identity", "ok"),
    "review_alias_spelling": ("Same name, spelled differently", "attn"),
    "mismatch": ("Does not match the verified identity", "bad"),
    "insufficient_attestation": ("No verified name to compare yet", "mute"),
}


def name_comparison_label(code):
    """A `compare_names` classification as a sentence."""

    if not code:
        return ""
    return NAME_COMPARISON.get(code, (code, "mute"))[0]


#: Known refusals, said as something an operator can act on. Anything else
#: falls back to the domain's own authored English, which never carries a
#: stack trace, a provider detail or an exception repr.
REFUSALS = {
    "Current attested identity required.": (
        "Nobody has confirmed this Traveler's legal name yet. Complete the "
        "identity check first."
    ),
    "Full crossed cheque evidence required.": (
        "No complete crossed-cheque photo is attached. The Traveler has to submit "
        "their details again with a readable photo."
    ),
    "Approved KYC required.": (
        "This Traveler has no current approved ID. Their KYC submission has to "
        "be approved first."
    ),
    "Current approved KYC and open assignment required.": (
        "The identity check could not be recorded against a current approved ID. "
        "Reload the page and try again."
    ),
    "Identity reviewer capability required.": (
        "That person cannot confirm identities. Choose someone with Trust & "
        "Verification or Super Admin access."
    ),
    "Legal given and family names required.": (
        "Enter both the legal first name(s) and the legal last name exactly as "
        "they appear on the ID."
    ),
    "Invalid attested aliases.": "The other spelling could not be read. Check it and try again.",
    "Payout capability required.": "Your role cannot do this.",
    "Payout profiles are disabled.": (
        "Payout profiles are switched off in this environment, so nothing can be "
        "reviewed."
    ),
    "identity_check_unconfirmed": (
        "Tick the box to confirm you compared the names with the ID document."
    ),
    "alias_incomplete": "Enter both parts of the other spelling, or leave both empty.",
    "name_difference_unaccepted": (
        "The name on this account differs from the verified identity. Tick the "
        "box to accept the difference, or reject the payout method."
    ),
}


def _refuse(request, label, exc):
    raw = " ".join(getattr(exc, "messages", None) or [str(exc)]).strip()
    messages.error(request, f"{label} was not recorded. {REFUSALS.get(raw, raw)}")


# ---------------------------------------------------------------------------
# Reading the queue
# ---------------------------------------------------------------------------


def _reviews_prefetch():
    return Prefetch(
        "current_version__dzd_profile_revision__reviews",
        queryset=PayoutProfileReview.objects.select_related("reviewer").order_by("pk"),
    )


#: Which bucket a profile falls in, decided in SQL from the latest review, so
#: the page can filter, count and page by it in the database.
_LATEST_REVIEW = Subquery(
    PayoutProfileReview.objects.filter(
        profile_id=OuterRef("current_version__dzd_profile_revision_id")
    )
    .order_by("-pk")
    .values("status")[:1]
)

_BUCKET = Case(
    When(latest_review="approved", then=Value("approved")),
    When(latest_review="needs_attention", then=Value("correction")),
    When(latest_review="rejected", then=Value("rejected")),
    default=Value("waiting"),
    output_field=CharField(),
)


def reviewable_methods():
    """Every DZD method whose *current* version carries a profile revision.

    Superseded revisions are out of scope: a Traveler who replaced their details
    replaced what a future payout would be sent to.
    """

    return TravelerPayoutMethod.objects.filter(
        currency="DZD",
        current_version__dzd_profile_revision__isnull=False,
    ).annotate(latest_review=_LATEST_REVIEW, bucket=_BUCKET)


def queue_page(bucket, *, page_number, page_size=25):
    """One page of one bucket, with everything a row needs already joined."""

    rows = (
        reviewable_methods()
        .filter(bucket=bucket)
        .select_related(
            "traveler",
            "current_version",
            "current_version__dzd_profile_revision",
            "current_version__dzd_profile_revision__evidence",
        )
        .prefetch_related(_reviews_prefetch())
        .order_by("-current_version__created_at", "-pk")
    )
    return Paginator(rows, page_size).get_page(page_number)


def bucket_counts() -> dict:
    """All four counts in one GROUP BY, whatever the queue holds."""

    counts = {key: 0 for key, *_ in BUCKETS}
    for row in reviewable_methods().values("bucket").annotate(total=Count("pk")):
        counts[row["bucket"]] = row["total"]
    return counts


def awaiting_review_count() -> int:
    """How many payout methods are Finance's move, in one indexed query.

    The one authority for "payout methods awaiting approval": the Finance
    Overview and the main Overview both publish this number, so the two cannot
    disagree. A profile sent back for correction is the Traveler's move and is
    not counted.
    """

    return reviewable_methods().filter(bucket="waiting").count()


def _bucket(reviews):
    """The same four buckets as `_BUCKET`, for a profile already in memory."""

    if not reviews:
        return "waiting"
    return {
        "approved": "approved",
        "needs_attention": "correction",
        "rejected": "rejected",
    }[reviews[-1].status]


def _identity_facts(traveler_ids):
    """Current attestation and open assignment for a whole page, in two queries."""

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
        return {"present": False, "label": "No cheque attached"}
    if evidence.upload_state != "complete":
        return {"present": False, "label": "Cheque upload incomplete"}
    return {
        "present": True,
        "label": "Crossed cheque attached",
        "reference": str(evidence.public_reference),
        "uploaded_at": evidence.created_at,
    }


def queue_rows(methods, *, user=None):
    """The safe queue projection. No account value appears here, masked or not."""

    methods = list(methods)
    traveler_ids = {m.traveler_id for m in methods}
    attested, assignments = _identity_facts(traveler_ids)
    # Only for rows that are blocked on identity: whether there is an approved
    # ID to check a name against at all, so the row can say whose move it is.
    unattested = traveler_ids - attested
    with_id = set()
    if unattested:
        now = timezone.now()
        with_id = set(
            KycSubmission.objects.filter(user_id__in=unattested, status="approved")
            .exclude(expires_at__lte=now)
            .values_list("user_id", flat=True)
        )
    linkable = user is not None and may_open_people(user)
    rows = []
    for method in methods:
        profile = method.current_version.dzd_profile_revision
        reviews = list(profile.reviews.all())
        latest = reviews[-1] if reviews else None
        assignment = assignments.get(method.traveler_id)
        evidence = _evidence_state(profile)
        blocker = ""
        if method.bucket == "waiting":
            if not evidence["present"]:
                blocker = evidence["label"]
            elif method.traveler_id not in attested:
                blocker = (
                    "ID not approved yet"
                    if method.traveler_id not in with_id
                    else f"Identity check with {display_name(assignment.reviewer)}"
                    if assignment
                    else "Identity check needed"
                )
        rows.append(
            {
                "reference": str(profile.public_reference),
                "review_url": reverse(
                    "admin_console:payout-review-detail",
                    args=(profile.public_reference,),
                ),
                "bucket": method.bucket,
                "bucket_label": BUCKET_LABELS[method.bucket],
                "bucket_tone": BUCKET_TONES[method.bucket],
                "traveler": {
                    "id": method.traveler_id,
                    "name": display_name(method.traveler),
                    "email": method.traveler.email,
                    "href": (
                        person_href(method.traveler_id, source="payout-reviews")
                        if linkable
                        else ""
                    ),
                },
                "revision": profile.sequence,
                "submitted_at": profile.submitted_at,
                "submitted_age": age_label(profile.submitted_at),
                "blocker": blocker,
                "decided_by": display_name(latest.reviewer) if latest else "",
                "decided_at": latest.created_at if latest else None,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Identity: reading the prerequisite, and completing it for Super Admin
# ---------------------------------------------------------------------------


def current_attestation(traveler_id):
    """The attestation `review_profile` would bind a decision to, or None."""

    now = timezone.now()
    return (
        PayoutIdentityAttestation.objects.filter(
            traveler_id=traveler_id,
            revocation__isnull=True,
            successors__isnull=True,
            kyc_submission__status="approved",
        )
        .exclude(kyc_submission__expires_at__lte=now)
        .select_related("attested_by")
        .order_by("-attested_at", "-pk")
        .first()
    )


def kyc_state(traveler_id) -> dict:
    """Is there an approved, unexpired ID an identity check can be bound to?

    Mirrors `assign_identity_review`'s own choice of submission, so the page
    never offers a check the command would refuse.
    """

    now = timezone.now()
    approved = (
        KycSubmission.objects.filter(user_id=traveler_id, status="approved")
        .order_by("-reviewed_at", "-pk")
        .first()
    )
    if approved and not (approved.expires_at and approved.expires_at <= now):
        return {"state": "approved", "submission": approved}
    pending = (
        KycSubmission.objects.filter(user_id=traveler_id, status="pending")
        .order_by("-created_at")
        .first()
    )
    if pending:
        return {"state": "pending", "submission": pending}
    return {"state": "expired" if approved else "missing", "submission": approved}


def may_confirm_identity(user) -> bool:
    """Can this operator complete the identity check on the review page itself?

    Only someone who can both open the assignment (`review_payout_profiles`,
    `view_payout_sensitive`) and attest it (`attest_payout_identity`), and who
    can see the ID document the attestation is a statement about (`view_kyc`,
    `view_evidence`). In the fixed role matrix that is Super Admin. The two
    domain commands re-check every capability themselves.
    """

    return has_all_admin_permissions(
        user,
        "review_payout_profiles",
        "view_payout_sensitive",
        "attest_payout_identity",
        "view_kyc",
        "view_evidence",
    )


@sensitive_variables()
def confirm_identity(*, actor, traveler_id, given_name, family_name, aliases=()):
    """Assign the identity check to yourself and attest it, in one transaction.

    Two existing commands, composed, nothing added: `assign_identity_review`
    checks the assigner's capabilities and that the Traveler has a current
    approved ID, and `attest_identity` checks the attester's capability, that
    the assignment is theirs and open, and the names. Both write their own audit
    record. The transaction exists only so a refused attestation does not leave
    a self-assignment behind.
    """

    now = timezone.now()
    with transaction.atomic():
        assignment = (
            PayoutIdentityReviewAssignment.objects.filter(
                traveler_id=traveler_id,
                reviewer=actor,
                closed_at__isnull=True,
                kyc_submission__status="approved",
            )
            .exclude(kyc_submission__expires_at__lte=now)
            .order_by("-pk")
            .first()
        )
        if assignment is None:
            assignment = assign_identity_review(
                actor=actor, traveler_id=traveler_id, reviewer_id=actor.pk
            )
        return attest_identity(
            actor=actor,
            assignment_reference=assignment.public_reference,
            given_name=given_name,
            family_name=family_name,
            aliases=aliases,
        )


@sensitive_variables()
def identity_form_values(post):
    """Names and one optional other spelling from an identity-check form."""

    if post.get("confirm_checked") != "on":
        raise ValidationError("identity_check_unconfirmed")
    other_given = (post.get("other_given_name") or "").strip()
    other_family = (post.get("other_family_name") or "").strip()
    if bool(other_given) != bool(other_family):
        raise ValidationError("alias_incomplete")
    return {
        "given_name": (post.get("given_name") or "").strip(),
        "family_name": (post.get("family_name") or "").strip(),
        "aliases": [[other_given, other_family]] if other_given else [],
    }


def reviewer_choices():
    """Staff who can actually attest an identity, for the assignment control."""

    from django.contrib.auth import get_user_model

    User = get_user_model()
    return [
        user
        for user in User.objects.filter(is_staff=True, is_active=True).order_by(
            "email"
        )
        if has_all_admin_permissions(user, "attest_payout_identity")
    ]


# ---------------------------------------------------------------------------
# The review page's view model
# ---------------------------------------------------------------------------


@sensitive_variables()
def review_view(profile, *, user, revealed=None, request=None):
    """One profile revision, arranged around the one decision it needs.

    `stage` is the single thing the page branches on:

    ``decide``           identity is established and the cheque is attached:
                         Approve and Reject are the page.
    ``confirm``          identity is missing and this operator can complete it
                         here (Super Admin): the identity check, then decide.
    ``assign``           identity is missing and this operator cannot attest
                         (Finance): ask someone who can.
    ``waiting``          identity is missing and someone has been asked.
    ``kyc``              there is no approved ID to check a name against.
    ``no_evidence``      no complete cheque; nothing can be decided.
    ``read_only``        this operator cannot record decisions.

    The name comparison is the only thing here that touches decrypted values,
    and it returns a classification, never the names. Reading it is audited by
    H4's own `payout_identity.compared` record.
    """

    method = profile.method
    traveler = method.traveler
    reviews = list(profile.reviews.all())
    latest = reviews[-1] if reviews else None
    bucket = _bucket(reviews)
    evidence = _evidence_state(profile)
    attestation = current_attestation(traveler.pk)
    kyc = kyc_state(traveler.pk)
    open_assignments = list(
        PayoutIdentityReviewAssignment.objects.filter(
            traveler_id=traveler.pk, closed_at__isnull=True
        )
        .select_related("reviewer")
        .order_by("-pk")
    )
    comparison = ""
    if attestation:
        comparison = profile_name_consistency(actor=user, profile=profile)[
            "classification"
        ]

    may_review = has_all_admin_permissions(
        user, "review_payout_profiles", "view_payout_sensitive", "view_payout_evidence"
    )
    may_assign = has_admin_permission(user, "review_payout_profiles")
    may_confirm = may_confirm_identity(user)

    if not may_review:
        stage = "read_only"
    elif not evidence["present"]:
        stage = "no_evidence"
    elif attestation:
        stage = "decide"
    elif kyc["state"] != "approved":
        stage = "kyc"
    elif may_confirm:
        stage = "confirm"
    elif open_assignments:
        stage = "waiting"
    else:
        stage = "assign"

    documents, documents_unavailable = [], False
    if stage == "confirm" and kyc["submission"] is not None:
        from .console_views import kyc_evidence_slots

        documents, documents_unavailable = kyc_evidence_slots(
            kyc["submission"], user=user, request=request
        )

    is_current = method.current_version.dzd_profile_revision_id == profile.pk
    comparison_label, comparison_tone = NAME_COMPARISON.get(
        comparison, ("Not checked yet", "mute")
    )
    return {
        "reference": str(profile.public_reference),
        "revision": profile.sequence,
        "submitted_at": profile.submitted_at,
        "is_current": is_current,
        "bucket": bucket,
        "bucket_label": BUCKET_LABELS[bucket],
        "bucket_tone": BUCKET_TONES[bucket],
        "approved": approved_profile(profile),
        "stage": stage,
        "traveler": {
            "id": traveler.pk,
            "name": display_name(traveler),
            "email": traveler.email,
            "initials": initials(traveler),
            "joined": traveler.date_joined,
            "href": (
                person_href(traveler.pk, tab="payouts") if may_open_people(user) else ""
            ),
        },
        "method": {
            "reference": str(method.public_reference),
            "version": method.current_version.sequence,
            "status": method.status,
            "status_label": METHOD_STATUS.get(method.status, method.status),
            "status_reason": method.status_reason,
            "enabled": method.enabled,
        },
        # Masks only. The full values are reachable from the reveal and from
        # nowhere else on this page.
        "masked": {
            "ccp": f"•••• {profile.ccp_last_four}",
            "key": "••",
            "rip": f"•••• {profile.rip_last_four}",
        },
        "evidence": {**evidence, "labels": CHEQUE_LABELS},
        "identity": {
            "attested": attestation is not None,
            "attested_by": display_name(attestation.attested_by) if attestation else "",
            "attested_at": attestation.attested_at if attestation else None,
            "comparison": comparison,
            "comparison_label": comparison_label,
            "comparison_tone": comparison_tone,
            "kyc_state": kyc["state"],
            "kyc_submission": kyc["submission"],
            "kyc_url": (
                reverse("admin_console:kyc-detail", args=(kyc["submission"].pk,))
                if kyc["submission"] is not None and has_admin_permission(user, "view_kyc")
                else ""
            ),
            "assignments": [
                {
                    "reviewer": display_name(row.reviewer),
                    "assigned_at": row.created_at,
                    "is_me": row.reviewer_id == user.pk,
                }
                for row in open_assignments
            ],
            "documents": documents,
            "documents_unavailable": documents_unavailable,
        },
        "latest": (
            {
                "status": latest.status,
                "label": DECISIONS[latest.status][1],
                "tone": DECISIONS[latest.status][2],
                "reviewer": display_name(latest.reviewer),
                "at": latest.created_at,
            }
            if latest
            else None
        ),
        "history": [
            {
                "label": DECISIONS[row.status][1],
                "tone": DECISIONS[row.status][2],
                "reviewer": display_name(row.reviewer),
                "at": row.created_at,
                "name_note": (
                    name_comparison_label(row.reason_code)
                    if row.reason_code and row.reason_code != "consistent"
                    else ""
                ),
            }
            for row in reversed(reviews)
        ],
        "revealed": revealed,
        "may": {
            "review": may_review,
            "reveal": has_all_admin_permissions(
                user, "view_payout_sensitive", "view_payouts"
            ),
            "evidence": has_admin_permission(user, "view_payout_evidence"),
            "assign": may_assign,
            "confirm": may_confirm,
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


def payout_reviews(request):
    """The queue. Waiting first; decided profiles are history, one click away."""

    from .console_views import _render

    require_capabilities(request.user, "review_payout_profiles")
    counts = bucket_counts()
    requested = request.GET.get("bucket", "")
    if requested not in counts:
        requested = "waiting"
    page = queue_page(requested, page_number=request.GET.get("page"))
    return _render(
        request,
        "admin/console/payout_reviews.html",
        {
            "title": "Payout method reviews",
            "waiting": {
                "key": "waiting",
                "label": BUCKET_LABELS["waiting"],
                "count": counts["waiting"],
                "selected": requested == "waiting",
            },
            "history": [
                {
                    "key": key,
                    "label": label,
                    "tone": tone,
                    "count": counts[key],
                    "selected": key == requested,
                }
                for key, label, tone in BUCKETS
                if key != "waiting"
            ],
            "rows": queue_rows(page.object_list, user=request.user),
            "page_obj": page,
            "selected": requested,
            "selected_label": BUCKET_LABELS[requested],
            "total": sum(counts.values()),
        },
    )


def _detail_redirect(request, reference):
    url = reverse("admin_console:payout-review-detail", args=(reference,))
    if request.GET.get("from") == "person":
        url += "?from=person"
    return redirect(url)


def _release_waiting_payouts(profile):
    """An approval can be the last thing a waiting payout needed."""

    from apps.finance.models import Payout
    from apps.finance.payout_release import evaluate_payout_release

    for deal_id in Payout.objects.filter(
        dzd_profile_revision_id=profile.pk,
        status__in=("blocked", "eligible", "scheduled"),
    ).values_list("deal_id", flat=True):
        evaluate_payout_release(deal_id=deal_id)


@sensitive_variables()
def _decide(request, profile, *, decision, accept_name_difference):
    if decision not in REVIEW_DECISIONS:
        raise ValidationError("Unknown payout profile review decision.")
    if decision == "approved" and not accept_name_difference:
        # `review_profile` quietly records an approval over a name difference as
        # "needs correction" — right for the API, wrong for a person who clicked
        # Approve and would then see the Traveler asked to resubmit. The console
        # says so instead and records nothing. The domain rule is untouched.
        if current_attestation(profile.method.traveler_id) is not None:
            comparison = profile_name_consistency(
                actor=request.user, profile=profile
            )["classification"]
            if comparison != "consistent":
                raise ValidationError("name_difference_unaccepted")
    review = review_profile(
        actor=request.user,
        reference=profile.public_reference,
        decision=decision,
        accept_name_difference=accept_name_difference,
    )
    if review.status == "approved":
        _release_waiting_payouts(profile)
    return review


@sensitive_post_parameters("__ALL__")
@sensitive_variables()
def payout_review_detail(request, reference):
    """One profile revision, and the decision it needs."""

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
                    "Identity check requested. The payout method can be decided "
                    "once they confirm the Traveler's legal name.",
                )
                return _detail_redirect(request, reference)
            elif action == "confirm_identity":
                if not may_confirm_identity(request.user):
                    raise PermissionDenied("Payout capability required.")
                confirm_identity(
                    actor=request.user,
                    traveler_id=profile.method.traveler_id,
                    **identity_form_values(request.POST),
                )
                if request.POST.get("then") == "approve":
                    comparison = profile_name_consistency(
                        actor=request.user, profile=profile
                    )["classification"]
                    if comparison == "consistent":
                        # The attestation is already recorded and valid on its
                        # own, so a refusal here has to say that rather than
                        # read as "the identity check failed".
                        try:
                            _decide(
                                request,
                                profile,
                                decision="approved",
                                accept_name_difference=False,
                            )
                        except (ValidationError, PermissionDenied) as exc:
                            messages.success(request, "Identity confirmed.")
                            _refuse(request, "The approval", exc)
                            return _detail_redirect(request, reference)
                        messages.success(
                            request,
                            "Identity confirmed and payout method approved. This "
                            "CCP account can now receive the Traveler's DZD payouts.",
                        )
                    else:
                        messages.warning(
                            request,
                            "Identity confirmed, but not approved yet: the name on "
                            "the payout account is "
                            f"{name_comparison_label(comparison).lower()}. Check the "
                            "cheque, then approve with the difference accepted, or "
                            "reject.",
                        )
                else:
                    messages.success(
                        request,
                        "Identity confirmed. You can now approve or reject this "
                        "payout method.",
                    )
                return _detail_redirect(request, reference)
            elif action == "decide":
                review = _decide(
                    request,
                    profile,
                    decision=request.POST.get("decision", ""),
                    accept_name_difference=(
                        request.POST.get("accept_name_difference") == "on"
                    ),
                )
                messages.success(request, DECISION_OUTCOMES[review.status])
                return _detail_redirect(request, reference)
            else:
                raise ValidationError("Unknown payout review action.")
        except ValueError:
            messages.error(
                request,
                "That request was malformed and was not applied. Reload the page "
                "and try again.",
            )
        except (ValidationError, PermissionDenied) as exc:
            label = {
                "confirm_identity": "The identity check",
                "assign": "The identity check request",
                "reveal": "The reveal",
            }.get(action, "The decision")
            _refuse(request, label, exc)
    profile = _profile_or_404(reference)
    review = review_view(
        profile, user=request.user, revealed=revealed, request=request
    )
    from_person = request.GET.get("from") == "person"
    response = _render(
        request,
        "admin/console/payout_review_detail.html",
        {
            "title": f"{review['traveler']['name']} · payout method review",
            "review": review,
            "decisions": {key: label for key, (label, _, _) in DECISIONS.items()},
            "reviewers": reviewer_choices() if review["stage"] in ("assign", "waiting") else [],
            "from_person": from_person,
            "confirm": request.GET.get("confirm", ""),
            "waiting_count": (
                awaiting_review_count() if review["bucket"] != "waiting" else None
            ),
        },
    )
    response["Cache-Control"] = "no-store, private"
    return response


@sensitive_variables()
def payout_review_evidence(request, reference):
    """This profile revision's own crossed cheque, and nothing else.

    The reference in the URL names the *profile*, and the document served is the
    one that profile owns. There is no path here to an arbitrary evidence id.
    Every open is audited by `read_evidence`.
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
