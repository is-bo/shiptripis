"""How a person appears to the helper (plan 2.11): id, short name, console link.

``{"id": 42, "display": "Amina B.", "console_url": "https://.../admin/users/42/"}``
and nothing else, ever. The short name is the first name and the last initial.
A name that does not look like a name (it holds an ``@``, a digit, a dot or a symbol)
is never sent, because people do type an email or a phone number into a name
field; the person is then "Member 42".
"""

from __future__ import annotations

import unicodedata

#: Characters a name may hold between letters ("Jean-Luc", "O'Neil").
_NAME_JOINERS = frozenset("-'’")
_MAX_NAME_PART = 30


def _looks_like_a_name(token: str) -> bool:
    """Letters joined by hyphens or apostrophes, or one initial with its dot.

    A dot anywhere else is refused, so a handle such as ``amina.benali.mail``
    is never sent as a name.
    """

    if token.endswith(".") and len(token) == 2:
        token = token[0]
    if not token or len(token) > _MAX_NAME_PART:
        return False
    letters = 0
    for char in token:
        if char in _NAME_JOINERS:
            continue
        if not unicodedata.category(char).startswith("L"):
            return False
        letters += 1
    return letters > 0


def short_name(user) -> str:
    """``"Amina B."`` for "Amina Benali", ``"Amina"`` for "Amina", else "Member <id>"."""

    parts = (getattr(user, "full_name", "") or "").split()
    if not parts or not all(_looks_like_a_name(part) for part in parts):
        return f"Member {user.pk}"
    first = parts[0]
    if len(parts) == 1:
        return first
    initial = next(char for char in parts[-1] if char not in _NAME_JOINERS and char != ".")
    return f"{first} {initial.upper()}."
