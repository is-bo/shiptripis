"""The connected-accounts webhook endpoint, and its separation from the platform one.

Two endpoints, two secrets, two scopes. Most of this file is about proving that
neither can be made to do the other's job, and that nothing a webhook says is
believed without asking Stripe directly.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import timedelta

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.finance.connect_webhooks import MAX_WEBHOOK_BYTES
from apps.finance.models import PaymentProviderEvent, StripePayoutAccount
from apps.finance import connect_webhooks
from apps.finance import payout_account_api
from .test_phase8fh2_accounts import (
    H2,
    FakeGateway,
    make_account,
    ready_snapshot,
)
from .factories import make_user

CONNECT_SECRET = "whsec_connect_test"
PLATFORM_SECRET = "whsec_platform_test"

WEBHOOK_SETTINGS = {
    **H2,
    "STRIPE_WEBHOOK_SECRET": PLATFORM_SECRET,
    "STRIPE_CONNECT_WEBHOOK_SECRET": CONNECT_SECRET,
    "STRIPE_WEBHOOK_TOLERANCE_SECONDS": 300,
}


def sign(body: bytes, secret: str, *, timestamp: int | None = None) -> str:
    stamp = int(time.time()) if timestamp is None else timestamp
    digest = hmac.new(
        secret.encode(), f"{stamp}".encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    return f"t={stamp},v1={digest}"


def connect_event(
    *,
    event_id="evt_connect_1",
    event_type="account.updated",
    account="acct_1TESTconnected",
    livemode=False,
    obj=None,
):
    return {
        "id": event_id,
        "object": "event",
        "type": event_type,
        "account": account,
        "livemode": livemode,
        "created": int(time.time()),
        "api_version": "2026-03-25.dahlia",
        "data": {
            "object": obj
            or {
                "id": account,
                "object": "account",
                "payouts_enabled": True,
                "country": "FR",
            }
        },
    }


def post(client, event, *, secret=CONNECT_SECRET, url_name="finance-webhook-stripe-connect", timestamp=None, body=None):
    raw = body if body is not None else json.dumps(event).encode()
    return client.post(
        reverse(url_name),
        data=raw,
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE=sign(raw, secret, timestamp=timestamp),
    )


@pytest.fixture
def connect(monkeypatch):
    """Freeze the Connect adapter used by the webhook handler."""

    gateway = FakeGateway(retrieve=ready_snapshot())
    monkeypatch.setattr(connect_webhooks, "get_connect_gateway", lambda **kw: gateway)
    with override_settings(**WEBHOOK_SETTINGS):
        yield gateway


@pytest.fixture
def account(db, connect):
    user = make_user("h2-webhook@example.com")
    return make_account(
        user,
        status="setup_required",
        transfers_status="pending",
        payouts_enabled=False,
        details_submitted=False,
        eur_bank_present=False,
        external_account_id="",
        readiness_checked_at=timezone.now() - timedelta(minutes=5),
    )


class TestSignature:
    def test_the_dedicated_secret_verifies_a_valid_event(self, client, account):
        response = post(client, connect_event())
        assert response.status_code == 200
        assert response.json() == {"received": True, "duplicate": False}

    def test_an_invalid_signature_is_a_400_and_writes_nothing(self, client, account):
        raw = json.dumps(connect_event()).encode()
        response = client.post(
            reverse("finance-webhook-stripe-connect"),
            data=raw,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="t=1,v1=deadbeef",
        )
        assert response.status_code == 400
        assert PaymentProviderEvent.objects.count() == 0

    def test_the_platform_secret_cannot_verify_a_connect_event(self, client, account):
        response = post(client, connect_event(), secret=PLATFORM_SECRET)
        assert response.status_code == 400
        assert PaymentProviderEvent.objects.count() == 0

    def test_the_connect_secret_cannot_verify_a_platform_event(self, client, account):
        payment_event = {
            "id": "evt_payment_1",
            "type": "checkout.session.completed",
            "livemode": False,
            "data": {"object": {"id": "cs_1", "object": "checkout.session"}},
        }
        response = post(
            client,
            payment_event,
            secret=CONNECT_SECRET,
            url_name="finance-webhook-stripe",
        )
        assert response.status_code == 400

    def test_a_stale_timestamp_is_refused(self, client, account):
        response = post(
            client, connect_event(), timestamp=int(time.time()) - 4000
        )
        assert response.status_code == 400

    def test_a_mutated_body_no_longer_verifies(self, client, account):
        event = connect_event()
        raw = json.dumps(event).encode()
        signature = sign(raw, CONNECT_SECRET)
        response = client.post(
            reverse("finance-webhook-stripe-connect"),
            data=raw.replace(b"acct_1TESTconnected", b"acct_1ATTACKERaccnt"),
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE=signature,
        )
        assert response.status_code == 400

    def test_an_oversized_body_is_refused_without_hashing_it(self, client, account):
        raw = b'{"id":"evt_big","padding":"' + b"a" * (MAX_WEBHOOK_BYTES + 10) + b'"}'
        response = client.post(
            reverse("finance-webhook-stripe-connect"),
            data=raw,
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE=sign(raw, CONNECT_SECRET),
        )
        assert response.status_code == 400

    def test_a_missing_connect_secret_answers_503_so_stripe_retries(
        self, client, account
    ):
        with override_settings(**{**WEBHOOK_SETTINGS, "STRIPE_CONNECT_WEBHOOK_SECRET": ""}):
            response = post(client, connect_event())
        assert response.status_code == 503


class TestScopeSeparation:
    def test_a_connected_account_event_on_the_platform_endpoint_is_not_applied(
        self, client, account
    ):
        response = post(
            client,
            connect_event(event_id="evt_wrong_scope"),
            secret=PLATFORM_SECRET,
            url_name="finance-webhook-stripe",
        )
        assert response.status_code == 200
        record = PaymentProviderEvent.objects.get(provider_event_id="evt_wrong_scope")
        assert record.endpoint_scope == "platform"
        assert record.processing_result == PaymentProviderEvent.ProcessingResult.IGNORED
        assert record.processing_note == "connected_account_scope"

    def test_a_platform_scoped_event_on_the_connect_endpoint_is_classified_only(
        self, client, account
    ):
        event = connect_event(event_id="evt_no_account", account="")
        event.pop("account")
        response = post(client, event)
        assert response.status_code == 200
        record = PaymentProviderEvent.objects.get(provider_event_id="evt_no_account")
        assert record.endpoint_scope == "connect"
        assert record.processing_note == "platform_scope_event"

    def test_the_connect_endpoint_never_reconciles_a_payment(self, client, account):
        checkout = connect_event(
            event_id="evt_checkout_on_connect",
            event_type="checkout.session.completed",
            obj={"id": "cs_1", "object": "checkout.session"},
        )
        post(client, checkout)
        record = PaymentProviderEvent.objects.get(
            provider_event_id="evt_checkout_on_connect"
        )
        assert record.processing_note == "event_not_subscribed"
        assert record.attempt_id is None and record.order_id is None


class TestModeIsolation:
    def test_a_live_event_never_touches_a_test_account(self, client, account):
        response = post(client, connect_event(event_id="evt_live", livemode=True))
        assert response.status_code == 200
        record = PaymentProviderEvent.objects.get(provider_event_id="evt_live")
        assert record.provider_mode == "live"
        assert record.processing_note == "mode_isolated"
        account.refresh_from_db()
        assert account.status == "setup_required"

    def test_a_wrong_mode_event_is_classified_not_endlessly_rejected(
        self, client, account
    ):
        assert post(client, connect_event(event_id="evt_live2", livemode=True)).status_code == 200


class TestReadinessRefresh:
    @pytest.mark.parametrize(
        "event_type",
        [
            "account.updated",
            "capability.updated",
            "account.external_account.created",
            "account.external_account.updated",
            "account.external_account.deleted",
        ],
    )
    def test_each_subscribed_event_refreshes_from_the_provider(
        self, client, account, connect, event_type
    ):
        response = post(
            client, connect_event(event_id=f"evt_{event_type}", event_type=event_type)
        )
        assert response.status_code == 200
        assert ("retrieve_account", "acct_1TESTconnected") in connect.calls
        account.refresh_from_db()
        assert account.status == "ready"

    def test_the_event_payload_is_never_the_source_of_readiness(
        self, client, account, connect
    ):
        # The event claims the account is fine; Stripe says a bank is missing.
        connect._retrieve = ready_snapshot(
            eur_bank_present=False, eur_bank_account_id="", external_account_count=0
        )
        post(
            client,
            connect_event(
                event_id="evt_lying",
                obj={"id": "acct_1TESTconnected", "object": "account", "payouts_enabled": True},
            ),
        )
        account.refresh_from_db()
        assert account.status == "setup_required"
        assert account.status_reason == "eur_bank_required"

    def test_an_unknown_connected_account_is_classified_never_created(
        self, client, account
    ):
        response = post(
            client,
            connect_event(event_id="evt_unknown", account="acct_not_ours"),
        )
        assert response.status_code == 200
        record = PaymentProviderEvent.objects.get(provider_event_id="evt_unknown")
        assert record.processing_note == "unknown_connected_account"
        assert StripePayoutAccount.objects.count() == 1

    def test_a_deferred_execution_event_is_stored_without_acting(
        self, client, account, connect
    ):
        response = post(
            client, connect_event(event_id="evt_payout", event_type="payout.paid")
        )
        assert response.status_code == 200
        record = PaymentProviderEvent.objects.get(provider_event_id="evt_payout")
        assert record.processing_note == "deferred_to_execution_phase"
        assert "retrieve_account" not in [name for name, _ in connect.calls]


class TestIdempotency:
    def test_a_redelivered_event_is_a_no_op(self, client, account, connect):
        first = post(client, connect_event(event_id="evt_dup"))
        second = post(client, connect_event(event_id="evt_dup"))
        assert first.json()["duplicate"] is False
        assert second.json() == {"received": True, "duplicate": True}
        assert PaymentProviderEvent.objects.filter(provider_event_id="evt_dup").count() == 1
        assert [name for name, _ in connect.calls].count("retrieve_account") == 1

    def test_an_out_of_order_event_cannot_regress_a_newer_observation(
        self, client, account, connect
    ):
        post(client, connect_event(event_id="evt_first"))
        account.refresh_from_db()
        assert account.status == "ready"
        generation = account.readiness_generation

        # A later delivery whose provider read is older than what is stored.
        StripePayoutAccount.objects.filter(pk=account.pk).update(
            readiness_checked_at=timezone.now() + timedelta(minutes=10)
        )
        connect._retrieve = ready_snapshot(payouts_enabled=False)
        response = post(client, connect_event(event_id="evt_second"))
        assert response.status_code == 200
        record = PaymentProviderEvent.objects.get(provider_event_id="evt_second")
        assert record.processing_note == "superseded_by_newer_observation"
        account.refresh_from_db()
        assert account.payouts_enabled is True
        assert account.readiness_generation == generation

    def test_a_reused_event_id_with_a_different_payload_is_a_contradiction(
        self, client, account
    ):
        post(client, connect_event(event_id="evt_conflict"))
        response = post(
            client,
            connect_event(event_id="evt_conflict", event_type="capability.updated"),
        )
        assert response.status_code == 200
        assert response.json()["duplicate"] is True
        record = PaymentProviderEvent.objects.get(provider_event_id="evt_conflict")
        assert record.event_type == "account.updated"


class TestProvenanceAndPrivacy:
    def test_the_event_row_carries_scope_account_version_and_object(
        self, client, account
    ):
        post(client, connect_event(event_id="evt_provenance"))
        record = PaymentProviderEvent.objects.get(provider_event_id="evt_provenance")
        assert record.endpoint_scope == "connect"
        assert record.provider_account_id == "acct_1TESTconnected"
        assert record.api_version == "2026-03-25.dahlia"
        assert record.provider_mode == "test"
        assert record.object_type == "account"
        assert record.object_id == "acct_1TESTconnected"

    def test_no_bank_payload_is_persisted_from_an_external_account_event(
        self, client, account
    ):
        post(
            client,
            connect_event(
                event_id="evt_bank",
                event_type="account.external_account.created",
                obj={
                    "id": "ba_1TESTbank",
                    "object": "bank_account",
                    "currency": "eur",
                    "status": "new",
                    "account_holder_name": "Jean Dupont",
                    "account_holder_type": "individual",
                    "last4": "3000",
                    "routing_number": "30003",
                    "fingerprint": "fptest",
                    "country": "FR",
                },
            ),
        )
        record = PaymentProviderEvent.objects.get(provider_event_id="evt_bank")
        stored = json.dumps([record.payload, record.normalized_event])
        for leaked in ("Dupont", "3000", "30003", "fptest"):
            assert leaked not in stored
        assert record.object_id == "ba_1TESTbank"

    def test_legacy_payment_event_history_still_reads(self, client, account):
        legacy = PaymentProviderEvent.objects.create(
            provider="stripe",
            provider_event_id="evt_legacy",
            event_type="checkout.session.completed",
            payload={"id": "evt_legacy"},
        )
        legacy.refresh_from_db()
        assert legacy.endpoint_scope == "platform"
        assert legacy.object_type == "" and legacy.object_id == ""


class TestNoMoneyExecution:
    def test_the_handler_module_has_no_money_moving_path(self):
        from pathlib import Path

        source = Path(connect_webhooks.__file__).read_text(encoding="utf-8")
        for forbidden in ("/v1/transfers", "/v1/payouts", "create_transfer", "create_payout"):
            assert forbidden not in source

    def test_the_api_module_has_no_money_moving_path(self):
        from pathlib import Path

        source = Path(payout_account_api.__file__).read_text(encoding="utf-8")
        for forbidden in ("/v1/transfers", "/v1/payouts", "create_transfer", "create_payout"):
            assert forbidden not in source

    def test_no_readiness_refresh_ever_calls_a_payout_or_transfer(
        self, client, account, connect
    ):
        post(client, connect_event(event_id="evt_no_money"))
        assert {name for name, _ in connect.calls} <= {
            "retrieve_account",
            "platform_identity",
            "set_payout_schedule",
            "create_account_link",
            "create_login_link",
            "create_account",
            "find_account_by_metadata",
        }


class TestExistingCheckoutRegression:
    def test_an_ordinary_platform_payment_event_still_reaches_reconciliation(
        self, client, db
    ):
        with override_settings(**WEBHOOK_SETTINGS):
            event = {
                "id": "evt_checkout_ok",
                "object": "event",
                "type": "checkout.session.expired",
                "livemode": False,
                "data": {
                    "object": {
                        "id": "cs_expired",
                        "object": "checkout.session",
                        "client_reference_id": "00000000-0000-0000-0000-000000000000",
                    }
                },
            }
            response = post(
                client,
                event,
                secret=PLATFORM_SECRET,
                url_name="finance-webhook-stripe",
            )
        assert response.status_code == 200
        record = PaymentProviderEvent.objects.get(provider_event_id="evt_checkout_ok")
        assert record.endpoint_scope == "platform"
        # It went through the payment path, not the connect classifier.
        assert record.processing_note != "connected_account_scope"
        assert record.normalized_event.get("outcome") == "expired"
