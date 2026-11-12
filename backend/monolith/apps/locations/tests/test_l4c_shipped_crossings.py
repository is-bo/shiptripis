"""L4C: the shipped sea crossings, priced and matched on the real catalogue.

L3A gave a crossing two ways to get its distance: the catalogue coordinates of
its two cities, and, for a city without them, a backup (port coordinates in
the seed file, or kilometres typed by staff). Since the French and Spanish
coordinates landed (PR #27) every launch-country city has catalogue
coordinates, so L4C removed the backup. This file is the proof that nothing
priced or matched through it:

* every port in the shipped list resolves to one catalogue city that has
  coordinates, so the seed never needed the backup;
* every shipped crossing's distance, and the distance, match and price of a
  ferry-only journey over every live line, are pinned to the values the code
  produced *before* the backup was removed. The same assertions passed on
  that code and pass on this one.

The real catalogue has 56k places and takes minutes to import. The test
imports only what `resolve_port` can see for the shipped port names: every
active city in a port's country whose name or alternate name normalizes to
the port's name, with its parents. A name two cities share in the full
catalogue is therefore still ambiguous here.
"""

from __future__ import annotations

import gzip
import json
import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.locations.geography import normalize_search_name
from apps.locations.management.commands.import_geography import (
    BUNDLED_MANIFEST,
    read_manifest_bytes,
)
from apps.locations.management.commands.seed_sea_crossings import DEFAULT_FILE
from apps.locations.models import SeaCrossing
from apps.locations.sea_crossings import great_circle_meters, resolve_port
from apps.matching.discovery import evaluate_candidate, phase2_policy
from apps.matching.tests.test_v1_matching import _ensure_business_settings, _user
from apps.trips.models import Journey, JourneyLegProof
from apps.trips.tests.sea_world import SEA, SeaWorld

#: Each shipped crossing's distance in metres, as the seed wrote it before L4C.
PINNED_DISTANCES = {
    ("marseille", "algiers"): 752_433,
    ("algiers", "marseille"): 752_433,
    ("marseille", "bejaia"): 726_687,
    ("bejaia", "marseille"): 726_687,
    ("marseille", "skikda"): 724_950,
    ("skikda", "marseille"): 724_950,
    ("marseille", "oran"): 995_449,
    ("oran", "marseille"): 995_449,
    ("marseille", "annaba"): 735_729,
    ("annaba", "marseille"): 735_729,
    ("valencia", "mostaganem"): 384_103,
    ("mostaganem", "valencia"): 384_103,
    ("almeria", "oran"): 204_966,
    ("oran", "almeria"): 204_966,
    ("almeria", "ghazaouet"): 202_602,
    ("ghazaouet", "almeria"): 202_602,
    ("alicante", "algiers"): 362_837,
    ("algiers", "alicante"): 362_837,
    ("valencia", "algiers"): 417_378,
    ("algiers", "valencia"): 417_378,
    ("valencia", "oran"): 421_050,
    ("oran", "valencia"): 421_050,
    ("barcelona", "algiers"): 520_739,
    ("algiers", "barcelona"): 520_739,
    ("sete", "algiers"): 739_747,
    ("algiers", "sete"): 739_747,
    ("sete", "bejaia"): 745_006,
    ("bejaia", "sete"): 745_006,
    ("sete", "oran"): 940_021,
    ("oran", "sete"): 940_021,
    ("sete", "skikda"): 773_724,
    ("skikda", "sete"): 773_724,
    ("sete", "annaba"): 796_064,
    ("annaba", "sete"): 796_064,
    ("alicante", "oran"): 304_001,
    ("oran", "alicante"): 304_001,
    ("barcelona", "oran"): 685_504,
    ("oran", "barcelona"): 685_504,
}

