"""K2 Admin workflow continuity and shared server-rendered UI contracts."""

from datetime import timedelta
from html import unescape
from urllib.parse import parse_qs, urlsplit

import pytest
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.admin_panel.permissions import AdminRole, assign_admin_roles
from apps.admin_panel.utils import admin_url, bounded_query_text, positive_page
from apps.core.templatetags.shiptrip_admin import admin_querystring
from apps.deals.tests.phase4_factories import delivered_scenario
from apps.disputes.models import Dispute
from apps.disputes.services import open_dispute
from apps.kyc.models import KycSubmission
from apps.trips.models import Journey, JourneyLeg, JourneyLegProof

User = get_user_model()


@pytest.fixture(autouse=True)
def unhashed_static(settings):
    with override_settings(
        STORAGES={
            **settings.STORAGES,
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
            },
        }
    ):
        yield


def _staff(role: str, suffix: str):
    user = User.objects.create_user(
        username=f"k2-{suffix}@example.test",
        email=f"k2-{suffix}@example.test",
        is_staff=True,
    )
    assign_admin_roles(user, (role,))
    return user


def test_admin_url_allowlists_query_and_rejects_unsafe_fragments():
    request = RequestFactory().get(
        "/admin/verification/kyc/?status=pending&page=2&q=Amina%20%26%20Co&next=https://evil.test"
    )
    url = admin_url(
        request,
        "admin_console:kyc-queue",
        fragment="st-decision-head",
        preserve_query={
            "status": {"pending", "approved"},
            "page": positive_page,
            "q": bounded_query_text,
        },
    )
    split = urlsplit(url)
    assert split.path == reverse("admin_console:kyc-queue")
    assert parse_qs(split.query) == {
        "status": ["pending"],
        "page": ["2"],
        "q": ["Amina & Co"],
    }
    assert split.fragment == "st-decision-head"
    assert "next" not in split.query

    with pytest.raises(ValueError, match="Unsafe Admin fragment"):
        admin_url(request, "admin_console:kyc-queue", fragment='bad" onclick="x')


def test_shared_pagination_replaces_only_page_and_encodes_values():
    request = RequestFactory().get(
        "/admin/?q=Amina%20%26%20Co&bucket=ready&start=2026-09-01&end=2026-09-21&page=1"
    )
    query = admin_querystring({"request": request}, page=2)
    assert parse_qs(query) == {
        "q": ["Amina & Co"],
        "bucket": ["ready"],
        "start": ["2026-09-01"],
        "end": ["2026-09-21"],
        "page": ["2"],
    }

    html = unescape(
        render_to_string(
            "admin/console/_pagination.html",
            {"page_obj": Paginator(range(60), 25).page(1)},
            request=request,
        )
    )
    assert 'aria-label="Next page, page 2"' in html
    href = html.split('aria-label="Next page, page 2" href="', 1)[1].split('"', 1)[0]
    assert parse_qs(urlsplit(href).query)["page"] == ["2"]
    assert parse_qs(urlsplit(href).query)["bucket"] == ["ready"]


def test_finance_scope_uses_canonical_controls():
    request = RequestFactory().get("/admin/finance/dashboard/")
    html = render_to_string(
        "admin/console/_finance_scope.html",
        {
            "scope": {
                "periods": (),
                "action": request.path,
                "hidden": (),
                "mode_choices": (("test", "TEST"),),
                "mode": "test",
                "custom": True,
                "start": "2026-09-01",
                "end": "2026-09-21",
                "period": "custom",
                "refine": (),
                "search": "",
                "reset_url": request.path,
                "mode_help": "TEST records only.",
            }
        },
        request=request,
    )
    assert '<form method="get"' in html and 'class="st-scope-form"' in html
    assert '<button class="button" type="submit">Apply</button>' in html
    assert 'class="st-scope-field"' in html
    assert 'type="date"' in html


@pytest.mark.django_db
@pytest.mark.parametrize("decision", ["approved", "rejected"])
def test_kyc_decision_preserves_valid_queue_context(decision):
    trust = _staff(AdminRole.TRUST, f"kyc-{decision}")
    applicant = User.objects.create_user(
        username=f"k2-applicant-{decision}@example.test",
        email=f"k2-applicant-{decision}@example.test",
    )
    submission = KycSubmission.objects.create(
        user=applicant,
        document_type=KycSubmission.DocumentType.PASSPORT,
        idempotency_key=f"k2-kyc-{decision}-000000000000"[:32],
        status=KycSubmission.Status.PENDING,
    )
    client = Client()
    client.force_login(trust)
    response = client.post(
        f"{reverse('admin_console:kyc-detail', args=(submission.pk,))}"
        "?status=pending&page=2&q=Amina&next=https://evil.test",
        {
            "decision": decision,
            "confirm": "on",
            "reason": "Evidence is not readable." if decision == "rejected" else "",
        },
    )
    assert response.status_code == 302
    split = urlsplit(response["Location"])
    assert split.fragment == "st-decision-head"
    assert parse_qs(split.query) == {
        "q": ["Amina"],
        "status": ["pending"],
        "page": ["2"],
    }
    assert client.get(response["Location"]).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("decision", ["approved", "rejected"])
