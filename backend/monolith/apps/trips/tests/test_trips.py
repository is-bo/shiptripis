from datetime import timedelta
from unittest import skip
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.trips.models import Trip


def _future(days: int = 7) -> str:
    return (timezone.now() + timedelta(days=days)).isoformat()


def _make_user(email: str = "trav@example.com", role: str = "traveler") -> User:
    user = User.objects.create_user(
        username=email,
        email=email,
        password="Sup3rStrongPass!",
        full_name="Trav Eler",
        phone="+213555000111",
        wilaya="16",
    )
    user.role = role
    user.save(update_fields=["role"])
    return user


def _auth_client(user: User) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


class AirportListTests(APITestCase):
    def test_lists_seeded_airports(self):
        # Migration 0002 seeds 18 airports.
        r = self.client.get(reverse("airports-list"))
        assert r.status_code == 200
        assert len(r.data) >= 18
        codes = {a["iata"] for a in r.data}
        assert {"ALG", "CDG", "MRS"}.issubset(codes)

    def test_filter_by_country(self):
        r = self.client.get(reverse("airports-list"), {"country": "DZ"})
        assert r.status_code == 200
        assert all(a["country"] == "DZ" for a in r.data)
        assert any(a["iata"] == "ALG" for a in r.data)


@skip("Legacy airport-pair Trip creation is retired in favor of V1 Journeys.")
class TripCreateTests(APITestCase):
    def setUp(self):
        self.user = _make_user()
        self.client = _auth_client(self.user)

    def _payload(self, **overrides) -> dict:
        base = {
            "origin": "ALG",
            "destination": "CDG",
            "departure_at": _future(7),
            "capacity_kg": 8,
            "flight_number": "AH1006",
            "notes": "Hand luggage only",
        }
        base.update(overrides)
        return base

    def test_unauthenticated_rejected(self):
        c = APIClient()
        r = c.post(reverse("trips-list-create"), self._payload(), format="json")
        assert r.status_code == 401

    @patch("apps.core.redis_bus.publish_after_commit")
    def test_creates_trip_and_publishes(self, pub):
        r = self.client.post(reverse("trips-list-create"), self._payload(), format="json")
        assert r.status_code == 201, r.data
        assert r.data["origin"]["iata"] == "ALG"
        assert r.data["destination"]["iata"] == "CDG"
        assert r.data["status"] == Trip.Status.ACTIVE
        assert r.data["capacity_kg"] == 8
        assert Trip.objects.count() == 1
        pub.assert_called_once()
        channel, payload = pub.call_args.args
        assert channel == "trip.created"
        assert payload["traveler_id"] == self.user.id

    def test_rejects_same_origin_destination(self):
        r = self.client.post(
            reverse("trips-list-create"),
            self._payload(destination="ALG"),
            format="json",
        )
        assert r.status_code == 400
        assert "destination" in r.data

    def test_rejects_past_departure(self):
        past = (timezone.now() - timedelta(days=1)).isoformat()
        r = self.client.post(
            reverse("trips-list-create"),
            self._payload(departure_at=past),
            format="json",
        )
        assert r.status_code == 400
        assert "departure_at" in r.data

    def test_rejects_unknown_iata(self):
        r = self.client.post(
            reverse("trips-list-create"),
            self._payload(origin="ZZZ"),
            format="json",
        )
        assert r.status_code == 400

    @patch("apps.core.redis_bus.publish_after_commit")
    def test_with_stopovers(self, _pub):
        r = self.client.post(
            reverse("trips-list-create"),
            self._payload(
                stopovers=[
                    {"airport": "MRS", "arrives_at": _future(7), "departs_at": _future(8)},
                ]
            ),
            format="json",
        )
        assert r.status_code == 201, r.data
        assert len(r.data["stopovers"]) == 1
        assert r.data["stopovers"][0]["airport"]["iata"] == "MRS"
        assert r.data["stopovers"][0]["position"] == 0


class TripListTests(APITestCase):
    def setUp(self):
        self.user = _make_user()
        self.other = _make_user(email="someone@example.com")
        self.client = _auth_client(self.user)

    def _make_trip(self, owner: User, status_value: str = "active") -> Trip:
        t = Trip.objects.create(
            traveler=owner,
            origin_id="ALG",
            destination_id="CDG",
            departure_at=timezone.now() + timedelta(days=10),
            capacity_kg=5,
            status=status_value,
        )
        return t

    def test_lists_only_my_trips(self):
        self._make_trip(self.user)
        self._make_trip(self.user)
        self._make_trip(self.other)
        r = self.client.get(reverse("trips-list-create"))
        assert r.status_code == 200
        assert len(r.data) == 2

    def test_filter_by_status(self):
        self._make_trip(self.user, "active")
        self._make_trip(self.user, "cancelled")
        r = self.client.get(reverse("trips-list-create"), {"status": "active"})
        assert r.status_code == 200
        assert len(r.data) == 1
        assert r.data[0]["status"] == "active"


