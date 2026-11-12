from __future__ import annotations

import csv
import json
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).with_name("normalize_sources.py")
SPEC = importlib.util.spec_from_file_location("normalize_sources", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
normalizer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(normalizer)


class _Page:
    def __init__(self, text: str):
        self.text = text

    def extract_text(self) -> str:
        return self.text


class _Reader:
    def __init__(self, pages: list[_Page]):
        self.pages = pages


class OfficialPdfParserTests(unittest.TestCase):
    def test_all_joradp_amendment_articles_are_extracted(self):
        blocks = []
        for article, wilaya_code in normalizer.JORADP_ARTICLE_WILAYAS.items():
            printed_article = "52. Bis 10" if article == "52 bis 10" else article
            blocks.append(
                f"« Art. {printed_article}. — Les une (1) communes suivantes "
                f"constituent une wilaya :\n1. Commune {wilaya_code}. »."
            )
        reader = _Reader([_Page("\n".join(blocks))])

        with mock.patch.object(normalizer, "_pdf_reader", return_value=reader):
            assignments = normalizer._parse_joradp_assignments(Path("law.pdf"))

        self.assertEqual(
            set(assignments), set(normalizer.JORADP_ARTICLE_WILAYAS.values())
        )
        self.assertEqual(assignments[59], ["Commune 59"])
        self.assertEqual(assignments[69], ["Commune 69"])

    def test_ons_parser_requires_and_preserves_all_1541_unique_codes(self):
        rows = []
        for index in range(1541):
            wilaya = index // 99 + 1
            commune = index % 99 + 1
            rows.append(f"COMMUNE {index:04d} {wilaya:02d} {commune:02d} Arabic-name")
        reader = _Reader([_Page("")] * 3 + [_Page("\n".join(rows))])

        with mock.patch.object(normalizer, "_pdf_reader", return_value=reader):
            communes = normalizer._parse_ons_communes(Path("ons.pdf"))

        self.assertEqual(len(communes), 1541)
        self.assertEqual(communes["0101"]["name"], "COMMUNE 0000")


class AirportPolicyTests(unittest.TestCase):
    def test_only_scheduled_non_closed_airports_are_selected(self):
        fieldnames = [
            "id",
            "ident",
            "type",
            "name",
            "latitude_deg",
            "longitude_deg",
            "iso_country",
            "iso_region",
            "municipality",
            "scheduled_service",
            "gps_code",
            "iata_code",
            "icao_code",
        ]
        rows = [
            {
                "id": "1",
                "type": "medium_airport",
                "name": "Scheduled",
                "latitude_deg": "1",
                "longitude_deg": "2",
                "iso_country": "FR",
                "iso_region": "FR-IDF",
                "scheduled_service": "yes",
            },
            {
                "id": "2",
                "type": "large_airport",
                "name": "Unscheduled",
                "latitude_deg": "1",
                "longitude_deg": "2",
                "iso_country": "FR",
                "iso_region": "FR-IDF",
                "scheduled_service": "no",
            },
            {
                "id": "3",
                "type": "closed",
                "name": "Closed",
                "latitude_deg": "1",
                "longitude_deg": "2",
                "iso_country": "FR",
                "iso_region": "FR-IDF",
                "scheduled_service": "yes",
            },
        ]
        manifest = {"places": []}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "airports.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            normalizer.parse_airports(path, manifest)

        self.assertEqual([place["source_id"] for place in manifest["places"]], ["1"])

    def test_reviewed_served_locality_alias_is_projected_without_name_parsing(self):
        manifest = {
            "places": [
                {
                    "source": "commune",
                    "source_id": "1601",
                    "place_type": "locality",
                    "name": "Alger Centre",
                }
            ],
            "alternate_names": [],
            "airport_mappings": [
                {
                    "source": "reviewed-map",
                    "source_id": "alg-served",
                    "source_version": "2026",
                    "locality_source": "commune",
                    "locality_source_id": "1601",
                    "relationship_type": "served",
                    "served_locality_aliases": [
                        {
                            "name": "Algiers",
                            "language": "en",
                            "review_basis": "reviewed test",
                        }
                    ],
                }
            ],
        }

        normalizer.add_reviewed_served_locality_aliases(manifest)

        self.assertEqual(manifest["alternate_names"][0]["name"], "Algiers")
        self.assertEqual(manifest["alternate_names"][0]["place_source_id"], "1601")


class CoordinateSupplementTests(unittest.TestCase):
    def _manifest(self):
        return {
            "sources": [],
            "places": [
                {
                    "source": "insee-cog-commune",
                    "source_id": "75056",
                    "source_version": "INSEE-COG-2026",
                    "metadata": {"official_code": "75056"},
                },
                {
                    "source": "ine-municipality",
                    "source_id": "28079",
                    "source_version": "INE-REL-2026-01-01",
                    "metadata": {"official_code": "28079"},
                },
            ],
        }

    def _write(self, directory: Path, france: list, features: list) -> None:
        (directory / normalizer.COORDINATE_FILES["france_coordinates"]).write_text(
            json.dumps(france), encoding="utf-8"
        )
        (directory / normalizer.COORDINATE_FILES["spain_coordinates"]).write_text(
            json.dumps({"type": "FeatureCollection", "features": features}),
            encoding="utf-8",
        )

    def _square(self, west, south, size):
        return [
            [west, south],
            [west + size, south],
            [west + size, south + size],
            [west, south + size],
            [west, south],
        ]

    def test_points_join_by_official_code_and_record_provenance(self):
        manifest = self._manifest()
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            self._write(
                directory,
                [
                    {
                        "code": "75056",
                        "centre": {"type": "Point", "coordinates": [2.34, 48.86]},
                        "mairie": {"type": "Point", "coordinates": [2.3525, 48.8564]},
                    },
                    # Published by the API but not an identity: ignored.
                    {
                        "code": "97501",
                        "centre": {"type": "Point", "coordinates": [-56.2, 46.8]},
                    },
                ],
                [
                    {
                        "properties": {"GISCO_ID": "ES_28079", "CNTR_CODE": "ES"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [self._square(-3.8, 40.3, 0.2)],
                        },
                    }
                ],
            )
            normalizer.apply_coordinate_supplements(directory, manifest)

        paris, madrid = manifest["places"]
        self.assertEqual((paris["latitude"], paris["longitude"]), ("48.8564", "2.3525"))
        self.assertIn("+GEOAPI-", paris["source_version"])
        self.assertEqual(
            paris["metadata"]["coordinate_authority"], "geo.api.gouv.fr communes (mairie)"
        )
        self.assertEqual((madrid["latitude"], madrid["longitude"]), ("40.40000", "-3.70000"))
        self.assertIn("+GISCO-LAU-2024-", madrid["source_version"])
        self.assertEqual(
            [row["name"] for row in manifest["sources"]],
            ["geo.api.gouv.fr communes", "Eurostat GISCO LAU 2024"],
        )

    def test_a_city_the_coordinate_source_lacks_is_a_hard_error(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            self._write(directory, [], [])
            with self.assertRaisesRegex(ValueError, "no point for INSEE commune 75056"):
                normalizer.apply_coordinate_supplements(directory, self._manifest())

    def test_a_point_outside_the_country_is_refused(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            self._write(
                directory,
                [
                    {
                        "code": "75056",
                        # Axes swapped: lands in Somalia.
                        "mairie": {"type": "Point", "coordinates": [48.8564, 2.3525]},
                    }
                ],
                [],
            )
            with self.assertRaisesRegex(ValueError, "Implausible point"):
                normalizer.apply_coordinate_supplements(directory, self._manifest())

    def test_the_point_lies_on_the_largest_part_even_for_a_crescent(self):
        # A U shape: its centroid falls in the notch, outside the shape.
        u_shape = [
            [0, 0], [3, 0], [3, 3], [2, 3], [2, 1], [1, 1], [1, 3], [0, 3], [0, 0]
        ]
        islet = self._square(10, 10, 0.1)
        latitude, longitude = normalizer._representative_point(
            {"type": "MultiPolygon", "coordinates": [[islet], [u_shape]]}
        )
        self.assertTrue(normalizer._inside(longitude, latitude, [u_shape]))
        self.assertLess(longitude, 3)

    def test_plain_decimal_text_never_uses_exponents(self):
        self.assertEqual(normalizer._decimal_text(0.00001), "0.00001")
        self.assertEqual(normalizer._decimal_text(-1.5), "-1.5")
        with self.assertRaises(ValueError):
            normalizer._decimal_text("2.3")


if __name__ == "__main__":
    unittest.main()
