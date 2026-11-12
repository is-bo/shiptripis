"""L3B console screens: sea crossings, ticket proofs, journey pause and detail.

Each screen is a thin form over a domain command that already enforces the
rule (`apps.locations.sea_crossings`, `apps.trips.services`); these tests prove
the screens collect the reason, honour the same permissions, and show what
staff need to decide.
"""

from __future__ import annotations

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.admin_panel.models import AdminAuditLog
from apps.admin_panel.permissions import assign_admin_roles
from apps.discovery.tests.support import STATIC_STORES
from apps.locations.models import SeaCrossing
from apps.trips.models import Journey, JourneyLegProof
from apps.trips.tests.sea_world import DRIVE, FLIGHT, SEA, SeaWorld


class ConsoleWorld(SeaWorld):
    def build_console_world(self) -> None:
        self.build_sea_world()
        self.traveler = self.person("l3b-traveler@example.com")
        self.root = self.staff_user("l3b-root@example.com", "super_admin")
        self.ops = self.staff_user("l3b-ops@example.com", "ops")
        self.support = self.staff_user("l3b-support@example.com", "support")
        self.trust = self.staff_user("l3b-trust@example.com", "trust_verification")

    def staff_user(self, email: str, role: str):
        user = self.person(email, verified=False)
        user.is_staff = True
        user.save(update_fields=["is_staff"])
        assign_admin_roles(user, [role])
        return user

    def get(self, user, url, **query):
        self.client.force_login(user)
        return self.client.get(url, query)

    def post(self, user, url, data):
        self.client.force_login(user)
        return self.client.post(url, data)

    def body(self, response) -> str:
        self.assertEqual(response.status_code, 200)
        return response.content.decode()


# ---------------------------------------------------------------------------
# Sea crossings
# ---------------------------------------------------------------------------


