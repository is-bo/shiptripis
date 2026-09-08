"""Phase 6A administrative roles and capabilities.

Roles are represented by Django ``Group`` rows, while this module keeps the
permission vocabulary in one place for API/view code.  A role is deliberately
not a free-form set of permissions: invitations and role-management helpers
accept only one of :data:`ROLE_CHOICES`, and the migration assigns the fixed
matrix below.
"""

from __future__ import annotations

from collections.abc import Iterable

from django.contrib.auth.models import Group
from rest_framework.permissions import BasePermission


class AdminRole:
    """Stable role slugs and their human-facing group names."""

    OPS = "ops"
    SUPPORT = "support"
    FINANCE = "finance"
    TRUST = "trust_verification"
    SUPER_ADMIN = "super_admin"


ROLE_GROUP_NAMES: dict[str, str] = {
    AdminRole.OPS: "Ops",
    AdminRole.SUPPORT: "Support",
    AdminRole.FINANCE: "Finance",
    AdminRole.TRUST: "Trust / Verification",
    AdminRole.SUPER_ADMIN: "Super Admin",
}

# Phase 4 shipped four compatibility groups before the granular Phase 6A
# matrix existed.  They are migration aliases, not an additional privilege
# tier.  Keeping them around after a role change would make a downgrade
# ineffective because Django permissions are additive across groups.
LEGACY_ADMIN_GROUP_TO_ROLE: dict[str, str] = {
    "Operations Admin": AdminRole.OPS,
    "Support Agent": AdminRole.SUPPORT,
    "Finance Admin": AdminRole.FINANCE,
    "Trust & Verification Admin": AdminRole.TRUST,
}

ROLE_CHOICES = tuple(ROLE_GROUP_NAMES.items())
ROLE_SLUGS = frozenset(ROLE_GROUP_NAMES)

# These codenames are intentionally resource/action oriented.  The model that
# owns them is AdminAuditLog; using a single content type keeps the matrix
# inspectable and avoids granting broad Django ``change_*`` permissions.
ADMIN_PERMISSION_CODES: tuple[str, ...] = (
    "view_dashboard",
    "view_users",
    "view_user_sensitive",
    "manage_users",
    "view_requests",
    "manage_requests",
    "view_journeys",
    "manage_journeys",
    "view_matches",
    "manage_matches",
    "view_deals",
    "manage_deals",
    "manage_lifecycle",
    "view_operational_incidents",
    "view_support_context",
    "manage_cancellations",
    "view_kyc",
    "review_kyc",
    "view_flight_proofs",
    "review_flight_proofs",
    "view_evidence",
    "view_disputes",
    "manage_disputes",
    "resolve_disputes",
    "review_safety",
    "record_no_show",
    "view_payment_orders",
    "view_payment_attempts",
    "view_provider_events",
    "issue_refunds",
    "settle_manual_refunds",
    "view_payouts",
    "settle_payouts",
    "reconcile_finance",
    "view_scheduled_jobs",
    "view_ratings",
    "view_boosts",
    "view_provider_health",
    "view_settings",
    "manage_settings",
    "manage_admins",
    "manage_permissions",
    "view_audit_log",
    "view_finance_summary",
    "view_payout_sensitive",
    "view_payout_evidence",
    "review_payout_profiles",
    "attest_payout_identity",
    "manage_payout_holds",
    "retry_payouts",
)

