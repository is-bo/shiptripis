"""The base every staff JSON API view under ``/api/admin/`` is built on.

Plan 2.12 and L14 (settled by the advisor on 2026-11-14): the staff API answers
only inside a console session that passed the second step. It therefore
authenticates by the console's session cookie alone, with Django's CSRF check
on every write, and never by a bearer token: a token from the mobile sign-in
proves a password, not the second step. The second-step gate itself is in
`HasAdminPermission`, which every staff view uses.

The only staff API route that answers without the second step is listed in
`OPEN_STAFF_API_ROUTES`; the route inventory test holds the API to that list.
"""

from __future__ import annotations

from rest_framework.authentication import SessionAuthentication
from rest_framework.views import APIView

#: Session only. A bearer token alone is refused (`admin_two_step_required`).
STAFF_API_AUTHENTICATION = (SessionAuthentication,)

#: Staff API routes, by URL name, that answer without a verified session.
#: ``admin-invitation-accept`` creates the account an invitation names, before
#: anything can be enrolled, and returns nothing that opens another route.
#: L15 adds the AI helper's routes, which take a helper key and no session.
OPEN_STAFF_API_ROUTES = frozenset({"admin-invitation-accept"})


class StaffSessionMixin:
    """For a staff view that cannot inherit `StaffAPIView` (it shares a base
    with a member route). Its permission class must still be a
    `HasAdminPermission`, which holds the second-step gate."""

    authentication_classes = STAFF_API_AUTHENTICATION


class StaffAPIView(StaffSessionMixin, APIView):
    pass
