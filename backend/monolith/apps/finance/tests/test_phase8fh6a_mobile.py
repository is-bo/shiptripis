"""Frozen mobile contract against real aggregates, with synthetic providers only."""

from unittest.mock import patch

import pytest
from django.db import transaction
from django.test import override_settings
from rest_framework.test import APIClient

from apps.finance.models import (
    Payout,
    StripeDisbursement,
    StripeDisbursementAllocation,
    TravelerPayoutMethod,
)
from apps.finance.payout_mobile import bank_stage, payout_status, eur_method, dzd_method
from apps.finance.payout_reconciliation import notify_payout_state, reconcile_payout
from apps.finance.payout_execution import execute_payout
from apps.finance.payout_manual import prepare, begin, confirm
from apps.finance.payout_evidence import upload_evidence
from apps.notifications.models import Notification, OutboundMessage
from .factories import make_user
from .payout_execution_harness import H3_SETTINGS, build_stripe_payout, FakeConnect, authorise_auto_stripe
from .test_phase8fh2_accounts import H2, FakeGateway, ready_snapshot, snapshot
from .test_phase8fh2_webhooks import connect_event, post as post_webhook
from .test_phase8fh4_manual import configured_h4, build_manual, image_upload  # noqa: F401

configured_h4_fixture = configured_h4

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def setup(settings):
    with override_settings(**{**H2, **H3_SETTINGS}):
        from django.core.cache import cache
        from django.apps import apps
        from django.db import connection
        from importlib import import_module
        from types import SimpleNamespace
        from apps.finance.tests.test_phase4_concurrency import _seed_phase4_settings
        _seed_phase4_settings()
        import_module("apps.core.migrations.0009_seed_boost_economics").seed_boost_economics(apps, None)
        import_module("apps.admin_panel.migrations.0002_seed_roles").seed_roles(apps, None)
        import_module("apps.admin_panel.migrations.0005_seed_payout_capabilities").seed(apps, SimpleNamespace(connection=connection))
        cache.clear()
        yield


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def preference(client, value, *, eur=0, dzd=0, country="FR", **extra):
    return client.patch("/api/payouts/methods", {
        "preference": value, "eur_revision": eur, "dzd_revision": dzd,
        "country": country, "consent_policy": "payout_profile_v1", **extra,
    }, format="json")


@pytest.mark.parametrize("value", ["eur_only", "dzd_only", "both"])
def test_preference_contract_and_future_route(value):
    from apps.finance.payout_snapshots import choose_method

    user = make_user(f"{value}@h6a.test")
    client = client_for(user)
    initial = client.get("/api/payouts/methods").json()
    assert initial["preference"] is None and initial["preference_required"]
    response = preference(client, value)
    assert response.status_code == 200, response.data
    assert response.data["preference"] == value
    methods = list(TravelerPayoutMethod.objects.filter(traveler=user))
    for provider in ("stripe", "chargily"):
        chosen = choose_method(methods, provider)
        expected = "EUR" if value == "eur_only" or (value == "both" and provider == "stripe") else "DZD"
        assert chosen.currency == expected
    assert response.data["preference_scope"] == "future_payouts_only"
    # Country is the Stripe EUR legal account country; a DZD manual instruction
    # is Algeria-side and must never carry it.
    for method in methods:
        version = method.current_version
        if version and method.currency == "DZD":
            assert version.country == ""


def test_preference_invalid_country_revision_and_authority_rollback():
    user = make_user("invalid@h6a.test")
    client = client_for(user)
    assert preference(client, "both", country="DZ").data["code"] == "payout_country_unsupported"
    assert not TravelerPayoutMethod.objects.filter(traveler=user).exists()
    assert preference(client, "both", dzd=19).status_code == 400
    assert not TravelerPayoutMethod.objects.filter(traveler=user).exists()
    for field in ("traveler_id", "rail", "approved", "payout_amount", "state"):
        assert preference(client, "both", **{field: 9}).status_code == 400


def test_preference_preserves_funded_history():
    s, payout, _, _ = build_stripe_payout(prefix="h6pref")
    before = Payout.objects.filter(pk=payout.pk).values().get()
    client = client_for(s.traveler)
    revision = client.get("/api/payouts/methods").data["revisions"]["EUR"]
    assert preference(client, "dzd_only", eur=revision).status_code == 200
    assert Payout.objects.filter(pk=payout.pk).values().get() == before


