"""Synthetic-only DZD workflow and authorization against the financial aggregate."""

from datetime import timedelta
from io import BytesIO
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Sum
from django.test import override_settings
from django.utils import timezone

from apps.admin_panel.permissions import assign_admin_roles
from apps.deals.models import Deal
from apps.finance.models import PaymentAttempt, Payout, LedgerEntry, PayoutEvidence
from apps.finance.payout_profiles import (
    set_preference,
    submit_dzd_profile,
    assign_identity_review,
    attest_identity,
)
from apps.finance.payout_manual_profiles import review_profile, reveal_profile
from apps.finance.payout_evidence import upload_evidence, read_evidence
from apps.finance.payout_manual import prepare, begin, confirm, release
from apps.finance.payout_domain import open_hold
from apps.finance.services import reconcile_attempt
from .factories import build_scenario
from .test_phase8fh1_foundations import KEYS


def image_upload():
    image = Image.new("RGB", (320, 120), "white")
    ImageDraw.Draw(image).text((10, 40), "QA TEST - NOT A BANK DOCUMENT", fill="black")
    body = BytesIO()
    image.save(body, format="PNG")
    return SimpleUploadedFile("qa.png", body.getvalue(), content_type="image/png")


@pytest.fixture
def configured_h4():
    import base64
    import json

    objects = {}

    class Store:
        def put(self, key, body, mime):
            assert key not in objects and mime == "application/octet-stream"
            objects[key] = body

        def get(self, key):
            return objects[key]

    keys = {
        **KEYS,
        "PAYOUT_DATA_ACTIVE_KEY_ID": "k2",
        "PAYOUT_DATA_KEYRING": json.dumps({"k2": base64.b64encode(b"e" * 32).decode()}),
    }
    with (
        override_settings(**keys, PAYOUT_DZD_EXECUTION_ENABLED=True),
        patch("apps.finance.payout_evidence.storage_for", return_value=Store()),
    ):
        yield objects


def build_manual(prefix="h4"):
    with override_settings(PAYOUT_PROFILES_ENABLED=False):
        s = build_scenario(prefix=prefix)
        s.accept(reward_eur_cents=6000)
    assign_admin_roles(s.admin, ["finance"])
    s.traveler.role = "traveler"
    s.traveler.save(update_fields=["role"])
    set_preference(actor=s.traveler, currency="DZD", enabled=True, expected_revision=0)
    proof = upload_evidence(actor=s.traveler, upload=image_upload())
    method = submit_dzd_profile(
        actor=s.traveler,
        expected_revision=1,
        first_name="QA",
        last_name="Synthetic",
        ccp_number="0000000000",
        ccp_key="00",
        rip="0" * 20,
        proof_reference=proof.public_reference,
    )
    assign_admin_roles(s.outsider, ["trust_verification"])
    assignment = assign_identity_review(
        actor=s.admin, traveler_id=s.traveler.pk, reviewer_id=s.outsider.pk
    )
    attest_identity(
        actor=s.outsider,
        assignment_reference=assignment.public_reference,
        given_name="QA",
        family_name="Synthetic",
    )
    profile = method.current_version.dzd_profile_revision
    review_profile(actor=s.admin, reference=profile.public_reference, approve=True)
    order = s.balance_order()
    amount = order.outstanding_eur_cents
    capture = PaymentAttempt.objects.create(
        order=order,
        provider="chargily",
        provider_mode="test",
        amount_eur_cents=amount,
        payment_currency="DZD",
        provider_amount_minor=amount * 260 // 100,
        fx_rate_micros=260000000,
        fx_settings_version=s.policy.settings_version,
        fx_source="business_settings",
        fx_snapshot_at=timezone.now(),
        idempotency_key=f"{prefix}-capture",
        status="checkout_pending",
    )
    reconcile_attempt(
        attempt_id=capture.pk,
        outcome="succeeded",
        provider_payment_id=f"qa-{prefix}",
        provider_amount_minor=amount * 260 // 100,
        provider_currency="DZD",
    )
    payout = Payout.objects.get(deal=s.deal)
    now = timezone.now()
    Deal.objects.filter(pk=s.deal.pk).update(
        status="protection_window",
        pickup_confirmed_at=now - timedelta(hours=96),
        delivery_code_available_at=now - timedelta(hours=95),
        delivery_code_released_at=now - timedelta(hours=95),
        delivery_confirmed_at=now - timedelta(hours=72),
        protection_ends_at=now - timedelta(hours=24),
    )
    from apps.finance.payout_release import evaluate_payout_release

    evaluate_payout_release(deal_id=s.deal.pk)
    payout.refresh_from_db()
    return s, payout, profile


