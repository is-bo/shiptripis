"""K7 data-scale probes: admin search, Find Travelers and inbox cost vs volume.

Run against a seeded load database (README "Seed"), never a shared one: every
subcommand inflates tables with synthetic rows and nothing is cleaned up.

    python backend/loadtest/data_scale_probe.py search --sizes 10000 100000 1000000
    python backend/loadtest/data_scale_probe.py matching --sizes 100 1000 10000
    python backend/loadtest/data_scale_probe.py inbox --sizes 1000000 5000000

Each step grows the tables to the target row count, runs ``VACUUM ANALYZE``,
then requests the real endpoint in-process through Django's test client (the
production view, serializer and SQL) and runs ``EXPLAIN (ANALYZE, BUFFERS)`` on
every SELECT it captured. Reported per surface: request wall time (median of
warm runs), query count, the slowest statement's server execution time, and
whether that statement sequentially scans the searched table.

Findings: ``docs/k7-notes/data-scale.md``.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manage_loadtest  # noqa: E402

manage_loadtest.bootstrap()

import django  # noqa: E402

django.setup()

from django.db import connection  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402
from django.utils import timezone  # noqa: E402

WORLD = Path(__file__).resolve().parent / ".data" / "world.json"
HOST = "127.0.0.1"
MISS = "zqxj-no-such-text"

FIRST = (
    "Amine", "Yacine", "Sofiane", "Karim", "Nadia", "Samira", "Lina", "Ines",
    "Mehdi", "Rayan", "Sarah", "Yasmine", "Walid", "Nabil", "Leila", "Hana",
    "Omar", "Imane", "Farid", "Meriem",
)
LAST = (
    "Benali", "Haddad", "Mansouri", "Bouzid", "Saidi", "Brahimi", "Rahmani",
    "Belkacem", "Cherif", "Djebbar", "Ferhat", "Ghazi", "Hamidi", "Kaci",
    "Lounis", "Meziane", "Nait", "Ouali", "Rezig", "Slimani", "Taleb", "Yahi",
    "Zerrouki", "Amrani", "Bensaid",
)
DOMAINS = ("gmail.com", "yahoo.fr", "hotmail.com", "outlook.fr", "orange.fr")


def _sql_array(values) -> str:
    return "ARRAY[" + ",".join("'" + v.replace("'", "''") + "'" for v in values) + "]"


def _count(table: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT count(*) FROM "{table}"')
        return cursor.fetchone()[0]


def _columns(table: str) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = %s ORDER BY ordinal_position",
            [table],
        )
        return [row[0] for row in cursor.fetchall()]


def _clone(table: str, template_id, n: int, overrides: dict[str, str], *, source="", start=0):
    """Insert ``n`` copies of one template row, overriding unique/varied columns.

    ``g`` is the 1-based copy number (offset by ``start``); ``source`` may add a
    FROM item (aliased ``u``) whose ``g`` column replaces the series.
    """

    columns = [c for c in _columns(table) if c != "id" or "id" in overrides]
    exprs = [overrides.get(c, f't."{c}"') for c in columns]
    series = source or f"(SELECT generate_series({start + 1}, {start + n}) AS g) u"
    sql = (
        f'INSERT INTO "{table}" ({", ".join(chr(34) + c + chr(34) for c in columns)}) '
        f"SELECT {', '.join(exprs)} FROM {series}, "
        f"(SELECT * FROM \"{table}\" WHERE id = '{template_id}') t"
    )
    # No bind parameters: the expressions use the SQL `%` operator.
    with connection.cursor() as cursor:
        cursor.execute(sql)


def _analyze(*tables: str) -> None:
    with connection.cursor() as cursor:
        for table in tables:
            cursor.execute(f'VACUUM ANALYZE "{table}"')


def _grow_users(target: int) -> None:
    have = _count("accounts_user")
    if have >= target:
        return
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM accounts_user WHERE email LIKE 'sender%%' ORDER BY id LIMIT 1"
        )
        template = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM accounts_user WHERE username LIKE 'k7b-%%'")
        start = cursor.fetchone()[0]
    first = f"({_sql_array(FIRST)})[1 + g % {len(FIRST)}]"
    last = f"({_sql_array(LAST)})[1 + (g / {len(FIRST)}) % {len(LAST)}]"
    domain = f"({_sql_array(DOMAINS)})[1 + g % {len(DOMAINS)}]"
    email = f"lower({first}) || '.' || lower({last}) || g || '@' || {domain}"
    _clone(
        "accounts_user",
        template,
        target - have,
        {
            "username": "'k7b-' || g",
            "email": email,
            "full_name": f"{first} || ' ' || {last}",
            "phone": "'+2135' || lpad(g::text, 8, '0')",
            "date_joined": "now() - (g % 900) * interval '1 day' - (g % 86400) * interval '1 second'",
        },
        start=start,
    )


def _grow_kyc(target: int) -> None:
    have = _count("kyc_submission")
    if have >= target:
        return
    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM kyc_submission ORDER BY id LIMIT 1")
        template = cursor.fetchone()[0]
    source = (
        "(SELECT a.id AS uid, row_number() OVER (ORDER BY a.id) AS g FROM accounts_user a "
        "WHERE a.username LIKE 'k7b-%' AND NOT EXISTS "
        "(SELECT 1 FROM kyc_submission k WHERE k.user_id = a.id) "
        f"ORDER BY a.id LIMIT {target - have}) u"
    )
    _clone(
        "kyc_submission",
        template,
        target - have,
        {
            "user_id": "u.uid",
            "idempotency_key": "'k7b-kyc-' || u.uid",
            "status": "(ARRAY['approved','approved','pending','rejected'])[1 + u.g % 4]",
            "created_at": "now() - (u.g % 900) * interval '1 day'",
        },
        source=source,
    )


JOB_KINDS = (
    "notification_dispatch:notification", "protection_expiry:protection_expiry",
    "delivery_code_release:delivery_code_release", "outbound_message:outbound",
    "payout_release_check:payout_release_check", "attempt_expiry:attempt_expiry",
)


def _grow_jobs(target: int) -> None:
    have = _count("finance_scheduled_job")
    if have >= target:
        return
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM finance_scheduled_job WHERE status = 'succeeded' ORDER BY id LIMIT 1"
        )
        row = cursor.fetchone()
        if row is None:
            cursor.execute("SELECT id FROM finance_scheduled_job ORDER BY id LIMIT 1")
            row = cursor.fetchone()
        template = row[0]
    kinds = f"({_sql_array(k.split(':')[0] for k in JOB_KINDS)})[1 + g % {len(JOB_KINDS)}]"
    prefixes = f"({_sql_array(k.split(':')[1] for k in JOB_KINDS)})[1 + g % {len(JOB_KINDS)}]"
    _clone(
        "finance_scheduled_job",
        template,
        target - have,
        {
            "key": f"{prefixes} || ':' || md5(g::text) || ':' || g",
            "kind": kinds,
            "status": "'succeeded'",
            "run_at": "now() - g * interval '2 second'",
            "completed_at": "now() - g * interval '2 second'",
            "last_result": "'ok'",
            "created_at": "now() - g * interval '2 second'",
        },
        start=have,
    )


AUDIT_ACTIONS = (
    "kyc.approved", "kyc.rejected", "kyc.evidence_viewed", "flight_proof.approved",
    "dispute.resolved", "payout.manual_settled", "user.restricted", "job.resolved",
)
AUDIT_REASONS = (
    "Documents match the account holder", "Blurry selfie, asked to resubmit",
    "Reviewed evidence", "Operator follow-up", "Duplicate account",
)


def _grow_audit(target: int, admin_id: int) -> None:
    from apps.admin_panel.models import AdminAuditLog

    if not AdminAuditLog.objects.exists():
        AdminAuditLog.objects.create(
            actor_id=admin_id, action="kyc.approved", target_type="kyc_submission",
            target_id="1", reason="template",
        )
    have = _count("admin_panel_audit_log")
    if have >= target:
        return
    template = str(AdminAuditLog.objects.order_by("created_at").first().pk)
    actions = f"({_sql_array(AUDIT_ACTIONS)})[1 + g % {len(AUDIT_ACTIONS)}]"
    reasons = f"({_sql_array(AUDIT_REASONS)})[1 + g % {len(AUDIT_REASONS)}]"
    _clone(
        "admin_panel_audit_log",
        template,
        target - have,
        {
            "id": "gen_random_uuid()",
            "action": actions,
            "target_type": "split_part(" + actions + ", '.', 1)",
            "target_id": "(g % 50000)::text",
            "reason": reasons,
            "created_at": "now() - g * interval '30 second'",
        },
        start=have,
    )


OUTBOUND_KINDS = (
    "payment_succeeded", "pickup_confirmed", "delivery_confirmed", "protection_ended",
    "payout_status", "kyc_status", "email_verification", "password_reset",
)


def _grow_outbound(target: int) -> None:
    from apps.notifications.models import OutboundMessage

    if not OutboundMessage.objects.exists():
        OutboundMessage.objects.create(
            key="k7b-template", kind="payment_succeeded", to_email="t@example.invalid",
            status="dispatched", dispatched_at=timezone.now(),
        )
    have = _count("notification_outbound_message")
    if have >= target:
        return
    template = OutboundMessage.objects.order_by("pk").first().pk
    kinds = f"({_sql_array(OUTBOUND_KINDS)})[1 + g % {len(OUTBOUND_KINDS)}]"
    domain = f"({_sql_array(DOMAINS)})[1 + g % {len(DOMAINS)}]"
    _clone(
        "notification_outbound_message",
        template,
        target - have,
        {
            "key": f"{kinds} || ':' || g",
            "kind": kinds,
            "to_email": "'user' || (g % 90000) || '@' || " + domain,
            "status": "'dispatched'",
            "dispatched_at": "now() - g * interval '5 second'",
            "created_at": "now() - g * interval '5 second'",
        },
        start=have,
    )


def _grow_notifications(target: int) -> None:
    have = _count("notification")
    if have >= target:
        return
    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM notification ORDER BY id LIMIT 1")
        template = cursor.fetchone()[0]
        cursor.execute(
            "SELECT array_agg(id ORDER BY id) FROM accounts_user "
            "WHERE email LIKE 'sender%%' OR email LIKE 'traveler%%'"
        )
        users = cursor.fetchone()[0]
    pool = "ARRAY[" + ",".join(str(u) for u in users) + "]"
    _clone(
        "notification",
        template,
        target - have,
        {
            "recipient_id": f"({pool})[1 + g % {len(users)}]",
            "event_id": "'k7b-' || g",
            "channel": "(ARRAY['deal.updated','chat.message.new','offer.accepted','payment.captured'])[1 + g % 4]",
            "created_at": "now() - (g % 180) * interval '1 day' - (g % 86400) * interval '1 second'",
            "read_at": "CASE WHEN g % 10 = 0 THEN NULL ELSE now() END",
        },
        start=have,
    )


def _explain(sql: str) -> tuple[float, list[str]]:
    with connection.cursor() as cursor:
        cursor.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql)
        plan = cursor.fetchone()[0]
    if isinstance(plan, str):
        plan = json.loads(plan)
    root = plan[0]
    seq = []

    def walk(node):
        if node.get("Node Type") == "Seq Scan":
            seq.append(node.get("Relation Name", "?"))
        for child in node.get("Plans", ()):
            walk(child)

    walk(root["Plan"])
    return root["Execution Time"], seq


def _measure(client: Client, url: str, *, runs: int = 3, headers=None, explain=True) -> dict:
    headers = headers or {}
    client.get(url, HTTP_HOST=HOST, **headers)  # warm
    times = []
    for _ in range(runs):
        with CaptureQueriesContext(connection) as ctx:
            started = time.perf_counter()
            response = client.get(url, HTTP_HOST=HOST, **headers)
            times.append((time.perf_counter() - started) * 1000)
    result = {
        "url": url,
        "status": response.status_code,
        "wall_ms": round(statistics.median(times), 1),
        "queries": len(ctx.captured_queries),
    }
    if explain:
        worst = (0.0, [], "")
        for query in ctx.captured_queries:
            sql = query["sql"]
            if not sql.lstrip().upper().startswith("SELECT"):
                continue
            exec_ms, seq = _explain(sql)
            if exec_ms > worst[0]:
                worst = (exec_ms, seq, sql)
        result["slowest_sql_ms"] = round(worst[0], 1)
        result["slowest_seq_scans"] = sorted(set(worst[1]))
    return result


def _world() -> dict:
    return json.loads(WORLD.read_text(encoding="utf-8"))


def cmd_search(args) -> None:
    world = _world()
    admin = world["admins"][0]
    # The seeded session already passed the second step (seed `_admin_session`);
    # since L14 the staff API answers only inside such a session, so the API
    # read goes through the same console client.
    console = Client()
    console.cookies["sessionid"] = admin["sessionid"]
    # A realistic hit and a miss (the miss is the worst case: nothing stops the
    # scan early, and the paginator's COUNT scans everything either way).
    terms = {"hit": "benali", "miss": MISS}
    report = []
    for size in args.sizes:
        started = time.perf_counter()
        _grow_users(size)
        _grow_kyc(max(1, size // 4))
        _grow_jobs(size)
        _grow_audit(size // 10, admin["id"])
        _grow_outbound(size)
        _analyze(
            "accounts_user", "kyc_submission", "finance_scheduled_job",
            "admin_panel_audit_log", "notification_outbound_message",
        )
        sizes = {
            t: _count(t)
            for t in (
                "accounts_user", "kyc_submission", "finance_scheduled_job",
                "admin_panel_audit_log", "notification_outbound_message",
            )
        }
        print(f"== step {size}: {sizes} (grow {time.perf_counter() - started:.0f}s)", flush=True)
        for label, term in terms.items():
            surfaces = [
                (console, f"/admin/users/?q={term}", {}),
                (console, f"/api/admin/users?q={term}", {}),
                (console, f"/admin/verification/kyc/?q={term}", {}),
                (console, f"/admin/system/jobs/?q={term}", {}),
                (console, f"/admin/system/email/?q={term}", {}),
                (console, f"/admin/audit/?q={term}", {}),
            ]
            for client, url, headers in surfaces:
                row = {"step": size, "term": label, **_measure(client, url, headers=headers)}
                print(json.dumps(row), flush=True)
                report.append({"sizes": sizes, **row})
    _write(args, report)


def _make_journeys(request, count: int, exact_share: float, admins) -> None:
    import seed
    from apps.accounts.models import User
    from apps.locations.models import AirportLocalityMapping

    fr = seed._airport_localities(seed.FR_AIRPORTS)
    dz = seed._airport_localities(seed.DZ_AIRPORTS)
    destinations = seed._destinations()
    travelers = list(User.objects.filter(email__startswith="traveler").order_by("pk"))
    pickup_airport = (
        AirportLocalityMapping.objects.filter(
            locality_id=request.pickup_place_id, is_primary=True, active=True
        )
        .select_related("airport")
        .first()
    )
    now = timezone.now()
    window = (request.ready_window_end - request.ready_window_start).total_seconds()
    for index in range(count):
        exact = random.random() < exact_share
        if exact and pickup_airport is not None:
            origin = pickup_airport.airport
            destination = request.delivery_place
        else:
            origin = random.choice([pair[0] for pair in fr.values()])
            destination = random.choice(destinations)
        arrival, arrival_locality = random.choice(list(dz.values()))
        if arrival_locality.pk == destination.pk:
            arrival, arrival_locality = next(
                pair for pair in dz.values() if pair[1].pk != destination.pk
            )
        depart = request.ready_window_start + timedelta(seconds=random.uniform(0, window))
        seed._journey(
            travelers[index % len(travelers)],
            origin=origin,
            arrival=arrival,
            arrival_locality=arrival_locality,
            destination=destination,
            depart=depart,
            now=now,
            reviewer=admins,
        )


def _make_requests(journey, count: int, exact_share: float) -> None:
    import seed
    from apps.accounts.models import User

    fr = seed._airport_localities(seed.FR_AIRPORTS)
    destinations = seed._destinations()
    senders = list(User.objects.filter(email__startswith="sender").order_by("pk"))
    legs = list(journey.legs.order_by("position"))
    pickup_locality = next(
        (pair[1] for pair in fr.values() if pair[0].pk == legs[0].origin_place_id), None
    )
    for index in range(count):
        exact = random.random() < exact_share
        if exact and pickup_locality is not None:
            pickup, delivery = pickup_locality, journey.destination_place
        else:
            pickup = random.choice([pair[1] for pair in fr.values()])
            delivery = random.choice(destinations)
        seed._request(
            senders[index % len(senders)],
            pickup=pickup,
            delivery=delivery,
            depart=legs[0].depart_at + timedelta(minutes=random.randint(-600, 60)),
            title=f"K7 probe {index}",
        )


def _overlapping_journeys(request) -> int:
    from apps.trips.models import JourneyLeg

    return (
        JourneyLeg.objects.filter(
            depart_at__lte=request.ready_window_end,
            arrive_at__gte=request.ready_window_start,
        )
        .values("journey_id")
        .distinct()
        .count()
    )


def cmd_matching(args) -> None:
    from apps.accounts.models import User
    from apps.matching import v1_views
    from apps.parcels.models import DeliveryRequest
    from apps.trips.models import Journey

    # Per-user discovery throttles (10/min) would measure the throttle.
    for view in (v1_views.FindTravelersV1View, v1_views.CompatibleRequestsV1View):
        view.throttle_classes = ()
    world = _world()
    random.seed(20260923)
    sender = next(s for s in world["senders"] if s["open_request_ids"])
    request = DeliveryRequest.objects.get(pk=sender["open_request_ids"][0])
    traveler = world["travelers"][0]
    journey = Journey.objects.get(pk=traveler["journey_ids"][0])
    admin = User.objects.get(pk=world["admins"][0]["id"])
    client = Client()
    sender_auth = {"HTTP_AUTHORIZATION": f"Bearer {sender['token']}"}
    traveler_auth = {"HTTP_AUTHORIZATION": f"Bearer {traveler['token']}"}
    report = []
    base = {
        "overlapping_journeys": _overlapping_journeys(request),
        "journey_window_requests": DeliveryRequest.objects.filter(
            status="open",
            ready_window_start__lte=journey.legs.order_by("-position").first().arrive_at,
            ready_window_end__gte=journey.legs.order_by("position").first().depart_at,
        ).count(),
    }
    for size in [0, *args.sizes]:
        started = time.perf_counter()
        if size:
            need = size - _overlapping_journeys(request)
            if need > 0:
                _make_journeys(request, need, args.exact_share, admin)
            existing = DeliveryRequest.objects.filter(title__startswith="K7 probe").count()
            if size - existing > 0:
                _make_requests(journey, size - existing, args.exact_share)
            _analyze("trips_journey", "trips_journey_leg", "parcels_request", "parcels_delivery")
        grow = time.perf_counter() - started
        ft = _measure(
            client,
            f"/api/matches/find-travelers?parcel_id={request.pk}",
            runs=5,
            headers=sender_auth,
        )
        ft_page2 = _measure(
            client,
            f"/api/matches/find-travelers?parcel_id={request.pk}&offset=20",
            runs=3,
            headers=sender_auth,
            explain=False,
        )
        cr = _measure(
            client,
            f"/api/matches/compatible-requests?journey_id={journey.pk}",
            runs=5,
            headers=traveler_auth,
        )
        body = client.get(
            f"/api/matches/find-travelers?parcel_id={request.pk}",
            HTTP_HOST=HOST,
            **sender_auth,
        ).json()
        row = {
            "step": size,
            "grow_s": round(grow),
            "overlapping_journeys": _overlapping_journeys(request),
            "baseline": base,
            "find_travelers": ft,
            "find_travelers_total": body.get("total"),
            "find_travelers_page2_ms": ft_page2["wall_ms"],
            "compatible_requests": cr,
        }
        print(json.dumps(row), flush=True)
        report.append(row)
    _write(args, report)


def cmd_inbox(args) -> None:
    world = _world()
    client = Client()
    report = []
    for size in args.sizes:
        started = time.perf_counter()
        _grow_notifications(size)
        _analyze("notification")
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT recipient_id, count(*) FROM notification "
                "GROUP BY recipient_id ORDER BY 2 DESC LIMIT 1"
            )
            heavy_id, heavy_rows = cursor.fetchone()
            cursor.execute("SELECT pg_total_relation_size('notification')")
            table_bytes = cursor.fetchone()[0]
        account = next(
            a for a in (*world["senders"], *world["travelers"]) if a["id"] == heavy_id
        )
        auth = {"HTTP_AUTHORIZATION": f"Bearer {account['token']}"}
        row = {
            "step": size,
            "rows": _count("notification"),
            "table_mb": round(table_bytes / 1024 / 1024),
            "heaviest_user_rows": heavy_rows,
            "grow_s": round(time.perf_counter() - started),
            "list": _measure(client, "/api/notifications?bucket=all", headers=auth),
            "unread_count": _measure(client, "/api/notifications/unread-count", headers=auth),
        }
        print(json.dumps(row), flush=True)
        report.append(row)
    _write(args, report)


def _write(args, report) -> None:
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("search", "matching", "inbox"):
        p = sub.add_parser(name)
        p.add_argument("--sizes", type=int, nargs="+", required=True)
        p.add_argument("--out", default="")
        if name == "matching":
            p.add_argument("--exact-share", type=float, default=0.1)
    args = parser.parse_args()
    {"search": cmd_search, "matching": cmd_matching, "inbox": cmd_inbox}[args.command](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
