"""Focused tests for the additive live chat history read contract."""

from __future__ import annotations

from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from django.db import close_old_connections
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.chat.models import ChatMessage
from apps.chat.tests.test_chat import (
    _accepted_offer,
    _client,
    _make_match,
    _pay,
    _user,
)
from apps.matching.models import Match
from apps.trips.models import Airport


class ChatLiveHistoryTests(APITestCase):
    def setUp(self):
        self.sender = _user("live-history-sender@example.com", "1")
        self.traveler = _user("live-history-traveler@example.com", "2")
        self.match = _make_match(self.sender, self.traveler)
        _pay(_accepted_offer(self.match, self.traveler), self.sender)
        self.url = f"/api/matches/{self.match.id}/chat/messages"

    def _messages(self, count: int) -> list[ChatMessage]:
        return list(
            ChatMessage.objects.bulk_create(
                [
                    ChatMessage(
                        match=self.match,
                        sender=self.traveler if index % 2 else self.sender,
                        body=f"message {index}",
                    )
                    for index in range(count)
                ]
            )
        )

    def test_latest_before_and_after_are_id_ordered_and_lossless(self):
        messages = self._messages(205)

        latest = _client(self.sender).get(
            self.url, {"latest": "1", "page_size": 7}
        )
        assert latest.status_code == 200, latest.data
        assert [row["id"] for row in latest.data["results"]] == [
            message.id for message in messages[-7:]
        ]
        assert latest.data["count"] == 7
        assert latest.data["has_more"] is True
        assert latest.data["next"] is None
        assert latest.data["oldest_id"] == messages[-7].id
        assert latest.data["latest_id"] == messages[-1].id

        before = _client(self.sender).get(
            self.url,
            {"before_id": str(latest.data["oldest_id"]), "page_size": 7},
        )
        assert [row["id"] for row in before.data["results"]] == [
            message.id for message in messages[-14:-7]
        ]
        assert before.data["has_more"] is True

        first = _client(self.sender).get(
            self.url, {"after_id": "0", "page_size": 200}
        )
        assert first.status_code == 200, first.data
        assert [row["id"] for row in first.data["results"]] == [
            message.id for message in messages[:200]
        ]
        assert first.data["has_more"] is True

        second = _client(self.sender).get(
            self.url,
            {"after_id": str(first.data["latest_id"]), "page_size": 200},
        )
        assert [row["id"] for row in second.data["results"]] == [
            message.id for message in messages[200:]
        ]
        assert second.data["has_more"] is False

    def test_equal_timestamps_still_follow_id_order(self):
        messages = self._messages(2)
        same_time = timezone.now() - timedelta(minutes=1)
        ChatMessage.objects.filter(id__in=[message.id for message in messages]).update(
            created_at=same_time
        )

        response = _client(self.sender).get(
            self.url, {"latest": "1", "page_size": 1}
        )
        assert response.status_code == 200, response.data
        assert response.data["results"][0]["id"] == messages[-1].id

        response = _client(self.sender).get(
            self.url, {"before_id": str(messages[-1].id), "page_size": 1}
        )
        assert response.data["results"][0]["id"] == messages[0].id

    def test_read_acknowledges_only_returned_counterparty_messages(self):
        messages = self._messages(4)
        response = _client(self.sender).get(
            self.url, {"after_id": "0", "page_size": 2}
        )
        assert response.status_code == 200, response.data

        for message in messages:
            message.refresh_from_db()
        assert messages[0].read_at is None  # sender's own message
        assert messages[1].read_at is not None  # returned counterparty message
        assert messages[2].read_at is None  # not returned yet
        assert messages[3].read_at is None  # not returned yet

    def test_closed_funded_history_remains_readable(self):
        self.match.status = Match.Status.CANCELLED
        self.match.save(update_fields=["status"])
        message = ChatMessage.objects.create(
            match=self.match, sender=self.traveler, body="history"
        )

        response = _client(self.sender).get(self.url, {"latest": "1"})
        assert response.status_code == 200, response.data
        assert response.data["results"][0]["id"] == message.id

    def test_nonparty_and_invalid_cursor_requests_are_rejected(self):
        intruder = _user("live-history-intruder@example.com", "3")
        assert _client(intruder).get(self.url, {"latest": "1"}).status_code == 403

        invalid_requests = (
            {"latest": "0"},
            {"latest": "1", "after_id": "0"},
            {"after_id": "-1"},
            {"before_id": "0"},
            {"after_id": "not-an-id"},
            {"after_id": "9999999999999999999"},
            {"after_id": "9" * 5000},
            {"latest": "1", "page": "2"},
            {"latest": "1", "page_size": "0"},
            {"latest": "1", "page_size": "201"},
            {"latest": "1", "page_size": "not-a-number"},
        )
        for query in invalid_requests:
            with self.subTest(query=query):
                assert _client(self.sender).get(self.url, query).status_code == 400


class ChatCommitOrderingTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_sends_cannot_commit_past_an_uncommitted_cursor(self):
        for code in ("ALG", "CDG"):
            Airport.objects.get_or_create(
                iata=code, defaults={"city": code, "name": code, "country": "DZ"},
            )
        sender = _user("commit-sender@example.com", "4")
        traveler = _user("commit-traveler@example.com", "5")
        match = _make_match(sender, traveler)
        _pay(_accepted_offer(match, traveler), sender)
        url = f"/api/matches/{match.pk}/chat/messages"
        original = ChatMessage.objects.create
        first_inserted, second_started, second_inserted, release = (
            Event(), Event(), Event(), Event()
        )

        def insert(**kwargs):
            row = original(**kwargs)
            if kwargs["body"] == "first":
                first_inserted.set()
                assert release.wait(10), "test failed to release first writer"
            else:
                second_inserted.set()
            return row

        def send(user, body):
            close_old_connections()
            try:
                if body == "second":
                    second_started.set()
                response = _client(user).post(url, {"body": body}, format="json")
                assert response.status_code == 201, response.data
                return response.data["id"]
            finally:
                close_old_connections()

        with patch("apps.chat.views.ChatMessage.objects.create", side_effect=insert), \
                patch("apps.core.redis_bus.get_client"), ThreadPoolExecutor(2) as pool:
            first = pool.submit(send, sender, "first")
            try:
                assert first_inserted.wait(5)
                second = pool.submit(send, traveler, "second")
                assert second_started.wait(5)
                assert not second_inserted.wait(0.3), "second ID allocated before first commit"
                latest = _client(sender).get(url, {"latest": "1"})
                assert latest.data["results"] == []
            finally:
                release.set()
            first_id, second_id = first.result(timeout=10), second.result(timeout=10)
        assert first_id < second_id
        delta = _client(sender).get(url, {"after_id": first_id})
        assert [row["id"] for row in delta.data["results"]] == [second_id]
