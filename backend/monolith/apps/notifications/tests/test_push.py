import json
import time
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import redis
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.accounts.models import SignInSession, User
from apps.accounts.sessions import end_all_sessions
from apps.core import redis_bus

from ..models import Notification, NotificationPreference, PushDevice
from ..push import (
    consume_fcm_results,
    deactivate_stale_push_devices,
    enqueue_fcm_for_event,
)
from .factories import push_device, signed_in


class _RedisRecorder:
    def __init__(self):
        self.entries = []
        self.acked = []
        self.read_result = []
        self.pipeline_calls = 0

    def pipeline(self, *, transaction=True):
        self.pipeline_calls += 1
        self.pipeline_transaction = transaction
        return self

    def execute(self):
        return ["1-0"] * len(self.entries)

    def xadd(self, stream, fields, **kwargs):
        self.entries.append((stream, fields, kwargs))
        return "1-0"

    def publish(self, channel, payload):
        return 1

    def xgroup_create(self, *args, **kwargs):
        return True

    def xreadgroup(self, *args, **kwargs):
        return self.read_result

    def xack(self, stream, group, entry_id):
        self.acked.append((stream, group, entry_id))
        return 1


def _user(email: str, language: str = "en") -> User:
    return User.objects.create_user(
        username=email,
        email=email,
        password="Test-password-123!",
        full_name="Push Test",
        preferred_language=language,
    )


def _registration(
    installation_id, token: str, platform: str = "android", sequence: int = 1
) -> dict:
    return {
        "installation_id": str(installation_id),
        "binding_sequence": sequence,
        "token": token,
        "platform": platform,
        "app_version": "1.0.0",
    }


