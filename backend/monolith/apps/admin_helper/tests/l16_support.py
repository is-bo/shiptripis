"""Shared pieces of the L16 tests: posting an action, confirming it, and the
whole-database effect of one step, so a helper-confirmed change can be
compared row for row with the console doing the same thing."""

from __future__ import annotations

import json
import re
from decimal import Decimal

from django.apps import apps
from django.db import models, transaction
from django.test import Client
from django.urls import reverse

from apps.admin_helper.models import AdminHelperCall, PreparedAction
from apps.admin_panel.models import AdminAuditLog
from apps.locations.models import Country, Place, SeaCrossing

API = "/api/admin/helper/v1/"
REASON = "The sender showed the carrier's damage report; staff agreed this on the call."


def post_action(plain: str, action: str, target_type: str, target_id: int, params=None,
                reason: str = REASON, client: Client | None = None):
    body = {"action": action, "target": {"type": target_type, "id": target_id}, "params": params or {}}
    if reason is not None:
        body["reason"] = reason
    return (client or Client()).post(
        API + "actions",
        data=json.dumps(body),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {plain}",
    )


def change_url(prepared) -> str:
    return reverse("admin_console:ai-helper-change", args=(prepared.pk,))


def confirm(client: Client, prepared, reason: str = REASON):
    return client.post(change_url(prepared), {"decision": "confirm", "reason": reason})


def reject(client: Client, prepared):
    return client.post(change_url(prepared), {"decision": "reject"})


def sea_crossing(*, active: bool) -> SeaCrossing:
    places = []
    for code, name in (("FR", "Marseille"), ("DZ", "Algiers")):
        country = Country.objects.filter(code=code).first() or Country.objects.create(
            code=code, name=name, source="l16-test", source_id=f"country-{code}", source_version="l16"
        )
        places.append(
            Place.objects.create(
                country=country,
                place_type=Place.PlaceType.LOCALITY,
                source="l16-test",
                source_id=f"l16-{code}-{name}",
                source_version="l16",
                name=name,
            )
        )
    return SeaCrossing.objects.create(
        origin_locality=places[0],
        destination_locality=places[1],
        distance_meters=770_000,
        is_active=active,
    )


# --- the effect of one step on the whole database ----------------------------------------

#: Written by a helper call or a console page view, not by the action itself.
_NOT_THE_ACTION = {AdminHelperCall, PreparedAction}
_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


def _models():
    return [
        model
        for model in apps.get_models()
        if model._meta.managed and not model._meta.proxy and model not in _NOT_THE_ACTION
        and model._meta.db_table != "django_session"
    ]


def _int_pk(model) -> bool:
    return isinstance(model._meta.pk, (models.AutoField, models.BigAutoField))


def _baseline() -> dict:
    tops = {}
    for model in _models():
        manager = model._base_manager
        if _int_pk(model):
            totals = manager.aggregate(n=models.Count("pk"), top=models.Max("pk"))
            tops[model] = {"n": totals["n"], "top": totals["top"] or 0}
        else:
            tops[model] = {"n": manager.count(), "top": None}
    return tops


def _plain(value):
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, str) and _TIME.match(value):
        return "<time>"
    if isinstance(value, Decimal):
        return str(value)
    return value


_DIGITS = re.compile(r"\d+")
_UUID = re.compile(r"[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}")


def _ids_masked(value):
    """A new row's text and JSON with its ids masked: they name other new rows
    (``refund_reconcile:<refund id>``, an event's uuid), whose ids differ
    between the two runs."""

    if isinstance(value, str):
        return _DIGITS.sub("#", _UUID.sub("<uuid>", value))
    if isinstance(value, dict):
        return {key: _ids_masked(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_ids_masked(item) for item in value]
    if isinstance(value, int) and not isinstance(value, bool):
        return "#"
    return value


def _row(obj, tops) -> dict:
    top = tops.get(type(obj), {}).get("top")
    new = top is not None and isinstance(obj.pk, int) and obj.pk > top
    data = {}
    for model_field in obj._meta.concrete_fields:
        value = getattr(obj, model_field.attname)
        if model_field.primary_key:
            continue
        if new and isinstance(model_field, (models.CharField, models.TextField, models.JSONField)):
            data[model_field.name] = _ids_masked(_plain(value))
            continue
        if isinstance(model_field, (models.DateTimeField, models.DateField)):
            value = value is not None
        elif isinstance(model_field, models.UUIDField):
            value = value is not None
        elif model_field.is_relation and value is not None:
            related = model_field.related_model
            top = tops.get(related, {}).get("top")
            value = "new" if top is not None and isinstance(value, int) and value > top else value
        data[model_field.name] = _plain(value)
    return data


#: Rows compared in full, ordered by primary key, besides the counts.
WATCHED = (
    "deals.Deal",
    "disputes.Dispute",
    "problems.ShipmentProblem",
    "finance.PaymentRefund",
    "finance.Payout",
    "finance.ScheduledJob",
    "trips.Journey",
    "accounts.User",
    "discovery.PublicProfile",
    "locations.SeaCrossing",
    "ratings.RatingModeration",
    "ratings.RatingReport",
    "admin_panel.AdminNote",
)


def _audit(row: AdminAuditLog, tops) -> dict:
    target = None
    if row.target_type:
        try:
            model = apps.get_model(row.target_type)
        except (LookupError, ValueError):
            model = None
        top = tops.get(model, {}).get("top") if model else None
        target = "new" if top is not None and row.target_id.isdigit() and int(row.target_id) > top else row.target_id
    return {
        "action": row.action,
        "actor": row.actor_id,
        "target_type": row.target_type,
        "target_id": target,
        "before": _plain(row.before),
        "after": _plain(row.after),
        "reason": row.reason,
        "reference": row.reference,
    }


def effect(do) -> dict:
    """What ``do()`` writes: the change in each table's row count, every audit
    row it adds (without its metadata, compared on its own), and the watched
    tables row by row. Rolled back afterwards, so two ways of doing the same
    thing can be compared from the same starting point."""

    tops = _baseline()
    audit_before = set(AdminAuditLog.objects.values_list("pk", flat=True))
    sid = transaction.savepoint()
    try:
        do()
        after = _baseline()
        counts = {
            model._meta.label: after[model]["n"] - tops[model]["n"]
            for model in after
            if after[model]["n"] != tops[model]["n"]
        }
        audits = sorted(
            AdminAuditLog.objects.exclude(pk__in=audit_before),
            key=lambda row: (row.created_at, row.action),
        )
        result = {
            "counts": counts,
            "audit": [_audit(row, tops) for row in audits],
            "metadata": [row.metadata for row in audits],
            "rows": {
                label: [_row(obj, tops) for obj in apps.get_model(label)._base_manager.order_by("pk")]
                for label in WATCHED
            },
        }
    finally:
        transaction.savepoint_rollback(sid)
    return result
