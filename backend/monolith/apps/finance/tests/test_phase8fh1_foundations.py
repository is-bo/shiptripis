import base64
import json
import uuid

import pytest
from django.core.exceptions import (
    ValidationError,
    ImproperlyConfigured,
    PermissionDenied,
)
from django.db import transaction
from django.test import override_settings
from django.utils import timezone

from apps.accounts.models import User
from apps.admin_panel.permissions import assign_admin_roles, has_all_admin_permissions
from apps.finance.sensitive_data import (
    encrypt,
    decrypt,
    account_fingerprint,
    key_configuration,
)
from apps.finance.payout_identity import compare_names
from apps.finance.payout_profiles import set_preference, submit_dzd_profile
from apps.finance.payout_profile_api import method_projection
from apps.finance.payout_domain import revise_amount_locked, validate_transition
from apps.finance.payout_snapshots import create_snapshot
from apps.finance.models import PaymentAttempt, Payout, PayoutMethodVersion
from apps.finance.money import convert_eur_cents
from .factories import build_scenario

KEYS = dict(
    PAYOUT_PROFILES_ENABLED=True,
    PAYOUT_DATA_KEYRING=json.dumps({"test-key": base64.b64encode(b"e" * 32).decode()}),
    PAYOUT_DATA_ACTIVE_KEY_ID="test-key",
    PAYOUT_ACCOUNT_FINGERPRINT_KEY=base64.b64encode(b"f" * 32).decode(),
    STRIPE_CONNECT_ALLOWED_COUNTRIES=["FR"],
)


@pytest.fixture
def configured():
    with override_settings(**KEYS):
        yield


def test_crypto_authenticates_aad_and_uses_random_nonce(configured):
    record = uuid.uuid4()
    context = dict(model="DzdPayoutProfileRevision", record=record, field="ccp_number")
    encrypted = encrypt("00123456789", **context)
    assert "00123456789" not in encrypted
    assert encrypted != encrypt("00123456789", **context)
    assert decrypt(encrypted, **context) == "00123456789"
    with pytest.raises(ValidationError):
        decrypt(encrypted, **{**context, "field": "rip"})
    with override_settings(
        PAYOUT_DATA_KEYRING=json.dumps(
            {"test-key": base64.b64encode(b"x" * 32).decode()}
        )
    ):
        with pytest.raises(ValidationError):
            decrypt(encrypted, **context)


def test_fingerprint_normalization_and_independent_key(configured):
    assert account_fingerprint("0012 34", "01", "0" * 20) == account_fingerprint(
        "٠٠١٢٣٤", "٠١", "0" * 20
    )
    with override_settings(
        PAYOUT_ACCOUNT_FINGERPRINT_KEY=base64.b64encode(b"e" * 32).decode()
    ):
        with pytest.raises(ImproperlyConfigured):
            key_configuration()


@pytest.mark.parametrize(
    "given,family,expected_given,expected_family,result",
    [
        ("Émile", "Du-Pont", "Emile", "Du Pont", "consistent"),
        ("مُحَمَّد", "علي", "محمد", "علي", "consistent"),
        ("Anne Marie", "Durand", "Anne", "Marie Durand", "review_alias_spelling"),
        ("Alice", "Smith", "Karim", "Benali", "mismatch"),
        ("Alice", "Smith", None, None, "insufficient_attestation"),
    ],
)
def test_name_classification(given, family, expected_given, expected_family, result):
    assert (
        compare_names(
            given,
            family,
            attested_given=expected_given,
            attested_family=expected_family,
        )["classification"]
        == result
    )


@pytest.mark.parametrize(
    "amount,rate,result",
    [
        (6000, 260000000, 15600),
        (1, 260000001, 3),
        (123, 260123456, 320),
        (10**12, 260000000, 2600000000000),
    ],
)
def test_integer_fx(amount, rate, result):
    assert convert_eur_cents(amount, to_currency="DZD", rate_micros=rate) == result


@pytest.mark.parametrize("bad", [True, 1.5])
def test_no_float_bool(bad):
    with pytest.raises(ValueError):
        convert_eur_cents(bad, to_currency="DZD", rate_micros=260000000)


