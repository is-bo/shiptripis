"""P3A, spec 21: a member's own profile photo.

`PUT /api/me/photo` and `DELETE /api/me/photo`, the member's own view in
`GET /api/me`, the race between a staff removal and a replacement (decided by
`version`), and account deletion. Object storage is replaced by a recorder:
signing a URL is local and needs no stub.
"""

from __future__ import annotations

import re
import threading
import time
from io import BytesIO
from unittest import mock
from urllib.parse import urlparse

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from PIL import ExifTags, Image
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from apps.accounts import deletion, photos
from apps.accounts.models import ProfilePhoto
from apps.admin_panel.models import AdminAuditLog
from apps.core.storage import ObjectStore
from apps.core.tests.test_p3a_image_reencode import app_markers, jpeg_with_gps

User = get_user_model()

KEY_SHAPE = re.compile(r"^profile-photos/[A-Za-z0-9_-]{22}\.jpg$")


def png(size=(300, 200), color=(10, 120, 200)) -> bytes:
    out = BytesIO()
    Image.new("RGB", size, color).save(out, format="PNG")
    return out.getvalue()


def upload(body: bytes, content_type: str = "image/jpeg", name: str = "me.jpg"):
    return SimpleUploadedFile(name, body, content_type=content_type)


class StoreRecorder:
    """Stands in for object storage: remembers what was put and deleted."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []
        self.fail_put = False

    def put(self, store, key, body, content_type):
        if self.fail_put:
            raise RuntimeError("bucket shiptrip-parcel AccessDenied for key " + key)
        assert content_type == "image/jpeg"
        self.objects[key] = body

    def delete(self, store, key):
        self.deleted.append(key)
        self.objects.pop(key, None)

    def patch(self):
        recorder = self
        return mock.patch.multiple(
            ObjectStore,
            put=lambda self, key, body, ct: recorder.put(self, key, body, ct),
            delete=lambda self, key: recorder.delete(self, key),
        )


def member(email: str, **fields):
    user = User.objects.create_user(
        email=email, username=email, password="Pw-p3a-12345", full_name="Lina Merabet", **fields
    )
    return user


class StoreMixin:
    def setUp(self):
        super().setUp()
        cache.clear()
        self.store = StoreRecorder()
        patcher = self.store.patch()
        patcher.start()
        self.addCleanup(patcher.stop)


class UploadTests(StoreMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = member("p3a-upload@example.com")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = reverse("me-photo")

    def put(self, body, content_type="image/jpeg"):
        return self.client.put(
            self.url, {"photo": upload(body, content_type)}, format="multipart"
        )

    def test_an_upload_is_stored_re_encoded_and_shown_at_once(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.put(jpeg_with_gps())
        assert response.status_code == 200, response.data
        photo = ProfilePhoto.objects.get(user=self.user)
        assert photo.state == ProfilePhoto.State.ACTIVE
        # Stored: the server's own 512 px square JPEG with no EXIF at all.
        stored = self.store.objects[photo.object_key]
        assert photo.bytes == len(stored)
        with Image.open(BytesIO(stored)) as image:
            assert image.format == "JPEG" and image.size == (512, 512)
            assert len(image.getexif()) == 0
            assert not image.getexif().get_ifd(ExifTags.IFD.GPSInfo)
        assert app_markers(stored) == [0xE0] and b"SecretCam" not in stored
        # The key is random and names nobody.
        assert KEY_SHAPE.match(photo.object_key), photo.object_key
        assert str(self.user.pk) not in photo.object_key.split("/")
        assert response.data == {
            "state": "active",
            "url": response.data["url"],
            "version": photo.version,
            "removed_at": None,
            "reason": None,
        }
        path = urlparse(response.data["url"]).path
        assert path.endswith("/" + photo.object_key)
        assert f"/{self.user.pk}/" not in path
        me = self.client.get(reverse("me")).data
        assert me["photo"]["state"] == "active" and me["photo"]["version"] == photo.version

    def test_png_and_webp_are_accepted_and_become_jpeg(self):
        webp = BytesIO()
        Image.new("RGB", (640, 480), (5, 5, 5)).save(webp, format="WEBP")
        for body, content_type in ((png(), "image/png"), (webp.getvalue(), "image/webp")):
            with self.subTest(content_type):
                assert self.put(body, content_type).status_code == 200
                stored = self.store.objects[ProfilePhoto.objects.get(user=self.user).object_key]
                assert stored[:3] == b"\xff\xd8\xff"

    def test_refusals_have_stable_codes_and_store_nothing(self):
        out = BytesIO()
        Image.new("1", (8000, 6000)).save(out, format="PNG")
        bomb = out.getvalue()
        cases = (
            ("a type that is not an image", jpeg_with_gps(), "image/gif", 415,
             photos.PHOTO_TYPE_UNSUPPORTED),
            ("bytes that are not the declared type", png(), "image/jpeg", 415,
             photos.PHOTO_TYPE_UNSUPPORTED),
            ("not an image at all", b"%PDF-1.7 hello", "image/jpeg", 415,
             photos.PHOTO_TYPE_UNSUPPORTED),
            ("a decompression bomb", bomb, "image/png", 415, photos.PHOTO_TYPE_UNSUPPORTED),
            ("over 10 MiB", b"\xff\xd8\xff" + b"\0" * photos.MAX_UPLOAD_BYTES, "image/jpeg",
             413, photos.PHOTO_TOO_LARGE),
        )
        for label, body, content_type, http, code in cases:
            with self.subTest(label):
                response = self.put(body, content_type)
                assert response.status_code == http, response.data
                assert response.data["code"] == code
        missing = self.client.put(self.url, {}, format="multipart")
        assert missing.status_code == 400 and missing.data["code"] == photos.PHOTO_MISSING
        assert not ProfilePhoto.objects.exists() and not self.store.objects

    def test_storage_failure_is_a_503_without_the_providers_words(self):
        self.store.fail_put = True
        response = self.put(jpeg_with_gps())
        assert response.status_code == 503
        assert response.data == {
            "code": photos.PHOTO_STORAGE_UNAVAILABLE,
            "detail": "Photo storage is temporarily unavailable.",
        }
        assert not ProfilePhoto.objects.exists()

    def test_uploads_take_the_media_upload_throttle(self):
        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"media_upload": "1/hour"}):
            assert self.put(png(), "image/png").status_code == 200
            assert self.put(png(), "image/png").status_code == 429
            # Removing is never throttled: a member can always take a photo down.
            assert self.client.delete(self.url).status_code == 204

    def test_a_guest_cannot_upload_or_remove(self):
        guest = APIClient()
        assert guest.put(self.url, {"photo": upload(png(), "image/png")}).status_code == 401
        assert guest.delete(self.url).status_code == 401


class ReplaceAndRemoveTests(StoreMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = member("p3a-replace@example.com")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = reverse("me-photo")

    def put(self):
        return self.client.put(
            self.url, {"photo": upload(png(), "image/png")}, format="multipart"
        )

    def test_a_replacement_deletes_the_old_object_after_commit(self):
        with self.captureOnCommitCallbacks(execute=True):
            first = self.put().data
        old = ProfilePhoto.objects.get(user=self.user)
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            second = self.put().data
        new = ProfilePhoto.objects.get(user=self.user)
        assert new.object_key != old.object_key and second["version"] != first["version"]
        assert self.store.deleted == []  # nothing goes before the commit
        for callback in callbacks:
            callback()
        assert self.store.deleted == [old.object_key]
        assert list(self.store.objects) == [new.object_key]

    def test_removing_deletes_the_row_and_then_the_object(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.put()
        key = ProfilePhoto.objects.get(user=self.user).object_key
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            response = self.client.delete(self.url)
        assert response.status_code == 204
        assert not ProfilePhoto.objects.exists()
        assert self.store.deleted == []
        for callback in callbacks:
            callback()
        assert self.store.deleted == [key]
        assert self.client.get(reverse("me")).data["photo"] is None
        # Removing again is harmless.
        assert self.client.delete(self.url).status_code == 204

    def test_a_failed_row_write_deletes_the_object_it_stored(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        with self.assertRaises(photos.PhotoRefused) as refused:
            photos.replace_photo(self.user, upload(png(), "image/png"))
        assert refused.exception.code == photos.ACCOUNT_INACTIVE
        assert not ProfilePhoto.objects.exists()
        assert not self.store.objects and len(self.store.deleted) == 1


class StaffRemovalRaceTests(StoreMixin, TestCase):
    """The rule: a staff removal applies only to the version it names."""

    def setUp(self):
        super().setUp()
        self.user = member("p3a-race@example.com")
        self.staff = member("p3a-race-staff@example.com", is_staff=True)

    def replace(self):
        with self.captureOnCommitCallbacks(execute=True):
            return photos.replace_photo(self.user, upload(png(), "image/png"))

    def remove(self, version, reason="Not a photo of a person."):
        with self.captureOnCommitCallbacks(execute=True):
            return photos.remove_by_staff(
                user=self.user, actor=self.staff, version=version, reason=reason
            )

    def test_removal_hides_the_photo_and_deletes_its_object(self):
        photo = self.replace()
        self.remove(photo.version)
        removed = ProfilePhoto.objects.get(user=self.user)
        assert removed.state == ProfilePhoto.State.REMOVED
        assert removed.object_key == "" and removed.bucket == ""
        assert self.store.deleted == [photo.object_key]
        assert photos.public_photo(User.objects.get(pk=self.user.pk)) is None
        own = photos.own_photo(User.objects.get(pk=self.user.pk))
        assert own["state"] == "removed" and own["url"] is None
        assert own["reason"] == "Not a photo of a person."

    def test_a_replacement_that_lands_first_is_never_removed(self):
        seen = self.replace()
        fresh = self.replace()
        with self.assertRaises(photos.PhotoRefused) as refused:
            self.remove(seen.version)
        assert refused.exception.code == photos.PHOTO_CHANGED
        current = ProfilePhoto.objects.get(user=self.user)
        assert current.state == ProfilePhoto.State.ACTIVE
        assert current.version == fresh.version
        assert not AdminAuditLog.objects.filter(action=photos.AUDIT_REMOVED).exists()

    def test_a_removal_that_lands_first_leaves_nothing_visible_and_a_new_upload_is_a_new_photo(self):
        seen = self.replace()
        self.remove(seen.version)
        assert photos.public_photo(User.objects.get(pk=self.user.pk)) is None
        fresh = self.replace()
        assert fresh.version != seen.version
        published = photos.public_photo(User.objects.get(pk=self.user.pk))
        assert published["version"] == fresh.version
        # The removal named the old version: it can never apply to the new one.
        with self.assertRaises(photos.PhotoRefused) as refused:
            self.remove(seen.version)
        assert refused.exception.code == photos.PHOTO_CHANGED

    def test_removal_needs_a_reason_and_an_active_photo(self):
        photo = self.replace()
        with self.assertRaises(photos.PhotoRefused) as refused:
            self.remove(photo.version, reason="   ")
        assert refused.exception.code == photos.REASON_REQUIRED
        photos.remove_own_photo(self.user)
        with self.assertRaises(photos.PhotoRefused) as refused:
            self.remove(photo.version)
        assert refused.exception.code == photos.PHOTO_NOT_ACTIVE


class ConcurrentRemovalTests(StoreMixin, TransactionTestCase):
    """A staff removal that arrives while a replacement holds the member's
    lock waits for it, then sees the new version and changes nothing."""

    def test_a_removal_queued_behind_a_replacement_refuses(self):
        user = member("p3a-concurrent@example.com")
        staff = member("p3a-concurrent-staff@example.com", is_staff=True)
        seen = photos.replace_photo(user, upload(png(), "image/png"))
        locked = threading.Event()
        outcome: dict = {}

        def replacement():
            try:
                with transaction.atomic():
                    photos._hold_member(user.pk)
                    locked.set()
                    time.sleep(0.5)  # the removal is now waiting on the lock
                    outcome["fresh"] = photos.replace_photo(user, upload(png(), "image/png"))
            finally:
                connection.close()

        def removal():
            try:
                locked.wait(5)
                photos.remove_by_staff(
                    user=user, actor=staff, version=seen.version, reason="Offensive."
                )
                outcome["removed"] = True
            except photos.PhotoRefused as exc:
                outcome["refused"] = exc.code
            finally:
                connection.close()

        threads = [threading.Thread(target=replacement), threading.Thread(target=removal)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(15)
        assert outcome.get("refused") == photos.PHOTO_CHANGED, outcome
        current = ProfilePhoto.objects.get(user=user)
        assert current.state == ProfilePhoto.State.ACTIVE
        assert current.version == outcome["fresh"].version != seen.version
        assert not AdminAuditLog.objects.filter(action=photos.AUDIT_REMOVED).exists()


class AccountDeletionTests(StoreMixin, TestCase):
    def test_deleting_the_account_removes_the_row_and_then_the_object(self):
        user = member("p3a-delete@example.com")
        with self.captureOnCommitCallbacks(execute=True):
            key = photos.replace_photo(user, upload(png(), "image/png")).object_key
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            deletion.delete_account(user, password="Pw-p3a-12345")
        assert not ProfilePhoto.objects.filter(user=user).exists()
        assert self.store.deleted == []
        for callback in callbacks:
            callback()
        assert self.store.deleted == [key]


class PublicPhotoTests(StoreMixin, TestCase):
    def test_a_banned_or_deactivated_account_shows_no_photo(self):
        user = member("p3a-banned@example.com")
        with self.captureOnCommitCallbacks(execute=True):
            photos.replace_photo(user, upload(png(), "image/png"))
        assert photos.public_photo(User.objects.get(pk=user.pk)) is not None
        for fields in ({"is_banned": True}, {"is_active": False}):
            with self.subTest(fields):
                User.objects.filter(pk=user.pk).update(
                    **{"is_banned": False, "is_active": True, **fields}
                )
                assert photos.public_photo(User.objects.get(pk=user.pk)) is None
