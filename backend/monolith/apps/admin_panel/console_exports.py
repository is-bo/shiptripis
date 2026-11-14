"""The Finance exports page (``finance/exports/``, spec 19.2, L14).

Pick a kind, a money mode and a date range; the answer is a streamed CSV. The
page reads finance rows and writes exactly one thing: the audit row naming the
kind, the range and the line count, written before the first byte is sent, so
no export leaves without its record.
"""

from __future__ import annotations

from django import forms
from django.http import StreamingHttpResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache

from . import exports
from .console_forms import ConsoleForm
from .console_views import _render, capability_required
from .models import AdminAuditLog
from .services import record_admin_action

EXPORT_PERMISSION = "export_finance"
AUDIT_ACTION = "finance.export_downloaded"

KIND_CHOICES = (
    (
        exports.TRANSACTIONS,
        "Transactions: one line per captured payment and one per refund",
    ),
    (
        exports.COMMISSIONS,
        "Commissions: one line per funded delivery, with the fee kept",
    ),
    (exports.PAYOUTS, "Payouts: one line per traveler payout"),
)
MODE_CHOICES = (
    ("live", "Live money"),
    ("test", "Test money"),
    ("legacy_unknown", "Unknown mode (older records)"),
)


class FinanceExportForm(ConsoleForm):
    kind = forms.ChoiceField(
        choices=KIND_CHOICES, widget=forms.RadioSelect, label="What to export"
    )
    mode = forms.ChoiceField(
        choices=MODE_CHOICES,
        initial="live",
        label="Money",
        help_text="The same split the Finance overview uses. Live and test money never share a file.",
    )
    start = forms.DateField(
        label="From", widget=forms.DateInput(attrs={"type": "date"})
    )
    end = forms.DateField(label="To", widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start"), cleaned.get("end")
        if start and end:
            try:
                exports.validate_range(start, end, today=timezone.now().date())
            except exports.ExportRangeError as exc:
                raise forms.ValidationError(str(exc)) from None
        return cleaned


def _recent_exports():
    rows = list(
        AdminAuditLog.objects.filter(action=AUDIT_ACTION)
        .select_related("actor")
        .order_by("-created_at")[:10]
    )
    labels = dict(MODE_CHOICES)
    for row in rows:
        row.mode_label = labels.get((row.after or {}).get("mode"), "")
    return rows


@never_cache
@capability_required(EXPORT_PERMISSION)
def finance_exports(request):
    today = timezone.now().date()
    form = FinanceExportForm(
        request.POST or None,
        initial={"start": today.replace(day=1), "end": today, "mode": "live"},
    )
    for name in ("start", "end"):
        form.fields[name].widget.attrs["max"] = today.isoformat()
    if request.method == "POST" and form.is_valid():
        spec = exports.ExportRequest(
            kind=form.cleaned_data["kind"],
            mode=form.cleaned_data["mode"],
            start=form.cleaned_data["start"],
            end=form.cleaned_data["end"],
            as_of=timezone.now(),
        )
        count = exports.line_count(spec)
        record_admin_action(
            actor=request.user,
            action=AUDIT_ACTION,
            target_type="finance.export",
            target_id=spec.kind,
            after={
                "kind": spec.kind,
                "mode": spec.mode,
                "from": spec.start.isoformat(),
                "to": spec.end.isoformat(),
                "lines": count,
            },
            metadata={"as_of": spec.as_of.isoformat()},
        )
        response = StreamingHttpResponse(
            exports.csv_chunks(spec), content_type="text/csv; charset=utf-8"
        )
        response["Content-Disposition"] = f'attachment; filename="{spec.filename}"'
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
    return _render(
        request,
        "admin/console/finance_exports.html",
        {
            "title": "Finance exports",
            "form": form,
            "max_days": exports.MAX_RANGE_DAYS,
            "recent": _recent_exports(),
            "columns": [
                (kind.capitalize(), exports.COLUMNS[kind]) for kind in exports.KINDS
            ],
        },
        status=400 if form.errors else 200,
    )