@pytest.mark.django_db
def test_manual_end_to_end_receipt_and_balanced_settlement(configured_h4):
    s, payout, profile = build_manual()
    assert payout.payout_amount_minor == 15600 and payout.amount_eur_cents == 6000
    values = reveal_profile(actor=s.admin, reference=profile.public_reference)
    assert set(values) == {"first_name", "last_name", "ccp_number", "ccp_key", "rip"}
    body, mime = read_evidence(
        actor=s.admin, reference=profile.evidence.public_reference
    )
    assert mime == "image/png" and body.startswith(b"\x89PNG")
    assert all(b"\x89PNG" not in value for value in configured_h4.values())
    prepare(
        actor=s.admin, payout_id=payout.pk, expected_state_version=payout.state_version
    )
    begin(actor=s.admin, payout_id=payout.pk, sequence=1)
    receipt = upload_evidence(
        actor=s.admin, upload=image_upload(), purpose="transfer_receipt"
    )
    sent = confirm(
        actor=s.admin,
        payout_id=payout.pk,
        sequence=1,
        evidence_reference=receipt.public_reference,
        confirmed=True,
    )
    assert sent.status == "sent" and not sent.paid_at
    completed = upload_evidence(
        actor=s.admin, upload=image_upload(), purpose="transfer_receipt"
    )
    paid = confirm(
        actor=s.admin,
        payout_id=payout.pk,
        sequence=1,
        evidence_reference=completed.public_reference,
        confirmed=True,
        settled=True,
    )
    assert paid.status == "paid" and paid.sent_at and paid.paid_at
    assert paid.attempts.get().manual_receipts.count() == 2
    assert (
        LedgerEntry.objects.filter(deal_id=s.deal.pk).aggregate(
            n=Sum("amount_eur_cents")
        )["n"]
        == 0
    )
    assert (
        LedgerEntry.objects.filter(
            deal_id=s.deal.pk, account="traveler_payable"
        ).aggregate(n=Sum("amount_eur_cents"))["n"]
        == 0
    )
    assert (
        confirm(
            actor=s.admin,
            payout_id=payout.pk,
            sequence=1,
            evidence_reference=completed.public_reference,
            confirmed=True,
            settled=True,
        ).status
        == "paid"
    )


@pytest.mark.django_db
def test_claim_hold_release_and_proof_authority(configured_h4):
    s, payout, profile = build_manual()
    for role in ("support", "ops", "trust_verification"):
        assign_admin_roles(s.outsider, [role])
        with pytest.raises(PermissionDenied):
            reveal_profile(actor=s.outsider, reference=profile.public_reference)
    prepare(
        actor=s.admin, payout_id=payout.pk, expected_state_version=payout.state_version
    )
    with pytest.raises(ValidationError):
        prepare(
            actor=s.admin,
            payout_id=payout.pk,
            expected_state_version=payout.state_version,
        )
    release(actor=s.admin, payout_id=payout.pk, sequence=1)
    payout.refresh_from_db()
    prepare(
        actor=s.admin, payout_id=payout.pk, expected_state_version=payout.state_version
    )
    begin(actor=s.admin, payout_id=payout.pk, sequence=2)
    hold = open_hold(
        actor=s.admin,
        payout_id=payout.pk,
        kind="manual",
        reason_code="qa_review",
        source_reference="qa",
    )
    assert hold.amount_exposure_eur_cents == 6000
    with pytest.raises(ValidationError):
        release(actor=s.admin, payout_id=payout.pk, sequence=2)
    receipt = upload_evidence(
        actor=s.admin, upload=image_upload(), purpose="transfer_receipt"
    )
    with pytest.raises(ValidationError):
        confirm(
            actor=s.admin,
            payout_id=payout.pk,
            sequence=2,
            evidence_reference=receipt.public_reference,
            confirmed=True,
            settled=True,
        )


@pytest.mark.django_db
def test_invalid_image_is_not_stored(configured_h4):
    from .factories import make_user

    user = make_user("qa-proof@example.invalid")
    user.role = "traveler"
    user.save(update_fields=["role"])
    with pytest.raises(ValidationError):
        upload_evidence(
            actor=user,
            upload=SimpleUploadedFile(
                "fake.png", b"not an image", content_type="image/png"
            ),
        )
    assert not configured_h4 and not PayoutEvidence.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field",
    ["verified", "dzd_amount", "fx_rate_micros", "paid_at", "status", "admin_actor"],
)
def test_traveler_cannot_supply_authoritative_fields(configured_h4, field):
    from rest_framework.test import APIClient
    from .factories import make_user

    user = make_user("qa-input@example.invalid")
    client = APIClient()
    client.force_authenticate(user)
    response = client.post(
        "/api/payouts/profiles/dzd", {field: "injected"}, format="json"
    )
    assert response.status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field",
    ["first_name", "last_name", "ccp_number", "ccp_key", "rip", "proof_reference"],
)
def test_required_profile_fields(configured_h4, field):
    from apps.finance.payout_profile_api import DzdInput

    data = dict(
        expected_revision=0,
        first_name="QA",
        last_name="Synthetic",
        ccp_number="0000",
        ccp_key="00",
        rip="0" * 20,
        proof_reference="00000000-0000-0000-0000-000000000000",
        consent_policy="payout_profile_v1",
    )
    del data[field]
    assert not DzdInput(data=data).is_valid()


