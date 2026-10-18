import json
from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from apps.notifications.backlog import classify
from apps.notifications.models import OutboundMessage


class Command(BaseCommand):
    help = (
        "Read-only email audit. Emits no addresses, bodies, contexts, keys or secrets."
    )

    def add_arguments(self, parser):
        parser.add_argument("--after-id", type=int, default=0)
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        if not 1 <= options["limit"] <= 1000:
            raise CommandError("limit must be 1..1000")
        rows = OutboundMessage.objects.filter(
            status__in=("pending", "failed"), pk__gt=options["after_id"]
        ).order_by("pk")
        reports = [classify(row) for row in rows[: options["limit"]]]
        counts = Counter(f'{item["kind"]}:{item["category"]}' for item in reports)
        self.stdout.write(
            json.dumps(
                {
                    "remaining_count": rows.count(),
                    "page_counts": counts,
                    "messages": reports,
                }
            )
        )
