"""P3C, spec 21.2: the other person's photo on the chat list and the chat header.

`GET /api/chat/threads` rows carry `counterparty_photo`: `{"url", "version"}`
or null, from `apps.accounts.photos.public_photo`. Message payloads, and the
`chat.message.new` event, stay as they were, so no signed URL ever enters Redis
or `PublishedEvent`.
"""

from __future__ import annotations

from unittest.mock import patch
from urllib.parse import urlparse

from django.db import connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts import deletion, photos
from apps.accounts.models import ProfilePhoto, UserBlock
from apps.chat.models import ChatMessage
from apps.core.storage import make_key, storage_for

from apps.deals.models import Deal
from apps.deals.tests.phase4_factories import enable_mock_rail
from apps.matching.tests.test_phase8dr_offer_locks import CanonicalOfferFixture
from apps.matching.tests.test_v1_matching import _approve_kyc
from apps.matching.tests.test_v1_matching import _user as _v1_user
from apps.matching.v1_services import accept_offer

from .test_chat import _accepted_offer, _client, _make_match, _pay, _user

#: The keys of a thread row before P3C.
ROW_KEYS = {
    "match_id",
    "deal_id",
    "counterparty_id",
    "counterparty_name",
    "route",
    "status",
    "can_send",
    "last_message",
    "last_message_removed",
    "counterparty_deleted",
    "blocked_by_me",
    "last_message_at",
    "unread_count",
}

#: The keys of a message, and of the `chat.message.new` event, before P3C.
MESSAGE_KEYS = {
    "id",
    "match_id",
    "sender_id",
    "body",
    "removed",
    "client_message_id",
    "created_at",
    "read_at",
}
EVENT_KEYS = {
    "message_id",
    "match_id",
    "sender_id",
    "body",
    "created_at",
    "client_message_id",
}


def give_photo(user) -> ProfilePhoto:
    return ProfilePhoto.objects.create(
        user=user,
        bucket=storage_for("media").require_bucket(),
        object_key=make_key("profile-photos", "jpg"),
        bytes=1234,
        version=f"v-{user.pk}-p3c",
        uploaded_at=timezone.now(),
    )


