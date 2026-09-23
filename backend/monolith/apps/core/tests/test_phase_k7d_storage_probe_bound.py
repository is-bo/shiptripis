"""K7 D: evidence reachability checks cannot hold an admin page hostage.

KYC detail, the payout identity check and the payout-method review page all
HEAD every stored ID image before they render (8F-C). Those HEADs ran in
series, each on a probe that retried once, so an object-store outage held the
request for about 26 seconds (three slots, two attempts, four-second reads).
The check itself stays: it is what turns a storage fault into "temporarily
unavailable, try again" instead of a broken image. What changes is its cost:
one attempt per HEAD, a short connect and read, and the slots side by side.
"""

from __future__ import annotations

import socket
import threading
import time
from types import SimpleNamespace
from unittest import mock

from botocore.exceptions import ClientError
from django.test import SimpleTestCase, override_settings

from apps.admin_panel import console_views
from apps.core import storage
from apps.core.storage import readable_many, reset_storage_clients, storage_for

LOCAL_KYC = {
    "S3_REGION": "us-east-1",
    "S3_ACCESS_KEY": "k7d-access",
    "S3_SECRET_KEY": "k7d-secret",
    "S3_USE_PATH_STYLE": True,
    "S3_BUCKET_KYC": "shiptrip-kyc",
    "KYC_S3_ACCESS_KEY": "",
    "KYC_S3_SECRET_KEY": "",
}

SUBMISSION = SimpleNamespace(
    pk=7, front_image_key="kyc/f.jpg", back_image_key="kyc/b.jpg", selfie_image_key="kyc/s.jpg"
)


class _SilentStore:
    """Accepts every connection and never answers: a store that has hung."""

    def __init__(self):
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(16)
        self.server.settimeout(0.2)
        self.connections: list[socket.socket] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._accept, daemon=True)
        self._thread.start()

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.server.getsockname()[1]}"

    def _accept(self):
        while not self._stop.is_set():
            try:
                conn, _ = self.server.accept()
            except OSError:
                continue
            self.connections.append(conn)

    def close(self):
        self._stop.set()
        self._thread.join(timeout=2)
        for conn in self.connections:
            conn.close()
        self.server.close()


class ProbeBoundTests(SimpleTestCase):
    def setUp(self):
        reset_storage_clients()
        self.addCleanup(reset_storage_clients)

    @override_settings(**LOCAL_KYC, S3_ENDPOINT_URL="http://127.0.0.1:9")
    def test_the_probe_client_makes_one_short_attempt(self):
        config = storage_for("kyc").probe_client.meta.config
        assert config.connect_timeout <= 2
        assert config.read_timeout <= 3
        # No retry on the request path: the operator's Try again is the retry.
        assert config.retries["total_max_attempts"] == 1

    def test_a_hung_store_costs_one_probe_for_all_three_slots_and_no_retries(self):
        silent = _SilentStore()
        self.addCleanup(silent.close)
        with (
            override_settings(**LOCAL_KYC, S3_ENDPOINT_URL=silent.endpoint),
            mock.patch.object(storage, "_PROBE_READ_TIMEOUT_SECONDS", 0.5),
            mock.patch.object(console_views, "has_admin_permission", return_value=True),
        ):
            reset_storage_clients()
            started = time.perf_counter()
            slots, unavailable = console_views.kyc_evidence_slots(SUBMISSION, user=None)
            elapsed = time.perf_counter() - started

        assert unavailable is True
        assert [slot["available"] for slot in slots] == [False, False, False]
        assert [slot["previewable"] for slot in slots] == [False, False, False]
        # Three serial reads would be at least 1.5 s; side by side it is one.
        assert elapsed < 1.4, elapsed
        # One connection per slot: a retry would have opened a second each.
        assert len(silent.connections) == 3, len(silent.connections)

    @override_settings(**LOCAL_KYC, S3_ENDPOINT_URL="http://127.0.0.1:9")
    def test_slow_heads_run_side_by_side_and_keep_their_answers(self):
        store = storage_for("kyc")
        denied = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access Denied."}},
            "HeadObject",
        )

        def slow_head(*, Bucket, Key):
            time.sleep(0.4)
            if Key == "kyc/b.jpg":
                raise denied
            return {}

        with (
            mock.patch.object(store.probe_client, "head_object", side_effect=slow_head),
            mock.patch.object(console_views, "has_admin_permission", return_value=True),
        ):
            started = time.perf_counter()
            slots, unavailable = console_views.kyc_evidence_slots(SUBMISSION, user=None)
            elapsed = time.perf_counter() - started

        assert elapsed < 1.0, elapsed  # serial would be at least 1.2 s
        assert {slot["slot"]: slot["available"] for slot in slots} == {
            "front": True,
            "back": False,
            "selfie": True,
        }
        assert unavailable is True
        # The links still go through the audited, permissioned evidence view;
        # nothing about how evidence is served changed.
        assert all(slot["url"].startswith("/") for slot in slots)
        assert all("X-Amz" not in slot["url"] for slot in slots)

    @override_settings(**LOCAL_KYC, S3_ENDPOINT_URL="http://127.0.0.1:9")
    def test_a_reviewer_without_evidence_access_triggers_no_heads(self):
        store = storage_for("kyc")
        with (
            mock.patch.object(store.probe_client, "head_object") as head,
            mock.patch.object(console_views, "has_admin_permission", return_value=False),
        ):
            slots, unavailable = console_views.kyc_evidence_slots(SUBMISSION, user=None)
        head.assert_not_called()
        assert unavailable is False
        assert len(slots) == 3

    @override_settings(**LOCAL_KYC, S3_ENDPOINT_URL="http://127.0.0.1:9")
    def test_readable_many_skips_blank_and_duplicate_keys(self):
        store = storage_for("kyc")
        with mock.patch.object(store.probe_client, "head_object", return_value={}) as head:
            assert readable_many(store, ["a", "", "a", None, "b"]) == {"a": True, "b": True}
            assert readable_many(store, []) == {}
        assert head.call_count == 2
