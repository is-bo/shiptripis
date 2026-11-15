"""Write ``apps/admin_helper/skill/INSTRUCTIONS.txt`` from ``SKILL.md`` and ``knowledge/`` (plan L17).

``--check`` writes nothing and fails when the file is out of date.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.admin_helper import skill


class Command(BaseCommand):
    help = "Regenerate the AI helper's pasted-instructions file from the skill."

    def add_arguments(self, parser):
        parser.add_argument("--check", action="store_true", help="Fail if the file is out of date.")

    def handle(self, *args, **options):
        wanted = skill.instructions_text()
        current = skill.INSTRUCTIONS_FILE.read_text(encoding="utf-8") if skill.INSTRUCTIONS_FILE.exists() else None
        if options["check"]:
            if current != wanted:
                raise CommandError("INSTRUCTIONS.txt is out of date. Run: manage.py build_helper_instructions")
            self.stdout.write("INSTRUCTIONS.txt is up to date.")
            return
        skill.INSTRUCTIONS_FILE.write_text(wanted, encoding="utf-8")
        self.stdout.write(f"Wrote {skill.INSTRUCTIONS_FILE.name} ({len(wanted.splitlines())} lines).")