@pytest.mark.django_db
@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        }
    }
)
def test_console_and_profile_replacement(configured_h4):
    from django.test import Client
    from django.urls import reverse
    from apps.finance.payout_profile_api import method_projection
    from apps.finance.models import DzdPayoutProfileRevision

    s, payout, profile = build_manual()
    client = Client()
    client.force_login(s.admin)
    url = reverse("admin_console:payout-detail", args=[payout.pk])
    response = client.get(url)
    assert response.status_code == 200
    assert (
        b"Prepare transfer" in response.content and b"Mark paid" not in response.content
    )
    assert b"0000000000" not in response.content
    assert response["Cache-Control"] == "no-store, private"
    assert client.post(url, {"action": "reveal"}).status_code == 200
    assert client.post(url, {"action": "proof"}).status_code == 200
    method = profile.method
    proof = upload_evidence(actor=s.traveler, upload=image_upload())
    replacement = submit_dzd_profile(
        actor=s.traveler,
        expected_revision=method.revision,
        first_name="QA",
        last_name="Synthetic",
        ccp_number="٠٠٠٠-٠٠٠٠٠٠",
        ccp_key="٠٠",
        rip="٠" * 20,
        proof_reference=proof.public_reference,
    )
    assert replacement.current_version.dzd_profile_revision_id != profile.pk
    assert (
        replacement.current_version.dzd_profile_revision.account_fingerprint
        == profile.account_fingerprint
    )
    payout.refresh_from_db()
    assert payout.active_instruction_version.dzd_profile_revision_id == profile.pk
    set_preference(
        actor=s.traveler,
        currency="DZD",
        enabled=False,
        expected_revision=replacement.revision,
    )
    assert DzdPayoutProfileRevision.objects.filter(pk=profile.pk).exists()
    assert "rip_encrypted" not in str(method_projection(replacement))
    assert (
        client.post(
            url, {"action": "prepare", "state_version": payout.state_version}
        ).status_code
        == 302
    )
    for role in ("support", "ops", "trust_verification"):
        assign_admin_roles(s.outsider, [role])
        client.force_login(s.outsider)
        assert client.get(url).status_code == 403


@pytest.mark.django_db
def test_api_upload_and_object_isolation(configured_h4):
    from rest_framework.test import APIClient

    s, payout, profile = build_manual()
    client = APIClient()
    client.force_authenticate(s.traveler)
    response = client.post(
        "/api/payouts/proofs", {"image": image_upload()}, format="multipart"
    )
    assert response.status_code == 201
    assert set(response.data) == {"reference", "labels"}
    for role in ("support", "ops", "trust_verification"):
        assign_admin_roles(s.outsider, [role])
        client.force_authenticate(s.outsider)
        assert (
            client.get(
                f"/api/admin/payouts/evidence/{profile.evidence.public_reference}"
            ).status_code
            == 403
        )
    client.force_authenticate(s.admin)
    evidence = client.get(
        f"/api/admin/payouts/evidence/{profile.evidence.public_reference}"
    )
    assert (
        evidence.status_code == 200 and evidence["Cache-Control"] == "no-store, private"
    )
    s.sender.role = "traveler"
    s.sender.save(update_fields=["role"])
    with pytest.raises(ValidationError):
        submit_dzd_profile(
            actor=s.sender,
            expected_revision=0,
            first_name="QA",
            last_name="Synthetic",
            ccp_number="0000",
            ccp_key="00",
            rip="0" * 20,
            proof_reference=profile.evidence.public_reference,
        )


@pytest.mark.django_db
@pytest.mark.parametrize("invalid", ["mime", "extension", "oversize", "malformed"])
def test_image_validation(configured_h4, invalid):
    from .factories import make_user
    from apps.finance.payout_evidence import MAX_BYTES

    user = make_user("qa-image@example.invalid")
    user.role = "traveler"
    user.save(update_fields=["role"])
    upload = image_upload()
    if invalid == "mime":
        upload.content_type = "application/pdf"
    elif invalid == "extension":
        upload.name = "qa.html"
    elif invalid == "oversize":
        upload = SimpleUploadedFile(
            "qa.png", b"0" * (MAX_BYTES + 1), content_type="image/png"
        )
    else:
        upload = SimpleUploadedFile("qa.png", b"\x89PNG\r\n", content_type="image/png")
    with pytest.raises(ValidationError):
        upload_evidence(actor=user, upload=upload)
    assert not configured_h4


