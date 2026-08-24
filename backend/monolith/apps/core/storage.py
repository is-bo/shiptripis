"""Tiny S3-compatible upload helper.

Wraps `boto3` so views don't need to know endpoint/region details. Used
by parcel + trip media upload endpoints. ARCHITECTURE.md §9 (G4): no
MinIO-specific code; client speaks plain S3 v4 with a custom endpoint
URL so we can swap MinIO → Supabase by env alone.
"""
from __future__ import annotations

import secrets
from functools import lru_cache
from io import BytesIO

import boto3
from botocore.client import Config
from django.conf import settings
from PIL import Image, UnidentifiedImageError


@lru_cache(maxsize=1)
def s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL,
        region_name=settings.S3_REGION,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def put_object(*, bucket: str, key: str, body: bytes, content_type: str) -> None:
    """Upload an object. Bucket must already exist (Supabase S3 does not
    expose CreateBucket; we manage buckets out-of-band in the dashboard)."""
    s3_client().put_object(
        Bucket=bucket, Key=key, Body=body, ContentType=content_type
    )


def make_key(prefix: str, ext: str) -> str:
    """`<prefix>/<random>.<ext>` — random component prevents enumeration."""
    return f"{prefix}/{secrets.token_urlsafe(16)}.{ext.lstrip('.')}"


_EXT_BY_CT = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


def ext_for_content_type(ct: str) -> str | None:
    return _EXT_BY_CT.get((ct or "").lower())


def image_bytes_match_extension(body: bytes, expected_ext: str) -> bool:
    """Verify decoded image bytes match the declared upload type.

    Browser-supplied content types are untrusted. Pillow parses only the
    header/structure here; the pixel limit also rejects decompression bombs.
    """
    format_to_ext = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
    try:
        with Image.open(BytesIO(body)) as image:
            if image.width * image.height > 40_000_000:
                return False
            actual_ext = format_to_ext.get(image.format or "")
            image.verify()
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError):
        return False
    return actual_ext == expected_ext
