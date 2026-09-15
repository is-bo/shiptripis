"""Phase J1.2 — the DZD review workflow, and the reads it must not slow down.

Three things are asserted here and nothing else:

* **The review surface exists and is bounded.** Before J1.2 a Traveler could
  submit a CCP account and a crossed cheque and nothing in the console said so;
  the only reachable decision was "approve", and only from a payout that already
  existed. What is tested is that the queue exists, that it says what is
  waiting, that all three outcomes are recordable, that each one is immutable
  and that nobody outside Finance can reach any of it.

* **No account value escapes the list.** H4.1's rule holds here: the queue shows
  no CCP number and no RIP, masked or otherwise, and the detail page shows them
  only inside the audited reveal.

* **The queue is cheap.** It is opened far more often than it is acted on, and
  the H5 control-plane snapshot behind the Finance dashboard costs roughly
  ninety queries. A bound is asserted rather than a wall-clock time, because a
  wall clock measures the machine and a query count measures the code.

H4's financial guarantees are not re-verified here and nothing in this file may
pass by weakening them; `test_phase8fh4_manual.py` still owns those.
"""

import pytest
from django.db import connection
from django.test import Client, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.admin_panel.console_payout_reviews import awaiting_review_count
from apps.admin_panel.permissions import assign_admin_roles
from apps.finance.models import PayoutProfileReview, TravelerPayoutMethod
from apps.finance.payout_evidence import upload_evidence
from apps.finance.payout_manual_profiles import approved_profile, review_profile
from apps.finance.payout_mobile import dzd_method
from apps.finance.payout_profiles import (
    assign_identity_review,
    attest_identity,
    set_preference,
    submit_dzd_profile,
)

from .factories import build_scenario
from .test_phase8fh4_manual import configured_h4, image_upload  # noqa: F401

SECRET_CCP = "0000000000"
SECRET_RIP = "0" * 20


@pytest.fixture(autouse=True)
def console_staticfiles(settings):
    # Render assertions must not depend on a pre-existing collectstatic manifest.
    with override_settings(
        STORAGES={
            **settings.STORAGES,
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
            },
        }
    ):
        yield


def build_profile(prefix, *, attested=True):
    """One Traveler with a submitted DZD profile, and optionally an identity.

    `attested=False` is the state every real submission starts in: the Traveler
    has sent their details and nobody has yet established that the account
    holder is them.
    """

    with override_settings(PAYOUT_PROFILES_ENABLED=False):
        scenario = build_scenario(prefix=prefix)
    assign_admin_roles(scenario.admin, ["finance"])
    scenario.traveler.role = "traveler"
    scenario.traveler.save(update_fields=["role"])
    set_preference(
        actor=scenario.traveler, currency="DZD", enabled=True, expected_revision=0
    )
    proof = upload_evidence(actor=scenario.traveler, upload=image_upload())
    method = submit_dzd_profile(
        actor=scenario.traveler,
        expected_revision=1,
        first_name="QA",
        last_name="Synthetic",
        ccp_number=SECRET_CCP,
        ccp_key="00",
        rip=SECRET_RIP,
        proof_reference=proof.public_reference,
    )
    if attested:
        assign_admin_roles(scenario.outsider, ["trust_verification"])
        assignment = assign_identity_review(
            actor=scenario.admin,
            traveler_id=scenario.traveler.pk,
            reviewer_id=scenario.outsider.pk,
        )
        attest_identity(
            actor=scenario.outsider,
            assignment_reference=assignment.public_reference,
            given_name="QA",
            family_name="Synthetic",
        )
    return scenario, method.current_version.dzd_profile_revision


def finance_client(scenario):
    client = Client()
    client.force_login(scenario.admin)
    return client


def detail_url(profile):
    return reverse(
        "admin_console:payout-review-detail", args=[profile.public_reference]
    )


# ---------------------------------------------------------------------------
# The queue
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_submitted_profile_is_visible_countable_and_carries_no_account_value(
    configured_h4,  # noqa: F811
):
    scenario, profile = build_profile("j12-queue")

    # The number the Finance Overview publishes under Needs attention.
    assert awaiting_review_count() == 1

    body = finance_client(scenario).get(
        reverse("admin_console:payout-reviews")
    ).content.decode()
    assert "Payout method reviews" in body
    assert scenario.traveler.email in body
    assert f"#{profile.sequence}" in body
    assert "Waiting for review" in body

    # H4.1's list rule, unchanged: no account data reaches a list, masked or
    # otherwise. A list is read over shoulders and screenshotted into chat, so
    # not even the mask that the detail page shows belongs here.
    assert SECRET_CCP not in body
    assert SECRET_RIP not in body
    assert "••••" not in body