class TripCancelTests(APITestCase):
    def setUp(self):
        self.user = _make_user()
        self.other = _make_user(email="someone@example.com")
        self.trip = Trip.objects.create(
            traveler=self.user,
            origin_id="ALG",
            destination_id="CDG",
            departure_at=timezone.now() + timedelta(days=5),
            capacity_kg=10,
        )
        self.client = _auth_client(self.user)

    @patch("apps.core.redis_bus.publish_after_commit")
    def test_legacy_cancel_is_retired_without_mutation(self, pub):
        r = self.client.post(reverse("trips-cancel", kwargs={"pk": self.trip.id}))
        assert r.status_code == 410
        self.trip.refresh_from_db()
        assert self.trip.status == Trip.Status.ACTIVE
        pub.assert_not_called()

    def test_non_owner_rejected(self):
        c = _auth_client(self.other)
        r = c.post(reverse("trips-cancel", kwargs={"pk": self.trip.id}))
        assert r.status_code == 410

    def test_already_cancelled_returns_409(self):
        self.trip.status = Trip.Status.CANCELLED
        self.trip.save(update_fields=["status"])
        r = self.client.post(reverse("trips-cancel", kwargs={"pk": self.trip.id}))
        assert r.status_code == 410


class TripDetailTests(APITestCase):
    def setUp(self):
        self.user = _make_user()
        self.client = _auth_client(self.user)
        self.trip = Trip.objects.create(
            traveler=self.user,
            origin_id="ALG",
            destination_id="ORN",
            departure_at=timezone.now() + timedelta(days=3),
            capacity_kg=12,
        )

    def test_retrieve(self):
        r = self.client.get(reverse("trips-detail", kwargs={"pk": self.trip.id}))
        assert r.status_code == 200
        assert r.data["id"] == self.trip.id
        assert r.data["origin"]["iata"] == "ALG"

    def test_non_owner_cannot_retrieve_legacy_trip(self):
        other = _make_user("legacy-trip-outsider@example.com")
        response = _auth_client(other).get(
            reverse("trips-detail", kwargs={"pk": self.trip.id})
        )
        assert response.status_code == 403

    def test_404_for_unknown(self):
        r = self.client.get(reverse("trips-detail", kwargs={"pk": 999_999}))
        assert r.status_code == 404


@skip("Legacy Trip discovery is retired in favor of V1 Journey search.")
class TripSearchTests(APITestCase):
    def setUp(self):
        self.traveler = _make_user("trav1@example.com")
        self.other_traveler = _make_user("trav2@example.com")
        self.sender = _make_user("send@example.com", role="sender")

        self.t_active = Trip.objects.create(
            traveler=self.other_traveler,
            origin_id="ALG",
            destination_id="CDG",
            departure_at=timezone.now() + timedelta(days=5),
            capacity_kg=10,
        )
        self.t_cancelled = Trip.objects.create(
            traveler=self.other_traveler,
            origin_id="ALG",
            destination_id="CDG",
            departure_at=timezone.now() + timedelta(days=4),
            capacity_kg=10,
            status=Trip.Status.CANCELLED,
        )
        self.t_own = Trip.objects.create(
            traveler=self.sender,
            origin_id="ALG",
            destination_id="CDG",
            departure_at=timezone.now() + timedelta(days=6),
            capacity_kg=10,
        )

    def test_returns_only_active_excluding_caller(self):
        c = _auth_client(self.sender)
        r = c.get(reverse("trips-search") + "?origin=ALG&destination=CDG")
        assert r.status_code == 200
        ids = {row["id"] for row in r.data}
        assert ids == {self.t_active.id}

    def test_filters_by_capacity(self):
        c = _auth_client(self.sender)
        r = c.get(
            reverse("trips-search")
            + "?origin=ALG&destination=CDG&min_capacity_kg=20"
        )
        assert r.status_code == 200
        assert r.data == []

    def test_requires_auth(self):
        c = APIClient()
        r = c.get(reverse("trips-search"))
        assert r.status_code in (401, 403)

    def test_trip_search_includes_traveler_name(self):
        self.other_traveler.full_name = "Yacine Bensalah"
        self.other_traveler.save(update_fields=["full_name"])
        c = _auth_client(self.sender)
        r = c.get(reverse("trips-search"))
        assert r.status_code == 200
        assert isinstance(r.data, list)
        assert any(t["traveler_name"] == "Yacine Bensalah" for t in r.data)