@override_settings(STORAGES=STATIC_STORES)
class SeaCrossingConsoleTests(ConsoleWorld, TestCase):
    def setUp(self):
        self.build_console_world()
        self.geography = reverse("admin_console:geography")
        self.new = reverse("admin_console:sea-crossing-new")

    def add(self, user=None, **fields):
        data = {
            "origin_country": "ES",
            "origin_city": "Barcelona",
            "destination_country": "DZ",
            "destination_city": "Algiers",
            "distance_km": "",
            "reason": "Operator confirmed the line",
        }
        data.update(fields)
        return self.post(user or self.root, self.new, data)

    def test_the_geography_page_lists_every_crossing_and_the_switch(self):
        body = self.body(self.get(self.root, self.geography))

        self.assertIn("Sea crossings", body)
        self.assertIn("Marseille", body)
        self.assertIn("Barcelona", body)
        self.assertIn("Sea legs: off", body)
        self.assertIn("Add a crossing", body)
        self.assertIn("Turn off", body)  # an active line
        self.assertIn("Turn on", body)  # the switched-off Barcelona line

    def test_the_page_shows_the_switch_being_on(self):
        self.set_sea_switch(True)

        self.assertIn("Sea legs: on", self.body(self.get(self.root, self.geography)))

    def test_staff_who_may_only_look_get_no_controls(self):
        body = self.body(self.get(self.ops, self.geography))

        self.assertIn("Marseille", body)
        self.assertNotIn("Add a crossing", body)
        self.assertNotIn("Turn off", body)

    def test_adding_a_crossing_resolves_cities_names_and_is_audited(self):
        response = self.add(origin_city="Oran", origin_country="DZ",
                            destination_city="Barcelona", destination_country="ES",
                            distance_km="520")

        self.assertEqual(response.status_code, 302)
        crossing = SeaCrossing.objects.get(
            origin_locality=self.oran, destination_locality=self.barcelona
        )
        self.assertFalse(crossing.is_active)  # off until staff turn it on
        self.assertEqual(crossing.distance_meters, 520_000)
        audit = AdminAuditLog.objects.get(action="sea_crossing.created")
        self.assertEqual(audit.reason, "Operator confirmed the line")
        self.assertEqual(audit.actor, self.root)

    def test_a_crossing_can_start_on(self):
        self.add(origin_city="Oran", origin_country="DZ",
                 destination_city="Barcelona", destination_country="ES",
                 distance_km="520", start_active="on")

        self.assertTrue(
            SeaCrossing.objects.get(
                origin_locality=self.oran, destination_locality=self.barcelona
            ).is_active
        )

    def test_a_city_without_coordinates_needs_a_distance(self):
        response = self.add(origin_city="Lille", origin_country="FR")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Distance", response.content.decode())
        self.assertFalse(
            SeaCrossing.objects.filter(origin_locality=self.lille).exists()
        )
        self.assertFalse(AdminAuditLog.objects.filter(action="sea_crossing.created").exists())

    def test_an_unknown_or_wrong_country_city_is_refused_not_guessed(self):
        response = self.add(origin_city="Atlantis")
        self.assertIn("cannot be used", self.body(response))

        response = self.add(origin_city="Marseille", origin_country="DZ")
        self.assertIn("cannot be used", self.body(response))
        self.assertEqual(SeaCrossing.objects.count(), 3)

    def test_a_crossing_that_exists_is_refused(self):
        response = self.add(origin_city="Marseille", origin_country="FR",
                            destination_city="Algiers", destination_country="DZ",
                            distance_km="753")

        self.assertIn("already exists", self.body(response))
        self.assertEqual(SeaCrossing.objects.count(), 3)

    def test_a_reason_is_required(self):
        response = self.add(origin_city="Oran", origin_country="DZ",
                            destination_city="Barcelona", destination_country="ES",
                            distance_km="520", reason="")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(SeaCrossing.objects.count(), 3)

    def test_only_manage_settings_may_add_or_change(self):
        url = reverse("admin_console:sea-crossing-toggle", args=(self.marseille_algiers.pk, "deactivate"))
        for user in (self.ops, self.support, self.trust):
            with self.subTest(user.email):
                self.assertEqual(self.add(user).status_code, 403)
                self.assertEqual(self.get(user, self.new).status_code, 403)
                self.assertEqual(self.post(user, url, {"reason": "x"}).status_code, 403)
        self.marseille_algiers.refresh_from_db()
        self.assertTrue(self.marseille_algiers.is_active)

    def test_turning_a_line_off_asks_for_a_reason_and_is_audited(self):
        url = reverse("admin_console:sea-crossing-toggle", args=(self.marseille_algiers.pk, "deactivate"))

        self.assertIn("Funded deals are never touched", self.body(self.get(self.root, url)))
        self.assertEqual(self.post(self.root, url, {"reason": ""}).status_code, 200)
        self.marseille_algiers.refresh_from_db()
        self.assertTrue(self.marseille_algiers.is_active)

        self.assertEqual(self.post(self.root, url, {"reason": "Operator suspended sailings"}).status_code, 302)

        self.marseille_algiers.refresh_from_db()
        self.assertFalse(self.marseille_algiers.is_active)
        audit = AdminAuditLog.objects.get(action="sea_crossing.deactivated")
        self.assertEqual(audit.reason, "Operator suspended sailings")

    def test_turning_a_line_on_is_audited(self):
        url = reverse("admin_console:sea-crossing-toggle", args=(self.barcelona_oran.pk, "activate"))

        self.post(self.root, url, {"reason": "Season started"})

        self.barcelona_oran.refresh_from_db()
        self.assertTrue(self.barcelona_oran.is_active)
        self.assertTrue(AdminAuditLog.objects.filter(action="sea_crossing.activated").exists())

    def test_an_unknown_action_or_crossing_is_not_found(self):
        bad = reverse("admin_console:sea-crossing-toggle", args=(self.marseille_algiers.pk, "delete"))
        self.assertEqual(self.get(self.root, bad).status_code, 404)
        missing = reverse("admin_console:sea-crossing-toggle", args=(999_999, "activate"))
        self.assertEqual(self.get(self.root, missing).status_code, 404)


# ---------------------------------------------------------------------------
# Ticket proofs
# ---------------------------------------------------------------------------


