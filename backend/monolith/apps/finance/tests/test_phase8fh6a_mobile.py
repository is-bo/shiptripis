"""Frozen mobile contract against real aggregates, with synthetic providers only."""

import json
from unittest.mock import patch

import pytest
from django.db import transaction
from django.test import override_settings
from rest_framework.test import APIClient

from apps.core.storage import StorageNotConfigured
from apps.finance.models import (
    DzdPayoutProfileRevision,
    Payout,
    PayoutAttempt,
    PayoutMethodVersion,
    PayoutProviderOperation,
    StripeDisbursement,
    StripeDisbursementAllocation,
    StripePayoutAccount,
    TravelerPayoutMethod,
)
from apps.finance.payout_mobile import bank_stage, payout_status, eur_method, dzd_method, setup_gate
from apps.finance.payout_reconciliation import notify_payout_state, reconcile_payout
from apps.finance.payout_execution import execute_payout
from apps.finance.payout_manual import prepare, begin, confirm
from apps.finance.payout_evidence import upload_evidence
from apps.notifications.models import Notification, OutboundMessage
from apps.finance.providers.base import ProviderUnavailable
from .factories import ccp_rip, make_user
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
        from apps.core.tests.business_settings_seed import seed_business_settings
        seed_business_settings()
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

    user = make_user(f"{value}@h6a.test", is_email_verified=True)
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
    user = make_user("invalid@h6a.test", is_email_verified=True)
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
    result = eur_method(method, setup_gate(s.traveler))
    assert result["state"] == expected
    assert "acct_" not in str(result) and "ba_" not in str(result)
    if changes.get("active") is False:
        assert not result["available_actions"]
    assert eur_method(None, setup_gate(s.traveler))["state"] == "not_configured"


def test_onboarding_resume_manage_refresh_and_owner_isolation(monkeypatch):
    user, other = make_user("setup@h6a.test", is_email_verified=True), make_user("other@h6a.test", is_email_verified=True)
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
            "last_name": "Synthetic", "ccp_number": "1234567890", "ccp_key": "12", "rip": ccp_rip("1234567890", "12"),
            "proof_reference": proof.data["reference"], "consent_policy": "payout_profile_v1"}
    assert client.post("/api/payouts/profiles/dzd", {**data, "approved": True}, format="json").status_code == 400
    response = client.post("/api/payouts/profiles/dzd", data, format="json")
    assert response.status_code == 201, response.data
    assert response.data["mobile"]["state"] == "pending_review"
    assert response.data["profile"]["reference"] != str(profile.public_reference)
    assert data["ccp_number"] not in str(response.data) and data["rip"] not in str(response.data)
    assert Payout.objects.filter(pk=payout.pk).values().get() == before
    payout.refresh_from_db()
    result = payout_status(payout)
    assert result["dzd_amount"] == 15600 and result["fx_rate_micros"] == 260000000
    assert result["display_state"] == "ready"
    method = TravelerPayoutMethod.objects.get(traveler=s.traveler, currency="DZD")
    method.enabled = False
    assert dzd_method(method, setup_gate(s.traveler))["state"] == "inactive"
    assert dzd_method(None, setup_gate(s.traveler))["state"] == "not_configured"


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
    default_history = client.get("/api/payouts")
    assert default_history.status_code == 200
    assert default_history.data["count"] == 1
    assert default_history.data["results"][0]["mobile"]["reference"] == str(ref)
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


# ---------------------------------------------------------------------------
# F1. Setup availability and every offered action follow the gates that refuse
# the write. Reads stay owner-scoped and write nothing.
# ---------------------------------------------------------------------------

#: Every action a setup or history read may offer. None of them moves money.
OFFERABLE = {"configure_eur", "resume_eur_setup", "manage_eur", "refresh",
             "configure_dzd", "replace_dzd_profile", "view_payout"}
OFF = {"PAYOUT_PROFILES_ENABLED": False}
NO_CONNECT = {"STRIPE_CONNECT_ENABLED": False}
NO_COUNTRIES = {"STRIPE_CONNECT_ALLOWED_COUNTRIES": []}
NO_STORE = {"S3_BUCKET_PAYOUT": "", "PAYOUT_S3_ACCESS_KEY": "", "PAYOUT_S3_SECRET_KEY": ""}


def summary(client):
    response = client.get("/api/payouts/methods")
    assert response.status_code == 200, response.data
    assert "no-store" in response["Cache-Control"]
    return response.data


def finance_state():
    """Every Finance row count, the audit log and the method rows."""
    from django.apps import apps as registry
    from apps.admin_panel.models import AdminAuditLog

    state = {model._meta.label: model.objects.count()
             for model in registry.get_app_config("finance").get_models()}
    state["audit"] = AdminAuditLog.objects.count()
    state["methods"] = list(TravelerPayoutMethod.objects.order_by("pk").values())
    return state


def dzd_body(revision, proof, **names):
    return {"expected_revision": revision, "first_name": "QA", "last_name": "Synthetic",
            "ccp_number": "1234567890", "ccp_key": "12", "rip": ccp_rip("1234567890", "12"),
            "proof_reference": str(proof), "consent_policy": "payout_profile_v1", **names}


def setup_writes(client):
    """Each member setup write, with a body that passes input validation."""
    return {
        "preference": client.patch("/api/payouts/methods", {
            "preference": "dzd_only", "eur_revision": 0, "dzd_revision": 0,
            "consent_policy": "payout_profile_v1"}, format="json"),
        "currency": client.post("/api/payouts/methods", {
            "currency": "DZD", "enabled": True, "expected_revision": 0,
            "consent_policy": "payout_profile_v1"}, format="json"),
        "proof": client.post("/api/payouts/proofs", {"image": image_upload()}, format="multipart"),
        "dzd": client.post("/api/payouts/profiles/dzd",
                           dzd_body(0, "00000000-0000-4000-8000-000000000000"), format="json"),
        "onboarding": client.post("/api/payouts/methods/stripe/onboarding",
                                  {"country": "FR"}, format="json"),
        "refresh": client.post("/api/payouts/methods/stripe/refresh", {}, format="json"),
        "dashboard": client.post("/api/payouts/methods/stripe/dashboard", {}, format="json"),
    }


