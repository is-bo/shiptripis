"""PostgreSQL integration for H8A; all provider calls are synthetic or forbidden."""

from unittest.mock import patch

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.finance.control_plane.attention import (
    attention_projection,
    attention_summary,
    snapshot_attention,
)
from apps.finance.control_plane.drilldown import drilldown
from apps.finance.control_plane.filters import Scope
from apps.finance.control_plane.queries import Queries
from apps.finance.control_plane.snapshot import consistent_read
from apps.finance.mode_safety import require_order_mode
from apps.finance.models import FinanceHold, Payout
from apps.finance.providers import ProviderConfigurationInvalid
from .payout_execution_harness import H3_SETTINGS, build_stripe_payout
from .test_phase8fh5_control_plane import no_provider_network  # noqa: F401
from .test_phase8fh4_manual import build_manual, configured_h4  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True)


def test_profile_attention_aggregate_drilldown_and_cross_mode_history():
    with override_settings(**H3_SETTINGS):
        scenario, payout, account, _ = build_stripe_payout(prefix="h8a")
        scope = Scope.parse({"mode": "test", "search": str(payout.public_reference)})

        def summary():
            with consistent_read():
                return attention_summary(
                    attention_projection(Queries(scope, as_of=timezone.now()).payouts)
                )

        assert summary()["count"] == 0
        account.details_submitted = False
        account.save(update_fields=["details_submitted"])
        result = summary()
        assert result["count"] == 1
        assert result["groups"] == [{"attention_owner": "traveler", "count": 1}]
        row = drilldown(scope, metric="payout_attention")["rows"][0]
        assert row["block_reason"] == "payout_setup_required" and row["needs_attention"]
        assert not any(
            s in str(row) for s in ("acct_", "ccp", "requirement_codes", "sk_test_")
        )
        for suffix in ("one", "two"):
            FinanceHold.objects.create(
                payout=payout,
                kind="manual",
                reason_code="review",
                source_reference="h8a-" + suffix,
            )
        result = summary()
        assert result["count"] == 1
        assert result["groups"] == [{"attention_owner": "finance", "count": 1}]
        rows = drilldown(scope, metric="payout_attention", page_size=1)
        assert (
            len(rows["rows"]) == rows["totals"]["count"] == 1 and not rows["has_next"]
        )
        from apps.admin_panel.finance_operations import _activity
        from apps.admin_panel.services import record_admin_action

        record_admin_action(
            actor=scenario.admin, action="payout.bank_payout_retry", target=payout
        )
        assert _activity(mode="test") and _activity(mode="live") == []
        with patch("apps.finance.control_plane.attention.MAX_PAYOUTS", 0):
            assert (
                snapshot_attention(Payout.objects.filter(pk=payout.pk))["count"] is None
            )
        with override_settings(PAYMENTS_ENVIRONMENT="live"):
            with pytest.raises(ProviderConfigurationInvalid):
                require_order_mode(payout.funding_attempt.order)
            with pytest.raises(ProviderConfigurationInvalid):
                from apps.finance.payout_execution import _assert_dispatchable

                _assert_dispatchable(payout)
            with patch(
                "apps.finance.providers.stripe_connect.StripeConnectGateway._request"
            ) as network:
                from apps.finance.payout_accounts import refresh_account

                with pytest.raises(ProviderConfigurationInvalid):
                    refresh_account(account)
                network.assert_not_called()

        # Verify signatures first, then prove wrong-mode events are durably
        # acknowledged without touching the captured TEST financial authority.
        import hashlib
        import hmac
        import json
        import time
        from apps.finance.providers import StripeGateway
        from apps.finance.services import apply_provider_event

        capture = payout.funding_attempt
        for mode, live, expected in (
            ("test", True, "mode_isolated"),
            ("live", False, "mode_isolated"),
            ("live", True, "provider_mode_mismatch"),
        ):
            payload = {
                "id": f"evt_h8a_{mode}_{live}",
                "livemode": live,
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "id": capture.provider_session_id,
                        "object": "checkout.session",
                        "payment_intent": capture.provider_payment_id,
                        "payment_status": "paid",
                        "client_reference_id": str(capture.order.public_reference),
                        "amount_total": capture.provider_amount_minor,
                        "currency": "eur",
                    }
                },
            }
            body = json.dumps(payload).encode()
            timestamp = str(int(time.time()))
            signature = hmac.new(
                b"whsec_h8a", timestamp.encode() + b"." + body, hashlib.sha256
            ).hexdigest()
            event = StripeGateway(webhook_secret="whsec_h8a").parse_webhook(
                raw_body=body,
                headers={"stripe-signature": f"t={timestamp},v1={signature}"},
            )
            with override_settings(
                SHIPTRIP_ENVIRONMENT="production", PAYMENTS_ENVIRONMENT=mode
            ):
                assert apply_provider_event(event).note == expected
                assert apply_provider_event(event).duplicate

        payout.status = "cancelled"
        payout.save(update_fields=["status"])
        assert summary()["count"] == 0
        assert drilldown(scope, metric="payout_attention")["totals"]["count"] == 0


def test_manual_dzd_explicit_live_intent_still_requires_execution_flag(configured_h4):  # noqa: F811
    from django.core.exceptions import PermissionDenied
    from apps.finance.payout_manual import prepare

    with override_settings(PAYMENTS_ENVIRONMENT="live"):
        scenario, payout, _ = build_manual(prefix="h8a-manual", provider_mode="live")
        with override_settings(PAYOUT_DZD_EXECUTION_ENABLED=False):
            with pytest.raises(PermissionDenied):
                prepare(
                    actor=scenario.admin,
                    payout_id=payout.pk,
                    expected_state_version=payout.state_version,
                )
        with override_settings(PAYOUT_DZD_EXECUTION_ENABLED=True):
            prepare(
                actor=scenario.admin,
                payout_id=payout.pk,
                expected_state_version=payout.state_version,
            )
        attempt = payout.attempts.get()
        assert attempt.provider_mode == "live" and attempt.status == "prepared"
        # Synthetic local rows only: preparation calls no provider and records no settlement.
        payout.refresh_from_db()
        assert payout.status != "paid" and payout.paid_at is None
