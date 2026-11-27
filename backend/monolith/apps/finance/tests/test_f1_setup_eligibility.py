"""F1 rule F-F: eligibility is decided on the locked user row.

One function answers "may this account write payout setup now": active, not
banned, a traveler role, a confirmed email (`payout_profiles.member_refusal`).
Every setup write asks it on the User row it has locked: the preference write
in `_method`, onboarding in `_plan_onboarding`, and once more in the last
transaction before a hosted link is handed out. A creation already committed
when a ban arrives is still recorded, so the account at Stripe is known here,
but it is not bound and no link is handed out.

A staff change that commits while a write waits for the User row is the one
that write reads, so these tests commit the change at the last moment before
the lock: inside the Stripe call that precedes it, or as the lock is asked for.
The real-thread version of the link handoff is in `test_f1_setup_freeze.py`.
"""

from unittest.mock import patch

import pytest
from django.test import override_settings

from apps.accounts.models import User
from apps.admin_panel.models import AdminAuditLog
from apps.finance.models import PayoutMethodVersion, PayoutProviderOperation, StripePayoutAccount

from .factories import make_user
from .test_phase8fh2_accounts import FakeGateway, snapshot
from .test_phase8fh4_manual import configured_h4  # noqa: F401
from .test_phase8fh6a_mobile import (  # noqa: F401
    BOTH_COUNTRIES,
    ONBOARDING,
    HookedGateway,
    client_for,
    connect_gateway,
    eur_version,
    preference,
    setup,
    summary,
)

pytestmark = pytest.mark.django_db


def staff_change(user, change):
    """What staff can do to a traveler's account, each committed by its own write."""
    from apps.admin_panel.permissions import AdminRole, assign_admin_roles
    from apps.admin_panel.staff_actions import set_account_ban

    if change == "ban":
        staff = make_user(f"staff-{user.pk}@f1.test", is_staff=True)
        assign_admin_roles(staff, (AdminRole.SUPER_ADMIN,), elevate_super_admin=True)
        set_account_ban(actor=staff, user_id=user.pk, banned=True, reason="F1 synthetic ban.")
    elif change == "role":
        User.objects.filter(pk=user.pk).update(role="sender")
    else:
        User.objects.filter(pk=user.pk).update(is_email_verified=False)


ANSWER = {"ban": "payout_traveler_required", "role": "payout_traveler_required",
          "email": "email_verification_required"}


def links_issued(user):
    return AdminAuditLog.objects.filter(
        actor=user, action="payout_account.onboarding_link_issued").count()


@override_settings(**BOTH_COUNTRIES)
@pytest.mark.parametrize("change", ["ban", "role", "email"])
def test_no_link_is_handed_out_after_eligibility_ends(monkeypatch, configured_h4, change):
    """Round-5 should-fix: eligibility is checked again at the link handoff."""
    user = make_user(f"f1link-{change}@f1.test", is_email_verified=True)
    client = client_for(user)
    assert preference(client, "eur_only").status_code == 200
    gateway = connect_gateway(monkeypatch, HookedGateway(
        during="create_account_link", hook=lambda: staff_change(user, change)))
    refused = client.post(ONBOARDING, {}, format="json")
    assert refused.status_code == 403, refused.data
    assert refused.data["code"] == ANSWER[change]
    assert "onboarding_url" not in refused.data
    assert "connect.stripe.test" not in str(refused.data)
    assert "create_account_link" in [name for name, _ in gateway.calls]
    assert links_issued(user) == 0
    # The account was bound before the change; it stays known and bound.
    account = StripePayoutAccount.objects.get(traveler=user)
    assert eur_version(user).stripe_account_id == account.pk


@override_settings(**BOTH_COUNTRIES)
@pytest.mark.parametrize("change", ["ban", "role", "email"])
def test_a_queued_onboarding_call_asks_stripe_for_nothing(monkeypatch, configured_h4, change):
    """Round-5 should-fix: the change commits while the call checks the platform."""
    user = make_user(f"f1queued-{change}@f1.test", is_email_verified=True)
    client = client_for(user)
    assert preference(client, "eur_only").status_code == 200
    gateway = connect_gateway(monkeypatch, HookedGateway(
        during="platform_identity", hook=lambda: staff_change(user, change)))
    refused = client.post(ONBOARDING, {}, format="json")
    assert refused.status_code == 403, refused.data
    assert refused.data["code"] == ANSWER[change]
    assert [name for name, _ in gateway.calls] == ["platform_identity"]
    assert not PayoutProviderOperation.objects.exists()
    assert not StripePayoutAccount.objects.filter(traveler=user).exists()


