from __future__ import annotations

import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from apps.locations.geography import normalize_search_name
from apps.locations.models import AirportLocalityMapping, Place


def _manifest(*, rename: str = "Jijel", inactive: bool = False) -> dict:
    return {
        "format_version": 1,
        "source_version": "test-2026",
        "countries": [
            {
                "code": "DZ",
                "name": "Algeria",
                "source": "test-country",
                "source_id": "DZ",
            },
            {
                "code": "FR",
                "name": "France",
                "source": "test-country",
                "source_id": "FR",
            },
        ],
        "places": [
            {
                "source": "test-region",
                "source_id": "DZ-18",
                "country_code": "DZ",
                "place_type": "admin_region",
                "name": "Jijel",
                "admin_level": "wilaya",
            },
            {
                "source": "test-region",
                "source_id": "FR-11",
                "country_code": "FR",
                "place_type": "admin_region",
                "name": "Île-de-France",
                "admin_level": "region",
            },
            {
                "source": "test-commune",
                "source_id": "DZ-1801",
                "country_code": "DZ",
                "place_type": "locality",
                "name": rename,
                "admin_level": "commune",
                "parent_source": "test-region",
                "parent_source_id": "DZ-18",
                "latitude": "36.820000",
                "longitude": "5.770000",
                "active": not inactive,
            },
            {
                "source": "test-commune",
                "source_id": "FR-75056",
                "country_code": "FR",
                "place_type": "locality",
                "name": "Paris",
                "admin_level": "commune",
                "parent_source": "test-region",
                "parent_source_id": "FR-11",
            },
            {
                "source": "test-airport",
                "source_id": "airport-1",
                "country_code": "DZ",
                "place_type": "airport",
                "name": "Jijel Ferhat Abbas Airport",
                "iata_code": "GJL",
                "icao_code": "DAAV",
                "airport_type": "medium_airport",
                "passenger_use": True,
                "latitude": "36.795100",
                "longitude": "5.873610",
                "parent_source": "test-commune",
                "parent_source_id": "DZ-1801",
                "legacy_city": "Jijel",
            },
        ],
        "alternate_names": [
            {
                "place_source": "test-commune",
                "place_source_id": "DZ-1801",
                "name": "جيجل",
                "language": "ar",
                "source": "test-alt",
                "source_id": "DZ-1801-ar",
            }
        ],
        "airport_mappings": [
            {
                "airport_source": "test-airport",
                "airport_source_id": "airport-1",
                "locality_source": "test-commune",
                "locality_source_id": "DZ-1801",
                "relationship_type": "served",
                "is_primary": True,
                "source": "test-map",
                "source_id": "airport-1-served",
            }
        ],
    }


def _run_manifest(manifest: dict, *, deactivate_missing: bool = False) -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "manifest.json"
        path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        args = {"manifest": str(path)}
        if deactivate_missing:
            args["deactivate_missing"] = True
        call_command("import_geography", **args)