def actions_in(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from (item if key == "available_actions" else actions_in(item))
    elif isinstance(value, list):
        for item in value:
            yield from actions_in(item)


@pytest.mark.parametrize("connect", [True, False])
def test_f1_profiles_off_is_a_stable_read_and_a_stable_refusal(connect):
    client = client_for(make_user(f"f1off{connect}@h6a.test", is_email_verified=True))
    with override_settings(**OFF, STRIPE_CONNECT_ENABLED=connect):
        before = finance_state()
        body = summary(client)
        dzd = client.get("/api/payouts/profiles/dzd")
        writes = setup_writes(client)
        history = client.get("/api/payouts?page=1")
        after = finance_state()
    assert body["setup"] == {"available": False, "unavailable_reason": "payout_profiles_disabled",
                             "preference_options": []}
    # Nothing asks for a preference while funding does not need one.
    assert body["preference"] is None and body["preference_required"] is False
    assert body["available_actions"] == []
    for rail in ("eur", "dzd"):
        assert body[rail]["available_actions"] == []
        assert body[rail]["unavailable_reason"] == "payout_profiles_disabled"
        assert body[rail]["supported"] is False and body[rail]["selectable"] is False
    assert dzd.status_code == 200 and dzd.data["method"] is None
    assert dzd.data["dzd"]["unavailable_reason"] == "payout_profiles_disabled"
    # The DZD read carries the same common contract as the methods read.
    assert dzd.data["contract_version"] == "f1.v1" and dzd.data["setup"] == body["setup"]
    for name, response in writes.items():
        assert response.status_code == 409, (name, response.data)
        assert response.data["code"] == "payout_profiles_disabled", name
    # History is its own read: an empty one is a 200, distinct from both.
    assert history.status_code == 200 and history.data["count"] == 0
    assert after == before


@pytest.mark.parametrize("connect", [True, False])
def test_f1_profiles_on_offers_each_rail_by_its_own_gate(configured_h4, connect):
    client = client_for(make_user(f"f1on{connect}@h6a.test", is_email_verified=True))
    with override_settings(STRIPE_CONNECT_ENABLED=connect):
        body = summary(client)
        dzd = client.get("/api/payouts/profiles/dzd").data
    assert dzd["contract_version"] == "f1.v1" and dzd["setup"] == body["setup"]
    assert dzd["dzd"] == body["dzd"]
    assert body["setup"]["available"] is True and body["setup"]["unavailable_reason"] is None
    assert body["preference_required"] is True
    assert body["dzd"]["available_actions"] == ["configure_dzd"]
    assert body["dzd"]["unavailable_reason"] is None and body["dzd"]["supported"] is True
    eur = body["eur"]
    assert eur["available_actions"] == (["configure_eur"] if connect else [])
    assert eur["supported"] is connect
    assert eur["unavailable_reason"] == (None if connect else "stripe_connect_unavailable")
    # Saving EUR checks the account country, not Connect, so it stays a choice
    # the server accepts; only the onboarding it leads to is closed.
    assert eur["selectable"] is True and eur["supported_countries"] == ["FR"]
    assert body["setup"]["preference_options"] == ["eur_only", "dzd_only", "both"]
    if not connect:
        with override_settings(**NO_CONNECT):
            assert preference(client, "eur_only").status_code == 200
            refused = client.post("/api/payouts/methods/stripe/onboarding", {}, format="json")
        assert refused.status_code == 409 and refused.data["code"] == "stripe_connect_unavailable"


@pytest.mark.parametrize("connect, code", [
    (True, "stripe_connect_no_countries"), (False, "stripe_connect_unavailable"),
])
def test_f1_an_empty_allowlist_closes_eur_with_its_own_reason(connect, code):
    client = client_for(make_user(f"f1empty{connect}@h6a.test", is_email_verified=True))
    with override_settings(STRIPE_CONNECT_ENABLED=connect, **NO_COUNTRIES):
        body = summary(client)
        before = finance_state()
        refused = [preference(client, value, country="FR") for value in ("eur_only", "both")]
        after = finance_state()
    eur = body["eur"]
    assert eur["unavailable_reason"] == code
    assert eur["available_actions"] == [] and eur["supported_countries"] == []
    assert eur["supported"] is False and eur["selectable"] is False
    assert body["setup"]["preference_options"] == ["dzd_only"]
    for response in refused:
        assert response.status_code == 409, response.data
        assert response.data["code"] == code
        assert response.data["supported_countries"] == []
        assert response.data["alternative"] == {"currency": "DZD", "rail": "manual"}
    assert after == before


def test_f1_legitimate_fr_and_dz_declarations(monkeypatch, configured_h4):
    gateway = FakeGateway(create=snapshot())
    monkeypatch.setattr("apps.finance.payout_accounts.get_connect_gateway", lambda: gateway)
    monkeypatch.setattr("apps.finance.payout_account_api.get_connect_gateway", lambda: gateway)
    client = client_for(make_user("f1fr@h6a.test", is_email_verified=True))
    assert preference(client, "eur_only", country="FR").status_code == 200
    eur = summary(client)["eur"]
    assert eur["country"] == "FR" and eur["available_actions"] == ["configure_eur"]
    started = client.post("/api/payouts/methods/stripe/onboarding", {}, format="json")
    assert started.status_code == 201, started.data
    actions = started.data["method"]["mobile"]["available_actions"]
    assert "refresh" in actions and "configure_eur" not in actions
    # A DZ legal account is never steered to a Stripe residency; it gets DZD.
    dz = make_user("f1dz@h6a.test", is_email_verified=True)
    client = client_for(dz)
    refused = preference(client, "eur_only", country="DZ")
    assert refused.status_code == 400
    assert refused.data["code"] == "payout_country_unsupported"
    assert refused.data["supported_countries"] == ["FR"]
    assert refused.data["alternative"] == {"currency": "DZD", "rail": "manual"}
    assert not TravelerPayoutMethod.objects.filter(traveler=dz).exists()
    assert preference(client, "dzd_only", country="").status_code == 200
    body = summary(client)
    assert body["preference"] == "dzd_only"
    assert body["dzd"]["available_actions"] == ["configure_dzd"]


@pytest.mark.parametrize("role, verified, banned, code", [
    ("sender", True, False, "payout_traveler_required"),
    ("traveler", True, True, "payout_traveler_required"),
    ("both", False, False, "email_verification_required"),
])
def test_f1_accounts_that_cannot_write_get_no_actions_and_a_coded_refusal(
    configured_h4, role, verified, banned, code
):
    user = make_user(f"f1-{role}-{verified}-{banned}@h6a.test", is_email_verified=verified)
    user.role, user.is_banned = role, banned
    user.save(update_fields=["role", "is_banned"])
    client = client_for(user)
    before = finance_state()
    body = summary(client)
    writes = setup_writes(client)
    assert body["setup"] == {"available": False, "unavailable_reason": code, "preference_options": []}
    assert body["available_actions"] == []
    for rail in ("eur", "dzd"):
        assert body[rail]["available_actions"] == [] and body[rail]["unavailable_reason"] == code
    for name, response in writes.items():
        assert response.status_code == 403, (name, response.data)
        assert response.data["code"] == code, name
    assert finance_state() == before


def test_f1_dzd_setup_works_while_eur_is_switched_off(configured_h4):
    user = make_user("f1dzdonly@h6a.test", is_email_verified=True)
    client = client_for(user)
    with override_settings(**NO_CONNECT, **NO_COUNTRIES):  # the live server's switches
        body = summary(client)
        chosen = preference(client, "dzd_only", country="")
        proof = client.post("/api/payouts/proofs", {"image": image_upload()}, format="multipart")
        submitted = client.post("/api/payouts/profiles/dzd",
                                dzd_body(chosen.data["revisions"]["DZD"], proof.data["reference"]),
                                format="json")
        refused = [
            preference(client, "both", eur=chosen.data["revisions"]["EUR"],
                       dzd=submitted.data["revision"], country="FR"),
            client.post("/api/payouts/methods/stripe/onboarding", {"country": "FR"}, format="json"),
        ]
    assert body["eur"]["unavailable_reason"] == "stripe_connect_unavailable"
    assert body["setup"]["preference_options"] == ["dzd_only"]
    assert body["dzd"]["available_actions"] == ["configure_dzd"]
    assert chosen.status_code == 200 and proof.status_code == 201
    assert submitted.status_code == 201, submitted.data
    assert submitted.data["mobile"]["state"] == "pending_review"
    assert submitted.data["mobile"]["available_actions"] == ["replace_dzd_profile"]
    for response in refused:
        assert response.status_code == 409, response.data
        assert response.data["code"] == "stripe_connect_unavailable"
    assert not StripePayoutAccount.objects.filter(traveler=user).exists()
    assert not PayoutProviderOperation.objects.exists()


def test_f1_saved_preferences_stay_visible_after_a_switch_change(configured_h4):
    user = make_user("f1saved@h6a.test", is_email_verified=True)
    client = client_for(user)
    saved = preference(client, "both", country="FR")
    assert saved.status_code == 200, saved.data
    revisions = saved.data["revisions"]
    rows = list(TravelerPayoutMethod.objects.filter(traveler=user).order_by("pk").values())
    with override_settings(**NO_CONNECT):
        body = summary(client)
    assert body["preference"] == "both" and body["revisions"] == revisions
    assert body["eur"]["unavailable_reason"] == "stripe_connect_unavailable"
    assert body["eur"]["available_actions"] == [] and body["eur"]["selectable"] is True
    assert body["setup"]["preference_options"] == ["eur_only", "dzd_only", "both"]
    with override_settings(**NO_COUNTRIES):
        body = summary(client)
        kept = preference(client, "both", eur=revisions["EUR"], dzd=revisions["DZD"], country="")
    assert body["preference"] == "both"
    assert body["eur"]["selectable"] is False
    assert body["eur"]["unavailable_reason"] == "stripe_connect_no_countries"
    assert body["setup"]["preference_options"] == ["dzd_only"]
    # The read and the write agree: keeping EUR needs an open account country.
    assert kept.status_code == 409 and kept.data["code"] == "stripe_connect_no_countries"
    with override_settings(**OFF):
        body = summary(client)
    assert body["preference"] == "both" and len(body["methods"]) == 2
    assert body["setup"]["unavailable_reason"] == "payout_profiles_disabled"
    assert body["available_actions"] == []
    # No read under any switch, and no refused write, changed a stored row.
    assert list(TravelerPayoutMethod.objects.filter(traveler=user).order_by("pk").values()) == rows


def test_f1_stale_revisions_change_nothing(configured_h4):
    user = make_user("f1stale@h6a.test", is_email_verified=True)
    client = client_for(user)
    first = preference(client, "dzd_only", country="")
    assert first.status_code == 200
    rows = list(TravelerPayoutMethod.objects.filter(traveler=user).order_by("pk").values())
    stale = preference(client, "both", eur=0, dzd=0, country="FR")
    proof = client.post("/api/payouts/proofs", {"image": image_upload()}, format="multipart")
    stale_dzd = client.post("/api/payouts/profiles/dzd", dzd_body(0, proof.data["reference"]),
                            format="json")
    for response in (stale, stale_dzd):
        assert response.status_code == 400 and response.data["code"] == "payout_profile_invalid"
    assert list(TravelerPayoutMethod.objects.filter(traveler=user).order_by("pk").values()) == rows
    assert not DzdPayoutProfileRevision.objects.filter(method__traveler=user).exists()


def test_f1_another_users_references_stay_private(configured_h4):
    s, payout, _ = build_manual(prefix="f1owner")
    other = make_user("f1stranger@h6a.test", is_email_verified=True)
    client = client_for(other)
    assert client.get(f"/api/payouts/{payout.public_reference}").status_code == 404
    assert client.get("/api/payouts?page=1").data["count"] == 0
    assert summary(client)["methods"] == []
    owners_proof = upload_evidence(actor=s.traveler, upload=image_upload())
    borrowed = client.post("/api/payouts/profiles/dzd",
                           dzd_body(0, owners_proof.public_reference), format="json")
    assert borrowed.status_code == 400 and borrowed.data["code"] == "payout_profile_invalid"
    assert not TravelerPayoutMethod.objects.filter(traveler=other).exists()


def test_f1_reads_hide_private_fields_claim_no_execution_and_leave_funding_alone(configured_h4):
    s, payout, _ = build_manual(prefix="f1funded")
    client = client_for(s.traveler)
    funded = Payout.objects.filter(pk=payout.pk).values().get()
    bound = PayoutMethodVersion.objects.filter(pk=payout.method_version_id).values().get()
    providers = (StripePayoutAccount, PayoutProviderOperation, PayoutAttempt)
    counts = [model.objects.count() for model in providers]
    revision = client.get("/api/payouts/profiles/dzd").data["method"]["revision"]
    proof = client.post("/api/payouts/proofs", {"image": image_upload()}, format="multipart")
    replaced = client.post("/api/payouts/profiles/dzd", dzd_body(
        revision, proof.data["reference"], first_name="Privategiven", last_name="Privatefamily",
        ccp_number="9876543210", ccp_key="34", rip=ccp_rip("9876543210", "34")), format="json")
    assert replaced.status_code == 201, replaced.data
    bodies = [replaced.data]
    for switches in ({}, NO_CONNECT, NO_COUNTRIES, OFF):
        with override_settings(**switches):
            detail = client.get(f"/api/payouts/{payout.public_reference}").data
            bodies += [summary(client), client.get("/api/payouts/profiles/dzd").data, detail,
                       client.get("/api/payouts?page=1").data]
        # The funded instruction reads the same whatever setup can do now.
        assert (detail["rail"], detail["amount_eur_cents"], detail["dzd_amount"],
                detail["fx_rate_micros"], detail["display_state"]) == (
            "manual_dzd", 6000, 15600, 260000000, "ready")
    text = json.dumps(bodies, default=str)
    for private in ("Privategiven", "Privatefamily", "9876543210", ccp_rip("9876543210", "34"),
                    str(proof.data["reference"]), '"first_name"', '"last_name"',
                    '"ccp_number"', '"ccp_key"', '"rip"', '"proof_reference"'):
        assert private not in text, private
    assert set(actions_in(bodies)) <= OFFERABLE
    for body in bodies[1::4]:
        assert body["execution_enabled"] is False
        assert {body["eur"]["state"], body["dzd"]["state"]}.isdisjoint({"processing", "sent", "paid"})
    assert Payout.objects.filter(pk=payout.pk).values().get() == funded
    assert PayoutMethodVersion.objects.filter(pk=payout.method_version_id).values().get() == bound
    assert [model.objects.count() for model in providers] == counts


def test_f1_history_publishes_only_usable_setup_actions_of_the_funded_rail(configured_h4):
    s, payout, _, _ = build_stripe_payout(prefix="f1rail")
    payout.block_reason = "payout_setup_required"
    payout.save(update_fields=["block_reason"])
    client = client_for(s.traveler)
    assert summary(client)["dzd"]["available_actions"] == ["configure_dzd"]

    def read():
        detail = client.get(f"/api/payouts/{payout.public_reference}")
        listed = client.get("/api/payouts?page=1")
        assert detail.status_code == 200 and listed.data["count"] == 1
        assert listed.data["results"][0]["mobile"]["available_actions"] == detail.data["available_actions"]
        return detail.data

    detail = read()
    assert detail["display_state"] == "needs_attention"
    assert detail["blocking_reason"] == "payout_setup_required"
    # The EUR rail's own usable action; never the DZD setup the traveler could
    # also start, which would not touch this EUR instruction.
    assert detail["available_actions"] == ["view_payout", "refresh", "manage_eur"]
    for switches in (OFF, NO_CONNECT):
        with override_settings(**switches):
            assert read()["available_actions"] == ["view_payout", "refresh"]
    s.traveler.is_email_verified = False
    s.traveler.save(update_fields=["is_email_verified"])
    assert read()["available_actions"] == ["view_payout", "refresh"]


def test_f1_outages_are_temporary_failures_not_unavailable_setup(monkeypatch):
    user = make_user("f1outage@h6a.test", is_email_verified=True)
    client = client_for(user)
    with override_settings(**NO_STORE):
        body = summary(client)
        upload = client.post("/api/payouts/proofs", {"image": image_upload()}, format="multipart")
    # Without its private store DZD setup is not offered, and says why; picking
    # DZD for future payouts needs no upload and stays open.
    assert body["dzd"]["available_actions"] == []
    assert body["dzd"]["unavailable_reason"] == "payout_evidence_unavailable"
    assert body["dzd"]["selectable"] is True
    assert upload.status_code == 503 and upload.data["code"] == "payout_evidence_unavailable"
    gateway = FakeGateway(create=ProviderUnavailable("synthetic outage"))
    monkeypatch.setattr("apps.finance.payout_accounts.get_connect_gateway", lambda: gateway)
    monkeypatch.setattr("apps.finance.payout_account_api.get_connect_gateway", lambda: gateway)
    assert preference(client, "eur_only").status_code == 200
    failed = client.post("/api/payouts/methods/stripe/onboarding", {}, format="json")
    assert failed.status_code == 502 and failed.data["code"] == "stripe_connect_provider_error"
    # An outage changes no stored readiness, so the same setup can be retried.
    eur = summary(client)["eur"]
    assert eur["state"] == "setup_required" and eur["available_actions"] == ["configure_eur"]
    assert not StripePayoutAccount.objects.filter(traveler=user).exists()


# ---------------------------------------------------------------------------
# F1 round 2 (Astra review of 317b55e). Each test names the finding it closes.
# ---------------------------------------------------------------------------

def connect_gateway(monkeypatch, gateway):
    monkeypatch.setattr("apps.finance.payout_accounts.get_connect_gateway", lambda: gateway)
    monkeypatch.setattr("apps.finance.payout_account_api.get_connect_gateway", lambda: gateway)
    return gateway


def eur_version(user):
    return TravelerPayoutMethod.objects.get(traveler=user, currency="EUR").current_version


def test_f1_eur_choice_follows_what_a_declaration_can_be_and_is_stored_normalized(configured_h4):
    """Finding 2: selectability, retained, replaced and normalized countries."""
    user = make_user("f1declare@h6a.test", is_email_verified=True)
    client = client_for(user)
    saved = preference(client, "both", country="FR")
    assert saved.status_code == 200, saved.data
    version = eur_version(user)
    # Retaining: no country keeps the saved declaration and makes no version.
    kept = preference(client, "both", eur=saved.data["revisions"]["EUR"],
                      dzd=saved.data["revisions"]["DZD"], country="")
    assert kept.status_code == 200, kept.data
    assert eur_version(user).pk == version.pk
    revisions = kept.data["revisions"]
    with override_settings(STRIPE_CONNECT_ALLOWED_COUNTRIES=["DE"]):
        body = summary(client)
        # The saved FR is closed, so keeping it is refused...
        refused = preference(client, "both", eur=revisions["EUR"], dzd=revisions["DZD"], country="")
        # ...while a new, open declaration is accepted, lowercase or not.
        replaced = preference(client, "both", eur=revisions["EUR"], dzd=revisions["DZD"], country="de")
        after = summary(client)
    eur = body["eur"]
    assert eur["selectable"] is True and eur["country"] == "FR" and eur["country_supported"] is False
    assert eur["supported_countries"] == ["DE"] and eur["blocking_reason"] == "payout_country_unsupported"
    assert body["setup"]["preference_options"] == ["eur_only", "dzd_only", "both"]
    assert refused.status_code == 400 and refused.data["code"] == "payout_country_unsupported"
    assert refused.data["supported_countries"] == ["DE"]
    assert replaced.status_code == 200, replaced.data
    assert eur_version(user).country == "DE"
    assert after["eur"]["country"] == "DE" and after["eur"]["country_supported"] is True
    # The DZD rail never takes the EUR account country.
    dzd = TravelerPayoutMethod.objects.get(traveler=user, currency="DZD").current_version
    assert dzd.country == ""
    # The single-currency route stores the normalized country too.
    other = make_user("f1declare-post@h6a.test", is_email_verified=True)
    posted = client_for(other).post("/api/payouts/methods", {
        "currency": "EUR", "enabled": True, "expected_revision": 0, "country": "fr",
        "consent_policy": "payout_profile_v1"}, format="json")
    assert posted.status_code == 200, posted.data
    assert eur_version(other).country == "FR"


@override_settings(STRIPE_CONNECT_ALLOWED_COUNTRIES=["FR", "DE"])
def test_f1_an_account_opened_for_another_country_is_never_offered_as_a_new_setup(
    monkeypatch, configured_h4
):
    """Finding 3: a bound DE account cannot serve an FR declaration."""
    gateway = connect_gateway(monkeypatch, FakeGateway(create=snapshot(country="DE")))
    user = make_user("f1mismatch@h6a.test", is_email_verified=True)
    client = client_for(user)
    first = preference(client, "eur_only", country="DE")
    assert client.post("/api/payouts/methods/stripe/onboarding", {}, format="json").status_code == 201
    account = StripePayoutAccount.objects.get(traveler=user)
    moved = preference(client, "eur_only", eur=summary(client)["revisions"]["EUR"],
                       dzd=first.data["revisions"]["DZD"], country="FR")
    assert moved.status_code == 200, moved.data
    eur = summary(client)["eur"]
    assert eur["state"] == "needs_attention" and eur["account_country"] == "DE"
    assert eur["unavailable_reason"] == "stripe_account_country_mismatch"
    assert eur["available_actions"] == []
    before = finance_state()
    refused = client.post("/api/payouts/methods/stripe/onboarding", {}, format="json")
    assert refused.status_code == 409, refused.data
    assert refused.data["code"] == "stripe_account_country_mismatch"
    assert refused.data["account_country"] == "DE"
    assert finance_state() == before
    # Declaring the account's own country again makes the setup usable, and
    # onboarding binds the same account instead of creating another.
    back = preference(client, "eur_only", eur=moved.data["revisions"]["EUR"],
                      dzd=moved.data["revisions"]["DZD"], country="DE")
    assert back.status_code == 200, back.data
    assert summary(client)["eur"]["available_actions"] == ["configure_eur"]
    creations = [name for name, _ in gateway.calls].count("create_account")
    resumed = client.post("/api/payouts/methods/stripe/onboarding", {}, format="json")
    assert resumed.status_code == 201, resumed.data
    assert [name for name, _ in gateway.calls].count("create_account") == creations
    assert StripePayoutAccount.objects.filter(traveler=user).count() == 1
    assert eur_version(user).stripe_account_id == account.pk
    assert "configure_eur" not in summary(client)["eur"]["available_actions"]


@pytest.mark.parametrize("profiles, role, code, status", [
    (False, "traveler", "payout_profiles_disabled", 409),
    (True, "sender", "payout_traveler_required", 403),
])
def test_f1_writes_meet_the_same_refusal_order_as_the_read(configured_h4, profiles, role, code, status):
    """Finding 5: an unconfirmed email never outranks profiles off or the role."""
    user = make_user(f"f1order-{role}@h6a.test", is_email_verified=False)
    user.role = role
    user.save(update_fields=["role"])
    client = client_for(user)
    with override_settings(PAYOUT_PROFILES_ENABLED=profiles):
        before = finance_state()
        body = summary(client)
        writes = setup_writes(client)
        after = finance_state()
    assert body["setup"]["unavailable_reason"] == code
    for name, response in writes.items():
        assert response.status_code == status, (name, response.data)
        assert response.data["code"] == code, name
    assert after == before


@pytest.mark.parametrize("number, ccp_mask, rip_mask", [
    ("1234567890", "7890", "9012"),
    ("12345678", "5678", "7812"),
    ("1234567", "567", ""),
    ("1234", "34", ""),
    ("0000001234", "34", ""),
    ("7", "", ""),
])
def test_f1_a_mask_never_shows_more_than_half_of_the_ccp_number(configured_h4, number, ccp_mask, rip_mask):
    """Finding 6: owner reads with profiles off never return a whole number.

    The RIP ends with the number's last two digits and a key computed from the
    whole number, so its ending is shown only beside a four-digit CCP ending.
    """
    user = make_user(f"f1mask{number}@h6a.test", is_email_verified=True)
    client = client_for(user)
    chosen = preference(client, "dzd_only", country="")
    proof = client.post("/api/payouts/proofs", {"image": image_upload()}, format="multipart")
    submitted = client.post("/api/payouts/profiles/dzd", {
        **dzd_body(chosen.data["revisions"]["DZD"], proof.data["reference"]),
        "ccp_number": number, "rip": ccp_rip(number, "12")}, format="json")
    assert submitted.status_code == 201, submitted.data
    with override_settings(**OFF):
        reads = [summary(client)["dzd"]["profile"], client.get("/api/payouts/profiles/dzd").data["dzd"]["profile"],
                 client.get("/api/payouts/profiles/dzd").data["method"]["profile"]]
    for profile in reads:
        assert (profile["ccp_last_four"], profile["rip_last_four"]) == (ccp_mask, rip_mask)
    assert 2 * len(ccp_mask) <= len(number.lstrip("0"))


@pytest.mark.parametrize("case, field, values", [
    ("eleven-digits", "ccp_number", {"ccp_number": "12345678901", "rip": ccp_rip("2345678901")}),
    ("only-zeros", "ccp_number", {"ccp_number": "0000", "rip": "00799999" + "0" * 12}),
    ("not-a-ccp-rip", "rip", {"rip": "00799998" + "1234567890" + "12"}),
    ("another-account", "rip", {"rip": ccp_rip("1234567891", "12")}),
    ("short-key", "ccp_key", {"ccp_key": "1"}),
])
def test_f1_a_ccp_account_must_be_one_algerie_poste_can_hold(configured_h4, case, field, values):
    """Finding 6: at most ten digits, and a CCP RIP that carries the number."""
    user = make_user(f"f1ccp-{case}@h6a.test", is_email_verified=True)
    client = client_for(user)
    chosen = preference(client, "dzd_only", country="")
    proof = client.post("/api/payouts/proofs", {"image": image_upload()}, format="multipart")
    before = finance_state()
    refused = client.post("/api/payouts/profiles/dzd", {
        **dzd_body(chosen.data["revisions"]["DZD"], proof.data["reference"]), **values}, format="json")
    assert refused.status_code == 400 and set(refused.data) == {field}, refused.data
    for value in values.values():
        assert value not in json.dumps(refused.data)
    assert finance_state() == before


def test_f1_one_account_has_one_spelling(configured_h4):
    """Finding 6: leading zeros do not make a second fingerprint or a wider mask."""
    from apps.finance.sensitive_data import postal_account

    padded = postal_account(ccp_number="0012 345678", ccp_key="12", rip=ccp_rip("12345678", "12"))
    assert padded == postal_account(ccp_number="12345678", ccp_key="12", rip=ccp_rip("12345678", "12"))
    assert padded[0] == "12345678"


def test_f1_a_proof_uploaded_before_the_store_closed_is_not_submitted(configured_h4):
    """Finding 8: the read and the submission agree when the store switch changes."""
    user = make_user("f1storeclosed@h6a.test", is_email_verified=True)
    client = client_for(user)
    chosen = preference(client, "dzd_only", country="")
    proof = client.post("/api/payouts/proofs", {"image": image_upload()}, format="multipart")
    assert proof.status_code == 201

    class ClosedStore:
        def require_bucket(self):
            raise StorageNotConfigured("No bucket is configured for the payout object store.")

    # The deconfigured store, in place of the fixture's fake one.
    with patch("apps.finance.payout_evidence.storage_for", return_value=ClosedStore()):
        before = finance_state()
        body = summary(client)
        refused = client.post("/api/payouts/profiles/dzd",
                              dzd_body(chosen.data["revisions"]["DZD"], proof.data["reference"]),
                              format="json")
        after = finance_state()
    assert body["dzd"]["available_actions"] == []
    assert body["dzd"]["unavailable_reason"] == "payout_evidence_unavailable"
    assert refused.status_code == 503 and refused.data["code"] == "payout_evidence_unavailable"
    assert after == before
    # Back on, the same unused proof is still the traveler's to submit.
    submitted = client.post("/api/payouts/profiles/dzd",
                            dzd_body(chosen.data["revisions"]["DZD"], proof.data["reference"]),
                            format="json")
    assert submitted.status_code == 201, submitted.data


#: The route each setup action is served by, as F2 maps them.
ADVERTISED = {"configure_eur": "/api/payouts/methods/stripe/onboarding",
              "resume_eur_setup": "/api/payouts/methods/stripe/onboarding"}


class FlakyGateway(FakeGateway):
    """Fails one step that runs after the account is bound, once."""

    def __init__(self, *, failing, **kwargs):
        super().__init__(**kwargs)
        self.failing = failing

    def set_payout_schedule(self, **kwargs):
        if self.failing == "schedule":
            self.calls.append(("set_payout_schedule", "failed"))
            raise ProviderUnavailable("synthetic schedule outage")
        return super().set_payout_schedule(**kwargs)

    def create_account_link(self, **kwargs):
        if self.failing == "link":
            self.calls.append(("create_account_link", "failed"))
            raise ProviderUnavailable("synthetic link outage")
        return super().create_account_link(**kwargs)


@pytest.mark.parametrize("failing", ["link", "schedule"])
def test_f1_a_failure_after_binding_keeps_the_account_and_the_retry_reuses_it(
    monkeypatch, configured_h4, failing
):
    """Finding 9: the 502 does not claim nothing changed, and a retry finishes."""
    created = snapshot(payout_schedule_interval="daily" if failing == "schedule" else "manual")
    connect_gateway(monkeypatch, FlakyGateway(failing=failing, create=created))
    user = make_user(f"f1kept-{failing}@h6a.test", is_email_verified=True)
    client = client_for(user)
    assert preference(client, "eur_only").status_code == 200
    failed = client.post("/api/payouts/methods/stripe/onboarding", {}, format="json")
    assert failed.status_code == 502 and failed.data["code"] == "stripe_connect_provider_error"
    assert "Nothing changed" not in failed.data["detail"]
    account = StripePayoutAccount.objects.get(traveler=user)
    assert eur_version(user).stripe_account_id == account.pk
    # Round 3: the refetch the 502 asks for advertises the way back. Stripe
    # still holds this account for review (transfers pending) while it waits
    # for the Traveler's details, so readiness alone would offer no link.
    eur = summary(client)["eur"]
    assert eur["state"] == "pending_verification"
    assert "resume_eur_setup" in eur["available_actions"]
    retry = connect_gateway(monkeypatch, FakeGateway(create=created, retrieve=snapshot()))
    resumed = client.post(ADVERTISED["resume_eur_setup"], {}, format="json")
    assert resumed.status_code == 201, resumed.data
    names = [name for name, _ in retry.calls]
    assert "create_account" not in names and "create_account_link" in names
    assert ("set_payout_schedule" in names) is (failing == "schedule")
    assert StripePayoutAccount.objects.filter(traveler=user).count() == 1
    account.refresh_from_db()
    assert account.payout_schedule_interval == "manual"


def test_f1_a_staff_ban_ends_the_session_before_any_payout_read_or_write(configured_h4):
    """Finding 10: a ban clears is_active, so a real bearer token is refused 401."""
    from rest_framework_simplejwt.tokens import RefreshToken
    from apps.admin_panel.permissions import AdminRole, assign_admin_roles
    from apps.admin_panel.staff_actions import set_account_ban

    traveler = make_user("f1ban@h6a.test", is_email_verified=True)
    staff = make_user("f1ban-staff@h6a.test", is_staff=True)
    assign_admin_roles(staff, (AdminRole.SUPER_ADMIN,), elevate_super_admin=True)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(traveler).access_token}")
    assert client.get("/api/payouts/methods").status_code == 200
    set_account_ban(actor=staff, user_id=traveler.pk, banned=True, reason="F1 synthetic ban.")
    before = finance_state()
    reads = [client.get("/api/payouts/methods"), client.get("/api/payouts/profiles/dzd"),
             client.get("/api/payouts?page=1")]
    writes = setup_writes(client)
    for response in reads + list(writes.values()):
        assert response.status_code == 401, response.data
    assert finance_state() == before


