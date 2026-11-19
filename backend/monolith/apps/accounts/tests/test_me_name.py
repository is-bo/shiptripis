"""`PATCH /api/me` sets a blank name once (plan EGS review).

A Google or Apple account can arrive without a name. The person adds it in
Profile, once: after that the name is fixed, as a typed sign-up name is. The
stored row decides, never the request's copy of the account, so two
concurrent requests cannot both set it.
"""

from __future__ import annotations

import threading
from unittest.mock import patch

from django.db import connection
from django.test import TransactionTestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User

URL = reverse("me")
ALREADY_SET = {"code": "name_already_set", "detail": "Your name is already set."}


def make_member(name: str = "", email: str = "social.member@example.com") -> User:
    return User.objects.create_user(
        username=email,
        email=email,
        password="Sup3rStrongPass!",
        full_name=name,
        phone="+33600000001",
        is_email_verified=True,
    )


def client_for(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class SetNameOnceTests(APITestCase):
    def stored_name(self, user):
        return User.objects.values_list("full_name", flat=True).get(pk=user.pk)

    def test_a_blank_name_is_set_once(self):
        member = make_member()
        response = client_for(member).patch(
            URL, {"full_name": "  Amina Benali  "}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["full_name"], "Amina Benali")
        self.assertEqual(self.stored_name(member), "Amina Benali")

        again = client_for(User.objects.get(pk=member.pk)).patch(
            URL, {"full_name": "Someone Else"}, format="json"
        )
        self.assertEqual(again.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(again.data, ALREADY_SET)
        self.assertEqual(self.stored_name(member), "Amina Benali")

    def test_a_whitespace_only_stored_name_counts_as_blank(self):
        member = make_member(name="   ")
        response = client_for(member).patch(URL, {"full_name": "A"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(self.stored_name(member), "A")

    def test_a_typed_name_cannot_be_changed_and_nothing_else_in_the_request_applies(
        self,
    ):
        member = make_member(name="Typed At Sign Up")
        response = client_for(member).patch(
            URL, {"full_name": "New Name", "preferred_language": "ar"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data, ALREADY_SET)
        member.refresh_from_db()
        self.assertEqual(
            (member.full_name, member.preferred_language), ("Typed At Sign Up", "")
        )

    def test_the_name_is_validated_before_anything_is_written(self):
        member = make_member()
        for value in ("", "   ", "N" * 121, None):
            with self.subTest(value=value):
                response = client_for(member).patch(
                    URL, {"full_name": value}, format="json"
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn("full_name", response.data)
                self.assertEqual(self.stored_name(member), "")
        longest = client_for(member).patch(URL, {"full_name": "N" * 120}, format="json")
        self.assertEqual(longest.status_code, status.HTTP_200_OK, longest.data)

    def test_the_stored_row_decides_not_the_requests_copy(self):
        member = make_member()
        stale = User.objects.get(pk=member.pk)
        User.objects.filter(pk=member.pk).update(full_name="Set Elsewhere")
        response = client_for(stale).patch(
            URL, {"full_name": "Too Late"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data, ALREADY_SET)
        self.assertEqual(self.stored_name(member), "Set Elsewhere")

    def test_a_language_change_from_a_stale_copy_keeps_a_name_set_meanwhile(self):
        member = make_member()
        stale = User.objects.get(pk=member.pk)
        User.objects.filter(pk=member.pk).update(full_name="Set Elsewhere")
        response = client_for(stale).patch(
            URL, {"preferred_language": "fr"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        member.refresh_from_db()
        self.assertEqual(
            (member.full_name, member.preferred_language), ("Set Elsewhere", "fr")
        )

    def test_name_and_language_change_together_while_the_name_is_blank(self):
        member = make_member()
        response = client_for(member).patch(
            URL,
            {"full_name": "Amina Benali", "preferred_language": "ar"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        member.refresh_from_db()
        self.assertEqual(
            (member.full_name, member.preferred_language), ("Amina Benali", "ar")
        )

    def test_every_other_profile_field_stays_read_only(self):
        member = make_member()
        response = client_for(member).patch(
            URL,
            {
                "full_name": "Amina Benali",
                "email": "changed@example.com",
                "phone": "+213555000999",
                "role": "admin",
                "is_kyc_verified": True,
                "is_email_verified": False,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        member.refresh_from_db()
        self.assertEqual(
            (
                member.email,
                member.phone,
                member.role,
                member.is_kyc_verified,
                member.is_email_verified,
            ),
            ("social.member@example.com", "+33600000001", User.Role.BOTH, False, True),
        )

    def test_a_guest_cannot_set_a_name(self):
        response = APIClient().patch(URL, {"full_name": "Amina"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class ConcurrentSetNameTests(TransactionTestCase):
    """Two requests that both read a blank name: exactly one sets it."""

    def test_two_concurrent_requests_cannot_both_set_the_name(self):
        member = make_member()
        barrier = threading.Barrier(2, timeout=10)
        real = User.fill_blank_name

        def fill_together(user, name):
            # Both requests have validated and hold a blank copy before
            # either writes.
            barrier.wait()
            return real(user, name)

        answers, failures = {}, []

        def run(name):
            try:
                client = client_for(User.objects.get(pk=member.pk))
                answers[name] = client.patch(URL, {"full_name": name}, format="json")
            except Exception as exc:  # pragma: no cover - reported below
                failures.append(exc)
            finally:
                connection.close()

        with patch.object(User, "fill_blank_name", fill_together):
            threads = [
                threading.Thread(target=run, args=(name,))
                for name in ("First", "Second")
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual(failures, [])
        codes = sorted(response.status_code for response in answers.values())
        self.assertEqual(codes, [200, 400])
        winner = next(
            name for name, response in answers.items() if response.status_code == 200
        )
        loser = next(
            response for response in answers.values() if response.status_code == 400
        )
        self.assertEqual(loser.data, ALREADY_SET)
        member.refresh_from_db()
        self.assertEqual(member.full_name, winner)
