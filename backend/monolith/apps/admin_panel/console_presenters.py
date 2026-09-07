"""Safe, read-only presentation helpers for the operations console."""

from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from apps.core.admin_display import format_eur, tone_for
from apps.locations.models import Place


def place_label(place: Place | None, fallback: str = "") -> str:
    """A canonical, human-readable label with airport and country context."""

    if place is None:
        return fallback or "Location not catalogued"
    parts = [place.name]
    if place.iata_code:
        parts[0] = f"{place.name} ({place.iata_code})"
    if place.parent_id and place.parent and place.parent.name != place.name:
        parts.append(place.parent.name)
    if place.country_id:
        parts.append(place.country.name)
    return " · ".join(parts)


def request_route(delivery_request) -> str:
    return " → ".join(
        (
            place_label(
                getattr(delivery_request, "pickup_place", None),
                getattr(
                    getattr(delivery_request, "pickup_location", None),
                    "public_label",
                    "",
                )
                or getattr(delivery_request, "pickup_city", ""),
            ),
            place_label(
                getattr(delivery_request, "delivery_place", None),
                getattr(
                    getattr(delivery_request, "delivery_location", None),
                    "public_label",
                    "",
                )
                or getattr(delivery_request, "delivery_city", ""),
            ),
        )
    )


def journey_route(journey) -> str:
    legs = list(journey.legs.all())
    if not legs:
        return " → ".join(
            (
                place_label(
                    getattr(journey, "start_place", None),
                    getattr(
                        getattr(journey, "start_location", None), "public_label", ""
                    ),
                ),
                place_label(
                    getattr(journey, "destination_place", None),
                    getattr(
                        getattr(journey, "destination_location", None),
                        "public_label",
                        "",
                    ),
                ),
            )
        )
    nodes = [
        place_label(
            getattr(legs[0], "origin_place", None),
            getattr(getattr(legs[0], "origin", None), "public_label", ""),
        )
    ]
    nodes.extend(
        place_label(
            getattr(leg, "destination_place", None),
            getattr(getattr(leg, "destination", None), "public_label", ""),
        )
        for leg in legs
    )
    return " → ".join(nodes)


def place_node(place: Place | None, fallback: str = "") -> dict:
    """One stop on a route, split into the parts an operator reads separately.

    The name is what is scanned, the airport code is what is quoted, and the
    administrative context is the line that resolves an ambiguous name. Joining
    all three with separators — which is what the console used to print — makes
    a two-leg journey unreadable at a glance.
    """

    if place is None:
        return {
            "name": fallback or "Location not catalogued",
            "code": "",
            "context": "",
        }
    context = []
    if place.parent_id and place.parent and place.parent.name != place.name:
        context.append(place.parent.name)
    if place.country_id:
        context.append(place.country.name)
    return {
        "name": place.name,
        "code": place.iata_code or "",
        "context": " · ".join(context),
    }


def request_route_nodes(delivery_request) -> list[dict]:
    """Pickup and delivery as route nodes."""

    return [
        place_node(
            getattr(delivery_request, "pickup_place", None),
            getattr(
                getattr(delivery_request, "pickup_location", None), "public_label", ""
            )
            or getattr(delivery_request, "pickup_city", ""),
        ),
        place_node(
            getattr(delivery_request, "delivery_place", None),
            getattr(
                getattr(delivery_request, "delivery_location", None), "public_label", ""
            )
            or getattr(delivery_request, "delivery_city", ""),
        ),
    ]


def journey_route_nodes(journey) -> list[dict]:
    """Ordered stops, each carrying the leg that arrives at it.

    ``mode`` on a node is the mode of the leg *into* that node, which is what
    lets the route render as ``CDG --flight--> ALG --drive--> Jijel`` rather
    than as an undifferentiated arrow chain.
    """

    legs = list(journey.legs.all())
    if not legs:
        return [
            place_node(
                getattr(journey, "start_place", None),
                getattr(getattr(journey, "start_location", None), "public_label", ""),
            ),
            place_node(
                getattr(journey, "destination_place", None),
                getattr(
                    getattr(journey, "destination_location", None), "public_label", ""
                ),
            ),
        ]
    nodes = [
        place_node(
            getattr(legs[0], "origin_place", None),
            getattr(getattr(legs[0], "origin", None), "public_label", ""),
        )
    ]
    for leg in legs:
        node = place_node(
            getattr(leg, "destination_place", None),
            getattr(getattr(leg, "destination", None), "public_label", ""),
        )
        node["mode"] = leg.mode
        node["mode_label"] = leg.get_mode_display()
        node["flight_number"] = leg.flight_number or ""
        nodes.append(node)
    return nodes


def route_cell(nodes: list[dict]) -> dict:
    """A route rendered inside a table cell rather than flattened to a string."""

    return {"primary": "", "kind": "route", "nodes": nodes, "secondary": "", "href": ""}