@override_settings(**BOTH_COUNTRIES)
@pytest.mark.parametrize("change", ["ban", "role", "email"])
def test_a_creation_committed_before_the_change_is_recorded_and_left_unbound(
    monkeypatch, configured_h4, change
):
    """The account Stripe opened is known here; it is not bound and no link is handed out."""
    user = make_user(f"f1inflight-{change}@f1.test", is_email_verified=True)
    client = client_for(user)
    assert preference(client, "eur_only").status_code == 200
    gateway = connect_gateway(monkeypatch, HookedGateway(
        during="create_account", hook=lambda: staff_change(user, change)))
    refused = client.post(ONBOARDING, {}, format="json")
    assert refused.status_code == 403, refused.data
    assert refused.data["code"] == ANSWER[change]
    account = StripePayoutAccount.objects.get(traveler=user)
    operation = PayoutProviderOperation.objects.get(kind="account_create")
    assert operation.status == "accepted" and operation.provider_object_id == account.provider_account_id
    assert not PayoutMethodVersion.objects.filter(stripe_account=account).exists()
    assert "create_account_link" not in [name for name, _ in gateway.calls]
    assert links_issued(user) == 0


@override_settings(**BOTH_COUNTRIES)
@pytest.mark.parametrize("change", ["ban", "role", "email"])
@pytest.mark.parametrize("route", ["post", "patch"])
def test_a_preference_write_reads_eligibility_on_the_row_it_locked(configured_h4, change, route):
    """Round-5 should-fix: the change commits while the write waits for the User row.

    PostgreSQL hands a waiting `FOR NO KEY UPDATE` the row as the change left
    it, so committing the change as the lock is asked for is that wait.
    """
    user = make_user(f"f1locked-{change}-{route}@f1.test", is_email_verified=True)
    client = client_for(user)
    saved = preference(client, "eur_only", country="FR")
    assert saved.status_code == 200, saved.data
    before = list(PayoutMethodVersion.objects.order_by("pk").values_list("pk", flat=True))
    lock = User.objects.select_for_update
    changed = []

    def changed_while_waiting(*args, **kwargs):
        if not changed:
            changed.append(True)
            staff_change(user, change)
        return lock(*args, **kwargs)

    with patch.object(User.objects, "select_for_update", changed_while_waiting):
        if route == "post":
            refused = client.post("/api/payouts/methods", {
                "currency": "EUR", "enabled": True, "country": "DE",
                "expected_revision": saved.data["revisions"]["EUR"],
                "consent_policy": "payout_profile_v1"}, format="json")
        else:
            refused = preference(client, "eur_only", eur=saved.data["revisions"]["EUR"],
                                 dzd=saved.data["revisions"]["DZD"], country="DE")
    assert changed
    assert refused.status_code == 403, refused.data
    assert refused.data["code"] == ANSWER[change]
    assert list(PayoutMethodVersion.objects.order_by("pk").values_list("pk", flat=True)) == before
    assert eur_version(user).country == "FR"


@pytest.mark.parametrize("change", ["role", "email"])
def test_the_read_names_the_same_reason_and_offers_nothing(configured_h4, change):
    """The read model asks the same function for the reason it reports.

    A ban also ends the session, so its reads answer 401 (round 2, finding 10).
    """
    user = make_user(f"f1read-{change}@f1.test", is_email_verified=True)
    client = client_for(user)
    assert preference(client, "both").status_code == 200
    staff_change(user, change)
    user.refresh_from_db()
    body = summary(client_for(user))
    assert body["setup"] == {"available": False, "unavailable_reason": ANSWER[change],
                             "preference_options": []}
    assert body["available_actions"] == []
    for rail in ("eur", "dzd"):
        assert body[rail]["unavailable_reason"] == ANSWER[change]


def test_unchanged_onboarding_still_links(monkeypatch, configured_h4):
    """Control: nothing changed, the link is handed out once."""
    user = make_user("f1control@f1.test", is_email_verified=True)
    client = client_for(user)
    assert preference(client, "eur_only").status_code == 200
    connect_gateway(monkeypatch, FakeGateway(create=snapshot()))
    linked = client.post(ONBOARDING, {}, format="json")
    assert linked.status_code == 201, linked.data
    assert links_issued(user) == 1