# ---------------------------------------------------------------------------
# F1 round 3 (Astra review of f3f37a3). Each test names the finding it closes.
# ---------------------------------------------------------------------------

BOTH_COUNTRIES = {"STRIPE_CONNECT_ALLOWED_COUNTRIES": ["FR", "DE"]}
ONBOARDING = "/api/payouts/methods/stripe/onboarding"


class HookedGateway(FakeGateway):
    """Runs `hook` once, inside the named provider call, before it answers."""

    def __init__(self, *, during, hook, **kwargs):
        super().__init__(**kwargs)
        self.during, self.hook = during, hook

    def _maybe(self, name):
        if self.during == name and self.hook:
            hook, self.hook = self.hook, None
            hook()

    def platform_identity(self):
        self._maybe("platform_identity")
        return super().platform_identity()

    def create_account(self, **kwargs):
        self._maybe("create_account")
        return super().create_account(**kwargs)

    def create_account_link(self, **kwargs):
        self._maybe("create_account_link")
        return super().create_account_link(**kwargs)


def declare(user, country):
    """Commit an EUR declaration the way the PATCH does, from outside onboarding."""
    from apps.finance.payout_profiles import set_preference

    method = TravelerPayoutMethod.objects.get(traveler=user, currency="EUR")
    set_preference(actor=user, currency="EUR", enabled=True, country=country,
                   expected_revision=method.revision)


