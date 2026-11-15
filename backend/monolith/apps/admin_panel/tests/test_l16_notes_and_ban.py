"""Plan L16: internal notes, and banning an account from the person page."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from rest_framework_simplejwt.tokens import RefreshToken

from apps.admin_helper.tests.test_l15_keys import PAGES
from apps.admin_helper.tests.world import build_world, make_staff
from apps.admin_panel import staff_actions
from apps.admin_panel.models import AdminAuditLog, AdminNote
from apps.admin_panel.permissions import AdminRole, has_admin_permission
from apps.admin_panel.tests.two_step_helpers import staff_login
from apps.deals.models import Deal
from apps.finance.models import PaymentAttempt

BODY = "Called the sender: the parcel is a laptop, packed in its original box. L16-NOTE"


@override_settings(**PAGES)
class NotesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.world = build_world(prefix="l16-notes")
        cls.owner = make_staff("notes-owner@example.test", AdminRole.SUPER_ADMIN)

    def setUp(self):
        cache.clear()
        self.client = Client()
        staff_login(self.client, self.owner)

    def pages(self):
        world = self.world
        return {
            "deal": reverse("admin_console:deal-detail", args=(world.deal.pk,)),
            "dispute": reverse("admin_console:dispute-detail", args=(world.dispute.pk,)),
            "person": reverse("admin_console:user-detail", args=(world.sender.pk,)),
        }

    def ids(self):
        return {"deal": self.world.deal.pk, "dispute": self.world.dispute.pk, "person": self.world.sender.pk}

    def test_staff_add_a_note_on_each_page_and_it_is_audited(self):
        for target_type, page in self.pages().items():
            url = reverse("admin_console:note-add", args=(target_type, self.ids()[target_type]))
            response = self.client.post(url, {"body": BODY})
            assert response.status_code == 302 and response["Location"] == f"{page}#st-notes", target_type
            shown = self.client.get(page).content.decode()
            assert 'id="st-notes"' in shown and "L16-NOTE" in shown, target_type
            assert "Added by their AI helper" not in shown
        notes = AdminNote.objects.order_by("pk")
        assert [note.target_type for note in notes] == ["deal", "dispute", "person"]
        assert {note.author_id for note in notes} == {self.owner.pk}
        audits = AdminAuditLog.objects.filter(action="admin_note.added")
        assert audits.count() == 3 and {row.reason for row in audits} == {BODY}
        assert {row.after["characters"] for row in audits} == {len(BODY)}

    def test_a_note_cannot_be_edited_or_deleted(self):
        note = staff_actions.add_note(actor=self.owner, target_type="deal", target_id=self.world.deal.pk, body=BODY)
        note.body = "Changed."
        with self.assertRaises(Exception):
            note.save()
        with self.assertRaises(Exception):
            note.delete()
        assert AdminNote.objects.get(pk=note.pk).body == BODY

    def test_a_note_needs_text_and_a_real_record(self):
        url = reverse("admin_console:note-add", args=("deal", self.world.deal.pk))
        self.client.post(url, {"body": "   "})
        self.client.post(url, {"body": "x" * 2001})
        assert self.client.post(reverse("admin_console:note-add", args=("payout", 1)), {"body": BODY}).status_code == 404
        assert self.client.post(reverse("admin_console:note-add", args=("deal", 999_999)), {"body": BODY}).status_code == 404
        assert self.client.get(url).status_code == 405
        assert not AdminNote.objects.exists()

    def test_the_page_permission_decides_who_writes_a_note(self):
        expected = {target_type: set() for target_type in staff_actions.NOTE_TARGETS}
        for role in (AdminRole.OPS, AdminRole.FINANCE, AdminRole.TRUST, AdminRole.SUPPORT):
            staff = make_staff(f"notes-{role}@example.test", role)
            client = Client()
            staff_login(client, staff)
            for target_type, (_model, codes) in staff_actions.NOTE_TARGETS.items():
                may = any(has_admin_permission(staff, code) for code in codes)
                url = reverse("admin_console:note-add", args=(target_type, self.ids()[target_type]))
                response = client.post(url, {"body": f"{role} {target_type}"})
                assert response.status_code == (302 if may else 403), (role, target_type)
                if may:
                    expected[target_type].add(staff.pk)
        for target_type, authors in expected.items():
            written = set(AdminNote.objects.filter(target_type=target_type).values_list("author_id", flat=True))
            assert written == authors, target_type

    def test_notes_are_never_in_a_members_payload(self):
        staff_actions.add_note(actor=self.owner, target_type="deal", target_id=self.world.deal.pk, body=BODY)
        staff_actions.add_note(actor=self.owner, target_type="person", target_id=self.world.sender.pk, body=BODY)
        member = Client()
        token = RefreshToken.for_user(self.world.sender).access_token
        for path in (f"/api/deals/{self.world.deal.pk}", "/api/deals", "/api/me"):
            response = member.get(path, HTTP_AUTHORIZATION=f"Bearer {token}")
            assert "L16-NOTE" not in response.content.decode(), path


@override_settings(**PAGES)
class AccountBanTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.world = build_world(prefix="l16-ban")
        cls.owner = make_staff("ban-owner@example.test", AdminRole.SUPER_ADMIN)

    def setUp(self):
        cache.clear()
        self.client = Client()
        staff_login(self.client, self.owner)
        self.person = self.world.sender

    def ban_url(self, person=None):
        return reverse("admin_console:user-ban", args=((person or self.person).pk,))

    def test_a_super_admin_bans_then_restores_with_a_reason(self):
        page = self.client.get(reverse("admin_console:user-detail", args=(self.person.pk,))).content.decode()
        assert "Ban account" in page and self.ban_url() in page
        deal_status = Deal.objects.get(pk=self.world.deal.pk).status
        payment_status = PaymentAttempt.objects.get(pk=self.world.payment.pk).status

        assert self.client.post(self.ban_url(), {"intent": "ban", "reason": ""}).status_code == 200
        self.person.refresh_from_db()
        assert not self.person.is_banned

        response = self.client.post(self.ban_url(), {"intent": "ban", "reason": "Threatened the traveler in chat."})
        assert response.status_code == 302
        self.person.refresh_from_db()
        assert self.person.is_banned and not self.person.is_active
        banned = AdminAuditLog.objects.get(action="account.banned")
        assert banned.before == {"is_banned": False, "is_active": True}
        assert banned.after == {"is_banned": True, "is_active": False}
        assert banned.reason == "Threatened the traveler in chat."
        # A ban changes nothing else.
        assert Deal.objects.get(pk=self.world.deal.pk).status == deal_status
        assert PaymentAttempt.objects.get(pk=self.world.payment.pk).status == payment_status
        token = RefreshToken.for_user(self.person).access_token
        assert Client().get("/api/me", HTTP_AUTHORIZATION=f"Bearer {token}").status_code == 401

        page = self.client.get(reverse("admin_console:user-detail", args=(self.person.pk,))).content.decode()
        assert "Restore account" in page
        self.client.post(self.ban_url(), {"intent": "restore", "reason": "Apologised; agreed with the traveler."})
        self.person.refresh_from_db()
        assert not self.person.is_banned and self.person.is_active
        assert AdminAuditLog.objects.get(action="account.restored").after == {"is_banned": False, "is_active": True}

    def test_a_page_left_open_never_does_the_opposite(self):
        """Opened to ban; a colleague bans first; the stale page must not restore."""

        page = self.client.get(self.ban_url()).content.decode()
        assert 'name="intent" value="ban"' in page
        staff_actions.set_account_ban(actor=self.owner, user_id=self.person.pk, banned=True, reason="Banned first.")
        response = self.client.post(self.ban_url(), {"intent": "ban", "reason": "Threatened the traveler."}, follow=True)
        self.person.refresh_from_db()
        assert self.person.is_banned and not self.person.is_active
        assert not AdminAuditLog.objects.filter(action="account.restored").exists()
        shown = response.content.decode()
        assert "This account is already banned. Nothing was changed." in shown and "Restore account" in shown

    def test_staff_and_ones_own_account_are_refused(self):
        colleague = make_staff("ban-colleague@example.test", AdminRole.OPS)
        for person, words in ((colleague, "Staff access is changed on Staff &amp; access"),
                              (self.owner, "You cannot ban or restore your own account.")):
            page = self.client.get(self.ban_url(person)).content.decode()
            assert words in page and 'name="reason"' not in page
            self.client.post(self.ban_url(person), {"intent": "ban", "reason": "Testing."})
            person.refresh_from_db()
            assert not person.is_banned and person.is_active
        with self.assertRaises(staff_actions.StaffActionError):
            staff_actions.set_account_ban(actor=self.owner, user_id=colleague.pk, banned=True, reason="x")
        assert not AdminAuditLog.objects.filter(action="account.banned").exists()

    def test_only_manage_users_bans(self):
        for role in (AdminRole.OPS, AdminRole.FINANCE, AdminRole.TRUST, AdminRole.SUPPORT):
            staff = make_staff(f"ban-{role}@example.test", role)
            client = Client()
            staff_login(client, staff)
            assert client.post(self.ban_url(), {"intent": "ban", "reason": "No."}).status_code == 403, role
            with self.assertRaises(PermissionDenied):
                staff_actions.set_account_ban(actor=staff, user_id=self.person.pk, banned=True, reason="No.")
        self.person.refresh_from_db()
        assert not self.person.is_banned
