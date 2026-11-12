"""J9.3: Journey inventory must begin strictly after authoritative server time."""

from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.kyc.models import KycSubmission
from apps.locations.models import Country, Place
from apps.trips.constraints import MAX_JOURNEY_LEG_CAPACITY_KG
from apps.trips.models import Journey, JourneyLeg


class JourneyDepartureIntegrityTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="j93-journey@example.test",
            email="j93-journey@example.test",
            password="Strong-pass-123!",
            full_name="J9.3 Traveler",
            role=User.Role.BOTH,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        country = Country.objects.create(
            code="DZ",
            name="Algeria",
            source="j93-test",
            source_id="country-dz",
            source_version="j93",
        )

        def place(name, source_id):
            return Place.objects.create(
                country=country,
                place_type=Place.PlaceType.LOCALITY,
                source="j93-test",
                source_id=source_id,
                source_version="j93",
                name=name,
            )

        self.jijel = place("Jijel", "locality-jijel")
        self.algiers = place("Algiers", "locality-algiers")
        self.oran = place("Oran", "locality-oran")
        self.now = datetime(2030, 5, 1, 12, 0, tzinfo=dt_timezone.utc)

    def _leg(
        self, origin, destination, depart, arrive, *, position=0, capacity="10.00"
    ):
        return {
            "position": position,
            "mode": JourneyLeg.Mode.DRIVE,
            "origin_place_id": origin.pk,
            "destination_place_id": destination.pk,
            "depart_at": depart.isoformat(),
            "arrive_at": arrive.isoformat(),
            "capacity_kg": capacity,
        }

    def _payload(self, depart, *, capacity="10.00"):
        return {
            "start_place_id": self.jijel.pk,
            "destination_place_id": self.algiers.pk,
            "notes": "J9.3 timing boundary",
            "legs": [
                self._leg(
                    self.jijel,
                    self.algiers,
                    depart,
                    depart + timedelta(hours=2),
                    capacity=capacity,
                )
            ],
        }

    def _create(self, payload, *, at=None):
        reference = self.now if at is None else at
        with patch("apps.trips.constraints.timezone.now", return_value=reference):
            return self.client.post(
                reverse("journeys-list-create"), payload, format="json"
            )

    def _approve_kyc(self):
        KycSubmission.objects.create(
            user=self.owner,
            document_type=KycSubmission.DocumentType.PASSPORT,
            idempotency_key=f"{self.owner.pk:032d}",
            front_image_key="kyc/j93/front.jpg",
            status=KycSubmission.Status.APPROVED,
        )

    def test_past_and_exact_boundary_are_rejected_but_future_is_accepted(self):
        for label, depart in (
            ("past", self.now - timedelta(seconds=1)),
            ("exact", self.now),
        ):
            with self.subTest(label=label):
                response = self._create(self._payload(depart))
                self.assertEqual(response.status_code, 400, response.data)
                self.assertEqual(
                    str(response.data["code"][0]), "journey_departure_not_future"
                )

        future = self._create(self._payload(self.now + timedelta(seconds=1)))
        self.assertEqual(future.status_code, 201, future.data)
        self.assertEqual(Journey.objects.count(), 1)

    def test_timezone_aware_future_timestamp_is_compared_by_instant(self):
        algeria_time = datetime(
            2030,
            5,
            1,
            14,
            0,
            tzinfo=dt_timezone(timedelta(hours=1)),
        )

        response = self._create(self._payload(algeria_time))

        self.assertEqual(response.status_code, 201, response.data)
        saved = JourneyLeg.objects.get()
        self.assertEqual(
            saved.depart_at.astimezone(dt_timezone.utc),
            datetime(2030, 5, 1, 13, 0, tzinfo=dt_timezone.utc),
        )

    def test_valid_multi_leg_route_is_accepted_and_chronology_remains_enforced(self):
        first_depart = self.now + timedelta(hours=1)
        payload = {
            "start_place_id": self.jijel.pk,
            "destination_place_id": self.oran.pk,
            "notes": "Two ordered legs",
            "legs": [
                self._leg(
                    self.jijel,
                    self.algiers,
                    first_depart,
                    first_depart + timedelta(hours=2),
                ),
                self._leg(
                    self.algiers,
                    self.oran,
                    first_depart + timedelta(hours=3),
                    first_depart + timedelta(hours=5),
                    position=1,
                ),
            ],
        }
        valid = self._create(payload)
        self.assertEqual(valid.status_code, 201, valid.data)

        payload["legs"][1]["depart_at"] = (
            first_depart + timedelta(hours=1)
        ).isoformat()
        invalid = self._create(payload)
        self.assertEqual(invalid.status_code, 400, invalid.data)
        self.assertIn("cannot depart before", str(invalid.data).lower())

        payload["legs"][1]["depart_at"] = (
            first_depart + timedelta(hours=3)
        ).isoformat()
        payload["legs"][0]["arrive_at"] = first_depart.isoformat()
        invalid_arrival = self._create(payload)
        self.assertEqual(invalid_arrival.status_code, 400, invalid_arrival.data)
        self.assertIn(
            "arrival must be after departure", str(invalid_arrival.data).lower()
        )

    def test_publish_rechecks_past_and_exact_departure_boundaries(self):
        self._approve_kyc()
        for label, publish_at in (
            ("exact", self.now + timedelta(hours=1)),
            ("past", self.now + timedelta(hours=1, seconds=1)),
        ):
            with self.subTest(label=label):
                created = self._create(
                    self._payload(self.now + timedelta(hours=1)),
                    at=self.now,
                )
                self.assertEqual(created.status_code, 201, created.data)
                with patch(
                    "apps.trips.constraints.timezone.now", return_value=publish_at
                ):
                    response = self.client.post(
                        reverse("journeys-publish", args=(created.data["id"],))
                    )
                self.assertEqual(response.status_code, 409, response.data)
                self.assertEqual(response.data["code"], "journey_departure_not_future")

    def test_route_edit_cannot_move_a_draft_to_an_expired_departure(self):
        created = self._create(self._payload(self.now + timedelta(hours=1)))
        self.assertEqual(created.status_code, 201, created.data)
        url = reverse("journeys-detail", args=(created.data["id"],))

        with patch("apps.trips.constraints.timezone.now", return_value=self.now):
            response = self.client.patch(url, self._payload(self.now), format="json")

        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(str(response.data["code"][0]), "journey_departure_not_future")
        self.assertEqual(
            JourneyLeg.objects.get(journey_id=created.data["id"]).depart_at,
            self.now + timedelta(hours=1),
        )

    def test_future_journey_publishes(self):
        self._approve_kyc()
        created = self._create(self._payload(self.now + timedelta(hours=1)))

        with patch("apps.trips.constraints.timezone.now", return_value=self.now):
            response = self.client.post(
                reverse("journeys-publish", args=(created.data["id"],))
            )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], Journey.Status.ACTIVE)

    def test_capacity_uses_the_20000_kg_typo_ceiling(self):
        accepted = self._create(
            self._payload(
                self.now + timedelta(hours=1),
                capacity=str(MAX_JOURNEY_LEG_CAPACITY_KG),
            )
        )
        self.assertEqual(accepted.status_code, 201, accepted.data)

        rejected = self._create(
            self._payload(
                self.now + timedelta(hours=1),
                capacity="20000.01",
            )
        )
        self.assertEqual(rejected.status_code, 400, rejected.data)
        self.assertIn("capacity_kg", str(rejected.data))
