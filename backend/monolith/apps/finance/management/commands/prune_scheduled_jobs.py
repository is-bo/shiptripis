"""Conservatively prune disposable job execution rows, never finance records."""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.finance.models import ScheduledJob

DEFAULT_BATCH_SIZE = 1_000


class Command(BaseCommand):
    help = (
        "Dry-run/prune succeeded or operator-resolved ScheduledJob rows older "
        "than the retention window. Financial and unresolved records are never selected."
    )

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=90)
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Perform the deletion. Without this flag the command is read-only.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=(
                "Rows locked and deleted per transaction "
                f"(default {DEFAULT_BATCH_SIZE})."
            ),
        )

    def handle(self, *args, **options):
        days = int(options["days"])
        if days < 30:
            raise CommandError("Retention must be at least 30 days.")
        batch_size = int(options["batch_size"])
        if batch_size < 1:
            raise CommandError("Batch size must be at least 1.")
        cutoff = timezone.now() - timedelta(days=days)
        eligible = ScheduledJob.objects.filter(completed_at__lt=cutoff).filter(
            Q(status=ScheduledJob.Status.SUCCEEDED)
            | Q(status=ScheduledJob.Status.FAILED, resolution__gt="")
        )
        count = eligible.count()
        if not options["execute"]:
            self.stdout.write(
                f"dry-run: {count} scheduled job row(s) older than {days} days eligible"
            )
            return
        # K7-E: one bounded transaction per batch, walking the primary key, so
        # a large backlog never holds every eligible row lock (and one huge
        # DELETE) in a single transaction. The cutoff is fixed above and each
        # batch re-applies the same filter under its lock, so exactly the rows
        # the single-transaction version selected are deleted.
        deleted = 0
        last_pk = 0
        while True:
            with transaction.atomic():
                ids = list(
                    eligible.filter(pk__gt=last_pk)
                    .select_for_update(no_key=True)
                    .order_by("pk")
                    .values_list("pk", flat=True)[:batch_size]
                )
                if not ids:
                    break
                ScheduledJob.objects.filter(pk__in=ids).delete()
            deleted += len(ids)
            last_pk = ids[-1]
        self.stdout.write(
            self.style.SUCCESS(
                f"deleted {deleted} scheduled job row(s); "
                "no payment, ledger, provider-event, refund, payout, or audit rows were targeted"
            )
        )
