from __future__ import annotations

import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from apps.locations.management.commands.import_geography import (
    BUNDLED_MANIFEST,
    read_manifest_bytes,
)
from apps.locations.models import Place


TARGET_LOCALITIES = {
    ("algeria-commune", "0601"),  # Bejaia
    ("algeria-commune", "1601"),  # Alger Centre
    ("algeria-commune", "1801"),  # Jijel
    ("algeria-commune", "2501"),  # Constantine
    ("algeria-commune", "3101"),  # Oran
    ("insee-cog-commune", "75056"),  # Paris
    ("insee-cog-commune", "82137"),  # Parisot (broader prefix control)
    ("ine-municipality", "08019"),  # Barcelona
    ("ine-municipality", "28079"),  # Madrid
    ("destatis-municipality", "06412000"),  # Frankfurt am Main
}
TARGET_AIRPORTS = {
    "ALG",
    "GJL",
    "ORN",
    "CZL",
    "BJA",
    "CDG",
    "ORY",
    "BCN",
    "MAD",
    "FRA",
    "HHN",
}


def _reviewed_search_fixture() -> dict:
    """Extract a small, exact fixture from the reviewed release catalogue."""

    manifest = json.loads(read_manifest_bytes(BUNDLED_MANIFEST))
    places_by_key = {
        (row["source"], str(row["source_id"])): row for row in manifest["places"]
    }
    included = set(TARGET_LOCALITIES)
    airport_keys = {
        (row["source"], str(row["source_id"]))
        for row in manifest["places"]
        if row.get("iata_code") in TARGET_AIRPORTS
    }
    included.update(airport_keys)

    airport_mappings = [
        row
        for row in manifest["airport_mappings"]
        if (
            row.get("airport_source", row.get("source")),
            str(row.get("airport_source_id", "")),
        )
        in airport_keys
    ]
    for mapping in airport_mappings:
        included.add((mapping["locality_source"], str(mapping["locality_source_id"])))

    pending = list(included)
    while pending:
        place = places_by_key[pending.pop()]
        parent_source_id = place.get("parent_source_id")
        if parent_source_id is None:
            continue
        parent_key = (
            place.get("parent_source", place["source"]),
            str(parent_source_id),
        )
        if parent_key not in included:
            included.add(parent_key)
            pending.append(parent_key)

    places = [row for key, row in places_by_key.items() if key in included]
    alternates = [
        row
        for row in manifest["alternate_names"]
        if (row["place_source"], str(row["place_source_id"])) in included
    ]
    country_codes = {row["country_code"] for row in places}
    return {
        "format_version": manifest["format_version"],
        "source_version": manifest.get("source_version", "reviewed-2026"),
        "countries": [
            row for row in manifest["countries"] if row["code"] in country_codes
        ],
        "places": places,
        "alternate_names": alternates,
        "airport_mappings": airport_mappings,
    }


def _import_fixture(manifest: dict) -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "reviewed-search-fixture.json"
        path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        call_command("import_geography", manifest=str(path))


class NearbyAirportSearchTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        _import_fixture(_reviewed_search_fixture())

    def _search(self, country: str, query: str, *, airport_only: bool = False):
        response = APIClient().get(
            reverse("geography-places"),
            {
                "country": country,
                "q": query,
                "place_type": "airport" if airport_only else "locality,airport",
            },
        )
        self.assertEqual(response.status_code, 200)
        return response.data["results"]

    def test_reviewed_city_searches_surface_their_airports(self):
        cases = (
            ("DZ", "Alger", "1601", {"ALG"}),
            ("DZ", "Jijel", "1801", {"GJL"}),
            ("DZ", "Oran", "3101", {"ORN"}),
            ("DZ", "Constantine", "2501", {"CZL"}),
            ("DZ", "Béjaïa", "0601", {"BJA"}),
            ("FR", "Paris", "75056", {"CDG", "ORY"}),
            ("ES", "Barcelona", "08019", {"BCN"}),
            ("ES", "Madrid", "28079", {"MAD"}),
            ("DE", "Frankfurt", "06412000", {"FRA", "HHN"}),
        )
        for country, query, expected_city_source_id, expected_iatas in cases:
            with self.subTest(query=query):
                results = self._search(country, query)
                self.assertEqual(results[0]["source_id"], expected_city_source_id)
                self.assertTrue(
                    expected_iatas.issubset({row["iata_code"] for row in results})
                )

    def test_served_airports_rank_before_broader_prefix_matches(self):
        results = self._search("FR", "Paris")
        result_ids = [row["source_id"] for row in results]

        parisot_index = result_ids.index("82137")
        self.assertLess(result_ids.index("4185"), parisot_index)  # CDG
        self.assertLess(result_ids.index("4189"), parisot_index)  # ORY

    def test_alger_ranks_the_city_then_its_served_airport_with_canonical_identity(self):
        results = self._search("DZ", "Alger")

        self.assertEqual(results[0]["source_id"], "1601")
        airport = next(row for row in results if row["iata_code"] == "ALG")
        self.assertEqual(airport["search_relation"], "serves_place")
        self.assertEqual(airport["search_context"]["name"], "Alger Centre")
        self.assertEqual(
            airport["matching_locality"]["id"],
            Place.objects.get(source="algeria-commune", source_id="1601").id,
        )
        self.assertNotIn("BJA", {row["iata_code"] for row in results})

    def test_airport_only_journey_search_can_start_from_a_city_name(self):
        results = self._search("DZ", "Alger", airport_only=True)

        self.assertEqual([row["iata_code"] for row in results], ["ALG"])
        self.assertEqual(results[0]["search_relation"], "serves_place")

    def test_exact_airport_name_search_remains_direct(self):
        results = self._search("DZ", "Houari")

        self.assertEqual(results[0]["iata_code"], "ALG")
        self.assertEqual(results[0]["search_relation"], "direct_match")
        self.assertIsNone(results[0]["search_context"])

    def test_english_and_arabic_aliases_enrich_the_same_canonical_alger_result(self):
        for query in ("Algiers", "الجزائر"):
            with self.subTest(query=query):
                results = self._search("DZ", query)
                self.assertEqual(results[0]["source_id"], "1601")
                self.assertIn("ALG", {row["iata_code"] for row in results})

    def test_nearby_fallback_is_bounded_and_does_not_change_matching_identity(self):
        nearby = Place.objects.create(
            country_id="DZ",
            place_type=Place.PlaceType.LOCALITY,
            source="phase8ff2-test",
            source_id="nearby",
            source_version="test",
            name="Nearbyville",
            latitude="36.760000",
            longitude="3.050000",
        )

        with self.assertNumQueries(6):
            results = self._search("DZ", "Nearbyville")
        airport = next(row for row in results if row["iata_code"] == "ALG")

        self.assertEqual(airport["search_relation"], "nearby")
        self.assertLessEqual(airport["search_distance_km"], 100.0)
        self.assertEqual(nearby.resolve_matching_locality(), nearby)
        self.assertNotEqual(
            airport["matching_locality"]["id"], nearby.resolve_matching_locality().id
        )

        Place.objects.create(
            country_id="DZ",
            place_type=Place.PlaceType.LOCALITY,
            source="phase8ff2-test",
            source_id="far",
            source_version="test",
            name="Farville",
            latitude="30.000000",
            longitude="-10.000000",
        )
        far_results = self._search("DZ", "Farville")
        self.assertEqual([row["name"] for row in far_results], ["Farville"])
