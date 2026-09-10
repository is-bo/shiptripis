"""H4.1 — the Finance operator's view of a manual DZD payout.

These tests are about what the screen *says* and what it *offers*, because that
is what H4.1 changed. The financial guarantees themselves are H4's and are
tested in `test_phase8fh4_manual.py`; nothing here re-verifies them, and nothing
here may pass by weakening them. What is asserted is the operator-facing
contract: no control that skips the state machine, no sensitive value outside a
deliberate reveal, no evidence reachable from a payout it does not belong to,
approved wording carried verbatim in all three languages, and a refusal that
tells the operator which condition failed.
"""

import re

import pytest
from django.test import Client, override_settings
from django.urls import reverse

from apps.admin_panel.console_manual_presenter import (
    blockers_of,
    manual_view,
    state_of,
)
from apps.admin_panel.permissions import assign_admin_roles
from apps.finance.payout_domain import open_hold
from apps.finance.payout_evidence import CHEQUE_LABELS, RECEIPT_LABELS
from apps.finance.payout_evidence import upload_evidence
from apps.finance.payout_manual import prepare, begin, confirm
from .test_phase8fh4_manual import configured_h4, build_manual, image_upload  # noqa: F401

SECRET_CCP = "0000000000"
SECRET_RIP = "0" * 20


@pytest.fixture(autouse=True)
def console_staticfiles(settings):
    # Render assertions do not depend on a pre-existing collectstatic manifest.
    with override_settings(
        STORAGES={
            **settings.STORAGES,
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
            },
        }
    ):
        yield


def detail_url(payout):
    return reverse("admin_console:payout-detail", args=[payout.pk])


@pytest.mark.django_db
def test_detail_reads_as_an_instruction_and_never_offers_mark_paid(configured_h4):  # noqa: F811
    s, payout, profile = build_manual(prefix="h41-read")
    client = Client()
    client.force_login(s.admin)
    body = client.get(detail_url(payout)).content.decode()

    # The exact approved wording, in the three languages it is approved in, for
    # both documents. Neither set is translated, abbreviated or merged.
    for label in CHEQUE_LABELS.values():
        assert label in body
    assert 'lang="ar" dir="rtl"' in body
    assert "NIP" not in body

    # The amount an operator retypes into a bank, and the euro obligation it is
    # derived from, both present and clearly distinguished.
    assert "15,600 DZD" in body
    assert "€60.00" in body
    assert "1 EUR = 260 DZD" in body
    assert 'data-copy-exact="15600"' in body

    # The instruction reads as something a person does, not something ShipTrip
    # does, and there is no one-click settlement anywhere on the page.
    assert "ShipTrip does not perform this transfer." in body
    assert "Mark paid" not in body and "Mark payout paid" not in body
    for offered in re.findall(r'name="action" value="([a-z_]+)"', body):
        assert offered in {"reveal", "prepare", "review", "hold", "clear_hold"}


@pytest.mark.django_db
def test_masked_by_default_and_revealed_only_on_purpose(configured_h4):  # noqa: F811
    s, payout, profile = build_manual(prefix="h41-mask")
    client = Client()
    client.force_login(s.admin)
    url = detail_url(payout)

    masked = client.get(url)
    assert masked["Cache-Control"] == "no-store, private"
    # Not merely "not displayed": absent from the document altogether, so no
    # attribute, script or comment carries it either.
    assert SECRET_CCP not in masked.content.decode()
    assert SECRET_RIP not in masked.content.decode()
    assert "•••• 0000" in masked.content.decode()

    revealed = client.post(url, {"action": "reveal"})
    assert revealed.status_code == 200
    assert revealed["Cache-Control"] == "no-store, private"
    shown = revealed.content.decode()
    assert SECRET_CCP in shown and SECRET_RIP in shown
    # The revealed panel is the only place the values appear, it says the open
    # was audited, and it offers a way back to masked.
    assert "this open was audited" in shown.lower()
    assert "Hide details" in shown

    # A reveal is never reachable by re-reading the page.
    assert SECRET_CCP not in client.get(url).content.decode()