def onboarded(monkeypatch, user, country):
    """`user` with an EUR account opened and bound for `country`."""
    connect_gateway(monkeypatch, FakeGateway(create=snapshot(country=country)))
    client = client_for(user)
    assert preference(client, "eur_only", country=country).status_code == 200
    assert client.post(ONBOARDING, {}, format="json").status_code == 201
    return client, StripePayoutAccount.objects.get(traveler=user)


@override_settings(**BOTH_COUNTRIES)
@pytest.mark.parametrize("body", [{}, {"country": "DE"}], ids=["saved", "named"])
def test_f1_a_declaration_committed_before_stripe_answers_is_never_overwritten(
    monkeypatch, configured_h4, body
):
    """Blocker: a stale onboarding of a bound DE account must not restore DE over FR.

    Also when the call names DE, as the phone does from the summary it read:
    the country passes the check before Stripe, and the lock refuses it.

    The writer runs on onboarding's own connection, which already holds the
    Traveler's account-setup lock, so it is not made to wait: this checks the
    guard under the method lock itself. A second session waits instead
    (`test_f1_payout_account_setup_race`).
    """
    user = make_user(f"f1stale-bound-{len(body)}@h6a.test", is_email_verified=True)
    client, account = onboarded(monkeypatch, user, "DE")
    gateway = connect_gateway(monkeypatch, HookedGateway(
        during="platform_identity", hook=lambda: declare(user, "FR"),
        create=snapshot(country="DE")))
    versions = PayoutMethodVersion.objects.count()
    refused = client.post(ONBOARDING, body, format="json")
    assert refused.status_code == 409, refused.data
    assert refused.data["code"] == "payout_preference_changed"
    # The FR declaration is the destination future funding reads, unbound.
    version = eur_version(user)
    assert version.country == "FR" and version.stripe_account_id is None
    assert PayoutMethodVersion.objects.count() == versions + 1
    assert "create_account_link" not in [name for name, _ in gateway.calls]
    eur = summary(client)["eur"]
    assert eur["unavailable_reason"] == "stripe_account_country_mismatch"
    assert eur["account_country"] == "DE" and eur["available_actions"] == []
    assert StripePayoutAccount.objects.filter(traveler=user).get().pk == account.pk