def test_j1_setup_notification_uses_funded_instruction_not_current_preference():
    from apps.notifications.resolution import resolved_notifications
    s, payout, _, _ = build_stripe_payout(prefix="j1notify")
    payout.block_reason = "payout_setup_required"
    payout.save(update_fields=["block_reason"])
    notify_payout_state(payout, "setup_required")
    row = Notification.objects.get(recipient=s.traveler, channel="payout.status_changed", payload__event="setup_required")
    assert not resolved_notifications(s.traveler).get(pk=row.pk).resolved
    # Only clearing the bound execution gate resolves this event.
    payout.block_reason = ""
    payout.save(update_fields=["block_reason"])
    assert resolved_notifications(s.traveler).get(pk=row.pk).resolved


@pytest.mark.parametrize("changes, expected", [
    ({}, "ready"), ({"transfers_status": "pending"}, "pending_verification"),
    ({"details_submitted": False}, "setup_required"),
    ({"disabled_reason": "rejected.fraud"}, "needs_attention"),
    ({"active": False}, "needs_attention"),
])
def test_eur_method_states(changes, expected):
    s, _, account, _ = build_stripe_payout(prefix="h6states")
    for key, value in changes.items():
        setattr(account, key, value)
    account.save()
    method = TravelerPayoutMethod.objects.get(traveler=s.traveler)
    result = eur_method(method)
    assert result["state"] == expected
    assert "acct_" not in str(result) and "ba_" not in str(result)
    if changes.get("active") is False:
        assert not result["available_actions"]
    assert eur_method(None)["state"] == "not_configured"


def test_onboarding_resume_manage_refresh_and_owner_isolation(monkeypatch):
    user, other = make_user("setup@h6a.test"), make_user("other@h6a.test")
    client = client_for(user)
    assert preference(client, "eur_only").status_code == 200
    gateway = FakeGateway(create=snapshot())
    monkeypatch.setattr("apps.finance.payout_accounts.get_connect_gateway", lambda: gateway)
    monkeypatch.setattr("apps.finance.payout_account_api.get_connect_gateway", lambda: gateway)
    for _ in range(2):
        response = client.post("/api/payouts/methods/stripe/onboarding", {}, format="json")
        assert response.status_code == 201, response.data
        assert response.data["onboarding_url"] == gateway.link_url
        assert "no-store" in response["Cache-Control"]
    assert len([c for c in gateway.calls if c[0] == "create_account"]) == 1
    for route in ("onboarding", "dashboard", "refresh"):
        url = f"/api/payouts/methods/stripe/{route}"
        assert client_for(other).post(url, {}, format="json").status_code == 400
        assert client.post(url, {"traveler_id": other.pk}, format="json").status_code == 400
    gateway._retrieve = ready_snapshot()
    response = client.post("/api/payouts/methods/stripe/refresh", {}, format="json")
    assert response.status_code == 200 and response.data["method"]["mobile"]["state"] == "ready"
    assert client.post("/api/payouts/methods/stripe/dashboard", {}, format="json").status_code == 201
    payload = str(client.get("/api/payouts/methods").data)
    assert "acct_" not in payload and gateway.link_url not in payload
    assert not Notification.objects.filter(payload__icontains=gateway.link_url).exists()


def test_dzd_replacement_immutable_history_and_review(configured_h4):
    s, payout, profile = build_manual(prefix="h6dzd")
    client = client_for(s.traveler)
    response = client.get("/api/payouts/profiles/dzd")
    assert response.status_code == 200 and response.data["dzd"]["state"] == "ready"
    before = Payout.objects.filter(pk=payout.pk).values().get()
    proof = client.post("/api/payouts/proofs", {"image": image_upload()}, format="multipart")
    assert proof.status_code == 201
    data = {"expected_revision": response.data["method"]["revision"], "first_name": "QA",
            "last_name": "Synthetic", "ccp_number": "1234567890", "ccp_key": "12", "rip": "1" * 20,
            "proof_reference": proof.data["reference"], "consent_policy": "payout_profile_v1"}
    assert client.post("/api/payouts/profiles/dzd", {**data, "approved": True}, format="json").status_code == 400
    response = client.post("/api/payouts/profiles/dzd", data, format="json")
    assert response.status_code == 201, response.data
    assert response.data["mobile"]["state"] == "pending_review"
    assert response.data["profile"]["reference"] != str(profile.public_reference)
    assert "1234567890" not in str(response.data) and "1" * 20 not in str(response.data)
    assert Payout.objects.filter(pk=payout.pk).values().get() == before
    payout.refresh_from_db()
    result = payout_status(payout)
    assert result["dzd_amount"] == 15600 and result["fx_rate_micros"] == 260000000
    assert result["display_state"] == "ready"
    method = TravelerPayoutMethod.objects.get(traveler=s.traveler, currency="DZD")
    method.enabled = False
    assert dzd_method(method)["state"] == "inactive"
    assert dzd_method(None)["state"] == "not_configured"


