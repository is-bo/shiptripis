"""Throttles for the public reads a guest makes while browsing (plan EGS).

Algerian mobile carriers put hundreds of people behind one IPv4 address
(carrier-grade NAT), so on a public read a per-address bucket is shared by
every guest on that network. Those reads therefore count a guest, a caller
without an account, on one roomy per-address scope, `discovery_guest`, and
nothing else; a member is never counted there and keeps the per-member
throttles the view already had. Every other endpoint keeps the shared `anon`
and `user` rates.
"""

from __future__ import annotations

from rest_framework.throttling import (
    AnonRateThrottle,
    ScopedRateThrottle,
    UserRateThrottle,
)


class GuestRateThrottle(AnonRateThrottle):
    """The `discovery_guest` bucket, per address, for a guest only."""

    scope = "discovery_guest"


class _MembersOnly:
    """Counts a member only: a guest is answered by `GuestRateThrottle`."""

    def get_cache_key(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return None
        return super().get_cache_key(request, view)


class MemberRateThrottle(_MembersOnly, UserRateThrottle):
    """The shared per-member `user` rate."""


class MemberScopedRateThrottle(_MembersOnly, ScopedRateThrottle):
    """The view's `throttle_scope`, per member."""


#: The throttles of a public read: a guest by address on `discovery_guest`, a
#: member on the `user` rate.
PUBLIC_READ_THROTTLES = (GuestRateThrottle, MemberRateThrottle)