@override_settings(**BOTH_COUNTRIES)
def test_f1_an_account_created_while_the_declaration_changed_is_kept_unbound(
    monkeypatch, configured_h4
):
    """Blocker: the account Stripe returns is kept for later, never bound over DE.

    The writer runs on onboarding's own connection, which already holds the
    Traveler's account-setup lock, so it is not made to wait: this checks the
    guard under the method lock itself. A second session waits instead
    (`test_f1_payout_account_setup_race`).
    """
    user = make_user("f1stale-create@h6a.test", is_email_verified=True)
    client = client_for(user)
    first = preference(client, "eur_only", country="FR")
    gateway = connect_gateway(monkeypatch, HookedGateway(
        during="create_account", hook=lambda: declare(user, "DE"),
        create=snapshot(country="FR")))
    refused = client.post(ONBOARDING, {}, format="json")
    assert refused.status_code == 409, refused.data
    assert refused.data["code"] == "payout_preference_changed"
    account = StripePayoutAccount.objects.get(traveler=user)
    assert account.active and account.declared_country == "FR"
    assert not PayoutMethodVersion.objects.filter(stripe_account=account).exists()
    version = eur_version(user)
    assert version.country == "DE" and version.stripe_account_id is None
    operation = PayoutProviderOperation.objects.get(kind="account_create")
    assert operation.status == "accepted" and operation.provider_object_id == account.provider_account_id
    # The read and the write agree on what is left: the FR account.
    eur = summary(client)["eur"]
    assert eur["unavailable_reason"] == "stripe_account_country_mismatch"
    assert eur["account_country"] == "FR"
    again = client.post(ONBOARDING, {}, format="json")
    assert again.status_code == 409 and again.data["code"] == "stripe_account_country_mismatch"
    # Declaring FR again binds the kept account; Stripe is never asked twice.
    revisions = summary(client)["revisions"]
    assert preference(client, "eur_only", eur=revisions["EUR"],
                      dzd=first.data["revisions"]["DZD"], country="FR").status_code == 200
    assert summary(client)["eur"]["available_actions"] == ["configure_eur"]
    assert client.post(ADVERTISED["configure_eur"], {}, format="json").status_code == 201
    assert eur_version(user).stripe_account_id == account.pk
    assert [name for name, _ in gateway.calls].count("create_account") == 1
    assert StripePayoutAccount.objects.filter(traveler=user).count() == 1


@override_settings(**BOTH_COUNTRIES)
@pytest.mark.parametrize("bound", ["DE", "FR"])
def test_f1_a_call_naming_another_country_never_gets_the_bound_accounts_link(
    monkeypatch, configured_h4, bound
):
    """Round 3 and 4 blocker: a country in the request is only an assertion.

    With DE saved, `country=FR` is refused. With FR saved after the phone read
    DE, its stale `country=DE` is refused too: it never restores DE over FR.
    Either way nothing is created, bound or linked before any Stripe call.
    """
    user = make_user(f"f1explicit-{bound}@h6a.test", is_email_verified=True)
    client, account = onboarded(monkeypatch, user, "DE")
    if bound == "FR":
        declare(user, "FR")
    stale = {"DE": "FR", "FR": "DE"}[bound]
    gateway = connect_gateway(monkeypatch, FakeGateway(create=snapshot(country="DE")))
    destination = eur_version(user)
    before = finance_state()
    refused = client.post(ONBOARDING, {"country": stale}, format="json")
    assert refused.status_code == 409, refused.data
    assert refused.data["code"] == "payout_preference_changed"
    assert gateway.calls == []
    assert finance_state() == before
    assert eur_version(user) == destination
    assert destination.country == bound
    assert destination.stripe_account_id == (account.pk if bound == "DE" else None)


@pytest.mark.parametrize("closed, code, status", [
    ("account", "payout_country_unsupported", 400),
    ("declaration", "stripe_account_country_mismatch", 409),
])
def test_f1_the_read_and_onboarding_make_one_country_decision(
    monkeypatch, configured_h4, closed, code, status
):
    """A standing DE account, an FR declaration, and one of the two countries closed."""
    user = make_user(f"f1one-{closed}@h6a.test", is_email_verified=True)
    with override_settings(**BOTH_COUNTRIES):
        client, account = onboarded(monkeypatch, user, "DE")
        declare(user, "FR")
    gateway = connect_gateway(monkeypatch, FakeGateway(create=snapshot(country="DE")))
    open_country = "FR" if closed == "account" else "DE"
    with override_settings(STRIPE_CONNECT_ALLOWED_COUNTRIES=[open_country]):
        eur = summary(client)["eur"]
        before = finance_state()
        refused = client.post(ONBOARDING, {}, format="json")
        after = finance_state()
    assert eur["unavailable_reason"] == code and eur["available_actions"] == []
    assert eur["account_country"] == "DE"
    assert refused.status_code == status, refused.data
    assert refused.data["code"] == code and refused.data["account_country"] == "DE"
    assert after == before
    assert [name for name, _ in gateway.calls] == []


