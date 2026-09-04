import json
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import redis
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.core import redis_bus

from ..models import Notification, NotificationPreference, PushDevice
from ..push import (
    consume_fcm_results,
    deactivate_stale_push_devices,
    enqueue_fcm_for_event,
)


class _RedisRecorder:
    def __init__(self):
        self.entries = []
        self.acked = []
        self.read_result = []

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


def _registration(installation_id, token: str, platform: str = "android") -> dict:
    return {
        "installation_id": str(installation_id),
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

    def test_registration_requires_authentication_and_never_returns_token(self):
        response = self.client.post(
            "/api/notifications/devices",
            _registration(self.installation, self.token),
            format="json",
        )
        self.assertEqual(response.status_code, 401)

        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/notifications/devices",
            _registration(self.installation, self.token),
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("token", response.data)
        self.assertNotIn("token_fingerprint", response.data)
        device = PushDevice.objects.get()
        self.assertEqual(device.user, self.user)
        self.assertTrue(device.active)

    def test_same_installation_is_idempotent_and_rotates_token_in_place(self):
        self.client.force_authenticate(self.user)
        first = self.client.post(
            "/api/notifications/devices",
            _registration(self.installation, self.token),
            format="json",
        )
        rotated = "fcm-token-rotated-1234567890"
        second = self.client.post(
            "/api/notifications/devices",
            _registration(self.installation, rotated),
            format="json",
        )
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(PushDevice.objects.count(), 1)
        self.assertEqual(PushDevice.objects.get().token, rotated)

    def test_same_token_moves_to_authenticated_owner_and_installation(self):
        self.client.force_authenticate(self.user)
        self.client.post(
            "/api/notifications/devices",
            _registration(self.installation, self.token),
            format="json",
        )
        replacement_installation = uuid4()
        self.client.force_authenticate(self.other)
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
        self.client.force_authenticate(self.user)
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

        self.client.force_authenticate(self.other)
        response = self.client.post(
            "/api/notifications/devices/unregister",
            {"installation_id": str(self.installation)},
            format="json",
        )
        self.assertEqual(response.status_code, 204)
        self.assertTrue(
            PushDevice.objects.get(installation_id=self.installation).active
        )

        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/notifications/devices/unregister",
            {"installation_id": str(self.installation)},
            format="json",
        )
        self.assertEqual(response.status_code, 204)
        self.assertFalse(
            PushDevice.objects.get(installation_id=self.installation).active
        )

    def test_valid_logout_disables_current_installation(self):
        PushDevice.objects.create(
            user=self.user,
            installation_id=self.installation,
            token=self.token,
            platform=PushDevice.Platform.ANDROID,
        )
        self.client.force_authenticate(self.user)
        response = self.client.post(
            "/api/auth/sign-out",
            {
                "refresh": str(RefreshToken.for_user(self.user)),
                "installation_id": str(self.installation),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 205)
        self.assertFalse(PushDevice.objects.get().active)

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
        stale = PushDevice.objects.create(
            user=self.user,
            installation_id=self.installation,
            token=self.token,
            platform=PushDevice.Platform.ANDROID,
        )
        recent = PushDevice.objects.create(
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
        return PushDevice.objects.create(
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
        invalid = PushDevice.objects.create(
            user=user,
            installation_id=uuid4(),
            token="fcm-token-invalid-1234567890",
            platform=PushDevice.Platform.ANDROID,
        )
        successful = PushDevice.objects.create(
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
        device = PushDevice.objects.create(
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
