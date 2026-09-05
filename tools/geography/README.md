# ShipTrip authoritative geography catalogue

Phases 8B–8C keep bulk geography out of Django migrations while making the
catalogue authoritative for active V1 creation and matching. The controlled
pipeline is:

1. Install the isolated source-tool dependency with `python -m pip install -r tools/geography/requirements.txt`.
2. Run `python tools/geography/normalize_sources.py --download --source-dir <dir> --output <manifest.json>` from a reviewed environment. `--download` can only fetch the fixed official/maintained hosts in the script; operators may instead place the downloaded files in `<dir>` and omit it.
3. Review the generated manifest and any airport locality mapping additions.
4. Run `python backend/monolith/manage.py import_geography --manifest <manifest.json> --deactivate-missing` with the deployment's Django settings.

The importer is transactional and idempotent. `(source, source_id)` is the
natural identity; renames update the existing row and preserve its internal
primary key. Records absent from an explicitly refreshed source are retained
but can be marked inactive. The import command never guesses an airport's
served city from a display name. Airports carry their physical source context
and explicit `airport_mappings` rows provide the commercial locality used by
Phase 8C matching.

## Source policy

- Algeria uses the official **ONS Code géographique national 2021** for all
  1,541 stable W/C commune identities, then applies **JORADP Law 26-06
  (Journal Officiel 2026, F2026025)** for the current 69-wilaya hierarchy.
  The normalizer parses the official PDF lists for all ten affected mother
  wilayas and all eleven new wilayas, reconciles every ONS identity exactly
  once, and rejects any membership/count mismatch. The current JSON is used
  only for coordinates, Arabic names, daïra hints and explicitly reviewed
  spelling reconciliation; its five-digit `post_code` is retained as
  supplemental metadata and is not represented as an official CGN code.
- France uses the official **INSEE COG 2026** CSV bundle, importing every
  `TYPECOM=COM` commune plus region and department parents and preserving the
  official commune code.
- Spain uses the official **INE municipality register as of 1 January 2026**,
  importing all 8,132 municipalities, 52 provinces and 19 autonomous-community
  parents. The five digit province+municipality code and check digit are
  preserved.
- Germany uses the official **Destatis GV-ISys extract for 30 June 2026**,
  importing 10,749 politically independent/statistically equivalent
  municipalities, 16 states and 401 district parents. Uninhabited
  municipality-free `Textkennzeichen=66` rows are excluded; the two inhabited
  `Textkennzeichen=65` rows are retained. The eight-digit AGS is preserved.
- Airports use the maintained **OurAirports** CSV. The conservative V1 policy
  includes only large/medium/small airport records explicitly marked
  `scheduled_service=yes`. Closed fields, heliports, seaplane/balloon/glider
  sites, military/private records without scheduled service and unsupported
  types are excluded. The observed extract yields DZ 31, FR 49, ES 42 and DE
  39 (161 total).

Every airport has a reviewed canonical administrative parent: Algerian wilaya,
French region, Spanish autonomous community or German state. OurAirports
municipality text remains metadata and never becomes a locality identity.
`airport_locality_mappings_2026.json` contains seven separately inspectable
high-impact served-city policies (ALG, CDG, ORY, BCN, MAD, FRA and MUC) and
four distinct physical-locality relationships. Of the other 154 selectable
airports, 81 use the maintained stable-ID source-context override table for
commercial semantics or ambiguous municipality nomenclature, and 73 resolve
uniquely from source municipality context. An ambiguous or missing resolution
is a hard normalizer error, not an airport display-name guess. The output gate
also requires the exact country counts (DZ 31, FR 49, ES 42, DE 39) and one
primary `served` mapping for every airport.

The verified manifest contains 56,134 places, 3,834 source-backed or explicitly
reviewed alternate names and 165 airport/locality relationships: 161 primary
served mappings plus
four physical-context mappings. Thus all 161 active/selectable airports have a
deterministic matching locality. CDG and ORY resolve to Paris; ALG resolves to
the canonical Alger Centre commune under the reviewed commercial Algiers
policy. The checked mapping is imported as data and can be revised without
changing airport identity.

Reviewed mapping rows may define `served_locality_aliases` when the mapping's
source evidence establishes a commercial-city name that the locality source
does not carry. The normalizer projects these as ordinary alternate-name rows
with mapping provenance. ALG currently contributes the OurAirports/reviewed
English `Algiers` alias to Alger Centre. This field is opt-in: airport display
names and raw municipality hints are never parsed into aliases automatically.

The runtime rule is intentionally small: a locality matches itself and an
airport matches its single active primary served locality. Preferred exact
`Location` coordinates are operational details only and never participate in
that identity comparison. Nearby/radius compatibility is not implemented.

Phase 8F-F2 reuses those imported `served` rows for search recommendations. A
city query returns its direct canonical locality first and may add up to three
airports whose active mapping serves it. If a matched locality has no served
airport row but does have reviewed coordinates, the API may recommend an active
selectable airport within 100 km; it computes Haversine distance against the
bounded airport subset for the selected country. This fallback is not written
back to the catalogue and never participates in matching. F2 adds only the
reviewed ALG `Algiers` locality alias described above; airport identities,
associations and matching mappings are unchanged.

## What ships in the release

Downloads are still not committed as migrations, and the normalizer's raw
source files are still not committed at all. From Phase 8E the *reviewed
output* is: `backend/monolith/apps/locations/data/geography_manifest_2026.json.gz`
is the manifest above, gzipped deterministically (28.2 MB of JSON, 1.05 MB
packed), and it ships inside the container image.

That reverses the earlier "keep it entirely out of the release" position, for
one reason: the Phase 8C write contract refuses a DeliveryRequest or a Journey
that does not reference a canonical `Place`, so a deployment with code and no
catalogue is a deployment on which nobody can create anything. Keeping the data
outside the artefact made the catalogue a separate manual step that the release
identifier could not vouch for. Now one commit carries the code and the exact
reviewed data, and `apps/locations/tests/test_geography_release_data.py` pins
the manifest's content digest so an unreviewed upstream refresh fails the suite
instead of reaching a phone.

The deployment applies it once:

```text
python manage.py import_geography --skip-if-current
```

With no `--manifest`, the command reads the bundled artefact. `--skip-if-current`
compares the manifest's uncompressed-content SHA-256 against
`locations_geography_catalogue_import` and returns after one indexed read when
they match — which is every boot after the first, so the import is never
destructive or expensive on a restart. `backend/railway/start.py` runs exactly
that, after the gateway is listening, so a slow first import cannot fail a
health check. The import is one transaction: until it commits, the catalogue
reads as its previous state, never as a half-built one. Rehearsed on
PostgreSQL 16 at 145.7 s and a 280 MB peak for the first import, 2.9 s for the
skip.

To publish a revised catalogue: regenerate the manifest, gzip it with
`mtime=0` so the artefact is reproducible, replace the bundled file, update
`REVIEWED_MANIFEST_SHA256` in the release-data test in the same commit, and
deploy. The new digest is a new marker row, so the next boot applies it.

Store reviewed manifests/checksums
in the operator's release artefact store when licensing or reproducibility
requires retention. Source/version metadata is persisted on every catalogue
row and alternate name; the generated manifest records a SHA-256 for every
input file, and volatile supplements include their digest in `source_version`.
