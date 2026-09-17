"""Phase J6.4 — the simplified DZD payout-method review, end to end.

What the owner reported: a pending payout method was visible only inside
Finance, the review page buried the decision under warnings, and Approve did
not work. The last one had a concrete cause — an identity check could be
*assigned* from the console but never *completed* there, because
`attest_identity` had no console surface — so a fresh submission could never
be decided.

These tests pin the rebuilt workflow from the operator's side:

* the pending count is the same number on the main Overview and the Finance
  Overview, and it disappears once the decision is recorded;
* Approve, Reject and "ask for a correction" each record the domain's own
  immutable review;
* a Super Admin completes the identity prerequisite and the approval in one
  guided step, through the two existing audited commands;
* Finance cannot attest, is not offered a control that would fail, and the
  Trust reviewer they ask can now finish the check in the console;
* masking, the audited reveal and the audited cheque are unchanged.

`test_phase_j12_finance_route_performance.py` still owns the queue's cost and
the J1.2 guarantees; `test_phase8fh4_manual.py` still owns H4's money rules.
Nothing here passes by weakening either.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.admin_panel.console_payout_reviews import awaiting_review_count
from apps.admin_panel.models import AdminAuditLog
from apps.admin_panel.permissions import assign_admin_roles
from apps.finance.models import (
    PayoutIdentityAttestation,
    PayoutIdentityReviewAssignment,
    PayoutProfileReview,
    TravelerPayoutMethod,
)
from apps.finance.payout_profiles import assign_identity_review

from .test_phase8fh4_manual import configured_h4  # noqa: F401
from .test_phase_j12_finance_route_performance import (
    SECRET_CCP,
    SECRET_RIP,
    build_profile,
    console_staticfiles,  # noqa: F401
    detail_url,
    finance_client,
)


def client_for(user):
    client = Client()
    client.force_login(user)
    return client


def kyc_store(readable=True):
    store = MagicMock()
    store.name = "kyc"
    store.readable.return_value = readable
    return store


def latest_status(profile):
    review = PayoutProfileReview.objects.filter(profile=profile).order_by("-pk").first()
    return review.status if review else None


def method_of(profile):
    return TravelerPayoutMethod.objects.get(pk=profile.method_id)


def finance_attention():
    """The Finance Overview's Needs attention rows over an empty H5 snapshot.

    The page itself needs a standalone REPEATABLE READ snapshot, which a
    transaction-wrapped test cannot open; `test_h8a_guards` reads the same
    builder this way. The payout-method row is read from the database after
    the snapshot, exactly as the page does.
    """

    from apps.admin_panel.finance_operations import build_overview
    from apps.finance.control_plane.attention import attention_summary

    snapshot = {
        "payout_attention": attention_summary({}),
        "rail_operations": [],
        "metrics": {},
    }
    with patch("apps.admin_panel.finance_operations._activity", return_value=[]):
        return build_overview(snapshot, {"mode": "test"}, None, user=None)["attention"]


# ---------------------------------------------------------------------------
# One authoritative count, on both overviews
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_pending_method_is_on_both_overviews_and_clears_when_approved(
    configured_h4,  # noqa: F811
):
    scenario, profile = build_profile("j64-overview")
    client = finance_client(scenario)

    main = client.get(reverse("admin_console:overview"))
    body = main.content.decode()
    assert main.status_code == 200
    raised = {item["title"]: item for item in main.context["raised_items"]}
    item = raised["Payout methods awaiting approval"]
    assert item["count"] == 1 == awaiting_review_count()
    assert item["url"] == reverse("admin_console:payout-reviews")
    assert "Travelers submitted DZD payout details that need review." in body

    finance_row = next(
        row for row in finance_attention()
        if row.get("label") == "Payout methods awaiting approval"
    )
    assert finance_row["count"] == item["count"]
    assert finance_row["url"] == item["url"]

    # One click on Approve, and no manual database step, clears both.
    client.post(detail_url(profile), {"action": "decide", "decision": "approved"})
    assert latest_status(profile) == "approved"
    assert awaiting_review_count() == 0

    after = client.get(reverse("admin_console:overview"))
    assert "Payout methods awaiting approval" not in {
        row["title"] for row in after.context["raised_items"]
    }
    assert "Payout methods awaiting approval" not in [
        row.get("label") for row in finance_attention()
    ]


@pytest.mark.django_db
def test_roles_without_review_access_do_not_see_the_payout_item(
    configured_h4,  # noqa: F811
):
    scenario, _ = build_profile("j64-overview-roles")
    assign_admin_roles(scenario.outsider, ["support"])
    titles = {
        item["title"]
        for item in client_for(scenario.outsider)
        .get(reverse("admin_console:overview"))
        .context["attention"]
    }
    assert "Payout methods awaiting approval" not in titles


# ---------------------------------------------------------------------------
# The queue
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_queue_leads_with_what_to_review_now_and_shows_only_safe_fields(
    configured_h4,  # noqa: F811
):
    scenario, waiting = build_profile("j64-queue-a", attested=False)
    decided_scenario, decided = build_profile("j64-queue-b")
    client = finance_client(scenario)
    client.post(detail_url(decided), {"action": "decide", "decision": "approved"})

    page = client.get(reverse("admin_console:payout-reviews"))
    body = page.content.decode()
    assert page.context["selected"] == "waiting"
    assert scenario.traveler.email in body
    assert decided_scenario.traveler.email not in body
    assert ">Review<" in body
    # A small indicator only because it genuinely blocks the decision.
    assert "Identity check needed" in body
    # No account value, masked or not, and no machine codes.
    for forbidden in (SECRET_CCP, SECRET_RIP, "••••", "profile_", "insufficient_attestation"):
        assert forbidden not in body

    history = client.get(reverse("admin_console:payout-reviews") + "?bucket=approved")
    assert decided_scenario.traveler.email in history.content.decode()


# ---------------------------------------------------------------------------
# The decisions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_approve_is_one_click_and_the_page_leads_with_it(configured_h4):  # noqa: F811
    scenario, profile = build_profile("j64-approve")
    client = finance_client(scenario)

    page = client.get(detail_url(profile))
    body = page.content.decode()
    assert page.context["review"]["stage"] == "decide"
    assert 'name="decision" value="approved"' in body
    assert "Reject" in body
    # Correction is reachable but deliberately not a third primary button.
    assert "Ask the Traveler for a correction" in body
    assert body.index('value="approved"') < body.index("Ask the Traveler for a correction")
    # Secondary information is collapsed rather than in the primary flow.
    assert "Review history (0)" in body
    assert "<summary>Details</summary>" in body

    response = client.post(
        detail_url(profile), {"action": "decide", "decision": "approved"}, follow=True
    )
    assert "Approved. This CCP account can now receive" in response.content.decode()
    assert latest_status(profile) == "approved"
    assert method_of(profile).status == "ready"


@pytest.mark.django_db
def test_reject_and_correction_confirm_then_record_the_domain_review(
    configured_h4,  # noqa: F811
):
    scenario, profile = build_profile("j64-reject")
    client = finance_client(scenario)

    # The confirmation is reachable without script, already open.
    confirm = client.get(detail_url(profile) + "?confirm=reject").content.decode()
    assert 'id="st-dialog-reject"' in confirm
    assert 'aria-labelledby="st-dialog-reject-title" open' in confirm

    rejected = client.post(
        detail_url(profile), {"action": "decide", "decision": "rejected"}, follow=True
    ).content.decode()
    assert "Rejected. The Traveler is told the account was refused" in rejected
    assert latest_status(profile) == "rejected"
    method = method_of(profile)
    assert (method.status, method.status_reason) == ("needs_review", "profile_rejected")
    assert awaiting_review_count() == 0

    client.post(
        detail_url(profile), {"action": "decide", "decision": "needs_attention"}
    )
    method = method_of(profile)
    assert latest_status(profile) == "needs_attention"
    assert method.status_reason == "profile_correction_required"

    history = client.get(detail_url(profile)).content.decode()
    assert "Review history (2)" in history
    # Immutable: both decisions remain, newest first.
    assert history.index("Correction requested") < history.rindex("Rejected")


@pytest.mark.django_db
def test_an_approval_over_a_name_difference_asks_for_explicit_acceptance(
    configured_h4,  # noqa: F811
):
    from apps.finance.payout_profiles import attest_identity

    scenario, profile = build_profile("j64-names", attested=False)
    assign_admin_roles(scenario.outsider, ["trust_verification"])
    assignment = assign_identity_review(
        actor=scenario.admin,
        traveler_id=scenario.traveler.pk,
        reviewer_id=scenario.outsider.pk,
    )
    attest_identity(
        actor=scenario.outsider,
        assignment_reference=assignment.public_reference,
        given_name="Someone",
        family_name="Different",
    )
    client = finance_client(scenario)
    page = client.get(detail_url(profile))
    body = page.content.decode()
    assert page.context["review"]["needs_name_acceptance"] is True
    assert "Name check:" in body
    # Approve opens a confirmation whose acceptance box is required.
    assert 'data-dialog-open="st-dialog-approve"' in body
    assert 'name="accept_name_difference" required' in body

    client.post(
        detail_url(profile),
        {"action": "decide", "decision": "approved", "accept_name_difference": "on"},
    )
    assert latest_status(profile) == "approved"
    assert AdminAuditLog.objects.filter(
        action="payout_profile.reviewed", after__name_difference_accepted=True
    ).exists()


# ---------------------------------------------------------------------------
# The identity prerequisite
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@patch("apps.admin_panel.console_views.storage_for", return_value=kyc_store())
def test_super_admin_confirms_identity_and_approves_in_one_step(
    _storage, configured_h4,  # noqa: F811
):
    scenario, profile = build_profile("j64-super", attested=False)
    assign_admin_roles(scenario.outsider, ["super_admin"])
    owner = scenario.outsider
    client = client_for(owner)

    page = client.get(detail_url(profile))
    body = page.content.decode()
    assert page.context["review"]["stage"] == "confirm"
    assert "Identity check required" in body
    assert "Confirm identity and approve" in body
    # The ID document is previewed through the audited KYC route.
    assert "/verification/kyc/" in body and "/evidence/front/" in body
    # Nothing is prefilled from the claim being checked.
    assert 'value="QA"' not in body and 'value="Synthetic"' not in body

    response = client.post(
        detail_url(profile),
        {
            "action": "confirm_identity",
            "given_name": "QA",
            "family_name": "Synthetic",
            "confirm_checked": "on",
            "then": "approve",
        },
        follow=True,
    )
    assert "Identity confirmed and payout method approved" in response.content.decode()
    assert latest_status(profile) == "approved"
    assert method_of(profile).status == "ready"

    attestation = PayoutIdentityAttestation.objects.get(traveler=scenario.traveler)
    assert attestation.attested_by_id == owner.pk
    assert not PayoutIdentityReviewAssignment.objects.filter(
        traveler=scenario.traveler, closed_at__isnull=True
    ).exists()
    # Both existing audited commands ran; nothing was bypassed.
    actions = set(
        AdminAuditLog.objects.filter(actor=owner).values_list("action", flat=True)
    )
    assert {
        "payout_identity.assigned",
        "payout_identity.attested",
        "payout_profile.reviewed",
    } <= actions


@pytest.mark.django_db
@patch("apps.admin_panel.console_views.storage_for", return_value=kyc_store())
def test_super_admin_identity_check_stops_before_approving_a_different_name(
    _storage, configured_h4,  # noqa: F811
):
    scenario, profile = build_profile("j64-super-names", attested=False)
    assign_admin_roles(scenario.outsider, ["super_admin"])
    client = client_for(scenario.outsider)

    # The checkbox is required: no attestation, and no dangling assignment.
    client.post(
        detail_url(profile),
        {"action": "confirm_identity", "given_name": "QA", "family_name": "Synthetic", "then": "approve"},
    )
    assert not PayoutIdentityAttestation.objects.filter(traveler=scenario.traveler).exists()
    assert not PayoutIdentityReviewAssignment.objects.filter(traveler=scenario.traveler).exists()

    response = client.post(
        detail_url(profile),
        {
            "action": "confirm_identity",
            "given_name": "Someone",
            "family_name": "Different",
            "confirm_checked": "on",
            "then": "approve",
        },
        follow=True,
    )
    body = response.content.decode()
    assert "Identity confirmed, but not approved yet" in body
    assert PayoutIdentityAttestation.objects.filter(traveler=scenario.traveler).exists()
    # No review was written: the approval did not silently become a correction.
    assert latest_status(profile) is None
    assert response.context["review"]["stage"] == "decide"
    assert response.context["review"]["needs_name_acceptance"] is True
    assert 'data-dialog-open="st-dialog-approve"' in body


@pytest.mark.django_db
def test_finance_is_told_whose_move_it_is_and_trust_finishes_the_check(
    configured_h4,  # noqa: F811
):
    scenario, profile = build_profile("j64-roles", attested=False)
    finance = finance_client(scenario)

    page = finance.get(detail_url(profile))
    body = page.content.decode()
    assert page.context["review"]["stage"] == "assign"
    assert "Trust &amp; Verification or a Super Admin" in body
    assert "Confirm identity" not in body
    assert 'name="decision"' not in body

    # A Finance post of the Super-only action is refused and leaves nothing.
    finance.post(
        detail_url(profile),
        {"action": "confirm_identity", "given_name": "QA", "family_name": "Synthetic", "confirm_checked": "on"},
    )
    assert not PayoutIdentityAttestation.objects.exists()
    assert not PayoutIdentityReviewAssignment.objects.exists()

    assign_admin_roles(scenario.outsider, ["trust_verification"])
    finance.post(detail_url(profile), {"action": "assign", "reviewer": scenario.outsider.pk})
    waiting = finance.get(detail_url(profile))
    assert waiting.context["review"]["stage"] == "waiting"
    assert f"Waiting on {scenario.outsider.full_name}" in waiting.content.decode()

    # The Trust reviewer sees it on their Overview and completes it in the console.
    trust = client_for(scenario.outsider)
    overview = trust.get(reverse("admin_console:overview"))
    item = next(
        row for row in overview.context["attention"]
        if row["title"] == "Payout identity checks assigned to you"
    )
    assert item["count"] == 1
    queue = trust.get(reverse("admin_console:identity-checks")).content.decode()
    assert scenario.traveler.email in queue and "Check identity" in queue

    assignment = PayoutIdentityReviewAssignment.objects.get(traveler=scenario.traveler)
    check_url = reverse("admin_console:identity-check-detail", args=[assignment.public_reference])
    with patch("apps.admin_panel.console_views.storage_for", return_value=kyc_store()):
        assert "Confirm the legal name on the approved ID" in trust.get(check_url).content.decode()
        trust.post(
            check_url,
            {"given_name": "QA", "family_name": "Synthetic", "confirm_checked": "on"},
        )
    assert PayoutIdentityAttestation.objects.filter(
        traveler=scenario.traveler, attested_by=scenario.outsider
    ).exists()
    assert next(
        row for row in trust.get(reverse("admin_console:overview")).context["attention"]
        if row["title"] == "Payout identity checks assigned to you"
    )["count"] == 0

    # And Finance can now simply approve.
    decided = finance.get(detail_url(profile))
    assert decided.context["review"]["stage"] == "decide"
    finance.post(detail_url(profile), {"action": "decide", "decision": "approved"})
    assert latest_status(profile) == "approved"

    # Finance and Support cannot open the Trust surface at all.
    assert finance.get(reverse("admin_console:identity-checks")).status_code == 403
    assert finance.get(check_url).status_code == 403


@pytest.mark.django_db
def test_a_traveler_without_an_approved_id_is_explained_not_offered_a_decision(
    configured_h4,  # noqa: F811
):
    from apps.kyc.models import KycSubmission

    scenario, profile = build_profile("j64-nokyc", attested=False)
    KycSubmission.objects.filter(user=scenario.traveler).update(status="pending")
    page = finance_client(scenario).get(detail_url(profile))
    assert page.context["review"]["stage"] == "kyc"
    body = page.content.decode()
    assert "ID not approved yet" in body
    assert 'name="decision"' not in body


# ---------------------------------------------------------------------------
# Sensitive data is exactly as protected as before
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_masked_values_audited_reveal_and_audited_cheque(configured_h4):  # noqa: F811
    scenario, profile = build_profile("j64-sensitive")
    client = finance_client(scenario)
    url = detail_url(profile)

    body = client.get(url).content.decode()
    assert SECRET_CCP not in body and SECRET_RIP not in body
    assert "•••• 0000" in body
    cheque_url = reverse("admin_console:payout-review-evidence", args=[profile.public_reference])
    # The cheque is a large inline preview, served only by its scoped route.
    assert f'<img src="{cheque_url}"' in body

    revealed = client.post(url, {"action": "reveal"})
    assert revealed["Cache-Control"] == "no-store, private"
    assert SECRET_CCP in revealed.content.decode()
    assert AdminAuditLog.objects.filter(
        action="payout_profile.revealed", actor=scenario.admin
    ).count() == 1
    assert SECRET_CCP not in client.get(url).content.decode()

    assert client.get(cheque_url).status_code == 200
    assert AdminAuditLog.objects.filter(
        action="payout_evidence.viewed", actor=scenario.admin
    ).count() == 1


@pytest.mark.django_db
def test_the_review_page_cost_does_not_grow_with_its_history(configured_h4):  # noqa: F811
    scenario, profile = build_profile("j64-cost")
    client = finance_client(scenario)
    url = detail_url(profile)
    client.post(url, {"action": "decide", "decision": "rejected"})
    client.get(url)
    with CaptureQueriesContext(connection) as one:
        assert client.get(url).status_code == 200
    for decision in ("needs_attention", "rejected", "approved", "rejected"):
        client.post(url, {"action": "decide", "decision": decision})
    with CaptureQueriesContext(connection) as five:
        assert client.get(url).status_code == 200
    assert len(five.captured_queries) == len(one.captured_queries)
