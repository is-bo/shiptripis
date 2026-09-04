from django.core.management.base import BaseCommand, CommandError

from apps.notifications.push import deactivate_stale_push_devices


class Command(BaseCommand):
    help = "Deactivate push installations that have not checked in recently."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=180)

    def handle(self, *args, **options):
        try:
            count = deactivate_stale_push_devices(days=options["days"])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(f"Deactivated {count} stale push device(s).")
        )
