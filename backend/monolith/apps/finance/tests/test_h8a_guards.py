"""Fast, network-free deployment and transport guard regressions."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.test import RequestFactory, override_settings

from config.settings.payments import (
    PaymentConfigurationError,
    validate_payment_configuration,
)
from apps.admin_panel.finance_dashboard import default_mode, scope_params
from apps.finance.mode_safety import event_mode_allowed, require_object_mode
from apps.finance.providers import (
    ChargilyGateway,
    StripeGateway,
    ProviderConfigurationInvalid,
)
from apps.finance.providers.stripe_connect import StripeConnectGateway
from apps.finance.control_plane.attention import attention_summary


def config(**changes):
    return SimpleNamespace(
        **{
            "PAYMENTS_ENVIRONMENT": "test",
            "STRIPE_SECRET_KEY": "sk_test_synthetic",
            "STRIPE_API_BASE": "https://api.stripe.com",
            "STRIPE_WEBHOOK_SECRET": "whsec_platform",
            "CHARGILY_SECRET_KEY": "test_sk_synthetic",
            "CHARGILY_WEBHOOK_SECRET": "",
            "CHARGILY_API_BASE": "https://pay.chargily.net/test/api/v2",
            "STRIPE_CONNECT_ENABLED": True,
            "STRIPE_CONNECT_EXPECTED_MODE": "test",
            "STRIPE_CONNECT_WEBHOOK_SECRET": "whsec_connect",
            "TRANSACTIONAL_EMAIL_ENABLED": False,
            "PAYOUT_DZD_EXECUTION_ENABLED": False,
            "PAYOUT_PROFILES_ENABLED": True,
            "PAYMENTS_PUBLIC_BASE_URL": "https://shiptrip-production-f7f7.up.railway.app",
            "FRONTEND_BASE_URL": "https://shiptrip-production-f7f7.up.railway.app",
            **changes,
        }
    )


LIVE = dict(
    PAYMENTS_ENVIRONMENT="live",
    STRIPE_SECRET_KEY="sk_live_synthetic",
    CHARGILY_SECRET_KEY="live_sk_synthetic",
    CHARGILY_API_BASE="https://pay.chargily.net/api/v2",
    STRIPE_CONNECT_EXPECTED_MODE="live",
    TRANSACTIONAL_EMAIL_ENABLED=True,
)


def test_coherent_test_and_explicit_live():
    validate_payment_configuration(config())
    validate_payment_configuration(config(**LIVE))


def test_unbound_order_history_excludes_unrelated_unbound_boosts():
    from apps.finance.payout_snapshots import source_order_ids

    order = SimpleNamespace(
        pk=11, deal_id=None, credit_source_id=12, credited_eur_cents=100
    )
    with patch("apps.boosts.models.BoostPurchase.objects.filter") as boosts:
        assert source_order_ids(order) == [11, 12]
        boosts.assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [
        {"PAYMENTS_ENVIRONMENT": "production"},
        {"STRIPE_SECRET_KEY": "sk_live_synthetic"},
        {"STRIPE_SECRET_KEY": "unclassified"},
        {"CHARGILY_SECRET_KEY": "live_sk_synthetic"},
        {"CHARGILY_API_BASE": "https://pay.chargily.net/api/v2"},
        {"STRIPE_CONNECT_EXPECTED_MODE": "live"},
        {"CHARGILY_WEBHOOK_SECRET": "test_sk_other"},
        {"STRIPE_CONNECT_WEBHOOK_SECRET": "whsec_platform"},
        {"STRIPE_API_BASE": "https://unexpected.example"},
    ],
)
def test_contradictions_refused_without_secret_leak(changes):
    with pytest.raises(PaymentConfigurationError) as caught:
        validate_payment_configuration(config(**changes))
    assert "synthetic" not in str(caught.value)


@pytest.mark.parametrize(
    "changes",
    [
        {"STRIPE_SECRET_KEY": "sk_test_synthetic"},
        {"CHARGILY_SECRET_KEY": "test_sk_synthetic"},
        {"TRANSACTIONAL_EMAIL_ENABLED": False},
        {"PAYOUT_PROFILES_ENABLED": False},
        {"PAYMENTS_PUBLIC_BASE_URL": "https://test.shiptrip.invalid"},
        {"FRONTEND_BASE_URL": "https://old.example"},
    ],
)
def test_live_prerequisites_fail_closed(changes):
    with pytest.raises(PaymentConfigurationError):
        validate_payment_configuration(config(**{**LIVE, **changes}))


@pytest.mark.parametrize("mode,opposite", [("test", "live"), ("live", "test")])
def test_transport_stops_before_any_provider_call(mode, opposite):
    session = Mock()
    with override_settings(
        SHIPTRIP_ENVIRONMENT="production", PAYMENTS_ENVIRONMENT=mode
    ):
        gateways = [
            StripeGateway(secret_key=f"sk_{opposite}_synthetic", session=session),
            ChargilyGateway(
                secret_key=f"{opposite}_sk_synthetic",
                session=session,
                api_base="https://pay.chargily.net"
                + ("/test" if opposite == "test" else "")
                + "/api/v2",
            ),
            StripeConnectGateway(
                secret_key=f"sk_{opposite}_synthetic",
                platform_account_id="acct_synthetic",
                session=session,
            ),
        ]
        for gateway in gateways:
            with pytest.raises(ProviderConfigurationInvalid):
                gateway._request("POST", "/never")
    session.request.assert_not_called()


def test_live_key_requires_intent_even_in_development():
    with override_settings(
        SHIPTRIP_ENVIRONMENT="development", PAYMENTS_ENVIRONMENT="test"
    ):
        with pytest.raises(ProviderConfigurationInvalid):
            StripeGateway(secret_key="sk_live_synthetic")._require_configured()


@pytest.mark.parametrize("mode", ["test", "live"])
def test_event_and_object_modes_require_boolean_evidence(mode):
    with override_settings(
        SHIPTRIP_ENVIRONMENT="production", PAYMENTS_ENVIRONMENT=mode
    ):
        assert event_mode_allowed({"livemode": mode == "live"})
        assert not event_mode_allowed(
            {
                "livemode": mode == "live",
                "data": {"object": {"livemode": mode != "live"}},
            }
        )
        for wrong in (
            {},
            {"livemode": "false"},
            {"livemode": 1},
            {"livemode": mode != "live"},
        ):
            assert not event_mode_allowed(wrong)
        require_object_mode(mode)
        for other in ("legacy_unknown", "live" if mode == "test" else "test"):
            with pytest.raises(ProviderConfigurationInvalid):
                require_object_mode(other)


def test_finance_defaults_to_intent_and_preserves_explicit_audit_scope():
    with override_settings(
        PAYMENTS_ENVIRONMENT="live", STRIPE_SECRET_KEY="sk_test_synthetic"
    ):
        assert default_mode() == "live"
        assert scope_params(RequestFactory().get("/"))["mode"] == "live"
        assert (
            scope_params(RequestFactory().get("/", {"mode": "test"}))["mode"] == "test"
        )


# J1.2 put one model read on the Overview: the count of payout methods waiting
# on a reviewer, which H5 publishes no figure for. The assertions below are
# unchanged — an empty database contributes no such row, so the headline still
# holds exactly the four payout owner groups plus refunds.
@pytest.mark.django_db
def test_overview_unique_headline_owner_groups_and_independent_refunds():
    from apps.admin_panel.finance_operations import build_overview

    projection = {
        i: {
            "attention_owner": owner,
            "needs_attention": True,
            "block_reason": "payout_setup_required",
        }
        for i, owner in enumerate(("traveler", "finance", "provider", None))
    }
    summary = attention_summary(projection)
    snapshot = {
        "payout_attention": summary,
        "rail_operations": [],
        "metrics": {
            "held_payouts": {"count": 4},
            "liability_blocked": {"count": 4},
            "refunds_failed": {
                "count": 2,
                "amount_eur_cents": 100,
                "status": "available",
            },
        },
    }
    with patch("apps.admin_panel.finance_operations._activity", return_value=[]):
        overview = build_overview(snapshot, {"mode": "test"}, None, user=None)
    assert overview["attention_total"] == 4
    assert len(overview["attention"]) == 5
    assert overview["attention"][3]["owner"] == ""
    assert "metric=payout_attention" in overview["attention"][0]["url"]
    assert not any(
        word in str(overview) for word in ("sk_test_", "iban", "requirement_codes")
    )
    snapshot["payout_attention"] = attention_summary({})
    snapshot["metrics"] = {}
    with patch("apps.admin_panel.finance_operations._activity", return_value=[]):
        clean = build_overview(snapshot, {"mode": "test"}, None, user=None)
    assert clean["attention_total"] == 0 and clean["attention"] == []


def test_production_entrypoint_accepts_test_and_refuses_a_key_swap():
    from .test_deployment_safety import boot_production

    good = boot_production(
        "from config.wsgi import application", PAYMENTS_ENVIRONMENT="test"
    )
    assert good.returncode == 0, good.stderr
    bad = boot_production(
        "from config.wsgi import application",
        STRIPE_SECRET_KEY="sk_live_synthetic",
        STRIPE_WEBHOOK_SECRET="whsec_synthetic",
        PAYMENTS_ENVIRONMENT="test",
    )
    assert bad.returncode != 0 and "PAYMENTS_ENVIRONMENT" in bad.stderr
    assert "sk_live_synthetic" not in bad.stderr


def test_live_transfer_checks_platform_readiness_before_post():
    from apps.finance.providers import ProviderUnavailable

    session = Mock()
    response = Mock(status_code=200, headers={})
    response.json.return_value = {
        "id": "acct_synthetic",
        "details_submitted": False,
        "charges_enabled": True,
        "payouts_enabled": True,
    }
    session.request.return_value = response
    with override_settings(PAYMENTS_ENVIRONMENT="live"):
        gateway = StripeConnectGateway(
            secret_key="sk_live_synthetic",
            platform_account_id="acct_synthetic",
            session=session,
        )
        with pytest.raises(ProviderUnavailable, match="activation is incomplete"):
            gateway._request("POST", "/v1/transfers")
    assert session.request.call_count == 1
    assert session.request.call_args.args[0] == "GET"


def test_final_execution_rechecks_arrival_floor_on_both_rails():
    from datetime import timedelta
    from django.core.exceptions import ValidationError
    from django.utils import timezone
    from apps.finance.payout_execution import _assert_dispatchable, PayoutDeferred
    from apps.finance.payout_manual import _gate

    now = timezone.now()
    payout = SimpleNamespace(
        snapshot_version=1,
        method="stripe_transfer",
        payout_currency="EUR",
        provider_mode="test",
        status="eligible",
        block_reason="",
        eligible_at=now,
        amount_eur_cents=100,
        deal=SimpleNamespace(
            delivery_confirmed_at=now - timedelta(days=3),
            protection_ends_at=now - timedelta(days=1),
        ),
    )
    with override_settings(
        PAYMENTS_ENVIRONMENT="test", STRIPE_CONNECT_EXPECTED_MODE="test"
    ):
        with patch(
            "apps.deals.arrival.payout_release_gate_at",
            return_value=now + timedelta(days=1),
        ):
            with pytest.raises(PayoutDeferred, match="arrival floor"):
                _assert_dispatchable(payout)
            payout.method, payout.payout_currency = "manual", "DZD"
            with pytest.raises(ValidationError, match="arrival floor"):
                _gate(payout, None)
