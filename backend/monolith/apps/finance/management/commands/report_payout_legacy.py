"""Read-only inventory, safe for operators before any later remediation."""

import json
from django.core.management.base import BaseCommand
from django.db.models import Count, Sum
from apps.finance.models import Payout, PaymentAttempt


class Command(BaseCommand):
    help = "Report legacy payout/mode totals without changing financial history."

    def handle(self, *args, **options):
        self.stdout.write(
            json.dumps(
                {
                    "payouts": list(
                        Payout.objects.filter(snapshot_version=0)
                        .values("legacy_classification", "provider_mode", "status")
                        .annotate(
                            count=Count("id"), amount_eur_cents=Sum("amount_eur_cents")
                        )
                        .order_by("legacy_classification", "provider_mode", "status")
                    ),
                    "attempts": list(
                        PaymentAttempt.objects.values(
                            "provider", "provider_mode", "mode_evidence"
                        )
                        .annotate(count=Count("id"))
                        .order_by("provider", "provider_mode", "mode_evidence")
                    ),
                    "mutations": False,
                },
                sort_keys=True,
            )
        )