# Explicit least-privilege matrix.  ``super_admin`` receives every code in the
# migration; it is listed here as an explicit role so callers can render a
# permission matrix without special-casing it.
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    AdminRole.OPS: frozenset(
        {
            "view_dashboard",
            "view_requests",
            "manage_requests",
            "view_journeys",
            "manage_journeys",
            "view_matches",
            "manage_matches",
            "view_deals",
            "manage_deals",
            "manage_lifecycle",
            "view_operational_incidents",
            "view_support_context",
            "view_ratings",
            "view_boosts",
            "view_audit_log",
            "record_no_show",
            "view_disputes",
            "manage_disputes",
            "view_provider_health",
        }
    ),
    AdminRole.SUPPORT: frozenset(
        {
            "view_dashboard",
            "view_users",
            "view_requests",
            "view_journeys",
            "view_deals",
            "view_support_context",
            "manage_cancellations",
            "view_ratings",
            "view_audit_log",
            "view_disputes",
        }
    ),
    AdminRole.FINANCE: frozenset(
        {
            "view_finance_summary",
            "view_payout_sensitive",
            "view_payout_evidence",
            "review_payout_profiles",
            "manage_payout_holds",
            "retry_payouts",
            "view_dashboard",
            "view_deals",
            "view_payment_orders",
            "view_payment_attempts",
            "view_provider_events",
            "issue_refunds",
            "settle_manual_refunds",
            "view_payouts",
            "settle_payouts",
            "reconcile_finance",
            "view_scheduled_jobs",
            "view_provider_health",
            "view_audit_log",
            "view_disputes",
            "resolve_disputes",
        }
    ),
    AdminRole.TRUST: frozenset(
        {
            "attest_payout_identity",
            "manage_payout_holds",
            "view_dashboard",
            "view_users",
            "view_user_sensitive",
            "view_kyc",
            "review_kyc",
            "view_flight_proofs",
            "review_flight_proofs",
            "view_evidence",
            "review_safety",
            "record_no_show",
            "view_deals",
            "view_audit_log",
            "view_disputes",
            "manage_disputes",
        }
    ),
    AdminRole.SUPER_ADMIN: frozenset(ADMIN_PERMISSION_CODES),
}

PERMISSION_LABELS: dict[str, str] = {
    code: "Can " + code.replace("_", " ") for code in ADMIN_PERMISSION_CODES
}


def normalize_role(role: str) -> str:
    """Return a role slug, accepting the group label for admin UX/API use."""

    candidate = (role or "").strip()
    if candidate in ROLE_SLUGS:
        return candidate
    folded = candidate.casefold()
    for slug, label in ROLE_GROUP_NAMES.items():
        if folded == label.casefold():
            return slug
    raise ValueError(f"Unknown administrative role: {role!r}")


def role_group(role: str, *, create: bool = True) -> Group:
    """Resolve a role's Django group, optionally creating its seed row."""

    slug = normalize_role(role)
    group, created = Group.objects.get_or_create(name=ROLE_GROUP_NAMES[slug])
    if created and not create:
        raise Group.DoesNotExist
    return group


def admin_permission(codename: str) -> str:
    """Return the fully-qualified Django permission name."""

    if codename not in ADMIN_PERMISSION_CODES:
        raise ValueError(f"Unknown administrative permission: {codename!r}")
    return f"admin_panel.{codename}"


def has_all_admin_permissions(user, *codes: str) -> bool:
    """Fresh capability AND gate, including immediate downgrade/ban revocation.

    Reload identity and permission membership instead of Django's per-instance
    cached has_perm set. Sensitive payout services use this boundary each time.
    """
    from django.contrib.auth import get_user_model

    if not getattr(user, "is_authenticated", False) or not codes:
        return False
    current = get_user_model().objects.filter(pk=user.pk).first()
    return bool(
        current
        and current.is_active
        and not current.is_banned
        and all(has_admin_permission(current, code) for code in codes)
    )