@pytest.mark.django_db
def test_the_queue_separates_finances_move_from_the_travelers(
    configured_h4,  # noqa: F811
):
    scenario, profile = build_profile("j12-buckets")
    client = finance_client(scenario)

    client.post(detail_url(profile), {"action": "decide", "decision": "needs_attention"})

    # A profile sent back for correction is the Traveler's move. Counting it as
    # work waiting on Finance is how a real submission waits behind a queue
    # nobody is working.
    assert awaiting_review_count() == 0
    correction = client.get(
        reverse("admin_console:payout-reviews") + "?bucket=correction"
    ).content.decode()
    assert scenario.traveler.email in correction
    waiting = client.get(
        reverse("admin_console:payout-reviews") + "?bucket=waiting"
    ).content.decode()
    assert scenario.traveler.email not in waiting


# ---------------------------------------------------------------------------
# The decisions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_all_three_decisions_are_recordable_and_each_one_is_kept(
    configured_h4,  # noqa: F811
):
    scenario, profile = build_profile("j12-decide")
    client = finance_client(scenario)
    url = detail_url(profile)

    for decision, expected_reason in (
        ("needs_attention", "profile_correction_required"),
        ("rejected", "profile_rejected"),
        ("approved", ""),
    ):
        client.post(url, {"action": "decide", "decision": decision})
        method = TravelerPayoutMethod.objects.get(pk=profile.method_id)
        assert method.status_reason == expected_reason, decision
        assert method.status == ("ready" if decision == "approved" else "needs_review")

    # Immutable: three appended rows, in order, none replacing another. The
    # revision itself is untouched by any of them.
    recorded = list(
        PayoutProfileReview.objects.filter(profile=profile)
        .order_by("pk")
        .values_list("status", flat=True)
    )
    assert recorded == ["needs_attention", "rejected", "approved"]
    profile.refresh_from_db()
    assert profile.sequence == 1
    assert approved_profile(profile) is True

    history = client.get(url).content.decode()
    assert history.count("Needs correction") >= 1
    assert history.count("Reject") >= 1


@pytest.mark.django_db
def test_no_decision_is_offered_or_accepted_without_an_attested_identity(
    configured_h4,  # noqa: F811
):
    scenario, profile = build_profile("j12-identity", attested=False)
    client = finance_client(scenario)
    url = detail_url(profile)

    page = client.get(url).content.decode()
    assert "Not attested" in page
    assert 'name="decision"' not in page
    assert "Assign identity review" in page

    # And the server refuses it independently of what the page offered.
    client.post(url, {"action": "decide", "decision": "approved"})
    assert not PayoutProfileReview.objects.filter(profile=profile).exists()
    assert awaiting_review_count() == 1


@pytest.mark.django_db
def test_an_approval_over_a_name_difference_needs_explicit_acceptance(
    configured_h4,  # noqa: F811
):
    scenario, profile = build_profile("j12-names", attested=False)
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
    url = detail_url(profile)

    # Approving without the acceptance is recorded as a correction request —
    # the server makes that substitution, not the page.
    client.post(url, {"action": "decide", "decision": "approved"})
    assert (
        PayoutProfileReview.objects.filter(profile=profile)
        .order_by("-pk")
        .first()
        .status
        == "needs_attention"
    )

    client.post(
        url,
        {
            "action": "decide",
            "decision": "approved",
            "accept_name_difference": "on",
        },
    )
    assert (
        PayoutProfileReview.objects.filter(profile=profile)
        .order_by("-pk")
        .first()
        .status
        == "approved"
    )


# ---------------------------------------------------------------------------
# Who may reach any of it
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["ops", "support", "trust_verification"])
def test_only_finance_and_super_reach_the_review_surface(role, configured_h4):  # noqa: F811
    scenario, profile = build_profile(f"j12-role-{role}")
    assign_admin_roles(scenario.outsider, [role])
    client = Client()
    client.force_login(scenario.outsider)

    for url in (
        reverse("admin_console:payout-reviews"),
        detail_url(profile),
        reverse(
            "admin_console:payout-review-evidence", args=[profile.public_reference]
        ),
    ):
        assert client.get(url).status_code == 403, url

    # And a decision cannot be posted past the page either.
    client.post(detail_url(profile), {"action": "decide", "decision": "approved"})
    assert not PayoutProfileReview.objects.filter(profile=profile).exists()


