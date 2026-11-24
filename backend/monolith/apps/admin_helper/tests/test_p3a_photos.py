"""P3A, spec 21 and plan 2.11: the AI helper never carries a profile photo.

Removing a photo is a console POST on the helper's "never" list, with a how-to
task, and no helper payload holds a photo, its signed address, its storage key
or its version, even for people who have one.
"""

from __future__ import annotations

import json

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.accounts.models import ProfilePhoto
from apps.admin_helper import actions, tasks
from apps.core.storage import make_key, storage_for

from .test_l15_privacy import PayloadsMixin, keys_of


class NeverListTests(SimpleTestCase):
    def test_photo_removal_is_never_done_by_the_helper(self):
        assert "user-photo-remove" in actions.NEVER
        assert "user-photo-remove" not in actions.CONSOLE_POSTS
        assert not any("photo" in code for code in actions.registry())

    def test_the_how_to_covers_it_with_the_right_capability(self):
        [task] = [task for task in tasks.TASKS if "user-photo-remove" in task.covers]
        assert task.permission == ("moderate_profile_photos",)


class NoPhotoInPayloadsTests(PayloadsMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        bucket = storage_for("media").require_bucket()
        cls.photo_rows = [
            ProfilePhoto.objects.create(
                user=user,
                bucket=bucket,
                object_key=make_key("profile-photos", "jpg"),
                bytes=1000,
                version=f"p3a-helper-version-{user.pk}",
                uploaded_at=timezone.now(),
            )
            for user in (cls.world.sender, cls.world.traveler)
        ]

    def test_no_helper_payload_carries_a_photo(self):
        forbidden = ["profile-photos", "X-Amz-"]
        for row in self.photo_rows:
            forbidden += [row.object_key, row.version]
        for name, body in self.payloads():
            text = json.dumps(body, ensure_ascii=False)
            for value in forbidden:
                assert value not in text, (name, value)
            for path, key in keys_of(body):
                assert "photo" not in str(key).lower() and "avatar" not in str(key).lower(), (
                    name,
                    path,
                )
