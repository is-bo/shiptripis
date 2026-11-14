"""Plan L15: helper keys, their policy, and the console that makes them."""

from __future__ import annotations

import io
from copy import deepcopy
from datetime import timedelta
from unittest import mock

from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.admin_helper import keys
from apps.admin_helper.models import AdminHelperKey
from apps.admin_helper.policy import AdminHelperPolicy, InvalidAdminHelperPolicy
from apps.admin_panel import two_step
from apps.admin_panel.models import AdminAuditLog
from apps.admin_panel.ops_serializers import AdminSettingsCreateSerializer
from apps.admin_panel.permissions import AdminRole
from apps.admin_panel.tests.two_step_helpers import staff_login, verify_session
from apps.core.business_settings import activate_business_settings, get_active_business_settings
from apps.core.models import BusinessSettingsVersion

from .world import PAYOUT_KEYS, _FreshRequest, bearer, make_staff, new_key

GUIDE = "/api/admin/helper/v1/guide"
#: Console pages render without a collected static manifest, and the payout
#: pages with their keyring.
PAGES = {
    **{name: value for name, value in PAYOUT_KEYS.items() if name != "PAYOUT_PROFILES_ENABLED"},
    "STORAGES": {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
}


def set_helper_policy(**values) -> BusinessSettingsVersion:
    """Activate a new settings revision with these AI helper values."""

    active = get_active_business_settings()
    policy = deepcopy(active.policy)
    policy.setdefault("admin_helper", {}).update(values)
    latest = BusinessSettingsVersion.objects.order_by("-version").first()
    revision = BusinessSettingsVersion.objects.create(
        version=latest.version + 1,
        commission_rate_bps=active.commission_rate_bps,
        pricing_version=active.pricing_version,
        policy=policy,
    )
    return activate_business_settings(revision)


class PolicyTests(TestCase):
    def test_absent_means_the_defaults(self):
        policy = AdminHelperPolicy.from_section(None)
        assert policy == AdminHelperPolicy(
            enabled=True,
            read_key_hours=8,
            change_key_minutes=30,
            prepared_action_valid_hours=24,
            requests_per_minute=60,
        )

    def test_bounds_types_and_unknown_keys_are_refused(self):
        for section in (
            {"read_key_hours": 0},
            {"read_key_hours": 9},
            {"change_key_minutes": 4},
            {"change_key_minutes": 61},
            {"prepared_action_valid_hours": 73},
            {"requests_per_minute": 9},
            {"requests_per_minute": 301},
            {"requests_per_minute": True},
            {"read_key_hours": "8"},
            {"enabled": "yes"},
            {"enabeld": False},
            [],
        ):
            with self.assertRaises(InvalidAdminHelperPolicy, msg=section):
                AdminHelperPolicy.from_section(section)
        assert AdminHelperPolicy.from_section({"read_key_hours": 1}).read_key_hours == 1

    def test_a_settings_revision_with_a_bad_section_is_refused(self):
        active = get_active_business_settings()
        policy = deepcopy(active.policy)
        policy["admin_helper"] = {"enabled": True, "read_key_hours": 24}
        serializer = AdminSettingsCreateSerializer(
            data={
                "commission_rate_bps": active.commission_rate_bps,
                "pricing_version": active.pricing_version,
                "policy": policy,
                "reason": "Test",
            }
        )
        assert not serializer.is_valid()
        assert str(serializer.errors["policy"]["code"]) == InvalidAdminHelperPolicy.code


class KeyTests(TestCase):
    def setUp(self):
        self.admin = make_staff("keys-admin@example.test", AdminRole.OPS)
        self.client = Client()

    def call(self, plain):
        return self.client.get(GUIDE, **bearer(plain))

    def test_the_key_format_and_only_its_hash_is_stored(self):
        plain = new_key(self.admin)
        assert plain.startswith("wslr_") and len(plain) == 5 + 43
        key = AdminHelperKey.objects.get(admin=self.admin)
        assert key.key_hash == keys.digest(plain) and key.hint == plain[-4:]
        assert self.call(plain).status_code == 200
        # The whole database, as `dumpdata` sees it, never holds the plain key.
        out = io.StringIO()
        call_command("dumpdata", stdout=out)
        dump = out.getvalue()
        assert plain not in dump and plain[5:] not in dump
        assert keys.digest(plain) in dump

    def test_creating_a_key_needs_a_code_entered_in_the_last_10_minutes(self):
        stale = _FreshRequest(self.admin, at=timezone.now() - timedelta(minutes=11))
        with self.assertRaises(keys.HelperKeyError) as caught:
            keys.issue_key(admin=self.admin, kind=AdminHelperKey.Kind.READ, request=stale)
        assert caught.exception.code == keys.FRESH_TWO_STEP_CODE
        assert not AdminHelperKey.objects.exists()

    def test_only_the_signed_in_admin_creates_their_own_key(self):
        other = make_staff("keys-other@example.test", AdminRole.SUPER_ADMIN)
        with self.assertRaises(keys.PermissionDenied):
            keys.issue_key(
                admin=self.admin, kind=AdminHelperKey.Kind.READ, request=_FreshRequest(other)
            )
        member = User.objects.create_user(username="m@example.test", email="m@example.test")
        with self.assertRaises(keys.PermissionDenied):
            keys.issue_key(admin=member, kind=AdminHelperKey.Kind.READ, request=_FreshRequest(member))

    def test_a_new_key_stops_the_old_one(self):
        first = new_key(self.admin)
        second = new_key(self.admin)
        assert self.call(first).status_code == 401
        assert self.call(second).status_code == 200
        old = AdminHelperKey.objects.get(key_hash=keys.digest(first))
        assert old.revoked_reason == AdminHelperKey.StopReason.REPLACED
        issued = AdminAuditLog.objects.filter(action="ai_helper.key_created")
        assert sorted(len(row.metadata["replaced"]) for row in issued) == [0, 1]
        assert issued.get(target_id=str(AdminHelperKey.objects.get(key_hash=keys.digest(second)).pk)).metadata == {
            "replaced": [str(old.pk)]
        }
        assert "wslr_" not in str(list(AdminAuditLog.objects.values()))
        stopped = AdminAuditLog.objects.get(action="ai_helper.key_stopped")
        assert stopped.target_id == str(old.pk) and stopped.after["why"] == "replaced"

    def test_a_read_key_answers_at_7h59_and_not_at_8h_even_just_used(self):
        start = timezone.now()
        with mock.patch("django.utils.timezone.now", return_value=start):
            plain = new_key(self.admin)
        for elapsed, status in (
            (timedelta(hours=7, minutes=59), 200),
            (timedelta(hours=8) - timedelta(seconds=1), 200),
            (timedelta(hours=8), 401),
            (timedelta(hours=9), 401),
        ):
            with mock.patch("django.utils.timezone.now", return_value=start + elapsed):
                assert self.call(plain).status_code == status, elapsed
        key = AdminHelperKey.objects.get(admin=self.admin)
        # Use never extended it.
        assert key.expires_at == start + timedelta(hours=8)
        assert key.use_count == 2

    def test_the_expiry_comes_from_the_policy_at_creation(self):
        set_helper_policy(read_key_hours=2)
        new_key(self.admin)
        key = AdminHelperKey.objects.get(admin=self.admin)
        assert key.expires_at - key.created_at == timedelta(hours=2)
        set_helper_policy(read_key_hours=8)
        key.refresh_from_db()
        assert key.expires_at - key.created_at == timedelta(hours=2)

    def test_switching_off_stops_every_key_for_good(self):
        plain = new_key(self.admin)
        other = new_key(make_staff("keys-trust@example.test", AdminRole.TRUST))
        revision = set_helper_policy(enabled=False)
        assert self.call(plain).status_code == 401
        assert self.call(other).status_code == 401
        assert set(AdminHelperKey.objects.values_list("revoked_reason", flat=True)) == {
            AdminHelperKey.StopReason.SWITCHED_OFF
        }
        # One audit row for the event, with the number of keys it stopped.
        audit = AdminAuditLog.objects.get(action=keys.SWITCHED_OFF_ACTION)
        assert (audit.target_type, audit.target_id) == ("core.businesssettingsversion",
                                                        str(revision.pk))
        assert audit.metadata["keys_stopped"] == 2
        assert not AdminAuditLog.objects.filter(action="ai_helper.key_stopped").exists()
        # Saving another revision while off stops nothing and writes nothing.
        set_helper_policy(enabled=False, requests_per_minute=30)
        assert AdminAuditLog.objects.filter(action=keys.SWITCHED_OFF_ACTION).count() == 1
        with self.assertRaises(keys.HelperKeyError) as caught:
            new_key(self.admin)
        assert caught.exception.code == keys.DISABLED_CODE
        set_helper_policy(enabled=True)
        assert self.call(plain).status_code == 401
        assert self.call(new_key(self.admin)).status_code == 200

    def test_the_stop_rolls_back_with_an_activation_that_fails(self):
        from django.db import transaction

        plain = new_key(self.admin)
        with self.assertRaises(RuntimeError), transaction.atomic():
            set_helper_policy(enabled=False)
            raise RuntimeError("The rest of the save failed.")
        assert get_active_business_settings().policy.get("admin_helper", {}).get("enabled", True)
        assert AdminHelperKey.objects.get(admin=self.admin).revoked_at is None
        assert not AdminAuditLog.objects.filter(action=keys.SWITCHED_OFF_ACTION).exists()
        assert self.call(plain).status_code == 200

    def test_every_call_reads_the_switch_itself(self):
        # The switch flipped without the activation hook: the key is not
        # stopped, yet it cannot act.
        plain = new_key(self.admin)
        active = get_active_business_settings()
        policy = deepcopy(active.policy)
        policy.setdefault("admin_helper", {})["enabled"] = False
        BusinessSettingsVersion.objects.filter(pk=active.pk).update(policy=policy)
        assert AdminHelperKey.objects.get(admin=self.admin).revoked_at is None
        assert self.call(plain).status_code == 401

    def test_an_unreadable_policy_refuses_every_key(self):
        plain = new_key(self.admin)
        active = get_active_business_settings()
        policy = deepcopy(active.policy)
        policy["admin_helper"] = {"read_key_hours": 99}
        BusinessSettingsVersion.objects.filter(pk=active.pk).update(policy=policy)
        assert self.call(plain).status_code == 401

    def test_an_admin_stops_their_own_key(self):
        plain = new_key(self.admin)
        key = AdminHelperKey.objects.get(admin=self.admin)
        keys.stop_key(actor=self.admin, key_id=key.pk)
        assert self.call(plain).status_code == 401
        key.refresh_from_db()
        assert key.revoked_reason == AdminHelperKey.StopReason.STOPPED
        # Stopping it again changes nothing and writes nothing.
        audits = AdminAuditLog.objects.count()
        keys.stop_key(actor=self.admin, key_id=key.pk)
        assert AdminAuditLog.objects.count() == audits

    def test_only_a_super_admin_stops_another_admins_key_and_with_a_reason(self):
        new_key(self.admin)
        key = AdminHelperKey.objects.get(admin=self.admin)
        finance = make_staff("keys-finance@example.test", AdminRole.FINANCE)
        with self.assertRaises(keys.PermissionDenied):
            keys.stop_key(actor=finance, key_id=key.pk, reason="No.")
        owner = make_staff("keys-owner@example.test", AdminRole.SUPER_ADMIN)
        with self.assertRaises(keys.HelperKeyError) as caught:
            keys.stop_key(actor=owner, key_id=key.pk, reason="  ")
        assert caught.exception.code == keys.REASON_REQUIRED_CODE
        keys.stop_key(actor=owner, key_id=key.pk, reason="Laptop lost.")
        key.refresh_from_db()
        assert key.revoked_reason == AdminHelperKey.StopReason.STOPPED_BY_SUPER_ADMIN
        audit = AdminAuditLog.objects.get(action="ai_helper.key_stopped")
        assert (audit.actor, audit.reason) == (owner, "Laptop lost.")

    def test_a_two_step_reset_stops_their_keys(self):
        plain = new_key(self.admin)
        owner = make_staff("keys-reset-owner@example.test", AdminRole.SUPER_ADMIN)
        result = two_step.reset(actor=owner, target=self.admin, reason="Lost phone.")
        assert result["sessions_ended"] == 1  # The session that created the key.
        assert self.call(plain).status_code == 401
        key = AdminHelperKey.objects.get(admin=self.admin)
        assert key.revoked_reason == AdminHelperKey.StopReason.TWO_STEP_RESET
        audit = AdminAuditLog.objects.get(action="admin.two_step_reset")
        assert audit.metadata["helper_keys_stopped"] == 1
        assert result["helper_keys_stopped"] == 1
        assert not AdminAuditLog.objects.filter(action="ai_helper.key_stopped").exists()

    def test_a_creation_that_waited_on_a_reset_is_refused(self):
        # The reset won the lock and ended the session that entered the code;
        # the creation, checked again under the same lock, makes no key.
        request = _FreshRequest(self.admin)
        owner = make_staff("keys-race-owner@example.test", AdminRole.SUPER_ADMIN)
        assert two_step.reset(actor=owner, target=self.admin, reason="Lost phone.")[
            "sessions_ended"
        ] == 1
        with self.assertRaises(keys.HelperKeyError) as caught:
            keys.issue_key(admin=self.admin, kind=AdminHelperKey.Kind.READ, request=request)
        assert caught.exception.code == keys.FRESH_TWO_STEP_CODE
        assert not AdminHelperKey.objects.filter(admin=self.admin).exists()

    def test_a_creation_reads_the_switch_again_under_its_lock(self):
        # A switch-off committed after the first, unlocked read: the locked
        # read sees it, so no key appears that the switch-off could not stop.
        on = AdminHelperPolicy.from_section({})
        set_helper_policy(enabled=False)
        with mock.patch.object(keys, "current_policy", return_value=on):
            with self.assertRaises(keys.HelperKeyError) as caught:
                new_key(self.admin)
        assert caught.exception.code == keys.DISABLED_CODE
        assert not AdminHelperKey.objects.exists()

    def test_the_server_reset_for_the_last_super_admin_stops_their_keys(self):
        owner = make_staff("keys-last-owner@example.test", AdminRole.SUPER_ADMIN)
        plain = new_key(owner)
        out = io.StringIO()
        call_command("reset_admin_two_step", owner.email, reason="Lost phone", stdout=out)
        assert self.call(plain).status_code == 401
        key = AdminHelperKey.objects.get(admin=owner)
        assert key.revoked_reason == AdminHelperKey.StopReason.TWO_STEP_RESET
        audit = AdminAuditLog.objects.get(action="admin.two_step_reset")
        assert audit.actor is None and audit.metadata["helper_keys_stopped"] == 1
        assert "1 AI helper key(s) ended" in out.getvalue()

    def test_the_audit_log_names_the_ai_helper(self):
        from apps.core.admin_display import humanize_action, humanize_object

        new_key(self.admin)
        audit = AdminAuditLog.objects.get(action="ai_helper.key_created")
        assert humanize_action(audit.action) == "AI helper key created"
        assert humanize_object(audit.target_type) == "AI helper key"
        assert humanize_action(keys.SWITCHED_OFF_ACTION) == "AI helper keys stopped"

    def test_one_live_key_per_admin_and_kind_is_a_database_rule(self):
        from django.db import IntegrityError, transaction

        new_key(self.admin)
        live = AdminHelperKey.objects.get(admin=self.admin)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AdminHelperKey.objects.create(
                admin=self.admin,
                kind=AdminHelperKey.Kind.READ,
                key_hash="0" * 64,
                hint="0000",
                created_at=live.created_at,
                expires_at=live.expires_at,
            )


@override_settings(**PAGES)
class ConsoleTests(TestCase):
    def setUp(self):
        self.admin = make_staff("console-admin@example.test", AdminRole.SUPPORT)
        self.client = Client()
        staff_login(self.client, self.admin)

    def create(self, **data):
        return self.client.post(reverse("admin_console:ai-helper-create"), data)

    def test_the_card_offers_a_read_key_and_none_exists(self):
        page = self.client.get(reverse("admin_console:overview")).content.decode()
        assert "AI helper" in page and "Create read key (8 hours)" in page
        assert "None" in page and "Stop key" not in page
        assert "change key" not in page.lower()

    def test_creating_shows_the_line_once(self):
        response = self.create()
        assert response.status_code == 200
        assert "no-store" in response["Cache-Control"]
        page = response.content.decode()
        key = AdminHelperKey.objects.get(admin=self.admin)
        line = page.split('id="st-helper-line" translate="no">', 1)[1].split("</code>", 1)[0]
        assert line.startswith("/wassla http://testserver/api/admin/helper/v1 wslr_")
        plain = self.plain_from(response)
        assert keys.digest(plain) == key.key_hash
        assert "It will not be shown again." in page
        # The key works, and no later page shows it.
        assert Client().get(GUIDE, **bearer(plain)).status_code == 200
        for url in (reverse("admin_console:overview"), reverse("admin_console:ai-helper")):
            later = self.client.get(url).content.decode()
            assert plain not in later
            assert "Active until" in later and key.hint in later
        assert plain not in str(dict(self.client.session))

    def test_creating_from_a_stale_session_asks_for_a_code_first(self):
        verify_session(self.client, self.admin, at=timezone.now() - timedelta(minutes=11))
        response = self.create()
        assert response.status_code == 302
        assert response["Location"].startswith(reverse("admin_console:two-step-verify"))
        assert not AdminHelperKey.objects.exists()

    def test_creating_is_post_only(self):
        assert self.client.get(reverse("admin_console:ai-helper-create")).status_code == 405

    def test_stopping_from_the_card(self):
        self.create()
        key = AdminHelperKey.objects.get(admin=self.admin)
        response = self.client.post(reverse("admin_console:ai-helper-stop", args=[key.pk]))
        assert response.status_code == 302
        key.refresh_from_db()
        assert key.revoked_reason == AdminHelperKey.StopReason.STOPPED

    def test_switched_off_the_card_says_so_and_offers_nothing(self):
        set_helper_policy(enabled=False)
        page = self.client.get(reverse("admin_console:overview")).content.decode()
        assert "The AI helper is switched off" in page
        assert reverse("admin_console:ai-helper-create") not in page
        response = self.create()
        assert response.status_code == 302 and not AdminHelperKey.objects.exists()

    def plain_from(self, response) -> str:
        page = response.content.decode()
        line = page.split('id="st-helper-line" translate="no">', 1)[1].split("</code>", 1)[0]
        return line.rsplit(" ", 1)[1]

    def test_the_page_lists_my_keys_and_calls_without_what_was_searched(self):
        plain = self.plain_from(self.create())
        Client().get("/api/admin/helper/v1/search?q=secret-words", **bearer(plain))
        response = self.client.get(reverse("admin_console:ai-helper"))
        assert response.status_code == 200 and response["Cache-Control"] == "no-store"
        page = response.content.decode()
        assert AdminHelperKey.objects.get(admin=self.admin).hint in page
        assert "GET /api/admin/helper/v1/search" in page and "secret-words" not in page

    def test_a_super_admin_sees_and_stops_other_keys_never_the_key(self):
        plain = new_key(self.admin)
        owner = make_staff("console-owner@example.test", AdminRole.SUPER_ADMIN)
        client = Client()
        staff_login(client, owner)
        page = client.get(reverse("admin_console:ai-helper")).content.decode()
        key = AdminHelperKey.objects.get(admin=self.admin)
        assert "Other admins' live keys" in page and key.hint in page and plain not in page
        refused = client.post(reverse("admin_console:ai-helper-stop", args=[key.pk]), {"from": "page"})
        assert refused.status_code == 302
        key.refresh_from_db()
        assert key.revoked_at is None
        client.post(
            reverse("admin_console:ai-helper-stop", args=[key.pk]),
            {"from": "page", "reason": "Left the company."},
        )
        key.refresh_from_db()
        assert key.revoked_reason == AdminHelperKey.StopReason.STOPPED_BY_SUPER_ADMIN

    def test_others_do_not_see_or_stop_other_keys(self):
        owner = make_staff("console-owner2@example.test", AdminRole.SUPER_ADMIN)
        new_key(owner)
        key = AdminHelperKey.objects.get(admin=owner)
        page = self.client.get(reverse("admin_console:ai-helper")).content.decode()
        assert "Other admins' live keys" not in page and key.hint not in page
        self.client.post(reverse("admin_console:ai-helper-stop", args=[key.pk]), {"reason": "x"})
        key.refresh_from_db()
        assert key.revoked_at is None


@override_settings(**PAGES)
class SettingsFormTests(TestCase):
    def setUp(self):
        self.owner = make_staff("settings-owner@example.test", AdminRole.SUPER_ADMIN)
        self.client = Client()
        staff_login(self.client, self.owner)

    def save(self, **overrides):
        data = {
            "action": "admin_helper",
            "enabled": "on",
            "read_key_hours": 8,
            "change_key_minutes": 30,
            "prepared_action_valid_hours": 24,
            "requests_per_minute": 60,
            "reason": "Test change.",
            "confirm": "on",
        }
        data.update(overrides)
        return self.client.post(reverse("admin_console:settings"), data)

    def test_the_form_is_on_the_settings_page(self):
        page = self.client.get(reverse("admin_console:settings")).content.decode()
        assert 'id="st-settings-helper"' in page and "Save AI helper settings" in page

    def test_saving_writes_an_audited_revision(self):
        response = self.save(requests_per_minute=120)
        assert response.status_code == 302
        assert get_active_business_settings().policy["admin_helper"]["requests_per_minute"] == 120
        audit = AdminAuditLog.objects.filter(action="settings.version_created").latest("pk")
        assert audit.after["admin_helper.requests_per_minute"] == 120

    def test_switching_off_from_the_form_stops_every_key(self):
        plain = new_key(self.owner)
        data = self.save(enabled="")
        assert data.status_code == 302
        assert Client().get(GUIDE, **bearer(plain)).status_code == 401
        key = AdminHelperKey.objects.get(admin=self.owner)
        assert key.revoked_reason == AdminHelperKey.StopReason.SWITCHED_OFF
        stopped = AdminAuditLog.objects.get(action=keys.SWITCHED_OFF_ACTION)
        assert stopped.actor == self.owner and stopped.metadata["keys_stopped"] == 1

    def test_out_of_bounds_values_are_refused(self):
        before = get_active_business_settings().pk
        self.save(read_key_hours=9)
        assert get_active_business_settings().pk == before

    def test_a_role_without_manage_settings_cannot_save(self):
        support = make_staff("settings-support@example.test", AdminRole.SUPPORT)
        client = Client()
        staff_login(client, support)
        response = client.post(reverse("admin_console:settings"), {"action": "admin_helper"})
        assert response.status_code == 403
