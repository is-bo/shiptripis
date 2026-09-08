"""Account ownership, readiness and onboarding security.

Three things are being defended here:

* one Traveler can never reach another's connected account, and no
  connected-account id supplied from outside this server is ever accepted;
* `ready` means every gate H0 named, not `details_submitted`;
* the hosted return leg is a re-read, never an assertion of success, and its
  signed state is a capability for exactly that one re-read.
"""

from __future__ import annotations

import base64
import json
import time
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.core.signing import TimestampSigner
from django.db.utils import IntegrityError
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.finance.models import (
    FinanceHold,
    PayoutMethodVersion,
    PayoutProviderOperation,
    StripePayoutAccount,
    TravelerPayoutMethod,
)
from apps.finance import payout_accounts as accounts
from apps.finance.payout_accounts import (
    AccountCreationUnresolved,
    CountryUnsupported,
    ensure_account,
    evaluate_readiness,
    open_dashboard,
    read_onboarding_state,
    refresh_account,
    resolve_state_account,
    sign_onboarding_state,
    start_onboarding,
    stripe_setup_projection,
)
from apps.finance.payout_profiles import set_preference
from apps.finance.providers.base import ProviderCheckoutRejected, ProviderError, ProviderUnavailable
from apps.finance.providers.stripe_connect import ConnectedAccountSnapshot
from .factories import make_user

PLATFORM = "acct_1TESTplatform"

H2 = dict(
    PAYOUT_PROFILES_ENABLED=True,
    STRIPE_CONNECT_ENABLED=True,
    STRIPE_CONNECT_EXPECTED_MODE="test",
    STRIPE_CONNECT_PLATFORM_ACCOUNT_ID=PLATFORM,
    STRIPE_CONNECT_API_VERSION="2026-03-25.dahlia",
    STRIPE_CONNECT_ALLOWED_COUNTRIES=["FR"],
    STRIPE_CONNECT_WEBHOOK_SECRET="whsec_connect_test",
    STRIPE_CONNECT_ONBOARDING_RETURN_URL="https://api.shiptrip.test/payouts/stripe/return",
    STRIPE_CONNECT_ONBOARDING_REFRESH_URL="https://api.shiptrip.test/payouts/stripe/refresh",
    STRIPE_SECRET_KEY="sk_test_h2",
    PAYOUT_DATA_KEYRING=json.dumps({"k": base64.b64encode(b"e" * 32).decode()}),
    PAYOUT_DATA_ACTIVE_KEY_ID="k",
    PAYOUT_ACCOUNT_FINGERPRINT_KEY=base64.b64encode(b"f" * 32).decode(),
)


def snapshot(**overrides) -> ConnectedAccountSnapshot:
    """A brand-new connected account, before any onboarding."""

    fields = dict(
        account_id="acct_1TESTconnected",
        livemode=False,
        country="FR",
        default_currency="eur",
        details_submitted=False,
        payouts_enabled=False,
        charges_enabled=False,
        transfers_capability="pending",
        controller={
            "stripe_dashboard.type": "express",
            "requirement_collection": "stripe",
            "fees.payer": "application",
            "losses.payments": "application",
            "is_controller": True,
        },
        disabled_reason="requirements.past_due",
        requirement_codes=["external_account"],
        past_due_codes=[],
        pending_verification_codes=[],
        current_deadline=None,
        payout_schedule_interval="manual",
        eur_bank_account_id="",
        eur_bank_present=False,
        external_account_count=0,
        metadata={},
        request_id="req_1",
    )
    fields.update(overrides)
    return ConnectedAccountSnapshot(**fields)


def ready_snapshot(**overrides) -> ConnectedAccountSnapshot:
    """A fully onboarded account that every H0 gate accepts."""

    fields = dict(
        details_submitted=True,
        payouts_enabled=True,
        transfers_capability="active",
        disabled_reason="",
        requirement_codes=[],
        eur_bank_account_id="ba_1TESTbank",
        eur_bank_present=True,
        external_account_count=1,
    )
    fields.update(overrides)
    return snapshot(**fields)