class ChatPhotoTests(TestCase):
    def setUp(self):
        self.sender = _user("p3c-sender@example.com", "1")
        self.traveler = _user("p3c-traveler@example.com", "2")
        self.match = _make_match(self.sender, self.traveler)
        _pay(_accepted_offer(self.match, self.traveler), self.sender)

    def row(self, viewer) -> dict:
        # A fresh request loads the people and their photo rows afresh.
        response = _client(type(viewer).objects.get(pk=viewer.pk)).get(
            reverse("chat-threads")
        )
        self.assertEqual(response.status_code, 200, response.data)
        return next(r for r in response.data["results"] if r["match_id"] == self.match.pk)

    def assertPhotoOf(self, block, user, photo):
        self.assertEqual(set(block), {"url", "version"})
        self.assertEqual(block["version"], photo.version)
        path = urlparse(block["url"]).path
        self.assertTrue(path.endswith("/" + photo.object_key), path)
        self.assertNotIn(str(user.pk), path.split("/"))
        self.assertNotIn(user.email, block["url"])

    # -- who sees whose ------------------------------------------------------

    def test_each_party_sees_the_other_partys_photo_and_never_their_own(self):
        sender_photo = give_photo(self.sender)
        traveler_photo = give_photo(self.traveler)

        self.assertPhotoOf(
            self.row(self.sender)["counterparty_photo"], self.traveler, traveler_photo
        )
        self.assertPhotoOf(
            self.row(self.traveler)["counterparty_photo"], self.sender, sender_photo
        )

    def test_nobody_gets_their_own_photo_when_the_other_has_none(self):
        give_photo(self.sender)
        self.assertIsNone(self.row(self.sender)["counterparty_photo"])
        self.assertIsNotNone(self.row(self.traveler)["counterparty_photo"])

    def test_the_row_adds_only_the_photo_block_to_its_keys(self):
        give_photo(self.traveler)
        self.assertEqual(set(self.row(self.sender)), ROW_KEYS | {"counterparty_photo"})

    # -- null cases ----------------------------------------------------------

    def test_null_without_a_photo(self):
        self.assertIsNone(self.row(self.sender)["counterparty_photo"])

    def test_null_once_staff_removed_it(self):
        photo = give_photo(self.traveler)
        staff = _user("p3c-staff@example.com", "3")
        photos.remove_by_staff(
            user=self.traveler, actor=staff, version=photo.version, reason="Not a face"
        )
        self.assertIsNone(self.row(self.sender)["counterparty_photo"])

    def test_null_for_a_banned_account(self):
        give_photo(self.traveler)
        self.traveler.is_banned = True
        self.traveler.save(update_fields=["is_banned"])
        self.assertIsNone(self.row(self.sender)["counterparty_photo"])

    def test_null_for_a_deactivated_account(self):
        give_photo(self.traveler)
        self.traveler.is_active = False
        self.traveler.save(update_fields=["is_active"])
        self.assertIsNone(self.row(self.sender)["counterparty_photo"])

    def test_null_for_a_deleted_account_whose_thread_is_still_listed(self):
        give_photo(self.traveler)
        with transaction.atomic():
            deletion._erase(self.traveler)
        row = self.row(self.sender)
        self.assertTrue(row["counterparty_deleted"])
        self.assertIsNone(row["counterparty_photo"])
        self.assertFalse(ProfilePhoto.objects.filter(user=self.traveler).exists())

    # -- blocked threads -----------------------------------------------------

    def test_a_thread_blocked_from_either_side_still_shows_the_photo(self):
        sender_photo = give_photo(self.sender)
        traveler_photo = give_photo(self.traveler)
        for blocker, blocked in (
            (self.sender, self.traveler),
            (self.traveler, self.sender),
        ):
            UserBlock.objects.all().delete()
            UserBlock.objects.create(blocker=blocker, blocked=blocked)
            sender_row = self.row(self.sender)
            traveler_row = self.row(self.traveler)
            self.assertFalse(sender_row["can_send"])
            self.assertFalse(traveler_row["can_send"])
            self.assertPhotoOf(sender_row["counterparty_photo"], self.traveler, traveler_photo)
            self.assertPhotoOf(traveler_row["counterparty_photo"], self.sender, sender_photo)

    def test_the_blocked_people_list_gets_no_photo(self):
        give_photo(self.traveler)
        UserBlock.objects.create(blocker=self.sender, blocked=self.traveler)
        rows = _client(self.sender).get(reverse("my-blocks")).data["results"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(set(rows[0]), {"user_id", "name", "deleted", "blocked_at"})

    # -- messages and the published event stay as they were ------------------

    def test_message_payloads_and_the_published_event_carry_no_photo(self):
        give_photo(self.sender)
        give_photo(self.traveler)
        with patch("apps.chat.views.redis_bus.publish_after_commit") as pub:
            sent = _client(self.sender).post(
                reverse("chat-messages", args=[self.match.pk]),
                {"body": "on my way"},
                format="json",
            )
        self.assertEqual(sent.status_code, 201, sent.data)
        self.assertEqual(set(sent.data), MESSAGE_KEYS)
        args, kwargs = pub.call_args
        self.assertEqual(args[0], "chat.message.new")
        self.assertEqual(set(args[1]), EVENT_KEYS)
        self.assertEqual(set(kwargs), {"targets"})
        history = _client(self.traveler).get(reverse("chat-messages", args=[self.match.pk]))
        self.assertEqual(history.status_code, 200, history.data)
        self.assertEqual(len(history.data["results"]), 1)
        for message in history.data["results"]:
            self.assertEqual(set(message), MESSAGE_KEYS)


class ChatPhotoQueryCountTests(CanonicalOfferFixture, TestCase):
    """The inbox costs the same queries for one thread as for five, every
    counterparty having an active photo: the photo row is joined, not read per
    thread. Both directions: the sender's inbox joins the travelers' photos,
    the traveler's inbox the senders'."""

    def setUp(self):
        enable_mock_rail()
        self.build_world()

    def add_funded_thread(self, *, sender, traveler, index: int) -> None:
        journey, flight, drive = self._journey(traveler, origin=self.cdg)
        # `_request` names `self.sender` as the request's sender.
        fixture_sender, self.sender = self.sender, sender
        try:
            delivery_request = self._request(
                self.paris, self.jijel, title=f"P3C thread {index}"
            )
        finally:
            self.sender = fixture_sender
        offer = self.propose(
            sender=sender,
            delivery_request=delivery_request,
            journey=journey,
            start_leg_id=flight.pk,
            end_leg_id=drive.pk,
        )
        deal = accept_offer(pending_offer=offer, actor=traveler).deal
        Deal.objects.filter(pk=deal.pk).update(
            status=Deal.Status.FUNDED, funded_at=timezone.now()
        )
        ChatMessage.objects.create(
            match=deal.match, sender=traveler, body=f"hello {index}"
        )

    def new_member(self, role: str, index: int):
        member = _v1_user(f"p3c-flat-{role}-{index}@example.com")
        _approve_kyc(member, f"p3c-flat-{role}-{index}")
        give_photo(member)
        return member

    def inbox(self, viewer) -> tuple[int, int]:
        client = _client(viewer)
        self.assertEqual(client.get(reverse("chat-threads")).status_code, 200)
        with CaptureQueriesContext(connection) as captured:
            response = client.get(reverse("chat-threads"))
        self.assertEqual(response.status_code, 200)
        with_photo = sum(1 for r in response.data["results"] if r["counterparty_photo"])
        return len(captured.captured_queries), with_photo

    def test_the_senders_inbox_query_count_is_flat_from_one_thread_to_five(self):
        """One sender, five different travelers."""

        for index in range(5):
            traveler = self.new_member("traveler", index)
            self.add_funded_thread(sender=self.sender, traveler=traveler, index=index)
            if index == 0:
                one, one_with_photo = self.inbox(self.sender)
        five, five_with_photo = self.inbox(self.sender)

        self.assertEqual((one_with_photo, five_with_photo), (1, 5))
        self.assertEqual(five, one)

    def test_the_travelers_inbox_query_count_is_flat_from_one_thread_to_five(self):
        """One traveler, five different senders."""

        for index in range(5):
            sender = self.new_member("sender", index)
            self.add_funded_thread(sender=sender, traveler=self.traveler, index=index)
            if index == 0:
                one, one_with_photo = self.inbox(self.traveler)
        five, five_with_photo = self.inbox(self.traveler)

        self.assertEqual((one_with_photo, five_with_photo), (1, 5))
        self.assertEqual(five, one)
