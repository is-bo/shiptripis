"""Compile the repository's small gettext PO catalogues without GNU gettext.

CI images may use Django's ordinary ``compilemessages`` command. Windows
development machines in this project do not always have ``msgfmt`` installed,
so this dependency-free compiler keeps the committed MO files reproducible.
It supports the singular msgid/msgstr records used by ShipTrip email copy.
"""

from __future__ import annotations

import ast
import struct
import sys
from pathlib import Path


def _catalog(path: Path) -> dict[str, str]:
    messages: dict[str, str] = {}
    msgid = ""
    msgstr = ""
    active: str | None = None

    def finish() -> None:
        nonlocal msgid, msgstr, active
        if active is not None and msgstr:
            messages[msgid] = msgstr
        msgid = ""
        msgstr = ""
        active = None

    for raw in [*path.read_text(encoding="utf-8").splitlines(), ""]:
        line = raw.strip()
        if not line:
            finish()
            continue
        if line.startswith("#"):
            continue
        if line.startswith("msgid "):
            if active == "msgstr":
                finish()
            active = "msgid"
            msgid = ast.literal_eval(line[6:])
            continue
        if line.startswith("msgstr "):
            active = "msgstr"
            msgstr = ast.literal_eval(line[7:])
            continue
        if line.startswith('"') and active:
            value = ast.literal_eval(line)
            if active == "msgid":
                msgid += value
            else:
                msgstr += value
            continue
        raise ValueError(f"Unsupported PO syntax in {path}: {raw}")
    return messages


def compile_po(path: Path) -> Path:
    messages = _catalog(path)
    keys = sorted(messages)
    ids = b""
    strings = b""
    id_offsets: list[tuple[int, int]] = []
    string_offsets: list[tuple[int, int]] = []
    for key in keys:
        encoded = key.encode("utf-8")
        id_offsets.append((len(encoded), len(ids)))
        ids += encoded + b"\0"
        translated = messages[key].encode("utf-8")
        string_offsets.append((len(translated), len(strings)))
        strings += translated + b"\0"

    count = len(keys)
    key_table_offset = 7 * 4
    value_table_offset = key_table_offset + count * 8
    ids_offset = value_table_offset + count * 8
    strings_offset = ids_offset + len(ids)
    output = [
        struct.pack(
            "<7I",
            0x950412DE,
            0,
            count,
            key_table_offset,
            value_table_offset,
            0,
            0,
        )
    ]
    output.extend(
        struct.pack("<2I", length, ids_offset + offset)
        for length, offset in id_offsets
    )
    output.extend(
        struct.pack("<2I", length, strings_offset + offset)
        for length, offset in string_offsets
    )
    output.extend((ids, strings))
    destination = path.with_suffix(".mo")
    destination.write_bytes(b"".join(output))
    return destination


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("usage: compile_po.py PATH [PATH ...]")
    for argument in sys.argv[1:]:
        source = Path(argument).resolve()
        destination = compile_po(source)
        print(f"compiled {source} -> {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