@pytest.mark.django_db
def test_super_admin_reaches_it(configured_h4):  # noqa: F811
    scenario, profile = build_profile("j12-super")
    assign_admin_roles(scenario.outsider, ["super_admin"])
    client = Client()
    client.force_login(scenario.outsider)
    assert client.get(reverse("admin_console:payout-reviews")).status_code == 200
    assert client.get(detail_url(profile)).status_code == 200


@pytest.mark.django_db
def test_the_destination_is_masked_until_a_deliberate_audited_reveal(
    configured_h4,  # noqa: F811
):
    scenario, profile = build_profile("j12-reveal")
    client = finance_client(scenario)
    url = detail_url(profile)

    masked = client.get(url)
    assert masked["Cache-Control"] == "no-store, private"
    body = masked.content.decode()
    assert SECRET_CCP not in body and SECRET_RIP not in body
    assert "•••• 0000" in body

    revealed = client.post(url, {"action": "reveal"})
    assert revealed["Cache-Control"] == "no-store, private"
    shown = revealed.content.decode()
    assert SECRET_CCP in shown and SECRET_RIP in shown
    assert "this open was audited" in shown.lower()

    # A reveal is never reachable by re-reading the page.
    assert SECRET_CCP not in client.get(url).content.decode()


@pytest.mark.django_db
def test_the_cheque_is_served_only_through_its_own_profile(configured_h4):  # noqa: F811
    scenario, profile = build_profile("j12-cheque")
    client = finance_client(scenario)
    response = client.get(
        reverse("admin_console:payout-review-evidence", args=[profile.public_reference])
    )
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store, private"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Referrer-Policy"] == "no-referrer"

    # A payout-method reference is not an evidence reference, and neither is a
    # random uuid: there is no route from this view to an arbitrary document.
    assert (
        client.get(
            reverse(
                "admin_console:payout-review-evidence",
                args=[profile.method.public_reference],
            )
        ).status_code
        == 404
    )


# ---------------------------------------------------------------------------
# What the Traveler is told afterwards
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_traveler_sees_a_safe_distinct_state_for_each_outcome(
    configured_h4,  # noqa: F811
):
    scenario, profile = build_profile("j12-traveler")

    def projected():
        method = TravelerPayoutMethod.objects.select_related(
            "current_version__dzd_profile_revision"
        ).get(pk=profile.method_id)
        return dzd_method(method)

    assert projected()["state"] == "pending_review"

    review_profile(
        actor=scenario.admin,
        reference=profile.public_reference,
        decision="needs_attention",
    )
    correction = projected()
    assert correction["state"] == "needs_attention"
    assert correction["profile"]["review_state"] == "needs_attention"

    review_profile(
        actor=scenario.admin, reference=profile.public_reference, decision="rejected"
    )
    rejected = projected()
    assert rejected["state"] == "needs_attention"
    # The one field that lets the Traveler's card tell the two apart, and the
    # only thing about the decision they are given.
    assert rejected["profile"]["review_state"] == "rejected"

    review_profile(
        actor=scenario.admin, reference=profile.public_reference, decision="approved"
    )
    ready = projected()
    assert ready["state"] == "ready" and ready["ready"] is True

    # Nothing a reviewer wrote or a reviewer's identity reaches the Traveler.
    flat = str(ready) + str(rejected) + str(correction)
    assert scenario.admin.email not in flat
    assert SECRET_CCP not in flat


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_review_queue_stays_cheap_as_it_fills(configured_h4):  # noqa: F811
    """A queue is opened far more often than it is acted on.

    The bound is generous — it is a regression guard, not a target — but it is
    flat: ten submissions must not cost ten times one submission. The Finance
    dashboard beside it costs roughly ninety queries for a full control-plane
    snapshot, and this page must not become that.
    """

    scenario, _ = build_profile("j12-cost-0")
    client = finance_client(scenario)
    url = reverse("admin_console:payout-reviews")

    client.get(url)  # warm the session/permission reads
    with CaptureQueriesContext(connection) as one:
        assert client.get(url).status_code == 200

    for index in range(1, 10):
        build_profile(f"j12-cost-{index}")
    with CaptureQueriesContext(connection) as ten:
        assert client.get(url).status_code == 200

    assert len(one.captured_queries) <= 12, len(one.captured_queries)
    assert len(ten.captured_queries) <= 12, len(ten.captured_queries)
    # Flat, not merely small: this is the N+1 guard.
    assert len(ten.captured_queries) == len(one.captured_queries)
    assert awaiting_review_count() == 10


@pytest.mark.django_db
def test_the_overview_attention_count_is_one_indexed_query(configured_h4):  # noqa: F811
    build_profile("j12-count")
    with CaptureQueriesContext(connection) as captured:
        assert awaiting_review_count() == 1
    assert len(captured.captured_queries) == 1