@pytest.mark.django_db
def test_profile_version_and_safe_projection(configured):
    user = User.objects.create_user(
        username="profile", email="profile@example.invalid", role="traveler"
    )
    method = set_preference(
        actor=user, currency="DZD", enabled=True, expected_revision=0
    )
    old = method.current_version_id
    method = submit_dzd_profile(
        actor=user,
        expected_revision=1,
        first_name="PrivateGiven",
        last_name="PrivateFamily",
        ccp_number="00123456789",
        ccp_key="01",
        rip="00123456789012345678",
        proof_reference=_profile_proof(user).public_reference,
    )
    profile = method.current_version.dzd_profile_revision
    assert old != method.current_version_id
    text = json.dumps(method_projection(method), default=str) + str(profile)
    for secret in (
        "PrivateGiven",
        "PrivateFamily",
        "00123456789",
        "00123456789012345678",
        profile.account_fingerprint,
    ):
        assert secret not in text
    with pytest.raises(ValidationError):
        PayoutMethodVersion.objects.filter(pk=old).update(currency="EUR")
    with pytest.raises(ValidationError):
        set_preference(actor=user, currency="DZD", enabled=False, expected_revision=0)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "currencies,provider,expected",
    [
        (["DZD"], "chargily", "DZD"),
        (["DZD"], "stripe", "DZD"),
        (["EUR"], "stripe", "EUR"),
        (["EUR"], "chargily", "EUR"),
        (["EUR", "DZD"], "stripe", "EUR"),
        (["EUR", "DZD"], "chargily", "DZD"),
    ],
)
def test_routing_snapshot(configured, currencies, provider, expected):
    # Acceptance is built before enabling profile preflight.
    with override_settings(PAYOUT_PROFILES_ENABLED=False):
        scenario = build_scenario(prefix="h1route")
        scenario.accept(reward_eur_cents=6000)
    for currency in currencies:
        set_preference(
            actor=scenario.traveler,
            currency=currency,
            enabled=True,
            expected_revision=0,
            country="FR" if currency == "EUR" else "",
        )
    order = scenario.balance_order()
    source = PaymentAttempt.objects.create(
        order=order,
        provider=provider,
        provider_mode="test",
        amount_eur_cents=7500,
        payment_currency="DZD" if provider == "chargily" else "EUR",
        provider_amount_minor=19500 if provider == "chargily" else 7500,
        fx_rate_micros=260000000 if provider == "chargily" else None,
        fx_settings_version=scenario.policy.settings_version
        if provider == "chargily"
        else None,
        fx_snapshot_at=timezone.now() if provider == "chargily" else None,
        fx_source="business_settings" if provider == "chargily" else "",
        idempotency_key="h1-source",
        status="succeeded",
        succeeded_at=timezone.now(),
    )
    payout = create_snapshot(
        deal_id=scenario.deal.pk,
        traveler_id=scenario.traveler.pk,
        amount_eur_cents=6000,
        order=order,
    )
    assert payout.payout_currency == expected
    assert payout.funding_attempt_id == source.pk
    assert payout.provider_mode == "test"
    if expected == "EUR":
        assert payout.fx_rate_micros is None
        if provider == "chargily":
            assert payout.block_reason == "funding_route_unavailable"
    elif provider == "chargily":
        assert payout.payout_amount_minor == 15600
    method = payout.method_version.method
    set_preference(
        actor=scenario.traveler,
        currency=expected,
        enabled=False,
        expected_revision=method.revision,
    )
    payout.refresh_from_db()
    assert payout.method_version_id == method.current_version_id
    from unittest.mock import patch

    original_fx = payout.fx_rate_micros
    with patch(
        "apps.finance.payout_snapshots.phase3_policy",
        side_effect=AssertionError("Existing snapshot must not read today's FX"),
    ):
        assert (
            create_snapshot(
                deal_id=scenario.deal.pk,
                traveler_id=scenario.traveler.pk,
                amount_eur_cents=6000,
            ).pk
            == payout.pk
        )
    payout.refresh_from_db()
    assert payout.fx_rate_micros == original_fx
    with transaction.atomic():
        revise_amount_locked(
            payout,
            amount=0,
            settlement_reference="cancel-h1",
            reason_code="cancellation",
        )
    payout.refresh_from_db()
    assert payout.amount_eur_cents == 0 and payout.funded_amount_eur_cents == 6000
    assert payout.status == Payout.Status.CANCELLED
    assert payout.amount_revisions.count() == 1


@pytest.mark.django_db
def test_permission_matrix_and_immediate_downgrade(configured):
    user = User.objects.create_user(
        username="finance-review", email="finance-review@example.invalid", is_staff=True
    )
    assign_admin_roles(user, ["finance"])
    assert has_all_admin_permissions(
        user, "view_payout_sensitive", "review_payout_profiles"
    )
    assert not has_all_admin_permissions(user, "view_kyc")
    assign_admin_roles(user, ["trust_verification"])
    assert has_all_admin_permissions(user, "attest_payout_identity")
    assert not has_all_admin_permissions(user, "view_payouts", "attest_payout_identity")
    for role in ("support", "ops"):
        assign_admin_roles(user, [role])
        assert not has_all_admin_permissions(user, "view_payout_sensitive")
    assign_admin_roles(user, ["super_admin"])
    assert has_all_admin_permissions(
        user, "view_payout_sensitive", "attest_payout_identity"
    )