class FakeGateway:
    """Scripted Connect adapter. Records what the domain asked it to do."""

    def __init__(self, *, create=None, retrieve=None, platform=PLATFORM, link_url="https://connect.stripe.test/setup/x"):
        self._create = create or snapshot()
        self._retrieve = retrieve
        self._platform = platform
        self.link_url = link_url
        self.calls = []

    def is_configured(self):
        return True

    def platform_identity(self):
        from apps.finance.providers.stripe_connect import (
            ConnectPlatformMismatch,
            PlatformIdentity,
        )

        self.calls.append(("platform_identity", None))
        if self._platform != PLATFORM:
            raise ConnectPlatformMismatch("wrong platform")
        return PlatformIdentity(
            account_id=self._platform, country="FR", default_currency="eur", mode="test"
        )

    def create_account(self, **kwargs):
        self.calls.append(("create_account", kwargs))
        if isinstance(self._create, Exception):
            raise self._create
        return self._create

    def retrieve_account(self, account_id):
        self.calls.append(("retrieve_account", account_id))
        result = self._retrieve if self._retrieve is not None else self._create
        if isinstance(result, Exception):
            raise result
        return result

    def find_account_by_metadata(self, **kwargs):
        self.calls.append(("find_account_by_metadata", kwargs))
        return getattr(self, "_found", None)

    def set_payout_schedule(self, *, account_id, interval="manual"):
        self.calls.append(("set_payout_schedule", (account_id, interval)))
        return self._create

    def create_account_link(self, *, account_id, refresh_url, return_url):
        from apps.finance.providers.stripe_connect import HostedLink

        self.calls.append(
            ("create_account_link", {"account": account_id, "return": return_url})
        )
        return HostedLink(url=self.link_url, expires_at=int(time.time()) + 300)

    def create_login_link(self, *, account_id):
        from apps.finance.providers.stripe_connect import HostedLink

        self.calls.append(("create_login_link", account_id))
        return HostedLink(url="https://connect.stripe.test/express/x")


@pytest.fixture
def h2():
    with override_settings(**H2):
        yield


@pytest.fixture
def traveler(db, h2):
    user = make_user("h2-traveler@example.com")
    set_preference(
        actor=user, currency="EUR", enabled=True, country="FR", expected_revision=0
    )
    return user


def method_of(user):
    return TravelerPayoutMethod.objects.get(traveler=user, method="stripe_connect")


def make_account(user, **overrides):
    fields = dict(
        traveler=user,
        platform_id=PLATFORM,
        provider_account_id="acct_1TESTconnected",
        provider_mode="test",
        declared_country="FR",
        verified_country="FR",
        default_currency="eur",
        creation_operation_key=f"fixture-{user.pk}-{overrides.get('provider_account_id', 'a')}",
        status="ready",
        transfers_status="active",
        payouts_enabled=True,
        details_submitted=True,
        eur_bank_present=True,
        external_account_id="ba_1TESTbank",
        payout_schedule_interval="manual",
        readiness_checked_at=timezone.now(),
        controller_summary={
            "stripe_dashboard.type": "express",
            "requirement_collection": "stripe",
            "fees.payer": "application",
            "losses.payments": "application",
            "is_controller": True,
        },
    )
    fields.update(overrides)
    return StripePayoutAccount.objects.create(**fields)


def bind_version(user, account):
    method = method_of(user)
    version = PayoutMethodVersion.objects.create(
        method=method,
        sequence=(method.versions.count() or 0) + 1,
        rail="stripe_transfer",
        currency="EUR",
        country="FR",
        stripe_account=account,
        policy_version="payout_profile_v1",
        consent_at=timezone.now(),
        created_by=user,
    )
    method.current_version = version
    method.save(update_fields=["current_version"])
    return method


# --------------------------------------------------------------------------
# Country eligibility
# --------------------------------------------------------------------------


class TestCountryEligibility:
    def test_algeria_is_never_an_eligible_stripe_eur_account_country(self, db, h2):
        user = make_user("h2-dz@example.com")
        with pytest.raises(CountryUnsupported):
            set_preference(
                actor=user,
                currency="EUR",
                enabled=True,
                country="DZ",
                expected_revision=0,
            )

    def test_the_dz_refusal_names_the_dzd_rail_instead_of_failing_generically(
        self, db, h2
    ):
        user = make_user("h2-dz-api@example.com")
        client = APIClient()
        client.force_authenticate(user)
        response = client.post(
            reverse("payout-methods"),
            {
                "currency": "EUR",
                "enabled": True,
                "country": "DZ",
                "expected_revision": 0,
                "consent_policy": "payout_profile_v1",
            },
            format="json",
        )
        assert response.status_code == 400
        assert response.json()["code"] == "payout_country_unsupported"
        assert response.json()["alternative"] == {"currency": "DZD", "rail": "manual"}

    def test_a_dz_traveler_still_has_the_dzd_setup_path(self, db, h2):
        user = make_user("h2-dz-alt@example.com")
        method = set_preference(
            actor=user, currency="DZD", enabled=True, expected_revision=0
        )
        assert method.enabled and method.currency == "DZD"

    def test_a_country_outside_the_deployment_allowlist_is_refused(self, db, h2):
        user = make_user("h2-de@example.com")
        with pytest.raises(CountryUnsupported):
            set_preference(
                actor=user,
                currency="EUR",
                enabled=True,
                country="DE",
                expected_revision=0,
            )

    def test_the_architecture_ceiling_bounds_the_deployment_list(self, db):
        with override_settings(**{**H2, "STRIPE_CONNECT_ALLOWED_COUNTRIES": ["US", "FR"]}):
            assert accounts.allowed_countries() == ("FR",)


# --------------------------------------------------------------------------
# Readiness
# --------------------------------------------------------------------------