def parcel_summary(delivery_request) -> str:
    title = delivery_request.title or delivery_request.get_category_display()
    weight = delivery_request.actual_weight_kg or delivery_request.weight_kg
    return f"{title} · {weight} kg" if weight is not None else title


def status_cell(value: str, label: str | None = None) -> dict:
    return {
        "primary": label or str(value or "—").replace("_", " ").title(),
        "kind": "status",
        "tone": tone_for(value),
    }


def text_cell(
    primary,
    secondary: str = "",
    *,
    href: str = "",
    kind: str = "",
    opens_row: bool = False,
    aria_label: str = "",
) -> dict:
    """One cell.

    ``opens_row`` marks this cell's link as the record the whole row stands
    for. It is the only declaration a list has to make to become clickable
    everywhere rather than on one word: the anchor stays exactly where it was
    and keeps doing the navigating, and the row around it becomes a surface
    that activates it. A row may declare at most one — a second one would make
    "click the row" ambiguous, and ``_table`` refuses it.
    """

    return {
        "primary": "—" if primary in (None, "") else str(primary),
        "secondary": secondary,
        "href": href,
        "kind": kind,
        "is_primary": bool(opens_row and href),
        # A visible "Review" is enough for an eye that has the row in front of
        # it and useless to a screen reader reading links out of context, so a
        # generic label names its record instead. The accessible name still
        # begins with the visible word, which is what label-in-name asks for.
        "aria_label": aria_label,
    }


def open_cell(label: str, *, href: str, aria_label: str = "") -> dict:
    """The row's own record, as a control rather than as a column of data.

    Some queues have no natural identity column to hang the link on — a payment
    is identified by its provider, its order and its amount together, none of
    which is "the payment". Those used to carry a trailing ``Action`` column
    holding the word *Review*, which is a control wearing a column's clothes:
    it costs real width in an already wide table, and once the table has to
    scroll it is the first thing to leave the screen.

    This is the same link with the column removed. ``_table`` lifts it out of
    the row's cells and into the pinned open affordance at the row's edge, so
    the target is always visible and there is one of it rather than two.
    """

    return {
        "primary": label,
        "kind": "open",
        "href": href,
        "secondary": "",
        "aria_label": aria_label or label,
        "is_primary": bool(href),
    }


def money_cell(cents: int | None, *, emphasis: bool = False) -> dict:
    return text_cell(format_eur(cents), kind="money-lead" if emphasis else "money")


def datetime_cell(value, *, relative: bool = False) -> dict:
    """A timestamp, optionally with the age an operator actually triages on."""

    if value is None:
        return text_cell("—")
    stamp = timezone.localtime(value).strftime("%d %b %Y, %H:%M")
    # `time` keeps the stamp on one line with tabular figures. A timestamp that
    # wraps to "04 Sep 2026," / "12:22" costs a second look on every row, and a
    # column of times that do not line up cannot be scanned for the odd one.
    return text_cell(
        stamp, f"{age_label(value)} ago" if relative else "", kind="time"
    )


def ref_cell(
    value, secondary: str = "", *, href: str = "", opens_row: bool = False
) -> dict:
    """An identifier that is quoted rather than read, set in the mono face."""

    return text_cell(
        value or "—", secondary, href=href, kind="ref", opens_row=opens_row
    )


def money_pair_cell(canonical_cents: int | None, provider_text: str = "") -> dict:
    """The canonical EUR obligation, with what a provider actually moved under it.

    EUR is the business currency and stays the larger of the two lines; the
    provider settlement is never allowed to read as the authority.
    """

    return {
        "primary": format_eur(canonical_cents),
        "secondary": provider_text or "",
        "kind": "money-pair",
        "href": "",
    }


def format_minor_amount(amount: int | None, exponent: int | None, currency: str) -> str:
    if amount is None:
        return "—"
    exponent = int(exponent or 0)
    sign = "-" if amount < 0 else ""
    absolute = abs(int(amount))
    if exponent <= 0:
        number = f"{absolute:,}"
    else:
        scale = 10**exponent
        whole, fraction = divmod(absolute, scale)
        number = f"{whole:,}.{fraction:0{exponent}d}"
    return f"{sign}{number} {currency or '—'}"


def percent_from_bps(value: int) -> Decimal:
    return Decimal(value) / Decimal(100)


def decimal_eur(cents: int) -> Decimal:
    return Decimal(cents) / Decimal(100)


def decimal_micros(value: int) -> Decimal:
    return Decimal(value) / Decimal(1_000_000)


def age_label(value) -> str:
    if value is None:
        return "—"
    seconds = max(0, int((timezone.now() - value).total_seconds()))
    if seconds < 3_600:
        return f"{max(1, seconds // 60)} min"
    if seconds < 86_400:
        return f"{seconds // 3_600} hr"
    return f"{seconds // 86_400} days"