def test_state_contract():
    validate_transition("processing", "sent")
    with pytest.raises(ValidationError):
        validate_transition("not_eligible", "paid")


@pytest.mark.django_db
def test_disabled_profiles_need_no_keys():
    with override_settings(PAYOUT_PROFILES_ENABLED=False, PAYOUT_DATA_KEYRING="{}"):
        user = User.objects.create_user(
            username="disabled", email="disabled@example.invalid"
        )
        with pytest.raises(PermissionDenied):
            set_preference(
                actor=user, currency="DZD", enabled=True, expected_revision=0
            )


@pytest.mark.django_db
def test_attestation_is_explicit_scoped_and_encrypted(configured):
    from apps.finance.payout_profiles import assign_identity_review, attest_identity
    from apps.kyc.models import KycSubmission
    from apps.admin_panel.models import AdminAuditLog

    traveler = User.objects.create_user(
        username="identity-holder", full_name="EditableProfile"
    )
    finance = User.objects.create_user(
        username="identity-finance",
        email="identity-finance@example.invalid",
        is_staff=True,
    )
    trust = User.objects.create_user(
        username="identity-trust", email="identity-trust@example.invalid", is_staff=True
    )
    assign_admin_roles(finance, ["finance"])
    assign_admin_roles(trust, ["trust_verification"])
    KycSubmission.objects.create(
        user=traveler,
        document_type="passport",
        idempotency_key="h1-attestation",
        front_image_key="synthetic/kyc",
        status="approved",
    )
    assignment = assign_identity_review(
        actor=finance, traveler_id=traveler.pk, reviewer_id=trust.pk
    )
    with pytest.raises(PermissionDenied):
        attest_identity(
            actor=finance,
            assignment_reference=assignment.public_reference,
            given_name="VerifiedGiven",
            family_name="VerifiedFamily",
        )
    record = attest_identity(
        actor=trust,
        assignment_reference=assignment.public_reference,
        given_name="VerifiedGiven",
        family_name="VerifiedFamily",
    )
    assert "VerifiedGiven" not in record.given_name_encrypted
    assert (
        decrypt(
            record.given_name_encrypted,
            model="PayoutIdentityAttestation",
            record=record.public_reference,
            field="given_name",
        )
        == "VerifiedGiven"
    )
    assert "VerifiedGiven" not in str(list(AdminAuditLog.objects.values()))
    assert "EditableProfile" not in str(record)


@pytest.mark.django_db
def test_profile_endpoints_disabled_and_owner_only(configured):
    from rest_framework.test import APIClient

    owner = User.objects.create_user(
        username="api-owner", email="api-owner@example.invalid", role="traveler"
    )
    other = User.objects.create_user(
        username="api-other", email="api-other@example.invalid", role="traveler"
    )
    set_preference(actor=owner, currency="DZD", enabled=True, expected_revision=0)
    client = APIClient()
    client.force_authenticate(other)
    response = client.get("/api/payouts/methods")
    assert response.status_code == 200
    assert response.data["methods"] == []
    with override_settings(PAYOUT_PROFILES_ENABLED=False):
        assert client.get("/api/payouts/methods").status_code == 404
    assert (
        client.post(
            "/api/payouts/methods",
            {
                "currency": "DZD",
                "enabled": True,
                "expected_revision": 0,
                "consent_policy": "payout_profile_v1",
                "traveler_id": owner.pk,
            },
            format="json",
        ).status_code
        == 400
    )


