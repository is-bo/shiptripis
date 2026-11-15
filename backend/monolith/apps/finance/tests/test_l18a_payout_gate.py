"""L18A item 6: writing payout setup needs a confirmed email.

Without it, a stranger who opened an account under someone else's address
could attach their own payout method and wait for the owner to claim the
account and earn. Every member route that writes payout setup (the
`ProfileView` and `ConnectView` families, unsafe methods) refuses with
`email_verification_required` and writes nothing; reads and staff routes are
unchanged.
"""

from __future__ import annotations

from django.apps import apps
from django.test import TestCase, override_settings
from django.urls import get_resolver, reverse
from rest_framework.test import APIClient

from apps.accounts.permissions import EMAIL_VERIFICATION_REQUIRED, EmailVerifiedToWrite
from apps.admin_panel.staff_api import StaffSessionMixin
from apps.finance.payout_account_api import ConnectView
from apps.finance.payout_profile_api import ProfileView

from .factories import make_user
from .test_phase8fh2_accounts import H2

WRITES = (
    ("patch", reverse("payout-methods"), {}),
    ("post", reverse("payout-methods"), {}),
    ("post", reverse("payout-dzd-profile"), {}),
    ("post", "/api/payouts/proofs", {}),
    ("post", reverse("payout-stripe-onboarding"), {"country": "FR"}),
    ("post", reverse("payout-stripe-refresh"), {}),
    ("post", reverse("payout-stripe-dashboard"), {}),
)
READS = (reverse("payout-methods"), reverse("payout-dzd-profile"))


def _finance_rows() -> dict[str, int]:
    return {
        model._meta.label: model.objects.count()
        for model in apps.get_app_config("finance").get_models()
    }


def _member_views():
    """Every routed view of the two families that a member (not staff) calls."""

    found = set()

    def walk(patterns):
        for pattern in patterns:
            if hasattr(pattern, "url_patterns"):
                walk(pattern.url_patterns)
                continue
            view = getattr(pattern.callback, "view_class", None)
            if (
                view is not None
                and issubclass(view, (ProfileView, ConnectView))
                and not issubclass(view, StaffSessionMixin)
            ):
                found.add(view)

    walk(get_resolver().url_patterns)
    return found


@override_settings(**H2)
class PayoutSetupGateTests(TestCase):
    def client_for(self, *, verified: bool) -> APIClient:
        user = make_user(
            f"l18a-payout-{'yes' if verified else 'no'}@example.com",
            is_email_verified=verified,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_every_write_is_refused_for_an_unconfirmed_account_and_writes_nothing(self):
        client = self.client_for(verified=False)
        before = _finance_rows()
        for method, url, body in WRITES:
            with self.subTest(method=method, url=url):
                response = getattr(client, method)(url, body, format="json")
                self.assertEqual(response.status_code, 403, response.content)
                self.assertEqual(response.json()["code"], EMAIL_VERIFICATION_REQUIRED)
        self.assertEqual(_finance_rows(), before)

    def test_reads_still_answer_for_an_unconfirmed_account(self):
        client = self.client_for(verified=False)
        for url in READS:
            with self.subTest(url=url):
                self.assertEqual(client.get(url).status_code, 200)

    def test_a_confirmed_account_passes_the_gate(self):
        client = self.client_for(verified=True)
        response = client.patch(
            reverse("payout-methods"), {}, format="json"
        )
        self.assertNotEqual(response.status_code, 403, response.content)

    def test_every_member_payout_view_carries_the_gate_and_staff_views_do_not(self):
        views = _member_views()
        self.assertTrue(views)
        for view in views:
            with self.subTest(view=view.__name__):
                self.assertIn(EmailVerifiedToWrite, view.permission_classes)
        for view in (ProfileView, ConnectView):
            for staff in view.__subclasses__():
                if issubclass(staff, StaffSessionMixin):
                    self.assertNotIn(EmailVerifiedToWrite, staff.permission_classes)