@override_settings(**BOTH_COUNTRIES)
@pytest.mark.parametrize("window", ["inside", "past"])
@pytest.mark.parametrize("found", [True, False])
def test_f1_a_superseded_creation_is_only_looked_for(monkeypatch, configured_h4, window, found):
    """Round 4 blocker 3: an FR intent is never sent once DE is declared.

    Inside Stripe's window too: the FR request may never have reached Stripe,
    so replaying it would open an FR account for a Traveler who now wants DE.
    It is looked for by its own operation; an account found is kept unbound
    and judged by the country decision, and nothing found waits for Finance.
    """
    from datetime import timedelta
    from django.utils import timezone

    user = make_user(f"f1superseded-{window}-{found}@h6a.test", is_email_verified=True)
    client = client_for(user)
    first = preference(client, "eur_only", country="FR")
    connect_gateway(monkeypatch, FakeGateway(create=ProviderUnavailable("timeout")))
    assert client.post(ONBOARDING, {}, format="json").status_code == 502
    operation = PayoutProviderOperation.objects.get(kind="account_create")
    if window == "past":
        PayoutProviderOperation.objects.filter(pk=operation.pk).update(
            first_request_at=timezone.now() - timedelta(days=2))
    operation.refresh_from_db()
    revisions = summary(client)["revisions"]
    assert preference(client, "eur_only", eur=revisions["EUR"],
                      dzd=first.data["revisions"]["DZD"], country="DE").status_code == 200
    # Until Stripe has been asked, the call that asks is the one offered.
    assert summary(client)["eur"]["available_actions"] == ["configure_eur"]
    gateway = FakeGateway(create=snapshot(country="DE"))
    gateway._found = snapshot(country="FR") if found else None
    connect_gateway(monkeypatch, gateway)
    answered = client.post(ONBOARDING, {}, format="json")
    eur = summary(client)["eur"]
    assert [name for name, _ in gateway.calls] == ["platform_identity", "find_account_by_metadata"]
    assert gateway.calls[1][1] == {
        "key": "shiptrip_operation", "value": str(operation.public_reference),
        "created_gte": int(operation.first_request_at.timestamp()) - 60}
    assert PayoutProviderOperation.objects.count() == 1
    assert eur_version(user).country == "DE" and eur_version(user).stripe_account_id is None
    if found:
        assert answered.status_code == 409 and answered.data["code"] == "stripe_account_country_mismatch"
        assert eur["unavailable_reason"] == "stripe_account_country_mismatch"
        assert eur["account_country"] == "FR"
        assert StripePayoutAccount.objects.get(traveler=user).declared_country == "FR"
    else:
        assert answered.status_code == 409 and answered.data["code"] == "stripe_account_unresolved"
        assert eur["unavailable_reason"] == "stripe_account_unresolved"
        assert not StripePayoutAccount.objects.filter(traveler=user).exists()
    assert eur["available_actions"] == []


@override_settings(**BOTH_COUNTRIES)
def test_f1_an_intent_for_an_earlier_declaration_of_the_same_country_is_only_looked_for(
    monkeypatch, configured_h4
):
    """Round 5 nit: FR, then DE, then FR again, inside Stripe's replay window.

    The country is the same as the ambiguous request's, but the declaration
    is a new version, so the request is not replayed: only its own account is
    looked for, and found, it serves the new FR declaration.
    """
    user = make_user("f1samecountry@h6a.test", is_email_verified=True)
    client = client_for(user)
    preference(client, "eur_only", country="FR")
    connect_gateway(monkeypatch, FakeGateway(create=ProviderUnavailable("timeout")))
    assert client.post(ONBOARDING, {}, format="json").status_code == 502
    operation = PayoutProviderOperation.objects.get(kind="account_create")
    declared_first = eur_version(user)
    declare(user, "DE")
    declare(user, "FR")
    assert eur_version(user).country == "FR" and eur_version(user).pk != declared_first.pk
    gateway = FakeGateway(create=snapshot(country="FR"))
    gateway._found = snapshot(country="FR")
    connect_gateway(monkeypatch, gateway)
    answered = client.post(ONBOARDING, {}, format="json")
    assert answered.status_code == 201, answered.data
    assert [name for name, _ in gateway.calls if name != "create_account_link"] == [
        "platform_identity", "find_account_by_metadata"]
    assert gateway.calls[1][1]["value"] == str(operation.public_reference)
    account = StripePayoutAccount.objects.get(traveler=user)
    assert eur_version(user).stripe_account_id == account.pk
    assert PayoutProviderOperation.objects.count() == 1


@override_settings(**BOTH_COUNTRIES)
def test_f1_a_current_creation_is_replayed_exactly_as_it_was_sent(monkeypatch, configured_h4):
    """Round 4 nit: the replay is the first request, every argument of it."""
    user = make_user("f1replay@h6a.test", is_email_verified=True)
    client = client_for(user)
    preference(client, "eur_only", country="FR")
    timing_out = connect_gateway(monkeypatch, FakeGateway(create=ProviderUnavailable("timeout")))
    assert client.post(ONBOARDING, {}, format="json").status_code == 502
    sent = [kw for name, kw in timing_out.calls if name == "create_account"]
    replaying = connect_gateway(monkeypatch, FakeGateway(create=snapshot(country="FR")))
    assert client.post(ONBOARDING, {}, format="json").status_code == 201
    replayed = [kw for name, kw in replaying.calls if name == "create_account"]
    assert len(sent) == 1 and replayed == sent
    assert "find_account_by_metadata" not in [name for name, _ in replaying.calls]
    account = eur_version(user).stripe_account
    assert account.declared_country == "FR"
    # Round 5 should-fix: Stripe answers a replay with the body it stored for
    # the first request, so the observation is dated then, and any refresh
    # made since outranks it.
    operation = PayoutProviderOperation.objects.get(kind="account_create")
    assert account.readiness_checked_at == operation.first_request_at


def test_f1_an_unresolved_creation_belongs_to_its_own_platform(monkeypatch, configured_h4):
    """An operation under another platform neither blocks nor is resumed here."""
    from datetime import timedelta
    from django.utils import timezone
    from apps.finance.providers.stripe_connect import PlatformIdentity

    class OtherPlatform(FakeGateway):
        def platform_identity(self):
            self.calls.append(("platform_identity", None))
            return PlatformIdentity(account_id="acct_platform_two", country="FR",
                                    default_currency="eur", mode="test")

    user = make_user("f1platform@h6a.test", is_email_verified=True)
    client = client_for(user)
    assert preference(client, "eur_only").status_code == 200
    connect_gateway(monkeypatch, FakeGateway(create=ProviderUnavailable("timeout")))
    assert client.post(ONBOARDING, {}, format="json").status_code == 502
    old = PayoutProviderOperation.objects.get(kind="account_create")
    PayoutProviderOperation.objects.filter(pk=old.pk).update(
        first_request_at=timezone.now() - timedelta(days=2))
    assert client.post(ONBOARDING, {}, format="json").status_code == 409
    assert summary(client)["eur"]["unavailable_reason"] == "stripe_account_unresolved"
    with override_settings(STRIPE_CONNECT_PLATFORM_ACCOUNT_ID="acct_platform_two"):
        eur = summary(client)["eur"]
        assert eur["unavailable_reason"] is None and eur["available_actions"] == ["configure_eur"]
        gateway = connect_gateway(monkeypatch, OtherPlatform())
        created = client.post(ADVERTISED["configure_eur"], {}, format="json")
    assert created.status_code == 201, created.data
    fresh = PayoutProviderOperation.objects.exclude(pk=old.pk).get()
    assert fresh.idempotency_key.startswith("acct_create:acct_platform_two:test:")
    assert [name for name, _ in gateway.calls].count("create_account") == 1
    old.refresh_from_db()
    assert old.status == "unknown" and old.provider_object_id == ""


class RefusingSearch(FakeGateway):
    """Stripe refusing the credential (403) on the recovery search, then fixed."""

    refusing = True

    def find_account_by_metadata(self, **kwargs):
        self.calls.append(("find_account_by_metadata", kwargs))
        if self.refusing:
            from apps.finance.providers.base import ProviderNotConfigured

            raise ProviderNotConfigured("Stripe rejected this deployment's API credentials.",
                                        provider_code="403")
        return self._create


@pytest.mark.parametrize("call", ["search", "replay"])
def test_f1_a_refused_recovery_never_opens_a_second_account(monkeypatch, configured_h4, call):
    """Pre-existing: a 403 is not Stripe refusing the creation; the identity stays."""
    from datetime import timedelta
    from django.utils import timezone
    from apps.finance.providers.base import ProviderNotConfigured

    user = make_user(f"f1refused-{call}@h6a.test", is_email_verified=True)
    client = client_for(user)
    assert preference(client, "eur_only").status_code == 200
    connect_gateway(monkeypatch, FakeGateway(create=ProviderUnavailable("timeout")))
    assert client.post(ONBOARDING, {}, format="json").status_code == 502
    operation = PayoutProviderOperation.objects.get(kind="account_create")
    if call == "search":
        PayoutProviderOperation.objects.filter(pk=operation.pk).update(
            first_request_at=timezone.now() - timedelta(days=2))
        gateway = connect_gateway(monkeypatch, RefusingSearch())
    else:
        gateway = connect_gateway(monkeypatch, FakeGateway(
            create=ProviderNotConfigured("Stripe rejected this deployment's API credentials.",
                                         provider_code="403")))
    refused = client.post(ONBOARDING, {}, format="json")
    assert refused.status_code == 502, refused.data
    operation.refresh_from_db()
    assert operation.status == "unknown"
    # Repaired: the same identity is recovered, and nothing is created anew.
    if call == "search":
        gateway.refusing = False
    else:
        gateway = connect_gateway(monkeypatch, FakeGateway())
    resumed = client.post(ONBOARDING, {}, format="json")
    assert resumed.status_code == 201, resumed.data
    assert PayoutProviderOperation.objects.get(kind="account_create").pk == operation.pk
    creations = [kw for name, kw in gateway.calls if name == "create_account"]
    assert all(kw["idempotency_key"] == operation.idempotency_key for kw in creations)
    assert StripePayoutAccount.objects.filter(traveler=user).count() == 1


