"""Strict bounded reporting scope; calendar dates follow the H0 Paris contract."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import re
from uuid import UUID
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.utils import timezone

from .definitions import OPERATION_STAGES, REPORTING_TIMEZONE


@dataclass(frozen=True)
class Scope:
    mode: str
    start: datetime
    end: datetime
    provider: str = ""
    rail: str = ""
    state: str = ""
    held: str = ""
    search: str = ""
    currency: str = ""
    operation: str = ""

    @classmethod
    def parse(cls, values, *, now=None):
        from apps.finance.models import Payout

        allowed = {
            "mode",
            "period",
            "start",
            "end",
            "provider",
            "rail",
            "state",
            "held",
            "search",
            "currency",
            "metric",
            "page",
            "page_size",
            "operation",
        }
        if set(values) - allowed:
            raise ValidationError("Unknown finance filter.")
        if hasattr(values, "getlist") and any(
            len(values.getlist(key)) != 1 for key in values
        ):
            raise ValidationError("Repeated finance filters are not allowed.")
        mode = values.get("mode", "")
        if mode not in {"test", "live", "legacy_unknown"}:
            raise ValidationError(
                "An explicit test, live or legacy_unknown mode is required."
            )
        choices = {
            "provider": {"", "stripe", "chargily"},
            "rail": {"", "stripe_eur", "manual_dzd"},
            "state": {"", *Payout.Status.values},
            "held": {"", "true", "false", "disputed"},
            "currency": {"", "EUR", "DZD"},
            "operation": {"", *OPERATION_STAGES},
        }
        filters = {key: values.get(key, "") for key in choices}
        if any(filters[key] not in options for key, options in choices.items()):
            raise ValidationError("Invalid finance filter value.")
        search = values.get("search", "").strip()
        if search:
            try:
                search = str(UUID(search))
            except ValueError:
                if not re.fullmatch(r"(?:ST|TR)-[1-9][0-9]{0,14}", search):
                    raise ValidationError(
                        "Search requires an exact payout/order UUID, ST-Deal or TR-Traveler reference."
                    ) from None
        zone = ZoneInfo(REPORTING_TIMEZONE)
        today = (now or timezone.now()).astimezone(zone).date()
        period = values.get("period", "30d")
        if period == "custom":
            try:
                start, last = (
                    date.fromisoformat(values.get("start", "")),
                    date.fromisoformat(values.get("end", "")),
                )
            except ValueError:
                raise ValidationError("Custom dates must use YYYY-MM-DD.") from None
        elif period in {"today", "7d", "30d"} and not (
            values.get("start") or values.get("end")
        ):
            last = today
            start = today - timedelta(days={"today": 0, "7d": 6, "30d": 29}[period])
        else:
            raise ValidationError("Invalid reporting period.")
        if start > last or (last - start).days >= 366 or last > today:
            raise ValidationError(
                "Use an ordered date range of at most 366 days, ending no later than today."
            )
        return cls(
            mode,
            datetime.combine(start, time.min, zone),
            datetime.combine(last + timedelta(days=1), time.min, zone),
            search=search,
            **filters,
        )

    def period(self, queryset, field):
        return queryset.filter(
            **{f"{field}__gte": self.start, f"{field}__lt": self.end}
        )