@override_settings(STORAGES=STATIC_STORES)
class TicketProofConsoleTests(ConsoleWorld, TestCase):
    def setUp(self):
        self.build_console_world()
        self.set_sea_switch(True)
        self.journey = self.make_journey(
            self.traveler,
            [(SEA, self.marseille, self.algiers), (FLIGHT, self.algiers, self.setif)],
            approve_tickets=False,
        )
        self.sea_leg, self.flight_leg = self.journey.legs.order_by("position")
        self.sea_proof = self.ticket(self.sea_leg, JourneyLegProof.Status.PENDING)
        self.flight_proof = self.ticket(self.flight_leg, JourneyLegProof.Status.PENDING)
        self.queue = reverse("admin_console:proof-queue")

    def test_the_queue_is_ticket_proofs_with_a_mode_column(self):
        body = self.body(self.get(self.trust, self.queue))

        self.assertIn("Ticket proofs", body)
        self.assertNotIn("Flight-proof review", body)
        self.assertIn("<th scope=\"col\">Mode</th>", body)
        self.assertIn("Sea", body)
        self.assertIn("Flight", body)
        self.assertIn("AH1001", body)  # the flight leg's number

    def test_a_ferry_row_names_the_document_where_a_flight_row_shows_its_number(self):
        self.sea_proof.kind = "booking_confirmation"
        self.sea_proof.save(update_fields=["kind"])

        body = self.body(self.get(self.trust, self.queue, mode="SEA"))

        self.assertIn("Booking confirmation", body)
        self.assertNotIn("AH1001", body)

    def test_the_mode_filter_narrows_the_queue(self):
        sea = self.body(self.get(self.trust, self.queue, mode="SEA"))
        flight = self.body(self.get(self.trust, self.queue, mode="FLIGHT"))

        self.assertNotIn("AH1001", sea)
        self.assertIn("AH1001", flight)
        self.assertIn(reverse("admin_console:proof-detail", args=(self.sea_proof.pk,)), sea)
        self.assertNotIn(reverse("admin_console:proof-detail", args=(self.flight_proof.pk,)), sea)

    def test_an_unknown_mode_shows_nothing_rather_than_everything(self):
        body = self.body(self.get(self.trust, self.queue, mode="ROCKET"))

        self.assertIn("No ticket proofs", body)

    def test_the_mode_and_state_filters_combine_and_can_be_cleared(self):
        self.sea_proof.delete()
        self.ticket(self.sea_leg, JourneyLegProof.Status.APPROVED)

        body = self.body(self.get(self.trust, self.queue, mode="SEA", status="pending"))

        self.assertIn("No ticket proofs waiting", body)
        self.assertIn("Clear filters", body)

    def test_a_ferry_ticket_detail_says_ferry(self):
        url = reverse("admin_console:proof-detail", args=(self.sea_proof.pk,))

        body = self.body(self.get(self.trust, url))

        self.assertIn("ferry crossing", body)
        self.assertIn("Ferry ticket", body)
        self.assertNotIn("this flight", body)
        self.assertNotIn(">Flight</dt>", body)  # no flight number row for a sail

    def test_a_flight_ticket_detail_still_says_flight(self):
        url = reverse("admin_console:proof-detail", args=(self.flight_proof.pk,))

        body = self.body(self.get(self.trust, url))

        self.assertIn("this flight", body)
        self.assertIn("AH1001", body)

    def test_a_ferry_ticket_decision_is_reviewed_and_audited(self):
        url = reverse("admin_console:proof-detail", args=(self.sea_proof.pk,))

        response = self.post(
            self.trust,
            url,
            {"decision": "approved", "reason": "", "confirm": "on"},
        )

        self.assertEqual(response.status_code, 302)
        self.sea_proof.refresh_from_db()
        self.assertEqual(self.sea_proof.status, JourneyLegProof.Status.APPROVED)
        audit = AdminAuditLog.objects.get(action="flight_proof.approved")
        self.assertEqual(audit.target_id, str(self.sea_proof.pk))

    def test_support_still_cannot_open_the_queue(self):
        self.assertEqual(self.get(self.support, self.queue).status_code, 403)


# ---------------------------------------------------------------------------
# Journey detail and pause
# ---------------------------------------------------------------------------


