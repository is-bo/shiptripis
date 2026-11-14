"""K7 end-to-end certification profile over one deterministic world.

One PostgreSQL world carries both halves of the product: the K4 canonical
marketplace (a funded V1 Deal with chat, notifications, an open compatible
request, extra funded threads, a dispute) and the K3 manual-DZD Finance world
(a released payout, a reviewed DZD profile, KYC, an operator).  Every flow in
master plan section 15.10 is read through its real endpoint.

The ceilings are broad regression guards, as in K3/K4.  Set
``SHIPTRIP_K7_PROFILE=1`` to print the measured latency (median of six warmed
reads), query count, summed DB time and rendered payload bytes recorded in
``docs/k7-notes/certification.md``.
"""

from __future__ import annotations

import json
import os
from statistics import median
from time import perf_counter
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.db import connection
from django.test import Client, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.admin_panel.tests.two_step_helpers import staff_login
from apps.admin_panel.permissions import assign_admin_roles
from apps.chat.models import ChatMessage
from apps.deals.models import Deal
from apps.deals.tests.phase4_factories import enable_mock_rail
from apps.disputes.models import Dispute
from apps.finance.models import PaymentOrder, Payout
from apps.finance.tests.factories import pay_order_with_mock
from apps.finance.tests.test_phase8fh4_manual import (  # noqa: F401
    build_manual,
    configured_h4,
)
from apps.finance.tests.test_phase8fh5_control_plane import (  # noqa: F401
    no_provider_network,
)
from apps.finance.tests.test_phase_j12_finance_route_performance import (  # noqa: F401
    console_staticfiles,
)
from apps.matching.tests.test_phase8dr_offer_locks import CanonicalOfferFixture
from apps.matching.v1_services import accept_offer
from apps.notifications.models import Notification
from apps.kyc.models import KycSubmission

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="K7 certification reads Finance snapshots that need PostgreSQL",
    ),
]

PASSWORD = "Sup3rStrongPass!"


class _Marketplace(CanonicalOfferFixture):
    """The K4 canonical world, built outside a TestCase."""

    def build(self) -> None:
        enable_mock_rail()
        self.build_world()
        self.deal = accept_offer(pending_offer=self.propose(), actor=self.traveler).deal
        self.balance_order = PaymentOrder.objects.get(
            deal=self.deal, purpose=PaymentOrder.Purpose.DEAL_BALANCE
        )
        pay_order_with_mock(Client(), self.balance_order)
        self.deal.refresh_from_db()
        ChatMessage.objects.create(
            match=self.deal.match,
            sender=self.traveler,
            body="K7 representative message",
        )
        for index in range(10):
            Notification.objects.create(
                recipient=self.sender,
                channel="system.notice",
                event_id=f"k7-notification-{index}",
                payload={"index": index},
            )
        for index in range(4):
            journey, flight, drive = self._journey(self.traveler, origin=self.cdg)
            offer = self.propose(
                delivery_request=self._request(
                    self.paris, self.jijel, title=f"K7 thread {index}"
                ),
                journey=journey,
                start_leg_id=flight.pk,
                end_leg_id=drive.pk,
            )
            deal = accept_offer(pending_offer=offer, actor=self.traveler).deal
            Deal.objects.filter(pk=deal.pk).update(
                status=Deal.Status.FUNDED, funded_at=timezone.now()
            )
            ChatMessage.objects.create(
                match=deal.match, sender=self.traveler, body=f"K7 thread {index}"
            )
        self.dispute = Dispute.objects.create(
            deal=self.deal,
            opened_by=self.sender,
            opened_by_role=Dispute.OpenedByRole.SENDER,
            category=Dispute.Category.DAMAGED,
            reason_text="K7 certification dispute",
        )
        # Matching needs an open request; acceptance closed the first one.
        self.matching_request = self._request(
            self.paris, self.jijel, title="K7 matching request"
        )


