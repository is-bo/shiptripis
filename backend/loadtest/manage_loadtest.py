"""``manage.py`` for the load harness: the monolith, under ``settings_loadtest``.

Usage (from anywhere)::

    python backend/loadtest/manage_loadtest.py migrate --noinput
    python backend/loadtest/manage_loadtest.py import_geography --skip-if-current
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

LOADTEST_DIR = Path(__file__).resolve().parent
MONOLITH_DIR = LOADTEST_DIR.parent / "monolith"


def bootstrap() -> None:
    """Put the monolith and this directory on the path and pick the settings."""

    for entry in (str(MONOLITH_DIR), str(LOADTEST_DIR)):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    os.environ["DJANGO_SETTINGS_MODULE"] = "settings_loadtest"


if __name__ == "__main__":
    bootstrap()
    os.chdir(MONOLITH_DIR)
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
