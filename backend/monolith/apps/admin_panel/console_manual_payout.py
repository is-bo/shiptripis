"""Functional H4 console, delegating every financial decision to domain services.

H4.1 changed how this screen reads and how it refuses, and changed nothing about
what it may do. Every command still goes to `apps.finance.payout_manual`, every
gate is still evaluated inside that transaction, and no control here can settle
a payout that the domain would not settle. What was added is the operator's half
of the contract: the destination and the exact amount presented so they cannot
be transcribed wrongly, the reason an action is impossible shown before it is
attempted rather than after, and a refusal that says which condition failed
instead of listing all of them.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.contrib import messages
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables

from apps.finance import payout_manual
from apps.finance.payout_profiles import require_capabilities
from apps.finance.payout_manual_profiles import reveal_profile, review_profile
from apps.finance.payout_evidence import upload_evidence, read_evidence
from .console_manual_presenter import manual_view

def _queue_return(request):
    """Where "back" goes, when the operator arrived from the H5.2 dinar queue.

    H5.2 asks that finishing one payout leaves an operator able to carry on
    rather than re-navigating from the top. The cohort travels as a query
    parameter and is validated against the queue's own four keys before it is
    turned into a URL — an arbitrary `?next=` echoed back as a link would be an
    open redirect on the one screen in this product that must not have one.

    There is deliberately no "next waiting payout" control. Chaining straight
    into the following transfer is exactly how a person sends the right amount
    to the wrong Traveler, and H4.1's guarantee is that each payout is selected,
    reviewed and attested on its own.
    """

    from django.urls import reverse

    from .finance_operations import DZD_COHORTS

    cohort = request.GET.get("cohort", "")
    if cohort not in {key for key, *_ in DZD_COHORTS}:
        return None
    label = next(row[1] for row in DZD_COHORTS if row[0] == cohort)
    return {
        "url": f"{reverse('admin_console:finance-dzd')}?cohort={cohort}",
        "label": label,
    }


#: What each command is called when it is refused. The domain's own sentence is
#: appended to this, because "Prepare transfer was refused" and "An operator
#: already owns this instruction" answer different halves of the question.
ACTION_LABELS = {
    "reveal": "Revealing the payout destination",
    "proof": "Opening the crossed cheque",
    "review": "Approving the payout profile",
    "prepare": "Claiming this payout",
    "begin": "Starting the transfer",
    "release": "Releasing the claim",
    "receipt": "Recording the transfer receipt",
    "hold": "Opening a hold",
    "clear_hold": "Releasing the hold",
}

#: The console never renders a raw exception. Where a refusal is one of these
#: known conditions, the operator gets the sentence that tells them what to do
#: about it; anything else falls back to the domain's own authored message,
#: which is a fixed English string and never carries provider or stack detail.
REFUSALS = {
    "An operator already owns this instruction.": (
        "Another operator has already claimed this payout. Reload the page to "
        "see who owns it."
    ),
    "Instruction revision conflict.": (
        "This payout changed while the page was open. Reload and try again — "
        "nothing was claimed."
    ),
    "Only the claiming operator may execute this instruction.": (
        "This instruction belongs to the operator who claimed it. You cannot "
        "act on it."
    ),
    "Committed instructions require recovery review.": (
        "The transfer is already committed and cannot be released. Open a hold "
        "for recovery review instead."
    ),
    "Delivery, protection or hold gate prevents progression.": (
        "A hold, an active dispute or the protection period is stopping this "
        "payout. The blockers are listed above."
    ),
    "Reviewed profile and crossed cheque are required.": (
        "The frozen payout profile has no current approval. Review the crossed "
        "cheque first."
    ),
    "Transfer evidence and explicit confirmation are required.": (
        "Attach the transfer receipt and tick the attestation before recording "
        "evidence."
    ),
    "A valid JPEG, PNG or WebP image is required.": (
        "That file was not accepted. Upload a JPEG, PNG or WebP image of the "
        "receipt, under 8 MB."
    ),
    "Evidence image exceeds the size limit.": (
        "That file is too large. The receipt must be under 8 MB."
    ),
    "Upload new evidence for a changed settlement attestation.": (
        "This receipt is already recorded with a different attestation. Upload "
        "a new receipt to correct it — recorded evidence is never replaced."
    ),
    "Settlement replay conflicts with recorded evidence.": (
        "This payout is already settled against different evidence. Nothing was "
        "changed."
    ),
    "Manual DZD execution is disabled.": (
        "Manual DZD execution is switched off in this environment. No transfer "
        "can be prepared or recorded."
    ),
}


def _refuse(request, action, exc):
    """One refusal, named, without leaking anything the operator may not see."""

    raw = " ".join(getattr(exc, "messages", None) or [str(exc)]).strip()
    detail = REFUSALS.get(raw, raw)
    label = ACTION_LABELS.get(action, "The action")
    messages.error(request, f"{label} was refused. {detail}")


def _evidence_response(body, mime):
    response = HttpResponse(body, content_type=mime)
    response["Cache-Control"] = "no-store, private"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Disposition"] = 'inline; filename="payout-evidence"'
    response["Referrer-Policy"] = "no-referrer"
    return response


def _scoped_evidence(payout, reference):
    """Resolve one evidence reference *belonging to this payout*, or nothing.

    The console never reads an arbitrary reference. A payout may show exactly
    two kinds of document: the crossed cheque frozen into its own instruction
    version, and a transfer receipt recorded against one of its own attempts.
    Anything else is somebody else's evidence and is a 404 here regardless of
    the operator's capabilities.
    """

    from apps.finance.models import ManualPayoutReceipt

    version = (
        payout.active_instruction_version
        if payout.active_instruction_version_id
        else None
    )
    profile = version.dzd_profile_revision if version else None
    if (
        profile
        and profile.evidence_id
        and str(profile.evidence.public_reference) == str(reference)
    ):
        return profile.evidence
    receipt = (
        ManualPayoutReceipt.objects.filter(
            attempt__payout=payout, evidence__public_reference=reference
        )
        .select_related("evidence")
        .first()
    )
    return receipt.evidence if receipt else None


@sensitive_variables()
def manual_evidence(request, payout, reference):
    """Serve one payout document to an authorized operator, and audit the open.

    A GET rather than a POST because the image has to be reachable from an
    ``<img>`` and from a plain new tab when scripting is off. It is still not a
    shareable URL: it is session-authenticated, capability-gated, no-store, and
    scoped to this payout's own evidence. No storage URL is ever emitted.
    """

    from apps.core.storage import StorageNotConfigured
    from botocore.exceptions import BotoCoreError, ClientError

    require_capabilities(
        request.user, "view_payouts", "view_payout_sensitive", "view_payout_evidence"
    )
    evidence = _scoped_evidence(payout, reference)
    if evidence is None:
        raise Http404
    try:
        body, mime = read_evidence(
            actor=request.user, reference=evidence.public_reference
        )
    except (StorageNotConfigured, BotoCoreError, ClientError, ValidationError):
        return HttpResponse(
            "Private payout evidence is temporarily unavailable.",
            content_type="text/plain; charset=utf-8",
            status=503,
            headers={"Cache-Control": "no-store, private"},
        )
    return _evidence_response(body, mime)


@sensitive_post_parameters("__ALL__")
@sensitive_variables()
def manual_detail(request, payout):
    from .console_views import _render
    from apps.core.storage import StorageNotConfigured
    from botocore.exceptions import BotoCoreError, ClientError

    require_capabilities(
        request.user, "view_payouts", "view_payout_sensitive", "view_payout_evidence"
    )
    profile = (
        payout.active_instruction_version.dzd_profile_revision
        if payout.active_instruction_version_id
        else None
    )
    revealed = None
    action = ""
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "reveal" and profile:
                revealed = reveal_profile(
                    actor=request.user, reference=profile.public_reference
                )
            elif action == "proof" and profile and profile.evidence_id:
                body, mime = read_evidence(
                    actor=request.user, reference=profile.evidence.public_reference
                )
                return _evidence_response(body, mime)
            elif action == "review" and profile:
                review_profile(
                    actor=request.user,
                    reference=profile.public_reference,
                    approve=True,
                    accept_name_difference=request.POST.get("accept_name_difference")
                    == "on",
                )
                from apps.finance.payout_release import evaluate_payout_release

                evaluate_payout_release(deal_id=payout.deal_id)
            elif action == "view_receipt":
                evidence = _scoped_evidence(
                    payout, request.POST.get("evidence_reference")
                )
                if evidence is None:
                    raise ValidationError("Receipt does not belong to this payout.")
                body, mime = read_evidence(
                    actor=request.user, reference=evidence.public_reference
                )
                return _evidence_response(body, mime)
            elif action == "prepare":
                payout_manual.prepare(
                    actor=request.user,
                    payout_id=payout.pk,
                    expected_state_version=int(request.POST.get("state_version", "-1")),
                )
            elif action in ("begin", "release"):
                getattr(payout_manual, action)(
                    actor=request.user,
                    payout_id=payout.pk,
                    sequence=int(request.POST.get("sequence", "-1")),
                )
            elif action == "receipt":
                if (
                    "receipt" not in request.FILES
                    or request.POST.get("confirmed") != "on"
                ):
                    raise ValidationError(
                        "Transfer evidence and explicit confirmation are required."
                    )
                evidence = upload_evidence(
                    actor=request.user,
                    upload=request.FILES["receipt"],
                    purpose="transfer_receipt",
                )
                payout_manual.confirm(
                    actor=request.user,
                    payout_id=payout.pk,
                    sequence=int(request.POST.get("sequence", "-1")),
                    evidence_reference=evidence.public_reference,
                    confirmed=True,
                    settled=request.POST.get("settled") == "on",
                )
            elif action == "hold":
                from apps.finance.payout_domain import open_hold

                open_hold(
                    actor=request.user,
                    payout_id=payout.pk,
                    kind="manual",
                    reason_code="manual_transfer_review",
                    source_reference=f"manual:{payout.pk}:{payout.state_version}",
                )
            elif action == "clear_hold":
                from apps.finance.payout_domain import clear_hold

                hold = payout.holds.filter(
                    pk=int(request.POST.get("hold_id", "-1"))
                ).first()
                if not hold:
                    raise ValidationError("Hold does not belong to this payout.")
                clear_hold(
                    actor=request.user,
                    hold_id=hold.pk,
                    expected_generation=int(request.POST.get("generation", "-1")),
                )
            else:
                raise ValidationError("Unknown manual payout action.")
            if action != "reveal":
                return redirect("admin_console:payout-detail", pk=payout.pk)
        except (StorageNotConfigured, BotoCoreError, ClientError):
            messages.error(
                request,
                "Private payout evidence storage is unavailable. The payout is "
                "intact; nothing was recorded. Try again shortly.",
            )
        except ValueError:
            messages.error(
                request,
                "That request was malformed and was not applied. Reload the page "
                "and try again.",
            )
        except (ValidationError, PermissionDenied) as exc:
            _refuse(request, action, exc)
    payout.refresh_from_db()
    view = manual_view(payout, user=request.user, revealed=revealed)
    response = _render(
        request,
        "admin/console/manual_payout.html",
        {
            "title": f"Manual DZD payout {payout.pk}",
            "manual": view,
            "revealed": revealed,
            "queue": _queue_return(request),
        },
    )
    response["Cache-Control"] = "no-store, private"
    return response
