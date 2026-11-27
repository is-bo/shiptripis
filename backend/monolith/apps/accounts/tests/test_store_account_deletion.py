"""A member deletes their own account (store readiness, App Store 5.1.1(v)).

`apps.accounts.deletion` is the rule: what must be finished first, what is
wiped, what stays, and the revocation of Sign in with Apple before anything is
deleted. Nothing here reaches Apple: its two endpoints are answered locally.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import apple_revoke
from apps.accounts.deletion import (
    BLOCKER_DELIVERIES,
    BLOCKER_JOURNEYS,
    BLOCKER_REQUESTS,
    DELETED_EMAIL_DOMAIN,
)
from apps.accounts.models import OAuthIdentity, SignInSession, User
from apps.core.tests.l10_world import DRIVE, AcceptanceWorld, api
from apps.discovery.models import PublicProfile
from apps.discovery.tests.support import STATIC_STORES
from apps.notifications.models import Notification, OutboundMessage, PushDevice
from apps.notifications.tests.factories import push_device, signed_in

DELETION = reverse("me-deletion")
PASSWORD = "Correct-horse-42"

APPLE_KEY = ec.generate_private_key(ec.SECP256R1())
APPLE_KEY_PEM = APPLE_KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
APPLE_SETTINGS = {
    "APPLE_SIGN_IN_CLIENT_IDS": ["eu.wassla.app"],
    "APPLE_TEAM_ID": "TEAM123456",
    "APPLE_SIGN_IN_KEY_ID": "KEY1234567",
    "APPLE_SIGN_IN_PRIVATE_KEY": APPLE_KEY_PEM,
}


def apple_id_token(subject="a-1"):
    """The identity token Apple's token endpoint returns with the refresh token."""

    return jwt.encode(
        {"iss": "https://appleid.apple.com", "aud": "eu.wassla.app", "sub": subject},
        "signed-by-apple",
        algorithm="HS256",
    )


def apple_answers(*responses):
    """Patch the two calls to Apple; each response is (status, json body)."""

    answers = []
    for status_code, body in responses:
        answer = MagicMock(status_code=status_code)
        answer.json.return_value = body
        answers.append(answer)
    return patch.object(apple_revoke.requests, "post", side_effect=answers)