class TestReadiness:
    def test_a_brand_new_account_is_setup_required(self, db, h2, traveler):
        account = make_account(
            traveler,
            status="setup_required",
            transfers_status="unrequested",
            payouts_enabled=False,
            details_submitted=False,
            eur_bank_present=False,
            external_account_id="",
        )
        verdict = evaluate_readiness(account)
        assert (verdict.status, verdict.reason) == (
            "setup_required",
            "transfers_not_requested",
        )

    def test_readiness_never_checked_is_setup_required_not_ready(self, db, h2, traveler):
        account = make_account(traveler, readiness_checked_at=None)
        assert evaluate_readiness(account).status == "setup_required"

    def test_details_submitted_alone_is_not_ready(self, db, h2, traveler):
        account = make_account(
            traveler,
            details_submitted=True,
            transfers_status="pending",
            payouts_enabled=False,
            eur_bank_present=False,
            external_account_id="",
        )
        verdict = evaluate_readiness(account)
        assert verdict.ready is False
        assert verdict.status == "pending_review"

    def test_outstanding_requirements_are_pending_or_setup_never_ready(
        self, db, h2, traveler
    ):
        account = make_account(traveler, requirement_codes=["individual.id_number"])
        verdict = evaluate_readiness(account)
        assert (verdict.status, verdict.reason) == ("setup_required", "requirements_due")

    def test_past_due_requirements_outrank_currently_due(self, db, h2, traveler):
        account = make_account(traveler, past_due_codes=["external_account"])
        assert evaluate_readiness(account).reason == "requirements_past_due"

    def test_a_rejected_account_needs_attention(self, db, h2, traveler):
        account = make_account(traveler, disabled_reason="rejected.fraud")
        verdict = evaluate_readiness(account)
        assert (verdict.status, verdict.reason) == ("needs_attention", "account_disabled")

    def test_an_account_under_review_is_pending_review(self, db, h2, traveler):
        account = make_account(traveler, disabled_reason="under_review")
        assert evaluate_readiness(account).status == "pending_review"

    def test_transfers_inactive_is_not_ready(self, db, h2, traveler):
        account = make_account(traveler, transfers_status="inactive")
        verdict = evaluate_readiness(account)
        assert verdict.ready is False
        assert verdict.reason == "transfers_inactive"

    def test_payouts_disabled_is_not_ready(self, db, h2, traveler):
        account = make_account(traveler, payouts_enabled=False)
        verdict = evaluate_readiness(account)
        assert verdict.ready is False
        assert verdict.reason == "payouts_not_enabled"

    def test_no_eur_bank_is_not_ready(self, db, h2, traveler):
        account = make_account(
            traveler, eur_bank_present=False, external_account_id=""
        )
        verdict = evaluate_readiness(account)
        assert (verdict.status, verdict.reason) == ("setup_required", "eur_bank_required")

    def test_a_non_manual_payout_schedule_is_not_ready(self, db, h2, traveler):
        account = make_account(traveler, payout_schedule_interval="daily")
        verdict = evaluate_readiness(account)
        assert (verdict.status, verdict.reason) == (
            "needs_attention",
            "payout_schedule_unexpected",
        )

    def test_an_unexpected_controller_needs_attention(self, db, h2, traveler):
        account = make_account(
            traveler,
            controller_summary={
                "stripe_dashboard.type": "express",
                "requirement_collection": "stripe",
                # The value Stripe assigns to a legacy `type=express` account.
                "fees.payer": "application_express",
                "losses.payments": "application",
            },
        )
        assert evaluate_readiness(account).reason == "controller_unexpected"

    def test_a_local_compliance_hold_outranks_a_happy_provider(self, db, h2, traveler):
        account = make_account(traveler)
        assert evaluate_readiness(account).ready is True
        FinanceHold.objects.create(
            account=account, kind="compliance", reason_code="review", source_reference="x"
        )
        verdict = evaluate_readiness(account)
        assert (verdict.status, verdict.reason) == ("needs_attention", "compliance_hold")

    def test_a_fully_valid_account_is_ready(self, db, h2, traveler):
        verdict = evaluate_readiness(make_account(traveler))
        assert (verdict.status, verdict.ready) == ("ready", True)

    def test_a_country_that_leaves_the_allowlist_makes_the_account_unavailable(
        self, db, h2, traveler
    ):
        account = make_account(traveler)
        with override_settings(**{**H2, "STRIPE_CONNECT_ALLOWED_COUNTRIES": []}):
            assert evaluate_readiness(account).reason == "country_unsupported"

    def test_a_replaced_account_is_unavailable(self, db, h2, traveler):
        account = make_account(traveler, active=False)
        assert evaluate_readiness(account).reason == "account_replaced"


