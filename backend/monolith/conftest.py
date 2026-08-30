"""Test-session setup.

The only thing here is a forward-compatibility shim for the interpreter a
developer happens to have, not for the one the product ships on. CI and the
container image both pin Python 3.12 (`.github/workflows/ci.yml`,
`backend/monolith/Dockerfile`); nothing below runs there.
"""

from __future__ import annotations

import sys


def _patch_template_context_copy() -> None:
    """Django 5.1 cannot copy a template context on Python 3.14.

    `BaseContext.__copy__` is written as `duplicate = copy(super())`. Copying a
    `super` proxy returned a real instance up to Python 3.13; from 3.14 it
    returns the proxy, and the next line — `duplicate.dicts = ...` — raises
    `AttributeError`. It fires inside `InclusionAdminNode`, so on 3.14 every
    admin changelist and change form 500s and every test that renders one
    fails, with nothing wrong in this codebase.

    Django fixes this upstream. Until the pinned version moves, this restores
    the pre-3.14 behaviour so an admin test means what it says on whichever
    interpreter it is run with.
    """

    if sys.version_info < (3, 14):
        return
    from django.template.context import BaseContext

    def __copy__(self):  # noqa: N807 - matching the name being replaced
        duplicate = BaseContext.__new__(type(self))
        duplicate.__dict__.update(self.__dict__)
        duplicate.dicts = self.dicts[:]
        return duplicate

    BaseContext.__copy__ = __copy__


_patch_template_context_copy()
