from __future__ import annotations

import base64

from django.test import override_settings

from apps.core.storage import (
    image_bytes_match_extension,
    reset_storage_clients,
    s3_client,
)


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
    reset_storage_clients()
    try:
        assert s3_client().meta.config.s3["addressing_style"] == "virtual"
    finally:
        reset_storage_clients()


#: A PNG with a valid signature and header and a corrupt IDAT chunk — the shape
#: a photo cut short by a flaky mobile upload arrives in. Pillow's PNG plugin
#: raises `SyntaxError` on it: a builtin, not an image error, and so not in any
#: reasonable list of "image exceptions". It escaped the validator as an
#: unhandled exception and turned an ordinary bad upload into an HTTP 500 on
#: every endpoint that accepts an image, which is how it reached a deployment.
_CORRUPT_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFElEQVR4nGP8z8Dwn4"
    "EIwEQdZaNKAVeoAgQOFVIYAAAAAElFTkSuQmCC"
)


def test_a_corrupt_image_is_refused_rather_than_raising():
    # The whole property: a judgement about untrusted bytes answers False. It
    # does not raise, whatever the decoder decides to throw.
    assert image_bytes_match_extension(_CORRUPT_PNG, "png") is False
    assert image_bytes_match_extension(_CORRUPT_PNG, "jpg") is False


def test_truncated_and_empty_bodies_are_refused_rather_than_raising():
    signature_only = _ONE_PIXEL_PNG[:8]
    for candidate in (b"", signature_only, _ONE_PIXEL_PNG[:20], _ONE_PIXEL_PNG[:1]):
        assert image_bytes_match_extension(candidate, "png") is False
