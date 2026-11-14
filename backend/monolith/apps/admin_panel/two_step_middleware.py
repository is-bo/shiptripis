"""Every page under ``/admin/`` waits for the staff second step (spec 19.1).

A signed-in staff member whose session has not passed the second step is sent
to it, whatever console or technical admin page they asked for, and comes back
to that page afterwards. Only the pages that lead there stay open: sign-in,
sign-out, the two-step pages themselves and the invitation acceptance page
(which creates the account, before anything can be enrolled).

Someone who is not signed in, or is not staff, passes through: the page's own
guard sends them to sign-in or refuses them, as before. The staff JSON API is
not covered here; `HasAdminPermission` holds its gate (plan 2.12).
"""

from __future__ import annotations

from functools import cached_property
from urllib.parse import urlencode

from django.http import HttpResponseRedirect
from django.urls import reverse

from .permissions import has_admin_access
from .two_step import required, two_step_satisfied

ADMIN_PREFIX = "/admin/"


class AdminTwoStepMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    @cached_property
    def open_paths(self) -> tuple[str, ...]:
        return (
            reverse("admin:login"),
            reverse("admin:logout"),
            reverse("admin-invitation-accept-page"),
        )

    @cached_property
    def two_step_prefix(self) -> str:
        return reverse("admin_console:two-step")

    def _guarded(self, path: str) -> bool:
        if not (path.startswith(ADMIN_PREFIX) or path == ADMIN_PREFIX.rstrip("/")):
            return False
        return path not in self.open_paths and not path.startswith(self.two_step_prefix)

    def __call__(self, request):
        if (
            self._guarded(request.path)
            and required()
            and has_admin_access(request.user)
            and not two_step_satisfied(request)
        ):
            back = (
                request.get_full_path()
                if request.method in ("GET", "HEAD")
                else request.path
            )
            return HttpResponseRedirect(
                f"{self.two_step_prefix}?{urlencode({'next': back})}"
            )
        return self.get_response(request)
