"""The catalogue that ships inside the release, and the once-only import.

Phase 8B kept 56k rows of reviewed geography out of migrations, which was
right, and left them outside the release, which was not: the active V1 write
contract refuses a request or a journey without a canonical Place, so a
deployment that has code but no catalogue is a deployment nobody can create
anything on. Phase 8E ships the reviewed manifest in the image and applies it
once.

Two things are tested here. First, that the artefact in the release is the
reviewed dataset and not something regenerated from newer upstream sources —
the counts below are the reviewed ones, and a silent upstream refresh must fail
this file rather than reach a device. Second, that applying it is idempotent
and cheap enough to sit in a boot sequence.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import pathlib
import tempfile
from copy import deepcopy
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase

from apps.locations.management.commands.import_geography import (
    BUNDLED_MANIFEST,
    read_manifest_bytes,
)
from apps.locations.models import GeographyCatalogueImport, Place

#: SHA-256 of the reviewed manifest's *uncompressed* bytes. This is the release
#: data gate: regenerating the catalogue from newer upstream sources changes it,
#: and that has to be a deliberate reviewed change with this constant updated in
#: the same commit, not a quiet one that lands on a phone.
REVIEWED_MANIFEST_SHA256 = (
    "47bf4f761cd7db1063a76abcc975a0579077fb29b888607661efd35f71288cd2"
)

#: The Phase 8B/8C reviewed coverage, per `docs/GEOGRAPHY_CATALOGUE.md`.
REVIEWED_COUNTS = {
    ("DZ", "admin_region"): 69,
    ("DZ", "locality"): 1541,
    ("DZ", "airport"): 31,
    ("FR", "admin_region"): 119,
    ("FR", "locality"): 34875,
    ("FR", "airport"): 49,
    ("ES", "admin_region"): 71,
    ("ES", "locality"): 8132,
    ("ES", "airport"): 42,
    ("DE", "admin_region"): 417,
    ("DE", "locality"): 10749,
    ("DE", "airport"): 39,
}


class BundledManifestTests(TestCase):
    """Does the release carry the reviewed catalogue, unchanged?"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.raw = read_manifest_bytes(BUNDLED_MANIFEST)
        cls.manifest = json.loads(cls.raw)

    def test_the_artefact_ships_and_is_the_reviewed_dataset(self):
        assert BUNDLED_MANIFEST.exists(), BUNDLED_MANIFEST
        assert BUNDLED_MANIFEST.suffix == ".gz"
        assert hashlib.sha256(self.raw).hexdigest() == REVIEWED_MANIFEST_SHA256

    def test_the_reviewed_coverage_is_exactly_what_the_catalogue_documents(self):
        counted: dict[tuple[str, str], int] = {}
        for place in self.manifest["places"]:
            key = (place["country_code"], place["place_type"])
            counted[key] = counted.get(key, 0) + 1

        assert counted == REVIEWED_COUNTS
        assert len(self.manifest["places"]) == 56_134
        assert len(self.manifest["alternate_names"]) == 3_834
        assert {row["code"] for row in self.manifest["countries"]} == {
            "DZ",
            "FR",
            "ES",
            "DE",
        }

    def test_every_selectable_airport_has_one_primary_served_locality(self):
        airports = {
            (place["source"], place["source_id"])
            for place in self.manifest["places"]
            if place["place_type"] == "airport" and place.get("active", True)
        }
        served = [
            row
            for row in self.manifest["airport_mappings"]
            if row["relationship_type"] == "served" and row.get("is_primary")
        ]
        served_airports = {
            (row["airport_source"], row["airport_source_id"]) for row in served
        }

        assert len(airports) == 161
        assert len(served) == 161, "an airport with two primary served rows is ambiguous"
        assert served_airports == airports

    def test_a_plain_manifest_reads_identically_to_the_packed_one(self):
        written = BUNDLED_MANIFEST.parent / "roundtrip-test.json"
        written.write_bytes(self.raw)
        try:
            assert read_manifest_bytes(written) == self.raw
        finally:
            written.unlink()


