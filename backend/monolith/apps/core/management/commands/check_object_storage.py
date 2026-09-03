"""Prove Django can actually write to every bucket it is configured to use.

This exists because of a real deployed failure. Django's object-storage
credential and the Go KYC service's credential are different keys with
different bucket grants, and nothing in `readyz`, the settings validation or
the admin console could tell the difference between "a bucket name is set"
and "this process may write to it". The first time anyone found out was a
traveller getting a 500 on a boarding-pass upload.

A name in an environment variable is not access. This command does the round
trip — put, get, delete — with the credential the application actually uses,
and reports per bucket. It writes only to a `.shiptrip-storage-check/` prefix
and removes what it wrote.

Usage::

    python manage.py check_object_storage
    python manage.py check_object_storage --bucket proof --read-only
"""

from __future__ import annotations

import secrets

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core.storage import s3_client

#: Logical name → the setting that names the bucket. Keyed by what the code
#: calls the bucket, not by its deployed name, which differs per environment.
BUCKET_SETTINGS = {
    "kyc": "S3_BUCKET_KYC",
    "parcel": "S3_BUCKET_PARCEL",
    "dispute": "S3_BUCKET_DISPUTE",
    "proof": "S3_BUCKET_PROOF",
}

_PROBE_PREFIX = ".shiptrip-storage-check"


class Command(BaseCommand):
    help = "Verify Django's own S3 credential can read and write each bucket."

    def add_arguments(self, parser):
        parser.add_argument(
            "--bucket",
            action="append",
            choices=sorted(BUCKET_SETTINGS),
            help="Check only these logical buckets. Repeatable.",
        )
        parser.add_argument(
            "--read-only",
            action="store_true",
            help="Only probe reachability; do not write a probe object.",
        )

    def handle(self, *args, **options):
        selected = options.get("bucket") or sorted(BUCKET_SETTINGS)
        read_only = options["read_only"]
        client = s3_client()

        self.stdout.write(f"endpoint  {settings.S3_ENDPOINT_URL}")
        self.stdout.write(f"region    {settings.S3_REGION}")
        self.stdout.write(
            f"addressing {'path' if settings.S3_USE_PATH_STYLE else 'virtual-hosted'}"
        )
        self.stdout.write("")

        failures: list[str] = []
        # Distinct buckets only: several logical names can point at one bucket,
        # and probing it four times proves nothing extra.
        seen: dict[str, str] = {}
        for name in selected:
            bucket = getattr(settings, BUCKET_SETTINGS[name], "")
            if not bucket:
                failures.append(f"{name}: no bucket configured")
                self.stdout.write(self.style.ERROR(f"{name:8} NOT CONFIGURED"))
                continue
            if bucket in seen:
                self.stdout.write(
                    f"{name:8} {bucket}  (same bucket as {seen[bucket]}, already checked)"
                )
                continue
            seen[bucket] = name

            problem = self._probe(client, bucket, read_only=read_only)
            if problem is None:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{name:8} {bucket}  "
                        f"{'reachable' if read_only else 'writable and readable'}"
                    )
                )
            else:
                failures.append(f"{name} ({bucket}): {problem}")
                self.stdout.write(self.style.ERROR(f"{name:8} {bucket}  {problem}"))

        if failures:
            raise CommandError(
                "Object storage is not usable for: " + "; ".join(failures)
            )
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Every configured bucket is usable."))

    def _probe(self, client, bucket: str, *, read_only: bool) -> str | None:
        """Return a short failure description, or None when the bucket works."""

        try:
            client.head_bucket(Bucket=bucket)
        except Exception as exc:  # noqa: BLE001 — the message is the report
            return f"head_bucket failed: {_short(exc)}"
        if read_only:
            return None

        key = f"{_PROBE_PREFIX}/{secrets.token_urlsafe(12)}.txt"
        payload = b"shiptrip storage check"
        try:
            client.put_object(
                Bucket=bucket, Key=key, Body=payload, ContentType="text/plain"
            )
        except Exception as exc:  # noqa: BLE001
            return f"put_object failed: {_short(exc)}"
        try:
            body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
            if body != payload:
                return "get_object returned different bytes than were written"
        except Exception as exc:  # noqa: BLE001
            return f"get_object failed: {_short(exc)}"
        finally:
            try:
                client.delete_object(Bucket=bucket, Key=key)
            except Exception:  # noqa: BLE001 — cleanup, not the verdict
                self.stderr.write(f"warning: could not delete probe object {key}")
        return None


def _short(exc: Exception) -> str:
    """One line, with the provider's error code but no credential material."""

    code = getattr(exc, "response", {}).get("Error", {}).get("Code")
    http = (
        getattr(exc, "response", {}).get("ResponseMetadata", {}).get("HTTPStatusCode")
    )
    if code:
        return f"{code} (HTTP {http})"
    return f"{type(exc).__name__}: {str(exc)[:120]}"
