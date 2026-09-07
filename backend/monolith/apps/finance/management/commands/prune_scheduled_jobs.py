"""Conservatively prune disposable job execution rows, never finance records."""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.finance.models import ScheduledJob


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

    def handle(self, *args, **options):
        days = int(options["days"])
        if days < 30:
            raise CommandError("Retention must be at least 30 days.")
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
        with transaction.atomic():
            ids = list(
                eligible.select_for_update(no_key=True)
                .order_by("pk")
                .values_list("pk", flat=True)
            )
            ScheduledJob.objects.filter(pk__in=ids).delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"deleted {len(ids)} scheduled job row(s); "
                "no payment, ledger, provider-event, refund, payout, or audit rows were targeted"
            )
        )
