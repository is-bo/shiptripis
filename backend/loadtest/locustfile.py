"""ShipTrip early-launch traffic mix for Locust.

Three populations, weighted like a marketplace in its first months:

* Senders (60 %): home badge + active Deals, Deal list/detail, chat inbox and
  thread, the odd chat send, notification inbox, place search, Journey search,
  their own requests and Find Travelers.
* Travelers (38 %): the same Deal/chat/notification surfaces plus their
  Journeys, open-request search and compatible requests.
* Operators (2 %): the JSON admin dashboard and lists plus Admin console pages
  (session cookie), at a slower pace.

Think time is 2-8 s per user between screens; a "screen" task issues the
requests the Flutter screen issues together. Per-user endpoint throttles
(matching discovery 10/min, chat send 60/min) stay at production values, so
task weights keep an individual user inside them: a 429 here is a real error.

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
JOURNEY_ROUTES = WORLD["journey_routes"]

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
    parser.add_argument(
        "--search-page-size",
        type=int,
        default=0,
        help=(
            "page_size for Journey browse and the open-request feed. 0 (default) "
            "sends none, as the Flutter client does, so the server's 100-row page."
        ),
    )


def _paged(environment, path: str) -> str:  # noqa: ANN001
    size = environment.parsed_options.search_page_size
    if not size:
        return path
    return f"{path}{'&' if '?' in path else '?'}page_size={size}"


class _AppUser(HttpUser):
    abstract = True
    wait_time = between(2, 8)
    account: dict

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

    # -- shared screens ---------------------------------------------------

    def _get(self, path: str, name: str) -> None:
        self.client.get(path, name=name)

    def home_badge(self) -> None:
        self._get("/api/notifications/unread-count", "notifications unread-count")

    def deals_active(self) -> None:
        self._get("/api/deals?activity=active", "deals ?activity=active")

    def deals_list(self) -> None:
        self._get("/api/deals", "deals list")

    def deal_detail(self) -> None:
        ids = self.account.get("deal_ids") or SAMPLE_DEALS
        deal_id = random.choice(ids)
        with self.client.get(
            f"/api/deals/{deal_id}", name="deals detail", catch_response=True
        ) as response:
            # A sample id that belongs to someone else is a correct 404.
            if response.status_code == 404 and not self.account.get("deal_ids"):
                response.success()

    def chat_inbox(self) -> None:
        self._get("/api/chat/threads", "chat threads")

    def chat_thread(self) -> None:
        matches = self.account.get("chat_match_ids")
        if not matches:
            self.chat_inbox()
            return
        self._get(
            f"/api/matches/{random.choice(matches)}/chat/messages?latest=1",
            "chat messages",
        )

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

    def notifications(self) -> None:
        self._get("/api/notifications?bucket=all", "notifications list")

    def place_search(self) -> None:
        # The Flutter place picker's exact query shape.
        query = random.choice(PLACE_QUERIES)
        country = random.choice(PLACE_COUNTRIES)
        self._get(
            f"/api/geography/places?country={country}&q={query}"
            "&place_type=locality,airport&page_size=25",
            "geography places ?q",
        )

    def catalogue(self) -> None:
        # Countries/airports carry strong ETags; a warm client revalidates.
        for path, name in (
            ("/api/geography/countries", "geography countries"),
            ("/api/airports", "airports"),
        ):
            headers = {}
            if etag := self.catalogue_etags.get(path):
                headers["If-None-Match"] = etag
            with self.client.get(path, name=name, headers=headers, catch_response=True) as r:
                if r.status_code == 304:
                    r.success()
                elif r.status_code == 200 and r.headers.get("ETag"):
                    self.catalogue_etags[path] = r.headers["ETag"]


class SenderUser(_AppUser):
    weight = 60

    def on_start(self) -> None:
        self.account = next(_SENDERS)
        super().on_start()

    @task(10)
    def home(self) -> None:
        self.home_badge()
        self.deals_active()

    @task(5)
    def deliveries(self) -> None:
        self.deals_list()

    @task(6)
    def open_deal(self) -> None:
        self.deal_detail()

    @task(5)
    def inbox(self) -> None:
        self.chat_inbox()

    @task(6)
    def thread(self) -> None:
        self.chat_thread()

    @task(1)
    def send(self) -> None:
        self.chat_send()

    @task(4)
    def bell(self) -> None:
        self.notifications()

    @task(6)
    def search_places(self) -> None:
        self.place_search()

    @task(1)
    def reference(self) -> None:
        self.catalogue()

    @task(2)
    def browse_journeys(self) -> None:
        # The unfiltered browse the Flutter client sends: no page_size, so the
        # server's 100-row default page.
        self._get(_paged(self.environment, "/api/journeys/search"), "journeys search (browse)")

    @task(3)
    def search_journeys(self) -> None:
        start, destination = random.choice(JOURNEY_ROUTES)
        self._get(
            f"/api/journeys/search?start_place_id={start}&destination_place_id={destination}",
            "journeys search (corridor)",
        )

    @task(3)
    def my_requests(self) -> None:
        self._get("/api/parcels", "parcels list")
        if self.account["request_ids"]:
            self._get(f"/api/parcels/{random.choice(self.account['request_ids'])}", "parcels detail")

    @task(2)
    def find_travelers(self) -> None:
        pool = self.account["open_request_ids"] or self.account["request_ids"]
        self._get(
            f"/api/matches/find-travelers?parcel_id={random.choice(pool)}",
            "matches find-travelers",
        )


class TravelerUser(_AppUser):
    weight = 38

    def on_start(self) -> None:
        self.account = next(_TRAVELERS)
        super().on_start()

    @task(10)
    def home(self) -> None:
        self.home_badge()
        self._get("/api/journeys", "journeys list")

    @task(4)
    def journey(self) -> None:
        if self.account["journey_ids"]:
            self._get(
                f"/api/journeys/{random.choice(self.account['journey_ids'])}",
                "journeys detail",
            )

    @task(5)
    def deliveries(self) -> None:
        self.deals_active()

    @task(5)
    def open_deal(self) -> None:
        self.deal_detail()

    @task(5)
    def inbox(self) -> None:
        self.chat_inbox()

    @task(6)
    def thread(self) -> None:
        self.chat_thread()

    @task(1)
    def send(self) -> None:
        self.chat_send()

    @task(4)
    def bell(self) -> None:
        self.notifications()

    @task(4)
    def open_requests(self) -> None:
        self._get(_paged(self.environment, "/api/parcels/open"), "parcels open")

    @task(2)
    def compatible_requests(self) -> None:
        if self.account["journey_ids"]:
            self._get(
                "/api/matches/compatible-requests?journey_id="
                f"{random.choice(self.account['journey_ids'])}",
                "matches compatible-requests",
            )

    @task(3)
    def search_places(self) -> None:
        self.place_search()


class OperatorUser(HttpUser):
    weight = 2
    wait_time = between(5, 15)

    def on_start(self) -> None:
        self.account = next(_ADMINS)
        self.api_headers = {
            "Authorization": f"Bearer {self.account['token']}",
            "Accept": "application/json",
        }
        self.client.cookies.set("sessionid", self.account["sessionid"])

    @task(4)
    def dashboard(self) -> None:
        self.client.get("/api/admin/dashboard", headers=self.api_headers, name="admin api dashboard")

    @task(3)
    def deal_queue(self) -> None:
        self.client.get("/api/admin/deals", headers=self.api_headers, name="admin api deals")

    @task(2)
    def users(self) -> None:
        self.client.get("/api/admin/users", headers=self.api_headers, name="admin api users")

    @task(3)
    def console_overview(self) -> None:
        self.client.get("/admin/", name="admin console overview")

    @task(2)
    def console_deals(self) -> None:
        self.client.get("/admin/marketplace/deals/", name="admin console deals")

    @task(1)
    def console_deal(self) -> None:
        self.client.get(
            f"/admin/marketplace/deals/{random.choice(SAMPLE_DEALS)}/",
            name="admin console deal detail",
        )