class GeographyImportTests(TestCase):
    def test_idempotent_import_rename_and_explicit_airport_mapping(self):
        _run_manifest(_manifest())
        locality = Place.objects.get(source="test-commune", source_id="DZ-1801")
        locality_id = locality.pk
        _run_manifest(_manifest(rename="Jijel Centre"))
        locality.refresh_from_db()
        self.assertEqual(locality.pk, locality_id)
        self.assertEqual(locality.name, "Jijel Centre")
        self.assertEqual(locality.parent.name, "Jijel")
        self.assertEqual(AirportLocalityMapping.objects.count(), 1)
        self.assertEqual(Place.objects.get(iata_code="GJL").legacy_airport.iata, "GJL")

    def test_deactivate_missing_is_source_scoped(self):
        _run_manifest(_manifest())
        manifest = _manifest()
        manifest["places"] = [
            row for row in manifest["places"] if row["source"] != "test-airport"
        ]
        manifest["deactivate_sources"] = ["test-airport"]
        _run_manifest(manifest, deactivate_missing=True)
        self.assertFalse(
            Place.objects.get(source="test-airport", source_id="airport-1").active
        )

    def test_deactivating_locality_retires_dependent_mapping(self):
        _run_manifest(_manifest())
        manifest = _manifest()
        manifest["places"] = [
            row
            for row in manifest["places"]
            if not (row["source"] == "test-commune" and row["source_id"] == "DZ-1801")
        ]
        manifest["deactivate_sources"] = ["test-commune"]

        _run_manifest(manifest, deactivate_missing=True)

        mapping = AirportLocalityMapping.objects.get(source="test-map")
        self.assertFalse(mapping.active)
        self.assertFalse(mapping.is_primary)

    def test_importer_rejects_invalid_boundary_values(self):
        cases = []

        invalid_boolean = _manifest()
        invalid_boolean["places"][0]["active"] = "flase"
        cases.append(invalid_boolean)

        invalid_coordinates = _manifest()
        invalid_coordinates["places"][2]["latitude"] = "NaN"
        cases.append(invalid_coordinates)

        invalid_country = _manifest()
        invalid_country["countries"][0]["code"] = "DŻ"
        cases.append(invalid_country)

        invalid_format = _manifest()
        invalid_format["format_version"] = 2
        cases.append(invalid_format)

        for manifest in cases:
            with self.subTest(manifest=manifest):
                with self.assertRaises(CommandError):
                    _run_manifest(manifest)

    def test_importer_rejects_cross_country_mapping_and_parent_cycle(self):
        cross_country = _manifest()
        cross_country["airport_mappings"][0]["locality_source_id"] = "FR-75056"
        with self.assertRaises(CommandError):
            _run_manifest(cross_country)

        cycle = _manifest()
        cycle["places"].extend(
            [
                {
                    "source": "test-cycle",
                    "source_id": "a",
                    "country_code": "DZ",
                    "place_type": "locality",
                    "name": "A",
                    "parent_source": "test-cycle",
                    "parent_source_id": "b",
                },
                {
                    "source": "test-cycle",
                    "source_id": "b",
                    "country_code": "DZ",
                    "place_type": "locality",
                    "name": "B",
                    "parent_source": "test-cycle",
                    "parent_source_id": "a",
                },
            ]
        )
        with self.assertRaises(CommandError):
            _run_manifest(cycle)

    def test_duplicate_source_identity_is_rejected(self):
        manifest = _manifest()
        manifest["places"].append(manifest["places"][1].copy())
        with self.assertRaises(CommandError):
            _run_manifest(manifest)

    def test_normalization_preserves_unicode_scripts(self):
        self.assertEqual(
            normalize_search_name("L’Abergement-de-Varey"), "l abergement de varey"
        )
        self.assertEqual(normalize_search_name("Jijel"), "jijel")
        self.assertEqual(normalize_search_name("جيجل"), "جيجل")


class GeographySearchApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        _run_manifest(_manifest())

    def test_country_endpoint_returns_active_catalogue(self):
        response = APIClient().get(reverse("geography-countries"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual({row["code"] for row in response.data}, {"DZ", "FR"})

    def test_search_is_paginated_and_disambiguated(self):
        with self.assertNumQueries(3):
            response = APIClient().get(
                reverse("geography-places"),
                {"country": "DZ", "q": "jijel", "page_size": 1},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 3)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertIn("parent_name", response.data["results"][0])
        self.assertIn("Jijel", response.data["results"][0]["display_label"])

    def test_parent_administrative_tier_is_served_from_reviewed_data(self):
        """A row carries its parent's own tier, so a client can say "Jijel

        Wilaya" instead of inferring a tier from the country. The value is the
        reviewed source's, never a guess: a place without a parent serves
        ``None`` and a parent with no recorded tier serves an empty string.
        """

        with self.assertNumQueries(3):
            response = APIClient().get(
                reverse("geography-places"),
                {"country": "DZ", "place_type": "locality", "q": "jijel"},
            )
        self.assertEqual(response.status_code, 200)
        commune = response.data["results"][0]
        self.assertEqual(commune["parent_name"], "Jijel")
        self.assertEqual(commune["parent_admin_level"], "wilaya")
        self.assertEqual(commune["admin_level"], "commune")
        self.assertEqual(commune["matching_locality"]["parent_admin_level"], "wilaya")

        france = APIClient().get(
            reverse("geography-places"),
            {"country": "FR", "place_type": "locality", "q": "paris"},
        )
        self.assertEqual(france.data["results"][0]["parent_admin_level"], "region")

        airport = APIClient().get(
            reverse("geography-places"),
            {"place_type": "airport", "country": "DZ"},
        )
        served = airport.data["results"][0]["served_locality"]
        self.assertEqual(served["admin_level"], "commune")
        self.assertEqual(served["parent_admin_level"], "wilaya")

        wilaya = APIClient().get(
            reverse("geography-places"),
            {"country": "DZ", "place_type": "admin_region", "q": "jijel"},
        )
        top = wilaya.data["results"][0]
        self.assertIsNone(top["parent_name"])
        self.assertIsNone(top["parent_admin_level"])

    def test_parent_tier_is_blank_when_the_source_records_none(self):
        parent = Place.objects.create(
            country_id="DZ",
            place_type=Place.PlaceType.ADMIN_REGION,
            source="test-region",
            source_id="DZ-untiered",
            source_version="test-2026",
            name="Untiered",
        )
        Place.objects.create(
            country_id="DZ",
            place_type=Place.PlaceType.LOCALITY,
            source="test-commune",
            source_id="DZ-untiered-child",
            source_version="test-2026",
            name="Untieredville",
            parent=parent,
        )

        response = APIClient().get(
            reverse("geography-places"),
            {"country": "DZ", "q": "untieredville"},
        )
        row = response.data["results"][0]
        self.assertEqual(row["parent_name"], "Untiered")
        self.assertEqual(row["parent_admin_level"], "")

    def test_arabic_alternate_name_and_airport_context_are_searchable(self):
        response = APIClient().get(reverse("geography-places"), {"q": "جيجل"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            any(row["source_id"] == "DZ-1801" for row in response.data["results"])
        )
        airport = APIClient().get(
            reverse("geography-places"), {"place_type": "airport", "country": "DZ"}
        )
        self.assertEqual(airport.status_code, 200)
        self.assertEqual(airport.data["results"][0]["served_locality"]["name"], "Jijel")

    def test_combined_mobile_search_keeps_localities_and_only_mapped_airports(self):
        response = APIClient().get(
            reverse("geography-places"),
            {"place_type": "locality,airport", "country": "DZ", "q": "jijel"},
        )

        self.assertEqual(response.status_code, 200)
        result_types = {row["place_type"] for row in response.data["results"]}
        self.assertEqual(result_types, {"locality", "airport"})
        self.assertTrue(
            all(
                row["available_for_matching"]
                for row in response.data["results"]
                if row["place_type"] == "airport"
            )
        )

    def test_served_locality_ignores_primary_physical_mapping(self):
        airport = Place.objects.get(source="test-airport", source_id="airport-1")
        physical = Place.objects.create(
            country_id="DZ",
            place_type=Place.PlaceType.LOCALITY,
            source="test-commune",
            source_id="DZ-physical",
            source_version="test-2026",
            name="Taher",
        )
        AirportLocalityMapping.objects.create(
            airport=airport,
            locality=physical,
            relationship_type=AirportLocalityMapping.RelationshipType.PHYSICAL,
            is_primary=True,
            source="test-map",
            source_id="airport-1-physical",
            source_version="test-2026",
        )

        response = APIClient().get(
            reverse("geography-places"),
            {"place_type": "airport", "country": "DZ"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["results"][0]["served_locality"]["name"], "Jijel"
        )

    def test_inactive_filter_is_bounded_and_validated(self):
        Place.objects.filter(source="test-commune", source_id="DZ-1801").update(
            active=False
        )
        default = APIClient().get(
            reverse("geography-places"), {"country": "DZ", "q": "jijel"}
        )
        self.assertEqual(default.data["count"], 2)
        inactive = APIClient().get(
            reverse("geography-places"),
            {"country": "DZ", "q": "jijel", "active": "false"},
        )
        self.assertEqual(inactive.data["count"], 1)
        invalid = APIClient().get(reverse("geography-places"), {"place_type": "city"})
        self.assertEqual(invalid.status_code, 400)

    def test_search_rejects_empty_normalization_and_unbounded_parent_ids(self):
        punctuation = APIClient().get(reverse("geography-places"), {"q": "---’"})
        self.assertEqual(punctuation.status_code, 400)

        for parent in ("²", "9" * 100):
            with self.subTest(parent=parent):
                response = APIClient().get(
                    reverse("geography-places"), {"parent": parent}
                )
                self.assertEqual(response.status_code, 400)

    def test_airport_with_inactive_matching_locality_is_not_selectable(self):
        Place.objects.filter(source="test-commune", source_id="DZ-1801").update(
            active=False
        )

        response = APIClient().get(
            reverse("geography-places"),
            {"place_type": "airport", "country": "DZ"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 0)
        self.assertEqual(response.data["results"], [])