@pytest.mark.django_db
def test_evidence_is_scoped_to_its_own_payout(configured_h4):  # noqa: F811
    s, payout, profile = build_manual(prefix="h41-ev1")
    other_s, other_payout, other_profile = build_manual(prefix="h41-ev2")
    client = Client()
    client.force_login(s.admin)

    mine = reverse(
        "admin_console:payout-evidence",
        args=[payout.pk, profile.evidence.public_reference],
    )
    response = client.get(mine)
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store, private"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Content-Disposition"] == 'inline; filename="payout-evidence"'
    # No storage URL is ever emitted; the bytes are the response.
    assert response.content[:4] == b"\x89PNG"

    # Someone else's crossed cheque is not reachable through this payout, even
    # for an operator who is allowed to see that document on its own payout.
    theirs = reverse(
        "admin_console:payout-evidence",
        args=[payout.pk, other_profile.evidence.public_reference],
    )
    assert client.get(theirs).status_code == 404


@pytest.mark.django_db
def test_only_finance_and_super_reach_the_screen_or_the_evidence(configured_h4):  # noqa: F811
    s, payout, profile = build_manual(prefix="h41-perm")
    client = Client()
    evidence = reverse(
        "admin_console:payout-evidence",
        args=[payout.pk, profile.evidence.public_reference],
    )
    for role in ("support", "ops", "trust_verification"):
        assign_admin_roles(s.outsider, [role])
        client.force_login(s.outsider)
        assert client.get(detail_url(payout)).status_code == 403
        assert client.get(evidence).status_code == 403
        assert client.post(detail_url(payout), {"action": "reveal"}).status_code == 403

    assign_admin_roles(s.outsider, ["super_admin"])
    client.force_login(s.outsider)
    assert client.get(detail_url(payout)).status_code == 200
    assert client.get(evidence).status_code == 200


@pytest.mark.django_db
def test_a_hold_names_itself_and_removes_the_controls(configured_h4):  # noqa: F811
    s, payout, profile = build_manual(prefix="h41-hold")
    client = Client()
    client.force_login(s.admin)
    assert (
        "Claim and prepare transfer" in client.get(detail_url(payout)).content.decode()
    )

    open_hold(
        actor=s.admin,
        payout_id=payout.pk,
        kind="manual",
        reason_code="manual_transfer_review",
        source_reference=f"manual:{payout.pk}:{payout.state_version}",
    )
    body = client.get(detail_url(payout)).content.decode()
    assert "What is holding this payout" in body
    assert "Opened by Finance for correction or recovery review" in body
    # The chip must not still read "Ready for payout" while the page refuses to
    # do anything: a held payout is stored as eligible and is not ready.
    assert "On hold" in body
    assert "Claim and prepare transfer" not in body
    # And the server refuses independently of what the page shows.
    assert (
        client.post(
            detail_url(payout),
            {"action": "prepare", "state_version": payout.state_version},
        ).status_code
        == 200
    )
    payout.refresh_from_db()
    assert payout.status == "eligible"


@pytest.mark.django_db
def test_a_claim_is_visible_to_the_operator_who_does_not_own_it(configured_h4):  # noqa: F811
    s, payout, profile = build_manual(prefix="h41-claim")
    client = Client()
    client.force_login(s.admin)
    assert "Available for processing" in client.get(detail_url(payout)).content.decode()

    prepare(
        actor=s.admin, payout_id=payout.pk, expected_state_version=payout.state_version
    )
    mine = client.get(detail_url(payout)).content.decode()
    assert "You are processing this" in mine
    assert "Start the transfer" in mine and "Release the claim" in mine

    assign_admin_roles(s.outsider, ["finance"])
    client.force_login(s.outsider)
    theirs = client.get(detail_url(payout)).content.decode()
    assert "Being processed by" in theirs
    assert "Do not send a second transfer." in theirs
    assert "Start the transfer" not in theirs and "Release the claim" not in theirs


