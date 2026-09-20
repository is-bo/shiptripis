"""Inspect or repair only funded DZD payouts frozen before initial setup."""

import json
from collections import Counter

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.finance.payout_profiles import require_capabilities
from apps.finance.payout_manual_profiles import approved_profile
from apps.finance.payout_setup_reconciliation import (
    complete_initial_dzd_setup,
    initial_setup_reason,
    reevaluate_settlement_setup,
    pending_setup_rechecks,
    setup_required_payouts,
    SETTLEMENT_BASES,
)


class Command(BaseCommand):
    help = (
        "Dry-run stranded initial DZD setup by default; execute with an audited actor."
    )

    def add_arguments(self, parser):
        parser.add_argument("--payout-id", type=int)
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--actor-id", type=int)

    def handle(self, *args, **options):
        actor = None
        if options["execute"]:
            if not options["actor_id"]:
                raise CommandError(
                    "--execute requires --actor-id with payout review capability."
                )
            actor = User.objects.filter(pk=options["actor_id"]).first()
            if actor is None:
                raise CommandError("Unknown actor.")
            require_capabilities(
                actor, "review_payout_profiles", "view_payout_sensitive"
            )

        queryset = setup_required_payouts().select_related(
            "active_instruction_version__method__current_version__dzd_profile_revision"
        )
        if options["payout_id"]:
            queryset = queryset.filter(pk=options["payout_id"])
        payout_ids = list(queryset.values_list("pk", flat=True))
        reasons = Counter()
        travelers = set()
        approved_current = 0
        reconciled = 0
        for payout_id in payout_ids:
            payout = queryset.get(pk=payout_id)
            travelers.add(payout.traveler_id)
            method = payout.active_instruction_version.method
            reason = initial_setup_reason(payout, method)
            current = method.current_version
            if current and approved_profile(current.dzd_profile_revision):
                approved_current += 1
            if not options["execute"]:
                reasons[reason or "safe_to_reconcile"] += 1
                continue
            result = complete_initial_dzd_setup(payout_id=payout_id, actor=actor)
            if result == "reconciled":
                reconciled += 1
                payout.refresh_from_db()
                if payout.eligibility_basis in SETTLEMENT_BASES:
                    reevaluate_settlement_setup(payout_id=payout_id)
                else:
                    from apps.finance.payout_release import evaluate_payout_release

                    evaluate_payout_release(deal_id=payout.deal_id)
            else:
                reasons[result] += 1
        recheck_ids = list(
            pending_setup_rechecks()
            .filter(**({"pk": options["payout_id"]} if options["payout_id"] else {}))
            .values_list("pk", "deal_id", "eligibility_basis")
        )
        for payout_id, deal_id, basis in recheck_ids:
            if not options["execute"]:
                continue
            if basis in SETTLEMENT_BASES:
                reasons[reevaluate_settlement_setup(payout_id=payout_id)] += 1
            else:
                from apps.finance.payout_release import evaluate_payout_release

                reasons[evaluate_payout_release(deal_id=deal_id)] += 1
        self.stdout.write(
            json.dumps(
                {
                    "mode": "execute" if options["execute"] else "dry_run",
                    "candidates": len(payout_ids),
                    "travelers": len(travelers),
                    "approved_current": approved_current,
                    "reconciled": reconciled,
                    "readiness_rechecks": len(recheck_ids),
                    "results": dict(sorted(reasons.items())),
                    "mutations": bool(options["execute"] and reconciled),
                },
                sort_keys=True,
            )
        )
