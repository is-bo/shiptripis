"""Backward-compatible pagination for legacy bare-array API collections."""

from __future__ import annotations

from django.core.paginator import EmptyPage, Paginator
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response


def paginated_array_response(
    request,
    queryset,
    *,
    serialize,
    default_page_size: int = 100,
    max_page_size: int = 100,
) -> Response:
    """Page a queryset while preserving its historic JSON array body.

    New clients can use ``page`` plus the additive response headers. Existing
    clients still receive the same first 100 rows, avoiding an array-to-envelope
    contract break while making later rows reachable.
    """

    params = request.query_params
    for name in ("page", "page_size"):
        if len(params.getlist(name)) > 1:
            raise ValidationError({name: f"{name} must be supplied once."})
    try:
        page_number = int(params.get("page", "1"))
        page_size = int(params.get("page_size", str(default_page_size)))
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            {"detail": "page and page_size must be integers."}
        ) from exc
    if page_number < 1:
        raise ValidationError({"page": "page must be at least 1."})
    if not 1 <= page_size <= max_page_size:
        raise ValidationError(
            {"page_size": f"page_size must be between 1 and {max_page_size}."}
        )

    paginator = Paginator(queryset, page_size)
    try:
        page = paginator.page(page_number)
    except EmptyPage as exc:
        raise NotFound("Invalid page.") from exc

    response = Response(serialize(page.object_list))
    response["X-Total-Count"] = str(paginator.count)
    response["X-Page"] = str(page.number)
    response["X-Page-Size"] = str(page_size)
    if page.has_next():
        response["X-Next-Page"] = str(page.next_page_number())
    if page.has_previous():
        response["X-Previous-Page"] = str(page.previous_page_number())
    return response