@pytest.mark.skipif("not __import__('django.db').db.connection.vendor == 'postgresql'")
def test_f1_onboarding_and_refresh_lock_the_method_before_the_account(monkeypatch, configured_h4):
    """Pre-existing: both paths take the canonical order, so they cannot deadlock."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from apps.finance.payout_accounts import refresh_account, start_onboarding

    user = make_user("f1lockorder@h6a.test", is_email_verified=True)
    client, account = onboarded(monkeypatch, user, "FR")
    method_table = TravelerPayoutMethod._meta.db_table
    account_table = StripePayoutAccount._meta.db_table

    def locks(call):
        with CaptureQueriesContext(connection) as captured:
            call()
        order = []
        for query in captured:
            sql = query["sql"]
            if "FOR NO KEY UPDATE" not in sql:
                continue
            for table in (method_table, account_table):
                if f'FROM "{table}"' in sql:
                    order.append(table)
        return order

    gateway = FakeGateway(retrieve=ready_snapshot())
    refreshed = locks(lambda: refresh_account(account, gateway=gateway))
    resumed = locks(lambda: start_onboarding(actor=user, gateway=FakeGateway()))
    for order in (refreshed, resumed):
        assert account_table in order and method_table in order
        assert order.index(method_table) < order.index(account_table), order


# ---------------------------------------------------------------------------
# F1 round 4 (Astra review of ee1e477). One root cause: onboarding took its
# country, version and operation from different moments. Each Stripe account
# call now serves one declaration, decided under the method lock.
# ---------------------------------------------------------------------------


def audit_actions(user, *names):
    from apps.admin_panel.models import AdminAuditLog

    return list(AdminAuditLog.objects.filter(actor=user, action__in=names)
                .order_by("pk").values_list("action", flat=True))


class SecondPlatform(FakeGateway):
    """The Connect adapter of a second platform account."""

    def platform_identity(self):
        from apps.finance.providers.stripe_connect import PlatformIdentity

        self.calls.append(("platform_identity", None))
        return PlatformIdentity(account_id="acct_platform_two", country="FR",
                                default_currency="eur", mode="test")


class ByOperation(FakeGateway):
    """Stripe's account list: each account carries its own operation reference."""

    def __init__(self, accounts, **kwargs):
        super().__init__(**kwargs)
        self.accounts = accounts

    def find_account_by_metadata(self, **kwargs):
        self.calls.append(("find_account_by_metadata", kwargs))
        return self.accounts.get((kwargs["key"], kwargs["value"]))


@override_settings(**BOTH_COUNTRIES)
def test_f1_a_late_timeout_never_reopens_a_refusal_and_a_search_finds_only_its_own(
    monkeypatch, configured_h4
):
    """Round 4 blocker 2, with two operation keys on one method.

    v1 (FR) is recorded refused while this call's v1 POST is in flight; its
    late timeout must leave v1 refused. Two onboarding calls no longer
    overlap (the setup lock), so the refusal is written from inside the call
    here: this checks the conditional write itself. v2 (DE) creates a DE
    account whose answer is lost. With FR declared again, the search for v2
    finds the DE account by v2's own reference, which is kept and never
    bound as FR; a search by method would have found it for v1.
    """
    from datetime import timedelta
    from django.utils import timezone

    user = make_user("f1twokeys@h6a.test", is_email_verified=True)
    client = client_for(user)
    preference(client, "eur_only", country="FR")

    def refused_meanwhile():
        PayoutProviderOperation.objects.filter(kind="account_create").update(status="failed")

    connect_gateway(monkeypatch, HookedGateway(
        during="create_account", hook=refused_meanwhile, create=ProviderUnavailable("timeout")))
    assert client.post(ONBOARDING, {}, format="json").status_code == 502
    v1 = PayoutProviderOperation.objects.get(kind="account_create")
    assert v1.status == "failed" and v1.provider_object_id == ""

    declare(user, "DE")
    connect_gateway(monkeypatch, FakeGateway(create=ProviderUnavailable("timeout")))
    assert client.post(ONBOARDING, {}, format="json").status_code == 502
    v2 = PayoutProviderOperation.objects.exclude(pk=v1.pk).get()
    assert v2.idempotency_key.endswith(":v2") and v2.status == "unknown"
    PayoutProviderOperation.objects.filter(pk=v2.pk).update(
        first_request_at=timezone.now() - timedelta(days=2))
    v2.refresh_from_db()

    declare(user, "FR")
    german = snapshot(country="DE", account_id="acct_1TESTgerman")
    gateway = connect_gateway(monkeypatch, ByOperation({
        ("shiptrip_operation", str(v2.public_reference)): german,
        ("shiptrip_method", str(TravelerPayoutMethod.objects.get(
            traveler=user, currency="EUR").public_reference)): german,
    }))
    refused = client.post(ONBOARDING, {}, format="json")
    assert refused.status_code == 409, refused.data
    assert refused.data["code"] == "stripe_account_country_mismatch"
    assert refused.data["account_country"] == "DE"
    assert [name for name, _ in gateway.calls] == ["platform_identity", "find_account_by_metadata"]
    assert gateway.calls[1][1]["key"] == "shiptrip_operation"
    assert gateway.calls[1][1]["value"] == str(v2.public_reference)
    v1.refresh_from_db()
    v2.refresh_from_db()
    assert v1.status == "failed" and v1.provider_object_id == ""
    assert v2.status == "accepted" and v2.provider_object_id == "acct_1TESTgerman"
    version = eur_version(user)
    assert version.country == "FR" and version.stripe_account_id is None
    assert StripePayoutAccount.objects.get(traveler=user).declared_country == "DE"


@pytest.mark.parametrize("found", [True, False])
def test_f1_an_intent_that_never_reached_stripe_is_never_sent_after_its_country_closed(
    monkeypatch, configured_h4, found
):
    """Round 4 blocker 3: the worker dies between the intent and the POST.

    FR then closes, DE stays open, and the Traveler declares DE. Inside the
    replay window the FR request is still never sent: it is looked for, and
    an FR account found is kept, refused for its own closed country.
    """
    from apps.finance.payout_accounts import ensure_account

    class Crash(FakeGateway):
        def create_account(self, **kwargs):
            raise RuntimeError("the worker died before the request left")

    user = make_user(f"f1crash-{found}@h6a.test", is_email_verified=True)
    client = client_for(user)
    with override_settings(**BOTH_COUNTRIES):
        first = preference(client, "eur_only", country="FR")
        with pytest.raises(RuntimeError):
            ensure_account(actor=user, gateway=Crash())
    operation = PayoutProviderOperation.objects.get(kind="account_create")
    assert operation.status == "committed"
    with override_settings(STRIPE_CONNECT_ALLOWED_COUNTRIES=["DE"]):
        revisions = summary(client)["revisions"]
        assert preference(client, "eur_only", eur=revisions["EUR"],
                          dzd=first.data["revisions"]["DZD"], country="DE").status_code == 200
        gateway = FakeGateway(create=snapshot(country="DE"))
        gateway._found = snapshot(country="FR") if found else None
        connect_gateway(monkeypatch, gateway)
        answered = client.post(ONBOARDING, {}, format="json")
        eur = summary(client)["eur"]
    assert "create_account" not in [name for name, _ in gateway.calls]
    assert [kw["value"] for name, kw in gateway.calls if name == "find_account_by_metadata"] == [
        str(operation.public_reference)]
    if found:
        assert answered.status_code == 400 and answered.data["code"] == "payout_country_unsupported"
        assert answered.data["account_country"] == "FR"
        assert eur["unavailable_reason"] == "payout_country_unsupported"
    else:
        assert answered.status_code == 409 and answered.data["code"] == "stripe_account_unresolved"
        assert eur["unavailable_reason"] == "stripe_account_unresolved"
    assert eur["available_actions"] == []
    assert eur_version(user).country == "DE" and eur_version(user).stripe_account_id is None


@override_settings(**BOTH_COUNTRIES)
def test_f1_binding_reads_the_accounts_readiness_as_it_stands(monkeypatch, configured_h4):
    """Round 4 should-fix and round 5 nit: the method takes the account's verdict as locked.

    An FR account stops being the destination when DE is declared, and FR is
    then declared again. Onboarding reads that standing account (pending)
    before it checks the platform; a webhook refresh makes it ready while the
    platform check runs, which leaves the method alone because the account is
    not its destination. The binding that follows projects the account as it
    now stands, read under its lock, not the copy read before the refresh.
    """
    from apps.finance.payout_accounts import refresh_account

    user = make_user("f1fresh@h6a.test", is_email_verified=True)
    client, account = onboarded(monkeypatch, user, "FR")
    declare(user, "DE")
    declare(user, "FR")
    method = TravelerPayoutMethod.objects.get(traveler=user, currency="EUR")
    assert method.status == "setup_required" and eur_version(user).stripe_account_id is None
    seen = []

    def webhook_refresh():
        refresh_account(account, gateway=FakeGateway(retrieve=ready_snapshot()))
        seen.append(TravelerPayoutMethod.objects.get(pk=method.pk).status)

    gateway = connect_gateway(monkeypatch, HookedGateway(
        during="platform_identity", hook=webhook_refresh, retrieve=ready_snapshot()))
    assert client.post(ONBOARDING, {}, format="json").status_code == 201
    assert seen == ["setup_required"]
    method.refresh_from_db()
    assert eur_version(user).stripe_account_id == account.pk
    assert method.status == "ready" and method.status_reason == ""
    assert "create_account" not in [name for name, _ in gateway.calls]