@pytest.mark.parametrize("status, expected", [
    ("not_eligible", "release_pending"), ("eligible", "ready"), ("scheduled", "ready"),
    ("processing", "processing"), ("sent", "sent"), ("paid", "paid"),
    ("blocked", "needs_attention"), ("failed", "needs_attention"),
    ("frozen", "needs_attention"), ("cancelled", "cancelled"),
])
def test_status_mapping_read_only(status, expected):
    _, payout, _, _ = build_stripe_payout(prefix="h6status")
    # Projection only; no fabricated financial transition is saved.
    payout.status = status
    result = payout_status(payout)
    assert result["display_state"] == expected
    assert set(result["available_actions"]) <= {"view_payout", "refresh", "manage_eur", "resume_eur_setup", "configure_dzd"}


def test_protection_is_authoritative_and_hold_overrides_ready():
    from apps.finance.payout_domain import open_hold

    s, payout, _, _ = build_stripe_payout(prefix="h6protect", protection_expired=False)
    assert payout_status(payout)["display_state"] == "protection_active"
    assert payout_status(payout)["protection_active"]
    open_hold(actor=s.admin, payout_id=payout.pk, kind="manual", reason_code="synthetic", source_reference="h6")
    assert payout_status(payout)["blocking_reason"] == "payout_on_hold"


def test_history_detail_deal_and_notifications_authorization():
    s, payout, _, _ = build_stripe_payout(prefix="h6auth")
    client = client_for(s.traveler)
    ref = payout.public_reference
    assert isinstance(client.get("/api/payouts").data, list)
    history = client.get("/api/payouts?page=1&page_size=999")
    assert history.status_code == 200 and history.data["count"] == 1
    assert history.data["results"][0]["mobile"]["reference"] == str(ref)
    assert client.get(f"/api/payouts/{ref}").status_code == 200
    assert client_for(s.outsider).get(f"/api/payouts/{ref}").status_code == 404
    assert client_for(s.outsider).get("/api/payouts?page=1").data["count"] == 0
    detail = client.get(f"/api/deals/{s.deal.pk}")
    assert detail.status_code == 200, detail.data
    assert detail.data["payout_summary"]["reference"] == str(ref)
    assert client_for(s.sender).get(f"/api/deals/{s.deal.pk}").data["payout_summary"] is None
    for url in ("/api/payouts/methods", "/api/payouts/profiles/dzd", "/api/payouts", f"/api/payouts/{ref}"):
        assert APIClient().get(url).status_code in (401, 403)
    notify_payout_state(payout, "eligible")
    row = Notification.objects.get(recipient=s.traveler, channel="payout.status_changed")
    assert client.get("/api/notifications").data["count"] >= 1
    assert client_for(s.outsider).post(f"/api/notifications/{row.pk}/read").status_code == 404
    assert client.post(f"/api/notifications/{row.pk}/read").status_code == 200


@pytest.mark.parametrize("code", ["eligible", "processing", "sent", "paid", "needs_attention", "returned"])
def test_notification_durable_deduplicated_and_push_safe(code):
    from apps.notifications.push import _safe_data

    s, payout, _, _ = build_stripe_payout(prefix="h6notif")
    with patch("apps.core.redis_bus.get_client") as redis:
        notify_payout_state(payout, code)
        notify_payout_state(payout, code)
        # Inbox is present even before commit/Redis delivery.
        row = Notification.objects.get(recipient=s.traveler, channel="payout.status_changed")
        assert row.payload["event"] == code
        assert row.payload["message_key"] == "payout." + ("ready" if code == "eligible" else code)
        assert OutboundMessage.objects.filter(key__startswith="payout_event:").count() == 1
        assert not redis.called
    payload = _safe_data(channel=row.channel, event_id=row.event_id, notification_id=row.pk,
                         payload={**row.payload, "ccp": "secret", "account_id": "acct_secret"})
    assert "secret" not in str(payload) and "acct_" not in str(row.payload)
    count = Notification.objects.count()
    with pytest.raises(RuntimeError), transaction.atomic():
        payout.state_version += 1
        notify_payout_state(payout, code)
        raise RuntimeError("rollback")
    assert Notification.objects.count() == count


