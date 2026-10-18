from django.core.management.base import BaseCommand, CommandError
from apps.accounts.models import User
from apps.notifications.backlog import review


class Command(BaseCommand):
    help = "Explicitly release or cancel one reviewed obligation; never sends email."

    def add_arguments(self, parser):
        parser.add_argument("--id", type=int, required=True)
        parser.add_argument("--fingerprint", required=True)
        parser.add_argument("--operator-id", type=int, required=True)
        parser.add_argument("--action", choices=("release", "cancel"), required=True)

    def handle(self, *args, **options):
        try:
            review(
                message_id=options["id"],
                expected_fingerprint=options["fingerprint"],
                action=options["action"],
                actor=User.objects.get(pk=options["operator_id"]),
            )
        except Exception:
            raise CommandError(
                "Review refused; check operator permission and repeat the audit."
            ) from None
        self.stdout.write("Email backlog decision recorded; no email sent.")
