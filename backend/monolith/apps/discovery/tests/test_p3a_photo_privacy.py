"""P3A, spec 21: the photo privacy walk.

Everyone who sees a person's first name sees their active photo, guests
included: trip and request cards, people and the person page, the own profile
preview, route alerts, Find Travelers, "Matches for you" and proposals. The
block is ``{"url", "version"}``: a fresh signed URL on a random key that never
names the person. A photo Wassla removed is absent everywhere, except in the
owner's own `GET /api/me`, which says so and gives the reason. The photo adds
nothing else: the L2A walk (no surname, contact, address, forbidden key) still
holds with photos present.
"""

from __future__ import annotations

import json
from urllib.parse import urlparse

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import ProfilePhoto
from apps.core.storage import make_key, storage_for

from .support import DiscoveryWorld, client_for
from .test_privacy import FORBIDDEN_KEYS, _keys

REMOVAL_REASON = "P3A-REMOVAL-REASON shown to the member only"


def photo_blocks(value, found: list) -> list:
    """Every ``photo``, ``sender_photo`` and ``traveler_photo`` value, at any depth."""

    if isinstance(value, dict):
        for key, inner in value.items():
            if key in ("photo", "sender_photo", "traveler_photo"):
                found.append(inner)
            else:
                photo_blocks(inner, found)
    elif isinstance(value, list):
        for inner in value:
            photo_blocks(inner, found)
    return found


