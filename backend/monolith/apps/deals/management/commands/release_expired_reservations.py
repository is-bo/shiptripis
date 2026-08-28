from django.core.management.base import BaseCommand, CommandError

from apps.deals.services import release_expired_reservations


class Command(BaseCommand):
    help = "Release expired pending-payment leg reservations idempotently."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        del args
        try:
            results = release_expired_reservations(limit=options["limit"])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        changed = sum(result.changed for result in results)
        allocations = sum(result.released_allocations for result in results)
        self.stdout.write(
            self.style.SUCCESS(
                f"Released {allocations} allocation(s) across {changed} deal(s)."
            )
        )
