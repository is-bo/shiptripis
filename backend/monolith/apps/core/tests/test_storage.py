from __future__ import annotations

import base64

from django.test import override_settings

from apps.core.storage import image_bytes_match_extension, s3_client


_ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_image_bytes_match_declared_extension():
    assert image_bytes_match_extension(_ONE_PIXEL_PNG, "png") is True
    assert image_bytes_match_extension(_ONE_PIXEL_PNG, "jpg") is False


def test_non_image_bytes_are_rejected():
    assert image_bytes_match_extension(b"not-an-image", "jpg") is False


@override_settings(S3_USE_PATH_STYLE=False)
def test_s3_client_honors_virtual_hosted_style():
    s3_client.cache_clear()
    try:
        assert s3_client().meta.config.s3["addressing_style"] == "virtual"
    finally:
        s3_client.cache_clear()