class PhotoPrivacyWalkTests(DiscoveryWorld, TestCase):
    def setUp(self):
        self.build_discovery_world()
        self.opt_in(self.sender, (self.paris, self.jijel))
        self.opt_in(self.traveler, (self.algiers, self.jijel))
        self.photos = {user.pk: self.give_photo(user) for user in (self.sender, self.traveler)}
        self.proposal = self.propose()
        # The sender follows the traveler, so an alert names them.
        response = client_for(self.sender).post(
            reverse("discovery-alerts"),
            {
                "watches": "trips",
                "origin_place_id": self.cdg.pk,
                "destination_place_id": self.jijel.pk,
                "subject_profile_id": str(self.traveler.public_profile.public_id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

    def give_photo(self, user) -> ProfilePhoto:
        return ProfilePhoto.objects.create(
            user=user,
            bucket=storage_for("media").require_bucket(),
            object_key=make_key("profile-photos", "jpg"),
            bytes=1234,
            version=f"v-{user.pk}-p3a",
            uploaded_at=timezone.now(),
        )

    def get(self, viewer, name, *args, **query):
        # A fresh row per request, as a real request loads it: the fixture's
        # instances remember the photo they were given.
        client = (
            APIClient() if viewer is None else client_for(type(viewer).objects.get(pk=viewer.pk))
        )
        response = client.get(reverse(name, args=args), query)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    # -- the surfaces --------------------------------------------------------

    def public_payloads(self, viewer):
        """Every public read, for a member (``viewer``) or a guest (None)."""

        traveler_card = str(self.traveler.public_profile.public_id)
        sender_card = str(self.sender.public_profile.public_id)
        yield "trips", self.get(viewer, "discovery-trips")
        yield "requests", self.get(viewer, "discovery-requests")
        yield "travelers", self.get(viewer, "discovery-people", role="sender")
        yield "senders", self.get(viewer, "discovery-people", role="traveler")
        yield "traveler page", self.get(viewer, "discovery-person", traveler_card)
        yield "sender page", self.get(viewer, "discovery-person", sender_card)

    def member_payloads(self):
        """The member surfaces that name a person, read by the people they are for."""

        yield "sender's alerts", self.get(self.sender, "discovery-alerts")
        yield "find travelers", self.get(
            self.sender, "matches-find-travelers-v1", parcel_id=self.request.pk
        )
        yield "matches for you", self.get(self.sender, "discovery-matches", role="sender")
        match_id = self.proposal.match_id
        for party in (self.sender, self.traveler):
            yield f"proposal for {party.pk}", self.get(party, "matches-detail", match_id)
            yield f"proposals for {party.pk}", self.get(party, "matches-list")

    def own_previews(self):
        for user in (self.sender, self.traveler):
            yield f"own preview {user.pk}", self.get(user, "discovery-profile-me")

    def all_payloads(self):
        for viewer, label in ((self.other, "member"), (None, "guest")):
            for name, payload in self.public_payloads(viewer):
                yield f"{label} {name}", payload
        yield from self.member_payloads()
        yield from self.own_previews()

    # -- assertions ----------------------------------------------------------

    def assertPhotoOf(self, block, user):
        photo = self.photos[user.pk]
        self.assertEqual(set(block), {"url", "version"})
        self.assertEqual(block["version"], photo.version)
        path = urlparse(block["url"]).path
        self.assertTrue(path.endswith("/" + photo.object_key), path)
        # The key is `profile-photos/<random>.jpg`: no segment names the person.
        self.assertNotIn(str(user.pk), path.split("/"))
        self.assertNotIn(user.email, block["url"])

    def test_everyone_sees_each_active_photo_with_a_url_that_names_nobody(self):
        for viewer, label in ((self.other, "member"), (None, "guest")):
            with self.subTest(viewer=label):
                trips = self.get(viewer, "discovery-trips")
                self.assertPhotoOf(trips["results"][0]["traveler"]["photo"], self.traveler)
                requests = self.get(viewer, "discovery-requests")
                self.assertPhotoOf(requests["results"][0]["sender"]["photo"], self.sender)
                travelers = self.get(viewer, "discovery-people", role="sender")
                self.assertPhotoOf(travelers["results"][0]["photo"], self.traveler)
                page = self.get(
                    viewer, "discovery-person", self.sender.public_profile.public_id
                )
                self.assertPhotoOf(page["profile"]["photo"], self.sender)
                self.assertPhotoOf(page["requests"][0]["sender"]["photo"], self.sender)
        alerts = self.get(self.sender, "discovery-alerts")
        self.assertPhotoOf(alerts["results"][0]["subject"]["photo"], self.traveler)
        found = self.get(self.sender, "matches-find-travelers-v1", parcel_id=self.request.pk)
        self.assertPhotoOf(found["results"][0]["traveler"]["photo"], self.traveler)
        self.assertNotIn("avatar_url", json.dumps(found))
        matches = self.get(self.sender, "discovery-matches", role="sender")
        self.assertPhotoOf(matches["groups"][0]["results"][0]["traveler"]["photo"], self.traveler)
        for party in (self.sender, self.traveler):
            proposal = self.get(party, "matches-detail", self.proposal.match_id)
            self.assertPhotoOf(proposal["sender_photo"], self.sender)
            self.assertPhotoOf(proposal["traveler_photo"], self.traveler)
        own = self.get(self.traveler, "discovery-profile-me")
        self.assertPhotoOf(own["card"]["photo"], self.traveler)

    def test_a_photo_adds_nothing_private_to_a_public_payload(self):
        for viewer, label in ((self.other, "member"), (None, "guest")):
            for name, payload in self.public_payloads(viewer):
                with self.subTest(f"{label} {name}"):
                    text = json.dumps(payload, default=str)
                    self.assertIn("profile-photos/", text)
                    self.assertEqual(_keys(payload, set()) & FORBIDDEN_KEYS, set())
                    for user in (self.sender, self.traveler):
                        self.assertNotIn(user.email, text)
                        self.assertNotIn(user.full_name.split()[-1], text)

    def test_a_removed_photo_is_gone_everywhere_but_the_owners_own_view(self):
        ProfilePhoto.objects.filter(user=self.traveler).update(
            state=ProfilePhoto.State.REMOVED,
            bucket="",
            object_key="",
            removed_at=timezone.now(),
            removed_reason=REMOVAL_REASON,
        )
        removed_version = self.photos[self.traveler.pk].version
        sender_version = self.photos[self.sender.pk].version
        for name, payload in self.all_payloads():
            with self.subTest(name):
                text = json.dumps(payload, default=str)
                self.assertNotIn(removed_version, text)
                self.assertNotIn(REMOVAL_REASON, text)
                versions = {
                    block["version"] for block in photo_blocks(payload, []) if block
                }
                self.assertLessEqual(versions, {sender_version})
        own = self.get(self.traveler, "me")["photo"]
        self.assertEqual(own["state"], "removed")
        self.assertIsNone(own["url"])
        self.assertEqual(own["reason"], REMOVAL_REASON)
        self.assertEqual(own["version"], removed_version)
        # The sender still has theirs, and their own view says it is active.
        self.assertEqual(self.get(self.sender, "me")["photo"]["state"], "active")

    def test_no_photo_is_null(self):
        ProfilePhoto.objects.all().delete()
        for name, payload in self.all_payloads():
            with self.subTest(name):
                blocks = photo_blocks(payload, [])
                self.assertTrue(blocks, "the payload names nobody")
                self.assertEqual(set(map(json.dumps, blocks)), {"null"})
        self.assertIsNone(self.get(self.traveler, "me")["photo"])
