"""Safe URL and redirect helpers for the server-rendered Admin console.

Console actions return to named ShipTrip routes only.  Query values are copied
only when the caller names the key and supplies a validator (or an explicit
allowlist), and fragments are restricted to simple HTML identifiers.  This
keeps workflow continuity without turning ``next`` or an arbitrary query
string into an open-redirect or injection surface.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Mapping

from django.http import HttpResponseRedirect
from django.urls import reverse

QueryRule = Collection[str] | Callable[[str], bool]

_FRAGMENT_RE = re.compile(r"^[a-z][a-z0-9-]{0,79}$")
_QUERY_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


def bounded_query_text(value: str) -> bool:
    """Allow one short, printable filter value (encoding happens later)."""

    return 0 < len(value) <= 200 and value.isprintable()


def positive_page(value: str) -> bool:
    """Accept Django paginator page numbers, not signs or alternate syntax."""

    return (
        0 < len(value) <= 6
        and value.isascii()
        and value.isdigit()
        and 0 < int(value) <= 999_999
    )


def _rule_accepts(rule: QueryRule, value: str) -> bool:
    if callable(rule):
        return bool(rule(value))
    return value in rule


def admin_url(
    request,
    route_name: str,
    *,
    route_kwargs: Mapping[str, object] | None = None,
    fragment: str | None = None,
    preserve_query: Mapping[str, QueryRule] | None = None,
) -> str:
    """Build one internal Admin URL with explicitly validated page context."""

    url = reverse(route_name, kwargs=dict(route_kwargs or {}))
    query = request.GET.copy()
    query.clear()
    for key, rule in (preserve_query or {}).items():
        if not _QUERY_KEY_RE.fullmatch(key):
            raise ValueError("Unsafe Admin query key")
        value = request.GET.get(key, "")
        if value and bounded_query_text(value) and _rule_accepts(rule, value):
            query[key] = value
    encoded = query.urlencode()
    if encoded:
        url = f"{url}?{encoded}"
    if fragment:
        if not _FRAGMENT_RE.fullmatch(fragment):
            raise ValueError("Unsafe Admin fragment")
        url = f"{url}#{fragment}"
    return url


def admin_redirect(
    request,
    route_name: str,
    *,
    route_kwargs: Mapping[str, object] | None = None,
    fragment: str | None = None,
    preserve_query: Mapping[str, QueryRule] | None = None,
) -> HttpResponseRedirect:
    """Redirect to a named Admin route while retaining only safe context."""

    return HttpResponseRedirect(
        admin_url(
            request,
            route_name,
            route_kwargs=route_kwargs,
            fragment=fragment,
            preserve_query=preserve_query,
        )
    )