class TestReadinessRefresh:
    def test_a_refresh_advances_the_generation_and_the_status(self, db, h2, traveler):
        account = make_account(
            traveler,
            status="setup_required",
            transfers_status="pending",
            payouts_enabled=False,
            details_submitted=False,
            eur_bank_present=False,
            external_account_id="",
            readiness_checked_at=timezone.now() - timedelta(minutes=10),
        )
        before = account.readiness_generation
        updated, applied = refresh_account(
            account, gateway=FakeGateway(retrieve=ready_snapshot())
        )
        assert applied is True
        assert updated.readiness_generation == before + 1
        assert updated.status == "ready"

    def test_a_stale_fetch_cannot_regress_a_newer_readiness(self, db, h2, traveler):
        account = make_account(
            traveler, readiness_checked_at=timezone.now() + timedelta(minutes=5)
        )
        # The stored observation is newer than the one this call was issued
        # with, so the older answer must not be written.
        updated, applied = refresh_account(
            account,
            gateway=FakeGateway(
                retrieve=ready_snapshot(
                    payouts_enabled=False, transfers_capability="inactive"
                )
            ),
        )
        assert applied is False
        assert updated.payouts_enabled is True
        assert updated.status == "ready"

    def test_a_deleted_external_account_removes_readiness(self, db, h2, traveler):
        account = make_account(
            traveler, readiness_checked_at=timezone.now() - timedelta(minutes=1)
        )
        updated, _ = refresh_account(
            account,
            gateway=FakeGateway(
                retrieve=ready_snapshot(
                    eur_bank_present=False,
                    eur_bank_account_id="",
                    external_account_count=0,
                )
            ),
        )
        assert updated.status == "setup_required"
        assert updated.status_reason == "eur_bank_required"

    def test_an_answer_for_another_account_is_refused(self, db, h2, traveler):
        account = make_account(
            traveler, readiness_checked_at=timezone.now() - timedelta(minutes=1)
        )
        with pytest.raises(ValidationError):
            refresh_account(
                account,
                gateway=FakeGateway(retrieve=ready_snapshot(account_id="acct_other")),
            )

    def test_a_live_answer_cannot_satisfy_a_test_account(self, db, h2, traveler):
        account = make_account(
            traveler, readiness_checked_at=timezone.now() - timedelta(minutes=1)
        )
        with pytest.raises(ValidationError):
            refresh_account(
                account, gateway=FakeGateway(retrieve=ready_snapshot(livemode=True))
            )

    def test_a_provider_outage_leaves_the_stored_readiness_and_currency_alone(
        self, db, h2, traveler
    ):
        account = make_account(traveler)
        with pytest.raises(ProviderUnavailable):
            refresh_account(
                account, gateway=FakeGateway(retrieve=ProviderUnavailable("down"))
            )
        account.refresh_from_db()
        assert account.status == "ready"
        assert method_of(traveler).currency == "EUR"

    def test_a_refresh_projects_its_verdict_onto_the_method(self, db, h2, traveler):
        account = make_account(
            traveler, readiness_checked_at=timezone.now() - timedelta(minutes=1)
        )
        bind_version(traveler, account)
        refresh_account(
            account,
            gateway=FakeGateway(retrieve=ready_snapshot(transfers_capability="pending")),
        )
        method = method_of(traveler)
        assert method.status == "pending_review"
        assert method.status_reason == "transfers_pending"


# --------------------------------------------------------------------------
# Ownership, mode and creation identity
# --------------------------------------------------------------------------