@pytest.mark.django_db
def test_protection_receipt_and_rail_guards(configured_h4):
    from apps.finance.payout_execution import _assert_dispatchable, PayoutBlocked

    s, payout, profile = build_manual()
    with pytest.raises(PayoutBlocked):
        _assert_dispatchable(payout)
    Deal.objects.filter(pk=s.deal.pk).update(
        protection_ends_at=timezone.now() + timedelta(hours=12)
    )
    with pytest.raises(ValidationError):
        prepare(
            actor=s.admin,
            payout_id=payout.pk,
            expected_state_version=payout.state_version,
        )
    Deal.objects.filter(pk=s.deal.pk).update(
        protection_ends_at=timezone.now() - timedelta(hours=1)
    )
    with override_settings(PAYOUT_DZD_EXECUTION_ENABLED=False):
        with pytest.raises(PermissionDenied):
            prepare(
                actor=s.admin,
                payout_id=payout.pk,
                expected_state_version=payout.state_version,
            )
    prepare(
        actor=s.admin, payout_id=payout.pk, expected_state_version=payout.state_version
    )
    begin(actor=s.admin, payout_id=payout.pk, sequence=1)
    with pytest.raises(PayoutEvidence.DoesNotExist):
        confirm(
            actor=s.admin,
            payout_id=payout.pk,
            sequence=1,
            evidence_reference=profile.evidence.public_reference,
            confirmed=True,
            settled=True,
        )
    from django.db import DatabaseError, transaction

    with pytest.raises(DatabaseError), transaction.atomic():
        Payout.objects.filter(pk=payout.pk).update(amount_eur_cents=5000)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("race", ["claim", "refund", "hold", "finalize"])
def test_postgres_manual_races(configured_h4, race):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import connection, connections
    from apps.finance.services import request_refund, RefundExceedsCapture
    from .test_phase8fh3_concurrency import _seed_settings, _seed_admin_roles

    assert connection.vendor == "postgresql", "Real PostgreSQL required"
    _seed_settings()
    _seed_admin_roles()
    with patch("apps.core.redis_bus.publish_after_commit"):
        s, payout, profile = build_manual(prefix=f"h4-{race}")
        assign_admin_roles(s.outsider, ["finance"])
        if race in ("hold", "finalize"):
            prepare(
                actor=s.admin,
                payout_id=payout.pk,
                expected_state_version=payout.state_version,
            )
        if race == "finalize":
            begin(actor=s.admin, payout_id=payout.pk, sequence=1)
            receipt = upload_evidence(
                actor=s.admin, upload=image_upload(), purpose="transfer_receipt"
            )
        barrier = Barrier(2)

        def worker(index):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                if race == "claim":
                    prepare(
                        actor=s.admin if index == 0 else s.outsider,
                        payout_id=payout.pk,
                        expected_state_version=payout.state_version,
                    )
                elif race == "refund":
                    if index == 0:
                        prepare(
                            actor=s.admin,
                            payout_id=payout.pk,
                            expected_state_version=payout.state_version,
                        )
                    else:
                        capture = payout.funding_attempt
                        request_refund(
                            order_id=capture.order_id,
                            attempt_id=capture.pk,
                            amount_eur_cents=capture.amount_eur_cents,
                            reason="admin",
                            requested_by_id=None,
                            idempotency_key="h4-race-refund",
                        )
                elif race == "hold":
                    if index == 0:
                        begin(actor=s.admin, payout_id=payout.pk, sequence=1)
                    else:
                        open_hold(
                            actor=s.outsider,
                            payout_id=payout.pk,
                            kind="manual",
                            reason_code="qa",
                            source_reference="qa-race",
                        )
                else:
                    confirm(
                        actor=s.admin,
                        payout_id=payout.pk,
                        sequence=1,
                        evidence_reference=receipt.public_reference,
                        confirmed=True,
                        settled=True,
                    )
                return "ok"
            except (ValidationError, RefundExceedsCapture):
                return "refused"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(worker, range(2)))
        if race in ("claim", "refund"):
            assert sorted(results) == ["ok", "refused"]
        elif race == "finalize":
            assert results == ["ok", "ok"]
            assert payout.attempts.get().manual_receipts.count() == 1
            assert LedgerEntry.objects.filter(payout=payout).count() == 2
        else:
            hold = payout.holds.get()
            assert hold.amount_exposure_eur_cents in (0, 6000)
            assert payout.attempts.get().status == (
                "prepared"
                if hold.amount_exposure_eur_cents == 0
                else "dispatch_committed"
            )