#: A 2 kg parcel sailing port to port on every live line, as matching priced
#: it before L4C: (matched distance, minimum reward, recommended reward).
PINNED_SAILINGS = {
    ("marseille", "algiers"): (752_433, 1_700, 2_350),
    ("algiers", "marseille"): (752_433, 1_700, 2_350),
    ("marseille", "bejaia"): (726_687, 1_400, 2_000),
    ("bejaia", "marseille"): (726_687, 1_400, 2_000),
    ("marseille", "skikda"): (724_950, 1_400, 2_000),
    ("skikda", "marseille"): (724_950, 1_400, 2_000),
    ("marseille", "oran"): (995_449, 1_700, 2_350),
    ("oran", "marseille"): (995_449, 1_700, 2_350),
    ("marseille", "annaba"): (735_729, 1_400, 2_000),
    ("annaba", "marseille"): (735_729, 1_400, 2_000),
    ("valencia", "mostaganem"): (384_103, 1_400, 2_000),
    ("mostaganem", "valencia"): (384_103, 1_400, 2_000),
    ("almeria", "oran"): (204_966, 1_100, 1_650),
    ("oran", "almeria"): (204_966, 1_100, 1_650),
    ("almeria", "ghazaouet"): (202_602, 1_100, 1_650),
    ("ghazaouet", "almeria"): (202_602, 1_100, 1_650),
    ("alicante", "algiers"): (362_837, 1_400, 2_000),
    ("algiers", "alicante"): (362_837, 1_400, 2_000),
    ("valencia", "algiers"): (417_378, 1_400, 2_000),
    ("algiers", "valencia"): (417_378, 1_400, 2_000),
    ("valencia", "oran"): (421_050, 1_400, 2_000),
    ("oran", "valencia"): (421_050, 1_400, 2_000),
    ("barcelona", "algiers"): (520_739, 1_400, 2_000),
    ("algiers", "barcelona"): (520_739, 1_400, 2_000),
}


def _port_catalogue(document: dict) -> bytes:
    """The slice of the bundled catalogue that `resolve_port` can see."""

    manifest = json.loads(read_manifest_bytes(BUNDLED_MANIFEST))
    wanted = {
        (str(port["country"]), normalize_search_name(str(port["name"])))
        for port in document["ports"].values()
    }
    by_key = {(row["source"], row["source_id"]): row for row in manifest["places"]}

    def is_candidate(place: dict, name: str) -> bool:
        return (
            place["place_type"] == "locality"
            and (place["country_code"], normalize_search_name(name)) in wanted
        )

    keys = {key for key, place in by_key.items() if is_candidate(place, place["name"])}
    keys |= {
        (row["place_source"], row["place_source_id"])
        for row in manifest["alternate_names"]
        if (place := by_key.get((row["place_source"], row["place_source_id"])))
        and is_candidate(place, row["name"])
    }
    pending = list(keys)
    while pending:
        place = by_key[pending.pop()]
        if place.get("parent_source_id") in (None, ""):
            continue
        parent = (place.get("parent_source") or place["source"], str(place["parent_source_id"]))
        if parent not in keys:
            keys.add(parent)
            pending.append(parent)

    sliced = {
        "format_version": manifest["format_version"],
        "countries": manifest["countries"],
        "places": [row for key, row in by_key.items() if key in keys],
        "alternate_names": [
            row
            for row in manifest["alternate_names"]
            if (row["place_source"], row["place_source_id"]) in keys
        ],
        "airport_mappings": [],
    }
    return gzip.compress(json.dumps(sliced).encode("utf-8"))