class TestOwnershipAndMode:
    def test_one_active_account_per_traveler_platform_and_mode(self, db, h2, traveler):
        make_account(traveler)
        with pytest.raises(IntegrityError):
            make_account(
                traveler,
                provider_account_id="acct_second",
                creation_operation_key="fixture-second",
            )

    def test_a_test_account_cannot_serve_a_live_expectation(self, db, h2, traveler):
        account = make_account(traveler)
        with override_settings(**{**H2, "STRIPE_CONNECT_EXPECTED_MODE": "live"}):
            assert evaluate_readiness(account).reason == "mode_mismatch"

    def test_an_account_under_another_platform_is_unavailable(self, db, h2, traveler):
        account = make_account(traveler, platform_id="acct_someone_else")
        assert evaluate_readiness(account).reason == "platform_mismatch"

    def test_creation_asserts_the_platform_before_creating_anything(
        self, db, h2, traveler
    ):
        gateway = FakeGateway(platform="acct_wrong")
        from apps.finance.providers.stripe_connect import ConnectPlatformMismatch

        with pytest.raises(ConnectPlatformMismatch):
            ensure_account(actor=traveler, gateway=gateway)
        assert StripePayoutAccount.objects.count() == 0
        assert [name for name, _ in gateway.calls] == ["platform_identity"]

    def test_creation_records_a_local_intent_before_the_provider_call(
        self, db, h2, traveler
    ):
        gateway = FakeGateway()
        ensure_account(actor=traveler, gateway=gateway)
        operation = PayoutProviderOperation.objects.get(kind="account_create")
        assert operation.method_id == method_of(traveler).pk
        assert operation.account_scope == PLATFORM
        assert operation.provider_mode == "test"
        assert operation.status == "accepted"
        assert operation.provider_object_id == "acct_1TESTconnected"
        assert operation.idempotency_key.startswith(f"acct_create:{PLATFORM}:test:")

    def test_a_second_call_reuses_the_account_and_creates_no_second_one(
        self, db, h2, traveler
    ):
        gateway = FakeGateway()
        first = ensure_account(actor=traveler, gateway=gateway)
        second = ensure_account(actor=traveler, gateway=gateway)
        assert first.pk == second.pk
        assert [name for name, _ in gateway.calls].count("create_account") == 1

    def test_a_timeout_marks_the_operation_unknown_rather_than_failed(
        self, db, h2, traveler
    ):
        gateway = FakeGateway(create=ProviderUnavailable("timeout"))
        with pytest.raises(ProviderUnavailable):
            ensure_account(actor=traveler, gateway=gateway)
        operation = PayoutProviderOperation.objects.get(kind="account_create")
        assert operation.status == "unknown"
        assert StripePayoutAccount.objects.count() == 0

    def test_a_cached_rejection_gets_a_new_durable_identity_after_repair(
        self, db, h2, traveler
    ):
        failed_keys = set()

        class CachingGateway(FakeGateway):
            activated = False

            def create_account(self, **kwargs):
                operation = PayoutProviderOperation.objects.get(
                    idempotency_key=kwargs["idempotency_key"]
                )
                assert operation.status == "committed"
                if not self.activated or kwargs["idempotency_key"] in failed_keys:
                    failed_keys.add(kwargs["idempotency_key"])
                    raise ProviderCheckoutRejected("Connect signup required")
                return super().create_account(**kwargs)

        gateway = CachingGateway()
        with pytest.raises(ProviderCheckoutRejected):
            ensure_account(actor=traveler, gateway=gateway)
        failed = PayoutProviderOperation.objects.get(kind="account_create")
        gateway.activated = True
        first = ensure_account(actor=traveler, gateway=gateway)
        second = ensure_account(actor=traveler, gateway=gateway)
        failed.refresh_from_db()
        accepted = PayoutProviderOperation.objects.get(status="accepted")
        assert failed.status == "failed" and failed.provider_object_id == ""
        assert accepted.idempotency_key != failed.idempotency_key
        assert accepted.provider_object_id == first.provider_account_id
        assert first.pk == second.pk
        assert StripePayoutAccount.objects.count() == 1
        assert PayoutProviderOperation.objects.count() == 2

    def test_an_unclassified_provider_response_keeps_the_creation_identity(
        self, db, h2, traveler
    ):
        gateway = FakeGateway(create=ProviderError("Malformed success response"))
        with pytest.raises(ProviderError):
            ensure_account(actor=traveler, gateway=gateway)
        operation = PayoutProviderOperation.objects.get(kind="account_create")
        assert operation.status == "unknown"
        recovering = FakeGateway()
        accounts.resume_account(actor=traveler, gateway=recovering)
        replay = [kw for name, kw in recovering.calls if name == "create_account"]
        assert replay[0]["idempotency_key"] == operation.idempotency_key
        assert PayoutProviderOperation.objects.count() == 1

    def test_an_unknown_creation_replays_the_same_key_inside_the_window(
        self, db, h2, traveler
    ):
        gateway = FakeGateway(create=ProviderUnavailable("timeout"))
        with pytest.raises(ProviderUnavailable):
            ensure_account(actor=traveler, gateway=gateway)
        key = PayoutProviderOperation.objects.get(kind="account_create").idempotency_key

        recovering = FakeGateway(create=snapshot())
        account = accounts.resume_account(actor=traveler, gateway=recovering)
        replay = [kw for name, kw in recovering.calls if name == "create_account"]
        assert replay and replay[0]["idempotency_key"] == key
        assert account.provider_account_id == "acct_1TESTconnected"
        assert StripePayoutAccount.objects.count() == 1

    def test_past_the_replay_window_an_unresolvable_creation_blocks(
        self, db, h2, traveler
    ):
        gateway = FakeGateway(create=ProviderUnavailable("timeout"))
        with pytest.raises(ProviderUnavailable):
            ensure_account(actor=traveler, gateway=gateway)
        operation = PayoutProviderOperation.objects.get(kind="account_create")
        PayoutProviderOperation.objects.filter(pk=operation.pk).update(
            first_request_at=timezone.now() - timedelta(days=2)
        )
        recovering = FakeGateway()
        recovering._found = None
        with pytest.raises(AccountCreationUnresolved):
            accounts.resume_account(actor=traveler, gateway=recovering)
        assert [name for name, _ in recovering.calls] == ["find_account_by_metadata"]
        assert StripePayoutAccount.objects.count() == 0

    def test_normal_onboarding_also_refuses_to_repost_an_expired_unknown_creation(
        self, db, h2, traveler
    ):
        with pytest.raises(ProviderUnavailable):
            start_onboarding(actor=traveler, gateway=FakeGateway(create=ProviderUnavailable("timeout")))
        operation = PayoutProviderOperation.objects.get(kind="account_create")
        PayoutProviderOperation.objects.filter(pk=operation.pk).update(
            first_request_at=timezone.now() - timedelta(days=2)
        )
        gateway = FakeGateway()
        with pytest.raises(AccountCreationUnresolved):
            start_onboarding(actor=traveler, gateway=gateway)
        assert "create_account" not in [name for name, _ in gateway.calls]
        operation.refresh_from_db()
        assert operation.status == "unknown"
        assert PayoutProviderOperation.objects.count() == 1

    def test_an_account_belonging_to_another_traveler_is_never_adopted(
        self, db, h2, traveler
    ):
        other = make_user("h2-other@example.com")
        make_account(other)
        gateway = FakeGateway()
        with pytest.raises(ValidationError):
            ensure_account(actor=traveler, gateway=gateway)

    def test_creation_provisions_the_manual_schedule_when_stripe_defaults_otherwise(
        self, db, h2, traveler
    ):
        gateway = FakeGateway(create=snapshot(payout_schedule_interval="daily"))
        ensure_account(actor=traveler, gateway=gateway)
        assert ("set_payout_schedule", ("acct_1TESTconnected", "manual")) in gateway.calls
        # And verified by re-reading, not by assuming the write took.
        assert [name for name, _ in gateway.calls].count("retrieve_account") >= 1

    def test_a_traveler_cannot_reach_another_travelers_account_through_the_api(
        self, db, h2, traveler
    ):
        account = make_account(traveler)
        bind_version(traveler, account)
        intruder = make_user("h2-intruder@example.com")
        set_preference(
            actor=intruder,
            currency="EUR",
            enabled=True,
            country="FR",
            expected_revision=0,
        )
        client = APIClient()
        client.force_authenticate(intruder)
        response = client.post(reverse("payout-stripe-refresh"), {}, format="json")
        assert response.status_code == 400
        assert response.json()["code"] == "payout_setup_invalid"

    def test_no_request_field_can_name_a_connected_account(self, db, h2, traveler):
        client = APIClient()
        client.force_authenticate(traveler)
        response = client.post(
            reverse("payout-stripe-onboarding"),
            {"country": "FR", "account": "acct_attacker_supplied"},
            format="json",
        )
        assert response.status_code == 400
        assert StripePayoutAccount.objects.count() == 0


