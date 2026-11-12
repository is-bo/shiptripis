"""L2A staff controls: hiding a public profile, and the person's Discovery tab."""

from __future__ import annotations

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.admin_panel.models import AdminAuditLog
from apps.admin_panel.permissions import assign_admin_roles
from apps.core import channels
from apps.discovery.models import PublicProfile, RouteAlert, TravelerInterest
from apps.notifications.push import _PUSH_SPECS

from .support import STATIC_STORES, DiscoveryWorld, client_for


@override_settings(STORAGES=STATIC_STORES)
class ProfileVisibilityConsoleTests(DiscoveryWorld, TestCase):
    def setUp(self):
        self.build_discovery_world()
        self.profile = self.opt_in(self.traveler, (self.algiers, self.jijel))
        self.staff = User.objects.create_user(
            username="ops-l2a@example.com",
            email="ops-l2a@example.com",
            password="Sup3rStrongPass!",
            is_staff=True,
        )

    def login(self, role):
        assign_admin_roles(self.staff, [role])
        self.client.force_login(self.staff)

    def post(self, reason="Reported as a scam profile"):
        return self.client.post(
            reverse("admin_console:user-profile-visibility", args=(self.traveler.pk,)),
            {"reason": reason},
        )

    def people(self):
        return client_for(self.sender).get(reverse("discovery-people"), {"role": "sender"}).data

    def test_hiding_removes_the_profile_and_is_audited(self):
        self.login("super_admin")

        response = self.post()

        self.assertEqual(response.status_code, 302)
        self.profile.refresh_from_db()
        self.assertIsNotNone(self.profile.hidden_at)
        self.assertEqual(self.profile.hidden_by, self.staff)
        self.assertTrue(self.profile.is_discoverable)  # the member's choice is kept
        self.assertEqual(self.people()["results"], [])
        audit = AdminAuditLog.objects.get(action="discovery.profile_hidden")
        self.assertEqual(audit.reason, "Reported as a scam profile")
        self.assertEqual((audit.before, audit.after), ({"hidden": False}, {"hidden": True}))

    def test_showing_it_again_restores_the_members_own_choice(self):
        self.login("super_admin")
        self.post()

        self.post(reason="Reviewed, not a scam")

        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.hidden_at)
        self.assertEqual(self.profile.hidden_reason, "")
        self.assertEqual(len(self.people()["results"]), 1)
        self.assertTrue(AdminAuditLog.objects.filter(action="discovery.profile_unhidden").exists())

    def test_a_reason_is_required(self):
        self.login("super_admin")
        response = self.post(reason="")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(PublicProfile.objects.get(pk=self.profile.pk).hidden_at)

    def test_staff_without_manage_users_cannot_hide(self):
        self.login("support")
        self.assertEqual(self.post().status_code, 403)
        self.assertIsNone(PublicProfile.objects.get(pk=self.profile.pk).hidden_at)

    def test_the_discovery_tab_shows_the_profile_alerts_and_signals(self):
        RouteAlert.objects.create(
            user=self.traveler,
            watches=RouteAlert.Watches.REQUESTS,
            origin_locality=self.paris,
            destination_locality=self.jijel,
        )
        TravelerInterest.objects.create(
            delivery_request=self.request, journey=self.journey, traveler=self.traveler
        )
        self.login("support")
        url = reverse("admin_console:user-detail", args=(self.traveler.pk,))

        alerts = self.client.get(url, {"tab": "discovery"})
        interests = self.client.get(url, {"tab": "discovery", "view": "interests"})

        self.assertContains(alerts, "Visible")
        self.assertContains(alerts, "Algiers → Jijel")
        self.assertContains(alerts, "Paris → Jijel")
        self.assertNotContains(alerts, "Hide profile")  # support cannot act
        self.assertContains(interests, f"Request {self.request.pk}")
        self.assertContains(interests, "Sent")


class PushSpecTests(TestCase):
    def test_both_new_channels_have_marketplace_push_copy(self):
        for channel in (channels.DISCOVERY_ROUTE_ALERT, channels.DISCOVERY_TRAVELER_INTERESTED):
            with self.subTest(channel):
                category, android_channel, _, copy = _PUSH_SPECS[channel]
                # Non-essential: honours the member's marketplace switch.
                self.assertEqual(category, "marketplace")
                self.assertEqual(android_channel, "deliveries")
                self.assertEqual(set(copy), {"en", "fr", "ar"})
