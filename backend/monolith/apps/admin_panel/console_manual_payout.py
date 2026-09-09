"""Functional H4 console, delegating every financial decision to domain services."""

from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import redirect
from django.contrib import messages
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables

from apps.finance import payout_manual
from apps.finance.payout_profiles import require_capabilities
from apps.finance.payout_manual_api import projection
from apps.finance.payout_manual_profiles import reveal_profile, review_profile
from apps.finance.payout_evidence import upload_evidence, read_evidence


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
                response = HttpResponse(body, content_type=mime)
                response["Cache-Control"] = "no-store, private"
                response["X-Content-Type-Options"] = "nosniff"
                return response
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
                from apps.finance.models import ManualPayoutReceipt

                receipt = (
                    ManualPayoutReceipt.objects.filter(
                        attempt__payout=payout,
                        evidence__public_reference=request.POST.get(
                            "evidence_reference"
                        ),
                    )
                    .select_related("evidence")
                    .first()
                )
                if not receipt:
                    raise ValidationError("Receipt does not belong to this payout.")
                body, mime = read_evidence(
                    actor=request.user, reference=receipt.evidence.public_reference
                )
                response = HttpResponse(body, content_type=mime)
                response["Cache-Control"] = "no-store, private"
                response["X-Content-Type-Options"] = "nosniff"
                return response
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
            messages.error(request, "Private payout evidence storage is unavailable.")
        except (ValidationError, ValueError):
            messages.error(
                request,
                "The action was refused. Check the instruction, evidence, profile and holds.",
            )
    payout.refresh_from_db()
    response = _render(
        request,
        "admin/console/manual_payout.html",
        {
            "title": f"Manual DZD payout {payout.pk}",
            "manual": projection(payout),
            "revealed": revealed,
        },
    )
    response["Cache-Control"] = "no-store, private"
    return response