# --------------------------------------------------------------------------
# Onboarding security
# --------------------------------------------------------------------------


class TestOnboardingSecurity:
    def test_onboarding_is_refused_without_authentication(self, db, h2):
        response = APIClient().post(reverse("payout-stripe-onboarding"), {}, format="json")
        assert response.status_code in (401, 403)

    def test_the_dashboard_link_is_refused_without_authentication(self, db, h2):
        response = APIClient().post(reverse("payout-stripe-dashboard"), {}, format="json")
        assert response.status_code in (401, 403)

    def test_a_link_is_returned_to_the_owner_and_never_persisted(
        self, db, h2, traveler, caplog
    ):
        gateway = FakeGateway()
        with caplog.at_level("INFO"):
            result = start_onboarding(actor=traveler, gateway=gateway)
        assert result["url"] == "https://connect.stripe.test/setup/x"
        assert "connect.stripe.test/setup" not in caplog.text
        from apps.admin_panel.models import AdminAuditLog

        rendered = json.dumps(
            list(AdminAuditLog.objects.values("action", "after")), default=str
        )
        assert "connect.stripe.test" not in rendered

    def test_the_signed_state_binds_user_method_account_and_mode(
        self, db, h2, traveler
    ):
        account = make_account(traveler)
        method = bind_version(traveler, account)
        payload = read_onboarding_state(
            sign_onboarding_state(user=traveler, method=method, account=account)
        )
        assert payload["u"] == traveler.pk
        assert payload["a"] == str(account.public_reference)
        assert payload["d"] == "test"

    def test_an_expired_state_is_refused(self, db, h2, traveler):
        account = make_account(traveler)
        method = bind_version(traveler, account)
        state = sign_onboarding_state(user=traveler, method=method, account=account)
        with override_settings(**{**H2, "STRIPE_CONNECT_STATE_TTL_SECONDS": 0}):
            time.sleep(1.1)
            with pytest.raises(ValidationError):
                read_onboarding_state(state)

    def test_an_authentic_but_malformed_state_is_refused_not_crashed(
        self, db, h2, traveler
    ):
        """Signed is not the same as well-formed.

        The fields go straight into a typed query, so a state carrying the
        right signature and the wrong types must be a refusal rather than a
        500 on an unauthenticated page.
        """

        signer = TimestampSigner(salt="shiptrip.payouts.stripe.onboarding.v1")
        for broken in (
            {"u": "not-an-int", "m": "m", "a": "a", "p": PLATFORM, "d": "test"},
            {"u": traveler.pk, "m": "", "a": "a", "p": PLATFORM, "d": "test"},
            {"u": traveler.pk, "m": "m", "a": 7, "p": PLATFORM, "d": "test"},
        ):
            with pytest.raises(ValidationError):
                read_onboarding_state(signer.sign(json.dumps(broken)))

    def test_a_state_naming_an_account_reference_that_is_not_a_uuid_is_refused(
        self, db, h2, traveler
    ):
        with pytest.raises(ValidationError):
            resolve_state_account(
                {
                    "u": traveler.pk,
                    "m": "m",
                    "a": "not-a-uuid",
                    "p": PLATFORM,
                    "d": "test",
                }
            )

    def test_a_forged_state_is_refused(self, db, h2, traveler):
        forged = TimestampSigner(salt="not-the-right-salt").sign(
            json.dumps({"u": traveler.pk, "m": "x", "a": "y", "p": PLATFORM, "d": "test"})
        )
        with pytest.raises(ValidationError):
            read_onboarding_state(forged)

    def test_a_state_naming_another_users_account_resolves_to_nothing(
        self, db, h2, traveler
    ):
        account = make_account(traveler)
        method = bind_version(traveler, account)
        payload = read_onboarding_state(
            sign_onboarding_state(user=traveler, method=method, account=account)
        )
        payload["u"] = make_user("h2-elsewhere@example.com").pk
        with pytest.raises(ValidationError):
            resolve_state_account(payload)

    def test_a_state_naming_another_account_resolves_to_nothing(self, db, h2, traveler):
        account = make_account(traveler)
        method = bind_version(traveler, account)
        payload = read_onboarding_state(
            sign_onboarding_state(user=traveler, method=method, account=account)
        )
        payload["a"] = "00000000-0000-0000-0000-000000000000"
        with pytest.raises(ValidationError):
            resolve_state_account(payload)

    def test_a_state_minted_in_another_mode_is_refused(self, db, h2, traveler):
        account = make_account(traveler)
        method = bind_version(traveler, account)
        payload = read_onboarding_state(
            sign_onboarding_state(user=traveler, method=method, account=account)
        )
        with override_settings(**{**H2, "STRIPE_CONNECT_EXPECTED_MODE": "live"}):
            with pytest.raises(ValidationError):
                resolve_state_account(payload)

    def test_the_return_urls_are_the_server_owned_configured_ones(
        self, db, h2, traveler
    ):
        gateway = FakeGateway()
        start_onboarding(actor=traveler, gateway=gateway)
        link = [kw for name, kw in gateway.calls if name == "create_account_link"][0]
        assert link["return"].startswith(
            "https://api.shiptrip.test/payouts/stripe/return?state="
        )

    def test_returning_does_not_mark_the_account_ready(self, db, h2, traveler, client):
        account = make_account(
            traveler,
            status="setup_required",
            transfers_status="pending",
            payouts_enabled=False,
            details_submitted=False,
            eur_bank_present=False,
            external_account_id="",
            readiness_checked_at=timezone.now() - timedelta(minutes=5),
        )
        method = bind_version(traveler, account)
        state = sign_onboarding_state(user=traveler, method=method, account=account)
        # Stripe still reports an unfinished account; the redirect claims nothing.
        with_fake = FakeGateway(retrieve=snapshot())
        original = accounts.get_connect_gateway
        try:
            import apps.finance.payout_account_api as api

            api.get_connect_gateway = lambda **kw: with_fake
            response = client.get(
                reverse("payout-stripe-onboarding-return"), {"state": state}
            )
        finally:
            import apps.finance.payout_account_api as api

            api.get_connect_gateway = original
        assert response.status_code == 200
        account.refresh_from_db()
        assert account.status != "ready"

    def test_an_invalid_return_state_renders_a_neutral_expired_page(self, db, h2, client):
        response = client.get(reverse("payout-stripe-onboarding-return"), {"state": "nonsense"})
        assert response.status_code == 400
        assert b"expired" in response.content.lower()

    def test_the_refresh_route_never_mints_a_new_link(self, db, h2, traveler, client):
        account = make_account(traveler)
        method = bind_version(traveler, account)
        state = sign_onboarding_state(user=traveler, method=method, account=account)
        response = client.get(reverse("payout-stripe-onboarding-refresh"), {"state": state})
        assert response.status_code == 200
        assert b"connect.stripe" not in response.content

    def test_resume_setup_mints_a_new_short_lived_link_when_authenticated(
        self, db, h2, traveler
    ):
        gateway = FakeGateway()
        first = start_onboarding(actor=traveler, gateway=gateway)
        gateway.link_url = "https://connect.stripe.test/setup/second"
        second = start_onboarding(actor=traveler, gateway=gateway)
        assert first["url"] != second["url"]
        assert second["expires_at"] is not None
        assert StripePayoutAccount.objects.count() == 1