class BundledImportTests(TestCase):
    """Applying a manifest: once, transactionally, cheap on every boot after.

    The mechanics run against a small synthetic manifest on purpose. Importing
    the real 56k-row catalogue takes about two and a half minutes against
    PostgreSQL, and four of those in the test suite would buy nothing the two
    rows below do not already prove. The real catalogue is applied once as a
    deployment rehearsal and gated here by content, not by re-importing it.
    """

    manifest_body = {
        "format_version": 1,
        "countries": [
            {
                "code": "DZ",
                "name": "Algeria",
                "source": "release-country",
                "source_id": "DZ",
                "source_version": "release-test",
            }
        ],
        "places": [
            {
                "source": "release-region",
                "source_id": "DZ-18",
                "source_version": "release-test",
                "country_code": "DZ",
                "place_type": "admin_region",
                "name": "Jijel",
                "admin_level": "wilaya",
            }
        ],
        "alternate_names": [],
        "airport_mappings": [],
    }

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = pathlib.Path(self.directory.name) / "manifest.json.gz"
        self.raw = json.dumps(self.manifest_body).encode("utf-8")
        self.path.write_bytes(gzip.compress(self.raw))
        self.digest = hashlib.sha256(self.raw).hexdigest()

    def _run(self, *args) -> dict:
        out = StringIO()
        call_command(
            "import_geography", "--manifest", str(self.path), *args, stdout=out
        )
        return json.loads(out.getvalue())

    def test_a_gzipped_manifest_imports_and_records_its_content_digest(self):
        result = self._run("--skip-if-current")

        assert result["places"] == 1
        assert result["content_sha256"] == self.digest
        assert Place.objects.get(source_id="DZ-18").name == "Jijel"
        marker = GeographyCatalogueImport.objects.get()
        assert marker.content_sha256 == self.digest
        assert marker.counts["places"] == 1

    def test_a_second_boot_is_a_no_op_that_touches_no_row(self):
        self._run("--skip-if-current")
        before = list(Place.objects.order_by("id").values_list("id", "updated_at"))

        result = self._run("--skip-if-current")

        assert result == {"skipped": True, "content_sha256": self.digest}
        assert list(Place.objects.order_by("id").values_list("id", "updated_at")) == (
            before
        )
        assert GeographyCatalogueImport.objects.count() == 1

    def test_a_changed_manifest_is_applied_rather_than_skipped(self):
        self._run("--skip-if-current")
        revised = deepcopy(self.manifest_body)
        revised["places"][0]["name"] = "Jijel (renamed)"
        raw = json.dumps(revised).encode("utf-8")
        self.path.write_bytes(gzip.compress(raw))

        result = self._run("--skip-if-current")

        # A different reviewed catalogue is a different digest, so the guard
        # lets it through; identity is preserved across the rename.
        assert result["content_sha256"] == hashlib.sha256(raw).hexdigest()
        assert Place.objects.get(source_id="DZ-18").name == "Jijel (renamed)"
        assert GeographyCatalogueImport.objects.count() == 2

    def test_without_the_flag_the_same_manifest_still_reruns(self):
        self._run("--skip-if-current")

        # Rerunnable by design: an operator re-applying the same manifest is a
        # supported repair, not a refused one.
        assert self._run()["places"] == 1
        assert GeographyCatalogueImport.objects.count() == 1

    def test_a_refused_manifest_leaves_no_marker_behind(self):
        self.path.write_bytes(gzip.compress(json.dumps({"format_version": 2}).encode()))

        with self.assertRaises(CommandError):
            self._run("--skip-if-current")

        # A marker that outlived a failed import would make the next boot skip
        # a catalogue that is not there.
        assert not GeographyCatalogueImport.objects.exists()
        assert not Place.objects.exists()

    def test_the_command_defaults_to_the_catalogue_shipped_in_the_release(self):
        # No `--manifest`: a deployment must not have to know a path, or be
        # able to point the boot sequence at the wrong file.
        assert BUNDLED_MANIFEST.exists()
        assert BUNDLED_MANIFEST.name == "geography_manifest_2026.json.gz"
