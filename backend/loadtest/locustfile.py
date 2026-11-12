"""ShipTrip early-launch traffic mix for Locust, shaped on the Flutter screens.

Every task is one screen (or one app event) and issues exactly the requests
that screen issues, with the app's query parameters (``mobile/lib/data/
repositories.dart`` and the providers in ``mobile/lib/app/app_state.dart``):

* Session: cold start or resume. K5 fixed this at ``/api/me``, chat threads,
  the Match list, ``deals?scope=current``, own requests (senders) or own
  Journeys (travelers), and the bell's ``unread-count``. List reads go through
  ``getAllPages``, which always sends ``page_size=100``.
* Deal detail, the Offers list (``GET /api/matches``, every role), chat inbox,
  chat thread (``latest=1``), chat send, notification inbox (``bucket=active``),
  Deliveries history (20-row pages), Profile.
* Senders: request detail, Find Travelers (``limit=10&sort=best_match``, the
  discovery screen's first page), the place picker while creating a request.
* Travelers: Journey detail (the Journey plus ``compatible-requests``),
  Earnings (payout history, first page), the place picker while creating a
  Journey.
* Operators (2 %): the server-rendered Admin console, at a slower pace.

The K6 mix also modelled ``GET /api/journeys/search`` and ``GET /api/parcels/open``,
which no app screen called (K7) and which L2A removed, which is why its numbers
are superseded. The L2A ``/api/discovery/*`` tiers are not modelled yet: no
screen calls them until L2B puts them on Home.

Populations: senders 60 %, travelers 38 %, operators 2 %. Think time is 2-8 s
between screens. Per-user endpoint throttles (matching discovery 10/min, chat
send 60/min) stay at production values; task weights keep one user inside them,
so a 429 here is a real error. Relative screen frequencies are an assumption
(there is no production analytics yet), anchored on the screen structure: the
session reads fire on every open and resume, detail and chat screens are the
most visited, discovery and creation flows are occasional.

Seed first (``seed.py``), then for example::

    locust -f backend/loadtest/locustfile.py --host http://127.0.0.1:8080 \
        --headless -u 100 -r 10 -t 5m --csv .data/run-100

``LOADTEST_WORLD`` overrides the world file path.
"""

from __future__ import annotations

import itertools
import json
import os
import random
import uuid
from pathlib import Path

from locust import HttpUser, between, events, task

WORLD_PATH = Path(
    os.environ.get("LOADTEST_WORLD", Path(__file__).resolve().parent / ".data" / "world.json")
)
WORLD = json.loads(WORLD_PATH.read_text(encoding="utf-8"))
PLACE_QUERIES = WORLD["place_queries"]
PLACE_COUNTRIES = WORLD["place_countries"]
SAMPLE_DEALS = WORLD["sample_deal_ids"]

# Hand each simulated user a distinct seeded account, round-robin.
_SENDERS = itertools.cycle(WORLD["senders"])
_TRAVELERS = itertools.cycle(WORLD["travelers"])
_ADMINS = itertools.cycle(WORLD["admins"])

CHAT_LINES = (
    "On my way to the pickup point.",
    "Can we meet at 18:00?",
    "Parcel received, thank you.",
    "Boarding now.",
)


@events.init_command_line_parser.add_listener
def _(parser):  # noqa: ANN001
    parser.add_argument(
        "--chat-send-share",
        type=float,
        default=1.0,
        help="Multiplier on the chat-send task weight (0 disables writes).",
    )


class _AppUser(HttpUser):
    abstract = True
    wait_time = between(2, 8)
    account: dict
    # The role's own list on Home and Deliveries: requests or Journeys.
    own_list_path: str
    own_list_name: str

    def on_start(self) -> None:
        self.client.headers.update(
            {
                "Authorization": f"Bearer {self.account['token']}",
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "User-Agent": "shiptrip-loadtest/1",
            }
        )
        self.catalogue_etags: dict[str, str] = {}

    def _get(self, path: str, name: str) -> None:
        self.client.get(path, name=name)

    # -- shared screens ---------------------------------------------------

    @task(4)
    def session(self) -> None:
        # Cold start or resume: the five K5 catch-up reads plus the bell.
        self._get("/api/me", "me")
        self._get("/api/chat/threads", "chat threads")
        self._get("/api/matches?page_size=100", "matches list (Offers)")
        self._get("/api/deals?scope=current&page_size=100", "deals ?scope=current")
        self._get(self.own_list_path, self.own_list_name)
        self._get("/api/notifications/unread-count", "notifications unread-count")

    @task(6)
    def deal_detail(self) -> None:
        # Home and Deliveries rows open the Deal. Without a Deal, the row the
        # user taps is their own request or Journey.
        if self.account.get("deal_ids"):
            self._get(f"/api/deals/{random.choice(self.account['deal_ids'])}", "deals detail")
        else:
            self.own_detail()

    @task(3)
    def offers(self) -> None:
        # Offers list (and every matches live-event refresh).
        self._get("/api/matches?page_size=100", "matches list (Offers)")

    @task(4)
    def chat_inbox(self) -> None:
        self._get("/api/chat/threads", "chat threads")

    @task(6)
    def chat_thread(self) -> None:
        matches = self.account.get("chat_match_ids")
        if not matches:
            self.chat_inbox()
            return
        self._get(
            f"/api/matches/{random.choice(matches)}/chat/messages?page_size=50&latest=1",
            "chat messages",
        )

    @task(1)
    def chat_send(self) -> None:
        matches = self.account.get("chat_match_ids")
        if not matches or self.environment.parsed_options.chat_send_share <= 0:
            return
        if random.random() > self.environment.parsed_options.chat_send_share:
            return
        self.client.post(
            f"/api/matches/{random.choice(matches)}/chat/messages",
            json={"body": random.choice(CHAT_LINES), "client_message_id": str(uuid.uuid4())},
            name="chat send",
        )

    @task(3)
    def bell(self) -> None:
        # The badge count is already held by the header; the inbox reads the
        # active page, and sometimes the user opens the history tab too.
        self._get("/api/notifications?bucket=active", "notifications list")
        if random.random() < 0.25:
            self._get("/api/notifications?bucket=history", "notifications list")

    @task(1)
    def history(self) -> None:
        self._get("/api/deals?scope=history&page_size=20", "deals ?scope=history")

    @task(1)
    def profile(self) -> None:
        self._get("/api/deals?status=completed", "deals count (Profile)")
        self._get("/api/users/me/ratings", "ratings received")

    def own_detail(self) -> None:
        raise NotImplementedError

    def place_search(self) -> None:
        # The Flutter place picker's exact query shape.
        query = random.choice(PLACE_QUERIES)
        country = random.choice(PLACE_COUNTRIES)
        self._get(
            f"/api/geography/places?country={country}&q={query}"
            "&place_type=locality,airport&page_size=25",
            "geography places ?q",
        )


