"""The AI helper skill as files (spec 20.7, plan L17).

The source of truth is ``apps/admin_helper/skill/``: ``SKILL.md`` (the short
instructions, standard skill layout) and ``knowledge/*.md`` (what the app does,
read from the code, for any "how does ... work?" question). Two things are
built from them and nothing is written twice:

* ``skill_zip()``: the folder ``wassla/`` (``SKILL.md`` and ``knowledge/``) for
  an assistant that installs skills (Claude Code: unzip into ``~/.claude/skills/``).
* ``instructions_text()``: one text for an assistant that takes pasted
  instructions. ``INSTRUCTIONS.txt`` is that text written to disk by
  ``manage.py build_helper_instructions`` and a test fails when they differ.

Neither holds a key or an address: the line the console copies supplies both.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent / "skill"
KNOWLEDGE_DIR = SKILL_DIR / "knowledge"
INSTRUCTIONS_FILE = SKILL_DIR / "INSTRUCTIONS.txt"
SKILL_NAME = "wassla"

#: Plan L17: the core file stays short; the knowledge files carry the rest.
SKILL_MAX_LINES = 140

_PREFACE = (
    "WASSLA ADMIN HELPER: INSTRUCTIONS FOR AN AI ASSISTANT\n"
    "(The same instructions and notes as the skill folder, for assistants that take pasted\n"
    "instructions. Use them whenever the admin starts a message with /wassla.\n"
    "Where the instructions say a notes file, read the matching NOTES section below.)\n"
)
_FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
_COMMENT = re.compile(r"<!--.*?-->[ \t]*\n?", re.DOTALL)


def skill_md() -> str:
    return (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")


def knowledge_files() -> list[Path]:
    return sorted(KNOWLEDGE_DIR.glob("*.md"))


def skill_body() -> str:
    """``SKILL.md`` without its front matter."""

    return _FRONT_MATTER.sub("", skill_md(), count=1).lstrip("\n")


def instructions_text() -> str:
    """The pasted-instructions form: the body, then every notes file."""

    parts = [_PREFACE, skill_body().rstrip() + "\n"]
    for path in knowledge_files():
        body = _COMMENT.sub("", path.read_text(encoding="utf-8")).strip()
        parts.append(f"\n\n==== NOTES: knowledge/{path.name} ====\n\n{body}\n")
    return "\n".join(parts).replace("\n\n\n\n", "\n\n\n")


def skill_zip() -> bytes:
    """The ``wassla/`` skill folder as a zip, built from the files."""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in [SKILL_DIR / "SKILL.md", *knowledge_files()]:
            relative = path.relative_to(SKILL_DIR).as_posix()
            info = zipfile.ZipInfo(f"{SKILL_NAME}/{relative}", date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    return buffer.getvalue()
