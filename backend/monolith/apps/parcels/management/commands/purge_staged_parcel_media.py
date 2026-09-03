"""Reclaim item photos that were uploaded but never posted.

Phase 8F-B stages the required item photo before the request exists, which is
what makes "no live request without a photo" true. The cost of that ordering
is the other tail: a sender who uploads a photo and then abandons the form
leaves a row and an object nobody will ever read.

Nothing depends on this running — an unclaimed row is inert and invisible to
everyone but its uploader — so it is a command rather than a startup hook or a
signal. Run it on a schedule when the environment has one.

Usage::

    python manage.py purge_staged_parcel_media
    python manage.py purge_staged_parcel_media --older-than-hours 168 --dry-run
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core.storage import s3_client
from apps.parcels.models import ParcelMedia


class Command(BaseCommand):
    help = "Delete unclaimed staged parcel item photos and their objects."

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than-hours",
            type=int,
            default=None,
            help=(
                "Age threshold in hours. Defaults to "
                "settings.PARCEL_STAGED_MEDIA_TTL_HOURS."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be removed without removing anything.",
        )

    def handle(self, *args, **options):
        hours = options["older_than_hours"]
        if hours is None:
            hours = int(getattr(settings, "PARCEL_STAGED_MEDIA_TTL_HOURS", 48) or 48)
        cutoff = timezone.now() - timedelta(hours=hours)
        dry_run = options["dry_run"]

        stale = ParcelMedia.objects.filter(
            parcel__isnull=True, created_at__lt=cutoff
        ).order_by("pk")
        total = stale.count()
        self.stdout.write(
            f"{total} staged photo(s) older than {hours}h"
            f"{' (dry run)' if dry_run else ''}"
        )
        if dry_run or total == 0:
            return

        client = s3_client()
        removed = 0
        for media in stale.iterator(chunk_size=200):
            try:
                client.delete_object(Bucket=media.bucket, Key=media.object_key)
            except Exception as exc:  # noqa: BLE001 — one object must not stop the run
                # Leave the row so a later run retries. An object we failed to
                # delete with a row still pointing at it is recoverable; an
                # object with no row pointing at it is not.
                self.stderr.write(f"skip media#{media.pk}: {type(exc).__name__}")
                continue
            media.delete()
            removed += 1

        self.stdout.write(self.style.SUCCESS(f"removed {removed} staged photo(s)"))