def has_admin_permission(user, codename: str) -> bool:
    """Check a Phase 6A capability with a staff boundary.

    Django's ``is_superuser`` is an intentional blanket override.  The
    bootstrap command creates the initial Super Admin as a superuser; ordinary
    staff accounts receive only the permissions assigned by their role group.
    """

    if not getattr(user, "is_authenticated", False):
        return False
    if not getattr(user, "is_staff", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    try:
        permission = admin_permission(codename)
    except ValueError:
        return False
    return bool(user.has_perm(permission))


def assign_admin_roles(
    user, roles: Iterable[str], *, elevate_super_admin: bool = False
):
    """Replace a user's Phase 6A role groups with validated roles.

    Legacy Phase 4 administrator groups are removed from this account.  Their
    model-specific permissions are seeded on the corresponding Phase 6A role
    group, so replacing a role really does revoke the old role's capabilities.
    Unrelated business groups are left untouched.
    """

    slugs = {normalize_role(role) for role in roles}
    groups = [role_group(slug) for slug in slugs]
    phase6_names = set(ROLE_GROUP_NAMES.values())
    legacy_names = set(LEGACY_ADMIN_GROUP_TO_ROLE)
    user.groups.remove(*Group.objects.filter(name__in=phase6_names | legacy_names))
    if groups:
        user.groups.add(*groups)
        user.is_staff = True
        user.role = "admin"
    elif not user.is_superuser:
        user.is_staff = False
    if elevate_super_admin:
        user.is_superuser = AdminRole.SUPER_ADMIN in slugs
    user.save(update_fields=("is_staff", "role", "is_superuser"))
    return tuple(sorted(slugs))


def user_admin_roles(user) -> tuple[str, ...]:
    """Return the validated Phase 6A role slugs assigned to ``user``."""

    names = set(
        user.groups.filter(name__in=ROLE_GROUP_NAMES.values()).values_list(
            "name", flat=True
        )
    )
    return tuple(
        sorted(slug for slug, name in ROLE_GROUP_NAMES.items() if name in names)
    )


class HasAdminPermission(BasePermission):
    """DRF permission class for a single Phase 6A capability.

    Views set ``required_admin_permission = "view_users"`` (or a tuple for an
    OR gate).  ``is_superuser`` remains the explicit blanket override; all
    other users must be staff and hold the named permission through a seeded
    role group.
    """

    required_admin_permission: str | tuple[str, ...] = ""
    message = "You do not have permission to perform this administrative operation."

    def has_permission(self, request, view) -> bool:
        required = getattr(
            view, "required_admin_permission", self.required_admin_permission
        )
        if isinstance(required, str):
            required = (required,)
        return any(has_admin_permission(request.user, code) for code in required)


def _permission_class(name: str, *codes: str):
    """Build small declarative DRF permission classes without broad role gates."""

    return type(name, (HasAdminPermission,), {"required_admin_permission": codes})


CanViewDashboard = _permission_class("CanViewDashboard", "view_dashboard")
CanViewUsers = _permission_class("CanViewUsers", "view_users")
CanViewRequests = _permission_class("CanViewRequests", "view_requests")
CanViewJourneys = _permission_class("CanViewJourneys", "view_journeys")
CanViewMatches = _permission_class("CanViewMatches", "view_matches")
CanViewDeals = _permission_class("CanViewDeals", "view_deals")
CanViewKyc = _permission_class("CanViewKyc", "view_kyc")
CanReviewKyc = _permission_class("CanReviewKyc", "review_kyc")
CanViewFlightProofs = _permission_class("CanViewFlightProofs", "view_flight_proofs")
CanReviewFlightProof = _permission_class("CanReviewFlightProof", "review_flight_proofs")
CanViewDisputes = _permission_class("CanViewDisputes", "view_disputes")
CanManageDisputes = _permission_class("CanManageDisputes", "manage_disputes")
CanResolveDisputes = _permission_class("CanResolveDisputes", "resolve_disputes")
CanRecordNoShow = _permission_class("CanRecordNoShow", "record_no_show")
CanViewPaymentOrders = _permission_class("CanViewPaymentOrders", "view_payment_orders")
CanViewPaymentAttempts = _permission_class(
    "CanViewPaymentAttempts", "view_payment_attempts"
)
CanViewProviderEvents = _permission_class(
    "CanViewProviderEvents", "view_provider_events"
)
CanViewRefunds = _permission_class(
    "CanViewRefunds", "issue_refunds", "settle_manual_refunds"
)
CanIssueRefunds = _permission_class("CanIssueRefunds", "issue_refunds")
CanSettleManualRefunds = _permission_class(
    "CanSettleManualRefunds", "settle_manual_refunds"
)
CanViewPayouts = _permission_class("CanViewPayouts", "view_payouts")
CanSettlePayouts = _permission_class("CanSettlePayouts", "settle_payouts")
CanViewScheduledJobs = _permission_class("CanViewScheduledJobs", "view_scheduled_jobs")
CanViewRatings = _permission_class("CanViewRatings", "view_ratings")
CanViewBoosts = _permission_class("CanViewBoosts", "view_boosts")
CanViewProviderHealth = _permission_class(
    "CanViewProviderHealth", "view_provider_health"
)
CanViewOperationalIncidents = _permission_class(
    "CanViewOperationalIncidents", "view_operational_incidents"
)
CanViewSettings = _permission_class("CanViewSettings", "view_settings")
CanManageSettings = _permission_class("CanManageSettings", "manage_settings")
CanManageAdmins = _permission_class("CanManageAdmins", "manage_admins")
CanManagePermissions = _permission_class("CanManagePermissions", "manage_permissions")
CanViewAuditLog = _permission_class("CanViewAuditLog", "view_audit_log")
