"""P3A, spec 21: a member's own profile photo.

`PUT /api/me/photo` and `DELETE /api/me/photo`, the member's own view in
`GET /api/me`, the race between a staff removal and a replacement (decided by
`version`), the member's lock whatever the account's state, the durable
cleanup of stored objects, and account deletion. Object storage is replaced by
a recorder: signing a URL is local and needs no stub.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import timedelta
from io import BytesIO
from unittest import mock
from urllib.parse import urlparse

from botocore.exceptions import ClientError
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import OperationalError, connection, connections, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from PIL import ExifTags, Image
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle, UserRateThrottle

from apps.accounts import deletion, photos
from apps.accounts.models import ProfilePhoto
from apps.admin_panel.models import AdminAuditLog
from apps.core.storage import ObjectStore
from apps.core.tests.test_p3a_image_reencode import app_markers, jpeg_with_gps
from apps.finance.jobs import run_due_jobs
from apps.finance.models import ScheduledJob

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
        self.fail_delete: Exception | None = None
        self.before_put = None

    def put(self, store, key, body, content_type):
        if self.before_put is not None:
            self.before_put(key)
        if self.fail_put:
            raise RuntimeError("bucket shiptrip-parcel AccessDenied for key " + key)
        assert content_type == "image/jpeg"
        self.objects[key] = body

    def delete(self, store, key):
        if self.fail_delete is not None:
            raise self.fail_delete
        self.deleted.append(key)
        self.objects.pop(key, None)

    def patch(self):
        recorder = self
        return mock.patch.multiple(
            ObjectStore,
            put=lambda self, key, body, ct: recorder.put(self, key, body, ct),
            delete=lambda self, key: recorder.delete(self, key),
        )


def cleanup_job(key: str, purpose: str = "release") -> ScheduledJob:
    return ScheduledJob.objects.get(key=f"{photos.OBJECT_JOB_PREFIX}:{purpose}:{key}")


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

    def test_removing_is_never_throttled_even_over_the_member_quota(self):
        with mock.patch.dict(UserRateThrottle.THROTTLE_RATES, {"user": "1/min"}):
            assert self.client.get(reverse("me")).status_code == 200
            assert self.client.get(reverse("me")).status_code == 429
            for _ in range(3):
                assert self.client.delete(self.url).status_code == 204

    def test_an_upload_never_touches_the_disk(self):
        # A valid photo just under the limit makes the multipart body pass
        # FILE_UPLOAD_MAX_MEMORY_SIZE, where Django's own handlers spill the
        # original, metadata and all, to a temporary file.
        near_limit = jpeg_with_gps()
        near_limit += b"\0" * (photos.MAX_UPLOAD_BYTES - 100 - len(near_limit))
        over_by_reading = b"\xff\xd8\xff" + b"\0" * photos.MAX_UPLOAD_BYTES
        over_by_length = b"\xff\xd8\xff" + b"\0" * (photos.MAX_UPLOAD_BYTES + 200_000)
        with mock.patch(
            "django.core.files.uploadhandler.TemporaryUploadedFile",
            side_effect=AssertionError("spilled to disk"),
        ):
            assert self.put(near_limit).status_code == 200
            for body in (over_by_reading, over_by_length):
                response = self.put(body)
                assert response.status_code == 413, response.data
                assert response.data == {
                    "code": photos.PHOTO_TOO_LARGE,
                    "detail": "File exceeds 10 MiB.",
                    "max_bytes": photos.MAX_UPLOAD_BYTES,
                }

    def test_a_banned_member_cannot_upload_but_can_remove(self):
        with self.captureOnCommitCallbacks(execute=True):
            assert self.put(png(), "image/png").status_code == 200
        User.objects.filter(pk=self.user.pk).update(is_banned=True)
        self.client.force_authenticate(User.objects.get(pk=self.user.pk))
        response = self.put(png(), "image/png")
        assert response.status_code == 403 and response.data["code"] == photos.ACCOUNT_INACTIVE
        assert self.client.delete(self.url).status_code == 204
        assert not ProfilePhoto.objects.exists()

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

    def test_removing_a_version_that_is_no_longer_current_changes_nothing(self):
        with self.captureOnCommitCallbacks(execute=True):
            first = self.put().data
            second = self.put().data
        response = self.client.delete(f"{self.url}?version={first['version']}")
        assert response.status_code == 409
        assert response.data["code"] == photos.PHOTO_CHANGED
        assert ProfilePhoto.objects.get(user=self.user).version == second["version"]
        assert self.client.delete(f"{self.url}?version={second['version']}").status_code == 204
        assert not ProfilePhoto.objects.exists()

    def test_a_refused_row_write_deletes_the_object_it_stored(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        with self.assertRaises(photos.PhotoRefused) as refused:
            photos.replace_photo(self.user, upload(png(), "image/png"))
        assert refused.exception.code == photos.ACCOUNT_INACTIVE
        assert not ProfilePhoto.objects.exists()
        assert not self.store.objects and len(self.store.deleted) == 1
        # The upload's own job stays as the backstop.
        assert cleanup_job(self.store.deleted[0], "upload").status == ScheduledJob.Status.PENDING


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

    def test_a_member_removal_applies_only_to_the_version_they_were_shown(self):
        shown = self.replace()
        self.remove(shown.version)
        # A second device uploads a replacement while the first still shows
        # Wassla's notice for the version staff removed.
        replacement = self.replace()
        assert replacement.version != shown.version
        with self.assertRaises(photos.PhotoRefused) as refused:
            photos.remove_own_photo(self.user, version=shown.version)
        assert refused.exception.code == photos.PHOTO_CHANGED
        assert refused.exception.status == 409
        kept = ProfilePhoto.objects.get(user=self.user)
        assert kept.version == replacement.version
        assert kept.state == ProfilePhoto.State.ACTIVE
        # The version they are looking at now goes; so does nothing at all.
        photos.remove_own_photo(self.user, version=replacement.version)
        assert not ProfilePhoto.objects.exists()
        photos.remove_own_photo(self.user, version=replacement.version)

    def test_dismissing_the_notice_for_the_version_staff_removed_clears_it(self):
        shown = self.replace()
        self.remove(shown.version)
        photos.remove_own_photo(self.user, version=shown.version)
        assert not ProfilePhoto.objects.exists()

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


class LockedWhateverTheStateTests(StoreMixin, TransactionTestCase):
    """The member's row is locked whatever the account's state: two staff
    removals of a deactivated or banned member's photo still queue."""

    def test_two_removals_of_a_restricted_account_queue_on_the_member_lock(self):
        staff = member("p3a-state-staff@example.com", is_staff=True)
        for label, fields in (("deactivated", {"is_active": False}), ("banned", {"is_banned": True})):
            user = member(f"p3a-state-{label}@example.com")
            seen = photos.replace_photo(user, upload(png(), "image/png"))
            User.objects.filter(pk=user.pk).update(**fields)
            user = User.objects.get(pk=user.pk)
            locked = threading.Event()
            outcome: dict = {}

            def first():
                try:
                    with transaction.atomic():
                        photos._hold_member(user.pk)
                        locked.set()
                        time.sleep(0.5)  # the second removal is now waiting on the lock
                        photos.remove_by_staff(
                            user=user, actor=staff, version=seen.version, reason="First."
                        )
                        outcome["first"] = "removed"
                finally:
                    connection.close()

            def second():
                try:
                    locked.wait(5)
                    photos.remove_by_staff(
                        user=user, actor=staff, version=seen.version, reason="Second."
                    )
                    outcome["second"] = "removed"
                except photos.PhotoRefused as exc:
                    outcome["second"] = exc.code
                finally:
                    connection.close()

            threads = [threading.Thread(target=first), threading.Thread(target=second)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(15)
            with self.subTest(label):
                # Without the lock the second removal would not wait, and
                # would be the one that applied.
                assert outcome == {"first": "removed", "second": photos.PHOTO_NOT_ACTIVE}, outcome
                assert ProfilePhoto.objects.get(user=user).removed_reason == "First."
                assert (
                    AdminAuditLog.objects.filter(
                        action=photos.AUDIT_REMOVED, target_id=str(user.pk)
                    ).count()
                    == 1
                )


class CleanupJobTests(StoreMixin, TestCase):
    """One rule for stored objects: delete K once no photo row names it,
    run by a durable job that retries until storage confirms."""

    def setUp(self):
        super().setUp()
        self.user = member("p3a-cleanup@example.com")

    def replace(self):
        with self.captureOnCommitCallbacks(execute=True):
            return photos.replace_photo(self.user, upload(png(), "image/png"))

    def test_every_upload_records_its_job_before_the_object_is_written(self):
        seen: list = []

        def before_put(key):
            job = cleanup_job(key, "upload")
            seen.append((job.status, job.payload["key"], job.run_at - timezone.now()))

        self.store.before_put = before_put
        photo = self.replace()
        [(status, key, delay)] = seen
        assert status == ScheduledJob.Status.PENDING and key == photo.object_key
        assert delay > photos.UPLOAD_CHECK_DELAY - timedelta(minutes=1)
        # When it runs, the photo is named by its row, so it stays.
        report = run_due_jobs(at=timezone.now() + photos.UPLOAD_CHECK_DELAY * 2)
        assert report.failed == 0
        assert cleanup_job(photo.object_key, "upload").last_result == "referenced"
        assert photo.object_key in self.store.objects

    def test_a_failed_put_leaves_the_job_to_delete_what_may_have_landed(self):
        self.store.fail_put = True
        with self.assertRaises(photos.PhotoRefused):
            photos.replace_photo(self.user, upload(png(), "image/png"))
        job = ScheduledJob.objects.get(kind=ScheduledJob.Kind.PROFILE_PHOTO_OBJECT_DELETE)
        assert job.key.startswith(f"{photos.OBJECT_JOB_PREFIX}:upload:")
        run_due_jobs(at=timezone.now() + photos.UPLOAD_CHECK_DELAY * 2)
        job.refresh_from_db()
        assert job.status == ScheduledJob.Status.SUCCEEDED and job.last_result == "deleted"

    def test_a_failed_delete_is_retried_until_storage_confirms(self):
        old = self.replace()
        self.store.fail_delete = RuntimeError("storage is down")
        with self.captureOnCommitCallbacks(execute=True):
            photos.replace_photo(self.user, upload(png(), "image/png"))
        # The fast path failed: the old image is still stored, the job is due.
        assert old.object_key in self.store.objects
        job = cleanup_job(old.object_key)
        assert job.status == ScheduledJob.Status.PENDING and job.run_at <= timezone.now()
        assert job.max_attempts == photos.CLEANUP_MAX_ATTEMPTS
        run_due_jobs()
        job.refresh_from_db()
        assert job.status == ScheduledJob.Status.PENDING and job.attempts == 1
        assert job.last_error_code == "profile_photo_storage_unavailable"
        self.store.fail_delete = None
        run_due_jobs(at=timezone.now() + timedelta(minutes=5))
        job.refresh_from_db()
        assert job.status == ScheduledJob.Status.SUCCEEDED and job.last_result == "deleted"
        assert old.object_key not in self.store.objects

    def test_an_object_already_gone_counts_as_deleted(self):
        old = self.replace()
        self.store.fail_delete = ClientError({"Error": {"Code": "NoSuchKey"}}, "DeleteObject")
        self.replace()
        run_due_jobs()
        job = cleanup_job(old.object_key)
        assert job.status == ScheduledJob.Status.SUCCEEDED and job.last_result == "deleted"

    def test_a_key_a_row_names_is_never_deleted(self):
        photo = self.replace()
        payload = {"bucket": photo.bucket, "key": photo.object_key}
        assert photos.handle_object_delete_job(payload) == "referenced"
        photos.release_object(photo.bucket, photo.object_key)
        run_due_jobs()
        assert cleanup_job(photo.object_key).last_result == "referenced"
        assert photo.object_key in self.store.objects and self.store.deleted == []

    def test_a_job_for_anything_but_a_photo_key_fails_without_deleting(self):
        from apps.finance.jobs import PermanentJobError

        for payload in ({"bucket": "b", "key": "parcels/abc.jpg"}, {"bucket": "b"}):
            with self.subTest(payload), self.assertRaises(PermanentJobError):
                photos.handle_object_delete_job(payload)
        assert self.store.deleted == []

    def test_deleting_rows_any_way_records_the_job(self):
        # A cascade from the user (as the Django admin deletes) and a bulk delete.
        cascade = self.replace()
        User.objects.filter(pk=self.user.pk).delete()
        assert cleanup_job(cascade.object_key).payload == {
            "bucket": cascade.bucket,
            "key": cascade.object_key,
        }
        other = member("p3a-cleanup-bulk@example.com")
        with self.captureOnCommitCallbacks(execute=True):
            bulk = photos.replace_photo(other, upload(png(), "image/png"))
        with self.captureOnCommitCallbacks(execute=True):
            ProfilePhoto.objects.all().delete()
        assert cleanup_job(bulk.object_key).status == ScheduledJob.Status.PENDING
        assert bulk.object_key in self.store.deleted

    def test_a_staff_removal_records_the_job_with_its_decision(self):
        photo = self.replace()
        staff = member("p3a-cleanup-staff@example.com", is_staff=True)
        with self.captureOnCommitCallbacks(execute=False):
            photos.remove_by_staff(
                user=self.user, actor=staff, version=photo.version, reason="Offensive."
            )
        assert cleanup_job(photo.object_key).status == ScheduledJob.Status.PENDING


class LostCommitAcknowledgementTests(StoreMixin, TransactionTestCase):
    """The commit landed but its acknowledgement was lost: the new object is
    the active photo, so nothing may delete it."""

    def test_the_new_object_stays_when_the_commit_answer_is_lost(self):
        user = member("p3a-ack@example.com")
        wrapper = connections["default"]
        real_commit = wrapper.commit
        real_hold = photos._hold_member
        armed = {"on": False}

        def hold(user_id):
            armed["on"] = True
            return real_hold(user_id)

        def commit_then_lose_the_answer():
            real_commit()
            if armed["on"]:
                armed["on"] = False
                raise OperationalError("server closed the connection unexpectedly")

        with mock.patch.object(photos, "_hold_member", side_effect=hold), mock.patch.object(
            wrapper, "commit", side_effect=commit_then_lose_the_answer
        ):
            with self.assertRaises(OperationalError):
                photos.replace_photo(user, upload(png(), "image/png"))
        photo = ProfilePhoto.objects.get(user=user)
        assert photo.object_key in self.store.objects and self.store.deleted == []
        run_due_jobs(at=timezone.now() + photos.UPLOAD_CHECK_DELAY * 2)
        assert cleanup_job(photo.object_key, "upload").last_result == "referenced"
        assert photo.object_key in self.store.objects and self.store.deleted == []


class AccountDeletionTests(StoreMixin, TestCase):
    def test_deleting_the_account_removes_the_row_and_then_the_object(self):
        user = member("p3a-delete@example.com")
        with self.captureOnCommitCallbacks(execute=True):
            key = photos.replace_photo(user, upload(png(), "image/png")).object_key
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            deletion.delete_account(user, password="Pw-p3a-12345")
        assert not ProfilePhoto.objects.filter(user=user).exists()
        assert self.store.deleted == []
        assert cleanup_job(key).status == ScheduledJob.Status.PENDING
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
