"""Granular staff permissions for Phase 4 operational endpoints.

Phase 3's admin routes use DRF's `IsAdminUser`, which is `is_staff` and nothing
finer. That is too blunt for the work Phase 4 introduces: reading a dispute's
evidence means reading a party's photos and chat references, and resolving one
moves money. Those should not be the same capability as viewing a payout queue,
and neither should require a superuser.

So Phase 4 endpoints check a named Django permission, with `is_superuser` as the
only blanket override. The permissions are declared on the models that own them
and granted through four seeded groups matching the roles in the specification.
The full role and admin-UX design remains Phase 6; this is the primitive it will
be built on, established now because retrofitting authorization is how
authorization gaps happen.
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission


class HasAnyPermission(BasePermission):
    """Allow a superuser, or any staff user holding one of `required_perms`.

    Subclass and set `required_perms` to a tuple of `app_label.codename`.
    Staff membership is required on top of the permission: a permission granted
    to a non-staff account by accident does not open an operations endpoint.
    """

    required_perms: tuple[str, ...] = ()
    message = "You do not have permission to perform this operation."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return False
        if getattr(user, "is_superuser", False):
            return True
        if not getattr(user, "is_staff", False):
            return False
        perms = getattr(view, "required_perms", None) or self.required_perms
        return any(user.has_perm(perm) for perm in perms)


class CanViewDisputes(HasAnyPermission):
    required_perms = ("disputes.view_dispute",)


class CanResolveDisputes(HasAnyPermission):
    required_perms = ("disputes.resolve_dispute",)


class CanViewDisputeEvidence(HasAnyPermission):
    required_perms = ("disputes.view_dispute_evidence",)


class CanRecordNoShow(HasAnyPermission):
    required_perms = ("deals.record_no_show",)


class CanSettlePayouts(HasAnyPermission):
    """Send a traveler their money.

    Phase 4 introduced named permissions because "resolving a dispute moves
    money". This endpoint is the half that actually moves it -- an irreversible
    bank transfer -- and it sat on bare `is_staff` while the decision that
    authorises it required `disputes.resolve_dispute`. Either permission opens
    it, so a finance role needs one grant rather than two.
    """

    required_perms = ("finance.settle_payout", "disputes.resolve_dispute")