def test_flight_proof_decision_preserves_valid_queue_context(decision):
    trust = _staff(AdminRole.TRUST, f"proof-{decision}")
    traveler = User.objects.create_user(
        username=f"k2-traveler-{decision}@example.test",
        email=f"k2-traveler-{decision}@example.test",
    )
    journey = Journey.objects.create(traveler=traveler)
    leg = JourneyLeg.objects.create(
        journey=journey,
        position=0,
        mode="FLIGHT",
        depart_at=timezone.now() + timedelta(days=2),
        capacity_kg="5.00",
        flight_number="AH1006",
    )
    proof = JourneyLegProof.objects.create(
        leg=leg,
        bucket="private-proof",
        object_key="journeys/k2/proof.jpg",
    )
    client = Client()
    client.force_login(trust)
    response = client.post(
        f"{reverse('admin_console:proof-detail', args=(proof.pk,))}"
        "?status=pending&page=3&q=AH1006&unsafe=drop-me",
        {
            "decision": decision,
            "confirm": "on",
            "reason": "Flight details are unclear." if decision == "rejected" else "",
        },
    )
    assert response.status_code == 302
    split = urlsplit(response["Location"])
    assert split.fragment == "st-decision-head"
    assert parse_qs(split.query) == {
        "q": ["AH1006"],
        "status": ["pending"],
        "page": ["3"],
    }
    assert client.get(response["Location"]).status_code == 200


@pytest.mark.django_db
def test_dispute_preview_stays_at_resolution_and_execute_redirects_there():
    client = Client()
    owner = User.objects.create_superuser(
        username="k2-dispute-owner@example.test",
        email="k2-dispute-owner@example.test",
        password="Strong-password-1",
    )
    scenario = delivered_scenario(client, prefix="k2-dispute")
    dispute = open_dispute(
        deal_id=scenario.deal.pk,
        actor_id=scenario.sender.pk,
        category=Dispute.Category.DAMAGED,
        reason_text="Synthetic damaged parcel evidence.",
    )
    client.force_login(owner)
    url = (
        reverse("admin_console:dispute-detail", args=(dispute.pk,))
        + "?status=open&page=2&q=synthetic"
    )
    data = {
        "action": "preview-resolution",
        "resolution": "full_sender_refund",
        "note": "Evidence supports refund.",
    }
    preview = client.post(url, data)
    assert preview.status_code == 200
    body = preview.content.decode()
    assert 'action="#st-dispute-resolution"' in body
    for anchor in (
        "st-dispute-evidence",
        "st-dispute-timeline",
        "st-dispute-resolution",
        "st-dispute-ledger",
    ):
        assert f'id="{anchor}"' in body

    executed = client.post(
        url,
        {**data, "action": "confirm-resolution", "confirm_resolution": "yes"},
    )
    assert executed.status_code == 302
    split = urlsplit(executed["Location"])
    assert split.fragment == "st-dispute-resolution"
    assert parse_qs(split.query) == {
        "q": ["synthetic"],
        "status": ["open"],
        "page": ["2"],
    }


@pytest.mark.django_db
@override_settings(DEBUG=False)
def test_console_permission_denied_is_friendly_and_remains_403():
    support = _staff(AdminRole.SUPPORT, "friendly-403")
    client = Client(raise_request_exception=False)
    client.force_login(support)
    response = client.get(reverse("admin_console:settings"))
    assert response.status_code == 403
    body = response.content.decode()
    assert "This area is not available to your role" in body
    assert "Return to Admin" in body
    assert "manage_settings" not in body


@pytest.mark.django_db
def test_staff_role_return_keeps_the_edited_row_open():
    owner = User.objects.create_superuser(
        username="k2-staff-owner@example.test",
        email="k2-staff-owner@example.test",
        password="Strong-password-1",
    )
    member = _staff(AdminRole.SUPPORT, "staff-member")
    client = Client()
    client.force_login(owner)
    response = client.post(
        reverse("admin_console:staff-role", args=(member.pk,))
        + f"?edit={member.pk}&next=https://evil.test",
        {"role": AdminRole.FINANCE, "confirm": "on"},
    )
    assert response.status_code == 302
    split = urlsplit(response["Location"])
    assert split.path == reverse("admin_console:staff")
    assert parse_qs(split.query) == {"edit": [str(member.pk)]}
    assert split.fragment == f"staff-{member.pk}"
    page = client.get(response["Location"])
    assert page.status_code == 200
    body = page.content.decode()
    assert f'<tr id="staff-{member.pk}">' in body
    assert '<details class="st-disclosure" open>' in body