def _api(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _measure(client, path, *, method="get", body=None) -> dict:
    """K4's method: one warm read, then the median of six timed reads.

    ``body`` may be a callable so a single-use credential (a rotating refresh
    token) is minted outside the timed region for each call.
    """

    cache.clear()  # production throttle budgets must not leak between paths

    def call():
        payload = body() if callable(body) else body
        if method == "get":
            return client.get(path)
        return client.post(path, payload, format="json")

    def timed():
        payload = body() if callable(body) else body
        started = perf_counter()
        if method == "get":
            response = client.get(path)
        else:
            response = client.post(path, payload, format="json")
        return response, (perf_counter() - started) * 1_000

    warm = call()
    assert warm.status_code == 200, (path, warm.status_code)
    latencies = []
    for _ in range(5):
        _response, elapsed = timed()
        latencies.append(elapsed)
    with CaptureQueriesContext(connection) as captured:
        response, elapsed = timed()
    latencies.append(elapsed)
    assert response.status_code == 200, (path, response.status_code)
    if hasattr(response, "render"):
        response.render()
    return {
        "latency_ms": round(median(latencies), 2),
        "queries": len(captured.captured_queries),
        "db_ms": round(
            sum(float(row.get("time") or 0) for row in captured.captured_queries)
            * 1_000,
            2,
        ),
        "payload_bytes": len(response.content),
    }


def _profile(world: _Marketplace, finance) -> dict[str, dict]:
    scenario, payout, _dzd_profile = finance
    sender = _api(world.sender)
    traveler = _api(world.traveler)
    anonymous = APIClient()
    deal = world.deal
    own_payout = Payout.objects.filter(deal=deal).first()

    operator = Client()
    assign_admin_roles(scenario.admin, ["super_admin"], elevate_super_admin=True)
    staff_login(operator, scenario.admin)
    kyc = KycSubmission.objects.filter(user=scenario.traveler).first()

    rows = {
        # Auth
        "auth.login": _measure(
            anonymous,
            "/api/auth/sign-in",
            method="post",
            body={"email": world.sender.email, "password": PASSWORD},
        ),
        "auth.restore": _measure(
            anonymous,
            "/api/auth/refresh",
            method="post",
            body=lambda: {"refresh": str(RefreshToken.for_user(world.sender))},
        ),
        "auth.profile": _measure(sender, "/api/me"),
        # Sender
        "sender.home_current_deals": _measure(sender, "/api/deals?scope=current"),
        # The exact K4 request, so the K5 `attention` projection is compared
        # like for like.
        "sender.deal_list": _measure(sender, "/api/deals"),
        "sender.home_unread_count": _measure(sender, "/api/notifications/unread-count"),
        "sender.requests": _measure(sender, "/api/parcels"),
        "sender.request_detail": _measure(sender, f"/api/parcels/{world.request.pk}"),
        "sender.find_travelers": _measure(
            sender,
            reverse("matches-find-travelers-v1")
            + f"?parcel_id={world.matching_request.pk}",
        ),
        "sender.offers_matches": _measure(sender, "/api/matches?role=sender"),
        "sender.offer_chain": _measure(sender, f"/api/matches/{deal.match_id}/offers"),
        "sender.deal_detail": _measure(sender, f"/api/deals/{deal.pk}"),
        "sender.deal_history": _measure(
            sender, "/api/deals?scope=history&page_size=20"
        ),
        "sender.payment_status": _measure(sender, f"/api/deals/{deal.pk}/payment"),
        "sender.payment_order": _measure(
            sender,
            f"/api/payments/orders/{world.balance_order.public_reference}",
        ),
        # Traveler
        "traveler.home_current_deals": _measure(traveler, "/api/deals?scope=current"),
        "traveler.home_compatible_requests": _measure(
            traveler,
            f"/api/matches/compatible-requests?journey_id={world.journey.pk}",
        ),
        "traveler.journeys": _measure(traveler, "/api/journeys"),
        "traveler.journey_detail": _measure(
            traveler, f"/api/journeys/{world.journey.pk}"
        ),
        "traveler.offers_matches": _measure(traveler, "/api/matches?role=traveler"),
        "traveler.deal_detail": _measure(traveler, f"/api/deals/{deal.pk}"),
        "traveler.earnings_history": _measure(
            traveler, "/api/payouts?page=1&page_size=30"
        ),
        "traveler.payout_detail": _measure(
            traveler, f"/api/payouts/{own_payout.public_reference}"
        )
        if own_payout is not None
        else None,
        # Shared
        "shared.chat_inbox": _measure(sender, "/api/chat/threads"),
        "shared.chat_messages": _measure(
            sender, f"/api/matches/{deal.match_id}/chat/messages?latest=1"
        ),
        "shared.notifications": _measure(sender, "/api/notifications?bucket=all"),
        "shared.deal_ratings": _measure(sender, f"/api/deals/{deal.pk}/ratings"),
        "shared.my_ratings": _measure(sender, "/api/users/me/ratings"),
        "shared.deal_disputes": _measure(sender, f"/api/deals/{deal.pk}/disputes"),
        "shared.dispute_detail": _measure(sender, f"/api/disputes/{world.dispute.pk}"),
    }
    with override_settings(PAYOUT_PROFILES_ENABLED=True):
        rows["traveler.payout_methods"] = _measure(traveler, "/api/payouts/methods")
    # KYC evidence is HEAD-probed on the request path. There is no object
    # store here, so an unstubbed probe measures its own timeout (4 s x 2
    # attempts per slot), not the page; K6 stubbed it the same way.
    with (
        override_settings(FINANCE_DASHBOARD_ENABLED=True),
        patch("apps.core.storage.ObjectStore.readable", return_value=True),
    ):
        admin = {
            "admin.overview": reverse("admin_console:overview"),
            "admin.people": reverse("admin_console:users"),
            "admin.person_detail": reverse(
                "admin_console:user-detail", args=[scenario.traveler.pk]
            ),
            "admin.kyc_queue": reverse("admin_console:kyc-queue"),
            "admin.kyc_detail": reverse("admin_console:kyc-detail", args=[kyc.pk]),
            "admin.finance_overview": reverse("admin_console:finance-dashboard")
            + "?mode=test",
            "admin.payouts_hub": reverse("admin_console:finance-payouts")
            + "?mode=test",
            "admin.payout_detail": reverse(
                "admin_console:payout-detail", args=[payout.pk]
            ),
            "admin.disputes": reverse("admin_console:disputes"),
            "admin.dispute_detail": reverse(
                "admin_console:dispute-detail", args=[world.dispute.pk]
            ),
            "admin.audit": reverse("admin_console:audit"),
        }
        for name, url in admin.items():
            rows[name] = _measure(operator, url)
    return {name: row for name, row in rows.items() if row is not None}


# Broad guards, not pins: roughly the measured count plus headroom, and the
# K3/K4 ceiling wherever one already exists for the same surface.
QUERY_CEILINGS = {
    "auth.login": 12,
    "auth.restore": 8,
    "auth.profile": 8,
    "sender.home_current_deals": 8,  # K4 deal_list
    "sender.deal_list": 8,  # K4
    "sender.home_unread_count": 10,  # K4
    "sender.requests": 8,  # K4
    "sender.request_detail": 8,  # K4
    "sender.find_travelers": 10,  # K4
    "sender.offers_matches": 12,
    "sender.offer_chain": 10,
    "sender.deal_detail": 16,  # K4
    "sender.deal_history": 8,
    "sender.payment_status": 16,
    "sender.payment_order": 12,
    "traveler.home_current_deals": 8,
    "traveler.home_compatible_requests": 14,
    "traveler.journeys": 12,  # K4
    "traveler.journey_detail": 14,  # K4
    "traveler.offers_matches": 12,
    # Measured 16, the K4 sender-side ceiling exactly; the traveler view adds
    # payout and leg reads. Headroom here, recorded as a K7 observation.
    "traveler.deal_detail": 20,
    "traveler.earnings_history": 12,
    "traveler.payout_detail": 10,
    "traveler.payout_methods": 4,
    "shared.chat_inbox": 8,  # K4
    "shared.chat_messages": 6,  # K4
    "shared.notifications": 12,  # K4
    "shared.deal_ratings": 10,
    "shared.my_ratings": 8,
    "shared.deal_disputes": 12,
    "shared.dispute_detail": 16,
    "admin.overview": 22,  # K3
    "admin.people": 8,  # K3
    "admin.person_detail": 30,  # K3
    "admin.finance_overview": 35,  # K3
    "admin.payouts_hub": 30,  # K3
    "admin.payout_detail": 28,  # K3 manual DZD detail
    "admin.disputes": 10,  # K3
    "admin.dispute_detail": 36,  # measured 29 for one dispute; no K3 budget
    "admin.kyc_queue": 10,
    "admin.kyc_detail": 10,
    "admin.audit": 10,
}


def test_k7_representative_flows_stay_within_budgets(configured_h4):  # noqa: F811
    world = _Marketplace()
    # As in K4's world: funding here predates the traveler's payout setup.
    with override_settings(PAYOUT_PROFILES_ENABLED=False):
        world.build()
    finance = build_manual(prefix="k7")

    profile = _profile(world, finance)
    if os.environ.get("SHIPTRIP_K7_PROFILE") == "1":
        print("K7_PROFILE=" + json.dumps(profile, sort_keys=True))

    over = {
        name: (profile[name]["queries"], ceiling)
        for name, ceiling in QUERY_CEILINGS.items()
        if profile[name]["queries"] > ceiling
    }
    assert not over, over
    # K4 payload guards, re-applied to the flows that now carry K5 additions.
    assert profile["sender.home_current_deals"]["payload_bytes"] < 150_000
    assert profile["sender.find_travelers"]["payload_bytes"] < 50_000
    assert profile["traveler.journeys"]["payload_bytes"] < 250_000