class PushDeviceAPITests(TestCase):
    def setUp(self):
        self.user = _user("push-one@example.com")
        self.other = _user("push-two@example.com")
        self.client = APIClient()
        self.installation = uuid4()
        self.token = "fcm-token-one-1234567890"

    def _as(self, session):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {session['access']}")

    def test_registration_requires_authentication_and_never_returns_token(self):
        response = self.client.post(
            "/api/notifications/devices",
            _registration(self.installation, self.token),
            format="json",
        )
        self.assertEqual(response.status_code, 401)

        self._as(signed_in(self.user))
        response = self.client.post(
            "/api/notifications/devices",
            _registration(self.installation, self.token),
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("token", response.data)
        self.assertNotIn("token_fingerprint", response.data)
        self.assertNotIn("session", response.data)
        device = PushDevice.objects.get()
        self.assertEqual(device.user, self.user)
        self.assertTrue(device.active)

    def test_same_installation_is_idempotent_and_rotates_token_in_place(self):
        self._as(signed_in(self.user))
        first = self.client.post(
            "/api/notifications/devices",
            _registration(self.installation, self.token),
            format="json",
        )
        rotated = "fcm-token-rotated-1234567890"
        second = self.client.post(
            "/api/notifications/devices",
            _registration(self.installation, rotated, sequence=2),
            format="json",
        )
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(PushDevice.objects.count(), 1)
        self.assertEqual(PushDevice.objects.get().token, rotated)

    def test_same_token_moves_to_authenticated_owner_and_installation(self):
        self._as(signed_in(self.user))
        self.client.post(
            "/api/notifications/devices",
            _registration(self.installation, self.token),
            format="json",
        )
        replacement_installation = uuid4()
        self._as(signed_in(self.other))
        response = self.client.post(
            "/api/notifications/devices",
            _registration(replacement_installation, self.token),
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(PushDevice.objects.count(), 1)
        device = PushDevice.objects.get()
        self.assertEqual(device.user, self.other)
        self.assertEqual(device.installation_id, replacement_installation)

    def test_user_can_have_multiple_devices_and_cannot_unregister_another_users(self):
        mine = signed_in(self.user)
        self._as(mine)
        self.client.post(
            "/api/notifications/devices",
            _registration(self.installation, self.token),
            format="json",
        )
        second_installation = uuid4()
        self.client.post(
            "/api/notifications/devices",
            _registration(second_installation, "fcm-token-tablet-1234567890"),
            format="json",
        )
        self.assertEqual(
            PushDevice.objects.filter(user=self.user, active=True).count(), 2
        )

        self._as(signed_in(self.other))
        response = self.client.post(
            "/api/notifications/devices/unregister",
            {"installation_id": str(self.installation), "binding_sequence": 2},
            format="json",
        )
        self.assertEqual(response.status_code, 204)
        self.assertTrue(
            PushDevice.objects.get(installation_id=self.installation).active
        )

        self._as(mine)
        response = self.client.post(
            "/api/notifications/devices/unregister",
            {"installation_id": str(self.installation), "binding_sequence": 2},
            format="json",
        )
        self.assertEqual(response.status_code, 204)
        self.assertFalse(
            PushDevice.objects.get(installation_id=self.installation).active
        )
        self.assertTrue(
            PushDevice.objects.get(installation_id=second_installation).active,
            "turning push off on one phone leaves the sign-in's other phone alone",
        )

    def test_valid_logout_disables_current_installation(self):
        session = signed_in(self.user)
        self._as(session)
        self.client.post(
            "/api/notifications/devices",
            _registration(self.installation, self.token),
            format="json",
        )
        response = self.client.post(
            "/api/auth/sign-out",
            {
                "refresh": session["refresh"],
                "installation_id": str(self.installation),
                "binding_sequence": 2,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 205)
        self.assertFalse(PushDevice.objects.get().active)

    # ---- A registration that was slow on the network (N1) -----------------
    # The app numbers every registration and sign-out of one installation from
    # a counter that only grows, and every token of a sign-in names it (`sid`,
    # a `SignInSession` row). A registration overtaken by a later operation
    # must not rebind the phone, a sign-out ends only its own sign-in's
    # binding, and a registration from a sign-in that has ended is refused,
    # whatever order the requests reach the server in.

    def _register(self, session, sequence, token=None, installation=None):
        self._as(session)
        return self.client.post(
            "/api/notifications/devices",
            _registration(
                installation or self.installation,
                token or self.token,
                sequence=sequence,
            ),
            format="json",
        )

    def _sign_out(self, session, sequence=2, *, installation=True):
        self._as(session)
        body = {"refresh": session["refresh"]}
        if installation:
            body["installation_id"] = str(self.installation)
        if sequence is not None:
            body["binding_sequence"] = sequence
        return self.client.post("/api/auth/sign-out", body, format="json")

    def _device(self):
        return PushDevice.objects.get()

    def test_a_registration_remembers_its_sign_in_and_number(self):
        a = signed_in(self.user)
        self.assertEqual(self._register(a, 7).status_code, 200)
        device = self._device()
        self.assertEqual(device.session_id.hex, a["sid"])
        self.assertEqual(device.binding_sequence, 7)

    def test_registration_delayed_past_sign_out_does_not_rebind_the_phone(self):
        # Registered earlier, then a token-refresh registration (2) is held up
        # while the person signs out (3).
        a = signed_in(self.user)
        self.assertEqual(self._register(a, 1).status_code, 200)
        self.assertEqual(self._sign_out(a, 3).status_code, 205)
        self.assertFalse(self._device().active)

        late = self._register(a, 2, token="fcm-token-late-1234567890")

        self.assertEqual(late.status_code, 409)
        device = self._device()
        self.assertEqual(device.user, self.user)
        self.assertFalse(device.active)
        self.assertEqual(device.token, self.token, "the late token is not stored")

    def test_a_late_registration_of_a_live_sign_in_learns_the_current_number(self):
        # The phone's counter is behind the server's (2 against 3): the server
        # says where it stands so the app can catch up.
        a = signed_in(self.user)
        self.assertEqual(self._register(a, 3).status_code, 200)

        late = self._register(a, 2, token="fcm-token-late-1234567890")

        self.assertEqual(late.status_code, 409)
        self.assertEqual(late.data["code"], "push_registration_superseded")
        self.assertEqual(late.data["current_sequence"], 3)
        self.assertEqual(self._device().token, self.token)

    def test_first_registration_delayed_past_sign_out_creates_no_device(self):
        # The sign-out reaches the server before the very first registration
        # does: there is no device to switch off, and the sign-in has ended.
        a = signed_in(self.user)
        self.assertEqual(self._sign_out(a, 2).status_code, 205)
        self.assertEqual(PushDevice.objects.count(), 0)

        late = self._register(a, 1)

        self.assertEqual(late.status_code, 409)
        self.assertEqual(PushDevice.objects.count(), 0)

    def test_an_unnumbered_sign_out_before_the_first_registration_refuses_it(self):
        # Astra round 3, blocker 1. The phone could not write its counter, so
        # the sign-out carries no number, and the first registration is still
        # on its way. Nothing records the installation, but the sign-in itself
        # has ended, and a registration made with its access token is refused.
        a = signed_in(self.user)
        self.assertEqual(self._sign_out(a, None).status_code, 205)

        late = self._register(a, 1)

        self.assertEqual(late.status_code, 409)
        self.assertEqual(late.data["code"], "push_session_ended")
        self.assertEqual(PushDevice.objects.count(), 0)

    def test_a_sign_out_that_names_no_installation_switches_its_devices_off(self):
        # Astra round 3, blocker 1: the installation id could not be read
        # either. The sign-in's devices go off all the same.
        a = signed_in(self.user)
        self.assertEqual(self._register(a, 1).status_code, 200)

        self.assertEqual(self._sign_out(a, None, installation=False).status_code, 205)

        self.assertFalse(self._device().active)
        self.assertEqual(self._register(a, 2).status_code, 409)
        self.assertFalse(self._device().active)

    def test_registration_delayed_past_the_next_account_keeps_that_account(self):
        # A's registration (1) is slow; A signs out (2); B signs in on the same
        # phone and registers (3); only then does A's request arrive.
        a, b = signed_in(self.user), signed_in(self.other)
        self.assertEqual(self._sign_out(a, 2).status_code, 205)
        self.assertEqual(self._register(b, 3).status_code, 200)

        late = self._register(a, 1)

        self.assertEqual(late.status_code, 409)
        device = self._device()
        self.assertEqual(device.user, self.other)
        self.assertTrue(device.active)

    def test_registration_delayed_past_the_next_account_without_a_sign_out(self):
        # The sign-out never reached the server (offline); B's registration
        # still overtakes A's late one.
        a, b = signed_in(self.user), signed_in(self.other)
        self.assertEqual(self._register(b, 3).status_code, 200)

        late = self._register(a, 1)

        self.assertEqual(late.status_code, 409)
        device = self._device()
        self.assertEqual(device.user, self.other)
        self.assertTrue(device.active)

    def test_sign_in_after_sign_out_registers_again(self):
        a = signed_in(self.user)
        self.assertEqual(self._sign_out(a, 2).status_code, 205)
        again = signed_in(self.user)
        self.assertEqual(self._register(again, 3).status_code, 200)
        device = self._device()
        self.assertEqual(device.user, self.user)
        self.assertTrue(device.active)

    def test_sign_out_delayed_past_the_same_persons_next_sign_in_changes_nothing(
        self,
    ):
        # The person signed back in and registered (3) before the earlier
        # sign-in's sign-out (2) arrived: that sign-out must not switch the new
        # binding off, even though both belong to the same account.
        first, second = signed_in(self.user), signed_in(self.user)
        self.assertEqual(self._register(second, 3).status_code, 200)

        self.assertEqual(self._sign_out(first, 2).status_code, 205)

        self.assertTrue(self._device().active)

    def test_every_sign_out_still_lands_when_the_operations_arrive_out_of_order(
        self,
    ):
        # A is registered (1). A's sign-out (2) and B's registration (3) are
        # delayed, and B's own sign-out (4) arrives first. Everybody has signed
        # out, so nothing may be left switched on, and B's late registration
        # must not switch it back on.
        a, b = signed_in(self.user), signed_in(self.other)
        self.assertEqual(self._register(a, 1).status_code, 200)

        self.assertEqual(self._sign_out(b, 4).status_code, 205)
        self.assertTrue(self._device().active, "B never owned the device")
        self.assertEqual(self._register(b, 3).status_code, 409)
        self.assertEqual(self._sign_out(a, 2).status_code, 205)

        device = self._device()
        self.assertEqual(device.user, self.user)
        self.assertFalse(device.active)

    def test_a_sign_out_from_a_phone_whose_counter_was_lost_still_signs_out(self):
        # The server has seen 40 but the phone starts over at 2: its sign-out is
        # numbered below what the server holds and still ends its own binding.
        a = signed_in(self.user)
        self.assertEqual(self._register(a, 40).status_code, 200)

        self.assertEqual(self._sign_out(a, 2).status_code, 205)

        self.assertFalse(self._device().active)

    def test_a_sign_out_without_a_number_ends_its_own_binding(self):
        a = signed_in(self.user)
        self.assertEqual(self._register(a, 1).status_code, 200)

        self.assertEqual(self._sign_out(a, None).status_code, 205)

        self.assertFalse(self._device().active)

    def test_a_sign_out_cannot_switch_off_another_accounts_phone(self):
        a, b = signed_in(self.user), signed_in(self.other)
        self.assertEqual(self._register(a, 1).status_code, 200)

        self.assertEqual(self._sign_out(b, 2).status_code, 205)

        self.assertTrue(self._device().active)

    def test_a_token_that_names_no_sign_in_cannot_register(self):
        # Every token the server issues names its sign-in; one that does not
        # (or names a sign-in that never existed) has nothing to end, so it
        # can never switch a phone on.
        refresh = RefreshToken.for_user(self.user)
        self._as({"access": refresh.access_token})
        response = self.client.post(
            "/api/notifications/devices",
            _registration(self.installation, self.token),
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "push_session_ended")

        refresh["sid"] = uuid4().hex
        self._as({"access": refresh.access_token})
        response = self.client.post(
            "/api/notifications/devices",
            _registration(self.installation, self.token),
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(PushDevice.objects.count(), 0)

    def test_a_sign_in_cannot_be_ended_through_another_account(self):
        # A sign-out names its sign-in by the refresh token, and only the
        # authenticated account's own sign-ins end.
        a, b = signed_in(self.user), signed_in(self.other)
        self.assertEqual(self._register(a, 1).status_code, 200)
        self._as(b)
        response = self.client.post(
            "/api/auth/sign-out", {"refresh": a["refresh"]}, format="json"
        )
        self.assertEqual(response.status_code, 205)
        self.assertTrue(self._device().active)
        self.assertTrue(SignInSession.live(user_id=self.user.pk, session_id=a["sid"]))

    def test_a_repeated_registration_is_idempotent(self):
        a = signed_in(self.user)
        self.assertEqual(self._register(a, 4).status_code, 200)
        self.assertEqual(self._register(a, 4).status_code, 200)
        self.assertEqual(PushDevice.objects.count(), 1)
        self.assertTrue(self._device().active)

    def test_an_acknowledged_repeat_changes_nothing(self):
        # A repeat of the registration already recorded is acknowledged as it
        # stands: a device the delivery feedback switched off stays off.
        a = signed_in(self.user)
        self.assertEqual(self._register(a, 4).status_code, 200)
        PushDevice.objects.update(active=False)

        self.assertEqual(self._register(a, 4).status_code, 200)

        self.assertFalse(self._device().active)

    def test_the_same_number_from_another_sign_in_of_the_same_person_collides(self):
        # Astra round 3, blocker 4. The phone's counter was lost and the same
        # person signed in again: both sign-ins register the same token at the
        # same number. The earlier sign-in's late request must not take the
        # binding over, or the newer sign-in's sign-out would miss the phone.
        older, newer = signed_in(self.user), signed_in(self.user)
        self.assertEqual(self._register(newer, 5).status_code, 200)

        late = self._register(older, 5)

        self.assertEqual(late.status_code, 409)
        self.assertEqual(late.data["current_sequence"], 5)
        self.assertEqual(self._device().session_id.hex, newer["sid"])
        self.assertEqual(self._sign_out(newer, None).status_code, 205)
        self.assertFalse(self._device().active)

    def test_the_same_number_for_another_token_is_a_collision(self):
        a = signed_in(self.user)
        self.assertEqual(self._register(a, 1).status_code, 200)

        collision = self._register(a, 1, token="fcm-token-other-1234567890")

        self.assertEqual(collision.status_code, 409)
        self.assertEqual(collision.data["current_sequence"], 1)
        self.assertEqual(self._device().token, self.token)

    def test_the_same_number_for_another_account_is_a_collision(self):
        # A's counter was lost while the installation id survived: B reuses the
        # number of A's registration, and whichever arrives last must not win.
        a, b = signed_in(self.user), signed_in(self.other)
        self.assertEqual(self._register(a, 1).status_code, 200)

        collision = self._register(b, 1)

        self.assertEqual(collision.status_code, 409)
        device = self._device()
        self.assertEqual(device.user, self.user)
        self.assertTrue(device.active)

    def test_a_registration_sharing_a_number_with_a_sign_out_is_a_collision(self):
        a, b = signed_in(self.user), signed_in(self.user)
        self.assertEqual(self._sign_out(a, 5).status_code, 205)

        collision = self._register(b, 5)

        self.assertEqual(collision.status_code, 409)
        self.assertEqual(collision.data["code"], "push_registration_superseded")
        self.assertEqual(PushDevice.objects.count(), 0)

    def test_a_binding_sequence_is_required_to_register(self):
        self._as(signed_in(self.user))
        body = _registration(self.installation, self.token)
        del body["binding_sequence"]
        response = self.client.post(
            "/api/notifications/devices", body, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PushDevice.objects.count(), 0)

    # ---- Ending every sign-in (password reset) ------------------------------

    def test_a_registration_begun_before_a_password_reset_cannot_switch_the_phone_on(
        self,
    ):
        a = signed_in(self.user)
        self.assertEqual(self._register(a, 1).status_code, 200)
        end_all_sessions(self.user)
        self.assertFalse(self._device().active)

        late = self._register(a, 2, token="fcm-token-late-1234567890")

        self.assertEqual(late.status_code, 409)
        self.assertEqual(late.data["code"], "push_session_ended")
        self.assertFalse(self._device().active)

    def test_a_token_from_the_reset_second_cannot_switch_the_phone_on(self):
        # Astra round 3, blocker 2. The old check compared whole seconds, so a
        # token issued in the reset's own second passed. A sign-in is ended by
        # identity, not by time: this token is stamped at the reset's second
        # (or later) and is refused, while a new sign-in in the same second
        # registers.
        a = signed_in(self.user)
        end_all_sessions(self.user)
        access = AccessToken(a["access"])
        access["iat"] = int(time.time())
        fresh = signed_in(self.user)

        late = self._register({"access": str(access)}, 1)

        self.assertEqual(late.status_code, 409)
        self.assertEqual(late.data["code"], "push_session_ended")
        self.assertEqual(self._register(fresh, 2).status_code, 200)
        self.assertTrue(self._device().active)

    def test_a_sign_in_after_the_password_reset_registers_normally(self):
        a = signed_in(self.user)
        self.assertEqual(self._register(a, 1).status_code, 200)
        end_all_sessions(self.user)

        fresh = signed_in(self.user)
        self.assertEqual(self._register(fresh, 2).status_code, 200)
        self.assertTrue(self._device().active)

    def test_a_password_reset_does_not_stop_other_accounts_registering(self):
        b = signed_in(self.other)
        end_all_sessions(self.user)
        self.assertEqual(self._register(b, 1).status_code, 200)

    def test_preferences_have_two_real_toggles_and_essential_is_fixed(self):
        self.client.force_authenticate(self.user)
        response = self.client.get("/api/notifications/preferences")
        self.assertEqual(
            response.data,
            {
                "essential_enabled": True,
                "messages_enabled": True,
                "marketplace_enabled": True,
            },
        )
        response = self.client.patch(
            "/api/notifications/preferences",
            {
                "essential_enabled": False,
                "messages_enabled": False,
                "marketplace_enabled": False,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["essential_enabled"])
        self.assertFalse(response.data["messages_enabled"])
        self.assertFalse(response.data["marketplace_enabled"])

    def test_stale_devices_can_be_pruned_without_touching_recent_devices(self):
        stale = push_device(
            user=self.user,
            installation_id=self.installation,
            token=self.token,
            platform=PushDevice.Platform.ANDROID,
        )
        recent = push_device(
            user=self.user,
            installation_id=uuid4(),
            token="fcm-token-recent-1234567890",
            platform=PushDevice.Platform.ANDROID,
        )
        PushDevice.objects.filter(pk=stale.pk).update(
            last_seen_at=timezone.now() - timedelta(days=181)
        )

        self.assertEqual(deactivate_stale_push_devices(), 1)
        stale.refresh_from_db()
        recent.refresh_from_db()
        self.assertFalse(stale.active)
        self.assertTrue(recent.active)


@override_settings(FCM_ENABLED=True, FCM_STREAM="notif:fcm")
class PushPublicationTests(TestCase):
    def _device(self, user: User, suffix: str) -> PushDevice:
        return push_device(
            user=user,
            installation_id=uuid4(),
            token=f"fcm-token-{suffix}-1234567890",
            platform=PushDevice.Platform.ANDROID,
        )

    @patch("apps.core.redis_bus.get_client")
    def test_localizes_per_user_and_uses_one_multicast_event(self, get_client):
        recorder = _RedisRecorder()
        get_client.return_value = recorder
        users = [
            _user("en@example.com", "en"),
            _user("fr@example.com", "fr"),
            _user("ar@example.com", "ar"),
        ]
        for index, user in enumerate(users):
            self._device(user, str(index))
            self._device(user, f"tablet-{index}")
            Notification.objects.create(
                recipient=user,
                channel="offer.created",
                event_id="event-localized",
                payload={},
            )

        count = enqueue_fcm_for_event(
            channel="offer.created",
            event_id="event-localized",
            payload={"offer_id": 7, "secret": "never", "exact_location": "never"},
            targets=[user.pk for user in users],
        )
        self.assertEqual(count, 3)
        self.assertEqual(recorder.pipeline_calls, 1)
        self.assertFalse(recorder.pipeline_transaction)
        payloads = [json.loads(entry[1]["payload"]) for entry in recorder.entries]
        self.assertEqual(
            {payload["event_id"] for payload in payloads}, {"event-localized"}
        )
        self.assertTrue(all(len(payload["tokens"]) == 2 for payload in payloads))
        self.assertEqual(
            {payload["title"] for payload in payloads},
            {"New offer", "Nouvelle offre", "عرض جديد"},
        )
        serialized = json.dumps(payloads, ensure_ascii=False)
        self.assertNotIn("never", serialized)
        self.assertTrue(all(payload["data"]["offer_id"] == "7" for payload in payloads))

    @patch("apps.core.redis_bus.get_client")
    def test_preferences_filter_optional_categories_but_not_essential(self, get_client):
        recorder = _RedisRecorder()
        get_client.return_value = recorder
        user = _user("preferences@example.com")
        self._device(user, "preferences")
        NotificationPreference.objects.create(
            user=user,
            messages_enabled=False,
            marketplace_enabled=False,
        )

        self.assertEqual(
            enqueue_fcm_for_event(
                channel="chat.message.new",
                event_id="message-off",
                payload={"thread_id": 1, "body": "private"},
                targets=[user.pk],
            ),
            0,
        )
        self.assertEqual(
            enqueue_fcm_for_event(
                channel="offer.created",
                event_id="market-off",
                payload={"offer_id": 2},
                targets=[user.pk],
            ),
            0,
        )
        self.assertEqual(
            enqueue_fcm_for_event(
                channel="payment.failed",
                event_id="essential-on",
                payload={"payment_order_id": 3},
                targets=[user.pk],
            ),
            1,
        )

    @patch("apps.core.redis_bus.get_client")
    def test_kyc_decision_copy_matches_status_and_language(self, get_client):
        recorder = _RedisRecorder()
        get_client.return_value = recorder
        user = _user("kyc-fr@example.com", "fr")
        self._device(user, "kyc-fr")
        Notification.objects.create(
            recipient=user,
            channel="kyc.status_changed",
            event_id="kyc-approved-fr",
            payload={},
        )

        enqueue_fcm_for_event(
            channel="kyc.status_changed",
            event_id="kyc-approved-fr",
            payload={"submission_id": 4, "status": "approved"},
            targets=[user.pk],
        )

        payload = json.loads(recorder.entries[0][1]["payload"])
        self.assertEqual(payload["title"], "Votre KYC a été approuvé")
        self.assertNotIn("status", payload["data"])

    @patch("apps.core.redis_bus.get_client")
    def test_no_active_tokens_is_a_safe_noop(self, get_client):
        user = _user("no-device@example.com")
        self.assertEqual(
            enqueue_fcm_for_event(
                channel="payment.captured",
                event_id="no-device",
                payload={},
                targets=[user.pk],
            ),
            0,
        )
        get_client.assert_not_called()

    @patch("apps.core.redis_bus.get_client")
    def test_xadd_outage_does_not_undo_inbox_or_business_commit(self, get_client):
        user = _user("outage@example.com")
        self._device(user, "outage")
        recorder = _RedisRecorder()
        recorder.xadd = lambda *args, **kwargs: (_ for _ in ()).throw(
            redis.RedisError("down")
        )
        get_client.return_value = recorder

        with self.captureOnCommitCallbacks(execute=True):
            event_id = redis_bus.publish_after_commit(
                "payment.captured",
                {"payment_order_id": 10},
                targets=[user.pk],
            )
        self.assertTrue(
            Notification.objects.filter(recipient=user, event_id=event_id).exists()
        )


@override_settings(
    FCM_ENABLED=True,
    FCM_RESULTS_STREAM="notif:fcm:results",
    FCM_RESULTS_CONSUMER_GROUP="notif-fcm-results-django",
    FCM_RESULTS_CONSUMER_NAME="notif-fcm-results-django-1",
)
class PushFeedbackTests(TestCase):
    @patch("apps.core.redis_bus.get_client")
    def test_invalid_device_feedback_deactivates_without_tokens(self, get_client):
        user = _user("feedback@example.com")
        invalid = push_device(
            user=user,
            installation_id=uuid4(),
            token="fcm-token-invalid-1234567890",
            platform=PushDevice.Platform.ANDROID,
        )
        successful = push_device(
            user=user,
            installation_id=uuid4(),
            token="fcm-token-success-1234567890",
            platform=PushDevice.Platform.ANDROID,
        )
        recorder = _RedisRecorder()
        recorder.read_result = [
            (
                "notif:fcm:results",
                [
                    (
                        "1-0",
                        {
                            "payload": json.dumps(
                                {
                                    "event_id": "event-feedback",
                                    "invalid_device_ids": [invalid.pk],
                                    "invalid_token_fingerprints": [
                                        invalid.token_fingerprint
                                    ],
                                    "successful_device_ids": [successful.pk],
                                    "successful_token_fingerprints": [
                                        successful.token_fingerprint
                                    ],
                                }
                            )
                        },
                    )
                ],
            )
        ]
        get_client.return_value = recorder

        self.assertEqual(consume_fcm_results(), 1)
        invalid.refresh_from_db()
        successful.refresh_from_db()
        self.assertFalse(invalid.active)
        self.assertIsNotNone(invalid.last_failure_at)
        self.assertTrue(successful.active)
        self.assertIsNotNone(successful.last_success_at)
        self.assertEqual(len(recorder.acked), 1)

    @patch("apps.core.redis_bus.get_client")
    def test_stale_invalid_feedback_cannot_disable_a_rotated_token(self, get_client):
        user = _user("rotated-feedback@example.com")
        device = push_device(
            user=user,
            installation_id=uuid4(),
            token="fcm-token-old-1234567890",
            platform=PushDevice.Platform.ANDROID,
        )
        old_fingerprint = device.token_fingerprint
        device.token = "fcm-token-new-1234567890"
        device.save()
        recorder = _RedisRecorder()
        recorder.read_result = [
            (
                "notif:fcm:results",
                [
                    (
                        "2-0",
                        {
                            "payload": json.dumps(
                                {
                                    "event_id": "event-stale-feedback",
                                    "invalid_device_ids": [device.pk],
                                    "invalid_token_fingerprints": [old_fingerprint],
                                    "successful_device_ids": [],
                                    "successful_token_fingerprints": [],
                                }
                            )
                        },
                    )
                ],
            )
        ]
        get_client.return_value = recorder

        self.assertEqual(consume_fcm_results(), 1)
        device.refresh_from_db()
        self.assertTrue(device.active)
        self.assertIsNone(device.last_failure_at)
