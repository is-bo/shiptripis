"""Doors that need a confirmed email (L18A, plan L18A items 2 and 6).

V1 asks a sender to verify their email, and nothing enforced it. A confirmed
address is also what makes an account its owner's (see `sessions.py`), so the
routes that would let an unproven person plant something for the owner to
inherit refuse until it is confirmed: posting a parcel, and writing payout
setup. Reads stay open; nothing else is gated.
"""

from __future__ import annotations

from rest_framework.permissions import SAFE_METHODS, BasePermission

#: The stable refusal code the app turns into the verify-email screen.
EMAIL_VERIFICATION_REQUIRED = "email_verification_required"


class EmailVerifiedToWrite(BasePermission):
    """Unsafe methods need `is_email_verified`; reads pass.

    Put after `IsAuthenticated`. The refusal is a 403 with
    `{"code": "email_verification_required", "detail": ...}`, raised before the
    view reads the body, so a refused call writes nothing.
    """

    message = {
        "code": EMAIL_VERIFICATION_REQUIRED,
        "detail": "Confirm your email address first.",
    }

    def has_permission(self, request, view) -> bool:
        if request.method in SAFE_METHODS:
            return True
        return bool(getattr(request.user, "is_email_verified", False))