class ShippedCrossingsOnTheRealCatalogue(SeaWorld, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.document = json.loads(DEFAULT_FILE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ports.json.gz"
            path.write_bytes(_port_catalogue(cls.document))
            call_command("import_geography", manifest=str(path), stdout=StringIO())
        out = StringIO()
        call_command("seed_sea_crossings", stdout=out)
        cls.seed_output = out.getvalue()
        cls.ports = {
            slug: resolve_port(str(port["country"]), str(port["name"]))[0]
            for slug, port in cls.document["ports"].items()
        }

    def crossing(self, origin: str, destination: str) -> SeaCrossing:
        return SeaCrossing.objects.get(
            origin_locality=self.ports[origin], destination_locality=self.ports[destination]
        )

    def test_every_port_is_one_catalogue_city_with_coordinates(self):
        for slug, port in self.document["ports"].items():
            with self.subTest(port=slug):
                place, problem = resolve_port(str(port["country"]), str(port["name"]))
                assert place is not None, problem
                assert place.latitude is not None and place.longitude is not None

    def test_the_seed_writes_every_shipped_line(self):
        assert "sea crossings: 38 created, 0 already present, 0 skipped" in self.seed_output
        lines = {(row["from"], row["to"]): row["active"] for row in self.document["crossings"]}
        assert set(lines) == set(PINNED_DISTANCES)
        for (origin, destination), active in lines.items():
            crossing = self.crossing(origin, destination)
            assert crossing.is_active is active

    def test_every_distance_is_the_catalogue_great_circle_pinned_before_l4c(self):
        for (origin, destination), meters in PINNED_DISTANCES.items():
            with self.subTest(line=f"{origin}->{destination}"):
                crossing = self.crossing(origin, destination)
                assert crossing.distance_meters == meters
                assert great_circle_meters(
                    crossing.origin_locality, crossing.destination_locality
                ) == meters

    def test_a_sailing_on_every_live_line_matches_and_prices_as_before_l4c(self):
        _ensure_business_settings()
        self.set_sea_switch(True)
        self.now = timezone.now()
        self.reviewer = _user("l4c-ticket-reviewer@example.com")
        traveler = self.person("l4c-traveler@example.com")
        sender = self.person("l4c-sender@example.com")
        policy = phase2_policy()
        client = APIClient()
        client.force_authenticate(user=traveler)
        depart = self.now + timedelta(days=5)
        live = [
            (row["from"], row["to"]) for row in self.document["crossings"] if row["active"]
        ]

        sailings = {}
        for origin, destination in live:
            with self.subTest(line=f"{origin}->{destination}"):
                response = client.post(
                    reverse("journeys-list-create"),
                    {
                        "start_place_id": self.ports[origin].pk,
                        "destination_place_id": self.ports[destination].pk,
                        "notes": "",
                        "legs": [
                            {
                                "position": 0,
                                "mode": SEA,
                                "origin_place_id": self.ports[origin].pk,
                                "destination_place_id": self.ports[destination].pk,
                                "depart_at": depart.isoformat(),
                                "arrive_at": (depart + timedelta(hours=20)).isoformat(),
                                "capacity_kg": "10.00",
                            }
                        ],
                    },
                    format="json",
                )
                assert response.status_code == 201, response.data
                journey = Journey.objects.get(pk=response.data["id"])
                leg = journey.legs.get()
                assert leg.distance_meters == PINNED_DISTANCES[(origin, destination)]
                self.ticket(leg, JourneyLegProof.Status.APPROVED)
                Journey.objects.filter(pk=journey.pk).update(
                    status=Journey.Status.ACTIVE, published_at=self.now
                )
                journey.refresh_from_db()
                parcel = self.request(
                    sender,
                    self.ports[origin],
                    self.ports[destination],
                    pickup_at=leg.depart_at,
                    deliver_by=leg.arrive_at + timedelta(days=1),
                )

                evaluation = evaluate_candidate(
                    delivery_request=parcel, journey=journey, policy=policy
                )

                result = evaluation.compatibility
                assert result.compatible, result.rejection_codes
                assert result.matched_distance_method == "great_circle_sea_crossing"
                sailings[(origin, destination)] = (
                    result.matched_distance_meters,
                    evaluation.pricing.minimum_reward_eur_cents,
                    evaluation.pricing.recommended_reward_eur_cents,
                )
        assert sailings == PINNED_SAILINGS
