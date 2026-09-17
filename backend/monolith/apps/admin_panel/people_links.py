"""Who may open a Person profile, and how every console page links to one.

J6.4 makes the Person profile the operational page for a user. Operators reach
people from Finance queues, Deals, disputes and verification, so the profile
cannot be gated on `view_users` alone: Finance and Ops hold no `view_users`,
and a name that 403s when clicked is worse than a name that is not a link.

The gate is therefore *any* capability that already shows this person's name
and email somewhere in the console. Nothing new is exposed by it — the header
of a profile is the name and email those queues already print — and every
section below the header is gated again on the capability that owns its data.

A link can carry a return context (`from`). It is a closed vocabulary resolved
server-side into named routes, never a URL taken from the request, so it cannot
become an open redirect or a way to render an arbitrary link.
"""

from __future__ import annotations

from urllib.parse import urlencode

from django.urls import reverse

from .permissions import has_admin_permission

#: Capabilities that already put a person's name in front of an operator.
PROFILE_CAPABILITIES: tuple[str, ...] = (
    "view_users",
    "view_kyc",
    "view_deals",
    "view_disputes",
    "view_payouts",
    "view_finance_summary",
    "review_payout_profiles",
    "attest_payout_identity",
    "view_payment_orders",
    "view_payment_attempts",
)


def may_open_people(user) -> bool:
    return any(has_admin_permission(user, code) for code in PROFILE_CAPABILITIES)


#: Where a profile was opened from, as breadcrumbs. Each entry is a label and a
#: route name; `None` as the route means "the current page's own crumb".
RETURN_CONTEXTS: dict[str, tuple[tuple[str, str], ...]] = {
    "users": (("People", "admin_console:users"),),
    "payout-reviews": (
        ("Finance", "admin_console:finance-dashboard"),
        ("Payout method reviews", "admin_console:payout-reviews"),
    ),
    "identity-checks": (
        ("Verification", "admin_console:kyc-queue"),
        ("Payout identity checks", "admin_console:identity-checks"),
    ),
    "deals": (("Marketplace", "admin_console:deals"), ("Deals", "admin_console:deals")),
    "disputes": (("Disputes", "admin_console:disputes"),),
    "kyc": (("Verification", "admin_console:kyc-queue"), ("KYC review", "admin_console:kyc-queue")),
    "payouts": (("Finance", "admin_console:finance-dashboard"), ("Payouts", "admin_console:payouts")),
}


def person_href(user_id, *, source: str = "", tab: str = "") -> str:
    """The profile URL for one user, optionally remembering where it came from."""

    url = reverse("admin_console:user-detail", args=(user_id,))
    query = {}
    if tab:
        query["tab"] = tab
    if source in RETURN_CONTEXTS:
        query["from"] = source
    return f"{url}?{urlencode(query)}" if query else url


def return_crumbs(source: str) -> list[dict]:
    """Breadcrumbs for a known return context; People for anything else."""

    trail = RETURN_CONTEXTS.get(source) or RETURN_CONTEXTS["users"]
    return [{"label": label, "url": reverse(route)} for label, route in trail]


def display_name(user) -> str:
    if user is None:
        return "System"
    return (getattr(user, "full_name", "") or "").strip() or user.email


def initials(user) -> str:
    name = (getattr(user, "full_name", "") or "").strip()
    if name:
        parts = [part for part in name.split() if part[:1].isalnum()]
        letters = "".join(part[0] for part in parts[:2])
        if letters:
            return letters.upper()
    return (getattr(user, "email", "") or "?")[:1].upper()