class TestDashboardLink:
    def test_the_owner_gets_a_single_use_url_that_is_never_stored(
        self, db, h2, traveler, caplog
    ):
        account = make_account(traveler)
        bind_version(traveler, account)
        with caplog.at_level("INFO"):
            url = open_dashboard(actor=traveler, gateway=FakeGateway())
        assert url == "https://connect.stripe.test/express/x"
        assert "express/x" not in caplog.text
        from apps.admin_panel.models import AdminAuditLog

        assert "express/x" not in json.dumps(
            list(AdminAuditLog.objects.values("action", "after")), default=str
        )

    def test_an_unonboarded_account_is_sent_to_onboarding_not_the_dashboard(
        self, db, h2, traveler
    ):
        account = make_account(traveler, details_submitted=False)
        bind_version(traveler, account)
        with pytest.raises(ValidationError):
            open_dashboard(actor=traveler, gateway=FakeGateway())


# --------------------------------------------------------------------------
# Admin visibility
# --------------------------------------------------------------------------


class TestAdminVisibility:
    """The minimum useful Finance view, and nothing more than that."""

    STATIC = override_settings(
        STORAGES={
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {
                "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
            },
        }
    )

    def _console(self, django_client, role):
        from apps.accounts.models import User
        from apps.admin_panel.permissions import assign_admin_roles

        staff = User.objects.create_user(
            username=f"h2-{role}@example.com",
            email=f"h2-{role}@example.com",
            password="Sup3rStrongPass!",
            full_name=role,
            is_staff=True,
        )
        assign_admin_roles(staff, [role])
        django_client.force_login(staff)
        with self.STATIC:
            return django_client.get("/admin/finance/payout-accounts/")

    def test_finance_can_see_setup_state(self, db, h2, traveler, client):
        make_account(traveler, transfers_status="active")
        response = self._console(client, "finance")
        assert response.status_code == 200
        page = response.content.decode()
        assert "Payout accounts" in page
        assert "Ready" in page

    def test_support_cannot_see_payout_accounts(self, db, h2, traveler, client):
        make_account(traveler)
        assert self._console(client, "support").status_code == 403

    def test_ops_cannot_see_payout_accounts(self, db, h2, traveler, client):
        make_account(traveler)
        assert self._console(client, "ops").status_code == 403

    def test_the_page_masks_the_account_and_carries_no_bank_data(
        self, db, h2, traveler, client
    ):
        make_account(traveler)
        page = self._console(client, "finance").content.decode()
        assert "acct_1TESTconnected" not in page
        assert "acct_1TE" in page
        assert "ba_1TESTbank" not in page

    def test_the_page_reads_the_same_readiness_authority(self, db, h2, traveler, client):
        account = make_account(traveler, disabled_reason="rejected.fraud")
        page = self._console(client, "finance").content.decode()
        assert evaluate_readiness(account).reason.replace("_", " ") in page