@override_settings(STORAGES=STATIC_STORES)
class JourneyConsoleTests(ConsoleWorld, TestCase):
    def setUp(self):
        self.build_console_world()
        self.set_sea_switch(True)
        self.journey = self.make_journey(
            self.traveler,
            [
                (DRIVE, self.lille, self.paris),
                (SEA, self.marseille, self.algiers),
            ],
            capacity="12.00",
        )
        self.sea_leg = self.journey.legs.get(position=1)
        self.detail = reverse("admin_console:journey-detail", args=(self.journey.pk,))
        self.pause = reverse("admin_console:journey-pause", args=(self.journey.pk, "pause"))
        self.resume = reverse("admin_console:journey-pause", args=(self.journey.pk, "resume"))

    def traveler_payload(self) -> dict:
        client = APIClient()
        client.force_authenticate(user=self.traveler)
        return client.get(reverse("journeys-detail", args=(self.journey.pk,))).json()

    # -- detail ---------------------------------------------------------------

    def test_the_detail_shows_stops_capacity_by_leg_and_what_is_taken(self):
        self.sea_leg.capacity_volume_l = 80
        self.sea_leg.capacity_parcels = 3
        self.sea_leg.save(update_fields=["capacity_volume_l", "capacity_parcels"])
        self.stop(self.journey, 1, accepts_dropoff=False, handover_note="Ask for Karim at the kiosk")
        self.journey.refused_categories = ["electronics"]
        self.journey.accepts_fragile = False
        self.journey.save(update_fields=["refused_categories", "accepts_fragile"])

        body = self.body(self.get(self.ops, self.detail))

        self.assertIn("Stops and what each accepts", body)
        self.assertIn("Ask for Karim at the kiosk", body)
        self.assertIn("80 L", body)
        self.assertIn("3</b> parcels", body)
        self.assertIn("Electronics", body)
        self.assertIn("Not accepted", body)
        self.assertIn("Sea", body)

    def test_a_ferry_leg_reports_its_ticket_not_a_flight_proof(self):
        JourneyLegProof.objects.filter(leg=self.sea_leg).delete()

        body = self.body(self.get(self.ops, self.detail))

        self.assertIn("Ticket missing", body)
        self.assertIn("Tickets: Missing", body)
        self.assertNotIn("Flight proof", body)
        self.assertIn("Ticket not required", body)  # the road leg

    def test_the_list_marks_a_paused_journey(self):
        self.post(self.ops, self.pause, {"reason": "Customer complaint"})

        body = self.body(self.get(self.ops, reverse("admin_console:journeys")))

        self.assertIn("Paused by staff", body)
        self.assertIn("Tickets", body)

    # -- pause ----------------------------------------------------------------

    def test_ops_pause_a_journey_with_a_reason_and_it_is_audited(self):
        self.assertIn("Pause journey", self.body(self.get(self.ops, self.detail)))

        response = self.post(self.ops, self.pause, {"reason": "Ticket looked altered"})

        self.assertEqual(response.status_code, 302)
        self.journey.refresh_from_db()
        self.assertTrue(self.journey.paused_by_staff)
        self.assertEqual(self.journey.pause_reason, "Ticket looked altered")
        audit = AdminAuditLog.objects.get(action="journey.paused")
        self.assertEqual(audit.reason, "Ticket looked altered")

    def test_a_reason_is_required_to_pause(self):
        response = self.post(self.ops, self.pause, {"reason": ""})

        self.assertEqual(response.status_code, 200)
        self.journey.refresh_from_db()
        self.assertIsNone(self.journey.paused_at)

    def test_the_detail_shows_the_internal_reason_and_the_traveler_never_gets_it(self):
        self.post(self.ops, self.pause, {"reason": "Ticket looked altered"})

        staff_view = self.body(self.get(self.ops, self.detail))
        self.assertIn("Ticket looked altered", staff_view)
        self.assertIn("Resume journey", staff_view)

        payload = self.traveler_payload()
        self.assertTrue(payload["pause"]["paused_by_staff"])
        self.assertNotIn("Ticket looked altered", str(payload))

    def test_staff_resume_a_staff_pause(self):
        self.post(self.ops, self.pause, {"reason": "Check ticket"})

        self.assertEqual(self.post(self.ops, self.resume, {"reason": "Ticket verified"}).status_code, 302)

        self.journey.refresh_from_db()
        self.assertIsNone(self.journey.paused_at)
        self.assertTrue(AdminAuditLog.objects.filter(action="journey.resumed").exists())

    def test_an_owner_pause_cannot_be_lifted_by_staff_but_can_be_taken_over(self):
        client = APIClient()
        client.force_authenticate(user=self.traveler)
        client.post(reverse("journeys-pause", args=(self.journey.pk,)))

        body = self.body(self.get(self.ops, self.detail))
        self.assertIn("Paused by the traveler", body)
        self.assertNotIn("Resume journey", body)
        self.assertIn("Take over the pause", body)

        self.post(self.ops, self.resume, {"reason": "Try to lift"})
        self.journey.refresh_from_db()
        self.assertIsNotNone(self.journey.paused_at)
        self.assertFalse(self.journey.paused_by_staff)

        self.post(self.ops, self.pause, {"reason": "Fraud review"})
        self.journey.refresh_from_db()
        self.assertTrue(self.journey.paused_by_staff)

    def test_a_finished_journey_offers_no_pause(self):
        Journey.objects.filter(pk=self.journey.pk).update(status=Journey.Status.COMPLETED)

        self.assertNotIn("Pause journey", self.body(self.get(self.ops, self.detail)))
        response = self.post(self.ops, self.pause, {"reason": "Too late"})
        self.assertEqual(response.status_code, 200)
        self.journey.refresh_from_db()
        self.assertIsNone(self.journey.paused_at)

    def test_only_manage_journeys_may_pause(self):
        self.assertNotIn("Pause journey", self.body(self.get(self.support, self.detail)))
        for user in (self.support, self.trust):
            with self.subTest(user.email):
                self.assertEqual(self.post(user, self.pause, {"reason": "x"}).status_code, 403)
        self.journey.refresh_from_db()
        self.assertIsNone(self.journey.paused_at)

    def test_an_unknown_action_is_not_found(self):
        url = reverse("admin_console:journey-pause", args=(self.journey.pk, "delete"))
        self.assertEqual(self.get(self.ops, url).status_code, 404)

    def test_a_staff_pause_takes_the_journey_out_of_discovery(self):
        from apps.discovery.listings import listable_journeys

        self.assertTrue(listable_journeys(at=self.now, sea_legs_enabled=True).filter(pk=self.journey.pk).exists())

        self.post(self.ops, self.pause, {"reason": "Check ticket"})

        self.assertFalse(listable_journeys(at=self.now, sea_legs_enabled=True).filter(pk=self.journey.pk).exists())