def test_stripe_reconciliation_and_webhook_replay_notification_idempotency(monkeypatch):
    s, payout, account, _ = build_stripe_payout(prefix="h6replay")
    authorise_auto_stripe()
    gateway = FakeConnect()
    execute_payout(payout.pk, gateway=gateway)
    gateway.payout_status = "paid"
    reconcile_payout(payout.pk, gateway=gateway)
    before = list(Notification.objects.filter(recipient=s.traveler).values_list("event_id", flat=True))
    reconcile_payout(payout.pk, gateway=gateway)
    assert list(Notification.objects.filter(recipient=s.traveler).values_list("event_id", flat=True)) == before
    # A signed account webhook and its duplicate use the real handler.
    account_gateway = FakeGateway(retrieve=ready_snapshot())
    monkeypatch.setattr("apps.finance.connect_webhooks.get_connect_gateway", lambda: account_gateway)
    event = connect_event(event_id="evt_h6_repeat")
    assert post_webhook(APIClient(), event).status_code == 200
    count = Notification.objects.count()
    assert post_webhook(APIClient(), event).status_code == 200
    assert Notification.objects.count() == count


def test_dzd_duplicate_finalization_does_not_notify_twice(configured_h4):
    s, payout, _ = build_manual(prefix="h6final")
    prepare(actor=s.admin, payout_id=payout.pk, expected_state_version=payout.state_version)
    begin(actor=s.admin, payout_id=payout.pk, sequence=1)
    proof = upload_evidence(actor=s.admin, upload=image_upload(), purpose="transfer_receipt")
    values = dict(actor=s.admin, payout_id=payout.pk, sequence=1,
                  evidence_reference=proof.public_reference, confirmed=True, settled=True)
    confirm(**values)
    count = Notification.objects.count()
    confirm(**values)
    assert Notification.objects.count() == count


# ---------------------------------------------------------------------------
# Returned bank payouts. H3's disbursement is the authority, never the Transfer.
# ---------------------------------------------------------------------------


def to_bank_stage(prefix):
    """A Traveler whose Transfer succeeded and whose bank payout now exists.

    Both stages run through `execute_payout`, so the disbursement and its
    allocation are written by H3 itself rather than inserted by the fixture.
    """

    scenario, payout, _, _ = build_stripe_payout(prefix=prefix)
    authorise_auto_stripe()
    gateway = FakeConnect()
    execute_payout(payout.pk, gateway=gateway)  # platform Transfer
    payout.refresh_from_db()
    execute_payout(payout.pk, gateway=gateway)  # connected-account bank payout
    payout.refresh_from_db()
    return scenario, payout, gateway


def read(user, payout):
    """The row exactly as the mobile read path loads it."""
    from apps.finance.payout_mobile import payouts_for

    return payouts_for(user).get(pk=payout.pk)


@pytest.mark.parametrize("provider_status, expected, reason", [
    ("pending", "processing", None),
    ("in_transit", "sent", None),
    ("paid", "paid", None),
    ("failed", "needs_attention", "payout_failed"),
])
def test_bank_payout_states_are_read_from_the_disbursement(provider_status, expected, reason):
    scenario, payout, gateway = to_bank_stage(f"h6bank{provider_status}")
    if provider_status != "pending":
        gateway.payout_status = provider_status
        reconcile_payout(payout.pk, gateway=gateway)
    disbursement = StripeDisbursement.objects.get()
    assert disbursement.status == provider_status
    result = payout_status(read(scenario.traveler, payout))
    assert result["display_state"] == expected
    assert result["blocking_reason"] == reason
    assert "po_" not in str(result) and "acct_" not in str(result)