class SenderUser(_AppUser):
    weight = 60
    own_list_path = "/api/parcels?page_size=100"
    own_list_name = "parcels list"

    def on_start(self) -> None:
        self.account = next(_SENDERS)
        super().on_start()

    def own_detail(self) -> None:
        self._get(f"/api/parcels/{random.choice(self.account['request_ids'])}", "parcels detail")

    @task(2)
    def request_detail(self) -> None:
        self.own_detail()

    @task(3)
    def find_travelers(self) -> None:
        pool = self.account["open_request_ids"] or self.account["request_ids"]
        self._get(
            f"/api/matches/find-travelers?parcel_id={random.choice(pool)}"
            "&limit=10&offset=0&sort=best_match",
            "matches find-travelers",
        )

    @task(2)
    def create_request(self) -> None:
        self.place_search()

    @task(1)
    def reference(self) -> None:
        # The country catalogue carries a strong ETag; a warm client revalidates.
        for path, name in (("/api/geography/countries", "geography countries"),):
            headers = {}
            if etag := self.catalogue_etags.get(path):
                headers["If-None-Match"] = etag
            with self.client.get(path, name=name, headers=headers, catch_response=True) as r:
                if r.status_code == 304:
                    r.success()
                elif r.status_code == 200 and r.headers.get("ETag"):
                    self.catalogue_etags[path] = r.headers["ETag"]


class TravelerUser(_AppUser):
    weight = 38
    own_list_path = "/api/journeys?page_size=100"
    own_list_name = "journeys list"

    def on_start(self) -> None:
        self.account = next(_TRAVELERS)
        super().on_start()

    def own_detail(self) -> None:
        self._get(f"/api/journeys/{random.choice(self.account['journey_ids'])}", "journeys detail")

    @task(4)
    def journey_detail(self) -> None:
        # The Journey screen reads the Journey and its compatible requests.
        journey_id = random.choice(self.account["journey_ids"])
        self._get(f"/api/journeys/{journey_id}", "journeys detail")
        self._get(
            f"/api/matches/compatible-requests?journey_id={journey_id}",
            "matches compatible-requests",
        )

    @task(1)
    def earnings(self) -> None:
        self._get("/api/payouts?page=1&page_size=30", "payouts (Earnings)")

    @task(1)
    def create_journey(self) -> None:
        self.place_search()


class OperatorUser(HttpUser):
    """The Admin console (server-rendered, session cookie)."""

    weight = 2
    wait_time = between(5, 15)

    def on_start(self) -> None:
        self.account = next(_ADMINS)
        self.client.cookies.set("sessionid", self.account["sessionid"])

    @task(3)
    def overview(self) -> None:
        self.client.get("/admin/", name="admin console overview")

    @task(2)
    def people(self) -> None:
        self.client.get("/admin/users/", name="admin console people")

    @task(2)
    def deals(self) -> None:
        self.client.get("/admin/marketplace/deals/", name="admin console deals")

    @task(2)
    def deal(self) -> None:
        self.client.get(
            f"/admin/marketplace/deals/{random.choice(SAMPLE_DEALS)}/",
            name="admin console deal detail",
        )

    @task(1)
    def disputes(self) -> None:
        self.client.get("/admin/disputes/", name="admin console disputes")

    @task(1)
    def kyc_queue(self) -> None:
        self.client.get("/admin/verification/kyc/", name="admin console kyc queue")

    @task(1)
    def requests(self) -> None:
        # The seeded Super Admins hold no Finance role, so the Finance pages
        # answer 404 here; their cost is K3/K7's (about 0.5-0.6 s each).
        self.client.get("/admin/marketplace/requests/", name="admin console requests")