@override_settings(STORAGES=STATIC_STORES)
class AccountDeletionTests(AcceptanceWorld, TestCase):
    def setUp(self):
        cache.clear()
        self.build_acceptance_world()
        self.member = self.person("leaving@example.com", verified=False)
        self.member.full_name = "Nadia Leaving"
        self.member.phone = "+213555000111"
        self.member.set_password(PASSWORD)
        self.member.save()

    def delete(self, user, **body):
        return api(user).post(DELETION, body, format="json")

    # -- what the app shows first -----------------------------------------

    def test_the_check_lists_nothing_for_a_member_with_nothing_open(self):
        response = api(self.member).get(DELETION)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {
                "blockers": [],
                "password_required": True,
                "apple_authorization_required": False,
            },
        )

    def test_a_signed_out_visitor_cannot_ask(self):
        self.assertEqual(APIClient().get(DELETION).status_code, 401)
        self.assertEqual(APIClient().post(DELETION, {}).status_code, 401)

    # -- deleting ----------------------------------------------------------

    def test_a_wrong_password_deletes_nothing(self):
        response = self.delete(self.member, password="not-it")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "password_incorrect")
        self.member.refresh_from_db()
        self.assertTrue(self.member.is_active)
        self.assertEqual(self.member.email, "leaving@example.com")

    def test_deleting_empties_the_account_and_ends_every_session(self):
        session = signed_in(self.member)
        push_device(
            user=self.member,
            installation_id="2b1f7f0e-5a0c-4d1e-9a51-3f7e5a7c9d10",
            platform="android",
            token="push-token-of-the-member",
            token_fingerprint="f" * 64,
            active=True,
        )
        Notification.objects.create(recipient=self.member, channel="x", event_id="e1")
        sent = OutboundMessage.objects.create(
            key="sent-before",
            kind=OutboundMessage.Kind.SECURITY_EVENT,
            to_email="leaving@example.com",
            recipient_user=self.member,
            status=OutboundMessage.Status.DISPATCHED,
            dispatched_at=timezone.now(),
        )
        PublicProfile.objects.create(user=self.member)
        OAuthIdentity.objects.create(
            user=self.member, provider=OAuthIdentity.Provider.GOOGLE, subject="g-1"
        )

        response = self.delete(self.member, password=PASSWORD)

        self.assertEqual(response.status_code, 204)
        self.member.refresh_from_db()
        self.assertFalse(self.member.is_active)
        self.assertIsNotNone(self.member.deleted_at)
        self.assertEqual(
            self.member.email, f"deleted-{self.member.pk}@{DELETED_EMAIL_DOMAIN}"
        )
        self.assertEqual(
            (self.member.full_name, self.member.phone, self.member.wilaya), ("", "", "")
        )
        self.assertFalse(self.member.has_usable_password())
        self.assertFalse(
            SignInSession.objects.filter(
                user=self.member, ended_at__isnull=True
            ).exists()
        )
        self.assertEqual(
            APIClient()
            .post("/api/auth/refresh", {"refresh": session["refresh"]}, format="json")
            .status_code,
            401,
        )
        self.assertFalse(PushDevice.objects.filter(user=self.member).exists())
        self.assertFalse(Notification.objects.filter(recipient=self.member).exists())
        self.assertFalse(PublicProfile.objects.filter(user=self.member).exists())
        self.assertFalse(OAuthIdentity.objects.filter(user=self.member).exists())
        sent.refresh_from_db()
        self.assertEqual(sent.to_email, self.member.email)

    def test_the_old_session_and_password_no_longer_open_anything(self):
        refresh = signed_in(self.member)["refresh"]
        self.assertEqual(self.delete(self.member, password=PASSWORD).status_code, 204)

        renewed = APIClient().post(reverse("auth-refresh"), {"refresh": refresh})
        self.assertEqual(renewed.status_code, 401)
        sign_in = APIClient().post(
            reverse("auth-sign-in"),
            {"email": "leaving@example.com", "password": PASSWORD},
            format="json",
        )
        self.assertEqual(sign_in.status_code, 400)

    def test_the_email_is_free_to_sign_up_again(self):
        self.assertEqual(self.delete(self.member, password=PASSWORD).status_code, 204)
        again = APIClient().post(
            reverse("auth-sign-up"),
            {
                "email": "leaving@example.com",
                "password": "Another-strong-pass-7",
                "full_name": "Nadia Again",
                "phone": "+213555000222",
            },
            format="json",
        )
        self.assertEqual(again.status_code, 201, again.data)
        self.assertNotEqual(again.data["user"]["id"], self.member.pk)

    def test_a_second_request_answers_that_the_account_is_gone(self):
        self.assertEqual(self.delete(self.member, password=PASSWORD).status_code, 204)
        self.member.refresh_from_db()
        # The access token of the deleted account is refused by authentication
        # itself; a request that slipped in before it is answered as gone.
        self.assertEqual(self.delete(self.member).status_code, 410)

    def test_staff_cannot_ban_or_restore_a_deleted_account(self):
        from apps.admin_panel import staff_actions

        self.assertEqual(self.delete(self.member, password=PASSWORD).status_code, 204)
        self.member.refresh_from_db()
        staff = User.objects.create_superuser(
            email="admin@example.com", username="admin-x", password="Admin-pass-42"
        )
        for banned in (True, False):
            refusal = staff_actions.ban_refusal(staff, self.member, banned=banned)
            self.assertEqual(refusal.code, "account_deleted")
        self.assertFalse(User.objects.get(pk=self.member.pk).is_active)

    def test_an_account_without_a_password_needs_none(self):
        self.member.set_unusable_password()
        self.member.save()
        self.assertFalse(api(self.member).get(DELETION).data["password_required"])
        self.assertEqual(self.delete(self.member).status_code, 204)

    def test_staff_accounts_are_not_deleted_from_the_app(self):
        response = self.delete(self.trust)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "staff_account")
        self.trust.refresh_from_db()
        self.assertTrue(self.trust.is_active)

    # -- what must be finished first ---------------------------------------

    def test_a_published_journey_and_an_open_delivery_block_deletion(self):
        depart = self.now + timedelta(hours=4)
        journey = self.post_trip(
            [self.leg_payload(DRIVE, self.algiers, self.setif, depart, hours=3)]
        )
        self.publish(journey)
        self.sender.set_password(PASSWORD)
        self.sender.save()
        self.traveler.set_password(PASSWORD)
        self.traveler.save()

        response = self.delete(self.traveler, password=PASSWORD)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "account_deletion_blocked")
        self.assertEqual(response.data["blockers"], [BLOCKER_JOURNEYS])

        leg = journey.legs.get()
        parcel = self.post_parcel(
            self.algiers,
            self.setif,
            ready_from=depart - timedelta(hours=2),
            ready_until=depart + timedelta(minutes=30),
            deliver_by=depart + timedelta(hours=12),
        )
        self.pay_deposit(parcel)
        deal = self.accept(self.propose(parcel, journey, leg, leg, 3_000))
        self.pay_balance(deal)

        check = api(self.sender).get(DELETION).data
        self.assertEqual(check["blockers"], [BLOCKER_DELIVERIES, BLOCKER_REQUESTS])
        response = self.delete(self.sender, password=PASSWORD)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.data["blockers"], [BLOCKER_DELIVERIES, BLOCKER_REQUESTS]
        )
        self.sender.refresh_from_db()
        self.assertTrue(self.sender.is_active)

    # -- Sign in with Apple --------------------------------------------------

    def link_apple(self):
        OAuthIdentity.objects.create(
            user=self.member, provider=OAuthIdentity.Provider.APPLE, subject="a-1"
        )

    def test_an_apple_member_must_send_a_fresh_authorization(self):
        self.link_apple()
        self.assertTrue(
            api(self.member).get(DELETION).data["apple_authorization_required"]
        )
        response = self.delete(self.member, password=PASSWORD)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "apple_authorization_required")

    @override_settings(**APPLE_SETTINGS)
    def test_apple_is_revoked_before_the_account_is_deleted(self):
        self.link_apple()
        with apple_answers(
            (
                200,
                {
                    "refresh_token": "apple-refresh",
                    "access_token": "apple-access",
                    "id_token": apple_id_token(),
                },
            ),
            (200, {}),
        ) as post:
            response = self.delete(
                self.member, password=PASSWORD, apple_authorization_code="code-1"
            )

        self.assertEqual(response.status_code, 204)
        exchange, revoke = post.call_args_list
        self.assertEqual(exchange.args[0], apple_revoke.TOKEN_URL)
        self.assertEqual(exchange.kwargs["data"]["code"], "code-1")
        self.assertEqual(exchange.kwargs["data"]["grant_type"], "authorization_code")
        self.assertEqual(revoke.args[0], apple_revoke.REVOKE_URL)
        self.assertEqual(revoke.kwargs["data"]["token"], "apple-refresh")
        self.assertEqual(revoke.kwargs["data"]["token_type_hint"], "refresh_token")
        for call in (exchange, revoke):
            self.assertEqual(call.kwargs["data"]["client_id"], "eu.wassla.app")
            self.assertEqual(call.kwargs["timeout"], apple_revoke.TIMEOUT_SECONDS)
            secret = call.kwargs["data"]["client_secret"]
            self.assertEqual(jwt.get_unverified_header(secret)["kid"], "KEY1234567")
            claims = jwt.decode(
                secret,
                APPLE_KEY.public_key(),
                algorithms=["ES256"],
                audience="https://appleid.apple.com",
            )
            self.assertEqual(claims["iss"], "TEAM123456")
            self.assertEqual(claims["sub"], "eu.wassla.app")
        self.member.refresh_from_db()
        self.assertFalse(self.member.is_active)

    @override_settings(**APPLE_SETTINGS)
    def test_a_code_apple_refuses_leaves_the_account_untouched(self):
        self.link_apple()
        with apple_answers((400, {"error": "invalid_grant"})):
            response = self.delete(
                self.member, password=PASSWORD, apple_authorization_code="used"
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "apple_authorization_refused")
        self.member.refresh_from_db()
        self.assertTrue(self.member.is_active)

    @override_settings(**APPLE_SETTINGS)
    def test_a_code_for_another_apple_id_revokes_nothing_and_deletes_nothing(self):
        self.link_apple()
        with apple_answers(
            (
                200,
                {"refresh_token": "theirs", "id_token": apple_id_token("someone-else")},
            ),
        ) as post:
            response = self.delete(
                self.member, password=PASSWORD, apple_authorization_code="their-code"
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "apple_authorization_refused")
        self.assertEqual(post.call_count, 1)
        self.assertTrue(User.objects.get(pk=self.member.pk).is_active)

    @override_settings(**APPLE_SETTINGS)
    def test_apple_refusing_the_server_credentials_is_unavailable_not_refused(self):
        self.link_apple()
        with apple_answers((400, {"error": "invalid_client"})):
            response = self.delete(
                self.member, password=PASSWORD, apple_authorization_code="code-1"
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["code"], "apple_revoke_unavailable")
        self.assertTrue(User.objects.get(pk=self.member.pk).is_active)

    @override_settings(**APPLE_SETTINGS)
    def test_apple_unreachable_leaves_the_account_untouched(self):
        self.link_apple()
        with patch.object(
            apple_revoke.requests,
            "post",
            side_effect=apple_revoke.requests.ConnectionError("down"),
        ):
            response = self.delete(
                self.member, password=PASSWORD, apple_authorization_code="code-1"
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["code"], "apple_revoke_unavailable")
        self.member.refresh_from_db()
        self.assertTrue(self.member.is_active)

    def test_without_the_apple_key_revoking_is_unavailable(self):
        self.link_apple()
        response = self.delete(
            self.member, password=PASSWORD, apple_authorization_code="code-1"
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["code"], "apple_revoke_unavailable")
        self.assertTrue(User.objects.get(pk=self.member.pk).is_active)