@pytest.mark.django_db
def test_postgres_raw_history_update_refused(configured):
    from django.db import connection, DatabaseError

    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL trigger contract")
    user = User.objects.create_user(
        username="raw-history", email="raw-history@example.invalid", role="traveler"
    )
    method = set_preference(
        actor=user, currency="DZD", enabled=True, expected_revision=0
    )
    with (
        pytest.raises(DatabaseError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE finance_payout_method_version SET country = 'XX' WHERE id = %s",
            [method.current_version_id],
        )


@pytest.fixture
def funded_snapshot(configured, db):
    from .test_concurrency import _seed_settings

    _seed_settings()
    from copy import deepcopy
    from apps.core.models import BusinessSettingsVersion
    from apps.core.business_settings import get_active_business_settings
    from .factories import pay_order_with_mock
    from django.test import Client

    with override_settings(PAYOUT_PROFILES_ENABLED=False):
        scenario = build_scenario(prefix="h1funded")
        scenario.accept(reward_eur_cents=6000)
        active = get_active_business_settings()
        policy = deepcopy(active.policy)
        policy["payments"]["providers"]["mock_enabled"] = True
        BusinessSettingsVersion.objects.filter(pk=active.pk).update(policy=policy)
    set_preference(
        actor=scenario.traveler, currency="DZD", enabled=True, expected_revision=0
    )
    # Unit-test adapter only; no external provider I/O.
    pay_order_with_mock(Client(), scenario.balance_order(), actor_id=scenario.sender.pk)
    payout = Payout.objects.get(deal=scenario.deal)
    return scenario, payout


@pytest.mark.django_db
def test_missing_fx_preserves_captured_obligation(funded_snapshot):
    from apps.finance.services import complete_manual_payout, PayoutNotReleasable

    scenario, payout = funded_snapshot
    assert payout.snapshot_version == 1
    assert payout.block_reason == "fx_snapshot_missing"
    assert payout.amount_eur_cents == 6000
    assert payout.payout_amount_minor is None
    assert payout.funding_attempt.status == "succeeded"
    with pytest.raises(PayoutNotReleasable):
        complete_manual_payout(
            payout_id=payout.pk,
            admin_actor_id=scenario.admin.pk,
            payout_currency="DZD",
            payout_amount_minor=15600,
            reference="not-a-receipt",
        )


@pytest.mark.django_db
def test_holds_clear_independently(funded_snapshot):
    from apps.finance.payout_domain import open_hold, clear_hold, active_holds

    scenario, payout = funded_snapshot
    assign_admin_roles(scenario.admin, ["finance"])
    first = open_hold(
        actor=scenario.admin,
        payout_id=payout.pk,
        kind="manual",
        reason_code="review",
        source_reference="review-1",
    )
    second = open_hold(
        actor=scenario.admin,
        payout_id=payout.pk,
        kind="treasury",
        reason_code="liquidity",
        source_reference="review-2",
    )
    clear_hold(actor=scenario.admin, hold_id=first.pk, expected_generation=1)
    assert list(active_holds(payout).values_list("pk", flat=True)) == [second.pk]


@pytest.mark.django_db
def test_failed_and_unapplied_attempts_not_funding_authority(funded_snapshot):
    from apps.finance.payout_snapshots import funding_attempt

    scenario, payout = funded_snapshot
    order = scenario.balance_order()
    authoritative = payout.funding_attempt
    for status, unapplied in (("failed", False), ("succeeded", True)):
        PaymentAttempt.objects.create(
            order=order,
            provider="stripe",
            amount_eur_cents=7500,
            payment_currency="EUR",
            provider_amount_minor=7500,
            idempotency_key=f"h1-ignored-{status}",
            status=status,
            is_unapplied=unapplied,
            succeeded_at=timezone.now(),
        )
    assert funding_attempt(order).pk == authoritative.pk


@pytest.mark.django_db
def test_allocation_bounded_idempotent_and_mode_checked(funded_snapshot):
    from apps.finance.payout_domain import allocate_source

    scenario, payout = funded_snapshot
    source = payout.funding_attempt
    # Mock fixture records test mode at checkout; no credentials are inferred.
    assert payout.provider_mode == "test"
    first = allocate_source(
        payout_id=payout.pk,
        source_attempt_id=source.pk,
        amount_eur_cents=6000,
        allocation_key="h1-allocation",
    )
    assert (
        allocate_source(
            payout_id=payout.pk,
            source_attempt_id=source.pk,
            amount_eur_cents=6000,
            allocation_key="h1-allocation",
        ).pk
        == first.pk
    )
    with pytest.raises(ValidationError):
        allocate_source(
            payout_id=payout.pk,
            source_attempt_id=source.pk,
            amount_eur_cents=1,
            allocation_key="h1-overallocation",
        )
    PaymentAttempt.objects.filter(pk=source.pk).update(provider_mode="live")
    with pytest.raises(ValidationError):
        allocate_source(
            payout_id=payout.pk,
            source_attempt_id=source.pk,
            amount_eur_cents=1,
            allocation_key="h1-wrong-mode",
        )


@pytest.mark.django_db(transaction=True)
def test_postgres_allocation_race(funded_snapshot):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import connection, connections
    from apps.finance.payout_domain import allocate_source

    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL reservation race")
    _, payout = funded_snapshot
    barrier = Barrier(2)

    def reserve(index):
        connections.close_all()
        barrier.wait(timeout=10)
        try:
            allocate_source(
                payout_id=payout.pk,
                source_attempt_id=payout.funding_attempt_id,
                amount_eur_cents=4000,
                allocation_key=f"race-{index}",
            )
            return "reserved"
        except ValidationError:
            return "refused"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(reserve, range(2))) == ["refused", "reserved"]
    assert payout.funding_allocations.count() == 1


