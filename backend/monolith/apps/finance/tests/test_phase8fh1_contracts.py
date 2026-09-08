"""Exercise dormant payout contracts without provider or storage access."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import override_settings
from django.utils import timezone

from apps.admin_panel.permissions import assign_admin_roles, has_all_admin_permissions
from apps.finance.models import (
    PaymentAttempt,
    PayoutMethodVersion,
    StripePayoutAccount,
)
from apps.finance.payout_domain import revise_amount_locked
from apps.finance.payout_operations import prepare_attempt, prepare_provider_operation
from apps.finance.payout_profiles import set_preference
from apps.finance.payout_snapshots import create_snapshot
from .factories import build_scenario
from .test_phase8fh1_foundations import KEYS


@pytest.fixture
def configured():
    with override_settings(**KEYS):
        yield


@pytest.fixture
def eur_snapshot(configured, db, request):
    with override_settings(PAYOUT_PROFILES_ENABLED=False):
        scenario = build_scenario(prefix="h1eur")
        scenario.accept(reward_eur_cents=6000)
    method = set_preference(
        actor=scenario.traveler,
        currency="EUR",
        enabled=True,
        country="FR",
        expected_revision=0,
    )
    account = StripePayoutAccount.objects.create(
        traveler=scenario.traveler,
        platform_id="acct_platform_fixture",
        provider_account_id="acct_connected_fixture",
        provider_mode=getattr(request, "param", "test"),
        declared_country="FR",
        verified_country="FR",
        creation_operation_key="fixture-account",
        status="ready",
        transfers_status="active",
        payouts_enabled=True,
        details_submitted=True,
        eur_bank_present=True,
    )
    version = PayoutMethodVersion.objects.create(
        method=method,
        sequence=2,
        rail="stripe_transfer",
        currency="EUR",
        country="FR",
        stripe_account=account,
        policy_version="payout_profile_v1",
        consent_at=timezone.now(),
        created_by=scenario.traveler,
    )
    method.current_version, method.status = version, "ready"
    method.save(update_fields=["current_version", "status"])
    order = scenario.balance_order()
    PaymentAttempt.objects.create(
        order=order,
        provider="stripe",
        provider_mode="test",
        amount_eur_cents=7500,
        payment_currency="EUR",
        provider_amount_minor=7500,
        idempotency_key="eur-source",
        provider_charge_id="ch_fixture",
        status="succeeded",
        succeeded_at=timezone.now(),
    )
    payout = create_snapshot(
        deal_id=scenario.deal.pk,
        traveler_id=scenario.traveler.pk,
        amount_eur_cents=6000,
        order=order,
    )
    payout.status, payout.eligible_at = "eligible", timezone.now()
    payout.eligibility_basis = "delivery_protection"
    payout.save(update_fields=["status", "eligible_at", "eligibility_basis"])
    assign_admin_roles(scenario.admin, ["finance"])
    return scenario, payout, account


@pytest.mark.django_db
def test_preference_toggle_preserves_readiness_and_funded_snapshot(eur_snapshot):
    scenario, payout, _ = eur_snapshot
    method = payout.method_version.method
    original_version = method.current_version_id
    disabled = set_preference(
        actor=scenario.traveler,
        currency="EUR",
        enabled=False,
        expected_revision=method.revision,
    )
    assert disabled.status == "ready"
    enabled = set_preference(
        actor=scenario.traveler,
        currency="EUR",
        enabled=True,
        country="FR",
        expected_revision=disabled.revision,
    )
    assert enabled.status == "ready" and enabled.current_version_id == original_version
    payout.refresh_from_db()
    assert payout.method_version_id == original_version


@pytest.mark.django_db
def test_prepared_intent_replay_scope_and_revision_invalidation(eur_snapshot):
    scenario, payout, account = eur_snapshot
    kwargs = dict(
        actor=scenario.admin,
        payout_id=payout.pk,
        expected_state_version=payout.state_version,
        idempotency_key="attempt-1",
    )
    attempt = prepare_attempt(**kwargs)
    assert prepare_attempt(**kwargs).pk == attempt.pk
    operation = prepare_provider_operation(
        actor=scenario.admin,
        attempt_id=attempt.pk,
        kind="transfer_create",
        account_scope=account.platform_id,
        idempotency_key="operation-1",
    )
    assert operation.status == "prepared" and not operation.provider_object_id
    assert (
        prepare_provider_operation(
            actor=scenario.admin,
            attempt_id=attempt.pk,
            kind="transfer_create",
            account_scope=account.platform_id,
            idempotency_key="operation-1",
        ).pk
        == operation.pk
    )
    with pytest.raises(ValidationError):
        prepare_provider_operation(
            actor=scenario.admin,
            attempt_id=attempt.pk,
            kind="bank_payout_create",
            account_scope=account.platform_id,
            idempotency_key="wrong-scope",
        )
    with transaction.atomic():
        revise_amount_locked(
            payout,
            amount=5000,
            settlement_reference="award-corrected",
            reason_code="settlement_award",
            actor=scenario.admin,
        )
    attempt.refresh_from_db()
    assert attempt.status == "cancelled"
    with pytest.raises(ValidationError):
        prepare_attempt(**kwargs)
    assert payout.funded_amount_eur_cents == 6000
    assert payout.amount_revisions.get().actor_id == scenario.admin.pk


@pytest.mark.django_db
@pytest.mark.parametrize("eur_snapshot", ["live"], indirect=True)
def test_mode_mismatch_refuses_preparation(eur_snapshot):
    scenario, payout, _ = eur_snapshot
    assert payout.block_reason == "provider_mode_mismatch"
    with pytest.raises(ValidationError):
        prepare_attempt(
            actor=scenario.admin,
            payout_id=payout.pk,
            expected_state_version=payout.state_version,
            idempotency_key="wrong-mode",
        )


@pytest.mark.django_db
def test_unresolved_commit_refuses_new_work(eur_snapshot):
    scenario, payout, _ = eur_snapshot
    attempt = prepare_attempt(
        actor=scenario.admin,
        payout_id=payout.pk,
        expected_state_version=payout.state_version,
        idempotency_key="valid-mode",
    )
    attempt.status = "unknown"
    attempt.save(update_fields=["status"])
    with pytest.raises(ValidationError):
        prepare_attempt(
            actor=scenario.admin,
            payout_id=payout.pk,
            expected_state_version=payout.state_version,
            idempotency_key="duplicate-exposure",
        )
    with pytest.raises(ValidationError), transaction.atomic():
        revise_amount_locked(
            payout,
            amount=0,
            settlement_reference="unsafe-cancel",
            reason_code="cancellation",
        )
    assert not payout.amount_revisions.exists()


@pytest.mark.django_db
def test_account_identity_and_active_mode_uniqueness(eur_snapshot):
    scenario, _, account = eur_snapshot
    values = dict(
        traveler=scenario.traveler,
        platform_id=account.platform_id,
        provider_account_id="acct_other",
        declared_country="FR",
        creation_operation_key="other-account",
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        StripePayoutAccount.objects.create(**values, provider_mode="test")
    # Different modes are separate domains, including active-account uniqueness.
    assert StripePayoutAccount.objects.create(**values, provider_mode="live").pk
    if connection.vendor == "postgresql":
        with pytest.raises(DatabaseError), transaction.atomic():
            StripePayoutAccount.objects.filter(pk=account.pk).update(
                provider_mode="live"
            )


@pytest.mark.django_db
def test_raw_snapshot_and_revision_mutation_rejected(eur_snapshot):
    _, payout, _ = eur_snapshot
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL raw-write authority")
    for column, value in (
        ("funded_amount_eur_cents", 123),
        ("amount_eur_cents", 123),
        ("provider_mode", "live"),
    ):
        with (
            pytest.raises(DatabaseError),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                f"UPDATE finance_payout SET {column} = %s WHERE id = %s",
                [value, payout.pk],
            )
    with transaction.atomic():
        revision = revise_amount_locked(
            payout,
            amount=0,
            settlement_reference="zero-outcome",
            reason_code="cancellation",
        )
    with (
        pytest.raises(DatabaseError),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "DELETE FROM finance_payout_amount_revision WHERE id = %s", [revision.pk]
        )
    payout.refresh_from_db()
    assert payout.status == "cancelled" and payout.amount_eur_cents == 0
    assert payout.funded_amount_eur_cents == 6000


@pytest.mark.django_db
def test_ban_revokes_cached_sensitive_and_owner_access(eur_snapshot):
    scenario, _, _ = eur_snapshot
    assert has_all_admin_permissions(scenario.admin, "view_payout_sensitive")
    type(scenario.admin).objects.filter(pk=scenario.admin.pk).update(is_banned=True)
    assert not has_all_admin_permissions(scenario.admin, "view_payout_sensitive")
    type(scenario.traveler).objects.filter(pk=scenario.traveler.pk).update(
        is_banned=True
    )
    with pytest.raises(PermissionDenied):
        set_preference(
            actor=scenario.traveler, currency="EUR", enabled=False, expected_revision=1
        )


def test_launcher_does_not_forward_financial_keys_to_go(monkeypatch):
    path = Path(__file__).resolve().parents[4] / "railway" / "start.py"
    spec = importlib.util.spec_from_file_location("h1_launcher_fixture", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    keys = {
        "PAYOUT_DATA_KEYRING": "synthetic",
        "PAYOUT_ACCOUNT_FINGERPRINT_KEY": "synthetic",
        "PAYOUT_S3_SECRET_KEY": "synthetic",
        "NORMAL_SETTING": "retained",
    }
    # Popen is replaced, so importing/exercising spawn starts no service.
    with patch.object(module.subprocess, "Popen") as popen:
        for name in ("chat", "notification", "kyc", "email", "gateway"):
            module.spawn(name, ["never-executed"], env=keys)
            assert popen.call_args.kwargs["env"] == {"NORMAL_SETTING": "retained"}
        module.spawn("web", ["never-executed"], env=keys)
        assert popen.call_args.kwargs["env"] == keys
