"""Minimal Finance/Super-only JSON consumer surface for H5.1."""

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import OperationalError
from django.http import Http404, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from apps.finance.control_plane.drilldown import drilldown
from apps.finance.control_plane.filters import Scope
from apps.finance.control_plane.snapshot import build_snapshot
from .permissions import has_all_admin_permissions


@never_cache
@staff_member_required
@require_GET
def finance_control_plane(request):
    if not has_all_admin_permissions(request.user, "view_finance_summary"):
        raise PermissionDenied("Finance summary access is required.")
    if not settings.FINANCE_DASHBOARD_ENABLED:
        raise Http404
    try:
        scope = Scope.parse(request.GET)
        metric = request.GET.get("metric")
        result = (
            drilldown(
                scope,
                metric=metric,
                page=request.GET.get("page", 1),
                page_size=request.GET.get("page_size", 50),
            )
            if metric
            else build_snapshot(scope)
        )
    except ValidationError as exc:
        return JsonResponse(
            {"code": "invalid_finance_query", "errors": exc.messages}, status=400
        )
    except OperationalError:
        return JsonResponse(
            {"code": "finance_snapshot_temporarily_unavailable"}, status=503
        )
    return JsonResponse(result)
