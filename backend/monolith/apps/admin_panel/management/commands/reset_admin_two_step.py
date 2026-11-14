"""Reset one staff account's second step from the server (spec 19.1, L14).

For the last Super Admin, who has nobody to reset it for them from the staff
page. The account enrols again at its next sign-in. The reset is the same as
the console's (`apps.admin_panel.two_step.reset`): the two-step rows are
deleted, every session and AI helper key of the account is ended and one
audit row is written, with no actor and ``via: manage.py``.

    python manage.py reset_admin_two_step owner@example.com --reason "lost phone"
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.admin_panel import two_step


class Command(BaseCommand):
    help = "Reset a staff account's two-step sign-in; it enrols again at next sign-in."

    def add_arguments(self, parser):
        parser.add_argument("email", help="The staff account's email address.")
        parser.add_argument(
            "--reason",
            required=True,
            help="Why, for the audit log (for example: lost phone, identity checked by call).",
        )

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        user = get_user_model().objects.filter(email__iexact=email).first()
        if user is None:
            raise CommandError(f"No account uses {email}.")
        try:
            result = two_step.reset(
                actor=None, target=user, reason=options["reason"], via="manage.py"
            )
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from None
        self.stdout.write(
            self.style.SUCCESS(
                f"Two-step sign-in reset for {user.email}; "
                f"{result['sessions_ended']} session(s) and "
                f"{result['helper_keys_stopped']} AI helper key(s) ended. "
                "They set it up again at their next sign-in."
            )
        )