# --------------------------------------------------------------------------
# Mobile contract
# --------------------------------------------------------------------------


class TestMobileContract:
    def test_the_projection_carries_states_and_codes_but_no_provider_payload(
        self, db, h2, traveler
    ):
        account = make_account(traveler, requirement_codes=["individual.id_number"])
        method = bind_version(traveler, account)
        projection = stripe_setup_projection(method)
        assert projection["status"] == "setup_required"
        assert projection["status_reason"] == "requirements_due"
        assert projection["supported_countries"] == ["FR"]
        assert projection["account_reference"].startswith("acct_1TE")
        assert "acct_1TESTconnected" not in json.dumps(projection, default=str)
        assert "individual.id_number" not in json.dumps(projection, default=str)
        assert projection["payouts_execution_enabled"] is False

    def test_the_projection_offers_the_actions_the_screen_needs(
        self, db, h2, traveler
    ):
        method = method_of(traveler)
        projection = stripe_setup_projection(method)
        assert projection["can_start_onboarding"] is True
        assert projection["can_manage"] is False
        account = make_account(traveler)
        method = bind_version(traveler, account)
        assert stripe_setup_projection(method)["can_manage"] is True

    def test_the_methods_list_exposes_the_same_single_authority(
        self, db, h2, traveler
    ):
        account = make_account(traveler, transfers_status="pending")
        bind_version(traveler, account)
        client = APIClient()
        client.force_authenticate(traveler)
        body = client.get(reverse("payout-methods")).json()
        setup = body["methods"][0]["stripe_setup"]
        assert setup["status"] == evaluate_readiness(account).status

    def test_with_connect_disabled_the_projection_reports_unavailable_setup(
        self, db, h2, traveler
    ):
        with override_settings(**{**H2, "STRIPE_CONNECT_ENABLED": False}):
            projection = stripe_setup_projection(method_of(traveler))
        assert projection["available"] is False
        assert projection["can_start_onboarding"] is False