@pytest.mark.django_db
def test_sent_and_paid_are_never_the_same_state(configured_h4):  # noqa: F811
    s, payout, profile = build_manual(prefix="h41-states")
    client = Client()
    client.force_login(s.admin)
    prepare(
        actor=s.admin, payout_id=payout.pk, expected_state_version=payout.state_version
    )
    payout.refresh_from_db()
    attempt = payout.attempts.order_by("-sequence").first()
    begin(actor=s.admin, payout_id=payout.pk, sequence=attempt.sequence)

    processing = client.get(detail_url(payout)).content.decode()
    assert "Processing" in processing
    assert RECEIPT_LABELS["fr"] in processing and RECEIPT_LABELS["ar"] in processing
    assert "I attest that exactly 15,600 DZD was sent" in processing

    first = upload_evidence(
        actor=s.admin, upload=image_upload(), purpose="transfer_receipt"
    )
    confirm(
        actor=s.admin,
        payout_id=payout.pk,
        sequence=attempt.sequence,
        evidence_reference=first.public_reference,
        confirmed=True,
        settled=False,
    )
    sent = client.get(detail_url(payout)).content.decode()
    assert "Transfer sent" in sent
    assert "ShipTrip has not recorded settlement yet." in sent
    # The state chip is the one place the two must not be interchangeable.
    assert 'class="st-chip st-info">Transfer sent</span>' in sent
    assert 'class="st-chip st-ok">Paid</span>' not in sent

    second = upload_evidence(
        actor=s.admin, upload=image_upload(), purpose="transfer_receipt"
    )
    confirm(
        actor=s.admin,
        payout_id=payout.pk,
        sequence=attempt.sequence,
        evidence_reference=second.public_reference,
        confirmed=True,
        settled=True,
    )
    paid = client.get(detail_url(payout)).content.decode()
    assert "Settlement is recorded against the ledger." in paid
    # Both revisions survive: a correction appends evidence, it never replaces
    # the document an operator already attested to.
    assert paid.count("View receipt") == 2
    assert "Record transfer evidence" not in paid


@pytest.mark.django_db
def test_a_newer_profile_is_context_and_never_an_alternative(configured_h4):  # noqa: F811
    from apps.finance.payout_profiles import submit_dzd_profile

    s, payout, profile = build_manual(prefix="h41-version")
    proof = upload_evidence(actor=s.traveler, upload=image_upload())
    submit_dzd_profile(
        actor=s.traveler,
        expected_revision=profile.method.revision,
        first_name="QA",
        last_name="Synthetic",
        ccp_number="9999999999",
        ccp_key="99",
        rip="9" * 20,
        proof_reference=proof.public_reference,
    )
    client = Client()
    client.force_login(s.admin)
    body = client.get(detail_url(payout)).content.decode()

    assert "The Traveler has since changed their payout details." in body
    assert "applies to future payouts only" in body
    assert "This destination was locked when the shipment was funded" in body
    # The replacement account's mask must not be offered as this payout's
    # destination.
    assert "•••• 9999" not in body
    payout.refresh_from_db()
    assert payout.active_instruction_version.dzd_profile_revision_id == profile.pk


@pytest.mark.django_db
def test_a_refusal_says_which_condition_failed(configured_h4):  # noqa: F811
    s, payout, profile = build_manual(prefix="h41-refuse")
    client = Client()
    client.force_login(s.admin)
    # A stale state version is the ordinary two-tabs-open case.
    body = client.post(
        detail_url(payout), {"action": "prepare", "state_version": 9999}
    ).content.decode()
    assert "Claiming this payout was refused." in body
    assert "This payout changed while the page was open." in body
    assert "Traceback" not in body


@pytest.mark.django_db
def test_the_queue_shows_the_settlement_amount_and_what_it_waits_on(configured_h4):  # noqa: F811
    s, payout, profile = build_manual(prefix="h41-queue")
    client = Client()
    client.force_login(s.admin)
    body = client.get(reverse("admin_console:payouts")).content.decode()

    assert "Manual DZD transfer" in body
    assert "€60.00" in body and "15,600 DZD" in body
    assert "Ready - claim and send" in body
    # A queue never carries account data, masked or otherwise.
    assert SECRET_CCP not in body and "•••• 0000" not in body


@pytest.mark.django_db
def test_presenter_rules(configured_h4):  # noqa: F811
    """The two judgements the presenter makes on its own."""

    s, payout, profile = build_manual(prefix="h41-unit")
    view = manual_view(payout, user=s.admin)

    # A held payout is not "ready", whatever the status column says.
    assert state_of(payout)["label"] == "Ready for payout"
    assert state_of(payout, holds=[object()])["label"] == "On hold"

    # One unreviewed profile is one problem, not two.
    payout.block_reason = "payout_setup_required"
    destination = dict(view["destination"])
    destination["review"] = {**destination["review"], "approved": False}
    titles = [b["title"] for b in blockers_of(payout, destination, holds=[])]
    assert titles.count("Traveler payout profile needs review") == 1
