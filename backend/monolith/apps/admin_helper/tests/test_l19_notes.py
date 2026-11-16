"""Plan L19 item 1: the helper's notes say what the server does about disputes.

L18A removed the uncalled staff path into a dispute (`open_dispute(as_admin=True)`)
and the uncalled `close_dispute`. A line in the notes kept describing the first
one (release report, section 14, finding 1). The Super Admin asks the skill how
the app works, so it must not describe code that is gone.
"""

from __future__ import annotations

import inspect
import re

from django.test import SimpleTestCase

from apps.admin_helper import skill
from apps.disputes import services as dispute_services

#: Wording that would describe a staff way into, or out of, a dispute.
STALE = re.compile(
    r"as_admin|close_dispute|staff[- ]side way to open a dispute|"
    r"(server|code) has a (staff|admin)[^.\n]* (way|path) to open",
    re.IGNORECASE,
)


class DisputeNotesTests(SimpleTestCase):
    def test_the_server_has_no_staff_way_to_open_or_close_a_dispute(self):
        parameters = inspect.signature(dispute_services.open_dispute).parameters
        assert set(parameters) == {"deal_id", "actor_id", "category", "reason_text"}
        assert not hasattr(dispute_services, "close_dispute")

    def test_no_note_describes_a_staff_way_to_open_a_dispute(self):
        for path in [skill.SKILL_DIR / "SKILL.md", *skill.knowledge_files()]:
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                assert not STALE.search(line), f"{path.name}:{number}: {line}"
        assert not STALE.search(skill.instructions_text())

    def test_the_notes_still_say_staff_cannot_open_a_dispute(self):
        for name in ("architecture-and-diagrams.md", "problems-and-disputes.md"):
            text = (skill.KNOWLEDGE_DIR / name).read_text(encoding="utf-8")
            assert "Staff cannot open a dispute" in text, name