def test_a_returned_bank_payout_is_neither_paid_nor_generically_failed():
    """The regression: a bank return leaves the Transfer attempt `accepted`.

    H3 hands the Transfer's money back to the connected account and puts the
    attempt back to `accepted`, because only the bank stage has to be retried.
    Nothing ever writes `returned` on a PayoutAttempt, so a reading taken from
    the attempt cannot distinguish a returned payout from any other failure —
    and would keep showing money the Traveler no longer has.
    """

    scenario, payout, gateway = to_bank_stage("h6returned")
    gateway.payout_status = "paid"
    reconcile_payout(payout.pk, gateway=gateway)
    paid = payout_status(read(scenario.traveler, payout))
    assert paid["display_state"] == "paid" and paid["paid_at"] is not None

    gateway.payout_status = "failed"
    reconcile_payout(payout.pk, gateway=gateway)
    payout.refresh_from_db()
    assert StripeDisbursement.objects.get().status == "returned"
    assert payout.attempts.get().status == "accepted"  # the Transfer is untouched
    assert not payout.attempts.filter(status="returned").exists()

    result = payout_status(read(scenario.traveler, payout))
    assert result["display_state"] == "needs_attention"
    assert result["blocking_reason"] == "payout_returned"
    assert result["state"] == "failed"  # the restored obligation, unchanged
    assert result["paid_at"] == paid["paid_at"]  # historical movement preserved
    assert result["message_key"] == "payout.needs_attention"

    # One safe `returned` event, and a replayed reconciliation adds no second.
    rows = Notification.objects.filter(recipient=scenario.traveler,
                                       channel="payout.status_changed")
    returned = rows.get(payload__event="returned")
    assert returned.payload["message_key"] == "payout.returned"
    assert returned.payload["payout_reference"] == str(payout.public_reference)
    body = str(returned.payload)
    for secret in ("acct_", "ba_", "tr_", "po_", "ccp", "rip", "http"):
        assert secret not in body.lower()
    before = set(rows.values_list("event_id", flat=True))
    reconcile_payout(payout.pk, gateway=gateway)
    assert set(rows.values_list("event_id", flat=True)) == before


def test_without_a_disbursement_no_bank_state_is_inferred():
    scenario, payout, _, _ = build_stripe_payout(prefix="h6nobank")
    assert bank_stage(payout) is None
    result = payout_status(read(scenario.traveler, payout))
    assert result["display_state"] == "ready" and result["blocking_reason"] is None


def test_a_retried_bank_payout_makes_the_newer_disbursement_current():
    from apps.finance.payout_execution import admin_retry_bank_payout

    scenario, payout, gateway = to_bank_stage("h6retry")
    gateway.payout_status = "failed"
    reconcile_payout(payout.pk, gateway=gateway)
    payout.refresh_from_db()
    assert payout_status(read(scenario.traveler, payout))["blocking_reason"] == "payout_failed"

    gateway.payout_status = "pending"
    admin_retry_bank_payout(actor=scenario.admin, payout_id=payout.pk,
                            expected_state_version=payout.state_version)
    execute_payout(payout.pk, gateway=gateway)
    allocations = StripeDisbursementAllocation.objects.filter(payout=payout)
    assert allocations.count() == 2 and allocations.filter(active=True).count() == 1
    result = payout_status(read(scenario.traveler, payout))
    assert result["display_state"] == "processing" and result["blocking_reason"] is None


def test_history_renders_a_returned_payout_and_costs_no_query_per_row():
    """Bounded rendering, not a planner assertion: a longer page must not cost
    more queries than a short one."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from apps.finance.payout_mobile import page_context, payouts_for
    from apps.finance.serializers import PayoutSerializer

    scenario, payout, gateway = to_bank_stage("h6history")
    gateway.payout_status = "paid"
    reconcile_payout(payout.pk, gateway=gateway)
    gateway.payout_status = "failed"
    reconcile_payout(payout.pk, gateway=gateway)

    client = client_for(scenario.traveler)
    history = client.get("/api/payouts?page=1&page_size=30")
    assert history.status_code == 200 and history.data["count"] == 1
    row = history.data["results"][0]["mobile"]
    assert row["display_state"] == "needs_attention"
    assert row["blocking_reason"] == "payout_returned"
    assert "no-store" in history["Cache-Control"]

    page = list(payouts_for(scenario.traveler))
    context = {"payout_page": page_context(page, user=scenario.traveler)}

    def cost(rows):
        with CaptureQueriesContext(connection) as captured:
            PayoutSerializer(rows, many=True, context=context).data
        return len(captured)

    assert cost(page) == cost(page * 25)
