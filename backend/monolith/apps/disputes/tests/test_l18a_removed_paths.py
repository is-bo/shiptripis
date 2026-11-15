"""L18A: the staff dispute paths nothing called are gone.

`open_dispute(as_admin=True)` skipped the party check and the window, and
`close_dispute` would have ended a dispute without a resolution, leaving the
payout frozen. Neither had a console page, staff API route or helper action.
This search proves neither has a definition or a caller left in the code.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.disputes import services

THIS_FILE = Path(__file__).resolve()
SEARCHED = ("apps", "config")
PATTERN = re.compile(r"\bas_admin\b|\bclose_dispute\b")


class RemovedDisputePathsTests(SimpleTestCase):
    def test_no_definition_or_caller_remains(self):
        root = Path(settings.BASE_DIR)
        hits = []
        for folder in SEARCHED:
            for path in (root / folder).rglob("*.py"):
                if path.resolve() == THIS_FILE:
                    continue
                for number, line in enumerate(path.read_text().splitlines(), 1):
                    if PATTERN.search(line):
                        hits.append(f"{path.relative_to(root)}:{number}: {line.strip()}")
        self.assertEqual(hits, [])

    def test_open_dispute_takes_no_staff_switch(self):
        self.assertNotIn("as_admin", inspect.signature(services.open_dispute).parameters)
        self.assertFalse(hasattr(services, "close_dispute"))
