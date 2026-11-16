"""Plan L19 item 1: the helper's notes say what the server does about disputes.

L18A removed the uncalled staff path into a dispute, and its own search
(`apps/disputes/tests/test_l18a_removed_paths.py`) proves that no code and no
note names the removed functions. A sentence in the notes still described that
path in plain words (release report, section 14, finding 1). The Super Admin
asks the skill how the app works, so it must not describe code that is gone.
"""

from __future__ import annotations

import re

from django.test import SimpleTestCase

from apps.admin_helper import skill

#: Plain words that would describe a staff way into a dispute.
STALE = re.compile(
    r"staff[- ]side way to open a dispute|"
    r"(server|code) has a (staff|admin)[^.\n]* (way|path) to open",
    re.IGNORECASE,
)


class DisputeNotesTests(SimpleTestCase):
    def test_no_note_describes_a_staff_way_to_open_a_dispute(self):
        for path in [skill.SKILL_DIR / "SKILL.md", *skill.knowledge_files()]:
            lines = path.read_text(encoding="utf-8").splitlines()
            for number, line in enumerate(lines, 1):
                assert not STALE.search(line), f"{path.name}:{number}: {line}"
        assert not STALE.search(skill.instructions_text())

    def test_the_notes_still_say_staff_cannot_open_a_dispute(self):
        for name in ("architecture-and-diagrams.md", "problems-and-disputes.md"):
            text = (skill.KNOWLEDGE_DIR / name).read_text(encoding="utf-8")
            assert "Staff cannot open a dispute" in text, name
