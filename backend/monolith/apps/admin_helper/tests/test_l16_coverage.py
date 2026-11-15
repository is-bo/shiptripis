"""Plan L16: every console POST is a helper action or on the "never" list.

Read from the console's own source, so a page that starts taking a POST
without a decision here fails this test.
"""

from __future__ import annotations

import inspect
import re

from django.test import SimpleTestCase

from apps.admin_helper import actions
from apps.admin_panel import console_urls

_POST = re.compile(r"request\.POST|require_POST|request\.method\s*[!=]=\s*[\"']POST[\"']")


def _functions(view, seen=None):
    """The view and everything it wraps: decorators, and the functions their
    closures hold, whether or not they use `functools.wraps`."""

    seen = set() if seen is None else seen
    if not callable(view) or id(view) in seen:
        return
    seen.add(id(view))
    if inspect.isfunction(view):
        yield view
    wrapped = getattr(view, "__wrapped__", None)
    if wrapped is not None:
        yield from _functions(wrapped, seen)
    for cell in getattr(view, "__closure__", None) or ():
        try:
            content = cell.cell_contents
        except ValueError:
            continue
        if inspect.isfunction(content):
            yield from _functions(content, seen)


def takes_post(view) -> bool:
    return any(_POST.search(inspect.getsource(function)) for function in _functions(view))


class ConsolePostCoverageTests(SimpleTestCase):
    def routes(self) -> dict[str, object]:
        return {pattern.name: pattern.callback for pattern in console_urls.urlpatterns}

    def test_every_console_post_is_an_action_or_never(self):
        posting = {name for name, view in self.routes().items() if takes_post(view)}
        decided = set(actions.CONSOLE_POSTS) | set(actions.NEVER)
        assert not set(actions.CONSOLE_POSTS) & set(actions.NEVER)
        assert posting == decided, (sorted(posting - decided), sorted(decided - posting))

    def test_the_pages_name_the_whole_registry(self):
        named = [code for codes in actions.CONSOLE_POSTS.values() for code in codes]
        assert len(named) == len(set(named))
        assert set(named) == set(actions.registry())
        assert set(actions.NEVER_ON_PAGE) <= set(actions.CONSOLE_POSTS)
        assert all(reason.endswith(".") for reason in [*actions.NEVER.values(), *actions.NEVER_ON_PAGE.values()])

    def test_the_plans_never_list_is_kept(self):
        # Plan L16, "in particular": each is a console POST the helper cannot reach.
        for route in (
            "staff", "staff-role", "staff-access", "staff-invitation-action", "settings",
            "ai-helper-create", "ai-helper-stop", "two-step-verify", "staff-two-step-reset",
            "payout-review-detail", "kyc-detail", "proof-detail", "identity-check-detail",
            "payment-reconcile", "payment-resolve", "refund-detail",
        ):
            assert route in actions.NEVER, route
        assert "dinar" in actions.NEVER_ON_PAGE["payout-detail"]

    def test_no_entry_saves_a_model_itself(self):
        source = inspect.getsource(actions)
        assert ".save(" not in source and ".objects.create(" not in source
        assert ".update(" not in source and ".delete(" not in source
