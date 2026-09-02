from __future__ import annotations

import csv
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


if __name__ == "__main__":
    unittest.main()