@pytest.mark.django_db
def test_instruction_amendment_keeps_original_snapshot(funded_snapshot):
    from apps.finance.payout_domain import confirm_instruction, amend_instruction
    from apps.finance.models import TravelerPayoutMethod

    scenario, payout = funded_snapshot
    assign_admin_roles(scenario.admin, ["finance"])
    initial = payout.method_version_id
    method = submit_dzd_profile(
        actor=scenario.traveler,
        expected_revision=1,
        first_name="Example",
        last_name="Holder",
        ccp_number="00123456789",
        ccp_key="01",
        rip="00123456789012345678",
        proof_reference=_profile_proof(scenario.traveler).public_reference,
    )
    # H4 will own evidence-backed review. This domain test supplies its ready
    # projection without exposing an approval endpoint in H1.
    TravelerPayoutMethod.objects.filter(pk=method.pk).update(status="ready")
    confirmation = confirm_instruction(
        actor=scenario.traveler,
        payout_id=payout.pk,
        new_version_id=method.current_version_id,
        expected_state_version=payout.state_version,
    )
    amend_instruction(
        actor=scenario.admin,
        traveler=scenario.traveler,
        payout_id=payout.pk,
        new_version_id=method.current_version_id,
        expected_state_version=payout.state_version,
        reason_code="destination_corrected",
        confirmed_at=confirmation.confirmed_at,
        confirmation_reference=confirmation.public_reference,
    )
    payout.refresh_from_db()
    assert payout.method_version_id == initial
    assert payout.active_instruction_version_id == method.current_version_id
    assert payout.payout_currency == "DZD" and payout.fx_rate_micros is None
    assert payout.instruction_amendments.count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("award", [3000, 0])
def test_settlement_revision_keeps_ledger_actor_and_protection(funded_snapshot, award):
    from datetime import timedelta
    from apps.core.financial_locks import lock_deal_lifecycle
    from apps.finance.settlement import (
        read_deal_money,
        plan_settlement,
        apply_settlement,
    )

    scenario, payout = funded_snapshot
    deal = scenario.deal
    deal.pickup_confirmed_at = timezone.now() - timedelta(hours=1)
    deal.delivery_code_available_at = timezone.now() - timedelta(minutes=30)
    deal.delivery_code_released_at = deal.delivery_code_available_at
    deal.delivery_confirmed_at = timezone.now()
    deal.protection_ends_at = timezone.now() + timedelta(hours=48)
    deal.save(
        update_fields=[
            "pickup_confirmed_at",
            "delivery_code_available_at",
            "delivery_code_released_at",
            "delivery_confirmed_at",
            "protection_ends_at",
        ]
    )
    with transaction.atomic():
        aggregate = lock_deal_lifecycle(deal.pk)
        money = read_deal_money(aggregate.deal)
        plan = plan_settlement(
            money=money,
            sender_refund_eur_cents=money.collected_eur_cents
            if award == 0
            else money.collected_eur_cents // 2,
            traveler_payout_eur_cents=award,
        )
        result = apply_settlement(
            plan=plan,
            settlement_key="h1-settlement",
            refund_reason="dispute_resolution",
            note="Synthetic settlement",
            actor_id=scenario.admin.pk,
        )
    payout.refresh_from_db()
    revision = payout.amount_revisions.get()
    assert revision.ledger_transaction_id == result.ledger_transaction_id
    assert revision.ledger_transaction_id is not None
    assert revision.actor_id == scenario.admin.pk
    assert payout.funded_amount_eur_cents == 6000 and payout.amount_eur_cents == award
    assert payout.status == ("cancelled" if award == 0 else "not_eligible")


def _profile_proof(owner):
    from apps.finance.models import PayoutEvidence

    return PayoutEvidence.objects.create(
        owner=owner,
        purpose="account_document",
        upload_state="complete",
        object_key=f"qa/{uuid.uuid4()}",
        digest="0" * 64,
        mime_type="image/png",
        size_bytes=1,
    )