def test_f1_an_account_from_another_platform_is_history_not_the_setup(monkeypatch, configured_h4):
    """Round 4 should-fix: setup is decided in the configured platform only."""
    user = make_user("f1history@h6a.test", is_email_verified=True)
    client, old = onboarded(monkeypatch, user, "FR")
    with override_settings(STRIPE_CONNECT_PLATFORM_ACCOUNT_ID="acct_platform_two"):
        body = summary(client)
        eur = body["eur"]
        assert eur["state"] == "setup_required" and eur["unavailable_reason"] is None
        assert eur["available_actions"] == ["configure_eur"]
        # The method's own projection still shows the account it is bound to.
        projection = next(m for m in body["methods"] if m["currency"] == "EUR")
        assert projection["stripe_setup"]["status_reason"] == "platform_mismatch"
        # Round 5 should-fix: what the read does not offer, a direct call is
        # refused before Stripe, also the dashboard of a submitted account.
        StripePayoutAccount.objects.filter(pk=old.pk).update(details_submitted=True)
        unused = connect_gateway(monkeypatch, SecondPlatform(retrieve=ready_snapshot()))
        for route in ("refresh", "dashboard"):
            refused = client.post(f"/api/payouts/methods/stripe/{route}", {}, format="json")
            assert refused.status_code == 400, refused.data
            assert refused.data["code"] == "payout_setup_invalid"
        assert unused.calls == []
        gateway = connect_gateway(monkeypatch, SecondPlatform(
            create=snapshot(account_id="acct_1TESTsecondplatform")))
        created = client.post(ADVERTISED["configure_eur"], {}, format="json")
        assert created.status_code == 201, created.data
        # Now the second platform's own account is the setup's.
        assert "resume_eur_setup" in summary(client)["eur"]["available_actions"]
    bound = eur_version(user).stripe_account
    assert bound.pk != old.pk and bound.platform_id == "acct_platform_two"
    assert [name for name, _ in gateway.calls].count("create_account") == 1
    old.refresh_from_db()
    assert old.active


@override_settings(**BOTH_COUNTRIES)
def test_f1_an_unresolved_creation_outranks_a_closed_declared_country(monkeypatch, configured_h4):
    """Round 4 and 5 should-fixes: the read and onboarding give one answer, in one order.

    A closed rail (no country open), then the creation that waits for
    Finance, then the declared country.
    """
    from datetime import timedelta
    from django.utils import timezone

    user = make_user("f1precedence@h6a.test", is_email_verified=True)
    client = client_for(user)
    first = preference(client, "eur_only", country="FR")
    connect_gateway(monkeypatch, FakeGateway(create=ProviderUnavailable("timeout")))
    assert client.post(ONBOARDING, {}, format="json").status_code == 502
    PayoutProviderOperation.objects.filter(kind="account_create").update(
        first_request_at=timezone.now() - timedelta(days=2))
    gateway = connect_gateway(monkeypatch, FakeGateway())
    assert client.post(ONBOARDING, {}, format="json").status_code == 409
    searches = [name for name, _ in gateway.calls].count("find_account_by_metadata")
    with override_settings(STRIPE_CONNECT_ALLOWED_COUNTRIES=["DE"]):
        eur = summary(client)["eur"]
        assert eur["unavailable_reason"] == "stripe_account_unresolved"
        assert eur["available_actions"] == [] and eur["selectable"] is True
        refused = client.post(ONBOARDING, {}, format="json")
        assert refused.status_code == 409 and refused.data["code"] == "stripe_account_unresolved"
        # Choosing an open country stays possible; the creation still waits.
        revisions = summary(client)["revisions"]
        assert preference(client, "eur_only", eur=revisions["EUR"],
                          dzd=first.data["revisions"]["DZD"], country="DE").status_code == 200
        assert summary(client)["eur"]["unavailable_reason"] == "stripe_account_unresolved"
        again = client.post(ONBOARDING, {}, format="json")
        assert again.status_code == 409 and again.data["code"] == "stripe_account_unresolved"
    # Round 5 should-fix: with no country open at all, the closed rail is
    # the answer on both paths, ahead of the creation that waits.
    with override_settings(STRIPE_CONNECT_ALLOWED_COUNTRIES=[]):
        eur = summary(client)["eur"]
        assert eur["unavailable_reason"] == "stripe_connect_no_countries"
        assert eur["available_actions"] == []
        closed = client.post(ONBOARDING, {}, format="json")
        assert closed.status_code == 409, closed.data
        assert closed.data["code"] == "stripe_connect_no_countries"
        assert closed.data["account_country"] is None
    # Recorded once, the answer needs no further Stripe call.
    assert [name for name, _ in gateway.calls].count("find_account_by_metadata") == searches


@override_settings(**BOTH_COUNTRIES)
@pytest.mark.parametrize("change", ["away", "away_and_back"])
def test_f1_a_link_minted_while_the_preference_changed_is_never_handed_out(
    monkeypatch, configured_h4, change
):
    """Round 4 and 5 should-fixes: the link is checked against the version it was resolved on.

    Away: FR is declared while the DE link is minted. Away and back: FR, then
    DE again, and the standing DE account is bound to that newer version, so
    the account is the destination once more but of another declaration.

    The writers run on onboarding's own connection, which already holds the
    Traveler's account-setup lock, so they are not made to wait: this checks
    the guard under the method lock itself. A second session waits instead
    (`test_f1_payout_account_setup_race`).
    """
    from apps.finance.payout_accounts import ensure_account

    user = make_user(f"f1link-{change}@h6a.test", is_email_verified=True)
    client, account = onboarded(monkeypatch, user, "DE")
    issued = audit_actions(user, "payout_account.onboarding_link_issued")

    def meanwhile():
        declare(user, "FR")
        if change == "away_and_back":
            declare(user, "DE")
            ensure_account(actor=user, gateway=FakeGateway())

    gateway = connect_gateway(monkeypatch, HookedGateway(
        during="create_account_link", hook=meanwhile, create=snapshot(country="DE")))
    refused = client.post(ONBOARDING, {}, format="json")
    assert refused.status_code == 409, refused.data
    assert refused.data["code"] == "payout_preference_changed"
    assert "onboarding_url" not in refused.data and "connect.stripe.test" not in str(refused.data)
    assert "create_account_link" in [name for name, _ in gateway.calls]
    assert audit_actions(user, "payout_account.onboarding_link_issued") == issued
    version = eur_version(user)
    if change == "away":
        assert version.country == "FR" and version.stripe_account_id is None
    else:
        assert version.country == "DE" and version.stripe_account_id == account.pk
        assert PayoutMethodVersion.objects.filter(stripe_account=account).count() == 2


@override_settings(**BOTH_COUNTRIES)
def test_f1_two_calls_for_one_declaration_bind_once_and_both_succeed(monkeypatch, configured_h4):
    """Round 4 should-fix: the second answer for the same account is not a conflict.

    The inner call runs on the outer call's connection, inside its setup lock,
    so it is not made to wait: this checks `_record_account`'s "already the
    destination" answer itself. A second session waits for the first call and
    then finds its account (`test_f1_payout_account_setup_race`).
    """
    from apps.finance.payout_accounts import ensure_account

    user = make_user("f1twice@h6a.test", is_email_verified=True)
    client = client_for(user)
    preference(client, "eur_only", country="FR")
    inner = []
    outer = HookedGateway(
        during="create_account",
        hook=lambda: inner.append(ensure_account(actor=user, gateway=FakeGateway())),
        create=snapshot())
    connect_gateway(monkeypatch, outer)
    first = ensure_account(actor=user, gateway=outer)
    assert inner and inner[0].pk == first.pk
    assert audit_actions(user, "payout_account.bound", "payout_account.kept_unbound") == [
        "payout_account.bound"]
    assert eur_version(user).stripe_account_id == first.pk
    assert PayoutMethodVersion.objects.filter(stripe_account=first).count() == 1
    assert PayoutProviderOperation.objects.get(kind="account_create").status == "accepted"


@override_settings(**BOTH_COUNTRIES)
def test_f1_a_refused_declared_country_never_names_the_accounts_country(
    monkeypatch, configured_h4
):
    """Round 4 should-fix: `account_country` only when the account's own country closed."""
    user = make_user("f1dz@h6a.test", is_email_verified=True)
    client, _ = onboarded(monkeypatch, user, "FR")
    revisions = summary(client)["revisions"]
    refused = preference(client, "eur_only", eur=revisions["EUR"], dzd=revisions["DZD"],
                         country="DZ")
    assert refused.status_code == 400, refused.data
    assert refused.data["code"] == "payout_country_unsupported"
    assert refused.data["account_country"] is None
